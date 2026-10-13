"""Read a publisher's whole archive through the open listing its own website
software provides (WordPress: /wp-json/wp/v2/<route>), a hundred items a page.

    .venv/bin/python -m ops.fetch_wp_json unispal            # the whole listing, oldest id first
    .venv/bin/python -m ops.fetch_wp_json pchr poica --pages 3
    .venv/bin/python -m ops.fetch_wp_json --list             # the publishers this reader knows

WHY THIS EXISTS. Zaid, 13 October 2026: the archive should reach "as much as
possible from 1948". A scout mapped what can be read (docs/scout-2026-10-13/):
several publishers serve their full archive, text included, through one
listing, with no key and no login. The largest is the UN's own information
system on the question of Palestine: 46,967 documents, the oldest dated 1915.

THE POSTURE is the one ops/fetch_telegram_public.py set:

  SLOW       each publisher's own crawl-delay where its robots file states one
             (UNISPAL 10 s, PCHR 3 s, IMEMC 20 s), two seconds otherwise.
  STOPS AT THE FIRST REFUSAL. An HTTP answer that is not 200 ends that
             publisher's run (`refused` in the ledger, exit 3 at the end). It
             is not retried or worked around. The next publisher on the list
             is a different house and is still asked.
  RESUMABLE  `cursor.json` holds the next page. Pages are asked in id order,
             so an item published during the run arrives at the end and no
             page shifts under the reader.
  ATOMIC, LEDGERED (`wp_json:<key>`), ONE AT A TIME (exit 4), and a STOP file:
             `touch data/raw/wp/STOP`.

WHAT IT WRITES, under --out (default data/raw/wp):

  <key>/items-<first id>-<last id>.ndjson.gz   one item a line: id, date, link,
                                               title, text, excerpt, and the
                                               publisher's own category ids
  <key>/terms.json                             those ids' names
  <key>/site.json                              the publisher, as the loader needs it
  <key>/cursor.json

Each page as it arrived is kept gzipped under --cache (default
data/cache/wp_json), a convenience that can be deleted. Each items file is
also archived in bronze (`wp_<key>`).

`text` is the item's body with the markup removed and paragraphs kept. A date
is the publisher's own; some carry a mistyped year (0001, 0201) and are kept
as written here, to be judged by the loader.
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import html as html_mod
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                                       # noqa: E402
from ops import fetchlib                                        # noqa: E402

UA = "palestine-v2 archive reader (personal research)"
OUT = ROOT / "data" / "raw" / "wp"
CACHE = ROOT / "data" / "cache" / "wp_json"
CHUNK_PAGES = 10             # a thousand items a file
POST_FIELDS = "id,date,date_gmt,modified_gmt,link,title,content,excerpt,categories,tags,type"

# key → what it is. `source` is the archive's publisher key (the loader's);
# `day_only` marks listings whose time of day is the hour of filing, not of the document.
SITES: dict[str, dict] = {
    "unispal": {"name": "UNISPAL, the UN's information system on the question of Palestine",
                "base": "https://www.un.org/unispal", "route": "document", "pause": 10,
                "source": "un:unispal", "kind": "reports", "doc_kind": "report", "day_only": True,
                "fields": None,
                "taxonomies": ["document-category", "document-source", "document-subject"]},
    "pchr": {"name": "Palestinian Centre for Human Rights", "base": "https://pchrgaza.org", "route": "posts",
             "pause": 3, "source": "org:pchr", "kind": "reports", "doc_kind": "report",
             "taxonomies": ["categories"]},
    "poica": {"name": "POICA, monitoring Israeli colonization activities (ARIJ and LRC)",
              "base": "https://poica.org", "route": "posts", "pause": 2, "source": "org:poica",
              "kind": "reports", "doc_kind": "report", "taxonomies": ["categories"]},
    "memo": {"name": "Middle East Monitor", "base": "https://www.middleeastmonitor.com", "route": "posts",
             "pause": 2, "source": "web:middle_east_monitor", "kind": "outlet", "doc_kind": "article",
             "taxonomies": ["categories"]},
    "mondoweiss": {"name": "Mondoweiss", "base": "https://mondoweiss.net", "route": "posts", "pause": 2,
                   "source": "web:mondoweiss", "kind": "outlet", "doc_kind": "article",
                   "taxonomies": ["categories"]},
    "palinfo_en": {"name": "Palestinian Information Center (English)", "base": "https://english.palinfo.com",
                   "route": "posts", "pause": 2, "source": "web:palinfo_en", "kind": "outlet",
                   "doc_kind": "article", "taxonomies": ["categories"]},
    "palinfo_ar": {"name": "Palestinian Information Center (Arabic)", "base": "https://palinfo.com",
                   "route": "posts", "pause": 2, "source": "web:palinfo_ar", "kind": "outlet",
                   "doc_kind": "article", "taxonomies": ["categories"]},
    "imemc": {"name": "IMEMC News", "base": "https://imemc.org", "route": "posts", "pause": 20,
              "source": "web:imemc", "kind": "outlet", "doc_kind": "article", "taxonomies": ["categories"]},
}

_BLOCK = re.compile(r"(?i)</(?:p|div|li|h[1-6]|tr|blockquote|table|ul|ol)>|<br\s*/?>")
_DROP = re.compile(r"(?is)<(script|style|noscript|figure|iframe)\b.*?</\1>")
_TAG = re.compile(r"<[^>]+>")
_SP = re.compile(r"[ \t\r\f\v\xa0]+")


class Refused(Exception):
    """The site answered, and the answer was not the listing."""


def text_of(markup: str | None) -> str:
    """A body's words with paragraphs kept and the markup gone."""
    if not markup:
        return ""
    s = _DROP.sub(" ", markup)
    s = _BLOCK.sub("\n", s)
    s = html_mod.unescape(_TAG.sub(" ", s))
    lines = [_SP.sub(" ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def item_of(r: dict, site: dict) -> dict:
    """One listing record → the line that is written."""
    out = {"id": r["id"], "date": r.get("date"), "date_gmt": r.get("date_gmt"),
           "modified_gmt": r.get("modified_gmt"), "link": r.get("link"),
           "title": text_of((r.get("title") or {}).get("rendered")).replace("\n", " "),
           "text": text_of((r.get("content") or {}).get("rendered")),
           "excerpt": text_of((r.get("excerpt") or {}).get("rendered")).replace("\n", " ")}
    for tax in site.get("taxonomies") or []:
        if r.get(tax):
            out.setdefault("terms", {})[tax] = r[tax]
    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


def get(url: str, tries: int = 3) -> tuple[bytes, dict]:
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                if r.status != 200:
                    raise Refused(f"HTTP {r.status}")
                return r.read(), {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            raise Refused(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries:
                raise Refused(f"network: {type(e).__name__} after {tries} tries") from None
            time.sleep(60 * attempt)
    raise Refused("unreachable")


def write_chunk(d: Path, key: str, items: list[dict], bronze_root: Path | None) -> str:
    items = sorted({i["id"]: i for i in items}.values(), key=lambda i: i["id"])
    name = f"items-{items[0]['id']:010d}-{items[-1]['id']:010d}.ndjson.gz"
    body = "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items).encode("utf-8")
    tmp = d / (name + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(body)
    tmp.replace(d / name)
    if bronze_root is not None:
        keep = bronze.BRONZE
        bronze.BRONZE = bronze_root
        try:
            bronze.put(f"wp_{key}", body, "ndjson", url=SITES[key]["base"])
        finally:
            bronze.BRONZE = keep
    return name


def write_site(d: Path, key: str) -> None:
    """What the loader needs to know about this publisher, beside its items."""
    s = SITES[key]
    (d / "site.json").write_text(json.dumps(
        {"key": key, "name": s["name"], "home_url": s["base"], "source": s["source"], "kind": s["kind"],
         "doc_kind": s["doc_kind"], "day_only": bool(s.get("day_only"))}, ensure_ascii=False, indent=1))


def fetch_terms(key: str, site: dict, d: Path, pause: float) -> None:
    """The names behind the category ids, once. A failure here is not a
    refusal of the archive: the ids are kept and the names can be asked again."""
    out = d / "terms.json"
    if out.exists():
        return
    names: dict[str, dict[str, str]] = {}
    try:
        for tax in site.get("taxonomies") or []:
            names[tax] = {}
            for page in range(1, 31):
                raw, _ = get(f"{site['base']}/wp-json/wp/v2/{tax}?per_page=100&page={page}&_fields=id,name,count")
                rows = json.loads(raw)
                for t in rows:
                    names[tax][str(t["id"])] = html_mod.unescape(t.get("name") or "")
                time.sleep(pause)
                if len(rows) < 100:
                    break
    except (Refused, ValueError) as e:
        print(f"  {key}: category names not read ({e}); the ids are kept", flush=True)
        return
    out.write_text(json.dumps(names, ensure_ascii=False, indent=1))


def run(key: str, out: Path, cache: Path, pages: int | None, bronze_root: Path | None) -> int:
    site = SITES[key]
    pause = float(site["pause"])
    d = out / key
    d.mkdir(parents=True, exist_ok=True)
    cdir = cache / key
    cdir.mkdir(parents=True, exist_ok=True)
    write_site(d, key)
    cur_path = d / "cursor.json"
    cursor = json.loads(cur_path.read_text()) if cur_path.exists() else {"page": 1, "items": 0}
    if cursor.get("done"):
        print(f"{key}: the whole listing is already read ({cursor.get('items'):,} items)")
        return 0
    fields = site.get("fields", POST_FIELDS)
    buf: list[dict] = []
    n_pages = n_items = 0
    outcome, why = "ok", ""

    def flush() -> None:
        nonlocal buf
        if buf:
            name = write_chunk(d, key, buf, bronze_root)
            print(f"  wrote {key}/{name} ({len(buf):,} items)", flush=True)
            buf = []
        cursor["updated"] = datetime.now(timezone.utc).isoformat()
        tmp = cur_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cursor, ensure_ascii=False, indent=1))
        tmp.replace(cur_path)

    try:
        fetch_terms(key, site, d, pause)
        while pages is None or n_pages < pages:
            if (out / "STOP").exists() or (d / "STOP").exists():
                outcome, why = "stopped", "stop file"
                break
            page = cursor["page"]
            url = (f"{site['base']}/wp-json/wp/v2/{site['route']}?per_page=100&page={page}&orderby=id&order=asc"
                   + (f"&_fields={fields}" if fields else ""))
            try:
                raw, head = get(url)
            except Refused as e:
                # the listing answers 400 one page past its end
                if str(e) == "HTTP 400" and cursor.get("pages_total") and page > cursor["pages_total"]:
                    cursor["done"] = True
                    outcome, why = "done", "reached the end of the listing"
                    break
                raise
            rows = json.loads(raw)
            if head.get("x-wp-total"):
                cursor["total"] = int(head["x-wp-total"])
                cursor["pages_total"] = int(head.get("x-wp-totalpages") or 0)
            with gzip.open(cdir / f"page-{page:05d}.json.gz", "wb") as fh:
                fh.write(raw)
            n_pages += 1
            if not rows:
                cursor["done"] = True
                outcome, why = "done", "reached the end of the listing"
                break
            buf.extend(item_of(r, site) for r in rows)
            n_items += len(rows)
            cursor["items"] = cursor.get("items", 0) + len(rows)
            cursor["page"] = page + 1
            if cursor.get("pages_total") and page >= cursor["pages_total"]:
                cursor["done"] = True
                outcome, why = "done", "reached the end of the listing"
                break
            if n_pages % CHUNK_PAGES == 0:
                flush()
                print(f"{key}: page {page:,} of {cursor.get('pages_total') or '?'}", flush=True)
            time.sleep(pause + random.uniform(0, pause / 4))
    except Refused as e:
        outcome, why = "refused", str(e)
    except ValueError as e:
        outcome, why = "refused", f"the answer was not the listing ({type(e).__name__})"
    finally:
        flush()
    fetchlib.event(f"wp_json:{key}", outcome, pages=n_pages, rows=n_items, total=cursor.get("total"),
                   held=cursor.get("items"), **({"why": why} if why else {}))
    print(f"{key}: {outcome}{' (' + why + ')' if why else ''} · {n_pages:,} pages, {n_items:,} items this run"
          f" · {cursor.get('items', 0):,} of {cursor.get('total') or '?'} held", flush=True)
    return 3 if outcome == "refused" else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sites", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pages", type=int, help="stop each publisher after this many pages (a trial)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--bronze-root", type=Path, default=bronze.BRONZE)
    ap.add_argument("--no-bronze", action="store_true")
    a = ap.parse_args()
    if a.list or not a.sites:
        for k, s in SITES.items():
            print(f"{k:<12} {s['source']:<26} {s['pause']:>3}s  {s['name']}")
        return 0
    unknown = [s for s in a.sites if s not in SITES]
    if unknown:
        ap.error(f"unknown publisher(s): {', '.join(unknown)} (see --list)")
    a.out.mkdir(parents=True, exist_ok=True)
    lock = open(a.out / ".reader.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another reader is already running on this folder; not starting a second")
        return 4
    worst = 0
    for key in a.sites:
        # one publisher's refusal says nothing about the next: go on, and report it at the end
        worst = max(worst, run(key, a.out, a.cache, a.pages, None if a.no_bronze else a.bronze_root))
        if (a.out / "STOP").exists():
            break
    return worst


if __name__ == "__main__":
    sys.exit(main())
