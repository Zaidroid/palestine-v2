"""P0-C.3 — incident answers carry what the last round measured."""
from serve import quality


def test_latest_round_is_read_not_asserted():
    q = quality.incident_precision()
    assert q and q["round"] == "8" and q["measured_version"] == "1.8.0"
    assert q["overall"]["precision"] == 0.767 and q["per_type"]["death"]["precision"] == 0.6
    assert q["gate"]["state"] == "below gate"


def test_a_serving_version_that_was_not_measured_says_so():
    q = quality.incident_precision()
    if q["serving_version"] != q["measured_version"]:
        assert "unmeasured" in q["note"]


def test_counts_are_annotated_and_unmeasured_types_say_so():
    bt = quality.annotate_by_type({"death": {"n": 3, "corroborated": 1}, "fire_detection": {"n": 2}})
    assert bt["death"]["precision"]["value"] == 0.6 and bt["death"]["precision"]["round"] == "8"
    assert bt["fire_detection"]["precision"]["value"] is None


def test_weak_types_come_deaths_first():
    weak = quality.weak_types({"raid": {"n": 5}, "siege": {"n": 2}, "death": {"n": 1}, "arrest": {"n": 4}})
    assert [w["type"] for w in weak][:2] == ["death", "siege"]
    assert all(w["precision"] < 0.8 for w in weak) and "arrest" not in [w["type"] for w in weak]


def test_the_answer_says_it_in_both_languages():
    from serve.mcp_server import _precision_ar
    from serve.mcp_en import _precision_en
    p = quality.summary({"death": {"n": 1}, "raid": {"n": 3}})
    assert "الوفيات" in _precision_ar(p) or "استشهاد" in _precision_ar(p) or "60%" in _precision_ar(p)
    assert "death 60 %" in _precision_en(p) and "round 8" in _precision_en(p)
