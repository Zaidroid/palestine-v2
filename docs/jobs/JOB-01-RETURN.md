---
job: 01
slug: water-gaza-series
status: returned
returned: 2026-10-19 by DeepSeek
branch: job-01-water-gaza-series
---

# JOB-01 return — Gaza water figures 2010→2026

## The finding first

**No water measure in the archive meets the job's own series threshold** (12 points in any two years, or 24 over any span). The closest is `need_share`: 15 exact figures over 2012 and 2023–2026, with at most 11 in any two-year window. `desalination_output` has 12 figures spread over 2012–2026 but only 9 in any two years. The archive states water numbers mostly as project capacities, damage counts, source shares («70% of the city from the Mekorot line»), or percentages of something other than water need — not as a repeated, comparable measurement.

**Delivered:** `data/raw/jobs/01/water_gaza_figures.ndjson` — **56 figures**, each with `doc_id`, `published_at`, `publisher`, `url`, `quote` (≤300 chars), `measure`, `value`, `unit`, `place`, `period`, `authority_named`, `confidence`, `attrs`.

| measure | figures | years |
|---|---|---|
| need_share | 15 | 2012, 2023, 2024, 2025, 2026 |
| desalination_output | 12 | 2012, 2014, 2021, 2024, 2025, 2026 |
| production_daily | 7 | 2024, 2025 |
| tanker_price | 7 | 2012, 2025, 2026 |
| supply_hours | 4 | 2012, 2013, 2024 |
| per_capita | 4 | 2024, 2025, 2026 |
| wells_out_of_service | 4 | 2024, 2025, 2026 |
| wells_working | 1 | 2025 |
| trucked_water | 2 | 2024, 2025 |

(`wells_working` only counts «N wells working» phrases; «N wells destroyed/out of service» is its own measure, so the two are not mixed.)

## How the 56 were reached

1. `q-water.json` (24,184 texts) and `q-tankers.json` (5,144) → **26,660 unique bodies** after collapsing syndicated copies.
2. Sentence extraction with a unit + a water cue → **3,409 raw figure sentences**.
3. Strict per-measure rules (number adjacent to its unit and its cue; no ranges, no «3–5», no standards, no damage/confiscation, no wastewater, no capacity) → **146 candidate figures**.
4. Every one of the 146 was then read against its quote; **90 were dropped**, leaving 56. Reasons counted: capacity not output (18), range/bound or «about» (17), damage/confiscation/fleet (14), share of something other than need (12), wastewater (5), standard/minimum (4), duplicate/restatement (12), other (8).

`attrs` records what the number is: `qualifier` (`approx`, `at_most`, `more_than`), `status` (`planned`, `before_destruction`), `sector` (`agriculture`), `priced_unit` (`cup`, `tanker`). The value is always the printed number; no bound was converted into a point.

## What can be said from it

- **Gaza-wide production**: 95,000 m³/day (2 June 2024), 52,000 (partial facilities, Apr 2024), 64,000 from wells (Aug 2024), 37,500 from Mekorot lines (Oct 2024), 2,500 from one solar plant (Jul 2025). Sparse, but the 2024 points are comparable.
- **Desalination**: 2,000 m³/day from three small plants (2012), 6,000 (2014), 6,500 (north Gaza, 2021), 18,000 restored (Mar and Jul 2025), 2,800 south (Dec 2024), 3,000 after power cut (Mar 2025), 1,600 before destruction (Jun 2026). Different plants — not one series.
- **Need coverage**: 10% (2012), 50% in the Middle Area (8 Oct 2023), 20–25% from named sources (Feb 2024), 40% Rafah (Mar 2025), 12% (Jul 2025), 15% of actual need (Nov 2025), 40% (Apr 2026), 10% from the main plant (Jul 2026). City and strip are mixed and must be read by `place`.
- **Tanker price**: 3.70 ILS/cup (2012, a proposed rise), 80 (Mar 2025), 100 (May 2025), 15/cup for large tankers and 100 for a 5-cup tanker (Aug 2025), 211 (2025 average, published 2026), 150 and 300 per tanker (2026). `priced_unit` says cup or tanker; do not average them.
- **Per person**: 84.6 L/day before the war (Mar 2024), 3 L/day north (Jan 2025), 21.2 L/day (Mar 2026, from 44,944 m³/day for the population), 4.3 L/day (Sep 2026). Four points, no series.
- **Supply frequency**: water every 5 days (2012), every 3 days (2013, two statements), every 3 days (2024). `unit=days_between`.

## Checks

- Every record's quote contains the number and the unit wording; quote max 300.
- 20-row random sample re-read: all 20 values match the quote; one `place` value was corrected during the pass (a Middle Area plant had been tagged North Gaza).
- Same figure, same day, several outlets → one record, several `doc_ids`.
- No database write, no `serve/`, no web fetch.

## Open questions for Claude

- Is `need_share` worth loading as a city-level series with `place` as the key, given the mix of city/strip and source-share statements? If yes, the 2023–2026 points are the usable block; 2012 is a single national point.
- Should the capacity figures (project «بطاقة إنتاجية») be a separate measure, `desalination_capacity`? I kept them out of `desalination_output` rather than mix capacity with output.
- The archive is not a water series. If the databank needs 2010–2022, the source is CMWU/PWA annual reports or the WASH cluster, not these texts.
