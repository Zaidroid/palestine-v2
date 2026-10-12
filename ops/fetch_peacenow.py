"""Fetch Peace Now's West Bank settler population by year — the v1 supply
line `peacenow-settlers` (scripts/sources/peacenow-settlements.js).

WHAT PEACE NOW PUBLISHES. Settlement Watch's Population page draws one line
chart whose year axis and values sit in the page's own script: 51 years,
"1967" to "2024", 0 to 511,100 settlers (East Jerusalem excluded), caption
"Source: Israeli CBS". This reads the two arrays; no browser.

WHICH YEAR A FIGURE BELONGS TO (measured 2026-10-12, because the page
contradicts itself). The chart puts 511,100 under "2024" and 503,732 under
"2023". Two pie charts higher on the same page show the same 511,100 with the
captions "Source: Israeli and Palestinian CBS, end of 2023" and "Source:
Israeli CBS, end of 2023". The chart is right and the captions are stale:
Israel's Central Bureau of Statistics gives the Judea and Samaria Area 1.5
thousand in 1972, 23.7 in 1983, 134.3 in 1995, 281.1 in 2008, 465.4 at the end
of 2021, 478.6 at the end of 2022 and 501.1 (Israelis; 504.7 with foreigners)
at the end of 2023 (Statistical Abstract 2023 table 2.17, 2024 tables 2.15 and
2.17), and the chart carries exactly 1,500 / 23,700 / 134,300 / 281,100 /
465,400 / 478,600 under those years. No end-of-2023 count reaches 511,100. So
a label is the figure's own year, the figure is that year's end-of-year
count, and `date` is written `<year>-12-31` as v1 wrote it. The spec then
stores it as that year, precision year (settlements.yaml).

WHAT IT WRITES. data/raw/peacenow/settlers.json in the record shape
db/mappings/settlements.yaml already transforms, so all 51 held rows are
matched on their identity (indicator + year) and a figure Peace Now revises
supersedes the held one.

LICENCE: the site states none; its footer reads "© 2026 Peace Now". Source
row `peace_now`, no licence found, no redistribution.

Posture (ops/fetchlib.py): atomic, floored, ledgered. One request a night,
with the project's own User-Agent (v1 sent a browser's).

Run: .venv/bin/python -m ops.fetch_peacenow
     .venv/bin/python -m ops.fetch_peacenow --dry-run
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

PAGE = "https://peacenow.org.il/en/settlements-watch/settlements-data/population"
OUT = fl.ROOT / "data" / "raw" / "peacenow" / "settlers.json"
LABEL = "peacenow:settlers"
SOURCE_NAME = "Peace Now — Settlement Watch"   # exactly as settlements.yaml routes it

MIN_YEARS = 46            # 0.9 x 51 years measured 2026-10-12

_YEARS = re.compile(r'categories:\s*(\["1967".*?\])', re.S)
_SERIES = re.compile(r"data:\s*(\[[^\]]*\])")
_SCRIPT = re.compile(r"<script.*?</script>", re.S)
_CAPTION = re.compile(r"Source:[^<\n]{3,120}")


class PageChanged(ValueError):
    """The page no longer holds the chart this was written against."""


def parse_population(page: str) -> list[tuple[int, int]]:
    """(year, settlers) for every point of the population chart."""
    m = _YEARS.search(page)
    if not m:
        raise PageChanged("no year axis starting at 1967")
    years = [int(y) for y in json.loads(m.group(1))]
    fits = []
    for s in _SERIES.finditer(page):
        try:
            arr = json.loads(s.group(1))
        except ValueError:
            continue                      # the pies hold ["", n] pairs
        if len(arr) == len(years) and all(
                isinstance(x, (int, float)) and not isinstance(x, bool)
                for x in arr):
            fits.append(arr)
    if len(fits) != 1:
        raise PageChanged(f"{len(fits)} numeric series as long as the year "
                          f"axis ({len(years)}), expected exactly one")
    if len(set(years)) != len(years) or years != sorted(years):
        raise PageChanged("the year axis repeats or is out of order")
    return [(y, int(n)) for y, n in zip(years, fits[0])]


def captions(page: str) -> list[str]:
    """The page's own "Source: ..." lines, in order, as it words them."""
    return [htmllib.unescape(c).strip()
            for c in _CAPTION.findall(_SCRIPT.sub("", page))]


def year_records(points: list[tuple[int, int]], fetched_at: str) -> list[dict]:
    src = {"name": SOURCE_NAME, "organization": "Peace Now", "url": PAGE,
           "license": "no licence stated (© Peace Now)",
           "fetched_at": fetched_at}
    return [{
        "stable_id": f"peacenow-settlers:{year}",
        "id": f"peacenow-settlers-{year}",
        "date": f"{year}-12-31",               # the year's end-of-year count
        "year": year,
        "event_type": "settler_population",
        "indicator_name": "Population",        # the chart's own series name
        "location": {"name": "West Bank", "region": "West Bank"},
        "metrics": {"count": n, "value": n, "unit": "settlers"},
        "sources": [src]} for year, n in points]


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    try:
        raw = fl.get(PAGE, timeout=60)
        page = raw.decode("utf-8", "replace")
        points = parse_population(page)
    except Exception as e:                                   # noqa: BLE001
        print(f"  FAIL {LABEL}: {type(e).__name__}: {e}")
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:200])
        return 1
    if len(points) < MIN_YEARS:
        print(f"  REFUSED {LABEL}: {len(points)} years below the floor of "
              f"{MIN_YEARS} — keeping the file already on disk")
        if not dry:
            fl.event(LABEL, "refused", rows=len(points), floor=MIN_YEARS)
        return 1
    fetched_at = datetime.now(timezone.utc).isoformat()
    recs = year_records(points, fetched_at)
    (y0, _), (y1, n1) = points[0], points[-1]
    print(f"  ok   {LABEL}  {len(recs)} years {y0} → {y1}, "
          f"latest {n1:,} settlers (end of {y1})")
    doc = {"metadata": {
        "fetched_at": fetched_at,
        "source": "Peace Now — Settlement Watch, Population",
        "source_url": PAGE,
        "vintage": str(y1),
        "vintage_basis": "the last year on the population chart's axis; each "
                         "point is the Israeli CBS end-of-year count for the "
                         "labelled year. The page's own captions are in "
                         "page_captions (two pie captions can lag the chart)",
        "vintage_url": PAGE,
        "page_captions": captions(page),
        "coverage": "West Bank, excludes East Jerusalem",
        "license": "no licence stated; footer \"© Peace Now\" (no-license-found)",
        "attribution": "Settler population: Peace Now (Settlement Watch), "
                       "peacenow.org.il; figures from the Israeli CBS.",
        "years": len(recs), "first_year": y0, "last_year": y1},
        "data": recs}
    if dry:
        print(f"         would write {OUT.relative_to(fl.ROOT)} and 1 bronze "
              "payload under peace_now  (dry run, nothing written)")
        fl.stage(fl.stage_dir(argv), OUT.name, doc)
        return 0
    from ingest import bronze
    doc["metadata"]["bronze"] = bronze.put("peace_now", raw, "html", url=PAGE).ref
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=len(recs), data_through=str(y1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
