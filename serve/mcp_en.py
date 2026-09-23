"""The same answer in English, built from the data rather than translated.

Every tool answers in Arabic, which was right when the callers were Fawwaz,
Sameera and a voice bot for people in the West Bank. It is a wall for everyone
else: a caller with no Arabic gets one sentence they cannot read and a blob of
JSON, and the sentence is the part that carries the uncertainty.

WHY NOT JUST LET THE MODEL TRANSLATE
Because the Arabic sentence exists precisely to stop the caveats being
rephrased. "ما في تحديث جديد — آخر معلومة قبل ساعتين: كان سالك" survives one
translation and loses its hedge on the next; a model with a helpful tone renders
it "the checkpoint is open". The English is therefore built from the same
structured fields the Arabic is built from — two renderings of one set of facts,
neither derived from the other, so neither can drift into confidence the data
does not support.

WHERE A TOOL ALREADY SPEAKS ENGLISH
The databank tools return `plain_english`, `reason` and `caveat` written by the
statistics layer. Those are used verbatim. Re-describing them here would be a
second place to keep the same wording correct.

A tool with no renderer returns nothing rather than something clumsy. A missing
`answer_en` is a gap a reader can see; a bad one is a claim they cannot check.
"""
from __future__ import annotations

from typing import Any, Callable

FLOW = {"open": "open", "closed": "closed", "congested": "congested",
        "slow": "slow", "unknown": "no recent reading"}
PRESENCE = {"idf": "army", "police": "police", "settlers": "settlers",
            "inspection": "inspection"}


def _age(minutes: Any) -> str:
    if minutes is None:
        return "age unknown"
    m = int(minutes)
    if m < 60:
        return f"{m} min ago"
    if m < 1440:
        return f"{m // 60}h ago"
    return f"{m // 1440}d ago"


def _n(d: dict, *keys, default=0):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


# ── live ─────────────────────────────────────────────────────────────────────

def checkpoint_status(d: dict) -> str:
    if d.get("found") is False:
        return f"No checkpoint found matching that name."
    flow, name = d.get("flow"), d.get("name")
    who = [PRESENCE.get(p, p) for p in (d.get("present") or [])]
    tail = f" {' and '.join(who)} present." if who else ""
    if flow == "unknown":
        last = d.get("last_known_flow")
        if not last or last == "unknown":
            return f"{name}: nothing known about it.{tail}"
        return (f"{name}: no current reading — last report {_age(d.get('age_minutes'))} "
                f"said {FLOW.get(last, last)}.{tail}")
    return (f"{name}: {FLOW.get(flow, flow)}, reported {_age(d.get('age_minutes'))}."
            f"{tail}")


def checkpoints_near(d: dict) -> str:
    cps = [c for c in d.get("checkpoints", []) if c.get("flow") != "unknown"]
    counts = d.get("counts") or {}
    if not cps:
        return (f"No recent checkpoint reports around {d.get('origin')}. "
                f"{counts.get('in_radius', 0)} are in range but their last news is old.")
    parts = [f"{c['name']} {FLOW.get(c['flow'], c['flow'])}" for c in cps[:4]]
    out = f"Around {d.get('origin')}: " + ", ".join(parts) + "."
    closed = [c["name"] for c in cps if c["flow"] == "closed"]
    if closed:
        out += f" Closed: {', '.join(closed)}."
    if counts.get("unknown"):
        out += f" {counts['unknown']} more have no recent reading."
    return out


def checkpoints_summary(d: dict) -> str:
    t = d.get("totals") or {}
    bits = [f"{t[k]} {k}" for k in ("open", "closed", "congested") if t.get(k)]
    out = "West Bank checkpoints — " + ", ".join(bits) + "." if bits else \
        "No recent checkpoint reports."
    if t.get("unknown"):
        out += f" {t['unknown']} have no recent reading."
    closed = [c["name"] for c in (d.get("closed_now") or [])[:6]]
    if closed:
        out += f" Closed now: {', '.join(closed)}."
    return out


def can_i_travel(d: dict) -> str:
    say = {"likely_open": "The route is probably passable",
           "slow": "The route is passable but congested",
           "blocked": "The route is blocked",
           "unknown": "No recent reports on this route"}.get(
        d.get("verdict"), str(d.get("verdict")))
    out = say
    if d.get("blocked_at"):
        out += " — blocked at " + ", ".join(d["blocked_at"][:2])
    mins = d.get("duration_minutes")
    if mins:
        out += f". {round(mins)} min driving"
    routes = d.get("routes") or [{}]
    r0 = routes[0]
    out += (f". {r0.get('known', 0)} of {r0.get('checkpoints_on_route', 0)} "
            f"checkpoints on it have recent reports.")
    return out


def fuel_prices(d: dict) -> str:
    if "history" in d:
        rows = d.get("history") or []
        if not rows:
            return "No confirmed prices recorded for that product."
        last = rows[-1]
        return (f"Latest confirmed price {last['price']:g} shekels from {last['effective_from']}; "
                f"{len(rows)} confirmed prices on record.")
    rows = d.get("prices") or []
    said, gaps = [], []
    for r in rows:
        unit = "shekels per litre" if r["unit"] == "ILS/L" else "shekels"
        if r["price"] is not None:
            said.append(f"{r['name_en']} {r['price']:g} {unit}")
        elif r["status"] == "awaiting_list":
            gaps.append(f"{r['name_en']}: this month's list not read yet "
                        f"(last confirmed {r['last_confirmed_price']:g} from {r['last_confirmed_from']})")
        elif r["status"] in ("unconfirmed", "conflicting"):
            gaps.append(f"{r['name_en']}: {r['status']}")
    since = next((r["effective_from"] for r in rows if r["price"] is not None), None)
    out = ("Official West Bank maximum fuel prices (Petroleum Corporation)"
           + (f", in force from {since}" if since else "") + ": "
           + ("; ".join(said) if said else "none confirmed right now"))
    return out + (". " + "; ".join(gaps) if gaps else "") + "."


def incidents_near(d: dict) -> str:
    items = d.get("incidents") or []
    if not items:
        return (f"No incidents recorded around {d.get('origin')} in the last "
                f"{d.get('hours')} hours.")
    bits = [f"{i['type'].replace('_', ' ')} in {i['place']}" for i in items[:4]]
    out = f"Around {d.get('origin')}: " + ", ".join(bits) + "."
    solo = sum(1 for i in items if (i.get("independent_sources") or 0) < 2)
    if solo:
        out += f" ({solo} reported by a single source only.)"
    return out


def incidents_summary(d: dict) -> str:
    bt = d.get("by_type") or {}
    if not bt:
        return f"No incidents recorded in the last {d.get('hours')} hours."
    bits = [f"{v['n']} {k.replace('_', ' ')}" for k, v in
            sorted(bt.items(), key=lambda kv: -kv[1]["n"])[:5]]
    out = f"In the last {d.get('hours')}h: " + ", ".join(bits) + "."
    places = ", ".join(p["place"] for p in (d.get("by_place") or [])[:4])
    if places:
        out += f" Worst affected: {places}."
    return out


def weather_now(d: dict) -> str:
    notable = d.get("notable") or []
    govs = d.get("governorates") or []
    if not govs:
        return "No weather data available."
    if notable:
        bits = [f"{n['governorate']} {n['advisory'].replace('_', ' ')} "
                f"({(n.get('today') or {}).get('max_c')}°C)" for n in notable]
        return "Weather advisories: " + ", ".join(bits) + "."
    h = govs[0]
    return (f"Normal across the West Bank. Hottest: {h['governorate']} "
            f"{(h.get('today') or {}).get('max_c')}°C.")


def connectivity_now(d: dict) -> str:
    return {"outage": (f"A widespread internet outage is measured in the West "
                       f"Bank ({d.get('signals_agreeing')} independent signals agree)."),
            "degraded": "West Bank internet quality is measurably degraded.",
            "ok": "West Bank internet is reachable and behaving normally.",
            }.get(d.get("status"), "No current measurement of the network.")


def crossings(d: dict) -> str:
    if d.get("no_source"):
        return ("Every crossing reads unknown because no source reports crossing "
                "status yet. That is absence of evidence, not an open crossing.")
    known = [c for c in d.get("crossings", []) if c.get("value") not in (None, "unknown")]
    return "; ".join(f"{c['name']}: {c['value']}" for c in known[:6])


def coverage(d: dict) -> str:
    out = (f"{d.get('total_claims')} messages from {len(d.get('sources') or [])} "
           f"sources, {sum((d.get('live_states') or {}).values())} live states.")
    if d.get("no_source"):
        out += f" NO source at all for: {', '.join(d['no_source'])}."
    if d.get("stale"):
        out += f" Quiet for a long time: {', '.join(d['stale'])}."
    return out


def place_profile(d: dict) -> str:
    if d.get("found") is False:
        return "Place not found."
    bits = []
    cp = d.get("checkpoint_now") or {}
    if cp.get("flow"):
        bits.append(f"checkpoint {FLOW.get(cp['flow'], cp['flow'])} "
                    f"({_age(cp.get('age_minutes'))})")
    if d.get("incidents"):
        bits.append(f"{len(d['incidents'])} recent incidents")
    days = len((d.get("history") or {}).get("series") or [])
    if days:
        bits.append(f"{days} days with reports")
    res = d.get("resolved") or {}
    which = ("the checkpoint" if res.get("as_checkpoint") else "the town")
    return (f"{d.get('place')} ({which}): " + ", ".join(bits) + "."
            if bits else f"{d.get('place')}: nothing recent held.")


def search(d: dict) -> str:
    if not d.get("count"):
        return "No recent message contains that text."
    return (f"{d['count']} recent messages match. Most recent: "
            f"{(d.get('items') or [{}])[0].get('text', '')[:160]}")


def where_is(d: dict) -> str:
    if d.get("found") is False:
        return "Place not found."
    return f"{d.get('name')} ({d.get('kind')}) at {d.get('lat')}, {d.get('lon')}."


def trend(d: dict) -> str:
    if d.get("refused"):
        return d.get("reason", "Refused.")
    c = d.get("change_pct")
    word = ("flat" if c is None or abs(c) < 10 else
            ("higher" if c > 0 else "lower"))
    return (f"{d.get('indicator')}: the last readings are {word}"
            + (f" by {abs(c)}%" if c is not None else "")
            + f" against the historical median ({d.get('recent_mean')} vs "
              f"{d.get('baseline_median')}). {d.get('caveat', '')}")


def what_correlates_with(d: dict) -> str:
    if d.get("refused"):
        return "Cannot scan: " + " ".join(d.get("reasons", []))[:200]
    ms = d.get("matches") or []
    if not ms:
        return ("Nothing held is comparable to this series. Reasons: "
                + ", ".join(f"{v} {k}" for k, v in (d.get("skipped") or {}).items()))
    top = ms[0]
    return (f"Of {d.get('tested')} series tested, the strongest is "
            f"{top['indicator']} (rho={top['rho']}, n={top['n']}). "
            + d.get("multiple_comparisons", ""))


def compare(d: dict) -> str:
    ss = d.get("series") or []
    bits = [f"{s['indicator']} ({s['n']} points, {s.get('canonical_unit') or 'no unit'})"
            for s in ss]
    ov = d.get("overlap") or {}
    return ("Comparing " + ", ".join(bits) +
            (f". Shared window {ov.get('from')} to {ov.get('to')} "
             f"({ov.get('n')} dates)." if ov.get("n")
             else ". These series share no dates."))


def correlate(d: dict) -> str:
    if d.get("refused"):
        return "Refused: " + " ".join(d.get("reasons", []))[:300]
    if d.get("plain_english"):
        return (f"{d['plain_english']} (n={d.get('n')}, 95% CI {d.get('ci95')})."
                + (" " + d["caveats"][0] if d.get("caveats") else ""))
    if d.get("indicators"):
        return f"{len(d['indicators'])} series matched."
    return "Concepts held in the databank; pass search or concept to narrow."


def licenses(d: dict) -> str:
    t = d.get("tiers") or {}
    return (f"{t.get('open', 0):,} rows are republishable with attribution, "
            f"{t.get('commercial_permissive', 0):,} are sellable with no further "
            f"obligation, and {t.get('commercial_sharealike', 0):,} carry a "
            f"share-alike licence: sellable, but a derived database must carry "
            f"the same licence.")


def data_gaps(d: dict) -> str:
    c = d.get("counts") or {}
    return (f"Gap radar: of {c.get('datasets')} series — {c.get('fresh')} fresh, "
            f"{c.get('late')} late, {c.get('stalled')} stalled, "
            f"{c.get('dead_upstream')} whose upstream has died.")


def databank(d: dict) -> str:
    if d.get("categories"):
        top = sorted(d["categories"].items(), key=lambda kv: -kv[1])[:5]
        return ("Historical databank — largest categories: "
                + ", ".join(f"{k} ({v:,})" for k, v in top)
                + f". {sum(d['categories'].values()):,} rows total.")
    return (f"{d.get('count', 0)} rows from {d.get('category')}"
            + (f" as of {d['as_of']}" if d.get("as_of") else "") + ".")


RENDERERS: dict[str, Callable[[dict], str]] = {
    "fuel_prices": fuel_prices,
    "checkpoint_status": checkpoint_status, "checkpoints_near": checkpoints_near,
    "checkpoints_summary": checkpoints_summary, "can_i_travel": can_i_travel,
    "incidents_near": incidents_near, "incidents_summary": incidents_summary,
    "weather_now": weather_now, "connectivity_now": connectivity_now,
    "crossings": crossings, "coverage": coverage, "place_profile": place_profile,
    "search": search, "where_is": where_is, "trend": trend,
    "what_correlates_with": what_correlates_with, "compare": compare,
    "correlate": correlate, "licenses": licenses, "data_gaps": data_gaps,
    "databank": databank,
}


def add_english(tool: str, out: Any) -> Any:
    """Attach `answer_en` when this tool has a renderer. Never raises: a
    formatting bug here must not take down an answer about a road."""
    if not isinstance(out, dict) or "answer_en" in out:
        return out
    fn = RENDERERS.get(tool)
    if fn is None:
        return out
    try:
        text = fn(out)
    except Exception:                                       # noqa: BLE001
        return out
    if text:
        out["answer_en"] = text.strip()
    return out
