#!/usr/bin/env bash
# Weekly: pull the newest set back DOWN FROM THE REMOTE and restore it.
#
# Deliberately --from-remote rather than testing the local staging copy. The
# local copy shares a disk with the database; proving it restores says nothing
# about whether the off-site copy is intact, which is the only copy that matters
# in the failure this defends against.
set -euo pipefail
cd /home/zaid/palestine-v2
exec "$(dirname "$0")/with-heartbeat.sh" restore-test 604800 86400 -- .venv/bin/python -m ops.restore_test --from-remote
