#!/usr/bin/env bash
# Check every job and feed. See ops/watchdog.py for what it checks and why.
#
# The watchdog reports its OWN heartbeat, so the thing that watches everything
# is itself watched. Without it, the one component whose silence means "nothing
# is being checked" would be the one component nobody checks — and it would
# look exactly like a system with no faults.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

# Exit 3 means a fault was FOUND — the run worked, and it has already raised
# the alarm itself. It used to be 1, which is also what Python exits with on
# ANY uncaught exception, so the wrapper and the unit (SuccessExitStatus=0 1)
# both recorded a watchdog that crashed as one that ran fine. Now 1 is a crash
# and nothing on this path calls it success.
export OK_EXIT_CODES=3
rc=0
./ops/with-heartbeat.sh watchdog 600 900 -- .venv/bin/python -m ops.watchdog || rc=$?

# What systemd sees. "Found faults" is a successful run: the watchdog pushed
# them itself, and a unit failure on top would be a second alarm about the
# alarm. Anything else is a watchdog that did not finish, mapped to 70
# (EX_SOFTWARE) rather than passed through, so it is a FAILURE under the unit
# file installed today (SuccessExitStatus=0 1, which would swallow a 1) as
# well as under the one in ops/systemd — OnFailure fires either way, from the
# first tick after this lands, without waiting for a unit to be copied.
case "$rc" in
  0|3) exit 0 ;;
  *)   echo "watchdog did not finish (exit $rc) — nothing was checked this run" >&2
       exit 70 ;;
esac
