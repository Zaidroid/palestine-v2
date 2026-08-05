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
exec ./ops/with-heartbeat.sh databank 86400 21600 -- \
  .venv/bin/python -m ingest.databank --all
