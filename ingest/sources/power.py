"""Scheduled electricity cuts, scraped from the distribution companies.

    .venv/bin/python -m ingest.sources.power --dry-run
    .venv/bin/python -m ingest.sources.power

THE SIGNAL WAS THERE ALL ALONG, BEHIND AN ENCODING BUG
This was nearly written off. NEDCO's pages are served as windows-1256 — legacy
Arabic — and read as UTF-8 they are pure mojibake, which looked like a site with
no usable content. Decoded correctly the headlines are exactly what was wanted:

    فصل تيار كهربائي في مدينة نابلس
    فصل تيار كهربائي في سالم

The action and the place are both in the title, and the body carries the areas
and the window ("من الساعة 8:30 صباحا حتى الساعة 1:00 من ظهر يوم الثلاثاء
الموافق 28/7/2026"). No OCR needed.

HEPCO (Hebron) publishes the same kind of notice as an uploaded JPG with no text
on the page, so it would need Arabic OCR on a scanned layout for a worse result.
It is deliberately not scraped.

THESE ARE SCHEDULED CUTS, NOT LIVE OUTAGES
Maintenance announced in advance, which is a different fact from "the power is
off now" — and conflating them would be the same error as serving a stale
checkpoint as current. So the ANNOUNCEMENT is recorded whenever it is found,
and `power = 'cut'` is asserted only while the clock is actually inside the
announced window. Outside it, the window is still returned so a caller can say
"a cut is scheduled for Tuesday morning".

Unannounced outages are a different problem and this cannot see them — nobody
publishes those. The nearest available proxy is connectivity (see
ingest/sources/connectivity.py), which infers reachability from outside.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx

from resolve.db import connect
from resolve.geo import resolve_place

BASE = "https://www.nedco.ps"
SOURCE_KEY = "nedco"
STATE_KIND = "power"
LOCAL_TZ = ZoneInfo("Asia/Hebron")
USER_AGENT = "Mozilla/5.0 (compatible; palestine-v2/2.0; humanitarian data)"
# The site is legacy-encoded and does not declare it in a way httpx honours.
ENCODING = "windows-1256"

CUT_TITLE = re.compile(r"(فصل\s+تيار|فصل\s+التيار|قطع\s+التيار|انقطاع\s+التيار)")
# "فصل تيار كهربائي في مدينة نابلس" -> "مدينة نابلس"
PLACE_IN_TITLE = re.compile(r"(?:في|عن)\s+(.{2,40})$")
DATE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})")
# "الساعة 8:30 صباحا" / "الساعة 1:00 من ظهر"
TIME = re.compile(r"الساعة\s*(\d{1,2})[:٫،.](\d{2})\s*(صباح\w*|مساء\w*|ظهر\w*|عصر\w*|ليل\w*)?")

_TAGS = re.compile(r"<script.*?</script>|<style.*?</style>", re.S)


def _text(html: str) -> str:
    t = _TAGS.sub("", html)
    t = re.sub(r"<br\s*/?>|</p>|</div>|</td>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", t)


def _get(url: str) -> str:
    r = httpx.get(url, timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.content.decode(ENCODING, errors="replace")


def _to_24h(hour: int, minute: int, marker: str | None) -> int:
    """Arabic day-part markers to a 24h hour.

    Note ظهر ("noon") with 1:00 means 13:00, not 01:00 — the notices write
    "الساعة 1:00 من ظهر" for early afternoon, so treating the marker as merely
    decorative would put a cut twelve hours off.
    """
    m = marker or ""
    if hour == 12:
        hour = 0
    if any(k in m for k in ("مساء", "ظهر", "عصر", "ليل")):
        return hour + 12 if hour < 12 else hour
    return hour


def parse_window(body: str) -> tuple[datetime, datetime] | None:
    """(start, end) in UTC for the announced cut, when both are stated."""
    d = DATE.search(body)
    times = TIME.findall(body)
    if not d or len(times) < 2:
        return None
    day, month, year = (int(x) for x in d.groups())
    try:
        (h1, m1, k1), (h2, m2, k2) = times[0], times[1]
        start = datetime(year, month, day, _to_24h(int(h1), int(m1), k1), int(m1),
                         tzinfo=LOCAL_TZ)
        end = datetime(year, month, day, _to_24h(int(h2), int(m2), k2), int(m2),
                       tzinfo=LOCAL_TZ)
    except ValueError:
        return None
    if end <= start:
        end += timedelta(hours=12)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _ensure_source(cur) -> int:
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                            attribution_text,authority_rank)
        VALUES (%s,'North Electricity Distribution Company (NEDCO)','api','NONE',false,
                'شركة توزيع كهرباء الشمال (NEDCO)',2)
        ON CONFLICT (key) DO NOTHING""", (SOURCE_KEY,))
    cur.execute("SELECT source_id FROM source WHERE key=%s", (SOURCE_KEY,))
    return cur.fetchone()[0]


def discover_notices() -> list[tuple[str, str]]:
    """[(newsid, title)] for headlines that announce a cut."""
    html = _get(BASE + "/")
    seen: dict[str, str] = {}
    for nid, title in re.findall(r'newsid=(\d+)[^>]*>([^<]{6,120})', html):
        title = re.sub(r"\s+", " ", title).strip()
        if title and nid not in seen and CUT_TITLE.search(title):
            seen[nid] = title
    return list(seen.items())


def load(dry_run: bool = False) -> dict:
    stats = {"notices": 0, "parsed_window": 0, "resolved": 0, "fetch_failed": 0,
             "announced": 0, "active_now": 0, "written": 0, "items": []}
    notices = discover_notices()
    stats["notices"] = len(notices)
    if not notices:
        return stats

    now = datetime.now(timezone.utc)
    with connect() as conn, conn.cursor() as cur:
        source_id = _ensure_source(cur)
        for nid, title in notices:
            try:
                body = _text(_get(f"{BASE}/?newsid={nid}"))
            except Exception:                              # noqa: BLE001
                # COUNTED, not swallowed. `power` sat at zero observations for
                # a week while this loop ran every 15 minutes, and a bare
                # continue meant the difference between "no cuts announced"
                # and "the site refused every body fetch" was invisible.
                stats["fetch_failed"] += 1
                continue
            window = parse_window(body)
            if window:
                stats["parsed_window"] += 1

            m = PLACE_IN_TITLE.search(title)
            place_text = m.group(1).strip() if m else None
            res = resolve_place(place_text, conn=conn, learn=False) if place_text else None
            if not res:
                continue
            stats["resolved"] += 1

            active = bool(window and window[0] <= now <= window[1])
            stats["items"].append({
                "newsid": nid, "title": title, "place": place_text,
                "resolved_to": res.name_ar or res.name_en,
                "window": [w.isoformat() for w in window] if window else None,
                "active_now": active,
            })

            # THE ANNOUNCEMENT ITSELF IS RECORDED, once per notice — the
            # docstring above always promised this and the code kept only the
            # other half. modality='scheduled' (040) keeps it out of belief
            # exactly like a question, while making the discovery observable
            # and "a cut is scheduled for Tuesday morning" servable.
            if window and not dry_run:
                cur.execute("""
                    INSERT INTO state_observation
                      (place_id,state_kind,value,raw_value,observed_at,source_id,
                       confidence,direction,direction_explicit,modality,attrs)
                    SELECT %s,%s,'cut',%s,%s,%s,0.9,'both',false,'scheduled',%s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM state_observation
                        WHERE state_kind = %s AND modality = 'scheduled'
                          AND attrs->>'newsid' = %s)""",
                    (res.place_id, STATE_KIND, title[:200], now, source_id,
                     json.dumps({"newsid": nid, "title": title,
                                 "window_start": window[0].isoformat(),
                                 "window_end": window[1].isoformat(),
                                 "scheduled": True,
                                 "url": f"{BASE}/?newsid={nid}"},
                                ensure_ascii=False),
                     STATE_KIND, nid))
                stats["announced"] += cur.rowcount

            if not active:
                continue
            stats["active_now"] += 1
            if dry_run:
                continue

            cur.execute("""
                INSERT INTO state_observation
                  (place_id,state_kind,value,raw_value,observed_at,source_id,confidence,
                   direction,direction_explicit,modality,attrs)
                VALUES (%s,%s,'cut',%s,%s,%s,0.9,'both',false,'assertion',%s)""",
                (res.place_id, STATE_KIND, title[:200], now, source_id,
                 json.dumps({"newsid": nid, "title": title,
                             "window_start": window[0].isoformat(),
                             "window_end": window[1].isoformat(),
                             "scheduled": True,
                             "url": f"{BASE}/?newsid={nid}"}, ensure_ascii=False)))
            stats["written"] += 1

        if stats["written"] and not dry_run:
            # Scoped to power only, for the reason the fuel loader taught us.
            cur.execute("""
                INSERT INTO state_current
                  (place_id,state_kind,direction,value,observed_at,source_id,
                   base_confidence,independent_sources,contradicted_by,updated_at)
                SELECT DISTINCT ON (place_id, state_kind)
                       place_id, state_kind, 'both', value, observed_at, source_id,
                       confidence, 1, 0, now()
                FROM state_observation WHERE state_kind = %s
                ORDER BY place_id, state_kind, observed_at DESC
                ON CONFLICT (place_id, state_kind, direction) DO UPDATE SET
                  value=EXCLUDED.value, observed_at=EXCLUDED.observed_at,
                  source_id=EXCLUDED.source_id, base_confidence=EXCLUDED.base_confidence,
                  updated_at=now()
                WHERE EXCLUDED.observed_at >= state_current.observed_at""", (STATE_KIND,))
        if not dry_run:
            conn.commit()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = load(a.dry_run)
    print(f"{s['notices']} cut notices · {s['parsed_window']} with a parsed window · "
          f"{s['resolved']} located · {s['active_now']} active right now")
    for it in s["items"][:10]:
        w = it["window"]
        when = f"{w[0][:16]} -> {w[1][11:16]}" if w else "window not parsed"
        mark = "  ACTIVE" if it["active_now"] else ""
        print(f"   {it['title'][:44]:<46} {str(it['resolved_to'])[:14]:<16}{when}{mark}")
    if a.dry_run:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
