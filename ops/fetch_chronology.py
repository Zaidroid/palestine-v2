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
import datetime
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
    "passia": {"name": "PASSIA Palestine Chronology (Palestinian Academic Society for the Study of"
                       " International Affairs, Jerusalem)",
               "home_url": "https://passia.org/palestine-chronology/",
               "page": "https://passia.org/palestine-chronology/",
               "source": "chron:passia", "floor": 4000},
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


_P_MONTH = (r"(Jan|Feb|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?")
_P_ENTRY = re.compile(rf"^{_P_MONTH}(?:\s+(\d{{1,2}})(?:\s*[-–/]\s*(\d{{1,2}}))?)?\s*:\s*(.*)$")
_P_LOOSE = re.compile(rf"^(?:(?:Mid|Early|Late|End of|Beginning of|Start of)[- ]+)?{_P_MONTH}"
                      rf"(?:\s*[-–/]\s*{_P_MONTH})?(?:\s+\d{{1,2}})?\s*:\s*(.*)$", re.I)
_P_DASH = re.compile(r"^[-–•]\s+(.*)$")
_P_YEAR = re.compile(r"^(1[4-9]\d\d|20\d\d)$")
_P_MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12}


_P_HEAD = re.compile(r"^(?:palestine\s+)?chronology(?:\s+(\d{4}))?$", re.I)
_P_MONTH_ONLY = re.compile(r"^(january|february|march|april|may|june|july|august|september|october|november|december)"
                           r"\s*:?$", re.I)


def parse_passia(text: str, url: str, default_year: int | None = None) -> tuple[list[dict], int]:
    """One PASSIA chronology file as text (pdftotext -layout) → its entries,
    and how many lines stood under no year and were not taken.

    The files have one shape from 1911 on: a year on a line of its own (or in
    the heading, "CHRONOLOGY 2019"; a month's name alone is a divider), then
    `Jan. 5: …`, `June 16-24: …`, `March: …`; a line that begins with a dash is
    one more event of the same date; other lines continue the entry above.
    Before the months begin, a year's heading is followed by plain sentences,
    which are taken as one entry of that year."""
    import hashlib
    entries: list[dict] = []
    year: int | None = default_year
    cur: dict | None = None
    undated = 0

    def close() -> None:
        nonlocal cur
        if cur and cur["text"].strip():
            cur["text"] = " ".join(cur["text"].split())
            cur["id"] = cur["date"] + ":" + hashlib.sha1(cur["text"].encode("utf-8")).hexdigest()[:10]
            entries.append(cur)
        cur = None

    def start(month: int | None, day: str | None, end: str | None, date_text: str, first: str) -> None:
        nonlocal cur
        close()
        if day:
            try:
                datetime.date(year, month, int(day))
            except ValueError:                          # "Feb. 30" in the source: keep the month, say what was printed
                day = None
        precision = "day" if day else ("month" if month else "year")
        cur = {"date": f"{year:04d}-{month or 1:02d}-{int(day or 1):02d}", "precision": precision,
               "date_text": f"{date_text} {year}".strip(), "text": first, "url": url}
        if end and day and int(end) > int(day):
            cur.update(end=f"{year:04d}-{month:02d}-{int(end):02d}", end_precision="day")

    for raw in text.replace("\f", "\n").split("\n"):
        line = raw.strip()
        if not line or re.fullmatch(r"\d{1,3}", line) or re.fullmatch(r"\d{4}\s*[-–]\s*\d{4}", line) \
                or _P_MONTH_ONLY.match(line):
            continue
        h = _P_HEAD.match(line)
        if h:                                           # "Palestine Chronology", "CHRONOLOGY 2019"
            if h.group(1):
                close()
                year = int(h.group(1))
            continue
        if _P_YEAR.match(line):
            close()
            year = int(line)
            continue
        if year is None:
            undated += 1
            continue
        m = _P_ENTRY.match(line)
        if m:
            start(_P_MON[m.group(1)[:3].lower()], m.group(2), m.group(3), line.split(":", 1)[0], m.group(4))
            continue
        m = _P_LOOSE.match(line)
        if m:
            start(_P_MON[m.group(1)[:3].lower()], None, None, line.split(":", 1)[0], m.group(3))
            continue
        m = _P_DASH.match(line)
        if m and cur is not None:
            month, day = int(cur["date"][5:7]), cur["date"][8:10]
            prev = cur
            start(month if prev["precision"] != "year" else None, day if prev["precision"] == "day" else None,
                  None, prev["date_text"].rsplit(" ", 1)[0], m.group(1))
            if prev.get("end"):
                cur.update(end=prev["end"], end_precision="day")
            continue
        if cur is None:
            start(None, None, None, "", line)                       # sentences under a bare year
        else:
            cur["text"] += " " + line
    close()
    return entries, undated


def read_passia(out: Path, from_dir: Path | None) -> tuple[list[dict], dict]:
    """Every chronology file PASSIA's index links, as entries. Asks the index
    once and each file once, two seconds apart; a dead link (404) is skipped and
    named, any other refusal ends the run."""
    import subprocess
    import tempfile
    import time
    import urllib.error
    import urllib.parse
    site = SITES["passia"]
    info: dict = {"files": 0, "missing": [], "undated_lines": 0}
    entries: list[dict] = []
    work = from_dir or Path(tempfile.mkdtemp(prefix="passia-"))
    if from_dir:
        files = {p.stem: json.loads((from_dir / "index.json").read_text())["files"][p.stem]["url"]
                 for p in sorted(from_dir.glob("*.pdf"))}
    else:
        req = urllib.request.Request(site["page"], headers={"User-Agent": UA})
        index = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
        files = {}
        for href, text in re.findall(r'href="([^"]+\.pdf)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{1,60})', index):
            label = html_mod.unescape(text).replace("\xa0", " ").replace("•", "").strip()
            if re.fullmatch(r"\d{4}(\s*[–-]\s*\d{4})?", label):
                files[re.sub(r"\s*[–-]\s*", "-", label)] = urllib.parse.urljoin("https://passia.org/", href)
        for label, url in list(files.items()):
            time.sleep(2.2)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                    (work / f"{label}.pdf").write_bytes(r.read())
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                info["missing"].append(label)
                del files[label]
    for label, url in files.items():
        pdf = work / f"{label}.pdf"
        bronze.put("chron_passia", pdf.read_bytes(), "pdf", url=url)
        text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode(
            "utf-8", "replace")
        got, undated = parse_passia(text, url, int(label) if label.isdigit() else None)
        for e in got:
            e["file"] = label
        entries.extend(got)
        info["files"] += 1
        info["undated_lines"] += undated
    seen: dict[str, dict] = {}
    for e in entries:
        seen.setdefault(e["id"], e)
    return sorted(seen.values(), key=lambda e: (e["date"], e["id"])), info


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
    return write(key, out, entries, {"not_understood": odd}, page if use_bronze else None)


def write(key: str, out: Path, entries: list[dict], facts: dict, page: str | None) -> int:
    site = SITES[key]
    label = f"chronology:{key}"
    try:
        fetchlib.check_floor(label, len(entries), site["floor"])
    except fetchlib.FetchRefused as e:
        print(str(e))
        return 2
    d = out / key
    d.mkdir(parents=True, exist_ok=True)
    if page is not None:
        bronze.put(f"chron_{key}", page, "html", url=site["page"])
    body = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries).encode("utf-8")
    tmp = d / "entries.ndjson.gz.tmp"
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(body)
    tmp.replace(d / "entries.ndjson.gz")
    (d / "site.json").write_text(json.dumps(
        {"key": key, "name": site["name"], "home_url": site["home_url"], "source": site["source"]},
        ensure_ascii=False, indent=1))
    if page is None and key != "palquest":
        bronze.put(f"chron_{key}", body, "ndjson", url=site["page"])
    fetchlib.event(label, "ok", rows=len(entries), first=entries[0]["date"], last=entries[-1]["date"], **facts)
    print(f"{key}: {len(entries):,} events, {entries[0]['date']} to {entries[-1]['date']} · {facts}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sites", nargs="+", choices=sorted(SITES))
    ap.add_argument("--from-file", type=Path, help="palquest: parse a page already in hand instead of asking for it")
    ap.add_argument("--from-dir", type=Path, help="passia: parse the files already in this folder (with index.json)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-bronze", action="store_true")
    a = ap.parse_args()
    worst = 0
    for k in a.sites:
        if k == "passia":
            try:
                entries, info = read_passia(a.out, a.from_dir)
            except Exception as e:                                   # noqa: BLE001
                fetchlib.event("chronology:passia", "failed", why=f"{type(e).__name__}: {e}"[:200])
                print(f"passia: not read ({type(e).__name__}: {e}); the file on disk is kept")
                worst = max(worst, 1)
                continue
            worst = max(worst, write(k, a.out, entries, info, None))
        else:
            worst = max(worst, run(k, a.out, a.from_file, not a.no_bronze))
    return worst


if __name__ == "__main__":
    sys.exit(main())
