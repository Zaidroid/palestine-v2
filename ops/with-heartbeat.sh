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

hb() {
  "$ROOT/.venv/bin/python" -m ops.heartbeat "$name" \
      --interval "$interval" --grace "$grace" "$@" || true
}

# THE ATTEMPT IS STAMPED BEFORE THE JOB RUNS. A job killed by TimeoutStartSec
# never returns here: systemd SIGTERMs the whole cgroup, this shell included,
# so a heartbeat written only AFTER "$@" was never written at all, last_attempt
# went stale with last_ok, and the view called a job that fired every five
# minutes and was killed every time `not_running` — "the scheduler stopped" —
# with no reason attached (the classifier re-read, 2026-09-24 18:04). With the
# attempt on record first, the same job reads `failing`, which is the truth.
hb --attempt

# And when the kill IS a SIGTERM, say so. With a trap set, bash waits for the
# child (which systemd signalled too) and then runs this, inside the stop
# timeout, so the row carries "killed by SIGTERM" instead of nothing. SIGKILL
# cannot be trapped; the attempt stamp above is what covers that one.
killed=""
trap 'killed=TERM' TERM
trap 'killed=INT' INT

"$@"
rc=$?

# OK_EXIT_CODES lets a job say "this exit code means I worked, and found
# something" — the watchdog exits 3 when it DETECTS a fault, which is a
# successful run with a bad result. It must be EXPORTED by the calling script
# before this wrapper runs: `-- env OK_EXIT_CODES=1 cmd` sets it for the child
# only, this shell never sees it, and every "found something" night was
# recorded as a failed job (mcp-audit, until 2026-09-25). And the code should
# not be 1, which is also what an uncaught Python exception exits with — a
# crash is then recorded as a working run (the watchdog, until the same day;
# mcp-audit still, until ops/mcp_accuracy_audit.py reports criticals as 3).
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
  hb
elif [ -n "$killed" ]; then
  hb --fail "killed by SIG$killed before it finished (TimeoutStartSec, or stopped by hand) — exited $rc"
else
  hb --fail "exited $rc"
fi

exit "$rc"
