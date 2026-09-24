"""Headlines that say something (P0-A.2/4, 2026-09-24).

The first-time walk found sentences that were true and empty — "5 rows from
demolitions", "history of 7 days across 12 governorates", "the stream is
running", "Jericho rest stop: open" while every Gaza crossing had no source at
all. These tests hold each headline to naming a datum, an age where there is
one, and the same facts in both languages.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import mcp_en as E                                     # noqa: E402
from serve import mcp_http as m                                   # noqa: E402
from serve import mcp_server as s                                 # noqa: E402

DIGITS = re.compile(r"\d")


def call(tool, tier="partner", **args):
    return m._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": tool, "arguments": args}}, None, tier)


def payload(reply):
    return json.loads(reply["result"]["content"][0]["text"])


def test_every_public_tool_has_an_english_renderer():
    missing = [n for n in s.TOOLS if n not in s.HOST_ONLY and n not in E.RENDERERS]
    assert not missing, missing


def test_databank_category_headline_is_the_latest_figure_not_a_row_count():
    p = payload(call("databank", category="demolitions", limit=5))
    assert p.get("count")
    assert "سجلاً من demolitions" not in p["answer"]
    assert "آخر الأرقام" in p["answer"] and DIGITS.search(p["answer"])
    assert p.get("latest_by_indicator")
    assert DIGITS.search(p["answer_en"])


def test_crossings_headline_names_what_has_no_source():
    p = payload(call("crossings"))
    if p.get("no_source_for"):
        assert "ما في ولا مصدر" in p["answer"]
        assert "NO source" in p["answer_en"]
        assert p["no_source_for"][0] in p["answer"]
    else:
        assert p.get("no_source") or p.get("with_a_current_reading")


def test_satellite_fire_pixels_travel_apart_from_incidents():
    p = payload(call("incidents", hours=168))
    assert "fire_detection" not in (p.get("by_type") or {})
    assert "fires" in p and "note" in p["fires"]
    p = payload(call("incidents", place="رام الله", hours=168))
    assert all(i.get("type") != "fire_detection" for i in p.get("incidents") or [])
    assert "fires" in p


def test_incident_channels_are_source_names_not_unit_ids():
    p = payload(call("incidents", place="رام الله", hours=168, limit=20))
    for i in p.get("incidents") or []:
        for ch in i.get("channels") or []:
            assert not re.fullmatch(r"src:\d+", ch), ch


def test_place_history_headline_carries_the_totals():
    p = payload(call("place", place="حوارة", view="history", days=7))
    if p.get("series"):
        assert DIGITS.search(p["answer"]) and "تقرير" in p["answer"]
        assert DIGITS.search(p["answer_en"])
    assert "تاريخ 7 يوم." not in p["answer"]


def test_area_history_ranks_governorates_and_drops_retired_kinds():
    p = payload(call("insights", scope="governorates", days=7))
    assert p.get("ranked_by_closed_share")
    assert "الأكثر إغلاقاً" in p["answer"] and "Most closures" in p["answer_en"]
    for g in p["governorates"].values():
        assert not ({"fuel_diesel", "fuel_gasoline"} & set((g.get("kinds") or {})))


def test_news_leaves_road_tables_out_unless_asked_and_collapses_reposts():
    p = payload(call("news", limit=5))
    assert all(not str(i["text"]).startswith(s.ROAD_BULLETIN) for i in p["items"])
    assert "أحدثها" in p["answer"] and DIGITS.search(p["answer"])
    keys = [(i["source_key"], " ".join(i["text"].split())[:80]) for i in p["items"]]
    assert len(keys) == len(set(keys))
    r = payload(call("news", limit=3, kind="roads"))
    assert all(str(i["text"]).startswith(s.ROAD_BULLETIN) for i in r["items"])
    q = payload(call("news", text="قلنديا", hours=24, limit=5))
    keys = [(i["source_key"], " ".join(i["text"].split())[:80]) for i in q["items"]]
    assert len(keys) == len(set(keys))


def test_stream_headline_says_how_much_is_watched():
    p = payload(call("about", section="stream"))
    if p.get("running"):
        assert DIGITS.search(p["answer"]) and "watched" in p["answer_en"]


def test_match_scores_never_exceed_one():
    p = payload(call("checkpoint_status", name="عين سينيا"))
    if p.get("match") and p["match"].get("score") is not None:
        assert p["match"]["score"] <= 1.0


def test_english_carries_the_fuzzy_doubt_the_arabic_carries():
    d = {"found": True, "name": "عورتا", "flow": "open", "age_minutes": 7,
         "direction": "both", "match": {"resolved_to": "عورتا", "score": 0.707},
         "present": [], "by_direction": {}}
    en = E.checkpoint_status(d)
    assert en.startswith("Not sure about the name")


def test_english_says_the_direction_split():
    d = {"found": True, "name": "قلنديا", "flow": "open", "age_minutes": 3, "direction": "both",
         "match": {"score": 1.0}, "present": [],
         "by_direction": {"inbound": {"flow": "open"}, "outbound": {"flow": "closed"}}}
    assert "inbound" in E.checkpoint_status(d) and "outbound" in E.checkpoint_status(d)


def test_trend_english_never_prints_none():
    assert "None" not in E.trend({"answer": "x", "n": 3})
    assert "None" not in E.trend({"indicator": "a", "recent_mean": 1.0, "baseline_median": 2.0,
                                  "change_pct": -50, "last": "2021-12-01", "last_age_days": 900})
    assert "stopped" in E.trend({"indicator": "a", "recent_mean": 1.0, "baseline_median": 2.0,
                                 "change_pct": -50, "last": "2021-12-01", "last_age_days": 900})


def test_weather_english_speaks_about_the_filtered_governorate():
    d = {"governorates": [{"governorate": "Hebron", "advisory": "normal", "temp_now_c": 22.4,
                           "today": {"max_c": 27.2}}], "notable": []}
    assert E.weather_now(d).startswith("Hebron:")
