---
job: 05
slug: gaza-electricity-rota-2010-2016
status: returned · 2026-10-19
opened: 2026-10-19 by Claude (Fable)
branch: job-05-gaza-electricity-rota
---

# JOB-05 — Gaza's electricity rota before 2017, from the archive

**Why.** OCHA's daily table (dataset `ocha_gaza_electricity_daily`, migration 130) starts on 1 January 2017. Before that GEDCO announced its distribution rota in statements the outlets printed — «4 ساعات وصل مقابل 12 قطع», «8 وصل مقابل 8 قطع», «جدول 6 ساعات وصل» — and the archive holds them: 8,165 texts match «كهرباء غزة ساعات» (2000 → 2026; Donia al-Watan 4,718, PIC 1,486, Palestine Today 506, Ma'an 501). A rota change is an event with a date; between changes the rota holds. This job reads them into a sparse series of rota changes 2010 → 2016 (and 2017 → 2023 as a check against OCHA's daily hours).

**Goal.** One NDJSON of rota statements with their quotes, and a return that says which months 2010 → 2016 have a stated rota.

## Inputs

```bash
cd /home/zaid/palestine-v2
.venv/bin/python -m ops.ask_archive 'كهرباء غزة (وصل OR قطع OR جدول)' --from 2010-01-01 --to 2023-12-31 --full --json --limit 12000 > data/raw/jobs/05/q-rota.json
.venv/bin/python -m ops.ask_archive '"شركة توزيع كهرباء" غزة' --from 2010-01-01 --to 2016-12-31 --full --json --limit 6000 > data/raw/jobs/05/q-gedco.json
```

## Records

`data/raw/jobs/05/rota_statements.ndjson`, one per statement: `doc_id`, `published_at`, `publisher`, `url`, `quote` (≤300 chars with the hours), `hours_on`, `hours_off` (null when only one is stated), `hours_per_day` (= 24 × on / (on + off) when a rota is stated; = the stated daily hours when given directly), `area` (the strip, or a named governorate / area), `as_of` (the day the rota applies, else `published_at` with `date_basis: published`), `authority_named` (GEDCO, the energy authority, the power plant, OCHA — or null), `kind` (`rota` for X on / Y off; `hours` for "N hours a day"; `outage` for a full stop; `restored` for a return), `confidence`.

## Acceptance

- Every record quotes the hours; no hours inferred from "severe" or "worse".
- Same rota, same day, several outlets → one record with several `doc_id`s.
- `JOB-05-RETURN.md`: records by year; the months 2010 → 2016 with a stated rota (a map of gaps); 2017 → 2023 statements against OCHA's daily `energy.gaza.supply_hours_per_day` for the same dates (agree / differ, with examples: OCHA gives a daily average, a 4/12 rota is 6 h); 30 rows checked by hand. Claude re-checks 20; at most one wrong.

## Do not

- Write to the database; touch `serve/`; fetch from the web (GEDCO's site has no archive; Facebook is off limits).
- Convert a rota into hours when the text gives only one side.
