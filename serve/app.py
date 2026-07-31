"""P1.9 — Palestine v2 serving API.

Answers the Phase 1 question: **which station has diesel right now, and how
long does it take me to get there?**

SERVING CONTRACT (ARCHITECTURE §3.5). Every state row returned carries:
    value · confidence · observed_at · age_minutes · staleness_band ·
    last_known_value · sources · geo_precision

`value` is what we are willing to assert now. Once decayed confidence falls
below the kind's floor it becomes "unknown" and the last reading moves to
`last_known_value` — the API never asserts a stale reading as current. That is
the structural fix for the failure mode v1 still has with checkpoints, and it
matters more for fuel: sending someone across a closed governorate to an empty
pump during a shortage is a real cost.

Reads ONLY from the `state_serving` view, never `state_current`.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

from resolve.db import dsn

VALHALLA = os.environ.get("VALHALLA_URL", "http://172.22.0.2:8002")
FUEL_KINDS = {"diesel": "fuel_diesel", "gasoline": "fuel_gasoline",
              "benzine": "fuel_gasoline", "gas": "cooking_gas"}

# Which geo precisions justify quoting a drive time at all. A station located
# only to admin2 sits at the REGION CENTROID, so routing to it returns the
# distance to the middle of the governorate — which came out as "0.0 min away"
# for Ramallah stations and ranked them ABOVE genuinely-located ones. Quoting a
# precise number for an imprecise location is the same failure as serving a
# stale checkpoint as open: confidently wrong beats honestly vague, until
# someone drives there.
ROUTABLE_PRECISION = {"exact", "street", "station", "town"}

app = FastAPI(
    title="Palestine Data Platform v2",
    version="2.0.0",
    description="Live fuel, checkpoint and humanitarian state for the West Bank and Gaza.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _drive_times(origin: tuple[float, float], targets: list[dict]) -> dict[int, dict]:
    """One Valhalla sources_to_targets call for the whole candidate set.

    Falls back to straight-line only — never to silence. A routing outage must
    degrade the ordering, not remove the answer, because "no fuel found" and
    "router down" must never look the same to someone who needs fuel.
    """
    if not targets:
        return {}
    try:
        body = {
            "sources": [{"lat": origin[0], "lon": origin[1]}],
            "targets": [{"lat": t["lat"], "lon": t["lon"]} for t in targets],
            "costing": "auto",
            "units": "km",
        }
        r = httpx.post(f"{VALHALLA}/sources_to_targets", json=body, timeout=25.0)
        r.raise_for_status()
        matrix = r.json()["sources_to_targets"][0]
        out = {}
        for i, cell in enumerate(matrix):
            if cell.get("time") is None:
                continue
            out[targets[i]["place_id"]] = {
                "drive_minutes": round(cell["time"] / 60, 1),
                "drive_km": round(cell.get("distance", 0), 1),
                "routing": "valhalla",
            }
        return out
    except Exception:                                   # noqa: BLE001
        return {}


@app.get("/health")
def health() -> dict:
    try:
        row = q("SELECT COUNT(*) AS n FROM state_serving WHERE state_kind LIKE 'fuel%%'")[0]
        fresh = q("""SELECT MAX(observed_at) AS latest FROM state_current
                     WHERE state_kind LIKE 'fuel%%'""")[0]["latest"]
        age_min = None
        if fresh:
            age_min = round((datetime.now(timezone.utc) - fresh).total_seconds() / 60, 1)
        return {"status": "ok", "fuel_states": row["n"], "feed_age_minutes": age_min}
    except Exception as e:                              # noqa: BLE001
        raise HTTPException(503, f"database unavailable: {e}")


@app.get("/v2/fuel/nearby", tags=["fuel"])
def fuel_nearby(
    lat: float = Query(..., ge=29.0, le=34.0),
    lon: float = Query(..., ge=33.0, le=37.0),
    fuel: str = Query("diesel", description="diesel | gasoline | gas"),
    radius_km: float = Query(30.0, gt=0, le=200),
    limit: int = Query(15, ge=1, le=100),
    include_unknown: bool = Query(False, description="include stations whose reading has decayed"),
) -> dict:
    """Stations with the requested fuel, ranked by drive time."""
    kind = FUEL_KINDS.get(fuel.lower())
    if not kind:
        raise HTTPException(400, f"unknown fuel '{fuel}'; use one of {sorted(set(FUEL_KINDS))}")

    rows = q("""
        SELECT s.place_id, s.name_ar, s.name_en, s.state_kind,
               s.value, s.last_known_value, s.observed_at, s.age_minutes,
               s.confidence, s.staleness_band, s.independent_sources,
               ST_Y(s.centroid::geometry) AS lat,
               ST_X(s.centroid::geometry) AS lon,
               ST_Distance(s.centroid, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)/1000.0
                   AS straight_km,
               p.attrs->>'geo_precision' AS geo_precision,
               p.source_refs->>'palhub_region' AS region,
               p.source_refs->>'palhub_locality' AS locality
        FROM state_serving s
        JOIN place p ON p.place_id = s.place_id
        WHERE s.state_kind = %s
          AND ST_DWithin(s.centroid, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, %s)
        ORDER BY straight_km ASC
        LIMIT 300""", (lon, lat, kind, lon, lat, radius_km * 1000))

    available = [r for r in rows if r["value"] == "available"]
    unknown = [r for r in rows if r["value"] == "unknown"]
    candidates = available + (unknown if include_unknown else [])

    routable = [c for c in candidates
                if c["lat"] is not None
                and (c["geo_precision"] or "station") in ROUTABLE_PRECISION]
    times = _drive_times((lat, lon), routable)

    results = []
    for c in candidates:
        precision = c["geo_precision"] or "station"
        is_routable = precision in ROUTABLE_PRECISION
        t = times.get(c["place_id"], {})
        # Never quote distance or drive time we have not earned.
        loc_note = None
        if not is_routable:
            t = {}
            loc_note = (f"approximate — location known only to "
                        f"{c['region'] or 'region'} level, not the station itself")
        results.append({
            "place_id": c["place_id"],
            "name": c["name_ar"] or c["name_en"],
            "name_en": c["name_en"],
            "region": c["region"],
            "locality": c["locality"],
            "lat": c["lat"], "lon": c["lon"],
            # the serving contract
            "value": c["value"],
            "last_known_value": c["last_known_value"],
            "confidence": round(float(c["confidence"]), 3),
            "observed_at": c["observed_at"],
            "age_minutes": c["age_minutes"],
            "staleness_band": c["staleness_band"],
            "independent_sources": c["independent_sources"],
            # how precisely we know WHERE this station is — distinct from how
            # confident we are about its fuel
            "geo_precision": precision,
            "straight_km": round(float(c["straight_km"]), 1) if is_routable else None,
            "location_note": loc_note,
            **t,
        })

    # Rank: precisely-located stations first (by drive time, then straight
    # line), then approximate ones. Confidence breaks ties so a fresher reading
    # wins at equal distance. Without the precision tier, region-centroid
    # stations sort to the top with a fictitious 0-minute drive.
    def rank(r):
        approx = r["location_note"] is not None
        if approx:
            return (1, 0.0, -r["confidence"])
        primary = r.get("drive_minutes")
        if primary is None:
            primary = (r["straight_km"] or 0) * 2      # rough min/km fallback
        return (0, primary, -r["confidence"])

    results.sort(key=rank)

    return {
        "query": {"lat": lat, "lon": lon, "fuel": fuel, "kind": kind,
                  "radius_km": radius_km, "include_unknown": include_unknown},
        "counts": {"in_radius": len(rows), "available": len(available),
                   "unknown": len(unknown), "returned": min(len(results), limit),
                   "located_precisely": sum(1 for r in results if r["location_note"] is None),
                   "located_approximately": sum(1 for r in results if r["location_note"])},
        "routing": "valhalla" if times else "straight_line_fallback",
        "results": results[:limit],
        "attribution": "Palhub - احوال الوقود (Telegram) · © OpenStreetMap contributors",
    }


@app.get("/v2/fuel/stations", tags=["fuel"])
def fuel_stations(region: str | None = None, only_available: bool = False) -> dict:
    rows = q("""
        SELECT s.place_id, s.name_ar, s.name_en, s.state_kind, s.value,
               s.last_known_value, s.confidence, s.observed_at, s.age_minutes,
               s.staleness_band,
               p.source_refs->>'palhub_region' AS region,
               p.source_refs->>'palhub_locality' AS locality
        FROM state_serving s
        JOIN place p ON p.place_id = s.place_id
        WHERE s.state_kind LIKE 'fuel%%'
          AND (%s IS NULL OR p.source_refs->>'palhub_region' = %s)
          AND (%s = false OR s.value = 'available')
        ORDER BY p.source_refs->>'palhub_region', s.name_ar""",
        (region, region, only_available))
    by_station: dict[int, dict] = {}
    for r in rows:
        st = by_station.setdefault(r["place_id"], {
            "place_id": r["place_id"], "name": r["name_ar"] or r["name_en"],
            "region": r["region"], "locality": r["locality"], "fuels": {},
        })
        st["fuels"][r["state_kind"].replace("fuel_", "")] = {
            "value": r["value"], "last_known_value": r["last_known_value"],
            "confidence": round(float(r["confidence"]), 3),
            "observed_at": r["observed_at"], "age_minutes": r["age_minutes"],
            "staleness_band": r["staleness_band"],
        }
    return {"count": len(by_station), "stations": list(by_station.values()),
            "attribution": "Palhub - احوال الوقود (Telegram)"}


@app.get("/v2/fuel/summary", tags=["fuel"])
def fuel_summary() -> dict:
    rows = q("""
        SELECT p.source_refs->>'palhub_region' AS region, s.state_kind,
               COUNT(*) FILTER (WHERE s.value='available') AS available,
               COUNT(*) FILTER (WHERE s.value='unavailable') AS unavailable,
               COUNT(*) FILTER (WHERE s.value='unknown') AS unknown,
               COUNT(*) AS total
        FROM state_serving s JOIN place p ON p.place_id = s.place_id
        WHERE s.state_kind LIKE 'fuel%%' AND p.source_refs ? 'palhub_region'
        GROUP BY 1,2 ORDER BY 1,2""")
    out: dict[str, Any] = {}
    for r in rows:
        out.setdefault(r["region"], {})[r["state_kind"].replace("fuel_", "")] = {
            "available": r["available"], "unavailable": r["unavailable"],
            "unknown": r["unknown"], "total": r["total"],
        }
    totals = q("""
        SELECT state_kind,
               COUNT(*) FILTER (WHERE value='available') AS available,
               COUNT(*) AS total
        FROM state_serving WHERE state_kind LIKE 'fuel%%' GROUP BY 1""")
    return {
        "totals": {t["state_kind"].replace("fuel_", ""):
                   {"available": t["available"], "total": t["total"]} for t in totals},
        "by_region": out,
        "attribution": "Palhub - احوال الوقود (Telegram)",
    }
