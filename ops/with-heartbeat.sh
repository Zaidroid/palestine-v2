#!/usr/bin/env bash
# Run a job and record whether it worked.
#
#   ops/with-heartbeat.sh <name> <interval_s> <grace_s> -- <command> [args...]
#
# Every scheduled job goes through this so that ops_heartbeat carries one row
# per job with no per-script bookkeeping to drift or be forgotten. The wrapper
# reports the cadence the job actually runs at, which is why the numbers live
# in the ExecStart line next to the timer rather than in a config file that can
# quietly disagree with it.
#
# THE WRAPPER MUST NOT CHANGE THE JOB'S OUTCOME. The heartbeat write is allowed
# to fail without affecting the exit status: monitoring that can take down the
# thing it monitors is worse than no monitoring, and a job whose database is
# unreachable is already going to be reported by the watchdog for the missing
# heartbeat. `set -e` is deliberately absent — the whole purpose here is to
# observe a non-zero exit and then re-raise it, which is exactly what -e would
# prevent.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
name="$1"; interval="$2"; grace="$3"; shift 3
[ "${1:-}" = "--" ] && shift

"$@"
rc=$?

if [ "$rc" -eq 0 ]; then
  "$ROOT/.venv/bin/python" -m ops.heartbeat "$name" \
      --interval "$interval" --grace "$grace" || true
else
  "$ROOT/.venv/bin/python" -m ops.heartbeat "$name" \
      --interval "$interval" --grace "$grace" --fail "exited $rc" || true
fi

exit "$rc"
