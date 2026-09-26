"""Press coverage of an incident, linked deterministically (P2-C.2, organ F's
first half).

Tier 1's incidents are read from Telegram channels; v1's news archive
(news.db, 16k articles from Al Jazeera, Quds News, WAFA-adjacent and English
outlets) was never joined to them. An article is linked to an event when, in
the half day around the event, its title or summary names the event's place
(whole word, the gazetteer's own Arabic or English name) AND carries a word of
the event's type. Linked, never merged: the event's count, corroboration and
verdict do not change — a newspaper repeating a channel is not a second
witness — the article is a published SOURCE a reader can follow.

    .venv/bin/python -m ops.press_links --dry-run --days 7   # show matches
    .venv/bin/python -m ops.press_links --days 2             # write attrs.press

Writes only `event.attrs.press` (at most PER_EVENT links, merged by url), and
only on events whose links changed; the versioning trigger keeps the prior row.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.arabic import normalize                                        # noqa: E402
from resolve.db import connect, env_value                                   # noqa: E402
from resolve.db import v1_path  # noqa: E402

NEWS_DB = Path(env_value("V1_NEWS_DB") or
               str(v1_path("services/westbank-alerts/data/news.db")))
BEFORE, AFTER = timedelta(hours=2), timedelta(hours=12)   # an article follows the event
PER_EVENT = 5

TYPE_WORDS = {
    "raid":           (r"اقتحام|تقتحم|اقتحمت|يقتحم|مداهم|اجتياح", r"raid|storm|incursion|invad"),
    "settler_attack": (r"مستوطن", r"settler"),
    "closure":        (r"إغلاق|اغلاق|تغلق|أغلق|اغلق|حاجز", r"clos|checkpoint|blockade"),
    "arrest":         (r"اعتقال|تعتقل|اعتقلت|يعتقل|معتقل", r"arrest|detain|abduct"),
    "shooting":       (r"إطلاق نار|اطلاق نار|الرصاص|رصاص", r"shot|shooting|gunfire|live fire"),
    "injury":         (r"إصاب|اصاب|جريح|جرحى", r"injur|wound"),
    "death":          (r"استشهاد|شهيد|استشهد|شهداء", r"killed|dead|martyr|died"),
    "demolition":     (r"هدم|تهدم|يهدم", r"demoli"),
    "siege":          (r"حصار|تحاصر|يحاصر", r"siege|besieg|encircl"),
    "land_levelling": (r"تجريف|يجرف|تجرف", r"bulldoz|raz"),
}


def _word(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])")


def articles(days: int) -> list[dict]:
    if not NEWS_DB.exists():
        return []
    con = sqlite3.connect(f"file:{NEWS_DB}?mode=ro", uri=True)
    since = (datetime.now(timezone.utc) - timedelta(days=days + 1)).isoformat()
    rows = con.execute("""SELECT source_name, language, title, description, link, published_at
                            FROM articles WHERE published_at >= ? AND COALESCE(palestine_relevant, 1) = 1""",
                       (since,)).fetchall()
    out = []
    for src, lang, title, desc, link, pub in rows:
        try:
            at = datetime.fromisoformat((pub or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        text = f"{title or ''} {desc or ''}"
        out.append({"source": src, "lang": lang, "title": (title or "")[:200], "url": link,
                    "at": at, "text": normalize(text) if lang == "ar" else text.lower()})
    return out


def match(events: list[dict], arts: list[dict], stop: set[str] | None = None) -> dict[int, list[dict]]:
    """event_id -> linked articles. Pure: tested without a database.

    `stop`: names too general to link on — a governorate's city (رام الله,
    Nablus, Jenin…) appears in every West Bank roundup, and the first dry run
    tied "Israel detains 150 Palestinians" to unrelated events there. Only a
    specific village, camp or town links an article to an event."""
    stop = {normalize(x) for x in (stop or set())} | {x.lower() for x in (stop or set())}
    out: dict[int, list[dict]] = {}
    for e in events:
        if (e.get("name_ar") and normalize(e["name_ar"]) in stop) or \
           (e.get("name_en") and e["name_en"].lower() in stop):
            continue
        ar_pat = _word(normalize(e["name_ar"])) if e.get("name_ar") and len(e["name_ar"]) >= 3 else None
        en_pat = _word(e["name_en"].lower()) if e.get("name_en") and len(e["name_en"]) >= 4 else None
        words = TYPE_WORDS.get(e["type"])
        if not words:
            continue
        ar_type, en_type = re.compile(words[0]), re.compile(words[1])
        for a in arts:
            if not (e["at"] - BEFORE <= a["at"] <= e["at"] + AFTER):
                continue
            if a["lang"] == "ar":
                ok = ar_pat and ar_pat.search(a["text"]) and ar_type.search(a["text"])
            else:
                ok = en_pat and en_pat.search(a["text"]) and en_type.search(a["text"])
            if ok:
                out.setdefault(e["event_id"], []).append(
                    {"source": a["source"], "title": a["title"], "url": a["url"],
                     "published": a["at"].isoformat(timespec="minutes")})
    return {k: sorted(v, key=lambda x: x["published"])[:PER_EVENT] for k, v in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", type=int, default=15)
    a = ap.parse_args()
    arts = articles(a.days)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT e.event_id, e.event_type, e.occurred_at, p.name_ar, p.name_en,
                              e.attrs->'press'
                         FROM event e JOIN place p ON p.place_id = e.place_id
                        WHERE e.status = 'believed' AND e.attrs->>'place_precision' = 'named'
                          AND e.occurred_at > now() - make_interval(days => %s)
                          AND e.event_type <> 'fire_detection'""", (a.days,))
        events = [{"event_id": r[0], "type": r[1], "at": r[2], "name_ar": r[3], "name_en": r[4],
                   "press": r[5] or []} for r in cur.fetchall()]
        cur.execute("""SELECT name_ar, name_en FROM place WHERE kind = 'governorate'
                       UNION SELECT name_ar, name_en FROM place WHERE kind = 'region'""")
        stop = {x for r in cur.fetchall() for x in r if x}
        stop |= {"رام الله", "البيرة", "القدس", "Ramallah", "Jerusalem", "West Bank", "Gaza"}
        links = match(events, arts, stop)
        changed = 0
        for e in events:
            new = links.get(e["event_id"])
            if not new:
                continue
            merged = {x["url"]: x for x in (e["press"] or []) + new if x.get("url")}
            merged_list = sorted(merged.values(), key=lambda x: x["published"])[:PER_EVENT]
            if merged_list != (e["press"] or []):
                changed += 1
                if not a.dry_run:
                    cur.execute("UPDATE event SET attrs = attrs || jsonb_build_object('press', %s::jsonb) "
                                "WHERE event_id = %s", (json.dumps(merged_list, ensure_ascii=False), e["event_id"]))
        if not a.dry_run:
            conn.commit()
    print(f"{len(arts):,} articles, {len(events):,} named events over {a.days} d: "
          f"{len(links):,} events linked, {changed:,} changed" + (" (dry run)" if a.dry_run else ""))
    for eid, ls in list(links.items())[:a.show]:
        e = next(x for x in events if x["event_id"] == eid)
        print(f"  {eid} {e['type']:<15} {e['name_ar'] or e['name_en']:<14} {e['at']:%m-%d %H:%M} <- "
              + " | ".join(f"{x['source']}: {x['title'][:70]}" for x in ls[:2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
