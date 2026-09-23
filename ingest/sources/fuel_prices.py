"""Fuel prices — the official monthly maximum, read from the outlets that repost it.

    .venv/bin/python -m ingest.sources.fuel_prices                 # feeds + archive
    .venv/bin/python -m ingest.sources.fuel_prices --dry-run
    .venv/bin/python -m ingest.sources.fuel_prices --url URL [--published YYYY-MM-DD]

Replaces fuel availability (retired 2026-09-23, migration 070). The number is
the Petroleum Corporation's maximum consumer price for the West Bank; there is
no feed, so it is read out of the news (cascade/fuel_price.py) from two
independent paths:

  WEB   public RSS feeds of Palestinian outlets. An item whose title or summary
        is about fuel prices has its article fetched once, archived to bronze
        and read. Refusals are recorded like readings, so a page is not fetched
        again every fifteen minutes — except a page that said nothing yet is
        retried every two hours for two days, because outlets publish the
        headline first and fill the list in after (raya.ps, 2026-08-31).
  CLAIMS the Telegram channels the poller already archives. Pure database
        read — nothing here touches the Telegram session.

Nothing is believed here. Every transcription lands in fuel_price_report; the
belief rule (two independent outlets, one naming the authority) is SQL
(migration 071), so the API, the watchdog and the gates all read the same
definition.

NO ACCOUNT, NO KEY. Plain HTTP to public pages, one fetch per new article,
a hard cap per run.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from cascade import fuel_price  # noqa: E402
from ingest import bronze  # noqa: E402
from resolve.db import connect  # noqa: E402

USER_AGENT = "palestine-v2/2.0 (humanitarian data; contact via repo)"
BRONZE_KEY = "fuel_prices_web"

# Verified reachable 2026-09-23 (HTTP 200, items present). qudsn and palinfo
# are read by rss_news already; they are read here too because this reader
# needs the article, not the summary.
FEEDS: list[str] = [
    "https://www.raya.ps/rss",
    "https://www.alquds.com/rss",
    "https://www.sadanews.ps/rss",
    "https://www.maannews.net/rss",
    "https://arn.ps/rss",
    "https://safa.ps/rss",
    "https://shehabnews.com/rss",
    "https://msdrnews.com/feed",
    "https://qudsn.co/rss",
    "https://palinfo.com/feed/",
]

# Title/summary filter: cheap, deliberately loose. The reader is the judge.
TOPIC = re.compile(r"المحروقات|أسعار الوقود|اسعار الوقود|البنزين|السولار|أسعار الغاز|اسعار الغاز")
CLAIM_TOPIC = r"(بنزين|سولار|السولار|الكاز|المحروقات)"
MAX_ARTICLES_PER_RUN = 25
RETRY_EMPTY_EVERY = timedelta(hours=2)
RETRY_EMPTY_FOR = timedelta(days=2)
CLAIM_LOOKBACK = timedelta(days=3)


# ── article text ─────────────────────────────────────────────────────────────

_DROP = re.compile(r"<(script|style|noscript|nav|footer|aside|form)\b.*?</\1>", re.S | re.I)
_BLOCK = re.compile(r"<(p|li|h1|h2|h3)\b[^>]*>(.*?)</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_META_PUB = re.compile(
    r'(?:property|name|itemprop)="(?:article:published_time|datePublished|pubdate)"'
    r'[^>]*content="([^"]+)"|"datePublished"\s*:\s*"([^"]+)"', re.I)


def article_text(page: str) -> str:
    """Title + paragraph and list text. Sidebars and scripts are dropped first;
    a related-article list is a <li> of TITLES, which carry no prices, and a
    stray price-less sentence is harmless to the reader."""
    page = _DROP.sub(" ", page)
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    parts = [htmllib.unescape(_TAG.sub(" ", title.group(1))).strip()] if title else []
    for _, inner in _BLOCK.findall(page):
        t = re.sub(r"\s+", " ", htmllib.unescape(_TAG.sub(" ", inner))).strip()
        if t:
            parts.append(t)
    return "\n".join(parts)


def published_from_page(page: str) -> datetime | None:
    m = _META_PUB.search(page)
    raw = (m.group(1) or m.group(2)) if m else None
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone(timedelta(hours=3)))


# ── one transcription ────────────────────────────────────────────────────────

def _row(ann: fuel_price.Announcement, *, outlet: str, unit: str, text: str,
         url: str | None, published: datetime | None, source_id: int | None = None,
         claim_id: int | None = None, bronze_ref: str | None = None) -> dict:
    implied = any("attribution implied" in d for d in ann.detail)
    return {
        "outlet": outlet, "independence_unit": unit, "source_id": source_id,
        "claim_id": claim_id, "url": url, "published_at": published,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "bronze_ref": bronze_ref, "reader_version": ann.version,
        "verdict": ann.verdict,
        "attribution": (None if ann.verdict != "prices" else ("implied" if implied else "named")),
        "effective_from": ann.effective_from, "effective_basis": ann.effective_basis,
        "period_month": ann.period_month,
        "prices": json.dumps(ann.prices), "detail": json.dumps(ann.detail, ensure_ascii=False),
        "evidence": json.dumps(ann.evidence, ensure_ascii=False),
    }


_INSERT = """
    INSERT INTO fuel_price_report
        (outlet, independence_unit, source_id, claim_id, url, published_at,
         content_sha256, bronze_ref, reader_version, verdict, attribution,
         effective_from, effective_basis, period_month, prices, detail, evidence)
    VALUES (%(outlet)s, %(independence_unit)s, %(source_id)s, %(claim_id)s, %(url)s,
            %(published_at)s, %(content_sha256)s, %(bronze_ref)s, %(reader_version)s,
            %(verdict)s, %(attribution)s, %(effective_from)s, %(effective_basis)s,
            %(period_month)s, %(prices)s::jsonb, %(detail)s::jsonb, %(evidence)s::jsonb)
    ON CONFLICT (outlet, content_sha256, reader_version) DO NOTHING
    RETURNING report_id"""


def read_article(client: httpx.Client, url: str, published: datetime | None) -> dict:
    r = client.get(url)
    r.raise_for_status()
    page = r.text
    ref = bronze.put(BRONZE_KEY, page, "html", url=url)
    published = published or published_from_page(page)
    text = article_text(page)
    local_day = published.astimezone(timezone(timedelta(hours=3))).date() if published else None
    ann = fuel_price.parse(text, local_day)
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    return _row(ann, outlet=domain, unit=f"web:{domain}", text=text, url=url,
                published=published, bronze_ref=ref.ref)


# ── the two paths ────────────────────────────────────────────────────────────

def _pubdate(item: ET.Element) -> datetime | None:
    raw = item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00").replace(" ", "T"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone(timedelta(hours=3)))


def candidate_items(client: httpx.Client, stats: dict) -> list[tuple[str, datetime | None]]:
    out = []
    for feed in FEEDS:
        try:
            r = client.get(feed)
            r.raise_for_status()
            items = ET.fromstring(r.content).findall(".//item")
        except Exception as e:                              # noqa: BLE001
            stats["feeds_failed"].append(f"{urlparse(feed).netloc}: {type(e).__name__}")
            continue
        stats["feeds_ok"] += 1
        for it in items:
            link = (it.findtext("link") or "").strip()
            blob = (it.findtext("title") or "") + " " + (it.findtext("description") or "")
            if link and TOPIC.search(blob):
                out.append((link, _pubdate(it)))
    return out


def _due(cur, url: str, now: datetime) -> bool:
    """Fetch a page once per reader version. A page that yielded no list yet is
    retried every two hours for two days (headline first, list after)."""
    cur.execute("""SELECT min(fetched_at), max(fetched_at), bool_or(verdict = 'prices')
                     FROM fuel_price_report WHERE url = %s AND reader_version = %s""",
                (url, fuel_price.VERSION))
    first, last, got = cur.fetchone()
    if first is None:
        return True
    if got:
        return False
    return now - first < RETRY_EMPTY_FOR and now - last >= RETRY_EMPTY_EVERY


def claim_rows(cur) -> list[dict]:
    cur.execute(f"""
        SELECT c.claim_id, c.raw_text, c.reported_at, s.source_id, s.key,
               COALESCE(s.independence_group, 'src:' || s.source_id::text)
          FROM claim c JOIN source s USING (source_id)
         WHERE c.reported_at > now() - %s
           AND c.raw_text ~ '(شيكل|شيقل)' AND c.raw_text ~ '{CLAIM_TOPIC}'""",
                (CLAIM_LOOKBACK,))
    rows = []
    for claim_id, text, reported, source_id, key, unit in cur.fetchall():
        day = reported.astimezone(timezone(timedelta(hours=3))).date()
        ann = fuel_price.parse(text, day)
        rows.append(_row(ann, outlet=key, unit=unit, text=text, url=None,
                         published=reported, source_id=source_id, claim_id=claim_id))
    return rows


def run(dry_run: bool = False, urls: list[str] | None = None,
        published: date | None = None, claim_lookback: timedelta | None = None) -> dict:
    global CLAIM_LOOKBACK
    if claim_lookback:
        CLAIM_LOOKBACK = claim_lookback
    stats: dict = {"feeds_ok": 0, "feeds_failed": [], "articles": 0, "article_errors": [],
                   "claims_read": 0, "inserted": 0, "verdicts": {}}
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ar,en;q=0.5"}
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client, \
         connect() as conn, conn.cursor() as cur:
        if urls:
            pub = (datetime.combine(published, datetime.min.time(), timezone(timedelta(hours=3)))
                   if published else None)
            todo = [(u, pub) for u in urls]
        else:
            todo = candidate_items(client, stats)
            rows.extend(claim_rows(cur))
            stats["claims_read"] = len(rows)
        seen = set()
        for url, pub in todo:
            if url in seen or stats["articles"] >= MAX_ARTICLES_PER_RUN:
                continue
            seen.add(url)
            if not urls and not _due(cur, url, now):
                continue
            try:
                rows.append(read_article(client, url, pub))
                stats["articles"] += 1
            except Exception as e:                          # noqa: BLE001
                stats["article_errors"].append(f"{urlparse(url).netloc}: {type(e).__name__}")
        for row in rows:
            stats["verdicts"][row["verdict"]] = stats["verdicts"].get(row["verdict"], 0) + 1
            if dry_run:
                continue
            cur.execute(_INSERT, row)
            if cur.fetchone():
                stats["inserted"] += 1
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--url", action="append", help="read one article (repeatable)")
    ap.add_argument("--published", type=date.fromisoformat,
                    help="publication date for --url pages that carry none")
    ap.add_argument("--claims-days", type=int, help="widen the Telegram lookback once")
    a = ap.parse_args()
    stats = run(a.dry_run, a.url, a.published,
                timedelta(days=a.claims_days) if a.claims_days else None)
    print(json.dumps(stats, ensure_ascii=False, default=str))
    # A dead outlet is normal; every feed dead at once is not.
    if not a.url and stats["feeds_ok"] == 0:
        print("every fuel-price feed failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
