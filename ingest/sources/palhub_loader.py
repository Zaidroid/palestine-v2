"""P1.8 — load palhubappfuel sweeps into v2 state tables.

Reads the tee spool, parses sweeps, resolves each station to the best available
place, and writes `state_observation` (+ `state_current`).

GEO PRECISION LADDER — never drop a station for want of coordinates, and never
pretend to precision we do not have:

    1. OSM station name match  -> precision 'station'  (real coordinates)
    2. "(locality)" suffix     -> precision 'town'     (locality centroid)
    3. region header           -> precision 'admin2'   (always present)

Measured on the first 200 stations: 17% match an OSM station, 48% a locality,
the rest fall back to region. Every station lands somewhere, and the precision
is recorded so the serving layer can rank a station-precise answer above a
region-precise one instead of treating them as equal.

Stations palhub knows and OSM does not are CREATED as places — palhub is the
authoritative list of which fuel stations exist; OSM merely has coordinates for
some of them.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cascade.palhub_fuel import parse_spool
from resolve.arabic import is_generic_alias, variants
from resolve.db import connect
from resolve.geo import resolve_place

SPOOL_DIR = Path("/opt/stacks/palestine/services/westbank-alerts/data/tee")
SOURCE_KEY = "telegram_fuel"

# palhub splits some governorates into towns (دورا, يطا, بيتونيا), so a region
# is resolved as a place rather than assumed to be an admin2.
_region_cache: dict[str, tuple | None] = {}


def _ensure_source(cur) -> int:
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,attribution_text,
                            authority_rank,independence_group)
        VALUES (%s,'Palhub - احوال الوقود (Telegram)','telegram','NONE',false,
                'Palhub fuel status channel',5,'palhub')
        ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name
        RETURNING source_id""", (SOURCE_KEY,))
    return cur.fetchone()[0]


def _resolve_station(cur, conn, name: str, locality: str | None, region: str):
    """Return (place_id, precision, how). Creates a place when palhub knows a
    station OSM does not."""
    # 1 — an actual station in the gazetteer
    r = resolve_place(name, {"prefer_kind": "station"}, conn=conn, learn=False)
    if r and r.kind == "station" and r.confidence >= 0.65:
        return r.place_id, "station", "osm_station"

    # 2 / 3 — anchor geometry on the locality, else the region
    anchor = None
    if locality:
        a = resolve_place(locality, conn=conn, learn=False)
        if a:
            anchor, precision, how = a, "town", "locality"
    if anchor is None:
        if region not in _region_cache:
            _region_cache[region] = resolve_place(region, conn=conn, learn=False)
        a = _region_cache[region]
        if a:
            anchor, precision, how = a, "admin2", "region"
    if anchor is None:
        return None, "unknown", "unresolved"

    # Create the station as a first-class place at the anchor's centroid.
    cur.execute("""
        SELECT place_id FROM place
        WHERE kind='station' AND source_refs->>'palhub_name' = %s""", (name,))
    row = cur.fetchone()
    if row:
        return row[0], precision, how

    cur.execute("""
        INSERT INTO place (kind,name_ar,admin1_pcode,admin2_pcode,geom,source_refs,confidence,attrs)
        SELECT 'station', %s, p.admin1_pcode, p.admin2_pcode,
               (p.centroid)::geometry, %s, %s, %s
        FROM place p WHERE p.place_id = %s
        RETURNING place_id""",
        (name,
         json.dumps({"palhub_name": name, "palhub_locality": locality,
                     "palhub_region": region, "source": "palhub",
                     "geo_anchor_place_id": anchor.place_id, "geo_basis": how}),
         0.8 if how == "locality" else 0.5,
         json.dumps({"geo_precision": precision}),
         anchor.place_id))
    pid = cur.fetchone()[0]

    for key in variants(name):
        if key and len(key) >= 2 and not is_generic_alias(key):
            cur.execute("""
                INSERT INTO place_alias (alias_norm, place_id, confidence, origin)
                VALUES (%s,%s,0.8,'observed') ON CONFLICT (alias_norm) DO NOTHING""",
                        (key, pid))
    return pid, precision, how


def load(spool_files=None) -> dict:
    files = spool_files or sorted(SPOOL_DIR.glob("*.ndjson"))
    rows = []
    for f in files:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))

    sweeps = parse_spool(rows)
    stats = {"sweeps": len(sweeps), "readings": 0, "observations": 0,
             "stations_created": 0, "unresolved": 0,
             "by_precision": {}, "by_how": {}}
    if not sweeps:
        return stats

    with connect() as conn, conn.cursor() as cur:
        source_id = _ensure_source(cur)
        cur.execute("SELECT COUNT(*) FROM place WHERE kind='station'")
        before = cur.fetchone()[0]

        resolved: dict[tuple, tuple] = {}
        now_utc = datetime.now(timezone.utc)
        for sw in sweeps:
            # observed_at comes from the TELEGRAM message date, which is UTC and
            # authoritative. The "آخر تحديث" stamp inside the message is
            # channel-LOCAL (UTC+3) with no offset; treating it as UTC put every
            # observation ~3h in the future, pinning confidence at 1.0 and
            # producing age_minutes = -177. Same class of bug as v1's negative
            # freshness. The local stamp is kept as provenance only.
            observed = None
            msg_date = getattr(sw, "msg_date", None)
            if msg_date:
                try:
                    observed = datetime.fromisoformat(msg_date.replace("Z", "+00:00"))
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                except ValueError:
                    observed = None
            if observed is None:
                observed = now_utc
            # Guard: an observation can never be in the future. If a source ever
            # claims one, clamp and keep the claim visible in attrs.
            future_skew_s = (observed - now_utc).total_seconds()
            if future_skew_s > 60:
                observed = now_utc
            else:
                future_skew_s = 0
            for rd in sw.readings:
                stats["readings"] += 1
                key = (rd.station_name, rd.locality, rd.region)
                if key not in resolved:
                    resolved[key] = _resolve_station(cur, conn, *key)
                place_id, precision, how = resolved[key]
                stats["by_precision"][precision] = stats["by_precision"].get(precision, 0) + 1
                stats["by_how"][how] = stats["by_how"].get(how, 0) + 1
                if place_id is None:
                    stats["unresolved"] += 1
                    continue

                cur.execute("""
                    INSERT INTO state_observation
                        (place_id,state_kind,value,raw_value,observed_at,source_id,confidence,attrs)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (place_id, rd.state_kind, rd.value, rd.raw_value, observed, source_id,
                     0.95,
                     json.dumps({"region": rd.region, "locality": rd.locality,
                                 "station_raw": rd.station_raw,
                                 "geo_precision": precision, "geo_basis": how,
                                 "msg_id": getattr(sw, "msg_id", None),
                                 "palhub_stamp_local": sw.updated_raw,
                                 "future_skew_clamped_s": future_skew_s or None})))
                stats["observations"] += 1

        # Rebuild state_current from the newest observation per (place, kind).
        cur.execute("""
            INSERT INTO state_current
                (place_id,state_kind,value,observed_at,source_id,base_confidence,
                 independent_sources,contradicted_by,updated_at)
            SELECT DISTINCT ON (place_id, state_kind)
                   place_id, state_kind, value, observed_at, source_id, confidence, 1, 0, now()
            FROM state_observation
            ORDER BY place_id, state_kind, observed_at DESC
            ON CONFLICT (place_id, state_kind) DO UPDATE SET
                value=EXCLUDED.value, observed_at=EXCLUDED.observed_at,
                source_id=EXCLUDED.source_id, base_confidence=EXCLUDED.base_confidence,
                updated_at=now()
            WHERE EXCLUDED.observed_at >= state_current.observed_at""")

        cur.execute("SELECT COUNT(*) FROM place WHERE kind='station'")
        stats["stations_created"] = cur.fetchone()[0] - before
        conn.commit()
    return stats


if __name__ == "__main__":
    s = load()
    print(f"sweeps            {s['sweeps']}")
    print(f"readings          {s['readings']}")
    print(f"observations      {s['observations']}")
    print(f"stations created  {s['stations_created']}")
    print(f"unresolved        {s['unresolved']}")
    print(f"by precision      {s['by_precision']}")
    print(f"by basis          {s['by_how']}")
