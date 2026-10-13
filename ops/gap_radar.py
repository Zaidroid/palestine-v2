"""The gap radar — where the record thins, measured, ranked, every night.

Born from the June-9 lesson (2026-08-06): the flagship casualty series froze
for 57 days while every mtime looked fresh, because freshness was measured on
FILES instead of on the data's own dates. This instrument measures the four
ways the databank can quietly rot, and ranks what it finds:

  1. FRESHNESS — per dataset, age of the last *information* day (not the last
     padding row, not a file mtime) against the series' OWN learned rhythm:
     the median gap between its distinct observation days. A series that
     publishes weekly is not "stale" at 6 days; one that publishes daily is.
     Dead upstreams are declared with evidence, excused, and still listed.
  2. HOLES — inside each day-grained series, the largest silent gap relative
     to its rhythm (a 30-day hole in a daily series is a wound; a 300-day gap
     in an annual series is Tuesday).
  3. ERAS — the category × era coverage grid, 1922 → today: where the record
     of Palestine simply has no shelf.
  4. FETCH HEALTH — the supply lines: v1's per-step refresh outcomes (FAIL
     streaks from refresh-events.ndjson) and v2's own fetch artifacts (raw
     tree ages) — the layer where June-9 actually broke.

  5. SUPPLY LINES (P1-B.3, 2026-09-25) — every nightly fetch judged as a line
     that feeds named datasets. A line is DEAD when its last three attempts
     failed, when it has stopped attempting at all, or when a dataset it feeds
     has stalled (data older than twice its allowance, the allowance being
     three times its learned rhythm). A v1 step is dead the same way unless it
     is declared RETIRED with its successor named. A dead line FAILS the
     nightly job: this module exits 5 and ops/databank-sync.sh runs it through
     ops/with-heartbeat.sh and exits non-zero, so systemd's OnFailure alarm
     pages (ops/alert.py) — the path every other job uses.

     Why: on 2026-09-25 four v1 fetches had failed 31 nights in a row, eight
     more 29, and the headline read "27 fresh of 32" — because the datasets
     they fed were judged on a 730-day allowance and the failures were a
     severity-3 line nobody was paged for. A dataset whose line is dead is
     now `supply_dead`, never `fresh`.

Output: data/gap-radar.json (served at /v2/databank/radar, read by the
Monday maintenance run) + a human table on stdout.

Exit: 0 every line alive · 5 at least one dead supply line (the job fails) ·
      1 the radar itself broke (the job fails too — an unjudged night is not
      a green one).

Run: .venv/bin/python -m ops.gap_radar
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from resolve.db import connect
from resolve.db import v1_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gap-radar.json"
V1_EVENTS = v1_path("public/data/refresh-events.ndjson")
V2_EVENTS = ROOT / "ops" / "fetch-events.ndjson"   # ops/fetchlib.py's ledger
V1_T4P_RAW = v1_path("public/data/tech4palestine")

# ── declarations: the radar's reviewable knowledge, never guessed ────────────

# Upstreams that died, with evidence. Excused from STALLED, still reported.
DEAD_UPSTREAM = {
    "v1_aid_access_unrwa_aid_trucks":
        "UNRWA ceased publishing aid-truck data 2025-01-16 (operational ban).",
    "v1_infrastructure_tech4palestine":
        "T4P's infrastructure-damaged series ended 2025-10-05 — verified "
        "against their live API 2026-08-06; UNOSAT and the unified infra "
        "sources carry the category forward.",
    "unrwa_registered_hdx":
        "UNRWA has published no quarter after 2025 Q4. HDX's dataset carries "
        "exactly one resource, '..._2025 Q4.xlsx', created and last modified "
        "2026-07-10 and untouched since (package_show, verified 2026-10-04) "
        "-- so the register is not behind, it is the whole of what exists. "
        "The fetcher is healthy and re-read it tonight; there is simply no "
        "newer quarter to load. This is DEAD_UPSTREAM, not a cadence problem: "
        "do NOT widen ALLOWANCE_OVERRIDE_DAYS to quiet it, that would let the "
        "databank go green while the series never updates again. Re-check HDX "
        "before clearing -- if a 2026 quarter appears, the nightly fetch loads "
        "it and this entry should go.",
}

# Copies we hold of a source that GOES ON publishing, where the next copy is
# not a fetch but a permission. Not dead upstream (the publisher is alive),
# not a closed corpus (the series continues there), and not a supply line that
# can stall, because nothing of ours fetches it. Excused from STALLED and
# named every night with what it waits for, so the wait stays visible and the
# job is not failed by a dataset no night's work could refresh.
AWAITING_PERMISSION = {
    "btselem_fatalities":
        "A frozen copy: B'Tselem's fatalities file as v1 held it, ending "
        "2023-09-24 (loaded 2026-10-11). B'Tselem's own database continues and "
        "answers automated reads with HTTP 429 (maintenance, 2026-10-12); bulk "
        "use needs their written consent, and the letter "
        "(db/scout/letters/btselem_bulk.md, source_permission btselem_bulk) "
        "has not been sent. Clear this entry the day a newer copy is granted "
        "and a fetch exists: from then on it is a supply line like any other.",
}

# Closed corpora: history, not feeds. Age is meaningless; only HOLES and the
# era grid speak for them.
CLOSED_CORPUS = {
    "v1_historical_palopenmaps",
    # Hand-entered statements about dated events (2026-10-12): a figure for
    # 1948 does not go stale, and the file grows only when a person adds one.
    "cited_figures",
    # A Wikipedia table scraped once in June 2026 (migration 110): UNRWA's camp
    # counts of about 2018 to 2020. Nothing can refresh it, and its age is not
    # the question; its vintage is on the dataset and in its warning.
    "v1_refugees_unrwa",
    # Frozen 2026-10-12 (db/mappings/culture.yaml): v1's nightly Wikidata
    # query result, carried in data/frozen/ and no longer fetched. As a
    # register its age is "days since the last ingest" against a learned
    # 12-day allowance, so without this entry the frozen corpus reads STALLED
    # 24 days after its last new row (2026-10-10) and fails the night as a
    # dead data line. The other static registers judged the same way
    # (v1_land_ocha, v1_land_peace_now, v1_education_hdx,
    # v1_infrastructure_hdx, v1_refugees_unrwa: last ingest 2026-08-05..09,
    # allowance 90) reach STALLED in the first week of February 2027 and
    # need the same answer; that is not decided here.
    "v1_culture_heritage_composite",
}

# Datasets whose series another dataset CONTINUES. Their age stops mattering
# on the day the successor takes over; the successor is judged instead, and
# if the successor stalls the radar reports that. Measured, not asserted:
# the successor's first day must follow the predecessor's last, checked below.
CONTINUED_BY = {
    # v1 stopped refreshing the Gaza series at 2026-08-08; conflict_gaza.yaml
    # reads the same publisher (T4P) from 2026-08-09 (F-12, 2026-09-23).
    "v1_conflict_tech4palestine": "t4p_gaza_daily",
}

# Rhythm overrides where the learned median would mislead (annual releases
# that arrive in one batch, registers whose dates are disclaimed).
ALLOWANCE_OVERRIDE_DAYS = {
    # Annual/year-labeled series: age is measured from the period LABEL
    # (2025 data is stamped 2025-01-01), so a healthy annual series reads
    # ~550d old the day before its next release. 730 = one missed release.
    "v1_conflict_ucdp": 730,
    "v1_health_who": 730,
    "v1_pcbs_pcbs": 730,
    "v1_settlements_peace_now": 730,   # the key was misspelt until 2026-10-12, so it never applied
    # Peace Now's per-settlement sheet (2026-10-13). Its newest label is old BY
    # DESIGN: a year's figure is stored at the start of its year and reaches
    # the sheet one to two years after the year ends. On 2026-10-13 the newest
    # column is "Population May 2024" (895 days old) and the newest year column
    # is 2023 (1,381 days old), in a file Peace Now named 07.2026. The same
    # publisher's chart was 1,309 days old the day before it gained 2024
    # (db/mappings/settlements.yaml). The learned rhythm would give 3 x 365 =
    # 1,095 and call a living sheet late. 1,460 = four years: late after one
    # whole missed year, stalled (and the night fails) at 2,920.
    "peacenow_settlement_population": 1460,
    "v1_casualties_ocha_casualties": 730,
    "who_gho_wash": 1200,             # JMP labels are biennial: 2024-label
                                      #   data ages ~1100d before the next
    "v1_martyrs_snapshot_2023_tech4palestine": 90,  # roster update cadence
    # FAO DIEM is survey ROUNDS, about one a year: the rows hold May 2024,
    # July 2025 and June-July 2026 and nothing between (measured 2026-10-12).
    # The learned 2.5-day rhythm is the interview dates inside one round, and
    # it gave a 7-day allowance that failed the night 101 days after a round.
    # 450 = a round missed by three months.
    "fao_diem_household_surveys": 450,
    "v1_conflict_t4p_westbank": 30,   # OCHA flash updates: ~weekly-biweekly;
                                      #   learned 1d rhythm is the kept-run
                                      #   artifact, not the publish cadence
    # UN2720's dashboard is capped BY THE PUBLISHER at its last verified day.
    # On 2026-10-12 that day was 2026-08-31, 42 days back, and the page said:
    # "Information for subsequent dates is pending final verification due to
    # an ongoing system migration." The series is daily, so the learned rhythm
    # gives a 7-day allowance: the dataset would read STALLED the night it is
    # first loaded and fail the job on a fetcher that is working. 45 = fresh
    # while the newest verified day is within a month and a half, late to 90,
    # stalled (and the night fails) after that. Bring it back down when the
    # cap goes: data/raw/un2720/daily.json, metadata.capped.
    "un2720_aid_daily": 45,
}

# Event-recording series: silence can mean "no events", not "feed died".
# They get a wide allowance and the note travels with the status.
EVENT_DRIVEN = {
    "v1_refugees_idmc": 90,           # displacement events
    "v1_infrastructure_unosat": 540,  # damage assessments after major events
    "v1_connectivity_ioda": 30,       # outage detections
}

# v1 refresh steps whose FAIL is an artifact, not a wound — excluded from
# the gap list, kept visible in fetch_health with the reason.
BENIGN_STEPS = {
    "docker-restart-api": "ExecStartPost restarts the container for real; "
                          "the in-container docker call always fails",
}

# Notes for failing v1 steps the project has already diagnosed. A step that is
# RETIRED (below) carries its successor instead.
STEP_NOTES = {
    "validate": "v1's own validation step (validate-data.js, 25 min a night)",
}

# ── supply lines (P1-B.3) ────────────────────────────────────────────────────
# Consecutive not-ok attempts that make a line dead. The same three the
# watchdog's fetch family uses (ops/watchdog.py FETCH_FAIL_STREAK), so the
# nightly job and the ten-minute watchdog never disagree about a line.
FAIL_STREAK = 3

# v2's own fetchers, by the labels they write to ops/fetch-events.ndjson, and
# the datasets each one feeds. `replaces` names the v1 step the line took
# over; `successor` is who carries the series if the line is ever declared
# dead (`declared_dead: "<evidence>"`), which excuses it from failing the job.
# ops/fetch_gho_wash.py writes no ledger line; the raw-artifact age below
# judges it.
SUPPLY_LINES = {
    "t4p": {"labels": ["t4p:gaza_daily", "t4p:westbank_daily",
                       "t4p:killed_in_gaza", "t4p:summary"],
            "feeds": ["t4p_gaza_daily", "v1_conflict_t4p_westbank",
                      "v1_martyrs_snapshot_2023_tech4palestine"],
            "fetcher": "ops/fetch_t4p.py", "every_days": 1},
    "ooni": {"labels": ["ooni:ps_daily"], "feeds": ["v1_connectivity_ooni"],
             "fetcher": "ops/fetch_ooni.py", "every_days": 1},
    "ioda": {"labels": ["ioda:outages"], "feeds": ["v1_connectivity_ioda"],
             "fetcher": "ops/fetch_ioda.py", "every_days": 1},
    "ocha-casualties": {"labels": ["ocha:casualties"],
                        "feeds": ["v1_casualties_ocha_casualties"],
                        "fetcher": "ops/fetch_ocha.py", "every_days": 1,
                        "replaces": "ocha-casualties"},
    "ocha-demolitions": {"labels": ["ocha:demolitions"],
                         "feeds": ["v1_demolitions_ocha_demolitions"],
                         "fetcher": "ops/fetch_ocha.py", "every_days": 1,
                         "replaces": "ocha-demolitions"},
    "pcbs-direct": {"labels": ["pcbs:population", "pcbs:cpi"],
                    "feeds": ["v1_economic_pcbs_direct"],
                    "fetcher": "ops/fetch_pcbs.py", "every_days": 1,
                    "replaces": "pcbs-indicators",
                    "note": "pcbs_poverty_rate has no source on PCBS's rebuilt "
                            "site; its 2 held rows are not refreshed"},
    # The `economic` category's two datasets, read from the publishers since
    # 2026-10-12. Both write a line every night, including the nights they
    # find the publisher's vintage unchanged and re-read nothing.
    "worldbank": {"labels": ["worldbank:indicators"],
                  "feeds": ["v1_economic_worldbank"],
                  "fetcher": "ops/fetch_worldbank.py", "every_days": 1,
                  "replaces": "worldbank",
                  "note": "125 held World Bank series for PSE; a series that "
                          "fails or is archived is named in the ledger line's "
                          "`missing` while the rest are written"},
    "imf": {"labels": ["imf:datamapper"], "feeds": ["v1_economic_imf"],
            "fetcher": "ops/fetch_imf.py", "every_days": 1,
            "replaces": "imf-economic",
            "note": "18 held IMF DataMapper series for WBG; the World Economic "
                    "Outlook moves twice a year (April, October)"},
    "hamoked": {"labels": ["hamoked:detention"],
                "feeds": ["v1_prisoners_hamoked"],
                "fetcher": "ops/fetch_hamoked.py", "every_days": 1,
                "replaces": "hamoked-detention",
                "successor": "Addameer (v1_prisoners_addameer, via v1's "
                             "`prisoners` step): total and administrative "
                             "detention, 2022 onward"},
    "unrwa-registered": {"labels": ["unrwa:registered"],
                         "feeds": ["unrwa_registered_hdx"],
                         "fetcher": "ops/fetch_unrwa_registered.py", "every_days": 1,
                         "note": "UNRWA's quarterly HDX release; the file holds one "
                                 "quarter, the databank keeps every one it has seen"},
    # ── the lines cut from v1's tree and from frozen files on 2026-10-12 ──
    "hdx-land": {"labels": ["hdx:west_bank_barrier", "hdx:peacenow_settlements"],
                 "feeds": ["v1_land_ocha", "v1_land_peace_now"],
                 "fetcher": "ops/fetch_hdx_land.py", "every_days": 1, "replaces": "land"},
    "goodshepherd-demolitions": {"labels": ["goodshepherd:demolitions"],
                                 "feeds": ["v1_land_goodshepherd"],
                                 "fetcher": "ops/fetch_goodshepherd.py", "every_days": 1},
    "peacenow-settlers": {"labels": ["peacenow:settlers"],
                          "feeds": ["v1_settlements_peace_now"],
                          "fetcher": "ops/fetch_peacenow.py", "every_days": 1,
                          "replaces": "peacenow-settlers"},
    "peacenow-settlement-population": {
        "labels": ["peacenow:settlement_population"],
        "feeds": ["peacenow_settlement_population"],
        "fetcher": "ops/fetch_peacenow_settlements.py", "every_days": 7,
        "note": "Peace Now's list of settlements (a Google spreadsheet linked "
                "from its Population page); re-read weekly, no ledger line on "
                "the nights between. A year's column arrives about once a year "
                "(see ALLOWANCE_OVERRIDE_DAYS)"},
    "addameer": {"labels": ["addameer:statistics"], "feeds": ["v1_prisoners_addameer"],
                 "fetcher": "ops/fetch_addameer.py", "every_days": 1, "replaces": "prisoners"},
    "wfp-food": {"labels": ["wfp:food_prices"], "feeds": ["v1_food_wfp"],
                 "fetcher": "ops/fetch_wfp_food.py", "every_days": 1},
    "hdx-schools": {"labels": ["hdx:schools"], "feeds": ["v1_education_hdx"],
                    "fetcher": "ops/fetch_hdx_schools.py", "every_days": 1},
    "hdx-infrastructure": {"labels": ["hdx:barrier", "hdx:village_boundaries",
                                      "unosat:gaza_damage"],
                           "feeds": ["v1_infrastructure_hdx", "v1_infrastructure_unosat"],
                           "fetcher": "ops/fetch_hdx_infrastructure.py", "every_days": 1},
    "gho-health": {"labels": ["gho:health"], "feeds": ["v1_health_who"],
                   "fetcher": "ops/fetch_gho_health.py", "every_days": 7},
    "fts": {"labels": ["fts:flows"], "feeds": ["v1_funding_unfts"],
            "fetcher": "ops/fetch_fts.py", "every_days": 1, "replaces": "unfts-funding"},
    "idmc": {"labels": ["idmc:events"], "feeds": ["v1_refugees_idmc"],
             "fetcher": "ops/fetch_idmc.py", "every_days": 1, "replaces": "idmc-displacement"},
    "ucdp": {"labels": ["ucdp:ged", "ucdp:candidate"], "feeds": ["v1_conflict_ucdp"],
             "fetcher": "ops/fetch_ucdp.py", "every_days": 1, "replaces": "ucdp-conflict"},
    "un2720": {"labels": ["un2720:daily"], "feeds": ["un2720_aid_daily"],
               "fetcher": "ops/fetch_un2720.py", "every_days": 1,
               "note": "UN2720's aid dashboard, one attempt a night for all "
                       "three stages; the publisher caps the window at its "
                       "last verified day (see ALLOWANCE_OVERRIDE_DAYS)"},
}

# v1 refresh steps that are RETIRED: a successor carries what they did, so
# their failure is not a dead supply line. They stay listed — with the
# successor, and as `retired_pending` while v1 keeps running them — until the
# line is removed from v1's refresh-data.sh (docs/HANDS-2026-09-24.md §9,
# Zaid's hand: v1 is live production and is never edited from here).
RETIRED_V1_STEPS = {
    "ocha-casualties": "v2 supply line ocha-casualties (ops/fetch_ocha.py)",
    "ocha-demolitions": "v2 supply line ocha-demolitions (ops/fetch_ocha.py)",
    "pcbs-indicators": "v2 supply line pcbs-direct (ops/fetch_pcbs.py)",
    "worldbank": "v2 supply line worldbank (ops/fetch_worldbank.py)",
    "imf-economic": "v2 supply line imf (ops/fetch_imf.py)",
    "hamoked-detention": "v2 supply line hamoked (ops/fetch_hamoked.py)",
    "databank-martyrs": "v2 Tier 2 databank (martyrs_snapshot_2023, from T4P)",
    "databank-btselem": "v2 Tier 2 databank (v1's people-killed backfill; the "
                        "B'Tselem register is a letter, not a feed)",
    "databank-gaza": "v2 Tier 2 databank (conflict_gaza, from T4P)",
    "databank-prisoners": "v2 Tier 2 databank (prisoners + prisoners_hamoked)",
    "databank-ucdp-actions": "v2 Tier 2 databank (UCDP events, migration 083)",
    "databank-structures": "v2 Tier 2 databank (infrastructure)",
    "databank-incidents": "v2 Tier 2 databank (v1's Insecurity Insight backfill)",
    "learn-corrections": "v2's accuracy loop (ops/measure_review.py, learn/)",
    "validate": "v2's spec floors, identity invariant and this radar — the "
                "loader refuses what validate-data.js only reported",
    "docker-restart-api": "palestine-refresh.service's ExecStartPost (the "
                          "in-container docker call never worked)",
    "prisoners": "v2 supply line addameer (ops/fetch_addameer.py)",
    "peacenow-settlers": "v2 supply line peacenow-settlers (ops/fetch_peacenow.py)",
    "land": "v2 supply line hdx-land (ops/fetch_hdx_land.py)",
    "culture": "frozen corpus data/frozen/culture.json.gz",
    "ucdp-conflict": "v2 supply line ucdp (ops/fetch_ucdp.py)",
    "unfts-funding": "v2 supply line fts (ops/fetch_fts.py)",
    "idmc-displacement": "v2 supply line idmc (ops/fetch_idmc.py)",
}

# Exit code for "found at least one dead supply line": the job must fail.
DEAD_EXIT = 5

# Datasets whose occurred_at is disclaimed (precision=unknown registers):
# freshness runs on ingest recency instead, and says so.
REGISTER_BASIS = "register (occurred_at disclaimed; age = last ingest)"
# ...unless the loader records when the publisher's file was last read
# (dataset.attrs.vintage_checked_at, written by every run that read a fetched
# file: ingest/databank.py). A register is then as old as its last successful
# reading: a school list re-read last night is fresh however old the list, and
# one whose fetch has failed for a quarter is stalled, which is the question.
# Judged on the last ingest alone, five static registers were going to read
# STALLED in February 2027 for the crime of not having changed.
CHECKED_BASIS = "register (publisher's vintage {vintage}; age = days since its file was last read)"

# Fill paths for gaps the project has already scoped. Everything else gets
# honest "unscoped".
FILL_PATHS = {
    "v1_casualties_ocha_casualties": "v2 fetch ops/fetch_ocha.py (supply line "
                                     "ocha-casualties) — read that line in "
                                     "supply_lines first.",
    "v1_demolitions_ocha_demolitions": "v2 fetch ops/fetch_ocha.py (supply "
                                       "line ocha-demolitions).",
    "v1_food_wfp": "WFP price data usually lands monthly; check the HDX "
                   "dataset revision if LATE persists.",
    "v1_aid_access_unrwa_aid_trucks": "dead. UN2720's dashboard "
                                      "(un2720_aid_daily, ops/fetch_un2720.py) "
                                      "counts UN-coordinated cargo from "
                                      "2025-05-19 under another definition: a "
                                      "second series, never a continuation. "
                                      "2025-01-17 to 2025-05-18 has no source.",
    "v1_economic_pcbs_direct": "v2 fetch ops/fetch_pcbs.py (supply line "
                               "pcbs-direct); poverty has no source.",
    "v1_prisoners_hamoked": "v2 fetch ops/fetch_hamoked.py (supply line "
                            "hamoked); successor if it dies: Addameer.",
    "v1_conflict_tech4palestine": "fix installed 2026-08-06, heals via the "
                                  "02:35→03:41 chain — if this is still "
                                  "stalled after 2026-08-07, the container "
                                  "copy was lost (recreate re-copies, see "
                                  "task #55).",
    "v1_connectivity_ooni": "v2 fetch ops/fetch_ooni.py (supply line ooni).",
}

ERAS = [
    ("1922–1947", "1922-01-01", "1947-12-31"),
    ("1948–1966", "1948-01-01", "1966-12-31"),
    ("1967–1999", "1967-01-01", "1999-12-31"),
    ("2000–2009", "2000-01-01", "2009-12-31"),
    ("2010 – Oct 2023", "2010-01-01", "2023-10-06"),
    ("Oct 2023 → today", "2023-10-07", "2100-01-01"),
]


# ── the hand-over, measured on the indicators two datasets SHARE ─────────────

HANDOVER_SQL = """
WITH shared AS (
  SELECT o.indicator FROM observation o JOIN dataset d USING (dataset_id)
   WHERE d.key = %(old)s AND upper_inf(o.sys_period)
  INTERSECT
  SELECT o.indicator FROM observation o JOIN dataset d USING (dataset_id)
   WHERE d.key = %(new)s AND upper_inf(o.sys_period)
)
SELECT (max(o.occurred_at) FILTER (WHERE d.key = %(old)s))::date,
       (min(o.occurred_at) FILTER (WHERE d.key = %(new)s))::date
  FROM observation o JOIN dataset d USING (dataset_id)
 WHERE d.key IN (%(old)s, %(new)s) AND upper_inf(o.sys_period)
   AND o.indicator IN (SELECT indicator FROM shared)
"""


def _hands_over(last_old, first_new) -> bool:
    """True when the successor's first day falls 1-3 days after the
    predecessor's last. Same window as before; only the inputs changed."""
    return bool(last_old and first_new and 0 < (first_new - last_old).days <= 3)


def continued_successors(cur) -> set[str]:
    """Which CONTINUED_BY successors really picked up where their predecessor
    stopped. Otherwise the predecessor is judged as before and a broken
    hand-over stays visible.

    MEASURED ON THE INDICATORS THE TWO DATASETS SHARE. A successor may also
    carry indicators the predecessor never held -- t4p_gaza_daily gained the
    cumulative children/women/medical/press/civil-defence tolls and the daily
    line back to 2023-10-07 on 2026-10-11, where the frozen series holds only
    gaza_cumulative_killed/_injured. Those extra indicators overlap nothing,
    so they cannot double-count; but a min() across the whole successor read
    2023-10-07, measured the hand-over at -1036 days, rejected a declaration
    that was true, and reported the predecessor STALLED at severity 5 (which
    exits this job 5). The shared indicators are the only ones that hand over,
    so they are the only ones the window may be measured on.
    """
    ok: set[str] = set()
    for old_key, new_key in CONTINUED_BY.items():
        cur.execute(HANDOVER_SQL, {"old": old_key, "new": new_key})
        row = cur.fetchone()
        if row and _hands_over(row[0], row[1]):
            ok.add(new_key)
    return ok


def measure_datasets(cur, today: date) -> list[dict]:
    cur.execute("""
        SELECT d.dataset_id, d.key, d.v1_category, s.key, s.license_spdx,
               s.commercial_use, d.attrs
        FROM dataset d JOIN source s ON s.source_id = d.source_id
        WHERE d.v1_category IS NOT NULL ORDER BY d.key""")
    metas = cur.fetchall()
    out = []
    continued_ok = continued_successors(cur)
    for ds_id, key, cat, src, lic, comm, ds_attrs in metas:
        ds_attrs = ds_attrs or {}
        cur.execute("""
            SELECT count(*), min(occurred_at)::date, max(occurred_at)::date,
                   count(DISTINCT occurred_at::date),
                   mode() WITHIN GROUP (ORDER BY occurred_precision::text),
                   max(coalesce(reported_at, ingested_at))::date
            FROM observation WHERE dataset_id = %s AND upper_inf(sys_period)""",
            (ds_id,))
        n, lo, hi, days, prec, last_touch = cur.fetchone()
        if not n:
            continue
        # the series' own rhythm + its largest internal hole
        cur.execute("""
            WITH d AS (SELECT DISTINCT occurred_at::date AS dt
                       FROM observation
                       WHERE dataset_id = %s AND upper_inf(sys_period)),
            g AS (SELECT dt, dt - lag(dt) OVER (ORDER BY dt) AS gap FROM d)
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY gap),
                   max(gap),
                   (SELECT dt FROM g WHERE gap = (SELECT max(gap) FROM g)
                    LIMIT 1)
            FROM g WHERE gap IS NOT NULL""", (ds_id,))
        med, maxgap, hole_end = cur.fetchone() or (None, None, None)

        basis, last_info = "data dates", hi
        if prec == "unknown":
            basis, last_info = REGISTER_BASIS, last_touch
            checked = str(ds_attrs.get("vintage_checked_at") or "")[:10]
            if checked:
                try:
                    last_info = date.fromisoformat(checked)
                    basis = CHECKED_BASIS.format(
                        vintage=ds_attrs.get("vintage") or "per indicator")
                except ValueError:
                    pass
        age = (today - last_info).days if last_info else None

        if key in ALLOWANCE_OVERRIDE_DAYS:
            allowance = ALLOWANCE_OVERRIDE_DAYS[key]
        elif key in EVENT_DRIVEN:
            allowance = EVENT_DRIVEN[key]
        elif med:
            allowance = max(int(3 * med), 7)
        else:
            allowance = 90
        if key in DEAD_UPSTREAM:
            status = "dead_upstream"
        elif key in AWAITING_PERMISSION:
            status = "awaiting_permission"
        elif key in CLOSED_CORPUS:
            status = "closed_corpus"
        elif key in CONTINUED_BY and CONTINUED_BY[key] in continued_ok:
            status = "continued"
        elif age is None:
            status = "unmeasured"
        elif age <= allowance:
            status = "fresh"
        elif age <= 2 * allowance:
            status = "late"
        else:
            status = "stalled"

        hole = None
        if med and maxgap and days and days > 30 and maxgap >= 6 * max(med, 1) \
                and maxgap >= 14 and status not in ("closed_corpus",):
            hole = {"days": int(maxgap),
                    "ended": str(hole_end),
                    "rhythm_days": float(med)}

        out.append({
            "dataset": key, "category": cat, "source": src,
            "license": lic, "commercial": comm,
            "rows": n, "span": [str(lo), str(hi)],
            "distinct_days": days, "precision": prec,
            "rhythm_median_days": float(med) if med else None,
            "freshness_basis": basis,
            "last_information_day": str(last_info) if last_info else None,
            "age_days": age, "allowance_days": allowance,
            "status": status,
            "event_driven": key in EVENT_DRIVEN,
            "dead_reason": DEAD_UPSTREAM.get(key),
            "largest_hole": hole,
        })
    return out


def measure_eras(cur) -> dict:
    grid: dict[str, dict[str, int]] = defaultdict(dict)
    for label, lo, hi in ERAS:
        cur.execute("""
            SELECT d.v1_category, count(*)
            FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
            WHERE d.v1_category IS NOT NULL AND upper_inf(o.sys_period)
              AND o.occurred_at >= %s AND o.occurred_at <= %s
            GROUP BY 1""", (lo, hi + " 23:59:59"))
        for cat, n in cur.fetchall():
            grid[cat][label] = n
        cur.execute("""
            SELECT count(*) FROM event
            WHERE attrs ? 'v1_stable_id' AND upper_inf(sys_period)
              AND occurred_at >= %s AND occurred_at <= %s""",
            (lo, hi + " 23:59:59"))
        n = cur.fetchone()[0]
        if n:
            grid["(events)"][label] = n
    return {cat: {label: vals.get(label, 0) for label, _, _ in ERAS}
            for cat, vals in sorted(grid.items())}


def measure_fetch_health(today: date) -> list[dict]:
    out = []
    # v1's per-step outcomes: current FAIL streak in consecutive runs
    if V1_EVENTS.exists():
        runs: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for line in V1_EVENTS.read_text().splitlines()[-4000:]:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            runs[e["label"]].append((e["at"], e["outcome"]))
        for label, hist in sorted(runs.items()):
            hist.sort()
            streak = 0
            for _, outcome in reversed(hist):
                if outcome == "FAIL":
                    streak += 1
                else:
                    break
            if streak:
                out.append({"line": f"v1 step {label}", "step": label,
                            "kind": "v1_refresh",
                            "fail_streak": streak, "last_at": hist[-1][0],
                            "benign": BENIGN_STEPS.get(label),
                            "retired_to": RETIRED_V1_STEPS.get(label),
                            "note": STEP_NOTES.get(label)})
    # v2-native fetch artifacts: file age at the RAW layer — the June-9 class
    for name, path, allowance in [
        # v2's own T4P fetch (ops/fetch_t4p.py). Until 2026-09-23 this line
        # watched v1's tree, which v2 stopped reading for T4P on 2026-08-08,
        # so it reported a 45-day-old file at severity 5 while the file v2
        # actually loads was refreshed every night.
        ("t4p raw casualties (v2-native fetch)",
         ROOT / "data" / "raw" / "tech4palestine" / "gaza_daily.json", 3),
        ("gho wash (v2-native fetch)", ROOT / "data" / "gho" / "wash_pse.json", 3),
        # The as_of evidence base. If this stops growing, the history layer
        # keeps answering and quietly stops being provable — the exact class
        # of silent failure this radar exists to catch.
        ("as_of evidence: v2 loader inputs",
         ROOT / "data" / "evidence" / "v2-manifest.json", 2),
        ("as_of evidence: vaulted v1 snapshots",
         ROOT / "data" / "evidence" / "manifest.json", 400),
    ]:
        try:
            if path.is_dir():
                mtime = max(p.stat().st_mtime for p in path.glob("*.json"))
            else:
                mtime = path.stat().st_mtime
            age = (today - date.fromtimestamp(mtime)).days
            out.append({"line": name, "kind": "raw_artifact",
                        "age_days": age, "allowance_days": allowance,
                        "status": "fresh" if age <= allowance else "stalled"})
        except (OSError, ValueError):
            out.append({"line": name, "kind": "raw_artifact",
                        "status": "missing"})
    return out


def _when(s: str) -> datetime:
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def read_events(path: Path, limit: int = 20000) -> dict[str, list[dict]]:
    """A fetch ledger (v2's ops/fetch-events.ndjson or v1's refresh-events)
    as label → attempts, oldest first. Both write {label, at, outcome}; v2
    says "ok", v1 says "OK" — anything else is a failed attempt."""
    if not path.exists():
        return {}
    by: dict[str, list[dict]] = defaultdict(list)
    for line in path.read_text(errors="replace").splitlines()[-limit:]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or not e.get("label") or not e.get("at"):
            continue
        out = str(e.get("outcome", ""))
        by[e["label"]].append({"at": e["at"], "outcome": out,
                               "ok": out.lower() == "ok"})
    for v in by.values():
        v.sort(key=lambda a: _when(a["at"]))
    return dict(by)


def judge_attempts(attempts: list[dict], now: datetime,
                   every_days: float = 1) -> dict:
    """One feed's verdict from its own attempts.

    dead     FAIL_STREAK consecutive failures, or no attempt at all for
             FAIL_STREAK × its cadence (the fetcher stopped being run — the
             June-9 class: nothing fails because nothing runs), or never
             attempted.
    failing  one or two failures at the tail — reported, not yet dead.
    live     the last attempt worked.
    """
    if not attempts:
        return {"status": "dead", "why": "never fetched — no attempt on record",
                "fail_streak": 0, "last_ok": None, "last_attempt": None,
                "attempts": 0}
    streak = 0
    for a in reversed(attempts):
        if a["ok"]:
            break
        streak += 1
    last = attempts[-1]
    silent = (now - _when(last["at"])).total_seconds() / 86400
    v = {"fail_streak": streak, "attempts": len(attempts),
         "last_attempt": last["at"], "last_outcome": last["outcome"],
         "last_ok": max((a["at"] for a in attempts if a["ok"]),
                        key=_when, default=None)}
    if streak >= FAIL_STREAK:
        return {**v, "status": "dead",
                "why": f"{streak} consecutive attempts failed "
                       f"(last: {last['outcome']}, {last['at'][:10]})"}
    if silent > FAIL_STREAK * every_days:
        return {**v, "status": "dead",
                "why": f"no attempt for {silent:.1f} days — the fetcher is "
                       "not being run"}
    if streak:
        return {**v, "status": "failing",
                "why": f"{streak} failed attempt(s), fewer than {FAIL_STREAK}"}
    return {**v, "status": "live", "why": None}


def judge_supply_lines(v2_events: dict, v1_events: dict,
                       datasets: list[dict], now: datetime) -> dict:
    """Every line that feeds the databank, judged — and which ones are dead.

    Returns {"v2": [...], "v1_steps": [...], "data": [...], "dead": [...]}:
    `dead` is the list the nightly job fails on. A v2 line is dead when any
    of its feeds is, or when a dataset it feeds has stalled; a v1 step is
    dead unless it is RETIRED (successor named) or BENIGN; a stalled dataset
    that no declared line feeds is a dead line of its own ("data").
    """
    status_of = {d["dataset"]: d["status"] for d in datasets}
    fed = set()
    v2 = []
    for name, decl in SUPPLY_LINES.items():
        every = decl.get("every_days", 1)
        feeds = [dict(label=lab, **judge_attempts(v2_events.get(lab, []), now,
                                                  every))
                 for lab in decl["labels"]]
        fed |= set(decl.get("feeds", []))
        stalled = [k for k in decl.get("feeds", [])
                   if status_of.get(k) == "stalled"]
        why = ([f"{f['label']}: {f['why']}" for f in feeds
                if f["status"] == "dead"]
               + [f"{k}: data stalled (older than twice its allowance)"
                  for k in stalled])
        if decl.get("declared_dead"):
            status = "declared_dead"
        elif why:
            status = "dead"
        elif any(f["status"] == "failing" for f in feeds):
            status = "failing"
        else:
            status = "live"
        v2.append({"line": name, "kind": "v2_fetch", "status": status,
                   "why": "; ".join(why) or None,
                   "fetcher": decl.get("fetcher"),
                   "feeds": decl.get("feeds", []),
                   "replaces_v1_step": decl.get("replaces"),
                   "successor": decl.get("successor"),
                   "declared_dead": decl.get("declared_dead"),
                   "note": decl.get("note"),
                   "labels": feeds})
    v1 = []
    for step, attempts in sorted(v1_events.items()):
        verdict = judge_attempts(attempts, now, 1)
        still_run = (now - _when(attempts[-1]["at"])).days < FAIL_STREAK
        if step in RETIRED_V1_STEPS:
            # Excused because a successor carries it — never because it works.
            status = "retired_pending" if still_run else "retired"
        elif step in BENIGN_STEPS and verdict["status"] != "live":
            status = "benign"
        else:
            status = verdict["status"]
        v1.append({"line": f"v1 step {step}", "step": step, "kind": "v1_step",
                   "status": status, "why": verdict["why"],
                   "fail_streak": verdict["fail_streak"],
                   "last_attempt": verdict["last_attempt"],
                   "last_ok": verdict["last_ok"],
                   "successor": RETIRED_V1_STEPS.get(step),
                   "benign": BENIGN_STEPS.get(step),
                   "note": STEP_NOTES.get(step)})
    data = [{"line": f"data {d['dataset']}", "kind": "data", "status": "dead",
             "why": f"stalled: last information {d['last_information_day']}, "
                    f"{d['age_days']}d old against a {d['allowance_days']}d "
                    "allowance — whatever feeds it has stopped delivering",
             "feeds": [d["dataset"]]}
            for d in datasets
            if d["status"] == "stalled" and d["dataset"] not in fed]
    dead = [x for x in v2 + v1 + data if x["status"] == "dead"]
    return {"v2": v2, "v1_steps": v1, "data": data, "dead": dead}


def apply_supply(datasets: list[dict], supply: dict) -> None:
    """A dataset fed by a dead line is `supply_dead`, never `fresh`: its age
    can look fine for months (a 730-day allowance) while nothing arrives."""
    line_of = {}
    for line in supply["v2"]:
        for k in line["feeds"]:
            line_of[k] = line
    for d in datasets:
        line = line_of.get(d["dataset"])
        if not line:
            continue
        d["supply_line"] = line["line"]
        if line["status"] == "dead" and d["status"] in ("fresh", "late"):
            d["status"] = "supply_dead"
            d["supply_why"] = line["why"]


def supply_counts(supply: dict) -> dict:
    def n(rows, st):
        return sum(1 for r in rows if r["status"] == st)
    v2, v1 = supply["v2"], supply["v1_steps"]
    return {"v2_lines": len(v2), "v2_live": n(v2, "live"),
            "v2_failing": n(v2, "failing"), "v2_dead": n(v2, "dead"),
            "v2_declared_dead": n(v2, "declared_dead"),
            "v1_steps": len(v1), "v1_live": n(v1, "live"),
            "v1_failing": n(v1, "failing"), "v1_dead": n(v1, "dead"),
            "v1_retired_pending": n(v1, "retired_pending"),
            "v1_retired": n(v1, "retired"), "v1_benign": n(v1, "benign"),
            "stalled_data_lines": len(supply["data"]),
            "dead": len(supply["dead"])}


def rank_gaps(datasets, fetch_health, supply: dict | None = None) -> list[dict]:
    gaps = []
    for d in datasets:
        if d["status"] == "stalled":
            gaps.append({
                "severity": 4, "kind": "freshness", "subject": d["dataset"],
                "measure": f"last information {d['last_information_day']} — "
                           f"{d['age_days']}d old against a "
                           f"{d['allowance_days']}d allowance "
                           f"(rhythm ≈ {d['rhythm_median_days']}d)",
                "fill_path": FILL_PATHS.get(d["dataset"], "unscoped — chase "
                             "the upstream before assuming it died"),
            })
        elif d["status"] == "late":
            note = (" (event-recording series — silence may mean no events)"
                    if d.get("event_driven") else "")
            gaps.append({
                "severity": 2, "kind": "freshness", "subject": d["dataset"],
                "measure": f"{d['age_days']}d old, allowance "
                           f"{d['allowance_days']}d — watch, don't panic"
                           + note,
                "fill_path": FILL_PATHS.get(d["dataset"], "recheck next run"),
            })
        elif d["status"] == "dead_upstream":
            gaps.append({
                "severity": 1, "kind": "dead_upstream",
                "subject": d["dataset"],
                "measure": d["dead_reason"],
                "fill_path": FILL_PATHS.get(d["dataset"], "successor source "
                             "unscoped"),
            })
        elif d["status"] == "awaiting_permission":
            gaps.append({
                "severity": 2, "kind": "awaiting_permission",
                "subject": d["dataset"],
                "measure": f"last information {d['last_information_day']}; "
                           + AWAITING_PERMISSION[d["dataset"]],
                "fill_path": "a person's step: send the letter, then build the fetch",
            })
        if d["largest_hole"]:
            h = d["largest_hole"]
            gaps.append({
                "severity": 2, "kind": "hole", "subject": d["dataset"],
                "measure": f"{h['days']}-day silent gap ending {h['ended']} "
                           f"in a series with a {h['rhythm_days']:.0f}d rhythm",
                "fill_path": "check bronze + upstream archive for that window",
            })
    # Dead supply lines: the gaps the nightly job FAILS on (P1-B.3). A v1
    # step's streak used to be a severity-3 line here that nobody was paged
    # for; it is judged in judge_supply_lines now, with retired steps excused
    # only by a named successor.
    for line in (supply or {}).get("dead", []):
        gaps.append({
            "severity": 5, "kind": "supply", "subject": line["line"],
            "measure": line["why"] or "dead",
            "fill_path": (f"run {line['fetcher']} by hand and read its error"
                          + (f"; successor if it cannot be revived: "
                             f"{line['successor']}" if line.get("successor")
                             else "")
                          if line.get("fetcher") else
                          "fix the step in v1, or declare it retired with its "
                          "successor in ops/gap_radar.py RETIRED_V1_STEPS"),
        })
    for f in fetch_health:
        if f.get("kind") == "v1_refresh":
            continue                      # judged as a supply line above
        if f.get("status") == "stalled":
            gaps.append({
                "severity": 5, "kind": "fetch", "subject": f["line"],
                "measure": f"raw artifact {f['age_days']}d old against "
                           f"{f['allowance_days']}d — the June-9 failure "
                           "class, at the layer where it actually breaks",
                "fill_path": "the fetcher behind this artifact stopped — "
                             "chase it TODAY",
            })
        elif f.get("status") == "missing":
            gaps.append({
                "severity": 4, "kind": "fetch", "subject": f["line"],
                "measure": "raw artifact missing entirely",
                "fill_path": "run the fetcher by hand and read its error",
            })
    return sorted(gaps, key=lambda g: -g["severity"])


def headline(today, c: dict) -> list[str]:
    """The two lines a human reads first. Every failure is COUNTED here — a
    retired v1 step that still fails inside v1 is said, not folded into
    'fresh' (the 2026-09-25 headline read '27 fresh of 32' over twelve
    supply lines that had failed for a month)."""
    s = c["supply_lines"]
    return [
        f"gap radar {today}: {c['datasets']} datasets — "
        f"{c['fresh']} fresh · {c['late']} late · {c['stalled']} stalled · "
        f"{c['supply_dead']} supply-dead · "
        f"{c['dead_upstream']} dead-upstream · {c['closed_corpus']} closed · "
        f"{c['continued']} continued · "
        f"{c.get('awaiting_permission', 0)} awaiting permission",
        f"supply lines: {s['dead']} DEAD · v2 fetches {s['v2_live']}/"
        f"{s['v2_lines']} live ({s['v2_failing']} failing, {s['v2_dead']} dead)"
        f" · v1 steps {s['v1_live']}/{s['v1_steps']} live ({s['v1_dead']} dead,"
        f" {s['v1_failing']} failing, {s['v1_retired_pending']} retired but "
        f"still run and fail in v1 until HANDS §9, {s['v1_retired']} retired, "
        f"{s['v1_benign']} benign) · {s['stalled_data_lines']} stalled "
        "datasets with no declared line"]


def main() -> int:
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    with connect() as conn, conn.cursor() as cur:
        datasets = measure_datasets(cur, today)
        eras = measure_eras(cur)
    fetch_health = measure_fetch_health(today)
    supply = judge_supply_lines(read_events(V2_EVENTS),
                                read_events(V1_EVENTS, limit=4000),
                                datasets, now)
    apply_supply(datasets, supply)
    gaps = rank_gaps(datasets, fetch_health, supply)

    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "method": "freshness on the data's own dates vs each series' median "
                  "rhythm (3x allowance, declared exceptions); holes vs "
                  "rhythm; era grid; fetch-layer artifact ages; supply lines "
                  f"judged on their own attempts ({FAIL_STREAK} failures in a "
                  "row, or silence, or a stalled dataset = dead)",
        "counts": {
            "datasets": len(datasets),
            "fresh": sum(1 for d in datasets if d["status"] == "fresh"),
            "late": sum(1 for d in datasets if d["status"] == "late"),
            "stalled": sum(1 for d in datasets if d["status"] == "stalled"),
            "supply_dead": sum(1 for d in datasets
                               if d["status"] == "supply_dead"),
            "dead_upstream": sum(1 for d in datasets
                                 if d["status"] == "dead_upstream"),
            "closed_corpus": sum(1 for d in datasets
                                 if d["status"] == "closed_corpus"),
            "continued": sum(1 for d in datasets if d["status"] == "continued"),
            "awaiting_permission": sum(1 for d in datasets
                                       if d["status"] == "awaiting_permission"),
            "open_gaps": len(gaps),
            "supply_lines": supply_counts(supply),
        },
        "datasets": datasets,
        "era_grid": eras,
        "fetch_health": fetch_health,
        "supply_lines": supply,
        "gaps": gaps,
    }
    # A dataset that stalled since the last radar is named (audit F275). It
    # is also a dead supply line, so it fails the job below.
    def _key(d):
        return d.get("dataset") or d.get("key") or d.get("name")
    prev_stalled: set = set()
    try:
        prev = json.loads(OUT.read_text())
        prev_stalled = {_key(d) for d in prev.get("datasets", []) if d.get("status") == "stalled"}
    except (OSError, ValueError):
        pass
    now_stalled = {_key(d) for d in datasets if d.get("status") == "stalled"}
    report["newly_stalled"] = sorted(x for x in (now_stalled - prev_stalled) if x)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    tmp.replace(OUT)

    for line in headline(today, report["counts"]):
        print(line)
    for g in gaps[:12]:
        print(f"  [{g['severity']}] {g['kind']:<12} {g['subject']:<44} "
              f"{g['measure'][:80]}")
    print(f"→ {OUT}")
    if report["newly_stalled"]:
        print("NEWLY STALLED:", ", ".join(report["newly_stalled"]))
    if supply["dead"]:
        print(f"DEAD SUPPLY LINES ({len(supply['dead'])}): "
              + "; ".join(f"{x['line']} — {x['why']}" for x in supply["dead"]),
              file=sys.stderr)
        return DEAD_EXIT
    return 0


if __name__ == "__main__":
    sys.exit(main())
