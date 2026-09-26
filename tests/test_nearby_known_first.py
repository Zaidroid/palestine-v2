"""2026-09-26: `checkpoints` around Nablus said "no recent updates" while Huwara,
Deir Sharaf and Awarta had readings minutes old — the route lists the nearest
N, and the six nearest the city centre were all unknown."""
from __future__ import annotations

from serve import mcp_en, mcp_server


def _cp(name, flow, km, **kw):
    return {"name": name, "name_en": name.upper(), "flow": flow, "straight_km": km,
            "passable": flow != "closed", "age_minutes": 5 if flow != "unknown" else None,
            **kw}


NEAREST = [_cp(f"u{i}", "unknown", 1 + i) for i in range(6)]
KNOWN = [_cp("حوارة", "open", 8.0), _cp("دير شرف", "closed", 9.0)]


def _api(path, **kw):
    if path == "/v2/geo/resolve":
        return {"found": True, "lat": 32.22, "lon": 35.26, "name": "نابلس", "name_en": "Nablus"}
    if kw.get("include_unknown") == "false":
        return {"results": KNOWN, "counts": {}}
    return {"results": NEAREST, "counts": {"in_radius": 71, "known": 2, "unknown": 69}}


def test_known_checkpoints_in_range_are_named_before_nearer_silences(monkeypatch):
    monkeypatch.setattr(mcp_server, "api", _api)
    p = mcp_server.checkpoints_near(place="نابلس")
    names = [c["name"] for c in p["checkpoints"]]
    assert names[:2] == ["حوارة", "دير شرف"] and len(names) == 6
    assert "حوارة" in p["answer"] and "قديمة" not in p["answer"]
    en = mcp_en.checkpoints_near(p)
    assert "No recent checkpoint reports" not in en and "closed" in en


def test_nothing_known_still_says_so(monkeypatch):
    def api(path, **kw):
        if path == "/v2/geo/resolve":
            return _api(path)
        return {"results": NEAREST, "counts": {"in_radius": 71, "known": 0, "unknown": 71}}
    monkeypatch.setattr(mcp_server, "api", api)
    p = mcp_server.checkpoints_near(place="نابلس")
    assert "قديمة" in p["answer"] and len(p["checkpoints"]) == 6


def test_a_search_under_way_keeps_its_place(monkeypatch):
    searched = _cp("بيتا", "unknown", 3, present=["inspection"], presence_age_minutes=10)
    many_known = [_cp(f"k{i}", "open", 5 + i) for i in range(6)]

    def api(path, **kw):
        if path == "/v2/geo/resolve":
            return _api(path)
        if kw.get("include_unknown") == "false":
            return {"results": many_known, "counts": {}}
        return {"results": [searched] + NEAREST[:5], "counts": {"in_radius": 20, "known": 6}}
    monkeypatch.setattr(mcp_server, "api", api)
    p = mcp_server.checkpoints_near(place="نابلس")
    assert "بيتا" in [c["name"] for c in p["checkpoints"]]
    assert "تفتيش" in p["answer"]


def test_the_english_incidents_answer_names_the_place_in_english(monkeypatch):
    """09-26 twelve-question run: "Around رام الله: settler attack in Yabrud …"."""
    def api(path, **kw):
        if path == "/v2/geo/resolve":
            return {"found": True, "lat": 31.9, "lon": 35.2, "name": "رام الله", "name_en": "Ramallah"}
        return {"items": [], "count": 0}
    monkeypatch.setattr(mcp_server, "api", api)
    p = mcp_server.incidents_near(place="رام الله")
    assert p.get("origin_en") == "Ramallah"
    assert "رام الله" not in mcp_en.incidents_near(p)
