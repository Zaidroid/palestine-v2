---
job: 02
slug: health-facilities-places
status: returned
returned: 2026-10-19 by DeepSeek
branch: job-02-health-facilities-places
---

# JOB-02 return — health facilities by place and status

## Delivered

- `data/raw/jobs/02/facilities.ndjson` — **12 facilities** with Arabic/English name, type, place, operator, first doc, event count.
- `data/raw/jobs/02/status_events.ndjson` — **79 status events** (2023-10-07 → 2026-10-19): 39 struck, 29 besieged, 4 out of service, 3 reopened, 2 evacuated, 2 partial.
- `data/raw/jobs/02/events.json` — the raw 1,673-candidate pass, kept for audit only.

| facility | place | events |
|---|---|---:|
| Kamal Adwan | Beit Lahia, North Gaza | 23 |
| Al-Shifa | Gaza City | 17 |
| Al-Awda | Nuseirat, Middle Area | 8 |
| Nasser | Khan Younis | 8 |
| Al-Amal | Khan Younis | 7 |
| Al-Sadaka (Turkish) | Gaza City | 5 |
| Al-Quds | Gaza City | 2 |
| Al-Rantisi | Gaza City | 2 |
| European Gaza | Khan Younis | 2 |
| Indonesian | Beit Lahia, North Gaza | 2 |
| Al-Durrah | Gaza City | 2 |
| Eye Hospital | Gaza City | 1 |

**Two facilities are timeline-ready (10+ events): Kamal Adwan (23) and Al-Shifa (17).** Al-Awda and Nasser are next at 8 each.

## How it was reached

41,403 unique texts → 1,673 machine candidates → 285 with a status cue adjacent to the facility → 106 after an automatic drop of casualty-arrival sentences, threats/orders, “around/near the hospital”, calls to reopen, and general roundups → **all 106 read by hand; 79 kept**. The 27 dropped at the manual stage were casualty arrivals, retrospective mentions of another hospital, or a status that belonged to a different facility in the same sentence.

## Checks

- Every one of the 79 events has a quote with the facility and the status wording; no status taken from a headline alone.
- 30 of the 79 re-read against the quote: **0 wrong status**.
- Same facility + status + day grouped with several `doc_ids`; same facility/status within 7 days collapsed to one event.
- Place is the facility's known locality; it is not inferred from a different place named in the same sentence.
- No database write, no `serve/`, no web fetch.

## Limits

- The inputs start on 2023-10-07, so this is a war-period register, not 2003→2026. Pre-2023 facility status needs a separate query.
- A “struck” event means the text reports the hospital being hit/raided; it is not a damage assessment.
- Some rows are retrospective (“اقتحام مستشفى الشفاء يوم 15 نوفمبر 2023” published in 2024); `as_of` is the publication day, `date_basis: published`.
- The 18-facility seed includes six facilities with no event surviving the read (Kuwaiti, Najjar, Jordanian field, UAE field); they are not in `facilities.ndjson` because the file is evidence-tied.

## Open questions for Claude

- Is the war-period register enough to start the map, with pre-2023 added by a second query?
- Should historical mentions be dated by the event date in the text rather than publication? That needs a date parser and would change `as_of`.

## Claude's review (2026-10-19)

**Not loaded; fixes named.** 20 of the 79 events re-read: the status wording is right in every one, but about six sit on the wrong day — retrospective mentions dated by publication (a 2026 text about a 2023 siege, a May 2024 text about a January siege, a tribute dated 2025). For a timeline, `as_of` must be the event's own date when the text gives one. Fixes: (1) parse the date in the text («في 21 يناير/كانون الثاني», «يوم 15 نوفمبر 2023», «9/12/2023») and set `as_of` to it with `date_basis: text`; (2) drop a mention with no date of its own that is clearly retrospective (a trial, a tribute, an anniversary); (3) re-check 20 rows. Then the war-period register is enough to start the map; pre-2023 is a second query.
