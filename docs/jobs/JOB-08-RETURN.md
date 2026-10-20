---
job: 08
slug: lake-second-pass
status: returned · A+B+C+D · 2026-10-20
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
| D fishing zone 2008–2026 | 175 | **32** | 143 drops; one duplicate Oslo row removed | 2009-08 → 2021-09 | 30 random: 1 duplicate dropped; 20-nm p95 read | returned · judgment pass (175 sentences) |

**E–K not started.** A and B passed Claude's review; C and D are new tonight. Every candidate sentence in A–D was read; scripts only formatted and merged.

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
