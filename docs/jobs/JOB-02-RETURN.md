---
job: 02
slug: health-facilities-places
status: returned · partial
returned: 2026-10-19 by DeepSeek
branch: job-02-health-facilities-places
---

# JOB-02 return — health facilities by place and status

## What was done

- Pulled the two archive queries into `q-moh.json` (14,455) and `q-status.json` (33,392), **41,403 unique texts** after de-duplication.
- Mined facility names from those texts and built an 18-facility seed register of the major Gaza hospitals (Shifa, Kamal Adwan, Indonesian, Nasser, European, Al-Amal, Al-Awda, Al-Aqsa, Al-Ahli/المعمداني, Al-Quds, Kuwaiti, Abu Yousef al-Najjar, Rantisi, Eye, Durrah, Turkish Friendship, Jordanian field, UAE field) with Arabic/English names, operator and place.
- Ran a status-event pass with direct-object patterns (`قصف مستشفى X`, `مستشفى X محاصر`, `إخلاء مستشفى X`) and a nearest-cue co-reference rule, then a strict direct-subject filter.

## Delivered

- `data/raw/jobs/02/facilities.ndjson` — **7 facilities** with at least one verified status event, each with `facility_id`, Arabic/English name, type, place, operator, first doc, event count.
- `data/raw/jobs/02/status_events.ndjson` — **16 events**: 8 struck, 5 evacuated, 3 besieged; Kamal Adwan 6, Indonesian 3, Al-Amal 2, Shifa 2, Nasser 1, Al-Najjar 1, Al-Awda 1.
- `data/raw/jobs/02/events.json` — the full machine pass (1,673 candidate events), kept for audit, **not** load-ready.

## What failed, and why the delivery is partial

A 30-event random read of the machine pass found **8 wrong (27%)**, above the job's ≤1/20 bar. The failures are systematic, not random:

1. **Co-reference.** A sentence can name three hospitals; the strike/cut belongs to one. “قصف المستشفى الإندونيسي … ومستشفى العودة” produced an Awda strike from the Indonesian clause. The nearest-cue rule helps, but Arabic sentence lists and “بينما/فيما” clauses still mis-assign.
2. **Threat/order vs event.** “يهدد بقصف”, “أنذرنا بإخلاء”, “أوامر إخلاء”, “لا نستطيع إخلاء” are orders or refusals, not an evacuation or a strike. These were the largest error class; a word-level filter removes many but not all.
3. **Retrospective.** Anniversary pieces and “في 17 أكتوبر 2023 قصف…” put a 2023 event on a 2026 row. `as_of` is the publication day, so these need a date-basis flag that the sentence parser cannot supply.

The 16 delivered events are the subset where the facility is the direct object of the status verb and the quote has no threat/order/negation. All 16 were read; no wrong status found. They are a **safe subset, not a timeline**: no facility reaches 10 events, so the job's “timeline-ready” test is not met.

## What would fix it

- A proper co-reference step (facility mentions + cue attachment by dependency, not character distance).
- A three-way cue classifier: event / order-threat / negation, on the whole sentence.
- The 1,673-candidate file is the input for that pass; it should not be loaded as is.

## Checks

- Every event has `doc_id`, `published_at`, `publisher`, `url`, `quote` (≤300), `status`, `place`, `authority_named`, `confidence`.
- No status inferred from a headline; each delivered quote contains the status wording and the facility.
- 16/16 delivered events re-read; 0 wrong.
- No database write, no `serve/`, no web fetch.

## Open questions for Claude

- Is the 7-facility safe subset useful as a seed for the map, with the register expanded later from MoH/WHO facility lists?
- Do you want the 1,673-candidate file returned to you for a manual pass, or should I build the co-reference step first?
