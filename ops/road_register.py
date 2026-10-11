"""The road register's one human yes: names the reader could not place.

    .venv/bin/python -m ops.road_register                              # the ten most written about
    .venv/bin/python -m ops.road_register --alias "المهلل" 1234         # another name for place 1234
    .venv/bin/python -m ops.road_register --place "المهلل" --lat 31.93 --lon 35.27 --en "Al-Muhallal gate"
    .venv/bin/python -m ops.road_register --not-a-place "اخر تحديث"
    .venv/bin/python -m ops.road_register --find "طيبه"                 # which rows hold a name

ingest/sources/roads.py counts every name that stands before a status and is
not in the register (road_candidate). A name becomes a place or an alias only
here, by a person: one letter also separates عوريف from صوريف, and a gate needs
a pin that somebody who drives past it can give. v1 kept such a list too —
20,268 names, with promotion switched off, and nothing read it.

Every command writes one decision and the next two-minute tick reads it. A new
place needs coordinates: the register does not hold a point it cannot put on
the map. `--dry-run` shows the rows and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect  # noqa: E402
from resolve.road_names import ROAD_KINDS, key_of  # noqa: E402

BY = "ops.road_register"


def _key(name: str) -> str:
    return " ".join(key_of(name))


def find(cur, name: str) -> list[tuple]:
    """Road places whose name, alias or board name contains `name`."""
    cur.execute("""
        SELECT p.place_id, p.name_ar, p.name_en, p.admin2_pcode, p.servable, p.merged_into
          FROM place p
         WHERE p.kind::text = ANY(%s)
           AND (p.name_ar ILIKE %s OR p.name_en ILIKE %s
                OR EXISTS (SELECT 1 FROM road_alias a WHERE a.place_id = p.place_id AND a.alias ILIKE %s))
         ORDER BY p.servable DESC, p.place_id""",
        (list(ROAD_KINDS), f"%{name}%", f"%{name}%", f"%{name}%"))
    return cur.fetchall()


def _decide(cur, name: str, status: str, place_id: int | None) -> int:
    cur.execute("""UPDATE road_candidate SET status = %s, place_id = %s, decided_at = now(),
                          decided_by = %s
                    WHERE name_norm = %s""", (status, place_id, BY, _key(name)))
    return cur.rowcount


def add_alias(cur, name: str, place_id: int, kind: str = "name") -> dict:
    cur.execute("""SELECT coalesce(merged_into, place_id), name_ar, servable OR merged_into IS NOT NULL
                     FROM place WHERE place_id = %s AND kind::text = ANY(%s)""",
                (place_id, list(ROAD_KINDS)))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"place {place_id} is not a road place")
    target, name_ar, live = row
    if not live:
        raise SystemExit(f"place {place_id} ({name_ar}) is hidden: a name cannot point at it")
    cur.execute("""INSERT INTO road_alias (alias, place_id, kind, origin, note)
                   VALUES (%s, %s, %s, 'weekly-review', NULL)
                   ON CONFLICT (alias, place_id) DO NOTHING""", (name.strip(), target, kind))
    return {"alias": name.strip(), "place_id": target, "place": name_ar,
            "candidate_rows_decided": _decide(cur, name, "alias", target)}


def add_place(cur, name: str, lat: float, lon: float, en: str | None) -> dict:
    if not (31.2 <= lat <= 32.6 and 34.2 <= lon <= 35.6):
        raise SystemExit(f"({lat}, {lon}) is not in the West Bank or Gaza")
    cur.execute("""
        SELECT l.place_id, l.name_ar, l.admin1_pcode, l.admin2_pcode, l.oslo_area,
               round(ST_Distance(l.centroid, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography))
          FROM place l
         WHERE l.kind = 'locality' AND l.admin2_pcode IS NOT NULL
         ORDER BY l.centroid <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography LIMIT 1""",
        (lon, lat, lon, lat))
    near = cur.fetchone()
    if not near:
        raise SystemExit("no locality to take the governorate from")
    cur.execute("""
        INSERT INTO place (kind, name_ar, name_en, admin1_pcode, admin2_pcode, oslo_area, geom,
                           confidence, source_refs, attrs, servable)
        VALUES ('checkpoint', %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), 0.85,
                %s, %s, true)
        RETURNING place_id""",
        (name.strip(), en, near[2], near[3], near[4], lon, lat,
         json.dumps({"origin": "named in the road channels, pinned by hand (ops.road_register)"}),
         json.dumps({"geo_precision": "hand-pin", "nearest_locality": near[0],
                     "nearest_locality_m": int(near[5]), "added_by": BY}, ensure_ascii=False)))
    pid = cur.fetchone()[0]
    return {"place_id": pid, "name": name.strip(), "governorate": near[3],
            "nearest_locality": near[1], "metres_from_it": int(near[5]),
            "candidate_rows_decided": _decide(cur, name, "place", pid)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--alias", nargs=2, metavar=("NAME", "PLACE_ID"))
    ap.add_argument("--weak", action="store_true",
                    help="with --alias: the name is also an ordinary word, read only after a road word")
    ap.add_argument("--place", metavar="NAME")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--en")
    ap.add_argument("--not-a-place", metavar="NAME")
    ap.add_argument("--find", metavar="NAME")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('road_candidate') IS NOT NULL")
        if not cur.fetchone()[0]:
            print("the register's tables are not there yet: apply migration 097 first")
            return 1
        if a.find:
            for pid, ar, en, gov, servable, merged in find(cur, a.find):
                state = f"merged into {merged}" if merged else ("" if servable else "hidden")
                print(f"{pid:6}  {ar or '':28} {en or '':32} {gov or '':8} {state}")
            return 0
        if a.alias:
            out = add_alias(cur, a.alias[0], int(a.alias[1]), "weak" if a.weak else "name")
        elif a.place:
            if a.lat is None or a.lon is None:
                raise SystemExit("--place needs --lat and --lon: the register holds no unpinned point")
            out = add_place(cur, a.place, a.lat, a.lon, a.en)
        elif a.not_a_place:
            out = {"name": a.not_a_place,
                   "candidate_rows_decided": _decide(cur, a.not_a_place, "not_a_place", None)}
        else:
            cur.execute("""
                SELECT surface, mentions, array_length(channels, 1), last_seen::date, example
                  FROM road_candidate
                 WHERE status = 'pending' AND last_seen > now() - interval '30 days'
                 ORDER BY mentions DESC LIMIT %s""", (a.limit,))
            rows = cur.fetchall()
            if not rows:
                print("nothing waiting")
            for surface, n, chans, last, example in rows:
                line = example.replace("\n", " ⏎ ")[:70]
                print(f"{n:5}  {surface:26} {chans} channel(s), last {last}   «{line}»")
            return 0
        if a.dry_run:
            conn.rollback()
            print("dry run, nothing written:", json.dumps(out, ensure_ascii=False))
        else:
            conn.commit()
            print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
