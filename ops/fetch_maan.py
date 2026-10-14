"""Ma'an News Agency's headlines from its full listing, 2005 to today.

    .venv/bin/python -m ops.fetch_maan --out DIR --bronze-root DIR      # runs for about a day; resumable
    touch DIR/maan/STOP                                                  # ends it after the page in hand

WHY (2026-10-14). Ma'an (Bethlehem, maannews.net) is the deepest West Bank
outlet the archive could read: its listing /news/latest?page=N runs to page
35,177, eighteen headlines a page, back to 9 May 2005 (about 633,000). The six
outlets held are Gaza's (Safa, Felesteen, Shehab), Sama, Arab48 and WAFA.

THE ROUTE (scouted and measured 2026-10-14). The site has no sitemap; its
robots file is empty. Each listing item is an `a.list-6__item` with the
article's address (/news/<id>.html) and its headline in `title`, and a
`div.list-6__date` with the day (dd/mm/yyyy). One request every three seconds,
newest page first; every page kept in bronze (`listing_maan`). Pages shift as
new items arrive, so an item can appear on two pages: it is one headline
(its id), written once.

WHAT IT WRITES, under DIR/maan/: items-p<first>-<last>.ndjson.gz every 200
pages (id, url, title, date, precision day, title_from "listing", date_basis
"listing"), site.json for the archive's sitemap reader (the nightly archive load
takes the files in), and cursor.json (the next page, so a stopped run goes on).
A refusal (any HTTP error but a missing page) ends the run, exit 3, ledgered
`listing:maan`; it does not try again by itself.
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

LISTING = "https://www.maannews.net/news/latest?page={n}"
SITE = {"name": "Ma'an News Agency (وكالة معاً الإخبارية)", "home_url": "https://www.maannews.net",
        "source": "web:maannews", "kind": "outlet", "lang": "ar"}
LABEL = "listing:maan"
PAUSE = 3.0
PER_FILE = 200
ITEM = re.compile(r'<a[^>]+class="[^"]*list-6__item[^"]*"[^>]*>.*?</a>', re.S)
HREF = re.compile(r'href="(?:https?://(?:www\.)?maannews\.net)?(/news/(\d+)\.html)"')
TITLE = re.compile(r'title="([^"]*)"')
DAY = re.compile(r'list-6__date[^>]*>\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*<')
LAST = re.compile(r'page=(\d+)')


class Refused(Exception):
    pass


def items_of(page: str) -> list[dict]:
    """A listing page → its headlines."""
    out = []
    for block in ITEM.findall(page):
        h, t, d = HREF.search(block), TITLE.search(block), DAY.search(block)
        if not (h and t and d):
            continue
        title = re.sub(r"\s+", " ", html_mod.unescape(t.group(1))).strip()
        try:
            day = datetime.date(int(d.group(3)), int(d.group(2)), int(d.group(1))).isoformat()
        except ValueError:
            continue
        if title:
            out.append({"id": h.group(2), "url": "https://www.maannews.net" + h.group(1), "title": title,
                        "date": day, "precision": "day", "title_from": "listing", "date_basis": "listing"})
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
    d = a.out / "maan"
    d.mkdir(parents=True, exist_ok=True)
    (d / "site.json").write_text(json.dumps(SITE, ensure_ascii=False, indent=1))
    cur_path = d / "cursor.json"
    cursor = json.loads(cur_path.read_text()) if cur_path.exists() else {"next": 1, "seen": 0}
    if cursor.get("done"):
        print("maan: the listing is read to its last page")
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
            bronze.put("listing_maan", page, "html", url=url)
            if last_page is None:
                nums = [int(x) for x in LAST.findall(page)]
                last_page = max(nums) if nums else None
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
                print(f"maan: page {n - 1:,} of {last_page or '?'} · {len(seen):,} headlines · back to "
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
    print(f"maan: {outcome} ({why}) · {pages:,} pages this run · {len(seen):,} headlines · next page {n:,}")
    return 3 if outcome == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
