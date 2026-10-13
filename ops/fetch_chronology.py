"""Read a published chronology of dated events into the archive's raw tree.

    .venv/bin/python -m ops.fetch_chronology palquest
    .venv/bin/python -m ops.fetch_chronology palquest --from-file page.html   # parse a page already in hand

WHY. Zaid, 13 October 2026: the archive should reach "as much as possible
from 1948". Channels begin in the 2010s and outlets' archives around 2000;
for the decades before, the dated backbone is the chronologies scholars have
already compiled. The first is the Interactive Encyclopedia of the Palestine
Question (the Institute for Palestine Studies with the Palestinian Museum):
its whole "overall chronology" is one page, measured that day at 2,541 events
from 1516 to 2026, each with a date or a date range, a title and one or more
of twelve kinds (Diplomatic, Violence, Colonization, Legal ...).

ONE REQUEST. The page is asked for once (the site's robots file sets a
crawl-delay of ten seconds and forbids only the chronology's query forms,
which this does not use). The event descriptions load by script and are not
taken; an entry is its date, title and kinds, with a link to the event.

THE POSTURE (ops/fetchlib.py): atomic, FLOORED (fewer than 2,000 events is
refused and the file on disk is kept), ledgered as `chronology:<key>`.

WHAT IT WRITES, under data/raw/chronology/<key>/:
  entries.ndjson.gz   one event a line: id, date, precision (day | month |
                      year), end and end_precision when it is a range,
                      date_text as published, title, tags, url
  site.json           the publisher, as the loader needs it
and the page as it arrived, gzipped, in bronze (`chron_<key>`).
"""
from __future__ import annotations

import argparse
import gzip
import html as html_mod
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                                       # noqa: E402
from ops import fetchlib                                        # noqa: E402

UA = "palestine-v2 archive reader (personal research)"
OUT = ROOT / "data" / "raw" / "chronology"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
SITES = {
    "palquest": {"name": "Interactive Encyclopedia of the Palestine Question, overall chronology"
                         " (Institute for Palestine Studies and the Palestinian Museum)",
                 "home_url": "https://www.palquest.org/en/overallchronology",
                 "page": "https://www.palquest.org/en/timeline/overallchronology-slim1",
                 "source": "chron:palquest", "floor": 2000},
}
_EVENT = re.compile(r'<article\s+data-sideview="\d+"\s+data-timelineyear="(-?\d+)"\s+data-id="(\d+)"\s+'
                    r'class="node node-event tl clearfix"\s*>(.*?)</article>', re.S)
_TITLE = re.compile(r'<a\s+href="/en/overallchronology#\d+"\s*>\s*(.*?)\s*</a>', re.S)
_DATE = re.compile(r'<div\s+class="text-12 karla upper black"\s*>\s*(.*?)\s*</div>', re.S)
_TAG = re.compile(r'<span\s+style="color:\s*#[0-9a-fA-F]+"\s*>([^<]+)</span>')
_WHEN = re.compile(r"^(?:(\d{1,2})\s+)?(?:([A-Za-z]+)\s+)?(\d{3,4})$")


def _text(s: str) -> str:
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def one_date(s: str) -> tuple[str, str] | None:
    """'5 January 1996' | 'July 1872' | '1605' → (ISO day, precision)."""
    m = _WHEN.match(s.strip())
    if not m:
        return None
    day, month, year = m.groups()
    if month and month.lower() not in MONTHS:
        return None
    mo = MONTHS[month.lower()] if month else 1
    precision = "day" if day else ("month" if month else "year")
    return f"{int(year):04d}-{mo:02d}-{int(day or 1):02d}", precision


def when(s: str) -> dict | None:
    """A date or a range as published → date, precision and, for a range, end
    and end_precision. None when the text is not a date this rule knows."""
    parts = [p.strip() for p in re.split(r"\s+[-–]\s+", s.strip())]
    if len(parts) > 2:
        return None
    a = one_date(parts[0])
    if a is None:
        return None
    out = {"date": a[0], "precision": a[1]}
    if len(parts) == 2:
        b = one_date(parts[1])
        if b is None:
            return None
        out.update(end=b[0], end_precision=b[1])
    return out


def parse_palquest(page: str) -> tuple[list[dict], int]:
    """The page → its events, each once (the page repeats an event under every
    year a range touches), and how many date texts were not understood."""
    seen: dict[str, dict] = {}
    odd = 0
    for _year, eid, body in _EVENT.findall(page):
        if eid in seen:
            continue
        t, d = _TITLE.search(body), _DATE.search(body)
        if not (t and d):
            odd += 1
            continue
        date_text = _text(d.group(1))
        w = when(date_text)
        if w is None:
            odd += 1
            continue
        seen[eid] = {"id": eid, **w, "date_text": date_text, "title": _text(t.group(1)),
                     "tags": [html_mod.unescape(x).strip() for x in _TAG.findall(body)],
                     "url": f"https://www.palquest.org/en/overallchronology#{eid}"}
    return sorted(seen.values(), key=lambda e: (e["date"], int(e["id"]))), odd


def run(key: str, out: Path, from_file: Path | None, use_bronze: bool) -> int:
    site = SITES[key]
    label = f"chronology:{key}"
    try:
        if from_file:
            page = from_file.read_text(encoding="utf-8", errors="replace")
        else:
            req = urllib.request.Request(site["page"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                page = r.read().decode("utf-8", "replace")
    except Exception as e:                                       # noqa: BLE001
        fetchlib.event(label, "failed", why=f"{type(e).__name__}: {e}"[:200])
        print(f"{key}: not read ({type(e).__name__}); the file on disk is kept")
        return 1
    entries, odd = parse_palquest(page)
    try:
        fetchlib.check_floor(label, len(entries), site["floor"])
    except fetchlib.FetchRefused as e:
        print(str(e))
        return 2
    d = out / key
    d.mkdir(parents=True, exist_ok=True)
    if use_bronze:
        bronze.put(f"chron_{key}", page, "html", url=site["page"])
    body = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries).encode("utf-8")
    tmp = d / "entries.ndjson.gz.tmp"
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(body)
    tmp.replace(d / "entries.ndjson.gz")
    (d / "site.json").write_text(json.dumps(
        {"key": key, "name": site["name"], "home_url": site["home_url"], "source": site["source"]},
        ensure_ascii=False, indent=1))
    fetchlib.event(label, "ok", rows=len(entries), not_understood=odd,
                   first=entries[0]["date"], last=entries[-1]["date"])
    print(f"{key}: {len(entries):,} events, {entries[0]['date']} to {entries[-1]['date']}"
          f" · date texts not understood: {odd}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sites", nargs="+", choices=sorted(SITES))
    ap.add_argument("--from-file", type=Path, help="parse a page already in hand instead of asking for it")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-bronze", action="store_true")
    a = ap.parse_args()
    return max(run(k, a.out, a.from_file, not a.no_bronze) for k in a.sites)


if __name__ == "__main__":
    sys.exit(main())
