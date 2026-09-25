"""Channel discovery for the v2 account — search, rank, REVIEW. Never joins.

    ./.venv/bin/python -m ingest.discover_channels --category fuel
    ./.venv/bin/python -m ingest.discover_channels --all

Uses `contacts.SearchRequest` (the same mechanism v1 used to find the King
Hussein Bridge channels) to surface public channels per category, ranks them,
and writes a review list to ops/channel-candidates.md.

WHY DISCOVERY, NOT A GUESSED LIST
Guessing handles produces failed resolves — v1 carries a dead `Almasshta` entry
that errors on every startup. Search returns handles that actually exist, with
subscriber counts and last-post times, so the shortlist is evidence.

SAFETY
  * Search is a READ. Nothing is joined; public channels can be polled without
    joining at all.
  * A fresh account is the most ban-prone thing on Telegram, so searches are
    spaced and capped. Adding channels is a separate, deliberate step by Zaid.
  * Channels v1 already polls are excluded — duplicating them would double the
    load on the same content for no extra signal.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Silent longer than this and a channel is dead for a real-time feed, whatever
# its historical posting rate was.
STALE_AFTER_DAYS = 14

OUT = ROOT / "ops" / "channel-candidates.md"
RAW = ROOT / "ops" / "channel-candidates.json"

# Arabic search queries per category. Deliberately colloquial — these are the
# words channel owners actually put in a title, not formal MSA.
QUERIES: dict[str, list[str]] = {
    "fuel": [
        "محروقات", "بنزين", "سولار", "احوال الوقود", "محطات الوقود",
        "ازمة الوقود", "غاز الطبخ",
    ],
    "services": [
        "كهرباء", "انقطاع الكهرباء", "مياه", "شركة الكهرباء",
        "بلدية", "خدمات",
    ],
    "local_news": [
        "اخبار نابلس", "اخبار الخليل", "اخبار جنين", "اخبار طولكرم",
        "اخبار رام الله", "اخبار بيت لحم", "اخبار قلقيلية", "اخبار اريحا",
        "اخبار طوباس", "اخبار سلفيت",
    ],
    "medical": [
        "الهلال الاحمر", "اسعاف", "مستشفى", "وزارة الصحة", "طوارئ",
    ],
    # ── added for tier-1 coverage gaps ───────────────────────────────────────
    # The live tracker currently answers fuel, checkpoints and incidents. These
    # target the kinds of question a family actually asks that nothing yet
    # covers.
    "crossings": [
        # Travel abroad runs through one bridge; when it closes or backs up,
        # that is the single highest-consequence movement fact for a family,
        # and no channel now polled reports it.
        "جسر الملك حسين", "معبر الكرامة", "الكرامة", "معبر اللنبي",
        "حالة الجسر", "السفر عبر الجسر", "معبر رفح",
    ],
    "utilities": [
        "انقطاع الكهرباء", "شركة كهرباء القدس", "كهرباء الشمال",
        "مصلحة مياه", "انقطاع المياه", "الاتصالات الفلسطينية", "جوال",
    ],
    "displacement": [
        "هدم المنازل", "اخطارات هدم", "نزوح", "اخلاء", "مسافر يطا",
        "الاغوار الشمالية", "التطهير العرقي",
    ],
    "markets": [
        "اسعار", "اسعار الخضار", "سوق", "غلاء الاسعار", "المستهلك",
    ],
    "education": [
        "وزارة التربية والتعليم", "تعليق الدوام", "الدوام المدرسي",
        "جامعة النجاح", "جامعة بيرزيت",
    ],
    "weather": [
        "طقس فلسطين", "الارصاد الجوية", "حالة الطقس", "منخفض جوي",
    ],
}

# Already polled by v1 — do not duplicate.
V1_ENV = Path("/opt/stacks/palestine/services/westbank-alerts/.env")

# Telegram search is REGIONAL, not national: "محروقات" returns Syrian and Iraqi
# fuel channels, "كهرباء" returns Aleppo and Idlib utilities, "خدمات" returned a
# massage channel. Relevance must be scored, not assumed.
PS_MARKERS = [
    "فلسطين", "الضفة", "الضفه", "غزة", "غزه", "القدس", "نابلس", "الخليل",
    "جنين", "رام الله", "طولكرم", "بيت لحم", "قلقيلية", "قلقيليه", "اريحا",
    "أريحا", "طوباس", "سلفيت", "بيرزيت", "الاغوار", "الأغوار", "بيتونيا",
    "دورا", "يطا", "قباطية", "يعبد", "عناتا", "حوارة", "حواره",
    "palestin", "gaza", "nablus", "hebron", "jenin", "ramallah", "tulkarm",
    "bethlehem", "qalqilya", "jericho", "tubas", "salfit", "khalil",
]
# Strong negatives — a title carrying these is almost certainly not local.
NON_PS_MARKERS = [
    "سوريا", "سورية", "حلب", "ادلب", "إدلب", "دمشق", "حمص", "درعا", "اللاذقية",
    "العراق", "الموصل", "بغداد", "الفلوجة", "البصرة", "كربلاء", "النجف",
    "ايران", "إيران", "طهران", "البرز", "كرج",
    "السودان", "الخرطوم", "مصر", "القاهرة", "اليمن", "صنعاء", "ليبيا",
    "السعودية", "الكويت", "قطر", "الامارات", "تركيا",
    "syria", "iraq", "iran", "sudan", "egypt", "yemen", "aleppo", "mosul",
    "baghdad", "tehran", "massage", "ماساژ", "صرافی",
]


def v1_channels() -> set[str]:
    """Everything ALREADY polled, by either account.

    v1's list and agent2's own list both count. Re-surfacing a channel one of
    them already reads wastes the review and, if added, would double the load on
    the same content for no extra signal — the two accounts exist to cover
    different ground, not the same ground twice.
    """
    out: set[str] = set()
    for path, keys in (
        (V1_ENV, ("TELEGRAM_CHANNELS=", "CHECKPOINT_CHANNELS=", "FUEL_CHANNELS=",
                  "GAZA_BULLETIN_CHANNELS=")),
        (ROOT / ".env", ("V2_TELEGRAM_CHANNELS=",)),
    ):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            for key in keys:
                if line.startswith(key):
                    out |= {c.strip().lstrip("@").lower()
                            for c in line.split("=", 1)[1].split(",") if c.strip()}
    return out


def relevance(title: str, username: str) -> tuple[int, list[str]]:
    """Score a channel's Palestine relevance from its title and handle.

    Positive: an explicit Palestinian place or national marker.
    Negative: a marker from another country. A title can hit both (e.g. a
    Palestinian channel mentioning Egypt), so the score is a difference and the
    reasons are reported for review rather than silently applied.
    """
    hay = f"{title} {username}".lower()
    hits = [m for m in PS_MARKERS if m.lower() in hay]
    misses = [m for m in NON_PS_MARKERS if m.lower() in hay]
    return len(hits) * 2 - len(misses) * 3, hits + [f"-{m}" for m in misses]


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update(os.environ)
    return env


async def discover(categories: list[str], per_query: int = 25) -> dict:
    from telethon import TelegramClient, functions

    e = _env()
    api_id = int(e.get("V2_TELEGRAM_API_ID", "0") or 0)
    api_hash = e.get("V2_TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        print("V2_TELEGRAM_API_ID / V2_TELEGRAM_API_HASH not set in .env")
        return {}
    session = str(ROOT / "data" / "session" / "v2_ingest")
    if not Path(session + ".session").exists():
        print(f"No session at {session}.session — run: "
              "./.venv/bin/python -m ingest.setup_session")
        return {}

    known = v1_channels()
    found: dict[str, dict] = {}
    from ingest.session_lock import acquire          # one client per session file (F213)
    acquire(session, who="discover_channels")
    client = TelegramClient(session, api_id, api_hash)
    await client.start()

    for cat in categories:
        for qi, query in enumerate(QUERIES.get(cat, [])):
            try:
                res = await client(functions.contacts.SearchRequest(q=query, limit=per_query))
            except Exception as exc:                       # noqa: BLE001
                print(f"  search {query!r} failed: {exc}")
                continue
            for chat in getattr(res, "chats", []):
                uname = (getattr(chat, "username", None) or "").lower()
                if not uname or uname in known:
                    continue
                title = getattr(chat, "title", "") or ""
                score, reasons = relevance(title, uname)
                prev = found.get(uname)
                rec = {
                    "relevance": score,
                    "relevance_reasons": reasons,
                    "username": getattr(chat, "username"),
                    "title": title,
                    "participants": getattr(chat, "participants_count", None) or 0,
                    "broadcast": bool(getattr(chat, "broadcast", False)),
                    "megagroup": bool(getattr(chat, "megagroup", False)),
                    "categories": sorted({cat} | set(prev["categories"] if prev else [])),
                    "matched": sorted({query} | set(prev["matched"] if prev else [])),
                }
                found[uname] = rec
            # Space the searches out — a new account hammering search is exactly
            # what trips rate limits.
            await asyncio.sleep(2.5 + random.random() * 2)
        print(f"  [{cat}] cumulative candidates: {len(found)}")

    await client.disconnect()
    return found


def write_report(found: dict) -> None:
    # RECENCY GATES RATE. Ranking on rate alone is not enough and produced its
    # own version of the @JDECONET mistake: @alrasedaljawe scored 14.1 msgs/day
    # and sorted top, but its newest post was 17 months old — the rate was
    # computed across the span of messages it made back when it was alive.
    # @alquds21alquds likewise, last post 2021. A channel silent for a
    # fortnight is dead for a real-time feed whatever it used to do, so it
    # sorts below every live one regardless of rate.
    def _rank(r):
        ago = r.get("days_since_post")
        stale = ago is None or ago > STALE_AFTER_DAYS
        return (stale, -(r.get("msgs_per_day") or 0), -r["relevance"], -r["participants"])

    all_rows = sorted(found.values(), key=_rank)
    rows = [r for r in all_rows if r["relevance"] > 0]
    rejected = [r for r in all_rows if r["relevance"] <= 0]
    RAW.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# Channel candidates — discovered {datetime.now(timezone.utc).date()}\n",
         f"Searched {len(all_rows) + len(v1_channels())} results; **{len(rows)} are "
         f"Palestine-relevant**, {len(rejected)} filtered out as other-country or "
         f"off-topic. Excludes the {len(v1_channels())} channels v1 already polls.",
         "**Nothing has been joined or added.**\n",
         "> Telegram search is regional: \"محروقات\" returns Syrian and Iraqi fuel",
         "> channels, \"كهرباء\" returns Aleppo and Idlib utilities. Relevance is",
         "> scored from Palestinian place/national markers in the title, minus",
         "> other-country markers. Review before adding — the filter is a",
         "> heuristic, not an oracle.\n",
         "Public channels can be polled without joining. Add a FEW at a time — a",
         "freshly-registered account is the most ban-prone thing on Telegram.\n",
         "| # | channel | msg/day | last post | subs | type | category | title |",
         "|--:|:--|--:|:--|--:|:--|:--|:--|"]
    for i, r in enumerate(rows[:60], 1):
        kind = "broadcast" if r["broadcast"] else ("group" if r["megagroup"] else "?")
        title = r["title"].replace("|", "/")[:40]
        rate = r.get("msgs_per_day")
        rate_s = "—" if rate is None else f"**{rate:g}**"
        ago = r.get("days_since_post")
        ago_s = "—" if ago is None else (f"{ago:g}d ago" if ago < 400 else f"**{ago/365:.1f}y ago**")
        L.append(f"| {i} | `{r['username']}` | {rate_s} | {ago_s} | {r['participants']:,} | "
                 f"{kind} | {','.join(r['categories'])} | {title} |")
    L.append("\n<details><summary>Filtered out (%d) — other country or off-topic</summary>\n"
             % len(rejected))
    L.append("| channel | subs | why |\n|:--|--:|:--|")
    for r in rejected[:40]:
        why = ", ".join(x for x in r["relevance_reasons"] if x.startswith("-")) or "no PS marker"
        L.append(f"| `{r['username']}` | {r['participants']:,} | {why} |")
    L.append("\n</details>")
    L.append("\n## To add (a few at a time)\n")
    L.append("```\n# ~/palestine-v2/.env\nV2_TELEGRAM_CHANNELS=chan1,chan2,chan3\n```\n")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n{len(rows)} candidates -> {OUT}")


async def probe_liveness(candidates: list[dict], limit: int = 30) -> None:
    """Measure POSTING RATE for the top candidates.

    Subscriber count says nothing about liveness. Selecting the first five
    channels by subscribers landed @JDECONET (334 subs, 3.5 years silent) and
    @Palrcs (2.5k subs, ~0.14 msg/day) — both useless for a live feed. Rate is
    the criterion that matters; subscribers only break ties.

    One cheap get_messages per channel, spaced. Read-only, no joins.
    """
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError

    e = _env()
    from ingest.session_lock import acquire          # one client per session file (F213)
    acquire(ROOT / "data" / "session" / "v2_ingest", who="probe_liveness")
    client = TelegramClient(str(ROOT / "data" / "session" / "v2_ingest"),
                            int(e["V2_TELEGRAM_API_ID"]), e["V2_TELEGRAM_API_HASH"])
    await client.connect()
    if not await client.is_user_authorized():
        print("not authorised — skipping liveness probe")
        return

    for i, c in enumerate(candidates, 1):
        try:
            msgs = await client.get_messages(c["username"], limit=limit)
            dates = [m.date for m in msgs if getattr(m, "date", None)]
            if len(dates) >= 2:
                span_days = max((max(dates) - min(dates)).total_seconds() / 86400, 0.04)
                c["msgs_per_day"] = round(len(dates) / span_days, 2)
                c["last_post"] = max(dates).isoformat()
                c["days_since_post"] = round(
                    (datetime.now(timezone.utc) - max(dates)).total_seconds() / 86400, 1)
            else:
                c["msgs_per_day"] = 0.0
                c["days_since_post"] = None
        except FloodWaitError as fw:
            print(f"  FLOOD WAIT {fw.seconds}s — stopping probe at {i}/{len(candidates)}")
            break
        except Exception as exc:                        # noqa: BLE001
            c["msgs_per_day"] = None
            c["probe_error"] = str(exc)[:80]
        if i % 5 == 0:
            print(f"  probed {i}/{len(candidates)}")
        await asyncio.sleep(2.0 + random.random() * 1.5)
    await client.disconnect()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=0,
                    help="measure posting rate for the top N relevant candidates")
    ap.add_argument("--category", action="append", choices=sorted(QUERIES))
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    cats = sorted(QUERIES) if a.all or not a.category else a.category
    print(f"Discovering: {', '.join(cats)}")
    found = asyncio.run(discover(cats))
    if found and a.probe:
        top = sorted([r for r in found.values() if r["relevance"] > 0],
                     key=lambda r: -r["participants"])[:a.probe]
        print(f"Probing liveness for top {len(top)} …")
        asyncio.run(probe_liveness(top))
    if found:
        write_report(found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
