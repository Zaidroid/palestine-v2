#!/usr/bin/env bash
# Nightly: freeze yesterday into the databank.
#
# Runs AFTER the learn jobs so a day is rolled up against final belief, and
# after the backup so the night's set predates anything this writes.
set -uo pipefail
cd /home/zaid/palestine-v2
exec ./ops/with-heartbeat.sh rollup 86400 10800 -- .venv/bin/python -m ops.rollup --days 3
