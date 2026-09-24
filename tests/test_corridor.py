"""P7.1 — the properties that make a route answer safe to act on.

    ./.venv/bin/python -m pytest tests/test_corridor.py -q

A corridor answer is more dangerous than a point answer, because it aggregates:
one wrong checkpoint becomes one wrong journey, and the person has already left.
These cover the asymmetry that keeps that from happening, and the polyline bug
that would silently move the whole route to the wrong country.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.corridor import (CORRIDOR_METRES, ENDS_KM,   # noqa: E402
                              UNVERIFIED_GAP_KM, CheckpointOnRoute,
                              _closures_at_ends, _score, decode_polyline)


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
