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
    by = d.get("by_direction") or {}
    inb, outb = by.get("inbound") or {}, by.get("outbound") or {}
    # THE SAME FACTS THE ARABIC SENTENCE CARRIES: a direction split and a
    # doubtful name match were said in Arabic and dropped here, so an English
    # reader of "Hawara" was told "عورتا: open" while an Arabic reader was
    # told the name was a guess. Two answers from one payload name one set
    # of facts.
    if (d.get("direction") == "both" and inb.get("flow") and outb.get("flow")
            and inb["flow"] != outb["flow"]
            and "unknown" not in (inb["flow"], outb["flow"])):
        out = (f"{name}: {FLOW.get(inb['flow'], inb['flow'])} inbound, "
               f"{FLOW.get(outb['flow'], outb['flow'])} outbound.{tail}")
    elif flow == "unknown":
        last = d.get("last_known_flow")
        if not last or last == "unknown":
            out = f"{name}: nothing known about it.{tail}"
        else:
            out = (f"{name}: no current reading — last report {_age(d.get('age_minutes'))} "
                   f"said {FLOW.get(last, last)}.{tail}")
    else:
        out = (f"{name}: {FLOW.get(flow, flow)}, reported {_age(d.get('age_minutes'))}."
               f"{tail}")
    score = float((d.get("match") or {}).get("score") or 0.0)
    if 0 < score < 0.8:
        out = (f"Not sure about the name — nearest match is {name}. {out} If that is "
               f"not the checkpoint you meant, try the full name or the Arabic spelling.")
    elif score < 0.9:
        out += " Note: the name matched approximately — there are checkpoints with similar names."
    return out


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
           # NOT "probably passable". Nothing seen is closed, but the evidence
           # does not cover the journey — see corridor._score.
           "unverified": "Cannot confirm this route is open",
           "unknown": "No recent reports on this route"}.get(
        d.get("verdict"), str(d.get("verdict")))
    out = say
    if d.get("blocked_at"):
        out += " — blocked at " + ", ".join(d["blocked_at"][:2])
    if d.get("verdict") == "unverified":
        why = []
        exits = [x for x in (d.get("doubts") or []) if x.get("kind") == "exit_closure"]
        if exits:
            why.append("a closure on the way " + "; ".join(
                f"{'out of the origin' if x['end'] == 'origin' else 'into the destination'} at "
                f"{x.get('name_en') or x.get('name')} ({int(x['off_route_m'])} m off the route"
                + (f", {_age(x['age_minutes'])}" if x.get("age_minutes") is not None else "") + ")"
                for x in exits[:3]))
        if any(x.get("kind") == "blind_stretch" for x in d.get("doubts") or []):
            why.append("most of the route has no tracked checkpoint")
        if why:
            out += " — because " + "; and ".join(why) + ". Check before travelling"
    mins = d.get("duration_minutes")
    if mins:
        out += f". {round(mins)} min driving"
    routes = d.get("routes") or [{}]
    r0 = routes[0]
    out += (f". {r0.get('known', 0)} of {r0.get('checkpoints_on_route', 0)} "
            f"checkpoints on it have recent reports.")
    # WHICH ROAD THIS IS, AND WHERE THE VERDICT IS BLIND. Both qualify the
    # sentence above, so they follow it — and the measured case is in
    # resolve/corridor.py:_corridor_for: 53 km with the first on-route checkpoint
    # at 26.9 km, which "2 of 8 have recent reports" cannot convey.
    # `passes` and `coverage` are TOP-LEVEL on the payload; the per-route dict is
    # a skinny allowlist that carries `coverage` only. Reading `passes` off
    # routes[0] silently returned nothing, so the English answer dropped the
    # waypoints the Arabic one names — the same one-language-only defect this
    # function was just fixed for, one line further down.
    waypoints = [w.get("name_en") or w["name"] for w in (d.get("passes") or [])][:5]
    if waypoints:
        out += f" It passes {', '.join(waypoints)}."
    cov = (d.get("routes") or [{}])[0].get("coverage") or {}
    if cov.get("longest_gap_km") and cov.get("coverage_fraction", 1.0) < 0.8:
        out += (f" No checkpoint is tracked for {cov['longest_gap_km']:.0f} km of "
                f"this route ({cov['longest_gap_from_km']:.0f} to "
                f"{cov['longest_gap_to_km']:.0f} km in), so that stretch is "
                f"unverified.")
    # THE ENGLISH ANSWER HAS TO SAY WHAT THE ARABIC ONE SAYS. The Arabic sentence
    # names a closure just outside the corridor; the English one did not, so an
    # English reader was told "probably passable" with no mention of the closed
    # checkpoint 2 km away while an Arabic reader was told about it. Two answers
    # built from the same fields must carry the same facts.
    exit_ids = {x.get("name") for x in (d.get("exit_closures") or [])}
    nm = [m for m in (d.get("near_misses") or [])
          if m.get("flow") == "closed" and m.get("name") not in exit_ids]
    if nm:
        w = nm[0]
        age = w.get("age_minutes")
        when = f" {int(age)} minutes ago" if age is not None else ""
        others = len(nm) - 1
        extra = (f" and {others} more nearby closures" if others > 1
                 else " and one more nearby" if others == 1 else "")
        out += (f" Warning: {w.get('name_en') or w.get('name')} was closed{when}, "
                f"{w.get('off_route_m')} m off this route — it may not stop you, "
                f"but know it{extra}.")
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
    bits = []
    for i in items[:4]:
        where = i.get("place_en") or i["place"]
        if i.get("place_precision") == "governorate" and i.get("named_place"):
            where = f"{i['named_place']} ({where} governorate)"
        elif i.get("place_precision") == "governorate":
            where = f"{where} governorate (village not resolved)"
        bits.append(f"{i['type'].replace('_', ' ')} in {where} {_age(_mins(i.get('occurred_at')))}")
    out = f"Around {d.get('origin')}: " + ", ".join(bits) + "."
    solo = sum(1 for i in items if (i.get("independent_sources") or 0) < 2)
    if solo:
        out += f" ({solo} reported by a single source only.)"
    fires = (d.get("fires") or {}).get("n")
    if fires:
        out += f" Satellite fire detections in range: {fires} (no reports)."
    out += _precision_en(d.get("precision"))
    return out


def _mins(iso) -> int | None:
    from datetime import datetime, timezone
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - t).total_seconds() // 60)
    except (ValueError, TypeError):
        return None


def incidents_summary(d: dict) -> str:
    bt = d.get("by_type") or {}
    if not bt:
        return f"No incidents recorded in the last {d.get('hours')} hours."
    bits = [f"{v['n']} {k.replace('_', ' ')}" for k, v in
            sorted(bt.items(), key=lambda kv: -kv[1]["n"])[:5]]
    # the tool names the window `window_hours`; reading `hours` printed None
    out = f"In the last {d.get('window_hours') or d.get('hours')}h: " + \
          ", ".join(bits) + "."
    places = ", ".join(p["place"] for p in (d.get("by_place") or [])[:4])
    if places:
        out += f" Worst affected: {places}."
    fires = (d.get("fires") or {}).get("n")
    if fires:
        out += f" Satellite fire detections: {fires}."
    out += _precision_en(d.get("precision"))
    return out


def _precision_en(precision: dict | None) -> str:
    weak = (precision or {}).get("weak") or []
    if not weak:
        return ""
    bits = [f"{w['type'].replace('_', ' ')} {round(w['precision'] * 100)} %" for w in weak[:3]]
    rnd = (precision or {}).get("round")
    return (" Machine-read precision on the last hand check" + (f" (round {rnd})" if rnd else "") +
            ": " + ", ".join(bits) + ".")


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
    if len(govs) == 1:
        return (f"{h['governorate']}: {str(h.get('advisory', 'normal')).replace('_', ' ')}, "
                f"{h.get('temp_now_c')}°C now, high {(h.get('today') or {}).get('max_c')}°C.")
    return (f"Normal across the West Bank. Hottest: {h['governorate']} "
            f"{(h.get('today') or {}).get('max_c')}°C.")


def connectivity_now(d: dict) -> str:
    """The status vocabulary is `normal`/`degraded`/`outage`/`unknown` — the
    renderer knew `ok`, so every healthy reading fell through to its default and
    the English sentence said "No current measurement of the network" while the
    payload said status=normal, two minutes old. A default that asserts absence
    is the worst kind: it invents a gap exactly where there is a measurement.
    """
    status = d.get("status")
    known = {
        "normal": "West Bank internet is reachable and behaving normally.",
        "ok": "West Bank internet is reachable and behaving normally.",
        "degraded": "West Bank internet quality is measurably degraded.",
        "outage": (f"A widespread internet outage is measured in the West "
                   f"Bank ({d.get('signals_agreeing')} independent signals agree)."),
        "unknown": "No current measurement of the network.",
    }
    if status in known:
        return known[status]
    return f"West Bank internet status: {status}."        # never claim silence


def crossings(d: dict) -> str:
    if d.get("no_source"):
        return ("Every crossing reads unknown because no source reports crossing "
                "status yet. That is absence of evidence, not an open crossing.")
    items = d.get("crossings", [])
    known = [c for c in items if c.get("value") not in (None, "unknown")]
    out = "Crossings — " + "; ".join(
        f"{c.get('name_en') or c['name']}: {c['value']}"
        + (f" ({_age(int(c['age_minutes']))})" if c.get("age_minutes") is not None else "")
        for c in known[:6]) + "."
    decayed = [c for c in items if c not in known and c.get("basis")]
    if decayed:
        out += " No current reading: " + "; ".join(
            f"{c.get('name_en') or c['name']} (last known {c.get('last_known_value') or 'unknown'}"
            + (f" {_age(int(c['age_minutes']))}" if c.get("age_minutes") is not None else "") + ")"
            for c in decayed[:4]) + "."
    unsourced = [c for c in items if not c.get("basis")]
    if unsourced:
        out += (" NO source reports " + ", ".join(c.get("name_en") or c["name"] for c in unsourced[:6])
                + " — that is not 'open', it is unmeasured.")
    return out


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
    if "recent_mean" not in d:
        # Not enough points: the Arabic says so; "None vs None" said nothing.
        return f"Not enough readings to compare a trend (n={d.get('n', 0)})."
    c = d.get("change_pct")
    word = ("flat" if c is None or abs(c) < 10 else
            ("higher" if c > 0 else "lower"))
    out = (f"{d.get('indicator')}: the last readings are {word}"
           + (f" by {abs(c)}%" if c is not None else "")
           + f" against the historical median ({d.get('recent_mean')} vs "
             f"{d.get('baseline_median')}).")
    age = d.get("last_age_days")
    if d.get("last"):
        out += f" Newest reading {str(d['last'])[:10]}"
        if age:
            out += f", {age} days ago"
        out += "."
        if age and age > 45:
            out += " The series has stopped; read the trend with that age in mind."
    return out + (f" {d.get('caveat')}" if d.get("caveat") else "")


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


def insights(d: dict) -> str:
    scope = d.get("scope") or {}
    ck = d.get("checkpoints") or {}
    inc = d.get("incidents") or {}
    name = scope.get("name_en") or scope.get("name") or scope.get("query") or "that place"
    out = (f"Last {scope.get('days')} days around {name} "
           f"({scope.get('radius_km'):g} km): {ck.get('readings', 0):,} checkpoint "
           f"readings across "
           f"{ck.get('places_in_window', ck.get('places', 0))} checkpoints")
    now = ck.get("now") or {}
    definite = {k: v for k, v in now.items() if k != "unknown"}
    if definite:
        said = ", ".join(f"{v} {k}" for k, v in sorted(definite.items(), key=lambda kv: -kv[1]))
        out += f". Right now {sum(definite.values())} have a definite reading: {said}"
    if ck.get("unknown_now"):
        out += f", and {ck['unknown_now']} have no recent reading at all"
    fresh = ck.get("freshest_reading_minutes")
    if fresh is not None:
        out += f". Newest reading is {int(fresh)} minutes old"
    top = (ck.get("most_reported") or [])[:3]
    if top:
        out += ". Most reported: " + ", ".join(
            f"{r['name_ar']} ({r['readings']:,} readings)" for r in top)
    rows = [r for r in (inc.get("by_type") or []) if r.get("type") != "fire_detection"]
    if rows:
        out += ". Incidents in the window: " + ", ".join(
            f"{r['events']} {r['type'].replace('_', ' ')} "
            f"({r['corroborated']} corroborated)" for r in rows[:6])
    fires = (inc.get("fires") or {}).get("n")
    if fires:
        out += f". Satellite fire detections: {fires} (no reports)"
    qy = (d.get("quality") or {}).get("incidents") or {}
    if qy.get("state") == "below gate":
        out += (f". Accuracy note: the incident classifier measures "
                f"{qy['precision']:.0%} against its {qy['gate']:.0%} gate, so read "
                f"those counts as a lower-confidence signal")
    return out + (". A reading is what a channel reported, not an official count; "
                  "no reading does not mean open.")


def licence_tools(d: dict) -> str:
    c = d.get("partner_tier_counts") or {}
    bits = []
    if c.get("full"):
        bits.append(f"{c['full']} may be carried away whole (our own derived "
                    f"observations)")
    if c.get("excerpt"):
        bits.append(f"{c['excerpt']} return an excerpt only — the channels own "
                    f"their wording and we hold no licence to republish it")
    if c.get("filtered"):
        bits.append(f"{c['filtered']} read the databank, where each row carries "
                    f"its own licence")
    if c.get("cited_fact_only"):
        bits.append(f"{c['cited_fact_only']} may travel as a cited fact only")
    out = (f"Of {d.get('public_tools')} public tools, {d.get('graded')} are "
           f"graded: " + "; ".join(bits) + ".")
    if d.get("ungraded"):
        out += (f" Warning: {len(d['ungraded'])} tool(s) carry no grade yet — "
                f"do not redistribute their output.")
    return out + (" A grade says what you may REDISTRIBUTE, not what you may "
                  "read.")


def about(d: dict) -> str:
    live, db, st = d.get("live") or {}, d.get("databank") or {}, d.get("stream") or {}
    out = (f"Palestine Data: {int(live.get('messages') or 0):,} messages from "
           f"{live.get('sources', 0)} sources, "
           f"{sum((live.get('live_states') or {}).values()):,} live states over "
           f"{live.get('checkpoints_tracked', 0)} tracked checkpoints.")
    if live.get("no_source"):
        out += " NO source at all for: " + ", ".join(live["no_source"]) + "."
    if live.get("stale"):
        out += " Quiet for a long time: " + ", ".join(live["stale"]) + "."
    out += (f" Databank: {int(db.get('rows') or 0):,} rows in {db.get('categories', 0)} "
            f"categories")
    if db.get("failing_supply_lines"):
        out += f", with {db['failing_supply_lines']} supply lines failing"
    out += ". Live stream " + ("running." if st.get("running") else "stopped.")
    return out


def latest_news(d: dict) -> str:
    items = d.get("items") or []
    if not items:
        return "No new messages" + (f" about {d['area']}." if d.get("area") else ".")
    first = items[0]
    what = {"news": "news items", "roads": "road bulletins", "all": "messages"}.get(
        d.get("kind"), "messages")
    text = " ".join(str(first.get("text") or "").split())[:160]
    return (f"Newest {len(items)} {what}; the latest, {_age(first.get('age_minutes'))} "
            f"from {first.get('source')}: {text}")


def place_history(d: dict) -> str:
    if d.get("found") is False:
        return "Place not found."
    if not d.get("series"):
        return f"No saved history for {d.get('place')} yet."
    flow = d.get("flow_totals") or {}
    out = f"{d.get('place')}, last {d.get('days')} days"
    if flow:
        n = sum(flow.values())
        said = ", ".join(f"{v} {FLOW.get(k, k)}" for k, v in sorted(flow.items(), key=lambda kv: -kv[1]))
        out += f": {n} road reports — {said}"
    else:
        out += f": {d.get('days_with_data')} days with reports"
    seen = []
    for kind, word in (("checkpoint_idf", "army"), ("checkpoint_settlers", "settlers"),
                       ("checkpoint_police", "police"), ("checkpoint_inspection", "inspection")):
        n = ((d.get("totals_by_kind") or {}).get(kind) or {}).get("present", 0)
        if n:
            seen.append(f"{word} {n}×")
    if seen:
        out += "; sighted: " + ", ".join(seen)
    u = d.get("max_independent_units_per_day")
    if u:
        out += f"; up to {u} independent reporters in a day"
    return out + ". Counts are reports, not time."


def place_pattern(d: dict) -> str:
    if d.get("found") is False:
        return "Place not found."
    tally = d.get("usually_by_hour_tally") or {}
    if not tally:
        return f"Not enough reports about {d.get('place')} to infer a pattern."
    modal, n_modal = max(tally.items(), key=lambda kv: kv[1])
    known = [h for h in (d.get("hours") or []) if h.get("usually") not in (None, "unknown")]
    out = (f"{d.get('place')}: usually {FLOW.get(modal, modal)} — {n_modal} of {len(known)} "
           f"hours with enough reports.")
    congested = [f"{h['hour']:02d}:00" for h in known if h.get("usually") == "congested"]
    if congested and modal != "congested":
        out += " Congested hours: " + ", ".join(congested[:8]) + "."
    closed = [f"{h['hour']:02d}:00" for h in known if h.get("usually") == "closed"]
    if closed:
        out += " Closed hours: " + ", ".join(closed[:6]) + "."
    return out + " A pattern is what was reported at that hour, not what was true."


def area_history(d: dict) -> str:
    ranked = d.get("ranked_by_closed_share") or []
    govs = d.get("governorates") or {}
    if not ranked:
        return f"Last {d.get('days')} days across {len(govs)} governorates — no road reports in the window."
    top = ", ".join(f"{r['governorate']} ({r['closed']} of {r['reports']} reports closed)"
                    for r in ranked[:3])
    last = ranked[-1]
    return (f"Last {d.get('days')} days across {len(govs)} governorates. Most closures: {top}. "
            f"Fewest: {last['governorate']} ({last['closed']} of {last['reports']}).")


def stream_info(d: dict) -> str:
    if not d.get("running"):
        return "The live stream is stopped — no live updates right now."
    age = d.get("last_poll_age_seconds")
    return (f"Live stream running — {int(d.get('watched_states') or 0):,} states watched"
            + (f", last checked {int(age)} s ago" if age is not None else "")
            + f". Subscribe at {d.get('url', '/v2/stream')} (server-sent events).")


RENDERERS: dict[str, Callable[[dict], str]] = {
    "about": about,
    "latest_news": latest_news, "place_history": place_history,
    "place_pattern": place_pattern, "area_history": area_history,
    "stream_info": stream_info,
    "fuel_prices": fuel_prices,
    "checkpoint_status": checkpoint_status, "checkpoints_near": checkpoints_near,
    "checkpoints_summary": checkpoints_summary, "can_i_travel": can_i_travel,
    "incidents_near": incidents_near, "incidents_summary": incidents_summary,
    "weather_now": weather_now, "connectivity_now": connectivity_now,
    "crossings": crossings, "coverage": coverage, "place_profile": place_profile,
    "search": search, "where_is": where_is, "trend": trend,
    "what_correlates_with": what_correlates_with, "compare": compare,
    "correlate": correlate, "licenses": licenses, "data_gaps": data_gaps,
    "databank": databank, "insights": insights,
    "licence_tools": licence_tools,
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
