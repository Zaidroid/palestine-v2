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
import re
import os
import sys
import threading
import time
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from resolve.db import dsn, env_value

# .env is the source of truth (ops/sync-valhalla-ip.sh keeps it current);
# no hardcoded IP fallback — a wrong default is worse than a loud miss.
VALHALLA = env_value("VALHALLA_URL", "http://wb-valhalla:8002")

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
    # One pooled connection per statement when psycopg_pool is installed,
    # a fresh one otherwise (resolve/db.py, audit F293/F287).
    from resolve.db import connection
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
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
# P1-B.6 (2026-09-25): the key is the databank ONLY. The TTL was 60 s and every
# DRY run appended to the runs ledger (2,258 of its 3,545 records), so the
# most-called public routes were cold most of the time. Now the runs stamp is
# the last load that actually WROTE rows, the watermark also sees inserts and
# the held events (083), and the TTL is a safety bound, not the invalidator.
CACHE_TTL_SECONDS = 6 * 3600
WATERMARK_SECONDS = 300
_RUNS_SEEN: dict[str, Any] = {"stat": None, "stamp": ""}
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



def _runs_stamp() -> str:
    """The timestamp of the last load that wrote something. The file is only
    re-read when its (mtime, size) changes, and then only its tail."""
    try:
        st = DATABANK_RUNS.stat()
    except OSError:
        return ""
    key = (st.st_mtime_ns, st.st_size)
    if _RUNS_SEEN["stat"] != key:
        stamp = _RUNS_SEEN["stamp"]
        try:
            with DATABANK_RUNS.open("rb") as fh:
                fh.seek(max(0, st.st_size - 256 * 1024))
                for line in fh.read().decode("utf-8", "replace").splitlines():
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if (not rec.get("dry_run") and ((rec.get("written") or 0)
                                                   + (rec.get("events_written") or 0)) > 0):
                        stamp = max(stamp, str(rec.get("ts") or ""))
        except OSError:
            pass
        _RUNS_SEEN.update(stat=key, stamp=stamp)
    return _RUNS_SEEN["stamp"]


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
                # lower() sees inserts AND supersessions (upper() sees only
                # the latter); the event table carries the held registers (083).
                rows = q("""SELECT (SELECT max(lower(sys_period)) FROM observation)::text
                                    || '|' || (SELECT max(upper(sys_period)) FROM observation)::text
                                    || '|' || (SELECT max(updated_at) FROM event
                                                WHERE attrs->>'dataset_key' LIKE 'v1_%%')::text AS w""")
                _WATERMARK["value"] = (rows[0]["w"] if rows else "") or ""
                _WATERMARK["at"] = time.monotonic()
    return _WATERMARK["value"]


def q_cached(sql: str, params: tuple = ()) -> list[dict]:
    """`q` with a memory, for the aggregates that read the whole databank."""
    # A dict of named parameters is not hashable and must still key the cache:
    # `insights` passes %(lat)s-style params, and a TypeError here would 500 the
    # route rather than miss the cache.
    key = (sql, tuple(sorted(params.items())) if isinstance(params, dict) else params)
    stamp = (_runs_stamp(), _databank_watermark())
    entry = _QUERY_CACHE.get(key)
    now = time.monotonic()
    if entry and entry[0] == stamp and (now - entry[1]) < CACHE_TTL_SECONDS:
        _QUERY_CACHE.move_to_end(key)          # a hit refreshes recency
        return entry[2]
    rows = q(sql, params)
    _QUERY_CACHE[key] = (stamp, now, rows)
    _QUERY_CACHE.move_to_end(key)
    while len(_QUERY_CACHE) > QUERY_CACHE_MAX:
        _QUERY_CACHE.popitem(last=False)       # evict least recently used
    return rows


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
    # Reachability is `SELECT 1`. The two fuel queries that stood here read
    # state_current (hard rule 6) and published the RETIRED fuel feed's age as
    # `feed_age_minutes` — a number that grew by 1,440 a day beside status:ok
    # (audit F160/F364). Gone; the fields with it.
    try:
        q("SELECT 1")
    except Exception as e:                              # noqa: BLE001
        raise HTTPException(503, f"database unavailable: {e}")

    # EVERY watchdog family, not only jobs and feeds: a full disk or a Valhalla
    # port collision used to leave this green while /v2/route 503ed (F288).
    try:
        from ops.watchdog import all_checks
        fam = all_checks()
        jobs, feeds, others = fam["jobs"], fam["feeds"], fam["others"]
        checks = jobs + feeds + others
        faults = [c for c in checks if c["fault"]]
    except Exception as e:                              # noqa: BLE001
        return {"status": "unknown", "error": f"health checks unavailable: {e}"}

    from serve.ratelimit import client_ip, is_local
    local = is_local(client_ip(request))

    families: dict[str, dict[str, int]] = {}
    for c in checks:
        f = families.setdefault(str(c.get("check") or "other"), {"ok": 0, "faults": 0})
        f["faults" if c["fault"] else "ok"] += 1
    from resolve.db import ROOT as _root
    maintenance = (_root / "ops" / "maintenance.flag").exists()
    from resolve.db import pool_status
    out: dict[str, Any] = {
        "status": "maintenance" if maintenance else ("degraded" if faults else "ok"),
        "maintenance": maintenance,
        "faults": [f"{c['check']}:{c['name']} {c['status']}" for c in faults] if local else [],
        "faults_total": len(faults),
        "families": families,
        "jobs_ok": sum(1 for c in jobs if not c["fault"]),
        "jobs_total": len(jobs),
        "feeds_ok": sum(1 for c in feeds if not c["fault"]),
        "feeds_total": len(feeds),
        "db": pool_status() if local else {"pooled": pool_status().get("pooled")},
    }
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
            "others": [{"family": c.get("check"), "name": c["name"], "status": c["status"],
                        "detail": c.get("detail")} for c in others],
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
    c.presence_age_minutes, c.passable, c.cadence_measured, c.differs_by_direction,
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
        # Since 079 the default row is the WORSE direction: `reported_for`
        # names the direction the reading came from and
        # `differs_by_direction` says the two travel directions disagree, so
        # a closure in one direction is never read as both (audit F089).
        "reported_for": r.get("reported_for"),
        "differs_by_direction": r.get("differs_by_direction"),
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
        # A fresh inspection sighting, said as a word beside the flow (P1-A.2);
        # `present` stays the separate axis it has always been.
        "searching": "inspection" in (r["present"] or []),
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
    from resolve.geo import _token_match

    n, f = normalize(name), fold_for_match(name)
    if not n:
        return None
    rows = q("""
        SELECT p.place_id, p.name_ar, p.name_en,
               COALESCE(o.n, 0) AS obs, o.latest AS latest,
               COALESCE(array_agg(a.alias_norm) FILTER (WHERE a.alias_norm IS NOT NULL),
                        ARRAY[]::text[]) AS aliases
        FROM place p
        LEFT JOIN place_alias a ON a.place_id = p.place_id
        -- Evidence for the tie-break from state_current (one row per place,
        -- kind and direction), not a COUNT over every checkpoint_flow row ever
        -- stored: that aggregate decompressed the whole hypertable on every
        -- checkpoint_status call for a 0.04-point tie-break (audit F296).
        LEFT JOIN (SELECT place_id, COUNT(*) n, MAX(observed_at) latest FROM state_current
                   WHERE state_kind = 'checkpoint_flow' GROUP BY 1) o ON o.place_id = p.place_id
        WHERE p.servable AND p.kind IN ('checkpoint','crossing','road')
        GROUP BY p.place_id, p.name_ar, p.name_en, o.n, o.latest""")

    def _sim(a: str, b: str) -> float:
        # A misspelling keeps its first letter (Hawara/Huwara); a lookalike of
        # another name usually does not (Hawara/Awarta, Zatara/Atara). Both
        # score 0.833 by pure edit similarity; the initial is what tells them
        # apart, so a changed initial costs a tenth.
        r_ = SequenceMatcher(None, a, b).ratio()
        return r_ - 0.10 if (a and b and a[0] != b[0]) else r_

    def _key(r) -> str:                       # rows that share a name are one candidate
        return (r["name_en"] or r["name_ar"] or "").lower()

    best, best_raw, best_score, best_ratio = None, 0.0, 0.0, 1.0
    ratio_by_name: dict[str, float] = {}
    for r in rows:
        names = [x for x in (r["name_ar"], r["name_en"]) if x]
        # A Latin registry name carries a parenthetical and an apostrophe
        # ("Za'tara (Tapuach)"): matched whole, `Zatara` sat closer to Atara's
        # row than to its own (audit F070). The bare form is a name too.
        bare = [re.sub(r"\s*\(.*?\)", "", x).replace("'", "").strip() for x in names]
        norms = {normalize(x) for x in names + bare if x}
        folds = {fold_for_match(x) for x in names + bare if x}
        aliases = set(r["aliases"] or [])
        ratio = 1.0

        if n in norms:
            score = 1.00
        elif n in aliases:
            score = 0.95
        elif f and f in folds:
            score = 0.90
        elif any(n and (_token_match(x, n) or _token_match(n, x)) for x in norms if x):
            # Whole-token containment ("حاجز حوارة" ⊃ "حوارة"), not a fragment
            # inside an unrelated word (audit F070).
            score = 0.85
        else:
            ratio = max((_sim(n, x) for x in norms if x), default=0.0)
            if ratio < 0.78:
                continue
            score = ratio * 0.8
            ratio_by_name[_key(r)] = max(ratio_by_name.get(_key(r), 0.0), ratio)
        # Evidence breaks ties: among equally-named candidates the one people
        # actually report about is the one they mean — the row with readings,
        # and the one read RECENTLY (two rows are named 'Huwara'; one is a
        # gate row last reported 106 days ago). The comparison keeps the
        # bonus; only the SERVED score is capped at 1.0 (F070).
        latest = r.get("latest")
        recent = latest is not None and (datetime.now(timezone.utc) - latest).days <= 30
        raw = score + min(r["obs"], 3) / 3 * 0.04 + (0.02 if recent else 0.0)
        if raw > best_raw:
            best, best_raw, best_score, best_ratio = r, raw, min(1.0, raw), ratio
    if not best:
        return None
    # A fuzzy match is served WITH its doubt spoken (tests/test_name_safety.py)
    # when it is a close misspelling of one name — `Hawara` → Huwara at 0.83.
    # It is NAMED, not served, when it is far from every name or when another
    # NAME sits nearly as close: that is a lookalike, not a spelling (F070).
    runner_up = max((v for k, v in ratio_by_name.items() if k != _key(best)), default=0.0)
    uncertain = best_ratio < 1.0 and (best_ratio < FUZZY_SERVE_RATIO
                                      or runner_up >= best_ratio - AMBIGUOUS_MARGIN)
    return {"place_id": best["place_id"],
            "name": best["name_ar"] or best["name_en"],
            "name_en": best["name_en"] or None,
            "score": round(best_score, 3),
            "uncertain": uncertain}


# A fuzzy match below this similarity, or with a rival this close behind it,
# is reported as `nearest` with no reading.
FUZZY_SERVE_RATIO = 0.80
AMBIGUOUS_MARGIN = 0.05


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
    if m.get("uncertain"):
        return {"found": False, "query": name,
                "nearest": {"name": m["name"], "score": m["score"]},
                "reason": "no checkpoint by that name; the nearest spelling is "
                          "named, not served (match below the gate)"}
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
        "related": _related_incidents(m["place_id"]),
        "attribution": CHECKPOINT_ATTRIBUTION,
    }


# P2-C.1: the two tiers, side by side. What happened near a checkpoint in the
# same hours — a CO-OCCURRENCE, never a cause: a closure at 14:30 and a raid
# 2 km away at 14:05 are two facts in one place and time, and saying one caused
# the other would be a claim nobody measured. Named places only, so a
# governorate-level "siege of Nablus" never attaches to every Nablus checkpoint.
RELATED_METRES = 2000
RELATED_HOURS = 3


def _related_incidents(place_id: int) -> list[dict]:
    try:
        rows = q("""
            SELECT e.event_id, e.event_type AS type, p2.name_ar AS name, p2.name_en,
                   round(ST_Distance(e.geom, p.centroid)::numeric) AS metres,
                   (extract(epoch FROM now() - e.occurred_at) / 60)::int AS age_minutes,
                   e.independent_sources
              FROM place p
              JOIN event e ON ST_DWithin(e.geom, p.centroid, %(m)s)
              LEFT JOIN place p2 ON p2.place_id = e.place_id
             WHERE p.place_id = %(pid)s AND e.status = 'believed'
               AND e.attrs->>'place_precision' = 'named'
               AND e.event_type IN ('closure','siege','raid','settler_attack','shooting',
                                    'arrest','injury','death')
               AND e.occurred_at > now() - make_interval(hours => %(h)s)
               AND e.occurred_at <= now() + interval '10 minutes'
             ORDER BY e.occurred_at DESC LIMIT 4""",
                 {"m": RELATED_METRES, "pid": place_id, "h": RELATED_HOURS})
    except Exception:                                            # noqa: BLE001
        return []
    return [{**r, "metres": int(r["metres"]), "age_minutes": max(0, int(r["age_minutes"])),
             "relation": "co-occurrence"} for r in rows]


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
    # Where a search is going on right now, by name (P1-A.2): the count alone
    # under `presence` told a traveller nothing they could act on.
    searching_now = q(f"""SELECT {CHECKPOINT_COLS} FROM checkpoint_serving c
                          WHERE c.direction = 'both' AND 'inspection' = ANY(c.present)
                          ORDER BY c.presence_age_minutes NULLS LAST LIMIT 20""")
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
        "searching_now": [_checkpoint_out(r) for r in searching_now],
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
                      "signals_agreeing": _signals_agreeing(
                          net[0]["value"], (net[0]["attrs"] or {}).get("signals")),
                      "signals_total": len((net[0]["attrs"] or {}).get("signals") or {}),
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


def _signals_agreeing(status: str | None, signals: dict | None) -> int | None:
    """How many of IODA's vantage points agree with the asserted status.

    `independent_sources` is 1 by construction (one source, IODA), and was
    served as `signals_agreeing` — always 1 — while the whole design is that
    three signals must agree before an outage is asserted (Claude web's test,
    2026-09-25). Counted from the signal ratios with the loader's thresholds."""
    if not signals or not status:
        return None
    from ingest.sources.connectivity import DEGRADED_RATIO, OUTAGE_RATIO
    ratios = [float(v.get("ratio")) for v in signals.values()
              if isinstance(v, dict) and v.get("ratio") is not None]
    if status == "outage":
        return sum(r < OUTAGE_RATIO for r in ratios)
    if status == "degraded":
        return sum(r < DEGRADED_RATIO for r in ratios)
    if status == "normal":
        return sum(r >= DEGRADED_RATIO for r in ratios)
    return None


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
            "signals_agreeing": _signals_agreeing(r["value"], (r["attrs"] or {}).get("signals")),
            "signals_total": len((r["attrs"] or {}).get("signals") or {}),
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
            # Stated, not implied: this is the posting time, hour-precision.
            "occurred_precision": "hour",
            "confidence": round(float(r["confidence"]), 3),
            "reports": r["claim_count"],
            "independent_sources": r["independent_sources"],
            "channels": _channel_labels((r["attrs"] or {}).get("channels")),
            # P2-C.2: published articles about this incident (ops/press_links.py)
            # — a SOURCE a reader can follow, never a second witness.
            "press": [{"source": x.get("source"), "title": x.get("title"), "url": x.get("url")}
                      for x in ((r["attrs"] or {}).get("press") or [])][:3],
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
            out.append(keys.get(int(u[4:]), u))
        else:
            out.append(u)
    return out


@functools.lru_cache(maxsize=1)
def _source_keys() -> dict[int, str]:
    return {int(r["source_id"]): r["key"] for r in q("SELECT source_id, key FROM source")}


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
    by_place = q("""SELECT p.name_ar, p.name_en, COUNT(*) n
                    FROM event e JOIN place p ON p.place_id = e.place_id
                    WHERE e.status='believed'
                      AND e.occurred_at > now() - make_interval(hours => %s)
                      AND COALESCE(e.attrs->>'place_precision', 'named') = 'named'
                    GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15""", (hours,))
    gov_only = q("""SELECT COUNT(*) n FROM event e
                    WHERE e.status='believed'
                      AND e.occurred_at > now() - make_interval(hours => %s)
                      AND e.attrs->>'place_precision' IN ('governorate', 'village_ambiguous')""",
                 (hours,))
    ledger = q("""SELECT verdict, reject_reason, COUNT(*) n
                  FROM claim_classification GROUP BY 1,2 ORDER BY 3 DESC""")
    from serve.quality import annotate_by_type, summary as precision_summary
    types = {r["event_type"]: {"n": r["n"], "corroborated": r["corroborated"]} for r in by_type}
    return {
        "window_hours": hours,
        "total": sum(r["n"] for r in by_type),
        # Every count carries what the last hand-scored round measured for
        # its type (deaths first in the answer): a count from a reader that
        # is right 60 % of the time is a different fact from one at 93 %.
        "by_type": annotate_by_type(types),
        "precision": precision_summary(types),
        "by_place": [{"place": r["name_ar"] or r["name_en"], "n": r["n"]}
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


ROAD_BULLETIN = "🚧"     # palhub's road tables start with it (serve/mcp_server.py too)


@app.get("/v2/news/latest", tags=["news"])
def news_latest(request: Request, area: str | None = None,
                limit: int = Query(10, ge=1, le=100),
                hours: int | None = Query(None, ge=1, le=720),
                text: str | None = Query(None, min_length=2),
                kind: str = Query("all", pattern="^(news|roads|all)$")) -> dict:
    """Most recent ingested messages, optionally filtered by area, text, window.

    `kind`: news leaves out palhub's machine-generated road tables (they start
    with 🚧 and name every checkpoint every 15 minutes, so a text search for a
    checkpoint name over a day is bulletins all the way past any LIMIT — audit
    F047), roads returns only them, all (default, the old shape) everything.

    Resolving the name first is the difference between "Ramallah" returning this
    morning's reports and returning two English-language mentions from July: the
    channel text is Arabic, so a literal Latin match only ever finds the rare
    message that happens to be written in English — and it finds it, however old
    it is, which reads as a quiet area rather than a missed filter.
    """
    # Channel and feed text only. A crowd report is an anonymous POST: its note
    # was served as the newest "news" and quoted into the spoken answer, which
    # is a stranger writing into what an agent reads aloud (audit F075/F079).
    where = ["length(c.raw_text) > 30", "s.kind <> 'crowd'",
             "c.claim_type IS DISTINCT FROM 'crowd_report'"]
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
    if kind == "news":
        where.append("c.raw_text NOT LIKE %s")
        params.append(f"{ROAD_BULLETIN}%")
    elif kind == "roads":
        where.append("c.raw_text LIKE %s")
        params.append(f"{ROAD_BULLETIN}%")
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


def _geo_out(query: str, place_id: int, *, method: str, confidence: float) -> dict:
    """The /v2/geo/resolve answer for a place chosen by id."""
    row = q("""SELECT place_id, name_ar, name_en, kind::text AS kind, admin2_pcode,
                      ST_Y(centroid::geometry) la, ST_X(centroid::geometry) lo
                 FROM place WHERE place_id = %s""", (place_id,))
    if not row or row[0]["la"] is None:
        return {"found": False, "query": query, "reason": "no geometry"}
    r = row[0]
    return {"found": True, "query": query, "place_id": r["place_id"],
            "name": r["name_ar"] or r["name_en"], "name_en": r["name_en"] or None,
            "kind": r["kind"], "precision": "checkpoint",
            "confidence": round(float(confidence), 3), "method": method,
            "admin2_pcode": r["admin2_pcode"], "lat": r["la"], "lon": r["lo"],
            "ambiguous_with": 0}


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
        from resolve.geo import _Ambiguous, _prefer_place_kinds
        options = None
        try:
            with connect() as conn:
                want = _prefer_place_kinds(conn).get(state_kind)
                r = resolve_for_state_kind(conn, q_, state_kind)
        except _Ambiguous as amb:
            r, options = None, amb.options
        # A CHECKPOINT KIND ASKED IN ENGLISH. The kind-aware resolver matches
        # exact names only, so "Huwara" (two checkpoint rows carry it) came back
        # ambiguous and place history/pattern answered "place not found" while
        # checkpoint_status, which scores names and breaks ties on evidence,
        # answered حوارة (Claude web's test, 2026-09-25). Same resolver now.
        if want == "checkpoint" and (r is None or r.kind not in ("checkpoint", "crossing", "road")):
            m = _resolve_checkpoint(q_)
            if m and not m["uncertain"]:
                return _geo_out(q_, m["place_id"], method="checkpoint_name",
                                confidence=m["score"])
        if options:
            names = {row["place_id"]: row for row in q(
                "SELECT place_id, name_ar, name_en FROM place WHERE place_id = ANY(%s)",
                ([pid for pid, _ in options],))}
            return {"found": False, "query": q_, "ambiguous": True,
                    "options": [{"place_id": pid, "name": n,
                                 "name_en": (names.get(pid) or {}).get("name_en") or None}
                                for pid, n in options],
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
    out = {"found": True, "query": q_, "place_id": r.place_id,
           "name": r.name_ar or r.name_en, "name_en": r.name_en or None,
           "kind": r.kind, "precision": r.precision,
           "confidence": round(r.confidence, 3), "method": r.method,
           "admin2_pcode": r.admin2_pcode,
           "lat": row[0]["la"], "lon": row[0]["lo"],
           "ambiguous_with": r.ambiguous_with}
    if not state_kind and r.kind not in ("checkpoint", "crossing", "road"):
        # "Huwara" is a town AND a checkpoint; a plain lookup answers the town
        # and now says the checkpoint exists, so the caller knows to ask for it.
        from resolve.arabic import fold_for_match
        m = _resolve_checkpoint(q_)
        # Only a checkpoint that carries the SAME name as the town: "Nablus"
        # also matched a row named شارع جنين نابلس whose English label is Nablus.
        if (m and not m["uncertain"] and m["score"] >= 0.9 and m["place_id"] != r.place_id
                and fold_for_match(m["name"] or "") == fold_for_match(r.name_ar or r.name_en or "")):
            out["also_checkpoint"] = {"place_id": m["place_id"], "name": m["name"],
                                      "name_en": m.get("name_en")}
    if r.ambiguous_with:
        # Twin villages (المغير in Ramallah AND Jenin) are named, not hidden (F067).
        out["alternatives"] = [{"place_id": pid, "name": nm, "admin2_pcode": a2}
                               for pid, nm, a2 in r.alternatives]
        out["note"] = (f"{r.ambiguous_with + 1} places carry this name; pass the "
                       "governorate (e.g. 'المغير رام الله') to choose")
    return out


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
    cov = {r["state_kind"]: r for r in q(
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
    note: str = Query("", max_length=280,
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
  SELECT DISTINCT s.place_id, p.name_ar, NULLIF(p.name_en, '') AS name_en
    FROM state_serving s
    JOIN place p ON p.place_id = s.place_id
    CROSS JOIN anchor a
   WHERE s.state_kind = 'checkpoint_flow'
     AND ST_DWithin(p.centroid, a.g, %(radius_m)s)),
win AS MATERIALIZED (
  SELECT o.place_id, n.name_ar, n.name_en, o.value, o.observed_at
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
      SELECT name_ar, name_en, count(*) readings,
             count(DISTINCT value) distinct_values,
             min(extract(epoch FROM now() - observed_at)/60)::int AS last_seen_minutes
        FROM win GROUP BY place_id, name_ar, name_en
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
      SELECT name_ar, max(name_en) AS name_en, count(*) AS readings,
             count(*) FILTER (WHERE prev_value IS NOT NULL
                                AND value IS DISTINCT FROM prev_value)
               AS transitions,
             count(DISTINCT value) AS distinct_values
        FROM (SELECT name_ar, name_en, value, observed_at,
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

INSIGHTS_INC_SQL = """
WITH anchor AS (
  SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography AS g)
SELECT e.event_type,
       -- Governorate fallbacks sit on the CITY centroid, so they always land
       -- inside a radius around the city. They are counted beside the named
       -- events, never among them (audit F034/F080; P0-C.2).
       count(*) FILTER (WHERE COALESCE(e.attrs->>'place_precision','named') = 'named')
                                                                 AS events,
       count(*) FILTER (WHERE COALESCE(e.attrs->>'place_precision','named') <> 'named')
                                                                 AS governorate_only,
       count(*) FILTER (WHERE e.independent_sources >= 2
                          AND COALESCE(e.attrs->>'place_precision','named') = 'named')
                                                                 AS corroborated,
       max(e.occurred_at) FILTER (WHERE COALESCE(e.attrs->>'place_precision','named') = 'named')
                                                                 AS newest,
       (array_agg(p.name_ar ORDER BY e.occurred_at DESC)
          FILTER (WHERE COALESCE(e.attrs->>'place_precision','named') = 'named'))[1]
                                                                 AS newest_place
  FROM event e
  LEFT JOIN place p ON p.place_id = e.place_id
  CROSS JOIN anchor a
 WHERE e.status = 'believed'
   AND e.occurred_at >= now() - make_interval(days => %(days)s)
   AND ST_DWithin(e.geom, a.g, %(radius_m)s)
 GROUP BY 1 ORDER BY events DESC
"""

_PRESENCE_KINDS = {"checkpoint_idf": "army", "checkpoint_inspection": "inspection",
                   "checkpoint_police": "police", "checkpoint_settlers": "settlers"}


def _measured_precision(state_kind: str) -> dict | None:
    """The newest backtest line for a state kind, from the accuracy ledger.

    Read rather than asserted: if the ledger has nothing for this subject, the
    answer says nothing about precision instead of inventing a number.
    """
    import json as _json
    repo = Path(__file__).resolve().parent.parent
    best = None
    try:
        for line in (repo / "ops" / "accuracy.ndjson").read_text().splitlines():
            r = _json.loads(line)
            if r.get("state_kind") == state_kind:
                best = r                      # the ledger is append-only: last wins
    except Exception:                          # noqa: BLE001
        return None
    if not best:
        return None
    return {"precision": round(best["precision"], 4), "n": best["pairs_examined"],
            "mode": best.get("mode"), "window_days": best.get("window_days"),
            "basis": "backtest, ops/accuracy.ndjson"}


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
           "gate": 0.80, "state": q["gate"]["state"],
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
        # A read path never teaches the gazetteer: learning here wrote every
        # caller's phrase into place_alias, permanently (audit F076/F081/F085).
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
    ck = q_cached(INSIGHTS_CKPT_SQL, par)[0]
    inc = q_cached(INSIGHTS_INC_SQL, par)
    governorate_only = sum(int(r["governorate_only"] or 0) for r in inc)
    inc = [r for r in inc if r["events"]]

    presence: dict[str, dict] = {}
    for row in (ck["presence"] or []):
        axis = _PRESENCE_KINDS.get(row["state_kind"], row["state_kind"])
        presence.setdefault(axis, {})[row["value"]] = row["n"]
    events = sum(r["events"] for r in inc)
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
    if inc and max(r["corroborated"] for r in inc) == 0:
        caves.append("No incident type here reached two independent sources in "
                     "this window; every count is single-source.")
    return {
        "scope": {**resolved, "radius_km": radius_km, "days": days,
                  "window_hours": days * 24},
        "as_of": datetime.now(timezone.utc).isoformat(),
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
            "events": events,
            "located_to_governorate_only": governorate_only,
            "precision_note": "events counts incidents located to a NAMED place; those the "
                              "classifier could pin only to the governorate are counted in "
                              "located_to_governorate_only, never under the city",
            "by_type": [{"type": r["event_type"], "events": r["events"],
                         "corroborated": r["corroborated"],
                         "newest": r["newest"], "newest_place": r["newest_place"]}
                        for r in inc],
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

def _csv_response(rows: list[dict], columns: list[str], filename: str):
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) for k in columns})
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

_EXPORT_CP_COLUMNS = ["place_id", "name_ar", "name_en", "lat", "lon", "direction",
                      "flow", "passable", "last_known_flow", "confidence",
                      "observed_at", "age_minutes", "staleness_band",
                      "independent_sources", "present", "absent"]


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


_EXPORT_INCIDENT_SQL = """
    SELECT e.event_id, e.event_type, e.occurred_at, e.confidence,
           e.claim_count, e.independent_sources,
           p.name_ar, p.name_en,
           -- A governorate-only event is a pin on the city with the city's
           -- name unless the export says so (audit F082): the JSON route
           -- carried these two since P0-A.4, the files did not.
           COALESCE(e.attrs->>'place_precision', 'named') AS place_precision,
           e.attrs->>'place_text' AS named_place,
           ST_Y(e.geom::geometry) AS lat, ST_X(e.geom::geometry) AS lon
    FROM event e LEFT JOIN place p ON p.place_id = e.place_id
    WHERE e.status = 'believed'
      AND e.event_type <> 'fire_detection'      -- satellite pixels, not incidents (P0-A.4)
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
            "incidents": group("/v2/incidents"),
            "other": ["/v2/weather", "/v2/connectivity", "/v2/services",
                      "/v2/news/latest"],
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
    if not ok:
        return JSONResponse(
            {"error": "rate limited", "class": cls, "retry_after_seconds": retry,
             "note": "limits are per address and generous for honest use; see "
                     "/v2 for what is available"},
            status_code=429, headers={"Retry-After": str(retry)})
    return await call_next(request)


from fastapi import Response as _Response                      # noqa: E402


@app.get("/", tags=["discovery"], response_model=dict)
def root(request: Request, response: _Response) -> Any:
    """The bare hostname answers with the map of the system rather than a 404 —
    and a browser gets the front door (P2-B, gate G6): same URL, negotiated on
    `Accept`. Only a request that PREFERS text/html gets the page; an API client
    sending `application/json`, `*/*`, nothing, or a tie gets exactly this JSON.
    See serve/front_door.py."""
    from serve.front_door import landing, wants_html
    if wants_html(request.headers.get("accept")):
        return landing()
    response.headers["Vary"] = "Accept"
    return discovery()


# The partner guide rendered (/docs/partner, /docs/partner.md), the script it
# tells a partner to run (/docs/try-twelve.sh) and the page's twelve live
# questions (/v2/try/{n}). See serve/front_door.py.
from serve.front_door import router as _front_door_router       # noqa: E402

app.include_router(_front_door_router)


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
        raise HTTPException(503, f"routing unavailable: {e}")

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

    A crossing nobody reports reads `unknown` (today: the Gaza crossings; the
    Allenby bridge and the Jericho rest stop are read through the road
    channels, `basis` checkpoint_flow). That is the honest state and it is
    shown rather than hidden: leaving the crossings out entirely would make the
    same ignorance invisible. `area` matches the governorate or the crossing
    name, in Arabic or English.
    """
    rows = q("""
        SELECT p.place_id, p.name_ar, p.name_en,
               p.attrs->>'crossing_role'   AS role,
               p.attrs->>'note'            AS note,
               g.name_en                   AS governorate,
               g.name_ar                   AS governorate_ar,
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
         ORDER BY g.name_en NULLS LAST, p.name_en
    """)
    # The area is matched in Python with the gazetteer's own normalisation,
    # against the governorate AND the crossing's name, in both scripts. The SQL
    # matched `g.name_en ILIKE` only, so "أريحا" found nothing and the answer
    # said no source reports any crossing while the bridge read closed (Claude
    # web's test, 2026-09-25).
    if area:
        from resolve.arabic import fold_for_match, normalize
        want = {k for k in (normalize(area), fold_for_match(area), area.strip().lower()) if k}

        def _hit(r) -> bool:
            names = [r["name_ar"], r["name_en"], r["governorate"], r.get("governorate_ar")]
            keys = set()
            for nm in names:
                if nm:
                    keys |= {normalize(nm), fold_for_match(nm), nm.strip().lower()}
            return any(w and any(w in k for k in keys if k) for w in want)
        rows = [r for r in rows if _hit(r)]

    out = [{"place_id": r["place_id"],
            "name": r["name_ar"] or r["name_en"], "name_en": r["name_en"],
            "governorate": r["governorate"], "governorate_ar": r["governorate_ar"],
            "role": r["role"], "note": r["note"],
            "lat": r["lat"], "lon": r["lon"],
            "value": r["value"] or "unknown",
            "last_known_value": r["last_known_value"],
            "confidence": round(r["confidence"], 3) if r["confidence"] is not None else None,
            "age_minutes": float(r["age_minutes"]) if r["age_minutes"] is not None else None,
            "staleness_band": r["staleness_band"],
            "independent_sources": r["independent_sources"],
            "basis": r["basis"]} for r in rows]

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
        "crossings": out, "area": area,
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
    rows = q("""
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


@app.get("/v2/databank/where", tags=["databank"])
def databank_where(indicator: str = Query(..., min_length=2, max_length=120)) -> dict:
    """Which categories hold rows for an indicator (prefix match), so a caller
    who names an indicator without its category still reaches its rows."""
    rows = q("""SELECT v1_category AS category, count(*) AS rows
                  FROM databank_serving
                 WHERE indicator LIKE %s AND v1_category IS NOT NULL
                 GROUP BY 1 ORDER BY 2 DESC LIMIT 5""", (indicator + "%",))
    return {"indicator": indicator, "categories": rows}


@app.get("/v2/databank/indicators", tags=["databank"])
def databank_indicators(concept: str | None = None, q_: str | None = None,
                        measure_kind: str | None = None,
                        limit: int = 100,
                        search: str | None = Query(None, alias="q",
                                                   description="words in the indicator string or name")) -> dict:
    """Find a series without knowing its string.

    THE endpoint for "I don't know the indicator name". 1,408 of them exist
    and most are WHO or World Bank codes that nobody can guess.
    """
    where, params = ["1=1"], {}
    if concept:
        where.append("(i.concept_key = %(c)s OR c.parent = %(c)s)")
        params["c"] = concept
    q_ = q_ or search
    if q_:
        where.append("(i.indicator ILIKE %(q)s OR i.name_en ILIKE %(q)s)")
        params["q"] = f"%{q_}%"
    if measure_kind:
        where.append("i.measure_kind = %(k)s")
        params["k"] = measure_kind
    params["lim"] = min(limit, 500)
    rows = q(f"""
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
                    "cumulative one must be differenced first: pass detrend=diff "
                    "to /v2/databank/correlate (the correlate tool's pair mode), "
                    "which correlates the changes between readings."}


# ── P2-C.3: Tier 1 → Tier 2 — a checkpoint's own history as a series ─────────
# The nightly rollup (ops/rollup.py) has written one row per place, kind and
# day since 2026-06-09, and nothing in the databank could read it, so "is
# Huwara getting worse this year" had no answer. Three series per checkpoint,
# read straight from the rollup rather than poured into databank_internal (130k
# derived rows would inflate every published databank count):
#   movement.checkpoint.reports         road reports that day
#   movement.checkpoint.closed_reports  how many of them said closed
#   movement.checkpoint.closed_share    closed_reports / reports — a share of
#                                       REPORTS, never of time (the rollup's rule)
MOVEMENT_INDICATORS = {
    "movement.checkpoint.reports": ("checkpoint_flow.reports", "count"),
    "movement.checkpoint.closed_reports": ("checkpoint_flow.reports.closed", "count"),
    "movement.checkpoint.closed_share": (None, "ratio"),
}
MOVEMENT_ATTRIBUTION = ("Derived by Palestine Data from road-channel reports "
                        "(daily counts, ops/rollup.py); a share of reports, not of time.")


def _movement_series(indicator: str, place_id: int | None, frm: str | None,
                     to: str | None) -> dict:
    raw, unit = MOVEMENT_INDICATORS[indicator]
    meta = {"concept_key": "movement.checkpoint", "measure_kind":
            "ratio" if unit == "ratio" else "flow", "polarity": -1 if "closed" in indicator else None,
            "grain": "day", "place_grain": "point", "canonical_unit": unit}
    if place_id is None:
        return {**meta, "known": True, "indicator": indicator, "points": [], "n": 0,
                "units": [unit], "unit_mixed": False, "sources": [], "source_names": set(),
                "attribution": [MOVEMENT_ATTRIBUTION],
                "note": "a movement series is per checkpoint: pass place"}
    where, params = ["d.key = 'tier1_daily'", "upper_inf(o.sys_period)", "o.place_id = %(p)s"], {"p": place_id}
    if frm:
        where.append("o.occurred_at >= %(f)s"); params["f"] = frm
    if to:
        where.append("o.occurred_at <= %(t)s"); params["t"] = to
    rows = q(f"""SELECT o.occurred_at::date AS at, o.indicator, o.value_num
                   FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
                  WHERE {' AND '.join(where)}
                    AND o.indicator IN ('checkpoint_flow.reports', 'checkpoint_flow.reports.closed')
                  ORDER BY 1""", params)
    by: dict = {}
    for r in rows:
        by.setdefault(r["at"], {})[r["indicator"]] = float(r["value_num"] or 0)
    pts = []
    for at, v in sorted(by.items()):
        n, c = v.get("checkpoint_flow.reports", 0.0), v.get("checkpoint_flow.reports.closed", 0.0)
        if raw is None:
            if n > 0:
                pts.append({"at": at, "prec": "day", "value": round(c / n, 4), "unit": unit,
                            "reports": int(n)})
        elif raw in v or (raw == "checkpoint_flow.reports.closed" and n > 0):
            # a day with reports and none closed is a ZERO, not a missing day
            pts.append({"at": at, "prec": "day", "value": v.get(raw, 0.0), "unit": unit})
    return {**meta, "known": True, "indicator": indicator, "points": pts, "n": len(pts),
            "units": [unit], "unit_mixed": False, "sources": ["tier1_rollup"],
            "source_names": {"tier1_rollup"}, "attribution": [MOVEMENT_ATTRIBUTION]}


def _wider_places(place_id: int) -> list[dict]:
    """The governorate, then the region, that contain a place."""
    return q("""
        SELECT g.place_id, g.name_ar, g.name_en, g.kind::text AS kind, 1 AS rank
          FROM place p JOIN place g ON g.kind = 'governorate'
                                   AND g.admin2_pcode = p.admin2_pcode
         WHERE p.place_id = %(p)s AND g.place_id <> p.place_id
        UNION ALL
        SELECT r.place_id, r.name_ar, r.name_en, r.kind::text, 2
          FROM place p JOIN place r ON r.kind = 'region'
                                   AND r.admin1_pcode = p.admin1_pcode
         WHERE p.place_id = %(p)s AND r.place_id <> p.place_id
         ORDER BY rank""", {"p": place_id})


def _series(indicator: str, place_id: int | None, frm: str | None,
            to: str | None) -> dict:
    """One databank series, at the place asked — or at the governorate or region
    that contains it when the series is not kept that finely.

    "الخليل" resolves to Hebron the CITY while food prices are kept per
    GOVERNORATE, so `series` with a place returned 0 points for bread in Hebron
    (Claude web's test, 2026-09-25). The widening is stated in `place_used`,
    never silent."""
    if indicator in MOVEMENT_INDICATORS:
        return {**_movement_series(indicator, place_id, frm, to), "place_used": None}
    s = _series_at(indicator, place_id, frm, to)
    if place_id is None or s["points"] or not s["known"]:
        return {**s, "place_used": None}
    for alt in _wider_places(place_id):
        s2 = _series_at(indicator, alt["place_id"], frm, to)
        if s2["points"]:
            return {**s2, "place_used": {"place_id": alt["place_id"], "name": alt["name_ar"],
                                         "name_en": alt["name_en"], "kind": alt["kind"],
                                         "widened_from": place_id}}
    return {**s, "place_used": None}


def _series_at(indicator: str, place_id: int | None, frm: str | None,
               to: str | None) -> dict:
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
                       -- The unit the VALUE is in: the resolved unit when a
                       -- conversion happened, the raw unit otherwise — never
                       -- the indicator's declared canonical unit, which
                       -- labelled litre prices ILS_per_kg (audit F030).
                       CASE WHEN v.value_canonical IS NOT NULL THEN v.resolved_unit
                            ELSE v.unit END AS unit,
                       v.source_name, v.attribution_text, v.redistribution
                FROM v_observation_canonical v
                WHERE {' AND '.join(where)} ORDER BY 1""", params)
    meta = q("""SELECT concept_key, measure_kind, polarity, grain, place_grain,
                       canonical_unit
                FROM indicator_def WHERE indicator = %(i)s""",
             {"i": indicator})
    m = meta[0] if meta else {"concept_key": None, "measure_kind": None,
                              "polarity": None, "grain": None,
                              "place_grain": None, "canonical_unit": None}
    # Attribution travels ONCE per series. It used to travel on every point:
    # two food-price series came back as 429 KB, of which the numbers were a
    # few kilobytes and the rest was the same sentence repeated per row.
    sources = sorted({p["source_name"] for p in pts if p["source_name"]})
    attribution = sorted({p["attribution_text"] for p in pts if p["attribution_text"]})
    # The series' grade is its most restrictive row's (audit TRANSPORT-01): the
    # licence layer needs it to keep a no-redistribution publisher's POINTS
    # out of a partner payload while the cited summary stays.
    from serve.licence import GRADE_ORDER
    grades = {p.get("redistribution") for p in pts if p.get("redistribution")}
    redistribution = (max(grades, key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else len(GRADE_ORDER))
                      if grades else None)
    for p in pts:
        p.pop("source_name", None)
        p.pop("attribution_text", None)
        p.pop("redistribution", None)
    units = sorted({str(p["unit"]) for p in pts if p.get("unit")})
    return {**m, "known": bool(meta), "indicator": indicator,
            "points": pts, "n": len(pts),
            # More than one unit in one series (108 per-litre and 854 per-kg
            # milk points under one label, F030) is said, not blended.
            "units": units, "unit_mixed": len(units) > 1,
            "sources": sources, "source_names": set(sources),
            "attribution": attribution, "redistribution": redistribution}


@app.get("/v2/databank/compare", tags=["databank"])
def databank_compare(indicators: str, place_id: int | None = None,
                     frm: str | None = None, to: str | None = None) -> dict:
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
                       frm: str | None = None, to: str | None = None,
                       method: str = "spearman",
                       max_lag: int = Query(0, ge=0, le=366,
                                            description="days to scan for a lagged fit"),
                       allow_same_concept: bool = False,
                       detrend: str = Query("none", pattern="^(none|diff)$",
                                            description="diff: correlate the changes "
                                                        "between consecutive readings")) -> dict:
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
    # A breakdown series (13 markets per month) has no single value per date;
    # 'last row wins' made rho depend on physical row order (F043). The
    # median per date stands for the date, and the caveat says so.
    sa, note_a = C.collapse_dates(sa)
    sb, note_b = C.collapse_dates(sb)
    aggregation = [n for n in (note_a, note_b) if n]
    if detrend == "diff":
        sa, sb = C.differenced(sa), C.differenced(sb)
    else:
        shape = C.check_shape([float(p["value"]) for p in sa["points"] if p["value"] is not None],
                              [float(p["value"]) for p in sb["points"] if p["value"] is not None])
        if shape:
            return {"refused": True, "a": a, "b": b, "reasons": shape,
                    "hint": "detrend=diff"}
    by_a = {p["at"]: p for p in sa["points"]}
    by_b = {p["at"]: p for p in sb["points"]}
    best = None
    for lag in range(-abs(max_lag), abs(max_lag) + 1):
        pairs = []
        for at, pa in by_a.items():
            shifted = at + timedelta(days=lag) if lag else at
            pb = by_b.get(shifted)
            if pb and pa["value"] is not None and pb["value"] is not None \
                    and pa["prec"] not in C.UNUSABLE_PRECISION \
                    and pb["prec"] not in C.UNUSABLE_PRECISION:
                pairs.append((pa["value"], pb["value"], at, pa["prec"],
                              pb["prec"]))
        if len(pairs) < C.MIN_N:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        rho = (C.spearman(xs, ys) if method == "spearman"
               else C.pearson(xs, ys))
        if rho is not None and (best is None or abs(rho) > abs(best[0])):
            best = (rho, lag, pairs)
    if best is None:
        usable = sum(1 for at in by_a
                     if at in by_b
                     and by_a[at]["prec"] not in C.UNUSABLE_PRECISION)
        return {"refused": True, "a": a, "b": b, "reasons": [
            f"only {usable} usable overlapping point(s); {C.MIN_N} are "
            "required. Points are excluded when either side carries "
            "'unknown' precision — that date is v1's fetch stamp, not an "
            "event date (law 1)."]}
    rho, lag, pairs = best
    ci = C.fisher_ci(rho, len(pairs))
    return {
        "refused": False, "a": a, "b": b, "method": method, "detrend": detrend,
        "rho": round(rho, 4), "n": len(pairs), "lag_days": lag,
        "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
        "overlap": {"from": min(p[2] for p in pairs).isoformat(),
                    "to": max(p[2] for p in pairs).isoformat()},
        "plain_english": C.describe(rho, sa, sb),
        "caveats": aggregation + C.caveats(sa, sb, pairs, lag),
        "attribution": sorted(set(sa["attribution"]) | set(sb["attribution"])),
    }


@app.get("/v2/databank/correlate/scan", tags=["databank"])
def databank_correlate_scan(
    a: str, place_id: int | None = None, frm: str | None = None,
    to: str | None = None, method: str = "spearman",
    candidates: int = Query(40, ge=5, le=120),
    allow_same_concept: bool = False,
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

    # Prefiltered in SQL only for speed — check_comparable below remains the
    # authority, so this cannot quietly allow something the pairwise path
    # would refuse.
    rows = q("""
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
    pts = q(f"""SELECT v.indicator, v.occurred_at::date AS at,
                       v.occurred_precision AS prec,
                       COALESCE(v.value_canonical, v.value_num) AS value
                  FROM v_observation_canonical v
                 WHERE {' AND '.join(where)}""", params)
    grouped: dict[str, list] = {}
    for p in pts:
        grouped.setdefault(p["indicator"], []).append(p)

    sa, note_a = C.collapse_dates(sa)             # median per date (F043)
    a_vals = [float(p["value"]) for p in sa["points"] if p["value"] is not None]
    by_a = {p["at"]: p for p in sa["points"]
            if p["prec"] not in C.UNUSABLE_PRECISION and p["value"] is not None}

    hits, skipped, tested = [], Counter(), 0
    for r in rows:
        sb = {**r, "known": True, "points": grouped.get(r["indicator"], [])}
        stop = C.check_comparable(sa, sb)
        if allow_same_concept:
            stop = [s for s in stop if "both series are" not in s]
        if stop:
            skipped[_skip_reason(stop[0])] += 1
            continue
        # Series are paired on exact dates, so a daily series and an annual one
        # can never meet and come back as "too few overlapping dates" — which
        # reads as "no relationship" when it means "these two were never
        # measured on the same day". Named for what it is instead. Resampling
        # one to the other's period would create the overlap, and a number
        # built on twelve invented monthly points is exactly the kind of
        # confident artifact the rest of this file refuses to produce.
        if sa["grain"] != r["grain"]:
            skipped[f"different time grain ({sa['grain']} vs {r['grain']})"] += 1
            continue
        sb, _note_b = C.collapse_dates(sb)
        if C.check_shape(a_vals, [float(p["value"]) for p in sb["points"]
                                  if p["value"] is not None]):
            skipped["both series move with time (monotone; would measure time)"] += 1
            continue
        pairs = [(by_a[p["at"]]["value"], p["value"]) for p in sb["points"]
                 if p["at"] in by_a and p["value"] is not None
                 and p["prec"] not in C.UNUSABLE_PRECISION]
        if len(pairs) < C.MIN_N:
            skipped["too few overlapping dates"] += 1
            continue
        tested += 1
        rho = (C.spearman([x for x, _ in pairs], [y for _, y in pairs])
               if method == "spearman"
               else C.pearson([x for x, _ in pairs], [y for _, y in pairs]))
        if rho is None:
            skipped["no variance in one series"] += 1
            continue
        ci = C.fisher_ci(rho, len(pairs))
        hits.append({"indicator": r["indicator"], "concept": r["concept_key"],
                     "rho": round(rho, 4), "n": len(pairs),
                     "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
                     "unit": r["canonical_unit"]})

    hits.sort(key=lambda h: -abs(h["rho"]))
    return {
        "refused": False, "a": a, "method": method,
        "considered": len(rows), "tested": tested,
        "aggregation": note_a,
        "skipped": dict(skipped),
        "capped_at": candidates,
        "truncated": len(rows) == candidates,
        "matches": hits[:15],
        # Zero tests used to read "0 tests were run … roughly 1 of these would
        # look significant" (Claude web's test, 2026-09-25).
        "multiple_comparisons": (
            (f"{tested} tests were run. At the conventional 5% threshold "
             f"roughly {round(tested * 0.05, 1):g} of these would look "
             "significant from noise alone, so treat every row as a hypothesis "
             "to check, never as a finding.") if tested else
            "No test was run: nothing held passed the comparability checks, "
            "so there is no coefficient to report and no false-positive risk."),
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
                          ("measure_kind is unclassified", "kind unclassified")):
        if needle in reason:
            return label
    return "not comparable"


@app.get("/v2/databank/{category}", tags=["databank"])
def databank_category(category: str, indicator: str | None = None,
                      as_of: str | None = None, memorial: bool = False,
                      limit: int = Query(200, ge=1, le=2000),
                      district: str | None = Query(
                          None, max_length=60,
                          description="displacement: a 1945 district or subdistrict, "
                                      "Arabic or English (e.g. Ramle, الرملة)")) -> dict:
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
    # An unknown category is a 404 with the list, not an empty 200 that reads
    # as "nothing held" (P1-B.2).
    known = {r["key"] for r in q_cached("SELECT key FROM category WHERE active")}
    if known and category not in known:
        raise HTTPException(404, {"error": f"no category named {category!r}",
                                  "categories": sorted(known)})
    if category == "water":
        # water is a DOMAIN, not just a dataset bucket (decided 2026-08-06):
        # its own datasets PLUS the JMP WASH access series that lives — with
        # full GHO identity — inside v1_health_who. One fact, served once,
        # reachable from both the water and health categories; indicator
        # names keep their home namespace so provenance stays visible.
        conds, params = ["(r.v1_category = 'water' OR r.indicator LIKE %s)"], \
            ["health.wsh%"]
    else:
        conds, params = ["r.v1_category = %s"], [category]
    if indicator:
        conds.append("r.indicator LIKE %s")
        params.append(indicator + "%")
    dist = _district_1945(district) if district else None
    if district:
        # The depopulation record is filed by the Mandate's 1945 geography: six
        # districts, and subdistricts (qada') where the gazetteer knows them.
        conds.append("(r.attrs->>'district_1945' ILIKE %s OR r.attrs->>'subdistrict_1945' ILIKE %s)")
        params += [dist, dist]
    if as_of:
        conds.append("r.sys_period @> %s::date::timestamptz")
    else:
        conds.append("upper_inf(r.sys_period)")
    # The held conflict events (083) are served beside the observations. Their
    # rows are current versions only, so an `as_of` before the day they entered
    # the databank correctly finds none of them.
    events = _event_rows_served()
    event_branch = """
        UNION ALL
        SELECT e.indicator, e.occurred_at, e.occurred_precision::text, e.value_num,
               e.value_text, e.unit, e.attrs, e.place_id, e.sys_period, e.v1_category,
               e.source_key, e.dataset_key, e.attribution_text, e.license_spdx,
               e.redistribution
          FROM databank_event_rows e""" if events else ""
    base = f"""
        SELECT o.indicator, o.occurred_at, o.occurred_precision::text AS occurred_precision,
               o.value_num, o.value_text, o.unit, o.attrs, o.place_id, o.sys_period,
               d.v1_category, s.key AS source_key, d.key AS dataset_key,
               -- dataset-grain licence first (054): the portal row credited
               -- OCHA/UNICEF CC-BY data to the HDX portal (audit F143)
               COALESCE(d.attribution_text, s.attribution_text) AS attribution_text,
               COALESCE(d.license_spdx, s.license_spdx)         AS license_spdx,
               COALESCE(d.redistribution, s.redistribution)     AS redistribution
          FROM observation o
          JOIN dataset d ON d.dataset_id = o.dataset_id
          JOIN source s ON s.source_id = d.source_id
         WHERE o.v1_stable_id IS NOT NULL{event_branch}"""
    sql = f"""
        SELECT r.*, p.name_en AS place_en, p.name_ar AS place_ar
          FROM ({base}) r
          LEFT JOIN place p ON p.place_id = r.place_id
         WHERE {' AND '.join(conds)}
         ORDER BY r.occurred_at DESC LIMIT %s"""
    # An `as_of` reconstruction must never come out of a cache keyed on the
    # present, so the historical path keeps the plain connection-per-call q().
    runner = q if as_of else q_cached
    where_params = tuple(params + ([as_of] if as_of else []))
    rows = runner(sql, where_params + (limit,))
    out = {"category": category, "as_of": as_of, "district": district,
           "district_1945_key": dist, "count": len(rows),
           "items": [{k: r[k] for k in
                      ("indicator", "occurred_at", "occurred_precision",
                       "value_num", "value_text", "unit", "place_en",
                       "place_ar", "attrs", "source_key", "dataset_key",
                       "license_spdx", "redistribution")}
                     | {"attribution": r["attribution_text"]} for r in rows],
           "attribution": sorted({r["attribution_text"] for r in rows if r["attribution_text"]})}
    warnings = _serve_warnings(sorted({r["indicator"] for r in rows if r["indicator"]}))
    if warnings:
        out["warnings"] = warnings
    if events:
        # A register of single events is summarised, not sampled: "the newest
        # ten rows" of 589 localities says nothing about the 589 (P1-B.1).
        summ = runner(f"""
            SELECT r.indicator, count(*) AS events, sum(r.value_num) AS value_sum,
                   min(r.occurred_at)::date AS first, max(r.occurred_at)::date AS last,
                   bool_or(r.occurred_precision = 'unknown') AS undated
              FROM ({base}) r
             WHERE r.indicator IN (SELECT DISTINCT indicator FROM databank_event_rows)
               AND {' AND '.join(conds)}
             GROUP BY 1 ORDER BY 2 DESC""", where_params)
        if summ:
            # A locality's value is its whole 1945 population: a sum of those is
            # not a number anyone should quote, so the payload does not offer one.
            for s_ in summ:
                if s_["indicator"] == "displacement.locality_depopulated":
                    s_["value_sum"] = None
            out["event_summary"] = summ
        if category == "displacement":
            groups = {}
            for key in ("district_1945", "subdistrict_1945", "locality_group"):
                groups[key] = runner(f"""
                    SELECT r.attrs->>'{key}' AS name, count(*) AS localities
                      FROM ({base}) r
                     WHERE {' AND '.join(conds)}
                     GROUP BY 1 ORDER BY 2 DESC""", where_params)
            out["by"] = groups
            out["value_note"] = ("value_num is each locality's TOTAL 1945 population (all "
                                 "residents, Village Statistics 1945), never a refugee count; "
                                 "do not sum it. locality_group says Palestinian, Mixed or Jewish.")
    return out


_DISTRICTS_AR = {"الرملة": "Ramle", "الرمله": "Ramle", "رملة": "Ramle", "يافا": "Jaffa",
                 "اللد": "Lydda", "حيفا": "Haifa", "عكا": "Acre", "صفد": "Safad",
                 "طبريا": "Tiberias", "بيسان": "Beisan", "الناصرة": "Nazareth",
                 "جنين": "Jenin", "طولكرم": "Tulkarem", "القدس": "Jerusalem",
                 "الخليل": "Hebron", "غزة": "Gaza", "بئر السبع": "Beersheba",
                 "بير السبع": "Beersheba", "الجليل": "Galilee", "السامرة": "Samaria",
                 "نابلس": "Samaria", "Ramla": "Ramle", "Lod": "Lydda", "Akka": "Acre",
                 "Safed": "Safad", "Beer Sheva": "Beersheba", "Bisan": "Beisan"}


def _district_1945(name: str) -> str:
    n = (name or "").strip()
    for pre in ("قضاء ", "لواء ", "district of ", "subdistrict of "):
        if n.startswith(pre):
            n = n[len(pre):]
    return _DISTRICTS_AR.get(n, n)


def _serve_warnings(indicators: list[str]) -> dict:
    """indicator -> {en, ar}: what the number is NOT, said beside it (086)."""
    if not indicators:
        return {}
    try:
        rows = q_cached("""SELECT indicator, serve_warning, serve_warning_ar FROM indicator_def
                            WHERE indicator = ANY(%s) AND serve_warning IS NOT NULL""",
                        (indicators,))
    except Exception:                                            # noqa: BLE001 — before 086
        return {}
    return {r["indicator"]: {"en": r["serve_warning"], "ar": r["serve_warning_ar"]} for r in rows}


def _event_rows_served() -> bool:
    """Migration 083 applied: the held conflict events are served."""
    try:
        return bool(q_cached("SELECT to_regclass('databank_event_rows') IS NOT NULL AS ok")[0]["ok"])
    except Exception:                                            # noqa: BLE001
        return False
