"""P0-B.5 — the agent audit's four Ramallah->Nablus cases (24 Sep), replayed.

Each fixture carries the numbers the audit logged; each must NOT read `open`
(docs/QA-2026-09-24-agent-audit.docx, "Verdict given" table). Plus P0-B.4: the
rest of Tier 1 on the way is spoken as a caution, never as a blocker.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve import corridor as C                                          # noqa: E402
from resolve.corridor import CheckpointOnRoute, _score                     # noqa: E402

DIST = 53.2
BLIND = {"longest_gap_km": 26.8, "longest_gap_from_km": 0.0, "longest_gap_to_km": 26.8,
         "watched_fraction": 0.5, "coverage_fraction": 0.5}


def cp(name, flow, along=0.7, age=10.0):
    c = CheckpointOnRoute(1, name, along, 10, 32.0, 35.0)
    c.flow, c.age_minutes = flow, (age if flow != "unknown" else None)
    return c


def miss(name, flow, off, along, age):
    return {"name": name, "flow": flow, "off_route_m": off, "along": along, "age_minutes": age}


def test_1647_beit_el_ein_siniya_silwad_closed_off_the_exit():
    v, _ = _score([cp("زعترة", "open"), cp("حوارة", "open", 0.85)], coverage=BLIND,
                  near_misses=[miss("بيت ايل", "closed", 2014, 0.05, 68),
                               miss("عين سينيا", "closed", 2300, 0.12, 18),
                               miss("سلواد", "closed", 2600, 0.16, 40)],
                  distance_km=DIST)
    assert v == "unverified"


def test_1624_ein_siniya_closed_three_minutes_earlier():
    v, _ = _score([cp("زعترة", "open")], coverage=BLIND,
                  near_misses=[miss("عين سينيا", "closed", 2300, 0.12, 3)], distance_km=DIST)
    assert v != "likely_open"


def test_1527_congested_is_not_permission_while_a_closure_sits_at_the_exit():
    v, msg = _score([cp("عطارة", "congested", 0.1), cp("زعترة", "open")], coverage=BLIND,
                    near_misses=[miss("عين سينيا", "closed", 2300, 0.12, 12)], distance_km=DIST)
    assert v == "slow" and "But" in msg              # the doubt travels with the delay


def test_0900_a_five_hour_old_row_does_not_block_huwara():
    # The decayed "Huwara Under Bridge" row arrives as unknown (the serving view
    # withdraws a 5 h closure); the main checkpoint is open 78 min ago.
    v, _ = _score([cp("حوارة", "open", 0.85, 78), cp("حوارة تحت الجسر", "unknown", 0.86)],
                  coverage={"longest_gap_km": 4.0, "watched_fraction": 0.8}, distance_km=DIST)
    assert v != "blocked"


def test_incident_and_obstacle_cautions_are_structured_and_bounded():
    assert C.INCIDENT_METRES == 2000 and C.INCIDENT_HOURS == 3
    assert "place_precision' = 'named'" in C.INCIDENTS_NEAR_SQL     # never a governorate fallback
    assert set(C.INCIDENT_TYPES) == {"closure", "siege", "raid", "settler_attack", "shooting"}
    obs = C._obstacles()
    assert len(obs) == 431 and all(o["verified"] for o in obs)
    o = obs[0]
    near = C.obstacles_at_ends((o["lon"] + 0.001, o["lat"]), (35.9, 31.0))
    assert near and near[0]["end"] == "origin" and near[0]["metres"] < 300
    assert C.obstacles_at_ends((34.0, 30.0), (34.1, 30.1)) == []


def test_cautions_are_spoken_in_both_languages():
    from serve import mcp_en as EN
    from serve import mcp_server as S
    best = {"incidents_near": [{"type": "raid", "name": "بيتا", "name_en": "Beita",
                                "off_route_m": 844, "age_minutes": 80}],
            "road_closures": [], "obstacles_at_ends": [
                {"end": "origin", "type": "Earthmound", "name": "Burin EM", "verified": "2025-12",
                 "metres": 120}]}
    ar = S._tier1_cautions_ar(best, "بورين", "نابلس")
    assert "اقتحام ببيتا (قبل ساعة، 844 متر عن المسار)" in ar and "سدّة ترابية سجّلتها أوتشا" in ar
    en = EN.can_i_travel({"verdict": "unverified", "routes": [{}], **best})
    assert "raid in Beita (1h ago, 844 m off the route)" in en and "OCHA-recorded earthmound" in en


def test_a_live_route_carries_the_new_fields(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("can_i_travel", origin="رام الله", destination="نابلس"))
    for k in ("incidents_near", "road_closures", "obstacles_at_ends"):
        assert isinstance(p.get(k), list)
    assert p["verdict"] != "likely_open" or not p.get("exit_closures")
