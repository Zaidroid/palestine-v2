#!/usr/bin/env bash
# Daily: measure whether the served surface still says exactly what the data
# says. Closes nothing, but it is the instrument that would notice if a change
# to the serving layer or a tool quietly made an answer wrong — which is how
# seven wrong answers survived to a partner's QA pass on 2026-09-23.
#
# Runs after the nightly databank sync (03:40) and the model backtest (04:10),
# so it measures the data the partner will actually see today.
#
# Exit 1 means "ran fine, found criticals": OK_EXIT_CODES tells the heartbeat
# wrapper that is a working job reporting a result, not a broken one, and the
# unit's SuccessExitStatus=0 1 tells systemd the same. The findings themselves
# page through ops/mcp_accuracy_audit.py's own alert.
#
# EXPORTED, not passed through `env` to the audit: it read
# `-- env OK_EXIT_CODES=1 .venv/bin/python ...`, which gives the variable to
# the audit process and not to the wrapper that reads it, so every night with
# a critical was recorded as a FAILED job — a second alarm from OnFailure, a
# third from the watchdog once last_ok aged past 27 h, and /health one job
# short, all for a run that had worked.
#
# KNOWN ALIAS: 1 is also Python's exit code for a crash, so a crashed audit is
# recorded as a working one. The cure is in ops/mcp_accuracy_audit.py (report
# criticals as 3, as ops/watchdog.py now does) and then OK_EXIT_CODES=3 here
# and SuccessExitStatus=0 3 in the unit.
set -euo pipefail
cd /home/zaid/palestine-v2
export OK_EXIT_CODES=1
exec "$(dirname "$0")/with-heartbeat.sh" mcp-audit 86400 10800 -- \
  .venv/bin/python -m ops.mcp_accuracy_audit
