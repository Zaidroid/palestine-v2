"""Prices in Gaza's markets from the Gaza Chamber of Commerce's reports
(ops/build_gazacham_prices.py, db/mappings/price_gazacham.yaml), 2026-10-14.

Offline: the reports here are cut to the tables the builder reads, in the
layouts the real reports use: a one-week report with a pre-war table, a
previous-week table that prints the same week's price otherwise (as week 39
does) and the index's basket; a two-week report with the minus sign printed
after the number; NA in place of a price; a row whose percent does not say
what its prices say; and the index by day, by its own weeks and by month.
"""
from __future__ import annotations

import json

import yaml

from ingest.databank import load_spec
from ops import build_gazacham_prices as P

ONE_WEEK = {"weeks": [39], "start": "2025-04-22", "date": "2025-04-28T00:00:00", "title": "x", "link": "https://gazacham.ps/x39",
            "text": """
 Table (1): comparing current prices with the normal prices before the war.
                                   Pre-war    Price Average
    #             Item            Unit         Prices    (current week)    to the Pre-war prices
    1            Garlic            Kg          10.00         272.00                 2,620%
    9             Flour       Sack (25Kg)      35.00         341.43                  876%
   15       Frozen veal            Kg          20.00           NA                     NA
 Table (3): comparing current prices of basic non-food items with pre-war prices.
   #               Item                 Unit       Prices      (current week)   Vs. Pre-war prices)
   3      Dishwashing liquid            Liter           6.00             35.00            483%
   4        Baby diapers           Pack (40 pcs)        29.00            85.00            193%
   5               Soap                 Piece           0.50             4.46              79%
 Table (4): comparing current prices of basic non-food items with the previous week prices.
  #               Item                Unit             (previous                (current           week Vs.
  5        Dishwashing liquid         Liter                37.86                 38.57                2%
 Table (5): Basic consumer goods included in the index and their quantities.
  #                          Item                             Unit               Quantity
  4                         Flour                              Kg                 12.65
"""}
TWO_WEEKS = {"weeks": [80, 81], "start": "2026-02-02", "date": "2026-02-15T00:00:00", "title": "x", "link": "https://gazacham.ps/x80",
             "text": """
                                                Pre-              Week 80                   Week 81        % Change
#              Item               Unit                                                                       (Week 81
            1          Flour       Sack (25Kg)      35       15.86       55%-      23.86     32%-     50%
            2          Onion       Kg               2        6.86        243%      5.71      186%     -17%
            3          firewood    Kg               0        6           1100%     5.79      1057%    -4%
             #                         Date                   Basket value (ILS)       Index value (%)
             1                      Aug - 25                        1,344                   1,454%
             2               Sep - 26 (up to 13)                    191                     206%
             3                      Mar - 26                        341                     365%
#               Date                   Basket value (ILS)                     index value (%)
1           02/02/2026                    138                       150%
2           03/02/2026                  2,342.25                  2,534%
    Week14           31/01/2025      06/02/2025                 154.06                    167%
"""}


def by(records, measure, week=None, date=None):
    return [r for r in records if r["measure"] == measure and (week is None or r.get("week") == week)
            and (date is None or r["date"] == date)]


def test_the_prewar_table_is_held_and_the_rest_are_not():
    recs, notes = P.build([ONE_WEEK])
    assert by(recs, "garlic", 39)[0]["value"] == 272.0 and by(recs, "garlic", 39)[0]["prewar_price"] == 10.0
    flour = by(recs, "flour_25kg_sack", 39)[0]
    assert flour["value"] == 341.43 and flour["unit"] == "ILS/25 KG" and flour["date"] == "2025-04-22"
    assert by(recs, "dishwashing_liquid", 39)[0]["value"] == 35.0            # the pre-war table's, not 38.57
    assert any("38.57" in s for s in notes["printed_otherwise_in_the_same_report"])
    assert by(recs, "baby_diapers_40_pack", 39)[0]["unit"] == "ILS/40 PIECES"
    na = by(recs, "frozen_veal_unpriced", 39)[0]
    assert na["value"] is None and na["text"] == "NA" and na["unit"] is None
    assert not by(recs, "soap_piece") and any("soap" in s for s in notes["rows_that_do_not_add_up"])
    assert not [r for r in recs if r["measure"] == "flour_25kg_sack" and r["value"] == 12.65]   # the basket's quantity


def test_two_week_tables_and_the_minus_printed_after_the_number():
    recs, notes = P.build([TWO_WEEKS])
    assert [r["value"] for r in by(recs, "flour_25kg_sack")] == [15.86, 23.86]
    assert by(recs, "flour_25kg_sack", 81)[0]["stated_change_vs_prewar_pct"] == -32.0
    assert [(r["week"], r["period_start"], r["period_end"]) for r in by(recs, "onion")] == [
        (80, "2026-02-02", "2026-02-08"), (81, "2026-02-09", "2026-02-15")]
    assert [r["value"] for r in by(recs, "firewood")] == [6.0, 5.79]          # pre-war printed as 0: unchecked, noted
    assert len(notes["rows_unchecked"]) == 2


def test_the_index_by_day_week_and_month():
    recs, notes = P.build([TWO_WEEKS])
    assert by(recs, "gcpi_daily", date="2026-02-03")[0]["value"] == 2534.0
    assert by(recs, "basket_cost_daily", date="2026-02-03")[0]["value"] == 2342.25
    assert by(recs, "gcpi_daily", date="2026-02-02")[0]["value"] == 150.0
    wk = by(recs, "gcpi_weekly")[0]
    assert (wk["date"], wk["period_end"], wk["index_week"], wk["value"]) == ("2025-01-31", "2025-02-06", 14, 167.0)
    m = by(recs, "gcpi_monthly")
    assert [(r["date"], r["period_end"], r["value"], r["precision"]) for r in m] == [("2025-08-01", "2025-08-31", 1454.0, "month")]
    assert notes["months_provisional"] and notes["index_values_that_do_not_add_up"]   # Sep-26 "up to 13"; Mar-26 341 is not 365


def test_the_spec_names_every_series_and_its_units_exist():
    spec = load_spec("price_gazacham")
    assert spec["datasets"] == [{"key": "gazacham_prices", "source": "gaza_chamber"}]
    rules = {r["when"]["equals"]: r for r in spec["registry"]["rules"]}
    goods = {g[0] for g in P.GOODS.values()}
    held = {r["measure"] for r in json.load(open(P.OUT))["data"]} if P.OUT.exists() else set()
    assert {f"price_gazacham.{m}" for m in held} <= set(rules) and len(goods) == 31   # the box of water, 2026-10-14
    for k in ("gcpi_daily", "gcpi_weekly", "gcpi_monthly", "basket_cost_daily"):
        assert f"price_gazacham.{k}" in rules
    assert all(r["name_ar"] and r["serve_warning"] and r["serve_warning_ar"] for r in rules.values())
    units = yaml.safe_load((P.ROOT / "db" / "registry" / "units.yaml").read_text(encoding="utf-8"))["units"]
    aliases = {raw for u in units.values() for raw in (u.get("aliases") or {})} | set(units)
    assert {g[2] for g in P.GOODS.values()} | {"index", "ILS"} <= aliases
    assert {r["canonical_unit"] for r in rules.values() if r.get("canonical_unit")} <= set(units)


EARLY = {"weeks": [14], "start": "2024-10-29", "date": "2024-11-04T00:00:00", "title": "x", "link": "https://gazacham.ps/x14",
         "text": """
Table (7): Daily market prices ILS/Kg for essential items (South of Gaza Strip)
#   Item     29/10 30/10 31/10 01/11 02/11 03/11 04/11 Average St. Dev
 4  Sugar    N/A   N/A   28    28    28    35    35    30.80   3.83
16  Bottled water box   28    28    28    28    28    28    28    28.00   0.00
Table (8): Price of food items in the northern part of Gaza Strip (ILS/Kg).
11  Sugar    N/A   N/A   N/A   95    95    95    100   96.25   2.50
Table (9): comparison between prices before and after the war
 5  Sugar        3     11.29    276%    94.29    3,043%
 6  Rice         9     30       233%    NA       NA
 7  Flour        30    50       67%     30.71    2%
"""}


def test_the_early_weeks_give_the_north_and_the_south_with_their_units_checked():
    recs, notes = P.build([EARLY])
    by = {r["measure"]: r for r in recs}
    s, n = by["sugar_south"], by["sugar_north"]
    assert (s["value"], n["value"]) == (11.29, 94.29)                        # the comparison table is held
    assert s["daily_table_average"] == 30.8 and n["daily_table_average"] == 96.25   # the daily table beside it
    assert s["market"] == "south" and s["unit"] == "ILS/KG" and s["date"] == "2024-10-29"
    assert by["bottled_water_box_south"]["value"] == 28.0                      # only the daily table prices it
    assert "daily table" in by["bottled_water_box_south"]["basis"]
    rice = by["rice_south"]                                                    # its own pre-war price, 9 not 8
    assert rice["prewar_price"] == 9.0 and "own pre-war price" in rice["basis"]
    assert by["rice_north_unpriced"]["text"] == "NA"
    assert not [r for r in recs if r["good"] == "flour_25kg_sack"]            # 30 is not flour's 35: no unit
    assert notes["early_rows_not_matched"] and notes["early_own_prewar"]


def test_an_early_daily_table_that_names_no_region_is_not_read():
    early = dict(EARLY, weeks=[3], start="2024-08-15", date="2024-08-21T00:00:00",
                 text="Table (7): Daily market prices ILS/Kg for essential items\n 4  Sugar  20  20  20  20  20  20  20  20.00  0.00\n")
    recs, _ = P.build([early])
    assert recs == []
