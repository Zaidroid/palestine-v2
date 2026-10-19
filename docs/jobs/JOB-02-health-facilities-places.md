---
job: 02
slug: health-facilities-places
status: open
opened: 2026-10-19 by Claude (Fable)
branch: job-02-health-facilities-places
---

# JOB-02 — Health facilities by place and status over time

**Why.** The health area holds 15,926 rows and 1,431 indicators, all national, none with a place. The archive holds 26,075 texts matching «"وزارة الصحة" مستشفى» (2003→2026, 34 publishers). Hospitals are named in them, with a status: working, partially working, out of service, evacuated, besieged, struck. A place-level register with status over time is the map the story bank cannot draw today.

**Goal.** A facility register with status events, each tied to a text, and a return that says which facilities have enough events for a timeline.

## Inputs

```bash
cd /home/zaid/palestine-v2
.venv/bin/python -m ops.ask_archive '"وزارة الصحة" مستشفى' --from 2023-10-07 --full --json --limit 20000 > data/raw/jobs/02/q-moh.json
.venv/bin/python -m ops.ask_archive 'مستشفى (خرج OR خارج OR توقف OR اقتحام OR حصار OR إخلاء OR قصف)' --from 2023-10-07 --full --json --limit 20000 > data/raw/jobs/02/q-status.json
# the gazetteer (read-only): place names and ids
.venv/bin/python - <<'PY'
from resolve.db import connect
with connect() as c:
    cur=c.cursor(); cur.execute("SET default_transaction_read_only = on")
    cur.execute("SELECT place_id, name_ar, name_en, kind, governorate FROM place WHERE kind='locality' ORDER BY name_ar")
    import json; json.dump(cur.fetchall(), open('data/raw/jobs/02/places.json','w'), ensure_ascii=False, default=str)
PY
```

(If the `place` columns differ, read `information_schema.columns` first; do not guess.)

## Records

Two files:

1. `facilities.ndjson` — one per facility: `facility_id` (slug), `name_ar`, `name_en` (if known), `type` (hospital / clinic / field_hospital / PHC), `place_name_ar`, `place_id` (from places.json when the locality matches exactly; else null and `place_note`), `operator` (MoH / UNRWA / NGO / private / unknown), `first_seen_doc_id`.
2. `status_events.ndjson` — one per status statement: `facility_id`, `status` (working / partial / out_of_service / evacuated / besieged / struck / reopened), `as_of` (the date the text says; else `published_at` with `date_basis: published`), `doc_id`, `publisher`, `quote` (≤300 chars), `authority_named` (MoH Gaza, MoH Ramallah, WHO, OCHA, PRCS, MSF, hospital director…), `confidence`.

## Output and acceptance

`JOB-02-RETURN.md` with: facilities by governorate and type; status events by month; the facilities with 10+ events (timeline-ready); 30 events checked by hand. Every event has a quote with the status wording; no status inferred from a headline alone. A 20-event sample re-checked by Claude finds at most one wrong status.

## Do not

- Write to the database; touch `serve/`; fetch from the web.
- Merge two facilities with similar names (الشفاء vs. مجمع الشفاء is one; الأقصى vs. شهداء الأقصى is one; العودة in Nuseirat vs. العودة in Jabalia are two).
