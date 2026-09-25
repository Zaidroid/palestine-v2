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
# wrapper that is a working job reporting a result, not a broken one. The
# findings themselves page through ops/mcp_accuracy_audit.py's own alert.
set -euo pipefail
cd /home/zaid/palestine-v2
exec "$(dirname "$0")/with-heartbeat.sh" mcp-audit 86400 10800 -- \
  env OK_EXIT_CODES=1 .venv/bin/python -m ops.mcp_accuracy_audit
