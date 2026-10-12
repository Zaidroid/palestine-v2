"""Move the held Insecurity Insight events onto the publisher's own event ids.

WHY (2026-10-12)
The events loaded on 11 October carry v1's incident id, which was meant to end
in the publisher's event number and missed it under three of its four column
spellings (ops/fetch_insecurity_insight.py, legacy_incident_id). Measured on
the publisher's eighteen files:

  - 9,627 incidents with their own content were dropped as repeats of another:
    6,189 of the Protection file's 7,400 (it has no id column and few
    coordinates), 1,601 food-system, 168 water, 15 sexual-violence incidents;
  - the same health-care incident, present in the thematic file and again in
    the yearly SHCC files, was held once per file: 4,965 distinct incidents
    stood as 7,903 events.

The fetcher now identifies an incident by the publisher's number within its
category. This script moves what is already held, ONCE, before the first load
from the new file:

  - a held event whose source row is known gets the new id (the old one stays
    in attrs.v1_stable_id_before);
  - where several held events are one incident, the one with coordinates is
    kept (else the one from the earliest file) and the others are marked
    superseded, pointing at it. Nothing is
    deleted, and every change is versioned by the event table's own trigger;
  - an event from the 2019/2020 SHCC files, which give a month, is dated the
    first of that month at month precision (it was the 15th, called a day);
  - a held event whose row the publisher has since changed or removed is left
    exactly as it is, and counted.

The load that follows then finds every re-keyed event held and writes the
incidents that were never held.

  .venv/bin/python -m ops.rekey_insecurity_insight            # report only
  .venv/bin/python -m ops.rekey_insecurity_insight --apply    # Zaid's hand

Safe to repeat: an event already moved is skipped.

ROLLBACK (before any load from the new file; after one, the newly written
events would also have to be retired):
  UPDATE event SET attrs = (attrs - 'v1_stable_id_before' - 'occurred_before')
                           || jsonb_build_object('v1_stable_id', attrs->>'v1_stable_id_before'),
                   occurred_at = COALESCE((attrs->>'occurred_before')::timestamptz, occurred_at),
                   occurred_precision = CASE WHEN attrs ? 'occurred_before' THEN 'day' ELSE occurred_precision END
   WHERE attrs->>'dataset_key' = 'insecurity_insight_incidents' AND attrs ? 'v1_stable_id_before';
  UPDATE event SET status = 'believed', superseded_by = NULL, correction_note = NULL
   WHERE attrs->>'dataset_key' = 'insecurity_insight_incidents'
     AND status = 'superseded' AND correction_note LIKE 'ii-rekey 2026-10-12%';
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetch_insecurity_insight import ID_MAP, OUT          # noqa: E402
from resolve.db import connect                                # noqa: E402

DATASET = "insecurity_insight_incidents"
NOTE = "ii-rekey 2026-10-12"
REPORT = ROOT / "ops" / "ii-rekey.json"


def plan(held: list[tuple], id_map: dict, incidents: dict) -> dict:
    """What to do with each held event. Pure: no database.

    held: (event_id, stable_id, day, precision, status, already_moved)"""
    rekey: dict[int, dict] = {}
    by_new: dict[str, list[tuple]] = defaultdict(list)
    counts: Counter = Counter()
    unmatched: list[str] = []
    for event_id, stable, day, precision, status, moved in held:
        counts["held"] += 1
        legacy = (stable or "")[3:] if (stable or "").startswith("ii-") else None
        if moved or (legacy in incidents and legacy not in id_map):
            counts["already_moved"] += 1
            continue
        if status != "believed":
            counts[f"left_{status}"] += 1
            continue
        if legacy is None or legacy not in id_map:
            counts["unmatched_left_as_is"] += 1
            if len(unmatched) < 12:
                unmatched.append(f"{stable} @ {day}")
            continue
        new, rank, located = (list(id_map[legacy]) + [False])[:3]
        # the copy with coordinates is the one worth keeping, as in the fetcher
        by_new[new].append(((not located, rank), event_id, stable, str(day)[:10], precision))
    for new, group in by_new.items():
        group.sort()
        _, keeper, stable, day, precision = group[0]
        rec = incidents.get(new) or {}
        fix = {}
        if rec.get("date_precision") == "month" and (day != rec["date"] or precision != "month"):
            fix = {"date": rec["date"], "precision": "month", "before": day}
            counts["dated_to_the_month"] += 1
        rekey[keeper] = {"new": f"ii-{new}", "old": stable, "keeper": None, **fix}
        counts["moved_to_the_publishers_id"] += 1
        for _, twin, tstable, _, _ in group[1:]:
            rekey[twin] = {"new": None, "old": tstable, "keeper": keeper}
            counts["superseded_as_the_same_incident"] += 1
    return {"actions": rekey, "counts": dict(counts), "unmatched_samples": unmatched}


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    data = Path(argv[argv.index("--data") + 1]) if "--data" in argv else OUT
    idmap = Path(argv[argv.index("--map") + 1]) if "--map" in argv else ID_MAP
    if not data.exists() or not idmap.exists():
        print(f"rekey: {data.name} or {idmap.name} is missing; run ops.fetch_insecurity_insight first",
              file=sys.stderr)
        return 1
    payload = json.loads(data.read_text(encoding="utf-8"))
    incidents = {r["incident_id"]: r for r in payload["data"]}
    if not any("incident_id_legacy" in r for r in payload["data"][:50]):
        print("rekey: the data file was written under the old id rule; fetch again first", file=sys.stderr)
        return 1
    id_map = json.loads(idmap.read_text(encoding="utf-8"))

    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT event_id, attrs->>'v1_stable_id', occurred_at::date, occurred_precision::text,
                   status::text, attrs ? 'v1_stable_id_before'
              FROM event
             WHERE attrs->>'dataset_key' = %s AND upper_inf(sys_period)""", (DATASET,))
        held = cur.fetchall()
        p = plan(held, id_map, incidents)
        acts = p["actions"]
        report = {"at": datetime.now(timezone.utc).isoformat(), "applied": False,
                  "incidents_in_file": len(incidents), **p["counts"],
                  "unmatched_samples": p["unmatched_samples"]}
        if apply and acts:
            cur.execute("SET LOCAL lock_timeout = '20s'")
            cur.execute("SET LOCAL statement_timeout = '300s'")
            cur.execute("CREATE TEMP TABLE _ii_rekey (event_id bigint PRIMARY KEY, new_id text, "
                        "old_id text, keeper bigint, new_date date, before text) ON COMMIT DROP")
            with cur.copy("COPY _ii_rekey FROM STDIN") as cp:
                for eid, a in acts.items():
                    cp.write_row((eid, a["new"], a["old"], a["keeper"], a.get("date"), a.get("before")))
            cur.execute("ANALYZE _ii_rekey")
            # the copies first: a keeper may take an id only once nothing else holds it
            cur.execute("""
                UPDATE event e
                   SET status = 'superseded', superseded_by = r.keeper,
                       correction_note = %s || ': the same incident as event ' || r.keeper
                                         || ', held a second time from another of the publisher''s files'
                  FROM _ii_rekey r
                 WHERE e.event_id = r.event_id AND r.keeper IS NOT NULL""", (NOTE,))
            report["superseded"] = cur.rowcount
            cur.execute("""
                UPDATE event e
                   SET attrs = e.attrs
                               || jsonb_build_object('v1_stable_id', r.new_id, 'v1_stable_id_before', r.old_id)
                               || CASE WHEN r.new_date IS NOT NULL
                                       THEN jsonb_build_object('occurred_before', r.before)
                                       ELSE '{}'::jsonb END,
                       occurred_at = COALESCE(r.new_date::timestamptz, e.occurred_at),
                       occurred_precision = CASE WHEN r.new_date IS NOT NULL THEN 'month'::time_precision
                                                 ELSE e.occurred_precision END
                  FROM _ii_rekey r
                 WHERE e.event_id = r.event_id AND r.keeper IS NULL""")
            report["moved"] = cur.rowcount
            want = (p["counts"].get("moved_to_the_publishers_id", 0),
                    p["counts"].get("superseded_as_the_same_incident", 0))
            if (report["moved"], report["superseded"]) != want:
                conn.rollback()
                print(f"rekey: wrote {report['moved']}/{report['superseded']}, planned {want}; rolled back",
                      file=sys.stderr)
                return 1
            conn.commit()
            report["applied"] = True
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
