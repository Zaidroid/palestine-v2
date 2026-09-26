"""P0-C.3 — incident answers carry what the last round measured."""
from serve import quality


def _file():
    """The latest hand-scored round, read the way a reader would (round 9 on
    2026-09-26 replaced the round-8 numbers these tests used to pin)."""
    import json
    return json.loads(quality.FILE.read_text())


def _types(r):
    return r.get("per_type") or r.get("types") or {}


def test_latest_round_is_read_not_asserted():
    q, r = quality.incident_precision(), _file()
    assert q and q["round"] == str(r["round"])
    assert q["measured_version"] == r["classifier_version"]
    death = _types(r).get("death") or {}
    if death.get("precision") is not None:
        assert q["per_type"]["death"]["precision"] == death["precision"]
    below = q["overall"]["precision"] < quality.GATE_OVERALL
    assert (q["gate"]["state"] == "below gate") == below


def test_a_serving_version_that_was_not_measured_says_so():
    q = quality.incident_precision()
    if q["serving_version"] != q["measured_version"]:
        assert "unmeasured" in q["note"]


def test_counts_are_annotated_and_unmeasured_types_say_so():
    q = quality.incident_precision()
    bt = quality.annotate_by_type({"death": {"n": 3, "corroborated": 1}, "fire_detection": {"n": 2}})
    assert bt["death"]["precision"]["value"] == q["per_type"]["death"]["precision"]
    assert bt["death"]["precision"]["round"] == q["round"]
    assert bt["fire_detection"]["precision"]["value"] is None


def test_weak_types_come_deaths_first():
    q = quality.incident_precision()
    asked = {"raid": {"n": 5}, "siege": {"n": 2}, "death": {"n": 1}, "arrest": {"n": 4}}
    weak = quality.weak_types(asked)
    per = q["per_type"]
    expect = sorted((t for t in asked if per.get(t, {}).get("precision") is not None
                     and per[t]["precision"] < quality.GATE_OVERALL),
                    key=lambda t: (per[t]["precision"], 0 if t == "death" else 1, t))
    assert [w["type"] for w in weak] == expect
    assert all(w["precision"] < quality.GATE_OVERALL for w in weak)
    # deaths first among equals: the ordering rule itself, independent of a round
    if per.get("death", {}).get("precision") is not None and weak:
        assert weak[0]["precision"] <= per["death"]["precision"]


def test_the_answer_says_it_in_both_languages():
    from serve.mcp_server import _precision_ar
    from serve.mcp_en import _precision_en
    p = quality.summary({"death": {"n": 1}, "raid": {"n": 3}})
    assert "الوفيات" in _precision_ar(p) or "استشهاد" in _precision_ar(p) or "60%" in _precision_ar(p)
    death = next((w for w in p["weak"] if w["type"] == "death"), None)
    if death:
        assert f"death {round(death['precision'] * 100)} %" in _precision_en(p)
    assert f"round {p['round']}" in _precision_en(p)
