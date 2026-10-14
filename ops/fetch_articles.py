"""The text of the articles a question finds, for headlines the archive holds without one.

    .venv/bin/python -m ops.fetch_articles 'ولاعة OR ولاعات OR قداحة' --limit 100
    .venv/bin/python -m ops.fetch_articles 'سعر الطحين' --from 2023-10-07 --source web:safa,web:shehab

WHY. The archive holds 1.6 million outlet headlines read from sitemaps
(ops/fetch_sitemaps.py), with no text: a headline is an index. A figure an
infographic needs (what a lighter cost in Gaza in July 2025) is in the
article: «قبل حرب الإبادة، كان سعر القداحة لا يتجاوز نصف شيقل. اليوم، إن
وُجدت، تباع بسعر يصل إلى 70» (Shehab, 2 July 2025). This asks the archive the
question (read-only), takes the headlines it finds that have no text yet, and
reads those articles only: the text, the true headline and the minute the
outlet published it.

WHAT EACH OUTLET GIVES (measured 2026-10-14 on one article each): the
headline in og:title, the publication time in the page's datePublished, and
the text in paragraphs inside the article's container: `post-text…` (Safa,
Felesteen, Shehab, Sama) or `text-right` blocks (Arab48, less its "read also"
and app lines); older articles put the text straight in the container, broken
by <br>, and its lines of 25 letters or more are taken instead. A paragraph
outside the container (the footer's rights line, newsletter calls) is not
read. An article whose container gives no text is counted and not written.

THE POSTURE: one request every three seconds; at most --limit articles a run
(default 200); a refusal (any HTTP error but a missing page) ends the run with
what was read kept; every page kept as fetched in bronze (`article_<outlet>`).
Ledgered as `articles:<outlet>`. It writes data/raw/articles/<outlet>/
items-<UTC stamp>.ndjson.gz (id, url, title, text, published, fetched_at) and
site.json; the archive's `articles` reader loads them at rank 3, in place of
the headline (the headline's row keeps its earlier words in the history).
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
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                                       # noqa: E402
from ops import fetchlib                                        # noqa: E402
from ops.fetch_sitemaps import OUTLETS, UA                      # noqa: E402

OUT = ROOT / "data" / "raw" / "articles"
PAUSE = 3.0
BODY = {"web:safa": r"\bpost-text", "web:felesteen": r"\bpost-text", "web:shehab": r"\bpost-text",
        "web:samanews": r"\bpost-text", "web:arab48": r"\btext-right\b"}
NOT_TEXT = re.compile(r"^(اقرأ/ي أيضًا|اقرأ أيضا|اقرأ أيضًا|تابعوا تطبيق|تابع عرب 48|عن الايام$|عن الأيام$)")
_KEY = {o["source"]: k for k, o in OUTLETS.items()}


class Refused(Exception):
    pass


class _Body(HTMLParser):
    """The paragraphs inside the outlet's article container."""

    def __init__(self, container: str):
        super().__init__(convert_charrefs=True)
        self.want = re.compile(container)
        self.stack: list[bool] = []                 # for each open div: is it (or an ancestor) the container
        self.skip = 0
        self.cur: list[str] | None = None
        self.paras: list[str] = []
        self.loose: list[str] = []                  # text in the container outside any paragraph (older articles)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "div":
            inside = bool(self.stack and self.stack[-1]) or bool(self.want.search(a.get("class") or ""))
            self.stack.append(inside)
        elif tag == "p" and self.stack and self.stack[-1]:
            self.cur = []
        elif tag == "br":
            (self.cur if self.cur is not None else self.loose).append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag == "div" and self.stack:
            self.stack.pop()
        elif tag == "p" and self.cur is not None:
            t = re.sub(r"\s+", " ", "".join(self.cur)).strip()
            if t and not NOT_TEXT.match(t) and (not self.paras or self.paras[-1] != t):
                self.paras.append(t)
            self.cur = None

    def handle_data(self, data):
        if self.skip:
            return
        if self.cur is not None:
            self.cur.append(data)
        elif self.stack and self.stack[-1]:
            self.loose.append(data)

    def text(self) -> list[str]:
        """The paragraphs; for an article written without them (Safa's and Sama's
        older pages put the text straight in the container, broken by <br>),
        the container's own lines."""
        if self.paras:
            return self.paras
        lines = [re.sub(r"[ \t\u00a0]+", " ", x).strip() for x in "".join(self.loose).split("\n")]
        return [x for x in lines if len(x) >= 25 and not NOT_TEXT.match(x)]


def article_of(source: str, page: str) -> dict:
    """An article page → its headline, publication time and text."""
    og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', page) or \
        re.search(r'<meta[^>]+content="([^"]*)"[^>]+property="og:title"', page)
    pub = re.search(r'"datePublished"\s*:\s*"([^"]+)"', page) or \
        re.search(r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"', page)
    p = _Body(BODY[source])
    p.feed(page)
    published = None
    if pub:
        raw = pub.group(1).strip().replace(" ", "T", 1)
        try:
            dt = datetime.datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=2)))   # Arab48 writes local time
            published = dt.isoformat()
        except ValueError:
            published = None
    return {"title": html_mod.unescape(og.group(1)).strip() if og else None, "published": published,
            "text": "\n".join(p.text())}


def wanted(question: str, *, source: str | None, date_from: str | None, date_to: str | None,
           limit: int) -> list[dict]:
    """The headlines a question finds that have no text yet, newest first (read-only)."""
    from ops import ask_archive as A
    from resolve.db import connect
    sources = source or ",".join(sorted(BODY))
    with connect() as conn:
        conn.execute("SET default_transaction_read_only = on")
        found = A.search(conn, question, date_from=date_from, date_to=date_to, source=sources, limit=max(limit * 3, 50))
        ids = [t["doc_id"] for t in found["texts"]]
        rows = conn.execute("SELECT doc_id, source, external_id, url, title FROM document WHERE doc_id = ANY(%s)"
                            " AND via = 'sitemap' AND body = '' ORDER BY published_at DESC", (ids,)).fetchall()
    return [{"doc_id": r[0], "source": r[1], "id": r[2], "url": r[3], "title": r[4]} for r in rows][:limit]


def get(url: str, tries: int = 3) -> str:
    """One article page; a reply cut off mid-way is tried again, a minute apart."""
    p = urllib.parse.urlsplit(url)
    quoted = urllib.parse.urlunsplit((p.scheme, p.netloc, urllib.parse.quote(p.path), p.query, ""))
    for attempt in range(1, tries + 1):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(urllib.request.Request(quoted, headers={"User-Agent": UA}), timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise FileNotFoundError(url) from None
            raise Refused(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as e:
            if attempt == tries:
                raise Refused(f"network: {type(e).__name__} after {tries} tries") from None
            time.sleep(60 * attempt)
    raise Refused("unreachable")


def run(items: list[dict], out: Path, use_bronze: bool) -> int:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    by: dict[str, list[dict]] = {}
    facts = {"asked": len(items), "read": 0, "no_text": 0, "missing": 0}
    worst = 0
    for it in items:
        try:
            page = get(it["url"])
        except FileNotFoundError:
            facts["missing"] += 1
            continue
        except Refused as e:
            print(f"refused ({e}) after {facts['read']} articles; what was read is kept")
            facts["refused"] = str(e)
            worst = 3
            break
        key = _KEY[it["source"]]
        if use_bronze:
            bronze.put(f"article_{key}", page, "html", url=it["url"])
        a = article_of(it["source"], page)
        if not a["text"]:
            facts["no_text"] += 1
            continue
        by.setdefault(key, []).append({"id": it["id"], "url": it["url"], "title": a["title"] or it["title"],
                                       "text": a["text"], "published": a["published"],
                                       "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        facts["read"] += 1
    for key, recs in by.items():
        o = OUTLETS[key]
        d = out / key
        d.mkdir(parents=True, exist_ok=True)
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs).encode("utf-8")
        tmp = d / f"items-{stamp}.ndjson.gz.tmp"
        tmp.write_bytes(gzip.compress(body, compresslevel=6))
        tmp.replace(d / f"items-{stamp}.ndjson.gz")
        (d / "site.json").write_text(json.dumps({"name": o["name"], "home_url": o["home_url"], "source": o["source"],
                                                 "kind": "outlet", "lang": "ar"}, ensure_ascii=False, indent=1))
        fetchlib.event(f"articles:{key}", "ok" if worst == 0 else "refused", rows=len(recs))
    print(f"{facts['read']} articles read of {facts['asked']} asked · {facts} · "
          f"{', '.join(f'{k} {len(v)}' for k, v in sorted(by.items()))}")
    return worst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("question")
    ap.add_argument("--source", help="archive publisher keys, comma-separated (default: the outlets this reads)")
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--list", action="store_true", help="say which articles would be read; read none")
    ap.add_argument("--no-bronze", action="store_true")
    a = ap.parse_args()
    items = wanted(a.question, source=a.source, date_from=a.date_from, date_to=a.date_to, limit=a.limit)
    if a.list:
        for it in items:
            print(it["source"], it["id"][:40], it["title"][:90])
        print(f"{len(items)} articles would be read")
        return 0
    return run(items, a.out, not a.no_bronze)


if __name__ == "__main__":
    sys.exit(main())
