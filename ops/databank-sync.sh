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

# Tech4Palestine, fetched straight from the publisher (Unlicense) rather than
# through v1. Non-fatal by design: the fetcher is atomic and floored, so a bad
# night leaves yesterday's tree and the loader's expect floors intact — which
# is strictly better than a truncated overwrite.
.venv/bin/python -m ops.fetch_t4p || echo "t4p fetch failed — loading yesterday's tree" >&2

./ops/with-heartbeat.sh databank 86400 21600 -- \
  .venv/bin/python -m ingest.databank --all
rc=$?

# Archive tonight's loader inputs as as_of evidence, in v1's snapshot shape.
# Non-fatal: a failed snapshot must never fail the night's ingest — but the
# gap radar watches the vault's age, so it cannot go quiet unnoticed. Without
# this the as_of proof would freeze at v1's last 38 days forever.
.venv/bin/python -m ops.snapshot_inputs || echo "snapshot-inputs failed — as_of evidence did not grow tonight" >&2

# The gap radar re-measures after every sync: freshness on the data's own
# dates, holes, era coverage, fetch-layer health → data/gap-radar.json
# (served at /v2/databank/radar; Monday's maintenance run reads it).
.venv/bin/python -m ops.gap_radar || echo "gap radar failed — yesterday's radar stands" >&2

exit $rc
