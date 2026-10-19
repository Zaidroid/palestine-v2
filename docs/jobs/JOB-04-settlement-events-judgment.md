---
job: 04
slug: settlement-events-judgment
status: returned · 2026-10-19
opened: 2026-10-19 by Claude (Fable)
branch: job-04-settlement-events
---

# JOB-04 — Judgment pass over the archive's settlement events

**Why.** `ops/extract_settlement_events.py` read the archive (6,410 texts naming housing units, 11,382 naming outposts) and wrote two event lists with their quotes: 640 unit announcements (2007 →) and 188 new outposts (2010 →). Claude read 16 of each by hand: about 14/16 unit events and 11/16 outposts are right. Before any row is loaded into the databank, every event needs a human-grade read against its quote. That is this job.

**Goal.** The same two files, each record marked keep / fix / drop with the fields filled, and a return that states the measured precision and what the patterns miss.

## Inputs (already on main-server, no network)

- `data/raw/settlements/events-units.ndjson` — one announcement per line: `date`, `stage` (tender / approval / plan / permit / promote / build), `units`, `settlement_ar`, `settlement_en` (from the reviewed table `db/reference/peacenow_settlement_names.yaml`; null when unmatched), `region`, `quote`, `doc_ids`, `outlets`, `url`, `where` (title or body).
- `data/raw/settlements/events-outposts.ndjson` — one new outpost per line: `date` (the stated day, else the publication day), `place_raw`, `place_id` / `place_en` (the gazetteer locality, when matched), `governorate`, `quote`, `doc_ids`, `outlets`, `url`.
- `data/raw/settlements/aggregates-units.ndjson` — 1,102 sentences that state a period total (a year, "since the start of the year", a month); not events, but the publishers' own tallies: useful for the cross-check.
- The full texts, if a quote is not enough: `data/raw/settlements/texts-units.ndjson`, `texts-outposts.ndjson` (by `doc_id`), or `.venv/bin/python -m ops.ask_archive '<words>' --full`.
- The outside tallies to compare against, with URLs, are in the return of Claude's 19 Oct research (Peace Now yearly plans/tenders/starts 2014 → 2025, the UN's 2334 quarterly figures 2025 → 2026, the EU's East Jerusalem yearly figures, Israel's CBS construction starts); ask Claude for the table.

## What to decide, per record

**Units.** `verdict`: `keep` (a real announcement of that many units on about that date), `fix` (right event, wrong field — correct `units`, `stage`, `settlement_en`, `region` or `date` and say which), `drop` (a warning, an intention, a condition, a past or cumulative figure, a non-settlement housing figure, a duplicate of another record). Add `settlement_en` from the quote whenever the settlement is named (use the reviewed names; a settlement not in the table goes in `settlement_other` as printed). Add `authority` when the quote names who decided (Civil Administration planning council, Jerusalem district committee, housing ministry, government).

**Outposts.** `verdict` as above; `drop` also for an attempt, a warning, an outpost evacuated or legalised, or an aggregate. Fill `place_en` / `place_id` from `data/raw/settlements/localities.json` when the village is named and the pattern missed it; `governorate` always when it can be read. Add `outpost_name` when the quote names it. Note `kind` when stated: `farm` (رعوية / زراعية), `caravan`, `tent`, `road`.

**Duplicates.** Two records are one event when they describe the same decision or the same outpost within 60 days; mark the later one `drop: duplicate_of <date>`.

## Output

`data/raw/jobs/04/events-units.reviewed.ndjson` and `events-outposts.reviewed.ndjson`: every input record, plus `verdict`, `verdict_note` (one line, why), and the corrected fields. `JOB-04-RETURN.md`: precision per list (keep+fix over all), the drop reasons counted, events by month 2023 → 2026 after review against Peace Now's and the UN's figures for the same periods, and the three most common things the patterns miss (with an example quote each).

## Acceptance

- Every record carries a verdict; a `fix` names the field it changed; a `drop` names its reason.
- Claude re-reads 20 kept records of each list against their quotes; at most one wrong.
- No record is added that has no quote in the archive. No row is written to the databank.
