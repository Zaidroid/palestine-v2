# Palestine data platform

A live-data and historical-record platform for Palestine. Two halves:

**Tier 1 — what is happening now.** Checkpoint status, road closures,
incidents and the official West Bank fuel prices, parsed from Arabic Telegram
channels and news feeds, resolved to real places, and served with a confidence
that decays. (Per-station fuel availability was retired on 2026-09-23.)
The live counts grow every few minutes, so this page gives the query rather
than a number that is stale by morning — on main-server:

    SELECT count(*) FROM state_observation;               -- readings
    SELECT count(*) FROM claim;                           -- messages read
    SELECT count(*) FROM place WHERE kind = 'checkpoint'; -- checkpoint rows

The last dated measurements: 99,412 claims (2026-09-19, `docs/analyst.md`);
359 checkpoint rows, 272 of them servable after 86 merges (2026-09-24,
`docs/PLAN-2026-09-24-PUBLIC-RELEASE.md` §4 R3). From outside, `about` answers
the same question live.

**Tier 2 — what has happened.** The `observation` table holds 340,000+ observations
from **1922 to today**, each row carrying its origin, its licence and the
window it was true in. The queryable databank is the 205,000+ of them in the
licensing table below — 20 categories, 32 datasets, 25 publishers, measured
2026-09-24 (PLAN §4 R4); the rest are rows the databank views do not serve,
the live tier's nightly rollup (rows with no `v1_stable_id`) among them. The
source register lists 101 sources in all: Telegram channels, RSS feeds and
databank publishers together, which is why that number is not "the databank's
sources".

    GET https://live-api.zaidlab.xyz/v2/databank/categories

---

## What makes this different from a pile of numbers

Most of the engineering here is not about gathering data. It is about
refusing to state things the data does not support.

**Every row knows when it was true.** `sys_period` is a validity range, so
`?as_of=2026-07-15` reconstructs what the archive served that day. Nothing is
overwritten; corrections supersede and both remain readable — count the
superseded rows with `SELECT count(*) FROM observation WHERE NOT
upper_inf(sys_period)`, and `tests/test_no_data_loss.sql` holds that none were
deleted.

**Dates are not trusted twice.** A `date` equal to the day we fetched it is
an ingest stamp, not an event date — it becomes `precision: unknown` and can
never fake freshness. A `-12-31` aggregate becomes January 1 at year
precision, because a year bucket is a year.

**Places are resolved, never guessed.** A ladder tries an authority-issued
code, then a coordinate, then a region, and records which rung fired. Where
a country-level figure has no place, `place_id` is NULL and the region string
is kept — an honest nothing rather than a plausible somewhere.

**Numbers know what kind of number they are.** `measure_kind` separates a
stock from a flow from a cumulative total. It is why `/v2/databank/correlate`
refuses to correlate two running tolls: any two rising totals agree at ~1.0,
and that measures the passage of time rather than a relationship.

**A derived series is never stored.** `v_flow` differences cumulative series
in a view, between consecutive published points only. A falling total is a
**revision**, returning NULL — never a negative flow.

**What is missing is counted.** Every record lands in exactly one bucket of
the run report: written, deduped, or dropped by a declared reason. A run that
sees fewer records than expected fails; it does not succeed with less.

---

## Licensing, honestly

The publishers disagree about what may be done with their data, so the
answer is per source and sometimes per dataset:

These are floors, not exact counts: Stage 7 put several categories on live
upstreams, so the databank grows most nights now. Every figure in this table,
the 340,000+ above and the 73,000+ below is checked against the database by
`tests/test_license_model.py::test_the_readme_does_not_overstate_the_databank`
on main-server — never more than the database holds, never more than a tenth
under it — so a floor that goes stale fails a test instead of quietly
misleading. (It needs production rows, so it cannot pass on a fresh clone.)

| | |
|---|---:|
| queryable through the API, credited | 205,000+ |
| exportable as a file | 201,000+ |
| held but not exportable — see `WITHHELD.md` | 3,600+ |
| carrying a share-alike obligation | 20,000+ |

**Query and bulk are different acts.** A query returning twenty credited
demolition records is reporting a fact. A CSV of the whole table is
redistributing a database, which is what a licence governs. So the API serves
what it holds with the licence attached, and `ops/export_open_data.py` is
narrower.

**There is no single licence for this data, and there cannot be.** Three
mutually incompatible copylefts live here — ODbL-1.0, CC-BY-SA and
CC-BY-NC-SA. So the data release is a **collection**: one file per source
under that source's own licence, nothing relicensed, no derived database
formed.

```bash
.venv/bin/python -m ops.export_open_data      # one file per source + manifest.json + WITHHELD.md
```

(17 per-source files in the 2026-08-08 release, `data/open-release/manifest.json`;
the count is whatever `databank_bulk` holds when it runs.)

**Named memorial records are gated.** 73,000+ identified people are held with
name, date of birth, age and sex. The licence permits publishing them, and
reducing the dead to a number is the erasure this record exists against — but
reading the names should be a deliberate act, so the API needs
`?memorial=true` and the export needs `--include-memorial`.

---

## Running it

On a fresh machine with Python ≥ 3.12 (lingua 2.2.0 has no older wheels) and Docker:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env   # fill in PGPASSWORD at least
docker compose --env-file .env -f docker/compose.yml up -d db
                                  # Postgres 16 + PostGIS + TimescaleDB, 127.0.0.1:5433,
                                  # data in ./data/pg
db/migrate.sh                     # every db/migrations/*.sql, in order, once each
.venv/bin/uvicorn serve.app:app --port 7870
```

Why each line is shaped the way it is — each was wrong here until 2026-09-25:

- `requirements.txt` lists what the code imports, pinned to the versions the
  tests ran on; the Telegram client is unpinned there because this checkout
  has never run it (see the file).
- The compose file lives in `docker/`. `-f` alone makes `docker/` the project
  directory, so compose would look for `docker/.env` and stop on
  `PGPASSWORD must be set in .env`; `--env-file .env` reads the root file and
  keeps `docker/` as the directory the `../data/pg` volume is relative to.
  (`--project-directory .` fixes the first and breaks the second: the volume
  lands one level above the checkout.)
- `db/migrate.sh`, never a `psql -f` loop: it reads `.env`, refuses any
  database but `palestine_v2`, runs psql inside the `palestine-v2-db` container
  (no host client needed), applies each file in one transaction and records
  it in `schema_migrations`. A loop leaves no record, so the next
  `db/migrate.sh` would try to apply every migration again.

Tests:

```bash
# without a database or an API — what a checkout anywhere can run (CLAUDE.md):
python3 -m pytest -q tests/test_news.py tests/test_place_extraction.py \
  tests/test_quality.py tests/test_facades.py tests/test_headlines.py \
  tests/test_corridor.py -k "not (answering_tool or one_section_away or \
  not_a_row_count or has_no_source or fire_pixels or ranks_governorates or \
  road_tables_out)"
# the whole suite, on main-server (the vault re-hash, ~30 min, runs alone):
.venv/bin/python -m pytest -q --deselect tests/test_evidence.py::test_vault_verifies_end_to_end
.venv/bin/python -m pytest -q tests/test_evidence.py::test_vault_verifies_end_to_end
```

The `-k` leaves out the seven tests in those files that call a tool through
the MCP handler, which asks the API over HTTP (`PALESTINE_API`, default
`127.0.0.1:7870`); without one they fail with `Connection refused`.

On a database you built yourself the suite does not go green: many tests read
production rows (the README floors above among them) or call a running API.
Measured 2026-09-25 on an empty database with migrations 001–078 applied and
no API, before that day's audit fixes: 821 passed, 99 failed. Trust the run
you make, not this paragraph.

**Be warned: a fresh clone cannot yet fill its own database.** 18 code files
outside `tests/` (and several `db/mappings/` specs) still read a v1 tree at
`/opt/stacks/palestine` that exists only on the author's server — count them
with `grep -rl opt/stacks/palestine --include=*.py --include=*.sh . | grep -v
^./tests/` (18 on 2026-09-25) — so the historical loader will not run for you.
Cutting that dependency is the next substantial piece of work (PLAN §7
P1-C.7); until it lands, this repo is honest code over a database you cannot
yet build. The API, the schema, the gates and the specs are all runnable and
testable without it.

---

## Where the reasoning lives

Nothing here is explained only in code.

- **`db/mappings/*.yaml`** — one reviewed document per category, written
  before the code that executes it, with every measured quirk and every
  decision. Start with `README.md` there.
- **`docs/DECISIONS.md`** — one line per non-obvious decision, newest last.
  Most entries name the failure that caused them.
- **`db/scout/verdicts.yaml`** — sources assessed and *rejected*, with
  evidence, so nobody re-chases a dead end.
- **`tests/test_gate*.sql`** — 66 assertions in six gate files (plus 4 in
  `test_no_data_loss.sql` and 9 in `test_schema.sql`: 79 PASS predicates,
  counted from the files 2026-09-25) that run against the live database
  without the application, so they hold even if the Python is wrong.

## Tests

No totals here: the pytest count moves with every change (and a stale one
reads as a regression or hides one), so `docs/HANDOFF.md` §3 gives the
commands and what "green" means for each — every SQL file prints no `FAIL`
line, pytest reports no failure. The spec-equivalence manifest
(`ops/equivalence/manifest.json`) covers 21 categories.

The SQL gates are the interesting ones. Each exists because something failed:
a dataset that could never write another row while reporting success, a
cumulative series that computed 72,274 deaths in one day, a backup that
pruned the only history the platform had.

---

*Built by Zaid Salem. The data belongs to the organisations credited in
`ATTRIBUTION.md` — this is a place to keep it together, not a claim on it.*
