---
job: 01
slug: water-gaza-series
status: open
opened: 2026-10-19 by Claude (Fable)
branch: job-01-water-gaza-series
---

# JOB-01 — Gaza water figures 2010→2026, from the archive

**Why.** The databank holds 75 water rows (WHO, annual, national, to 2024). The archive holds 25,524 texts matching «مياه غزة» and 5,392 matching «تحلية OR صهريج OR "شاحنة مياه"», 2000→2026, 41 publishers. The numbers in them (daily production, share of need met, desalination output, trucked water, wells working, hours of supply, price of a tanker) have never been read as a series. This job reads them.

**Goal.** One NDJSON of water figures with their quotes, and a return that says which measures can be a series.

## Inputs

```bash
cd /home/zaid/palestine-v2
.venv/bin/python -m ops.ask_archive 'مياه غزة' --from 2010-01-01 --full --json --limit 30000 > data/raw/jobs/01/q-water.json
.venv/bin/python -m ops.ask_archive 'تحلية OR صهريج OR "شاحنة مياه"' --from 2010-01-01 --full --json --limit 10000 > data/raw/jobs/01/q-tankers.json
.venv/bin/python -m ops.ask_archive 'مياه غزة' --years          # the shape, for the return
```

Read the texts, not the titles. A text with no number is skipped. A text whose number is about the West Bank is kept with `place` = the named locality.

## Measures to look for (Arabic cues)

| measure | cues | unit |
|---|---|---|
| production_daily | إنتاج المياه، متر مكعب يومياً، كوب | m3_per_day |
| need_share | من الاحتياج، من الحاجة، نسبة التغطية | pct |
| desalination_output | محطة التحلية، تنتج، متر مكعب | m3_per_day |
| trucked_water | صهاريج، شاحنات مياه، نقل المياه | trucks_per_day or m3_per_day |
| wells_working | بئر، آبار تعمل، خرجت عن الخدمة | wells |
| supply_hours | ساعات ضخ، تصل المياه كل | hours or days_between |
| tanker_price | سعر الكوب، سعر الصهريج، شيكل | ILS |
| per_capita | لتر للفرد | l_per_person_day |

`authority_named`: CMWU «مصلحة مياه بلديات الساحل», PWA «سلطة المياه», UNICEF, OCHA, WASH cluster «كتلة المياه», a municipality — or null.

## Output

`data/raw/jobs/01/water_gaza_figures.ndjson`, one record per figure (the README's contract), plus `JOB-01-RETURN.md` with: records by measure × year; 30 rows checked by hand against their quotes; the measures that qualify as a series; the texts that were ambiguous and why.

## Acceptance

- Every record has `doc_id`, `quote` containing the number, `measure`, `value`, `unit`.
- No value without a quote; no quote longer than 300 characters.
- Same figure, same day, several outlets → one record, several `doc_id`s.
- A 20-row random sample re-checked by Claude finds at most one wrong value.

## Do not

- Write to the database. Do not touch `serve/`. Do not fetch from the web; everything is already in the archive.
- Round, convert or "correct" a number. If two outlets disagree, keep both records and say so in the return.
