"""P7.1 — answer "can I get from here to there", not "here is a dot".

    from resolve.corridor import routes
    routes((31.9038, 35.2034), (32.2211, 35.2544))   # Ramallah -> Nablus

Everything above this file answers about a PLACE. A person deciding whether to
travel is asking about a JOURNEY, and the two are not the same question: five
checkpoints can each be individually unremarkable while the route through them
is shut.

WHY THIS IS THE PRODUCT AND NOT A FEATURE
Point coverage is 23% — 96 of 419 checkpoint_flow rows are asserted, the rest
are honestly `unknown` because nobody has looked recently. Rendered as a map of
dots that reads as a broken app. Rendered as a corridor it reads as useful:

    "3 of 5 checkpoints on this route confirmed open in the last 20 minutes.
     Za'tara has not been reported since 06:12."

Same data, same honesty, and the second one answers the question. Aggregation
along a route is what makes sparse point data usable, which is why this comes
before any consumer app rather than after it.

It is also the thing a competitor with stale data cannot copy. Scoring a
corridor multiplies whatever error is in the inputs: a route of five
checkpoints each a day old is not "a bit stale", it is five independent chances
to be wrong about a journey somebody is about to make. Route-level answers are
only honest on top of a decay model, and ours is the decay model.

HOW IT WORKS
Valhalla returns a route and its alternates as encoded polylines. Each polyline
becomes a PostGIS geography; checkpoints within CORRIDOR_METRES of it are the
ones on the route, ordered by ST_LineLocatePoint so they come back in travel
order. Their SERVED state — already decayed and gated — is what scores the
corridor.

THE SCORING IS ASYMMETRIC, DELIBERATELY, AND FOR THE SAME REASON P2.4 IS
One confirmed closure blocks a route no matter how many open checkpoints
surround it, because a journey is a conjunction: every checkpoint has to be
passable, not most of them. Unknowns never block and never silently pass —
they are named, counted, and they lower the confidence attached to the verdict.
Being wrong toward "you should check" costs a phone call; being wrong toward
"it is fine" costs the journey.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

import httpx

from resolve.db import connect, env_value

VALHALLA = env_value("VALHALLA_URL", "http://wb-valhalla:8002")

# How near a checkpoint must be to count as "on this route".
#
# Measured on Ramallah->Nablus: 100m finds 5, 200m finds 8, 300m finds 10, 500m
# finds 11. 300 is where the curve flattens — it catches Za'tara at 247m and
# Lubban at 217m, both genuinely on the road and both missed at 200m, while
# 500m adds one checkpoint that is beside the route rather than on it.
# Registry coordinates are approximate, which is most of why the slack is
# needed at all.
CORRIDOR_METRES = 300

# Presence is a SIGHTING, not a state (migration 025) — a 15-minute half-life
# against a 35-hour reporting gap. It never blocks a route, because an army
# sighting two hours ago says nothing reliable about now. It is surfaced as a
# caution because a family planning a journey wants to know it was seen at all.
PRESENCE_KINDS = ("checkpoint_idf", "checkpoint_settlers", "checkpoint_police")

ON_ROUTE_SQL = """
WITH line AS (SELECT ST_GeogFromText(%(wkt)s) g, ST_GeomFromText(%(wkt)s, 4326) m),
     cp AS (
  SELECT p.place_id, p.name_ar, p.name_en,
         ST_LineLocatePoint(line.m, p.centroid::geometry)      AS along,
         round(ST_Distance(p.centroid, line.g)::numeric)       AS off_route_m,
         ST_Y(p.centroid::geometry) lat, ST_X(p.centroid::geometry) lon
    FROM place p, line
   WHERE p.kind = 'checkpoint' AND p.centroid IS NOT NULL
     AND COALESCE(p.servable, true) AND p.merged_into IS NULL
     AND ST_DWithin(p.centroid, line.g, %(buf)s)
)
SELECT cp.place_id, cp.name_ar, cp.name_en, cp.along, cp.off_route_m,
       cp.lat, cp.lon,
       f.value          AS flow,
       f.last_known_value AS flow_last,
       f.confidence     AS flow_conf,
       f.age_minutes    AS flow_age,
       f.independent_sources,
       f.direction
  FROM cp
  LEFT JOIN state_serving f
    ON f.place_id = cp.place_id AND f.state_kind = 'checkpoint_flow'
 ORDER BY cp.along, f.direction
"""

PRESENCE_SQL = """
SELECT place_id, state_kind, value, age_minutes
  FROM state_serving
 WHERE place_id = ANY(%(ids)s) AND state_kind = ANY(%(kinds)s)
   AND value <> 'unknown'
"""

BLOCKING = "closed"
SLOWING = ("congested", "slow")


@dataclass
class CheckpointOnRoute:
    place_id: int
    name: str
    along: float                    # 0..1 position in travel order
    off_route_m: int
    lat: float
    lon: float
    flow: str = "unknown"           # worst across directions
    flow_last_known: str | None = None
    confidence: float | None = None
    age_minutes: float | None = None
    independent_sources: int | None = None
    directions: dict = field(default_factory=dict)
    presence: list = field(default_factory=list)


@dataclass
class Corridor:
    verdict: str                    # blocked | slow | likely_open | unknown
    summary: str
    distance_km: float
    duration_minutes: float
    checkpoints_on_route: int
    known: int
    unknown: int
    worst: str
    oldest_known_minutes: float | None
    blocked_at: list = field(default_factory=list)
    slow_at: list = field(default_factory=list)
    unreported: list = field(default_factory=list)
    cautions: list = field(default_factory=list)
    checkpoints: list = field(default_factory=list)
    shape: str = ""
    is_alternate: bool = False

    def as_dict(self) -> dict:
        d = asdict(self)
        d["checkpoints"] = [asdict(c) if not isinstance(c, dict) else c
                            for c in self.checkpoints]
        return d


def decode_polyline(s: str, precision: int = 6) -> list[tuple[float, float]]:
    """Valhalla encodes at 1e6, NOT the 1e5 most polyline code assumes.

    Getting this wrong does not raise — it silently produces a route in the
    wrong part of the world, which then matches zero checkpoints and looks
    exactly like a quiet day.
    """
    inv = 1.0 / (10 ** precision)
    pts: list[tuple[float, float]] = []
    i = lat = lon = 0
    while i < len(s):
        for axis in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if axis == 0:
                lat += delta
            else:
                lon += delta
        pts.append((lon * inv, lat * inv))
    return pts


def _valhalla(origin, dest, alternates: int) -> list[dict]:
    body = {"locations": [{"lat": origin[0], "lon": origin[1]},
                          {"lat": dest[0], "lon": dest[1]}],
            "costing": "auto", "alternates": alternates,
            "directions_options": {"units": "km"}}
    r = httpx.post(f"{VALHALLA}/route", json=body, timeout=30.0)
    r.raise_for_status()
    d = r.json()
    trips = [d["trip"]] + [a["trip"] for a in d.get("alternates", [])]
    return trips


def _score(cps: list[CheckpointOnRoute]) -> tuple[str, str]:
    """Verdict and a sentence. See the module docstring on the asymmetry."""
    blocked = [c for c in cps if c.flow == BLOCKING]
    slow = [c for c in cps if c.flow in SLOWING]
    known = [c for c in cps if c.flow != "unknown"]
    unknown = [c for c in cps if c.flow == "unknown"]

    if blocked:
        names = "، ".join(c.name for c in blocked[:3])
        age = min((c.age_minutes for c in blocked if c.age_minutes is not None),
                  default=None)
        when = f" ({age:.0f} min ago)" if age is not None else ""
        return "blocked", f"Closed at {names}{when}."
    if not known:
        return "unknown", (f"No recent reports from any of the "
                           f"{len(cps)} checkpoints on this route.")
    if slow:
        names = "، ".join(c.name for c in slow[:3])
        return "slow", (f"Passable but congested at {names}. "
                        f"{len(known)} of {len(cps)} checkpoints reported"
                        + (f", {len(unknown)} not checked recently." if unknown else "."))
    return "likely_open", (f"{len(known)} of {len(cps)} checkpoints confirmed open"
                           + (f"; {len(unknown)} have not been reported recently."
                              if unknown else "."))


def _corridor_for(conn, trip: dict, is_alternate: bool) -> Corridor:
    leg = trip["legs"][0]
    pts = decode_polyline(leg["shape"])
    wkt = "LINESTRING(" + ",".join(f"{x} {y}" for x, y in pts) + ")"

    with conn.cursor() as cur:
        cur.execute(ON_ROUTE_SQL, {"wkt": wkt, "buf": CORRIDOR_METRES})
        rows = cur.fetchall()

    # One checkpoint can appear once per direction. A route has a direction of
    # travel but our inbound/outbound is defined relative to the CHECKPOINT, and
    # mapping one to the other reliably is not something we can do yet — so the
    # WORST direction is taken and both are reported. Guessing would be wrong
    # half the time, in a way that silently favours "it is fine".
    by_id: dict[int, CheckpointOnRoute] = {}
    order = {"closed": 3, "congested": 2, "slow": 1, "open": 0, "unknown": -1}
    for (pid, ar, en, along, off, lat, lon, flow, last, conf, age, srcs, direction) in rows:
        c = by_id.get(pid)
        if c is None:
            c = CheckpointOnRoute(pid, ar or en or f"#{pid}", float(along),
                                  int(off), float(lat), float(lon))
            by_id[pid] = c
        v = flow or "unknown"
        if direction:
            c.directions[direction] = v
        if order.get(v, -1) > order.get(c.flow, -1):
            c.flow, c.flow_last_known = v, last
            c.confidence = float(conf) if conf is not None else None
            c.age_minutes = float(age) if age is not None else None
            c.independent_sources = srcs

    cps = sorted(by_id.values(), key=lambda c: c.along)

    if cps:
        with conn.cursor() as cur:
            cur.execute(PRESENCE_SQL, {"ids": [c.place_id for c in cps],
                                       "kinds": list(PRESENCE_KINDS)})
            for pid, kind, val, age in cur.fetchall():
                if pid in by_id and val == "present":
                    by_id[pid].presence.append(
                        {"kind": kind, "age_minutes": float(age) if age is not None else None})

    verdict, summary = _score(cps)
    known = [c for c in cps if c.flow != "unknown"]
    return Corridor(
        verdict=verdict, summary=summary,
        distance_km=round(trip["summary"]["length"], 1),
        duration_minutes=round(trip["summary"]["time"] / 60, 1),
        checkpoints_on_route=len(cps),
        known=len(known), unknown=len(cps) - len(known),
        worst=max((c.flow for c in cps), key=lambda v: order.get(v, -1)) if cps else "unknown",
        oldest_known_minutes=max((c.age_minutes for c in known
                                  if c.age_minutes is not None), default=None),
        blocked_at=[c.name for c in cps if c.flow == BLOCKING],
        slow_at=[c.name for c in cps if c.flow in SLOWING],
        unreported=[c.name for c in cps if c.flow == "unknown"],
        cautions=[{"place": c.name, "seen": p["kind"], "age_minutes": p["age_minutes"]}
                  for c in cps for p in c.presence],
        checkpoints=cps, shape=leg["shape"], is_alternate=is_alternate)


def routes(origin: tuple[float, float], dest: tuple[float, float],
           alternates: int = 2) -> list[Corridor]:
    """Every reasonable way to get there, each scored by what is on it.

    Alternates matter more here than in ordinary navigation: the answer to "the
    road is shut" is not a shorter time estimate, it is a different road, and
    that is the whole reason somebody opens this.
    """
    trips = _valhalla(origin, dest, alternates)
    out = []
    with connect() as conn:
        for i, t in enumerate(trips):
            out.append(_corridor_for(conn, t, is_alternate=i > 0))
    # A passable route beats a shorter blocked one. WITHIN a verdict, rank by
    # time and nothing else.
    #
    # Ranking by evidence first was tried and is wrong: on Ramallah->Nablus it
    # put a 66-minute alternate above the 51-minute main road because we happened
    # to know more about it. That spends fifteen minutes of somebody's day to buy
    # US confidence. How much is known is shown on every route — 4 of 7, 3 of 8 —
    # so the traveller can weigh it themselves. Reporting uncertainty is the job;
    # acting on it for them is not.
    rank = {"likely_open": 0, "slow": 1, "unknown": 2, "blocked": 3}
    out.sort(key=lambda c: (rank.get(c.verdict, 9), c.duration_minutes))
    return out
