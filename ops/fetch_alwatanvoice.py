"""Donia al-Watan's headlines from its "Palestinian affairs" listing (شؤون فلسطينية), newest first, back as far as it goes.

    .venv/bin/python -m ops.fetch_alwatanvoice --out DIR --bronze-root DIR      # runs for most of a day; resumable
    touch DIR/alwatanvoice/STOP                                                  # ends it after the page in hand

WHY (2026-10-15). Donia al-Watan (alwatanvoice.com, Gaza) is one of the outlets the 2026-10-13 scouts marked "read
whole now": its "Palestinian affairs" category is paged (/arabic/category/2/{n}.html, about 22 headlines a page,
12,900 pages measured; page 5,000 = 15 May 2019), each article address carries its day
(/arabic/news/YYYY/MM/DD/{id}.html). Robots: "Allow: /". The archive held none of it.

THE ROUTE. One listing page every three seconds, newest first; every page kept in bronze (`listing_alwatanvoice`).
A page also shows a few headlines from other sections beside the list; they are written too (an id is written
once). Pages shift as new items arrive, so an item can appear on two pages: it is one headline (its id).

WHAT IT WRITES, under DIR/alwatanvoice/: items-p<first>-<last>.ndjson.gz every 200 pages (id, url, title, date,
precision day, title_from "listing", date_basis "address"), site.json for the archive's sitemap reader (the
nightly archive load takes the files in), and cursor.json (the next page, so a stopped run goes on).
A refusal (any HTTP error but a missing page) ends the run, exit 3, ledgered `listing:alwatanvoice`.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import html as html_mod
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import fetchlib as fl                                  # noqa: E402

LISTING = "https://www.alwatanvoice.com/arabic/category/2/{n}.html"
SITE = {"name": "Donia al-Watan (دنيا الوطن)", "home_url": "https://www.alwatanvoice.com",
        "source": "web:alwatanvoice", "kind": "outlet", "lang": "ar"}
LABEL = "listing:alwatanvoice"
PAUSE = 3.0
PER_FILE = 200
ITEM = re.compile(r'<a[^>]+href="(?:https?://www\.alwatanvoice\.com/arabic/|/arabic/|\.\./)?(news/(\d{4})/(\d{2})/(\d{2})/(\d+)\.html)"[^>]*>(.*?)</a>', re.S)
LAST = re.compile(r'category/2/(\d+)\.html')


class Refused(Exception):
    pass


def items_of(page: str) -> list[dict]:
    """A listing page → its headlines (the address gives the day)."""
    out, seen = [], set()
    for path, y, m, d, i, inner in ITEM.findall(page):
        title = re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        if len(title) < 8 or i in seen:
            continue
        try:
            day = datetime.date(int(y), int(m), int(d)).isoformat()
        except ValueError:
            continue
        seen.add(i)
        out.append({"id": i, "url": "https://www.alwatanvoice.com/arabic/" + path, "title": title,
                    "date": day, "precision": "day", "title_from": "listing", "date_basis": "address"})
    return out


def get(url: str, tries: int = 3) -> str:
    for attempt in range(1, tries + 1):
        time.sleep(PAUSE)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": fl.UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise Refused(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as e:
            if attempt == tries:
                raise Refused(f"network: {type(e).__name__} after {tries} tries") from None
            time.sleep(60 * attempt)
    raise Refused("unreachable")


def write_file(d: Path, first: int, last: int, items: list[dict]) -> None:
    body = "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items).encode("utf-8")
    tmp = d / f"items-p{first:05d}-{last:05d}.ndjson.gz.tmp"
    tmp.write_bytes(gzip.compress(body, compresslevel=6))
    tmp.replace(d / f"items-p{first:05d}-{last:05d}.ndjson.gz")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "raw" / "sitemaps")
    ap.add_argument("--bronze-root", type=Path, default=None)
    ap.add_argument("--max-pages", type=int, default=None, help="stop after this many pages (a trial)")
    a = ap.parse_args()
    d = a.out / "alwatanvoice"
    d.mkdir(parents=True, exist_ok=True)
    (d / "site.json").write_text(json.dumps(SITE, ensure_ascii=False, indent=1))
    cur_path = d / "cursor.json"
    cursor = json.loads(cur_path.read_text()) if cur_path.exists() else {"next": 1, "seen": 0}
    if cursor.get("done"):
        print("alwatanvoice: the listing is read to its last page")
        return 0
    if a.bronze_root:
        from ingest import bronze
        bronze.BRONZE = a.bronze_root
    else:
        from ingest import bronze
    seen: set[str] = set()
    for f in d.glob("items-p*.ndjson.gz"):                      # ids already written, so a shifted page adds none twice
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            seen.update(json.loads(line)["id"] for line in fh)
    n, last_page, batch, batch_first, pages = cursor["next"], cursor.get("last_page"), [], cursor["next"], 0
    outcome, why = "stopped", ""
    try:
        while True:
            if (d / "STOP").exists():
                outcome, why = "stopped", "stop file"
                break
            url = LISTING.format(n=n)
            page = get(url)
            bronze.put("listing_alwatanvoice", page, "html", url=url)
            items = [i for i in items_of(page) if i["id"] not in seen]
            seen.update(i["id"] for i in items)
            batch += items
            pages += 1
            if not items_of(page):
                outcome, why = "done", f"page {n} lists nothing"
                n += 1
                break
            n += 1
            if len(range(batch_first, n)) >= PER_FILE:
                write_file(d, batch_first, n - 1, batch)
                cursor.update({"next": n, "seen": len(seen), "last_page": last_page,
                               "oldest_date": batch[-1]["date"] if batch else cursor.get("oldest_date")})
                cur_path.write_text(json.dumps(cursor))
                print(f"alwatanvoice: page {n - 1:,} of {last_page or '?'} · {len(seen):,} headlines · back to "
                      f"{cursor.get('oldest_date')}", flush=True)
                batch, batch_first = [], n
            if last_page and n > last_page:
                outcome, why = "done", "the last page"
                break
            if a.max_pages and pages >= a.max_pages:
                outcome, why = "stopped", f"--max-pages {a.max_pages}"
                break
    except Refused as e:
        outcome, why = "refused", str(e)
    if batch:
        write_file(d, batch_first, n - 1, batch)
    cursor.update({"next": n, "seen": len(seen), "last_page": last_page,
                   "oldest_date": batch[-1]["date"] if batch else cursor.get("oldest_date"),
                   "done": outcome == "done"})
    cur_path.write_text(json.dumps(cursor))
    fl.event(LABEL, "ok" if outcome in ("done", "stopped") else "refused", pages=pages, headlines=len(seen),
             next_page=n, why=why)
    print(f"alwatanvoice: {outcome} ({why}) · {pages:,} pages this run · {len(seen):,} headlines · next page {n:,}")
    return 3 if outcome == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
