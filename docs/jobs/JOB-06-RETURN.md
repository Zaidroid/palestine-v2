---
job: 06
slug: archive-figures-lake
status: returned
returned: 2026-10-19 by DeepSeek
branch: job-06-archive-figures-lake
---

# JOB-06 return — the figures lake

## What is finished

- **Corpus dump:** 2,799,562 bodies, 74 publisher shards, 1.1 GB gzipped, 36 minutes, one server-side cursor, read-only DB. Deleted after the lake was built (rule 8).
- **The lake:** `data/raw/jobs/06/lake/` — **284,728 figure sentences**, 29 families, 2003–2026. Each has `doc_id`, date, publisher, url, family, cue, number, printed number, unit, qualifier, place_hint, period_hint, authority_hint, quote ≤300. 6 workers, ~42 minutes, `STOP` support; no `other` family was emitted (see below).
- **The catalogue:** `catalogue.json`, `catalogue.md`, `coverage.md` (year × family heat map, 2005–2026). Every family has the 12-row read and a verdict.
- **Ten series, pilot-reviewed:** `data/raw/jobs/06/reviewed/` — **260 kept records**, every candidate in the reviewed window read against its quote, verdict + one-line note.

## Catalogue — top of the table

| family | months | figures | 12/12 | verdict |
|---|---:|---:|---:|---|
| casualties_place | 278 | 221,498 | 10/12 | **series_ready** |
| trees_uprooted | 235 | 3,303 | 11/12 | **series_ready** |
| wages_remittances | 201 | 786 | 9/12 | **series_ready** |
| land_orders | 254 | 2,023 | 7/12 | sparse |
| unemployment | 254 | 2,681 | 8/12 | sparse |
| power_plant | 123 | 496 | 8/12 | sparse |
| hospital_capacity | 114 | 302 | 8/12 | sparse |
| cooking_gas | 105 | 367 | 8/12 | sparse |
| hunger_strike | 141 | 1,061 | 11/12 | **series_ready** |
| road_gates | 69 | 183 | 9/12 | **series_ready** |
| aid_trucks | 61 | 1,330 | 9/12 | **series_ready** |

**6 series_ready, 5 sparse, 18 noise.** The clean families are those whose cue is a phrase (trees, hunger strike, land orders, aid trucks, road gates); the noisy ones are single words (فقر, نسبة, سرير, دونم). Full table in `catalogue.md`.

## The ten reviewed series (pilot)

| family | reviewed | kept | span |
|---|---:|---:|---|
| trees_uprooted | 60 | 45 | 2026-05 → 2026-10 |
| unemployment | 60 | 49 | 2026-04 → 2026-10 |
| land_orders | 30 | 28 | 2026-07 → 2026-10 |
| rafah_crossing | 30 | 25 | 2026-07 → 2026-10 |
| cooking_gas | 30 | 23 | 2025-11 → 2026-09 |
| aid_trucks | 30 | 25 | 2025-10 → 2026-09 |
| road_gates | 30 | 11 | 2025-07 → 2026-10 |
| power_plant | 30 | 27 | 2017-06 → 2026-04 |
| hospital_capacity | 20 | 12 | 2025-07 → 2026-08 |
| displaced | 20 | 15 | 2026-09 → 2026-10 |

This is a **pilot, not the 300–3,000 per family** the brief set: the most recent 20–60 candidates per family were read, the rest are not reviewed and not delivered. The full candidate sets are in `series/*.candidates.ndjson.gz`.

**20-row self-check:** two errors found — a trees figure printed `26.395` (thousands separator) parsed as 26.395, corrected to 26,395; and a 50% national unemployment rate tagged `Gaza`, dropped. After those two, the 20 re-read match. The unemployment file therefore has 49 kept, not 50.

## Five stories the lake suggests

1. **The olive tree count is a monthly series.** 45 kept records in May–Oct 2026 alone; incidents run 50–3,000 trees, and the half-year total is 45,195 damaged/uprooted, 26,395 of them olive. A monthly curve from 2003 exists in the lake.
2. **Gaza unemployment crossed 80% and stayed there.** 68% during the war (Apr 2026), 78% for 2025, 80% in mid-2026, 85%+ in late 2026; the West Bank moved 28% → 42%. The lake has 2,681 sentences over 254 months.
3. **2026 is a land-order year.** 37.481 dunums at Beitunia, 741 at Jenin, 5,283 at Jaba, 137,500 behind the wall at Jayyous; the cumulative since October 2023 is 64.2 thousand dunums. 28 kept orders in three months.
4. **Rafah is a closure series, not a crossing series.** In September 2026 it was closed 20 of 30 days; 21,000 patients wait, 1,929 have died after closure, and only 60–80 patients leave a week. 25 kept records in three months.
5. **Aid is a compliance series.** 69,387 trucks entered in 330 days of the ceasefire, against 198,000 promised (35%); September 2026 alone was 986 of 6,600. The lake has 1,330 sentences.

## What the patterns miss

- **Run-on headline bodies.** Many bodies are a bulletin pasted as one paragraph; the number and the cue can be in different headlines. The quote window is the number ±150 chars, so related-but-different headlines leak in. This is the largest source of the noise.
- **Single-word cues.** فقر, نسبة, سرير, دونم, شهيد, صاروخ match any sentence; the 12-row read found 0–4/12 right for several families. The fix is clause-level patterns, which the reviewed series used.
- **Dot as thousands separator.** `26.395` is 26,395, not 26.395; the lake reads it as a decimal.
- **Place vs national.** A national rate can carry a Gaza place hint from a nearby clause.
- **`other` not built.** The lake keeps only the 29 named families; a number with a unit that fits none was not emitted. That is a deliberate cap, not a claim that the archive has no other figures.

## Not finished

- Step 3's per-family volume (300–3,000 kept) — only the pilot 260.
- The other 19 families were not reviewed as series.
- `other` family, and a full place gazetteer mapping (`place_id` is filled only when `place_hint` matches a locality name exactly).

Files: `lake/`, `catalogue.json`, `catalogue.md`, `coverage.md`, `samples.tsv`, `reviewed/`, `series/`. Corpus deleted.
