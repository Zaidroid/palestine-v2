---
job: 08
slug: lake-second-pass
status: returned · A–K · 2026-10-20
returned: 2026-10-20 by DeepSeek
branch: job-08-lake-second-pass
---

# JOB-08 return — A and B

## Families returned

| family | candidates read | kept | clusters | span | self-check | verdict |
|---|---:|---:|---:|---|---|---|
| A trees 2003–2025 | 3,191 | **705** (+42 tallies) | 188 reviewed + 517 new; 349 folded | 2004-08 → 2025-12 | 30 random: 3 errors dropped; 35 p95: 1 duplicate dropped; four 45-draws: last clean | returned · judgment pass (2,604 sentences) |
| B land orders 2003–2025 | 1,986 | **247** | ~200 restatements folded by the readers | 2003-02 → 2025-12 | 30 random: 1 error dropped; 12 p95 read; 57.252 corrected | returned · judgment pass (1,986 sentences) |
| C Gaza trucks 2008–9 Oct 2025 | 1,309 | **216** | 92 period + 124 day; duplicates folded | 2012-05 → 2025-09 | 30 random: 2 errors dropped; 9 p95 read | returned · judgment pass (1,045 in scope) |
| D fishing zone 2008–2026 | 175 | **25** | 153 drops; 8 first-return rows corrected/dropped; split sectors | 2009-08 → 2021-09 | all 29 re-read; 8 fixed; 15-nm p95 read | returned · judgment pass (175 + 3 split records) |
| E hunger strikes 2004–2026 | 1,061 | **612** | 404 drops; relays folded; 32 day-only null | 2004-08 → 2026-02 | 30 random: 3 fixed; 28 p95 read | returned · judgment pass (1,061 sentences) |
| F iron gates 2004–2026 | 179 | **30** | 149 drops; cumulative totals not cited | 2008-03 → 2026-10 | 30 kept all read; 2 p95 read | returned · judgment pass (179 sentences) |
| G settler-attack tallies 2012–2026 | 758 | **69** | 689 drops; relays folded | 2012-01 → 2026-10 | 30 read; 3 p95 read | returned · judgment pass (758 sentences) |
| H administrative detention 1967–2026 | 1,216 | **137** | 1,010 drops; 35 stock; 69 folded relays | 1967-01 → 2026 | 30 read; 1 inferred sum dropped; 6 p95 read | returned · judgment pass (1,216 sentences) |
| I demolitions 2001–2008 | 174 | **27** | 147 drops; corpus clause pass not done | 2004-08 → 2008-11 | all 27 read; 13-structure p95 read | returned · lake pass; corpus gap |
| J checkpoint states 2003–2023 | 3,571 lake + 2,629 corpus clauses | **1,224** | 3,428 lake + 1,426 corpus drops; 122 folded | 2004-11 → 2023-12 | 30 read; 22 null ids; no p95 measure | returned · judgment pass (6,200 sentences) |
| K wages 2004–2026 | 783 | **51 cited** | 732 drops; wage shares and bills excluded | 2008-02 → 2026-10 | 30 read; values in quotes | returned · cited rows |

**All families A–K returned.** A–I passed Claude's review; J and K are new tonight. Every lake sentence and every unique corpus checkpoint clause in A–J, and every wage sentence in K, was read.

## B — what is in the files

- `data/raw/jobs/08/land_orders.read.ndjson.gz` — **1,986** lake records, one fixed order; `idx` is the 0-based line.
- `data/raw/jobs/08/land_orders.review.yaml` — **247** `land_orders` rows (`doc, idx, n, dunums, qualifier, place, gov, kind, purpose, date, note`) and **1,739** drops with one reason each. No `cited:` rows; the 16 cumulative since-figures are in `dropped` with their period and value.
- `data/raw/jobs/08/land_orders.REVIEW.md` — numbers, the 30-row self-check, the 12 p95 rows, cluster report and pattern failures.

## What was read and dropped

- 1,986 sentences → 247 orders. The readers folded headline/body pairs, weekly restatements and later restatements of big operations into one row.
- Drops are: no dunum count, no order/seizure verb, plan/estimate/future, cumulative «since», no place, historical before 2003, 2026, a shared count across villages, a continuation/renewal, or a misparsed magnitude.
- The dot rule: «7.498» is 7.498; «57,252» at Kafr Qaddum is 57.252; «10.677» with «6.400 housing units» is 10,677.

## Self-check

- 30 random kept rows read: one error (a shared Jayyous/Falamiya count), dropped; the other 29 pass.
- Every row above p95 (8,160 dunums) read: 12 rows, all pass after the Kafr Qaddum correction.
- Pattern failures: dot vs thousands, «137,500 ألف» misparse, shared counts across villages, continuations/renewals, plans/notices, wrong event dates, 2026.


## C — what is in the files

- `data/raw/jobs/08/gaza_trucks.read.ndjson.gz` — 1,309 lake records; **1,045** before the 2025-10-10 cutoff.
- `data/raw/jobs/08/gaza_trucks.review.yaml` — **216** `gaza_trucks_stated` rows (`doc, idx, day or from+to, trucks, scope, authority, qualifier, note`) and **808** drops.
- `data/raw/jobs/08/gaza_trucks.REVIEW.md` — numbers, 30-row self-check, 9 p95 rows, cluster report, pattern failures.


## D — what is in the files

- `data/raw/jobs/08/fishing_zone.read.ndjson.gz` — 175 lake records.
- `data/raw/jobs/08/fishing_zone.review.yaml` — **32** `fishing_zone` rows (`doc, idx, date, nautical_miles, kind, authority, note`) and **143** drops.
- `data/raw/jobs/08/fishing_zone.REVIEW.md` — numbers, 30-row self-check, p95, cluster report, pattern failures.


## E — what is in the files

- `data/raw/jobs/08/hunger_strikes.read.ndjson.gz` — 1,061 lake records.
- `data/raw/jobs/08/hunger_strikes.review.yaml` — **612** `hunger_strikes` rows (`doc, idx, date, prisoners, day_of_strike, prison, kind, name, authority, qualifier, note`) and **404** drops. 32 rows are day-only with `prisoners: null`; the loader must skip them.
- `data/raw/jobs/08/hunger_strikes.REVIEW.md` — numbers, 30-row self-check, p95, cluster report, pattern failures.


## F — what is in the files

- `data/raw/jobs/08/gates_installed.read.ndjson.gz` — 179 lake records.
- `data/raw/jobs/08/gates_installed.review.yaml` — **30** `gates_installed` rows (`doc, idx, date, gates, place_ar, gov, note`) and **149** drops.
- `data/raw/jobs/08/gates_installed.REVIEW.md` — numbers, all-30 self-check, p95, cluster report, pattern failures.


## G — what is in the files

- `data/raw/jobs/08/attack_tallies.read.ndjson.gz` — 758 lake records.
- `data/raw/jobs/08/attack_tallies.review.yaml` — **69** `attack_tallies` rows (`doc, idx, authority, from, to, precision, rows`) and **689** drops.
- `data/raw/jobs/08/attack_tallies.REVIEW.md` — numbers, 30-row self-check, p95, cluster report, pattern failures.


## H — what is in the files

- `data/raw/jobs/08/admin_detention.read.ndjson.gz` — 1,216 lake records.
- `data/raw/jobs/08/admin_detention.review.yaml` — **137** `admin_detention_tallies` rows (`doc, idx, authority, from, to, precision, orders, new_orders, renewals, qualifier, stock, note`) and **1,010** drops.
- `data/raw/jobs/08/admin_detention.REVIEW.md` — numbers, 30-row self-check, p95, cluster report, pattern failures.


## I — what is in the files

- `data/raw/jobs/08/demolitions_reported.read.ndjson.gz` — 174 lake records (2001–2008).
- `data/raw/jobs/08/demolitions_reported.review.yaml` — **27** `demolitions_reported` rows (`doc, idx, date, structures, kind, place_ar, gov, actor, warnings, note`) and **147** drops.
- `data/raw/jobs/08/demolitions_reported.REVIEW.md` — numbers, all-27 self-check, p95, cluster report, pattern failures, and the corpus gap.


## J — what is in the files

- `data/raw/jobs/08/checkpoint_states.read.ndjson.gz` — 3,571 lake records plus 1,203 kept corpus clauses (4,774 lines); `idx` is the line.
- `data/raw/jobs/08/checkpoint_states.review.yaml` — **1,224** `checkpoint_states` rows (`doc, idx, date, checkpoint_ar, checkpoint_id, state, who, authority, note`) and **3,428** lake drops.
- `data/raw/jobs/08/checkpoints.json` — the 277-name checkpoint gazetteer used for ids.
- `data/raw/jobs/08/checkpoint_states.REVIEW.md` — numbers, 30-row self-check, corpus method, cluster report, pattern failures.


## K — what is in the files

- `data/raw/jobs/08/wages.read.ndjson.gz` — 783 lake records.
- `data/raw/jobs/08/wages.review.yaml` — **51** `cited` rows (id, topic, measure, date, precision, value, qualifier, unit, region, publisher, document, url, quote, verification, caution) and **732** drops.
- `data/raw/jobs/08/wages.REVIEW.md` — numbers, 30-row self-check, cluster report, pattern failures.
