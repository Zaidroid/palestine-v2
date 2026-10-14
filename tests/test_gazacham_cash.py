"""The cash-out commission in Gaza from the Gaza Chamber of Commerce's reports
(ops/build_gazacham_cash.py, db/mappings/cash_gazacham.yaml), 2026-10-14.

Offline: reports cut to the commission tables in the layouts the real ones
use, including the copied block of late June / early July 2025 (two reports
printing the same days differently) and a month given before it ended.
"""
from __future__ import annotations

from ingest.databank import load_spec
from ops import build_gazacham_cash as C

R48 = {"weeks": [48], "start": "2025-06-17", "date": "2025-06-23T00:00:00", "link": "https://gazacham.ps/x?slug=r48",
       "text": """
           Table (9): weekly cash out commission from 19/01/2025 to 07/06/2025.
          Week                 From                 To           cash out commission (%)
         Week 01            19/01/2025          25/01/2025                  17%
         Week 02            26/01/2025          01/02/2025                  16%
                  Table (10): Daly cash out commission from 17/06/2025 to 30/06/2025.
  1                      17/06/2025                                       45%
  2                      24/06/2025                                       45%
  3                      26/06/2025                                       42%
"""}
R49 = {"weeks": [49], "start": "2025-06-24", "date": "2025-06-30T00:00:00", "link": "https://gazacham.ps/x?slug=r49",
       "text": """
         Week 01            19/01/2025          25/01/2025                  17%
  1                      24/06/2025                                       41%
  2                      26/06/2025                                       42%
"""}
R50 = {"weeks": [50], "start": "2025-07-08", "date": "2025-07-14T00:00:00", "link": "https://gazacham.ps/x?slug=r50",
       "text": """
 Table (9): Monthly cash out commission rate (January – July 2025).
  Jan-25      19/01/2025      31/01/2025      17%
  Jun-25      01/06/2025      30/06/2025      42%
  July-25     01/07/2025      21/07/2025      40%
"""}
R76 = {"weeks": [76, 77], "start": "2026-01-05", "date": "2026-01-18T00:00:00", "link": "https://gazacham.ps/x?slug=r76",
       "text": """
                   Table (9): Monthly cash out commission rate (November 2025 to January 2026).
                 Nov- Dec- Jan-
  Month
                  25     25     26
 cash out
commission 17%            14%         14%
   (%)
"""}


def by(recs, measure):
    return {r["date"]: r for r in recs if r["measure"] == measure}


def test_weeks_days_and_months_are_read():
    recs, notes = C.build([R48, R49, R50, R76])
    w = by(recs, "cashout_commission_weekly")
    assert w["2025-01-19"]["value"] == 17.0 and w["2025-01-19"]["period_end"] == "2025-01-25"
    assert w["2025-01-19"]["commission_week"] == 1 and w["2025-01-26"]["value"] == 16.0
    d = by(recs, "cashout_commission_daily")
    assert d["2025-06-17"]["value"] == 45.0 and d["2025-06-26"]["value"] == 42.0   # printed the same twice: held
    m = by(recs, "cashout_commission_monthly")
    assert m["2025-01-01"]["value"] == 17.0 and m["2025-01-01"]["measured_from"] == "2025-01-19"
    assert m["2025-06-01"]["precision"] == "month" and m["2025-06-01"]["period_end"] == "2025-06-30"
    assert m["2025-11-01"]["value"] == 17.0 and m["2025-12-01"]["value"] == 14.0
    assert all(r["unit"] == "percent" and r["location"] == {"region": "Gaza Strip"} for r in recs)


def test_a_day_two_reports_print_differently_is_held_from_neither():
    recs, notes = C.build([R48, R49])
    assert "2025-06-24" not in by(recs, "cashout_commission_daily")
    assert notes["days_printed_differently"] and "neither is held" in notes["days_printed_differently"][0]


def test_a_month_given_before_it_ended_is_not_held():
    recs, notes = C.build([R50, R76])
    m = by(recs, "cashout_commission_monthly")
    assert "2025-07-01" not in m and "2026-01-01" not in m           # to 21 July; January 2026 in a report to 18 January
    assert len(notes["months_not_whole"]) == 2


def test_the_spec_names_the_three_series():
    spec = load_spec("cash_gazacham")
    assert spec["datasets"] == [{"key": "gazacham_cash", "source": "gaza_chamber"}]
    rules = {r["when"]["equals"]: r for r in spec["registry"]["rules"]}
    assert set(rules) == {f"cash_gazacham.cashout_commission_{g}" for g in ("daily", "weekly", "monthly")}
    assert all(r["name_ar"] and r["serve_warning_ar"] and r["canonical_unit"] == "percent" for r in rules.values())
