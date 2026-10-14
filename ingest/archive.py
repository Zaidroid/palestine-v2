"""Fill the archive (`document`, migration 116) from what the house holds.

    .venv/bin/python -m ingest.archive                 # every reader, DRY: reads, compares, writes nothing
    .venv/bin/python -m ingest.archive --apply         # writes
    .venv/bin/python -m ingest.archive tg_public v1_news --apply
    .venv/bin/python -m ingest.archive --reindex --apply   # rewrite search vectors of an older rule

Dry is the default: a run without --apply opens no transaction that writes,
so it is safe on the live store and on a read-only connection.

THE READERS, each a function that yields texts as the publisher wrote them:

  tg_public   data/raw/tg_public/<channel>/posts-*.ndjson.gz, written by
              ops/fetch_telegram_public.py. A file already loaded (same size
              and time) is not opened again.
  wp_json     data/raw/wp/<publisher>/items-*.ndjson.gz, written by
              ops/fetch_wp_json.py: a publisher's own listing, full text
              (the UN's Palestine documents, PCHR, POICA, several outlets).
  reports     data/raw/reports/<publisher>/items-*.ndjson.gz, in the same shape:
              a publisher's periodic reports made text (ops/fetch_gazacham.py,
              the Gaza Chamber of Commerce's weekly goods reports).
  chronology  data/raw/chronology/<publisher>/entries.ndjson.gz, written by
              ops/fetch_chronology.py: a published chronology, one dated
              event a row (kind `entry`), precise to the day, month or year.
  v1_news     v1's news.db: 15 outlets' articles, the full text where v1 has it.
  v1_alerts   v1's alerts.db: the channel posts and feed items v1 keeps.
  v2_claim    this store's own channel and feed messages, WITHOUT the two road
              and fuel robots (they post tables, not news). Read from the last
              claim it reached.

ONE TEXT, ONE ROW. A row is (publisher, the publisher's own id). The same
Telegram post can arrive from three readers; the fuller reader wins
(`via_rank`: for a channel post the public page 3, this store's poller 2,
v1's alert 1; for an article v1's full text 3, v1's title and summary 2, this
store's feed line 1), a thinner one never overwrites it, and a text whose words changed moves its old words to `document_history`
(the table's trigger) — an edited post is two versions, not one overwrite.

A post with no words (a photo alone) is not a document. It stays in the raw
file; the report counts it as `no_text`.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html as html_mod
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import archive_text as T                           # noqa: E402
from resolve.db import connect, v1_path                         # noqa: E402

TG_PUBLIC = ROOT / "data" / "raw" / "tg_public"
WP = ROOT / "data" / "raw" / "wp"
CHRON = ROOT / "data" / "raw" / "chronology"
REPORTS = ROOT / "data" / "raw" / "reports"
ROBOTS = ("tg_palhubappfuel", "tg_palhubapproad")    # tables every 15 minutes, not news
SERVICE = {"channel photo updated", "channel created", "channel name was changed", "channel photo removed"}
BATCH = 2000
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_AR = re.compile(r"[ء-ي]")
_HE = re.compile(r"[א-ת]")
_LA = re.compile(r"[A-Za-z]")

# v1's outlet ids → the registry's key for the same publisher, where there is one
V1_OUTLET_SOURCE = {
    "middleeasteye": "middle_east_eye_rss", "aljazeera-en": "al_jazeera_rss",
    "middle-east-monitor": "memo", "haaretz": "haaretz_rss", "bbc-middle-east": "bbc",
    "mondoweiss": "mondoweiss_rss", "electronic-intifada": "electronic_intifada_rss",
    "palinfo-en": "palinfo", "qudsn": "rss_qudsn",
}
V2_FEED = {"rss_qudsn": ("web:qudsn", "Quds News Network", "https://qudsn.co"),
           "rss_palinfo": ("web:palinfo_ar", "Palestinian Information Center (Arabic)", "https://palinfo.com")}


@dataclass
class Source:
    key: str
    name: str
    kind: str
    home_url: str | None = None
    lang: str | None = None
    source_key: str | None = None


@dataclass
class Doc:
    source: str
    external_id: str
    kind: str
    body: str
    via: str
    via_rank: int
    url: str | None = None
    title: str | None = None
    extra: str | None = None
    lang: str | None = None
    published_at: str | None = None
    precision: str = "second"
    attrs: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for k in ("title", "body", "extra"):          # the database refuses a NUL inside text
            v = getattr(self, k)
            if v and "\x00" in v:
                setattr(self, k, v.replace("\x00", ""))
        self.published_at = stamp(self.published_at)

    def content_hash(self) -> str:
        parts = [_WS.sub(" ", (p or "")).strip() for p in (self.title, self.body, self.extra)]
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def stamp(s: str | None) -> str | None:
    """A publisher's date as ISO text the database will take, or None. One
    unreadable date must not sink a batch of two thousand rows."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    # a chronology reaches back to the 1500s; a mistyped year (0001, 0201) is still no date
    return d.isoformat() if 1000 <= d.year <= datetime.now(timezone.utc).year + 1 else None


def guess_lang(text: str) -> str | None:
    """Arabic, English or Hebrew by which letters fill the text. Cheap on
    purpose: a million posts pass through here."""
    s = text[:600]
    n = {"ar": len(_AR.findall(s)), "he": len(_HE.findall(s)), "en": len(_LA.findall(s))}
    best = max(n, key=n.get)
    return best if n[best] >= 8 else None


def tidy_url(u: str | None) -> str | None:
    """The address as the publisher gave it, without the feed's tracking tail:
    what a reader is sent to. `clean_url` is the key; this is the link."""
    if not u:
        return None
    p = urlsplit(u.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if k != "traffic_source" and not k.startswith("utm_")]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))


def clean_html(s: str | None) -> str:
    return _WS.sub(" ", html_mod.unescape(_TAG.sub(" ", s or ""))).strip()


def clean_url(u: str | None) -> str | None:
    """An article's address in ONE spelling, so the same article read from two
    feeds is one row: no tracking tail, no `www.`, the host in lower case.
    Quds News writes one article three ways (`/post/218203`,
    `/post?id=218203&slug=…`, and the same under `www.`): all become the first."""
    if not u:
        return None
    p = urlsplit(u.strip())
    host = p.netloc.lower().removeprefix("www.")
    query = dict(parse_qsl(p.query, keep_blank_values=True))
    if host == "qudsn.co" and p.path.rstrip("/") == "/post" and query.get("id", "").isdigit():
        return f"https://qudsn.co/post/{query['id']}"
    q = [(k, v) for k, v in query.items() if k != "traffic_source" and not k.startswith("utm_")]
    return urlunsplit((p.scheme.lower() or "https", host, p.path, urlencode(q), ""))


# ── the readers ─────────────────────────────────────────────────────────────
def tg_post(channel: str, p: dict) -> Doc | None:
    """One line of a public-page file → a document, or None when the post has
    no words of its own."""
    text = (p.get("text") or "").strip()
    pv = p.get("preview") or {}
    extra = "\n".join(x for x in (pv.get("title"), pv.get("description")) if x) or None
    if text.lower() in SERVICE or not (text or extra):
        return None
    attrs = {k: p[k] for k in ("views", "media", "fwd_from", "reply_to", "edited", "author") if p.get(k)}
    if p.get("links"):
        attrs["links"] = p["links"][:20]
    if pv.get("url"):
        attrs["preview_url"] = pv["url"]
    return Doc(source=f"tg:{channel.lower()}", external_id=str(p["id"]), kind="post", body=text,
               extra=extra, url=f"https://t.me/{channel}/{p['id']}", lang=guess_lang(text or extra or ""),
               published_at=p.get("date"), via="tg_public", via_rank=3, attrs=attrs)


def read_tg_public(root: Path = TG_PUBLIC, loaded: dict | None = None,
                   only: set[str] | None = None) -> Iterator[tuple[Source, str, str, list[Doc], int]]:
    """Yields (source, file label, file mark, documents, posts without words)
    for every file not already loaded."""
    loaded = loaded or {}
    if not root.exists():
        return
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if only and d.name.lower() not in only:
            continue
        meta = json.loads((d / "channel.json").read_text()) if (d / "channel.json").exists() else {}
        src = Source(f"tg:{d.name.lower()}", meta.get("title") or f"Telegram @{d.name}", "channel",
                     f"https://t.me/{d.name}", source_key=f"tg_{d.name.lower()}")
        for f in sorted(d.glob("posts-*.ndjson.gz")):
            st = f.stat()
            label, mark = f"{d.name}/{f.name}", f"{st.st_size}:{int(st.st_mtime)}"
            if loaded.get(label) == mark:
                continue
            docs, empty = [], 0
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    doc = tg_post(d.name, json.loads(line))
                    if doc is None:
                        empty += 1
                    else:
                        docs.append(doc)
            yield src, label, mark, docs, empty


def wp_item(site: dict, item: dict, terms: dict) -> Doc | None:
    """One line of a publisher's listing file → a document."""
    title = (item.get("title") or "").strip() or None
    body = (item.get("text") or "").strip() or (item.get("excerpt") or "").strip()
    if not (title or body):
        return None
    link = item.get("link")
    day_only = bool(site.get("day_only"))
    # a filing system's hour is the hour of filing: keep the document's day
    when = (item.get("date") or "")[:10] + "T00:00:00+00:00" if day_only and item.get("date") else (
        item.get("date_gmt") or item.get("date"))
    attrs: dict = {"wp_id": item["id"]}
    named = {tax: [terms.get(tax, {}).get(str(i), str(i)) for i in ids]
             for tax, ids in (item.get("terms") or {}).items()}
    if named:
        attrs["terms"] = named
    return Doc(source=site["source"], external_id=clean_url(link) or f"{site['key']}:{item['id']}",
               kind=site["doc_kind"], title=title, body=body, url=tidy_url(link),
               lang=guess_lang(body or title or ""), published_at=when,
               precision="day" if day_only else "second", via="wp_json", via_rank=3, attrs=attrs)


def read_wp(root: Path = WP, loaded: dict | None = None,
            only: set[str] | None = None) -> Iterator[tuple[Source, str, str, list[Doc], int]]:
    """Yields (source, file label, file mark, documents, items without words)
    for every listing file not already loaded."""
    loaded = loaded or {}
    if not root.exists():
        return
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "site.json").exists()):
        if only and d.name.lower() not in only:
            continue
        site = json.loads((d / "site.json").read_text())
        terms = json.loads((d / "terms.json").read_text()) if (d / "terms.json").exists() else {}
        src = Source(site["source"], site["name"], site["kind"], site.get("home_url"))
        for f in sorted(d.glob("items-*.ndjson.gz")):
            st = f.stat()
            label, mark = f"{d.name}/{f.name}", f"{st.st_size}:{int(st.st_mtime)}"
            if loaded.get(label) == mark:
                continue
            docs, empty = [], 0
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    doc = wp_item(site, json.loads(line), terms)
                    if doc is None:
                        empty += 1
                    else:
                        docs.append(doc)
            yield src, label, mark, docs, empty


def chron_entry(site: dict, e: dict) -> Doc:
    """One event of a published chronology → a document of kind `entry`. Its
    title is the event; the kinds the publisher gave it are searchable beside it."""
    attrs = {k: e[k] for k in ("date_text", "tags", "end", "end_precision", "file") if e.get(k)}
    return Doc(source=site["source"], external_id=str(e["id"]), kind="entry", title=e.get("title") or None,
               body=e.get("text") or "", extra=", ".join(e.get("tags") or []) or None, url=e.get("url"),
               lang=guess_lang(e.get("title") or e.get("text") or ""), published_at=e["date"] + "T00:00:00+00:00",
               precision=e["precision"], via="chronology", via_rank=3, attrs=attrs)


def read_chronology(root: Path = CHRON, loaded: dict | None = None,
                    only: set[str] | None = None) -> Iterator[tuple[Source, str, str, list[Doc], int]]:
    """Yields (source, file label, file mark, documents, 0) for every
    chronology file not already loaded (ops/fetch_chronology.py writes them)."""
    loaded = loaded or {}
    if not root.exists():
        return
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "site.json").exists()):
        if only and d.name.lower() not in only:
            continue
        site = json.loads((d / "site.json").read_text())
        src = Source(site["source"], site["name"], "chronology", site.get("home_url"), lang=site.get("lang"))
        for f in sorted(d.glob("entries*.ndjson.gz")):
            st = f.stat()
            label, mark = f"{d.name}/{f.name}", f"{st.st_size}:{int(st.st_mtime)}"
            if loaded.get(label) == mark:
                continue
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                docs = [chron_entry(site, json.loads(line)) for line in fh]
            yield src, label, mark, docs, 0


def read_v1_news(path: Path | None = None) -> Iterator[tuple[Source, list[Doc], int]]:
    path = path or v1_path("services/westbank-alerts/data/news.db")
    if not path.exists():
        return
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    by: dict[str, tuple[Source, dict[str, Doc]]] = {}
    empty = 0
    for r in con.execute("SELECT id, guid_hash, source_id, source_name, language, category, title, link,"
                         " description, body, author, published_at, topics FROM articles ORDER BY id"):
        sid = r["source_id"] or "unknown"
        key = "web:" + sid.replace("-", "_")
        src, docs = by.setdefault(key, (Source(key, r["source_name"] or sid, "outlet", lang=r["language"],
                                               source_key=V1_OUTLET_SOURCE.get(sid)), {}))
        title = clean_html(r["title"])
        summary = clean_html(r["description"])
        full = (r["body"] or "").strip()
        body = full if len(full) > len(summary) else summary
        if not (title or body):
            empty += 1
            continue
        ext = clean_url(r["link"]) or f"v1:{r['guid_hash']}"
        attrs = {"v1_id": r["id"]}
        for k in ("category", "author"):
            if r[k]:
                attrs[k] = r[k]
        if r["topics"]:
            try:
                attrs["topics"] = json.loads(r["topics"])
            except ValueError:
                pass
        attrs["full_text"] = bool(full and body is full)
        doc = Doc(source=key, external_id=ext, kind="article", title=title or None, body=body,
                  extra=summary if (body is full and summary and summary not in full) else None,
                  url=tidy_url(r["link"]), lang=r["language"] or guess_lang(body or title),
                  published_at=r["published_at"], via="v1_news", via_rank=3 if attrs["full_text"] else 2,
                  attrs=attrs)
        old = docs.get(ext)
        if old is None or len(doc.body) >= len(old.body):      # the same address twice: keep the fuller
            docs[ext] = doc
    con.close()
    for i, (src, docs) in enumerate(by.values()):
        yield src, list(docs.values()), empty if i == 0 else 0


def read_v1_alerts(path: Path | None = None) -> Iterator[tuple[Source, list[Doc], int]]:
    path = path or v1_path("services/westbank-alerts/data/alerts.db")
    if not path.exists():
        return
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    by: dict[str, tuple[Source, list[Doc]]] = {}
    empty = 0
    for r in con.execute("SELECT id, source, source_msg_id, source_type, raw_text, timestamp, type, area, title"
                         " FROM alerts ORDER BY id"):
        text = (r["raw_text"] or "").strip()
        if not text:
            empty += 1
            continue
        name = (r["source"] or "unknown").lower()
        tg = r["source_type"] == "telegram"
        key = f"tg:{name}" if tg else f"web:{name}"
        src, docs = by.setdefault(key, (Source(key, f"Telegram @{name}" if tg else name, "channel" if tg else "outlet",
                                               f"https://t.me/{name}" if tg else None,
                                               source_key=f"tg_{name}" if tg else None), []))
        ts = r["timestamp"]
        docs.append(Doc(source=key, external_id=str(r["source_msg_id"]) if tg else f"v1alert:{r['source_msg_id']}",
                        kind="post" if tg else "article", body=text,
                        url=f"https://t.me/{name}/{r['source_msg_id']}" if tg else None,
                        lang=guess_lang(text), published_at=ts,
                        via="v1_alerts", via_rank=1,
                        attrs={k: v for k, v in (("v1_id", r["id"]), ("v1_type", r["type"]), ("v1_area", r["area"]),
                                                 ("v1_label", r["title"])) if v}))
    con.close()
    for i, (src, docs) in enumerate(by.values()):
        yield src, docs, empty if i == 0 else 0


def read_v2_claim(conn, after: int) -> Iterator[tuple[Source, list[Doc], int, int]]:
    """This store's own channel and feed messages newer than claim `after`.
    Yields (source, documents, without words, highest claim id read)."""
    rows = conn.execute(
        "SELECT c.claim_id, s.key, s.name, s.kind::text AS kind, c.external_id, c.raw_text, c.lang,"
        "       c.reported_at, c.attrs"
        "  FROM claim c JOIN source s USING (source_id)"
        " WHERE s.kind IN ('telegram', 'rss') AND s.key <> ALL(%s) AND c.claim_id > %s"
        " ORDER BY c.claim_id", (list(ROBOTS), after)).fetchall()
    by: dict[str, tuple[Source, list[Doc]]] = {}
    empty, top = 0, after
    for claim_id, skey, sname, kind, ext, text, lang, reported, attrs in rows:
        top = max(top, claim_id)
        text = (text or "").strip()
        if not text or not ext:
            empty += 1
            continue
        attrs = attrs or {}
        if kind == "telegram":
            ch = attrs.get("channel") or skey[3:]
            key = f"tg:{ch.lower()}"
            src = Source(key, sname, "channel", f"https://t.me/{ch}", source_key=skey)
            doc = Doc(source=key, external_id=str(ext), kind="post", body=text, url=f"https://t.me/{ch}/{ext}",
                      lang=lang or guess_lang(text), published_at=reported.isoformat() if reported else None,
                      via="v2_claim", via_rank=2,
                      attrs={k: attrs[k] for k in ("views", "fwd_from", "reply_to") if attrs.get(k)} | {"claim_id": claim_id})
        else:
            key, name, home = V2_FEED.get(skey, (f"web:{skey}", sname, None))
            src = Source(key, name, "outlet", home, source_key=skey)
            doc = Doc(source=key, external_id=clean_url(ext) or str(ext), kind="article", body=text,
                      url=tidy_url(ext) if str(ext).startswith("http") else None,
                      lang=lang or guess_lang(text), published_at=reported.isoformat() if reported else None,
                      via="v2_claim", via_rank=1, attrs={"claim_id": claim_id})
        by.setdefault(key, (src, []))[1].append(doc)
    for i, (src, docs) in enumerate(by.values()):
        yield src, docs, empty if i == 0 else 0, top
    if not by:
        yield Source("-", "-", "channel"), [], empty, top


# ── compare, then write ─────────────────────────────────────────────────────
def decide(held: dict[str, tuple[str, int]], docs: Iterable[Doc]) -> dict[str, list[Doc]]:
    """Sort a publisher's texts against what is held for that publisher.
    `held` maps the publisher's id to (content hash, via_rank)."""
    out: dict[str, list[Doc]] = {"new": [], "changed": [], "same": [], "kept_fuller": []}
    seen: dict[str, Doc] = {}
    for d in docs:                                   # the same id twice in one batch: the last stands
        seen[d.external_id] = d
    for d in seen.values():
        h = held.get(d.external_id)
        if h is None:
            out["new"].append(d)
        elif h[0] == d.content_hash():
            out["same"].append(d)
        elif d.via_rank >= h[1]:
            out["changed"].append(d)
        else:
            out["kept_fuller"].append(d)
    return out


INSERT = """
INSERT INTO document (source, external_id, kind, url, title, body, extra, lang, published_at,
                      published_precision, via, via_rank, content_hash, attrs, terms, terms_version)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
        %s::tsvector || setweight(to_tsvector('english', %s), 'A') || to_tsvector('english', %s), %s)
ON CONFLICT (source, external_id) DO NOTHING"""

UPDATE = """
UPDATE document SET kind = %s, url = %s, title = %s, body = %s, extra = %s, lang = %s, published_at = %s,
       published_precision = %s, via = %s, via_rank = %s, content_hash = %s, attrs = %s::jsonb,
       terms = %s::tsvector || setweight(to_tsvector('english', %s), 'A') || to_tsvector('english', %s),
       terms_version = %s
 WHERE source = %s AND external_id = %s"""


def _terms(d: Doc) -> tuple[str, str, str]:
    return (T.vector(d.title, d.body, d.extra), T.latin(d.title),
            T.latin((d.body or "") + "\n" + (d.extra or "")))


def _insert_row(d: Doc) -> tuple:
    v, la, lb = _terms(d)
    return (d.source, d.external_id, d.kind, d.url, d.title, d.body, d.extra, d.lang, d.published_at,
            d.precision, d.via, d.via_rank, d.content_hash(), json.dumps(d.attrs, ensure_ascii=False),
            v, la, lb, T.VERSION)


def _update_row(d: Doc) -> tuple:
    v, la, lb = _terms(d)
    return (d.kind, d.url, d.title, d.body, d.extra, d.lang, d.published_at, d.precision, d.via, d.via_rank,
            d.content_hash(), json.dumps(d.attrs, ensure_ascii=False), v, la, lb, T.VERSION,
            d.source, d.external_id)


def held_for(conn, source: str, ids: list[str], table: bool) -> dict[str, tuple[str, int]]:
    """What is held for these ids of one publisher: {id: (content hash, via_rank)}."""
    if not table or not ids:
        return {}
    return {e: (h, r) for e, h, r in conn.execute(
        "SELECT external_id, content_hash, via_rank FROM document"
        " WHERE source = %s AND external_id = ANY(%s)", (source, ids))}


def write(conn, src: Source, sorted_docs: dict[str, list[Doc]]) -> None:
    # A chronology's name, address and language come from its own site.json and may be
    # corrected there (Wikipedia's English source gained its timelines on 2026-10-14); every
    # other reader names a source from its texts, where spellings vary, so its first name stays.
    conn.execute("INSERT INTO archive_source (key, name, kind, home_url, lang, source_key)"
                 " VALUES (%s, %s, %s, %s, %s, (SELECT key FROM source WHERE key = %s))"
                 " ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, home_url = EXCLUDED.home_url,"
                 " lang = EXCLUDED.lang"
                 " WHERE archive_source.kind = 'chronology' AND EXCLUDED.kind = 'chronology'"
                 " AND (archive_source.name, archive_source.home_url, archive_source.lang)"
                 " IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.home_url, EXCLUDED.lang)",
                 (src.key, src.name, src.kind, src.home_url, src.lang, src.source_key))
    with conn.cursor() as cur:
        new = sorted_docs["new"]
        for i in range(0, len(new), BATCH):
            cur.executemany(INSERT, [_insert_row(d) for d in new[i:i + BATCH]])
        ch = sorted_docs["changed"]
        for i in range(0, len(ch), BATCH):
            cur.executemany(UPDATE, [_update_row(d) for d in ch[i:i + BATCH]])


def run(readers: list[str], apply: bool, only: set[str] | None = None) -> dict:
    report: dict = {"apply": apply, "terms_version": T.VERSION, "readers": {}, "totals": {}}
    with connect() as conn:
        table = conn.execute("SELECT to_regclass('public.document') IS NOT NULL").fetchone()[0]
        report["table_present"] = table
        if apply and not table:
            raise SystemExit("the document table is missing: apply migration 116 first")
        loaded: dict[str, dict[str, str]] = {}
        if table:
            for reader, item, mark in conn.execute("SELECT reader, item, mark FROM archive_load"):
                loaded.setdefault(reader, {})[item] = mark
        conn.rollback()

        def take(reader: str, src: Source, docs: list[Doc], empty: int) -> None:
            r = report["readers"].setdefault(reader, {"sources": {}, "no_text": 0})
            r["no_text"] += empty
            if not docs:
                return
            s = decide(held_for(conn, src.key, [d.external_id for d in docs], table), docs)
            c = r["sources"].setdefault(src.key, {"read": 0, "new": 0, "changed": 0, "same": 0, "kept_fuller": 0})
            c["read"] += len(docs)
            for k in ("new", "changed", "same", "kept_fuller"):
                c[k] += len(s[k])
            if apply:
                write(conn, src, s)

        def mark(reader: str, item: str, value: str, rows: int) -> None:
            if apply:
                conn.execute("INSERT INTO archive_load (reader, item, mark, rows) VALUES (%s, %s, %s, %s)"
                             " ON CONFLICT (reader, item) DO UPDATE SET mark = EXCLUDED.mark, rows = EXCLUDED.rows,"
                             " loaded_at = now()", (reader, item, value, rows))
                conn.commit()
            else:
                conn.rollback()

        if "tg_public" in readers:
            files = 0
            for src, label, value, docs, empty in read_tg_public(loaded=loaded.get("tg_public"), only=only):
                take("tg_public", src, docs, empty)
                mark("tg_public", label, value, len(docs))
                files += 1
            report["readers"].setdefault("tg_public", {"sources": {}, "no_text": 0})["files"] = files
        if "wp_json" in readers:
            files = 0
            for src, label, value, docs, empty in read_wp(loaded=loaded.get("wp_json"), only=only):
                take("wp_json", src, docs, empty)
                mark("wp_json", label, value, len(docs))
                files += 1
            report["readers"].setdefault("wp_json", {"sources": {}, "no_text": 0})["files"] = files
        if "reports" in readers:                 # publishers' reports, the listing reader's file shape
            for src, label, value, docs, empty in read_wp(root=REPORTS, loaded=loaded.get("reports"), only=only):
                take("reports", src, docs, empty)
                mark("reports", label, value, len(docs))
        if "chronology" in readers:
            for src, label, value, docs, empty in read_chronology(loaded=loaded.get("chronology"), only=only):
                take("chronology", src, docs, empty)
                mark("chronology", label, value, len(docs))
        if "v1_news" in readers:
            for src, docs, empty in read_v1_news():
                take("v1_news", src, docs, empty)
            mark("v1_news", "run", datetime.now(timezone.utc).isoformat(), 0)
        if "v1_alerts" in readers:
            for src, docs, empty in read_v1_alerts():
                take("v1_alerts", src, docs, empty)
            mark("v1_alerts", "run", datetime.now(timezone.utc).isoformat(), 0)
        if "v2_claim" in readers:
            after = int(loaded.get("v2_claim", {}).get("watermark") or 0)
            top = after
            for src, docs, empty, top in read_v2_claim(conn, after):
                take("v2_claim", src, docs, empty)
            mark("v2_claim", "watermark", str(top), 0)
            report["readers"].setdefault("v2_claim", {"sources": {}, "no_text": 0})["read_from_claim"] = after
            report["readers"]["v2_claim"]["read_to_claim"] = top
        if table:
            n, first, last = conn.execute("SELECT count(*), min(published_at), max(published_at) FROM document").fetchone()
            report["held_after"] = {"documents": n, "first": first and first.isoformat(), "last": last and last.isoformat()}
        conn.rollback()
    tot = {"read": 0, "new": 0, "changed": 0, "same": 0, "kept_fuller": 0, "no_text": 0}
    for r in report["readers"].values():
        tot["no_text"] += r.get("no_text", 0)
        for c in r["sources"].values():
            for k in ("read", "new", "changed", "same", "kept_fuller"):
                tot[k] += c[k]
    report["totals"] = tot
    return report


def reindex(apply: bool) -> dict:
    """Rewrite the search vector of every row written by an older rule."""
    done = 0
    with connect() as conn:
        todo = conn.execute("SELECT count(*) FROM document WHERE terms_version IS DISTINCT FROM %s",
                            (T.VERSION,)).fetchone()[0]
        while apply:
            rows = conn.execute("SELECT doc_id, title, body, extra FROM document"
                                " WHERE terms_version IS DISTINCT FROM %s LIMIT %s", (T.VERSION, BATCH)).fetchall()
            if not rows:
                break
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE document SET terms = %s::tsvector || setweight(to_tsvector('english', %s), 'A')"
                    " || to_tsvector('english', %s), terms_version = %s WHERE doc_id = %s",
                    [(T.vector(t, b, x), T.latin(t), T.latin((b or "") + "\n" + (x or "")), T.VERSION, i)
                     for i, t, b, x in rows])
            conn.commit()
            done += len(rows)
    return {"apply": apply, "terms_version": T.VERSION, "rows_of_an_older_rule": todo, "rewritten": done}


READERS = ("tg_public", "wp_json", "reports", "chronology", "v1_news", "v1_alerts", "v2_claim")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fill the archive from what the house holds. Dry unless --apply.")
    ap.add_argument("readers", nargs="*", choices=[*READERS, []], help="default: all of them")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--channels", help="tg_public and wp_json only: these folders (comma-separated)")
    a = ap.parse_args()
    if a.reindex:
        out = reindex(a.apply)
    else:
        only = {c.strip().lower() for c in a.channels.split(",")} if a.channels else None
        out = run(list(a.readers) or list(READERS), a.apply, only)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
