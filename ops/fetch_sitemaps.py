"""Every headline an outlet's sitemap lists, with its date, into the archive's raw tree.

    .venv/bin/python -m ops.fetch_sitemaps safa felesteen shehab sama arab48 wafa
    .venv/bin/python -m ops.fetch_sitemaps safa --from-cache        # parse what is already fetched

WHY. Zaid, 13 October 2026: the archive should answer a question nobody asked
yet (what lighters cost in Gaza, when water ran out) across everything the
outlets wrote. The large Palestinian Arabic outlets publish sitemaps that list
every item since they began, each with its address and a date, and four of
them its headline too; read whole, they are the index of about 1.9 million
items. Headlines first; an item's text can be read later, on demand.

WHAT EACH OUTLET GIVES (measured 2026-10-14 on one sub-sitemap each; robots
files read the same day allow the sitemaps and name no crawler of ours):

  safa       post-1..43 × 10,000 · headline in <image:title> · date: last
             modified, kept to the day when it falls in the month of the
             image's folder (95.7% of a sample), else that month
  felesteen  post-1..21 × 10,000 · as Safa (95.4%)
  shehab     post-1..19 × 10,000 · headline in <image:title> · as Safa,
             except that the site re-saved its files 2 to 18 on 30 September,
             1 and 4 October 2026: a day that covers 5% of a file dates
             nothing, and those items take the image folder's month. Files 3
             to 8 (about 60,000 items, 2017 to 2021) have no image month
             either: they are left out, counted, never dated by guess
  sama       part-1..25 × 25,000 · headline from the address · last modified,
             which follows the post ids without one inversion in 25,000
  arab48     news1..9 × 49,000 · headline and day from the address, except
             that the site moved its archive in 2010 and gave the moved items
             addresses of that year: 53,429 items carry 2010 in their address,
             6,058 were last modified that day and the rest in their own years
             (2003, 2007 ...). Where the last-modified day is earlier than the
             address's, it is the item's date
  wafa       one sitemap a day from 5 February 2020 (2,328 days) · headline and
             day from the address

  Palestine Today is not read: its addresses cut a headline after about thirty
  letters and its image captions complete it for 5% of items.

A headline taken from an address is the address's words (the outlet writes it
from the headline, dropping punctuation); `title_from` says which. It is an
index, not a quotation: an address drops a number's decimal point and commas
(Felesteen's "3.69 مليار جرعة" reads «369 مليار») and splits a tanwin
(«منزلًا» reads «منزل ا»), so a figure in such a headline is read from the
article before it is used. An image title is taken as the headline only when
it opens with the address's first words (Shehab's image titles are photo
captions). A date's source is `date_basis`; an item with no date this rule
can read (Shehab's items without an image) is left out and counted.

THE POSTURE: one request every three seconds; a refusal (any HTTP error but a
missing file) ends that outlet with what it read kept; every sub-sitemap is
kept as fetched in the cache and in bronze (`sitemap_<key>`); a sub-sitemap is
asked for once, except the newest, which is asked for again each run; a file
whose entries read fewer than 95% of its addresses is refused (the file on
disk is kept). Ledgered as `sitemap:<key>`.

WHAT IT WRITES, under data/raw/sitemaps/<key>/:
  items-<sub-sitemap>.ndjson.gz   id, url, title, title_from, date, precision,
                                  date_basis, lastmod
  site.json                       the outlet, as the archive's loader needs it
"""
from __future__ import annotations

import argparse
import gzip
import html as html_mod
import http.client
import json
import re
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

UA = "zaidlab-palestine-archive/1.0 (https://zaidlab.xyz; personal research archive; one request every three seconds)"
OUT = ROOT / "data" / "raw" / "sitemaps"
CACHE = ROOT / "data" / "cache" / "sitemaps"
PAUSE = 3.0

OUTLETS = {
    "safa": {"name": "Safa News Agency (وكالة صفا)", "home_url": "https://safa.ps/", "source": "web:safa",
             "index": "https://safa.ps/sitemap.xml", "sub": r"/uploads/sitemaps/post-(\d+)\.xml$",
             "newest": "max", "id": r"/post/(\d+)(?:/|$)", "title": "image", "date": "lastmod_in_image_month"},
    "felesteen": {"name": "Felesteen (فلسطين أون لاين)", "home_url": "https://felesteen.news/",
                  "source": "web:felesteen", "index": "https://felesteen.news/sitemap.xml",
                  "sub": r"/uploads/sitemaps/post-(\d+)\.xml$", "newest": "max", "id": r"/post/(\d+)(?:/|$)",
                  "title": "image", "date": "lastmod_in_image_month"},
    "shehab": {"name": "Shehab News Agency (وكالة شهاب)", "home_url": "https://shehabnews.com/",
               "source": "web:shehab", "index": "https://shehabnews.com/sitemap.xml",
               "sub": r"/uploads/sitemaps/post-(\d+)\.xml$", "newest": "max", "id": r"/post/(\d+)(?:/|$)",
               "title": "image", "date": "lastmod_in_image_month"},
    "sama": {"name": "Sama News Agency (وكالة سما الإخبارية)", "home_url": "https://samanews.ps/ar/",
             "source": "web:samanews", "index": "https://samanews.ps/ar/sitemap.xml",
             "sub": r"/ar/sitemap/google/part-(\d+)-sitemap\.xml$", "newest": "min", "id": r"/ar/post/(\d+)(?:/|$)",
             "title": "address", "date": "lastmod"},
    "arab48": {"name": "Arab48 (عرب 48)", "home_url": "https://www.arab48.com/", "source": "web:arab48",
               "index": "https://www.arab48.com/sitemap/https/sitemapIndex",
               "sub": r"data\.arab48\.com/sitemap/https/news(\d+)\.xml$", "newest": "min", "id": None,
               "title": "address", "date": "address_or_earlier_lastmod"},
    "wafa": {"name": "WAFA, the Palestinian News & Info Agency (وفا)", "home_url": "https://www.wafa.ps/",
             "source": "web:wafa", "index": "https://www.wafa.ps/sitemap.xml",
             "sub": r"sitemap\.xml\?yyyy=(\d{4})&mm=(\d{1,2})&dd=(\d{1,2})$", "newest": "days:3", "id": None,
             "title": "address", "date": "address"},
    # Palestine Today (2026-10-14): its addresses cut the headline after about 30 characters, so an
    # address is never a headline; the image's caption is, when it opens with the address's first
    # words. The others are listed apart (untitled-*.ndjson.gz) for a reader of their pages.
    "paltoday": {"name": "Palestine Today (فلسطين اليوم)", "home_url": "https://paltoday.ps/ar",
                 "source": "web:paltoday", "index": "https://paltoday.ps/ar/sitemap.xml",
                 "sub": r"/ar/uploads/sitemaps/post-(\d+)\.xml$", "newest": "max", "id": r"/ar/post/(\d+)(?:/|$)",
                 "title": "image_only", "date": "lastmod"},
}
_ENTRY = re.compile(r"<url>(.*?)</url>", re.S)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
_LASTMOD = re.compile(r"<lastmod>\s*(.*?)\s*</lastmod>", re.S)
_IMG = re.compile(r"<image:loc>\s*(.*?)\s*</image:loc>", re.S)
_IMG_TITLE = re.compile(r"<image:title>\s*(.*?)\s*</image:title>", re.S)
_IMG_CAPTION = re.compile(r"<image:caption>\s*(.*?)\s*</image:caption>", re.S)
_ADDR_DATE = re.compile(r"/(\d{4})/(\d{1,2})/(\d{1,2})/")
_IMG_MONTH = re.compile(r"/(20\d\d|19\d\d)/(\d\d)/")


class Refused(Exception):
    pass


UNDATED = {"undated": True}           # an item whose date no rule can vouch for: counted, not written


def _unescape(s: str) -> str:
    s = s.strip()
    if s.startswith("<![CDATA[") and s.endswith("]]>"):
        s = s[9:-3]
    return html_mod.unescape(s).strip()


def address_title(url: str) -> str:
    """The headline an address carries: its last segment, %-decoded, dashes as spaces."""
    seg = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    return re.sub(r"\s+", " ", seg.replace("-", " ").replace("_", " ")).strip()


def _letters(s: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06FF]+", s.replace("ـ", ""))


def _same_start(caption: str, from_address: str) -> bool:
    """An image's title is the item's headline only when it opens with the
    address's first three words: Shehab's image titles are the photo's
    caption ("القيادي في حركة حماس عبدالرحمن شديد" under an address that reads
    «شديد من المبكر الحديث عن قرب التوصل لاتفاق …»)."""
    a, b = _letters(caption)[:3], _letters(from_address)[:3]
    return bool(a) and len(b) >= 2 and a[:len(b)] == b[:len(a)]


def _covers_cut_address(caption: str, from_address: str) -> bool:
    """For an address cut short (Palestine Today, about 30 characters): the
    caption is the headline only when it holds every whole word of the address
    (all but the last, which may be cut) and runs to three words or more. A
    one-word label that matches the address's first word («الديمقراطية» over
    «الديمقراطية اقتحام مؤسسة الضمي…») is a caption, not the headline."""
    a, b = _letters(caption), _letters(from_address)
    if b and b[0] == "خبر" and (not a or a[0] != "خبر"):
        b = b[1:]                         # older addresses open with «خبر-» ("news-") before the headline
    need = b[:-1]
    return len(need) >= 2 and len(a) >= max(3, len(need)) and a[:len(need)] == need


def entry_of(o: dict, block: str, resaved: set[str] | frozenset = frozenset()) -> dict | None:
    """One <url> block → a headline record, or None when it is not an item.
    `resaved`: the last-modified days the file's entries share in bulk (a
    re-save of the site, not an edit of the item), which date nothing."""
    m = _LOC.search(block)
    if not m:
        return None
    url = _unescape(m.group(1))
    lastmod = _unescape(_LASTMOD.search(block).group(1)) if _LASTMOD.search(block) else None
    if lastmod and (lastmod[:4] < "1995" or lastmod[:10] in resaved):
        lastmod = None                    # 1970-01-01 (Safa: 16 items) or the site's re-save day: no date
    img = _IMG.search(block)
    img_title = _IMG_TITLE.search(block) or _IMG_CAPTION.search(block)
    rec: dict = {"url": url}
    if o["id"]:
        mid = re.search(o["id"], urllib.parse.urlsplit(url).path)
        if not mid:
            return None
        rec["id"] = mid.group(1)
    else:
        p = urllib.parse.urlsplit(url)
        rec["id"] = urllib.parse.unquote(p.path)
    from_address = address_title(url)
    caption = _unescape(img_title.group(1)) if img_title else ""
    if o["title"] == "image" and caption and _same_start(caption, from_address):
        rec["title"], rec["title_from"] = caption, "headline"                 # the address's words, punctuated
    elif o["title"] == "image_only" and caption and _covers_cut_address(caption, from_address):
        rec["title"], rec["title_from"] = caption, "headline"
    elif o["title"] == "image_only":
        rec["title"], rec["title_from"], rec["untitled"] = None, None, True    # a cut-short address is no headline
    else:
        rec["title"], rec["title_from"] = from_address, "address"
    if not rec["title"] and not rec.get("untitled"):
        return None
    month = None
    if img:
        mm = _IMG_MONTH.search(_unescape(img.group(1)))
        if mm:
            month = f"{mm.group(1)}-{mm.group(2)}"
    rule = o["date"]
    if rule in ("address", "address_or_earlier_lastmod"):
        md = _ADDR_DATE.search(urllib.parse.unquote(url))
        if not md:
            return UNDATED
        y, mo, d = (int(x) for x in md.groups())
        rec.update(date=f"{y:04d}-{mo:02d}-{d:02d}", precision="day", date_basis="the address")
        if rule == "address_or_earlier_lastmod" and lastmod and lastmod[:10] < rec["date"]:
            rec.update(date=lastmod[:10], date_basis="last modified, earlier than the address: a migrated item")
    elif rule == "lastmod" and lastmod:
        rec.update(date=lastmod[:10], precision="day", date_basis="last modified")
    elif rule == "lastmod_in_image_month":
        if lastmod and month and lastmod[:7] == month:
            rec.update(date=lastmod[:10], precision="day", date_basis="last modified, in the image folder's month")
        elif month:
            rec.update(date=f"{month}-01", precision="month", date_basis="the image folder's month")
        elif lastmod:
            rec.update(date=lastmod[:10], precision="day", date_basis="last modified")
        else:
            return UNDATED
    elif rule == "image_month" and month:
        rec.update(date=f"{month}-01", precision="month", date_basis="the image folder's month")
    else:
        return UNDATED
    if lastmod:
        rec["lastmod"] = lastmod
    return rec


def parse(o: dict, xml: str) -> tuple[list[dict], int, int]:
    """A sub-sitemap → its records and the number of entries it holds. A
    last-modified day that covers 5% or more of a file's entries (and at least
    200 of them) is a re-save of the site, not a day's news: these sites carry
    about 1% of a file a day. Shehab re-saved its files 2-18 on 30 September,
    1 and 4 October 2026; those days date nothing."""
    import collections
    blocks = _ENTRY.findall(xml)
    days = collections.Counter(m.group(1)[:10] for m in (_LASTMOD.search(b) for b in blocks) if m)
    resaved = frozenset(d for d, n in days.items() if n >= 200 and n >= 0.05 * len(blocks))
    got = [entry_of(o, b, resaved) for b in blocks]
    undated = sum(1 for r in got if r is UNDATED)
    return [r for r in got if r and r is not UNDATED], len(blocks), undated


def get(url: str, tries: int = 3) -> bytes:
    """One sub-sitemap. A reply cut off mid-way (IncompleteRead) or a broken
    connection is tried again, a minute apart, then refused: measured 2026-10-14
    12:01 UTC, WAFA's day file of 21 August 2025 came back cut off and ended the
    run instead of being tried again."""
    for attempt in range(1, tries + 1):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
                body = r.read()
            return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(url) from None
            raise Refused(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as e:
            if attempt == tries:
                raise Refused(f"network: {type(e).__name__} after {tries} tries") from None
            time.sleep(60 * attempt)
    raise Refused("unreachable")


def subs_of(o: dict, index: str) -> list[tuple[str, str]]:
    """(name, url) of every sub-sitemap the index lists, oldest first."""
    out = []
    for loc in _LOC.findall(index):
        url = _unescape(loc)
        m = re.search(o["sub"], url)
        if not m:
            continue
        g = m.groups()
        name = (f"{int(g[0]):04d}-{int(g[1]):02d}-{int(g[2]):02d}" if len(g) == 3 else f"{int(g[0]):03d}")
        out.append((name, url))
    order = sorted(out)
    return list(reversed(order)) if o["newest"] == "min" else order       # Sama's and Arab48's file 1 is newest


def newest(o: dict, subs: list[tuple[str, str]]) -> set[str]:
    if not subs:
        return set()
    if o["newest"].startswith("days:"):
        return {n for n, _ in subs[-int(o["newest"].split(":")[1]):]}
    return {subs[-1][0]} if o["newest"] == "max" else {subs[-1][0]}


def run(key: str, out: Path, cache_root: Path, from_cache: bool, use_bronze: bool) -> int:
    o = OUTLETS[key]
    label = f"sitemap:{key}"
    cache = cache_root / key
    cache.mkdir(parents=True, exist_ok=True)
    d = out / key
    d.mkdir(parents=True, exist_ok=True)
    facts = {"files": 0, "files_fetched": 0, "items": 0, "missing": [], "refused_files": []}
    try:
        idx_file = cache / "index.xml.gz"
        if from_cache:
            index = gzip.decompress(idx_file.read_bytes()).decode("utf-8", "replace")
        else:
            raw = get(o["index"])
            idx_file.write_bytes(gzip.compress(raw))
            if use_bronze:
                bronze.put(f"sitemap_{key}", raw, "xml", url=o["index"])
            index = raw.decode("utf-8", "replace")
        subs = subs_of(o, index)
        fresh = newest(o, subs)
        for name, url in subs:
            if (d / "STOP").exists() or (out / "STOP").exists():
                facts["stopped"] = True
                break
            f = cache / f"{name}.xml.gz"
            if f.exists() and (from_cache or name not in fresh):
                xml = gzip.decompress(f.read_bytes()).decode("utf-8", "replace")
            elif from_cache:
                continue
            else:
                try:
                    raw = get(url)
                except FileNotFoundError:
                    facts["missing"].append(name)
                    continue
                f.write_bytes(gzip.compress(raw))
                if use_bronze:
                    bronze.put(f"sitemap_{key}", raw, "xml", url=url)
                facts["files_fetched"] += 1
                xml = raw.decode("utf-8", "replace")
            items, blocks, undated = parse(o, xml)
            facts["undated"] = facts.get("undated", 0) + undated
            if blocks and len(items) < 0.95 * (blocks - undated):
                facts["refused_files"].append(f"{name}: {len(items)} of {blocks - undated} dated entries read")
                continue
            untitled = [i for i in items if i.get("untitled")]
            if untitled:                                  # read later from their pages; the archive skips this file
                facts["untitled"] = facts.get("untitled", 0) + len(untitled)
                (d / f"untitled-{name}.ndjson.gz").write_bytes(gzip.compress("".join(
                    json.dumps({k: i[k] for k in ("id", "url", "date", "precision") if k in i}, ensure_ascii=False)
                    + "\n" for i in untitled).encode("utf-8")))
                items = [i for i in items if not i.get("untitled")]
            target = d / f"items-{name}.ndjson.gz"
            body = "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items).encode("utf-8")
            if target.exists() and gzip.decompress(target.read_bytes()) == body:
                facts["files"] += 1
                facts["items"] += len(items)
                continue                                  # unchanged: the loader's mark stays as it is
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(body, compresslevel=6))
            tmp.replace(target)
            facts["files"] += 1
            facts["items"] += len(items)
            if facts["files"] % 25 == 0:
                print(f"  {key}: {facts['files']} files, {facts['items']:,} items", flush=True)
    except Refused as e:
        fetchlib.event(label, "refused", why=str(e), **{k: v for k, v in facts.items() if k != "missing"})
        print(f"{key}: refused ({e}) after {facts['files']} files; what was read is kept")
        _site(d, o)
        return 3
    _site(d, o)
    facts["missing"] = len(facts["missing"])
    fetchlib.event(label, "ok", rows=facts["items"], **{k: v for k, v in facts.items() if k != "items"})
    print(f"{key}: {facts['files']} files, {facts['items']:,} items · {facts}")
    return 0


def _site(d: Path, o: dict) -> None:
    (d / "site.json").write_text(json.dumps({"name": o["name"], "home_url": o["home_url"], "source": o["source"],
                                             "kind": "outlet", "lang": "ar"}, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("outlets", nargs="+", choices=sorted(OUTLETS))
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--from-cache", action="store_true", help="parse the sub-sitemaps already fetched; ask for nothing")
    ap.add_argument("--no-bronze", action="store_true")
    ap.add_argument("--bronze-root", type=Path, default=None, help="keep the bronze copies under this folder")
    a = ap.parse_args()
    if a.bronze_root:
        bronze.BRONZE = a.bronze_root
    worst = 0
    for k in a.outlets:
        worst = max(worst, run(k, a.out, a.cache, a.from_cache, not a.no_bronze))
    return worst


if __name__ == "__main__":
    sys.exit(main())
