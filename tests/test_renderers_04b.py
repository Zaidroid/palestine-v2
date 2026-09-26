"""Audit 2026-09-25, area 04 — the tasks left open after the cloud's pass
(RENDERERS-07 14 16 21/24 22 23 25 26 28 29). Offline: `api()` is a fixture."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from serve import mcp_en, mcp_facades as F, mcp_server as s          # noqa: E402

AGE_EN = re.compile(r"\d+(\s?min|h|d) ago")


class Capture:
    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, path, **kw):
        self.calls.append((path, kw))
        v = self.table.get(path, {})
        if isinstance(v, Exception):
            raise v
        return v


def _news_items():
    return {"items": [{"text": s.ROAD_BULLETIN + " table", "source": "a", "reported_at": None},
                      {"text": "خبر عادي", "source": "b", "reported_at": None}]}


def test_renderers_07_news_search_keeps_place_kind_and_hours(monkeypatch):
    cap = Capture({"/v2/news/latest": _news_items()})
    monkeypatch.setattr(s, "api", cap)
    target, args = F.route("news", {"text": "قلنديا", "place": "رام الله", "kind": "roads",
                                    "hours": 6, "limit": 5})
    assert target == "search" and args["area"] == "رام الله" and args["kind"] == "roads"
    out = s.search(**args)
    _, kw = cap.calls[-1]
    assert kw["area"] == "رام الله" and kw["hours"] == 6
    assert all(i["text"].startswith(s.ROAD_BULLETIN) for i in out["items"])
    # newest mode: hours reaches the API too, and the declared default is 8
    target, args = F.route("news", {"hours": 6})
    assert target == "latest_news"
    s.latest_news(**args)
    assert cap.calls[-1][1]["hours"] == 6
    assert F.FACADES["news"]["schema"]["properties"]["limit"]["default"] == 8
    import inspect
    assert inspect.signature(s.search).parameters["limit"].default == 8


def test_renderers_14_out_of_range_arguments_are_clamped_not_422(monkeypatch):
    cap = Capture({"/v2/news/latest": {"items": []},
                   "/v2/incidents/recent": {"found": True, "events": [], "count": 0},
                   "/v2/geo/resolve": {"found": True, "place_id": 1, "name": "حوارة",
                                       "lat": 32.0, "lon": 35.0},
                   "/v2/patterns/place": {"found": True, "hours": [], "n": 0}})
    monkeypatch.setattr(s, "api", cap)
    s.latest_news(limit=30)
    assert cap.calls[-1][1]["limit"] <= 100
    s.incidents_near(lat=32.0, lon=35.0, hours=200)
    assert cap.calls[-1][1]["hours"] == 168
    try:
        s.place_pattern("حوارة", days=3)
    except (KeyError, TypeError):
        pass                                   # the fake payload is thin; the call is what matters
    pat = [kw for path, kw in cap.calls if path == "/v2/patterns/place"]
    assert pat and pat[-1]["days"] == 7
    for name, key in (("news", "limit"), ("incidents", "hours"), ("place", "days"), ("series", "days")):
        prop = F.FACADES[name]["schema"]["properties"][key]
        assert "minimum" in prop and "maximum" in prop, (name, key)


def _route_payload():
    cps = [{"name": "حوارة", "name_en": "Huwara", "flow": "closed", "age_minutes": 30,
            "along": 0.5, "independent_sources": 1},
           {"name": "زعترة", "name_en": "Za'tara", "flow": "open", "age_minutes": 80,
            "along": 0.7, "independent_sources": 1}]
    r = {"verdict": "blocked", "duration_minutes": 50, "distance_km": 40, "blocked_at": ["حوارة"],
         "slow_at": [], "unreported": [], "cautions": [], "known": 2, "checkpoints_on_route": 2,
         "checkpoints": cps, "coverage": {}, "passes": [], "near_misses": [], "exit_closures": [],
         "doubts": [], "oldest_known_minutes": 80}
    return {"routes": [r]}


def test_renderers_16_route_speaks_the_age_of_its_evidence(monkeypatch):
    monkeypatch.setattr(s, "api", lambda *a, **k: _route_payload())
    out = s.can_i_travel("رام الله", "نابلس")
    ar = out["answer"]
    assert "مسكّر عند حوارة (قبل 30 دقيقة)" in ar, ar
    # the short answer (2026-09-26) gives EVERY named checkpoint its own age
    # instead of one "newest reading" clause
    assert "زعترة سالك (قبل ساعة)" in ar, ar
    assert out["freshest_reading_minutes"] == 30
    assert not re.search(r"[a-z_]{4,}", ar), ar          # no Latin verdict token
    en = mcp_en.can_i_travel(out)
    assert "blocked at Huwara (" in en and "Za'tara open (1h ago)" in en and AGE_EN.search(en), en


def test_renderers_21_24_series_days_is_applied_and_spoken(monkeypatch):
    pts = [{"at": f"2026-0{m}-01", "value": v} for m, v in
           zip(range(1, 8), (10, 11, 12, 10, 20, 21, 22))]
    cap = Capture({"/v2/databank/compare": {"series": [{"points": pts}]}})
    monkeypatch.setattr(s, "api", cap)
    out = s.trend("food.price.bread", days=30)
    path, kw = cap.calls[-1]
    assert path == "/v2/databank/compare" and "frm" in kw and len(kw["frm"]) == 10
    assert out["window_days"] == 30 and "خلال آخر 30 يوم" in out["answer"]
    assert "over the last 30 days" in mcp_en.trend(out)


def test_renderers_22_databank_span_is_the_series_not_the_page(monkeypatch):
    items = [{"indicator": "demolitions.structures", "value_num": 678.0, "unit": "structures",
              "occurred_at": f"2026-0{i}-01", "occurred_precision": "month"} for i in range(1, 10)]
    cap = Capture({"/v2/databank/demolitions": {"items": items, "count": 9, "category": "demolitions",
                                                 "attribution": ["OCHA"]},
                   "/v2/databank/indicators": {"indicators": [
                       {"indicator": "demolitions.structures", "from_date": "2009-01-01",
                        "to_date": "2026-09-01", "rows_served": 210}]}})
    monkeypatch.setattr(s, "api", cap)
    out = s.databank(category="demolitions")
    assert "السلسلة من 2009 إلى 2026" in out["answer"], out["answer"]
    assert "أحدث 9 سجلات" in out["answer"]
    assert out["series_span"]["demolitions.structures"]["from"] == "2009-01-01"
    en = mcp_en.databank(out)
    assert "2009→2026" in en and "678" in en and "rows from" not in en, en


def test_renderers_23_api_calls_are_bounded_and_about_degrades_to_partial(monkeypatch):
    seen = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {}
    def fake_get(url, params=None, timeout=None):
        seen["t"] = timeout
        return R()
    monkeypatch.setattr(s.httpx, "get", fake_get)
    s.api("/v2/health")
    assert seen["t"] == s.API_TIMEOUT and s.API_TIMEOUT <= 10
    monkeypatch.setattr(s, "coverage", lambda: {"total_claims": 1, "sources": [], "fields": [],
                                                "places": {"checkpoint": 359}})
    monkeypatch.setattr(s, "data_gaps", lambda: (_ for _ in ()).throw(RuntimeError("radar down")))
    monkeypatch.setattr(s, "stream_info", lambda: {"running": True})
    monkeypatch.setattr(s, "checkpoints_summary", lambda: {"tracked": 272, "known_fraction": 0.35})
    monkeypatch.setattr(s, "api", lambda *a, **k: {"datasets": []})
    out = s.about()
    assert out["name"] == "Palestine Data — live + databank" and out["partial"] == ["gaps"]


def test_renderers_25_about_counts_servable_checkpoints_and_says_both_facts(monkeypatch):
    monkeypatch.setattr(s, "coverage", lambda: {"total_claims": 1, "sources": [], "fields": [],
                                                "places": {"checkpoint": 359}})
    monkeypatch.setattr(s, "data_gaps", lambda: {"gaps": [], "counts": {}})
    monkeypatch.setattr(s, "stream_info", lambda: {"running": True})
    monkeypatch.setattr(s, "checkpoints_summary", lambda: {"tracked": 272, "known_fraction": 0.35})
    monkeypatch.setattr(s, "api", lambda *a, **k: {"datasets": []})
    out = s.about()
    assert "272 حاجز متابَع، 95 منها عليها قراءة حالية" in out["answer"], out["answer"]
    assert out["live"]["checkpoints_tracked"] == 272
    assert out["live"]["checkpoints_with_current_reading"] == 95
    assert "359" not in out["answer"]


def test_renderers_26_stdio_uses_the_http_dispatcher():
    ping = s.handle_stdio({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert ping["result"] == {}
    init = s.handle_stdio({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})
    assert "instructions" in init["result"] and init["result"]["serverInfo"]["name"] == "palestine-data"
    tl = s.handle_stdio({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    names = {t["name"] for t in tl["result"]["tools"]}
    assert set(F.LISTED) <= names and s.HOST_ONLY <= names          # the host lists its own tools
    assert all("outputSchema" in t for t in tl["result"]["tools"])
    assert s.handle_stdio({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_renderers_28_arabic_ages_are_counted_the_way_they_are_said():
    assert s._age_ar(1) == "قبل دقيقة"
    assert s._age_ar(2) == "قبل دقيقتين"
    assert s._age_ar(5) == "قبل 5 دقايق"
    assert s._age_ar(15) == "قبل 15 دقيقة"
    assert s._age_ar(120) == "قبل ساعتين"
    assert s._age_ar(3 * 60) == "قبل 3 ساعات"
    assert s._age_ar(3 * 1440) == "قبل 3 أيام"
    assert s._age_ar(-3) == "الآن"                    # clock skew is not a fact
    assert s._age_ar(None) == "غير معروف"


def test_renderers_29_correlate_answers_in_arabic(monkeypatch):
    cap = Capture({"/v2/databank/correlate": {"rho": 0.82, "n": 40, "lag_days": 0, "ci95": [0.7, 0.9],
                                              "plain_english": "a and b move together"},
                   "/v2/databank/indicators": {"indicators": [{"indicator": "x.y"}]}})
    monkeypatch.setattr(s, "api", cap)
    pair = s.correlate(a="a", b="b")
    assert "الارتباط بين a وb قوي بنفس الاتجاه" in pair["answer"], pair["answer"]
    assert "move together" not in pair["answer"]
    found = s.correlate(search="x")
    assert "سلسلة مطابقة" in found["answer"] and "series matched" not in found["answer"]
    assert "series matched “x”: x.y" in mcp_en.correlate(found)
