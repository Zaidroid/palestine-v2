"""Trucks into Gaza, week by week, from the Gaza Chamber of Commerce's weekly
goods reports: the series the reports hold and nobody has charted.

    .venv/bin/python -m ops.build_gazacham_series            # write data/raw/gazacham/weekly.json
    .venv/bin/python -m ops.build_gazacham_series --check    # read and check, write nothing

It reads the reports as the archive holds them (data/raw/reports/gazacham/
items-all.ndjson.gz, written by ops/fetch_gazacham.py) and makes no request.

THREE KINDS OF REPORT, read three ways (measured 2026-10-14 over 81 reports,
weeks 1 to 111, 1 August 2024 to 13 September 2026):

  weeks 1-31    one week a report; the crossings table ends in a Total row
                whose last figure is the week's trucks.
  weeks 32-50   the closure of 2 March 2025 and the months after it: the
                figures are in sentences, so they are read by hand into
                db/reference/gazacham_trucks_by_hand.yaml, each with the sentence
                it stands on. Week 42 states no figure for its week.
  weeks 51-111  two weeks a report; the crossings table has a Subtotal row per
                week ("Subtotal 1 (Week 90) 1,222 360 0 1,582") whose last
                figure is that week's trucks. The two must add up to the
                table's Total row; a report where they do not is refused.

Looted and delivered trucks are taken where a report states them: by hand for
weeks 43 to 50 and 55, and from the sentence "In Week 60 (...), 614 trucks
arrived (282 looted, 332 delivered)" where it appears (weeks 51 to 61), which
must agree with the table's figure for the week.

A week is dated by its first day (precision: day) and carries its last day:
the store has no "week" precision, and a weekly count dated to one day must
say so. The names say "in the week beginning".

Nothing is averaged, filled or derived. A week with no stated figure has no row.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import fetchlib                                        # noqa: E402

REPORTS = ROOT / "data" / "raw" / "reports" / "gazacham" / "items-all.ndjson.gz"
BY_HAND = ROOT / "db" / "reference" / "gazacham_trucks_by_hand.yaml"
OUT = ROOT / "data" / "raw" / "gazacham" / "weekly.json"
SOURCE_NAME = "Gaza Chamber of Commerce and Industry — Gaza Movement of Goods weekly reports"
MEASURES = ("trucks_entered", "trucks_looted", "trucks_delivered")
_N = re.compile(r"[\d,]+")


class Refused(Exception):
    pass


def _n(s: str) -> int:
    return int(s.replace(",", ""))


def total_row(text: str) -> int | None:
    """The last figure of the first Total row (the crossings table comes first)."""
    for line in text.split("\n"):
        if re.match(r"\s*Total\b", line):
            nums = _N.findall(line)
            if nums:
                return _n(nums[-1])
    return None


def subtotal_rows(text: str) -> tuple[dict[int, int], list[str]]:
    """{week: trucks} from the first Subtotal row of each week whose columns
    add up to its last figure, and a note for every row passed over because
    they do not. Measured: the crossings table of weeks 82-83 prints 1,749
    for week 82, its own columns (1,404 + 260 + 14) make 1,678, and so do the
    report's private and humanitarian rows (976 + 702) and its text."""
    out: dict[int, int] = {}
    passed_over: list[str] = []
    for wk, vals in re.findall(r"^[ \t]*Subtotal[ \t]+\d+[ \t]+\(Week[ \t]+(\d+)\)[ \t]+([\d, \t]+)$", text, flags=re.M):
        nums = [_n(x) for x in _N.findall(vals)]
        if int(wk) in out or len(nums) < 2:
            continue
        if sum(nums[:-1]) == nums[-1]:
            out[int(wk)] = nums[-1]
        else:
            passed_over.append(f"week {wk}: a Subtotal row prints {nums[-1]:,} where its columns make {sum(nums[:-1]):,}")
    return out, passed_over


def looted_sentences(text: str) -> dict[int, tuple[int, int, int]]:
    flat = re.sub(r"\s+", " ", text)
    return {int(m.group(1)): tuple(_n(x) for x in m.groups()[1:])
            for m in re.finditer(r"Week (\d+) \([^)]*\),? ([\d,]+) trucks (?:arrived|entered)[^(]{0,20}"
                                 r"\(([\d,]+) looted, ([\d,]+) delivered\)", flat)}


def dated_elsewhere(item: dict) -> bool:
    """True when a report's tables carry day dates and none falls in the period
    the report is listed for. Measured: the file linked for week 6 (5 to 11
    September 2024) is week 7's report, its tables dated 12 to 18 September."""
    start = datetime.date.fromisoformat(item["start"])
    end = datetime.date.fromisoformat(item["date"][:10])
    days = []
    for d, m, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", item["text"]):
        try:
            days.append(datetime.date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return bool(days) and not any(start <= x <= end for x in days)


def week_periods(item: dict) -> dict[int, tuple[str, str]]:
    """Each week's first and last day: a one-week report is its own period; a
    two-week report splits at seven days."""
    start = datetime.date.fromisoformat(item["start"])
    end = datetime.date.fromisoformat(item["date"][:10])
    weeks = item["weeks"]
    if len(weeks) == 1:
        return {weeks[0]: (start.isoformat(), end.isoformat())}
    mid = start + datetime.timedelta(days=7)
    return {weeks[0]: (start.isoformat(), (mid - datetime.timedelta(days=1)).isoformat()),
            weeks[1]: (mid.isoformat(), end.isoformat())}


def build(items: list[dict], by_hand: dict) -> tuple[list[dict], dict]:
    figures: dict[int, dict] = {}
    periods: dict[int, tuple[str, str, dict]] = {}
    notes: dict = {"reports": len(items), "weeks_without_a_figure": [], "by_hand": [], "from_tables": 0}
    for item in sorted(items, key=lambda i: i["weeks"]):
        for wk, (a, b) in week_periods(item).items():
            periods[wk] = (a, b, item)
        weeks = item["weeks"]
        text = item["text"]
        if dated_elsewhere(item):
            notes.setdefault("reports_whose_tables_are_another_period", []).append(
                {"weeks": weeks, "listed_for": [item["start"], item["date"][:10]], "report": item["link"]})
            continue
        if max(weeks) <= 31:
            t = total_row(text)
            if t is None:
                raise Refused(f"week {weeks[0]}: no Total row in the crossings table")
            figures.setdefault(weeks[0], {})["trucks_entered"] = (t, "the crossings table's Total row")
            notes["from_tables"] += 1
        elif min(weeks) >= 51:
            subs, passed_over = subtotal_rows(text)
            if passed_over:
                notes.setdefault("publisher_rows_that_do_not_add_up", []).extend(passed_over)
            if all(w in subs for w in weeks):
                stated = total_row(text)
                if stated is not None and stated != sum(subs[w] for w in weeks):
                    # the Total row of the first table must agree with the weeks chosen
                    raise Refused(f"weeks {weeks}: the weekly rows add to {sum(subs[w] for w in weeks)}, the table says {stated}")
                for w in weeks:
                    basis = f"the report's Subtotal row for week {w}"
                    if any(s.startswith(f"week {w}:") for s in passed_over):
                        basis += " (the crossings table's own row for this week does not add up; see the dataset's notes)"
                    figures.setdefault(w, {})["trucks_entered"] = (subs[w], basis)
                    notes["from_tables"] += 1
            for w, (entered, looted, delivered) in looted_sentences(text).items():
                if w not in weeks:
                    continue
                held = figures.get(w, {}).get("trucks_entered")
                if held and held[0] != entered:
                    raise Refused(f"week {w}: the sentence says {entered} trucks, the table {held[0]}")
                if looted + delivered != entered:
                    raise Refused(f"week {w}: {looted} looted and {delivered} delivered do not make {entered}")
                figures.setdefault(w, {})["trucks_looted"] = (looted, "the report's sentence for the week")
                figures[w]["trucks_delivered"] = (delivered, "the report's sentence for the week")
    for w, row in (by_hand.get("weeks") or {}).items():
        w = int(w)
        for m in MEASURES:
            if m in row:
                if m in figures.get(w, {}) and figures[w][m][0] != row[m]:
                    raise Refused(f"week {w}: by hand {m} = {row[m]}, the table {figures[w][m][0]}")
                figures.setdefault(w, {})[m] = (int(row[m]), "read by hand: " + row["quote"])
        notes["by_hand"].append(w)
    records = []
    for w in sorted(periods):
        a, b, item = periods[w]
        if w not in figures:
            notes["weeks_without_a_figure"].append(w)
            continue
        for m, (value, basis) in figures[w].items():
            records.append({
                "stable_id": f"gazacham:week{w:03d}:{m}", "measure": m, "value": value, "unit": "truck",
                "date": a, "period_start": a, "period_end": b, "week": w,
                "basis": basis[:400], "report": item["link"], "report_title": item["title"],
                "indicator_name": {"trucks_entered": "Trucks entered Gaza", "trucks_looted": "Trucks looted",
                                   "trucks_delivered": "Trucks delivered"}[m],
                "location": {"region": "Gaza Strip"},
                "sources": [{"name": SOURCE_NAME, "organization": "Gaza Chamber of Commerce and Industry",
                             "url": item["link"]}]})
    return records, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="read and check, write nothing")
    ap.add_argument("--reports", type=Path, default=REPORTS)
    a = ap.parse_args()
    with gzip.open(a.reports, "rt", encoding="utf-8") as fh:
        items = [json.loads(line) for line in fh]
    try:
        records, notes = build(items, yaml.safe_load(BY_HAND.read_text(encoding="utf-8")))
    except Refused as e:
        print(f"REFUSED: {e}")
        return 1
    weeks = sorted({r["week"] for r in records if r["measure"] == "trucks_entered"})
    newest = max(i["date"][:10] for i in items)
    print(f"{len(records)} figures · trucks entered for {len(weeks)} weeks ({weeks[0]}-{weeks[-1]}) · looted for "
          f"{sum(1 for r in records if r['measure'] == 'trucks_looted')} weeks · no figure: {notes['weeks_without_a_figure']}")
    if a.check:
        return 0
    doc = {"metadata": {"source": SOURCE_NAME, "source_url": "https://gazacham.ps/InformationCenter/Reports",
                        "vintage": newest, "vintage_basis": "the last day of the newest report read",
                        "vintage_url": "https://gazacham.ps/InformationCenter/Reports",
                        "license": "\"All rights reserved, 2023, Gaza Chamber of Commerce and Industry\" in the site footer "
                                   "(no-license-found)",
                        "attribution": "Trucks into Gaza: Gaza Chamber of Commerce and Industry, Gaza Movement of Goods "
                                       "weekly reports (gazacham.ps).",
                        "built_from": str(a.reports.relative_to(ROOT)) if a.reports.is_relative_to(ROOT) else str(a.reports),
                        **notes},
           "data": records}
    fetchlib.write_atomic(OUT, doc)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
