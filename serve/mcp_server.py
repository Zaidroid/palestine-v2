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
                  timeout=30.0)
    r.raise_for_status()
    return r.json()


def _age_ar(minutes: int | None) -> str:
    if minutes is None:
        return "غير معروف"
    if minutes < 60:
        return f"قبل {int(minutes)} دقيقة"
    if minutes < 1440:
        return f"قبل {int(minutes // 60)} ساعة"
    return f"قبل {int(minutes // 1440)} يوم"


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
    since = next((r["effective_from"] for r in rows if r["price"] is not None), None)
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


def checkpoint_status(name: str, direction: str = "both") -> dict:
    """Is a named checkpoint open? Optionally for one travel direction."""
    direction = DIR_IN.get(direction.strip().lower(), direction.strip().lower())
    if direction not in ("inbound", "outbound", "both"):
        direction = "both"
    d = api("/v2/checkpoints/status", name=name, direction=direction)
    if not d.get("found"):
        return {"answer": f"ما عرفت حاجز اسمه {name}.", **d}

    nm = d["match"]["resolved_to"]
    by = d.get("by_direction") or {}
    inb, outb = by.get("inbound"), by.get("outbound")

    # Where the two directions genuinely differ, say so — that difference is
    # the whole reason direction is tracked, and it is exactly what a bare
    # status hides.
    if (direction == "both" and inb and outb
            and inb["flow"] != outb["flow"]
            and "unknown" not in (inb["flow"], outb["flow"])):
        answer = (f"{nm}: {FLOW_AR.get(inb['flow'], inb['flow'])} للداخل، "
                  f"و{FLOW_AR.get(outb['flow'], outb['flow'])} للخارج."
                  f"{_presence_phrase(d)}")
    else:
        suffix = "" if direction == "both" else f" {DIR_AR[direction]}"
        answer = f"{nm}{suffix}: {_flow_phrase(d)}.{_presence_phrase(d)}"
        if d["flow"] != "unknown":
            answer += f" آخر تحديث {_age_ar(d.get('age_minutes'))}."

    return {"answer": answer, "name": nm, "direction": direction,
            "flow": d["flow"], "passable": d["passable"],
            "last_known_flow": d.get("last_known_flow"),
            "age_minutes": d.get("age_minutes"),
            "staleness_band": d.get("staleness_band"),
            "confidence": d.get("confidence"),
            "independent_sources": d.get("independent_sources"),
            "present": d.get("present"), "by_direction": by,
            "lat": d.get("lat"), "lon": d.get("lon"),
            "source": d.get("attribution")}


def checkpoints_near(place: str | None = None, lat: float | None = None,
                     lon: float | None = None, direction: str = "both",
                     radius_km: float = 15.0, limit: int = 6) -> dict:
    """What are the checkpoints around here doing?"""
    direction = DIR_IN.get(direction.strip().lower(), direction.strip().lower())
    if direction not in ("inbound", "outbound", "both"):
        direction = "both"
    if lat is None or lon is None:
        if not place:
            return {"answer": "لازم تحدد المكان.", "error": "need place or lat/lon"}
        geo = api("/v2/geo/resolve", q=place)
        if not geo.get("found"):
            return {"answer": f"ما عرفت وين {place}.", "error": "place not resolved"}
        lat, lon, place = geo["lat"], geo["lon"], geo["name"]

    d = api("/v2/checkpoints/nearby", lat=lat, lon=lon, direction=direction,
            radius_km=radius_km, limit=limit)
    res, counts = d.get("results", []), d.get("counts", {})
    known = [r for r in res if r["flow"] != "unknown"]

    if not known:
        answer = (f"ما في تحديثات جديدة عن الحواجز حوالين {place or 'هون'}. "
                  f"في {counts.get('in_radius', 0)} حاجز بالمنطقة بس آخر أخبارهم قديمة.")
    else:
        closed = [r for r in known if r["flow"] == "closed"]
        parts = [f"{r['name']} {FLOW_AR.get(r['flow'], r['flow'])}"
                 f"{_presence_phrase(r)}" for r in known[:4]]
        answer = f"حوالين {place or 'موقعك'}: " + "، ".join(parts) + "."
        if closed:
            answer += f" انتبه: {'، '.join(r['name'] for r in closed)} مغلق."
        # Never let the confident part imply full coverage.
        if counts.get("unknown"):
            answer += f" وفي {counts['unknown']} حاجز ما إلهم تحديث حديث."

    return {"answer": answer, "origin": place or f"{lat:.4f},{lon:.4f}",
            "direction": direction, "counts": counts,
            "checkpoints": [{"name": r["name"], "flow": r["flow"],
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
    if closed:
        answer += " المغلقة حالياً: " + "، ".join(c["name"] for c in closed[:6]) + "."
    return {"answer": answer, "totals": t,
            "known_fraction": d.get("known_fraction"),
            "tracked": d.get("tracked"), "presence": d.get("presence"),
            "closed_now": [{"name": c["name"], "age_minutes": c["age_minutes"],
                            "present": c.get("present")} for c in closed],
            "source": d.get("attribution")}


# ── incidents ────────────────────────────────────────────────────────────────
INCIDENT_AR = {
    "raid": "اقتحام", "settler_attack": "اعتداء مستوطنين", "closure": "إغلاق",
    "siege": "حصار", "arrest": "اعتقالات", "injury": "إصابات",
    "shooting": "إطلاق نار", "demolition": "هدم", "death": "استشهاد",
}


def incidents_near(place: str | None = None, lat: float | None = None,
                   lon: float | None = None, hours: int = 12,
                   radius_km: float = 25.0, limit: int = 8) -> dict:
    """What has been happening around here — raids, settler attacks, closures."""
    if lat is None or lon is None:
        if not place:
            return {"answer": "لازم تحدد المكان.", "error": "need place or lat/lon"}
        geo = api("/v2/geo/resolve", q=place)
        if not geo.get("found"):
            return {"answer": f"ما عرفت وين {place}.", "error": "place not resolved"}
        lat, lon, place = geo["lat"], geo["lon"], geo["name"]

    d = api("/v2/incidents/recent", lat=lat, lon=lon, hours=hours,
            radius_km=radius_km, limit=limit)
    items = d.get("incidents", [])
    if not items:
        answer = f"ما في أحداث مسجلة حوالين {place or 'موقعك'} بآخر {hours} ساعة."
    else:
        parts = []
        for i in items[:4]:
            ar = INCIDENT_AR.get(i["type"], i["type"])
            parts.append(f"{ar} في {i['place']} {_age_ar(_mins_since(i['occurred_at']))}")
        answer = f"حوالين {place or 'موقعك'}: " + "، ".join(parts) + "."
        # Corroboration stated plainly — a single channel is not the same as four.
        solo = sum(1 for i in items if i["independent_sources"] < 2)
        if solo:
            answer += f" ({solo} منها من مصدر واحد بس.)"
    return {"answer": answer, "origin": place or f"{lat:.4f},{lon:.4f}",
            "hours": hours, "count": len(items), "by_type": d.get("by_type"),
            "incidents": items, "source": d.get("attribution")}


def incidents_summary(hours: int = 24) -> dict:
    d = api("/v2/incidents/summary", hours=hours)
    bt = d.get("by_type", {})
    if not bt:
        return {"answer": f"ما في أحداث مسجلة بآخر {hours} ساعة.", **d}
    bits = [f"{v['n']} {INCIDENT_AR.get(k, k)}" for k, v in
            sorted(bt.items(), key=lambda kv: -kv[1]["n"])[:5]]
    places = ", ".join(p["place"] for p in d.get("by_place", [])[:4])
    answer = f"بآخر {hours} ساعة بالضفة: " + "، ".join(bits) + "."
    if places:
        answer += f" الأكثر تأثراً: {places}."
    return {"answer": answer, **d}


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
        answer = ("في انقطاع واسع بالإنترنت بالضفة حسب القياس الخارجي "
                  f"({d.get('signals_agreeing')} مؤشرات مستقلة متفقة).")
    elif st == "degraded":
        answer = "في تراجع بجودة الإنترنت بالضفة حسب القياس الخارجي."
    else:
        answer = "الإنترنت بالضفة شغال طبيعي حسب القياس الخارجي."
    return {"answer": answer, **d}


def latest_news(area: str | None = None, limit: int = 8) -> dict:
    d = api("/v2/news/latest", area=area, limit=limit)
    items = d.get("items", [])
    if not items:
        return {"answer": (f"ما في أخبار جديدة عن {area}." if area else "ما في أخبار جديدة."),
                "items": []}
    return {"answer": f"آخر خبر: {items[0]['text'][:180]}",
            "count": len(items), "items": items}


def coverage() -> dict:
    d = api("/v2/coverage")
    # Lead with the BLIND SPOTS, not the totals. An agent that reads
    # "1,000,000 messages from 47 sources" and stops has learned the opposite
    # of what this endpoint is for; the fields that nothing reports are the
    # part it needs before it answers a question about them.
    fields = d.get("fields", [])
    dark = [f["state_kind"] for f in fields if f.get("coverage_state") == "never_reported"]
    stale = [f["state_kind"] for f in fields if f.get("coverage_state") == "stale"]
    say = (f"عندي {d['total_claims']} رسالة من {len(d['sources'])} مصدر، "
           f"و{sum(d['live_states'].values())} حالة مباشرة.")
    if dark:
        say += f" ما في ولا مصدر لـ: {'، '.join(dark)}."
    if stale:
        say += f" وهاي ساكتة من زمان: {'، '.join(stale)}."
    return {"answer": say,
            "no_source": dark,
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
    known = [c for c in items if c.get("value") not in (None, "unknown")]
    if not known:
        return {"answer": ("ما عندي ولا مصدر بيقول عن حالة المعابر — "
                           "مش معناها مفتوحة، معناها ما حدا بيخبرنا."),
                "count": len(items), "crossings": items,
                "no_source": True,
                "warning": ("Every crossing reads `unknown` because NO source "
                            "reports crossing status yet. This is absence of "
                            "evidence, not evidence of absence. Never present "
                            "it as 'the crossing is open'.")}
    say = "، ".join(f"{c['name']}: {c['value']}" for c in known[:6])
    return {"answer": say, "count": len(items), "crossings": items}


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
        return {"answer": f"ما عرفت وين {place}.", **d}
    return {"answer": f"{d.get('name')} ({d.get('kind')}) — "
                      f"{d.get('lat')}, {d.get('lon')}", **d}



# ── P5.1/P5.2 parity: an agent must be able to reach everything a frontend can ─
# Otherwise "one place to read everything" quietly means "one place, unless you
# are an agent", and the two surfaces drift until nobody knows which is
# authoritative.

def place_history(place: str, state_kind: str | None = None,
                  days: int = 30) -> dict:
    """Daily report counts for a place, from the databank rollup."""
    g = api("/v2/geo/resolve", q=place, state_kind=state_kind or "checkpoint_status")
    if not g.get("found"):
        return {"answer": f"ما عرفت وين {place}.", "found": False, **g}
    d = api("/v2/history/place", place_id=g["place_id"],
            state_kind=state_kind, days=days)
    series = d.get("series", [])
    if not series:
        return {"answer": f"ما عندي تاريخ محفوظ عن {g['name']} بعد.",
                "place": g["name"], "series": []}
    # Summarise so a model does not have to reduce 30 days itself to answer
    # "has it been bad lately".
    tot: dict[str, dict[str, int]] = {}
    for day in series:
        for kind, v in day["kinds"].items():
            slot = tot.setdefault(kind, {})
            for val, n in v.get("values", {}).items():
                slot[val] = slot.get(val, 0) + n
    return {"answer": f"{g['name']}: تاريخ {len(series)} يوم.",
            "place": g["name"], "place_id": g["place_id"],
            "days_with_data": len(series), "totals_by_kind": tot,
            "series": series,
            "counts": "reports, not time — sparse days mean sparse attention."}


def place_pattern(place: str, state_kind: str = "checkpoint_status",
                  days: int = 60) -> dict:
    """What usually happens here, by hour of day, local time."""
    g = api("/v2/geo/resolve", q=place, state_kind=state_kind)
    if not g.get("found"):
        return {"answer": f"ما عرفت وين {place}.", "found": False, **g}
    d = api("/v2/patterns/place", place_id=g["place_id"],
            state_kind=state_kind, days=days)
    known = [h for h in d["hours"] if h["usually"] != "unknown"]
    if not known:
        return {"answer": f"ما في تقارير كافية عن {g['name']} لأستنتج نمط.",
                "place": g["name"], "hours": d["hours"]}
    worst = [h for h in known if h["usually"] in ("closed", "unavailable")]
    hrs = "، ".join(f"{h['hour']:02d}:00" for h in worst[:6]) or "ما في"
    return {"answer": f"{g['name']}: عادة مسكّر الساعات {hrs}." if worst
                      else f"{g['name']}: عادة سالك بمعظم الساعات.",
            "place": g["name"], "place_id": g["place_id"],
            "timezone": d["timezone"], "hours": d["hours"],
            "caveat": d["note"]}


def area_history(state_kind: str | None = None, days: int = 30) -> dict:
    """Totals by governorate — the cross-tier view."""
    d = api("/v2/history/area", state_kind=state_kind, days=days)
    govs = d.get("governorates", {})
    return {"answer": f"تاريخ {days} يوم عبر {len(govs)} محافظة.",
            "governorates": govs, "note": d.get("note")}


def stream_info() -> dict:
    """How to subscribe to live changes, and whether the stream is alive."""
    d = api("/v2/stream/status")
    return {"answer": ("البث شغال." if d.get("running") else "البث واقف."),
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
    say = {"likely_open": "الطريق سالك على الأغلب",
           "slow": "الطريق سالك بس فيه ازمة",
           "blocked": "الطريق مسكّر",
           "unknown": "ما في تقارير حديثة عن هالطريق"}[best["verdict"]]
    detail = ""
    if best["blocked_at"]:
        detail = " — مسكّر عند " + "، ".join(best["blocked_at"][:2])
        alt = next((r for r in rs if r["verdict"] in ("likely_open", "slow")), None)
        if alt:
            detail += f". بديل: {alt['duration_minutes']:.0f} دقيقة ({alt['verdict']})"
    return {"answer": f"{say}{detail}. "
                      f"{best['known']} من {best['checkpoints_on_route']} حواجز عليها تقارير حديثة.",
            "verdict": best["verdict"],
            "duration_minutes": best["duration_minutes"],
            "distance_km": best["distance_km"],
            "blocked_at": best["blocked_at"],
            "congested_at": best["slow_at"],
            "not_reported_recently": best["unreported"],
            "cautions": best["cautions"],
            "routes": [{k: r[k] for k in ("verdict", "duration_minutes", "distance_km",
                                          "known", "checkpoints_on_route",
                                          "blocked_at", "unreported")} for r in rs],
            "caveat": "one confirmed closure blocks a route; unreported checkpoints "
                      "never block and are always named"}


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
        d = api("/v2/databank/correlate", a=a, b=b, place_id=place_id,
                max_lag=max_lag,
                allow_same_concept="true" if allow_same_concept else "false")
        if d.get("refused"):
            return {"answer": "لا يمكن حساب الارتباط: " + " ".join(
                        r.split("—")[0] for r in d["reasons"])[:300],
                    "refused": True, "reasons": d["reasons"],
                    "caveat": "This is a hard refusal, not a warning. Do not "
                              "report a coefficient for this pair."}
        return {"answer": (f"{d['plain_english']} — n={d['n']}"
                           + (f", lag {d['lag_days']}d" if d["lag_days"] else "")
                           + f", 95% CI {d['ci95']}."),
                **d}
    if search or concept:
        d = api("/v2/databank/indicators", q_=search, concept=concept, limit=25)
        inds = d["indicators"]
        return {"answer": (f"{len(inds)} series matched: "
                           + "، ".join(i["indicator"] for i in inds[:6])),
                "indicators": inds}
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
    if d.get("refused"):
        return {"answer": "ما قدرت أفحص: " + " ".join(d["reasons"])[:200], **d}
    ms = d["matches"]
    if not ms:
        # The reasons ARE the answer here. "Nothing correlates" and "nothing
        # was comparable enough to test" are different findings and the second
        # is the common one.
        return {"answer": ("ما في ولا سلسلة قابلة للمقارنة مع هاي. الأسباب: "
                           + "، ".join(f"{v} {k}" for k, v in d["skipped"].items())),
                **d}
    top = ms[0]
    return {"answer": (f"من {d['tested']} سلسلة مفحوصة، أقواها: "
                       f"{top['indicator']} (ρ={top['rho']}, n={top['n']}). "
                       f"هاي فرضيات للفحص، مش نتائج."),
            **d}


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
    bits = [f"{s['indicator']} ({s['n']} نقطة، {s.get('canonical_unit') or 'بدون وحدة'})"
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
                           "place_id": anchor.get("place_id"),
                           "kind": anchor.get("kind"),
                           "resolved": {"as_town": town.get("found"),
                                        "as_checkpoint": cp.get("found")}}
    said = []

    if cp.get("found"):
        try:
            live = api("/v2/checkpoints/status", name=place, direction="both")
            out["checkpoint_now"] = {"flow": live.get("flow"),
                                     "age_minutes": live.get("age_minutes"),
                                     "present": live.get("present")}
            said.append(f"الحاجز {FLOW_AR.get(live.get('flow'), live.get('flow'))}")
        except Exception:                                   # noqa: BLE001
            pass

    for label, call in (("history", lambda: api("/v2/history/place",
                                                place_id=anchor["place_id"],
                                                days=days)),
                        ("pattern", lambda: api("/v2/patterns/place",
                                                place_id=anchor["place_id"],
                                                state_kind="checkpoint_status",
                                                days=60))):
        try:
            out[label] = call()
        except Exception:                                   # noqa: BLE001
            out[label] = None

    if town.get("found"):
        try:
            inc = api("/v2/incidents/recent", lat=town["lat"], lon=town["lon"],
                      hours=days * 24, radius_km=10, limit=20)
            out["incidents"] = inc.get("incidents", [])
            if out["incidents"]:
                said.append(f"{len(out['incidents'])} حدث بآخر {days} يوم")
        except Exception:                                   # noqa: BLE001
            out["incidents"] = []

    days_with = len((out.get("history") or {}).get("series") or [])
    if days_with:
        said.append(f"{days_with} يوم فيها تقارير")
    out["answer"] = (f"{anchor.get('name')}: " + "، ".join(said) + "."
                     if said else
                     f"{anchor.get('name')}: ما في معلومات حديثة عنها.")
    out["caveat"] = ("A town and the checkpoint named after it are different "
                     "rows; `resolved` says which of the two this answer "
                     "actually covers.")
    return out


def search(text: str, hours: int = 168, limit: int = 20) -> dict:
    """Free-text search across recent messages — the way people actually ask.

    Every other tool needs a place or an indicator string. This one takes the
    words somebody used.
    """
    d = api("/v2/news/latest", limit=100)          # the endpoint's own ceiling
    needle = text.strip().lower()
    hits = [i for i in d.get("items", [])
            if needle in (i.get("text") or "").lower()][:limit]
    if not hits:
        return {"answer": f"ما لقيت ولا رسالة فيها «{text}» بالمخزون الحالي.",
                "count": 0, "items": [],
                "caveat": "searches the most recent ingested messages only, "
                          "not the whole archive"}
    return {"answer": f"{len(hits)} رسالة فيها «{text}». آخرها: "
                      f"{hits[0]['text'][:160]}",
            "count": len(hits), "items": hits,
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
    d = api("/v2/databank/compare", indicators=f"{indicator},{indicator}",
            place_id=place_id)
    pts = [p for p in (d.get("series") or [{}])[0].get("points", [])
           if p.get("value") is not None]
    if len(pts) < 6:
        return {"answer": f"ما في نقاط كفاية بـ{indicator} لأقارن باتجاه.",
                "n": len(pts)}

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
    return {"answer": (f"{indicator}: آخر {len(recent)} قراءة {word}"
                       + (f" بنسبة {abs(change)}% عن الوسيط التاريخي"
                          if change is not None else "")
                       + f" ({round(avg, 2)} مقابل {round(med, 2)})."),
            "indicator": indicator, "n": len(pts),
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
            return {"answer": f"No source matching {source!r} is served.",
                    "licenses": []}
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


def databank(category: str | None = None, indicator: str | None = None,
             as_of: str | None = None, limit: int = 10) -> dict:
    """The historical databank: 186k observations from 19 categories
    (prisoners, demolitions, food prices, funding, the martyrs roster…),
    each row carrying its source's license and attribution. `as_of`
    reconstructs what the archive served on a past day."""
    if not category:
        d = api("/v2/databank/categories")
        cats: dict[str, int] = {}
        for ds in d["datasets"]:
            cats[ds["category"]] = cats.get(ds["category"], 0) + ds["rows"]
        top = sorted(cats.items(), key=lambda kv: -kv[1])
        answer = ("بنك المعلومات التاريخي — أكبر الفئات: " +
                  "، ".join(f"{c} ({n:,})" for c, n in top[:6]) +
                  f". المجموع {sum(cats.values()):,} سجلاً من "
                  f"{len(d['datasets'])} مصدراً.")
        return {"answer": answer, "categories": cats,
                "datasets": d["datasets"]}
    # The one place a caller's string becomes part of a URL path rather than a
    # query value. Named categories only — no slashes, no dots, no query.
    if not re.fullmatch(r"[a-z0-9_]{1,40}", category):
        return {"answer": f"ما في فئة اسمها {category}.",
                "error": "category must be a name from /v2/databank/categories",
                "count": 0, "items": []}
    d = api(f"/v2/databank/{category}", indicator=indicator,
            as_of=as_of, limit=limit)
    when = f" كما كانت بتاريخ {as_of}" if as_of else ""
    answer = (f"{d['count']} سجلاً من {category}{when}."
              if d["count"] else f"لا سجلات مطابقة في {category}{when}.")
    return {"answer": answer, **d}


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


TOOLS = {
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
                      "max_lag": {"type": "integer",
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
                   "hours": {"type": "integer"},
                   "limit": {"type": "integer"}},
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
    "data_gaps": (data_gaps,
                  "The gap radar: which datasets are stalled/late/dead, "
                  "where the timeline has holes, which supply lines are "
                  "failing — freshness measured on the data's own dates, "
                  "re-measured after every nightly sync. Use for 'what data "
                  "is missing/stale?' and before trusting a quiet series.",
                  {"type": "object", "properties": {}}),
    "databank": (databank,
                 "Historical databank (186k+ rows, 19 categories: prisoners, "
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
                     "limit": {"type": "integer"}}}),
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
                                             "lpg_2_5kg", "lpg_5kg", "lpg_12kg", "lpg_48kg"]},
                        "history": {"type": "boolean"}}}),
    "checkpoint_status": (checkpoint_status,
                          "Is a named checkpoint open right now? Returns flow (open/congested/"
                          "slow/closed), whether it is passable, who is present (army, police, "
                          "settlers, inspection) as a SEPARATE fact, and how old the reading is. "
                          "Inbound and outbound can differ and are both reported.",
                          {"type": "object", "properties": {
                              "name": {"type": "string", "description": "e.g. حوارة, قلنديا, Huwara"},
                              "direction": {"type": "string", "enum": ["inbound", "outbound", "both"],
                                            "description": "direction of travel; both is the default"}},
                           "required": ["name"]}),
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
    "latest_news": (latest_news, "Most recent ingested messages, optionally filtered by area.",
                    {"type": "object", "properties": {
                        "area": {"type": "string"}, "limit": {"type": "integer"}}}),
    "coverage": (coverage, "What sources and data this system currently holds — "
                           "and, more usefully, what it holds NOTHING for. Check "
                           "this before answering a question about power, water, "
                           "cooking gas or crossings.",
                 {"type": "object", "properties": {}}),
    "crossings": (crossings, "Status of Gaza and West Bank crossings (Rafah, Kerem "
                             "Shalom, Erez, Zikim, Kissufim, Allenby...). Values are "
                             "open / partial / closed / unknown, where `partial` "
                             "means open only for some traffic and is NOT open. "
                             "Currently every crossing reads unknown because no "
                             "source reports this yet — say so plainly.",
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


def _tail_ndjson(name: str, n: int = 3) -> list[dict]:
    p = _ROOT / "ops" / name
    if not p.exists():
        return []
    lines = [x for x in p.read_text().splitlines() if x.strip()]
    return [json.loads(x) for x in lines[-n:]]


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
    return {"answer": say, "status": h.get("status"),
            "faults": h.get("faults", []),
            "jobs_ok": f"{h.get('jobs_ok')}/{h.get('jobs_total')}",
            "feeds_ok": f"{h.get('feeds_ok')}/{h.get('feeds_total')}",
            "open_alarms": alarms,
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


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, rid = req.get("method"), req.get("id")

        if method == "initialize":
            _reply(rid, {"protocolVersion": PROTOCOL,
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": "palestine-v2", "version": "2.0.0"}})
        elif method == "tools/list":
            _reply(rid, {"tools": [{"name": n, "description": d, "inputSchema": s}
                                   for n, (_, d, s) in TOOLS.items()]})
        elif method == "tools/call":
            p = req.get("params", {})
            name = p.get("name")
            if name not in TOOLS:
                _error(rid, -32602, f"unknown tool: {name}")
                continue
            try:
                from serve.mcp_en import add_english
                out = add_english(name, TOOLS[name][0](**(p.get("arguments") or {})))
            except Exception as exc:                    # noqa: BLE001
                out = {"error": str(exc), "answer": "صار خطأ بالنظام."}
            _reply(rid, {"content": [{"type": "text",
                                      "text": json.dumps(out, ensure_ascii=False, default=str)}]})
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif rid is not None:
            _error(rid, -32601, f"method not found: {method}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
