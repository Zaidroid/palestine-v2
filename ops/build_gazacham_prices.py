"""Prices in Gaza's markets, week by week and day by day, from the Gaza Chamber
of Commerce's weekly goods reports: what flour, sugar, diesel or diapers cost
in each week from April 2025, against what they cost before the war, and the
Chamber's own price index (GCPI) of a basket of essential goods.

    .venv/bin/python -m ops.build_gazacham_prices            # write data/raw/gazacham/prices.json
    .venv/bin/python -m ops.build_gazacham_prices --check    # read and check, write nothing

It reads the reports as the archive holds them (data/raw/reports/gazacham/
items-all.ndjson.gz, written by ops/fetch_gazacham.py) and makes no request.

WHAT IS READ (measured 2026-10-14 over the 81 reports):

  goods     every row of a table that compares a good's average price in a
            week with its pre-war price, from week 36 (1 April 2025) on: the
            row states the good, its unit, its pre-war price, the week's price
            and the change in percent. Three layouts: one week a report
            (weeks 36-50: pre-war, the week, change), week 55 (pre-war, the
            week before, the week, change on the week, change on pre-war), and
            two weeks a report (pre-war, a week, its change, the next week,
            its change, change between them). A row is taken only when its
            own percent says what its prices say (within rounding); a row
            that does not is listed in the notes, never mended.
  NA        a good the table prints NA for, in place of a price: kept as the
            report's mark in a series of its own, never as a price. The
            reports do not define NA; their summaries say, in the same weeks,
            that such goods were no longer found in the markets.
  index     the Chamber's GCPI: a basket of essential goods that cost ILS
            92.44 before the war (index 100). Daily from 27 May 2025, weekly
            (the index's own weeks) from 31 January 2025, monthly from
            February 2025; each value is the basket's cost in shekels and the
            index. A value is taken when its index is its cost over 92.44
            (within rounding), and a day or a month printed by two reports
            must read the same in both.

WHAT IS LEFT, and why:

  weeks 1-35   the earliest reports price goods day by day, and by region from
               week 8, under a header that says "ILS/Kg" for every row while
               flour and eggs are plainly priced by the sack and the tray: the
               unit of a row is not stated. Not read until that is decided.
  weeks 62-65  prices and the index split into North and South, as markets
               were cut off again in October 2025: they need a place each and
               come with the regional tables of the earliest reports.
  a month the newest report gives "up to" a day: provisional, so not a value.

Nothing is averaged, filled or derived. Units are the report's own (a 25 kg
sack, a can of 400 g, a pack of 40); the API puts a per-kilogram or per-piece
value beside them where the conversion is exact.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import fetchlib                                        # noqa: E402
from ops.build_gazacham_series import SOURCE_NAME, week_periods  # noqa: E402

REPORTS = ROOT / "data" / "raw" / "reports" / "gazacham" / "items-all.ndjson.gz"
OUT = ROOT / "data" / "raw" / "gazacham" / "prices.json"
PREWAR_BASKET = 92.44        # "Before the war, the total price of the basket ... was standing at 92.44 shekels" (week 40)
FIRST_PRICED_WEEK = 36

# The goods, as the tables name them (lower-cased, spaces collapsed), and the
# series each is held in. A name the tables use for the same good in other
# reports is listed with it; every name is printed in the dataset's notes with
# its count, so a merge here can be checked against the reports.
GOODS = {
    "flour":                ("flour_25kg_sack", "Sack (25Kg)", "ILS/25 KG", "food",
                             "Wheat flour", "طحين"),
    "sugar":                ("sugar", "Kg", "ILS/KG", "food", "Sugar", "سكر"),
    "rice":                 ("rice", "Kg", "ILS/KG", "food", "Rice", "أرز"),
    "macaroni":             ("macaroni", "Kg", "ILS/KG", "food", "Macaroni", "معكرونة"),
    "kidney beans":         ("kidney_beans", "Kg", "ILS/KG", "food", "Kidney beans", "فاصولياء حمراء"),
    "vegetable oil":        ("vegetable_oil", "Liter", "ILS/L", "food", "Vegetable oil", "زيت نباتي"),
    "oil":                  ("vegetable_oil", "Liter", "ILS/L", "food", "Vegetable oil", "زيت نباتي"),
    "onion":                ("onion", "Kg", "ILS/KG", "food", "Onion", "بصل"),
    "tomato":               ("tomato", "Kg", "ILS/KG", "food", "Tomato", "بندورة"),
    "potato":               ("potato", "Kg", "ILS/KG", "food", "Potato", "بطاطا"),
    "cucumber":             ("cucumber", "Kg", "ILS/KG", "food", "Cucumber", "خيار"),
    "eggplant":             ("eggplant", "Kg", "ILS/KG", "food", "Eggplant", "باذنجان"),
    "pepper":               ("pepper", "Kg", "ILS/KG", "food", "Pepper", "فلفل"),
    "garlic":               ("garlic", "Kg", "ILS/KG", "food", "Garlic", "ثوم"),
    "lemon":                ("lemon", "Kg", "ILS/KG", "food", "Lemon", "ليمون"),
    "apple":                ("apple", "Kg", "ILS/KG", "food", "Apple", "تفاح"),
    "banana":               ("banana", "Kg", "ILS/KG", "food", "Banana", "موز"),
    "orange":               ("orange", "Kg", "ILS/KG", "food", "Orange", "برتقال"),
    "egg":                  ("eggs", "Kg", "ILS/KG", "food", "Eggs", "بيض"),
    "eggs":                 ("eggs", "Kg", "ILS/KG", "food", "Eggs", "بيض"),
    "frozen chicken":       ("frozen_chicken", "Kg", "ILS/KG", "food", "Frozen chicken", "دجاج مجمّد"),
    "frozen chicken thigh": ("frozen_chicken_thigh", "Kg", "ILS/KG", "food", "Frozen chicken thighs", "أفخاذ دجاج مجمّدة"),
    "frozen chicken wing":  ("frozen_chicken_wing", "Kg", "ILS/KG", "food", "Frozen chicken wings", "أجنحة دجاج مجمّدة"),
    "frozen veal":          ("frozen_veal", "Kg", "ILS/KG", "food", "Frozen veal", "لحم عجل مجمّد"),
    "baby milk":            ("baby_milk_400g_can", "Can (400 gm)", "ILS/400 G", "nonfood",
                             "Baby milk", "حليب أطفال"),
    "baby diapers":         ("baby_diapers_40_pack", "Pack (40 pcs)", "ILS/40 PIECES", "nonfood",
                             "Baby diapers", "حفاضات أطفال"),
    "sanitary towels":      ("sanitary_towels_10_pack", "Pack (10 pcs)", "ILS/10 PIECES", "nonfood",
                             "Sanitary towels", "فوط صحية"),
    "soap":                 ("soap_piece", "Piece", "ILS/PIECE", "nonfood", "Soap", "صابون"),
    "dishwashing liquid":   ("dishwashing_liquid", "Liter", "ILS/L", "nonfood", "Dishwashing liquid", "سائل جلي"),
    "laundry detergent":    ("laundry_detergent", "Kg", "ILS/KG", "nonfood", "Laundry detergent", "مسحوق غسيل"),
    "firewood":             ("firewood", "Kg", "ILS/KG", "nonfood", "Firewood", "حطب"),
    "fire wood":            ("firewood", "Kg", "ILS/KG", "nonfood", "Firewood", "حطب"),
    "diesel":               ("diesel", "Liter", "ILS/L", "nonfood", "Diesel", "سولار"),
}
_UNIT = r"(Kg|KG|kg|Liter|Litre|liter|Sack\s*\(\s*25\s*Kg\)|Pack\s*\(\s*\d+\s*pcs\s*\)|Can\s*\(\s*400\s*gm\s*\)|Piece|piece)"
_ROW = re.compile(r"^[ \t]*(\d{1,2})[ \t]+([A-Za-z][A-Za-z .'-]*?[A-Za-z])[ \t]{2,}" + _UNIT + r"[ \t]{2,}(\S.*?)[ \t]*$", re.M)
_NUM = re.compile(r"^-?[\d,]*\.?\d+$")
_PCT = re.compile(r"^(-?)([\d,]*\.?\d+)%(-?)$")      # "-55%", and "55%-" as right-to-left layout prints it
_DAY = r"(\d{1,2}/\d{1,2}/20\d\d)"
_AMT = r"([\d,]+(?:\.\d+)?)"
_DAILY = re.compile(r"^[ \t]*\d{1,2}[ \t]+" + _DAY + r"[ \t]+" + _AMT + r"[ \t]+" + _AMT + r"%[ \t]*$", re.M)
_WEEKLY = re.compile(r"^[ \t]*Week[ \t]*(\d+)[ \t]+" + _DAY + r"[ \t]+" + _DAY + r"[ \t]+" + _AMT + r"[ \t]+" + _AMT + r"%[ \t]*$", re.M)
_MONTHLY = re.compile(r"^[ \t]*\d{1,2}[ \t]+([A-Z][a-z]{2})[ \t]*-[ \t]*(\d\d)([^\n]*?)[ \t]{2,}" + _AMT + r"[ \t]+" + _AMT + r"%[ \t]*$", re.M)
_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


class Refused(Exception):
    pass


def _num(tok: str) -> float | None:
    if _NUM.match(tok):
        return float(tok.replace(",", ""))
    return None


def _pct(tok: str) -> float | None:
    m = _PCT.match(tok)
    if not m or (m.group(1) and m.group(3)):
        return None
    v = float(m.group(2).replace(",", ""))
    return -v if (m.group(1) or m.group(3)) else v


def _agrees(price: float, prewar: float, stated: float) -> bool:
    """The stated change in percent is what the two prices say, to rounding:
    prices are printed to the cent and percents to the unit."""
    if prewar <= 0:
        return False
    said = (price / prewar - 1) * 100
    return abs(said - stated) <= 1.0 + 0.005 * abs(stated) + 100 * 0.006 / prewar


def _day(s: str) -> str:
    d, m, y = (int(x) for x in s.split("/"))
    return datetime.date(y, m, d).isoformat()


_CAPTION = re.compile(r"Table\s*\(\d+\)\s*:([^\n]*(?:\n[^\n]*)?)")


def table_kind(text: str, pos: int) -> str:
    """What the table a row sits in compares, from the nearest table caption
    above it ("Table (3): comparing current prices of basic non-food items
    with pre-war prices."): 'prewar', 'previous' (the week before), 'basket'
    (the index's quantities) or 'other'. Measured: one-week reports print a
    pre-war table and a previous-week table in the same three columns, and
    week 39 gives dishwashing liquid 35.00 in one and 38.57 in the other for
    the same week. Two-week reports print one six-column table and need no
    caption (the newest have none)."""
    caps = list(_CAPTION.finditer(text, 0, pos))
    if not caps:
        return "other"
    cap = re.sub(r"\s+", " ", caps[-1].group(1)).lower()
    if "quantit" in cap or "included in the index" in cap:
        return "basket"
    if "previous" in cap:
        return "previous"
    if re.search(r"pre-? ?war|before the war", cap):
        return "prewar"
    return "other"


def goods_rows(item: dict, notes: dict) -> list[dict]:
    """The week prices of one report, each checked against its own percents."""
    weeks = item["weeks"]
    periods = week_periods(item)
    out = []
    previous_table: dict[str, float] = {}
    for m in _ROW.finditer(item["text"]):
        name = re.sub(r"\s+", " ", m.group(2)).strip().lower()
        unit_printed = re.sub(r"\s+", " ", m.group(3)).strip()
        toks = m.group(4).split()
        kind = table_kind(item["text"], m.start()) if len(weeks) == 1 else "prewar"
        if kind in ("basket", "other"):
            continue                                        # the index's quantities, or a table this does not read
        if name not in GOODS:
            notes["names_not_held"][name] = notes["names_not_held"].get(name, 0) + 1
            continue
        key, unit_held, *_ = GOODS[name]
        if len(weeks) == 1 and len(toks) == 3 and kind == "previous":
            cur = _num(toks[1])
            if cur is not None:
                previous_table[key] = cur                   # the same week's price, printed again: compared below
            continue
        if len(weeks) == 1 and len(toks) == 3 and kind == "prewar":   # weeks 36-50: pre-war, the week, change
            layout = [(weeks[0], 1, 2)]
        elif len(weeks) == 1 and len(toks) == 5 and weeks[0] == 55:   # pre-war, before, the week, on the week, on pre-war
            layout = [(55, 2, 4)]
        elif len(weeks) == 2 and len(toks) == 6:            # pre-war, a week, change, the next, change, between
            layout = [(weeks[0], 1, 2), (weeks[1], 3, 4)]
        else:
            continue                                        # another table (the basket, the week before, North/South)
        prewar = _num(toks[0])
        if prewar is None:
            notes["rows_not_read"].append(f"weeks {weeks}: {name}: pre-war price {toks[0]!r}")
            continue
        if re.sub(r"\s+", "", unit_printed).lower() != re.sub(r"\s+", "", unit_held).lower():
            notes["units_printed_otherwise"].append(f"weeks {weeks}: {name} priced per {unit_printed!r}, held per {unit_held!r}")
            continue
        for wk, pi, ci in layout:
            p_tok, c_tok = toks[pi], toks[ci]
            a, b = periods[wk]
            base = {"week": wk, "date": a, "period_start": a, "period_end": b, "good": key, "name_printed": name,
                    "unit_printed": unit_printed, "prewar_price": prewar, "report": item["link"]}
            if p_tok.upper() in ("NA", "N/A"):
                out.append({**base, "measure": f"{key}_unpriced", "value": None, "text": "NA"})
                continue
            price, stated = _num(p_tok), _pct(c_tok)
            if price is None or stated is None:
                notes["rows_not_read"].append(f"week {wk}: {name}: {p_tok!r} {c_tok!r}")
                continue
            if prewar == 0:
                notes["rows_unchecked"].append(f"week {wk}: {name}: the table prints its pre-war price as 0")
            elif not _agrees(price, prewar, stated):
                notes["rows_that_do_not_add_up"].append(
                    f"week {wk}: {name}: {price:g} against {prewar:g} before the war is "
                    f"{(price / prewar - 1) * 100:+.0f}%, the row says {stated:+g}%")
                continue
            out.append({**base, "measure": key, "value": price, "stated_change_vs_prewar_pct": stated})
    for r in out:
        again = previous_table.get(r["good"])
        if r["value"] is not None and again is not None and abs(again - r["value"]) > 0.005:
            notes["printed_otherwise_in_the_same_report"].append(
                f"week {r['week']}: {r['name_printed']}: {r['value']:g} against the pre-war price, "
                f"{again:g} in the report's table against the week before (the first is held)")
    return out


def index_rows(item: dict, notes: dict) -> list[dict]:
    """The GCPI values one report prints: daily, weekly and monthly."""
    out = []
    t = item["text"]

    def checked(basket: float, idx: float, where: str) -> bool:
        if abs(basket / PREWAR_BASKET * 100 - idx) <= 1.0 + 0.005 * idx:
            return True
        notes["index_values_that_do_not_add_up"].append(
            f"{where}: a basket of ILS {basket:g} is index {basket / PREWAR_BASKET * 100:.0f}, the row says {idx:g}")
        return False

    for day, basket, idx in _DAILY.findall(t):
        b, i = float(basket.replace(",", "")), float(idx.replace(",", ""))
        d = _day(day)
        if checked(b, i, d):
            out.append({"grain": "daily", "date": d, "period_start": d, "period_end": d, "basket": b, "index": i,
                        "report": item["link"]})
    for wk, d1, d2, basket, idx in _WEEKLY.findall(t):
        b, i = float(basket.replace(",", "")), float(idx.replace(",", ""))
        a, z = _day(d1), _day(d2)
        if checked(b, i, f"index week {wk}"):
            out.append({"grain": "weekly", "date": a, "period_start": a, "period_end": z, "index_week": int(wk),
                        "basket": b, "index": i, "report": item["link"]})
    for mon, yy, rest, basket, idx in _MONTHLY.findall(t):
        if mon not in _MONTHS:
            continue
        if re.search(r"up to|\(", rest):
            notes["months_provisional"].append(f"{mon}-{yy} {rest.strip()} ({item['link'].rsplit('=', 1)[-1]})")
            continue
        b, i = float(basket.replace(",", "")), float(idx.replace(",", ""))
        d = datetime.date(2000 + int(yy), _MONTHS[mon], 1)
        end = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
        if checked(b, i, f"{mon}-{yy}"):
            out.append({"grain": "monthly", "date": d.isoformat(), "period_start": d.isoformat(),
                        "period_end": end.isoformat(), "basket": b, "index": i, "report": item["link"]})
    return out


def build(items: list[dict]) -> tuple[list[dict], dict]:
    notes: dict = {"reports": len(items), "names_not_held": {}, "rows_not_read": [], "rows_unchecked": [],
                   "rows_that_do_not_add_up": [], "units_printed_otherwise": [],
                   "index_values_that_do_not_add_up": [], "months_provisional": [], "names_read": {},
                   "printed_twice_differently": [], "printed_otherwise_in_the_same_report": []}
    goods: dict[tuple, dict] = {}
    index: dict[tuple, dict] = {}
    for item in sorted(items, key=lambda i: i["weeks"]):
        if min(item["weeks"]) < FIRST_PRICED_WEEK:
            continue
        for r in goods_rows(item, notes):
            notes["names_read"][r["name_printed"]] = notes["names_read"].get(r["name_printed"], 0) + 1
            k = (r["measure"], r["week"])
            if k in goods and goods[k]["value"] != r["value"]:
                raise Refused(f"week {r['week']} {r['measure']}: {goods[k]['value']} and {r['value']} in one report")
            goods[k] = r
        for r in index_rows(item, notes):
            k = (r["grain"], r["date"])
            if k in index and (index[k]["basket"], index[k]["index"]) != (r["basket"], r["index"]):
                # a day or month printed again later: the later report is the publisher's latest word
                notes["printed_twice_differently"].append(
                    f"{r['grain']} {r['date']}: ILS {index[k]['basket']:g} ({index[k]['index']:g}) in "
                    f"{index[k]['report'].rsplit('=', 1)[-1]}, ILS {r['basket']:g} ({r['index']:g}) in "
                    f"{r['report'].rsplit('=', 1)[-1]}")
            index[k] = r
    records = []
    for (measure, wk), r in sorted(goods.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        key = r["good"]
        names = GOODS[r["name_printed"]]
        records.append({
            "stable_id": f"gazacham:prices:week{wk:03d}:{measure}", "measure": measure,
            "value": r["value"], "text": r.get("text"),
            "unit": names[2] if r["value"] is not None else None,
            "date": r["date"], "period_start": r["period_start"], "period_end": r["period_end"], "week": wk,
            "prewar_price": r["prewar_price"], "stated_change_vs_prewar_pct": r.get("stated_change_vs_prewar_pct"),
            "name_printed": r["name_printed"], "unit_printed": r["unit_printed"], "report": r["report"],
            "indicator_name": f"{names[4]} ({'not priced' if r['value'] is None else 'price'})",
            "location": {"region": "Gaza Strip"},
            "sources": [{"name": SOURCE_NAME, "organization": "Gaza Chamber of Commerce and Industry", "url": r["report"]}],
            "good": key})
    for (grain, date), r in sorted(index.items()):
        for measure, value, unit in ((f"gcpi_{grain}", r["index"], "index"), (f"basket_cost_{grain}", r["basket"], "ILS")):
            records.append({
                "stable_id": f"gazacham:prices:{measure}:{date}", "measure": measure, "value": value, "text": None,
                "unit": unit, "date": date, "precision": "month" if grain == "monthly" else "day",
                "period_start": r["period_start"], "period_end": r["period_end"],
                "index_week": r.get("index_week"), "prewar_basket": PREWAR_BASKET, "report": r["report"],
                "indicator_name": measure, "location": {"region": "Gaza Strip"},
                "sources": [{"name": SOURCE_NAME, "organization": "Gaza Chamber of Commerce and Industry",
                             "url": r["report"]}]})
    return records, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="read and check, write nothing")
    ap.add_argument("--reports", type=Path, default=REPORTS)
    a = ap.parse_args()
    with gzip.open(a.reports, "rt", encoding="utf-8") as fh:
        items = [json.loads(line) for line in fh]
    try:
        records, notes = build(items)
    except Refused as e:
        print(f"REFUSED: {e}")
        return 1
    goods = sorted({r["good"] for r in records if r.get("good") and r["value"] is not None})
    by = {}
    for r in records:
        by[r["measure"]] = by.get(r["measure"], 0) + 1
    print(f"{len(records)} figures · {len(goods)} goods priced, "
          f"{sum(1 for r in records if r.get('good') and r['value'] is not None)} week prices, "
          f"{sum(1 for r in records if r['text'] == 'NA')} NA marks · index: "
          f"{by.get('gcpi_daily', 0)} days, {by.get('gcpi_weekly', 0)} weeks, {by.get('gcpi_monthly', 0)} months · "
          f"left: {len(notes['rows_that_do_not_add_up'])} rows that do not add up, "
          f"{len(notes['units_printed_otherwise'])} priced in another unit, "
          f"{len(notes['index_values_that_do_not_add_up'])} index values that do not add up")
    if a.check:
        return 0
    newest = max(i["date"][:10] for i in items)
    doc = {"metadata": {"source": SOURCE_NAME, "source_url": "https://gazacham.ps/InformationCenter/Reports",
                        "vintage": newest, "vintage_basis": "the last day of the newest report read",
                        "vintage_url": "https://gazacham.ps/InformationCenter/Reports",
                        "license": "\"All rights reserved, 2023, Gaza Chamber of Commerce and Industry\" in the site footer "
                                   "(no-license-found)",
                        "attribution": "Prices in Gaza: Gaza Chamber of Commerce and Industry, Gaza Movement of Goods "
                                       "weekly reports (gazacham.ps).",
                        "prewar_basket_ils": PREWAR_BASKET, **notes},
           "data": records}
    fetchlib.write_atomic(OUT, doc)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
