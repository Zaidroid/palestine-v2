"""The price of cash in Gaza: the commission a person paid to turn a balance in a
bank or a payment app into cash in hand, as the Gaza Chamber of Commerce
recorded it in its weekly goods reports.

    .venv/bin/python -m ops.build_gazacham_cash            # write data/raw/gazacham/cash.json
    .venv/bin/python -m ops.build_gazacham_cash --check    # read and check, write nothing

It reads the reports as the archive holds them (data/raw/reports/gazacham/
items-all.ndjson.gz) and makes no request. The reports explain the rate:
"Individuals, whether merchants or otherwise, provide cash to customers in
exchange for a percentage called a 'commission'. The beneficiary customer
transfers money via various electronic wallets to the cash provider's bank
account and receives the amount in cash, minus the commission" (week 33).

WHAT IS READ (measured 2026-10-14 over the 81 reports):

  weekly   the commission's own weeks, numbered from the ceasefire of 19 January
           2025 ("Week 01  19/01/2025  25/01/2025  17%"), printed whole again by
           each report from week 40 to week 49.
  daily    from 17 June 2025, fourteen days a report, to 19 July 2026.
  monthly  the Chamber's monthly rate: rows that carry the month's first and last
           day, or the table printed sideways under a caption that names its
           first and last month (its values must be as many as its months).

WHAT IS NOT HELD, and why:

  a day two reports print differently. Measured: report 49 gives 24 to 30 June
           2025 the run 41, 42, 42, 42, 35, 36, 40, and report 50 gives the same
           run to 1 to 7 July; one of the two is a copied block and nothing says
           which. Such days are listed in the file's notes, held from neither.
  a month a report gives before it has ended (its last day is not the month's).
  For a whole month printed differently by two reports the later is held (the
  month is the Chamber's own average) and the earlier is noted.

The reports of August 2026 say the commission "has become largely insignificant
due to the widespread adoption of electronic payment systems"; the daily table
is not printed after report 102-103.
"""
from __future__ import annotations

import argparse
import calendar
import datetime
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import fetchlib                                        # noqa: E402
from ops.build_gazacham_series import SOURCE_NAME              # noqa: E402

REPORTS = ROOT / "data" / "raw" / "reports" / "gazacham" / "items-all.ndjson.gz"
OUT = ROOT / "data" / "raw" / "gazacham" / "cash.json"
_DAY = r"(\d{1,2}/\d{1,2}/20\d\d)"
_PCT = r"(\d+(?:\.\d+)?)%"
_WEEKLY = re.compile(r"^[ \t]*Week[ \t]*(\d+)[ \t]+" + _DAY + r"[ \t]+" + _DAY + r"[ \t]+" + _PCT + r"[ \t]*$", re.M)
_DAILY = re.compile(r"^[ \t]*\d{1,2}[ \t]+" + _DAY + r"[ \t]+" + _PCT + r"[ \t]*$", re.M)
_MONTH_ROW = re.compile(r"^[ \t]*(?:\d{1,2}[ \t]+)?([A-Z][a-z]{2,3})-(\d\d)[ \t]+" + _DAY + r"[ \t]+" + _DAY + r"[ \t]+" + _PCT + r"[ \t]*$", re.M)
_MONTH_CAPTION = re.compile(r"Monthly cash out commission rate \(([A-Za-z]+)[ \t-]*(\d{4})?[ \t]*(?:–|-|to)[ \t]*([A-Za-z]+)[ \t-]*(\d{4})\)")
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
_MONTHS["july"] = 7
_MONTHS["sept"] = 9


class Refused(Exception):
    pass


def _day(s: str) -> datetime.date:
    d, m, y = (int(x) for x in s.split("/"))
    return datetime.date(y, m, d)


def _month_end(d: datetime.date) -> datetime.date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def report_end(item: dict) -> datetime.date:
    return datetime.date.fromisoformat(item["date"][:10])


def rows_of(item: dict, notes: dict) -> list[dict]:
    t = item["text"]
    name = item["link"].rsplit("=", 1)[-1]
    out = []
    for wk, a, b, pct in _WEEKLY.findall(t):
        out.append({"grain": "weekly", "start": _day(a), "end": _day(b), "value": float(pct), "commission_week": int(wk),
                    "report": item["link"], "report_name": name})
    for a, pct in _DAILY.findall(t):
        d = _day(a)
        out.append({"grain": "daily", "start": d, "end": d, "value": float(pct), "report": item["link"], "report_name": name})
    for mon, yy, a, b, pct in _MONTH_ROW.findall(t):
        start, end = _day(a), _day(b)
        first = datetime.date(2000 + int(yy), _MONTHS[mon.lower()], 1)
        if end != _month_end(first):
            # the month's first row starts on 19 January 2025, the ceasefire: whole from then on
            notes["months_not_whole"].append(f"{mon}-{yy} to {b} ({name})")
            if end < _month_end(first):
                continue
        out.append({"grain": "monthly", "start": first, "end": _month_end(first), "value": float(pct),
                    "measured_from": start.isoformat(), "report": item["link"], "report_name": name})
    for cap in _MONTH_CAPTION.finditer(t):
        m1, y1, m2, y2 = cap.groups()
        y1 = y1 or y2
        try:
            first = datetime.date(int(y1), _MONTHS[m1.lower()], 1)
            last = datetime.date(int(y2), _MONTHS[m2.lower()], 1)
        except KeyError:
            continue
        months = []
        d = first
        while d <= last:
            months.append(d)
            d = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        after = t[cap.end(): cap.end() + 1500]
        line = re.search(r"commission[ \t]+((?:\d+(?:\.\d+)?%[ \t]+){2,}\d+(?:\.\d+)?%)", after)
        if not line or _MONTH_ROW.search(after[: line.start()] if line else ""):
            continue                                            # the vertical table: read above
        vals = [float(v[:-1]) for v in line.group(1).split()]
        if len(vals) != len(months):
            notes["tables_not_read"].append(f"{name}: {len(vals)} values under a caption of {len(months)} months")
            continue
        for d, v in zip(months, vals):
            if _month_end(d) > report_end(item):
                notes["months_not_whole"].append(f"{d:%b-%y} printed by {name}, which ends {report_end(item)}")
                continue
            out.append({"grain": "monthly", "start": d, "end": _month_end(d), "value": v, "report": item["link"],
                        "report_name": name})
    return out


def build(items: list[dict]) -> tuple[list[dict], dict]:
    notes: dict = {"reports": len(items), "days_printed_differently": [], "weeks_printed_differently": [],
                   "months_printed_differently": [], "months_not_whole": [], "tables_not_read": []}
    held: dict[tuple, dict] = {}
    contested: set[tuple] = set()
    for item in sorted(items, key=lambda i: i["weeks"]):
        for r in rows_of(item, notes):
            k = (r["grain"], r["start"])
            if k in held and held[k]["value"] != r["value"]:
                was = held[k]
                line = (f"{r['start']}: {was['value']:g}% in {was['report_name']}, {r['value']:g}% in {r['report_name']}")
                if r["grain"] == "monthly":
                    notes["months_printed_differently"].append(line + " (the later is held)")
                else:
                    notes[f"{'days' if r['grain'] == 'daily' else 'weeks'}_printed_differently"].append(line + " (neither is held)")
                    contested.add(k)
            held[k] = r
    records = []
    for k, r in sorted(held.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if k in contested:
            continue
        measure = f"cashout_commission_{r['grain']}"
        records.append({
            "stable_id": f"gazacham:cash:{measure}:{r['start']}", "measure": measure, "value": r["value"], "unit": "percent",
            "date": r["start"].isoformat(), "precision": "month" if r["grain"] == "monthly" else "day",
            "period_start": r["start"].isoformat(), "period_end": r["end"].isoformat(),
            "commission_week": r.get("commission_week"), "measured_from": r.get("measured_from"), "report": r["report"],
            "indicator_name": measure, "location": {"region": "Gaza Strip"},
            "sources": [{"name": SOURCE_NAME, "organization": "Gaza Chamber of Commerce and Industry", "url": r["report"]}]})
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
    by = {}
    for r in records:
        by[r["measure"]] = by.get(r["measure"], 0) + 1
    print(f"{len(records)} figures · {by.get('cashout_commission_daily', 0)} days, {by.get('cashout_commission_weekly', 0)} weeks, "
          f"{by.get('cashout_commission_monthly', 0)} months · not held: {len(notes['days_printed_differently'])} days and "
          f"{len(notes['weeks_printed_differently'])} weeks two reports print differently")
    if a.check:
        return 0
    newest = max(i["date"][:10] for i in items)
    doc = {"metadata": {"source": SOURCE_NAME, "source_url": "https://gazacham.ps/InformationCenter/Reports",
                        "vintage": newest, "vintage_basis": "the last day of the newest report read (the reports after "
                                                            "July 2026 print no commission table)",
                        "last_figure": max(r["period_end"] for r in records),
                        "vintage_url": "https://gazacham.ps/InformationCenter/Reports",
                        "license": "\"All rights reserved, 2023, Gaza Chamber of Commerce and Industry\" in the site footer "
                                   "(no-license-found)",
                        "attribution": "The cash-out commission in Gaza: Gaza Chamber of Commerce and Industry, Gaza Movement "
                                       "of Goods weekly reports (gazacham.ps).",
                        **notes},
           "data": records}
    fetchlib.write_atomic(OUT, doc)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
