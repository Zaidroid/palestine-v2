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

# The attempt is stamped BEFORE the job runs, and a TERM (systemd's
# TimeoutStartSec kill) is recorded as a failed attempt with its reason —
# a killed job used to read `not_running` (audit F286).
"$ROOT/.venv/bin/python" -m ops.heartbeat "$name" --attempt \
    --interval "$interval" --grace "$grace" || true
trap '"$ROOT/.venv/bin/python" -m ops.heartbeat "$name" --interval "$interval" --grace "$grace" --fail "killed (TERM — timeout?)" || true; exit 143' TERM

"$@"
rc=$?
trap - TERM

# OK_EXIT_CODES lets a job say "this exit code means I worked, and found
# something" — the watchdog exits 3 when it DETECTS a fault, which is a
# successful run with a bad result.
#
# Without it the watchdog recorded `--fail` on every run that found anything,
# so it reported ITSELF as failing, which is a fault, which it then found on
# the next run. Seven consecutive failures had accumulated before gate G3.7
# caught it. systemd already knew better via SuccessExitStatus=0 1; the
# heartbeat did not, and the two disagreeing is exactly the drift this wrapper
# exists to prevent.
ok=0
for code in 0 ${OK_EXIT_CODES:-}; do
  [ "$rc" -eq "$code" ] && ok=1
done

if [ "$ok" -eq 1 ]; then
  "$ROOT/.venv/bin/python" -m ops.heartbeat "$name" \
      --interval "$interval" --grace "$grace" --detail "${HEARTBEAT_DETAIL:-{\}}" || true
  # A failure alarm systemd raised for this unit is answered by the next
  # successful run — silently, and only if one is open (ops/alert.py).
  "$ROOT/.venv/bin/python" -m ops.alert --resolve "palestine-v2-$name.service" >/dev/null 2>&1 || true
else
  "$ROOT/.venv/bin/python" -m ops.heartbeat "$name" \
      --interval "$interval" --grace "$grace" --fail "exited $rc" || true
fi

exit "$rc"
