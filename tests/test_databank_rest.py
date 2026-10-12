"""The rest of the databank's defects from the 2026-10-11 audit (finding 08 and
plan H), fixed on 2026-10-12/13. One section per defect; each test says in its
name the thing a reader of an answer would have got wrong."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import licence                                                    # noqa: E402

FILTERED = {"grade": "share-alike", "partner_tier": "filtered"}


# ── the partner tier is a commercial one ─────────────────────────────────────
# Measured 2026-10-12: 22,140 served rows are licensed for non-commercial use
# only and graded attribution or share-alike (WHO 12,577, UCDP 7,638, OONI
# 1,376, IMF 474, the UNRWA camp rows 75). The partner filter asked for the
# grade alone, so every one of them travelled in a partner payload.

def _who_row(**over):
    return {"indicator": "health.x", "source_key": "who", "redistribution": "share-alike",
            "commercial_use": False, "value_num": 1.0} | over


def test_a_non_commercial_row_stays_out_of_a_partner_payload_and_the_cut_says_why():
    out = {"answer": "x", "answer_en": "x", "count": 3, "items": [
        _who_row(), _who_row(),
        {"indicator": "economic.y", "source_key": "worldbank",
         "redistribution": "attribution", "commercial_use": True}]}
    got = licence.apply("databank", out, "partner", FILTERED)
    assert [it["source_key"] for it in got["items"]] == ["worldbank"]
    w = got["licence"]["withheld"]
    assert w["rows"] == 2 and w["non_commercial_rows"] == 2
    assert w["by_source"] == {"who (share-alike, non-commercial)": 2}
    assert "non-commercial use only" in got["answer_en"]
    assert "الاستخدام التجاري" in got["answer"]
    assert got["count"] == 1


def test_a_non_commercial_series_keeps_its_summary_and_loses_its_points():
    out = {"answer": "x", "answer_en": "x", "series": [
        {"indicator": "connectivity.ooni", "redistribution": "share-alike",
         "commercial_use": False, "sources": ["OONI"],
         "points": [{"at": "2026-10-01", "value": 1}] * 7, "n": 7},
        {"indicator": "economic.y", "redistribution": "attribution",
         "commercial_use": True, "sources": ["World Bank"],
         "points": [{"at": "2020-01-01", "value": 1}] * 4, "n": 4}]}
    got = licence.apply("compare", out, "partner", FILTERED)
    ooni, wb = got["series"]
    assert ooni["points"] == [] and ooni["points_withheld"] == 7 and ooni["n"] == 7
    assert len(wb["points"]) == 4
    assert got["licence"]["withheld"]["non_commercial_rows"] == 7


def test_the_house_keeps_every_non_commercial_row():
    out = {"items": [_who_row(), _who_row()], "count": 2}
    got = licence.apply("databank", out, "house", FILTERED)
    assert len(got["items"]) == 2 and "withheld" not in got["licence"]


def test_a_row_that_does_not_say_is_judged_on_its_grade_as_before():
    # the live tier's rows and older payloads carry no flag at all
    assert licence.partner_may_carry("attribution", None) is None
    assert licence.partner_may_carry("ask", None) == "grade"
    assert licence.partner_may_carry("share-alike", False) == "non-commercial"
    assert licence.partner_may_carry("no-redistribution", False) == "grade"
    assert licence.partner_may_carry("open", True) is None


def test_the_mixed_cut_names_both_reasons():
    out = {"answer": "x", "answer_en": "x", "items": [
        _who_row(),
        {"indicator": "casualties.annual_total", "source_key": "ocha_casualties",
         "redistribution": "no-redistribution", "commercial_use": False}]}
    got = licence.apply("databank", out, "partner", FILTERED)
    assert got["items"] == []
    assert got["licence"]["withheld"]["rows"] == 2
    assert got["licence"]["withheld"]["non_commercial_rows"] == 1
    assert "redistribution or commercial use" in got["answer_en"]


def test_the_routes_hand_the_flag_to_the_licence_layer():
    src = (ROOT / "serve" / "app.py").read_text()
    assert "COALESCE(d.commercial_use, s.commercial_use)     AS commercial_use" in src
    assert '"license_spdx", "redistribution", "commercial_use")' in src
    assert '"commercial_use": commercial_use,' in src
    assert licence.table(lambda *a, **k: [], set())["partner_requires_commercial_use"] is True


# ── when a row is about ──────────────────────────────────────────────────────
# "5,304 persons in 2008-01-01" was OCHA's count of people killed in Gaza
# between 2008 and 2023; "1 schools in 2026-08-05" was a register row whose
# only date is the day v1 downloaded it.

from serve.when import when_ar, when_en                                      # noqa: E402

GAZA_TOTAL = {"indicator": "casualties.region.gaza_strip", "value_num": 5304.0,
              "occurred_at": "2008-01-01T00:00:00Z", "occurred_precision": "unknown",
              "attrs": {"coverage_start": "2008-01-01", "coverage_end": "2023-09-19"}}
SCHOOL = {"indicator": "education.school_record", "value_num": 1.0,
          "occurred_at": "2026-08-05T00:00:00Z", "occurred_precision": "unknown", "attrs": {}}


def test_a_period_total_names_both_ends_of_its_period():
    assert when_en(GAZA_TOTAL) == "between 2008-01-01 and 2023-09-19 (one total for the period)"
    assert "من 2008-01-01 لغاية 2023-09-19" in when_ar(GAZA_TOTAL)
    assert "2008-01-01" not in when_en(GAZA_TOTAL).split("between")[0]


def test_a_register_row_is_never_dated_by_the_day_it_was_fetched():
    assert "2026-08-05" not in when_en(SCHOOL) and "2026-08-05" not in when_ar(SCHOOL)
    assert when_en(SCHOOL) == "with no date given by the source"
    dated = SCHOOL | {"dataset_vintage": "2023-07-25"}
    assert when_en(dated) == "in the publisher's register of 2023-07-25"
    assert "2023-07-25" in when_ar(dated)


def test_a_dated_row_is_said_at_its_own_precision_and_no_finer():
    row = {"occurred_at": "2024-01-01T00:00:00Z", "attrs": {}}
    assert when_en(row | {"occurred_precision": "year"}) == "in 2024"
    assert when_en(row | {"occurred_precision": "month"}) == "in 2024-01"
    assert when_en(row | {"occurred_precision": "day"}) == "on 2024-01-01"
    assert when_ar(row | {"occurred_precision": "year"}) == "سنة 2024"


def test_the_english_databank_answer_uses_it():
    from serve import mcp_en
    said = mcp_en.databank({"category": "casualties", "count": 1,
                            "latest_by_indicator": [GAZA_TOTAL | {"unit": "persons"}]})
    assert "between 2008-01-01 and 2023-09-19" in said and "in 2008-01-01" not in said


def test_a_period_total_is_never_differenced_into_a_flow():
    sql = (ROOT / "db" / "migrations" /
           "104_flows_and_freshness_count_what_is_there.sql").read_text()
    assert "v.occurred_precision <> 'unknown'" in sql
    assert "FILTER (WHERE upper_inf(o.sys_period))" in sql and "FROM event e" in sql


# ── correlate: four things the audit found ───────────────────────────────────
from serve import correlate as C                                             # noqa: E402


def _s(ind, kind="flow", grain="day", place="region", concept="x", **over):
    return {"indicator": ind, "measure_kind": kind, "grain": grain, "place_grain": place,
            "concept_key": concept, "points": [], "source_names": {"p"}} | over


def test_the_advice_to_difference_a_running_total_can_be_followed():
    a, b = _s("a.cumulative", "cumulative", concept="a"), _s("b.daily", concept="b")
    assert any("CUMULATIVE" in r for r in C.check_comparable(a, b))
    assert C.check_comparable(a, b, "diff") == []


def test_a_running_totals_downward_correction_is_not_a_negative_flow():
    s = _s("a.cumulative", "cumulative", points=[
        {"at": i, "value": v, "prec": "day"} for i, v in enumerate([10, 15, 14, 20])])
    d = C.differenced(s)
    assert [p["value"] for p in d["points"]] == [5.0, 6.0] and d["revisions_left_out"] == 1
    said = C.caveats(d, _s("b", concept="b"), [(1, 1, 0, "day", "day")] * 40, 0)
    assert any("running total" in c and "1 downward correction" in c for c in said)


def test_a_daily_series_and_a_yearly_one_are_refused_as_a_pair():
    stop = C.check_comparable(_s("a", concept="a"), _s("b", grain="year", concept="b"))
    assert len(stop) == 1 and "time grains differ" in stop[0] and "daily" in stop[0]
    assert "الدقة الزمنية مختلفة" in C.reason_ar(stop[0])


def test_one_label_holding_two_units_is_refused():
    milk = _s("food.milk", concept="a", unit_mixed=True, units=["ILS_per_kg", "ILS_per_litre"])
    stop = C.check_comparable(milk, _s("b", concept="b"))
    assert len(stop) == 1 and "more than one unit (ILS_per_kg, ILS_per_litre)" in stop[0]
    assert "أكثر من وحدة" in C.reason_ar(stop[0])


def test_two_publishers_of_one_figure_are_not_pooled():
    from serve.app import _one_source
    pts = ([{"at": i, "source_key": "hamoked"} for i in range(192)]
           + [{"at": i, "source_key": "addameer"} for i in range(50)])
    kept, used, others = _one_source(pts, None)
    assert used == "hamoked" and len(kept) == 192 and others == {"addameer": 50}
    kept, used, others = _one_source(pts, "addameer")
    assert used == "addameer" and len(kept) == 50 and others == {"hamoked": 192}
    one = [{"at": 1, "source_key": "who"}] * 3
    assert _one_source(one, None) == (one, None, {})


def test_a_lag_is_an_order_in_time_and_the_answer_says_so():
    a, b = _s("raids", concept="a"), _s("closures", concept="b")
    said = C.caveats(a, b, [(1, 1, 0, "day", "day")] * 40, 7, shifts=29)
    assert any("raids moving before closures is an order in time, not a cause" in c for c in said)
    assert any("29 shifts were tried" in c for c in said)
    from serve import mcp_en
    en = mcp_en.correlate({"plain_english": "a weak association", "n": 40, "ci95": [0.0, 0.4],
                           "lag_days": 7, "caveats": said})
    assert "order in time, not a cause" in en and "at a lag of 7 days" in en


def test_the_interval_widens_with_the_number_of_shifts_tried():
    one, many = C.fisher_ci(0.5, 40, C.z_for_shifts(1)), C.fisher_ci(0.5, 40, C.z_for_shifts(29))
    assert abs(C.z_for_shifts(1) - 1.96) < 0.001
    assert many[0] < one[0] and many[1] > one[1]


def test_the_mcp_tool_can_ask_for_the_differenced_series():
    from serve import mcp_facades, mcp_server
    import inspect
    assert "detrend" in inspect.signature(mcp_server.correlate).parameters
    assert '"detrend": {"type": "string", "enum": ["none", "diff"]' in \
        (ROOT / "serve" / "mcp_facades.py").read_text()
    assert mcp_facades is not None
