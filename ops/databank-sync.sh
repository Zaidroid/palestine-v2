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

# Connectivity, cut from v1 2026-08-08. Same non-fatal posture, and the same
# reason: both fetchers are atomic and floored. OONI is the one that MATTERS
# to run — v1's copy of it died on 2026-06-09 and nobody noticed for sixty
# days, so a silent failure here is the exact thing being fixed.
.venv/bin/python -m ops.fetch_ooni || echo "ooni fetch failed — loading yesterday's file" >&2
.venv/bin/python -m ops.fetch_ioda || echo "ioda fetch failed — loading yesterday's file" >&2

./ops/with-heartbeat.sh databank 86400 21600 -- \
  .venv/bin/python -m ingest.databank --all
rc=$?

# F-12: the Gaza series is served from T4P (conflict_gaza.yaml); organ C reads
# the same Ministry bulletins directly. A served day the two disagree on
# alarms once and stays open until they agree. Non-fatal: the check reports,
# it never changes a figure, and a failed check must not fail the ingest.
.venv/bin/python -m ops.gaza_crosscheck || echo "gaza crosscheck failed — tonight's served days are unchecked" >&2

# Archive tonight's loader inputs as as_of evidence, in v1's snapshot shape.
# Non-fatal: a failed snapshot must never fail the night's ingest — but the
# gap radar watches the vault's age, so it cannot go quiet unnoticed. Without
# this the as_of proof would freeze at v1's last 38 days forever.
.venv/bin/python -m ops.snapshot_inputs || echo "snapshot-inputs failed — as_of evidence did not grow tonight" >&2

# Hot-copy any NEW days from v1's snapshot archive into the vault. Idempotent
# (sha-skips what it holds) and cheap after the first run — but never wired
# into the nightly until 2026-08-11, when the vault was found three days
# behind and a test caught it. While v1's archive still writes days, each one
# is as_of evidence; when v1 finally stops, the vault simply stops growing.
.venv/bin/python -m ops.vault_snapshots || echo "vault hot-copy failed — new v1 snapshot days not preserved tonight" >&2

# The gap radar re-measures after every sync: freshness on the data's own
# dates, holes, era coverage, fetch-layer health → data/gap-radar.json
# (served at /v2/databank/radar; Monday's maintenance run reads it).
.venv/bin/python -m ops.gap_radar || echo "gap radar failed — yesterday's radar stands" >&2

exit $rc
