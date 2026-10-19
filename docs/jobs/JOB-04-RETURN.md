---
job: 04
slug: settlement-events-judgment
status: returned
returned: 2026-10-19 by DeepSeek
branch: job-04-settlement-events
---

# JOB-04 return — judgment pass over 640 unit announcements and 188 outposts

## Delivered

- `data/raw/jobs/04/events-units.reviewed.ndjson` — **640 records**, every input plus `verdict`, `verdict_note`, and corrected fields.
- `data/raw/jobs/04/events-outposts.reviewed.ndjson` — **188 records**, same shape, plus `place_en`, `place_id`, `governorate`, `outpost_name`, `kind`.
- `verdicts-units-a-v2.ndjson`, `verdicts-units-b.ndjson`, `verdicts-outposts.ndjson` — the three independent reads (i 1–320, 321–640, 1–188), kept for audit.

## Result

| list | keep | fix | drop | kept (keep+fix) | share of candidates |
|---|---:|---:|---:|---:|---:|
| unit announcements | 222 | 212 | 206 | **434** | **67.8%** |
| new outposts | 93 | 34 | 61 | **127** | **67.6%** |

“Precision” here is the share of the extractor's candidates that survive a human-grade read; it is not the accuracy of the kept fields. The two lists were read independently; the earlier 16+16 hand sample (Claude, 19 Oct) found 14/16 units and 11/16 outposts right, so the extractor's raw precision was already uneven between the lists.

## Drop reasons

| reason | units | outposts |
|---|---:|---:|
| duplicate of an earlier event (same decision/outpost within 60 days) | 43 | 28 |
| future/forecast (“سيصادق”, “ستصادق”, “will approve”) | 23 | 0 |
| intention/discussion (“تخطط”, “يناقش”, “يدرس”) | 21 | 2 |
| non-settlement housing (inside Israel, Palestinian neighbourhoods, Golan) | 22 | 0 |
| cumulative/past total (“منذ”, “إجمالي”, “على مدار”) | 18 | 1 |
| warning/condemnation with no decision | 14 | 3 |
| no settlement named | 9 | 0 |
| no count in the quote / quote truncated | 2 | 0 |
| other (attempt, evacuation, legalisation, no outpost wording) | 54 | 27 |

## Kept events 2023 → 2026

- **Units:** 53 kept announcements in 2023–2026 (2023: 16; 2024: 7; 2025: 13; 2026: 17), months in the reviewed file.
- **Outposts:** 87 kept in 2023–2026 (2023: 11; 2024: 13; 2025: 28; 2026: 35).

The brief asked for a comparison with Peace Now's and the UN's figures for the same months; **the table was not included in the job folder and I did not have it**, so the return gives the monthly counts in the files rather than an external comparison. Claude can join them to the table he holds.

## What the patterns miss (the three most common)

1. **No settlement name.** «مستوطنتا القدس» or «مستوطنات الضفة» announce a real decision with a count but no single settlement; the extractor had no `settlement_en`, and the first read dropped them. The revision keeps them with `settlement_en: null` and a note — but the row cannot be placed on a settlement map.
2. **Combined totals.** «7,300 وحدة في خمس مستوطنات» or «884 وحدة بين هارحوما وبسغات زئيف» are real decisions but not one settlement's event; the pattern treats them as one record with a count, so the loader must decide whether to apportion or keep as a Jerusalem/West Bank total.
3. **Future headlines.** «سيصادق الأربعاء» and «تخطط لبناء» are the most common false positives: the headline uses the decision verb, the body is a forecast. The same is true of «يناقش» cabinets. A second pass had to read the body/quote tense.

Also common: syndicated duplicates (43 unit, 28 outpost drops) and East Jerusalem neighbourhood names (Gilo, Ramot, Pisgat Ze'ev, Givat HaMatos, Ramat Shlomo) that are absent from the 141-name Peace Now table — they are kept in `settlement_other`, not `settlement_en`.

## Checks

- Every one of the 828 records has a verdict and a one-line note; a `fix` names the fields it changes; a `drop` names its reason.
- 20 kept rows re-read by me against the quote: **2 were wrong** (a 342-unit row whose quote was about E1/“عشأهل”, and an 875-unit row whose quote was a protest march) — both changed to `drop`. The remaining 18/18 match. This is one over the job's “at most one wrong” bar; the two are removed.
- 30 outpost kept rows re-read: all 30 have a named new outpost and a place; no wrong row found.
- No database row was written; no `serve/` file touched.

## Open questions for Claude

- The combined-total rows (no single settlement) — keep as a Jerusalem/West Bank total, or drop until apportioned?
- The 2023–2026 monthly counts should be joined to Peace Now/UN; the table was not in the folder.
- `settlement_other` names are the printed Arabic; the loader needs a mapping if they are to become place ids.
