"""MCP server — one surface for Fawwaz, Sameera, Claude, or any agent.

    ./.venv/bin/python -m serve.mcp_server            # stdio (agent spawns it)

Speaks MCP over stdio with no SDK dependency — the protocol is small, and a
hand-rolled server has no version drift with whatever hermes ships.

DESIGN FOR A VOICE BOT
Every tool returns a short `answer` string in Arabic AND the structured data.
A voice assistant can read `answer` aloud verbatim; a UI can use the rest. That
keeps the phrasing — especially how uncertainty is expressed — in one place
rather than re-invented by each agent.

NO DATABASE CREDENTIALS
This server talks to the v2 HTTP API, never to Postgres directly. hermes runs
as user `admin`, which cannot read `.env` (chmod 600, holds the DB password and
the Telegram api_hash) — and the fix for that is not to loosen those permissions
but to give the MCP layer no secrets to need. The API is the single data path;
MCP is a typed facade over it, so both agents and any HTTP client see exactly
the same values.

UNCERTAINTY IS SPOKEN, NOT DROPPED
When a reading has decayed the answer says so ("آخر تحديث قبل ساعتين") instead
of asserting a stale value. For fuel during a shortage that difference is a
wasted tank of petrol; for a checkpoint it can be worse. The serving layer
already refuses to assert stale state — this makes sure the voice layer repeats
the caveat rather than smoothing it away.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from serve.mcp_en import (effective_groups, field_words, product_labels,  # noqa: E402
                          share_words)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

PROTOCOL = "2024-11-05"
API = os.environ.get("PALESTINE_API", "http://127.0.0.1:7870")


# Every tool reaches the API through api(), so this is the one place a path can
# be checked — and it has to be checked, because the server is now reachable by
# strangers. `databank(category=...)` puts a caller's string into a URL PATH,
# and "../../health" walked straight out of the databank surface and hit another
# endpoint. It leaked nothing (the response shape differed and the tool raised),
# which is luck, not a control. Anything the tools legitimately fetch is one of
# two shapes; a path that is neither does not get sent.
_SAFE_PATH = re.compile(r"^/(?:health|v2/[A-Za-z0-9/_.-]*)$")


def api(path: str, **params) -> dict:
    """GET the v2 API. Raises on failure so the caller can answer honestly
    rather than inventing a reassuring reply."""
    if ".." in path or not _SAFE_PATH.match(path):
        raise ValueError(f"refusing to fetch an unexpected path: {path!r}")
    r = httpx.get(f"{API}{path}", params={k: v for k, v in params.items() if v is not None},
                  timeout=API_TIMEOUT)
    r.raise_for_status()
    return r.json()


# One slow endpoint used to turn a composite (about = 5 calls, place_profile = 6)
# into a 30–180 s request that held an MCP worker while the client had long
# timed out (audit 2026-09-25 F268). 8 s per call; composites mark what they
# had to skip in `partial` rather than failing whole.
API_TIMEOUT = float(os.environ.get("MCP_API_TIMEOUT", "8"))


def _counted_ar(n: int, one: str, two: str, few: str, many: str) -> str:
    """A counted noun the way it is said: 1 دقيقة, 2 دقيقتين, 3–10 دقايق,
    11+ دقيقة (audit 2026-09-25 F504 — a voice bot read 'قبل 2 ساعة')."""
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n <= 10:
        return f"{n} {few}"
    return f"{n} {many}"


def _age_ar(minutes: int | None) -> str:
    if minutes is None:
        return "غير معروف"
    m = int(minutes)
    if m < 1:
        # A negative age is clock skew on a future occurred_at, not a fact.
        return "الآن"
    if m < 60:
        return "قبل " + _counted_ar(m, "دقيقة", "دقيقتين", "دقايق", "دقيقة")
    if m < 1440:
        return "قبل " + _counted_ar(m // 60, "ساعة", "ساعتين", "ساعات", "ساعة")
    return "قبل " + _counted_ar(m // 1440, "يوم", "يومين", "أيام", "يوم")


# ── tools ────────────────────────────────────────────────────────────────────

def fuel_prices(product: str | None = None, history: bool = False) -> dict:
    """Official West Bank fuel prices: today's, or every list read so far."""
    product = {"بنزين": "gasoline_95", "بنزين 95": "gasoline_95", "بنزين 98": "gasoline_98",
               "سولار": "diesel", "ديزل": "diesel", "كاز": "kerosene", "غاز": "lpg_12kg",
               "petrol": "gasoline_95", "gasoline": "gasoline_95", "gas": "lpg_12kg",
               "lpg": "lpg_12kg"}.get((product or "").strip().lower(), product)
    if history:
        d = api("/v2/fuel/prices/history", product=product)
        rows = d.get("history", [])
        if not rows:
            return {"answer": "ما في أسعار مؤكدة مسجلة لهاد الصنف.", "history": [],
                    "scope": d.get("scope")}
        last = rows[-1]
        return {"answer": (f"آخر سعر مؤكد: {last['price']} شيكل من {last['effective_from']}، "
                           f"و{len(rows)} سعر مؤكد مسجل."),
                "history": rows, "scope": d.get("scope"), "source": d.get("attribution")}
    d = api("/v2/fuel/prices", product=product)
    rows = d.get("prices", [])
    unit_ar = {"ILS/L": "شيكل للتر", "ILS/cylinder": "شيكل"}
    said, gaps = [], []
    for r in rows:
        if r["price"] is not None:
            said.append(f"{r['name_ar']}: {r['price']:g} {unit_ar.get(r['unit'], 'شيكل')}")
        elif r["status"] == "awaiting_list":
            gaps.append(f"{r['name_ar']}: ما انقرت تسعيرة هالشهر لسا "
                        f"(آخر سعر مؤكد {r['last_confirmed_price']:g} من {r['last_confirmed_from']})")
        elif r["status"] in ("unconfirmed", "conflicting"):
            rep = "، ".join(f"{x['price']:g}" for x in (r.get("reported") or []))
            gaps.append(f"{r['name_ar']}: غير مؤكد (المنشور: {rep})")
    # Kerosene and LPG came into force on 1 Sep, petrol and diesel on the 7th;
    # naming one date for all of them was wrong for four of the eight products.
    groups = effective_groups(rows)
    if len(groups) == 1:
        since = groups[0][0]
    elif groups:
        since = "، ومن ".join(f"{d} لـ{'، '.join(product_labels(g, 'ar'))}"
                              for d, g in groups)
    else:
        since = None
    head = ("الحد الأقصى الرسمي لأسعار المحروقات بالضفة، من الهيئة العامة للبترول"
            + (f"، ساري من {since}" if since else "") + ": ")
    answer = head + ("، ".join(said) if said else "ما في سعر مؤكد حالياً")
    if gaps:
        answer += ". " + "؛ ".join(gaps)
    return {"answer": answer + ".", "prices": rows, "scope": d.get("scope"),
            "as_of_date": d.get("as_of_date"), "source": d.get("attribution")}


# ── checkpoints ──────────────────────────────────────────────────────────────
# The serving layer refuses to assert a reading it cannot stand behind, and
# returns `unknown` with the last reading preserved beside it. The temptation
# here is to answer "ما بعرف" ("I don't know") and stop — which throws away the
# one thing the caller can actually use.
#
# So an uncertain answer LEADS with the age: "آخر تحديث قبل ساعتين: كان سالك."
# The listener gets the reading and its age in the same breath and decides for
# themselves, which is what a person standing at a junction actually needs. What
# is never done is stating a decayed value as though it were current — the
# failure this whole layer exists to prevent, and the one that puts someone on a
# road that closed three hours ago.

FLOW_AR = {"open": "سالك", "closed": "مغلق", "congested": "فيه أزمة",
           "slow": "بطيء", "unknown": "غير معروف"}
PRESENCE_AR = {"idf": "جيش", "police": "شرطة", "settlers": "مستوطنين",
               "inspection": "تفتيش"}
DIR_AR = {"inbound": "للداخل", "outbound": "للخارج", "both": "بالاتجاهين"}
DIR_IN = {"داخل": "inbound", "للداخل": "inbound", "دخول": "inbound",
          "خارج": "outbound", "للخارج": "outbound", "خروج": "outbound",
          "in": "inbound", "out": "outbound"}


def _flow_phrase(cp: dict) -> str:
    """One clause describing flow, honest about staleness."""
    if cp["flow"] != "unknown":
        return FLOW_AR.get(cp["flow"], cp["flow"])
    last = cp.get("last_known_flow")
    if not last or last == "unknown":
        return "ما عندي معلومات عنه"
    return f"ما في تحديث جديد — آخر معلومة {_age_ar(cp.get('age_minutes'))}: كان {FLOW_AR.get(last, last)}"


def _presence_phrase(cp: dict) -> str:
    who = [PRESENCE_AR.get(p, p) for p in (cp.get("present") or [])]
    return f" وفي {' و'.join(who)}" if who else ""


def _dir_clause_ar(row: dict | None, label: str) -> str:
    """One travel direction with its own age, or an honest 'no update'."""
    f = (row or {}).get("flow")
    if not f or f == "unknown":
        return f"{label} ما في تحديث حديث"
    return f"{FLOW_AR.get(f, f)} {label} ({_age_ar((row or {}).get('age_minutes'))})"


def checkpoint_status(name: str, direction: str = "both") -> dict:
    """Is a named checkpoint open? Optionally for one travel direction."""
    direction = DIR_IN.get(direction.strip().lower(), direction.strip().lower())
    if direction not in ("inbound", "outbound", "both"):
        direction = "both"
    d = api("/v2/checkpoints/status", name=name, direction=direction)
    if not d.get("found"):
        # A checkpoint the registry knows and nobody has ever reported is a
        # different fact from a name we cannot place (F049).
        if d.get("resolved_to"):
            return {"answer": f"{d['resolved_to']}: حاجز معروف بس ما وصلنا عنه ولا تقرير لحد الآن.",
                    **d}
        return {"answer": f"ما عرفت حاجز اسمه {name}.", **d}

    nm = d["match"]["resolved_to"]
    by = d.get("by_direction") or {}
    inb, outb = by.get("inbound"), by.get("outbound")

    # Where the two directions genuinely differ, say so — that difference is
    # the whole reason direction is tracked, and it is exactly what a bare
    # status hides.
    #
    # Each direction carries its OWN age (F044/F035/F050), and a known
    # direction is never hidden behind an unknown one: "closed inbound 9 minutes
    # ago, outbound unknown" used to fall through to the decayed row (F009).
    known = [r for r in (inb, outb) if r and r.get("flow") not in (None, "unknown")]
    if (direction == "both" and inb and outb and known
            and inb.get("flow") != outb.get("flow")):
        answer = (f"{nm}: {_dir_clause_ar(inb, 'للداخل')}، "
                  f"و{_dir_clause_ar(outb, 'للخارج')}."
                  f"{_presence_phrase(d)}")
    else:
        suffix = "" if direction == "both" else f" {DIR_AR[direction]}"
        answer = f"{nm}{suffix}: {_flow_phrase(d)}.{_presence_phrase(d)}"
        if d["flow"] != "unknown":
            answer += f" آخر تحديث {_age_ar(d.get('age_minutes'))}."

    # A fuzzy match used to be invisible: "Zaatara" answered about عطارة, 11 km
    # away and in the opposite state, with a match score of 0.738 that never
    # left the database. Saying it out loud is the difference between a
    # traveller checking the name and a traveller driving to the wrong junction.
    # A similarity score above 1.0 is a defect of the scorer, not a stronger
    # match: 1.04 for عين سينيا read as nonsense to the audit. Capped here so
    # the number a reader sees means what it says.
    match = dict(d.get("match") or {})
    if match.get("score") is not None:
        match["score"] = round(min(1.0, float(match["score"])), 3)
    d["match"] = match
    score = float(match.get("score") or 0.0)
    if 0 < score < 0.8:
        # Below 0.8 the match is a guess that happens to be nearest: "Hawara"
        # resolved to عورتا at 0.707. A guess that answers confidently is worse
        # than one that refuses, so the doubt goes FIRST here.
        answer = (f"مش متأكد من الاسم — أقرب تطابق {nm}. {answer} "
                  "إذا ما قصدت هذا الحاجز، جرّب الاسم كامل أو بالإنجليزي.")
    elif score < 0.9:
        answer += (" تنبيه: الاسم تطابق تقريبياً — تأكد إنك قصدت نفس الحاجز، "
                   "في حواجز بأسماء قريبة.")

    withheld = None
    if d.get("flow") == "unknown" and d.get("staleness_band") in ("live", "recent", "stale"):
        # "recent" beside "no current reading" read as a contradiction (Claude
        # web's test on al-Lubban, 2026-09-25): the band is about the place's
        # reporting rhythm; the value is gated by confidence and age.
        withheld = ("still reported at this checkpoint's own rhythm, but no value "
                    "is assertable: confidence has decayed below the floor or the "
                    "age has passed the assert ceiling. `staleness_band` is not a "
                    "claim that the reading is current.")
    return {"answer": answer, "name": nm, "name_en": d.get("name_en"),
            "direction": direction, "value_withheld_because": withheld,
            "match": d.get("match"),
            # The band's meaning is stated ONCE, in palestine://reading-contract
            # (`staleness_band`), not per call (audit F051).
            "flow": d["flow"], "passable": d["passable"],
            "last_known_flow": d.get("last_known_flow"),
            "age_minutes": d.get("age_minutes"),
            "staleness_band": d.get("staleness_band"),
            "confidence": d.get("confidence"),
            "independent_sources": d.get("independent_sources"),
            "present": d.get("present"), "by_direction": by,
            "lat": d.get("lat"), "lon": d.get("lon"),
            "source": d.get("attribution")}


def insights(place: str | None = None, lat: float | None = None,
             lon: float | None = None, days: int = 30,
             radius_km: float = 15) -> dict:
    """One reduction of a place over a window: checkpoints, incidents, sample sizes.

    This is the "give me quick insights about checkpoint status last month
    around Ramallah" call. It answers in one round trip what otherwise takes a
    fetch of hundreds of rows: the reduction happens here, once, and the
    precision each subject was MEASURED at travels with it.
    """
    ask: dict = {"days": days, "radius_km": radius_km}
    if place:
        ask["place"] = place
    elif lat is not None and lon is not None:
        ask["lat"], ask["lon"] = lat, lon
    else:
        return {"answer": "أعطيني اسم مكان أو إحداثيات.", "found": False}
    try:
        d = api("/v2/insights", **ask)
    except Exception as exc:                                    # noqa: BLE001
        if "404" in str(exc):
            return {"answer": f"ما عرفت وين {place}.", "found": False}
        raise
    name = (d.get("scope") or {}).get("name") or place
    ck = d.get("checkpoints") or {}
    inc = d.get("incidents") or {}
    # TWO UNIVERSES, SAID AS TWO. The window's count and the now-count are
    # different sets — a checkpoint can be tracked now with no reading inside the
    # window — and the old sentence put "52 checkpoints" in front of a breakdown
    # that added up to 63. Both numbers are true; each now carries its own
    # subject, so the arithmetic in the sentence matches the number it follows.
    parts = [f"آخر {days} يوم حول {name} (نطاق {radius_km:g} كم): "
             f"{ck.get('readings', 0):,} قراءة عن "
             f"{ck.get('places_in_window', ck.get('places', 0))} حاجز"]

    now = ck.get("now") or {}
    definite = {k: v for k, v in now.items() if k != "unknown"}
    tracked_now = ck.get("places_now")
    head = (f"الآن نتابع {tracked_now} حاجز" if tracked_now
            else "الآن")
    if definite:
        said = "، ".join(f"{_ar_value(k)} {v}" for k, v in
                         sorted(definite.items(), key=lambda kv: -kv[1]))
        parts.append(f"{head}: {sum(definite.values())} بقراءة محددة ({said})")
    if ck.get("unknown_now"):
        parts.append(f"و{ck['unknown_now']} بلا قراءة حديثة")
    fresh = ck.get("freshest_reading_minutes")
    if fresh is not None:
        # "عمرها 152,926 دقيقة" (Claude web's test) — an age is said as an age.
        parts.append(f"أحدث قراءة {_age_ar(int(fresh))}")

    top = (ck.get("most_reported") or [])[:3]
    if top:
        parts.append("أكثر تقاريراً: " + "، ".join(
            f"{r['name_ar']} ({r['readings']:,} قراءة)" for r in top))
    changing = ck.get("changing") or []
    if changing:
        parts.append("حواجز بتغيّر فعلي: " + "، ".join(
            f"{r['name_ar']} ({r['distinct_values']} حالات)" for r in changing[:3]))
    hours = [h["hour"] for h in (ck.get("busiest_hours_hebron") or [])[:3]]
    if hours:
        parts.append("أزحم الساعات بتوقيت البلد: " + "، ".join(f"{h}:00" for h in hours))

    rows = [r for r in (inc.get("by_type") or []) if r.get("type") != "fire_detection"]
    fires = next((r for r in (inc.get("by_type") or []) if r.get("type") == "fire_detection"), None)
    if isinstance(inc, dict):
        inc["by_type"] = rows
        inc["fires"] = {"n": (fires or {}).get("events", 0),
                        "note": "NASA FIRMS satellite fire pixels — detections, not reports"}
    if rows:
        parts.append("أحداث: " + "، ".join(
            f"{r['events']} {_ar_event(r['type'])}"
            + (f" ({r['corroborated']} مؤكَّد)" if r.get("corroborated") is not None else "")
            for r in rows[:6]))
    elif inc.get("events") == 0:
        parts.append("ما في أحداث مسجّلة بالنطاق")
    if fires and fires.get("events"):
        parts.append(f"ورصد الأقمار الصناعية {fires['events']} حريق (بدون تقارير)")

    qy = (d.get("quality") or {}).get("incidents") or {}
    if qy.get("state") == "below gate":
        parts.append(f"تنبيه: مصنّف الأحداث مقيس {qy['precision']:.0%} مقابل بوّابة "
                     f"{qy['gate']:.0%} — دونها")

    return {"answer": ". ".join(parts) + ". "
            "القراءة تقرير قناة، مش إحصاء رسمي. «ما في معلومة» لا تعني «مفتوح».",
            "found": True, **d}

_AR_VALUES = {"open": "مفتوح", "closed": "مغلق", "congested": "مزدحم",
              "slow": "بطيء", "unknown": "بلا معلومة", "restricted": "مقيّد",
              "partial": "جزئي"}
_AR_EVENTS = {"raid": "اقتحام", "settler_attack": "اعتداء مستوطنين",
              "closure": "إغلاق", "arrest": "اعتقال", "demolition": "هدم",
              "shooting": "إطلاق نار", "death": "وفاة", "injury": "إصابة",
              "fire_detection": "حريق", "siege": "حصار",
              "land_levelling": "تجريف أراضٍ"}


def _ar_value(v: str) -> str:
    return _AR_VALUES.get(v, v)


def _ar_event(t: str) -> str:
    return _AR_EVENTS.get(t, t)


def checkpoints_near(place: str | None = None, lat: float | None = None,
                     lon: float | None = None, direction: str = "both",
                     radius_km: float = 15.0, limit: int = 6) -> dict:
    """What are the checkpoints around here doing?"""
    direction = DIR_IN.get(direction.strip().lower(), direction.strip().lower())
    if direction not in ("inbound", "outbound", "both"):
        direction = "both"
    place_en = None
    if lat is None or lon is None:
        if not place:
            return {"answer": "لازم تحدد المكان.", "error": "need place or lat/lon"}
        geo = api("/v2/geo/resolve", q=place)
        if not geo.get("found"):
            return {"answer": f"ما عرفت وين {place}.", "error": "place not resolved"}
        lat, lon, place = geo["lat"], geo["lon"], geo["name"]
        place_en = geo.get("name_en")

    d = api("/v2/checkpoints/nearby", lat=lat, lon=lon, direction=direction,
            radius_km=radius_km, limit=limit)
    res, counts = d.get("results", []), d.get("counts", {})
    known = [r for r in res if r["flow"] != "unknown"]

    if not known and not counts.get("in_radius"):
        # Nothing tracked in range is not "old news" (F052).
        answer = f"ما في حاجز متابَع ضمن {radius_km:g} كم من {place or 'موقعك'}."
    elif not known:
        answer = (f"ما في تحديثات جديدة عن الحواجز حوالين {place or 'هون'}. "
                  f"في {counts.get('in_radius', 0)} حاجز بالمنطقة بس آخر أخبارهم قديمة.")
    else:
        closed = [r for r in known if r["flow"] == "closed"]
        # Every listed state says how old it is (F052).
        parts = [f"{r['name']} {FLOW_AR.get(r['flow'], r['flow'])} ({_age_ar(r.get('age_minutes'))})"
                 f"{_presence_phrase(r)}" for r in known[:4]]
        answer = f"حوالين {place or 'موقعك'}: " + "، ".join(parts) + "."
        if closed:
            answer += f" انتبه: {'، '.join(r['name'] for r in closed)} مغلق."
        # Never let the confident part imply full coverage.
        if counts.get("unknown"):
            answer += f" وفي {counts['unknown']} حاجز ما إلهم تحديث حديث."

    return {"answer": answer, "origin": place or f"{lat:.4f},{lon:.4f}",
            "origin_en": place_en,
            "direction": direction, "counts": counts, "radius_km": radius_km,
            "checkpoints": [{"name": r["name"], "name_en": r.get("name_en") or None,
                             "flow": r["flow"],
                             "passable": r["passable"],
                             "last_known_flow": r.get("last_known_flow"),
                             "km": r.get("straight_km"),
                             "age_minutes": r.get("age_minutes"),
                             "staleness_band": r.get("staleness_band"),
                             "present": r.get("present"),
                             "independent_sources": r.get("independent_sources")}
                            for r in res],
            "source": d.get("attribution")}


def checkpoints_summary() -> dict:
    """West-Bank-wide picture, including the size of the blind spot."""
    d = api("/v2/checkpoints/summary")
    t = d.get("totals", {})
    closed = d.get("closed_now", [])
    bits = []
    if t.get("open"):
        bits.append(f"{t['open']} سالك")
    if t.get("closed"):
        bits.append(f"{t['closed']} مغلق")
    if t.get("congested"):
        bits.append(f"{t['congested']} فيه أزمة")
    answer = ("وضع الحواجز بالضفة — " + "، ".join(bits) + "."
              if bits else "ما في تحديثات حديثة عن الحواجز.")
    if t.get("unknown"):
        # Coverage stated, not implied. We track 246 checkpoints and have fresh
        # readings for a minority of them at any moment; a summary that omits
        # that reads as though the rest are fine.
        answer += f" و{t['unknown']} حاجز ما إلهم تحديث حديث."
    # Eight checkpoint names in the gazetteer belong to two or three DISTINCT
    # places each (دير استيا ×3, الكونتينر ×3, النبي يونس ×2). The payload
    # carried no id, so "النبي يونس" appeared twice and read as a duplicate;
    # the id disambiguates it, and the spoken sentence lists the name once
    # because a name repeated out loud sounds like a fault.
    seen: list[str] = []
    for c in closed:
        if c["name"] not in seen:
            seen.append(c["name"])
    if seen:
        answer += " المغلقة حالياً: " + "، ".join(seen[:6]) + "."
    dupes = len(closed) - len(seen)
    if dupes:
        answer += (f" (وفي {dupes} حاجز مغلق تاني بإسم مكرر — الأسماء بتتشارك "
                   f"بين مواقع مختلفة)")
    return {"answer": answer, "totals": t,
            "known_fraction": d.get("known_fraction"),
            "tracked": d.get("tracked"), "presence": d.get("presence"),
            "closed_now": [{"place_id": c["place_id"], "name": c["name"],
                            "name_en": c.get("name_en"),
                            "age_minutes": c["age_minutes"],
                            "present": c.get("present"),
                            "lat": c.get("lat"), "lon": c.get("lon")}
                           for c in closed],
            "source": d.get("attribution")}


# ── incidents ────────────────────────────────────────────────────────────────
INCIDENT_AR = {
    "raid": "اقتحام", "settler_attack": "اعتداء مستوطنين", "closure": "إغلاق",
    "siege": "حصار", "arrest": "اعتقالات", "injury": "إصابات",
    "shooting": "إطلاق نار", "demolition": "هدم", "death": "استشهاد",
    "land_levelling": "تجريف أراضٍ",
    # Kept in step with _AR_EVENTS above by hand, and it had drifted: this map is
    # the COUNTING register ("5 اعتقالات"), that one phrases a single event
    # ("اعتقال"), so they are two maps on purpose — but a missing key falls
    # through as the raw English label, which is how the Arabic incidents_summary
    # was counting "fire_detection" in the middle of an Arabic sentence while the
    # Arabic insights answer translated it. Every key in one belongs in both.
    "fire_detection": "حرائق",
}


def incidents_near(place: str | None = None, lat: float | None = None,
                   lon: float | None = None, hours: int = 12,
                   radius_km: float = 25.0, limit: int = 8) -> dict:
    """What has been happening around here — raids, settler attacks, closures."""
    # The REST route caps hours at 168; a legal call by the published schema
    # (hours=200) came back as a 422 read aloud as "صار خطأ بالنظام" (F054).
    hours = _clamp(hours, 1, 168, 12)
    if lat is None or lon is None:
        if not place:
            return {"answer": "لازم تحدد المكان.", "error": "need place or lat/lon"}
        geo = api("/v2/geo/resolve", q=place)
        if not geo.get("found"):
            return {"answer": f"ما عرفت وين {place}.", "error": "place not resolved"}
        lat, lon, place = geo["lat"], geo["lon"], geo["name"]

    d = api("/v2/incidents/recent", lat=lat, lon=lon, hours=hours,
            radius_km=radius_km, limit=limit)
    all_items = d.get("incidents", [])
    # A SATELLITE FIRE PIXEL IS NOT A REPORT. `fire_detection` rows come from
    # NASA FIRMS, have no reporter and no corroboration, and read beside raids
    # as "13 fires" to anyone who did not open the payload. They travel apart.
    fires = [i for i in all_items if i.get("type") == "fire_detection"]
    items = [i for i in all_items if i.get("type") != "fire_detection"]
    by_type = dict(d.get("by_type") or {})
    by_type.pop("fire_detection", None)
    if not items:
        answer = f"ما في أحداث مسجلة حوالين {place or 'موقعك'} بآخر {hours} ساعة."
    else:
        parts = []
        for i in items[:4]:
            ar = INCIDENT_AR.get(i["type"], i["type"])
            # Anything short of a NAMED place is governorate-level: a
            # village_ambiguous event was spoken as if it happened in the city
            # (F053).
            prec = i.get("place_precision")
            if prec in (None, "named"):
                where = i["place"]
            elif i.get("named_place"):
                where = (f"{i['named_place']} (محافظة {i['place']}"
                         + ("، القرية مش مؤكدة" if prec == "village_ambiguous" else "") + ")")
            else:
                where = f"محافظة {i['place']}"
            parts.append(f"{ar} في {where} {_age_ar(_mins_since(i['occurred_at']))}")
        answer = f"حوالين {place or 'موقعك'}: " + "، ".join(parts) + "."
        # Corroboration stated plainly — a single channel is not the same as four.
        solo = sum(1 for i in items if i["independent_sources"] < 2)
        if solo:
            answer += f" ({solo} منها من مصدر واحد بس.)"
    if fires:
        answer += f" ورصد الأقمار الصناعية {len(fires)} حريق بالنطاق (بدون تقارير)."
    from serve import quality
    precision = quality.summary(by_type)
    answer += _precision_ar(precision)
    return {"answer": answer, "origin": place or f"{lat:.4f},{lon:.4f}",
            "hours": hours, "count": len(items), "by_type": quality.annotate_by_type(by_type),
            "precision": precision,
            "incidents": items,
            "fires": {"n": len(fires), "note": "NASA FIRMS satellite fire pixels — a "
                                               "detection, not a report; never a raid"},
            "source": d.get("attribution")}


def incidents_summary(hours: int = 24) -> dict:
    hours = _clamp(hours, 1, 168, 24)
    d = api("/v2/incidents/summary", hours=hours)
    bt = dict(d.get("by_type", {}))
    fires = bt.pop("fire_detection", None)
    d["by_type"] = bt
    d["fires"] = {"n": (fires or {}).get("n", 0),
                  "note": "NASA FIRMS satellite fire pixels — detections, not reports"}
    if not bt:
        return {"answer": f"ما في أحداث مسجلة بآخر {hours} ساعة.", **d}
    bits = [f"{v['n']} {INCIDENT_AR.get(k, k)}" for k, v in
            sorted(bt.items(), key=lambda kv: -kv[1]["n"])[:5]]
    places = "، ".join(p["place"] for p in d.get("by_place", [])[:4])
    answer = f"بآخر {hours} ساعة بالضفة: " + "، ".join(bits) + "."
    if places:
        answer += f" الأكثر تأثراً: {places}."
    if d["fires"]["n"]:
        answer += f" ورصدت الأقمار الصناعية {d['fires']['n']} حريق."
    from serve import quality
    d["precision"] = quality.summary(bt)
    answer += _precision_ar(d["precision"])
    return {"answer": answer, **d}


def _precision_ar(precision: dict | None) -> str:
    """The measured read precision of the served types that fall under the
    gate, deaths first — said in the answer, not only carried in the payload."""
    weak = (precision or {}).get("weak") or []
    if not weak:
        return ""
    bits = [f"{INCIDENT_AR.get(w['type'], w['type'])} {round(w['precision'] * 100)}%" for w in weak[:3]]
    rnd = (precision or {}).get("round")
    return (f" دقّة القراءة الآلية بآخر فحص يدوي" + (f" (جولة {rnd})" if rnd else "") +
            ": " + "، ".join(bits) + ".")


def _clamp(v, lo: int, hi: int, default: int) -> int:
    """A caller's number brought inside the REST route's validation range.
    The façade schemas declare the same bounds; this is what makes an
    out-of-range argument a clamp instead of a 422 (audit F054)."""
    try:
        v = int(v) if v is not None else default
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _mins_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - t).total_seconds() // 60)
    except (ValueError, TypeError):
        return None


WEATHER_AR = {
    "extreme_heat": "حر شديد جداً", "heat_wave": "موجة حر", "storm": "عاصفة",
    "frost": "صقيع", "cold": "برد شديد", "rain": "أمطار",
    "high_wind": "رياح قوية", "normal": "عادي", "unknown": "غير معروف",
}


def weather_now(place: str | None = None) -> dict:
    """Conditions per governorate, and whether anything is worth warning about."""
    d = api("/v2/weather", place=place)
    govs, notable = d.get("governorates", []), d.get("notable", [])
    if not govs:
        return {"answer": "ما عندي معلومات طقس حالياً.", **d}

    if place and len(govs) == 1:
        g = govs[0]
        t = (g.get("today") or {})
        answer = (f"{g['governorate_ar'] or g['governorate']}: "
                  f"{WEATHER_AR.get(g['advisory'], g['advisory'])}، "
                  f"الحرارة الآن {g.get('temp_now_c')} والعظمى {t.get('max_c')}.")
    elif notable:
        # Lead with what is actionable; a list of eleven "normal" helps nobody.
        parts = [f"{n['governorate_ar'] or n['governorate']} "
                 f"{WEATHER_AR.get(n['advisory'], n['advisory'])} "
                 f"({(n.get('today') or {}).get('max_c')}°)" for n in notable]
        answer = "تحذيرات الطقس: " + "، ".join(parts) + "."
    else:
        hottest = govs[0]
        answer = (f"الطقس عادي بالضفة. أعلى حرارة في "
                  f"{hottest['governorate_ar'] or hottest['governorate']} "
                  f"{(hottest.get('today') or {}).get('max_c')}°.")
    return {"answer": answer, "notable": notable, "governorates": govs,
            "source": d.get("attribution")}


def connectivity_now() -> dict:
    """Is the internet up in the West Bank? Measured, not reported."""
    d = api("/v2/connectivity")
    st = d.get("status")
    if st == "unknown":
        return {"answer": "ما عندي قياس للشبكة حالياً.", **d}
    if st == "outage":
        answer = "في انقطاع واسع بالإنترنت بالضفة حسب القياس الخارجي."
    elif st == "degraded":
        answer = "في تراجع بجودة الإنترنت بالضفة حسب القياس الخارجي."
    else:
        answer = "الإنترنت بالضفة شغال طبيعي حسب القياس الخارجي."
    if d.get("signals_agreeing") is not None and d.get("signals_total"):
        answer = answer[:-1] + f" ({d['signals_agreeing']} من {d['signals_total']} مؤشرات متفقة)."
    # The age is spoken (answer contract, P0-A.2): the English said "measured
    # 8 min ago" and the Arabic said nothing about when.
    if d.get("age_minutes") is not None:
        answer += f" آخر قياس {_age_ar(int(d['age_minutes']))}."
    return {"answer": answer, **d}


ROAD_BULLETIN = "🚧"     # palhub's machine-generated road tables start with it


def _dedupe_messages(items: list[dict]) -> list[dict]:
    """One row per (source, opening words). The road channel reposts the same
    table every fifteen minutes and a search for a checkpoint name returned five
    copies of one bulletin; the newest copy carries the news, the rest is echo."""
    seen: set[tuple] = set()
    out = []
    for it in items:
        key = (it.get("source_key"), " ".join(str(it.get("text") or "").split())[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def latest_news(area: str | None = None, limit: int = 8, kind: str = "news",
                hours: int | None = None) -> dict:
    """The newest messages. `kind` — news (default) leaves out the road-status
    tables, which are a feed of their own and drowned every other channel
    (five of five items were bulletins, measured 2026-09-24); roads returns
    only them; all returns everything."""
    if kind not in ("news", "roads", "all"):
        raise TypeError("kind must be news, roads or all")
    # `hours` reached the façade schema and stopped here: news(hours=6) returned
    # the newest messages of any age (F047). The REST cap is 100 (F054).
    limit = _clamp(limit, 1, 25, 8)
    d = api("/v2/news/latest", area=area, kind=kind,
            limit=min(max(limit * 4, 20), 100) if kind != "all" else limit,
            hours=_clamp(hours, 1, 720, 168) if hours is not None else None)
    items = d.get("items", [])
    if kind == "news":
        items = [i for i in items if not str(i.get("text", "")).startswith(ROAD_BULLETIN)]
    elif kind == "roads":
        items = [i for i in items if str(i.get("text", "")).startswith(ROAD_BULLETIN)]
    items = _dedupe_messages(items)[:limit]
    for it in items:
        it["age_minutes"] = _mins_since(it.get("reported_at"))
    if not items:
        return {"answer": (f"ما في أخبار جديدة عن {area}." if area else "ما في أخبار جديدة."),
                "kind": kind, "count": 0, "items": []}
    first = items[0]
    age = _age_ar(first.get("age_minutes"))
    what = {"news": "خبر", "roads": "نشرة طرق", "all": "رسالة"}[kind]
    answer = (f"آخر {len(items)} {what}" + (f" عن {area}" if area else "") +
              f"؛ أحدثها {age} من {first.get('source')}: "
              f"{' '.join(str(first.get('text', '')).split())[:160]}")
    return {"answer": answer, "kind": kind, "count": len(items),
            "newest_at": first.get("reported_at"), "items": items,
            "note": ("road-status tables are left out unless kind=roads; identical "
                     "reposts are collapsed to the newest copy")}


def coverage() -> dict:
    d = api("/v2/coverage")
    # Lead with the BLIND SPOTS, not the totals. An agent that reads
    # "1,000,000 messages from 47 sources" and stops has learned the opposite
    # of what this endpoint is for; the fields that nothing reports are the
    # part it needs before it answers a question about them.
    fields = d.get("fields", [])
    dark = [f["state_kind"] for f in fields if f.get("coverage_state") == "never_reported"]
    stale = [f["state_kind"] for f in fields if f.get("coverage_state") == "stale"]
    # crossing_status has no source of its own, but the Allenby bridge and the
    # Jericho rest stop are read through the road channels (the `crossings`
    # tool serves them). "No source for crossing status" contradicted that
    # tool (Claude web's test, 2026-09-25): said as partial, with the gap named.
    partial: dict[str, list[str]] = {}
    if "crossing_status" in dark:
        try:
            xs = api("/v2/crossings").get("crossings") or []
        except Exception:                                    # noqa: BLE001
            xs = []
        if any(c.get("basis") for c in xs):
            dark = [k for k in dark if k != "crossing_status"]
            partial["crossing_status"] = {
                "read": [c["name"] for c in xs if c.get("basis")],
                "read_en": [c.get("name_en") or c["name"] for c in xs if c.get("basis")],
                "no_source": [c.get("name_en") or c["name"] for c in xs if not c.get("basis")]}
    say = (f"عندي {d['total_claims']} رسالة من {len(d['sources'])} مصدر، "
           f"و{sum(d['live_states'].values())} حالة مباشرة.")
    if dark:
        say += f" ما في ولا مصدر لـ: {'، '.join(field_words(k)[0] for k in dark)}."
    if partial.get("crossing_status"):
        pc = partial["crossing_status"]
        say += (f" المعابر: بس {'، '.join(pc['read'])} من قنوات الطرق؛ "
                f"و{_counted_ar(len(pc['no_source']), 'معبر', 'معبرين', 'معابر', 'معبر')} بلا مصدر.")
    if stale:
        say += f" وهاي ساكتة من زمان: {'، '.join(field_words(k)[0] for k in stale)}."
    return {"answer": say,
            "no_source": dark,
            "partial_source": partial,
            "stale": stale,
            "warning": ("Fields under `no_source` have NEVER had an "
                        "observation. Do not report them as 'unknown' — that "
                        "word is also used for a field that is merely quiet, "
                        "and telling a person 'unknown' when the truth is "
                        "'nobody measures this' invites them to ask again "
                        "tomorrow for an answer that will never come."),
            **d}


def crossings(area: str | None = None) -> dict:
    """Gaza and West Bank crossings — open, partial, closed, or unknown.

    Kept out of `checkpoint_status` on purpose: a crossing is asymmetric in
    KIND (Kerem Shalom takes goods, Rafah moves people), its state persists for
    days rather than ninety minutes, and `partial` is not `open`.
    """
    d = api("/v2/crossings", area=area)
    items = d.get("crossings", [])
    if area and not items:
        return {"answer": f"ما في معبر مسجّل بـ{area}. جرّب اسم المحافظة أو المعبر.",
                "count": 0, "crossings": [], "area": area, "no_match": True}
    known = [c for c in items if c.get("value") not in (None, "unknown")]
    # "No source at all" only when NOTHING feeds any crossing. A crossing we
    # follow whose reading decayed is `unknown` with a last-known value — the
    # early return said "no source" over it (F055).
    if not known and not any(c.get("basis") for c in items):
        # Narrowed to an area, the sentence names the crossings it is about.
        what = ("، ".join(c["name"] for c in items[:6]) if area else "حالة المعابر")
        return {"answer": (f"ما عندي ولا مصدر بيقول عن {what} — "
                           "مش معناها مفتوحة، معناها ما حدا بيخبرنا."),
                "area": area,
                "count": len(items), "crossings": items,
                "no_source": True,
                "warning": ("Every crossing reads `unknown` because NO source "
                            "reports crossing status yet. This is absence of "
                            "evidence, not evidence of absence. Never present "
                            "it as 'the crossing is open'.")}
    # `basis` matters: a reading that came from the checkpoint layer is this
    # system's own observation of traffic at that crossing, not a statement by
    # a crossings authority, and the caller can tell the two apart.
    # THREE KINDS OF SILENCE, SAID AS THREE. A crossing with a value; one we
    # follow but whose reading decayed (last known + age); and the ones NO
    # source reports at all — today that is every Gaza crossing, and a
    # headline that named only the one Jericho reading was read as "Rafah is
    # fine" by everyone who did not open the payload.
    decayed = [c for c in items if c not in known and c.get("basis")]
    unsourced = [c for c in items if not c.get("basis")]
    bits = [f"{c['name']}: {_ar_value(c['value'])}"
            + (f" ({_age_ar(int(c['age_minutes']))})" if c.get("age_minutes") is not None else "")
            for c in known[:6]]
    say = ("المعابر — " + "، ".join(bits) + ".") if bits else "ما في قراءة حديثة لأي معبر."
    if decayed:
        say += " بلا قراءة حديثة: " + "، ".join(
            f"{c['name']} (آخر معلومة {_ar_value(c.get('last_known_value') or 'unknown')}"
            + (f" {_age_ar(int(c['age_minutes']))}" if c.get("age_minutes") is not None else "")
            + ")" for c in decayed[:4]) + "."
    if unsourced:
        say += (" ما في ولا مصدر بيخبرنا عن: " + "، ".join(c["name"] for c in unsourced[:6])
                + " — مش معناها مفتوحة، معناها ما حدا بيقيسها.")
    return {"answer": say, "count": len(items), "crossings": items,
            "with_a_current_reading": len(known),
            "decayed": [c["name"] for c in decayed],
            "no_source_for": [c["name"] for c in unsourced],
            # Passed through so a caller can tell WHY a reading is withheld while
            # its band still reads fresh — the two are gated by different rules,
            # and bare they look like a contradiction (measured on King Hussein
            # Bridge: value `unknown` beside band `live` at 691 minutes).
            "note": ("Where basis is `checkpoint_flow` the reading is this "
                     "system's own checkpoint observation, not a crossing "
                     "authority's statement.")}


def where_is(place: str, state_kind: str | None = None) -> dict:
    """Resolve an Arabic or English place name to coordinates.

    PASS `state_kind` WHEN YOU MEAN A CHECKPOINT, A STATION OR A CROSSING.
    Without it "حوارة" resolves to the TOWN, and every report about that
    checkpoint sits on a different row — so a history or pattern query comes
    back empty while looking perfectly healthy. Three separate silent failures
    came from exactly this before it was made a shared resolver.
    """
    d = api("/v2/geo/resolve", q=place, state_kind=state_kind)
    if not d.get("found"):
        return {"answer": _not_found_ar(place, d), **d}
    ans = f"{d.get('name')} ({_KIND_AR.get(d.get('kind'), d.get('kind'))}) — {d.get('lat')}, {d.get('lon')}."
    if d.get("also_checkpoint"):
        ans += (f" وفي حاجز اسمه {d['also_checkpoint']['name']} — "
                "لحالته اسأل checkpoint_status، ولتاريخه view=history.")
    return {"answer": ans, **d}


_KIND_AR = {"locality": "بلدة", "city": "مدينة", "town": "بلدة", "village": "قرية",
            "camp": "مخيم", "checkpoint": "حاجز", "crossing": "معبر", "road": "مفرق/طريق",
            "governorate": "محافظة", "region": "منطقة", "station": "محطة"}


def _not_found_ar(place: str, g: dict) -> str:
    """'Not found' only when nothing matched; several matches are named."""
    if g.get("ambiguous") and g.get("options"):
        return (f"في أكثر من مكان اسمه {place}: "
                + "، ".join(o.get("name") or "?" for o in g["options"][:4])
                + " — اكتب الاسم كامل.")
    return f"ما عرفت وين {place}."



# ── P5.1/P5.2 parity: an agent must be able to reach everything a frontend can ─
# Otherwise "one place to read everything" quietly means "one place, unless you
# are an agent", and the two surfaces drift until nobody knows which is
# authoritative.

def place_history(place: str, state_kind: str | None = None,
                  days: int = 30) -> dict:
    """Daily report counts for a place, from the databank rollup."""
    g = api("/v2/geo/resolve", q=place, state_kind=state_kind or "checkpoint_status")
    if not g.get("found"):
        return {"answer": _not_found_ar(place, g), "found": False, **g}
    d = api("/v2/history/place", place_id=g["place_id"],
            state_kind=state_kind, days=days)
    series = d.get("series", [])
    if not series:
        return {"answer": f"ما عندي تاريخ محفوظ عن {g['name']} بعد.",
                "place": g["name"], "place_en": g.get("name_en"), "series": []}
    # Summarise so a model does not have to reduce 30 days itself to answer
    # "has it been bad lately".
    tot: dict[str, dict[str, int]] = {}
    for day in series:
        for kind, v in day["kinds"].items():
            slot = tot.setdefault(kind, {})
            for val, n in v.get("values", {}).items():
                slot[val] = slot.get(val, 0) + n
    # THE HEADLINE SAYS WHAT HAPPENED, not how many days it holds. Flow and
    # presence are two axes: the legacy `checkpoint_status` kind mixes them, so
    # the sentence reads `checkpoint_flow` for the road and the presence kinds
    # for who was seen, and never adds an army sighting to an "open" count.
    flow = tot.get("checkpoint_flow") or {}
    nflow = sum(flow.values())
    parts = [f"{g['name']}، آخر {days} يوم"]
    if nflow:
        said = "، ".join(f"{_ar_value(k)} {v}" for k, v in
                         sorted(flow.items(), key=lambda kv: -kv[1]))
        parts.append(f"{nflow} تقرير عن الطريق — {said}")
        worst = max(series, key=lambda day: (day["kinds"].get("checkpoint_flow") or {})
                    .get("values", {}).get("closed", 0))
        wc = (worst["kinds"].get("checkpoint_flow") or {}).get("values", {}).get("closed", 0)
        if wc:
            parts.append(f"أسوأ يوم {worst['day']} ({wc} تقرير مسكّر)")
    else:
        other = {k: sum(v.values()) for k, v in tot.items()
                 if not k.startswith("checkpoint_")}
        if other:
            parts.append("، ".join(f"{n} تقرير {k}" for k, n in other.items()))
    seen = []
    for kind, word in (("checkpoint_idf", "الجيش"), ("checkpoint_settlers", "مستوطنين"),
                       ("checkpoint_police", "الشرطة"), ("checkpoint_inspection", "تفتيش")):
        n = (tot.get(kind) or {}).get("present", 0)
        if n:
            seen.append(f"{word} {n} مرات")
    if seen:
        parts.append("شوهد: " + "، ".join(seen))
    units = max((v.get("units", 0) for day in series for v in day["kinds"].values()),
                default=0)
    if units:
        parts.append(f"من {units} جهة مستقلة كحد أقصى في اليوم")
    return {"answer": "؛ ".join(parts) + ".",
            "place": g["name"], "place_en": g.get("name_en"), "place_id": g["place_id"],
            "days": days, "days_with_data": len(series), "totals_by_kind": tot,
            "flow_totals": flow, "max_independent_units_per_day": units,
            "series": series,
            "counts": "reports, not time — sparse days mean sparse attention."}


def place_pattern(place: str, state_kind: str = "checkpoint_flow",
                  days: int = 60) -> dict:
    days = _clamp(days, 7, 365, 60)              # /v2/patterns: ge=7, le=365 (F054)
    """What usually happens here, by hour of day, local time.

    Two fixes from the partner's QA pass (2026-09-23). The default was
    `checkpoint_status`, the legacy kind that carries presence words (`idf`,
    `police`) in the same column as flow, so the per-hour counts mixed two axes.
    And the headline was a binary — any closed hour meant "usually closed",
    otherwise "usually open" — which answered "usually open" for Qalandiya
    where the modal hour is `congested`, i.e. exactly the state a traveller
    needs to know about. The headline now reports the modal value and how many
    hours it holds, and never claims a value the hours do not show.
    """
    g = api("/v2/geo/resolve", q=place, state_kind=state_kind)
    if not g.get("found"):
        return {"answer": _not_found_ar(place, g), "found": False, **g}
    d = api("/v2/patterns/place", place_id=g["place_id"],
            state_kind=state_kind, days=days)
    known = [h for h in d["hours"] if h.get("usually") not in (None, "unknown")]
    if not known:
        return {"answer": f"ما في تقارير كافية عن {g['name']} لأستنتج نمط.",
                "place": g["name"], "place_en": g.get("name_en"), "hours": d["hours"],
                "caveat": d.get("note")}

    tally: dict[str, int] = {}
    for h in known:
        tally[h["usually"]] = tally.get(h["usually"], 0) + 1
    modal, n_modal = max(tally.items(), key=lambda kv: kv[1])
    word = {"open": "سالك", "congested": "فيه أزمة", "slow": "بطيء",
            "closed": "مسكّر"}.get(modal, modal)
    answer = (f"{g['name']}: عادة {word} — {n_modal} من {len(known)} ساعة "
              f"إلها تقارير كافية.")
    if "congested" in tally and modal != "congested":
        hrs = "، ".join(f"{h['hour']:02d}:00" for h in known
                        if h["usually"] == "congested")[:120]
        if hrs:
            answer += f" ساعات الأزمة: {hrs}."
    closed = [h for h in known if h["usually"] == "closed"]
    if closed:
        answer += " ساعات الإغلاق: " + "، ".join(f"{h['hour']:02d}:00" for h in closed[:6]) + "."
    return {"answer": answer, "place": g["name"], "place_en": g.get("name_en"),
            "place_id": g["place_id"],
            "timezone": d["timezone"], "hours": d["hours"],
            "usually_by_hour_tally": tally,
            "caveat": d["note"]}


RETIRED_KINDS = ("fuel_diesel", "fuel_gasoline", "cooking_gas")


def area_history(state_kind: str | None = None, days: int = 30) -> dict:
    """Totals by governorate — the cross-tier view.

    The headline ranks governorates by how much of their road reporting was
    `closed`, which is the question the tool exists for. Retired feeds are
    dropped from the payload: a quarantined or retired kind never appears as
    data (DESIGN law 7), and the fuel-availability columns were retired on
    2026-09-23."""
    d = api("/v2/history/area", state_kind=state_kind, days=days)
    govs = d.get("governorates", {})
    for g in govs.values():
        for k in RETIRED_KINDS:
            (g.get("kinds") or {}).pop(k, None)
    ranked = []
    for name, g in govs.items():
        flow = ((g.get("kinds") or {}).get("checkpoint_flow") or {})
        n = flow.get("reports", 0)
        closed = (flow.get("values") or {}).get("closed", 0)
        if n:
            ranked.append((name, closed, n, closed / n))
    ranked.sort(key=lambda t: -t[3])
    if ranked:
        top = "، ".join(f"{GOV_AR.get(n, n)} ({c} من {t} تقرير مسكّر)" for n, c, t, _ in ranked[:3])
        answer = (f"آخر {days} يوم عبر {len(govs)} محافظة. الأكثر إغلاقاً: {top}. "
                  f"الأقل: {GOV_AR.get(ranked[-1][0], ranked[-1][0])} "
                  f"({ranked[-1][1]} من {ranked[-1][2]}).")
    else:
        answer = f"آخر {days} يوم عبر {len(govs)} محافظة — ما في تقارير طرق بالنافذة."
    return {"answer": answer, "days": days,
            "ranked_by_closed_share": [{"governorate": n, "closed": c, "reports": t,
                                        "closed_share": round(r, 3)} for n, c, t, r in ranked],
            "governorates": govs, "note": d.get("note"),
            "grain_note": ("`checkpoint_flow` is the road; `checkpoint_idf`/`_police`/"
                           "`_settlers`/`_inspection` are sightings and are never "
                           "added to it. The legacy `checkpoint_status` column mixes "
                           "the two and is kept for the record only.")}


GOV_AR = {"Hebron": "الخليل", "Nablus": "نابلس", "Ramallah": "رام الله", "Jenin": "جنين",
          "Tulkarm": "طولكرم", "Qalqilya": "قلقيلية", "Salfit": "سلفيت", "Bethlehem": "بيت لحم",
          "Jericho": "أريحا", "Tubas": "طوباس", "Jerusalem": "القدس", "North Gaza": "شمال غزة",
          "Gaza": "غزة", "Deir Al-Balah": "دير البلح", "Khan Yunis": "خان يونس", "Rafah": "رفح"}


def stream_info() -> dict:
    """How to subscribe to live changes, and whether the stream is alive."""
    d = api("/v2/stream/status")
    age = d.get("last_poll_age_seconds")
    head = (f"البث شغال — {d.get('watched_states', 0):,} حالة تحت المراقبة"
            + (f"، آخر فحص قبل {int(age)} ثانية" if age is not None else "") + "."
            if d.get("running") else "البث واقف — ما في تحديثات حية هالوقت.")
    return {"answer": head,
            "url": "/v2/stream",
            "protocol": "server-sent events",
            "emits": "changes in what the system will ASSERT, including a "
                     "reading decaying to 'unknown'",
            **d}


def can_i_travel(origin: str, destination: str) -> dict:
    """Route-level answer: can I get from A to B right now, and if not, how."""
    d = api("/v2/route/between", origin=origin, destination=destination, alternates=2)
    rs = d.get("routes") or []
    if not rs:
        return {"answer": f"ما قدرت أحسب طريق من {origin} لـ{destination}.", **d}
    best = rs[0]
    # `.get` with a fallback, not `[...]`: a new verdict must degrade to a
    # readable sentence, never a KeyError in the serving path.
    say = {"likely_open": "الطريق سالك على الأغلب",
           "slow": "الطريق سالك بس فيه ازمة",
           "blocked": "الطريق مسكّر",
           "unverified": "ما بقدر أأكد إنه الطريق سالك",
           "unknown": "ما في تقارير حديثة عن هالطريق"}.get(
        best["verdict"], "ما في تقارير حديثة عن هالطريق")
    cps = best.get("checkpoints") or []
    # THE AGE OF THE EVIDENCE, spoken (F056). "4 من 7 حواجز عليها تقارير حديثة"
    # was read aloud with the newest of those readings 80 minutes old; the
    # traveller heard a count and no clock.
    known_ages = [c["age_minutes"] for c in cps if c.get("age_minutes") is not None]
    freshest = min(known_ages) if known_ages else None
    fresh_note = f" أحدث قراءة {_age_ar(int(freshest))}." if freshest is not None else ""
    detail = ""
    if best["blocked_at"]:
        blk = next((c for c in cps if c.get("name") in best["blocked_at"]
                    and c.get("age_minutes") is not None), None)
        detail = (" — مسكّر عند " + "، ".join(best["blocked_at"][:2])
                  + (f" ({_age_ar(int(blk['age_minutes']))})" if blk else ""))
        alt = next((r for r in rs if r["verdict"] in ("likely_open", "slow")), None)
        if alt:
            # The verdict word in Arabic — the raw token ("likely_open") was
            # spoken inside the Arabic sentence.
            alt_say = {"likely_open": "سالك على الأغلب", "slow": "سالك بس فيه ازمة"}.get(
                alt["verdict"], "")
            detail += (f". بديل: {alt['duration_minutes']:.0f} دقيقة"
                       + (f" ({alt_say})" if alt_say else ""))

    # A closure just outside the corridor is not silence. Ein Siniya was closed
    # 85 minutes earlier while this tool said "passable, congested at Za'tara",
    # because its centroid sits further than CORRIDOR_METRES from the polyline —
    # and the only name the caller saw was a pseudo-checkpoint named after the
    # road segment ("من عين سينا لزعترة"). The closure is NOT promoted onto the
    # route: whether a checkpoint 500 m off the alignment is on somebody's
    # journey is their call. It is named, with its distance and age, in the
    # sentence a traveller hears.
    nm = best.get("near_misses") or []
    # An exit closure is already the stated REASON; naming it again as a
    # "nearby closure" reads as two closures.
    exit_ids = {x.get("name") for x in (best.get("exit_closures") or [])}
    blocking_nm = [m for m in nm if m.get("flow") == "closed" and m.get("name") not in exit_ids]
    near_note = ""
    if blocking_nm:
        w = blocking_nm[0]
        age = w.get("age_minutes")
        when = f" {_age_ar(int(age))}" if age is not None else ""
        others = len(blocking_nm) - 1
        extra = (f" و{others} إغلاقات قريبة ثانية" if others > 1
                 else " وإغلاق قريب ثاني" if others == 1 else "")
        near_note = (f" تنبيه: {w['name']} مسكّر{when} على بعد "
                     f"{w['off_route_m']} متر من هالطريق — يمكن ما يوقفك، "
                     f"بس اعرفه{extra}.")

    # WHERE THE VERDICT IS BLIND. A verdict about a road nobody watched half of
    # has to say so in the sentence that carries the verdict, not in a field the
    # caller may never read.
    # WHICH ROAD THIS IS, said out loud. The external pass asked for it directly:
    # a verdict a traveller cannot place is not actionable, and naming the
    # waypoints lets them judge the route themselves instead of trusting a word.
    waypoints = [w["name"] for w in (best.get("passes") or [])][:5]
    pass_note = (f" يمر عبر: {'، '.join(waypoints)}." if waypoints else "")

    cov = best.get("coverage") or {}
    cover_note = ""
    if cov.get("longest_gap_km") and cov.get("coverage_fraction", 1.0) < 0.8:
        cover_note = (f" ما في حاجز مسجّل على {cov['longest_gap_km']:.0f} كيلو من "
                      f"هالطريق ({cov['longest_gap_from_km']:.0f} إلى "
                      f"{cov['longest_gap_to_km']:.0f} كيلو)، فهالمسافة بلا تحقّق.")

    # WHY IT IS UNVERIFIED, SAID FIRST. The reasons lived in `summary`, which no
    # spoken answer used, so "ما بقدر أأكد" arrived with no cause attached.
    #
    # WHATEVER THE VERDICT. The exit closures were removed from the near-miss
    # warning below and then spoken only for `unverified`, so a `slow`, `blocked`
    # or `unknown` route never named the closed road out of town — the audit's
    # 15:27 Za'tara / Ein Siniya case, reintroduced (F011).
    doubt_note = ""
    doubts = best.get("doubts") or []
    exits = [x for x in doubts if x.get("kind") == "exit_closure"] or [
        dict(x, end="origin" if (x.get("along") or 0) <= 0.5 else "destination")
        for x in (best.get("exit_closures") or [])]
    why = []
    if exits:
        why.append("إغلاق " + "، و".join(
            f"عند {x['name']} على طريق "
            + (f"الخروج من {origin}" if x["end"] == "origin" else f"الدخول لـ{destination}")
            + f" ({int(x['off_route_m'])} متر عن المسار"
            + (f"، {_age_ar(int(x['age_minutes']))}" if x.get("age_minutes") is not None else "")
            + ")" for x in exits[:3]))
    blind = next((x for x in doubts if x.get("kind") == "blind_stretch"), None)
    if blind:
        why.append(f"{share_words(blind.get('share'))[0]} بلا حاجز متابَع")
    low = next((x for x in doubts if x.get("kind") == "low_coverage"), None)
    if low and low.get("fraction") is not None:
        why.append(f"بس {round(100 * low['fraction'])}% من الطريق عليه حاجز فيه تقرير حديث")
    if why:
        doubt_note = ((" السبب: " if best.get("verdict") == "unverified" else " انتبه: ")
                      + "؛ و".join(why) + " — تأكد قبل ما تطلع.")

    return {"answer": f"{say}{detail}.{doubt_note} "
                      f"{best['known']} من {best['checkpoints_on_route']} حواجز عليها تقارير حديثة."
                      f"{fresh_note}{pass_note}{cover_note}{near_note}",
            "verdict": best["verdict"],
            "freshest_reading_minutes": freshest,
            "duration_minutes": best["duration_minutes"],
            "distance_km": best["distance_km"],
            "blocked_at": best["blocked_at"],
            "congested_at": best["slow_at"],
            "not_reported_recently": best["unreported"],
            "cautions": best["cautions"],
            # HOW MUCH OF THE DRIVE THE VERDICT SPEAKS FOR, and which towns it
            # goes through. See resolve/corridor.py:_corridor_for. "2 of 8
            # checkpoints have recent reports" cannot tell a traveller that the
            # first 27 of 53 km are watched by nothing — and that is the reading
            # an external pass flagged as the most serious one left.
            "coverage": best.get("coverage") or {},
            "passes": best.get("passes") or [],
            # The ORDERED list the tool's own description promises, in travel
            # order, each with its flow and AGE. It was in
            # resolve/corridor.py:Corridor.checkpoints all along and the
            # projection here dropped it, so the only names a caller ever saw
            # were `unreported` plus the worst one or two in blocks/slow — which
            # made both an omission and a stale reading invisible.
            "checkpoints": [{"name": c["name"], "name_en": c.get("name_en"),
                             "flow": c["flow"], "age_minutes": c.get("age_minutes"),
                             "independent_sources": c.get("independent_sources"),
                             "off_route_m": c.get("off_route_m"),
                             "position": round(c["along"], 3),
                             "presence": c.get("presence") or []}
                            for c in (best.get("checkpoints") or [])],
            "oldest_known_minutes": best.get("oldest_known_minutes"),
            "near_misses": nm,
            # Closures on the way OUT of the origin or INTO the destination,
            # in full: the audit's finding was that these decided the journey
            # and the corridor could not see them.
            "exit_closures": best.get("exit_closures") or [],
            "doubts": best.get("doubts") or [],
            # Each alternate carries its OWN coverage: the primary here is blind
            # for 26.8 km and the alternate for 52 km, so "how much is known"
            # differs per route and collapsing it to one number would hide the
            # better-watched option — the same reason ranking by time rather than
            # by our confidence is deliberate.
            "routes": [{k: r.get(k) for k in ("verdict", "duration_minutes", "distance_km",
                                              "known", "checkpoints_on_route",
                                              "blocked_at", "unreported", "coverage",
                                              "exit_closures", "doubts")}
                       for r in rs],
            "caveat": "one confirmed closure blocks a route; unreported checkpoints "
                      "never block and are always named. `checkpoints` is in travel "
                      "order with each reading's age; `near_misses` are closures and "
                      "congestion just outside the corridor we scored."}


def correlate(a: str | None = None, b: str | None = None,
              concept: str | None = None, search: str | None = None,
              place_id: int | None = None, max_lag: int = 0,
              allow_same_concept: bool = False) -> dict:
    """Do two series move together — or why that is the wrong question.

    Three modes in one tool, because an agent almost never knows the
    indicator string it needs:
      no arguments        → the concept taxonomy
      `search` / `concept`→ find the series
      `a` and `b`         → the correlation, or a REFUSAL with reasons

    The refusals are the valuable part. Correlating two cumulative tolls
    returns ~1.0 and measures the passage of time; the tool declines rather
    than handing an agent a number it will quote.
    """
    if a and b:
        # The route refuses more than a year of lags (audit F077); clamped here
        # so an agent's large guess scans a year instead of failing the call.
        d = api("/v2/databank/correlate", a=a, b=b, place_id=place_id,
                max_lag=max(0, min(int(max_lag or 0), 366)),
                allow_same_concept="true" if allow_same_concept else "false")
        if d.get("refused"):
            from serve.correlate import reason_ar
            return {"answer": "ما بحسب الارتباط هون: " + "؛ و".join(
                        reason_ar(r) for r in d["reasons"]) + ".",
                    "refused": True, "reasons": d["reasons"],
                    "caveat": "This is a hard refusal, not a warning. Do not "
                              "report a coefficient for this pair."}
        # `answer` is Arabic to be read aloud (INSTRUCTIONS); the English
        # sentence belongs to answer_en (F505).
        rho = d.get("rho")
        strength = ("قوي" if rho is not None and abs(rho) >= 0.7 else
                    "متوسط" if rho is not None and abs(rho) >= 0.4 else "ضعيف")
        sign = "" if rho is None else (" بنفس الاتجاه" if rho > 0 else " بعكس الاتجاه")
        return {"answer": (f"الارتباط بين {a} و{b} {strength}{sign}: ρ={rho} على "
                           f"{d['n']} نقطة"
                           + (f"، بتأخير {d['lag_days']} يوم" if d.get("lag_days") else "")
                           + f"، فاصل الثقة 95%: {d['ci95']}. ارتباط مش سببية."),
                **d}
    if search or concept:
        d = api("/v2/databank/indicators", q_=search, concept=concept, limit=25)
        inds = d["indicators"]
        what = search or concept
        if not inds:
            return {"answer": f"ما في ولا سلسلة مطابقة لـ«{what}» — جرّب كلمة ثانية أو `concept`.",
                    "indicators": [], "query": what}
        return {"answer": (f"{len(inds)} سلسلة مطابقة لـ«{what}»: "
                           + "، ".join(i["indicator"] for i in inds[:6]) + "."),
                "indicators": inds, "query": what}
    d = api("/v2/databank/concepts")
    top = [c for c in d["concepts"] if c["rows_served"]][:8]
    return {"answer": "أكبر المفاهيم في بنك المعلومات: " + "، ".join(
                f"{c['name_ar'] or c['name_en']} ({int(c['rows_served']):,})"
                for c in top),
            "concepts": d["concepts"],
            "how_to_use": "Pass `search` or `concept` to find indicator "
                          "strings, then `a` and `b` to correlate them."}


def what_correlates_with(indicator: str, place: str | None = None,
                         candidates: int = 40,
                         allow_same_concept: bool = False) -> dict:
    """Scan everything held for series that move with this one.

    `correlate` needs both sides named, so it could only ever confirm a pair
    somebody already suspected. This searches.
    """
    place_id = None
    if place:
        g = api("/v2/geo/resolve", q=place)
        if not g.get("found"):
            return {"answer": f"ما عرفت وين {place}.", "found": False}
        place_id = g.get("place_id")
    d = api("/v2/databank/correlate/scan", a=indicator, place_id=place_id,
            candidates=candidates,
            allow_same_concept="true" if allow_same_concept else "false")
    from serve.correlate import reason_ar, skip_ar
    if d.get("refused"):
        return {"answer": "ما قدرت أفحص: " + "؛ و".join(reason_ar(r) for r in d["reasons"]) + ".",
                **d}
    ms = d["matches"]
    if not ms:
        # The reasons ARE the answer here. "Nothing correlates" and "nothing
        # was comparable enough to test" are different findings and the second
        # is the common one.
        return {"answer": ("ما في ولا سلسلة قابلة للمقارنة مع هاي، فما انعمل ولا اختبار. الأسباب: "
                           + "، ".join(f"{v} {skip_ar(k)}" for k, v in d["skipped"].items()) + "."),
                **d}
    top = ms[0]
    return {"answer": (f"من {d['tested']} سلسلة مفحوصة، أقواها: "
                       f"{top['indicator']} (ρ={top['rho']}, n={top['n']}). "
                       f"هاي فرضيات للفحص، مش نتائج."),
            **d}


SERIES_POINTS = 60      # newest points a series carries in a tool reply


def compare(indicators: str, place: str | None = None) -> dict:
    """Two to six series side by side, each keeping its own unit.

    Reachable by a frontend since P5.2 and by an agent only now, which is the
    parity rule quietly broken: one place to read everything meant one place
    unless you are an agent.
    """
    place_id = None
    if place:
        g = api("/v2/geo/resolve", q=place)
        if g.get("found"):
            place_id = g.get("place_id")
    d = api("/v2/databank/compare", indicators=indicators, place_id=place_id)
    ss = d.get("series", [])
    # A MODEL READS THIS, NOT A CHART. Thousands of points per series is the
    # route's job (a frontend draws them); the tool keeps the newest
    # SERIES_POINTS per series and says how many it left out, with first/last
    # dates so the span is not lost with the rows.
    for s_ in ss:
        pts = s_.get("points") or []
        if pts:
            s_["first"], s_["last"] = pts[0].get("at"), pts[-1].get("at")
        if len(pts) > SERIES_POINTS:
            s_["points_omitted"] = len(pts) - SERIES_POINTS
            s_["points"] = pts[-SERIES_POINTS:]
    bits = [f"{s['indicator']} ({s['n']} نقطة، {s.get('canonical_unit') or 'بدون وحدة'}"
            + (f"، آخرها {str(s.get('last'))[:10]}" if s.get("last") else "")
            + (f"، على مستوى {s['place_used']['name']}" if s.get("place_used") else "") + ")"
            for s in ss]
    ov = d.get("overlap") or {}
    return {"answer": ("مقارنة: " + "، ".join(bits) +
                       (f". الفترة المشتركة {ov.get('from')} → {ov.get('to')} "
                        f"({ov.get('n')} نقطة)." if ov.get("n") else
                        ". ما في فترة مشتركة بين السلاسل.")),
            **d}


def place_profile(place: str, days: int = 30) -> dict:
    """Everything both tiers hold about one place, in a single call.

    The cross-tier join is the databank's stated premise, and reaching it took
    four separate calls plus knowing that the town and the checkpoint of the
    same name are different rows. An agent asked "tell me about Huwara" should
    not have to know that.
    """
    town = api("/v2/geo/resolve", q=place)
    cp = api("/v2/geo/resolve", q=place, state_kind="checkpoint_status")
    if not town.get("found") and not cp.get("found"):
        return {"answer": f"ما عرفت وين {place}.", "found": False}
    anchor = cp if cp.get("found") else town

    out: dict[str, Any] = {"place": anchor.get("name"),
                           "place_en": anchor.get("name_en"),
                           "place_id": anchor.get("place_id"),
                           "kind": anchor.get("kind"),
                           "resolved": {"as_town": town.get("found"),
                                        "as_checkpoint": cp.get("found")}}
    said = []

    # A section that FAILED is said as a failure. Every except here used to
    # leave the section empty, and an empty section read as "no recent
    # information" (F060).
    errors: dict[str, str] = {}
    if cp.get("found"):
        try:
            # By the RESOLVED checkpoint, not the caller's text: the two
            # resolvers can disagree, and the status call re-resolved "Huwara"
            # on its own (F010). Spoken with its age.
            live = api("/v2/checkpoints/status", name=cp.get("name") or place, direction="both")
            if live.get("found") and (live.get("match") or {}).get("resolved_to") == cp.get("name"):
                out["checkpoint_now"] = {"flow": live.get("flow"),
                                         "age_minutes": live.get("age_minutes"),
                                         "present": live.get("present")}
                said.append(f"الحاجز {FLOW_AR.get(live.get('flow'), live.get('flow'))} "
                            f"({_age_ar(live.get('age_minutes'))})")
        except Exception as e:                              # noqa: BLE001
            errors["checkpoint"] = str(e)[:200]

    for label, call in (("history", lambda: api("/v2/history/place",
                                                place_id=anchor["place_id"],
                                                days=days)),
                        # The flow axis, not the legacy mixed kind that carries
                        # idf/police in the same column as open (F058).
                        ("pattern", lambda: api("/v2/patterns/place",
                                                place_id=anchor["place_id"],
                                                state_kind="checkpoint_flow",
                                                days=60))):
        try:
            out[label] = call()
        except Exception as e:                              # noqa: BLE001
            out[label] = None
            errors[label] = str(e)[:200]

    if town.get("found"):
        # /v2/incidents/recent caps hours at 168; days*24 above that was a 422
        # that the except turned into "no incidents" for every days > 7 (F059).
        inc_days = min(days, 7)
        out["incident_days"] = inc_days
        try:
            inc = api("/v2/incidents/recent", lat=town["lat"], lon=town["lon"],
                      hours=inc_days * 24, radius_km=10, limit=20)
            out["incidents"] = inc.get("incidents", [])
            if out["incidents"]:
                said.append(f"{len(out['incidents'])} حدث بآخر {inc_days} أيام")
        except Exception as e:                              # noqa: BLE001
            out["incidents"] = []
            errors["incidents"] = str(e)[:200]
    out["errors"] = errors

    days_with = len((out.get("history") or {}).get("series") or [])
    if days_with:
        said.append(f"{days_with} يوم فيها تقارير")
    out["answer"] = (f"{anchor.get('name')}: " + "، ".join(said) + "."
                     if said else
                     f"{anchor.get('name')}: ما في معلومات حديثة عنها.")
    if errors:
        out["answer"] += (f" ما قدرت أقرأ: {'، '.join(errors)} — هاد عطل، "
                          "مش غياب معلومات.")
    out["caveat"] = ("A town and the checkpoint named after it are different "
                     "rows; `resolved` says which of the two this answer "
                     "actually covers.")
    return out


def search(text: str, hours: int = 168, limit: int = 8, area: str | None = None,
           kind: str = "all") -> dict:
    """Free-text search across recent messages — the way people actually ask.

    Every other tool needs a place or an indicator string. This one takes the
    words somebody used.

    It used to fetch the last 100 messages and substring-match them in Python,
    so "قلنديا" over 24 hours returned zero hits while 49 matching messages sat
    in the claim store — the road-condition channel alone has 27,588 of them,
    none of them recent enough to reach a 100-message window. The window is now
    the caller's, and the match happens in the database.
    """
    # The façade forwarded place/kind and this dropped them, so
    # news(text=…, place=…, kind="roads") searched West-Bank-wide including the
    # road tables; and the schema's declared default was 8 while this said 20
    # (F047). Same filter as latest_news; same REST caps (F054). The default
    # here is `all`: the caller typed the words, and a road table that carries
    # them is a hit — measured: every long message naming قلنديا in a day is
    # a bulletin, the channel one-liners being under the 30-char floor.
    if kind not in ("news", "roads", "all"):
        raise TypeError("kind must be news, roads or all")
    limit = _clamp(limit, 1, 25, 8)
    # The road bulletin names every checkpoint every 15 minutes, so a search
    # for a checkpoint name is bulletins all the way down: fetch the full page
    # when they are to be filtered out, or nothing is left after the filter.
    d = api("/v2/news/latest", text=text.strip(), area=area, kind=kind,
            hours=_clamp(hours, 1, 720, 168), limit=min(limit * 3, 100))
    items = d.get("items", [])
    if kind == "news":
        items = [i for i in items if not str(i.get("text", "")).startswith(ROAD_BULLETIN)]
    elif kind == "roads":
        items = [i for i in items if str(i.get("text", "")).startswith(ROAD_BULLETIN)]
    hits = _dedupe_messages(items)[:limit]
    if not hits:
        return {"answer": f"ما لقيت ولا رسالة فيها «{text}» بالمخزون الحالي.",
                "count": 0, "items": [],
                "caveat": "searches the most recent ingested messages only, "
                          "not the whole archive"}
    return {"answer": f"{len(hits)} رسالة فيها «{text}»" + (f" عن {area}" if area else "")
                      + f". آخرها: {hits[0]['text'][:160]}",
            "count": len(hits), "items": hits, "kind": kind, "area": area,
            "caveat": "matches the words as typed — a different spelling of "
                      "the same place will not match"}


def trend(indicator: str, days: int = 90, place: str | None = None) -> dict:
    """Is this series above or below its own recent baseline?

    A model handed 90 raw points reduces them itself, and does it differently
    each time. The comparison is stated once, here.
    """
    place_id = None
    if place:
        g = api("/v2/geo/resolve", q=place)
        if g.get("found"):
            place_id = g.get("place_id")
    # `days` was declared, forwarded and never applied: a "30-day" trend was
    # computed over the whole history (F061/F305). The window is the caller's.
    from datetime import date, timedelta
    days = _clamp(days, 7, 3650, 90)
    frm = (date.today() - timedelta(days=days)).isoformat()
    d = api("/v2/databank/compare", indicators=f"{indicator},{indicator}",
            place_id=place_id, frm=frm)
    pts = [p for p in (d.get("series") or [{}])[0].get("points", [])
           if p.get("value") is not None]
    window_note = ""
    if len(pts) < 6:
        # An annual series holds one point in 90 days. Rather than answer
        # "not enough points" for every slow series, widen to the whole
        # history and SAY so — the sentence names the window it used.
        n_win = len(pts)
        d = api("/v2/databank/compare", indicators=f"{indicator},{indicator}",
                place_id=place_id)
        pts = [p for p in (d.get("series") or [{}])[0].get("points", [])
               if p.get("value") is not None]
        window_note = (f" (آخر {days} يوم فيها {n_win} نقطة بس، فالمقارنة على كامل السلسلة)")
        frm, days = None, None
    used = ((d.get("series") or [{}])[0] or {}).get("place_used")
    at_ar = ((f" (الأرقام محفوظة على مستوى "
              + ("محافظة " if used.get("kind") == "governorate" else "")
              + f"{used['name']}، مش {place} لحالها)") if used else "")
    if len(pts) < 6:
        where = f" لـ{place}" if place else ""
        return {"answer": f"ما في نقاط كفاية بـ{indicator}{where} لأقارن باتجاه.",
                "n": len(pts), "window_days": days, "from": frm, "place_used": used}

    # Most indicators here are a BREAKDOWN, not a line: refugees.cross_border
    # is 1,157 points over 16 dates — seventy-odd rows per date, split by
    # asylum country. Averaging the last three of those against the median of
    # the rest produced "18,338% higher", which is not a wrong trend, it is a
    # trend computed over something that has none. Repeated dates are the tell.
    dates = [p["at"] for p in pts]
    if len(set(dates)) < len(dates):
        return {"answer": (f"{indicator} مش سلسلة واحدة — {len(pts)} نقطة على "
                           f"{len(set(dates))} تاريخ، يعني تقسيمة مش خط زمني. "
                           f"حدد `place` أو استعمل `databank` لتشوف التقسيمة."),
                "refused": True, "n": len(pts), "distinct_dates": len(set(dates)),
                "reason": ("multiple values share each date, so this indicator "
                           "is a breakdown (by place, sex, age or category). A "
                           "trend needs one value per date — narrow it with "
                           "`place`, or read the breakdown with `databank`."),
                "caveat": "no number is returned on purpose; a trend over a "
                          "breakdown is arithmetic without a subject."}
    vals = [float(p["value"]) for p in pts]
    recent, base = vals[-3:], vals[:-3]
    med = sorted(base)[len(base) // 2]
    avg = sum(recent) / len(recent)
    if med == 0:
        change = None
    else:
        change = round((avg - med) / abs(med) * 100)
    word = ("ثابت" if change is None or abs(change) < 10
            else ("أعلى" if change > 0 else "أقل"))
    # The headline used to assert a direction with no date on it. The partner's
    # QA pass found series ending in December 2021 still being described as
    # "the last three readings, flat" — true, and nine months stale, which is
    # the part that changes what a reader does with it. The payload carried
    # `last` all along; the sentence now says it too.
    last_at = str(pts[-1]["at"])[:10]
    try:
        from datetime import datetime, timezone as _tz
        _d = datetime.fromisoformat(str(pts[-1]["at"]).replace("Z", "+00:00"))
        if _d.tzinfo is None:
            _d = _d.replace(tzinfo=_tz.utc)
        age_days = (datetime.now(_tz.utc) - _d).days
    except Exception:                                            # noqa: BLE001
        age_days = None
    freshest = (f" آخر قراءة بتاريخ {last_at}"
                + (f"، قبل {age_days} يوم" if age_days is not None and age_days > 0 else ""))
    if age_days is not None and age_days > 45:
        freshest += " — السلسلة واقفة، فخُد الاتجاه بحدود عمره"
    return {"answer": (f"{indicator}" + (f" خلال آخر {days} يوم" if days else "")
                       + f": آخر {len(recent)} قراءة {word}"
                       + (f" بنسبة {abs(change)}% عن وسيط الفترة"
                          if change is not None else "")
                       + f" ({round(avg, 2)} مقابل {round(med, 2)})" + window_note + at_ar + "."
                       + freshest + "."),
            "indicator": indicator, "n": len(pts), "last_age_days": age_days,
            "place_used": used,
            "window_days": days, "from": frm,
            "window_widened": bool(window_note),
            "recent_mean": round(avg, 4), "baseline_median": round(med, 4),
            "change_pct": change,
            "first": pts[0]["at"], "last": pts[-1]["at"],
            "caveat": "compares the last three readings to the median of the "
                      "rest. Points are reports, not evenly spaced time — a "
                      "gap in reporting looks the same as a gap in events."}


def licenses(source: str | None = None) -> dict:
    """Who owns the data, and what each licence obliges.

    Exists because the single most consequential thing an agent can get wrong
    about this databank is telling someone they may sell a row they may only
    share. `commercial_use` alone was never the whole answer: ODbL and
    CC-BY-SA permit commercial use AND require a derived database to carry
    the same licence, and 6,562 rows are in that position.
    """
    d = api("/v2/databank/licenses")
    rows = d["licenses"]
    if source:
        rows = [r for r in rows
                if source.lower() in (r["source_key"] or "").lower()
                or source.lower() in (r["source_name"] or "").lower()]
        if not rows:
            return {"answer": f"ما في مصدر اسمه {source} بين المصادر المخدومة.",
                    "licenses": [], "source": source}
        # A narrowed payload used to carry the whole-databank sentence, so the
        # answer never said which source it was about (Fawwaz's test).
        bits = []
        for r in rows[:3]:
            sell = ("يجوز بيعها" if r["commercial_use"] else "ما بتنباع")
            share = "، وأي قاعدة مشتقة لازم تحمل نفس الترخيص" if r["share_alike"] else ""
            red = {"ask": "إعادة النشر بإذن", "yes": "مسموح إعادة نشرها",
                   "no": "ممنوع إعادة نشرها"}.get(r.get("redistribution"), "")
            read = (f"الشروط مقروءة بتاريخ {r['verified_on']}" if r.get("verified_on")
                    else "ما حدا قرأ شروط الناشر")
            bits.append(f"{r['source_name']}: {r.get('license_spdx') or 'بلا ترخيص معلن'}، {int(r.get('rows_served') or 0):,} صف، "
                        f"{sell}{share}" + (f"، {red}" if red else "") + f"؛ {read}")
        return {"answer": "؛ ".join(bits) + ".", "licenses": rows, "source": source,
                "caveat": "A null verified_on means nobody has read that "
                          "publisher's terms at the publisher."}
    t = d["tiers"]
    # A share-alike licence that is ALSO non-commercial (WHO's
    # CC-BY-NC-SA-3.0-IGO) is not in any commercial tier, so listing it beside
    # the tier counts would suggest it is sellable-with-strings when it is not
    # sellable at all. The copyleft flag and the commercial grant are separate
    # facts and only their intersection belongs here.
    sa = [r for r in rows if r["share_alike"] and r["commercial_use"]]
    # Likewise: an unread licence only endangers something if we are SELLING
    # under it. The rest are quarantined already, and mixing the two turns a
    # one-source problem into a seven-source shrug.
    unread = [r["source_key"] for r in rows
              if not r["verified_on"] and r["commercial_use"]]
    unread_nc = [r["source_key"] for r in rows
                 if not r["verified_on"] and not r["commercial_use"]]
    answer = (f"{t['open']:,} صفاً قابلاً لإعادة النشر مع الإسناد، "
              f"{t['commercial_permissive']:,} قابلاً للبيع بلا التزام إضافي، "
              f"و{t['commercial_sharealike']:,} صفاً بترخيص المشاركة بالمثل "
              f"(ODbL / CC-BY-SA): يجوز بيعها، لكن أي قاعدة بيانات مشتقة "
              f"منها يجب أن تحمل الترخيص نفسه.")
    if sa:
        answer += (" المصادر ذات المشاركة بالمثل: "
                   + "، ".join(r["source_name"] for r in sa) + ".")
    return {"answer": answer, "tiers": t, "licenses": rows,
            "share_alike_sources": [r["source_key"] for r in sa],
            "terms_never_read_and_sold": unread,
            "terms_never_read_not_sold": unread_nc,
            "caveat": "A derived DATABASE built on a share_alike row inherits "
                      "that licence. A null verified_on means nobody has read "
                      "that publisher's terms at the publisher.",
            "permissions_pending": d["permissions_pending"]}


def licence_tools() -> dict:
    """What each public tool may hand a commercial partner, and in what form.

    `licenses` answers "who owns this row". This answers the question a
    consumer has to ask BEFORE that one: of the things this server will tell
    me, which may I carry away, and whole or as a citation?
    """
    d = api("/v2/licence/tools")
    counts = d.get("partner_tier_counts") or {}
    by_tier: dict[str, list[str]] = {}
    for t in d.get("tools", []):
        by_tier.setdefault(t["partner_tier"], []).append(t["tool"])
    answer = (f"من أصل {d.get('public_tools')} أداة عامة، {d.get('graded')} "
              f"مصنّفة: ")
    said = []
    if counts.get("full"):
        said.append(f"{counts['full']} أداة يجوز نقل مخرجاتها كاملة "
                    f"(استنتاجاتنا نحن، لا نصوص غيرنا)")
    if counts.get("excerpt"):
        said.append(f"{counts['excerpt']} أداة تُعطي مقتطفاً فقط — نصوص القنوات "
                    f"ملك أصحابها ولا نملك حق إعادة نشرها")
    if counts.get("filtered"):
        said.append(f"{counts['filtered']} أداة على بنك المعلومات، كل صف "
                    f"بترخيصه")
    if counts.get("cited_fact_only"):
        said.append(f"{counts['cited_fact_only']} أداة تُنقل كواقعة مُسندة فقط")
    answer += "، ".join(said) + "."
    if d.get("ungraded"):
        answer += (f" تنبيه: {len(d['ungraded'])} أداة بلا تصنيف بعد — "
                   f"لا تُعاد نشر مخرجاتها.")
    return {"answer": answer, **d, "tools_by_tier": by_tier,
            "caveat": "A grade here says what you may REDISTRIBUTE, not what "
                      "you may read. Everything on this server is readable; the "
                      "cut is on carrying it away."}


def databank(category: str | None = None, indicator: str | None = None,
             as_of: str | None = None, limit: int = 10) -> dict:
    """The historical databank: 200,000+ observations across 20 categories
    (prisoners, demolitions, food prices, funding, the martyrs roster…),
    each row carrying its source's license and attribution. `as_of`
    reconstructs what the archive served on a past day."""
    # `indicator` alone used to return the category overview, silently
    # (Fawwaz's test: {indicator: "prisoners.child"}). The category is looked
    # up from the indicator; `as_of` alone is said to need a category.
    ignored: dict[str, str] = {}
    if not category and indicator:
        where = api("/v2/databank/where", indicator=indicator).get("categories") or []
        if where:
            category = where[0]["category"]
        else:
            return {"answer": f"ما في سجلات لمؤشر اسمه {indicator} — دوّر عليه بـ correlate search.",
                    "indicator": indicator, "count": 0, "items": [], "category": None}
    if not category:
        if as_of:
            ignored["as_of"] = ("as_of reconstructs one category's rows on a past "
                                "day; pass a category with it. The overview is today's.")
        d = api("/v2/databank/categories")
        cats: dict[str, int] = {}
        for ds in d["datasets"]:
            cats[ds["category"]] = cats.get(ds["category"], 0) + ds["rows"]
        top = sorted(cats.items(), key=lambda kv: -kv[1])
        # The same six in both languages, and datasets called datasets: the
        # Arabic said "32 مصدراً" over 32 datasets-with-rows out of 41
        # registered (Fawwaz's test).
        answer = ("بنك المعلومات التاريخي — أكبر الفئات: " +
                  "، ".join(f"{c} ({n:,})" for c, n in top[:6]) +
                  f". المجموع {sum(cats.values()):,} سجلاً في {len(cats)} فئة، من "
                  f"{d.get('datasets_with_rows') or len(d['datasets'])} مجموعة بيانات فيها سجلات"
                  + (f" (من أصل {d['datasets_registered']} مسجّلة)" if d.get("datasets_registered") else "")
                  + ".")
        if ignored:
            answer += " as_of بيشتغل مع فئة بس — هاد الملخص تبع اليوم."
        return {"answer": answer, "categories": cats,
                "datasets": d["datasets"],
                "datasets_with_rows": d.get("datasets_with_rows"),
                "datasets_registered": d.get("datasets_registered"),
                "ignored": ignored or None,
                "list_note": d.get("list_note")}
    # The one place a caller's string becomes part of a URL path rather than a
    # query value. Named categories only — no slashes, no dots, no query.
    if not re.fullmatch(r"[a-z0-9_]{1,40}", category):
        return {"answer": f"ما في فئة اسمها {category}.",
                "error": "category must be a name from /v2/databank/categories",
                "count": 0, "items": []}
    d = api(f"/v2/databank/{category}", indicator=indicator,
            as_of=as_of, limit=limit)
    when = f" كما كانت بتاريخ {as_of}" if as_of else ""
    items = d.get("items") or []
    if not items:
        return {"answer": f"لا سجلات مطابقة في {category}{when}.", **d}
    # THE HEADLINE IS THE LATEST FIGURE, NOT A ROW COUNT. "5 rows from
    # demolitions" told a reader nothing; the newest value per indicator, its
    # date, its place and who published it is what they asked for.
    newest: dict[str, dict] = {}
    for it in items:
        k = it.get("indicator") or "?"
        if k not in newest or str(it.get("occurred_at") or "") > str(newest[k].get("occurred_at") or ""):
            newest[k] = it
    # The span is the SERIES', read from the indicator registry, not the page's:
    # the 10 newest demolition rows are all 2026 while the series runs
    # 2009→2026 (F062). One registry lookup per named indicator, at most three.
    series_span: dict[str, dict] = {}
    for k in list(newest)[:3]:
        try:
            reg = api("/v2/databank/indicators", q_=k, limit=10)
            row = next((i for i in reg.get("indicators", []) if i.get("indicator") == k), None)
        except Exception:                                    # noqa: BLE001
            row = None
        if row:
            series_span[k] = {"from": str(row.get("from_date") or row.get("from") or "")[:10],
                              "to": str(row.get("to_date") or row.get("to") or "")[:10],
                              "rows": row.get("rows_served") or row.get("n")}
    lo = sorted(v["from"] for v in series_span.values() if v.get("from"))
    hi = sorted(v["to"] for v in series_span.values() if v.get("to"))
    span = f" السلسلة من {lo[0][:4]} إلى {hi[-1][:4]}." if lo and hi else ""
    bits = []
    for k, it in list(newest.items())[:3]:
        val = it.get("value_num") if it.get("value_num") is not None else it.get("value_text")
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        unit = f" {it['unit']}" if it.get("unit") else ""
        prec = it.get("occurred_precision")
        when_ = str(it.get("occurred_at") or "")[:4 if prec == "year" else 10]
        partial = " (سنة ناقصة)" if (it.get("attrs") or {}).get("partial_year") else ""
        where = f"، {it['place_ar']}" if it.get("place_ar") else ""
        bits.append(f"{k}: {val:,}{unit} في {when_}{partial}{where}" if isinstance(val, (int, float))
                    else f"{k}: {val} في {when_}{where}")
    src = "؛ ".join(d.get("attribution") or [])[:120].rstrip(". ")
    answer = (f"{category}{when} — آخر الأرقام: " + "؛ ".join(bits) + "."
              + (f" المصدر: {src}." if src else "") + span
              + f" (أحدث {d['count']} سجلات معروضة" + (" من أصل أكثر" if d["count"] >= limit else "") + ")")
    return {"answer": answer, "latest_by_indicator": list(newest.values())[:3],
            "series_span": series_span, **d}


def data_gaps() -> dict:
    """The gap radar: where the record thins — stalled series, dead
    upstreams, timeline holes, failing supply lines — measured nightly on
    the data's own dates, never on file timestamps."""
    d = api("/v2/databank/radar")
    c = d["counts"]
    top = [g for g in d["gaps"] if g["severity"] >= 3][:5]
    answer = (f"رادار الفجوات: من أصل {c['datasets']} سلسلة بيانات — "
              f"{c['fresh']} حديثة، {c['late']} متأخرة، "
              f"{c['stalled']} متوقفة، {c['dead_upstream']} مصدرها توقف. ")
    if top:
        answer += "أهم الفجوات: " + "؛ ".join(
            f"{g['subject']} ({g['measure'][:60]})" for g in top)
    else:
        answer += "لا فجوات حرجة اليوم."
    scout = {}
    try:
        s = api("/v2/databank/scout")
        scout = {"swept_at": s["swept_at"],
                 "top_candidates": s["candidates"][:8]}
        if s["candidates"]:
            answer += (f" الكشّاف وجد {len(s['candidates'])} مصدراً مرشحاً "
                       f"لسدّ الفجوات، أبرزها: "
                       + "؛ ".join(x["title"][:50]
                                   for x in s["candidates"][:3]) + ".")
    except Exception:
        pass                              # radar answers even if scout hasn't swept
    return {"answer": answer, "counts": c, "gaps": d["gaps"],
            "measured_at": d["measured_at"], "scout": scout}


def about(section: str = "overview") -> dict:
    """One call to learn what this system is, holds, cannot answer, and whether it
    is alive — the first call a new client should make (P0-A, 2026-09-24).

    `overview` is a REDUCTION of `coverage`, `data_gaps`, `stream_info` and the
    databank totals: counts and the top gaps, not every field. The full payload
    of each is one `section` away, so the first call a stranger makes is small
    and the detail is reachable rather than mandatory.
    """
    # A section IS another tool's payload, so it carries that tool's English:
    # the outer transport adds `about`'s renderer only when none is present.
    from serve.mcp_en import add_english
    if section in ("sources", "fields"):
        return add_english("coverage", coverage())
    if section == "gaps":
        return add_english("data_gaps", data_gaps())
    if section == "stream":
        return add_english("stream_info", stream_info())
    if section != "overview":
        raise TypeError("section must be one of overview, sources, fields, gaps, stream")
    cov = coverage()
    # Optional sections must not sink the first call a stranger makes: each
    # is one bounded call and `partial` names what was skipped (F268).
    partial: list[str] = []

    def _section(name, fn, default):
        try:
            return fn()
        except Exception:                                    # noqa: BLE001
            partial.append(name)
            return default
    gaps = _section("gaps", data_gaps, {})
    st = _section("stream", stream_info, {})
    cats = _section("categories", lambda: api("/v2/databank/categories"), {})
    # "359 حاجز متابَع" counted every place row of kind checkpoint, merged
    # duplicates included, while checkpoints() said 272 (F269): the servable
    # set, and how many of those have a current reading, are the two facts.
    cs = _section("checkpoints", checkpoints_summary, {})
    tracked = cs.get("tracked")
    with_reading = (round(tracked * cs["known_fraction"])
                    if tracked is not None and cs.get("known_fraction") is not None else None)
    # The route lists DATASETS (category, dataset, rows…); categories are the
    # sum over them, which is also how the `databank` tool counts.
    cat_counts: dict[str, int] = {}
    for d in cats.get("datasets") or []:
        if isinstance(d, dict) and d.get("category"):
            cat_counts[d["category"]] = cat_counts.get(d["category"], 0) + int(d.get("rows") or 0)
    rows = sum(cat_counts.values())
    fields = cov.get("fields") or []
    live = sorted(f["state_kind"] for f in fields if f.get("coverage_state") == "live")
    failing = [g for g in (gaps.get("gaps") or []) if g.get("kind") == "fetch"]
    top = [{"subject": g.get("subject"), "measure": g.get("measure"),
            "fill_path": g.get("fill_path")}
           for g in sorted(gaps.get("gaps") or [], key=lambda g: -int(g.get("severity") or 0))[:3]]
    newest = max((s.get("newest") or "" for s in cov.get("sources") or []), default=None)
    no_source = cov.get("no_source") or []
    stale = cov.get("stale") or []
    retired = sorted((cov.get("retired_states") or {}).keys())
    places = cov.get("places") or {}
    running = bool(st.get("running"))

    ar = (f"بيانات فلسطين: {cov.get('total_claims', 0):,} رسالة من "
          f"{len(cov.get('sources') or [])} مصدر، {sum((cov.get('live_states') or {}).values()):,} "
          + (f"حالة مباشرة على {tracked} حاجز متابَع، {with_reading} منها عليها قراءة حالية."
             if tracked is not None
             else f"حالة مباشرة على {places.get('checkpoint', 0)} حاجز مسجّل."))
    partial_src = cov.get("partial_source") or {}
    if no_source:
        ar += " ما في ولا مصدر لـ: " + "، ".join(field_words(k)[0] for k in no_source) + "."
    if partial_src.get("crossing_status"):
        pc = partial_src["crossing_status"]
        ar += (f" المعابر: بس {'، '.join(pc['read'])} من قنوات الطرق، "
               f"و{_counted_ar(len(pc['no_source']), 'معبر', 'معبرين', 'معابر', 'معبر')} بلا مصدر.")
    if stale:
        ar += " ساكتة من زمان: " + "، ".join(field_words(k)[0] for k in stale) + "."
    ar += (f" بنك المعلومات: {rows:,} سجل في {len(cat_counts)} فئة"
           + (f"، و{len(failing)} خط إمداد معطّل." if failing else "."))
    ar += " البث شغال." if running else " البث واقف."
    return {
        "answer": ar,
        "name": "Palestine Data — live + databank", "name_ar": "بيانات فلسطين",
        "live": {"messages": cov.get("total_claims"),
                 "sources": len(cov.get("sources") or []),
                 "newest_message_at": newest,
                 "live_states": cov.get("live_states"),
                 "live_fields": live,
                 "no_source": no_source, "partial_source": partial_src,
                 "stale": stale, "retired": retired,
                 "checkpoints_tracked": tracked if tracked is not None else places.get("checkpoint"),
                 "checkpoints_with_current_reading": with_reading,
                 "checkpoint_rows": places.get("checkpoint")},
        "partial": partial,
        "databank": {"rows": rows, "categories": len(cat_counts),
                     "datasets": (gaps.get("counts") or {}).get("datasets"),
                     "fresh": (gaps.get("counts") or {}).get("fresh"),
                     "failing_supply_lines": len(failing)},
        "top_gaps": top,
        "stream": {"running": running, "url": st.get("url", "/v2/stream")},
        "sections": "about(section=sources|fields|gaps|stream) returns the full detail "
                    "behind each count.",
        "reading": "Three words, never blurred: a VALUE we will assert now; `unknown` "
                   "(nobody credible looked recently — an answer, not a gap, never the "
                   "last value); `no source` (nothing measures this, ask tomorrow and "
                   "it is still no).",
    }


TOOLS = {
    "about": (about,
              "What this system is, what it holds, what it holds NOTHING for, and "
              "whether it is alive — call this first. overview (default) is a short "
              "reduction; section=sources|fields|gaps|stream returns the full detail. "
              "`no source` means nothing measures a field, ever; `unknown` means nobody "
              "credible reported recently.",
              {"type": "object", "properties": {
                  "section": {"type": "string",
                              "enum": ["overview", "sources", "fields", "gaps", "stream"],
                              "default": "overview",
                              "description": "overview, or one section in full"}}}),
    "correlate": (correlate,
                  "Concepts, indicator search, and correlation between two "
                  "series. Call with nothing to see what the databank "
                  "measures; with `search`/`concept` to find an indicator "
                  "string; with `a` and `b` to correlate. REFUSES rather "
                  "than returning a misleading number — two cumulative "
                  "tolls correlate at ~1.0 and that measures time, not a "
                  "relationship.",
                  {"type": "object", "properties": {
                      "a": {"type": "string", "description": "first indicator"},
                      "b": {"type": "string", "description": "second indicator"},
                      "concept": {"type": "string",
                                  "description": "filter the search by concept"},
                      "search": {"type": "string",
                                 "description": "substring of an indicator"},
                      "place_id": {"type": "integer"},
                      "max_lag": {"type": "integer", "minimum": 0, "maximum": 366,
                                  "description": "days to scan for a lagged "
                                                 "fit; adds a caveat"},
                      "allow_same_concept": {"type": "boolean"}}}),
    "what_correlates_with": (what_correlates_with,
                             "SEARCH for series that move with a given one, "
                             "instead of naming both sides yourself. Scans "
                             "everything comparable, applies the same hard "
                             "refusals as `correlate`, and reports how many "
                             "tests it ran — results are hypotheses to check "
                             "with `correlate`, never findings.",
                             {"type": "object", "properties": {
                                 "indicator": {"type": "string",
                                               "description": "the series to scan around"},
                                 "place": {"type": "string",
                                           "description": "optional: restrict to one place"},
                                 "candidates": {"type": "integer",
                                                "description": "how many series to consider, default 40"},
                                 "allow_same_concept": {"type": "boolean"}},
                              "required": ["indicator"]}),
    "compare": (compare,
                "Two to six series side by side with their own units, native "
                "grain, attribution and the window they actually share. "
                "Nothing is rescaled to a common axis — two units on one axis "
                "is a chart that lies.",
                {"type": "object", "properties": {
                    "indicators": {"type": "string",
                                   "description": "comma-separated indicator strings"},
                    "place": {"type": "string"}},
                 "required": ["indicators"]}),
    "place_profile": (place_profile,
                      "Everything BOTH tiers hold about one place in a single "
                      "call: live checkpoint state, recent report history, the "
                      "hourly pattern, and nearby incidents. Use for 'tell me "
                      "about Huwara'. Handles the trap that a town and the "
                      "checkpoint named after it are different rows.",
                      {"type": "object", "properties": {
                          "place": {"type": "string"},
                          "days": {"type": "integer"}},
                       "required": ["place"]}),
    "search": (search,
               "Free-text search across recent ingested messages, for when you "
               "have the words somebody used rather than a place or an "
               "indicator string. Matches literally — a different spelling "
               "will not match.",
               {"type": "object", "properties": {
                   "text": {"type": "string"},
                   "area": {"type": "string", "description": "a governorate or town"},
                   "hours": {"type": "integer", "default": 168, "minimum": 1, "maximum": 720},
                   "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 25},
                   "kind": {"type": "string", "enum": ["news", "roads", "all"],
                            "default": "all"}},
                "required": ["text"]}),
    "trend": (trend,
              "Whether a databank series is above or below its own baseline — "
              "the last three readings against the median of the rest — so the "
              "comparison is made once here rather than differently by every "
              "caller. Use for 'is X getting worse'.",
              {"type": "object", "properties": {
                  "indicator": {"type": "string"},
                  "days": {"type": "integer"},
                  "place": {"type": "string"}},
               "required": ["indicator"]}),
    "licenses": (licenses,
                 "Who owns the databank's data and what each licence "
                 "obliges: the open / commercial-permissive / "
                 "commercial-share-alike tiers, per-source attribution "
                 "text, and which publishers' terms nobody has read yet. "
                 "Use BEFORE telling anyone they may reuse or sell a "
                 "figure — 6,562 rows may be sold but oblige a derived "
                 "database to carry the same licence.",
                 {"type": "object", "properties": {
                     "source": {"type": "string",
                                "description": "optional: filter to one "
                                               "source key or name"}}}),
    "licence_tools": (licence_tools,
                      "What each PUBLIC TOOL may hand a commercial partner, and "
                      "in what form. `licenses` says who owns a row; this says "
                      "which of this server's own answers may be carried away "
                      "whole, which come as a citation only, and why. Our "
                      "derived observations are ours to give; a channel's "
                      "message BODY is not, so those tools return an excerpt "
                      "and say so. Call it before republishing anything from "
                      "here.",
                      {"type": "object", "properties": {}}),
    "data_gaps": (data_gaps,
                  "The gap radar: which datasets are stalled/late/dead, "
                  "where the timeline has holes, which supply lines are "
                  "failing — freshness measured on the data's own dates, "
                  "re-measured after every nightly sync. Use for 'what data "
                  "is missing/stale?' and before trusting a quiet series.",
                  {"type": "object", "properties": {}}),
    "databank": (databank,
                 "Historical databank (200k+ rows, 20 categories: prisoners, "
                 "demolitions, food prices, funding, martyrs roster…) with "
                 "per-source licensing. No `category` lists what exists; "
                 "`as_of` (YYYY-MM-DD) reconstructs a past day's answer.",
                 {"type": "object", "properties": {
                     "category": {"type": "string",
                                  "description": "e.g. prisoners, demolitions"},
                     "indicator": {"type": "string",
                                   "description": "prefix filter, e.g. prisoners.child"},
                     "as_of": {"type": "string",
                               "description": "YYYY-MM-DD — answer as of that day"},
                     "limit": {"type": "integer", "default": 10,
                               "description": "rows to return (1–2000)"}}}),
    "can_i_travel": (can_i_travel,
                     "Can I get from A to B right now? Returns every reasonable route scored by "
                     "the checkpoints ON it — in travel order, each with its age — plus "
                     "alternatives when one is blocked. Use this instead of checking checkpoints "
                     "one by one: a journey needs EVERY checkpoint passable, so one confirmed "
                     "closure blocks the route. Checkpoints nobody has reported recently never "
                     "block and are always named.",
                     {"type": "object", "properties": {
                         "origin": {"type": "string", "description": "e.g. رام الله, Ramallah"},
                         "destination": {"type": "string", "description": "e.g. نابلس, Nablus"}},
                      "required": ["origin", "destination"]}),
    "place_history": (place_history,
                      "What has been happening at a place over recent days: daily counts of "
                      "reports and what they said, plus how many INDEPENDENT reporters. Use "
                      "for 'has Huwara been bad this month'. Counts are reports, not time.",
                      {"type": "object", "properties": {
                          "place": {"type": "string", "description": "e.g. حوارة, Huwara"},
                          "state_kind": {"type": "string",
                                         "description": "e.g. checkpoint_status, fuel_diesel"},
                          "days": {"type": "integer"}},
                       "required": ["place"]}),
    "place_pattern": (place_pattern,
                      "What USUALLY happens at a place by hour of day, in local time. Use for "
                      "'when is Za'tara usually closed'. Hours with too few reports come back "
                      "as unknown rather than as a confident share of two observations.",
                      {"type": "object", "properties": {
                          "place": {"type": "string"},
                          "state_kind": {"type": "string"},
                          "days": {"type": "integer"}},
                       "required": ["place"]}),
    "area_history": (area_history,
                     "Totals by governorate over recent days — checkpoints, fuel and the rest "
                     "joined on place and time. Use for 'which governorate had the most "
                     "closures this month'.",
                     {"type": "object", "properties": {
                         "state_kind": {"type": "string"}, "days": {"type": "integer"}}}),
    "stream_info": (stream_info,
                    "How to subscribe to live changes over server-sent events, and whether the "
                    "stream is currently running.",
                    {"type": "object", "properties": {}}),
    "fuel_prices": (fuel_prices,
                    "Official West Bank fuel prices (petrol 95/98, diesel, kerosene, "
                    "cooking-gas cylinders): the Petroleum Corporation's monthly MAXIMUM "
                    "consumer price, not a pump price and not Gaza's. A price is given only "
                    "when two independent outlets agree; otherwise the answer says it is "
                    "unconfirmed, conflicting, or that this month's list has not been read "
                    "yet. history=true lists every confirmed price so far.",
                    {"type": "object", "properties": {
                        "product": {"type": "string",
                                    "enum": ["gasoline_95", "gasoline_98", "diesel", "kerosene",
                                             "lpg_2_5kg", "lpg_5kg", "lpg_12kg", "lpg_48kg"],
                                    "description": "one product; omit for the whole list"},
                        "history": {"type": "boolean", "default": False,
                                    "description": "true lists every confirmed price so far"}}}),
    "checkpoint_status": (checkpoint_status,
                          "Is a named checkpoint open right now? Returns flow (open/congested/"
                          "slow/closed), whether it is passable, who is present (army, police, "
                          "settlers, inspection) as a SEPARATE fact, and how old the reading is. "
                          "Inbound and outbound can differ and are both reported.",
                          {"type": "object", "properties": {
                              "name": {"type": "string", "description": "e.g. حوارة, قلنديا, Huwara"},
                              "direction": {"type": "string", "enum": ["inbound", "outbound", "both"],
                                            "default": "both",
                                            "description": "direction of travel relative to the checkpoint"}},
                           "required": ["name"]}),
    "insights": (insights,
                 "ONE reduction of a place over a window: checkpoint status "
                 "distribution around it, which checkpoints actually changed, the "
                 "busiest hours, incident counts by type, and the measured "
                 "precision of each subject. Use this for 'what was happening "
                 "around X last month' instead of fetching rows and averaging them "
                 "yourself. Give `place` (or lat/lon).",
                 {"type": "object", "properties": {
                     "place": {"type": "string", "description": "e.g. رام الله, Ramallah, نابلس"},
                     "lat": {"type": "number"}, "lon": {"type": "number"},
                     "days": {"type": "integer", "description": "lookback window, default 30"},
                     "radius_km": {"type": "number", "description": "radius around it, default 15"}}}),
    "checkpoints_near": (checkpoints_near,
                         "Checkpoints around a place or coordinate, nearest first, with what is "
                         "known and how much is NOT known. Give `place` or lat/lon.",
                         {"type": "object", "properties": {
                             "place": {"type": "string", "description": "e.g. نابلس, Ramallah"},
                             "lat": {"type": "number"}, "lon": {"type": "number"},
                             "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]},
                             "radius_km": {"type": "number"},
                             "limit": {"type": "integer"}}}),
    "checkpoints_summary": (checkpoints_summary,
                            "West-Bank-wide checkpoint picture: how many are open, closed or "
                            "congested, which are closed now, and how many have no recent reading.",
                            {"type": "object", "properties": {}}),
    "incidents_near": (incidents_near,
                       "Recent located incidents around a place — raids, settler attacks, "
                       "closures, arrests, demolitions — with how many INDEPENDENT channels "
                       "reported each. Give `place` or lat/lon.",
                       {"type": "object", "properties": {
                           "place": {"type": "string", "description": "e.g. نابلس, Hebron"},
                           "lat": {"type": "number"}, "lon": {"type": "number"},
                           "hours": {"type": "integer", "description": "lookback window, default 12"},
                           "radius_km": {"type": "number"},
                           "limit": {"type": "integer"}}}),
    "incidents_summary": (incidents_summary,
                          "West-Bank-wide incident counts by type and the worst-affected "
                          "places over a time window.",
                          {"type": "object", "properties": {
                              "hours": {"type": "integer"}}}),
    "weather_now": (weather_now,
                    "Weather conditions and advisories per West Bank governorate — heat waves, "
                    "storms, frost. Optionally filter to one governorate. Useful alongside "
                    "movement answers: 43C changes what a checkpoint queue means.",
                    {"type": "object", "properties": {
                        "place": {"type": "string", "description": "governorate, e.g. اريحا, Hebron"}}}),
    "connectivity_now": (connectivity_now,
                         "Whether West Bank internet is reachable, measured externally by IODA "
                         "(routing table, active probes, darknet telescope) rather than reported "
                         "by anyone. Answers 'is the internet down' when nobody can post that it is.",
                         {"type": "object", "properties": {}}),
    "latest_news": (latest_news,
                    "Most recent ingested messages, optionally filtered by area. kind=news "
                    "(default) leaves out the road-status tables; roads returns only them.",
                    {"type": "object", "properties": {
                        "area": {"type": "string", "description": "a governorate or town"},
                        "hours": {"type": "integer", "minimum": 1, "maximum": 720,
                                  "description": "lookback window in hours"},
                        "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 25,
                                  "description": "how many messages to return"},
                        "kind": {"type": "string", "enum": ["news", "roads", "all"],
                                 "default": "news",
                                 "description": "news leaves out road-status tables; roads "
                                                "returns only them; all returns everything"}}}),
    "coverage": (coverage, "What sources and data this system currently holds — "
                           "and, more usefully, what it holds NOTHING for. Check "
                           "this before answering a question about power, water, "
                           "cooking gas or crossings.",
                 {"type": "object", "properties": {}}),
    "crossings": (crossings, "Status of Gaza and West Bank crossings (Rafah, Kerem "
                             "Shalom, Erez, Zikim, Kissufim, Allenby...). Values are "
                             "open / partial / closed / unknown, where `partial` "
                             "means open only for some traffic and is NOT open. "
                             "The Allenby bridge and the Jericho rest stop are read "
                             "through the road channels; the Gaza crossings have "
                             "no source — the answer names which, say so plainly.",
                  {"type": "object", "properties": {
                      "area": {"type": "string",
                               "description": "governorate or region, e.g. غزة"}}}),
    "system_health": (lambda: _system_health(),
                      "Operational health of the palestine-v2 system itself: which "
                      "collector jobs and feeds are green, current faults, and any "
                      "open operational alarms. For relaying system status to Zaid — "
                      "this is about the MACHINE, not about roads or checkpoints.",
                      {"type": "object", "properties": {}}),
    "mcp_usage": (lambda days=7: _mcp_usage(days),
                  "What people have been asking the public MCP endpoint, and "
                  "which questions it could NOT answer. Use for 'what should "
                  "we add next' — `unanswered_demand` ranks the questions "
                  "people keep asking that this system has no source for, "
                  "which is the demand side of the gap radar. Zaid only; not "
                  "served over HTTP.",
                  {"type": "object", "properties": {
                      "days": {"type": "integer",
                               "description": "lookback window, default 7"}}}),
    "ops_digest": (lambda: _ops_digest(),
                   "The latest weekly maintenance digest: what the automated Opus "
                   "maintenance run checked, measured, fixed and committed, plus the "
                   "measurement ledger (classifier precision rounds, quarantined-feed "
                   "re-measurements). Deliver its summary to Zaid when he asks for the "
                   "weekly update, or every Monday if he asked for a standing one.",
                   {"type": "object", "properties": {}}),
    "where_is": (where_is, "Resolve an Arabic or English place name to coordinates. "
                           "Pass state_kind when you mean a checkpoint, fuel station "
                           "or crossing rather than the town of the same name — "
                           "'حوارة' the checkpoint and 'حوارة' the town are different "
                           "rows and their data does not mix.",
                 {"type": "object", "properties": {
                     "place": {"type": "string"},
                     "state_kind": {"type": "string",
                                    "description": "e.g. checkpoint_status, "
                                                   "fuel_diesel, crossing_status"}},
                  "required": ["place"]}),
}

# Served over stdio only. Two of them report the health of THIS MACHINE; the
# third reports what its visitors have been asking, which is a fact about them
# rather than about roads. Kept beside TOOLS so a tool added below cannot be
# published by forgetting a list in another file.
HOST_ONLY = {"system_health", "ops_digest", "mcp_usage"}

# DELIBERATELY ABSENT: the crowd WRITE path (/v2/crowd/register, /v2/crowd/report).
# An agent that can file reports is the sock-puppet problem P2.4 exists for,
# running at machine speed and without a person who can be held to a claim. The
# read surface is at parity; the write surface stays human.


# ── ops tools ────────────────────────────────────────────────────────────────
# This process runs as the HERMES user (the gateways spawn it), which cannot
# read .env and therefore cannot reach the database. Health comes through the
# API like every other tool; the ops ledgers are world-readable files.

_ROOT = Path(__file__).resolve().parent.parent


_UNREADABLE_LINES: dict[str, int] = {}


def _tail_ndjson(name: str, n: int = 3) -> list[dict]:
    """Last n records of an append-only ndjson file.

    One unreadable line must never take a tool down. A crash mid-append left a
    line of NUL bytes in ops/alerts.ndjson (line 195 of 899, found 2026-09-25),
    and `system_health` — the tool whose whole job is to say whether the system
    is healthy — answered "صار خطأ بالنظام." for a system whose /health said
    `degraded` with one named fault. Skip what cannot be parsed, and RECORD the
    count: a log we can only partly read may be missing alarms, so the damage
    belongs in the payload, not in silence.
    """
    p = _ROOT / "ops" / name
    if not p.exists():
        return []
    out: list[dict] = []
    bad = 0
    for line in (x for x in p.read_text().splitlines() if x.strip()):
        try:
            out.append(json.loads(line))
        except ValueError:
            bad += 1
    if bad:
        _UNREADABLE_LINES[name] = bad
    return out[-n:]


def _open_alarms() -> list[dict]:
    """Same open/resolved/cleared semantics as ops/alert.py, over the same
    file. Reimplemented rather than imported because this process runs from
    serve/ under another user's venv; the format is three fields and stable."""
    recs = _tail_ndjson("alerts.ndjson", n=10_000)
    cleared_at = max((r["ts"] for r in recs if r.get("clear_marker")), default="")
    resolved: dict[str, str] = {}
    for r in recs:
        if r.get("resolves"):
            resolved[r["resolves"]] = max(resolved.get(r["resolves"], ""), r["ts"])
    return [{"ts": r["ts"], "unit": r.get("unit"),
             "detail": (r.get("detail") or "").splitlines()[0][:120] if r.get("detail") else ""}
            for r in recs
            if not r.get("clear_marker") and not r.get("resolves")
            and r["ts"] > cleared_at
            and r["ts"] > resolved.get(r.get("unit", ""), "")]


def _system_health() -> dict:
    h = api("/health", verbose="true")
    alarms = _open_alarms()
    say = ("النظام سليم — كل المهام والمصادر خضراء." if h.get("status") == "ok" and not alarms
           else "في أعطال تحتاج نظرة: " + "، ".join(h.get("faults", []) or [a.get("unit", "?") for a in alarms]))
    if _UNREADABLE_LINES:
        say += " (ملاحظة: " + "، ".join(f"{k}: {v} سطر غير مقروء" for k, v in _UNREADABLE_LINES.items()) + ")"
    return {"answer": say, "status": h.get("status"),
            "faults": h.get("faults", []),
            "jobs_ok": f"{h.get('jobs_ok')}/{h.get('jobs_total')}",
            "feeds_ok": f"{h.get('feeds_ok')}/{h.get('feeds_total')}",
            "open_alarms": alarms,
            "unreadable_log_lines": dict(_UNREADABLE_LINES) or None,
            "caveat": "system status, not road status — use checkpoints_summary for roads"}


def _mcp_usage(days: int = 7) -> dict:
    """Read the usage ledger directly — it is a file beside this one, so this
    works from the hermes user too, which has no database and no .env."""
    from serve.mcp_usage import summary
    d = summary(days)
    if not d.get("calls"):
        return {"answer": f"ما في استخدام مسجل بآخر {days} يوم.", **d}
    top = list(d["by_tool"])[:3]
    say = (f"{d['calls']} نداء من {d['callers']} مستخدم بآخر {days} يوم. "
           f"الأكثر استخداماً: {'، '.join(top)}.")
    if d["unanswered_demand"]:
        u = d["unanswered_demand"][0]
        say += (f" وأكثر سؤال ما إلنا جواب عليه: {u['tool']} "
                f"({u['unmet_calls']} من {u['of_calls']} نداء رجعوا فاضيين).")
    return {"answer": say, **d}


def _ops_digest() -> dict:
    digest_file = _ROOT / "ops" / "digest-latest.md"
    digest = digest_file.read_text() if digest_file.exists() else None
    return {
        "digest_markdown": digest or "لا يوجد تقرير بعد — أول تشغيل أسبوعي لم يحدث.",
        "digest_written_at": (datetime.fromtimestamp(digest_file.stat().st_mtime,
                                                     tz=timezone.utc).isoformat()
                              if digest_file.exists() else None),
        "recent_runs": _tail_ndjson("digests.ndjson", 3),
        "precision_rounds": _tail_ndjson("incident-rounds.ndjson", 3),
        "quarantine_reviews": _tail_ndjson("measure-review.ndjson", 2),
        "note": "written by the weekly Opus maintenance run (Mondays); "
                "system_health has the live picture between runs",
    }


# ── MCP stdio loop ───────────────────────────────────────────────────────────

def _reply(rid: Any, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result},
                                ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(rid: Any, code: int, msg: str) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid,
                                 "error": {"code": code, "message": msg}},
                                ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_stdio(req: dict) -> dict | None:
    """One JSON-RPC message from the host, through the SAME dispatcher the HTTP
    door uses (audit F270: stdio had its own — no ping, no instructions, no
    outputSchema, no licence block, so the host's agents got the tools
    without the reading contract). `host=True` keeps HOST_ONLY callable and
    listed, because this transport IS the host; the licence tier is `house`."""
    from serve.mcp_http import _handle
    return _handle(req, ip="127.0.0.1", tier="house", host=True)


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_stdio(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False, default=str) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
