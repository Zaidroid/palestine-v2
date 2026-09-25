"""The two testers' round of 2026-09-25 (Fawwaz through the partner door,
Claude web through the connector), pinned. Each test is one reported defect;
the name says what a reader was told before the fix.

Needs main-server (the MCP dispatcher calls the dev or live API over HTTP).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import correlate as C                                           # noqa: E402
from serve.mcp_en import effective_groups, share_words                     # noqa: E402

LATIN_SENTENCE = re.compile(r"\b[a-z]+ [a-z]+ [a-z]+ [a-z]+\b")   # four English words in a row


def test_databank_indicator_without_category_reaches_its_rows(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("databank", indicator="prisoners.child"))
    assert p.get("category") == "prisoners"
    assert "prisoners.child" in p["answer"] and "prisoners.child" in p["answer_en"]
    assert "categories" not in p                     # not the overview


def test_databank_as_of_without_category_is_said_not_dropped(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("databank", as_of="2026-09-01"))
    assert (p.get("ignored") or {}).get("as_of")
    assert "as_of" in p["answer"] and "as_of" in p["answer_en"]


def test_databank_overview_says_the_same_in_both_languages(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("databank"))
    top = sorted(p["categories"].items(), key=lambda kv: -kv[1])[:6]
    for k, _ in top:
        assert k in p["answer"] and k in p["answer_en"]
    assert "مصدراً" not in p["answer"]                 # datasets are not sources
    n = str(p["datasets_with_rows"])
    assert n in p["answer"] and n in p["answer_en"]


def test_english_answers_use_english_names(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("checkpoints", place="نابلس"))
    named = [c for c in p["checkpoints"] if c.get("name_en") and c["flow"] != "unknown"][:4]
    assert named, "no English-named checkpoint around Nablus to test with"
    for c in named:
        assert c["name"] not in p["answer_en"] or c["name"] == c["name_en"]
    assert "نابلس" not in p["answer_en"]
    s = mcp_payload(mcp_call("checkpoints"))
    for c in (s.get("closed_now") or [])[:6]:
        if c.get("name_en"):
            assert c["name"] not in s["answer_en"]


def test_refusals_are_arabic_inside_arabic(mcp_call, mcp_payload):
    for args in ({"a": "prisoners.total", "b": "prisoners.administrative"},
                 {"a": "prisoners.total", "b": "food.price.bread"},
                 {"a": "no.such.series", "b": "prisoners.total"}):
        p = mcp_payload(mcp_call("correlate", **args))
        assert p.get("refused")
        assert not LATIN_SENTENCE.search(p["answer"]), p["answer"]
    scan = mcp_payload(mcp_call("correlate", indicator="prisoners.total"))
    assert not LATIN_SENTENCE.search(scan["answer"]), scan["answer"]


def test_every_refusal_shape_has_an_arabic_rendering():
    samples = [
        "no series named 'x.y' — search /v2/databank/indicators?q= to find the right string.",
        "x.y exists but has no points at place_id 5 in the requested window.",
        "x.y: nobody has established what KIND of number this is",
        "x.y is CUMULATIVE — a running total.",
        "x.y is categorical (status); a correlation",
        "place grains differ: a.b is region-grade and c.d is governorate-grade. A",
        "both series are mortality.conflict. Two measures of one concept",
        "both series rise with time over the window (monotony 0.91 and 0.88)",
        "nothing else held is comparable to a.b: no other series shares its place grain (region) with enough points.",
    ]
    for r in samples:
        assert C.reason_ar(r) != "مرفوض — السبب مفصّل في `reasons`", r
    assert "mortality.conflict" in C.reason_ar(samples[6])


def test_fuel_dates_are_the_same_groups_in_both_languages(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("fuel_prices"))
    for d, _ in effective_groups(p["prices"]):
        assert d in p["answer"] and d in p["answer_en"]


def test_licence_for_one_source_names_that_source(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("licence", scope="sources", source="ioda"))
    assert "IODA" in p["answer"] and "IODA" in p["answer_en"]


@pytest.mark.parametrize("area", ["أريحا", "اريحا", "Jericho"])
def test_crossings_area_in_either_script(mcp_call, mcp_payload, area):
    p = mcp_payload(mcp_call("crossings", place=area))
    names = {c["name_en"] for c in p["crossings"]}
    assert any("Allenby" in (n or "") for n in names), names


def test_crossings_area_that_matches_nothing_is_not_no_source(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("crossings", place="Nowhere"))
    assert p.get("no_match") and not p.get("no_source")


def test_about_does_not_deny_the_bridge(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("about"))
    assert "crossing_status" not in p["live"]["no_source"]
    assert "crossing_status" not in p["answer"] and "crossing_status" not in p["answer_en"]


def test_huwara_in_english_reaches_the_checkpoint_everywhere(mcp_call, mcp_payload):
    for view in ("history", "pattern"):
        p = mcp_payload(mcp_call("place", place="Huwara", view=view))
        assert p.get("found") is not False, (view, p.get("answer_en"))
        assert "not found" not in p["answer_en"].lower()
    loc = mcp_payload(mcp_call("place", place="Huwara", view="locate"))
    assert loc.get("also_checkpoint")


def test_series_with_a_city_reads_its_governorate(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("series", indicators="food.price.bread", place="الخليل"))
    assert p.get("n", 0) > 0
    assert (p.get("place_used") or {}).get("kind") == "governorate"


def test_duplicate_dates_counts_dates_not_rows():
    s = {"points": [{"at": d} for d in ["a", "a", "a", "b", "c", "c"]]}
    assert C.duplicate_dates(s) == (2, 3)


def test_zero_tests_is_not_one_false_positive(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("correlate", indicator="prisoners.total"))
    if p.get("tested") == 0:
        assert "No test was run" in p["multiple_comparisons"]


def test_insights_speak_ages_not_minute_counts(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("insights", place="جنين", days=7))
    assert not re.search(r"\d{3,} ?(دقيقة|minutes)", p["answer"] + p["answer_en"])


def test_route_blind_stretch_is_the_same_size_in_both_languages(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("can_i_travel", origin="رام الله", destination="نابلس"))
    blind = next((x for x in p.get("doubts") or [] if x.get("kind") == "blind_stretch"), None)
    if blind is None:
        pytest.skip("no blind stretch on this route right now")
    ar, en = share_words(blind.get("share"))
    assert ar in p["answer"] and en in p["answer_en"]


def test_signals_agreeing_counts_signals(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("connectivity_now"))
    if p.get("status") in (None, "unknown"):
        pytest.skip("no measurement")
    assert p.get("signals_total") == 3
    assert 0 <= p["signals_agreeing"] <= 3


def test_checkpoint_status_takes_place_like_every_other_tool(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("checkpoint_status", place="حوارة"))
    assert p.get("flow") and p.get("answer") and p.get("answer_en")


def test_bad_arguments_answer_in_both_languages(mcp_call):
    import json
    r = mcp_call("checkpoint_status", bogus=1)
    p = json.loads(r["result"]["content"][0]["text"])
    assert p.get("answer") and p.get("answer_en") and "name" in p["answer_en"]
