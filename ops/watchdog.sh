#!/usr/bin/env bash
# Check every job and feed. See ops/watchdog.py for what it checks and why.
#
# The watchdog reports its OWN heartbeat, so the thing that watches everything
# is itself watched. Without it, the one component whose silence means "nothing
# is being checked" would be the one component nobody checks — and it would
# look exactly like a system with no faults.
set -uo pipefail
cd /home/zaid/palestine-v2
exec ./ops/with-heartbeat.sh watchdog 600 900 -- .venv/bin/python -m ops.watchdog
