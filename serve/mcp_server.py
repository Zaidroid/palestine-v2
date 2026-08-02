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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

PROTOCOL = "2024-11-05"
API = os.environ.get("PALESTINE_API", "http://127.0.0.1:7870")
FUEL_AR = {"fuel_diesel": "سولار", "fuel_gasoline": "بنزين", "cooking_gas": "غاز"}


def api(path: str, **params) -> dict:
    """GET the v2 API. Raises on failure so the caller can answer honestly
    rather than inventing a reassuring reply."""
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

def fuel_near(place: str | None = None, lat: float | None = None,
              lon: float | None = None, fuel: str = "diesel", limit: int = 5) -> dict:
    """Where can I get diesel/petrol right now?"""
    fuel = {"سولار": "diesel", "بنزين": "gasoline", "غاز": "gas",
            "petrol": "gasoline"}.get(fuel.lower(), fuel.lower())

    if lat is None or lon is None:
        if not place:
            return {"answer": "لازم تحدد المكان.", "error": "need place or lat/lon"}
        geo = api("/v2/geo/resolve", q=place)
        if not geo.get("found"):
            return {"answer": f"ما عرفت وين {place}.", "error": "place not resolved"}
        lat, lon, place = geo["lat"], geo["lon"], geo["name"]

    d = api("/v2/fuel/nearby", lat=lat, lon=lon, fuel=fuel, limit=limit, radius_km=60)
    label = {"diesel": "سولار", "gasoline": "بنزين", "gas": "غاز"}.get(fuel, fuel)
    res = d.get("results", [])

    if not res:
        answer = f"ما في ولا محطة فيها {label} حالياً حسب آخر تحديث."
    else:
        parts = []
        for r in res[:3]:
            approx = "" if r.get("location_note") is None else " (الموقع تقريبي)"
            dist = (f"{r['drive_minutes']:.0f} دقيقة بالسيارة"
                    if r.get("drive_minutes") is not None
                    else f"{r.get('straight_km') or 0:.0f} كم")
            parts.append(f"{r['name']} على بعد {dist}{approx}")
        answer = (f"في {len(res)} محطة فيها {label}: " + "، ".join(parts) +
                  f". آخر تحديث {_age_ar(res[0].get('age_minutes'))}.")

    return {"answer": answer, "fuel": label,
            "origin": place or f"{lat:.4f},{lon:.4f}",
            "count": len(res), "counts": d.get("counts"),
            "routing": d.get("routing"),
            "stations": [{
                "name": r["name"], "region": r.get("region"),
                "drive_minutes": r.get("drive_minutes"),
                "straight_km": r.get("straight_km"),
                "value": r["value"], "confidence": r["confidence"],
                "age_minutes": r.get("age_minutes"),
                "staleness_band": r.get("staleness_band"),
                "location_precise": r.get("location_note") is None,
            } for r in res],
            "source": d.get("attribution")}


def fuel_summary() -> dict:
    d = api("/v2/fuel/summary")
    h = api("/health")
    bits = [f"{FUEL_AR.get('fuel_' + k, k)}: {v['available']} من {v['total']} محطة"
            for k, v in d.get("totals", {}).items()]
    age = h.get("feed_age_minutes")
    return {"answer": "وضع الوقود بالضفة — " + "، ".join(bits) +
                      f". آخر تحديث {_age_ar(age)}.",
            "totals": d.get("totals"), "by_region": d.get("by_region"),
            "feed_age_minutes": age, "source": d.get("attribution")}


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
    return {"answer": f"عندي {d['total_claims']} رسالة من {len(d['sources'])} مصدر، "
                      f"و{sum(d['live_states'].values())} حالة مباشرة.",
            **d}



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


TOOLS = {
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
    "fuel_near": (fuel_near, "Which stations have diesel/petrol right now, nearest first. "
                             "Give `place` (Arabic or English name) or lat/lon.",
                  {"type": "object", "properties": {
                      "place": {"type": "string", "description": "e.g. نابلس, Ramallah"},
                      "lat": {"type": "number"}, "lon": {"type": "number"},
                      "fuel": {"type": "string", "enum": ["diesel", "gasoline", "gas"]},
                      "limit": {"type": "integer"}}}),
    "fuel_summary": (fuel_summary, "West-Bank-wide fuel availability totals.",
                     {"type": "object", "properties": {}}),
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
    "coverage": (coverage, "What sources and data this system currently holds.",
                 {"type": "object", "properties": {}}),
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
                out = TOOLS[name][0](**(p.get("arguments") or {}))
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
