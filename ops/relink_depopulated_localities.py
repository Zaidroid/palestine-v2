"""Put each depopulated locality on its own gazetteer row (P1-B.1 follow-up).

v1's importer, when it could not match a village, filed the event on the
GOVERNORATE or a same-named modern town: Imwas, Bayt Nuba and al-Latrun (1967)
read "رام الله" in the databank. 28 of the 32 misfiled localities have their own
Palestine Open Maps row by name within 1,500 m of the raw point; those are
re-linked. A locality left on a governorate row with no match would lose the link rather
than keep a wrong one. The prior place_id is kept in attrs (and the versioning
trigger keeps the prior row).

    .venv/bin/python -m ops.relink_depopulated_localities            # dry run
    .venv/bin/python -m ops.relink_depopulated_localities --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect                                              # noqa: E402

PLAN_SQL = """
WITH v AS (
  SELECT e.event_id, e.place_id AS old, p.kind::text AS old_kind, p.name_ar AS old_name,
         lower(e.attrs->>'name') AS n,
         ST_SetSRID(ST_MakePoint((e.attrs->>'raw_lon')::float, (e.attrs->>'raw_lat')::float), 4326)::geography AS pt,
         e.attrs->>'name' AS name
    FROM event e LEFT JOIN place p ON p.place_id = e.place_id
   WHERE e.event_type = 'conflict.village_depopulation' AND e.status = 'believed'
     AND upper_inf(e.sys_period)
     AND COALESCE(p.source_refs->>'source', '') <> 'palopenmaps'
     AND e.attrs ? 'raw_lat'
)
SELECT v.event_id, v.old, v.old_kind, v.old_name, v.name,
       (SELECT array_agg(q.place_id ORDER BY ST_Distance(q.centroid, v.pt))
          FROM place q
         WHERE q.source_refs->>'source' = 'palopenmaps' AND lower(q.name_en) = v.n
           AND q.merged_into IS NULL
           AND ST_DWithin(q.centroid, v.pt, 1500)) AS candidates
  FROM v
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    stats: Counter = Counter()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(PLAN_SQL)
        todo = []
        for eid, old, old_kind, old_name, name, cands in cur.fetchall():
            if cands:
                todo.append((eid, cands[0], old))
                stats["relink"] += 1
            elif old is not None and old_kind == "governorate":
                todo.append((eid, None, old))
                stats["unlink_governorate"] += 1
            else:
                stats["leave"] += 1
                print(f"  leave {eid} {name!r} on {old_kind} {old_name!r}")
        print(dict(stats))
        if not a.apply:
            print("dry run (--apply to write)")
            return 0
        for eid, new, old in todo:
            cur.execute("""UPDATE event SET place_id = %s,
                                  attrs = attrs || jsonb_build_object('place_id_before_relink', %s::bigint,
                                            'relinked_by', 'ops/relink_depopulated_localities 2026-09-25')
                            WHERE event_id = %s""", (new, old, eid))
        conn.commit()
        print(f"wrote {len(todo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
