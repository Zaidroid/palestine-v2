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

import functools

import json
import logging
import os
import sys
import threading
import time
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from resolve.db import dsn, env_value

log = logging.getLogger("serve.app")

# .env is the source of truth (ops/sync-valhalla-ip.sh keeps it current);
# no hardcoded IP fallback — a wrong default is worse than a loud miss.
VALHALLA = env_value("VALHALLA_URL", "http://wb-valhalla:8002")


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


# ── the answers that re-aggregate the whole databank, remembered ─────────────
#
# /v2/databank/categories groups 206k serving rows per call — 1,119 ms measured
# 2026-09-22 — and it is the most-called public route. /v2/databank/{category}
# is the same shape over the same view. The databank changes once a night, so
# the identical answer was being rebuilt thousands of times a day.
#
# The key is the databank, not the clock:
#   * `ops/databank-runs.ndjson` (mtime, size) is free to stat and is appended
#     by every load, so a nightly sync invalidates this immediately;
#   * `max(upper(sys_period))` on `observation` is the authoritative watermark
#     the plan names, and costs ~380 ms, so it is re-read at most every
#     WATERMARK_SECONDS rather than per request;
#   * CACHE_TTL_SECONDS bounds the age of any answer regardless of both.
# `as_of` NEVER routes through here: a historical answer must not be served
# from a cache keyed on the present, so those callers keep the plain `q`.
DATABANK_RUNS = Path(__file__).resolve().parent.parent / "ops" / "databank-runs.ndjson"
CACHE_TTL_SECONDS = 60
WATERMARK_SECONDS = 300
# F-84: BOUNDED, because the key includes the caller's parameters. A stranger
# varying `limit` (1..2000), `indicator` or `days` mints a new cache entry per
# request, and one entry can hold 276 KB of rows (`limit=2000` measured), so the
# cache was an unbounded memory growth vector with a trivial trigger. 400 entries
# covers every aggregate route this API has, several times over; beyond that the
# least recently used is evicted, and a miss just costs a query. OrderedDict so a
# hit can refresh recency — a plain dict cannot move a key to the end.
QUERY_CACHE_MAX = 400
_QUERY_CACHE: "OrderedDict[tuple, tuple]" = OrderedDict()
_WATERMARK: dict[str, Any] = {"at": 0.0, "value": None}
_WATERMARK_LOCK = threading.Lock()



def _runs_stamp() -> tuple:
    try:
        st = DATABANK_RUNS.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def _databank_watermark() -> str:
    now = time.monotonic()
    if _WATERMARK["value"] is None or now - _WATERMARK["at"] > WATERMARK_SECONDS:
        # F-84: ONE reader, not N. Without this lock every concurrent request
        # that finds the watermark stale runs the same ~380 ms aggregate at the
        # same moment, so a burst of callers multiplies the most expensive query
        # on the cheapest path — the thundering herd lands exactly when the
        # server is busiest. Double-checked so the waiters reuse the winner's
        # value instead of queueing up to each re-read it.
        with _WATERMARK_LOCK:
            if (_WATERMARK["value"] is None
                    or time.monotonic() - _WATERMARK["at"] > WATERMARK_SECONDS):
                rows = q("SELECT max(upper(sys_period))::text AS w FROM observation")
                _WATERMARK["value"] = (rows[0]["w"] if rows else "") or ""
                _WATERMARK["at"] = time.monotonic()
    return _WATERMARK["value"]


# THE CACHE IS SHARED BY ~40 THREADPOOL THREADS, so its structure is locked.
# Unlocked, thread A could find key K, thread B could insert a new key and
# evict K as least recently used, and A's `move_to_end(K)` raised KeyError —
# a 500 on a route whose answer was sitting in memory. The lock covers only
# dictionary operations; the query itself runs outside it.
_CACHE_LOCK = threading.Lock()
# SINGLE-FLIGHT, one level below the watermark's. When a key goes cold, ten
# concurrent callers used to run ten identical multi-second aggregates, each on
# its own connection — the thundering herd _WATERMARK_LOCK was written to stop,
# one call deeper. Striped rather than one lock per key so the lock table is
# bounded no matter how many parameter combinations a caller invents; two keys
# sharing a stripe only wait for each other, which is slower, never wrong.
_FILL_LOCKS = tuple(threading.Lock() for _ in range(64))


def _cache_hit(key: tuple, stamp: tuple) -> tuple | None:
    with _CACHE_LOCK:
        entry = _QUERY_CACHE.get(key)
        if (entry and entry[0] == stamp
                and (time.monotonic() - entry[1]) < CACHE_TTL_SECONDS):
            _QUERY_CACHE.move_to_end(key)      # a hit refreshes recency
            return entry
    return None


def q_cached_at(sql: str, params: tuple = ()) -> tuple[list[dict], datetime]:
    """`q_cached`, plus WHEN the rows were read — for an answer that states its
    own age (`insights.as_of`) rather than the time it was sent."""
    # A dict of named parameters is not hashable and must still key the cache:
    # `insights` passes %(lat)s-style params, and a TypeError here would 500 the
    # route rather than miss the cache. Lists (the scan's `= ANY(%(inds)s)`)
    # are frozen the same way.
    def _freeze(v):
        return tuple(_freeze(x) for x in v) if isinstance(v, (list, tuple)) else v
    key = (sql, tuple((k, _freeze(v)) for k, v in sorted(params.items()))
           if isinstance(params, dict) else _freeze(params))
    stamp = (_runs_stamp(), _databank_watermark())
    entry = _cache_hit(key, stamp)
    if entry is None:
        with _FILL_LOCKS[hash(key) % len(_FILL_LOCKS)]:
            # Double-checked: a caller that waited reuses the winner's rows.
            entry = _cache_hit(key, stamp)
            if entry is None:
                rows = q(sql, params)
                entry = (stamp, time.monotonic(), rows, datetime.now(timezone.utc))
                with _CACHE_LOCK:
                    _QUERY_CACHE[key] = entry
                    _QUERY_CACHE.move_to_end(key)
                    while len(_QUERY_CACHE) > QUERY_CACHE_MAX:
                        _QUERY_CACHE.popitem(last=False)   # evict least recently used
    built = entry[3] if len(entry) > 3 else datetime.now(timezone.utc)
    return entry[2], built


def q_cached(sql: str, params: tuple = ()) -> list[dict]:
    """`q` with a memory, for the aggregates that read the whole databank."""
    return q_cached_at(sql, params)[0]


@app.get("/health")
def health(request: Request,
           verbose: bool = Query(True, description="include the per-check detail")) -> dict:
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
    from serve.ratelimit import client_ip, is_local
    local = is_local(client_ip(request))

    # THE DATABASE PROBE IS A PROBE. It used to be two fuel queries, one of them
    # on `state_current` — the only read of it in serve/, against the module's
    # own contract and HANDOFF rule 6 — for `feed_age_minutes`, the age of the
    # fuel feed retired on purpose on 2026-09-23 (070). That number grew by
    # 1,440 a day beside `status: ok` and meant nothing; the feeds' real
    # judgement is `feeds_ok/feeds_total`. Both fuel fields are gone.
    try:
        q("SELECT 1 AS ok")
    except Exception as e:                              # noqa: BLE001
        # The exception names the host, port and database user. A stranger
        # polling /health during an outage learned where to push next; the
        # detail is for local callers (and the journal) only.
        log.warning("health: database probe failed: %s", e)
        raise HTTPException(503, "database unavailable" + (f": {e}" if local else ""))

    try:
        from ops.watchdog import feed_checks, job_checks
        jobs = job_checks()
        feeds = feed_checks(jobs)                       # cached cadence
        faults = [c for c in jobs + feeds if c["fault"]]
    except Exception as e:                              # noqa: BLE001
        # The checks failing must not take down the endpoint that reports
        # health — but it must not report health it could not establish
        # either, so this is surfaced rather than swallowed into an "ok".
        log.warning("health: checks unavailable: %s", e)
        return {"status": "unknown",
                "error": "health checks unavailable" + (f": {e}" if local else "")}

    out: dict[str, Any] = {
        "status": "degraded" if faults else "ok",
        # The named list is the same internal detail `checks` withholds below —
        # "job:maintain failing" names a job a stranger has no business knowing
        # exists, and a list of what is currently broken is a map of where to
        # push. The COUNT stays public alongside the status, so a degraded
        # system still cannot be mistaken for a healthy one.
        "faults": [f"{c['check']}:{c['name']} {c['status']}" for c in faults] if local else [],
        "faults_total": len(faults),
        "jobs_ok": sum(1 for c in jobs if not c["fault"]),
        "jobs_total": len(jobs),
        "feeds_ok": sum(1 for c in feeds if not c["fault"]),
        "feeds_total": len(feeds),
    }
    # The per-check detail names internal jobs and the absolute paths of the
    # upstream files this system reads. That is exactly what an operator needs
    # and exactly what a stranger does not, so once the API is reachable from
    # outside it is answered only for local callers. The COUNTS stay public:
    # "13 of 13 jobs healthy" is a useful public promise, and hiding it would
    # make a degraded system look identical to a healthy one.
    if verbose and local:
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


# ── fuel availability: RETIRED 2026-09-23 ────────────────────────────────────
# Zaid: "fuel is not an issue to track anymore, lets change that to track live
# updated prices of fuel in palestine". The vertical's last source was one
# Telegram channel's rendered cards — measured once (0.957, every error a false
# "available") and not re-measurable after its text feed died on 2026-08-28.
# Its collectors were stopped 2026-09-23 07:40 UTC (migration 070).
#
# WHY 410 AND NOT A DELETED ROUTE. A caller that asked "where is diesel" must
# not get a 404 that reads as a typo, and must never get a 200 whose stations
# all decayed to `unknown` — that answer reads as "no station has diesel",
# which is a claim this system can no longer make either way. 410 says the
# question itself is retired, and the body says what replaced it. The 848k
# availability observations stay in the database (070 deleted nothing).
FUEL_AVAILABILITY_RETIRED = {
    "retired": "2026-09-23",
    "what": "Per-station fuel availability (which station has diesel/petrol now).",
    "why": ("Its last source was one Telegram channel's rendered cards: measured "
            "once, with every error a false 'available', and impossible to "
            "re-measure after the channel's text feed stopped on 2026-08-28."),
    "replacement": "/v2/fuel/prices",
    "history": "Past availability observations are retained in the database; nothing was deleted.",
}


def fuel_availability_retired() -> JSONResponse:
    return JSONResponse(FUEL_AVAILABILITY_RETIRED, status_code=410)


FUEL_RETIRED_PATHS = ("/v2/fuel/nearby", "/v2/fuel/stations", "/v2/fuel/summary",
                      "/v2/export/fuel.csv")
for _path in FUEL_RETIRED_PATHS:
    app.add_api_route(_path, fuel_availability_retired, methods=["GET"],
                      tags=["fuel"], include_in_schema=False)


# ── fuel PRICES: the official monthly maximum (071-073) ─────────────────────
# What replaced availability. The Petroleum Corporation's maximum consumer
# price for the West Bank, read from the outlets that repost it
# (ingest/sources/fuel_prices.py) and believed only when two independent
# outlets agree (db/migrations/071-073). It is a regulated CEILING for the West
# Bank, not a pump price and not Gaza's; the response says so every time.
FUEL_PRICE_SCOPE = {
    "what": "Official maximum consumer price, set monthly by the Palestinian "
            "General Petroleum Corporation (Ministry of Finance).",
    "where": "West Bank. Gaza has no official consumer fuel price.",
    "not": "Not a pump price: stations may sell below the ceiling, and a "
           "station charging above it is breaking the published maximum.",
    "belief": "A price is served only when two independent outlets report the "
              "same number for the same start date, at least one of them naming "
              "the Petroleum Corporation, and nobody credible reports another.",
}
FUEL_PRICE_ATTRIBUTION = ("Palestinian General Petroleum Corporation, as reported by "
                          "Palestinian news outlets (sources listed per price)")


@app.get("/v2/fuel/prices", tags=["fuel"])
def fuel_prices(product: str | None = None) -> dict:
    """Today's official fuel prices, one row per product.

    `price` is null unless the newest list for that product is confirmed and
    was set for the current month. `status` says why when it is null:
    `unconfirmed` (one outlet so far), `conflicting` (outlets disagree),
    `awaiting_list` (the month has turned and no new list has been read yet),
    `no_data`. `reported` always shows what the outlets said, and
    `last_confirmed_price` the last price that was confirmed, with its date.
    """
    rows = q("""SELECT product, name_ar, name_en, unit, status, price, effective_from,
                       newest_list, outlets_agreeing, source_urls, reported,
                       last_confirmed_price, last_confirmed_from, as_of_date
                  FROM fuel_price_current
                 WHERE %s::text IS NULL OR product = %s::text
                 ORDER BY sort""", (product, product))
    if product and not rows:
        raise HTTPException(404, f"unknown product {product!r}")
    for r in rows:
        r["price"] = float(r["price"]) if r["price"] is not None else None
        r["last_confirmed_price"] = (float(r["last_confirmed_price"])
                                     if r["last_confirmed_price"] is not None else None)
    return {"scope": FUEL_PRICE_SCOPE, "as_of_date": rows[0]["as_of_date"] if rows else None,
            "prices": rows, "attribution": FUEL_PRICE_ATTRIBUTION}


@app.get("/v2/fuel/prices/history", tags=["fuel"])
def fuel_price_history(product: str | None = None,
                       include_unconfirmed: bool = Query(
                           False, description="also list prices only one outlet reported")) -> dict:
    """Every list read, oldest first: the confirmed price per start date, and
    optionally the single-outlet readings beside them, marked as such."""
    rows = q("""SELECT v.effective_from, v.product, p.unit, v.price, v.units AS outlets,
                       v.outlets AS sources, v.urls,
                       EXISTS (SELECT 1 FROM fuel_price_believed b
                                WHERE b.effective_from = v.effective_from
                                  AND b.product = v.product AND b.price = v.price) AS confirmed
                  FROM fuel_price_votes v JOIN fuel_price_product p USING (product)
                 WHERE (%s::text IS NULL OR v.product = %s::text)
                 ORDER BY v.effective_from, p.sort, v.units DESC""", (product, product))
    rows = [dict(r, price=float(r["price"])) for r in rows
            if include_unconfirmed or r["confirmed"]]
    return {"scope": FUEL_PRICE_SCOPE, "history": rows, "attribution": FUEL_PRICE_ATTRIBUTION}


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

# THE GATE A NAME MUST CLEAR BEFORE THIS API SPEAKS FOR A CHECKPOINT. Below it
# the match is the nearest-looking name, not the one the caller wrote: "Zatara"
# reached عطارة (11 km away, the opposite state) through the substring tier at
# 0.738, "Hawara" reached عورتا at 0.707, and "عين" reached whichever of the
# عين-checkpoints had the most reports. The doubt sentence lived only in the MCP
# layer (mcp_server.checkpoint_status), so a REST partner got `found: true` and
# the WRONG checkpoint's flow with a score it had no instruction to read, and
# the MCP place profile spoke the flow without reading the score at all. A
# guess is now `found: false` with the guess named under `nearest`, and no
# flow: refusing is recoverable, a confident wrong junction is not. Exact
# names, 074-style aliases and folded spellings ("حاجز حوارة") score 0.90+ and
# are unaffected; containment (0.70) and fuzzy (≤ 0.80) never clear it alone.
CHECKPOINT_MATCH_GATE = 0.80


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
    from resolve.geo import _token_match

    n, f = normalize(name), fold_for_match(name)
    if not n:
        return None
    # CACHED, AND ASSERTIONS ONLY. The candidate table used to aggregate every
    # checkpoint_flow observation ever stored — a growing hypertable scan on the
    # hottest safety route, every call — for a tie-break worth at most 0.04.
    # The rows change when a place, an alias or the report count changes, none
    # of which a minute of staleness can hurt. And the count now reads only
    # `modality = 'assertion'`: palhub's ~72k quarantined rows a week "must not
    # move a value", and they were deciding which of two same-named checkpoints
    # a caller meant.
    rows = q_cached("""
        SELECT p.place_id, p.name_ar, p.name_en,
               COALESCE(o.n, 0) AS obs,
               COALESCE(array_agg(a.alias_norm) FILTER (WHERE a.alias_norm IS NOT NULL),
                        ARRAY[]::text[]) AS aliases
        FROM place p
        LEFT JOIN place_alias a ON a.place_id = p.place_id
        LEFT JOIN (SELECT place_id, COUNT(*) n FROM state_observation
                   WHERE state_kind = 'checkpoint_flow' AND modality = 'assertion'
                   GROUP BY 1) o ON o.place_id = p.place_id
        WHERE p.servable AND p.kind IN ('checkpoint','crossing','road')
        GROUP BY p.place_id, p.name_ar, p.name_en, o.n""")

    best, best_score, best_rank = None, 0.0, -1.0
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
        # WHOLE WORDS ONLY. A bare substring test put "atara" inside "zatara"
        # and "بيت" inside every بيت-name; containment is only evidence when
        # one side is a run of whole words of the other.
        elif any(_token_match(x, n) or _token_match(n, x) for x in norms if x):
            score = 0.70
        else:
            score = max((SequenceMatcher(None, n, x).ratio() for x in norms if x),
                        default=0.0)
            if score < 0.78:
                continue
            score *= 0.8
        # Evidence breaks ties: among equally-named candidates the one people
        # actually report about is the one they mean. It RANKS; it is not part
        # of the served score, which is how well the NAME matched — so an
        # exact name reads 1.0, never the 1.04 the audit found.
        rank = score + min(r["obs"], 5000) / 5000 * 0.04
        if rank > best_rank:
            best, best_score, best_rank = r, score, rank
    if not best:
        return None
    return {"place_id": best["place_id"],
            "name": best["name_ar"] or best["name_en"],
            "score": round(min(1.0, best_score), 3),
            "confident": best_score >= CHECKPOINT_MATCH_GATE}


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
        ORDER BY straight_km ASC""", (lon, lat, direction, lon, lat, radius_km * 1000))
    # No row cap before the counts: `in_radius`, `unknown` and `closed` were
    # computed over the 200 nearest, so a 100 km query (the whole West Bank)
    # reported in_radius 200 and a closed count that stopped there. A
    # direction holds one row per checkpoint — a few hundred at most — and
    # only `results` is trimmed to `limit`.

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
    # Bounded: the name is matched against every candidate with SequenceMatcher,
    # so an unbounded string was a per-request CPU cost the caller chose.
    name: str = Query(..., min_length=2, max_length=120,
                      description="Arabic or English checkpoint name"),
    direction: str = Query("both", description="inbound | outbound | both"),
) -> dict:
    """Status of one named checkpoint.

    Resolution runs against every spelling ever seen, including those of merged
    duplicates (migration 013) — the misspelling in an incoming message is
    exactly the string that needs to resolve.

    A name that only resembles a checkpoint (score below CHECKPOINT_MATCH_GATE)
    answers `found: false` with the resemblance under `nearest` and NO flow.
    """
    if direction not in ("inbound", "outbound", "both"):
        raise HTTPException(400, "direction must be inbound, outbound or both")
    m = _resolve_checkpoint(name)
    if not m:
        return {"found": False, "query": name}
    if not m["confident"]:
        return {"found": False, "query": name, "uncertain": True,
                "nearest": {"place_id": m["place_id"], "name": m["name"],
                            "score": m["score"]},
                "reason": ("no checkpoint has this name; the nearest-looking one "
                           "is named under `nearest` and its status is NOT given, "
                           "because a lookalike name is not the checkpoint asked "
                           "about. Ask again with the full or the Arabic name.")}
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


# Worst first. A place's summary reading is the WORST current reading across
# its three direction rows, and `unknown` only when no direction is known: a
# summary may never present a place as better than its worst known direction.
_FLOW_SEVERITY = {"closed": 4, "congested": 3, "slow": 2, "open": 1}
CLOSED_NOW_MAX = 40


def _summarise_checkpoints(rows: list[dict]) -> dict:
    """Fold checkpoint_serving's per-direction rows into one reading per PLACE.

    The summary used to read `direction='both'` only, and in checkpoint_serving
    the 'both' row holds UNDIRECTED reports alone (027: `s.direction = t.dir OR
    s.direction = 'both'` with t.dir = 'both'). So a checkpoint reported
    'دخول 🔴 خروج 🟢' — closed inbound, fresh — never reached `closed_now`, the
    list a person scans before leaving, and a place with only directional
    readings was missing from `tracked` altogether. Absence from that list reads
    as safety. Pure, so the fold is tested without a database.
    """
    by_place: dict[Any, list[dict]] = {}
    for r in rows:
        by_place.setdefault(r["place_id"], []).append(r)

    totals: dict[str, int] = {}
    by_staleness: Counter = Counter()
    presence: Counter = Counter()
    closed: list[dict] = []
    for pid, rs in by_place.items():
        known = [r for r in rs if r["flow"] in _FLOW_SEVERITY]
        if known:
            worst = max(_FLOW_SEVERITY[r["flow"]] for r in known)
            # Among the rows carrying the worst flow, the undirected one
            # speaks for the place when it agrees, else the freshest.
            pick = sorted((r for r in known if _FLOW_SEVERITY[r["flow"]] == worst),
                          key=lambda r: (r["direction"] != "both",
                                         r["age_minutes"] if r["age_minutes"] is not None
                                         else float("inf")))[0]
        else:
            pick = next((r for r in rs if r["direction"] == "both"), rs[0])
        flow = pick["flow"] if known else "unknown"
        totals[flow] = totals.get(flow, 0) + 1
        by_staleness[f"{flow}/{pick['staleness_band']}"] += 1
        for who in {w for r in rs for w in (r["present"] or [])}:
            presence[who] += 1
        if flow == "closed":
            closed.append(_checkpoint_out(pick, {
                # Which directions are closed, said — "closed inbound" and
                # "closed both ways" are different journeys.
                "closed_directions": sorted(r["direction"] for r in rs
                                            if r["flow"] == "closed")}))
    closed.sort(key=lambda c: c["age_minutes"] if c["age_minutes"] is not None
                else float("inf"))
    tracked = sum(totals.values())
    return {
        "tracked": tracked,
        "totals": totals,
        # Stated explicitly rather than left to be inferred from the totals.
        "known_fraction": round(1 - totals.get("unknown", 0) / tracked, 3) if tracked else 0.0,
        "by_staleness": dict(by_staleness),
        "presence": dict(presence.most_common()),
        "closed_now": closed[:CLOSED_NOW_MAX],
        "counting_note": ("one reading per checkpoint: the worst current flow "
                          "across its inbound, outbound and undirected readings. "
                          "A checkpoint closed in one direction counts as closed "
                          "and `closed_directions` names which."),
        "attribution": CHECKPOINT_ATTRIBUTION,
    }


@app.get("/v2/checkpoints/summary", tags=["checkpoints"])
def checkpoints_summary() -> dict:
    """West-Bank-wide picture, including how much of it we do NOT know.

    One read of checkpoint_serving (it used to be three), folded per place in
    `_summarise_checkpoints`."""
    return _summarise_checkpoints(q(f"SELECT {CHECKPOINT_COLS} FROM checkpoint_serving c"))


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
        SELECT p.name_ar, p.name_en, s.value, s.observed_at, s.age_minutes,
               s.staleness_band, o.attrs
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
                               "url": (r["attrs"] or {}).get("url"),
                               # The serving contract, as on every other state
                               # row: a notice read days ago and one read this
                               # morning must not look the same.
                               "observed_at": r["observed_at"],
                               "age_minutes": r["age_minutes"],
                               "staleness_band": r["staleness_band"]} for r in power],
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
    # The attribution is READ from the source registry, never typed here. It used
    # to say "CC BY-NC 4.0", which was an assumption recorded with no terms_url
    # and no evidence (migration 053's own note). Migration 067 read IODA's API
    # and found a copyright line on every response with no grant of any kind, so
    # the registry says All Rights Reserved and `redistribution = 'ask'`. A
    # hardcoded string cannot follow that, and this one did not: the payload
    # contradicted its own licence block until 2026-09-24.
    src = q_cached("""SELECT attribution_text, license_spdx, redistribution
                        FROM source WHERE key = 'ioda'""")
    return {"region": r["name_en"], "status": r["value"],
            "observed_at": r["observed_at"], "age_minutes": r["age_minutes"],
            "staleness_band": r["staleness_band"],
            "confidence": round(float(r["confidence"]), 3),
            "signals_agreeing": r["independent_sources"],
            "signals": (r["attrs"] or {}).get("signals"),
            "method": (r["attrs"] or {}).get("method"),
            "attribution": (src[0]["attribution_text"] if src else
                            "Internet outage detection: IODA, Georgia Tech"),
            "license": (src[0]["license_spdx"] if src else None),
            "redistribution": (src[0]["redistribution"] if src else None)}


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
    into "no raid". `occurred_precision` is 'hour' for news events because the
    timestamp is when the channel POSTED, not when the incident happened;
    satellite fire detections carry their own ('exact').

    `independent_sources` counts independence GROUPS, so channels that mirror
    each other cannot inflate it — the same rule the checkpoint layer uses.
    """
    # Both or neither: with one of the pair missing, ST_MakePoint was NULL, so
    # ST_DWithin excluded every row and the answer was "0 incidents" — which
    # reads as a quiet area rather than a malformed question.
    if (lat is None) != (lon is None):
        raise HTTPException(400, "give both `lat` and `lon`, or neither")
    want = [t.strip() for t in types.split(",")] if types else None
    rows = q("""
        SELECT e.event_id, e.event_type, e.occurred_at, e.confidence,
               e.occurred_precision::text AS occurred_precision,
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
            # WHAT THE CHANNEL NAMED, AND HOW THE PIN WAS EARNED. `place` above
            # is where the gazetteer located the event, which for an
            # unresolvable village is its GOVERNORATE — the centroid of Ramallah
            # for something that happened in المزرعة الغربية, or of al-Bireh for
            # بيت عور. `place_precision` says which of the two answered, and
            # `named_place` carries the village as the message wrote it, so a
            # reader is never told an incident happened in a city it did not.
            "named_place": (r["attrs"] or {}).get("place_text"),
            "place_precision": (r["attrs"] or {}).get("place_precision") or "named",
            "lat": r["lat"], "lon": r["lon"],
            "straight_km": round(float(r["straight_km"]), 1) if r["straight_km"] is not None else None,
            "occurred_at": r["occurred_at"],
            # Stated, not implied — and READ, not typed: a news event is stored
            # 'hour' (its time is when the channel posted), while a satellite
            # detection carries its real acquisition time as 'exact'. The
            # constant 'hour' told the second it was a posting time.
            "occurred_precision": r["occurred_precision"],
            "confidence": round(float(r["confidence"]), 3),
            "reports": r["claim_count"],
            "independent_sources": r["independent_sources"],
            "channels": _channel_labels((r["attrs"] or {}).get("channels")),
        } for r in rows],
        "attribution": "West Bank governorate news channels (Telegram) via agent2",
    }


def _channel_labels(units) -> list[str] | None:
    """Independence units, as names a reader can recognise.

    The classifier stores each event's reporters as INDEPENDENCE UNITS —
    `COALESCE(independence_group, 'src:' || source_id)` — because that is what
    corroboration counts. `src:36` is correct there and meaningless in a
    payload: the partner audit listed it as a leak. A unit that is a bare
    source id becomes that source's key; a named group stays a group name.
    """
    if not units:
        return units
    keys = _source_keys()
    out = []
    for u in units:
        if isinstance(u, str) and u.startswith("src:") and u[4:].isdigit():
            sid = int(u[4:])
            if sid not in keys:
                keys = _source_keys(refresh=True)
            out.append(keys.get(sid, u))
        else:
            out.append(u)
    return out


_SOURCE_KEYS: dict[str, Any] = {"at": 0.0, "keys": None}
SOURCE_KEYS_REFRESH_SECONDS = 60


def _source_keys(refresh: bool = False) -> dict[int, str]:
    """source_id → key, re-read on a miss (at most once a minute).

    It was an lru_cache for the life of the process, so a channel subscribed
    after the API started rendered as `src:47` — the leak P0-A.4 fixed — until
    a restart only Zaid can make. A miss now re-reads the table; the minute's
    floor keeps an unknown id from turning every call into a query.
    """
    now = time.monotonic()
    if (_SOURCE_KEYS["keys"] is None
            or (refresh and now - _SOURCE_KEYS["at"] > SOURCE_KEYS_REFRESH_SECONDS)):
        _SOURCE_KEYS["keys"] = {int(r["source_id"]): r["key"]
                                for r in q("SELECT source_id, key FROM source")}
        _SOURCE_KEYS["at"] = now
    return _SOURCE_KEYS["keys"]


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
    # NAMED PLACES ONLY. An incident the classifier could pin only to a
    # governorate sat at the city centroid and was counted under the city, which
    # is why Ramallah topped every "worst affected" list (audit, 2026-09-24).
    # Those are counted apart, as what they are.
    # Grouped by PLACE, not by name: twin villages (المغير in Ramallah's and in
    # Jenin's governorate, 232 and 9 events) were summed into one "worst
    # affected" row that no caller could tell apart. The id and governorate
    # travel with the name.
    by_place = q("""SELECT p.place_id, p.name_ar, p.name_en, g.name_en AS governorate,
                           COUNT(*) n
                    FROM event e JOIN place p ON p.place_id = e.place_id
                    LEFT JOIN place g ON g.kind = 'governorate'
                                     AND g.admin2_pcode = p.admin2_pcode
                    WHERE e.status='believed'
                      AND e.occurred_at > now() - make_interval(hours => %s)
                      AND COALESCE(e.attrs->>'place_precision', 'named') = 'named'
                      AND e.event_type <> 'fire_detection'
                    GROUP BY 1,2,3,4 ORDER BY 5 DESC LIMIT 15""", (hours,))
    gov_only = q("""SELECT COUNT(*) n FROM event e
                    WHERE e.status='believed'
                      AND e.occurred_at > now() - make_interval(hours => %s)
                      AND e.attrs->>'place_precision' IN ('governorate', 'village_ambiguous')""",
                 (hours,))
    # The whole-ledger rollup changes only when the classifier timer runs, so
    # it is remembered for the cache TTL instead of rescanned per call.
    ledger = q_cached("""SELECT verdict, reject_reason, COUNT(*) n
                         FROM claim_classification GROUP BY 1,2 ORDER BY 3 DESC""")
    # Which classifier wrote the events counted here — read from the events,
    # because the version this process imported is not necessarily the one the
    # five-minute classifier timer ran (serve/quality.summary).
    versions = q("""SELECT DISTINCT e.attrs->>'classifier_version' AS v
                    FROM event e
                    WHERE e.status='believed'
                      AND e.occurred_at > now() - make_interval(hours => %s)
                      AND e.attrs ? 'classifier_version'""", (hours,))
    from serve.quality import annotate_by_type, summary as precision_summary
    types = {r["event_type"]: {"n": r["n"], "corroborated": r["corroborated"]} for r in by_type}
    fires = sum(r["n"] for r in by_type if r["event_type"] == FIRE_EVENT_TYPE)
    return {
        "window_hours": hours,
        # REPORTS ONLY. A NASA FIRMS pixel is a detection, and summing 13 of
        # them with 40 reports served "53 incidents"; the MCP tool stripped
        # them from by_type and still spoke the 53. `by_type` keeps its
        # fire_detection row (the renderers take it from there); `total` and
        # `fires` are the two numbers apart.
        "total": sum(r["n"] for r in by_type if r["event_type"] != FIRE_EVENT_TYPE),
        "fires": {"n": fires,
                  "note": "NASA FIRMS satellite fire pixels — detections, not "
                          "reports; never counted in `total`"},
        # Every count carries what the last hand-scored round measured for
        # its type (deaths first in the answer): a count from a reader that
        # is right 60 % of the time is a different fact from one at 93 %.
        "by_type": annotate_by_type(types),
        "precision": precision_summary(types, [r["v"] for r in versions]),
        "by_place": [{"place": r["name_ar"] or r["name_en"], "n": r["n"],
                      "place_id": r["place_id"], "governorate": r["governorate"]}
                     for r in by_place],
        "located_to_governorate_only": int(gov_only[0]["n"]) if gov_only else 0,
        "by_place_note": "counts incidents whose village resolved; the rest are "
                         "counted in located_to_governorate_only, never under a city",
        "classification_ledger": [{"verdict": r["verdict"],
                                   "reason": r["reject_reason"], "n": r["n"]}
                                  for r in ledger],
        "attribution": "West Bank governorate news channels (Telegram) via agent2",
    }


# How much of a message body this route will hand back at all. It is a STORAGE
# cap, not a licence decision: the partner-tier excerpt (serve/licence.py) is
# applied on top of it. Reported per item as `text_full_chars` so a reader can
# tell a short message from a truncated one — before this, the licence layer
# measured the already-capped string and every excerpted row claimed exactly
# this number as its "full" length.
NEWS_TEXT_CHARS = 500


@app.get("/v2/news/latest", tags=["news"])
def news_latest(request: Request,
                area: str | None = Query(None, max_length=80),
                limit: int = Query(10, ge=1, le=100),
                hours: int | None = Query(None, ge=1, le=720),
                # Bounded: each value becomes an ILIKE '%…%' over the claim
                # table, and a caller-sized needle is a caller-sized cost.
                text: str | None = Query(None, min_length=2, max_length=80)) -> dict:
    """Most recent ingested messages, optionally filtered by area, text, window.

    Resolving the name first is the difference between "Ramallah" returning this
    morning's reports and returning two English-language mentions from July: the
    channel text is Arabic, so a literal Latin match only ever finds the rare
    message that happens to be written in English — and it finds it, however old
    it is, which reads as a quiet area rather than a missed filter.

    Crowd reports are never news. They reach answers only through the belief
    model, where the P2.4 gate withholds a lone stranger's reassurance.
    """
    # CROWD FREE TEXT IS NOT NEWS. Every accepted crowd report is a claim
    # ('[checkpoint_flow=open] قلنديا — <note>', crowd/engine.py), and this
    # route selected every claim over 30 characters, so an unauthenticated
    # stranger's note was served as the NEWEST message and quoted into the MCP
    # `answer` that clients are told to read aloud verbatim — reassurance the
    # gate exists to withhold, and a prompt-injection channel into agents.
    # Excluded by the source's kind AND the claim's type, so neither a re-kinded
    # source nor a re-typed claim reopens the door alone.
    where = ["length(c.raw_text) > 30", "s.kind <> 'crowd'",
             "c.claim_type <> 'crowd_report'"]
    params: list = []
    if area:
        names = {area}
        try:
            from resolve.geo import resolve_place
            r = resolve_place(area, learn=False)
            if r:
                names |= {n for n in (r.name_ar, r.name_en) if n}
        except Exception:                                        # noqa: BLE001
            pass                     # an unresolvable name keeps the literal match
        where.append("c.raw_text ILIKE ANY(%s)")
        params.append([f"%{n}%" for n in names])
    if text:
        where.append("c.raw_text ILIKE %s")
        params.append(f"%{text}%")
    if hours:
        where.append("c.reported_at >= now() - make_interval(hours => %s)")
        params.append(hours)
    params.append(limit)
    rows = q(f"""
        SELECT c.raw_text, c.reported_at, s.name AS src, s.key AS src_key
        FROM claim c JOIN source s ON s.source_id = c.source_id
        WHERE {' AND '.join(where)}
        ORDER BY c.reported_at DESC LIMIT %s""", tuple(params))
    # F-81: the MCP tool over this route is not the only door — this route is
    # itself public, so a cut applied only in the MCP layer would be decoration.
    # The tier is decided here, from who is calling, and the MCP layer then sees
    # an already-honest payload.
    from serve import licence as L
    from serve.ratelimit import client_ip, is_local
    tier = "house" if is_local(client_ip(request)) else "partner"
    out = {"count": len(rows), "area": area,
           "items": [{"text": " ".join(r["raw_text"].split())[:NEWS_TEXT_CHARS],
                      "text_full_chars": len(" ".join(r["raw_text"].split())),
                      "source": r["src"], "source_key": r["src_key"],
                      "reported_at": r["reported_at"]} for r in rows]}
    return L.apply("latest_news", out, tier)


@app.get("/v2/coverage", tags=["meta"])
def coverage() -> dict:
    """What this system currently holds — so an agent can answer honestly about
    the limits of its own knowledge instead of implying total coverage.

    Measured 2,695 ms before 2026-09-23 (the source/claim rollup scans every
    claim ever ingested) and this is the FIRST call a new client makes, which is
    the worst possible place to look slow. Cached like the databank aggregates:
    same TTL, same invalidation, so a fresh ingest is visible within a minute.
    """
    src = q_cached("""SELECT s.name, s.key, COUNT(c.*) AS claims, MAX(c.reported_at) AS newest
               FROM source s LEFT JOIN claim c ON c.source_id = s.source_id
               GROUP BY 1,2 HAVING COUNT(c.*) > 0 ORDER BY 3 DESC""")
    st = q_cached("""SELECT s.state_kind, COUNT(*) AS n,
                            (k.retired_at IS NOT NULL) AS retired
                       FROM state_serving s
                       LEFT JOIN state_kind_config k USING (state_kind)
                      GROUP BY 1, 3 ORDER BY 2 DESC""")
    pl = q_cached("SELECT kind::text AS kind, COUNT(*) AS n FROM place GROUP BY 1 ORDER BY 2 DESC")
    # `live_states` is built from state_serving, so a field with no data at all
    # simply DOES NOT APPEAR — the blind spot is invisible in the very endpoint
    # whose job is to describe the blind spots. `fields` lists every configured
    # kind whether or not anything feeds it (migration 036).
    fields = q_cached("""SELECT c.state_kind, c.coverage_state, c.no_source,
                         c.crowd_reportable, c.observations, c.non_crowd_sources,
                         c.last_observed_at, k.retired_at IS NOT NULL AS retired
                    FROM state_kind_coverage c
                    LEFT JOIN state_kind_config k USING (state_kind)
                   ORDER BY c.coverage_state, c.state_kind""")
    return {"sources": [{"name": r["name"], "key": r["key"], "claims": r["claims"],
                         "newest": r["newest"]} for r in src],
            "total_claims": sum(r["claims"] for r in src),
            "live_states": {r["state_kind"]: r["n"] for r in st if not r["retired"]},
            # Retired on purpose (fuel availability, 2026-09-23) is not the same
            # as gone quiet, and calling it live made coverage contradict a
            # working fuel-prices feature.
            "retired_states": {r["state_kind"]: r["n"] for r in st if r["retired"]},
            "grain_note": ("`checkpoint_status` is the legacy kind that carries "
                           "presence words (`idf`, `police`) in the same column as "
                           "flow; `checkpoint_flow` is the flow grain every flow "
                           "answer is built on."),
            "places": {r["kind"]: r["n"] for r in pl},
            # A retired kind is not a stale kind. Fuel availability was
            # retired on purpose (its monitoring went with it), and reporting it
            # as `stale` made coverage contradict a live fuel-prices feature.
            "fields": [{**dict(r),
                        **({"coverage_state": "retired"} if r.get("retired") else {})}
                       for r in fields],
            "field_states": {
                "live": "a source is feeding this and the last reading is "
                        "within its assert ceiling",
                "stale": "a source exists but has gone quiet past the ceiling — "
                         "everything reads unknown until it speaks again",
                "crowd_only": "no non-crowd source has ever reported this. A "
                              "lone crowd unit cannot clear the P2.4 gate on a "
                              "reassuring value, so in practice this field can "
                              "raise cautions but not give all-clears",
                "never_reported": "NOTHING reports this to us, ever. Not quiet "
                                  "— absent. Do not render this as 'unknown' "
                                  "alongside fields that are merely quiet",
            }}


@app.get("/v2/geo/resolve", tags=["meta"])
def geo_resolve(q_: str = Query(..., alias="q", min_length=2),
                state_kind: str | None = Query(
                    None, description="resolve to the place kind this field's "
                                      "data actually lives on")) -> dict:
    """Resolve a free-text Arabic/English place name to coordinates.

    Exposed so the MCP layer (and any agent) can turn "نابلس" into a lat/lon
    without needing database access or its own copy of the gazetteer.

    PASS `state_kind` WHEN YOU MEAN A CHECKPOINT OR A STATION. Without it,
    "حوارة" resolves to the TOWN — and every channel report about that
    checkpoint sits on a different row, so a history or pattern query comes
    back empty while looking perfectly healthy. The crowd engine hit this
    first; the resolver is now shared so both cannot drift.
    """
    from resolve.geo import resolve_for_state_kind, resolve_place
    if state_kind:
        from resolve.db import connect
        from resolve.geo import _Ambiguous
        try:
            with connect() as conn:
                r = resolve_for_state_kind(conn, q_, state_kind)
        except _Ambiguous as amb:
            return {"found": False, "query": q_, "ambiguous": True,
                    "options": [{"place_id": pid, "name": n} for pid, n in amb.options],
                    "note": "more than one place of that kind has this name — "
                            "ask again with the fuller name"}
    else:
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
    # Attach coverage so a reporter can see WHY their report matters. Four of
    # these fields (power, water, cooking_gas, crossing_status) have never had a
    # single observation from anyone — a report against those is not
    # corroborating a feed, it is the only thing there is.
    # Cached: state_kind_coverage counts every observation ever stored (036),
    # and its answer — never_reported / crowd_only / live — changes when a
    # source is added or a ceiling passes, not per page load of a form.
    cov = {r["state_kind"]: r for r in q_cached(
        "SELECT state_kind, coverage_state, no_source FROM state_kind_coverage")}
    for k in kinds:
        c = cov.get(k.get("state_kind"))
        if c:
            k["coverage_state"] = c["coverage_state"]
            k["no_source"] = c["no_source"]
    return {
        "fields": kinds,
        "count": len(kinds),
        "sourceless": sorted(k["state_kind"] for k in kinds
                             if k.get("coverage_state") == "never_reported"),
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
    # Bounded: the note is stored (immutable) on every accepted report, and an
    # unbounded one let a stranger file kilobytes of text per report.
    note: str = Query("", max_length=500,
                      description="optional free text, kept, never parsed"),
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


_PENDING: dict[str, Any] = {"at": 0.0, "rows": None}
_PENDING_LOCK = threading.Lock()


def _withheld_by_gate() -> list[dict]:
    """blocked_by_gate(), remembered for CACHE_TTL_SECONDS.

    It re-derives corroboration with the belief SQL over every crowd kind's
    window — the work the crowd timer does every two minutes — and this public
    read route ran it per request, 120 times a minute per address. One thread
    computes; the rest read its answer.
    """
    with _PENDING_LOCK:
        if (_PENDING["rows"] is None
                or time.monotonic() - _PENDING["at"] >= CACHE_TTL_SECONDS):
            from resolve.belief import blocked_by_gate
            _PENDING["rows"] = blocked_by_gate()
            _PENDING["at"] = time.monotonic()
        return _PENDING["rows"]


@app.get("/v2/crowd/pending", tags=["crowd"])
def crowd_pending() -> dict:
    """Reports the P2.4 gate is currently withholding, and what they need.

    A gate that silently drops things is indistinguishable from a gate that is
    not working. This is how you check it is doing something — and how a
    submitter can be told their report is waiting for a second witness rather
    than lost.
    """
    rows = _withheld_by_gate()
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


# ── insights: the question a person actually asks (2026-09-23, W8) ───────────
# "Give me quick insights about checkpoint status last month around Ramallah."
# Nothing answered that: /v2/history/area rolls up to GOVERNORATE, /v2/history/
# place and /v2/patterns/place need one exact place, /v2/checkpoints/summary is
# a national snapshot, /v2/incidents/recent is a list. The partner's own example
# needed a radius, a window and a reduction — which meant the caller fetching
# hundreds of rows and averaging them itself, the exact step where an agent
# invents a summary.
#
# So the reduction happens here, once, with the caveats attached. Two things it
# gets right on purpose: the flow distribution reads `checkpoint_flow` with
# direction='both' (checkpoint_status is a legacy kind that mixes flow words
# with presence words like `idf`, so counting it mixes two axes into one
# histogram), and presence stays a SEPARATE block because a sighting is not a
# state — empty means "not sighted", never "not there".
INSIGHTS_CKPT_SQL = """
WITH anchor AS (
  SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography AS g),
near AS MATERIALIZED (
  -- The radius holds every kind of place — 591 of them around Ramallah, of
  -- which 33 report flow. Driving the scan from `place` therefore fetched 18x
  -- the rows it needed (820 ms measured). state_serving already holds exactly
  -- the places that have ever had a reading, so it drives instead.
  SELECT DISTINCT s.place_id, p.name_ar
    FROM state_serving s
    JOIN place p ON p.place_id = s.place_id
    CROSS JOIN anchor a
   WHERE s.state_kind = 'checkpoint_flow'
     AND ST_DWithin(p.centroid, a.g, %(radius_m)s)),
win AS MATERIALIZED (
  SELECT o.place_id, n.name_ar, o.value, o.observed_at
    FROM near n
    JOIN state_observation o
      ON o.place_id = n.place_id
   WHERE o.state_kind = 'checkpoint_flow'
     AND o.direction = 'both'
     AND o.modality = 'assertion'
     AND o.observed_at >= now() - make_interval(days => %(days)s)),
now_rows AS (
  SELECT s.place_id, s.name_ar, s.value, s.age_minutes
    FROM state_serving s JOIN near n ON n.place_id = s.place_id
   WHERE s.state_kind = 'checkpoint_flow' AND s.direction = 'both'),
dirs AS (
  SELECT o.direction::text AS direction, count(*) AS n
    FROM near n JOIN state_observation o ON o.place_id = n.place_id
   WHERE o.state_kind = 'checkpoint_flow' AND o.modality = 'assertion'
     AND o.observed_at >= now() - make_interval(days => %(days)s)
   GROUP BY 1),
presence AS (
  SELECT o.state_kind, o.value, count(*) AS n
    FROM near n JOIN state_observation o ON o.place_id = n.place_id
   WHERE o.state_kind IN ('checkpoint_idf', 'checkpoint_inspection',
                          'checkpoint_police', 'checkpoint_settlers')
     AND o.observed_at >= now() - make_interval(days => %(days)s)
   GROUP BY 1, 2)
SELECT
  -- `places_in_window` (readings inside the window) and `places_now` (a current
  -- serving row at all) are DIFFERENT UNIVERSES and must not be printed as one.
  -- Measured 2026-09-24 around Ramallah: 52 in the window against 63 tracked
  -- now, while the prose said "52 checkpoints" and then "31 have a definite
  -- reading … 32 do not" — 31+32=63, so the sentence contradicted the number in
  -- front of it. Both are true; they answer different questions.
  (SELECT count(DISTINCT place_id) FROM win)                       AS places_in_window,
  (SELECT count(*) FROM now_rows)                                  AS places_now,
  (SELECT count(*) FROM win)                                       AS readings,
  (SELECT jsonb_object_agg(v.value, v.n) FROM (
      SELECT value, count(*) n FROM win GROUP BY 1) v)             AS over_window,
  (SELECT jsonb_object_agg(n.value, n.n) FROM (
      SELECT value, count(*) n FROM now_rows GROUP BY 1) n)        AS now_snapshot,
  (SELECT min(age_minutes) FROM now_rows)                          AS freshest_minutes,
  (SELECT count(*) FROM now_rows WHERE value = 'unknown')          AS unknown_now,
  (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.readings DESC) FROM (
      SELECT name_ar, count(*) readings,
             count(DISTINCT value) distinct_values,
             min(extract(epoch FROM now() - observed_at)/60)::int AS last_seen_minutes
        FROM win GROUP BY place_id, name_ar
       ORDER BY count(*) DESC LIMIT 8) t)                          AS most_reported,
  (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.transitions DESC, t.readings DESC)
     FROM (
      -- CHANGING measures CHANGE, not variety. The old version ordered places
      -- by how many DISTINCT values they showed, which in practice returned the
      -- same eight places in the same order as `most_reported`: how often a
      -- place is reported and how many different things it said are correlated,
      -- so the second list added nothing. A traveller reading `changing` wants
      -- the places that FLIPPED — open, closed, open again — so it now counts
      -- transitions over time and reports them as `transitions`, keeping
      -- `distinct_values` beside it for context.
      SELECT name_ar, count(*) AS readings,
             count(*) FILTER (WHERE prev_value IS NOT NULL
                                AND value IS DISTINCT FROM prev_value)
               AS transitions,
             count(DISTINCT value) AS distinct_values
        FROM (SELECT name_ar, value, observed_at,
                     lag(value) OVER (PARTITION BY place_id
                                      ORDER BY observed_at) AS prev_value
                FROM win) w
       GROUP BY name_ar
      HAVING count(*) FILTER (WHERE prev_value IS NOT NULL
                                AND value IS DISTINCT FROM prev_value) > 0
       ORDER BY transitions DESC, readings DESC LIMIT 8) t)          AS changing,
  (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.n DESC) FROM (
      SELECT extract(hour FROM observed_at AT TIME ZONE 'Asia/Hebron')::int AS hour,
             count(*) n FROM win GROUP BY 1
       ORDER BY n DESC LIMIT 5) t)                                 AS busiest_hours,
  -- NOT A PARTITION, AND IT MUST NOT LOOK LIKE ONE. `readings_total` counts
  -- direction='both' rows; inbound and outbound are recorded as SEPARATE rows
  -- for the same readings, so they overlap the total rather than dividing it.
  -- Measured: {both: 12566, inbound: 439, outbound: 623} against readings 12566
  -- — 439+623+12566 = 13628, which reads as arithmetic that does not add up.
  -- 'both' is therefore removed from this map: what is left is explicitly the
  -- directional subset, and nothing here can be mistaken for a total.
  (SELECT jsonb_object_agg(direction, n) FROM dirs
    WHERE direction <> 'both')                                     AS directional_readings,
  (SELECT jsonb_agg(to_jsonb(t)) FROM (
      SELECT state_kind, value, n FROM presence) t)                AS presence
"""

# NAMED PLACES ONLY, the rule /v2/incidents/summary adopted in P0-C.2 and this
# reduction never did. An event the classifier could pin only to a governorate
# sits on the governorate city's centroid (news_incidents resolves the bare
# governorate name to the city row), so every radius covering Ramallah counted
# the whole governorate's fallbacks as events AROUND Ramallah — 909 of 5,098
# events (17.8 %) on 2026-09-24 — and `newest_place` named the city for a raid
# in an unnamed village. Those are counted apart, as `governorate_only`.
INSIGHTS_INC_SQL = """
WITH anchor AS (
  SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography AS g)
SELECT e.event_type,
       count(*) FILTER (WHERE x.named)                            AS events,
       count(*) FILTER (WHERE x.named AND e.independent_sources >= 2) AS corroborated,
       max(e.occurred_at) FILTER (WHERE x.named)                  AS newest,
       (array_agg(p.name_ar ORDER BY e.occurred_at DESC)
            FILTER (WHERE x.named))[1]                            AS newest_place,
       count(*) FILTER (WHERE NOT x.named)                        AS governorate_only
  FROM event e
  LEFT JOIN place p ON p.place_id = e.place_id
  CROSS JOIN anchor a
  CROSS JOIN LATERAL (SELECT COALESCE(e.attrs->>'place_precision', 'named') = 'named'
                             AS named) x
 WHERE e.status = 'believed'
   AND e.occurred_at >= now() - make_interval(days => %(days)s)
   AND ST_DWithin(e.geom, a.g, %(radius_m)s)
 GROUP BY 1 ORDER BY events DESC
"""

# A satellite fire pixel is a detection, not a report: counted apart from the
# incidents it was being summed with (REST `events` said 53 where 40 reports
# and 13 NASA FIRMS pixels were meant).
FIRE_EVENT_TYPE = "fire_detection"

_PRESENCE_KINDS = {"checkpoint_idf": "army", "checkpoint_inspection": "inspection",
                   "checkpoint_police": "police", "checkpoint_settlers": "settlers"}


ACCURACY_LEDGER = Path(__file__).resolve().parent.parent / "ops" / "accuracy.ndjson"


@functools.lru_cache(maxsize=4)
def _accuracy_lines(path: str, mtime_ns: int, size: int) -> dict[str, dict]:
    """The newest ledger line per state kind, parsed once per file version.

    The ledger is append-only and grows every night; it was re-read and
    re-parsed whole on every /v2/insights call. Keyed on (mtime, size) the way
    serve/quality.py keys its round file, so the nightly append is seen at once.
    """
    last: dict[str, dict] = {}
    for line in Path(path).read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue                           # one torn line is not the ledger
        if isinstance(r, dict) and r.get("state_kind"):
            last[r["state_kind"]] = r          # append-only: last wins
    return last


def _measured_precision(state_kind: str) -> dict | None:
    """The newest backtest line for a state kind, from the accuracy ledger.

    Read rather than asserted: if the ledger has nothing for this subject, the
    answer says nothing about precision instead of inventing a number.
    """
    try:
        st = ACCURACY_LEDGER.stat()
        best = _accuracy_lines(str(ACCURACY_LEDGER), st.st_mtime_ns, st.st_size).get(state_kind)
    except Exception:                          # noqa: BLE001
        return None
    if not best:
        return None
    # A NIGHT WITH NO PAIRS IS A LINE WITH precision: null (learn/accuracy.py
    # writes it when the channels went quiet), and round(None) raised here —
    # every /v2/insights call, and the MCP insights tool, 500'd until a night
    # with pairs. It is an answer: nothing was verifiable in that window.
    p = best.get("precision")
    # `n` is the precision's DENOMINATOR — the readings the model would have
    # asserted — not every pair examined; older lines without the field fall
    # back to what they have.
    n = best.get("would_have_asserted", best.get("pairs_examined"))
    out = {"precision": round(float(p), 4) if p is not None else None,
           "n": n if p is not None else 0,
           "pairs_examined": best.get("pairs_examined"),
           "mode": best.get("mode"), "window_days": best.get("window_days"),
           "basis": "backtest, ops/accuracy.ndjson"}
    if p is None:
        out["note"] = ("no independent verification pairs in the last backtest "
                       "window — precision is unmeasured, not zero")
    return out


def _incident_quality() -> dict | None:
    """The incident classifier's measured precision and its gate state.

    ZAID-9 settled on 2026-09-23 that an obituary or a funeral is not a death
    report. This measurement predates that: it is what the ledger says, and
    saying it out loud is the point.
    """
    from serve.quality import incident_precision
    q = incident_precision()                   # the LATEST round, whichever it is
    if not q:
        return None
    o = q["overall"]
    out = {"precision": o["precision"], "ci95": o["ci95"], "n": o["n"],
           "gate": q["gate"]["overall"], "state": q["gate"]["state"],
           "per_type_gate": q["gate"]["per_type"],
           "failing_types": q["gate"].get("failing_types", []),
           "measured_at": q["measured_at"], "round": q["round"],
           "measured_version": q["measured_version"], "serving_version": q["serving_version"],
           "by_type": {k: v["precision"] for k, v in q["per_type"].items()},
           "basis": q["basis"]}
    if q.get("note"):
        out["note"] = q["note"]
    return out


@app.get("/v2/insights", tags=["insights"])
def insights(
    place: str | None = Query(None, min_length=2, description="Arabic or English place name"),
    lat: float | None = Query(None, ge=29.0, le=34.0),
    lon: float | None = Query(None, ge=33.0, le=37.0),
    radius_km: float = Query(15.0, gt=0, le=60),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """One reduction of a place over a window: checkpoints, incidents, precision.

    Answers "what was happening around X for the last N days" in a single call
    — the reduction a person does by eye, with the sample sizes kept.
    """
    if place:
        from resolve.geo import resolve_place
        # learn=False: A READ PATH NEVER WRITES. With the default, a containment
        # or fuzzy hit INSERTed the caller's whole phrase into place_alias as an
        # 'observed' alias (and bumped hits on every exact hit) — so any
        # anonymous caller, the MCP insights tool and every test run taught the
        # gazetteer the incident classifier resolves against. Every other
        # serving route already passed it; PLAN P0-A.2 named this call.
        r = resolve_place(place, learn=False)
        if not r:
            raise HTTPException(404, f"place {place!r} did not resolve")
        row = q("SELECT ST_Y(centroid::geometry) AS la, ST_X(centroid::geometry) AS lo "
                "FROM place WHERE place_id = %s", (r.place_id,))
        if not row or row[0]["la"] is None:
            raise HTTPException(404, f"place {place!r} resolved but carries no geometry")
        lat, lon = row[0]["la"], row[0]["lo"]
        resolved = {"query": place, "name": r.name_ar or r.name_en, "kind": r.kind,
                    "name_en": r.name_en, "place_id": r.place_id,
                    "lat": round(lat, 4), "lon": round(lon, 4),
                    "precision": r.precision, "confidence": round(r.confidence, 3),
                    "method": r.method}
    elif lat is None or lon is None:
        raise HTTPException(400, "give either `place` or both `lat` and `lon`")
    else:
        resolved = {"query": f"{lat:.4f},{lon:.4f}", "lat": lat, "lon": lon}

    par = {"lat": lat, "lon": lon, "days": days, "radius_m": radius_km * 1000}
    # Cached like the other whole-databank reductions — and here the trade is
    # explicit: a benchmark that calls this twenty times gets the same answer
    # twenty times, so the FIRST call is the one that costs. `as_of` in the
    # payload is when the answer was built, so a caller can always see the age;
    # CACHE_TTL_SECONDS bounds it at a minute.
    ck_rows, ck_built = q_cached_at(INSIGHTS_CKPT_SQL, par)
    ck = ck_rows[0]
    inc_all, inc_built = q_cached_at(INSIGHTS_INC_SQL, par)
    # Types with at least one NAMED event are the incidents; fallbacks pinned
    # to a governorate city are counted apart, never under the place asked.
    inc = [r for r in inc_all if r["events"]]
    gov_only = sum(int(r["governorate_only"] or 0) for r in inc_all
                   if r["event_type"] != FIRE_EVENT_TYPE)
    fires = sum(r["events"] for r in inc if r["event_type"] == FIRE_EVENT_TYPE)
    reports = [r for r in inc if r["event_type"] != FIRE_EVENT_TYPE]

    presence: dict[str, dict] = {}
    for row in (ck["presence"] or []):
        axis = _PRESENCE_KINDS.get(row["state_kind"], row["state_kind"])
        presence.setdefault(axis, {})[row["value"]] = row["n"]
    events = sum(r["events"] for r in reports)
    caves = [
        "A checkpoint reading is what a channel reported, not an official "
        "count. `unknown` means nobody reported recently — it is NOT `open`.",
        "`present` counts sightings; an empty presence block means nobody "
        "sighted them, never that they were not there.",
        "Incident times are when the channel POSTED, not when it happened "
        "(precision: hour).",
        "`independent_sources` counts independence groups: channels that "
        "mirror each other count once.",
    ]
    if not ck["readings"]:
        caves.append("No checkpoint reading in this radius and window at all — "
                     "that is absence of evidence, not a quiet month.")
    if reports and max(r["corroborated"] for r in reports) == 0:
        caves.append("No incident type here reached two independent sources in "
                     "this window; every count is single-source.")
    if gov_only:
        caves.append(f"{gov_only} more incident(s) were located only to a "
                     "governorate: their pin is the governorate city's centroid, "
                     "so they may have happened anywhere in it. They are counted "
                     "in `located_to_governorate_only`, never in `events`.")
    return {
        "scope": {**resolved, "radius_km": radius_km, "days": days,
                  "window_hours": days * 24},
        # WHEN THE ANSWER WAS BUILT, not when it was sent: the reductions come
        # out of a cache up to CACHE_TTL_SECONDS old, and stamping the response
        # time made two calls fifty seconds apart show identical ages under
        # different as_of values. The older of the two builds is the honest one.
        "as_of": min(ck_built, inc_built).isoformat(),
        "checkpoints": {
            # Named apart so a caller cannot read one as the other: the first is
            # the window's universe, the second is what is tracked right now.
            "places_in_window": ck["places_in_window"],
            "readings": ck["readings"],
            "over_window": ck["over_window"] or {},
            "now": ck["now_snapshot"] or {},
            "places_now": ck["places_now"],
            "unknown_now": ck["unknown_now"],
            "freshest_reading_minutes": ck["freshest_minutes"],
            # The directional subset, with 'both' removed: these OVERLAP the
            # reading total rather than dividing it, and the key now says so.
            "directional_readings": ck["directional_readings"] or {},
            "direction_note": ("`directions` is not a partition of `readings`. "
                               "A reading is recorded once as direction='both' "
                               "and separately as inbound/outbound where the "
                               "report distinguished them, so these counts "
                               "overlap the total and never sum to it."),
            "most_reported": ck["most_reported"] or [],
            "changing": ck["changing"] or [],
            "changing_note": ("`changing` ranks by TRANSITIONS over the window "
                              "(the count of times a place's reported value "
                              "differed from its previous reading), not by how "
                              "many readings it has — how busy a place is and "
                              "how much it changes are different questions."),
            "busiest_hours_hebron": ck["busiest_hours"] or [],
            "presence": presence,
        },
        "incidents": {
            # Reports at NAMED places only; satellite fire pixels and
            # governorate-only fallbacks are the two counts beside it.
            "events": events,
            "by_type": [{"type": r["event_type"], "events": r["events"],
                         "corroborated": r["corroborated"],
                         "newest": r["newest"], "newest_place": r["newest_place"]}
                        for r in inc],
            "fires": {"n": fires,
                      "note": "NASA FIRMS satellite fire pixels — detections, not "
                              "reports; listed in by_type as fire_detection and "
                              "never counted in `events`"},
            "located_to_governorate_only": gov_only,
            "events_note": ("`events` counts reports whose village or town "
                            "resolved; incidents located only to a governorate "
                            "are `located_to_governorate_only`, and fire "
                            "detections are `fires`."),
            "absent_types": [t for t in ("raid", "settler_attack", "demolition", "land_levelling",
                                         "closure", "arrest", "shooting", "death",
                                         "injury", "fire_detection", "siege")
                             if t not in {r["event_type"] for r in inc}],
        },
        "quality": {"checkpoints": _measured_precision("checkpoint_flow"),
                    "incidents": _incident_quality()},
        "caveats": caves,
        "attribution": ("Checkpoints and incidents: Telegram road-condition and news "
                        "channels via Palestine Data Platform v2. See /v2/coverage "
                        "and /v2/databank/licenses."),
    }


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
    # The FLOW grain by default, as the MCP place_pattern tool already does
    # (QA 2026-09-23 fix 5). `checkpoint_status` is the legacy kind that carries
    # presence words (`idf`, `police`) in the flow column, so the REST default
    # served "usually idf at 07:00" as a flow pattern while the same question
    # through MCP answered from flow alone.
    state_kind: str = Query("checkpoint_flow", max_length=64),
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


# ── P5.2: real-time push ─────────────────────────────────────────────────────

@app.on_event("startup")
async def _start_stream() -> None:
    from serve.stream import broadcaster
    broadcaster.start()


@app.on_event("shutdown")
async def _stop_stream() -> None:
    from serve.stream import broadcaster
    await broadcaster.stop()


@app.get("/v2/stream", tags=["stream"])
async def stream(
    state_kind: str | None = Query(None, description="only this kind"),
    place_id: int | None = Query(None, description="only this place"),
    snapshot: bool = Query(True, description="send current state on connect"),
):
    """Server-sent events: changes in what the system will assert.

        curl -N localhost:7870/v2/stream
        curl -N 'localhost:7870/v2/stream?state_kind=checkpoint_status'

    Events are belief changes, not raw reports — a thirty-eighth "Huwara open"
    is not news, Huwara closing is. `decayed: true` marks a reading that aged
    out of assertability, which is a real transition and the one most easily
    forgotten: without it a phone connected at noon would still show "open" at
    midnight, which is exactly the v1 failure this architecture exists to fix.

    See serve/stream.py for why SSE rather than WebSockets.
    """
    from fastapi.responses import JSONResponse, StreamingResponse

    from serve.stream import event_source
    return StreamingResponse(
        event_source(state_kind, place_id, snapshot),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Nginx and some Cloudflare configurations buffer proxied responses,
            # which turns a live stream into a long silence followed by
            # everything at once.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/v2/stream/status", tags=["stream"])
def stream_status() -> dict:
    """Whether the stream is actually running — a dead poller and a quiet night
    look identical to a subscriber, which is the same trap P3.1 exists for."""
    from serve.stream import POLL_SECONDS, broadcaster
    last = broadcaster.last_poll_at
    age = (datetime.now(timezone.utc) - last).total_seconds() if last else None
    return {
        "running": broadcaster._task is not None and not broadcaster._task.done(),
        "subscribers": broadcaster.subscribers,
        "poll_seconds": POLL_SECONDS,
        "last_poll_at": last.isoformat() if last else None,
        "last_poll_age_seconds": round(age, 1) if age is not None else None,
        "watched_states": len(broadcaster._last),
        "events_sent": broadcaster.events_sent,
    }


# ── P4.1: the page — a human can finally look at it ─────────────────────────
# Static, self-contained (no CDN, no tiles, no fonts — DESIGN.md law 5),
# reading the same public API as everyone else. Three concept variants for
# the options loop; /app is the chooser until one is locked.
from fastapi.staticfiles import StaticFiles  # noqa: E402

app.mount("/app", StaticFiles(directory=str(Path(__file__).parent / "webapp"),
                              html=True), name="webapp")


# ── P4.2: export — the data walks out the door in standard shapes ───────────
# CSV for spreadsheets, GeoJSON for maps. Same serving views as the JSON API,
# same gates, same honesty columns: an export that dropped `staleness_band`
# would let a week-old "open" travel the world looking fresh.

_CSV_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(v):
    """A third-party STRING that a spreadsheet would execute is quoted inert.

    Names come from OSM, palhub and outlet pages; one starting with '=', '+',
    '-' or '@' is run as a formula by Excel/LibreOffice when a downloader opens
    the export. Numbers are left alone — -3.5 is a value, not a formula.
    """
    if isinstance(v, str) and v.lstrip(" ").startswith(_CSV_FORMULA_LEAD):
        return "'" + v
    return v


def _csv_response(rows: list[dict], columns: list[str], filename: str):
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: _csv_cell(r.get(k)) for k in columns})
    from fastapi import Response
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _geojson_response(features: list[dict], attribution: str):
    # jsonable_encoder first: a bare JSONResponse uses stdlib json, which
    # cannot serialise the datetimes in observed_at/occurred_at.
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse
    return JSONResponse(jsonable_encoder(
        {"type": "FeatureCollection", "features": features,
         "attribution": attribution}), media_type="application/geo+json")


_EXPORT_CHECKPOINT_SQL = f"""
    SELECT {CHECKPOINT_COLS}
    FROM checkpoint_serving c
    ORDER BY c.name_ar, c.direction"""

# The same honesty columns the JSON routes carry (_checkpoint_out). The pages
# read this export: without `presence_age_minutes` a sighting chip rendered
# with no age (DESIGN law 8), and without `reported_for` a 'دخول · سالك'
# inherited from an undirected report was indistinguishable from one filed for
# that direction.
_EXPORT_CP_COLUMNS = ["place_id", "name_ar", "name_en", "lat", "lon", "direction",
                      "flow", "passable", "last_known_flow", "reported_for",
                      "confidence", "observed_at", "age_minutes", "staleness_band",
                      "independent_sources", "contradicted_by", "present", "absent",
                      "presence_age_minutes"]


@app.get("/v2/export/fuel_prices.csv", tags=["export"])
def export_fuel_prices_csv():
    """Every price read, one row per start date, product and price, with how
    many independent outlets reported it and whether that made it confirmed."""
    rows = fuel_price_history(include_unconfirmed=True)["history"]
    rows = [dict(r, sources=";".join(r["sources"] or []), urls=";".join(r["urls"] or []))
            for r in rows]
    return _csv_response(rows, ["effective_from", "product", "unit", "price", "confirmed",
                                "outlets", "sources", "urls"], "fuel-prices-westbank.csv")


@app.get("/v2/export/checkpoints.csv", tags=["export"])
def export_checkpoints_csv():
    """Every checkpoint's current serving state, honesty columns included."""
    rows = [dict(r, present=",".join(r["present"] or []),
                 absent=",".join(r["absent"] or [])) for r in q(_EXPORT_CHECKPOINT_SQL)]
    return _csv_response(rows, _EXPORT_CP_COLUMNS, "checkpoints.csv")


@app.get("/v2/export/checkpoints.geojson", tags=["export"])
def export_checkpoints_geojson():
    feats = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
        "properties": {k: r[k] for k in _EXPORT_CP_COLUMNS
                       if k not in ("lat", "lon")} | {
            "present": list(r["present"] or []), "absent": list(r["absent"] or [])},
    } for r in q(_EXPORT_CHECKPOINT_SQL) if r["lat"] is not None]
    return _geojson_response(feats, CHECKPOINT_ATTRIBUTION)


# THE SAME HONESTY COLUMNS AS /v2/incidents/recent. Without them one event in
# six — located only to a governorate — left as a pin on the city centroid
# named as the city, indistinguishable from a raid that happened in the city:
# the map lied exactly the way the JSON route was fixed not to.
# `place_precision` says which answered; `named_place` is what the channel wrote.
_EXPORT_INCIDENT_SQL = """
    SELECT e.event_id, e.event_type, e.occurred_at, e.confidence,
           e.claim_count, e.independent_sources,
           p.name_ar, p.name_en,
           COALESCE(e.attrs->>'place_precision', 'named') AS place_precision,
           e.attrs->>'place_text' AS named_place,
           ST_Y(e.geom::geometry) AS lat, ST_X(e.geom::geometry) AS lon
    FROM event e LEFT JOIN place p ON p.place_id = e.place_id
    WHERE e.status = 'believed'
      AND e.occurred_at > now() - make_interval(days => %s)
    ORDER BY e.occurred_at DESC"""

_EXPORT_INC_COLUMNS = ["event_id", "event_type", "occurred_at", "name_ar",
                       "name_en", "place_precision", "named_place", "lat", "lon",
                       "confidence", "claim_count", "independent_sources"]


@app.get("/v2/export/incidents.csv", tags=["export"])
def export_incidents_csv(days: int = Query(30, ge=1, le=365)):
    """Believed incidents. occurred_at is the POSTING time, hour precision."""
    return _csv_response(q(_EXPORT_INCIDENT_SQL, (days,)),
                         _EXPORT_INC_COLUMNS, f"incidents-{days}d.csv")


@app.get("/v2/export/incidents.geojson", tags=["export"])
def export_incidents_geojson(days: int = Query(30, ge=1, le=365)):
    feats = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
        "properties": {k: r[k] for k in _EXPORT_INC_COLUMNS if k not in ("lat", "lon")},
    } for r in q(_EXPORT_INCIDENT_SQL, (days,)) if r["lat"] is not None]
    return _geojson_response(
        feats, "West Bank governorate news channels (Telegram) via agent2")


@app.get("/v2", tags=["discovery"])
def discovery() -> dict:
    """Everything this system can answer, from one URL.

    A frontend or an agent should not have to be told twenty URLs, and a list
    maintained by hand beside the code drifts from it within a week. This is
    generated from the live route table and the live configuration, so it
    describes what the server will actually do rather than what someone
    remembered to write down.

    The reading contract is stated here too, because the single most dangerous
    way to consume this API is to take `value` and ignore everything beside it.
    """
    routes = sorted(
        {r.path for r in app.routes
         if getattr(r, "path", "").startswith("/v2") and r.path != "/v2"
         and r.path not in FUEL_RETIRED_PATHS})

    def group(prefix: str) -> list[str]:
        return [p for p in routes if p.startswith(prefix)]

    try:
        kinds = q("""SELECT state_kind, serving_mode, crowd_reportable,
                            confidence_floor, max_assert_seconds
                       FROM state_kind_config ORDER BY state_kind""")
    except Exception:                                   # noqa: BLE001
        kinds = []

    return {
        "service": "Palestine Data Platform v2",
        "now": datetime.now(timezone.utc).isoformat(),
        "read_this_first": {
            "value": "what we are willing to assert RIGHT NOW. 'unknown' means "
                     "nobody credible has looked recently — it is an answer, "
                     "not a gap, and must not be rendered as the last value.",
            "last_known_value": "what it was before it decayed. Show it WITH "
                                "age_minutes or not at all.",
            "confidence": "decayed from corroboration by independent observers. "
                          "Below the kind's floor, value becomes 'unknown'.",
            "independent_sources": "how many INDEPENDENT units agree. Nine "
                                   "channels reposting each other count as one.",
            "serving_mode": "'state' describes now. 'sighting' describes a "
                            "moment that was observed — read it with "
                            "age_minutes and never as current.",
        },
        "live": {
            "fuel": group("/v2/fuel"),
            "checkpoints": group("/v2/checkpoints"),
            "crossings": group("/v2/crossings"),
            "incidents": group("/v2/incidents"),
            "insights": group("/v2/insights"),
            "other": ["/v2/weather", "/v2/connectivity", "/v2/services",
                      "/v2/news/latest"],
        },
        # Generated from the route table like the rest, so the databank (the
        # whole second tier) and the licence surface are on the map: an agent
        # starting here, as the docstring says it should, never learned they
        # existed while `route_count` counted them.
        "databank": {
            "endpoints": group("/v2/databank"),
            "licence": group("/v2/licence"),
            "export": group("/v2/export"),
        },
        "history": {
            "endpoints": group("/v2/history") + group("/v2/patterns"),
            "source": "the tier-2 `observation` table — tier 1's memory and the "
                      "databank are the same rows, joinable on place and time.",
            "counts": "reports, not shares of time.",
        },
        "realtime": {
            "endpoints": group("/v2/stream"),
            "protocol": "server-sent events",
            "emits": "changes in what the system will ASSERT, including a "
                     "reading decaying to 'unknown'.",
        },
        "contribute": {
            "endpoints": group("/v2/crowd"),
            "note": "reassuring values need a second independent witness; "
                    "cautions do not. See /v2/crowd/fields.",
        },
        "agents": {
            "mcp": "/mcp",
            "transport": "streamable HTTP, JSON-RPC 2.0, stateless — POST only",
            "add_to_claude_code":
                "claude mcp add --transport http palestine "
                "https://live-api.zaidlab.xyz/mcp",
            "note": "the same tools the on-host stdio server serves, minus the "
                    "two that report the health of this machine. No write "
                    "path: contributing a report stays human.",
        },
        "meta": {"health": "/health", "coverage": "/v2/coverage",
                 "geo": "/v2/geo/resolve", "openapi": "/openapi.json"},
        "fields": [
            {"state_kind": k["state_kind"], "serving_mode": k["serving_mode"],
             "crowd_reportable": k["crowd_reportable"],
             "confidence_floor": k["confidence_floor"]}
            for k in kinds
        ],
        "route_count": len(routes),
    }


# ── P5.3: going public ───────────────────────────────────────────────────────

@app.middleware("http")
async def _rate_limit(request, call_next):
    """One visitor cannot spoil it for everyone. See serve/ratelimit.py."""
    from fastapi.responses import JSONResponse

    from serve import ratelimit as rl
    ip = rl.client_ip(request)
    cls = rl.classify(request.url.path, request.method)
    ok, retry = rl.check(ip, cls)
    if not ok and request.url.path.startswith("/mcp"):
        # An MCP client parses every body as JSON-RPC; a bare {"error": ...}
        # read as a malformed response instead of "back off for Retry-After".
        # Same code as the quota refusal in serve/mcp_http.py.
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32003, "message": "rate limited",
                       "data": {"class": cls, "retry_after_seconds": retry}}},
            status_code=429, headers={"Retry-After": str(retry)})
    if not ok:
        return JSONResponse(
            {"error": "rate limited", "class": cls, "retry_after_seconds": retry,
             "note": "limits are per address and generous for honest use; see "
                     "/v2 for what is available"},
            status_code=429, headers={"Retry-After": str(retry)})
    return await call_next(request)


@app.get("/", tags=["discovery"])
def root() -> dict:
    """The bare hostname answers with the map of the system rather than a 404."""
    return discovery()


# An agent can now reach this system without a clone, a venv or a path on the
# caller's machine — the same tool table the stdio server serves, over HTTP.
# Mounted on this host rather than a new one because the tunnel is
# token-managed: hostnames live in the Cloudflare dashboard and cannot be added
# from here, and a path costs nothing. See serve/mcp_http.py.
from serve.mcp_http import router as _mcp_router                # noqa: E402

app.include_router(_mcp_router)
from serve.mcp_oauth import router as _oauth_router             # noqa: E402
app.include_router(_oauth_router)          # discovery, registration, /authorize, /token


@app.post("/v2/crowd/register", tags=["crowd"])
def crowd_register(
    handle: str = Query(..., min_length=3, max_length=40,
                        description="letters, digits, _ - . only"),
    note: str = Query("", max_length=200, description="optional, for you"),
) -> dict:
    """Create a submitter and receive a token. **The token is shown once.**

    Open, by decision: the point is that anybody can contribute. That is safe
    for a structural reason rather than a procedural one — every unverified
    submitter shares ONE independence unit and scores 0.17, below every
    confidence floor, so a thousand sign-ups carry the weight of one anonymous
    stranger. Standing is earned afterwards by being right, and it is earned
    per person, not per account.

    Rate limited to three an hour per address, which is about disk and noise
    rather than trust.
    """
    from crowd.engine import register
    try:
        return register(handle, channel="http", note=note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/v2/usage", include_in_schema=False)
def mcp_usage(request: Request, days: int = Query(7, ge=1, le=90)) -> dict:
    """Who asked this system what, and what it could not answer.

    LOCAL CALLERS ONLY, and not in the schema. Aggregate usage of a service
    people consult about checkpoints is not neutral information — it says which
    places are on people's minds this week, which is a fact about them rather
    than about roads. It is here to tell the maintainer what to build next, and
    that job needs no audience.
    """
    from serve.ratelimit import client_ip, is_local
    if not is_local(client_ip(request)):
        raise HTTPException(404, "Not Found")
    from serve.mcp_usage import summary
    return summary(days)


@app.get("/v2/limits", tags=["meta"])
def limits() -> dict:
    """What the rate limits are, so a client can pace itself instead of
    discovering them by being refused."""
    from serve import ratelimit as rl
    return {"limits": rl.stats(),
            "local_exempt": True,
            "note": "per client address, sliding window. 429 carries Retry-After."}


# ── P7.1: corridors ──────────────────────────────────────────────────────────
# Everything above answers about a PLACE. This answers about a JOURNEY, which is
# the question somebody actually has. See resolve/corridor.py for why route-level
# aggregation is what makes 23% point coverage useful rather than embarrassing.

@app.get("/v2/route", tags=["corridors"])
def route(
    from_lat: float = Query(..., ge=29.0, le=34.0),
    from_lon: float = Query(..., ge=33.0, le=37.0),
    to_lat: float = Query(..., ge=29.0, le=34.0),
    to_lon: float = Query(..., ge=33.0, le=37.0),
    alternates: int = Query(2, ge=0, le=3),
    include_shape: bool = Query(False, description="route polylines, for a map"),
) -> dict:
    """Can I get from here to there right now — and if not, which way instead.

    Returns every reasonable route scored by the checkpoints ON it, in travel
    order, each with its own age and confidence. Ranked by verdict then by
    time: how much is known is reported on every route, never used to send
    somebody the long way round for our benefit.

    One confirmed closure blocks a route regardless of how many open
    checkpoints surround it — a journey is a conjunction, every checkpoint has
    to be passable. Unknowns never block and are never hidden; they are named,
    so "we do not know" is an answer rather than a silence.
    """
    from resolve.corridor import routes as _routes
    try:
        found = _routes((from_lat, from_lon), (to_lat, to_lon), alternates)
    except Exception as e:                              # noqa: BLE001
        # A routing outage must not look like "no way through" — that is the
        # same failure as serving a stale checkpoint as open, one step removed.
        # NAMED FOR WHAT FAILED, AND NOTHING ELSE SAID. Every failure used to be
        # "routing unavailable: <exception>": a Postgres restart sent the
        # operator chasing Valhalla, and the exception text handed a stranger
        # the database user and the router's internal address. The detail goes
        # to the journal.
        log.warning("route: %s: %s", type(e).__name__, e)
        if isinstance(e, psycopg.Error):
            raise HTTPException(503, "database unavailable") from None
        if isinstance(e, httpx.HTTPError):
            raise HTTPException(503, "routing unavailable") from None
        raise HTTPException(503, "routing failed") from None

    out = []
    for c in found:
        d = c.as_dict()
        if not include_shape:
            d.pop("shape", None)
        out.append(d)
    best = found[0] if found else None
    return {
        "routes": out,
        "best": {"verdict": best.verdict, "summary": best.summary,
                 "distance_km": best.distance_km,
                 "duration_minutes": best.duration_minutes} if best else None,
        "corridor_metres": __import__("resolve.corridor", fromlist=["x"]).CORRIDOR_METRES,
        "note": ("checkpoints are matched to a route by proximity to its "
                 "geometry; `unreported` names the ones on your way that "
                 "nobody has checked recently, which is a real part of the "
                 "answer rather than a gap in it"),
    }


@app.get("/v2/route/between", tags=["corridors"])
def route_between(
    origin: str = Query(..., description="place name, Arabic or English"),
    destination: str = Query(...),
    alternates: int = Query(2, ge=0, le=3),
) -> dict:
    """The same answer, by place name — 'من رام الله لنابلس'."""
    from resolve.geo import resolve_place

    # NOT named `q` — that is the module-level query helper, and shadowing it
    # here fails at call time with "'str' object is not callable" rather than
    # at import.
    def _pt(name: str):
        r = resolve_place(name, learn=False)
        if not r:
            raise HTTPException(404, f"could not place {name!r}")
        row = q("SELECT ST_Y(centroid::geometry) la, ST_X(centroid::geometry) lo "
                "FROM place WHERE place_id=%s", (r.place_id,))
        if not row or row[0]["la"] is None:
            raise HTTPException(404, f"{name!r} has no coordinates")
        return (row[0]["la"], row[0]["lo"]), r

    (a, ra), (b, rb) = _pt(origin), _pt(destination)
    res = route(a[0], a[1], b[0], b[1], alternates, False)
    res["origin"] = {"query": origin, "place": ra.name_ar or ra.name_en,
                     "place_id": ra.place_id}
    res["destination"] = {"query": destination, "place": rb.name_ar or rb.name_en,
                          "place_id": rb.place_id}
    return res


@app.get("/v2/crossings", tags=["crossings"])
def crossings(area: str | None = Query(None, description="governorate name")) -> dict:
    """Crossings and what is known about them — Gaza and West Bank.

    A crossing is not a checkpoint. Its state persists for days rather than
    ninety minutes, it is asymmetric in kind (Kerem Shalom takes goods, Rafah
    moves people), and "open" is rarely binary — open for medical evacuation is
    not open. `partial` is kept distinct for that reason.

    Every crossing will read `unknown` until a source reports one. That is the
    honest state and it is shown rather than hidden: leaving the crossings out
    entirely would make the same ignorance invisible.
    """
    rows = q("""
        SELECT p.place_id, p.name_ar, p.name_en,
               p.attrs->>'crossing_role'   AS role,
               p.attrs->>'note'            AS note,
               g.name_en                   AS governorate,
               ST_Y(p.centroid::geometry)  AS lat,
               ST_X(p.centroid::geometry)  AS lon,
               COALESCE(s.value, cf.value)                       AS value,
               COALESCE(s.last_known_value, cf.last_known_value)  AS last_known_value,
               COALESCE(s.confidence, cf.confidence)              AS confidence,
               COALESCE(s.age_minutes, cf.age_minutes)            AS age_minutes,
               COALESCE(s.staleness_band, cf.staleness_band)      AS staleness_band,
               COALESCE(s.independent_sources, cf.independent_sources)
                                                                  AS independent_sources,
               CASE WHEN s.value IS NOT NULL THEN 'crossing_status'
                    WHEN cf.value IS NOT NULL THEN 'checkpoint_flow'
               END                                                AS basis
          FROM place p
          LEFT JOIN place g ON g.kind = 'governorate'
                           AND g.admin2_pcode = p.admin2_pcode
          LEFT JOIN state_serving s ON s.place_id = p.place_id
                                   AND s.state_kind = 'crossing_status'
          -- Allenby reads "no source has ever reported this" while
          -- checkpoints_summary lists جسر الملك حسين with a reading 114 minutes
          -- old: the same place, known to one layer and denied by the other.
          -- A crossing that is also a checkpoint is served from the checkpoint
          -- layer, and `basis` says which layer answered.
          LEFT JOIN state_serving cf ON cf.place_id = p.place_id
                                    AND cf.state_kind = 'checkpoint_flow'
                                    AND cf.direction = 'both'
         WHERE p.kind = 'crossing'
           AND (%s::text IS NULL OR g.name_en ILIKE %s)
         ORDER BY g.name_en NULLS LAST, p.name_en
    """, (area, f"%{area}%" if area else None))

    out = [{"place_id": r["place_id"],
            "name": r["name_ar"] or r["name_en"], "name_en": r["name_en"],
            "governorate": r["governorate"], "role": r["role"], "note": r["note"],
            "lat": r["lat"], "lon": r["lon"],
            "value": r["value"] or "unknown",
            "last_known_value": r["last_known_value"],
            "confidence": round(r["confidence"], 3) if r["confidence"] is not None else None,
            "age_minutes": float(r["age_minutes"]) if r["age_minutes"] is not None else None,
            "staleness_band": r["staleness_band"],
            "independent_sources": r["independent_sources"],
            "basis": r["basis"],
            # THE THIRD STATE, SAID ON REST TOO. `unknown` is "nobody credible
            # looked recently"; a crossing no layer has EVER held a reading for
            # is `no source` (DESIGN law 2), and the two read identically here
            # while only the MCP tool rebuilt the difference from `basis`.
            "no_source": r["basis"] is None} for r in rows]

    # A BAND IS ABOUT RHYTHM, NOT CURRENCY — and printed bare the two read as a
    # contradiction. `value` is gated by three separate rules (confidence below
    # its floor, an expired band, and the kind's `max_assert_seconds` ceiling)
    # while `staleness_band` is gated by none of them, so `value: unknown` beside
    # `staleness_band: live` is possible BY CONSTRUCTION. Measured 2026-09-24 on
    # King Hussein Bridge: value `unknown`, band `live`, age 691 minutes — its
    # half-life makes eleven and a half hours count as `live` for reporting
    # rhythm, while the assert ceiling withdrew the value long before. Both facts
    # are true; neither is wrong; what was missing is that the payload never said
    # what the band is FOR.
    for c in out:
        if c["value"] == "unknown" and c["staleness_band"] in (
                "live", "recent", "stale"):
            c["value_withheld_because"] = (
                "still being reported at this place's own rhythm, but no value "
                "is assertable: its confidence has decayed below the floor for "
                "this kind, or its age has passed the kind's assert ceiling. "
                "`staleness_band` is not a claim that the reading is current.")

    known = [c for c in out if c["value"] != "unknown"]
    return {
        "crossings": out,
        "total": len(out), "with_a_current_reading": len(known),
        "vocabulary": ["open", "partial", "closed"],
        "band_note": ("`staleness_band` describes whether a place is still being "
                      "reported at its OWN rhythm — a crossing reported twice a "
                      "day reads `live` at an age where one reported every few "
                      "minutes reads `stale`. It is never a claim that a value is "
                      "current: `value` is what may be asserted, and it is gated "
                      "separately by the confidence floor and the kind's assert "
                      "ceiling. Where the two look inconsistent, "
                      "`value_withheld_because` states why."),
        "note": ("`partial` means open for some traffic only — medical cases, "
                 "aid lorries, a named list. It is never rounded up to `open`. "
                 "`crossing_status` still has no source of its own, so a "
                 "crossing that is ALSO a checkpoint is served from the "
                 "checkpoint layer and `basis` says where the reading came "
                 "from; the rest read `unknown`, which is the truth rather "
                 "than a gap."),
    }


# ── T2: the databank goes public — free tier, attribution on every row ───────

@app.get("/v2/databank/categories", tags=["databank"])
def databank_categories() -> dict:
    """What the databank holds: per-dataset counts, ranges, and licenses.
    Serving is the free tier by decision (2026-08-05): everything
    redistributable, credited; `sellable` marks the commercial subset."""
    rows = q_cached("""
        SELECT v1_category, dataset_key, source_name, license_spdx,
               commercial_use, attribution_text,
               COUNT(*) AS n, MIN(occurred_at)::date AS from_date,
               MAX(occurred_at)::date AS to_date
        FROM databank_serving
        GROUP BY 1,2,3,4,5,6 ORDER BY 1,7 DESC""")
    return {"datasets": [
        {"category": r["v1_category"], "dataset": r["dataset_key"],
         "source": r["source_name"], "license": r["license_spdx"],
         "sellable": r["commercial_use"], "rows": r["n"],
         "from": r["from_date"], "to": r["to_date"],
         "attribution": r["attribution_text"]} for r in rows],
        "note": "occurred_precision governs how much a date claims; "
                "year/month/unknown rows are periods or registers, not days.",
        # The list is what CARRIES ROWS. Nine registered datasets carry none, so
        # a reader counting the registry against this list finds a gap and has
        # to guess at it; naming both numbers costs one query and removes the
        # guess (the partner's QA pass asked exactly this).
        "datasets_with_rows": len(rows),
        "datasets_registered": q_cached("SELECT count(*) AS n FROM dataset")[0]["n"],
        "list_note": "`datasets` lists the ones carrying rows; the difference "
                     "from `datasets_registered` is datasets with no data yet."}


@app.get("/v2/databank/radar", tags=["databank"])
def databank_radar() -> dict:
    """The gap radar: where the record thins — per-dataset freshness
    measured on the data's OWN dates against each series' learned rhythm,
    internal holes, era coverage, and fetch-layer health. Re-measured after
    every nightly sync (ops/gap_radar.py); born from the June-9 lesson,
    where file mtimes said 'fresh' through a 57-day freeze."""
    p = Path(__file__).resolve().parent.parent / "data" / "gap-radar.json"
    if not p.exists():
        raise HTTPException(503, "radar has not been measured yet — "
                                 "run ops.gap_radar")
    return json.loads(p.read_text())


@app.get("/v2/databank/scout", tags=["databank"])
def databank_scout() -> dict:
    """The source scout: what the open-data world currently offers to fill
    the radar's gaps — swept weekly from structured catalogs, scored against
    open gaps, with never-seen-before flagged. Discovery only: nothing here
    enters the databank without a reviewed spec."""
    p = Path(__file__).resolve().parent.parent / "data" / "source-scout.json"
    if not p.exists():
        raise HTTPException(503, "scout has not swept yet — "
                                 "run ops.source_scout")
    return json.loads(p.read_text())


@app.get("/v2/databank/licenses", tags=["databank"])
def databank_licenses() -> dict:
    """Every licence governing the databank, and what each one obliges.

    Published because a consumer cannot comply with terms they cannot see.
    `commercial_use` alone was never enough: ODbL and CC-BY-SA permit
    commercial use AND require a derived DATABASE to carry the same licence,
    and a buyer who learns that after shipping learns it too late. The
    `redistribution` grade and `share_alike` flag are the missing half.

    Licence resolves at the DATASET grain and falls back to the source (054),
    because a portal is not a licence-holder — the three datasets we take
    through HDX carry three different publishers' terms.
    """
    # F-84: CACHED, and it was the slowest public route before this. Five
    # whole-dataset aggregates over 206k serving rows, every call, with no cache
    # — measured warm at 3.5-4.0 s serial and 5.6 s median under ten concurrent
    # callers, on a single-worker server that opens ONE CONNECTION PER QUERY.
    # So a stranger could spend 5 connections and 4 seconds per request, and the
    # rate limit allowed 120 of them a minute. These are exactly the aggregates
    # `q_cached` exists for: the databank changes once a night, and the cache is
    # keyed on the sync watermark rather than the clock, so a nightly load
    # invalidates them immediately. `as_of` does not apply here — nothing on this
    # route reconstructs a past day.
    rows = q_cached("""
        SELECT source_key, source_name, license_spdx, commercial_use,
               share_alike, attribution_required, redistribution,
               terms_url, terms_verified_at::date AS verified_on,
               attribution_text,
               COUNT(*) AS rows_served,
               COUNT(DISTINCT dataset_key) AS datasets
        FROM databank_serving
        GROUP BY 1,2,3,4,5,6,7,8,9,10
        ORDER BY 11 DESC""")
    tiers = q_cached("""
        SELECT 'open'                  AS tier, COUNT(*) AS n FROM v_tier_open
        UNION ALL SELECT 'commercial_permissive', COUNT(*)
          FROM v_tier_commercial_permissive
        UNION ALL SELECT 'commercial_sharealike', COUNT(*)
          FROM v_tier_commercial_sharealike""")
    pending = q_cached("""SELECT source_key, status, scope, asked_at, expires_at
                   FROM source_permission WHERE status <> 'granted'
                   ORDER BY source_key""")
    withheld = q_cached("""SELECT v1_category, source_name, license_spdx, rows_held,
                           from_date, to_date, reason, permission_status,
                           terms_url
                    FROM v_withheld ORDER BY rows_held DESC""")
    bulk = q_cached("""SELECT (SELECT count(*) FROM databank_serving) AS queryable,
                       (SELECT count(*) FROM databank_bulk)    AS exportable""")[0]
    return {
        "tiers": {r["tier"]: r["n"] for r in tiers},
        "surfaces": {
            **bulk,
            "note": "Every row here answers a QUERY with its source credited. "
                    "A narrower set may leave as a DATABASE — a bulk export, "
                    "a dump, an open-data release — because that is what a "
                    "licence governs. The difference is listed in `withheld`, "
                    "never silently short.",
        },
        "withheld_from_bulk": withheld,
        "licenses": rows,
        "share_alike_note":
            "Rows whose share_alike is true may be used commercially, but a "
            "DERIVED DATABASE built on them must be released under the same "
            "licence (ODbL-1.0, CC-BY-SA). They are served through "
            "v_tier_commercial_sharealike, never through the permissive tier.",
        "unverified_note":
            "A null verified_on means nobody has read that publisher's terms "
            "at the publisher; the licence shown was inherited from an "
            "earlier registry. Gate G5.11 fails while any commercial source "
            "is in that state.",
        "permissions_pending": pending,
    }


@app.get("/v2/licence/tools", tags=["meta"])
def licence_tools() -> dict:
    """What each public tool may hand a commercial partner, and why (F-81).

    /v2/databank/licenses answers "who owns this row". This answers the question
    a partner actually has to ask first: "of the things this API will tell me,
    which may I carry away, and in what form". Migration 066 settled that a
    credited FACT answering a question is reporting rather than redistribution,
    so the query tier is unfiltered; that reasoning does not reach a message
    BODY, which is the channel's own expression and not a cited fact.

    Every grade is read from `source.redistribution` at call time — the same
    column this system's databank tiers read — so nothing here can quietly
    disagree with /v2/databank/licenses, and a re-graded source changes this
    table without a deploy.
    """
    from serve import licence as L
    from serve.mcp_http import PUBLIC_TOOLS
    return L.table(q_cached, set(PUBLIC_TOOLS))


@app.get("/v2/databank/concepts", tags=["databank"])
def databank_concepts() -> dict:
    """What the databank measures, as a reviewed taxonomy rather than 1,408
    free-text strings. Start here when you do not know what exists."""
    # Cached like /categories: a whole-databank aggregate behind the bare
    # `correlate()` call the find_a_relationship prompt makes first.
    rows = q_cached("""
        SELECT c.key, c.parent, c.name_en, c.name_ar, c.definition,
               count(DISTINCT i.indicator) AS indicators,
               COALESCE(sum(x.n), 0)       AS rows_served
        FROM concept c
        LEFT JOIN indicator_def i ON i.concept_key = c.key
        LEFT JOIN (SELECT indicator, count(*) AS n FROM databank_serving
                   GROUP BY 1) x ON x.indicator = i.indicator
        GROUP BY 1,2,3,4,5 ORDER BY 7 DESC, 1""")
    return {"concepts": rows,
            "note": "A concept with 0 rows is a declared gap, not an error — "
                    "energy.supply is there because the absence is the point."}


@app.get("/v2/databank/indicators", tags=["databank"])
def databank_indicators(concept: str | None = None,
                        # `?q=` is what every refusal in this file tells a
                        # caller to use ("search /v2/databank/indicators?q="),
                        # and the parameter was named `q_`, so the documented
                        # form was silently ignored and returned the 100 largest
                        # series — reading as "bread does not exist". Named
                        # `search` here only because `q` is the query helper.
                        search: str | None = Query(None, alias="q", max_length=80),
                        q_: str | None = Query(None, max_length=80,
                                               include_in_schema=False),
                        measure_kind: str | None = None,
                        # Bounded below too: -1 reached `LIMIT -1` and 500'd.
                        limit: int = Query(100, ge=1, le=500)) -> dict:
    """Find a series without knowing its string.

    THE endpoint for "I don't know the indicator name". 1,408 of them exist
    and most are WHO or World Bank codes that nobody can guess.
    """
    term = search or q_          # `q_` kept for the MCP tool that sends it
    where, params = ["1=1"], {}
    if concept:
        where.append("(i.concept_key = %(c)s OR c.parent = %(c)s)")
        params["c"] = concept
    if term:
        where.append("(i.indicator ILIKE %(q)s OR i.name_en ILIKE %(q)s)")
        params["q"] = f"%{term}%"
    if measure_kind:
        where.append("i.measure_kind = %(k)s")
        params["k"] = measure_kind
    params["lim"] = limit
    rows = q_cached(f"""
        SELECT i.indicator, i.concept_key, i.measure_kind, i.polarity,
               i.canonical_unit, i.grain, i.place_grain, i.notes,
               x.n AS rows_served, x.from_date, x.to_date
        FROM indicator_def i
        LEFT JOIN concept c ON c.key = i.concept_key
        JOIN (SELECT indicator, count(*) n, min(occurred_at)::date from_date,
                     max(occurred_at)::date to_date
              FROM databank_serving GROUP BY 1) x ON x.indicator = i.indicator
        WHERE {' AND '.join(where)}
        ORDER BY x.n DESC LIMIT %(lim)s""", params)
    return {"indicators": rows, "count": len(rows),
            "note": "measure_kind governs what may be done with a series: a "
                    "cumulative one must be differenced through /v2/databank/"
                    "flow before it is compared to anything."}


# THE UNIT OF A POINT IS THE UNIT ITS VALUE IS IN. `value` is the unit
# registry's conversion when one applied (value_canonical, in resolved_unit)
# and the source's own number otherwise (value_num, in unit). The label used to
# be COALESCE(canonical_unit, unit) — canonical_unit read from indicator_def,
# which the food rule sets to ILS_per_kg for EVERY food.price.* — so drinking
# water priced per cubic metre came back divided by 1,000 and labelled per
# kilogram, cooking oil and milk per-litre prices were labelled per kilogram,
# and an unconverted raw value wore the canonical label it was never put in.
_POINT_UNIT_SQL = ("CASE WHEN v.value_canonical IS NOT NULL THEN v.resolved_unit "
                   "ELSE v.unit END")


def _units_of(points: list[dict]) -> list[str]:
    return sorted({p["unit"] for p in points if p.get("unit")})


def _series(indicator: str, place_id: int | None, frm: date | str | None,
            to: date | str | None) -> dict:
    where = ["v.indicator = %(i)s"]
    params: dict = {"i": indicator}
    if place_id is not None:
        where.append("v.place_id = %(p)s")
        params["p"] = place_id
    if frm:
        where.append("v.occurred_at >= %(f)s")
        params["f"] = frm
    if to:
        where.append("v.occurred_at <= %(t)s")
        params["t"] = to
    pts = q(f"""SELECT v.occurred_at::date AS at, v.occurred_precision AS prec,
                       COALESCE(v.value_canonical, v.value_num) AS value,
                       {_POINT_UNIT_SQL} AS unit,
                       v.source_name, v.attribution_text
                FROM v_observation_canonical v
                WHERE {' AND '.join(where)} ORDER BY 1""", params)
    meta = q("""SELECT concept_key, measure_kind, polarity, grain, place_grain,
                       canonical_unit
                FROM indicator_def WHERE indicator = %(i)s""",
             {"i": indicator})
    m = meta[0] if meta else {"concept_key": None, "measure_kind": None,
                              "polarity": None, "grain": None,
                              "place_grain": None, "canonical_unit": None}
    m = dict(m)
    # Attribution travels ONCE per series. It used to travel on every point:
    # two food-price series came back as 429 KB, of which the numbers were a
    # few kilobytes and the rest was the same sentence repeated per row.
    sources = sorted({p["source_name"] for p in pts if p["source_name"]})
    attribution = sorted({p["attribution_text"] for p in pts if p["attribution_text"]})
    for p in pts:
        p.pop("source_name", None)
        p.pop("attribution_text", None)
    # The series' unit is what its points are served in. The registry's label
    # is kept as `declared_unit`; where the points disagree with each other the
    # series has no single unit, and says so instead of borrowing one.
    units = _units_of(pts)
    m["declared_unit"] = m.get("canonical_unit")
    if len(units) == 1:
        m["canonical_unit"] = units[0]
    elif len(units) > 1:
        m["canonical_unit"] = None
    return {**m, "known": bool(meta), "indicator": indicator,
            "points": pts, "n": len(pts),
            "units": units, "unit_mixed": len(units) > 1,
            "sources": sources, "source_names": set(sources),
            "attribution": attribution}


@app.get("/v2/databank/compare", tags=["databank"])
def databank_compare(indicators: str = Query(..., max_length=600),
                     place_id: int | None = None,
                     # Dates, validated: a free string reached `%s` in SQL and
                     # 'yesterday' or 2026-13-01 was a 500 instead of a 422.
                     frm: date | None = None, to: date | None = None) -> dict:
    """N series side by side, each keeping its own unit and attribution.

    Deliberately does NOT rescale anything to a common axis. Two series with
    different units on one axis is a chart that lies; the caller gets the
    numbers, the units, the native grain and the overlap window, and decides.
    """
    keys = [s.strip() for s in indicators.split(",") if s.strip()][:6]
    if len(keys) < 2:
        raise HTTPException(422, "pass at least two indicators, comma-separated")
    series = [_series(k, place_id, frm, to) for k in keys]
    dated = [{p["at"] for p in s["points"]} for s in series if s["points"]]
    overlap = set.intersection(*dated) if len(dated) == len(series) else set()
    return {
        "series": [{k: v for k, v in s.items() if k != "source_names"}
                   for s in series],
        "overlap": {"from": min(overlap).isoformat() if overlap else None,
                    "to": max(overlap).isoformat() if overlap else None,
                    "n": len(overlap)},
        "note": "Nothing here is rescaled to a shared axis. Each series keeps "
                "its own unit, its own grain and its own attribution — "
                "plotting two units on one axis is a chart that lies.",
    }


@app.get("/v2/databank/correlate", tags=["databank"])
def databank_correlate(a: str, b: str, place_id: int | None = None,
                       frm: date | None = None, to: date | None = None,
                       # A closed vocabulary: any other word silently computed
                       # Pearson and labelled the result with the caller's word.
                       method: Literal["spearman", "pearson"] = "spearman",
                       # BOUNDED. The lag loop runs 2·max_lag+1 passes over every
                       # point on a sync worker thread, and an unbounded value
                       # (~700k days is the ceiling before a date overflows) held
                       # a thread for minutes; forty such GETs, inside one
                       # address's read allowance, filled the threadpool and
                       # hung checkpoint_status and can_i_travel. A year of days
                       # covers every lag worth asking about.
                       max_lag: int = Query(0, ge=0, le=365,
                                            description="days to scan either side"),
                       allow_same_concept: bool = False,
                       detrend: Literal["diff"] | None = Query(
                           None, description="`diff`: correlate period-to-period "
                                             "changes, for two series that trend")) -> dict:
    """Whether two series move together — or an explanation of why asking is
    the wrong question.

    Every refusal below returns a REASON and no number. A coefficient with a
    warning stapled to it gets quoted without the warning.
    """
    from serve import correlate as C
    sa, sb = _series(a, place_id, frm, to), _series(b, place_id, frm, to)
    # Three different absences, three different answers. Conflating them
    # sends the caller to fix a spec when they made a typo, or to widen a
    # date range when the series was never there.
    unknown = [k for k, s in ((a, sa), (b, sb)) if not s["known"]]
    if unknown:
        return {"refused": True, "a": a, "b": b, "reasons": [
            f"no series named {k!r} — search /v2/databank/indicators?q= to "
            "find the right string." for k in unknown]}
    empty = [k for k, s in ((a, sa), (b, sb)) if not s["points"]]
    if empty:
        window = " in the requested window" if (frm or to) else ""
        where = f" at place_id {place_id}" if place_id else ""
        return {"refused": True, "a": a, "b": b, "reasons": [
            f"{k} exists but has no points{where}{window}." for k in empty]}
    stop = C.check_comparable(sa, sb)
    if allow_same_concept:
        stop = [s for s in stop if "both series are" not in s]
    if stop:
        return {"refused": True, "reasons": stop,
                "a": a, "b": b,
                "note": "No coefficient is returned. These refusals are hard "
                        "by design — a number with a caveat attached gets "
                        "quoted without the caveat."}
    # One point per date, or a refusal naming the dates that carry several —
    # see correlate.collapse_by_date for the row-order bug this replaced.
    by_a, conf_a = C.collapse_by_date(sa["points"])
    by_b, conf_b = C.collapse_by_date(sb["points"])
    several = [C.several_rows_reason(k, c, len(c) + len(by))
               for k, c, by in ((a, conf_a, by_a), (b, conf_b, by_b)) if c]
    if several:
        return {"refused": True, "a": a, "b": b, "reasons": several}
    got = C.fit(by_a, by_b, method, max_lag, detrend)
    if "reason" in got:
        return {"refused": True, "a": a, "b": b, "reasons": [got["reason"]]}
    rho, lag, pairs = got["rho"], got["lag"], got["pairs"]
    if detrend is None:
        trend = C.shared_trend(got["raw_pairs"])
        if trend:
            return {"refused": True, "a": a, "b": b,
                    "reasons": [C.trend_reason(a, b, trend)],
                    "note": "No coefficient is returned. A shared trend makes "
                            "any two series look related; detrend=diff asks "
                            "the question that is left."}
    ci = C.fisher_ci(rho, len(pairs))
    return {
        "refused": False, "a": a, "b": b, "method": method,
        "detrend": detrend,
        "rho": round(rho, 4), "n": len(pairs), "lag_days": lag,
        "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
        "overlap": {"from": min(p[2] for p in pairs).isoformat(),
                    "to": max(p[2] for p in pairs).isoformat()},
        "plain_english": C.describe(rho, sa, sb),
        "caveats": C.caveats(sa, sb, pairs, lag, detrend),
        "attribution": sorted(set(sa["attribution"]) | set(sb["attribution"])),
    }


@app.get("/v2/databank/correlate/scan", tags=["databank"])
def databank_correlate_scan(
    a: str, place_id: int | None = None, frm: date | None = None,
    to: date | None = None, method: Literal["spearman", "pearson"] = "spearman",
    candidates: int = Query(40, ge=5, le=120),
    allow_same_concept: bool = False,
    detrend: Literal["diff"] | None = None,
) -> dict:
    """What, out of everything held, moves with this series.

    The pairwise endpoint answers a question the caller already had. This one
    is for the question they cannot ask yet, because naming both sides requires
    knowing 1,349 indicator strings — so in practice `correlate` only ever got
    asked about pairs somebody already suspected, which is a search that can
    only confirm.

    THE REFUSALS ARE STILL THE POINT, AND HARDER HERE
    A scan is a multiple-comparisons machine: run forty tests at p<0.05 and two
    come back "significant" from noise alone. So every candidate goes through
    the SAME check_comparable gate as a pairwise call — cumulative totals,
    categorical statuses, mismatched place grains and same-concept pairs are
    dropped before any arithmetic — and what survives is reported with the
    number of tests it survived beside it. A coefficient from a scan is a
    hypothesis, and the response says so rather than implying a finding.

    Ranked results carry no caveats on purpose: call /v2/databank/correlate on
    the pair to get them. Finding is not the same act as concluding, and
    keeping them separate is what stops a scan from reading like a result.
    """
    from serve import correlate as C
    sa = _series(a, place_id, frm, to)
    if not sa["known"]:
        return {"refused": True, "a": a, "reasons": [
            f"no series named {a!r} — search /v2/databank/indicators?q= to "
            "find the right string."]}
    if not sa["points"]:
        return {"refused": True, "a": a, "reasons": [
            f"{a} exists but has no points in that window or place."]}

    if sa["unit_mixed"]:
        return {"refused": True, "a": a, "reasons": [
            f"{a}: its points are in different units ({', '.join(sa['units'])}); "
            "it cannot be ranked against anything as one series."]}
    by_a, conf_a = C.collapse_by_date(sa["points"])
    if conf_a:
        return {"refused": True, "a": a, "reasons": [
            C.several_rows_reason(a, conf_a, len(conf_a) + len(by_a))]}

    # Prefiltered in SQL only for speed — check_comparable below remains the
    # authority, so this cannot quietly allow something the pairwise path
    # would refuse. Cached: both reads are whole-view aggregates over a
    # databank that changes nightly, and a partner scripting a scan over a few
    # dozen indicators re-ran them per call.
    rows = q_cached("""
        SELECT d.indicator, d.concept_key, d.measure_kind, d.place_grain,
               d.grain, d.canonical_unit, COUNT(*) AS n
          FROM indicator_def d
          JOIN v_observation_canonical v ON v.indicator = d.indicator
         WHERE d.indicator <> %(a)s
           AND d.place_grain IS NOT DISTINCT FROM %(grain)s
           AND d.measure_kind NOT IN ('cumulative', 'status', 'unclassified')
           AND d.measure_kind IS NOT NULL
           AND (%(p)s::int IS NULL OR v.place_id = %(p)s)
         GROUP BY 1, 2, 3, 4, 5, 6
        HAVING COUNT(*) >= %(minn)s
         ORDER BY n DESC
         LIMIT %(lim)s
    """, {"a": a, "grain": sa["place_grain"], "p": place_id,
          "minn": C.MIN_N, "lim": candidates})
    if not rows:
        return {"refused": True, "a": a, "reasons": [
            f"nothing else held is comparable to {a}: no other series shares "
            f"its place grain ({sa['place_grain']}) with enough points."]}

    # One query for every candidate's points rather than one per candidate.
    where = ["v.indicator = ANY(%(inds)s)"]
    params: dict = {"inds": [r["indicator"] for r in rows]}
    if place_id is not None:
        where.append("v.place_id = %(p)s")
        params["p"] = place_id
    if frm:
        where.append("v.occurred_at >= %(f)s")
        params["f"] = frm
    if to:
        where.append("v.occurred_at <= %(t)s")
        params["t"] = to
    pts = q_cached(f"""SELECT v.indicator, v.occurred_at::date AS at,
                       v.occurred_precision AS prec,
                       COALESCE(v.value_canonical, v.value_num) AS value,
                       {_POINT_UNIT_SQL} AS unit
                  FROM v_observation_canonical v
                 WHERE {' AND '.join(where)}""", params)
    grouped: dict[str, list] = {}
    for p in pts:
        grouped.setdefault(p["indicator"], []).append(p)

    hits, skipped, tested = [], Counter(), 0
    for r in rows:
        points = grouped.get(r["indicator"], [])
        units = _units_of(points)
        sb = {**r, "known": True, "points": points, "units": units,
              "unit_mixed": len(units) > 1}
        # check_comparable now refuses different time grains itself, for both
        # endpoints alike. Series are paired on exact dates, so a daily series
        # and an annual one can never meet and would come back as "too few
        # overlapping dates" — which reads as "no relationship" when it means
        # "these two were never measured on the same day". Resampling one to
        # the other's period would create the overlap, and a number built on
        # twelve invented monthly points is exactly the kind of confident
        # artifact the rest of this file refuses to produce.
        stop = C.check_comparable(sa, sb)
        if allow_same_concept:
            stop = [s for s in stop if "both series are" not in s]
        if stop:
            skipped[_skip_reason(stop[0])] += 1
            continue
        # The candidate is collapsed too: pairing every one of its rows whose
        # date `a` held reported n=312 "overlapping points" from 24 months.
        by_b, conf_b = C.collapse_by_date(points)
        if conf_b:
            skipped["several rows per date (pass place_id)"] += 1
            continue
        got = C.fit(by_a, by_b, method, 0, detrend)
        if "reason" in got:
            skipped["no variance in one series" if "does not vary" in got["reason"]
                    else "too few overlapping dates"] += 1
            continue
        if detrend is None and C.shared_trend(got["raw_pairs"]):
            skipped["shared time trend (ask with detrend=diff)"] += 1
            continue
        tested += 1
        rho, pairs = got["rho"], got["pairs"]
        ci = C.fisher_ci(rho, len(pairs))
        hits.append({"indicator": r["indicator"], "concept": r["concept_key"],
                     "rho": round(rho, 4), "n": len(pairs),
                     "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
                     # the unit the candidate's points are served in, not the
                     # registry's label (see _POINT_UNIT_SQL)
                     "unit": units[0] if len(units) == 1 else r["canonical_unit"]})

    hits.sort(key=lambda h: -abs(h["rho"]))
    return {
        "refused": False, "a": a, "method": method, "detrend": detrend,
        "considered": len(rows), "tested": tested,
        "skipped": dict(skipped),
        "capped_at": candidates,
        "truncated": len(rows) == candidates,
        "matches": hits[:15],
        "multiple_comparisons": C.expected_false_positives(tested),
        "next": ("/v2/databank/correlate?a=…&b=… returns the caveats, the "
                 "attribution and the lag search for one pair. This endpoint "
                 "deliberately returns none of those: finding is not "
                 "concluding."),
    }


def _skip_reason(reason: str) -> str:
    """Collapse a full refusal sentence into something countable."""
    for needle, label in (("CUMULATIVE", "cumulative — a running total"),
                          ("categorical", "categorical status"),
                          ("place grains differ", "different place grain"),
                          ("both series are", "same concept as the subject"),
                          ("measure_kind is unclassified", "kind unclassified"),
                          ("time grains differ", "different time grain"),
                          ("different units", "points in mixed units")):
        if needle in reason:
            return label
    return "not comparable"


@app.get("/v2/databank/{category}", tags=["databank"])
def databank_category(category: str, indicator: str | None = Query(None, max_length=120),
                      # A date, validated: a free string was cast in SQL and an
                      # invalid one (2026-13-01) was a 500 instead of a 422.
                      as_of: date | None = None, memorial: bool = False,
                      limit: int = Query(200, ge=1, le=2000)) -> dict:
    """Rows from one category. `as_of=YYYY-MM-DD` reconstructs what v1's
    archive served on that day (validity-tracked; superseded values appear
    at their own time and never at the present)."""
    if category == "martyrs_snapshot_2023" and not memorial:
        # Serving posture (decided 2026-08-05): the license permits per-name
        # serving; decency defaults to aggregates. `memorial=true` opens the
        # per-name view as a deliberate act, never as a default row dump.
        rows = q_cached("""
            SELECT CASE WHEN (attrs->>'age')::int < 13 THEN 'children_under_13'
                        WHEN (attrs->>'age')::int < 18 THEN 'ages_13_17'
                        WHEN (attrs->>'age')::int < 40 THEN 'ages_18_39'
                        WHEN (attrs->>'age')::int < 65 THEN 'ages_40_64'
                        ELSE 'ages_65_plus' END AS age_band,
                   attrs->>'sex' AS sex, COUNT(*) AS n
            FROM databank_serving
            WHERE v1_category = 'martyrs_snapshot_2023'
              AND indicator = 'martyrs.identified_killed'
            GROUP BY 1, 2 ORDER BY 1, 2""")
        total = sum(r["n"] for r in rows)
        return {"category": category, "memorial": False,
                "identified_total": total,
                "by_age_and_sex": rows,
                "note": "Named records exist and are public memorial data "
                        "(Gaza MoH via Tech4Palestine, public domain/Unlicense). Pass "
                        "memorial=true to read them, deliberately.",
                "attribution": ["Data: Tech4Palestine "
                                "(data.techforpalestine.org), public domain (Unlicense)."]}
    if category == "water":
        # water is a DOMAIN, not just a dataset bucket (decided 2026-08-06):
        # its own datasets PLUS the JMP WASH access series that lives — with
        # full GHO identity — inside v1_health_who. One fact, served once,
        # reachable from both the water and health categories; indicator
        # names keep their home namespace so provenance stays visible.
        conds, params = ["(d.v1_category = 'water' OR o.indicator LIKE %s)"], \
            ["health.wsh%"]
    else:
        conds, params = ["d.v1_category = %s"], [category]
    if indicator:
        conds.append("o.indicator LIKE %s")
        params.append(indicator + "%")
    if as_of:
        conds.append("o.sys_period @> %s::date::timestamptz")
    else:
        conds.append("upper_inf(o.sys_period)")
    # LICENCE AT THE DATASET GRAIN, falling back to the source (054): a portal
    # is not a licence-holder. Read straight from `source`, the HDX-carried
    # education (2,359 rows) and infrastructure (603) datasets were credited to
    # "Humanitarian Data Exchange … License varies by dataset" instead of the
    # OCHA/UNICEF CC-BY and CC-BY-IGO terms 065 recorded, and the payload
    # contradicted /v2/databank/licenses for the same rows. Every licence column
    # is COALESCEd the way databank_serving does, and each row names its
    # dataset, source and licence so the credit travels with the datum.
    sql = f"""
        SELECT o.indicator, o.occurred_at, o.occurred_precision::text,
               o.value_num, o.value_text, o.unit, o.attrs,
               p.name_en AS place_en, p.name_ar AS place_ar,
               d.key AS dataset_key, s.key AS source_key,
               COALESCE(d.attribution_text, s.attribution_text) AS attribution_text,
               COALESCE(d.license_spdx, s.license_spdx)         AS license_spdx,
               COALESCE(d.redistribution, s.redistribution)     AS redistribution
        FROM observation o
        JOIN dataset d ON d.dataset_id = o.dataset_id
        JOIN source s ON s.source_id = d.source_id
        LEFT JOIN place p ON p.place_id = o.place_id
        WHERE o.v1_stable_id IS NOT NULL AND {' AND '.join(conds)}
        ORDER BY o.occurred_at DESC LIMIT %s"""
    # An `as_of` reconstruction must never come out of a cache keyed on the
    # present, so the historical path keeps the plain connection-per-call q().
    runner = q if as_of else q_cached
    rows = runner(sql, tuple(params + ([as_of] if as_of else []) + [limit]))
    return {"category": category, "as_of": as_of, "count": len(rows),
            "items": [{k: r[k] for k in
                       ("indicator", "occurred_at", "occurred_precision",
                        "value_num", "value_text", "unit", "place_en",
                        "place_ar", "attrs", "dataset_key", "source_key",
                        "license_spdx", "redistribution")} for r in rows],
            "attribution": sorted({r["attribution_text"] for r in rows})}
