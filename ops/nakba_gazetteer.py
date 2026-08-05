"""The Nakba gazetteer — Mandate-era localities become place rows (T2 close).

Zaid delegated the call (2026-08-05): historical's 2,424 Palestine Open Maps
localities — coordinates, Arabic names, 1945 districts, depopulation status,
Zochrot / PalestineRemembered cross-references — enter the `place` table as
**servable=false** reference rows. That flag is the whole design:

  - historical joins work: the migrated censuses and depopulation records
    resolve from 33% to ~99%, and a map of destroyed villages is one query;
  - live capture cannot touch them: resolve/geo.py's name path filters
    `AND servable`, the alias path never sees them (no aliases are created),
    and the crowd/checkpoint surfaces filter servable already. A report
    naming طنطورة today resolves exactly as it did yesterday.

Post-1948 'New locality' rows (locality_group='Jewish', recorded by POM for
contrast) are included with their group visible in attrs — the gazetteer
states what its sources state; `servable=false` means v2 never serves them
as Palestinian places, and the group is queryable for anyone drawing maps.

Idempotent: keyed on source_refs->>'v1_canonical_key'. Read-only on v1.

Run: .venv/bin/python -m ops.nakba_gazetteer
"""
from __future__ import annotations

import json
from pathlib import Path

from resolve.db import connect

V1_HIST = Path("/opt/stacks/palestine/public/data/unified/historical/all-data.json")


def main() -> None:
    recs = json.loads(V1_HIST.read_text())["data"]
    pom = [r for r in recs
           if (r.get("sources") or [{}])[0].get("name") == "Palestine Open Maps"]

    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT source_refs->>'v1_canonical_key' FROM place
                       WHERE source_refs ? 'v1_canonical_key'""")
        existing = {r[0] for r in cur.fetchall()}

        created = skipped_existing = skipped_nogeom = 0
        for r in pom:
            loc = r.get("location") or {}
            key = loc.get("gazetteer_key")
            if not key or key in existing:
                skipped_existing += 1
                continue
            lat, lon = loc.get("lat"), loc.get("lon")
            if lat is None or lon is None:
                skipped_nogeom += 1
                continue
            existing.add(key)
            attrs = {
                "historic": "mandate-palestine",
                "locality_group": r.get("locality_group"),
                "locality_status": r.get("locality_status"),
                "district_1945": r.get("district_1945"),
                "subdistrict_1945": r.get("subdistrict_1945"),
            }
            xrefs = r.get("cross_references") or {}
            attrs.update({k: v for k, v in xrefs.items() if v})
            cur.execute("""
                INSERT INTO place (kind, name_en, name_ar, geom, servable,
                                   confidence, source_refs, attrs)
                VALUES ('locality', %s, %s,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326), false,
                        0.8, %s, %s)""",
                (loc.get("name"), loc.get("name_ar"), lon, lat,
                 json.dumps({"v1_canonical_key": key,
                             "source": "palopenmaps"}),
                 json.dumps({k: v for k, v in attrs.items() if v},
                            ensure_ascii=False)))
            created += 1

        # re-point the migrated rows that could not resolve before
        cur.execute("""
            UPDATE observation o
               SET place_id = p.place_id
              FROM dataset d, place p
             WHERE d.dataset_id = o.dataset_id
               AND d.v1_category = 'historical'
               AND o.place_id IS NULL
               AND o.attrs ? 'gazetteer_key'
               AND p.source_refs->>'v1_canonical_key' = o.attrs->>'gazetteer_key'""")
        obs_linked = cur.rowcount
        cur.execute("""
            UPDATE event e
               SET place_id = p.place_id
              FROM place p
             WHERE e.attrs ? 'v1_stable_id'
               AND e.place_id IS NULL
               AND e.attrs ? 'gazetteer_key'
               AND p.source_refs->>'v1_canonical_key' = e.attrs->>'gazetteer_key'""")
        ev_linked = cur.rowcount
        cur.execute("""SELECT count(*), count(place_id) FROM observation o
                       JOIN dataset d ON d.dataset_id=o.dataset_id
                       WHERE d.v1_category='historical'""")
        total, placed = cur.fetchone()
        conn.commit()

    print(f"nakba gazetteer: {created} places created, "
          f"{skipped_existing} already known, {skipped_nogeom} without geometry; "
          f"{obs_linked} observations + {ev_linked} events re-pointed; "
          f"historical resolution {placed}/{total} = {placed/total:.0%}")


if __name__ == "__main__":
    main()
