"""The road register's one human yes: names the reader could not place.

    .venv/bin/python -m ops.road_register                              # the ten most written about
    .venv/bin/python -m ops.road_register --alias "المهلل" 1234         # another name for place 1234
    .venv/bin/python -m ops.road_register --place "المهلل" --lat 31.93 --lon 35.27 --en "Al-Muhallal gate"
    .venv/bin/python -m ops.road_register --place "دير شرف البلد" --anchor 5201     # at that town's centre
    .venv/bin/python -m ops.road_register --place "بوابة المهلل" --anchor 5014 --also "المهلل" "لمهلل"
    .venv/bin/python -m ops.road_register --pin 6901 --lat 31.9512 --lon 35.0381    # the exact point, later
    .venv/bin/python -m ops.road_register --not-a-place "اخر تحديث"
    .venv/bin/python -m ops.road_register --find "طيبه"                 # which rows hold a name

ingest/sources/roads.py counts every name that stands before a status and is
not in the register (road_candidate). A name becomes a place or an alias only
here, by a person: one letter also separates عوريف from صوريف, and a gate needs
a pin that somebody who drives past it can give. v1 kept such a list too —
20,268 names, with promotion switched off, and nothing read it.

Every command writes one decision and the next two-minute tick reads it. A new
place needs a point, because the register does not hold one it cannot put on
the map, and the row says how good the point is (`attrs.geo_precision`):
    --lat/--lon                 hand-pin      somebody looked at a map
    --lat/--lon --approx WHY    approx        worked out, not seen; WHY is kept on the row
    --anchor LOCALITY_ID        approx-anchor the centre of the town it is named after
                                              (migration 081's rule for the board's gates)
`--also` gives the new place its other names in the same breath. `--dry-run`
shows the rows and writes nothing.
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


def add_place(cur, name: str, lat: float | None, lon: float | None, en: str | None,
              anchor: int | None = None, approx: str | None = None,
              also: tuple[str, ...] = ()) -> dict:
    """A new road place: pinned by hand, worked out (`approx`), or put at the
    centre of the locality it is named after (`anchor`)."""
    cur.execute("""SELECT place_id FROM place WHERE kind::text = ANY(%s) AND name_ar = %s
                      AND merged_into IS NULL AND servable""", (list(ROAD_KINDS), name.strip()))
    if cur.fetchone():
        raise SystemExit(f"a road place named «{name.strip()}» already exists")
    if anchor is not None:
        cur.execute("""SELECT place_id, name_ar, admin1_pcode, admin2_pcode, oslo_area,
                              ST_Y(centroid::geometry), ST_X(centroid::geometry), 0
                         FROM place WHERE place_id = %s AND kind = 'locality'
                          AND admin2_pcode IS NOT NULL""", (anchor,))
        near = cur.fetchone()
        if not near:
            raise SystemExit(f"{anchor} is not a locality with a governorate")
        lat, lon = float(near[5]), float(near[6])
        precision, origin = "approx-anchor", "named in the road channels, anchored to its town (ops.road_register)"
    else:
        if lat is None or lon is None:
            raise SystemExit("--place needs --lat and --lon, or --anchor: the register holds no unpinned point")
        if not (31.2 <= lat <= 32.6 and 34.2 <= lon <= 35.6):
            raise SystemExit(f"({lat}, {lon}) is not in the West Bank or Gaza")
        cur.execute("""
            SELECT l.place_id, l.name_ar, l.admin1_pcode, l.admin2_pcode, l.oslo_area, 0, 0,
                   round(ST_Distance(l.centroid, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography))
              FROM place l
             WHERE l.kind = 'locality' AND l.admin2_pcode IS NOT NULL
             ORDER BY l.centroid <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography LIMIT 1""",
            (lon, lat, lon, lat))
        near = cur.fetchone()
        if not near:
            raise SystemExit("no locality to take the governorate from")
        precision = "approx" if approx else "hand-pin"
        origin = ("named in the road channels, located by inference (ops.road_register)" if approx
                  else "named in the road channels, pinned by hand (ops.road_register)")
    attrs = {"geo_precision": precision, "added_by": BY}
    if anchor is not None:
        attrs["anchored_to"] = near[0]
    else:
        attrs.update(nearest_locality=near[0], nearest_locality_m=int(near[7]))
    if approx:
        attrs["located_by"] = approx
    cur.execute("""
        INSERT INTO place (kind, name_ar, name_en, admin1_pcode, admin2_pcode, oslo_area, geom,
                           confidence, source_refs, attrs, servable)
        VALUES ('checkpoint', %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s,
                %s, %s, true)
        RETURNING place_id""",
        (name.strip(), en, near[2], near[3], near[4], lon, lat,
         0.85 if precision == "hand-pin" else 0.8,
         json.dumps({"origin": origin}, ensure_ascii=False),
         json.dumps(attrs, ensure_ascii=False)))
    pid = cur.fetchone()[0]
    decided = _decide(cur, name, "place", pid)
    for a in also:
        cur.execute("""INSERT INTO road_alias (alias, place_id, kind, origin, note)
                       VALUES (%s, %s, 'name', 'weekly-review', NULL)
                       ON CONFLICT (alias, place_id) DO NOTHING""", (a.strip(), pid))
        decided += _decide(cur, a, "alias", pid)
    return {"place_id": pid, "name": name.strip(), "governorate": near[3],
            "geo_precision": precision, "lat": round(lat, 5), "lon": round(lon, 5),
            ("anchored_to" if anchor is not None else "nearest_locality"): near[1],
            "also": list(also), "candidate_rows_decided": decided}


def pin(cur, place_id: int, lat: float, lon: float) -> dict:
    """Move a road place to a point somebody looked at. The old point stays on
    the row (`attrs.geom_before_pin`) so the move can be undone."""
    if not (31.2 <= lat <= 32.6 and 34.2 <= lon <= 35.6):
        raise SystemExit(f"({lat}, {lon}) is not in the West Bank or Gaza")
    cur.execute("""
        UPDATE place p
           SET geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
               attrs = COALESCE(p.attrs, '{}'::jsonb) || jsonb_build_object(
                         'geom_before_pin', ST_AsText(p.geom),
                         'geo_precision_before_pin', p.attrs->>'geo_precision',
                         'geo_precision', 'hand-pin', 'pinned_by', %s::text),
               updated_at = now()
         WHERE p.place_id = %s AND p.kind::text = ANY(%s)
        RETURNING name_ar, attrs->>'geom_before_pin',
                  round(ST_Distance(ST_GeomFromText(attrs->>'geom_before_pin', 4326)::geography,
                                    p.geom::geography))""",
        (lon, lat, BY, place_id, list(ROAD_KINDS)))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"place {place_id} is not a road place")
    return {"place_id": place_id, "name": row[0], "moved_from": row[1], "metres_moved": int(row[2])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--alias", nargs=2, metavar=("NAME", "PLACE_ID"))
    ap.add_argument("--weak", action="store_true",
                    help="with --alias: the name is also an ordinary word, read only after a road word")
    ap.add_argument("--place", metavar="NAME")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--en")
    ap.add_argument("--anchor", type=int, metavar="LOCALITY_ID",
                    help="with --place: put it at the centre of this locality (approx-anchor)")
    ap.add_argument("--approx", metavar="WHY",
                    help="with --place --lat --lon: the point was worked out, not seen; say how")
    ap.add_argument("--also", nargs="+", default=[], metavar="ALIAS",
                    help="with --place: other names for the new place")
    ap.add_argument("--pin", type=int, metavar="PLACE_ID",
                    help="with --lat --lon: move an existing road place to a point you looked at")
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
        if a.pin:
            if a.lat is None or a.lon is None:
                raise SystemExit("--pin needs --lat and --lon")
            out = pin(cur, a.pin, a.lat, a.lon)
        elif a.alias:
            out = add_alias(cur, a.alias[0], int(a.alias[1]), "weak" if a.weak else "name")
        elif a.place:
            out = add_place(cur, a.place, a.lat, a.lon, a.en, a.anchor, a.approx, tuple(a.also))
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
            if a.alias or a.place:
                print("  its past is still unread: .venv/bin/python -m ingest.sources.roads "
                      "--reread --since 2026-07-31   (once, after the last decision)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
