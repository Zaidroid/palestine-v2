# Palestine data platform

A live-data and historical-record platform for Palestine. Two halves:

**Tier 1 — what is happening now.** Checkpoint status, road closures,
incidents and the official West Bank fuel prices, parsed from Arabic Telegram
channels and news feeds, resolved to real places, and served with a confidence
that decays. (Per-station fuel availability was retired on 2026-09-23.)
Over a million state observations across 35,000+ claims and 359 checkpoints,
and growing every few minutes — which is why those three are rounded here and
exact only in the API.

**Tier 2 — what has happened.** 340,000+ observations and 10,400+ events from
**1922 to today**, across 21 categories and 101 sources, each row carrying
its origin, its licence and the window it was true in.

    GET https://live-api.zaidlab.xyz/v2/databank/categories

---

## What makes this different from a pile of numbers

Most of the engineering here is not about gathering data. It is about
refusing to state things the data does not support.

**Every row knows when it was true.** `sys_period` is a validity range, so
`?as_of=2026-07-15` reconstructs what the archive served that day. Nothing is
overwritten; corrections supersede and both remain readable. 8,877 rows are
superseded and none were deleted.

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

101 sources disagree about what may be done with their data, so the answer is
per source and sometimes per dataset:

Measured 2026-08-08. These are lower bounds, not exact counts: Stage 7 put
several categories on live upstreams, so the databank grows most nights now.
A figure here is a floor the API is checked against — never a number that
was true once and quietly stopped being true.

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
.venv/bin/python -m ops.export_open_data      # 18 files + WITHHELD.md
```

**Named memorial records are gated.** 73,000+ identified people are held with
name, date of birth, age and sex. The licence permits publishing them, and
reducing the dead to a number is the erasure this record exists against — but
reading the names should be a deliberate act, so the API needs
`?memorial=true` and the export needs `--include-memorial`.

---

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # fill in, then: chmod 600 .env
docker compose up -d db       # Postgres 16 + PostGIS + TimescaleDB
for f in db/migrations/*.sql; do psql -f "$f"; done
.venv/bin/python -m pytest -q
.venv/bin/uvicorn serve.app:app --port 7870
```

**Be warned: a fresh clone cannot yet fill its own database.** 17 files still
read a v1 tree at `/opt/stacks/palestine` that exists only on the author's
server, so the historical loader will not run for you. Cutting that
dependency is the next substantial piece of work; until it lands, this repo
is honest code over a database you cannot yet build. The API, the schema, the
gates and the specs are all runnable and testable without it.

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
- **`tests/test_gate*.sql`** — 66 assertions that run against the live
  database without the application, so they hold even if the Python is wrong.

## Tests

```
557 pytest · 82 SQL gates · 21/21 spec-equivalence
```

The SQL gates are the interesting ones. Each exists because something failed:
a dataset that could never write another row while reporting success, a
cumulative series that computed 72,274 deaths in one day, a backup that
pruned the only history the platform had.

---

*Built by Zaid Salem. The data belongs to the organisations credited in
`ATTRIBUTION.md` — this is a place to keep it together, not a claim on it.*
