"""The sentences a traveller hears, held offline (fix group: MCP tool answers,
2026-09-25).

Every test here calls a tool function in serve/mcp_server.py with `api`
replaced by a table of hand-built REST payloads — shapes read from serve/app.py
and resolve/corridor.py — and then the English renderer over the same payload.
So the answer is checked without a database and without a running API, which
is where the audit found most of these defects hiding: the live tests skip or
fail on data, and the renderers were never called on the shapes that break
them.

The rules held, in both languages:
  * a value is never spoken without its age, and a direction split carries
    both ages;
  * `unknown` (nobody credible looked recently) and `no source` (nothing
    measures this) are never blurred, and neither is a failure or an unknown
    name rendered as a quiet road;
  * `None` never reaches a sentence;
  * the Arabic and the English name the same facts.
"""
from __future__ import annotations

import copy
import io
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import mcp_en as E                                     # noqa: E402
from serve import mcp_facades as F                                # noqa: E402
from serve import mcp_server as s                                 # noqa: E402


# ── a fake API ───────────────────────────────────────────────────────────────

class FakeAPI:
    """`api(path, **params)` answered from a table. A value is returned as a
    deep copy; a callable is called with the non-None params; an Exception
    instance is raised. Every call is recorded so a test can check what the
    tool ASKED for, not only what it said."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, **params):
        p = {k: v for k, v in params.items() if v is not None}
        self.calls.append((path, p))
        if path not in self.routes:
            raise AssertionError(f"unexpected API call {path} {p}")
        r = self.routes[path]
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(**p)
        return copy.deepcopy(r)

    def params(self, path: str) -> list[dict]:
        return [p for x, p in self.calls if x == path]


@pytest.fixture
def fake(monkeypatch):
    def install(routes: dict) -> FakeAPI:
        f = FakeAPI(routes)
        monkeypatch.setattr(s, "api", f)
        return f
    return install


def both(tool: str, out: dict) -> tuple[str, str]:
    """The Arabic answer and the English one, from one payload."""
    out = E.add_english(tool, out)
    return out["answer"], out.get("answer_en") or ""


def _http_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://127.0.0.1:7870/v2/x")
    return httpx.HTTPStatusError(f"{code}", request=req,
                                 response=httpx.Response(code, request=req))


def _iso_ago(minutes: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


# ── payload builders (shapes from serve/app.py) ──────────────────────────────

def _status(flow="open", age=5, last=None, direction="both", by=None, present=(),
            score=1.0, name="قلنديا"):
    """/v2/checkpoints/status, found."""
    return {"found": True, "query": name,
            "match": {"resolved_to": name, "score": score},
            "place_id": 7, "name": name, "name_en": "Qalandiya",
            "lat": 31.86, "lon": 35.21, "direction": direction,
            "flow": flow, "passable": None if flow == "unknown" else flow != "closed",
            "last_known_flow": last or (None if flow == "unknown" else flow),
            "confidence": 0.8, "observed_at": _iso_ago(age or 0),
            "age_minutes": age, "staleness_band": "live",
            "independent_sources": 2, "contradicted_by": 0,
            "reported_for": direction, "cadence_measured": True,
            "present": list(present), "absent": [], "presence_age_minutes": None,
            "by_direction": by or {}, "attribution": "channels"}


def _dir(flow, age, present=()):
    """One /v2/checkpoints/status by_direction entry."""
    return {"flow": flow, "passable": None if flow == "unknown" else flow != "closed",
            "age_minutes": age, "present": list(present)}


def _near_row(name, flow, age, km=2.0, present=(), last=None, name_en=None):
    """One /v2/checkpoints/nearby result (app._checkpoint_out + straight_km)."""
    return {"place_id": abs(hash(name)) % 10_000, "name": name, "name_en": name_en,
            "lat": 32.2, "lon": 35.25, "direction": "both", "flow": flow,
            "passable": None if flow == "unknown" else flow != "closed",
            "last_known_flow": last or (None if flow == "unknown" else flow),
            "confidence": 0.7, "observed_at": None, "age_minutes": age,
            "staleness_band": "live", "independent_sources": 1,
            "contradicted_by": 0, "reported_for": "both", "cadence_measured": True,
            "present": list(present), "absent": [], "presence_age_minutes": None,
            "straight_km": km}


# resolve/corridor.py shapes: a CheckpointOnRoute as_dict, a near miss, a Corridor
EIN = {"place_id": 9, "name": "عين سينيا", "name_en": "Ein Sinya",
       "off_route_m": 2327, "flow": "closed", "age_minutes": 18.0,
       "independent_sources": 2, "along": 0.05}


def _cp(name, along, flow="open", age=20.0, name_en=None, presence=()):
    return {"place_id": abs(hash(name)) % 10_000, "name": name, "along": along,
            "off_route_m": 40, "lat": 32.0, "lon": 35.2, "flow": flow,
            "flow_last_known": None, "confidence": 0.8,
            "age_minutes": None if flow == "unknown" else age,
            "independent_sources": 1, "directions": {}, "presence": list(presence),
            "name_en": name_en}


def _corr(verdict, cps, near=(), exits=None, doubts=(), is_alt=False, dur=51.4,
          passes=(), coverage=None, cautions=()):
    known = [c for c in cps if c["flow"] != "unknown"]
    near = list(near)
    return {
        "verdict": verdict, "summary": "…", "distance_km": 53.2,
        "duration_minutes": dur, "checkpoints_on_route": len(cps),
        "known": len(known), "unknown": len(cps) - len(known), "worst": "open",
        "oldest_known_minutes": max((c["age_minutes"] for c in known
                                     if c["age_minutes"] is not None), default=None),
        "blocked_at": [c["name"] for c in cps if c["flow"] == "closed"],
        "slow_at": [c["name"] for c in cps if c["flow"] in ("congested", "slow")],
        "unreported": [c["name"] for c in cps if c["flow"] == "unknown"],
        "cautions": list(cautions), "near_misses": near,
        "exit_closures": list(exits if exits is not None else
                              [m for m in near if m["flow"] == "closed"
                               and (m["along"] <= 0.19 or m["along"] >= 0.81)]),
        "doubts": list(doubts), "checkpoints": cps,
        "coverage": coverage or {"distance_km": 53.2, "checkpoints_on_route": len(cps),
                                 "coverage_fraction": 0.9, "covered_km": 47.9,
                                 "longest_gap_km": 5.3, "longest_gap_from_km": 0.0,
                                 "longest_gap_to_km": 5.3,
                                 "verdict_covers": "the whole route"},
        "passes": list(passes), "shape": "", "is_alternate": is_alt}


def _between(*routes, origin="رام الله", dest="نابلس", o_place=None, d_place=None):
    best = routes[0] if routes else None
    return {"routes": list(routes),
            "best": ({"verdict": best["verdict"], "summary": best["summary"],
                      "distance_km": best["distance_km"],
                      "duration_minutes": best["duration_minutes"]} if best else None),
            "corridor_metres": 300, "note": "…",
            "origin": {"query": origin, "place": o_place or origin, "place_id": 1},
            "destination": {"query": dest, "place": d_place or dest, "place_id": 2}}


LATIN_VERDICT = re.compile(r"likely_open|unverified|\bslow\b|\bblocked\b|\bunknown\b")


# ═════════════════════════════════════════════════════════════════════════════
# checkpoint_status
# ═════════════════════════════════════════════════════════════════════════════

def test_f009_a_fresh_inbound_closure_is_spoken_when_the_undirected_row_decayed(fake):
    """The `both` row is built from undirected readings only (migration 027),
    so a fresh 'قلنديا دخول مغلق' never refreshes it. The answer used to read
    the decayed row: 'no new update — last report 3 h ago said open'."""
    fake({"/v2/checkpoints/status": _status(
        flow="unknown", age=190, last="open",
        by={"inbound": _dir("closed", 9), "outbound": _dir("unknown", None)})})
    ar, en = both("checkpoint_status", s.checkpoint_status("قلنديا"))
    assert "مغلق للداخل" in ar and "قبل 9 دقايق" in ar, ar
    assert "للخارج ما في تحديث" in ar, ar
    assert "closed inbound (9 min ago)" in en and "no recent reading outbound" in en, en


def test_f009_two_fresh_direction_closures_are_not_replaced_by_a_decayed_open(fake):
    fake({"/v2/checkpoints/status": _status(
        flow="unknown", age=190, last="open",
        by={"inbound": _dir("closed", 9), "outbound": _dir("closed", 14)})})
    ar, en = both("checkpoint_status", s.checkpoint_status("قلنديا"))
    assert "مغلق للداخل (قبل 9 دقايق)" in ar and "مغلق للخارج (قبل 14 دقيقة)" in ar, ar
    assert "كان سالك" not in ar, ar
    assert "closed inbound (9 min ago)" in en and "closed outbound (14 min ago)" in en, en
    assert "said open" not in en, en


def test_f047_f035_f053_a_direction_split_carries_both_ages(fake):
    """'قلنديا: سالك للداخل، ومغلق للخارج.' carried no age at all, and the
    presence clause dangled after the full stop."""
    fake({"/v2/checkpoints/status": _status(
        flow="open", age=3, present=["idf"],
        by={"inbound": _dir("open", 3), "outbound": _dir("closed", 170)})})
    ar, en = both("checkpoint_status", s.checkpoint_status("قلنديا"))
    assert "سالك للداخل (قبل 3 دقايق)" in ar and "مغلق للخارج (قبل 3 ساعات)" in ar, ar
    assert "جيش" in ar and not re.search(r"\.\s*وفي ", ar), ar
    assert "open inbound (3 min ago)" in en and "closed outbound (2h 50m ago)" in en, en
    assert "army" in en


def test_f052_f263_a_known_checkpoint_never_read_is_not_an_unknown_name(fake):
    fake({"/v2/checkpoints/status": {
        "found": False, "query": "الفوار", "resolved_to": "الفوار",
        "reason": "no checkpoint reading has ever been recorded here"}})
    ar, en = both("checkpoint_status", s.checkpoint_status("الفوار"))
    assert "ما عرفت حاجز" not in ar and "الفوار" in ar and "ولا تقرير" in ar, ar
    assert "No checkpoint found" not in en and "never" in en and "الفوار" in en, en
    assert "open" not in en.replace("not open", ""), en


def test_a_lookalike_name_is_refused_with_the_lookalike_named_and_no_flow(fake):
    """The REST route now answers found:false + `nearest` below its match gate
    (serve/app.py CHECKPOINT_MATCH_GATE). The renderers must name the lookalike
    as a lookalike and never give a flow."""
    fake({"/v2/checkpoints/status": {
        "found": False, "query": "Hawara", "uncertain": True,
        "nearest": {"place_id": 3, "name": "عورتا", "score": 0.707},
        "reason": "no checkpoint has this name"}})
    ar, en = both("checkpoint_status", s.checkpoint_status("Hawara"))
    assert "عورتا" in ar and "عورتا" in en
    assert not any(w in ar for w in ("سالك", "مغلق")), ar
    assert not re.search(r"\b(open|closed)\b", en), en


def test_f252_english_states_the_direction_asked_for(fake):
    fake({"/v2/checkpoints/status": _status(
        flow="closed", age=5, direction="outbound",
        by={"inbound": _dir("open", 4), "outbound": _dir("closed", 5)})})
    ar, en = both("checkpoint_status", s.checkpoint_status("قلنديا", direction="outbound"))
    assert "للخارج" in ar
    assert "outbound" in en, en


# ═════════════════════════════════════════════════════════════════════════════
# place_profile
# ═════════════════════════════════════════════════════════════════════════════

def _profile_routes(geo_cp, status_by_name, history=None, incidents=None):
    town = {"found": True, "query": "Hawara", "place_id": 100, "name": "حوارة",
            "name_en": "Huwara", "kind": "locality", "precision": "exact",
            "confidence": 0.9, "method": "alias", "lat": 32.15, "lon": 35.25}

    def geo(q, state_kind=None):
        return copy.deepcopy(geo_cp if state_kind else town)

    def status(name, direction="both"):
        r = status_by_name.get(name)
        if r is None:
            return {"found": False, "query": name}
        return copy.deepcopy(r)

    return {"/v2/geo/resolve": geo, "/v2/checkpoints/status": status,
            "/v2/history/place": history if history is not None else
            {"place_id": 100, "days": 30,
             "series": [{"day": f"2026-09-{d:02d}", "kinds": {}} for d in range(1, 13)]},
            "/v2/patterns/place": {"hours": [], "timezone": "Asia/Hebron", "note": "n"},
            "/v2/incidents/recent": incidents if incidents is not None else
            {"incidents": [], "by_type": {}, "count": 0}}


LOCALITY = {"found": True, "query": "Hawara", "place_id": 100, "name": "حوارة",
            "name_en": "Huwara", "kind": "locality", "lat": 32.15, "lon": 35.25}
CHECKPOINT = {"found": True, "query": "حوارة", "place_id": 200, "name": "حوارة",
              "name_en": "Huwara checkpoint", "kind": "checkpoint",
              "lat": 32.16, "lon": 35.26}


def test_f010_a_town_is_not_given_another_checkpoints_flow(fake):
    """cp resolved to the TOWN (a +3.0 bonus, not a filter), then the live
    status was fetched by the raw string through a different matcher and landed
    on عورتا at 0.707 — spoken as 'حوارة: الحاجز سالك' with no age."""
    fake(_profile_routes(LOCALITY, {
        "Hawara": _status(flow="open", age=300, name="عورتا", score=0.707)}))
    out = s.place_profile("Hawara")
    ar, en = both("place_profile", out)
    assert "عورتا" not in ar and "سالك" not in ar, ar
    assert "عورتا" not in en and "open" not in en, en
    assert out["resolved"]["as_checkpoint"] is False
    assert "(the checkpoint)" not in en


def test_f010_f264_the_checkpoint_clause_carries_its_age_in_arabic(fake):
    fake(_profile_routes(CHECKPOINT, {"حوارة": _status(flow="open", age=300, name="حوارة")}))
    out = s.place_profile("حوارة")
    ar, en = both("place_profile", out)
    assert "سالك" in ar and "قبل 5 ساعات" in ar, ar
    assert "open" in en and "5h ago" in en, en
    assert out["resolved"]["as_checkpoint"] is True


def test_f264_an_unknown_checkpoint_in_a_profile_keeps_its_last_value_and_age(fake):
    fake(_profile_routes(CHECKPOINT, {"حوارة": _status(flow="unknown", age=400,
                                                        last="open", name="حوارة")}))
    ar, en = both("place_profile", s.place_profile("حوارة"))
    assert "آخر معلومة" in ar and "كان سالك" in ar and "قبل 7 ساعات" in ar, ar
    assert "no current reading" in en and "said open" in en, en


def test_f061_the_profile_pattern_reads_the_flow_grain(fake):
    f = fake(_profile_routes(CHECKPOINT, {"حوارة": _status(name="حوارة")}))
    s.place_profile("حوارة")
    assert [p.get("state_kind") for p in f.params("/v2/patterns/place")] == ["checkpoint_flow"]


def test_f062_the_profile_incident_window_fits_the_api_and_is_said(fake):
    inc = {"incidents": [{"type": "raid", "place": "حوارة", "occurred_at": _iso_ago(90),
                          "independent_sources": 2, "place_precision": "named"}] * 2,
           "by_type": {"raid": 2}, "count": 2}
    f = fake(_profile_routes(CHECKPOINT, {"حوارة": _status(name="حوارة")}, incidents=inc))
    out = s.place_profile("حوارة", days=30)
    ar, en = both("place_profile", out)
    assert all(p["hours"] <= 168 for p in f.params("/v2/incidents/recent"))
    assert "7 أيام" in ar, ar
    assert "7 days" in en, en


def test_f063_a_failed_section_is_said_not_rendered_as_a_quiet_place(fake):
    routes = _profile_routes(CHECKPOINT, {})
    routes["/v2/checkpoints/status"] = _http_error(500)
    routes["/v2/history/place"] = httpx.ReadTimeout("timed out")
    routes["/v2/incidents/recent"] = _http_error(500)
    routes["/v2/patterns/place"] = _http_error(500)
    out = s.place_profile("حوارة")
    ar, en = both("place_profile", out)
    assert "ما في معلومات حديثة" not in ar and "ما قدرت أقرأ" in ar, ar
    assert "nothing recent" not in en and "Could not read" in en, en
    assert set(out["errors"]) >= {"checkpoint", "history", "incidents"}


# ═════════════════════════════════════════════════════════════════════════════
# can_i_travel
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("verdict,flow", [("slow", "congested"), ("blocked", "closed"),
                                          ("unknown", "unknown")])
def test_f011_an_exit_closure_is_spoken_whatever_the_verdict(fake, verdict, flow):
    """The audit's 15:27 case: 'passable, congested at Za'tara' while Ein Siniya
    was closed on the way out of Ramallah. Exit closures were subtracted from
    the near-miss warning and spoken only when the verdict was `unverified`."""
    cps = [_cp("زعترة", 0.75, flow=flow, age=40.0), _cp("حوارة", 0.9, flow="unknown")]
    fake({"/v2/route/between": _between(_corr(verdict, cps, near=[EIN]))})
    ar, en = both("can_i_travel", s.can_i_travel("رام الله", "نابلس"))
    assert "عين سينيا" in ar, ar
    assert "Ein Sinya" in en, en


def test_f011_every_exit_closure_is_at_least_counted_in_the_sentence(fake):
    exits = [{**EIN, "place_id": i, "name": f"حاجز{i}", "name_en": f"cp{i}",
              "off_route_m": 500 * (i + 1)} for i in range(5)]
    doubts = [{"kind": "exit_closure", "name": x["name"], "name_en": x["name_en"],
               "flow": "closed", "off_route_m": x["off_route_m"], "age_minutes": 18.0,
               "end": "origin"} for x in exits[:3]]
    cps = [_cp("زعترة", 0.75, flow="open", age=40.0)]
    fake({"/v2/route/between": _between(_corr("unverified", cps, near=exits,
                                              exits=exits, doubts=doubts))})
    ar, en = both("can_i_travel", s.can_i_travel("رام الله", "نابلس"))
    assert all(f"حاجز{i}" in ar for i in range(3)) and "و2 إغلاقات" in ar, ar
    assert "2 more" in en, en
    # and none of the five is repeated as a separate "nearby closure"
    assert "تنبيه: حاجز" not in ar, ar


def test_f059_f327_the_route_answer_speaks_the_age_of_its_evidence(fake):
    cps = [_cp("عطارة", 0.2, flow="open", age=12.0), _cp("زعترة", 0.6, flow="closed", age=40.0),
           _cp("حوارة", 0.9, flow="unknown")]
    fake({"/v2/route/between": _between(_corr("blocked", cps))})
    ar, en = both("can_i_travel", s.can_i_travel("رام الله", "نابلس"))
    assert "زعترة (قبل 40 دقيقة)" in ar, ar
    assert "أحدثها قبل 12 دقيقة" in ar and "أقدمها قبل 40 دقيقة" in ar, ar
    assert "40 min ago" in en and "newest 12 min ago" in en, en
    assert not LATIN_VERDICT.search(ar), ar


def test_f324_f254_a_detour_says_the_direct_road_is_blocked(fake):
    direct = _corr("blocked", [_cp("زعترة", 0.6, flow="closed", age=30.0)], dur=51.4)
    alt = _corr("likely_open", [_cp("دير دبوان", 0.5, flow="open", age=20.0)],
                is_alt=True, dur=66.0)
    fake({"/v2/route/between": _between(alt, direct)})
    out = s.can_i_travel("رام الله", "نابلس")
    ar, en = both("can_i_travel", out)
    assert "الطريق المباشر" in ar and "زعترة" in ar and "بديل" in ar, ar
    assert "66 دقيقة" in ar and "51 دقيقة" in ar, ar
    assert not LATIN_VERDICT.search(ar), ar
    assert "direct road" in en and "زعترة" in en and "alternative" in en, en
    assert [r["is_alternate"] for r in out["routes"]] == [True, False]


def test_f324_when_every_route_is_blocked_the_answer_says_so(fake):
    a = _corr("blocked", [_cp("زعترة", 0.6, flow="closed", age=30.0)], dur=51.4)
    b = _corr("blocked", [_cp("عطارة", 0.4, flow="closed", age=10.0)], is_alt=True, dur=70.0)
    fake({"/v2/route/between": _between(a, b)})
    ar, en = both("can_i_travel", s.can_i_travel("رام الله", "نابلس"))
    assert "البديل" in ar and "مسكّر" in ar, ar
    assert "alternative" in en and "blocked too" in en, en


def test_f323_slow_says_where_the_congestion_is(fake):
    cps = [_cp("زعترة", 0.75, flow="congested", age=25.0), _cp("حوارة", 0.9, flow="open", age=5.0)]
    fake({"/v2/route/between": _between(_corr("slow", cps))})
    ar, en = both("can_i_travel", s.can_i_travel("رام الله", "نابلس"))
    assert "أزمة عند زعترة" in ar, ar
    assert "congested at زعترة" in en, en


def test_f325_the_blind_stretch_is_said_in_kilometres(fake):
    blind = {"kind": "blind_stretch", "km": 10.5, "from_km": 40.2, "to_km": 50.7}
    cov = {"distance_km": 100.0, "checkpoints_on_route": 3, "coverage_fraction": 0.9,
           "covered_km": 89.5, "longest_gap_km": 10.5, "longest_gap_from_km": 40.2,
           "longest_gap_to_km": 50.7, "verdict_covers": "the whole route"}
    cps = [_cp("عطارة", 0.2, age=12.0), _cp("زعترة", 0.6, age=20.0)]
    fake({"/v2/route/between": _between(_corr("unverified", cps, doubts=[blind],
                                              coverage=cov, exits=[]))})
    ar, en = both("can_i_travel", s.can_i_travel("جنين", "الخليل"))
    assert "نص الطريق" not in ar and "10 كيلو" in ar and "40" in ar and "51" in ar, ar
    assert "most of the route" not in en and "10 km" in en and "40" in en, en


def test_f326_the_resolved_places_are_named_and_carried(fake):
    fake({"/v2/route/between": _between(_corr("likely_open", [_cp("زعترة", 0.5, age=9.0)]),
                                        origin="بيتونيا", o_place="بيت اونيا")})
    out = s.can_i_travel("بيتونيا", "نابلس")
    ar, en = both("can_i_travel", out)
    assert "بيت اونيا" in ar and "بيت اونيا" in en
    assert out["origin"]["place"] == "بيت اونيا" and out["destination"]["place"] == "نابلس"


def test_f535_a_sighting_on_the_route_is_spoken(fake):
    cps = [_cp("زعترة", 0.5, age=9.0, presence=[{"kind": "checkpoint_settlers",
                                                  "age_minutes": 20.0}])]
    cautions = [{"place": "زعترة", "seen": "checkpoint_settlers", "age_minutes": 20.0}]
    fake({"/v2/route/between": _between(_corr("likely_open", cps, cautions=cautions))})
    ar, en = both("can_i_travel", s.can_i_travel("رام الله", "نابلس"))
    assert "مستوطنين" in ar and "قبل 20 دقيقة" in ar, ar
    assert "settlers" in en and "20 min ago" in en, en


def test_f534_f060_waypoints_keep_the_destination_end_and_say_what_they_are(fake):
    passes = [{"name": f"بلدة{i}", "name_en": None, "along": i / 8 + 0.05,
               "km": 6.0 * i, "off_m": 100} for i in range(8)]
    fake({"/v2/route/between": _between(_corr("likely_open", [_cp("زعترة", 0.5, age=9.0)],
                                              passes=passes))})
    ar, en = both("can_i_travel", s.can_i_travel("رام الله", "نابلس"))
    assert "بلدة0" in ar and "بلدة7" in ar, ar
    assert "بلدة7" in en, en
    # the registry does not flag settlements: the list must not read as towns
    # a traveller can pass THROUGH
    assert "المستوطنات" in ar and "settlements" in en


def test_f253_english_says_when_no_route_was_computed(fake):
    fake({"/v2/route/between": {"routes": [], "best": None, "corridor_metres": 300,
                                "note": "n", "origin": {"query": "a", "place": "a", "place_id": 1},
                                "destination": {"query": "b", "place": "b", "place_id": 2}}})
    ar, en = both("can_i_travel", s.can_i_travel("a", "b"))
    assert "ما قدرت أحسب طريق" in ar
    assert "None" not in en and "0 of 0" not in en and "Could not compute" in en, en


def test_an_unplaceable_name_is_not_a_system_error(fake):
    fake({"/v2/route/between": _http_error(404)})
    ar, en = both("can_i_travel", s.can_i_travel("Ramalla", "نابلس"))
    assert "ما عرفت" in ar and "Ramalla" in ar, ar
    assert "None" not in en and "Ramalla" in en, en


# ═════════════════════════════════════════════════════════════════════════════
# checkpoints near / summary
# ═════════════════════════════════════════════════════════════════════════════

def test_f055_f496_nearby_checkpoints_carry_their_ages_and_sightings(fake):
    fake({"/v2/checkpoints/nearby": {
        "query": {}, "counts": {"in_radius": 3, "known": 2, "unknown": 1, "closed": 1,
                                "returned": 3},
        "results": [_near_row("حوارة", "open", 170, present=["idf"]),
                    _near_row("زعترة", "closed", 12),
                    _near_row("عورتا", "unknown", 400, last="open")],
        "attribution": "x"}})
    ar, en = both("checkpoints_near", s.checkpoints_near(lat=32.2, lon=35.25))
    assert "حوارة سالك (قبل 3 ساعات)" in ar and "زعترة مغلق (قبل 12 دقيقة)" in ar, ar
    assert "2h 50m ago" in en and "12 min ago" in en, en
    assert "army" in en, en


def test_f055_no_tracked_checkpoint_in_range_is_not_old_news(fake):
    fake({"/v2/checkpoints/nearby": {"query": {}, "counts": {"in_radius": 0, "known": 0,
                                                             "unknown": 0, "closed": 0,
                                                             "returned": 0},
                                     "results": [], "attribution": "x"}})
    ar, en = both("checkpoints_near", s.checkpoints_near(lat=32.2, lon=35.25))
    assert "0 حاجز" not in ar and "ما في ولا حاجز متابَع" in ar, ar
    assert "0 are in range" not in en and "No tracked checkpoint" in en, en


def test_f497_english_summary_names_a_shared_name_once(fake):
    closed = [{"place_id": i, "name": "النبي يونس", "name_en": None, "age_minutes": 5,
               "present": [], "lat": 31.6, "lon": 35.1, "closed_directions": ["both"]}
              for i in (1, 2)]
    fake({"/v2/checkpoints/summary": {"tracked": 10, "totals": {"closed": 2, "open": 3,
                                                                "unknown": 5},
                                      "known_fraction": 0.5, "presence": {},
                                      "closed_now": closed, "attribution": "x"}})
    ar, en = both("checkpoints_summary", s.checkpoints_summary())
    assert en.count("النبي يونس") == 1 and "shared" in en, en
    assert ar.count("النبي يونس") == 1


# ═════════════════════════════════════════════════════════════════════════════
# failure payloads in English (F048, F049, F257, F499, F500)
# ═════════════════════════════════════════════════════════════════════════════

def test_f048_f049_an_unresolved_place_is_not_a_quiet_road_in_english(fake):
    fake({"/v2/geo/resolve": {"found": False, "query": "Hawarra"}})
    for tool, fn in (("checkpoints_near", s.checkpoints_near),
                     ("incidents_near", s.incidents_near)):
        ar, en = both(tool, fn(place="Hawarra"))
        assert "Hawarra" in ar
        assert "None" not in en and "No recent" not in en and "No incidents" not in en, en
        assert "Hawarra" in en and "not recognised" in en, en


@pytest.mark.parametrize("tool", sorted(E.RENDERERS))
def test_no_renderer_prints_none_for_a_failure_payload(tool):
    for p in ({"answer": "ما عرفت وين Hawarra.", "error": "place not resolved"},
              {"answer": "ما عرفت وين Hawarra.", "error": "place not resolved",
               "query": "Hawarra"},
              {"answer": "ما عرفت وين Hawarra.", "found": False},
              {"answer": "ما عرفت وين Hawarra.", "found": False, "query": "Hawarra"}):
        en = E.add_english(tool, dict(p)).get("answer_en") or ""
        assert "None" not in en, (tool, p, en)


def test_f257_f500_f499_not_found_shapes_in_english(fake):
    fake({"/v2/geo/resolve": {"found": False, "query": "Ramalla"},
          "/v2/insights": Exception("404 Client Error: Not Found")})
    for tool, out in (("what_correlates_with", s.what_correlates_with("food.price.bread",
                                                                      place="Ramalla")),
                      ("insights", s.insights(place="Ramalla")),
                      ("databank", s.databank(category="Demolitions"))):
        ar, en = both(tool, out)
        assert en and "None" not in en, (tool, en)
        assert "comparable" not in en and "0 rows" not in en, (tool, en)


# ═════════════════════════════════════════════════════════════════════════════
# incidents
# ═════════════════════════════════════════════════════════════════════════════

def test_f056_a_twin_named_village_is_not_placed_in_the_city(fake):
    fake({"/v2/incidents/recent": {"incidents": [{
        "event_id": 1, "type": "raid", "place": "رام الله", "place_en": "Ramallah",
        "named_place": "المزرعة", "place_precision": "village_ambiguous",
        "occurred_at": _iso_ago(60), "independent_sources": 1}],
        "by_type": {"raid": 1}, "count": 1}})
    ar, en = both("incidents_near", s.incidents_near(lat=31.9, lon=35.2))
    assert "اقتحام في رام الله" not in ar and "المزرعة" in ar and "محافظة رام الله" in ar, ar
    assert "raid in Ramallah" not in en and "المزرعة" in en, en


def test_f256_an_empty_summary_window_is_stated_in_english(fake):
    fake({"/v2/incidents/summary": {"window_hours": 1, "total": 0, "by_type": {},
                                    "by_place": [], "located_to_governorate_only": 0}})
    ar, en = both("incidents_summary", s.incidents_summary(hours=1))
    assert "None" not in en and "1 hour" in en, en


def test_f498_every_weak_type_is_spoken():
    p = {"round": "8", "weak": [{"type": t, "precision": v} for t, v in
                                (("death", 0.6), ("siege", 0.6), ("demolition", 0.667),
                                 ("land_levelling", 0.667))]}
    assert "تجريف" in s._precision_ar(p)
    assert "land levelling" in E._precision_en(p)


def test_f261_insights_says_the_precision_of_the_types_it_counts(fake):
    fake({"/v2/insights": {
        "scope": {"name": "رام الله", "name_en": "Ramallah", "days": 30, "radius_km": 15},
        "checkpoints": {"readings": 10, "places_in_window": 3},
        "incidents": {"events": 7, "by_type": [
            {"type": "death", "events": 5, "corroborated": 2},
            {"type": "arrest", "events": 2, "corroborated": 2}]},
        "quality": {"incidents": {"state": "below gate", "precision": 0.767, "gate": 0.8}}}})
    ar, en = both("insights", s.insights(place="رام الله"))
    assert "60%" in ar, ar
    assert "death 60 %" in en, en


# ═════════════════════════════════════════════════════════════════════════════
# crossings, connectivity, fuel
# ═════════════════════════════════════════════════════════════════════════════

def test_f058_a_decayed_crossing_is_not_no_source(fake):
    fake({"/v2/crossings": {"crossings": [
        {"name": "جسر الملك حسين", "name_en": "King Hussein Bridge", "value": "unknown",
         "last_known_value": "open", "age_minutes": 840.0, "basis": "checkpoint_flow",
         "staleness_band": "live"},
        {"name": "رفح", "name_en": "Rafah", "value": "unknown", "last_known_value": None,
         "age_minutes": None, "basis": None, "staleness_band": None}],
        "total": 2, "with_a_current_reading": 0, "band_note": "b", "note": "n"}})
    out = s.crossings()
    ar, en = both("crossings", out)
    assert out.get("no_source") is not True
    assert "جسر الملك حسين" in ar and "آخر معلومة" in ar and "قبل 14 ساعة" in ar, ar
    assert "رفح" in ar
    assert "King Hussein Bridge" in en and "last known open" in en and "Rafah" in en, en
    assert "because no source reports crossing status" not in en, en


def test_f502_arabic_connectivity_never_asserts_normal_for_an_unknown_word(fake):
    for st in (None, "partial"):
        fake({"/v2/connectivity": {"status": st}})
        ar, en = both("connectivity_now", s.connectivity_now())
        assert "طبيعي" not in ar, (st, ar)


def test_f187_f255_f470_fuel_rows_never_confirmed_and_two_dates(fake):
    rows = [
        {"product": "kerosene", "name_ar": "كاز", "name_en": "Kerosene", "unit": "ILS/L",
         "status": "confirmed", "price": 5.0, "effective_from": "2026-09-01",
         "reported": [], "last_confirmed_price": 5.0, "last_confirmed_from": "2026-09-01"},
        {"product": "gasoline_95", "name_ar": "بنزين 95", "name_en": "Petrol 95",
         "unit": "ILS/L", "status": "confirmed", "price": 7.2,
         "effective_from": "2026-09-07", "reported": [],
         "last_confirmed_price": 7.2, "last_confirmed_from": "2026-09-07"},
        {"product": "gasoline_98", "name_ar": "بنزين 98", "name_en": "Petrol 98",
         "unit": "ILS/L", "status": "awaiting_list", "price": None,
         "effective_from": None, "reported": [], "last_confirmed_price": None,
         "last_confirmed_from": None},
        {"product": "diesel", "name_ar": "سولار", "name_en": "Diesel", "unit": "ILS/L",
         "status": "conflicting", "price": None, "effective_from": None,
         "reported": [{"price": 6.1}, {"price": 6.3}], "last_confirmed_price": 6.0,
         "last_confirmed_from": "2026-08-01"}]
    fake({"/v2/fuel/prices": {"scope": "x", "as_of_date": "2026-09-25", "prices": rows,
                              "attribution": "x"}})
    ar, en = both("fuel_prices", s.fuel_prices())
    assert "بنزين 98" in ar and "None" not in ar, ar
    assert "Petrol 98" in en and "None" not in en, en
    assert "2026-09-01" in en and "2026-09-07" in en, en
    assert "6.1" in en and "6.3" in en, en


# ═════════════════════════════════════════════════════════════════════════════
# databank, series, correlate, licences
# ═════════════════════════════════════════════════════════════════════════════

def _db_item(indicator, when, value, prec="day", attrs=None, place_ar=None):
    return {"indicator": indicator, "occurred_at": when, "occurred_precision": prec,
            "value_num": value, "value_text": None, "unit": "structures",
            "place_en": None, "place_ar": place_ar, "attrs": attrs or {}}


def test_f065_f260_the_page_span_is_not_called_the_series_and_english_says_the_figure(fake):
    items = [_db_item("demolitions.structures", f"2026-09-{d:02d}T00:00:00+00:00", 10.0 + d)
             for d in range(10, 0, -1)]
    fake({"/v2/databank/demolitions": {"category": "demolitions", "as_of": None,
                                       "count": 10, "items": items,
                                       "attribution": ["OCHA"]}})
    ar, en = both("databank", s.databank(category="demolitions"))
    assert "السلسلة من 2026 إلى 2026" not in ar, ar
    assert "rows from" not in en and "20" in en and "OCHA" in en, en


def test_f174_a_cumulative_row_is_not_dated_to_its_series_start(fake):
    item = _db_item("demolitions.locality.structures", "2009-01-01T00:00:00+00:00", 416.0,
                    prec="unknown", place_ar="القدس",
                    attrs={"coverage_start": "2009-01-01", "coverage_end": "2026-08-05",
                           "locality_name": "جبل المكبر"})
    fake({"/v2/databank/demolitions": {"category": "demolitions", "as_of": None,
                                       "count": 1, "items": [item], "attribution": ["OCHA"]}})
    ar, en = both("databank", s.databank(category="demolitions"))
    assert "في 2009-01-01" not in ar and "2026-08-05" in ar and "جبل المكبر" in ar, ar
    assert "2026-08-05" in en and "cumulative" in en, en


def test_f064_f305_series_days_is_applied_as_a_window(fake):
    pts = [{"at": f"2026-{m:02d}-01", "value": 10 + m} for m in range(1, 10)]
    f = fake({"/v2/databank/compare": {"series": [{"points": pts}, {"points": pts}],
                                       "overlap": {}}})
    target, args = F.route("series", {"indicators": "food.price.bread", "days": 30})
    out = s.TOOLS[target][0](**args)
    assert f.params("/v2/databank/compare")[0].get("frm") == \
        (date.today() - timedelta(days=30)).isoformat()
    ar, en = both(target, out)
    assert "30 يوم" in ar and "30 days" in en, (ar, en)
    # and with no window asked for, the whole series is compared — said as such
    target, args = F.route("series", {"indicators": "food.price.bread"})
    s.TOOLS[target][0](**args)
    assert "frm" not in f.params("/v2/databank/compare")[-1]


def test_f505_f258_correlate_answers_in_arabic_and_english_keeps_the_lag(fake):
    fake({"/v2/databank/correlate": {
        "refused": False, "a": "x.a", "b": "x.b", "method": "spearman", "rho": 0.71,
        "n": 14, "lag_days": 3, "ci95": [0.2, 0.9],
        "plain_english": "a strong same-direction association (rho = +0.71)",
        "caveats": ["Correlation is not causation.", "n = 14. Below about 30…",
                    "a lag of 3 period(s) was applied. …"]},
        "/v2/databank/indicators": {"indicators": [{"indicator": "food.price.bread"}]}})
    ar, en = both("correlate", s.correlate(a="x.a", b="x.b", max_lag=30))
    assert re.search(r"[؀-ۿ]", ar) and not ar.startswith("a strong"), ar
    assert "3" in ar
    assert "lag" in en and "3" in en and "n = 14" in en, en
    ar, en = both("correlate", s.correlate(search="bread"))
    assert re.search(r"[؀-ۿ]", ar.split("food.price.bread")[0]), ar


def test_f259_an_unmatched_licence_filter_is_not_zero_republishable_rows(fake):
    fake({"/v2/databank/licenses": {"licenses": [{"source_key": "wfp", "source_name": "WFP",
                                                  "share_alike": False, "commercial_use": True,
                                                  "verified_on": "2026-01-01"}],
                                    "tiers": {"open": 10, "commercial_permissive": 5,
                                              "commercial_sharealike": 2},
                                    "permissions_pending": []}})
    ar, en = both("licenses", s.licenses(source="btselem"))
    assert re.search(r"[؀-ۿ]", ar), ar
    assert "0 rows are republishable" not in en and "btselem" in en, en


def test_f456_the_licences_description_carries_no_stale_count():
    assert "6,562" not in s.TOOLS["licenses"][1]
    assert "6,562" not in (s.licenses.__doc__ or "")


# ═════════════════════════════════════════════════════════════════════════════
# about, gaps, history
# ═════════════════════════════════════════════════════════════════════════════

def test_f269_about_counts_the_servable_checkpoints(fake):
    fake({"/v2/coverage": {"total_claims": 1000, "sources": [{"newest": "2026-09-25"}],
                           "live_states": {"checkpoint_flow": 95}, "fields": [],
                           "places": {"checkpoint": 359}},
          "/v2/databank/radar": {"counts": {"datasets": 5, "fresh": 3, "late": 1,
                                            "stalled": 1, "dead_upstream": 0},
                                 "gaps": [], "measured_at": "x"},
          "/v2/databank/scout": {"swept_at": "x", "candidates": []},
          "/v2/stream/status": {"running": True, "watched_states": 10},
          "/v2/databank/categories": {"datasets": [{"category": "a", "rows": 5}]},
          "/v2/checkpoints/summary": {"tracked": 272, "totals": {"open": 60, "unknown": 177,
                                                                 "closed": 35}}})
    ar, en = both("about", s.about())
    assert "272" in ar and "359" not in ar, ar
    assert "272" in en and "359" not in en, en


def test_f501_english_names_the_worst_day_and_the_top_gaps(fake):
    series = [{"day": "2026-09-20", "kinds": {"checkpoint_flow": {"values": {"closed": 4,
                                                                             "open": 1},
                                                                  "units": 2}}},
              {"day": "2026-09-21", "kinds": {"checkpoint_flow": {"values": {"open": 3},
                                                                  "units": 1}}}]
    fake({"/v2/geo/resolve": CHECKPOINT,
          "/v2/history/place": {"place_id": 200, "days": 7, "series": series},
          "/v2/databank/radar": {"counts": {"datasets": 5, "fresh": 3, "late": 1,
                                            "stalled": 1, "dead_upstream": 0},
                                 "gaps": [{"severity": 4, "subject": "prices.wfp",
                                           "measure": "no rows since 2026-05"}],
                                 "measured_at": "x"},
          "/v2/databank/scout": {"swept_at": "x", "candidates": [{"title": "HDX prices"}]}})
    ar, en = both("place_history", s.place_history("حوارة", days=7))
    assert "2026-09-20" in ar and "2026-09-20" in en, en
    ar, en = both("data_gaps", s.data_gaps())
    assert "prices.wfp" in en and "HDX prices" in en, en


# ═════════════════════════════════════════════════════════════════════════════
# the words themselves
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("m,want", [
    (0, "قبل أقل من دقيقة"), (-3, "قبل أقل من دقيقة"), (1, "قبل دقيقة"),
    (2, "قبل دقيقتين"), (5, "قبل 5 دقايق"), (12, "قبل 12 دقيقة"), (60, "قبل ساعة"),
    (90, "قبل ساعة ونص"), (119, "قبل ساعتين"), (170, "قبل 3 ساعات"),
    (840, "قبل 14 ساعة"), (1440, "قبل يوم"), (2880, "قبل يومين"), (7200, "قبل 5 أيام")])
def test_f504_f461_arabic_ages_agree_with_their_number_and_never_go_negative(m, want):
    assert s._age_ar(m) == want


@pytest.mark.parametrize("m,want", [(-3, "just now"), (5, "5 min ago"), (119, "1h 59m ago"),
                                    (180, "3h ago"), (840, "14h ago"), (2880, "2d ago")])
def test_f461_english_ages_do_not_halve_a_two_hour_reading(m, want):
    assert E._age(m) == want


def test_f262_a_renderer_that_raises_leaves_a_trace(monkeypatch, caplog):
    def broken(d):
        raise KeyError("renamed_field")
    monkeypatch.setitem(E.RENDERERS, "checkpoint_status", broken)
    with caplog.at_level(logging.WARNING, logger="serve.mcp_en"):
        out = E.add_english("checkpoint_status", {"answer": "x"})
    assert "answer_en" not in out
    assert any("checkpoint_status" in r.getMessage() for r in caplog.records)


# ═════════════════════════════════════════════════════════════════════════════
# the façade: arguments honoured and clamped
# ═════════════════════════════════════════════════════════════════════════════

def test_f050_news_search_keeps_place_and_kind_and_newest_keeps_hours(fake):
    assert F.route("news", {"text": "قلنديا", "place": "رام الله", "kind": "roads",
                            "hours": 6}) == \
        ("search", {"text": "قلنديا", "area": "رام الله", "kind": "roads", "hours": 6})
    assert F.route("news", {"hours": 6, "place": "نابلس"}) == \
        ("latest_news", {"area": "نابلس", "hours": 6})
    bulletin = {"text": s.ROAD_BULLETIN + " قلنديا سالك", "source": "palhub",
                "source_key": "palhub", "reported_at": _iso_ago(5)}
    news = {"text": "قلنديا: اقتحام", "source": "wafa", "source_key": "wafa",
            "reported_at": _iso_ago(9)}
    f = fake({"/v2/news/latest": {"count": 2, "items": [bulletin, news]}})
    target, args = F.route("news", {"text": "قلنديا", "place": "رام الله", "kind": "roads"})
    out = s.TOOLS[target][0](**args)
    assert f.params("/v2/news/latest")[-1].get("area") == "رام الله"
    assert [i["source_key"] for i in out["items"]] == ["palhub"]
    target, args = F.route("news", {"hours": 6})
    s.TOOLS[target][0](**args)
    assert f.params("/v2/news/latest")[-1].get("hours") == 6
    # the declared default of 8 is what a bare text search returns
    many = {"count": 30, "items": [{**news, "text": f"قلنديا {i}"} for i in range(30)]}
    fake({"/v2/news/latest": many})
    target, args = F.route("news", {"text": "قلنديا"})
    assert s.TOOLS[target][0](**args)["count"] == 8


# (public name, arguments) -> the REST caps in serve/app.py the request must fit
CAPS = [
    ("news", {"limit": 30}, "/v2/news/latest", {"limit": (1, 100)}),
    ("news", {"text": "قلنديا", "limit": 40, "hours": 5000}, "/v2/news/latest",
     {"limit": (1, 100), "hours": (1, 720)}),
    ("place", {"place": "نابلس", "view": "pattern", "days": 3}, "/v2/patterns/place",
     {"days": (7, 365)}),
    ("place", {"place": "نابلس", "view": "history", "days": 900}, "/v2/history/place",
     {"days": (1, 365)}),
    ("incidents", {"place": "نابلس", "hours": 200, "limit": 500, "radius_km": 900},
     "/v2/incidents/recent", {"hours": (1, 168), "limit": (1, 200), "radius_km": (0, 200)}),
    ("incidents", {"hours": 500}, "/v2/incidents/summary", {"hours": (1, 168)}),
    ("checkpoints", {"place": "نابلس", "limit": 60, "radius_km": 500},
     "/v2/checkpoints/nearby", {"limit": (1, 50), "radius_km": (0, 100)}),
    ("insights", {"place": "نابلس", "days": 400, "radius_km": 100}, "/v2/insights",
     {"days": (1, 365), "radius_km": (0, 60)}),
    ("insights", {"scope": "governorates", "days": 900}, "/v2/history/area",
     {"days": (1, 365)}),
]


@pytest.mark.parametrize("name,args,path,caps", CAPS)
def test_f057_f304_facade_arguments_are_clamped_to_what_the_api_accepts(fake, name, args,
                                                                         path, caps):
    geo = {"found": True, "query": "نابلس", "place_id": 5, "name": "نابلس", "kind": "locality",
           "lat": 32.22, "lon": 35.26}
    f = fake({"/v2/news/latest": {"count": 0, "items": []}, "/v2/geo/resolve": geo,
              "/v2/patterns/place": {"hours": [], "timezone": "Asia/Hebron", "note": "n"},
              "/v2/history/place": {"series": []}, "/v2/history/area": {"governorates": {}},
              "/v2/incidents/recent": {"incidents": [], "by_type": {}, "count": 0},
              "/v2/incidents/summary": {"window_hours": 168, "by_type": {}, "by_place": []},
              "/v2/checkpoints/nearby": {"counts": {}, "results": []},
              "/v2/insights": {"scope": {"name": "نابلس", "days": 365, "radius_km": 60},
                               "checkpoints": {}, "incidents": {}, "quality": {}}})
    target, targs = F.route(name, args)
    s.TOOLS[target][0](**targs)
    sent = f.params(path)
    assert sent, f.calls
    for k, (lo, hi) in caps.items():
        assert lo <= sent[-1][k] <= hi, (k, sent[-1])


def test_f057_the_facade_schemas_declare_the_bounds():
    props = {n: F.FACADES[n]["schema"]["properties"] for n in F.FACADES}
    assert props["news"]["limit"]["maximum"] <= 100
    assert props["news"]["hours"]["maximum"] == 720
    assert props["incidents"]["hours"]["maximum"] == 168
    assert props["checkpoints"]["limit"]["maximum"] == 50
    assert props["insights"]["days"]["maximum"] == 365
    assert props["place"]["days"]["maximum"] == 365


# ═════════════════════════════════════════════════════════════════════════════
# the stdio transport
# ═════════════════════════════════════════════════════════════════════════════

def _stdio(monkeypatch, *msgs) -> list[dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\n"))
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    s.main()
    return [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]


def test_f270_f457_stdio_answers_ping_sends_the_reading_contract_and_flags_errors(fake,
                                                                                  monkeypatch):
    fake({"/v2/coverage": _http_error(500)})
    init, ping, call = _stdio(
        monkeypatch,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "coverage", "arguments": {}}})
    assert "Do not rephrase" in init["result"]["instructions"]
    assert ping == {"jsonrpc": "2.0", "id": 2, "result": {}}
    assert call["result"]["isError"] is True
