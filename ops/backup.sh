#!/usr/bin/env bash
# Nightly: dump the database, archive bronze and secrets, encrypt, ship
# off-host, verify the bytes landed, prune. See ops/backup.py for the why.
#
# Runs BEFORE the nightly learn/accuracy jobs (03:20, 04:10) so that if one of
# them rewrites something wrongly, the night's backup predates the damage.
set -euo pipefail
cd /home/zaid/palestine-v2
exec "$(dirname "$0")/with-heartbeat.sh" backup 86400 10800 -- .venv/bin/python -m ops.backup
