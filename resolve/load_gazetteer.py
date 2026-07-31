"""P0.14–P0.17 — build the gazetteer.

Sources, in authority order (later loads never overwrite an earlier place, they
only add aliases):

  P0.14  OCHA admin1/admin2 boundaries + Oslo areas   (polygons, pcodes)
  P0.15  v1 known_locations.json — 1,446 localities   (points, ar/en, aliases)
  P0.16  v1 checkpoints.db — 403 checkpoints          (points, canonical_key)
  P0.17  alias seeding from all of the above

All v1 paths are opened READ-ONLY. Nothing is written outside the v2 database.

Run:  .venv/bin/python resolve/load_gazetteer.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from resolve.arabic import fold, is_generic_alias, normalize, variants
from resolve.db import connect

V1_ADMIN = Path("/opt/stacks/palestine/services/westbank-alerts/data/admin")
V1_DATA = Path("/opt/stacks/palestine/services/westbank-alerts/data")

# The 16 governorates, Arabic names keyed by OCHA pcode. The OCHA file carries
# adm2_name only in English (adm2_name1..3 are all NULL), so Arabic has to come
# from somewhere — these are stable, official, and small enough to state.
GOV_AR = {
    "PS0101": "جنين", "PS0102": "طوباس", "PS0103": "طولكرم", "PS0104": "نابلس",
    "PS0105": "قلقيلية", "PS0106": "سلفيت", "PS0107": "رام الله والبيرة",
    "PS0108": "أريحا والأغوار", "PS0109": "القدس", "PS0110": "بيت لحم",
    "PS0111": "الخليل", "PS0201": "شمال غزة", "PS0202": "غزة",
    "PS0203": "دير البلح", "PS0204": "خان يونس", "PS0205": "رفح",
}
ADM1_AR = {"PS01": "الضفة الغربية", "PS02": "قطاع غزة"}

# Oslo CLASS -> our oslo_area domain. Unmapped classes are informational only.
OSLO_MAP = {"A": "A", "B": "B", "C": "C", "H1": "H1", "H2": "H2",
            "Israeli Declared East Jerusalem": "seam", "No Man's Land": "seam"}


def _src(cur, key, name, kind, spdx, commercial, attribution, rank) -> int:
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,attribution_text,authority_rank)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name
        RETURNING source_id""", (key, name, kind, spdx, commercial, attribution, rank))
    return cur.fetchone()[0]


def _add_aliases(cur, place_id: int, names, origin: str, confidence: float) -> int:
    """Insert alias keys for a place. First writer wins — a later, lower-authority
    source must never steal an alias that already points somewhere else."""
    n = 0
    seen = set()
    for name in names:
        for key in variants(name):
            # A generic key would match every phrase containing the plain noun.
            # Length is NOT filtered here — short real names (Jit, Kur, غزه)
            # must stay exact-matchable; containment applies its own floor.
            if not key or len(key) < 2 or key in seen or is_generic_alias(key):
                continue
            seen.add(key)
            cur.execute("""
                INSERT INTO place_alias (alias_norm, place_id, confidence, origin)
                VALUES (%s,%s,%s,%s) ON CONFLICT (alias_norm) DO NOTHING""",
                        (key, place_id, confidence, origin))
            n += cur.rowcount
    return n


# ── P0.14 ────────────────────────────────────────────────────────────────────
def load_admin(cur) -> tuple[int, int]:
    sid = _src(cur, "ocha_admin", "OCHA oPt administrative boundaries", "file",
               "CC-BY-3.0-IGO", True, "UN OCHA oPt", 4)
    places = aliases = 0

    for level, fname in (("admin1", "admin1.geojson"), ("admin2", "admin2.geojson")):
        doc = json.loads((V1_ADMIN / fname).read_text())
        for feat in doc["features"]:
            p = feat["properties"]
            if level == "admin1":
                pcode, name_en = p["adm1_pcode"], p["adm1_name"]
                name_ar, kind, a1, a2 = ADM1_AR.get(pcode), "region", pcode, None
            else:
                pcode, name_en = p["adm2_pcode"], p["adm2_name"]
                name_ar, kind, a1, a2 = GOV_AR.get(pcode), "governorate", p["adm1_pcode"], pcode

            cur.execute("""
                INSERT INTO place (kind,name_en,name_ar,admin1_pcode,admin2_pcode,geom,source_refs,confidence)
                VALUES (%s,%s,%s,%s,%s, ST_GeomFromGeoJSON(%s), %s, 1.0)
                RETURNING place_id""",
                        (kind, name_en, name_ar, a1, a2, json.dumps(feat["geometry"]),
                         json.dumps({"ocha_pcode": pcode, "source": "ocha_admin"})))
            pid = cur.fetchone()[0]
            places += 1
            aliases += _add_aliases(cur, pid, [n for n in (name_ar, name_en) if n], "ocha", 0.95)

    # Oslo areas are attributes of geography, not places — stamp them onto the
    # admin polygons rather than creating rows nobody would ever look up.
    oslo = json.loads((V1_ADMIN / "oslo.geojson").read_text())
    for feat in oslo["features"]:
        cls = OSLO_MAP.get(feat["properties"].get("CLASS"))
        if not cls:
            continue
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS _oslo (cls text, geom geometry(Geometry,4326))""")
        cur.execute("INSERT INTO _oslo VALUES (%s, ST_GeomFromGeoJSON(%s))",
                    (cls, json.dumps(feat["geometry"])))
    return places, aliases


def stamp_oslo(cur) -> int:
    """Assign oslo_area to any place whose centroid falls inside an Oslo polygon.
    Runs after all point loads so localities and checkpoints get stamped too."""
    cur.execute("""
        UPDATE place p SET oslo_area = o.cls
        FROM (SELECT DISTINCT ON (p2.place_id) p2.place_id, _oslo.cls
              FROM place p2 JOIN _oslo
                ON ST_Contains(_oslo.geom, (p2.centroid)::geometry)
              ORDER BY p2.place_id, ST_Area(_oslo.geom) ASC) o
        WHERE p.place_id = o.place_id AND p.oslo_area IS NULL""")
    return cur.rowcount


# ── P0.15 ────────────────────────────────────────────────────────────────────
def load_localities(cur) -> tuple[int, int]:
    sid = _src(cur, "v1_known_locations", "v1 known_locations registry", "file",
               "NONE", True, "Palestine Data Backend v1", 3)
    rows = json.loads((V1_DATA / "known_locations.json").read_text())
    places = aliases = 0

    # Governorate name -> admin2_pcode, so localities inherit a real pcode.
    gov_to_pcode = {normalize(v): k for k, v in GOV_AR.items()}
    gov_slug = {  # v1 uses slugs, not Arabic names
        "jenin": "PS0101", "tubas": "PS0102", "tulkarm": "PS0103", "nablus": "PS0104",
        "qalqilya": "PS0105", "salfit": "PS0106", "ramallah": "PS0107",
        "jericho": "PS0108", "jerusalem": "PS0109", "bethlehem": "PS0110",
        "hebron": "PS0111", "north_gaza": "PS0201", "gaza": "PS0202",
        "deir_al_balah": "PS0203", "khan_younis": "PS0204", "rafah": "PS0205",
    }

    for r in rows:
        lat, lon = r.get("latitude"), r.get("longitude")
        if lat is None or lon is None:
            continue
        pcode = gov_slug.get((r.get("governorate") or "").lower()) \
            or gov_to_pcode.get(normalize(r.get("governorate")))
        cur.execute("""
            INSERT INTO place (kind,name_en,name_ar,admin1_pcode,admin2_pcode,geom,source_refs,confidence)
            VALUES ('locality',%s,%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326), %s, 0.9)
            RETURNING place_id""",
                    (r.get("name_en"), r.get("name_ar"),
                     ("PS02" if (pcode or "").startswith("PS02") else "PS01") if pcode else None,
                     pcode, lon, lat,
                     json.dumps({"v1_canonical_key": r["canonical_key"],
                                 "zone": r.get("zone"), "source": "v1_known_locations"})))
        pid = cur.fetchone()[0]
        places += 1
        names = [n for n in (r.get("name_ar"), r.get("name_en")) if n]
        names += list(r.get("aliases") or [])
        names.append(r["canonical_key"].replace("_", " "))
        aliases += _add_aliases(cur, pid, names, "pcbs", 0.85)
    return places, aliases


# ── P0.16 ────────────────────────────────────────────────────────────────────
def load_checkpoints(cur) -> tuple[int, int]:
    sid = _src(cur, "v1_checkpoints", "v1 checkpoint registry", "file",
               "NONE", True, "Palestine Data Backend v1", 3)
    # READ-ONLY connection to production. immutable=1 prevents any write or
    # journal creation even if something below misbehaves.
    db = sqlite3.connect(f"file:{V1_DATA/'checkpoints.db'}?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    places = aliases = 0

    kindmap = {"checkpoint": "checkpoint", "gate": "checkpoint", "crossing": "crossing",
               "bridge": "road", "roundabout": "road", "traffic_signal": "road"}

    for r in db.execute("""SELECT canonical_key,name_ar,name_en,latitude,longitude,
                                  checkpoint_type,governorate,oslo_area
                           FROM checkpoints"""):
        if r["latitude"] is None or r["longitude"] is None:
            continue   # 29 of 403 have no coords; they cannot be a place yet
        cur.execute("""
            INSERT INTO place (kind,name_en,name_ar,oslo_area,geom,source_refs,confidence)
            VALUES (%s,%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326), %s, 0.85)
            RETURNING place_id""",
                    (kindmap.get(r["checkpoint_type"], "checkpoint"),
                     r["name_en"], r["name_ar"],
                     r["oslo_area"] if r["oslo_area"] in OSLO_MAP.values() else None,
                     r["longitude"], r["latitude"],
                     json.dumps({"v1_canonical_key": r["canonical_key"],
                                 "checkpoint_type": r["checkpoint_type"],
                                 "source": "v1_checkpoints"})))
        pid = cur.fetchone()[0]
        places += 1
        names = [n for n in (r["name_ar"], r["name_en"]) if n]
        names.append(r["canonical_key"].replace("_", " "))
        aliases += _add_aliases(cur, pid, names, "checkpoint_db", 0.9)
    db.close()
    return places, aliases


def main() -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM place")
        if cur.fetchone()[0]:
            print("gazetteer already populated — truncating for a clean rebuild")
            cur.execute("TRUNCATE place, place_alias RESTART IDENTITY CASCADE")

        a_p, a_a = load_admin(cur);        print(f"P0.14 admin      {a_p:>6} places  {a_a:>6} aliases")
        l_p, l_a = load_localities(cur);   print(f"P0.15 localities {l_p:>6} places  {l_a:>6} aliases")
        c_p, c_a = load_checkpoints(cur);  print(f"P0.16 checkpoints{c_p:>6} places  {c_a:>6} aliases")
        n = stamp_oslo(cur);               print(f"      oslo stamped {n} places")
        conn.commit()

        cur.execute("SELECT kind, count(*) FROM place GROUP BY 1 ORDER BY 2 DESC")
        print("\nplaces by kind:")
        for kind, n in cur.fetchall():
            print(f"  {kind:<14}{n:>6}")
        cur.execute("SELECT count(*) FROM place_alias")
        print(f"\ntotal aliases: {cur.fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
