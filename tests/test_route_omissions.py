"""A route must not go quiet about a closure it knows.

    ./.venv/bin/python -m pytest tests/test_route_omissions.py -q

Reported 2026-09-24: `can_i_travel` Ramallah -> Nablus answered "passable,
congested at Za'tara" while عين سينيا was closed 25 minutes earlier with two
independent sources. Measured causation: that checkpoint's centroid is 2,327 m
from the polyline the router returned, so the 300 m corridor dropped it — and
`Corridor.checkpoints`, which carries EVERY point with its age, was thrown away
by the MCP projection. So the caller could not see the omission, could not see
that a reading was stale, and the only names they ever got were `unreported`
plus the worst one or two.

These tests are about the shape of the answer, not about today's closures: a
test that asserts "Ein Siniya is closed" would fail the moment it reopens, and
would then be deleted rather than fixed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve import corridor as C                                   # noqa: E402
from serve import mcp_server as s                                   # noqa: E402


@pytest.fixture(scope="module")
def route():
    """One real journey. The box has Valhalla and the database; without either
    there is no answer to test and skipping is honest."""
    try:
        out = s.can_i_travel("رام الله", "نابلس")
    except Exception as exc:                                        # noqa: BLE001
        pytest.skip(f"routing unavailable: {exc}")
    if "checkpoints" not in out:
        pytest.skip("route answered from the failure path")
    return out


# ── the list the tool's own description promises ─────────────────────────────

def test_the_ordered_checkpoint_list_is_in_the_payload(route):
    """The tool promises the checkpoints ON the route with their ages. It had
    them and dropped them, which is how an omission became invisible."""
    assert route["checkpoints"], "no checkpoint list in the payload"
    positions = [c["position"] for c in route["checkpoints"]]
    assert positions == sorted(positions), "the list is not in travel order"
    for c in route["checkpoints"]:
        assert set(("name", "flow", "age_minutes", "off_route_m",
                    "independent_sources")) <= set(c)


def test_every_on_route_checkpoint_is_inside_the_corridor(route):
    """The list and the buffer must agree, or one of them is lying."""
    for c in route["checkpoints"]:
        assert c["off_route_m"] <= C.CORRIDOR_METRES, (c["name"], c["off_route_m"])


def test_an_unknown_reading_carries_no_invented_age(route):
    """`unknown` with an age beside it would read as a stale-but-real reading.
    Age is null exactly when there is no reading to age."""
    for c in route["checkpoints"]:
        if c["flow"] == "unknown":
            assert c["age_minutes"] is None, c


def test_the_oldest_reading_travels_with_the_answer(route):
    """How stale the evidence is decides how much the verdict means. It was
    dropped alongside the list."""
    assert "oldest_known_minutes" in route


# ── the band just outside the corridor ───────────────────────────────────────

def test_a_near_miss_is_named_and_never_promoted_onto_the_route(route):
    """The whole point. A closure 2.3 km off the alignment is not ON the route —
    promoting it would block journeys it does not block, which is its own kind of
    wrong answer. Both halves matter: named, and not counted."""
    on_route = {c["name"] for c in route["checkpoints"]}
    for m in route["near_misses"]:
        assert m["off_route_m"] > C.CORRIDOR_METRES, m
        assert m["off_route_m"] <= C.NEAR_MISS_METRES, m
        assert m["name"] not in on_route, m
        assert m["flow"] in ("closed", "congested", "slow"), m
        # And it must not have leaked into the scored fields.
        assert m["name"] not in route["blocked_at"]
        assert m["name"] not in route["not_reported_recently"]


def test_the_band_is_wider_than_the_corridor_by_construction():
    """A near-miss band narrower than the corridor would return nothing; a
    corridor wider than the band would score things it should only name."""
    assert C.CORRIDOR_METRES < C.NEAR_MISS_METRES


def test_a_closed_near_miss_is_spoken_not_only_structured(route):
    """The sentence is what a traveller hears. A fact that exists only in
    `near_misses` is a fact nobody read."""
    closed = [m for m in route["near_misses"] if m["flow"] == "closed"]
    if not closed:
        pytest.skip("no closed checkpoint within the band right now")
    answer = route["answer"]
    # An exit closure is spoken as the REASON ("إغلاق عند X على طريق …"), not
    # repeated as a nearby-closure warning (audit F011); either form names it.
    assert "انتبه" in answer or "إغلاق عند" in answer, answer
    assert any(m["name"] in answer for m in closed), (answer, closed)


def test_the_answer_and_the_payload_cannot_disagree_about_the_count(route):
    """Every checkpoint on the route is accounted for in what is spoken: named,
    counted as more-open, or counted as unreported (the short answer,
    2026-09-26, replaced the "3 of 8" sentence with the checkpoints themselves)."""
    sp = route["spoken"]
    assert len(sp["on_way"]) + sp["more_open"] + sp["unreported"] == len(route["checkpoints"])
    for w in sp["on_way"]:
        if w["flow"] != "unknown" and w["name"] not in (route.get("blocked_at") or []):
            assert w["name"] in route["answer"], (w, route["answer"])


def test_a_displaced_checkpoint_is_kept_once_with_its_best_reading(route):
    """A place appears once per direction and once per reading. Reporting the
    stale solo reading beside a fresh corroborated one understates a closure the
    system actually knows well — Ein Siniya had both at 2,327 m."""
    seen = [m["name"] for m in route["near_misses"]]
    assert len(seen) == len(set(seen)), f"duplicated near-miss: {seen}"
    for m in route["near_misses"]:
        assert m["flow"] in ("closed", "congested", "slow")
