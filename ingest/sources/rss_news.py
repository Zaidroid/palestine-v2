"""RSS news agencies — observers that are not on Telegram at all.

    .venv/bin/python -m ingest.sources.rss_news
    .venv/bin/python -m ingest.sources.rss_news --dry-run

WHY THIS MATTERS MORE THAN THE YIELD SUGGESTS
These feeds classify at 12-20% against 20-42% for the Telegram channels, so on
volume alone they look like the weaker source. They are not, because of what
corroboration actually needs: nine of the road channels agree 99.5-100% of the
time and count as ONE observer, and the news channels are a second cluster on
the same platform, often reposting each other. A wire agency publishing to RSS
is a genuinely separate newsroom — when it agrees with a Telegram report, that
agreement carries information the way a copy never does.

The corroboration counts bear this out: before RSS, `independent_sources` on
incidents topped out at 3-4 and most events sat at 1.

NO ACCOUNT, NO KEY, NO RISK
Plain HTTP to a public feed. Nothing here touches a Telegram session, so it
cannot cost us the account — which is the scarcest thing in this system. It also
keeps working if a Telegram account is ever rate-limited, so the two paths fail
independently.

CLASSIFICATION IS NOT DUPLICATED
These write `claim` rows in exactly the shape the poller does, so the existing
news cascade picks them up with no changes. Title AND summary are stored: the
title carries the action, the summary usually carries the village, and the place
extractor needs both.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx

from analyst.lang import detect_quietly
from ingest import bronze
from resolve.db import connect

USER_AGENT = "palestine-v2/2.0 (humanitarian data; contact via repo)"

# Feeds verified reachable and Palestine-focused. `key` becomes the source key,
# so independence grouping and reliability apply to them like any other source.
FEEDS: list[dict] = [
    {"key": "rss_qudsn",   "name": "Quds News Network",
     "url": "https://qudsn.co/rss"},
    {"key": "rss_palinfo", "name": "Palestinian Information Center",
     "url": "https://palinfo.com/feed/"},
]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean(html: str | None) -> str:
    if not html:
        return ""
    return _WS.sub(" ", _TAG.sub(" ", html)).strip()


def _parsed_at(item: ET.Element) -> datetime:
    raw = item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            try:
                dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    # Never invent a precise time we do not have; ingestion time is the honest
    # fallback and the claim records which it was.
    return datetime.now(timezone.utc)


def _external_id(item: ET.Element, feed_key: str) -> str:
    for tag in ("guid", "link"):
        v = (item.findtext(tag) or "").strip()
        if v:
            return v[:250]
    title = (item.findtext("title") or "").strip()
    return f"{feed_key}:{hashlib.sha256(title.encode()).hexdigest()[:24]}"


def _ensure_source(cur, feed: dict) -> int:
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                            attribution_text,authority_rank)
        VALUES (%s,%s,'rss','NONE',false,%s,3)
        ON CONFLICT (key) DO NOTHING""",
        (feed["key"], feed["name"], f"{feed['name']} (RSS)"))
    cur.execute("SELECT source_id FROM source WHERE key=%s", (feed["key"],))
    return cur.fetchone()[0]


def fetch(feed: dict) -> list[ET.Element]:
    r = httpx.get(feed["url"], timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return ET.fromstring(r.content).findall(".//item")


def ingest(dry_run: bool = False) -> dict:
    stats: dict = {"feeds": 0, "items": 0, "new": 0, "dupe": 0, "errors": []}
    with connect() as conn, conn.cursor() as cur:
        for feed in FEEDS:
            try:
                items = fetch(feed)
            except Exception as exc:                       # noqa: BLE001
                # One bad feed must not stop the others — the same rule the
                # Telegram poller follows for a dead channel.
                stats["errors"].append(f"{feed['key']}: {type(exc).__name__}: {exc}")
                continue
            stats["feeds"] += 1
            stats["items"] += len(items)
            source_id = _ensure_source(cur, feed)

            for item in items:
                ext = _external_id(item, feed["key"])
                cur.execute("""SELECT claim_id FROM claim_dedup
                               WHERE source_id=%s AND external_id=%s""",
                            (source_id, ext))
                if cur.fetchone():
                    stats["dupe"] += 1
                    continue

                title = _clean(item.findtext("title"))
                summary = _clean(item.findtext("description"))
                # Title AND summary: the action is in the headline, the village
                # is usually only in the body, and the place extractor needs both.
                text = f"{title}. {summary}".strip(". ").strip()
                if len(text) < 25:
                    continue
                reported = _parsed_at(item)

                if dry_run:
                    stats["new"] += 1
                    continue

                payload = json.dumps({"feed": feed["key"], "title": title,
                                      "summary": summary, "link": item.findtext("link"),
                                      "published": item.findtext("pubDate")},
                                     ensure_ascii=False)
                ref = bronze.put(feed["key"], payload, "json")
                # These feeds are the ones the hard-coded 'ar' was most wrong
                # about: a wire agency publishes what it publishes, and the
                # claim now carries the measured language plus what measured it.
                # No detector -> NULL, and the analyst's organ A fills it in.
                code, detector = detect_quietly(text)
                attrs = {"feed": feed["key"], "title": title,
                         "link": item.findtext("link")}
                if detector:
                    attrs["lang_detector"] = detector
                cur.execute("""
                    INSERT INTO claim (source_id,external_id,raw_ref,raw_text,lang,
                                       claim_type,reported_at,attrs)
                    VALUES (%s,%s,%s,%s,%s,'unclassified',%s,%s)
                    RETURNING claim_id, ingested_at""",
                    (source_id, ext, ref.ref, text[:4000], code, reported,
                     json.dumps(attrs, ensure_ascii=False)))
                claim_id, ingested_at = cur.fetchone()
                cur.execute("""INSERT INTO claim_dedup (source_id,external_id,claim_id,ingested_at)
                               VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                            (source_id, ext, claim_id, ingested_at))
                stats["new"] += 1
        if not dry_run:
            conn.commit()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = ingest(a.dry_run)
    print(f"{s['feeds']}/{len(FEEDS)} feeds · {s['items']} items · "
          f"{s['new']} new · {s['dupe']} already seen")
    for e in s["errors"]:
        print(f"  FEED FAILED {e}")
    if a.dry_run:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
