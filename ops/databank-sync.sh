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

# Failures are COUNTED and carried in the heartbeat detail, and the watchdog's
# `fetch` family reads ops/fetch-events.ndjson (three failures in a row = a
# fault): the `|| echo` lines were read by nobody (audit F275).
fails=0
step() { "$@" || { echo "$3 failed — loading yesterday's copy" >&2; fails=$((fails+1)); }; }

# v2-native pre-fetches (Phase 4): sources v2 pulls for itself, before the
# loader runs. Non-fatal by design — a failed fetch leaves yesterday's file
# and the spec's expect floor still guards the load.
step .venv/bin/python -m ops.fetch_gho_wash

# Tech4Palestine, fetched straight from the publisher (Unlicense) rather than
# through v1. Non-fatal by design: the fetcher is atomic and floored, so a bad
# night leaves yesterday's tree and the loader's expect floors intact — which
# is strictly better than a truncated overwrite.
step .venv/bin/python -m ops.fetch_t4p

# Connectivity, cut from v1 2026-08-08. Same non-fatal posture, and the same
# reason: both fetchers are atomic and floored. OONI is the one that MATTERS
# to run — v1's copy of it died on 2026-06-09 and nobody noticed for sixty
# days, so a silent failure here is the exact thing being fixed.
step .venv/bin/python -m ops.fetch_ooni
step .venv/bin/python -m ops.fetch_ioda

# The four supply lines v2 took over from v1 on 2026-09-25 (P1-B.3) — each
# had failed 31 nights inside v1's refresh with nothing paging. Same posture:
# atomic, floored, ledgered; a failed fetch keeps yesterday's file, and the
# gap radar below judges every line on its own attempts.
step .venv/bin/python -m ops.fetch_ocha          # OCHA casualties + demolitions
step .venv/bin/python -m ops.fetch_pcbs          # PCBS population + CPI
step .venv/bin/python -m ops.fetch_hamoked       # HaMoked detention, monthly
step .venv/bin/python -m ops.fetch_wpp           # UN WPP 2024, the 1950s (monthly at most)
step .venv/bin/python -m ops.fetch_unrwa_registered   # UNRWA registered refugees by field (HDX)

export HEARTBEAT_DETAIL="{\"fetch_failures\": $fails}"
# The unit's OnFailure alarm is resolved once, at the END, when the whole
# night passed — not by this step alone, or a dead supply line found below
# would be "resolved" and re-raised every night (HEARTBEAT_RESOLVE=0).
HEARTBEAT_RESOLVE=0 ./ops/with-heartbeat.sh databank 86400 21600 -- \
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
# dates, holes, era coverage, and every SUPPLY LINE judged on its own attempts
# → data/gap-radar.json (served at /v2/databank/radar; Monday's maintenance
# run reads it).
.venv/bin/python -m ops.gen_attribution --write || echo "attribution not regenerated — yesterday's file stands" >&2

# A DEAD SUPPLY LINE FAILS THE NIGHT (P1-B.3). The radar exits 5 when a line
# failed three nights running, stopped running, or feeds a stalled dataset —
# and any other non-zero exit means the lines went unjudged, which is not a
# green night either. It runs through the heartbeat wrapper under its own
# name, so ops_heartbeat and the watchdog see `supply-lines` failing, and
# this script exits non-zero, so systemd's OnFailure alarm pages
# (palestine-v2-alert@ → ops/alert.py) — the path every other job uses.
HEARTBEAT_RESOLVE=0 ./ops/with-heartbeat.sh supply-lines 86400 21600 -- \
  .venv/bin/python -m ops.gap_radar
radar=$?
if [ "$radar" -eq 5 ]; then
  echo "gap radar: DEAD SUPPLY LINE(S) — see data/gap-radar.json supply_lines.dead" >&2
elif [ "$radar" -ne 0 ]; then
  echo "gap radar failed (exit $radar) — tonight's supply lines are unjudged" >&2
fi

final=$rc
[ "$final" -eq 0 ] && final=$radar
if [ "$final" -eq 0 ]; then
  # The whole night passed: close the unit's alarm if one is open.
  .venv/bin/python -m ops.alert --resolve palestine-v2-databank.service >/dev/null 2>&1 || true
fi
exit $final
