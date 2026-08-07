#!/usr/bin/env bash
# Weekly maintenance: a scheduled Claude Opus session runs the playbook in
# ops/maintenance-prompt.md — the audit/measure/fix/verify/digest loop a human
# did by hand on 2026-08-03, on a clock.
#
# THE MODEL IS PINNED to claude-opus-5 by Zaid's explicit instruction
# (2026-08-04). Do not "upgrade" this flag; changing the maintainer's model is
# his call, not a side effect of someone tidying flags.
#
# --dangerously-skip-permissions is scoped by everything around it: the run is
# local, as user zaid, in this repo, under a playbook whose hard rules forbid
# the destructive paths, with OnFailure= alarming and the digest recording
# what happened. An unattended agent that stops to ask for permission is an
# agent that silently does nothing for a week.
set -uo pipefail
cd /home/zaid/palestine-v2

LOGDIR=ops/maintain-logs
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date -u +%Y-%m-%dT%H-%M-%SZ).log"

# Keep 12 logs — three months of Mondays.
ls -1t "$LOGDIR"/*.log 2>/dev/null | tail -n +13 | xargs -r rm --

# Pre-flight: every reviewed document must parse before the run that reads them
# starts. The specs and the scout's verdict memory are hand-edited prose; a
# stray `word:` inside a plain scalar broke verdicts.yaml on 2026-08-07 and the
# Sunday sweep died silently. Failing here costs a Monday; failing there costs
# a week of not knowing.
if ! .venv/bin/python - <<'PREFLIGHT' | tee -a "$LOG"
import sys, pathlib, yaml
bad = []
for p in sorted(pathlib.Path("db").rglob("*.yaml")):
    try:
        yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        m = getattr(e, "problem_mark", None)
        where = f" line {m.line + 1} col {m.column + 1}" if m else ""
        bad.append(f"{p}{where}: {getattr(e, 'problem', e)}")
print("\n".join(f"UNPARSEABLE {b}" for b in bad) if bad
      else "pre-flight: every db/**/*.yaml parses")
sys.exit(1 if bad else 0)
PREFLIGHT
then
    echo "maintain: REFUSING to run — a reviewed document does not parse" \
        | tee -a "$LOG" >&2
    exit 1
fi

# Absolute path: systemd's PATH has no ~/.local/bin, and the first run died
# with `claude: command not found` — caught by its own OnFailure alarm, which
# is the loop working.
exec ./ops/with-heartbeat.sh maintain 604800 172800 -- \
  /home/zaid/.local/bin/claude -p "$(cat ops/maintenance-prompt.md)" \
    --model claude-opus-5 \
    --dangerously-skip-permissions \
    > "$LOG" 2>&1
