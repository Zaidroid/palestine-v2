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

from resolve.corridor import (CORRIDOR_METRES, CheckpointOnRoute,   # noqa: E402
                              _score, decode_polyline)


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
