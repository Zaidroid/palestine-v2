"""F-12 — the Gaza series served from T4P, and the cross-check behind it."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.databank import GAZA_CUTOVER, Drop, t_conflict_gaza  # noqa: E402
from ops.gaza_crosscheck import classify  # noqa: E402

PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2}}


def _t(day, k, i, source="mohtel", **kw):
    return {"report_date": day, "killed_cum": k, "injured_cum": i,
            "report_source": source, **kw}


def test_the_series_starts_the_day_after_the_frozen_value():
    """2026-08-08 is served by v1_conflict_tech4palestine; serving it again
    under a second dataset would put the day in the databank twice."""
    assert GAZA_CUTOVER == "2026-08-09"
    out = t_conflict_gaza(_t("2026-08-08", 73384, 174242), {}, PLACES, Counter())
    assert isinstance(out, Drop) and out.reason == "before_cutover"
    rows = t_conflict_gaza(_t("2026-08-09", 73386, 174250), {}, PLACES, Counter())
    assert [(r.indicator, r.value_num) for r in rows] == [
        ("conflict.gaza_cumulative_killed", 73386),
        ("conflict.gaza_cumulative_injured", 174250)]
    assert {r.occurred_at for r in rows} == {"2026-08-09"} and rows[0].place_id == 1


def test_a_value_t4p_filled_by_arithmetic_is_not_served():
    """2026-09-13: no bulletin that day, T4P filled 73,784 by subtracting the
    next bulletin's 24 h line; the bulletin itself says 73,786."""
    out = t_conflict_gaza(_t("2026-09-13", 73784, 174746, source="missing"), {}, PLACES, Counter())
    assert isinstance(out, Drop) and out.reason == "t4p_inferred"


def test_a_day_with_no_totals_is_a_gap_not_a_zero():
    out = t_conflict_gaza(_t("2026-09-18", None, None, source="missing"), {}, PLACES, Counter())
    assert isinstance(out, Drop) and out.reason == "no_cumulative"


def _m(k, i, cid=1):
    return {"cum_killed": k, "cum_injured": i, "claim_id": cid}


def test_agreement_and_disagreement_are_told_apart():
    k = classify({"2026-09-01": _m(10, 20), "2026-09-02": _m(11, 21)}, {},
                 {"2026-09-01": _t("2026-09-01", 10, 20), "2026-09-02": _t("2026-09-02", 11, 22)},
                 "2026-08-09")
    assert [r["date"] for r in k["agree"]] == ["2026-09-01"]
    assert [r["date"] for r in k["disagree"]] == ["2026-09-02"]


def test_one_bulletin_filed_under_two_dates_is_not_a_disagreement():
    """Claim 98669: posted 2026-09-14, dated 13 Sep in its own text; T4P
    files the same two numbers under the 14th."""
    k = classify({"2026-09-13": _m(73786, 174771, 98669)}, {},
                 {"2026-09-14": _t("2026-09-14", 73786, 174771)}, "2026-08-09")
    assert not k["disagree"] and not k["t4p_only"] and not k["ministry_only"]
    assert k["dated_differently"] == [{"bulletin_date": "2026-09-13", "t4p_date": "2026-09-14",
                                       "totals": [73786, 174771], "claim_id": 98669}]


def test_only_the_rows_the_databank_serves_are_compared():
    """A T4P fill ("missing") is not served, so it is not checked either."""
    k = classify({"2026-09-13": _m(73786, 174771)}, {},
                 {"2026-09-13": _t("2026-09-13", 73784, 174746, source="missing")}, "2026-08-09")
    assert not k["disagree"] and [r["date"] for r in k["ministry_only"]] == ["2026-09-13"]
