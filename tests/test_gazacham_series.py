"""Trucks into Gaza by week from the Gaza Chamber of Commerce's reports
(ops/build_gazacham_series.py, db/mappings/aid_gazacham.yaml), 2026-10-14.

Offline: the reports here are cut to the lines the builder reads, in the
layouts the real reports use (a one-week Total row; two-week Subtotal rows,
one of them the publisher's own arithmetic slip of weeks 82-83; the looted
sentence of weeks 51-61; a file linked for one week that is another week's).
"""
from __future__ import annotations

import yaml
import pytest

from ingest.databank import load_spec
from ops import build_gazacham_series as B

ONE_WEEK = {"weeks": [9], "start": "2024-09-25", "date": "2024-09-30T00:00:00", "title": "Weekly Report (9)",
            "link": "https://gazacham.ps/x9",
            "text": "Day Date KAS Erez Total\n 1 Wednesday 25/09/2024 100 33 133\n  Total   500   133   633\n"
                    "  Total 6 78 14 1 11 24 499 633\n"}
TWO_WEEKS = {"weeks": [82, 83], "start": "2026-02-16", "date": "2026-03-01T00:00:00", "title": "Weekly Report 82 - 83",
             "link": "https://gazacham.ps/x82",
             "text": "  1 Monday 16/2/2026 228 32 0 260\n"
                     "           Subtotal 1 (Week 82)               1,404      260       14      1,749\n"
                     "           Subtotal 2 (Week 83)               1,128      246        0      1,374\n"
                     "           Total                              2,532      506       14      3,052\n"
                     "           Subtotal 1 (Week 82)          976         702       1,678\n"
                     "           Subtotal 2 (Week 83)          663         711       1,374\n"}
LOOTED = {"weeks": [60, 61], "start": "2025-09-15", "date": "2025-09-28T00:00:00", "title": "Weekly Report 60-61",
          "link": "https://gazacham.ps/x60",
          "text": "Table 15/09/2025\n  Subtotal 1 (Week 60)   400  214  614\n  Subtotal 2 (Week 61)   300  142  442\n"
                  "  Total   700  356  1,056\n"
                  "• In Week 60 (September 15 – 21, 2025), 614 trucks arrived (282 looted, 332 delivered), while in "
                  "Week 61 (September 22-28, 2025) 442 trucks arrived (219 looted, 223 delivered).\n"}
ELSEWHERE = {"weeks": [6], "start": "2024-09-05", "date": "2024-09-11T00:00:00", "title": "Weekly Report (6)",
             "link": "https://gazacham.ps/x6", "text": "1 Thursday 12/09/2024 0 150 150\n  Total 0 150 655 805\n"}


def fig(records, week, measure):
    return next((r["value"] for r in records if r["week"] == week and r["measure"] == measure), None)


def test_each_kind_of_report_gives_its_weeks():
    recs, notes = B.build([ONE_WEEK, TWO_WEEKS, LOOTED], {"weeks": {}})
    assert fig(recs, 9, "trucks_entered") == 633
    assert fig(recs, 82, "trucks_entered") == 1678 and fig(recs, 83, "trucks_entered") == 1374
    assert notes["publisher_rows_that_do_not_add_up"] == ["week 82: a Subtotal row prints 1,749 where its columns make 1,678"]
    assert (fig(recs, 60, "trucks_looted"), fig(recs, 60, "trucks_delivered")) == (282, 332)
    assert (fig(recs, 61, "trucks_looted"), fig(recs, 61, "trucks_delivered")) == (219, 223)
    r82 = next(r for r in recs if r["week"] == 82)
    assert (r82["period_start"], r82["period_end"], r82["date"]) == ("2026-02-16", "2026-02-22", "2026-02-16")
    assert r82["sources"][0]["name"] == B.SOURCE_NAME and r82["location"] == {"region": "Gaza Strip"}
    assert r82["stable_id"] == "gazacham:week082:trucks_entered"


def test_a_file_dated_in_another_week_gives_no_figure():
    recs, notes = B.build([ELSEWHERE], {"weeks": {}})
    assert recs == [] and notes["reports_whose_tables_are_another_period"][0]["weeks"] == [6]


def test_weeks_that_do_not_add_up_or_contradict_are_refused():
    bad = dict(TWO_WEEKS, text=TWO_WEEKS["text"].replace("3,052", "3,999"))
    with pytest.raises(B.Refused):
        B.build([bad], {"weeks": {}})
    wrong = dict(LOOTED, text=LOOTED["text"].replace("282 looted", "283 looted"))
    with pytest.raises(B.Refused):                                  # 283 + 332 is not 614
        B.build([wrong], {"weeks": {}})
    with pytest.raises(B.Refused):                                  # by hand may not contradict a table
        B.build([ONE_WEEK], {"weeks": {9: {"trucks_entered": 600, "quote": "x"}}})


def test_the_weeks_read_by_hand_each_stand_on_a_sentence():
    hand = yaml.safe_load(B.BY_HAND.read_text(encoding="utf-8"))["weeks"]
    assert sorted(hand) == [*range(32, 42), *range(43, 51), 55]     # 42 states no figure for its week
    for w, row in hand.items():
        assert row["quote"] and "trucks_entered" in row, w
        if "trucks_delivered" in row:
            assert row["trucks_looted"] + row["trucks_delivered"] == row["trucks_entered"], w
    assert all(hand[w]["trucks_entered"] == 0 for w in range(32, 42))  # the closure of 2 March 2025


def test_the_dataset_is_held_for_the_house_and_names_its_weeks():
    spec = load_spec("aid_gazacham")
    assert spec["datasets"] == [{"key": "gazacham_trucks_weekly", "source": "gaza_chamber"}]
    rules = {r["when"]["equals"]: r for r in spec["registry"]["rules"]}
    assert set(rules) == {"aid_gazacham.trucks_entered", "aid_gazacham.trucks_looted", "aid_gazacham.trucks_delivered"}
    assert all("week beginning" in r["name_en"] and "الأسبوع الذي يبدأ" in r["name_ar"] for r in rules.values())
    sql = (B.ROOT / "db" / "migrations" / "117_gaza_chamber_source.sql").read_text()
    assert "'no-redistribution'" in sql and "commercial_use" in sql and "جميع الحقوق محفوظة" in sql
