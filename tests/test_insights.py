"""The insights reduction, and the two things it must never do.

It was built for a partner's own example question ("give me quick insights
about checkpoint status last month around Ramallah"), so these tests hold the
parts a partner will check: the grain is the canonical one, the numbers are
sample-sized, and nothing is asserted that the data does not carry.
"""
import json
import pytest
from fastapi.testclient import TestClient

from serve.app import app

client = TestClient(app)


def _ins(place="رام الله", **kw):
    r = client.get("/v2/insights", params={"place": place, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_ramallah_last_month_answers_in_one_call():
    d = _ins(days=30, radius_km=15)
    ck = d["checkpoints"]
    assert d["scope"]["name_en"] == "Ramallah"
    assert ck["places"] > 5 and ck["readings"] > 1000
    assert set(ck["over_window"]) <= {"open", "closed", "congested", "slow"}, \
        "flow words only: presence words in this histogram mean the wrong grain"
    assert ck["most_reported"] and ck["most_reported"][0]["readings"] > 0
    assert ck["busiest_hours_hebron"], "the hour rhythm is the part a person asks for"
    assert d["incidents"]["events"] >= 0


def test_it_reads_the_canonical_grain_not_the_legacy_mixed_kind():
    """`checkpoint_status` carries `idf` and `police` in the same value column
    as `open`. Counting it produced a histogram with two axes in it; the fix is
    the grain, and this is the test that keeps it."""
    d = _ins(days=7, radius_km=10)
    for value in d["checkpoints"]["over_window"]:
        assert value in ("open", "closed", "congested", "slow", "unknown")
    for value in d["checkpoints"]["now"]:
        assert value in ("open", "closed", "congested", "slow", "unknown")


def test_presence_is_a_separate_axis_and_never_merged_into_flow():
    d = _ins(days=30, radius_km=15)
    p = d["checkpoints"]["presence"]
    assert isinstance(p, dict)
    for axis in p:
        assert axis in ("army", "inspection", "police", "settlers")
    assert "idf" not in d["checkpoints"]["over_window"]


def test_every_subject_carries_its_sample_size_and_its_measured_precision():
    d = _ins(days=30, radius_km=15)
    q = d["quality"]
    assert q["checkpoints"]["n"] > 0 and 0 < q["checkpoints"]["precision"] <= 1
    inc = q["incidents"]
    assert inc["n"] > 0 and inc["gate"] == 0.80
    assert inc["state"] in ("below gate", "passing")
    assert inc["state"] == ("passing" if inc["precision"] >= 0.80 else "below gate")


def test_the_caveats_travel_with_the_answer():
    d = _ins(days=30, radius_km=15)
    joined = " ".join(d["caveats"])
    assert "not an official count" in joined
    assert "NOT `open`" in joined
    assert "sighted" in joined, "presence must say what an empty block means"


def test_absent_place_is_a_404_not_an_empty_month():
    r = client.get("/v2/insights", params={"place": "ززززززز"})
    assert r.status_code == 404


def test_radius_and_window_are_bounded():
    assert client.get("/v2/insights",
                      params={"place": "رام الله", "radius_km": 500}).status_code == 422
    assert client.get("/v2/insights",
                      params={"place": "رام الله", "days": 900}).status_code == 422


def test_the_mcp_tool_answers_the_partner_question_the_way_a_model_reads_it():
    from serve.mcp_server import TOOLS
    fn = TOOLS["insights"][0]
    out = fn(place="رام الله", days=30)
    assert out["answer"].startswith("آخر 30 يوم")
    assert "ما في معلومة" in out["answer"]
    assert out["quality"]["incidents"]["state"] == "below gate"


def test_english_renderer_exists_for_the_new_tool():
    from serve.mcp_en import RENDERERS, add_english
    assert "insights" in RENDERERS, "a public tool without an English rendering"
    out = add_english("insights", {"answer": "س", "scope": {"name": "Ramallah", "days": 30,
                                                     "radius_km": 15},
                                   "checkpoints": {"readings": 10, "places": 2},
                                   "incidents": {}, "quality": {}})
    assert out["answer_en"] and "Ramallah" in out["answer_en"]
