"""P7.1 — the properties that make a route answer safe to act on.

    ./.venv/bin/python -m pytest tests/test_corridor.py -q

A corridor answer is more dangerous than a point answer, because it aggregates:
one wrong checkpoint becomes one wrong journey, and the person has already left.
These cover the asymmetry that keeps that from happening, and the polyline bug
that would silently move the whole route to the wrong country.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve import corridor as C                           # noqa: E402
from resolve.corridor import (CORRIDOR_METRES, ENDS_KM,   # noqa: E402
                              UNVERIFIED_GAP_KM, CheckpointOnRoute,
                              _closures_at_ends, _score, decode_polyline,
                              doubt_records)


# Captured from our Valhalla for a short road inside Nablus.
SHAPE = "owrm|@gfwfbAZuBlEyQhHi^nB{MdAqLZiHD_JOoHcA{HoJmSwMwNmGqGsKsH"


def cp(name, flow, along=0.5, age=5.0):
    c = CheckpointOnRoute(1, name, along, 10, 32.0, 35.0)
    c.flow, c.age_minutes = flow, age
    return c


# ── the asymmetry: a journey is a conjunction ────────────────────────────────

def test_one_closure_blocks_a_route_however_many_are_open():
    """Every checkpoint has to be passable, not most of them. Averaging would
    report a route with four open checkpoints and one shut as 'mostly fine'."""
    v, msg = _score([cp("A", "open"), cp("B", "open"), cp("C", "closed"),
                     cp("D", "open"), cp("E", "open")])
    assert v == "blocked"
    assert "C" in msg


def test_the_blocking_checkpoint_is_named_with_its_age():
    """'Blocked' is not actionable; 'closed at Za'tara 4 minutes ago' is — it
    tells the traveller how much to trust it and where to ask."""
    v, msg = _score([cp("زعتره", "closed", age=4.0)])
    assert v == "blocked" and "زعتره" in msg and "4 min" in msg


def test_unknowns_never_block():
    """An unreported checkpoint is not a closed one. Treating silence as
    closure would make the whole map unusable at 23% coverage."""
    v, _ = _score([cp("A", "open"), cp("B", "unknown"), cp("C", "unknown")])
    assert v == "likely_open"


def test_unknowns_are_never_silently_passed_over_either():
    """They must appear in the sentence. 'We do not know' is an answer; leaving
    it out turns partial knowledge into an implied all-clear."""
    _, msg = _score([cp("A", "open"), cp("B", "unknown"), cp("C", "unknown")])
    assert "1 of 3" in msg and "2 have not been reported" in msg


def test_a_route_with_nothing_known_says_so_rather_than_guessing():
    v, msg = _score([cp("A", "unknown"), cp("B", "unknown")])
    assert v == "unknown"
    assert "No recent reports" in msg


def test_congestion_is_reported_without_blocking():
    v, msg = _score([cp("A", "open"), cp("B", "congested")])
    assert v == "slow" and "B" in msg


def test_closure_outranks_congestion():
    v, _ = _score([cp("A", "congested"), cp("B", "closed")])
    assert v == "blocked"


def test_an_empty_route_is_unknown_not_open():
    """No checkpoints matched means we know nothing about the road, not that
    the road is clear."""
    v, _ = _score([])
    assert v == "unknown"


# ── "likely open" has to have SEEN the route ─────────────────────────────────
#
# Regression cover for the partner audit of 2026-09-24, which caught the same
# trip reading "likely open" four times while the checkpoints out of the origin
# were closed and half the drive was watched by nothing.

def _coverage(gap_km, dist=53.2):
    return {"distance_km": dist, "longest_gap_km": gap_km,
            "longest_gap_from_km": 0.0, "longest_gap_to_km": gap_km,
            "coverage_fraction": round(1.0 - gap_km / dist, 2)}


def _miss(name, flow="closed", off_m=2300, along=0.02):
    return {"place_id": 1, "name": name, "name_en": name, "off_route_m": off_m,
            "flow": flow, "age_minutes": 18.0, "independent_sources": 2,
            "along": along}


def test_open_checkpoints_do_not_certify_a_route_nobody_watched():
    """The measured case: 53.2 km with the first tracked checkpoint at 26.8 km.
    Every checkpoint we could see was open, and the verdict still may not say
    the route is open, because it has not seen the route."""
    v, msg = _score([cp("A", "open", along=0.55)],
                    coverage=_coverage(26.8), distance_km=53.2)
    assert v == "unverified"
    assert "27 km" in msg and "Check before travelling" in msg


def test_a_gap_shorter_than_the_threshold_still_reads_open():
    """The rule has to stay silent on ordinary routes or it means nothing:
    West Bank coverage is thin everywhere, so a short blind stretch between two
    junctions is the normal case, not a warning."""
    v, _ = _score([cp("A", "open")],
                  coverage=_coverage(UNVERIFIED_GAP_KM - 1), distance_km=53.2)
    assert v == "likely_open"


def test_a_closure_on_the_way_out_of_town_blocks_the_open_verdict():
    """Ein Siniya, Beit El and Silwad were closed 2.0-2.6 km off the route at
    the Ramallah end. A closure that near the origin is usually the road you
    must take to reach the corridor at all."""
    v, msg = _score([cp("A", "open", along=0.6)],
                    coverage=_coverage(2.0), near_misses=[_miss("عين سينيا")],
                    distance_km=53.2)
    assert v == "unverified"
    assert "عين سينيا" in msg and "leaving" in msg


def test_a_closure_at_the_destination_end_counts_too():
    v, msg = _score([cp("A", "open", along=0.4)],
                    coverage=_coverage(2.0),
                    near_misses=[_miss("حوارة", along=0.99)], distance_km=53.2)
    assert v == "unverified" and "arriving at" in msg


def test_a_closure_in_the_middle_of_a_long_drive_does_not():
    """Mid-route, an off-corridor closure is far more often a genuinely
    different road. It is still reported in near_misses; it just does not
    overturn the verdict."""
    v, _ = _score([cp("A", "open")],
                  coverage=_coverage(2.0),
                  near_misses=[_miss("somewhere", along=0.5)], distance_km=53.2)
    assert v == "likely_open"


def test_congestion_off_the_route_does_not_trigger_unverified():
    """A busy junction near town is the road's normal state and would fire on
    almost every trip, which would make the verdict meaningless."""
    v, _ = _score([cp("A", "open")],
                  coverage=_coverage(2.0),
                  near_misses=[_miss("busy", flow="congested")], distance_km=53.2)
    assert v == "likely_open"


def test_unverified_never_overrides_evidence_we_do_have():
    """It qualifies an ABSENCE of evidence. A confirmed closure on the route
    still blocks and congestion still reads slow — degrading those would hide
    what we actually know."""
    blocked, _ = _score([cp("C", "closed")], coverage=_coverage(40.0),
                        near_misses=[_miss("x")], distance_km=53.2)
    slow, _ = _score([cp("A", "open"), cp("B", "congested")],
                     coverage=_coverage(40.0), near_misses=[_miss("x")],
                     distance_km=53.2)
    assert blocked == "blocked" and slow == "slow"


def test_score_without_coverage_is_unchanged():
    """Callers that pass no coverage (and the existing tests above) must keep
    the old behaviour, so the new rule can never fire on missing input."""
    v, _ = _score([cp("A", "open"), cp("B", "unknown")])
    assert v == "likely_open"


def test_the_ends_window_scales_with_the_route_and_is_capped():
    """ENDS_KM is a distance, so on a long drive it is a small slice at each
    end and the middle is excluded. On a hop shorter than 2*ENDS_KM the whole
    route genuinely IS within reach of both ends, and the cap at half keeps the
    two windows from overlapping into a double count."""
    mid_long = _miss("mid", along=0.5)
    assert _closures_at_ends([mid_long], distance_km=53.2) == []
    assert _closures_at_ends([_miss("out", along=0.02)], distance_km=53.2)
    # 4 km hop: every point on it is inside ENDS_KM of an end.
    assert len(_closures_at_ends([mid_long], distance_km=4.0)) == 1


def test_only_the_three_nearest_closures_are_named():
    """The verdict is a briefing, not a directory of every shut checkpoint in
    the governorate, and the ones closest to the alignment are the ones most
    likely to actually be on the way."""
    many = [_miss(f"cp{i}", off_m=500 * (i + 1), along=0.01) for i in range(6)]
    picked = _closures_at_ends(many, distance_km=53.2)
    assert [m["name"] for m in picked] == ["cp0", "cp1", "cp2"]


# ── the polyline, which fails silently ───────────────────────────────────────

def test_valhalla_polylines_decode_at_1e6_not_1e5():
    """Valhalla encodes at precision 6; most polyline code assumes Google's 5.
    Getting it wrong does not raise — it puts the route in the wrong part of
    the world, matches zero checkpoints, and reads exactly like a quiet day."""
    # A REAL shape returned by our Valhalla for a road inside Nablus, captured
    # rather than invented — a hand-made string tests the decoder against my
    # idea of the format instead of against the format.
    lon, lat = decode_polyline(SHAPE)[0]
    assert 34.0 < lon < 36.0, f"longitude {lon} is not in Palestine"
    assert 31.0 < lat < 33.5, f"latitude {lat} is not in Palestine"
    # The same string at 1e5 lands at (352, 322) — off the planet, and silent.
    wrong_lon, wrong_lat = decode_polyline(SHAPE, precision=5)[0]
    assert not (34.0 < wrong_lon < 36.0 and 31.0 < wrong_lat < 33.5)


def test_a_polyline_decodes_to_more_than_its_first_point():
    assert len(decode_polyline(SHAPE)) >= 2


# ── the buffer is a measured choice ──────────────────────────────────────────

def test_the_corridor_buffer_is_wide_enough_for_registry_error():
    """Measured on Ramallah->Nablus: 100m finds 5 checkpoints, 200m finds 8,
    300m finds 10, 500m finds 11. Za'tara sits 247m from the line and is
    unambiguously on that road, so anything under 250 drops a checkpoint that
    matters. Registry coordinates are approximate; the slack is for them."""
    assert 250 <= CORRIDOR_METRES <= 400


# ── the reasons are STRUCTURED so both languages can say them ────────────────

def test_doubts_are_records_a_renderer_can_speak():
    recs = doubt_records(_coverage(26.8), [_miss("عين سينيا"), _miss("حوارة", along=0.99)],
                         distance_km=53.2)
    kinds = [r["kind"] for r in recs]
    assert kinds[0] == "blind_stretch" and recs[0]["km"] == 26.8
    ends = {r["name"]: r["end"] for r in recs if r["kind"] == "exit_closure"}
    assert ends == {"عين سينيا": "origin", "حوارة": "destination"}


def test_exit_closures_are_uncapped_in_the_payload_and_capped_in_the_sentence():
    many = [_miss(f"cp{i}", off_m=500 * (i + 1), along=0.01) for i in range(6)]
    assert len(_closures_at_ends(many, distance_km=53.2)) == 3
    assert len(_closures_at_ends(many, distance_km=53.2, cap=None)) == 6


def test_both_spoken_answers_name_the_exit_closure_and_the_cause():
    """The audit's Ramallah->Nablus case, as the renderers see it. The reason a
    route is unverified lived in `summary`, which neither answer used."""
    from serve import mcp_en
    payload = {"verdict": "unverified", "blocked_at": [], "duration_minutes": 51.4,
               "routes": [{"known": 2, "checkpoints_on_route": 8, "coverage": {}}],
               "passes": [], "near_misses": [],
               "doubts": [{"kind": "blind_stretch", "km": 26.8, "from_km": 0, "to_km": 26.8},
                          {"kind": "exit_closure", "name": "عين سينيا", "name_en": "Ein Sinya",
                           "flow": "closed", "off_route_m": 2327, "age_minutes": 18,
                           "end": "origin"}]}
    en = mcp_en.can_i_travel(payload)
    assert en.startswith("Cannot confirm this route is open")
    assert "Ein Sinya" in en and "out of the origin" in en and "no tracked checkpoint" in en


# ── G2 as written: `likely_open` needs coverage measured on READINGS ─────────
#
# PLAN §6 G2: "`open` only when corridor coverage ≥ 0.6". The code checked an
# absolute 10 km gap measured on the REGISTRY — where checkpoints are, not
# where anybody has looked — and never read a fraction at all (audit F071,
# F380, and the lead probe: 1 of 8 known read `likely_open`).

def test_a_short_drive_that_is_mostly_unwatched_is_not_open():
    """F071. Ramallah->Bir Zeit shape: 12 km, the one reported checkpoint at
    km 3, nothing for the other 9. A 10 km gap can never fire on a drive this
    short, so the coverage floor is the only thing that stops "probably
    passable" being said over a road three-quarters unwatched."""
    v, msg = _score([cp("A", "open", along=0.25)],
                    coverage=_coverage(9.0, dist=12.0), distance_km=12.0)
    assert v == "unverified", msg
    assert "Check before travelling" in msg


def test_g2_floor_on_the_nineteen_km_case():
    """F380: tracked checkpoints at km 9 and km 18 of a 19 km drive — the
    longest gap is 9 km, coverage 0.53. G2 as written says not open."""
    cps = [cp("A", "open", along=9 / 19), cp("B", "open", along=18 / 19)]
    cov = C.coverage_of(cps, 19.0)
    assert cov["reported_fraction"] < C.MIN_OPEN_COVERAGE
    v, _ = _score(cps, coverage=cov, distance_km=19.0)
    assert v == "unverified"


def test_silent_checkpoints_are_not_coverage():
    """The lead probe. Eight tracked checkpoints spread evenly, ONE with a
    current reading: the registry is dense, the evidence is not, and the verdict
    was the same whether 1 or 8 were known (PLAN §4 R2)."""
    alongs = [0.06, 0.18, 0.30, 0.42, 0.54, 0.66, 0.78, 0.90]
    cps = [cp(f"c{i}", "open" if i == 4 else "unknown", along=a)
           for i, a in enumerate(alongs)]
    cov = C.coverage_of(cps, 40.0)
    assert cov["coverage_fraction"] >= 0.8             # where checkpoints ARE
    assert cov["reported_fraction"] < C.MIN_OPEN_COVERAGE  # where anybody LOOKED
    v, msg = _score(cps, coverage=cov, distance_km=40.0)
    assert v == "unverified", msg
    recs = doubt_records(cov, [], 40.0)
    silent = [r for r in recs if r["kind"] == "unreported_stretch"]
    assert silent, recs
    assert {"c0", "c1", "c2", "c3"} <= set(silent[0]["silent"])
    # "No tracked checkpoint" would be false here — eight are tracked.
    assert not [r for r in recs if r["kind"] == "blind_stretch"], recs


def test_knowing_a_checkpoint_exists_never_makes_a_route_more_open():
    """Monotonicity. Readings at km 5/20/35/50 of 53 leave 15 km stretches
    nobody watches, which already reads `unverified`. Adding three REGISTRY
    rows nobody has reported in those stretches used to turn the same evidence
    into `likely_open`, because the gap was measured between tracked rows."""
    reported = [cp(f"r{i}", "open", along=k / 53.0) for i, k in enumerate((5, 20, 35, 50))]
    v_bare, _ = _score(reported, coverage=C.coverage_of(reported, 53.0), distance_km=53.0)
    silent = [cp(f"s{i}", "unknown", along=k / 53.0) for i, k in enumerate((12, 27, 42))]
    cps = sorted(reported + silent, key=lambda c: c.along)
    v_more, _ = _score(cps, coverage=C.coverage_of(cps, 53.0), distance_km=53.0)
    assert v_bare == "unverified"
    assert v_more == "unverified"


def test_a_well_reported_route_still_reads_open():
    """The floor has to stay silent where the evidence is real, or `unverified`
    means nothing: readings every 8 km of a 40 km drive."""
    cps = [cp(f"r{i}", "open", along=k / 40.0) for i, k in enumerate((4, 12, 20, 28, 36))]
    cov = C.coverage_of(cps, 40.0)
    assert cov["reported_fraction"] >= C.MIN_OPEN_COVERAGE
    v, _ = _score(cps, coverage=cov, distance_km=40.0)
    assert v == "likely_open"


def test_the_fraction_floor_is_the_plans_number():
    assert C.MIN_OPEN_COVERAGE == 0.6


# ── `slow` is a claim that the road is passable, so it carries its doubts ────

def test_slow_carries_its_doubts():
    """F318. The only watched checkpoint is a congested one 47 km in, the first
    45 km are unwatched and Beit El is closed on the way out. `slow` survives
    (a reported delay is evidence) but it may not arrive without the reasons
    `likely_open` would have been withheld for."""
    v, msg = _score([cp("A", "open", along=0.9), cp("B", "congested", along=0.95)],
                    coverage=_coverage(45.0, dist=50.0),
                    near_misses=[_miss("بيت ايل", along=0.03)], distance_km=50.0)
    assert v == "slow"
    assert "B" in msg
    assert "بيت ايل" in msg and "45 km" in msg and "Check before travelling" in msg


# ── the flow vocabulary is closed ────────────────────────────────────────────

def test_an_unrecognised_flow_is_never_confirmed_open():
    """F530. A value the scorer does not know ('restricted', 'checking', a new
    crowd value) is not a reading of `open`."""
    v, msg = _score([cp("A", "restricted")])
    assert v == "unknown", msg
    v, msg = _score([cp("A", "open"), cp("B", "restricted")])
    assert "1 of 2" in msg and "1 have not been reported" in msg, msg


# ── `verdict_covers` is derived from the same doubt as the verdict ───────────

def test_verdict_covers_never_says_whole_route_beside_a_blind_stretch():
    """F531. 60 km with a 10.5 km blind stretch: coverage 0.83, so the old 0.8
    rule said "the whole route" beside a verdict of `unverified` for exactly
    that stretch."""
    cov = _coverage(10.5, dist=60.0)
    recs = doubt_records(cov, [], 60.0)
    assert recs and C.verdict_covers(cov, recs) == "part of the route"
    clean = _coverage(6.0, dist=60.0)
    assert C.verdict_covers(clean, doubt_records(clean, [], 60.0)) == "the whole route"


# ── the audit's four Ramallah→Nablus cases (PLAN §7 P0-B.5) ──────────────────
#
# RECONSTRUCTED from the evidence log in docs/QA-2026-09-24-agent-audit.docx
# (the table "Route verdicts miss closures at the exits"), not captured: the
# Corridor inputs of those four calls were never saved. Positions along the
# 53.2 km drive follow the audit's words ("first 26.8 km have no tracked
# checkpoint", closures "2 to 2.6 km off the route" leaving Ramallah). Each must
# not read `likely_open`, and each must carry the exit closure it missed.

def _audit_route(known_at=(0.55, 0.8), unknown_at=(0.505, 0.6, 0.66, 0.72, 0.9, 0.95),
                 flow="open", congested=None):
    cps = [cp(f"k{i}", flow, along=a) for i, a in enumerate(known_at)]
    cps += [cp(f"u{i}", "unknown", along=a) for i, a in enumerate(unknown_at)]
    if congested:
        cps.append(cp(congested, "congested", along=0.52))
    return sorted(cps, key=lambda c: c.along)


def _audit_miss(name, off_m, along, age, flow="closed", srcs=2):
    m = _miss(name, flow=flow, off_m=off_m, along=along)
    m.update(age_minutes=age, independent_sources=srcs)
    return m


AUDIT_CASES = {
    # 16:47 — "Likely open"; Beit El closed 68 min / 2 sources, Ein Siniya
    # closed 18 min / 2 sources, Silwad closed, Silwad-Yabroud congested.
    "16:47": (_audit_route(),
              [_audit_miss("بيت ايل", 2000, 0.05, 68),
               _audit_miss("عين سينيا", 2327, 0.13, 18),
               _audit_miss("سلواد", 2600, 0.16, 40, srcs=1),
               _audit_miss("سلواد يبرود", 2500, 0.17, 30, flow="congested", srcs=1)],
              "likely_open", "بيت ايل"),
    # 16:24 — "Likely open"; Ein Siniya closed 3 min earlier; Beit El and
    # Silwad closed; all 2 to 2.6 km off the route.
    "16:24": (_audit_route(),
              [_audit_miss("عين سينيا", 2327, 0.13, 3),
               _audit_miss("بيت ايل", 2000, 0.05, 45),
               _audit_miss("سلواد", 2600, 0.16, 50, srcs=1)],
              "likely_open", "بيت ايل"),
    # 15:27 — "Passable but congested"; Ein Siniya closed 12 min / 2 sources,
    # Atara congested; neither on the route. Za'tara congested on it.
    "15:27": (_audit_route(congested="زعتره"),
              [_audit_miss("عين سينيا", 2327, 0.13, 12),
               _audit_miss("عطارة", 1800, 0.30, 20, flow="congested")],
              "slow", "عين سينيا"),
}


@pytest.mark.parametrize("case", sorted(AUDIT_CASES))
def test_the_audits_route_cases_do_not_read_open(case):
    cps, near, was, exit_name = AUDIT_CASES[case]
    cov = C.coverage_of(cps, 53.2)
    v, msg = _score(cps, coverage=cov, near_misses=near, distance_km=53.2)
    assert v != "likely_open", (case, msg)
    assert exit_name in msg, (case, msg)
    recs = doubt_records(cov, near, 53.2)
    assert any(r["kind"] == "exit_closure" and r["name"] == exit_name for r in recs)
    if was == "slow":
        # A reported delay is still evidence; it stays `slow`, with its doubts.
        assert v == "slow"
    else:
        assert v == "unverified"


def test_the_audits_0900_case_blocks_and_names_the_stale_row_with_its_age():
    """09:00 — "Blocked at Huwara" while Huwara main read open 78 min; the
    block came from the separate "Huwara Under Bridge" row, 5 hours old. A
    confirmed closure still blocks (the asymmetry), and it is named with its
    age so the reader can weigh a five-hour-old report."""
    cps = [cp("حوارة", "open", along=0.9, age=78.0),
           cp("حوارة تحت الجسر", "closed", along=0.91, age=300.0)]
    v, msg = _score(cps, coverage=C.coverage_of(cps, 53.2), distance_km=53.2)
    assert v == "blocked"
    assert "حوارة تحت الجسر" in msg and "300 min" in msg


# ── against the database: the corridor reads what the serving views say ─────
#
# A synthetic world in the open sea west of the coast (no real place is within
# 50 km of it), inserted inside a transaction that is always rolled back — the
# tests/test_crowd.py pattern. Skipped where there is no database.

LON0, LAT0 = 33.30, 32.20
KM_PER_DEG_LAT = 110.86
KM_PER_DEG_LON = 111.32 * math.cos(math.radians(LAT0))


def _encode(points, precision=6):
    """Valhalla's polyline6, the inverse of decode_polyline; points are (lon, lat)."""
    out, plat, plon = [], 0, 0
    for lon, lat in points:
        ilat, ilon = round(lat * 10 ** precision), round(lon * 10 ** precision)
        for d in (ilat - plat, ilon - plon):
            v = ~(d << 1) if d < 0 else (d << 1)
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def test_the_test_encoder_round_trips():
    pts = [(LON0, LAT0), (LON0 + 0.1, LAT0 + 0.2)]
    back = decode_polyline(_encode(pts))
    assert all(abs(a - b) < 1e-6 for p, q in zip(pts, back) for a, b in zip(p, q))


class _World:
    def __init__(self, conn):
        self.conn = conn
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO source (key, name, kind, license_spdx,
                                               commercial_use, attribution_text,
                                               authority_rank)
                           VALUES ('_t_corridor', '_t_corridor', 'manual', 'NONE',
                                   false, 't', 5) RETURNING source_id""")
            self.source_id = cur.fetchone()[0]

    def place(self, kind, lon, lat, name_ar=None, name_en=None):
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO place (kind, name_ar, name_en, geom)
                           VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                           RETURNING place_id""",
                        (kind, name_ar, name_en, lon, lat))
            return cur.fetchone()[0]

    def flow(self, pid, value, minutes_ago, direction="both", sources=1, base=0.9):
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO state_current (place_id, state_kind, value,
                                   observed_at, source_id, base_confidence,
                                   independent_sources, direction)
                           VALUES (%s, 'checkpoint_flow', %s,
                                   now() - make_interval(mins => %s), %s, %s, %s, %s)""",
                        (pid, value, minutes_ago, self.source_id, base, sources, direction))

    def served(self, pid):
        with self.conn.cursor() as cur:
            cur.execute("""SELECT direction, flow FROM checkpoint_serving
                            WHERE place_id = %s""", (pid,))
            return dict(cur.fetchall())


def _north(km, east_m=0.0):
    """A point `km` north of the origin, `east_m` metres off the line."""
    return (LON0 + east_m / 1000.0 / KM_PER_DEG_LON, LAT0 + km / KM_PER_DEG_LAT)


def _trip(points, length_km):
    return {"legs": [{"shape": _encode(points)}],
            "summary": {"length": length_km, "time": length_km * 60.0}}


def _straight(length_km):
    return _trip([_north(0.0), _north(length_km)], length_km)


@pytest.fixture()
def world():
    try:
        import psycopg

        from resolve.db import dsn
        conn = psycopg.connect(dsn(), connect_timeout=3)
    except Exception as exc:                                        # noqa: BLE001
        pytest.skip(f"no database in this checkout: {exc}")
    try:
        yield _World(conn)
    finally:
        conn.rollback()
        conn.close()


def _cp(w, km, *readings, east_m=0.0, name=None):
    pid = w.place("checkpoint", *_north(km, east_m), name_ar=name or f"ح{km:g}")
    for r in readings:
        w.flow(pid, *r)
    return pid


def test_a_short_route_with_one_reading_is_unverified_end_to_end(world):
    """F071 through the real queries: 12 km, one open checkpoint at km 3."""
    _cp(world, 3.0, ("open", 5, "both", 2))
    c = C._corridor_for(world.conn, _straight(12.0), False)
    assert c.checkpoints_on_route == 1
    assert c.verdict == "unverified", c.summary
    assert c.doubts and c.coverage["verdict_covers"] == "part of the route"


def test_a_fresh_both_reading_supersedes_a_stale_directional_one(world):
    """F320. 60 min ago one channel said Beit El was closed INBOUND; 5 min ago
    three said it is open (both ways). checkpoint_status serves open in both
    travel directions (freshest of specific-or-both); the route must not say
    `blocked` on the same checkpoint in the same minute."""
    pid = _cp(world, 10.0, ("closed", 60, "inbound", 1), ("open", 5, "both", 3),
              name="بيت ايل")
    assert world.served(pid) == {"inbound": "open", "outbound": "open", "both": "open"}
    c = C._corridor_for(world.conn, _straight(20.0), False)
    on = {x.name: x for x in c.checkpoints}
    assert c.verdict != "blocked", c.summary
    assert on["بيت ايل"].flow == "open"
    assert on["بيت ايل"].directions == {"inbound": "open", "outbound": "open"}


def test_a_superseded_directional_closure_is_not_an_exit_closure(world):
    """The same reconciliation for the band just off the route."""
    _cp(world, 5.0, ("open", 5, "both", 2))
    _cp(world, 12.0, ("open", 5, "both", 2))
    _cp(world, 1.0, ("closed", 60, "inbound", 1), ("open", 5, "both", 3),
        east_m=2000.0, name="عين سينيا")
    c = C._corridor_for(world.conn, _straight(16.0), False)
    assert not c.near_misses and not c.exit_closures, c.near_misses


def test_a_closure_reports_its_best_known_reading(world):
    """F321. Closed both ways: inbound a 60-minute single-channel report,
    outbound a 5-minute three-source one. The route used to say "closed (60
    min ago)" from one source — understating a closure the system knows well."""
    pid = _cp(world, 10.0, ("closed", 60, "inbound", 1), ("closed", 5, "outbound", 3),
              name="بيت ايل")
    c = C._corridor_for(world.conn, _straight(20.0), False)
    b = next(x for x in c.checkpoints if x.place_id == pid)
    assert c.verdict == "blocked"
    assert (b.age_minutes, b.independent_sources) == (5.0, 3), b
    assert "5 min ago" in c.summary


def test_open_is_only_as_fresh_as_its_stalest_direction(world):
    """The other half of F321, deliberately asymmetric: the travel direction is
    unknown, so an `open` checkpoint reports the OLDER of its two open readings
    — the one a traveller going that way would be relying on."""
    pid = _cp(world, 10.0, ("open", 40, "outbound", 1), ("open", 5, "inbound", 3))
    c = C._corridor_for(world.conn, _straight(20.0), False)
    o = next(x for x in c.checkpoints if x.place_id == pid)
    assert o.flow == "open" and o.age_minutes == 40.0
    assert c.oldest_known_minutes == 40.0


def test_slow_route_carries_doubts_and_exit_closures(world):
    """F318 end to end, and the renderers' contract: `doubts` and
    `exit_closures` are populated whatever the verdict."""
    _cp(world, 10.0, ("congested", 5, "both", 2), name="زعتره")
    _cp(world, 1.0, ("closed", 15, "both", 2), east_m=2300.0, name="عين سينيا")
    c = C._corridor_for(world.conn, _straight(20.0), False)
    assert c.verdict == "slow", c.summary
    assert [x["name"] for x in c.exit_closures] == ["عين سينيا"]
    kinds = {d["kind"] for d in c.doubts}
    assert "exit_closure" in kinds, c.doubts
    assert "عين سينيا" in c.summary


def test_blocked_and_unknown_routes_carry_doubts_too(world):
    _cp(world, 10.0, ("closed", 5, "both", 2), name="حوارة")
    _cp(world, 1.0, ("closed", 15, "both", 2), east_m=2300.0, name="عين سينيا")
    blocked = C._corridor_for(world.conn, _straight(20.0), False)
    assert blocked.verdict == "blocked"
    assert any(d["kind"] == "exit_closure" for d in blocked.doubts), blocked.doubts


def test_along_is_measured_in_metres_not_degrees(world):
    """F526. An L-shaped drive: 20 km east, then 30 km north. A closure 9.5 km
    along the first leg projected, in degree space, to 10.4 km — outside the
    10 km exit window — because a degree of longitude is 94 km here and a
    degree of latitude 111."""
    east = lambda km, south_m=0.0: (LON0 + km / KM_PER_DEG_LON,        # noqa: E731
                                    LAT0 - south_m / 1000.0 / KM_PER_DEG_LAT)
    corner = east(20.0)
    north = lambda km: (corner[0], LAT0 + km / KM_PER_DEG_LAT)          # noqa: E731
    trip = _trip([east(0.0), corner, north(30.0)], 50.0)
    for pt in (east(5.0), east(14.0), north(2.0), north(10.0), north(18.0), north(26.0)):
        pid = world.place("checkpoint", *pt, name_ar=f"ح{pt}")
        world.flow(pid, "open", 5, "both", 2)
    pid = world.place("checkpoint", *east(9.5, south_m=2000.0), name_ar="قرب البداية")
    world.flow(pid, "closed", 10, "both", 2)
    c = C._corridor_for(world.conn, trip, False)
    m = next(x for x in c.near_misses if x["name"] == "قرب البداية")
    assert abs(m["along"] * 50.0 - 9.5) < 0.3, m["along"] * 50.0
    assert [x["name"] for x in c.exit_closures] == ["قرب البداية"]
    assert c.verdict == "unverified", c.summary


def test_waypoints_are_towns_not_stations_governorates_or_hebrew_only_rows(world):
    """F528 + the part of F322 that needs no registry flag. A forecourt under a
    brand the noise list does not know, a governorate centroid and a row whose
    only name is in Hebrew script were all spoken as towns the route passes."""
    _cp(world, 3.0, ("open", 5, "both", 2))
    world.place("village", *_north(2.0, 400.0), name_ar="سنجل", name_en="Sinjil")
    world.place("station", *_north(6.5, 200.0), name_ar="الريان")
    world.place("governorate", *_north(9.0, 300.0), name_ar="محافظة تجريبية")
    world.place("village", *_north(14.0, 100.0), name_en="גבעת הראל")
    world.place("village", *_north(17.0, 500.0), name_ar="ترمسعيا", name_en="Turmus'ayya")
    c = C._corridor_for(world.conn, _straight(20.0), False)
    names = [p["name"] for p in c.passes]
    assert "سنجل" in names and "ترمسعيا" in names, names
    assert "الريان" not in names and "محافظة تجريبية" not in names, names
    assert not any("֐" <= ch <= "׿" for n in names for ch in n), names
    assert not any(p["name_en"] and any("֐" <= ch <= "׿" for ch in p["name_en"])
                   for p in c.passes), c.passes
