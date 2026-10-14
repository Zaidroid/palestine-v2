"""Fetch Addameer's monthly prisoner statistics — the v1 supply line
`prisoners` (scripts/fetch-prisoners.js), the last reader of v1's unified
prisoners file.

WHAT ADDAMEER PUBLISHES on addameer.ps/statistics (one page, read once):

  - a dated block, "date of statistics" (05-10-2026 on 2026-10-12), with the
    current figures by label: total, administrative detainees, child
    prisoners, female prisoners and others;
  - three charts whose series sit in `data-chart` attributes as JSON, months
    newest first over a rolling window of about fourteen entries: "Total
    Number of Political Prisoners", "Administrative Detainees" and "East
    Jerusalem prisoners".

WHAT IS LOADED, the same four series v1 loaded into v1_prisoners_addameer:
total and administrative from the charts (a month per point), child and
female from the dated block (the charts do not carry them). The East
Jerusalem chart and the block's other labels are kept in the raw file's
metadata and not loaded: v1 did not load them, and this line does not widen.

ONE DATE v1 GOT WRONG, corrected here. v1 dated the block's child and female
figures by the month IT RAN in. A run on the first days of a month, before
Addameer posts that month's block, filed last month's figures under the new
month (the store's 2026-10 child row was written on 1 October; the block is
dated 5 October). This reads the block's own date and files the two figures
under that month. A page with no readable block date yields no child or
female row rather than a guessed one.

THE WINDOW ROLLS. Months that leave the charts stay in the databank (22 held
months against 14 on the page); identity is indicator + month and nothing
declares the window complete.

TWO DOORS, as v1 had: addameer.ps has served an expired TLS certificate for
weeks at a time, so when the site itself does not answer with the charts, the
newest 200-status capture of the same page in the Internet Archive is read
byte for byte (`id_` mode) and recorded as `via: wayback:<timestamp>`. A
capture carries its own block date, so its figures are still filed under the
right month.

LICENCE: the page footer reads "Addameer, All rights reserved ©2021". Source
row `addameer`, no licence found, no redistribution.

Posture (ops/fetchlib.py): atomic, floored, ledgered. One request a night.

Run: .venv/bin/python -m ops.fetch_addameer
     .venv/bin/python -m ops.fetch_addameer --dry-run
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

PAGE = "https://www.addameer.ps/statistics"
CDX = ("https://web.archive.org/cdx/search/cdx?url=addameer.ps/statistics"
       "&output=json&filter=statuscode:200&fl=timestamp,statuscode,digest"
       "&limit=-5")
WAYBACK = "https://web.archive.org/web/{ts}id_/" + PAGE
OUT = fl.ROOT / "data" / "raw" / "addameer" / "statistics.json"
LABEL = "addameer:statistics"
SOURCE_NAME = "Addameer Prisoner Support and Human Rights Association"  # as prisoners.yaml routes it

# 14 months x 2 chart series + child + female = 30 on 2026-10-12. Below ten
# months of both series the page is not the page we know.
MIN_RECORDS = 20

_CHART = re.compile(r'data-chart="([^"]+)"')
_BLOCK_DATE = re.compile(
    r'field-date-of-statistics.*?<time datetime="(\d{4}-\d{2}-\d{2})', re.S)
_FIELD = re.compile(
    r'<span class="views-label[^"]*">\s*([^<]+?)\s*</span>\s*'
    r'<div class="field-content">\s*([\d,]+)\s*</div>')
_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")


def classify(series_name: str | None) -> str | None:
    """Addameer's series name → the databank's metric. v1's mapping."""
    n = (series_name or "").lower()
    if "total number" in n or "total prisoners" in n:
        return "total"
    if "administrative" in n:
        return "administrative"
    if "child" in n:
        return "child"
    if "female" in n or "women" in n:
        return "female"
    # The block's other figures, added 2026-10-14 (each on about 168 monthly
    # pages since 2011). Order matters: the unlawful-combatant line names Gaza.
    if "1948" in n:
        return "from_1948"
    if "jerusalem" in n:                     # "Jerusalemite prisoners"; the chart's "East Jerusalem prisoners"
        return "jerusalem"
    if "legislative council" in n:
        return "legislative_council"
    if "life sentence" in n:
        return "life_sentence"
    if "unlawful combatant" in n:
        return "unlawful_combatants"
    if "gaza" in n:
        return "gaza"
    if "before oslo" in n:
        return "pre_oslo"
    # Left on the page, not loaded: "serving more than 20 / 25 years" and "a
    # sentence above 20 years" (two readings of twenty years that cannot be told
    # apart over the run), the running count of arrests since 7 October 2023
    # (nine pages, counted in arrests, not persons) and the deaths in custody
    # since 1967 (two pages).
    return None


def month_start(label) -> str | None:
    """'2026-10\\n' → '2026-10-01'."""
    m = _MONTH.match(str(label or "").strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-01"


def charts(page: str) -> list[dict]:
    out = []
    for raw in _CHART.findall(page):
        try:
            c = json.loads(htmllib.unescape(raw))
        except ValueError:
            continue
        if isinstance(c, dict):
            out.append(c)
    return out


def chart_points(page: str) -> tuple[dict, dict]:
    """({(month, metric): (count, the publisher's name for the series)},
    {series name: points} for the series this line does not load). The first
    reading of a month wins."""
    loaded: dict[tuple[str, str], tuple[int, str]] = {}
    other: dict[str, dict] = {}
    for c in charts(page):
        x = c.get("xAxis")
        x = x[0] if isinstance(x, list) and x else x
        cats = (x or {}).get("categories") if isinstance(x, dict) else None
        cats = cats or c.get("categories") or []
        for s in c.get("series") or []:
            data = s.get("data")
            if not isinstance(data, list):
                continue
            metric = classify(s.get("name"))
            for label, point in zip(cats, data):
                day = month_start(label)
                n = point.get("y") if isinstance(point, dict) else point
                if day is None or isinstance(n, bool) or \
                        not isinstance(n, (int, float)):
                    continue
                if metric is None:
                    other.setdefault(str(s.get("name")), {}).setdefault(day, n)
                else:
                    loaded.setdefault((day, metric), (int(n), str(s.get("name"))))
    return loaded, other


def statistics_block(page: str) -> tuple[str | None, dict]:
    """(the block's own date, {label: figure}) — Addameer's current numbers."""
    m = _BLOCK_DATE.search(page)
    fields = {}
    for label, num in _FIELD.findall(page):
        label = htmllib.unescape(label).strip().rstrip(":").strip()
        fields.setdefault(label, int(num.replace(",", "")))
    return (m.group(1) if m else None), fields


def month_records(page: str, via: str, fetched_at: str) -> tuple[list[dict], dict]:
    """Records in the shape t_prisoners reads, and what was read beside them."""
    points, other = chart_points(page)
    block_day, block = statistics_block(page)
    notes = {"block_date": block_day, "statistics_block": block,
             "series_not_loaded": other}
    if block_day:
        month = block_day[:7] + "-01"
        for label, n in block.items():
            metric = classify(label)
            if metric is not None:                # the chart's reading of a month wins where it has one
                points.setdefault((month, metric), (n, label))
        # the block and the chart state the same month's total; say so if not
        total = next((n for label, n in block.items()
                      if classify(label) == "total"), None)
        charted = points.get((month, "total"))
        if total is not None and charted and charted[0] != total:
            notes["block_total_differs_from_chart"] = {
                "month": month, "block": total, "chart": charted[0]}
    else:
        notes["no_block_date"] = "child and female not filed: no date to file them under"
    src = {"name": SOURCE_NAME, "organization": SOURCE_NAME, "url": PAGE,
           "license": "all rights reserved (no-license-found)",
           "via": via, "fetched_at": fetched_at}
    recs = [{
        "stable_id": f"addameer:{day}:{metric}",
        "id": f"addameer_{metric}_{day}",
        "date": day,
        "event_type": "prisoners_count",
        "prisoner_metric_type": metric,
        "indicator_name": name,                # Addameer's own wording
        "location": {"name": "West Bank & Gaza", "region": "Palestine"},
        "metrics": {"count": n, "unit": "persons"},
        "sources": [src]}
        for (day, metric), (n, name) in sorted(
            points.items(), key=lambda kv: (kv[0][0], kv[0][1]), reverse=True)]
    return recs, notes


def _get(url: str, ua: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": ua, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_capture(cdx_rows) -> str | None:
    """Newest 200-status timestamp from a CDX JSON answer (header row first)."""
    rows = [r for r in (cdx_rows or [])[1:] if len(r) >= 2 and r[1] == "200"]
    return max((r[0] for r in rows), default=None)


def fetch(get=_get) -> tuple[str, str, bytes, str]:
    """(html, via, raw bytes, url) — Addameer first, then the archive."""
    errors = []
    try:
        raw = get(PAGE, fl.UA)
        page = raw.decode("utf-8", "replace")
        if _CHART.search(page):
            return page, "direct", raw, PAGE
        errors.append("direct: 200 without charts")
    except urllib.error.HTTPError as e:
        errors.append(f"direct: HTTP {e.code}")
        if e.code in (403, 429):
            # the site said no to this client; the archive is not a way round it
            raise OSError("; ".join(errors)) from e
    except (urllib.error.URLError, OSError) as e:
        errors.append(f"direct: {type(e).__name__}")
    try:
        ts = latest_capture(json.loads(get(CDX, fl.UA)))
        if not ts:
            raise ValueError("no 200 capture in the archive")
        url = WAYBACK.format(ts=ts)
        raw = get(url, fl.UA, timeout=120)
        page = raw.decode("utf-8", "replace")
        if not _CHART.search(page):
            raise ValueError(f"capture {ts} holds no charts")
        return page, f"wayback:{ts}", raw, url
    except (urllib.error.URLError, OSError, ValueError) as e:
        errors.append(f"wayback: {type(e).__name__}: {str(e)[:80]}")
    raise OSError("; ".join(errors))


HISTORY = OUT.parent / "history.json"
HISTORY_LABEL = "addameer:history"
MONTH_PAGE = "https://www.addameer.ps/statistics/{y}/{m:02d}"
MIN_HISTORY = 400            # 170 months × 4 series on 2026-10-13, less the months the nightly file carries


def history_records(pages: dict[str, str], skip: set[tuple[str, str]],
                    fetched_at: str) -> tuple[list[dict], dict]:
    """Addameer keeps one page a month (statistics/YYYY/MM), each with that
    month's dated block. `pages` maps "YYYY-MM" to a page; the records are the
    four series the databank already names (total, administrative, child,
    female), filed under the block's own month, in the shape t_prisoners
    reads. `skip` is the (month, series) pairs the nightly file carries, so
    one month never arrives from two files."""
    recs, seen = [], set()
    notes: dict = {"pages": len(pages), "no_block": [], "block_in_another_month": []}
    for ym in sorted(pages):
        day, block = statistics_block(pages[ym])
        if not day or not block:
            notes["no_block"].append(ym)
            continue
        if day[:7] != ym:
            notes["block_in_another_month"].append({"page": ym, "block": day})
        month = day[:7] + "-01"
        url = MONTH_PAGE.format(y=int(ym[:4]), m=int(ym[5:7]))
        src = {"name": SOURCE_NAME, "organization": SOURCE_NAME, "url": url,
               "license": "all rights reserved (no-license-found)", "via": "direct",
               "fetched_at": fetched_at, "block_date": day}
        for label, n in block.items():
            metric = classify(label)
            if metric is None or (month, metric) in skip or (month, metric) in seen:
                continue
            seen.add((month, metric))
            recs.append({
                "stable_id": f"addameer:{month}:{metric}",
                "id": f"addameer_{metric}_{month}",
                "date": month,
                "event_type": "prisoners_count",
                "prisoner_metric_type": metric,
                "indicator_name": label,
                "location": {"name": "West Bank & Gaza", "region": "Palestine"},
                "metrics": {"count": n, "unit": "persons"},
                "sources": [src]})
    recs.sort(key=lambda r: (r["date"], r["prisoner_metric_type"]), reverse=True)
    notes["months"] = len({r["date"] for r in recs})
    notes["newest_block"] = max((r["sources"][0]["block_date"] for r in recs), default=None)
    return recs, notes


def history(argv: list[str]) -> int:
    """`--history [--from-dir DIR]`: the monthly pages since January 2011,
    once each, two seconds apart (or the pages already saved in DIR as
    YYYY-MM.html). Run by hand when the back months are wanted again; the
    nightly run reads the current page only."""
    import time
    import urllib.error
    dry = "--dry-run" in argv
    pages: dict[str, str] = {}
    if "--from-dir" in argv:
        d = Path(argv[argv.index("--from-dir") + 1])
        for f in sorted(d.glob("[12][0-9][0-9][0-9]-[01][0-9].html")):
            pages[f.stem] = f.read_text(encoding="utf-8", errors="replace")
    else:
        now = datetime.now(timezone.utc)
        for y in range(2011, now.year + 1):
            for m in range(1, 13):
                if (y, m) > (now.year, now.month):
                    break
                try:
                    pages[f"{y}-{m:02d}"] = _get(MONTH_PAGE.format(y=y, m=m), fl.UA).decode("utf-8", "replace")
                except urllib.error.HTTPError as e:
                    if e.code != 404:            # a month with no page is skipped; a refusal ends the walk
                        print(f"  FAIL {HISTORY_LABEL}: HTTP {e.code} at {y}-{m:02d}; keeping the file on disk")
                        if not dry:
                            fl.event(HISTORY_LABEL, "refused", error=f"HTTP {e.code}", at_month=f"{y}-{m:02d}")
                        return 1
                time.sleep(2.0)
    skip: set[tuple[str, str]] = set()
    if OUT.exists():
        skip = {(r["date"], r["prisoner_metric_type"]) for r in json.loads(OUT.read_text())["data"]}
    fetched_at = datetime.now(timezone.utc).isoformat()
    recs, notes = history_records(pages, skip, fetched_at)
    if len(recs) < MIN_HISTORY:
        print(f"  REFUSED {HISTORY_LABEL}: {len(recs)} records below the floor of {MIN_HISTORY}"
              " — keeping the file already on disk")
        if not dry:
            fl.event(HISTORY_LABEL, "refused", rows=len(recs), floor=MIN_HISTORY)
        return 1
    months = sorted({r["date"] for r in recs})
    print(f"  ok   {HISTORY_LABEL}  {len(months)} months {months[0][:7]} → {months[-1][:7]}, {len(recs)} records"
          f" from {notes['pages']} pages ({len(notes['no_block'])} with no block)")
    doc = {"metadata": {
        "fetched_at": fetched_at,
        "source": "Addameer Prisoner Support and Human Rights Association — Statistics, the monthly pages",
        "source_url": PAGE, "via": "direct",
        # No `vintage` here on purpose: the nightly file states the dataset's
        # vintage (the current block's date). This file is the back months, and
        # its newest block is older than that; each record carries its own
        # block date in sources[0].block_date.
        "license": "\"All rights reserved\" in the page footer (no-license-found); attribution",
        "attribution": "Prisoner statistics: Addameer Prisoner Support and Human Rights Association (addameer.ps).",
        "first_month": months[0][:7], "data_through": months[-1][:7], **notes},
        "data": recs}
    if dry:
        print(f"         would write {HISTORY.relative_to(fl.ROOT)}  (dry run, nothing written)")
        fl.stage(fl.stage_dir(argv), HISTORY.name, doc)
        return 0
    from ingest import bronze
    for ym, page in pages.items():
        bronze.put("addameer", page, "html", url=MONTH_PAGE.format(y=int(ym[:4]), m=int(ym[5:7])))
    fl.write_atomic(HISTORY, doc)
    fl.event(HISTORY_LABEL, "ok", rows=len(recs), months=len(months), first=months[0][:7],
             data_through=months[-1][:7])
    return 0


def main(argv: list[str]) -> int:
    if "--history" in argv:
        return history(argv)
    dry = "--dry-run" in argv
    try:
        page, via, raw, url = fetch()
    except OSError as e:
        print(f"  FAIL {LABEL}: {e}")
        if not dry:
            fl.event(LABEL, "error", error=str(e)[:200])
        return 1
    fetched_at = datetime.now(timezone.utc).isoformat()
    recs, notes = month_records(page, via, fetched_at)
    if len(recs) < MIN_RECORDS:
        print(f"  REFUSED {LABEL}: {len(recs)} records below the floor of "
              f"{MIN_RECORDS} (via {via}) — keeping the file already on disk")
        if not dry:
            fl.event(LABEL, "refused", rows=len(recs), floor=MIN_RECORDS, via=via)
        return 1
    months = sorted({r["date"] for r in recs})
    last = months[-1][:7]
    latest = {r["prisoner_metric_type"]: r["metrics"]["count"]
              for r in recs if r["date"] == months[-1]}
    print(f"  ok   {LABEL}  {len(months)} months {months[0][:7]} → {last}, "
          f"{len(recs)} records, via {via}")
    print(f"         latest {last} (block dated {notes['block_date']}): "
          + " · ".join(f"{k} {v:,}" for k, v in sorted(latest.items())))
    doc = {"metadata": {
        "fetched_at": fetched_at,
        "source": "Addameer Prisoner Support and Human Rights Association — "
                  "Statistics",
        "source_url": PAGE, "via": via, "read_url": url,
        "vintage": notes["block_date"],
        "vintage_basis": "the page's own \"date of statistics\" on its "
                         "current block; chart points are labelled by month",
        "vintage_url": PAGE,
        "license": "\"All rights reserved\" in the page footer "
                   "(no-license-found); attribution",
        "attribution": "Prisoner statistics: Addameer Prisoner Support and "
                       "Human Rights Association (addameer.ps).",
        "months": len(months), "first_month": months[0][:7],
        "data_through": last, **notes},
        "data": recs}
    if dry:
        print(f"         would write {OUT.relative_to(fl.ROOT)} and 1 bronze "
              "payload under addameer  (dry run, nothing written)")
        fl.stage(fl.stage_dir(argv), OUT.name, doc)
        return 0
    from ingest import bronze
    doc["metadata"]["bronze"] = bronze.put("addameer", raw, "html", url=url).ref
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=len(recs), via=via, data_through=last)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
