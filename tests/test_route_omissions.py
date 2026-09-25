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

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve import corridor as C                                   # noqa: E402
from serve import mcp_server as s                                   # noqa: E402


def _routing_expected() -> bool:
    """Whether this checkout is one where routing MUST work.

    Skipping on any exception made these tests vanish exactly when routing is
    broken (audit F390): with Valhalla down on main-server the suite reported
    "N passed, 8 skipped" and `can_i_travel` answered every journey with the
    system error. HANDOFF §4: never infer health from the absence of a
    complaint. main-server runs the suite with PALESTINE_API set (CLAUDE.md)
    and has VALHALLA_URL in its .env; a laptop or cloud checkout has neither,
    and there skipping is still the honest answer. PALESTINE_REQUIRE_ROUTING=1
    forces it anywhere."""
    if os.environ.get("PALESTINE_API") or os.environ.get("PALESTINE_REQUIRE_ROUTING") == "1":
        return True
    try:
        from resolve.db import _env
        return bool(_env().get("VALHALLA_URL"))
    except Exception:                                               # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def route():
    """One real journey. The box has Valhalla and the database; without either
    there is no answer to test and skipping is honest — but only where routing
    is not expected to exist at all."""
    try:
        out = s.can_i_travel("رام الله", "نابلس")
    except Exception as exc:                                        # noqa: BLE001
        if _routing_expected():
            pytest.fail(f"routing is expected on this box and failed: {exc}")
        pytest.skip(f"routing unavailable: {exc}")
    if "checkpoints" not in out:
        if _routing_expected():
            pytest.fail(f"route answered from the failure path: {out.get('answer')}")
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
    `near_misses` is a fact nobody read.

    The NAME is the assertion, not the word "تنبيه". An exit closure is spoken
    as the REASON the route is unverified ("السبب: إغلاق عند …") and is kept
    out of the "تنبيه" clause on purpose (naming it twice reads as two
    closures), so requiring "تنبيه" failed in exactly the case this test
    guards whenever every closed near-miss was an exit closure (audit F328)."""
    closed = [m for m in route["near_misses"] if m["flow"] == "closed"]
    if not closed:
        pytest.skip("no closed checkpoint within the band right now")
    answer = route["answer"]
    assert any(m["name"] in answer for m in closed), (answer, closed)


def test_the_answer_and_the_payload_cannot_disagree_about_the_count(route):
    """"3 of 8" is a claim about the list. Count it from the list."""
    n = len(route["checkpoints"])
    known = len([c for c in route["checkpoints"] if c["flow"] != "unknown"])
    assert f"{known} من {n}" in route["answer"], route["answer"]


def test_a_displaced_checkpoint_is_kept_once_with_its_best_reading(route):
    """A place appears once per direction and once per reading. Reporting the
    stale solo reading beside a fresh corroborated one understates a closure the
    system actually knows well — Ein Siniya had both at 2,327 m."""
    seen = [m["name"] for m in route["near_misses"]]
    assert len(seen) == len(set(seen)), f"duplicated near-miss: {seen}"
    for m in route["near_misses"]:
        assert m["flow"] in ("closed", "congested", "slow")


# ── the corridor's structure, as the Arabic answer speaks it ─────────────────
#
# Offline: the corridor builds the payload with its own functions and the MCP
# renderer reads it through a patched `api`, so this runs without Valhalla or a
# database. The live tests above depend on today's closures; this one does not.

def _payload(verdict_cps, near, dist=53.2):
    cov = C.coverage_of(verdict_cps, dist)
    verdict, summary = C._score(verdict_cps, coverage=cov, near_misses=near,
                                distance_km=dist)
    records = C.doubt_records(cov, near, dist)
    cov["verdict_covers"] = C.verdict_covers(cov, records)
    corr = C.Corridor(
        verdict=verdict, summary=summary, distance_km=dist, duration_minutes=51.4,
        checkpoints_on_route=len(verdict_cps),
        known=sum(1 for c in verdict_cps if c.flow != "unknown"),
        unknown=sum(1 for c in verdict_cps if c.flow == "unknown"),
        worst="open", oldest_known_minutes=18.0,
        unreported=[c.name for c in verdict_cps if c.flow == "unknown"],
        near_misses=near, exit_closures=C._closures_at_ends(near, dist, cap=None),
        doubts=records, checkpoints=verdict_cps, coverage=cov)
    return {"routes": [corr.as_dict()]}


def test_the_arabic_answer_names_the_exit_closure_the_corridor_found(monkeypatch):
    """The audit's 16:47 shape end to end: open checkpoints only past km 27,
    Beit El closed 2 km off the line on the way out of Ramallah."""
    def cp(name, flow, along):
        c = C.CheckpointOnRoute(hash(name) % 10_000, name, along, 50, 32.0, 35.2)
        c.flow, c.age_minutes = flow, (12.0 if flow != "unknown" else None)
        return c
    cps = [cp("زعتره", "open", 0.55), cp("عيون الحرامية", "unknown", 0.6),
           cp("حوارة", "open", 0.8)]
    near = [{"place_id": 7, "name": "بيت ايل", "name_en": "Beit El",
             "off_route_m": 2000, "flow": "closed", "age_minutes": 68.0,
             "independent_sources": 2, "along": 0.05}]
    payload = _payload(cps, near)
    assert payload["routes"][0]["verdict"] == "unverified"
    monkeypatch.setattr(s, "api", lambda path, **kw: payload)
    out = s.can_i_travel("رام الله", "نابلس")
    assert out["verdict"] == "unverified"
    assert "بيت ايل" in out["answer"], out["answer"]
    assert [x["name"] for x in out["exit_closures"]] == ["بيت ايل"]
    assert any(d["kind"] == "exit_closure" for d in out["doubts"])
