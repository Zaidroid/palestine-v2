"""The Gaza Chamber of Commerce and Industry's weekly reports on the movement
of goods into Gaza and the state of its markets, whole, into the archive.

    .venv/bin/python -m ops.fetch_gazacham                    # read the listing, the pages and the files
    .venv/bin/python -m ops.fetch_gazacham --from-dir DIR     # the files already in DIR (with walk.json)

WHAT THEY ARE. A report every week from August 2024, every two weeks since
(81 reports, weeks 1 to 111 on 2026-10-14): trucks entering by crossing and by
day, the private-sector and humanitarian shares, what they carried, prices of
food and non-food goods against their pre-war level, and from 2025 the
Chamber's own Gaza consumer price index (GCPI). A scout found them
(docs/scout-2026-10-13/outlets-and-bulletins.md); the robots file of
gazacham.ps sets no rule and no content signal.

WHAT THIS DOES. It reads the listing (the first page has no number; page=0
answers 500), each report's page and its file, two seconds apart, and ends at
the first refusal. Each file becomes text (`pdftotext -layout`) and one item
in the archive's report shape: the period it covers (read from the report's
address, which spells a period five ways), its weeks, title, text and link.
The tables inside are kept as text here; reading them into series is a later,
separate step, because their layout changed at least three times.

THE POSTURE: atomic, FLOORED (fewer than 70 reports is refused and the file on
disk kept), ledgered as `reports:gazacham`, each file archived in bronze
(`reports_gazacham`).

WHAT IT WRITES, under data/raw/reports/gazacham/:
  items-all.ndjson.gz   one report a line: id, date (its last day), start, weeks,
                    title, text, link (the report's page), pdf
  site.json         the publisher, as the loader needs it
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import html as html_mod
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                                       # noqa: E402
from ops import fetchlib                                        # noqa: E402

UA = "palestine-v2 archive reader (personal research)"
BASE = "https://gazacham.ps"
SLUG = "حركة-البضائع-وحالة-الأسواق"
OUT = ROOT / "data" / "raw" / "reports" / "gazacham"
LABEL = "reports:gazacham"
FLOOR = 70
SITE = {"key": "gazacham", "name": "Gaza Chamber of Commerce and Industry, Gaza Movement of Goods weekly reports",
        "home_url": BASE + "/InformationCenter/Reports?slug=" + urllib.parse.quote(SLUG),
        "source": "org:gazacham", "kind": "reports", "doc_kind": "report", "day_only": True}

NAMES = ["january","february","march","april","may","june","july","august","september","october","november","december"]
MON = {**{m: i for i, m in enumerate(NAMES, 1)}, **{m[:3]: i for i, m in enumerate(NAMES, 1)}, "sept": 9}
MP = "|".join(sorted(MON, key=len, reverse=True))
def report_period(slug):
    """A report's address → (first day, last day), or None. The addresses
    write a period five ways: 1-7-august-2024, august-19-to-01-sep-2025,
    september-01-14-2025, 13-to-26-oct-2025, dec-22-2025-to-jan-04-2026."""
    s = slug.lower().split("from", 1)[-1]
    years = [int(y) for y in re.findall(r"(20\d\d)", s)]
    if not years:
        return None
    pairs = []
    for m in re.finditer(rf"(?<![a-z])({MP})-+(\d{{1,2}})-+(\d{{1,2}})(?![\d])(?!-+(?:{MP}))", s):
        pairs += [(m.start(), int(m.group(2)), MON[m.group(1)]), (m.start() + 1, int(m.group(3)), MON[m.group(1)])]
    taken = [(m.start(), m.end()) for m in re.finditer(rf"(?<![a-z])({MP})-+(\d{{1,2}})-+(\d{{1,2}})(?![\d])(?!-+(?:{MP}))", s)]
    def free(i):
        return not any(a <= i < b for a, b in taken)
    for m in re.finditer(rf"(\d{{1,2}})-+(?:to-+)?({MP})(?![a-z])", s):
        if free(m.start()) and len(m.group(1)) <= 2:
            pairs.append((m.start(), int(m.group(1)), MON[m.group(2)]))
    for m in re.finditer(rf"(?<![a-z])({MP})-+(\d{{1,2}})(?![\d])", s):
        if free(m.start()) and not re.match(r"20\d\d", s[m.start(2):m.start(2) + 4]):
            pairs.append((m.start(), int(m.group(2)), MON[m.group(1)]))
    pairs = sorted(set(pairs))
    if not pairs:
        return None
    end_d, end_m = pairs[-1][1], pairs[-1][2]
    if len(pairs) >= 2:
        st_d, st_m = pairs[0][1], pairs[0][2]
    else:
        lead = re.match(r"-*(\d{1,2})-", s)
        st_d, st_m = (int(lead.group(1)), end_m) if lead and int(lead.group(1)) < end_d else (end_d, end_m)
    end_y = years[-1]
    try:
        end = datetime.date(end_y, end_m, end_d)
        start = datetime.date(end_y - (1 if st_m > end_m else 0), st_m, st_d)
    except ValueError:
        return None
    return start, end


def weeks_of(slug: str) -> list[int]:
    """'weekly-report-110---111-from-…' → [110, 111]; '(9)-from-…' → [9]."""
    head = slug.lower().split("from", 1)[0]
    return [int(x) for x in re.findall(r"\d+", head)]


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
        data = r.read()
    time.sleep(2.0)
    return data


def walk(work: Path) -> list[dict]:
    """The listing, each report's page and its file. Returns one record per report."""
    q = urllib.parse.quote(SLUG)
    pages: list[str] = []
    for n in range(1, 30):
        t = _get(f"{BASE}/InformationCenter/Reports?slug={q}" + ("" if n == 1 else f"&&page={n}")).decode("utf-8", "replace")
        found = [html_mod.unescape(x) for x in re.findall(r'href="(/InformationCenter/Details\?slug=[^"]+)"', t)]
        new = [f for f in dict.fromkeys(found) if f not in pages]
        if not new:
            break
        pages += new
    out = []
    for p in pages:
        t = _get(BASE + p).decode("utf-8", "replace")
        pdf = re.findall(r'href="(/Uploads/InformationCenter/[^"]+\.pdf)"', t, flags=re.I)
        title = html_mod.unescape(re.sub(r"\s+", " ", (re.findall(r"<title>(.*?)</title>", t, flags=re.S) or [""])[0])).strip()
        rec = {"slug": urllib.parse.unquote(p.split("slug=", 1)[1]), "page": BASE + p, "title": title,
               "pdf": BASE + pdf[0] if pdf else None}
        if pdf:
            name = work / Path(pdf[0]).name
            if not name.exists():
                name.write_bytes(_get(rec["pdf"]))
            rec["file"] = name.name
        out.append(rec)
    return out


def items_from(reports: list[dict], work: Path, use_bronze: bool) -> tuple[list[dict], dict]:
    items, notes = [], {"reports": 0, "no_file": [], "no_period": []}
    seen = set()
    for r in reports:
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        notes["reports"] += 1
        if not r.get("file"):
            notes["no_file"].append(r["slug"])
            continue
        period = report_period(r["slug"])
        if period is None:
            notes["no_period"].append(r["slug"])
            continue
        pdf = work / r["file"]
        text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode(
            "utf-8", "replace")
        if use_bronze:
            bronze.put("reports_gazacham", pdf.read_bytes(), "pdf", url=r["pdf"])
        title = re.sub(r"\s*\|.*$", "", r.get("title") or "").strip() or r["slug"]
        items.append({"id": r["slug"], "date": period[1].isoformat() + "T00:00:00", "start": period[0].isoformat(),
                      "weeks": weeks_of(r["slug"]), "title": title,
                      "text": "\n".join(ln.rstrip() for ln in text.replace("\f", "\n").split("\n")).strip(),
                      "link": r["page"], "pdf": r["pdf"]})
    items.sort(key=lambda i: i["date"])
    return items, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from-dir", type=Path, help="the files already read, with walk.json beside them")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-bronze", action="store_true")
    a = ap.parse_args()
    try:
        if a.from_dir:
            reports = json.loads((a.from_dir / "walk.json").read_text())["reports"]
            work = a.from_dir / "pdf"
        else:
            work = a.out / "_files"
            work.mkdir(parents=True, exist_ok=True)
            reports = walk(work)
        items, notes = items_from(reports, work, not a.no_bronze)
    except (urllib.error.URLError, OSError, subprocess.CalledProcessError, ValueError) as e:
        fetchlib.event(LABEL, "failed", why=f"{type(e).__name__}: {e}"[:200])
        print(f"gazacham: not read ({type(e).__name__}: {e}); the file on disk is kept")
        return 1
    try:
        fetchlib.check_floor(LABEL, len(items), FLOOR)
    except fetchlib.FetchRefused as e:
        print(str(e))
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items).encode("utf-8")
    tmp = a.out / "items-all.ndjson.gz.tmp"
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(body)
    tmp.replace(a.out / "items-all.ndjson.gz")
    (a.out / "site.json").write_text(json.dumps(SITE, ensure_ascii=False, indent=1))
    weeks = sorted(w for i in items for w in i["weeks"])
    fetchlib.event(LABEL, "ok", rows=len(items), first=items[0]["date"][:10], last=items[-1]["date"][:10],
                   weeks=f"{weeks[0]}-{weeks[-1]}", **{k: v for k, v in notes.items() if v})
    print(f"gazacham: {len(items)} reports, weeks {weeks[0]} to {weeks[-1]}, {items[0]['start']} to {items[-1]['date'][:10]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
