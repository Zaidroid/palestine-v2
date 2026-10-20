---
job: 08
slug: lake-second-pass
status: returned · A · 2026-10-20
returned: 2026-10-20 by DeepSeek
branch: job-08-lake-second-pass
---

# JOB-08 return — first night

## Families returned

| family | candidates read | kept | clusters | span | self-check | verdict |
|---|---:|---:|---:|---|---|---|
| A trees 2003–2025 | 3,191 | **705** (+42 tallies) | 188 reviewed + 517 new; 349 folded | 2004-08 → 2025-12 | 30 random: 3 errors dropped; 35 p95: 1 duplicate dropped; four 45-draws: last clean | returned · judgment pass (2,604 sentences) |

**B–K not started.** A judgment pass read all 383 new rows and all 2,221 drops, kept the 188 reviewed rows, and returns 705 incidents with 42 tallies. B starts after A clears.

## A — what is in the files

- `data/raw/jobs/08/trees_uprooted.read.ndjson.gz` — **3,191** lake records read, one fixed order; `idx` is the 0-based line in this file.
- `data/raw/jobs/08/trees_uprooted.review.yaml` — 199 `trees_incidents` (doc, idx, trees, qualifier, place, gov, actor, kind, note) and **2,992** drop entries with one reason each. `trees_tallies` is empty for 2003–2025: JOB-06's 2026 tallies are settled; the historical tallies need the second pass.
- `data/raw/jobs/08/trees_uprooted.REVIEW.md` — numbers, 12-row self-check, every row above the 95th percentile, cluster report, pattern failures.

## What was read and what was dropped

- 3,191 records → 336 candidate incidents → 203 after clustering → 199 after the high-value audit.
- The 2,992 drops are mostly not incidents: a tree mention without a count next to a tree noun, a cutting verb and a named village in one clause (2,931). The other 61 are audit drops: monthly tallies, wall-impact statements, orders to uproot, aggregate governorate splits, duplicates, and two place misreads.
- 133 outlets' rows were folded into the 199 events (same governorate, place and count within 14 days, or same day/count).

## Self-check

- 12 random kept rows re-read: 11 pass; one place corrected from البقعة to المنيا (the sentence says al-Minya). The sample is printed in REVIEW.md with dates and quotes.
- Every row above the 95th percentile (500 trees) re-read: 9 rows, all pass; a tenth (600 trees, placed on Ram Karkar but the sentence says Hebron) was dropped and is in the YAML's dropped map.
- Pattern failures: duplicate village names (Barqa/Ramallah vs Barqa/Nablus), mixed-tree sentences, aggregate governorate tallies, place from a nearby clause, and "مغتصبون" not recognized as settlers.

## Files not yet in the loader's shape

- A's incidents are in the JOB-06 `trees_incidents` shape. The loader extension for `--only 08` must read `trees_uprooted.read.ndjson.gz` (not `data/raw/jobs/06/reviewed/`) for `doc`+`idx`.
- `trees_tallies` is empty; `cited:` absent from this family. B's cumulative land figures will use the cited shape.
