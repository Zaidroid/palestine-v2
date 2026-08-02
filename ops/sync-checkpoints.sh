#!/usr/bin/env bash
# Pull new checkpoint reports from v1, re-read them, and refresh belief.
#
# v1 keeps parsing road-condition channels every few seconds into its own
# SQLite. This picks up whatever is new, re-reads each raw line with v2's
# parser (questions excluded from belief, direction bound per clause, flow and
# presence kept apart), and recomputes state.
#
# Ordering matters and is not arbitrary:
#   1. import      new observations, attributed to their real channel
#   2. state       belief, weighted by INDEPENDENT groups agreeing
#   3. cadence     each place's own reporting rhythm, for the freshness gate
#
# The learners are deliberately NOT here. Independence grouping and persistence
# fitting are stable population-level facts measured over 90 days; recomputing
# them every five minutes would spend real work to watch a number not move, and
# would let a brief burst from one channel reshape the confidence model. They
# run nightly instead — see palestine-v2-checkpoint-learn.timer.
set -euo pipefail

cd /home/zaid/palestine-v2
exec "$(dirname "$0")/with-heartbeat.sh" sync-checkpoints 120 600 -- .venv/bin/python -m ingest.sources.checkpoints
