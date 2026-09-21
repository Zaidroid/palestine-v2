#!/usr/bin/env bash
# Weekly maintenance: a scheduled Claude Opus session runs the playbook in
# ops/maintenance-prompt.md — the audit/measure/fix/verify/digest loop a human
# did by hand on 2026-08-03, on a clock.
#
# THE MODEL IS PINNED to claude-opus-5 by Zaid's explicit instruction
# (2026-08-04). Do not "upgrade" this flag; changing the maintainer's model is
# his call, not a side effect of someone tidying flags. MAINTAIN_MODEL exists
# only so the seat probe's failure path can be forced with a bogus name; its
# default IS the pin, and the probe and the session read the same variable so
# the probe always tests the model the session will ask for.
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

# One maintainer at a time, however it was started. Every scheduled path
# starts palestine-v2-maintain.service, and systemd never runs a unit twice at
# once; this covers the one path that bypasses the unit — ops/maintain.sh run
# by hand from a shell, racing a timer. `flock -o` keeps the lock in flock
# itself rather than in the session's children, so nothing the agent spawns
# can hold it past the run. A refusal is not a failure: the holder is doing
# the week, and reports its own outcome.
if [ -z "${MAINTAIN_HOLDS_LOCK:-}" ]; then
    export MAINTAIN_HOLDS_LOCK=1
    flock -n -o -E 99 "$LOGDIR/.lock" "$PWD/ops/maintain.sh" "$@"
    rc=$?
    if [ "$rc" -eq 99 ]; then
        echo "maintain: not starting — another maintenance run holds $LOGDIR/.lock" >&2
        exit 0
    fi
    exit "$rc"
fi

LOG="$LOGDIR/$(date -u +%Y-%m-%dT%H-%M-%SZ).log"
MODEL="${MAINTAIN_MODEL:-claude-opus-5}"
# Absolute path: systemd's PATH has no ~/.local/bin, and the first run died
# with `claude: command not found` — caught by its own OnFailure alarm, which
# is the loop working.
CLAUDE=/home/zaid/.local/bin/claude

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

# Seat probe. The maintainer has failed three distinct ways in five weeks —
# OAuth expired (08-10), API overloaded 529 (08-24), the Claude monthly spend
# limit (09-14 and 09-21) — and each lost the whole week, because the Monday
# attempt was the only one and nothing outside it noticed. Two words ask "can
# this seat run this model right now?" before a two-hour session is started.
#
# MCP servers, tools and hooks are off because they are what the CLI loads
# first, not what the seat is: with them this took ~55s of its 60, without
# them ~3s. Auth is untouched — --bare would be quicker still, but it reads
# only ANTHROPIC_API_KEY, and the seat that caps is the OAuth one.
#
# A failed probe exits 75 (EX_TEMPFAIL in sysexits.h, "try again later") —
# distinct from the 1 above, which is a document to fix rather than a wait —
# and schedules a retry +6h, at most 3 per ISO week. A retry starts
# palestine-v2-maintain-retry.service, which runs only while the week still
# has no digest and then starts the real unit, never this script: systemd runs
# one instance of a unit at a time, so a retry cannot overlap a session. That
# unit's Tuesday timer is the net under all three.
SEAT_TEMPFAIL=75
probe=$(timeout 60 "$CLAUDE" -p "say ok" --model "$MODEL" \
          --strict-mcp-config --tools "" --settings '{"disableAllHooks":true}' 2>&1)
rc=$?
case "$probe" in
  *"spend limit"*|*"usage limit"*) why="spend-limit" ;;
  *529*|*verloaded*)               why="overloaded" ;;
  *OAuth*|*401*|*/login*)          why="auth" ;;
  *)                               why="other" ;;
esac
[ "$rc" -eq 124 ] && why="timeout"
said=$(printf '%s\n' "$probe" | grep -v '^[[:space:]]*$' | tail -n 1 | cut -c1-300)

if [ "$rc" -eq 0 ] && [ -n "$said" ] && [ "$why" != "spend-limit" ]; then
    echo "seat-probe $(date -u +%FT%TZ) model=$MODEL rc=0 ok: $said" | tee -a "$LOG"
else
    echo "seat-probe $(date -u +%FT%TZ) model=$MODEL rc=$rc FAILED ($why): $said" \
        | tee -a "$LOG" >&2

    week=$(date -u +%G-W%V)
    state="$LOGDIR/retry-state"              # "<ISO week> <retries scheduled>"
    n=0
    if [ -r "$state" ] && read -r s_week s_n < "$state" && [ "$s_week" = "$week" ]; then
        n=${s_n:-0}
    fi
    case "$n" in ''|*[!0-9]*) n=0 ;; esac   # a garbled state must not stop retries
    if [ "$n" -lt 3 ]; then
        n=$((n + 1))
        unit="palestine-v2-maintain-retry-$week-$n"
        # System scope, via sudo: the unit a retry must start is a system unit,
        # and a retry timer belongs next to the Monday one in list-timers.
        if sudo -n /usr/bin/systemd-run --unit="$unit" --on-active=6h \
               --timer-property=AccuracySec=1min --collect \
               --description="Palestine v2 — maintenance retry $n/3 after a failed seat probe ($why)" \
               /usr/bin/systemctl start --no-block palestine-v2-maintain-retry.service \
               2>&1 | tee -a "$LOG" >&2; then
            echo "$week $n" > "$state"
            echo "maintain: retry $n/3 for $week scheduled as $unit.timer, +6h" \
                | tee -a "$LOG" >&2
        else
            echo "maintain: COULD NOT schedule retry $n/3 — only the Tuesday timer is left" \
                | tee -a "$LOG" >&2
        fi
    else
        echo "maintain: all 3 retries for $week used — palestine-v2-maintain-retry.timer (Tue 05:15) is the last net" \
            | tee -a "$LOG" >&2
    fi

    # The wrapper below never runs, so record the failure here — with the
    # reason, which "exited 1" never carried.
    .venv/bin/python -m ops.heartbeat maintain \
        --fail "seat probe, model $MODEL: $why (rc $rc)" || true
    exit "$SEAT_TEMPFAIL"
fi

# `>>`, not `>`: the pre-flight and seat-probe lines above are the first thing
# to read when a run goes wrong, and truncating the log threw them away.
exec ./ops/with-heartbeat.sh maintain 604800 172800 -- \
  "$CLAUDE" -p "$(cat ops/maintenance-prompt.md)" \
    --model "$MODEL" \
    --dangerously-skip-permissions \
    >> "$LOG" 2>&1
