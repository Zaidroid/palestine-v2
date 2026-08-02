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
# POST is allowed since P2: the crowd engine takes submissions from a browser.
# Without it the preflight fails and every report from a phone dies silently at
# the CORS layer while the endpoint tests fine with curl.
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])


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
def health(verbose: bool = Query(True, description="include the per-check detail")) -> dict:
    """P3.2 — every vertical, its age, and whether that age is within cadence.

    This used to report fuel and nothing else, so nine of the ten verticals
    could stop without the health endpoint changing by a character. On
    2026-08-01 the Telegram poller sat dead for eight hours and /health stayed
    a cheerful `{"status": "ok"}` throughout, because the one thing it looked
    at was not the thing that had broken.

    The judgement is not made here. It comes from ops/watchdog.py, which is the
    same code the alarm path runs, so a red status page and a silent watchdog
    cannot happen — they would have to disagree with themselves. The expensive
    part of that judgement (a 21-day scan to measure each feed's rhythm) is
    read from feed_cadence rather than recomputed, which is what keeps this
    endpoint at ~140ms instead of ~570ms.

    WHY A STALE FEED IS STILL HTTP 200
    503 means "do not send me requests". A stale feed is not that: the API can
    still answer correctly, and part of answering correctly is saying a reading
    has decayed. Returning 503 would take a working API out of a load
    balancer's rotation because a Telegram channel went quiet, replacing
    degraded answers with no answers. 503 is reserved for the database being
    unreachable, which is the case where this genuinely cannot serve.
    """
    try:
        row = q("SELECT COUNT(*) AS n FROM state_serving WHERE state_kind LIKE 'fuel%%'")[0]
        fresh = q("""SELECT MAX(observed_at) AS latest FROM state_current
                     WHERE state_kind LIKE 'fuel%%'""")[0]["latest"]
        age_min = None
        if fresh:
            age_min = round((datetime.now(timezone.utc) - fresh).total_seconds() / 60, 1)
    except Exception as e:                              # noqa: BLE001
        raise HTTPException(503, f"database unavailable: {e}")

    try:
        from ops.watchdog import feed_checks, job_checks
        jobs = job_checks()
        feeds = feed_checks(jobs)                       # cached cadence
        faults = [c for c in jobs + feeds if c["fault"]]
    except Exception as e:                              # noqa: BLE001
        # The checks failing must not take down the endpoint that reports
        # health — but it must not report health it could not establish
        # either, so this is surfaced rather than swallowed into an "ok".
        return {"status": "unknown", "fuel_states": row["n"],
                "feed_age_minutes": age_min,
                "error": f"health checks unavailable: {e}"}

    out: dict[str, Any] = {
        "status": "degraded" if faults else "ok",
        # Kept from the original response so existing callers keep working.
        "fuel_states": row["n"],
        "feed_age_minutes": age_min,
        "faults": [f"{c['check']}:{c['name']} {c['status']}" for c in faults],
        "jobs_ok": sum(1 for c in jobs if not c["fault"]),
        "jobs_total": len(jobs),
        "feeds_ok": sum(1 for c in feeds if not c["fault"]),
        "feeds_total": len(feeds),
    }
    if verbose:
        out["checks"] = {
            "jobs": [{"name": c["name"], "status": c["status"],
                      "age_minutes": c["age_minutes"],
                      "expected_seconds": c["expected_seconds"],
                      "detail": c["detail"]} for c in jobs],
            "feeds": [{"name": c["name"], "status": c["status"],
                       "age_minutes": c["age_minutes"],
                       "threshold_minutes": c.get("threshold_minutes"),
                       "collector": c.get("collector"),
                       "detail": c["detail"]} for c in feeds],
        }
    return out


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


# ── checkpoints ──────────────────────────────────────────────────────────────
# All three read `checkpoint_serving` (migration 014), which resolves the
# direction fallback and keeps flow and presence apart. Two properties are
# deliberate and load-bearing:
#
#   `flow` is 'unknown' once the reading has decayed past its floor, with the
#   reading itself preserved in `last_known_flow` and its age alongside. v1
#   asserts a bare status with no decay at all, so 165 checkpoints there would
#   currently be reported open on evidence over a day old.
#
#   `present` (army, police, settlers, inspection) is returned NEXT TO flow,
#   never instead of it. v1 overwrites one with the other, which is why
#   "opened, with inspection" became simply `inspection` and stopped answering
#   the only question a traveller asked.
#
#   `present` and `absent` are SIGHTINGS, not states, and both are almost always
#   empty. That is correct rather than broken. P1.3 measured an army patrol at a
#   FIFTEEN MINUTE half-life against a reporting gap of 34.7 hours, so "is the
#   army there now?" is a question nobody has the evidence to answer for 99% of
#   checkpoints. Read them with `presence_age_minutes`; an empty `present` means
#   "not sighted recently", never "not there".

CHECKPOINT_COLS = """
    c.place_id, c.name_ar, c.name_en, c.direction, c.flow, c.last_known_flow,
    c.reported_for, c.observed_at, c.age_minutes, c.confidence, c.staleness_band,
    c.independent_sources, c.contradicted_by, c.present, c.absent,
    c.presence_age_minutes, c.passable, c.cadence_measured,
    ST_Y(c.centroid::geometry) AS lat, ST_X(c.centroid::geometry) AS lon
"""


def _checkpoint_out(r: dict, extra: dict | None = None) -> dict:
    return {
        "place_id": r["place_id"],
        "name": r["name_ar"] or r["name_en"],
        "name_en": r["name_en"],
        "lat": r["lat"], "lon": r["lon"],
        "direction": r["direction"],
        # the serving contract
        "flow": r["flow"],
        "passable": r["passable"],
        "last_known_flow": r["last_known_flow"],
        "confidence": round(float(r["confidence"]), 3),
        "observed_at": r["observed_at"],
        "age_minutes": r["age_minutes"],
        "staleness_band": r["staleness_band"],
        "independent_sources": r["independent_sources"],
        "contradicted_by": r["contradicted_by"],
        # whether this reading was filed for this direction or inherited from a
        # 'both' report — so a caller can tell a specific answer from a general one
        "reported_for": r["reported_for"],
        "cadence_measured": r["cadence_measured"],
        # separate axis, never merged into flow. Sightings, not states:
        # empty means "not sighted recently", never "not there".
        "present": list(r["present"] or []),
        # somebody stood there and said the army was NOT present. A different
        # fact from nobody having looked, and the more useful one to a family.
        "absent": list(r["absent"] or []),
        "presence_age_minutes": r["presence_age_minutes"],
        **(extra or {}),
    }


CHECKPOINT_ATTRIBUTION = ("Telegram road-condition channels via Palestine Data "
                          "Backend v1 parser · © OpenStreetMap contributors")


def _resolve_checkpoint(name: str) -> dict | None:
    """Resolve a name to a CHECKPOINT, not merely to a place.

    The general resolver cannot do this. `place_alias.alias_norm` is a global
    primary key, so one spelling maps to exactly one place — and for "حواره"
    the LOCALITY of Huwara won the alias, while the checkpoint carrying 1,429
    observations had none. Asking the general resolver for the busiest
    checkpoint in the West Bank therefore returned a town with no reading.

    Someone asking this endpoint has already said they mean a checkpoint, so
    the search is scoped to checkpoint-like places and scored here, reusing the
    same Arabic normalisation as the gazetteer. The candidate set is a few
    hundred rows; matching in Python keeps fold/normalize identical to
    resolve.arabic instead of reimplementing them in SQL.
    """
    from difflib import SequenceMatcher

    from resolve.arabic import fold_for_match, normalize

    n, f = normalize(name), fold_for_match(name)
    if not n:
        return None
    rows = q("""
        SELECT p.place_id, p.name_ar, p.name_en,
               COALESCE(o.n, 0) AS obs,
               COALESCE(array_agg(a.alias_norm) FILTER (WHERE a.alias_norm IS NOT NULL),
                        ARRAY[]::text[]) AS aliases
        FROM place p
        LEFT JOIN place_alias a ON a.place_id = p.place_id
        LEFT JOIN (SELECT place_id, COUNT(*) n FROM state_observation
                   WHERE state_kind = 'checkpoint_flow' GROUP BY 1) o ON o.place_id = p.place_id
        WHERE p.servable AND p.kind IN ('checkpoint','crossing','road')
        GROUP BY p.place_id, p.name_ar, p.name_en, o.n""")

    best, best_score = None, 0.0
    for r in rows:
        names = [x for x in (r["name_ar"], r["name_en"]) if x]
        norms = {normalize(x) for x in names}
        folds = {fold_for_match(x) for x in names}
        aliases = set(r["aliases"] or [])

        if n in norms:
            score = 1.00
        elif n in aliases:
            score = 0.95
        elif f and f in folds:
            score = 0.90
        elif any(n and (n in x or x in n) for x in norms if x):
            score = 0.70
        else:
            score = max((SequenceMatcher(None, n, x).ratio() for x in norms if x),
                        default=0.0)
            if score < 0.78:
                continue
            score *= 0.8
        # Evidence breaks ties: among equally-named candidates the one people
        # actually report about is the one they mean.
        score += min(r["obs"], 5000) / 5000 * 0.04
        if score > best_score:
            best, best_score = r, score
    if not best:
        return None
    return {"place_id": best["place_id"],
            "name": best["name_ar"] or best["name_en"],
            "score": round(best_score, 3)}


@app.get("/v2/checkpoints/nearby", tags=["checkpoints"])
def checkpoints_nearby(
    lat: float = Query(..., ge=29.0, le=34.0),
    lon: float = Query(..., ge=33.0, le=37.0),
    direction: str = Query("both", description="inbound | outbound | both"),
    radius_km: float = Query(15.0, gt=0, le=100),
    limit: int = Query(10, ge=1, le=50),
    include_unknown: bool = Query(True,
        description="include checkpoints whose reading has decayed (returned as flow=unknown)"),
) -> dict:
    """Checkpoints near a point, nearest first, with what we currently believe.

    include_unknown defaults to TRUE, unlike the fuel endpoint. A checkpoint we
    have no fresh reading for is still on your route and still worth naming —
    dropping it would imply the road is clear. Fuel is the opposite: a station
    we know nothing about is not worth driving to during a shortage.
    """
    if direction not in ("inbound", "outbound", "both"):
        raise HTTPException(400, "direction must be inbound, outbound or both")
    rows = q(f"""
        SELECT {CHECKPOINT_COLS},
               ST_Distance(c.centroid, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)/1000.0
                   AS straight_km
        FROM checkpoint_serving c
        WHERE c.direction = %s
          AND ST_DWithin(c.centroid, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, %s)
        ORDER BY straight_km ASC
        LIMIT 200""", (lon, lat, direction, lon, lat, radius_km * 1000))

    if not include_unknown:
        rows = [r for r in rows if r["flow"] != "unknown"]

    results = [_checkpoint_out(r, {"straight_km": round(float(r["straight_km"]), 1)})
               for r in rows[:limit]]
    return {
        "query": {"lat": lat, "lon": lon, "direction": direction,
                  "radius_km": radius_km, "include_unknown": include_unknown},
        "counts": {"in_radius": len(rows),
                   "known": sum(1 for r in rows if r["flow"] != "unknown"),
                   "unknown": sum(1 for r in rows if r["flow"] == "unknown"),
                   "closed": sum(1 for r in rows if r["flow"] == "closed"),
                   "returned": len(results)},
        "results": results,
        "attribution": CHECKPOINT_ATTRIBUTION,
    }


@app.get("/v2/checkpoints/status", tags=["checkpoints"])
def checkpoint_status(
    name: str = Query(..., min_length=2, description="Arabic or English checkpoint name"),
    direction: str = Query("both", description="inbound | outbound | both"),
) -> dict:
    """Status of one named checkpoint.

    Resolution runs against every spelling ever seen, including those of merged
    duplicates (migration 013) — the misspelling in an incoming message is
    exactly the string that needs to resolve.
    """
    if direction not in ("inbound", "outbound", "both"):
        raise HTTPException(400, "direction must be inbound, outbound or both")
    m = _resolve_checkpoint(name)
    if not m:
        return {"found": False, "query": name}
    rows = q(f"""SELECT {CHECKPOINT_COLS} FROM checkpoint_serving c
                 WHERE c.place_id = canonical_place(%s) AND c.direction = %s""",
             (m["place_id"], direction))
    if not rows:
        return {"found": False, "query": name, "resolved_to": m["name"],
                "reason": "no checkpoint reading has ever been recorded here"}
    both = q(f"""SELECT {CHECKPOINT_COLS} FROM checkpoint_serving c
                 WHERE c.place_id = canonical_place(%s)
                   AND c.direction IN ('inbound','outbound')""", (m["place_id"],))
    return {
        "found": True, "query": name,
        "match": {"resolved_to": m["name"], "score": m["score"]},
        **_checkpoint_out(rows[0]),
        # Both directions alongside the asked-for one: they can differ, and a
        # caller planning a round trip needs to see that they do.
        "by_direction": {b["direction"]: {"flow": b["flow"], "passable": b["passable"],
                                          "age_minutes": b["age_minutes"],
                                          "present": list(b["present"] or [])}
                         for b in both},
        "attribution": CHECKPOINT_ATTRIBUTION,
    }


@app.get("/v2/checkpoints/summary", tags=["checkpoints"])
def checkpoints_summary() -> dict:
    """West-Bank-wide picture, including how much of it we do NOT know."""
    rows = q("""SELECT flow, staleness_band, COUNT(*) AS n
                FROM checkpoint_serving WHERE direction='both'
                GROUP BY 1,2""")
    closed = q(f"""SELECT {CHECKPOINT_COLS} FROM checkpoint_serving c
                   WHERE c.direction='both' AND c.flow='closed'
                   ORDER BY c.age_minutes LIMIT 40""")
    presence = q("""SELECT unnest(present) AS who, COUNT(*) AS n
                    FROM checkpoint_serving WHERE direction='both' AND present <> '{}'
                    GROUP BY 1 ORDER BY 2 DESC""")
    totals: dict[str, int] = {}
    for r in rows:
        totals[r["flow"]] = totals.get(r["flow"], 0) + r["n"]
    tracked = sum(totals.values())
    return {
        "tracked": tracked,
        "totals": totals,
        # Stated explicitly rather than left to be inferred from the totals.
        "known_fraction": round(1 - totals.get("unknown", 0) / tracked, 3) if tracked else 0.0,
        "by_staleness": {f"{r['flow']}/{r['staleness_band']}": r["n"] for r in rows},
        "presence": {r["who"]: r["n"] for r in presence},
        "closed_now": [_checkpoint_out(r) for r in closed],
        "attribution": CHECKPOINT_ATTRIBUTION,
    }


@app.get("/v2/services", tags=["services"])
def services() -> dict:
    """Utilities: internet reachability and announced electricity cuts.

    The two are gathered in opposite ways, and the difference is the point.
    Internet is MEASURED from outside (IODA) because nobody can report an
    outage they are inside of. Power cuts are ANNOUNCED in advance by the
    distribution company, so they are scraped — and asserted only while the
    clock is inside the announced window, never merely because a notice exists.

    Unannounced power failures are visible to neither, and that is stated here
    rather than left to be inferred from an empty list.
    """
    net = q("""
        SELECT p.name_en, s.value, s.age_minutes, s.staleness_band,
               s.independent_sources, o.attrs
        FROM state_serving s JOIN place p ON p.place_id = s.place_id
        JOIN LATERAL (SELECT attrs FROM state_observation
                      WHERE place_id=s.place_id AND state_kind='internet'
                      ORDER BY observed_at DESC LIMIT 1) o ON true
        WHERE s.state_kind='internet'""")
    power = q("""
        SELECT p.name_ar, p.name_en, s.value, s.age_minutes, s.staleness_band, o.attrs
        FROM state_serving s JOIN place p ON p.place_id = s.place_id
        JOIN LATERAL (SELECT attrs FROM state_observation
                      WHERE place_id=s.place_id AND state_kind='power'
                      ORDER BY observed_at DESC LIMIT 1) o ON true
        WHERE s.state_kind='power' AND s.value <> 'unknown'""")
    return {
        "internet": ({"region": net[0]["name_en"], "status": net[0]["value"],
                      "age_minutes": net[0]["age_minutes"],
                      "signals_agreeing": net[0]["independent_sources"],
                      "signals": (net[0]["attrs"] or {}).get("signals"),
                      "method": "measured externally (IODA)"} if net else None),
        "power_cuts_active": [{"place": r["name_ar"] or r["name_en"],
                               "window_start": (r["attrs"] or {}).get("window_start"),
                               "window_end": (r["attrs"] or {}).get("window_end"),
                               "notice": (r["attrs"] or {}).get("title"),
                               "url": (r["attrs"] or {}).get("url")} for r in power],
        "coverage_note": ("Power cuts are scheduled announcements from NEDCO (northern "
                          "West Bank) only. UNANNOUNCED outages are not visible to this "
                          "system, and neither are other distribution areas."),
        "attribution": "IODA (Georgia Tech) · شركة توزيع كهرباء الشمال (NEDCO)",
    }


@app.get("/v2/connectivity", tags=["services"])
def connectivity() -> dict:
    """Is the West Bank internet reachable?

    Measured from OUTSIDE by IODA, not reported by anyone — which is the point.
    When a network goes down, the people who would report it are the people who
    just lost their connection, so a feed of outage reports has a hole exactly
    where the outage is. Three independent vantage points (routing table,
    active probes, darknet telescope) must agree before an outage is asserted.
    """
    rows = q("""
        SELECT p.name_en, s.value, s.observed_at, s.age_minutes, s.staleness_band,
               s.confidence, s.independent_sources, o.attrs
        FROM state_serving s
        JOIN place p ON p.place_id = s.place_id
        JOIN LATERAL (SELECT attrs FROM state_observation
                      WHERE place_id = s.place_id AND state_kind = 'internet'
                      ORDER BY observed_at DESC LIMIT 1) o ON true
        WHERE s.state_kind = 'internet'""")
    if not rows:
        return {"status": "unknown", "reason": "no measurement yet"}
    r = rows[0]
    return {"region": r["name_en"], "status": r["value"],
            "observed_at": r["observed_at"], "age_minutes": r["age_minutes"],
            "staleness_band": r["staleness_band"],
            "confidence": round(float(r["confidence"]), 3),
            "signals_agreeing": r["independent_sources"],
            "signals": (r["attrs"] or {}).get("signals"),
            "method": (r["attrs"] or {}).get("method"),
            "attribution": "Internet measurement by IODA, Georgia Tech (CC BY-NC 4.0)"}


@app.get("/v2/weather", tags=["weather"])
def weather(place: str | None = Query(None, description="governorate name, Arabic or English")) -> dict:
    """Conditions and advisory per West Bank governorate.

    Not a weather service — it is here because weather changes what the rest of
    the system's answers MEAN. 43°C turns a checkpoint queue from tedious into
    dangerous, and 30mm of rain closes unpaved approaches no checkpoint report
    will mention. `advisory` is the band; the raw numbers that produced it are
    returned alongside, because the thresholds are judgement and will be revised.
    """
    # Arabic must be compared in ONE orthography. The stored name is "أريحا"
    # (hamza) and callers type "اريحا" (bare alef); ILIKE does not fold them, so
    # the governorate filter silently matched nothing. The query is normalised
    # in Python and the column folded with the same letter mapping in SQL —
    # the same class of bug as writing regex patterns in an orthography the
    # normalised text can never have.
    from resolve.arabic import normalize
    needle = f"%{normalize(place)}%" if place else None
    rows = q("""
        SELECT p.name_en, p.name_ar, s.value AS advisory, s.observed_at,
               s.age_minutes, s.staleness_band, s.confidence, o.attrs
        FROM state_serving s
        JOIN place p ON p.place_id = s.place_id
        JOIN LATERAL (SELECT attrs FROM state_observation
                      WHERE place_id = s.place_id AND state_kind = 'weather'
                      ORDER BY observed_at DESC LIMIT 1) o ON true
        WHERE s.state_kind = 'weather'
          AND (%s::text IS NULL
               OR lower(p.name_en) LIKE %s
               OR translate(p.name_ar, 'أإآىةئؤ', 'ااايهيو') LIKE %s)
        ORDER BY (o.attrs->'today'->>'max_c')::float DESC NULLS LAST""",
        (needle, needle, needle))

    out = []
    for r in rows:
        a = r["attrs"] or {}
        out.append({
            "governorate": r["name_en"], "governorate_ar": r["name_ar"],
            "advisory": r["advisory"],
            "temp_now_c": a.get("temp_now_c"),
            "today": a.get("today"), "tomorrow": a.get("tomorrow"),
            "observed_at": r["observed_at"], "age_minutes": r["age_minutes"],
            "staleness_band": r["staleness_band"],
        })
    notable = [o for o in out if o["advisory"] not in ("normal", "unknown")]
    return {"count": len(out), "notable": notable, "governorates": out,
            "attribution": "Weather data by Open-Meteo.com (CC BY 4.0)"}


@app.get("/v2/incidents/recent", tags=["incidents"])
def incidents_recent(
    hours: int = Query(24, ge=1, le=168),
    lat: float | None = Query(None, ge=29.0, le=34.0),
    lon: float | None = Query(None, ge=33.0, le=37.0),
    radius_km: float = Query(25.0, gt=0, le=200),
    types: str | None = Query(None, description="comma-separated, e.g. raid,closure"),
    min_sources: int = Query(1, ge=1, le=10),
    limit: int = Query(30, ge=1, le=200),
) -> dict:
    """Located incidents — raids, settler attacks, closures — from the news feed.

    Events, not state: a raid happened at a time and place and does not decay
    into "no raid". `occurred_precision` is 'hour' throughout because the
    timestamp is when the channel POSTED, not when the incident happened.

    `independent_sources` counts independence GROUPS, so channels that mirror
    each other cannot inflate it — the same rule the checkpoint layer uses.
    """
    want = [t.strip() for t in types.split(",")] if types else None
    rows = q("""
        SELECT e.event_id, e.event_type, e.occurred_at, e.confidence,
               e.claim_count, e.independent_sources, e.attrs,
               p.name_ar, p.name_en, p.kind::text AS place_kind,
               ST_Y(e.geom::geometry) AS lat, ST_X(e.geom::geometry) AS lon,
               CASE WHEN %s::float8 IS NULL THEN NULL
                    ELSE ST_Distance(e.geom,
                         ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)/1000.0
               END AS straight_km
        FROM event e
        LEFT JOIN place p ON p.place_id = e.place_id
        WHERE e.status = 'believed'
          AND e.occurred_at > now() - make_interval(hours => %s)
          AND (%s::text[] IS NULL OR e.event_type = ANY(%s::text[]))
          AND e.independent_sources >= %s
          AND (%s::float8 IS NULL
               OR ST_DWithin(e.geom, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, %s))
        ORDER BY e.occurred_at DESC
        LIMIT %s""",
        (lat, lon, lat, hours, want, want, min_sources,
         lat, lon, lat, (radius_km or 0) * 1000, limit))

    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["event_type"]] = by_type.get(r["event_type"], 0) + 1
    return {
        "query": {"hours": hours, "types": want, "min_sources": min_sources,
                  "near": [lat, lon] if lat is not None else None,
                  "radius_km": radius_km if lat is not None else None},
        "count": len(rows),
        "by_type": by_type,
        "incidents": [{
            "event_id": r["event_id"],
            "type": r["event_type"],
            "place": r["name_ar"] or r["name_en"],
            "place_en": r["name_en"],
            "lat": r["lat"], "lon": r["lon"],
            "straight_km": round(float(r["straight_km"]), 1) if r["straight_km"] is not None else None,
            "occurred_at": r["occurred_at"],
            # Stated, not implied: this is the posting time, hour-precision.
            "occurred_precision": "hour",
            "confidence": round(float(r["confidence"]), 3),
            "reports": r["claim_count"],
            "independent_sources": r["independent_sources"],
            "channels": (r["attrs"] or {}).get("channels"),
        } for r in rows],
        "attribution": "West Bank governorate news channels (Telegram) via agent2",
    }


@app.get("/v2/incidents/summary", tags=["incidents"])
def incidents_summary(hours: int = Query(24, ge=1, le=168)) -> dict:
    """Incident counts by type and governorate, plus what was rejected.

    The rejection ledger is exposed deliberately. 395 of 953 claims were
    rejected as Gaza, international politics or commentary — publishing that
    is what lets a reader judge whether the channel mix is worth polling,
    rather than assuming the incident count is the whole story.
    """
    by_type = q("""SELECT event_type, COUNT(*) n,
                          COUNT(*) FILTER (WHERE independent_sources > 1) corroborated
                   FROM event WHERE status='believed'
                     AND occurred_at > now() - make_interval(hours => %s)
                   GROUP BY 1 ORDER BY 2 DESC""", (hours,))
    by_place = q("""SELECT p.name_ar, p.name_en, COUNT(*) n
                    FROM event e JOIN place p ON p.place_id = e.place_id
                    WHERE e.status='believed'
                      AND e.occurred_at > now() - make_interval(hours => %s)
                    GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15""", (hours,))
    ledger = q("""SELECT verdict, reject_reason, COUNT(*) n
                  FROM claim_classification GROUP BY 1,2 ORDER BY 3 DESC""")
    return {
        "window_hours": hours,
        "total": sum(r["n"] for r in by_type),
        "by_type": {r["event_type"]: {"n": r["n"], "corroborated": r["corroborated"]}
                    for r in by_type},
        "by_place": [{"place": r["name_ar"] or r["name_en"], "n": r["n"]}
                     for r in by_place],
        "classification_ledger": [{"verdict": r["verdict"],
                                   "reason": r["reject_reason"], "n": r["n"]}
                                  for r in ledger],
        "attribution": "West Bank governorate news channels (Telegram) via agent2",
    }


@app.get("/v2/news/latest", tags=["news"])
def news_latest(area: str | None = None, limit: int = Query(10, ge=1, le=100)) -> dict:
    """Most recent ingested messages, optionally filtered by area substring."""
    if area:
        rows = q("""
            SELECT c.raw_text, c.reported_at, s.name AS src, s.key AS src_key
            FROM claim c JOIN source s ON s.source_id = c.source_id
            WHERE c.raw_text ILIKE %s AND length(c.raw_text) > 30
            ORDER BY c.reported_at DESC LIMIT %s""", (f"%{area}%", limit))
    else:
        rows = q("""
            SELECT c.raw_text, c.reported_at, s.name AS src, s.key AS src_key
            FROM claim c JOIN source s ON s.source_id = c.source_id
            WHERE length(c.raw_text) > 30
            ORDER BY c.reported_at DESC LIMIT %s""", (limit,))
    return {"count": len(rows), "area": area,
            "items": [{"text": " ".join(r["raw_text"].split())[:500],
                       "source": r["src"], "source_key": r["src_key"],
                       "reported_at": r["reported_at"]} for r in rows]}


@app.get("/v2/coverage", tags=["meta"])
def coverage() -> dict:
    """What this system currently holds — so an agent can answer honestly about
    the limits of its own knowledge instead of implying total coverage."""
    src = q("""SELECT s.name, s.key, COUNT(c.*) AS claims, MAX(c.reported_at) AS newest
               FROM source s LEFT JOIN claim c ON c.source_id = s.source_id
               GROUP BY 1,2 HAVING COUNT(c.*) > 0 ORDER BY 3 DESC""")
    st = q("SELECT state_kind, COUNT(*) AS n FROM state_serving GROUP BY 1 ORDER BY 2 DESC")
    pl = q("SELECT kind::text AS kind, COUNT(*) AS n FROM place GROUP BY 1 ORDER BY 2 DESC")
    return {"sources": [{"name": r["name"], "key": r["key"], "claims": r["claims"],
                         "newest": r["newest"]} for r in src],
            "total_claims": sum(r["claims"] for r in src),
            "live_states": {r["state_kind"]: r["n"] for r in st},
            "places": {r["kind"]: r["n"] for r in pl}}


@app.get("/v2/geo/resolve", tags=["meta"])
def geo_resolve(q_: str = Query(..., alias="q", min_length=2)) -> dict:
    """Resolve a free-text Arabic/English place name to coordinates.

    Exposed so the MCP layer (and any agent) can turn "نابلس" into a lat/lon
    without needing database access or its own copy of the gazetteer.
    """
    from resolve.geo import resolve_place
    r = resolve_place(q_, learn=False)
    if not r:
        return {"found": False, "query": q_}
    row = q("SELECT ST_Y(centroid::geometry) la, ST_X(centroid::geometry) lo "
            "FROM place WHERE place_id=%s", (r.place_id,))
    if not row or row[0]["la"] is None:
        return {"found": False, "query": q_, "reason": "no geometry"}
    return {"found": True, "query": q_, "place_id": r.place_id,
            "name": r.name_ar or r.name_en, "name_en": r.name_en,
            "kind": r.kind, "precision": r.precision,
            "confidence": round(r.confidence, 3), "method": r.method,
            "lat": row[0]["la"], "lon": row[0]["lo"]}


# ── P2: the crowd reporting engine ───────────────────────────────────────────
# One endpoint for every field, because there is one engine. Which fields it
# accepts is a row in state_kind_config, not a branch in this file — see
# crowd/engine.py.

@app.get("/v2/crowd/fields", tags=["crowd"])
def crowd_fields() -> dict:
    """What can be reported, in what words, and what needs corroboration.

    Generated from configuration rather than maintained beside it, so it cannot
    drift from what the engine will actually accept.
    """
    from crowd.engine import reportable_kinds
    kinds = reportable_kinds()
    return {
        "fields": kinds,
        "count": len(kinds),
        "note": ("Values under `gated_values` are the reassuring ones. A crowd "
                 "report may always corroborate them and may always raise a "
                 "caution alone, but sole authorship of reassurance is "
                 "withheld until `min_units_for_gated` independent units agree "
                 "— being wrong in the reassuring direction is what gets "
                 "somebody hurt."),
    }


@app.post("/v2/crowd/report", tags=["crowd"])
def crowd_report(
    handle: str = Query(..., description="submitter handle"),
    token: str = Query(..., description="submission token"),
    state_kind: str = Query(..., description="see /v2/crowd/fields"),
    place: str = Query(..., description="place name, Arabic or English"),
    value: str = Query(..., description="must be in that field's vocabulary"),
    direction: str = Query("both", description="both | inbound | outbound"),
    note: str = Query("", description="optional free text, kept, never parsed"),
) -> dict:
    """Submit one report. Every field goes through here.

    Always 200 for an authenticated submitter, including when the report is
    refused: the outcome is in the body. A refusal is a fact about the report,
    not a transport error, and a phone on a bad connection should be able to
    tell "the network failed" from "the system heard me and said no".
    """
    from crowd.engine import submit
    res = submit(handle, token, state_kind, place, value, direction, note)
    if not res.ok and res.detail in ("unknown handle", "bad token"):
        raise HTTPException(401, res.detail)
    return res.as_dict()


@app.get("/v2/crowd/pending", tags=["crowd"])
def crowd_pending() -> dict:
    """Reports the P2.4 gate is currently withholding, and what they need.

    A gate that silently drops things is indistinguishable from a gate that is
    not working. This is how you check it is doing something — and how a
    submitter can be told their report is waiting for a second witness rather
    than lost.
    """
    from resolve.belief import blocked_by_gate
    rows = blocked_by_gate()
    return {"withheld": len(rows),
            "reports": [{"place_id": r["place_id"], "state_kind": r["state_kind"],
                         "value": r["value"], "units": r["agree"],
                         "units_needed": r["need"],
                         "observed_at": r["observed_at"]} for r in rows]}


# ── P5.1: history and patterns ───────────────────────────────────────────────
# Everything above answers "right now". These answer "what has been happening",
# which is the question a frontend charts and an agent reasons about.
#
# The source is `observation` — the DATABANK's table — written daily by
# ops/rollup.py. Tier 1's memory and tier 2's corpus are the same rows against
# the same place_id and clock, so a cross-tier query is a GROUP BY rather than a
# future migration. See db/migrations/031_tier1_history.sql.
#
# Counts of REPORTS, never shares of time. A checkpoint with three reports a day
# cannot speak for the other 23 hours, and a "40% closed" figure invites exactly
# that misreading. `units` travels with every count because nine channels
# reposting each other are one observer.

HISTORY_SQL = """
SELECT o.occurred_at::date                          AS day,
       (o.attrs->>'state_kind')                     AS state_kind,
       o.indicator,
       o.value_num
  FROM observation o
  JOIN dataset d USING (dataset_id)
 WHERE d.key = 'tier1_daily'
   AND o.place_id = %s
   AND o.occurred_at >= CURRENT_DATE - %s::int
   AND (%s::text IS NULL OR o.attrs->>'state_kind' = %s)
 ORDER BY 1
"""


@app.get("/v2/history/place", tags=["history"])
def history_place(
    place_id: int = Query(..., description="from /v2/geo/resolve"),
    state_kind: str | None = Query(None, description="e.g. checkpoint_status"),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """Daily report counts for one place, per state kind and value."""
    rows = q(HISTORY_SQL, (place_id, days, state_kind, state_kind))
    if not rows:
        return {"place_id": place_id, "days": days, "series": [],
                "note": "no rolled-up history — the place may be new, or the "
                        "rollup has not run for these days"}

    by_day: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = str(r["day"])
        kind = r["state_kind"]
        slot = by_day.setdefault(d, {}).setdefault(
            kind, {"reports": 0, "units": 0, "values": {}})
        ind = r["indicator"]
        n = int(r["value_num"] or 0)
        if ind.endswith(".units"):
            slot["units"] = n
        elif ind.endswith(".reports"):
            slot["reports"] = n
        else:
            slot["values"][ind.rsplit(".", 1)[-1]] = n

    return {
        "place_id": place_id,
        "days": days,
        "series": [{"day": d, "kinds": k} for d, k in sorted(by_day.items())],
        "counts": "reports, not time — a day with 3 reports does not describe "
                  "the other 23 hours. `units` is how many INDEPENDENT "
                  "reporters those came from.",
    }


AREA_SQL = """
SELECT g.name_en                                    AS governorate,
       g.admin2_pcode,
       (o.attrs->>'state_kind')                     AS state_kind,
       o.indicator,
       sum(o.value_num)                             AS total,
       count(DISTINCT o.place_id)                   AS places
  FROM observation o
  JOIN dataset d USING (dataset_id)
  JOIN place p ON p.place_id = o.place_id
  JOIN place g ON g.kind = 'governorate' AND g.admin2_pcode = p.admin2_pcode
 WHERE d.key = 'tier1_daily'
   AND o.occurred_at >= CURRENT_DATE - %s::int
   AND (%s::text IS NULL OR o.attrs->>'state_kind' = %s)
 GROUP BY 1,2,3,4
"""


@app.get("/v2/history/area", tags=["history"])
def history_area(
    state_kind: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """The same counts rolled up to governorate — the cross-tier query.

    Only possible since migration 032 gave every mapped place an admin2 code:
    ZERO of 235 checkpoint places carrying history had one, so this returned an
    empty result while looking perfectly healthy. Coverage is now 100%, with
    spatially-derived codes marked as such in place.attrs.
    """
    rows = q(AREA_SQL, (days, state_kind, state_kind))
    out: dict[str, dict] = {}
    for r in rows:
        g = out.setdefault(r["governorate"], {
            "admin2_pcode": r["admin2_pcode"], "places": 0, "kinds": {}})
        g["places"] = max(g["places"], r["places"])
        k = g["kinds"].setdefault(r["state_kind"],
                                  {"reports": 0, "values": {}})
        ind, n = r["indicator"], int(r["total"] or 0)
        if ind.endswith(".units"):
            continue                      # not summable across places
        if ind.endswith(".reports"):
            k["reports"] = n
        else:
            k["values"][ind.rsplit(".", 1)[-1]] = n
    return {"days": days, "governorates": out,
            "note": "`units` is deliberately absent here: independent-observer "
                    "counts do not sum across places. Ask /v2/history/place "
                    "for that."}


# Hour-of-day comes from state_observation rather than a stored hourly rollup.
# Inventing a second grain for a question the raw record already answers is
# premature aggregation, and the raw record is compressed and retained anyway.
#
# DISTINCT for the same reason the rollup uses it: 762,609 retained duplicate
# fuel rows would otherwise dominate every pattern they touch.
PATTERN_SQL = """
WITH obs AS (
  SELECT DISTINCT o.value, o.source_id, o.observed_at,
         extract(hour FROM o.observed_at AT TIME ZONE 'Asia/Hebron')::int AS hour
    FROM state_observation o
   WHERE o.place_id = %s AND o.state_kind = %s
     AND o.modality = 'assertion'
     AND o.observed_at >= now() - (%s::int * interval '1 day')
)
SELECT hour, value, count(*) AS n FROM obs GROUP BY 1,2 ORDER BY 1,2
"""


@app.get("/v2/patterns/place", tags=["history"])
def patterns_place(
    place_id: int = Query(...),
    state_kind: str = Query("checkpoint_status"),
    days: int = Query(60, ge=7, le=365),
    min_reports: int = Query(5, ge=1,
                             description="hours with fewer are returned as unknown"),
) -> dict:
    """What usually happens here, by hour of day, in local time.

    Reported in Asia/Hebron, because "usually closed at 7am" is a claim about
    somebody's morning, not about UTC.

    An hour with too few reports is returned as `unknown` rather than as a
    confident share of two observations. This is the same discipline the
    watchdog applies to feeds it cannot judge: saying "not enough to tell" is a
    result, and quietly returning a percentage computed from n=2 is not.
    """
    rows = q(PATTERN_SQL, (place_id, state_kind, days))
    hours: dict[int, dict[str, int]] = {}
    for r in rows:
        hours.setdefault(int(r["hour"]), {})[r["value"]] = int(r["n"])

    out = []
    for h in range(24):
        counts = hours.get(h, {})
        total = sum(counts.values())
        if total < min_reports:
            out.append({"hour": h, "reports": total, "usually": "unknown",
                        "why": f"only {total} reports in {days} days"})
            continue
        top, n = max(counts.items(), key=lambda kv: kv[1])
        out.append({"hour": h, "reports": total, "usually": top,
                    "share": round(n / total, 2), "counts": counts})

    known = [h for h in out if h["usually"] != "unknown"]
    return {
        "place_id": place_id, "state_kind": state_kind, "days": days,
        "timezone": "Asia/Hebron",
        "hours": out,
        "hours_with_enough_data": len(known),
        "note": ("A pattern is what was REPORTED at that hour, not what was "
                 "true — nobody reports a quiet checkpoint at 3am, so sparse "
                 "hours mean sparse attention, not calm."),
    }
