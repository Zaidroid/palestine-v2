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
import re
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

# A CLOSURE JUST OUTSIDE THE CORRIDOR IS NOT SILENCE.
# Measured 2026-09-24: `can_i_travel` Ramallah→Nablus answered "passable, congested
# at Za'tara" while عين سينيا (Ein Siniya) was closed 25 minutes earlier with TWO
# independent sources. Its row passes every registry filter — kind='checkpoint',
# servable, not merged — its centroid is simply 2,327 m from the polyline, so the
# corridor dropped it without a word. The only name the traveller ever saw was a
# pseudo-checkpoint literally named "من عين سينا لزعترة" (a road SEGMENT, whose
# centroid lands on the line and therefore survives the buffer).
#
# WIDTH IS CHOSEN FROM THE DATA, NOT FROM TASTE. Counting blocking/slow
# checkpoints by radius on that same call: 300 m → 1 (just Za'tara), 900 m → 1,
# 1,500 m → 1, 2,500 m → 4 (بيت ايل closed, سلواد يبرود congested, عين سينيا
# closed, كفر عقب closed at 2.7 km), 5,000 m → 9 and climbing. So 3 km is the band
# that reaches the closure a traveller needs while still being a briefing rather
# than a directory of every shut checkpoint in the Ramallah area.
#
# The closure is NAMED, never promoted onto the route: whether a checkpoint 2.3 km
# off the alignment is on somebody's journey is their call. Silence is not.
NEAR_MISS_METRES = 3000

# WHEN "LIKELY OPEN" IS NOT A THING WE MAY SAY.
#
# Two thresholds, both taken from the partner audit's own measurements on
# Ramallah->Nablus (2026-09-24) rather than picked for roundness.
#
# UNVERIFIED_GAP_KM — the route is 53.2 km and the first tracked checkpoint sits
# at 26.8 km. Coverage on the West Bank road network is thin by nature, so this
# must not fire on every trip: measured across the corridors this server serves,
# a 10 km blind stretch is roughly the point where the unwatched part stops
# being "between two junctions" and starts being "most of the drive". Below it
# the payload still reports the gap; above it the gap outweighs the verdict.
UNVERIFIED_GAP_KM = 10.0

# ENDS_KM — a closure in the first or last stretch is the one that decides
# whether you can start or finish the journey at all. On the audited trip Beit
# El, Ein Siniya and Silwad were all closed 2.0-2.6 km off the line within the
# first few km of leaving Ramallah: the corridor could not see them and they
# were exactly the roads out of the city. 10 km is the distance within which an
# off-route closure is still plausibly on the way in or out rather than an
# unrelated road that happens to pass nearby.
ENDS_KM = 10.0

# PLAN §6 G2: `open` needs the corridor to be WATCHED — coverage >= 0.6, where
# coverage counts only checkpoints with a current reading. The absolute 10 km
# gap above never fired on a short route: Ramallah->Bir Zeit (~10 km) with one
# reported checkpoint at km 1 read `likely_open` over 9 unwatched km (F071).
MIN_WATCHED_FRACTION = 0.6

_HEBREW = re.compile(r"[\u0590-\u05FF]")

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

NEAR_MISS_SQL = """
WITH line AS (SELECT ST_GeogFromText(%(wkt)s) g, ST_GeomFromText(%(wkt)s, 4326) m)
SELECT p.place_id, p.name_ar, p.name_en,
       round(ST_Distance(p.centroid, line.g)::numeric) AS off_route_m,
       f.value AS flow, f.age_minutes, f.independent_sources,
       ST_LineLocatePoint(line.m, p.centroid::geometry) AS along
  FROM place p
 CROSS JOIN line
  JOIN state_serving f
    ON f.place_id = p.place_id AND f.state_kind = 'checkpoint_flow'
 WHERE p.kind = 'checkpoint' AND p.centroid IS NOT NULL
   AND COALESCE(p.servable, true) AND p.merged_into IS NULL
   AND ST_DWithin(p.centroid, line.g, %(near)s)
   AND NOT ST_DWithin(p.centroid, line.g, %(buf)s)
   AND f.value IN ('closed', 'congested', 'slow')
"""

PRESENCE_SQL = """
SELECT place_id, state_kind, value, age_minutes
  FROM state_serving
 WHERE place_id = ANY(%(ids)s) AND state_kind = ANY(%(kinds)s)
   AND value <> 'unknown'
"""

# WHICH TOWNS THE ROUTE ACTUALLY GOES THROUGH.
#
# The external pass asked for this and the reason is sound: a verdict about a
# road is unusable if the reader cannot tell WHICH road. "Probably passable" on a
# 53 km drive means nothing; "passes Surda, Bir Zeit, Sinjil, then Za'tara" lets
# them judge. Built from our OWN gazetteer rather than a geocoder we do not have.
#
# Fuel stations and neighbourhoods are excluded: `محطة ...` rows are a third of
# the gazetteer and 228 named places sit within 1.5 km of this one route, so an
# unfiltered list is a wall of petrol stations in Ramallah's city centre.
PASSES_METRES = 1500
# POIs, not places. Matching is SUBSTRING, not prefix: "Fuel station (OSM
# 4976038228)" is an OSM row with an English name and a prefix test let it
# through into a list of Palestinian towns.
#
# Matching is also FOLDED, because Arabic orthography defeats a literal list:
# "محطة بنزين" and "محطه بنزين سونول" are the same word written two ways and only
# the first was caught, so a petrol station made it into the answer sentence.
# The fold also collapses the البيرة/البيره spelling pairs that appeared as two
# separate waypoints 300 m apart.
def _fold_ar(x: str) -> str:
    for a, b in (("ة", "ه"), ("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"),
                 ("ـ", "")):
        x = x.replace(a, b)
    return x


_PASSES_NOISE = tuple(_fold_ar(n) for n in ("محطة", "كازية", "Fuel station", "fuel", "park", "Park",
                 "حديقة", "البلدة القديمة", "المنطقة الصناعية", "إسكان", "شارع",
                 "دوار", "منتزه", "مطعم", "مسجد", "جامع", "مدرسة", "مستشفى",
                 "ملعب", "مقبرة", "مخبز", "سوبرماركت", "عيادة", "صيدلية",
                 "UNRWA", "Camp", "refugee", "Crossing", "crossing",
                 # Fuel brands and junctions. "Paz", "Sonol" and "Delek" are
                 # forecourts, not places, and "إشارات" is a set of traffic
                 # lights — all of them hug the alignment more tightly than the
                 # town they serve, so picking the CLOSEST candidate per slice
                 # favoured them over the towns the list exists to name.
                 "Paz", "Sonol", "Delek", "Dor Alon", "Yellow", "Sde",
                 "إشارات", "اشارات", "junction", "Junction", "צומת",
                 "מחלף", "Interchange", "מרכז", "Center", "Centre",
                 # The same forecourts in Hebrew script, which the Latin brand
                 # list above does not catch: "סונול" is Sonol.
                 "סונול", "פז", "דלק", "דור אלון", "ח'רבת", "Khirbet", "Khirbat",
                 "بنزين", "بترول", "غاز", "Petrol", "Gas", "غسيل"))

PASSES_SQL = """
WITH line AS (SELECT ST_GeogFromText(%(wkt)s) g, ST_GeomFromText(%(wkt)s, 4326) m)
SELECT p.name_ar, p.name_en,
       ST_LineLocatePoint(line.m, p.centroid::geometry) AS along,
       round(ST_Distance(p.centroid, line.g)::numeric)  AS off_m
  FROM place p, line
 WHERE p.merged_into IS NULL
   AND COALESCE(p.servable, true)
   AND p.kind <> 'checkpoint'
   AND ST_DWithin(p.centroid, line.g, %(near)s)
 ORDER BY along
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
    # The English name travels with the point. It was selected by the corridor
    # query and then dropped because this dataclass had no field for it, so every
    # ON-ROUTE checkpoint came back with `name_en: null` while the near-miss list
    # (built separately) was fully translated — an Arabic-only list for the step
    # that matters most, in a payload the docs promise is bilingual.
    name_en: str | None = None


@dataclass
class Corridor:
    verdict: str                    # blocked | slow | unverified | likely_open | unknown
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
    near_misses: list = field(default_factory=list)
    # Closures just off the route in its first/last ENDS_KM — the roads you
    # take to reach the corridor or leave it. Named in full (no cap), never
    # merged into `blocked_at` (they are not ON the route) or `near_misses`
    # (which is every closure/congestion along the whole line).
    exit_closures: list = field(default_factory=list)
    # Why an otherwise-open route reads `unverified`, structured for the
    # renderers: blind_stretch / exit_closure records.
    doubts: list = field(default_factory=list)
    checkpoints: list = field(default_factory=list)
    # How much of this drive anything actually watches, and which towns it goes
    # through. See _corridor_for: the verdict is a claim about the whole journey
    # but the checkpoints are only where they are.
    coverage: dict = field(default_factory=dict)
    passes: list = field(default_factory=list)
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


def _score(cps: list[CheckpointOnRoute], *, coverage: dict | None = None,
           near_misses: list | None = None, distance_km: float | None = None
           ) -> tuple[str, str]:
    """Verdict and a sentence. See the module docstring on the asymmetry.

    THE VERDICT MUST NOT SPEAK FOR ROAD IT CANNOT SEE.
    Until 2026-09-24 this function received ONLY the checkpoints inside the
    300 m corridor, so `likely_open` was structurally incapable of knowing
    either how much of the drive nothing watched or that a closure sat just
    off the line. The partner's audit caught the consequence four times on one
    trip: Ramallah->Nablus read "likely open" at 16:24 and 16:47 while Beit El,
    Ein Siniya and Silwad were all closed 2.0-2.6 km off the route, and the
    first 26.8 km of that route had no tracked checkpoint at all. Every
    statement in the payload was individually true and the headline was still
    the opposite of the answer.

    So `likely_open` — the only verdict that reads as permission — now has to
    earn it. It degrades to `unverified` when either:

      * the longest unwatched stretch exceeds UNVERIFIED_GAP_KM, or
      * a closure sits within ENDS_KM of the origin or the destination.

    The second is the one that matters most and the one the audit named: a
    closure 2 km off a corridor AT THE ORIGIN is usually the road you must take
    to reach that corridor. Near the middle of a long drive it is far more
    often a genuinely different road, which is why position, not just distance
    from the line, decides.

    `unverified` is not `blocked`. It means: we cannot tell you this is open,
    here is what we do know. A confirmed closure ON the route still blocks, and
    congestion still reads as slow — degrading those would be hiding evidence
    rather than qualifying its absence.
    """
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
    # Asked BEFORE `slow`, not after: "passable but congested" is the same
    # permission-shaped claim as "open" plus a delay, and it used to return
    # before the blind stretch and the exit closures were even looked at (F318).
    doubts = _doubts(coverage, near_misses, distance_km)
    if slow:
        names = "، ".join(c.name for c in slow[:3])
        return "slow", (f"Passable but congested at {names}. "
                        f"{len(known)} of {len(cps)} checkpoints reported"
                        + (f", {len(unknown)} not checked recently." if unknown else ".")
                        + (" But " + "; ".join(doubts) + ". Check before travelling."
                           if doubts else ""))

    # Nothing on the route contradicts "open" — now ask whether we saw enough
    # of the route, and of its two ends, to say so.
    if doubts:
        return "unverified", ("Nothing on this route is reported closed, but "
                              + "; ".join(doubts)
                              + ". Check before travelling.")
    return "likely_open", (f"{len(known)} of {len(cps)} checkpoints confirmed open"
                           + (f"; {len(unknown)} have not been reported recently."
                              if unknown else "."))


def doubt_records(coverage: dict | None, near_misses: list | None,
                  distance_km: float | None) -> list[dict]:
    """The same reasons as `_doubts`, STRUCTURED, so both spoken answers can
    render them in their own language. Until 2026-09-24 the reasons existed
    only in the English `summary`, which neither the Arabic nor the English
    MCP answer used: a route read `unverified` and never said why."""
    out: list[dict] = []
    gap = float((coverage or {}).get("longest_gap_km") or 0.0)
    if gap >= UNVERIFIED_GAP_KM:
        # The SHARE of the route, so both answers say the same size: Arabic
        # said "about half" and English "most of the route" over one record,
        # for 27 km of a 50 km trip (Claude web's test, 2026-09-25).
        share = (round(gap / float(distance_km), 2)
                 if distance_km and float(distance_km) > 0 else None)
        out.append({"kind": "blind_stretch", "km": round(gap, 1),
                    "share": min(share, 1.0) if share is not None else None,
                    "from_km": (coverage or {}).get("longest_gap_from_km"),
                    "to_km": (coverage or {}).get("longest_gap_to_km")})
    elif _low_coverage(coverage):
        c = coverage or {}
        out.append({"kind": "low_coverage", "fraction": c.get("watched_fraction"),
                    "km": c.get("watched_longest_gap_km"),
                    "from_km": c.get("watched_gap_from_km"),
                    "to_km": c.get("watched_gap_to_km")})
    for m in _closures_at_ends(near_misses, distance_km):
        out.append({"kind": "exit_closure", "name": m.get("name"),
                    "name_en": m.get("name_en"), "flow": m.get("flow"),
                    "off_route_m": m.get("off_route_m"),
                    "age_minutes": m.get("age_minutes"),
                    "end": "origin" if (m.get("along") or 0) <= 0.5 else "destination"})
    return out


def _low_coverage(coverage: dict | None) -> bool:
    """G2's coverage rule, on WATCHED checkpoints. Absent when the caller did not
    measure it (the pure _score tests), so it never fires on a guess."""
    wf = (coverage or {}).get("watched_fraction")
    return wf is not None and wf < MIN_WATCHED_FRACTION


def _doubts(coverage: dict | None, near_misses: list | None,
            distance_km: float | None) -> list[str]:
    """Reasons an otherwise-open route cannot be called open. Empty means clean."""
    out: list[str] = []

    gap = float((coverage or {}).get("longest_gap_km") or 0.0)
    if gap >= UNVERIFIED_GAP_KM:
        frm = (coverage or {}).get("longest_gap_from_km")
        to = (coverage or {}).get("longest_gap_to_km")
        where = f" ({frm:.0f}-{to:.0f} km in)" if frm is not None and to is not None else ""
        out.append(f"no checkpoint is tracked for {gap:.0f} km of it{where}")
    elif _low_coverage(coverage):
        c = coverage or {}
        km, a, b = c.get("watched_longest_gap_km"), c.get("watched_gap_from_km"), c.get("watched_gap_to_km")
        where = (f" (nothing reported for {km:.0f} km, {a:.0f}-{b:.0f} km in)"
                 if None not in (km, a, b) else "")
        out.append(f"only {round(100 * c['watched_fraction'])}% of it is watched by a "
                   f"checkpoint with a recent report{where}")

    for m in _closures_at_ends(near_misses, distance_km):
        end = "leaving" if m["along"] <= 0.5 else "arriving at"
        out.append(f"{m['name']} is {m['flow']} {m['off_route_m'] / 1000:.1f} km "
                   f"off the route where you are {end} it")
    return out


def _closures_at_ends(near_misses: list | None, distance_km: float | None,
                      cap: int | None = 3) -> list[dict]:
    """Near-miss CLOSURES sitting in the first or last ENDS_KM of the route.

    Congestion is excluded deliberately: a busy junction near town is the
    normal state of the road and would fire on almost every trip, which would
    make `unverified` meaningless. A closure is an event.

    `cap` limits the SPOKEN list (a briefing, not a directory); pass None for
    the full list that travels as `exit_closures` in the payload.
    """
    if not near_misses or not distance_km:
        return []
    frac = min(0.5, ENDS_KM / distance_km) if distance_km else 0.0
    out = []
    for m in near_misses:
        if m.get("flow") != "closed":
            continue
        along = m.get("along")
        if along is None:
            continue
        if along <= frac or along >= (1.0 - frac):
            out.append(m)
    # Nearest to the alignment first — the most likely to actually be on the way.
    out = sorted(out, key=lambda m: m["off_route_m"])
    return out[:cap] if cap else out


_SEVERITY = {"closed": 3, "congested": 2, "slow": 1, "open": 0, "unknown": -1}


def _reconcile_directions(rows: list[tuple]) -> tuple:
    """(value, row) for one checkpoint from its per-direction serving rows.

    rows are (direction, value, age_minutes, ...). Resolved EXACTLY as
    checkpoint_serving resolves them: for each travel direction the freshest of
    {that direction, 'both'} (a tie goes to the direction-specific report), then
    the worse of the two, because our inbound/outbound is relative to the
    checkpoint and the route's direction of travel through it is unknown.

    It used to be the worst across every raw row, so a 295-minute-old
    "inbound closed" outranked a 5-minute-old "both open" from three groups and
    can_i_travel said blocked while checkpoint_status said open (F320).
    """
    rows = [r for r in rows if r[0]]
    if not rows:
        return "unknown", None

    def age(r):
        return r[2] if r[2] is not None else 1e9

    def pick(d):
        cand = [r for r in rows if r[0] in (d, "both")]
        return min(cand, key=lambda r: (age(r), 0 if r[0] == d else 1)) if cand else None

    picks = [p for p in (pick("inbound"), pick("outbound")) if p]
    best = max(picks, key=lambda r: (_SEVERITY.get(r[1] or "unknown", -1), -age(r)))
    return (best[1] or "unknown"), best


def _waypoint_name(name_ar: str | None, name_en: str | None) -> str | None:
    """The name a traveller navigates by, or None. A name only in Hebrew script
    ("עפרה") is a settlement's own label, not a waypoint to read to a Palestinian
    traveller (F322). Labelling settlements that carry an Arabic name needs a
    registry flag the gazetteer does not have yet."""
    for n in ((name_ar or "").strip(), (name_en or "").strip()):
        if n and not _HEBREW.search(n):
            return n
    return None


def _corridor_for(conn, trip: dict, is_alternate: bool) -> Corridor:
    leg = trip["legs"][0]
    pts = decode_polyline(leg["shape"])
    wkt = "LINESTRING(" + ",".join(f"{x} {y}" for x, y in pts) + ")"

    with conn.cursor() as cur:
        cur.execute(ON_ROUTE_SQL, {"wkt": wkt, "buf": CORRIDOR_METRES})
        rows = cur.fetchall()
        # The band just outside the corridor. A closure here is NAMED, not
        # promoted: whether a checkpoint 500 m off the alignment is on the
        # journey is the traveller's call, not ours — but silence is not an
        # option either, which is exactly what Ein Siniya was.
        cur.execute(NEAR_MISS_SQL, {"wkt": wkt, "buf": CORRIDOR_METRES,
                                    "near": NEAR_MISS_METRES})
        near_rows = cur.fetchall()

    # One place can appear several times (per direction, and once per reading).
    # Keep the most severe, then the best-corroborated, then the FRESHEST: on
    # 2026-09-24 Ein Siniya had a 25-minute-old reading with two independent
    # sources AND an 87-minute-old one from a single source. Reporting the stale
    # solo reading would understate a closure the system actually knows well.
    order_worst = {"closed": 3, "congested": 2, "slow": 1}

    def _rank(m: dict) -> tuple:
        return (order_worst.get(m["flow"], 0),
                m.get("independent_sources") or 0,
                -(m.get("age_minutes") if m.get("age_minutes") is not None else 1e9))

    near: dict[int, dict] = {}
    for (npid, nar, nen, noff, nflow, nage, nsrcs, nalong) in near_rows:
        cand = {"place_id": npid, "name": nar or nen or f"#{npid}",
                "name_en": nen, "off_route_m": int(noff),
                "flow": nflow,
                "age_minutes": float(nage) if nage is not None else None,
                "independent_sources": nsrcs,
                # WHERE on the route it sits, 0.0 at the origin and 1.0 at the
                # destination. A closure's position is what decides whether it
                # is on the way out of town or an unrelated road thirty km away.
                "along": float(nalong)}
        prev = near.get(npid)
        if prev is None or _rank(cand) > _rank(prev):
            near[npid] = cand
    near_on_route: set[int] = set()
    near_misses: list = []

    # One checkpoint can appear once per direction. A route has a direction of
    # travel but our inbound/outbound is defined relative to the CHECKPOINT, and
    # mapping one to the other reliably is not something we can do yet — so the
    # WORST direction is taken and both are reported. Guessing would be wrong
    # half the time, in a way that silently favours "it is fine".
    by_id: dict[int, CheckpointOnRoute] = {}
    readings: dict[int, list[tuple]] = {}
    order = _SEVERITY
    for (pid, ar, en, along, off, lat, lon, flow, last, conf, age, srcs, direction) in rows:
        c = by_id.get(pid)
        if c is None:
            c = CheckpointOnRoute(pid, ar or en or f"#{pid}", float(along),
                                  int(off), float(lat), float(lon))
            by_id[pid] = c
        v = flow or "unknown"
        if en and not c.name_en:
            c.name_en = en
        if direction:
            c.directions[direction] = v
            readings.setdefault(pid, []).append(
                (direction, v, float(age) if age is not None else None, last, conf, srcs))
    for pid, c in by_id.items():
        v, r = _reconcile_directions(readings.get(pid, []))
        if r is not None:
            c.flow, c.flow_last_known = v, r[3]
            c.confidence = float(r[4]) if r[4] is not None else None
            # `unknown` carries no age: an age beside it would read as a
            # stale-but-real reading (tests/test_route_omissions.py). The
            # reconciliation picks a decayed row's age otherwise (F320 fix).
            c.age_minutes = r[2] if v != "unknown" else None
            c.independent_sources = r[5]

    cps = sorted(by_id.values(), key=lambda c: c.along)
    near_on_route = {c.place_id for c in cps}
    near_misses = sorted((v for k, v in near.items() if k not in near_on_route),
                         key=lambda v: v["off_route_m"])

    if cps:
        with conn.cursor() as cur:
            cur.execute(PRESENCE_SQL, {"ids": [c.place_id for c in cps],
                                       "kinds": list(PRESENCE_KINDS)})
            for pid, kind, val, age in cur.fetchall():
                if pid in by_id and val == "present":
                    by_id[pid].presence.append(
                        {"kind": kind, "age_minutes": float(age) if age is not None else None})

    known = [c for c in cps if c.flow != "unknown"]

    # ── HOW MUCH OF THIS DRIVE ANYTHING ACTUALLY WATCHES ──
    #
    # The verdict is a claim about the WHOLE journey; the checkpoints are only
    # where they are. Measured 2026-09-24 on Ramallah->Nablus: 53.2 km, and the
    # first ON-ROUTE checkpoint sat at 26.9 km — so half the drive was watched by
    # nothing and the tool still opened with "probably passable". "2 of 8
    # checkpoints have recent reports" does not convey that, because the reader
    # cannot see WHERE on the 53 km those two are. So the longest blind stretch
    # travels with the verdict, in kilometres, with an explicit section:
    # unverified.
    #
    # THIS IS COMPUTED BEFORE THE VERDICT, NOT AFTER IT. Until 2026-09-24 the
    # order was reversed, which is precisely why the verdict could not take any
    # of it into account — see _score.
    dist = float(trip["summary"]["length"])
    marks = sorted([0.0] + [c.along for c in cps if 0.0 <= c.along <= 1.0] + [1.0])
    segs = [(marks[i + 1] - marks[i], marks[i], marks[i + 1])
            for i in range(len(marks) - 1)]
    gap_frac, gap_a, gap_b = max(segs) if segs else (1.0, 0.0, 1.0)
    coverage = {
        "distance_km": round(dist, 1),
        "checkpoints_on_route": len(cps),
        "coverage_fraction": round(1.0 - gap_frac, 2),
        "covered_km": round(dist * (1.0 - gap_frac), 1),
        "longest_gap_km": round(dist * gap_frac, 1),
        "longest_gap_from_km": round(dist * gap_a, 1),
        "longest_gap_to_km": round(dist * gap_b, 1),
    }
    # G2's coverage, on checkpoints somebody actually reported recently. The
    # registry-based fraction above counts a checkpoint nobody has mentioned in
    # a day as coverage; this one does not.
    kmarks = sorted([0.0] + [c.along for c in known if 0.0 <= c.along <= 1.0] + [1.0])
    wg, wa, wb = max((kmarks[i + 1] - kmarks[i], kmarks[i], kmarks[i + 1])
                     for i in range(len(kmarks) - 1))
    coverage.update({
        "watched_fraction": round(1.0 - wg, 2),
        "watched_longest_gap_km": round(dist * wg, 1),
        "watched_gap_from_km": round(dist * wa, 1),
        "watched_gap_to_km": round(dist * wb, 1),
    })

    verdict, summary = _score(cps, coverage=coverage, near_misses=near_misses,
                              distance_km=dist)

    # A verdict that speaks for a route it cannot see half of is the defect, not
    # the numbers behind it. Say which it is rather than leaving the reader to
    # infer it from a fraction.
    coverage["verdict_covers"] = ("the whole route"
                                  if coverage["coverage_fraction"] >= 0.8
                                  else "part of the route")
    # `unverified` already says this in its own sentence, from the same numbers.
    if (verdict != "unverified" and coverage["coverage_fraction"] < 0.8
            and coverage["longest_gap_km"] > 0):
        summary += (f" No checkpoint is tracked for {coverage['longest_gap_km']:.0f}"
                    f" km of this route ({coverage['longest_gap_from_km']:.0f}-"
                    f"{coverage['longest_gap_to_km']:.0f} km in), so that stretch is"
                    f" unverified — the verdict covers the rest.")

    with conn.cursor() as cur:
        cur.execute(PASSES_SQL, {"wkt": wkt, "near": PASSES_METRES})
        pass_rows = cur.fetchall()
    # Spread the sample along the route instead of taking the first N by
    # position. 228 named places sit within 1.5 km of Ramallah->Nablus and the
    # first twelve are all Ramallah and al-Bireh city-centre POIs — a list that
    # stops at km 3 answers nothing about a 53 km drive. One representative per
    # equal slice of the route, choosing the place CLOSEST to the alignment in
    # each slice, is what "which towns does it go through" actually asks.
    cands = []
    for par, pen, palong, poff in pass_rows:
        nm = _waypoint_name(par, pen)
        if not nm or any(x in _fold_ar(nm) for x in _PASSES_NOISE):
            continue
        cands.append((float(palong), int(poff), nm, pen, nm == (par or "").strip()))
    # A PALESTINIAN TRAVELLER NAVIGATES BY THE NAMES THE ROAD SIGNS AND THE
    # CHANNELS USE. Within a slice, a place that has an Arabic name in the
    # gazetteer outranks one that has only a Latin one: the audit's
    # Ramallah->Nablus answer read "passes Ofra, Yabrud, Mevo Shillo, Givat
    # harel" — three of them settlements the traveller cannot enter, chosen
    # only because they sat nearest the alignment. The registry does not flag
    # settlements, so this is a preference, not a claim about what a place is.
    PASS_BUCKETS = 8
    chosen: dict[int, tuple] = {}
    seen_folded = set()
    for along, poff, nm, pen, has_ar in sorted(cands, key=lambda c: (not c[4], c[1])):
        b = min(PASS_BUCKETS - 1, int(along * PASS_BUCKETS))
        key = _fold_ar(nm).strip().lower()
        if key in seen_folded or b in chosen:
            continue
        chosen[b] = (along, poff, nm, pen)
        seen_folded.add(key)
    passes = [{"name": nm, "name_en": pen,
               "along": round(along, 3), "km": round(dist * along, 1),
               "off_m": poff}
              for _b, (along, poff, nm, pen) in sorted(chosen.items())]

    return Corridor(
        verdict=verdict, summary=summary,
        coverage=coverage, passes=passes,
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
        near_misses=near_misses,
        exit_closures=_closures_at_ends(near_misses, dist, cap=None),
        doubts=(doubt_records(coverage, near_misses, dist)
                if verdict in ("unverified", "slow") else []),
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
    # `unverified` outranks `unknown`: both are absences of evidence, but
    # unverified means the checkpoints we DID see were open, which is strictly
    # more than nothing. It sits below `slow` because a reported delay is still
    # a road somebody got through.
    rank = {"likely_open": 0, "slow": 1, "unverified": 2, "unknown": 3, "blocked": 4}
    out.sort(key=lambda c: (rank.get(c.verdict, 9), c.duration_minutes))
    return out