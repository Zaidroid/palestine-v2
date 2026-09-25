"""Populate place_closure — the containment nothing could previously query.

Three kinds of edge, each recording HOW it was proven, because "this locality
is in Hebron because its pcode says so" and "…because its point falls inside
Hebron's polygon" are different strengths of claim and a rollup built on the
second deserves to say so.

  pcode              an authority-issued admin2 code. The strongest.
  st_contains        the locality's point falls inside a governorate polygon.
  mandate_gazetteer  Palestine Open Maps' own district_1945 /
                     subdistrict_1945 fields, corrected against the 1945
                     Village Statistics where the source disagrees with
                     itself (it files Jenin and Nablus as districts; both are
                     sub-districts of Samaria).

THE TWO GEOGRAPHIES NEVER MIX. `relation` is 'modern' or 'mandate' and a
rollup must pick one: Safad sub-district and Jenin governorate are not
comparable containers, and summing a locality into both would double-count
it. The gates assert no place has ancestors of both kinds at the same depth.

Run:  .venv/bin/python -m ops.build_place_closure           # measure
      .venv/bin/python -m ops.build_place_closure --apply

--apply REBUILDS the modern relation, it does not append to it. Every edge was
`ON CONFLICT DO NOTHING` and nothing ever deleted one, so an edge proven from a
code migration 077 later re-coded (v1's PS0105 = Qalqilya joined OCHA's PS0105
= Tubas, as 'pcode', the strongest claim in the table) survived every re-run,
and a re-run added the correct parent beside it (F313, 2026-09-25). The modern
edges are derived from `place` and nothing else, so they are deleted and
re-derived in ONE transaction, which commits only if the gates below hold. The
Mandate edges come from a fixed 1945 crosswalk and are left as they are.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect                                   # noqa: E402

EDGES = {
    # governorate -> locality, by the locality's own admin2 code
    "modern_pcode": ("""
        INSERT INTO place_closure
            (ancestor_id, descendant_id, depth, relation, established_by)
        SELECT g.place_id, l.place_id, 1, 'modern', 'pcode'
        FROM place l JOIN place g
          ON g.kind = 'governorate' AND g.admin2_pcode = l.admin2_pcode
         AND g.merged_into IS NULL
        WHERE l.kind = 'locality' AND l.merged_into IS NULL
          AND l.admin2_pcode IS NOT NULL AND l.place_id <> g.place_id
          -- Servable only, as for st_contains below. Since 077 a
          -- NON-servable reference row inside a polygon carries that polygon's
          -- code too (077 re-coded every kind but the admin ones), so without
          -- this the pcode edge gave ~2,000 Mandate reference rows a modern
          -- parent — the G4.11 double-count 062 caught once already (F313).
          AND l.servable
        ON CONFLICT DO NOTHING"""),

    # governorate -> locality, by geometry, for the ones with no code. Only
    # where the point actually falls inside; nothing is nearest-matched.
    "modern_contains": ("""
        INSERT INTO place_closure
            (ancestor_id, descendant_id, depth, relation, established_by)
        SELECT g.place_id, l.place_id, 1, 'modern', 'st_contains'
        FROM place l JOIN place g
          ON g.kind = 'governorate' AND g.merged_into IS NULL
         AND ST_Contains(g.geom::geometry, l.geom::geometry)
        WHERE l.kind = 'locality' AND l.merged_into IS NULL
          AND l.admin2_pcode IS NULL AND l.geom IS NOT NULL
          AND ST_GeometryType(l.geom::geometry) = 'ST_Point'
          -- THE MODERN HIERARCHY CONTAINS ONLY SERVABLE PLACES. A
          -- depopulated 1948 village inside today's Hebron governorate is
          -- geographically inside it, and putting that edge in the closure
          -- would let "population of Hebron governorate" quietly include
          -- 1945 village figures. Gate G4.11 caught exactly this: 843
          -- Mandate reference rows had acquired a modern parent. `servable`
          -- is the line the rest of the system already draws, so it is the
          -- line here too.
          AND l.servable
        ON CONFLICT DO NOTHING"""),

    # region -> governorate
    "modern_region": ("""
        INSERT INTO place_closure
            (ancestor_id, descendant_id, depth, relation, established_by)
        SELECT r.place_id, g.place_id, 1, 'modern', 'pcode'
        FROM place g JOIN place r
          ON r.kind = 'region' AND r.admin1_pcode = g.admin1_pcode
         AND r.merged_into IS NULL
        WHERE g.kind = 'governorate' AND g.merged_into IS NULL
        ON CONFLICT DO NOTHING"""),

    # region -> locality, the transitive edge, so a national rollup does not
    # have to walk two hops
    "modern_transitive": ("""
        INSERT INTO place_closure
            (ancestor_id, descendant_id, depth, relation, established_by)
        SELECT a.ancestor_id, b.descendant_id, 2, 'modern', a.established_by
        FROM place_closure a JOIN place_closure b
          ON b.ancestor_id = a.descendant_id
        WHERE a.relation = 'modern' AND b.relation = 'modern'
          AND a.depth = 1 AND b.depth = 1
        ON CONFLICT DO NOTHING"""),

    # sub-district -> Mandate locality, from Palestine Open Maps' own fields
    "mandate": ("""
        INSERT INTO place_closure
            (ancestor_id, descendant_id, depth, relation, established_by)
        SELECT d.place_id, l.place_id, 1, 'mandate', 'mandate_gazetteer'
        FROM place l JOIN place d
          ON d.kind = 'district_mandate'
         AND d.name_en = l.attrs->>'subdistrict_1945'
        WHERE l.attrs->>'historic' = 'mandate-palestine'
          AND l.kind = 'locality' AND l.merged_into IS NULL
        ON CONFLICT DO NOTHING"""),
}


# The two things a rebuilt closure must never hold. G4.11 is the gate in
# tests/test_gate4_history.sql; the second one it did not check: a locality
# with two modern parents at depth 1 is counted in two governorates.
GATES = {
    "two_modern_parents": """
        SELECT count(*) FROM (SELECT descendant_id FROM place_closure
                               WHERE relation = 'modern' AND depth = 1
                               GROUP BY 1 HAVING count(*) > 1) x""",
    "both_geographies": """
        SELECT count(*) FROM (SELECT descendant_id FROM place_closure
                               WHERE depth = 1 GROUP BY 1
                              HAVING count(DISTINCT relation) > 1) x""",
}


def rebuild(cur) -> dict:
    """Delete and re-derive the modern edges, append the Mandate ones, and
    measure the gates. The caller commits only when every gate is zero."""
    cur.execute("DELETE FROM place_closure WHERE relation = 'modern'")
    out = {"modern_deleted": cur.rowcount}
    for name, sql in EDGES.items():
        cur.execute(sql)
        out[name] = cur.rowcount
    for name, sql in GATES.items():
        cur.execute(sql)
        out[name] = cur.fetchone()[0]
    return out


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    with connect() as conn, conn.cursor() as cur:
        if apply:
            got = rebuild(cur)
            for name, n in got.items():
                print(f"  {name:<20} {n}")
            broken = {g: got[g] for g in GATES if got[g]}
            if broken:
                conn.rollback()
                print(f"\n  NOT COMMITTED — gate(s) failed: {broken}")
                return 1
            conn.commit()

        cur.execute("""SELECT relation, established_by, depth, count(*)
                       FROM place_closure GROUP BY 1,2,3 ORDER BY 1,3,2""")
        print(f"\n  {'relation':<10}{'established_by':<20}{'depth':>6}{'edges':>8}")
        for r, e, d, n in cur.fetchall():
            print(f"  {r:<10}{e:<20}{d:>6}{n:>8}")

        # What is STILL unreachable is the finding, and it is stated rather
        # than left as the absence of a row.
        cur.execute("""
            SELECT count(*) FROM place l
            WHERE l.kind = 'locality' AND l.merged_into IS NULL
              AND NOT EXISTS (SELECT 1 FROM place_closure c
                              WHERE c.descendant_id = l.place_id)""")
        orphan = cur.fetchone()[0]
        cur.execute("""
            SELECT count(*) FROM observation o
            JOIN dataset d USING (dataset_id)
            WHERE d.v1_category = 'historical' AND upper_inf(o.sys_period)
              AND o.occurred_at < '1948-01-01'
              AND EXISTS (SELECT 1 FROM place_closure c
                          WHERE c.descendant_id = o.place_id
                            AND c.relation = 'mandate')""")
        pre48 = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM observation o
                       JOIN dataset d USING (dataset_id)
                       WHERE d.v1_category='historical'
                         AND upper_inf(o.sys_period)
                         AND o.occurred_at < '1948-01-01'""")
        pre48_total = cur.fetchone()[0]

    print(f"\n  {orphan} locality(ies) still in no container — stated, not "
          "hidden: a locality with no parent is one no rollup can reach")
    print(f"  {pre48}/{pre48_total} pre-1948 observations now roll up to a "
          "1945 sub-district")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
