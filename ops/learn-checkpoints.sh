#!/usr/bin/env bash
# Nightly: re-measure the things the confidence model rests on.
#
# Both of these are learned from the archive, never hand-set, and both can
# legitimately CHANGE — which is the point of re-running them:
#
#   source independence — which channels are copies of each other. Measured at
#     99.5-100% agreement across a nine-channel cluster today; a channel can
#     stop mirroring, or a new one can start, and confidence must follow.
#
#   value persistence — how long each status actually stays true. Congestion
#     currently decays to 0.41 and closure to 0.69; those are properties of the
#     situation on the ground, not constants.
#
#   reporter reliability (Loop A) — how often each reporter agrees with an
#     independent consensus, as a Beta posterior whose LOWER BOUND is what gets
#     used. This is the one that has to keep running once crowd reporting
#     exists: a submitter's standing must rise as they are repeatedly confirmed
#     and fall when they are contradicted, without anyone deciding it by hand.
#
# Kept apart from the five-minute sync on purpose: these are population-level
# fits over 90 days of history, and letting a single busy evening reshape them
# would make confidence jitter for no gain.
set -euo pipefail

# Without this, an aborted run leaves NO heartbeat at all, and a job that ran
# and failed becomes indistinguishable from a job the timer never fired —
# which are the two states ops_heartbeat exists to separate. `|| true` so the
# trap can never mask the real exit status.
trap 'rc=$?; cd /home/zaid/palestine-v2 && .venv/bin/python -m ops.heartbeat \
      learn-checkpoints --interval 86400 --grace 10800 \
      --fail "aborted with $rc" || true' ERR

cd /home/zaid/palestine-v2
.venv/bin/python -m learn.source_independence --apply --kinds checkpoint_flow
.venv/bin/python -m learn.state_persistence  --apply --kinds checkpoint_flow

# Loop A runs AFTER independence, because its consensus is taken one vote per
# independence unit — scoring reporters against a stale grouping would let a
# newly-detected copyset vote several times.
.venv/bin/python -m learn.reliability --days 30 --write

# Independence groups and trust weights both feed base_confidence, so belief
# must be recomputed after they move — otherwise the new values do not reach
# anything served until the next report happens to arrive.
.venv/bin/python -m ingest.sources.checkpoints --state-only

# Reached only on success: `set -e` above means any failing step aborts before
# here, leaving last_ok where it was. That is the intended behaviour — a nightly
# learn that dies halfway must not report the night as done.
.venv/bin/python -m ops.heartbeat learn-checkpoints \
    --interval 86400 --grace 10800 || true
