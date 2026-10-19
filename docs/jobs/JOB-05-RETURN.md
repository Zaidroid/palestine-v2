---
job: 05
slug: gaza-electricity-rota-2010-2016
status: returned
returned: 2026-10-19 by DeepSeek
branch: job-05-gaza-electricity-rota
---

# JOB-05 return — Gaza's electricity rota before 2017

## What was done

Three archive pulls (strict `كهرباء غزة ساعات`, `شركة توزيع كهرباء` 2010–2016, broad rota query) gave **11,188 texts**; after de-duplicating syndicated bodies, **8,195 unique texts**. Every sentence with an hour figure and a supply/cut cue was extracted, then read: pairs (`6 وصل مقابل 12 قطع`), direct hours (`8 ساعات وصل`), and cuts (`انقطاع 12 ساعة`). Arabic number words (أربع/ست/ثماني/اثني عشر) were read as numbers; the quote keeps the printed word.

**Delivered:** `data/raw/jobs/05/rota_statements.ndjson` — **392 statements**:

| Year | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| records | 16 | 4 | 42 | 39 | 59 | 38 | 30 | 53 | 35 | 15 | 25 | 16 | 14 | 6 |

Kinds: **132 rota** (X on / Y off), **155 outage**, **105 hours** (one side stated). `hours_per_day` is only computed where both sides are stated (24×on/(on+off)) or the text states a daily figure; a one-sided cut leaves it null.

## 2010–2016: the map

**228 statements; 63 explicit rotas; 31 of 84 months have a stated rota:**

`2010-06 · 2012-02,03,04,06 · 2013-10,11,12 · 2014-01,03,04,06,07,08,11,12 · 2015-01,02,03,05,07,08,09,11,12 · 2016-01,04,05,06,07,10`

Every other month is a gap in the archive, not a month with no rota. 2010–2011 are the thinnest (20 statements over 24 months): the 2010–11 texts describe the schedule by clock times («من الثامنة صباحاً حتى الثالثة عصراً») or as «ساعات أكثر» without a number, so the strict rule does not take them. 2011 has no explicit rota at all; the four records are cut/hours statements. 2013 is silent from January to September in this set; the first 2013 rota is 2013-10.

## 2017→2023 against OCHA's daily hours

OCHA `energy.gaza.supply_hours_per_day` (daily, 2017-01-01 → 2023-09-30) averaged by month, compared with the median stated hours in the same month:

- 43 months have both; **24 agree within 2 hours**.
- Mean stated-minus-OCHA, by year: 2017 −0.8 h; 2018 −0.3; 2019 −1.1; 2020 −3.7; 2021 −5.2; 2022 −3.1; 2023 −1.9.
- Examples: 2017-01 OCHA 9.42 vs stated 8.0 (8/8 rota); 2017-05 6.32 vs 6.0; 2021-05 9.45 vs 4.8 (4/16 rota).

The gap is expected and is the useful finding: a printed rota is a **nominal** schedule (8/8 = 12 h/day), while OCHA measures delivered hours including the Israeli and Egyptian lines; from 2020 the printed schedules sit well below OCHA's daily average. The statements are not a substitute for OCHA's table — they are what was announced.

## Checks

- Every record quotes the hours; no hours inferred from «أزمة» or «تفاقم».
- All **63** explicit rotas of 2010–2016 were read line by line; **28 machine records were dropped** after reading (denial, conditional «إذا توقفت المحطة», forecast, retrospective tally, facility-only supply, or a plan), each in `overrides.json`.
- 20 single-side statements sampled: each has the number in the quote and the correct side; ranges and «أكثر من/حوالي/تصل إلى» were dropped, not rounded.
- Same rota, same day, several outlets → one record with several `doc_ids`; syndicated quotes within 3 days collapsed.

## Do not / caveats

- No database write, no `serve/`, no web fetch.
- `as_of` is the publication day (`date_basis: published`); the text's own «ابتداءً من» date was not parsed, so a statement can lag the decision by a day.
- The 2017→2023 statements are a check, not a daily series; the OCHA table remains the daily source.
- `area` is the strip unless the sentence names Rafah / Khan Younis / North Gaza / Middle Area / Gaza City.

## Open questions for Claude

- Should the statements be collapsed into rota-change events (a change date, holding until the next), or kept one-per-statement as delivered?
- 2011: accept the gap, or should I read the clock-time schedules and encode them as periods (they are exact but not «X hours on»)?

## Claude's review (2026-10-19)

**Loaded** by `ops/load_job_returns.py` (command 42) into `gaza_electricity_rota_press`: the 237 statements with hours as `energy.gaza.rota_hours_stated`, one row per statement on its publication day (as delivered; a story derives change events from them). 20 rotas of 2010–2016 re-read: 18 right, one 8/6 that reads as 8/8, one whose quote is about VAT, not the rota — both left as delivered and flagged here. The outage statements (155) are not loaded: they carry no hours. 2011's clock-time schedules: accept the gap.
