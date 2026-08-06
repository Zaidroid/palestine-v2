#!/usr/bin/env bash
# Nightly databank sync — the migration loader, on a clock (T2.3 close-out).
#
# v1's fetchers refresh /opt/stacks/palestine/.../unified at ~02:51 nightly;
# this re-runs every reviewed category at 03:40. Idempotency (044/046) means
# only genuinely new upstream records land; a category whose upstream shrank
# below its spec's expect.min_records FAILS the run and the alert fires —
# growth is verified, not assumed.
set -uo pipefail
cd /home/zaid/palestine-v2

# v2-native pre-fetches (Phase 4): sources v2 pulls for itself, before the
# loader runs. Non-fatal by design — a failed fetch leaves yesterday's file
# and the spec's expect floor still guards the load.
.venv/bin/python -m ops.fetch_gho_wash || echo "gho-wash fetch failed — loading yesterday's file" >&2

exec ./ops/with-heartbeat.sh databank 86400 21600 -- \
  .venv/bin/python -m ingest.databank --all
