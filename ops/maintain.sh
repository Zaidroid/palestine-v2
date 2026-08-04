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

exec ./ops/with-heartbeat.sh maintain 604800 172800 -- \
  claude -p "$(cat ops/maintenance-prompt.md)" \
    --model claude-opus-5 \
    --dangerously-skip-permissions \
    > "$LOG" 2>&1
