"""P1.3 — fuel station registry from OpenStreetMap via Overpass.

Creates `place.kind='station'` rows for every fuel station in the West Bank and
Gaza. These are the entities the Phase 1 product answers about: "which station
has diesel right now".

Filtering is done in PostGIS against the admin polygons already loaded in
P0.14 rather than by bounding box — the WB/Gaza bbox unavoidably includes a
large slice of Israel, and a station registry that silently includes Israeli
stations would be both wrong and, for a routing product, dangerous.

Run:  .venv/bin/python -m ingest.sources.osm_fuel
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ingest.framework import BaseFetcher, SkipRun
from resolve.arabic import fold, is_generic_alias, normalize, variants
from resolve.db import connect

OVERPASS = "https://overpass-api.de/api/interpreter"

# Generous bbox over WB + Gaza; PostGIS does the real filtering.
BBOX = "31.20,34.15,32.60,35.60"
QUERY = f"""
[out:json][timeout:180];
(
  node["amenity"="fuel"]({BBOX});
  way["amenity"="fuel"]({BBOX});
);
out center tags;
"""


class OsmFuelStations(BaseFetcher):
    key = "osm_fuel_stations"

    def fetch(self):
        # Overpass 406s on a bare GET; POST with the query as a form field is
        # the documented interface.
        r = self.http_post(OVERPASS, data={"data": QUERY}, timeout=180.0)
        if r.status_code != 200:
            raise RuntimeError(f"overpass returned HTTP {r.status_code}")
        body = r.text
        self.archive(body, "json", url=OVERPASS)
        doc = json.loads(body)

        out = []
        for el in doc.get("elements", []):
            tags = el.get("tags") or {}
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            if lat is None or lon is None:
                continue
            out.append({
                "osm_type": el.get("type"),
                "osm_id": el.get("id"),
                "lat": lat,
                "lon": lon,
                "name_ar": tags.get("name:ar") or (tags.get("name") if _is_ar(tags.get("name")) else None),
                "name_en": tags.get("name:en") or (tags.get("name") if not _is_ar(tags.get("name")) else None),
                "brand": tags.get("brand") or tags.get("operator"),
                # Which commodities OSM claims this station sells. Useful as a
                # prior, but never as evidence of what is in the tank today.
                "diesel": tags.get("fuel:diesel"),
                "octane_95": tags.get("fuel:octane_95"),
                "lpg": tags.get("fuel:lpg"),
                "tags": tags,
            })
        return out


def _is_ar(s: str | None) -> bool:
    return bool(s) and any("؀" <= c <= "ۿ" for c in s)


def load(records) -> dict:
    """Insert stations that fall inside PS01/PS02, with aliases."""
    stats = {"seen": len(records), "inserted": 0, "outside": 0, "aliases": 0, "unnamed": 0}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO source (key,name,kind,license_spdx,commercial_use,attribution_text,authority_rank)
            VALUES ('osm_fuel_stations','OpenStreetMap fuel stations','api','ODbL-1.0',true,
                    '© OpenStreetMap contributors',2)
            ON CONFLICT (key) DO NOTHING""")

        for r in records:
            # Inside Palestine? Ask the admin polygons, not the bbox.
            cur.execute("""
                SELECT admin1_pcode, admin2_pcode FROM place
                WHERE kind IN ('region','governorate')
                  AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(%s,%s),4326))
                ORDER BY ST_Area(geom) ASC LIMIT 1""", (r["lon"], r["lat"]))
            row = cur.fetchone()
            if not row:
                stats["outside"] += 1
                continue
            a1, a2 = row

            if not (r["name_ar"] or r["name_en"]):
                # Unnamed stations still matter: a message can say "the station
                # at Barqa" and resolve by proximity even with no OSM name.
                stats["unnamed"] += 1
                r["name_en"] = f"Fuel station (OSM {r['osm_id']})"

            cur.execute("""
                INSERT INTO place (kind,name_en,name_ar,admin1_pcode,admin2_pcode,geom,source_refs,confidence,attrs)
                VALUES ('station',%s,%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326), %s, 0.8, %s)
                RETURNING place_id""",
                (r["name_en"], r["name_ar"], a1, a2, r["lon"], r["lat"],
                 json.dumps({"osm_id": r["osm_id"], "osm_type": r["osm_type"],
                             "source": "osm_fuel_stations"}),
                 json.dumps({k: v for k, v in {
                     "brand": r["brand"], "fuel:diesel": r["diesel"],
                     "fuel:octane_95": r["octane_95"], "fuel:lpg": r["lpg"]}.items() if v})))
            pid = cur.fetchone()[0]
            stats["inserted"] += 1

            # Aliases: names, brand, and the colloquial "كازية <name>" /
            # "محطة <name>" forms people actually type.
            names = [n for n in (r["name_ar"], r["name_en"], r["brand"]) if n]
            for base in list(names):
                if _is_ar(base):
                    names += [f"كازية {base}", f"محطة {base}", f"محطة محروقات {base}"]
            for name in names:
                for key in variants(name):
                    if not key or len(key) < 2 or is_generic_alias(key):
                        continue
                    cur.execute("""
                        INSERT INTO place_alias (alias_norm, place_id, confidence, origin)
                        VALUES (%s,%s,0.75,'osm') ON CONFLICT (alias_norm) DO NOTHING""",
                                (key, pid))
                    stats["aliases"] += cur.rowcount
        conn.commit()
    return stats


def main() -> int:
    f = OsmFuelStations()
    res = f.run()
    print(f"fetch: {res.status.value} records={res.records} {res.reason or ''}")
    if res.status.value != "ok":
        return 1
    stats = load(f.records)
    print(f"load : inserted={stats['inserted']} outside_palestine={stats['outside']} "
          f"unnamed={stats['unnamed']} aliases={stats['aliases']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
