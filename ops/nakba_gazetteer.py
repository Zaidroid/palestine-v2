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
from resolve.db import v1_path  # noqa: E402

V1_HIST = v1_path("public/data/unified/historical/all-data.json")


def main() -> None:
    recs = json.loads(V1_HIST.read_text())["data"]
    pom = [r for r in recs
           if (r.get("sources") or [{}])[0].get("name") == "Palestine Open Maps"]

    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT source_refs->>'v1_canonical_key' FROM place
                       WHERE source_refs ? 'v1_canonical_key'""")
        existing = {r[0] for r in cur.fetchall()}
        # Coordinates are the durable key now. v1 has DROPPED
        # location.gazetteer_key from all 2,490 historical records (measured
        # 2026-08-07, the same regression that took the demolition localities'
        # keys). The first run of this script keyed on it and therefore
        # skipped every record that lacked one — leaving 632 real depopulated
        # villages (Jaba', Isfiya, Arraba, Dayr al-Qasi …) with no place row
        # at all, and historical resolution stuck at 94%.
        # Rendered in Python on both sides: Postgres round() is half-up
        # and Python's format is banker's, so on an exact tie they disagree
        # by one ulp and 135 villages silently failed to match.
        cur.execute("""SELECT ST_Y(geom::geometry), ST_X(geom::geometry)
                       FROM place WHERE geom IS NOT NULL
                         AND merged_into IS NULL
                         AND ST_GeometryType(geom::geometry) = 'ST_Point'""")
        existing_geo = {(f"{a:.5f}", f"{b:.5f}") for a, b in cur.fetchall()}

        created = skipped_existing = skipped_nogeom = 0
        for r in pom:
            loc = r.get("location") or {}
            key = loc.get("gazetteer_key")
            if key and key in existing:
                skipped_existing += 1
                continue
            if loc.get("lat") is not None and loc.get("lon") is not None and \
                    (f"{loc['lat']:.5f}", f"{loc['lon']:.5f}") in existing_geo:
                skipped_existing += 1          # already here, under any key
                continue
            lat, lon = loc.get("lat"), loc.get("lon")
            if lat is None or lon is None:
                skipped_nogeom += 1
                continue
            if key:
                existing.add(key)
            existing_geo.add((f"{lat:.5f}", f"{lon:.5f}"))
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
                 json.dumps({k: v for k, v in
                             {"v1_canonical_key": key,
                              "source": "palopenmaps"}.items() if v}),
                 json.dumps({k: v for k, v in attrs.items() if v},
                            ensure_ascii=False)))
            created += 1

        # Re-point rows that could not resolve when they were written.
        # The original join was on attrs.gazetteer_key; v1 has since dropped
        # that field from every historical record, so the join matches
        # nothing. attrs.geo_key — written by the transformer in the same
        # format used above — is the durable equivalent.
        geo_to_place = {k: v for k, v in
                        ((f"{a:.5f},{b:.5f}", pid) for a, b, pid in (
                            cur.execute(
                                "SELECT ST_Y(geom::geometry), "
                                "ST_X(geom::geometry), place_id FROM place "
                                "WHERE geom IS NOT NULL AND merged_into IS NULL "
                                "AND ST_GeometryType(geom::geometry)='ST_Point'")
                            or cur.fetchall()))}
        obs_linked = ev_linked = 0
        for table, extra in (("observation o", "o.place_id IS NULL"),
                             ("event o", "o.place_id IS NULL")):
            cur.execute(f"""SELECT o.{'observation_id' if 'observation' in table
                                        else 'event_id'}, o.attrs->>'geo_key'
                            FROM {table}
                            WHERE {extra} AND o.attrs ? 'geo_key'""")
            pending = [(oid, gk) for oid, gk in cur.fetchall()
                       if gk in geo_to_place]
            for oid, gk in pending:
                cur.execute(
                    f"UPDATE {table.split()[0]} SET place_id = %s WHERE "
                    f"{'observation_id' if 'observation' in table else 'event_id'}"
                    " = %s", (geo_to_place[gk], oid))
            if "observation" in table:
                obs_linked = len(pending)
            else:
                ev_linked = len(pending)
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
