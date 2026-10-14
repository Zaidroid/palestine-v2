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

# The fragments brought in on 2026-10-11 (Zaid: the databank is for personal
# use; everything we hold goes in). Insecurity Insight reads HDX's eighteen
# xlsx files directly (v1's file is its fallback); B'Tselem reads v1's frozen
# CSV through V1_ROOT. Atomic and floored like the rest.
step .venv/bin/python -m ops.fetch_insecurity_insight
step .venv/bin/python -m ops.fetch_btselem_file
# Second batch, same day: UNHCR's six population tables and FAO DIEM's four
# survey files, both straight from HDX.
step .venv/bin/python -m ops.fetch_unhcr_hdx
step .venv/bin/python -m ops.fetch_fao_diem
step .venv/bin/python -m ops.fetch_acled_file      # held under `internal`, never served (096)

# ── cut from v1's tree and from frozen files on 2026-10-12 ──────────────────
# Each writes the record shape its category's transformer already read, so a
# failed night leaves yesterday's file and the spec's frozen fallback behind it.
step .venv/bin/python -m ops.fetch_worldbank          # 125 World Bank series for PSE (re-reads when the Bank's vintage moves)
step .venv/bin/python -m ops.fetch_imf                # 18 IMF DataMapper series for WBG, with the IMF's own units
step .venv/bin/python -m ops.fetch_fts                # UN OCHA FTS flows for PSE (v1's window: 2015 to this year)
step .venv/bin/python -m ops.fetch_idmc               # IDMC events (HDX) + the carried UNHCR and camp rows
step .venv/bin/python -m ops.fetch_wfp_food           # WFP food prices (HDX)
step .venv/bin/python -m ops.fetch_hdx_schools        # the school register (HDX, OCHA oPt)
step .venv/bin/python -m ops.fetch_hdx_infrastructure # barrier, village boundaries, UNOSAT assessments
step .venv/bin/python -m ops.fetch_hdx_land           # barrier + settlement footprints (HDX; downloads only when changed)
step .venv/bin/python -m ops.fetch_goodshepherd       # demolitions per day
step .venv/bin/python -m ops.fetch_peacenow           # settler population by year
step .venv/bin/python -m ops.fetch_peacenow_settlements   # Peace Now's population per settlement (its linked spreadsheet; re-reads weekly)
step .venv/bin/python -m ops.fetch_addameer           # prisoner statistics, monthly
step .venv/bin/python -m ops.fetch_gho_health         # WHO GHO health, every dimension kept (re-reads weekly)
# UCDP's own bulk files: GED 26.1's events of 2025 (the candidate events are
# fetched and not loaded). Exit 1 with a `pending` ledger line = a newer release.
step .venv/bin/python -m ops.fetch_ucdp
# The UN2720 Mechanism's aid dashboard: trucks, pallets and tonnes offloaded,
# collected and arrived in Gaza, per day. Five GETs, no key.
step .venv/bin/python -m ops.fetch_un2720
# WHO's attacks on health care in the oPt (one GET) and ILO's quarterly labour series (four GETs),
# both keyless (2026-10-14). The World Bank's night lights are read by hand: one file a year.
step .venv/bin/python -m ops.fetch_who_ssa
step .venv/bin/python -m ops.fetch_ilostat
# Hand-entered cited figures: checked and written from db/reference/ (no network).
step .venv/bin/python -m ops.build_cited_figures

export HEARTBEAT_DETAIL="{\"fetch_failures\": $fails}"
# The unit's OnFailure alarm is resolved once, at the END, when the whole
# night passed — not by this step alone, or a dead supply line found below
# would be "resolved" and re-raised every night (HEARTBEAT_RESOLVE=0).
HEARTBEAT_RESOLVE=0 ./ops/with-heartbeat.sh databank 86400 21600 -- \
  .venv/bin/python -m ingest.databank --all
rc=$?

# EVERY INDICATOR THE NIGHT LEFT IN THE STORE GETS ITS DEFINITION. The registry
# (concept, kind of number, unit, serve warning) was loaded by hand, last on
# 2026-09-26. The datasets loaded on 2026-10-11 therefore had none: 717 of
# 2,047 served indicators, 105,908 rows, which `series`, `compare`, `correlate`
# and the indicator search answered with "no series named ...". An indicator no
# rule classifies fails the night (the spec's `registry.max_unclassified`), and
# it fails it here, in the journal and through the unit's alarm, because a row
# served without its meaning is the loader's unfinished work.
.venv/bin/python -m ops.load_registry --apply
reg=$?
if [ "$reg" -ne 0 ]; then
  echo "registry: an indicator in the store has no rule — see ops/registry-load.json and add one to its spec" >&2
  [ "$rc" -eq 0 ] && rc=$reg
fi

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
if [ "$final" -ne 0 ] && [ "$radar" -eq 5 ]; then
  # BOTH halves failed. `final=$rc` on its own kept only the loader's code, so
  # on 2026-10-04 the alarm said "exited 1" and the reader never learned that a
  # supply line was dead as well — the loader's crash silently swallowed the
  # radar's verdict, which is the fact that must never be lost. Exit 5 (a dead
  # supply line fails the night) and name both in the journal; the loader's
  # code is preserved in stderr, the heartbeat's fetch_failures, and the run
  # ledger, so nothing here is discarded either.
  echo "both halves failed: loader exit $rc AND gap radar exit 5 (dead supply line)" >&2
  final=5
elif [ "$final" -eq 0 ]; then
  final=$radar
fi
if [ "$final" -eq 0 ]; then
  # The whole night passed: close the unit's alarm if one is open.
  .venv/bin/python -m ops.alert --resolve palestine-v2-databank.service >/dev/null 2>&1 || true
fi
# The archive (2026-10-13, migration 116): bring what v1 and this store took in
# since last night, and what the two readers (ops/fetch_telegram_public.py,
# ops/fetch_wp_json.py) have written, into `document`. It decides nothing about
# the night: a failure here is printed, the exit code above stands, and nothing
# pages.
# FIFTEEN MINUTES AT MOST. The unit is killed at sixty (TimeoutStartSec), and
# while the readers are bringing whole archives a night's backlog can be
# hundreds of thousands of long texts (measured 2026-10-13: 46,967 UN documents
# took about thirteen minutes). The loader commits file by file, so a run that is
# stopped keeps what it finished and the next night goes on from there.
timeout 900 .venv/bin/python -m ingest.archive --apply > ops/archive-last-run.json 2> ops/archive-last-run.err \
  || echo "archive load stopped or failed (exit $?; 124 = its fifteen minutes ran out, the rest follows tomorrow) - see ops/archive-last-run.err; the night's result is unchanged" >&2

exit $final
