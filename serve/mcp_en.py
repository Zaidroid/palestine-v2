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
            "inspection": "a search"}


def _age(minutes: Any) -> str:
    if minutes is None:
        return "age unknown"
    m = int(minutes)
    if m < 60:
        return f"{m} min ago"
    if m < 1440:
        return f"{m // 60}h ago"
    return f"{m // 1440}d ago"


def _nm(x: dict | None, key: str = "name") -> str:
    """The English name when the payload has one, else the Arabic.

    The English answers printed عين سينيا and نابلس over payloads that
    carried `name_en` (Fawwaz's test, 2026-09-25)."""
    x = x or {}
    return (x.get(f"{key}_en") or x.get(key) or "").strip() or "?"


# ── phrases both languages share (imported by serve/mcp_server.py) ───────────
# One table per fact, so the Arabic and the English cannot say different
# things about the same record.

FIELD_WORDS = {
    "checkpoint_flow": ("حركة السير على الحواجز", "checkpoint traffic"),
    "checkpoint_status": ("حالة الحواجز (النوع القديم)", "checkpoint status (legacy kind)"),
    "checkpoint_idf": ("تواجد الجيش على الحواجز", "army at checkpoints"),
    "checkpoint_police": ("الشرطة على الحواجز", "police at checkpoints"),
    "checkpoint_inspection": ("التفتيش على الحواجز", "inspection at checkpoints"),
    "checkpoint_settlers": ("المستوطنين على الحواجز", "settlers at checkpoints"),
    "crossing_status": ("حالة المعابر", "crossing status"),
    "road_closure": ("إغلاق الطرق", "road closures"),
    "internet": ("الإنترنت", "internet"), "power": ("قطع الكهرباء", "power cuts"),
    "weather": ("الطقس", "weather"), "water": ("المي", "water"),
    "cooking_gas": ("غاز الطبخ", "cooking gas"),
    "fuel_diesel": ("توفّر السولار", "diesel availability"),
    "fuel_gasoline": ("توفّر البنزين", "petrol availability"),
}


def field_words(kind: str) -> tuple[str, str]:
    return FIELD_WORDS.get(kind, (kind.replace("_", " "), kind.replace("_", " ")))


def share_words(share: float | None) -> tuple[str, str]:
    """How much of a route a blind stretch is, in words both answers use."""
    if share is None or share < 0.4:
        return "جزء من الطريق", "part of the route"
    if share < 0.65:
        return "نص الطريق تقريباً", "about half the route"
    return "معظم الطريق", "most of the route"


def effective_groups(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Priced fuel products grouped by the date their price took effect, newest
    first. Kerosene and gas took effect on the 1st and petrol and diesel on the
    7th; one date for all eight was wrong in each language differently."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("price") is not None and r.get("effective_from"):
            groups.setdefault(str(r["effective_from"])[:10], []).append(r)
    return sorted(groups.items(), key=lambda kv: kv[0], reverse=True)


def product_labels(rows: list[dict], lang: str) -> list[str]:
    """Product names for one date group; the four gas cylinders are one word."""
    out: list[str] = []
    for r in rows:
        if str(r.get("product") or "").startswith("lpg"):
            lab = "أسطوانات الغاز" if lang == "ar" else "gas cylinders"
        else:
            lab = r.get("name_ar") if lang == "ar" else (r.get("name_en") or r.get("name_ar"))
        if lab and lab not in out:
            out.append(lab)
    return out


SEEN_ORDER = ("checkpoint_inspection", "checkpoint_idf", "checkpoint_settlers",
              "checkpoint_police")
SEEN_WORDS = {"checkpoint_inspection": ("تفتيش", "searching"),
              "checkpoint_idf": ("جيش", "army"),
              "checkpoint_settlers": ("مستوطنين", "settlers"),
              "checkpoint_police": ("شرطة", "police")}


def seen_on_route(cautions: list[dict] | None) -> list[tuple[dict, list[str], float | None]]:
    """Route cautions grouped per checkpoint, searching first, each kind once
    (state_serving carries a row per direction), with the newest sighting's age."""
    by: dict[str, dict] = {}
    for c in cautions or []:
        slot = by.setdefault(c.get("place") or "?", {"c": c, "kinds": set(), "age": None})
        slot["kinds"].add(c.get("seen"))
        a = c.get("age_minutes")
        if a is not None and (slot["age"] is None or a < slot["age"]):
            slot["age"] = a
    out = [(v["c"], [k for k in SEEN_ORDER if k in v["kinds"]], v["age"]) for v in by.values()]
    return sorted(out, key=lambda t: (SEEN_ORDER.index(t[1][0]) if t[1] else 9,
                                      t[2] if t[2] is not None else 1e9))


def searching(cp: dict | None) -> bool:
    """A fresh inspection sighting at this checkpoint (P1-A.2).

    Presence rows in the serving view are already decayed by their own
    half-life (an hour for inspection), so "present" means recently seen.
    Searching is spoken WITH the flow word — "open, with searching" — because
    to a traveller a search is a queue even when the road is open; it stays a
    separate fact in the payload (`present`, `searching`)."""
    return "inspection" in ((cp or {}).get("present") or [])


def _n(d: dict, *keys, default=0):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


# ── live ─────────────────────────────────────────────────────────────────────

def _dir_clause(row: dict | None, label: str) -> str:
    f = (row or {}).get("flow")
    if not f or f == "unknown":
        return f"no recent reading {label}"
    return f"{FLOW.get(f, f)} {label} ({_age((row or {}).get('age_minutes'))})"


_NOT_PLACED = "Place not recognised — try the Arabic spelling or a nearby town."


def _search_folds(cp: dict) -> bool:
    return searching(cp) and cp.get("flow") != "closed"


def _flow_word(cp: dict) -> str:
    """A known flow with searching folded in — the same rule as the Arabic."""
    w = FLOW.get(cp["flow"], cp["flow"])
    if not _search_folds(cp):
        return w
    return f"{w}, searching under way"


def _seen(cp: dict, fold: bool = True) -> str:
    """Who was seen there; searching left out when the flow word carries it."""
    folded = fold and (_search_folds(cp) or (cp.get("flow") == "unknown" and searching(cp)))
    order = ["inspection", "idf", "settlers", "police"]
    present = sorted(cp.get("present") or [], key=lambda p: order.index(p) if p in order else 9)
    who = [PRESENCE.get(p, p) for p in present if not (p == "inspection" and folded)]
    if not who:
        return ""
    when = f" ({_age(cp['presence_age_minutes'])})" if cp.get("presence_age_minutes") is not None else ""
    return f" Seen there: {' and '.join(who)}{when}."


def checkpoint_status(d: dict) -> str:
    if d.get("found") is False:
        if d.get("resolved_to"):
            return f"{d['resolved_to']} is a known checkpoint, but it has never been reported."
        return f"No checkpoint found matching that name."
    flow, name = d.get("flow"), _nm(d)
    tail = _seen(d)
    by = d.get("by_direction") or {}
    inb, outb = by.get("inbound") or {}, by.get("outbound") or {}
    # THE SAME FACTS THE ARABIC SENTENCE CARRIES: a direction split and a
    # doubtful name match were said in Arabic and dropped here, so an English
    # reader of "Hawara" was told "عورتا: open" while an Arabic reader was
    # told the name was a guess. Two answers from one payload name one set
    # of facts.
    known = [r for r in (inb, outb) if r.get("flow") not in (None, "unknown")]
    if (d.get("direction") == "both" and inb and outb and known
            and inb.get("flow") != outb.get("flow")):
        out = f"{name}: {_dir_clause(inb, 'inbound')}, {_dir_clause(outb, 'outbound')}.{_seen(d, fold=False)}"
    elif flow == "unknown":
        last = d.get("last_known_flow")
        lead = ""
        if searching(d):
            when = (f" ({_age(d['presence_age_minutes'])})"
                    if d.get("presence_age_minutes") is not None else "")
            lead = f"a search reported{when}; "
        if not last or last == "unknown":
            out = (f"{name}: {lead}nothing known about the traffic.{tail}" if lead
                   else f"{name}: nothing known about it.{tail}")
        else:
            out = (f"{name}: {lead}no current {'traffic ' if lead else ''}reading — last report "
                   f"{_age(d.get('age_minutes'))} said {FLOW.get(last, last)}.{tail}")
    else:
        out = f"{name}: {_flow_word(d)}. Reported {_age(d.get('age_minutes'))}"
        if _search_folds(d) and d.get("presence_age_minutes") is not None:
            out += f"; the search seen {_age(d['presence_age_minutes'])}"
        out += f".{tail}"
    score = float((d.get("match") or {}).get("score") or 0.0)
    if 0 < score < 0.8:
        out = (f"Not sure about the name — nearest match is {name}. {out} If that is "
               f"not the checkpoint you meant, try the full name or the Arabic spelling.")
    elif score < 0.9:
        out += " Note: the name matched approximately — there are checkpoints with similar names."
    return out


def checkpoints_near(d: dict) -> str:
    if d.get("error"):
        return _NOT_PLACED
    cps = [c for c in d.get("checkpoints", []) if c.get("flow") != "unknown"]
    counts = d.get("counts") or {}
    if not cps and not counts.get("in_radius"):
        r = d.get("radius_km")
        return (f"No tracked checkpoint within {r:g} km of {_nm(d, 'origin')}." if r
                else f"No tracked checkpoint in range of {_nm(d, 'origin')}.")
    if not cps:
        return (f"No recent checkpoint reports around {_nm(d, 'origin')}. "
                f"{counts.get('in_radius', 0)} are in range but their last news is old.")
    def _seen_short(c):
        s_ = _seen(c, fold=False).strip().rstrip(".").replace("Seen there: ", "")
        return f", {s_} seen" if s_ else ""
    # In a list each fact keeps its own age: the flow's, then the sighting's.
    parts = [f"{_nm(c)} {FLOW.get(c['flow'], c['flow'])} ({_age(c.get('age_minutes'))}){_seen_short(c)}"
             for c in cps[:4]]
    out = f"Around {_nm(d, 'origin')}: " + ", ".join(parts) + "."
    closed = [_nm(c) for c in cps if c["flow"] == "closed"]
    if closed:
        out += f" Watch out: {', '.join(closed)} closed."
    if counts.get("unknown"):
        out += f" {counts['unknown']} more have no recent reading."
    search_only = [c for c in d.get("checkpoints", []) if c.get("flow") == "unknown" and searching(c)]
    if search_only:
        out += " A search reported at: " + ", ".join(
            _nm(c) + (f" ({_age(c['presence_age_minutes'])})"
                      if c.get("presence_age_minutes") is not None else "")
            for c in search_only[:4]) + "."
    return out


def checkpoints_summary(d: dict) -> str:
    t = d.get("totals") or {}
    bits = [f"{t[k]} {k}" for k in ("open", "closed", "congested") if t.get(k)]
    out = "West Bank checkpoints — " + ", ".join(bits) + "." if bits else \
        "No recent checkpoint reports."
    if t.get("unknown"):
        out += f" {t['unknown']} have no recent reading."
    # The same list the Arabic speaks: each name once, then the count of
    # closed checkpoints whose name another place shares (dropped in English
    # until Fawwaz's test, 2026-09-25).
    seen: list[str] = []
    for c in d.get("closed_now") or []:
        if _nm(c) not in seen:
            seen.append(_nm(c))
    if seen:
        out += f" Closed now: {', '.join(seen[:6])}."
    dupes = len(d.get("closed_now") or []) - len(seen)
    if dupes:
        out += f" ({dupes} more closed under a shared name — names repeat across places.)"
    srch = d.get("searching_now") or []
    if srch:
        out += " Searching now at: " + ", ".join(_nm(c) for c in srch[:6]) + "."
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
    cps = d.get("checkpoints") or []
    if d.get("blocked_at"):
        blk = next((c for c in cps if c.get("name") in d["blocked_at"]
                    and c.get("age_minutes") is not None), None)
        out += (" — blocked at " + ", ".join(d["blocked_at"][:2])
                + (f" ({_age(blk['age_minutes'])})" if blk else ""))
    # Exit closures are spoken WHATEVER THE VERDICT (F011) — see the Arabic
    # renderer in serve/mcp_server.py for the case that proved it.
    doubts = d.get("doubts") or []
    exits = [x for x in doubts if x.get("kind") == "exit_closure"] or [
        dict(x, end="origin" if (x.get("along") or 0) <= 0.5 else "destination")
        for x in (d.get("exit_closures") or [])]
    why = []
    if exits:
        why.append("a closure on the way " + "; ".join(
            f"{'out of the origin' if x['end'] == 'origin' else 'into the destination'} at "
            f"{x.get('name_en') or x.get('name')} ({int(x['off_route_m'])} m off the route"
            + (f", {_age(x['age_minutes'])}" if x.get("age_minutes") is not None else "") + ")"
            for x in exits[:3]))
    blind = next((x for x in doubts if x.get("kind") == "blind_stretch"), None)
    if blind:
        why.append(f"{share_words(blind.get('share'))[1]} has no tracked checkpoint")
    low = next((x for x in doubts if x.get("kind") == "low_coverage"), None)
    if low and low.get("fraction") is not None:
        why.append(f"only {round(100 * low['fraction'])}% of it is watched by a "
                   f"checkpoint with a recent report")
    if why:
        out += ((" — because " if d.get("verdict") == "unverified" else " — but ")
                + "; and ".join(why) + ". Check before travelling")
    mins = d.get("duration_minutes")
    if mins:
        out += f". {round(mins)} min driving"
    routes = d.get("routes") or [{}]
    r0 = routes[0]
    out += (f". {r0.get('known', 0)} of {r0.get('checkpoints_on_route', 0)} "
            f"checkpoints on it have recent reports.")
    if d.get("freshest_reading_minutes") is not None:
        out += f" Newest reading {_age(d['freshest_reading_minutes'])}."
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
    # P0-B.4: the rest of Tier 1 on the way — the same facts as the Arabic.
    inc = d.get("incidents_near") or []
    if inc:
        out += (" Near the route in the last 3 hours: " + "; ".join(
            f"{i['type'].replace('_', ' ')} in {i.get('name_en') or i['name']} "
            f"({_age(i['age_minutes'])}, {i['off_route_m']} m off the route)" for i in inc[:3]) + ".")
    rc = d.get("road_closures") or []
    if rc:
        out += (" Road closures reported near the route: " + "; ".join(
            (r.get("name_en") or r["name"]) + (f" ({_age(r['age_minutes'])})" if r.get("age_minutes") is not None else "")
            for r in rc[:3]) + ".")
    for end in ("origin", "destination"):
        obs = [o for o in (d.get("obstacles_at_ends") or []) if o["end"] == end]
        if obs:
            o = obs[0]
            out += (f" Near the {end}: an OCHA-recorded {str(o['type']).lower()} ({o['name']}, "
                    f"last verified {o['verified']}) {o['metres']} m away — it may block your way out.")
    # WHO WAS SEEN ON THE WAY — searching first (P1-A.2). The route carried
    # these cautions in the payload and neither answer said them.
    seen = seen_on_route(d.get("cautions"))
    if seen:
        out += " On the way: " + "; ".join(
            f"{' and '.join(SEEN_WORDS[k][1] for k in kinds)} at {_nm(c, 'place')}"
            + (f" ({_age(age)})" if age is not None else "")
            for c, kinds, age in seen[:4]) + "."
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
    groups = effective_groups(rows)
    if len(groups) == 1:
        since = groups[0][0]
    elif groups:
        since = "; from ".join(f"{dt} for {', '.join(product_labels(g, 'en'))}"
                               for dt, g in groups)
    else:
        since = None
    out = ("Official West Bank maximum fuel prices (Petroleum Corporation)"
           + (f", in force from {since}" if since else "") + ": "
           + ("; ".join(said) if said else "none confirmed right now"))
    return out + (". " + "; ".join(gaps) if gaps else "") + "."


def incidents_near(d: dict) -> str:
    if d.get("error"):
        return _NOT_PLACED
    items = d.get("incidents") or []
    if not items:
        return (f"No incidents recorded around {d.get('origin')} in the last "
                f"{d.get('hours')} hours.")
    bits = []
    for i in items[:4]:
        where = i.get("place_en") or i["place"]
        prec = i.get("place_precision")
        if prec not in (None, "named") and i.get("named_place"):
            where = (f"{i['named_place']} ({where} governorate"
                     + (", village uncertain" if prec == "village_ambiguous" else "") + ")")
        elif prec not in (None, "named"):
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
        "outage": "A widespread internet outage is measured in the West Bank.",
        "unknown": "No current measurement of the network.",
    }
    age = d.get("age_minutes")
    when = f" Measured {_age(age)}." if age is not None else ""    # the age is spoken (P0-A.2)
    agree = ""
    if d.get("signals_agreeing") is not None and d.get("signals_total") and status != "unknown":
        agree = f" ({d['signals_agreeing']} of {d['signals_total']} signals agree.)"
    if status in known:
        return known[status] + agree + when
    return f"West Bank internet status: {status}.{when}"        # never claim silence


def crossings(d: dict) -> str:
    if d.get("no_match"):
        return (f"No crossing is registered in {d.get('area')}. Try the governorate "
                "or the crossing's name.")
    if d.get("no_source"):
        if d.get("area"):
            names = ", ".join(_nm(c) for c in (d.get("crossings") or [])[:6])
            return (f"No source reports {names}. That is absence of evidence, "
                    "not an open crossing.")
        return ("Every crossing reads unknown because no source reports crossing "
                "status yet. That is absence of evidence, not an open crossing.")
    items = d.get("crossings", [])
    known = [c for c in items if c.get("value") not in (None, "unknown")]
    out = ("Crossings — " + "; ".join(
        f"{c.get('name_en') or c['name']}: {c['value']}"
        + (f" ({_age(int(c['age_minutes']))})" if c.get("age_minutes") is not None else "")
        for c in known[:6]) + ".") if known else "No crossing has a current reading."
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
        out += f" NO source at all for: {', '.join(field_words(k)[1] for k in d['no_source'])}."
    pc = (d.get("partial_source") or {}).get("crossing_status")
    if pc:
        out += (f" Crossings: only {', '.join(pc['read_en'])} from the road channels; "
                f"{len(pc['no_source'])} crossings have no source.")
    if d.get("stale"):
        out += f" Quiet for a long time: {', '.join(field_words(k)[1] for k in d['stale'])}."
    return out


def place_profile(d: dict) -> str:
    if d.get("found") is False:
        return "Place not found."
    failed = ", ".join(d.get("errors") or {})
    bits = []
    cp = d.get("checkpoint_now") or {}
    if cp.get("flow"):
        bits.append(f"checkpoint {FLOW.get(cp['flow'], cp['flow'])} "
                    f"({_age(cp.get('age_minutes'))})")
    if d.get("incidents"):
        bits.append(f"{len(d['incidents'])} incidents in the last "
                    f"{d.get('incident_days') or 7} days")
    days = len((d.get("history") or {}).get("series") or [])
    if days:
        bits.append(f"{days} days with reports")
    res = d.get("resolved") or {}
    which = ("the checkpoint" if res.get("as_checkpoint") else "the town")
    out = (f"{_nm(d, 'place')} ({which}): " + ", ".join(bits) + "."
           if bits else f"{_nm(d, 'place')}: nothing recent held.")
    return out + (f" Could not read: {failed} — that is a failure, not an absence."
                  if failed else "")


def search(d: dict) -> str:
    if not d.get("count"):
        return "No recent message contains that text."
    return (f"{d['count']} recent messages match. Most recent: "
            f"{(d.get('items') or [{}])[0].get('text', '')[:160]}")


def _not_found(d: dict) -> str:
    """'Not found' only when nothing matched; several matches are named."""
    if d.get("ambiguous") and d.get("options"):
        return (f"More than one place is called {d.get('query')}: "
                + ", ".join(_nm(o) for o in d["options"][:4]) + " — give the fuller name.")
    return "Place not found."


def where_is(d: dict) -> str:
    if d.get("found") is False:
        return _not_found(d)
    out = f"{_nm(d)} ({d.get('kind')}) at {d.get('lat')}, {d.get('lon')}."
    if d.get("also_checkpoint"):
        out += (f" There is also a checkpoint called {_nm(d['also_checkpoint'])} — "
                "ask checkpoint_status for its state, or view=history for its record.")
    return out


def trend(d: dict) -> str:
    if d.get("refused"):
        return d.get("reason", "Refused.")
    used = d.get("place_used")
    at = ((f" (kept for {_nm(used)}" + (" governorate" if used.get("kind") == "governorate" else "")
           + ", not for the place asked on its own)") if used else "")
    if "recent_mean" not in d:
        # Not enough points: the Arabic says so; "None vs None" said nothing.
        return f"Not enough readings to compare a trend (n={d.get('n', 0)})."
    c = d.get("change_pct")
    word = d.get("direction") or ("flat" if c is None or abs(c) < 10 else
                                  ("higher" if c > 0 else "lower"))
    win = (f" over the last {d['window_days']} days" if d.get("window_days")
           else " over the whole series (too few points in the window asked for)"
           if d.get("window_widened") else "")
    out = (f"{d.get('indicator')}{win}: the last readings are {word}"
           + (f" by {abs(c)}%" if c is not None else "")
           + f" against the window's median ({d.get('recent_mean')} vs "
             f"{d.get('baseline_median')}){at}.")
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
        return ("Nothing held is comparable to this series, so no test was run. Reasons: "
                + ", ".join(f"{v} {k}" for k, v in (d.get("skipped") or {}).items()) + ".")
    top = ms[0]
    return (f"Of {d.get('tested')} series tested, the strongest is "
            f"{top['indicator']} (rho={top['rho']}, n={top['n']}). "
            + d.get("multiple_comparisons", ""))


def compare(d: dict) -> str:
    ss = d.get("series") or []
    bits = [f"{s['indicator']} ({s['n']} points, {s.get('canonical_unit') or 'no unit'}"
            + (f", read at {_nm(s['place_used'])}" if s.get("place_used") else "") + ")"
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
    if "indicators" in d:
        inds = d["indicators"]
        if not inds:
            return f"No series matched “{d.get('query')}” — try another word or a concept."
        return (f"{len(inds)} series matched “{d.get('query')}”: "
                + ", ".join(i["indicator"] for i in inds[:6]) + ".")
    return "Concepts held in the databank; pass search or concept to narrow."


def licenses(d: dict) -> str:
    if d.get("source"):
        rows = d.get("licenses") or []
        if not rows:
            return f"No served source matches {d['source']}."
        bits = []
        for r in rows[:3]:
            sell = "may be sold" if r.get("commercial_use") else "may not be sold"
            share = ", and a derived database must carry the same licence" if r.get("share_alike") else ""
            red = {"ask": "republishing needs permission", "yes": "may be republished",
                   "no": "may not be republished"}.get(r.get("redistribution"), "")
            read = (f"terms read on {r['verified_on']}" if r.get("verified_on")
                    else "nobody has read the publisher's terms")
            bits.append(f"{r['source_name']}: {r.get('license_spdx') or 'no stated licence'}, "
                        f"{int(r.get('rows_served') or 0):,} rows, {sell}{share}"
                        + (f", {red}" if red else "") + f"; {read}")
        return "; ".join(bits) + "."
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


_EVENT_EN = {"conflict.deaths.state_based": "state-based conflict events (UCDP)",
             "conflict.deaths.one_sided": "one-sided violence events (UCDP)",
             "conflict.deaths.non_state": "non-state conflict events (UCDP)",
             "conflict.journalists_killed": "journalists killed (Tech4Palestine; the source gives no dates)"}


def _displacement_en(d: dict) -> str | None:
    summ = next((s for s in d.get("event_summary") or []
                 if s["indicator"] == "displacement.locality_depopulated"), None)
    if not summ:
        return None
    by = d.get("by") or {}
    grp = ", ".join(f"{n['localities']} {n['name'] or 'unclassified'}"
                    for n in by.get("locality_group") or [])
    y0, y1 = str(summ["first"])[:4], str(summ["last"])[:4]
    out = (f"Depopulation record (Palestine Open Maps): {summ['events']:,} localities depopulated "
           + (f"in {y0}" if y0 == y1 else f"between {y0} and {y1}")
           + (f" in the {d.get('district_1945_key') or d['district']} district/subdistrict"
              if d.get("district") else "")
           + (f" — {grp}." if grp else "."))
    if not d.get("district"):
        dists = [s for s in by.get("district_1945") or [] if s["name"]]
        subs = [s for s in by.get("subdistrict_1945") or [] if s["name"]][:6]
        out += " By 1945 district: " + ", ".join(f"{s['name']} {s['localities']}" for s in dists) + "."
        if subs:
            out += (" By subdistrict (where known): "
                    + ", ".join(f"{s['name']} {s['localities']}" for s in subs) + ".")
    else:
        names: list[str] = []
        for it in d.get("items") or []:
            n = it.get("value_text") or it.get("place_en")
            if n and n not in names:
                names.append(n)
        if names:
            out += " Among them: " + ", ".join(names[:12]) + "."
    return out + (" The figure with each locality is its 1945 population (all residents), "
                  "not a refugee count — it does not add up.")


def _event_note_en(d: dict) -> str:
    bits = []
    for s in d.get("event_summary") or []:
        if s["indicator"].startswith("displacement."):
            continue
        span = "" if s.get("undated") else f" {str(s['first'])[:4]}–{str(s['last'])[:4]}"
        deaths = (f", {int(s['value_sum']):,} deaths" if s.get("value_sum") is not None
                  and not s["indicator"].endswith("journalists_killed") else "")
        bits.append(f"{s['events']:,} {_EVENT_EN.get(s['indicator'], s['indicator'])}{span}{deaths}")
    return (" Registers of single events: " + "; ".join(bits) + ".") if bits else ""


def databank(d: dict) -> str:
    if d.get("error") and d.get("categories") and not d.get("items"):
        return f"No category by that name. Categories: {', '.join(d['categories'])}."
    if d.get("categories"):
        top = sorted(d["categories"].items(), key=lambda kv: -kv[1])[:6]
        out = ("Historical databank — largest categories: "
               + ", ".join(f"{k} ({v:,})" for k, v in top)
               + f". {sum(d['categories'].values()):,} rows in {len(d['categories'])} categories, "
               f"from {d.get('datasets_with_rows') or len(d.get('datasets') or [])} datasets with rows"
               + (f" (of {d['datasets_registered']} registered)" if d.get("datasets_registered") else "")
               + ".")
        if d.get("ignored"):
            out += " as_of works with a category only — this overview is today's."
        return out
    if d.get("category") is None and d.get("indicator"):
        return f"No rows held for an indicator called {d['indicator']} — search for it with correlate."
    if d.get("category") == "displacement":
        said = _displacement_en(d)
        if said:
            return said

    # The same facts as the Arabic: latest value per indicator, the series'
    # span, the source — not a row count (F062).
    bits = []
    for it in (d.get("latest_by_indicator") or [])[:3]:
        val = it.get("value_num") if it.get("value_num") is not None else it.get("value_text")
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        elif isinstance(val, float):
            val = round(val, 2) if abs(val) >= 1 else round(val, 4)
        unit = f" {it['unit']}" if it.get("unit") else ""
        when = str(it.get("occurred_at") or "")[:4 if it.get("occurred_precision") == "year" else 10]
        partial = " (partial year)" if (it.get("attrs") or {}).get("partial_year") else ""
        where = f", {it['place_en'] or it['place_ar']}" if it.get("place_en") or it.get("place_ar") else ""
        bits.append((f"{it.get('indicator')}: {val:,}{unit} in {when}{partial}{where}"
                     if isinstance(val, (int, float)) else
                     f"{it.get('indicator')}: {val} in {when}{where}"))
    spans = d.get("series_span") or {}
    lo = sorted(v["from"] for v in spans.values() if v.get("from"))
    hi = sorted(v["to"] for v in spans.values() if v.get("to"))
    span = f" Series {lo[0][:4]}→{hi[-1][:4]}." if lo and hi else ""
    src = "; ".join(d.get("attribution") or [])[:120].rstrip(". ")
    if not bits:
        return (f"No matching rows in {d.get('category')}"
                + (f" as of {d['as_of']}" if d.get("as_of") else "") + ".")
    return (f"{d.get('category')}" + (f" as of {d['as_of']}" if d.get("as_of") else "")
            + " — latest: " + "; ".join(bits) + "." + (f" Source: {src}." if src else "") + span
            + f" (newest {d.get('count', 0)} rows shown.)" + _event_note_en(d)
            + "".join(f" Note: {w['en']}" for ind, w in (d.get("warnings") or {}).items()
                      if w.get("en") and any(it.get("indicator") == ind
                                             for it in d.get("latest_by_indicator") or [])))


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
    tracked = ck.get("places_now")
    if definite:
        said = ", ".join(f"{v} {k}" for k, v in sorted(definite.items(), key=lambda kv: -kv[1]))
        out += (f". Of {tracked} tracked now, " if tracked else ". Right now ") + \
            f"{sum(definite.values())} have a definite reading: {said}"
    if ck.get("unknown_now"):
        out += f", and {ck['unknown_now']} have no recent reading at all"
    fresh = ck.get("freshest_reading_minutes")
    if fresh is not None:
        out += f". Newest reading {_age(int(fresh))}"
    top = (ck.get("most_reported") or [])[:3]
    if top:
        out += ". Most reported: " + ", ".join(
            f"{r.get('name_en') or r['name_ar']} ({r['readings']:,} readings)" for r in top)
    changing = (ck.get("changing") or [])[:3]
    if changing:
        out += ". Actually changing: " + ", ".join(
            f"{r.get('name_en') or r['name_ar']} ({r['distinct_values']} states)" for r in changing)
    hours = [h["hour"] for h in (ck.get("busiest_hours_hebron") or [])[:3]]
    if hours:
        out += ". Busiest hours, local time: " + ", ".join(f"{h}:00" for h in hours)
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
           f"{live.get('checkpoints_tracked', 0)} tracked checkpoints"
           + (f", {live['checkpoints_with_current_reading']} of them with a current reading."
              if live.get("checkpoints_with_current_reading") is not None else "."))
    if live.get("no_source"):
        out += " NO source at all for: " + ", ".join(field_words(k)[1] for k in live["no_source"]) + "."
    pc = (live.get("partial_source") or {}).get("crossing_status")
    if pc:
        out += (f" Crossings: only {', '.join(pc['read_en'])} from the road channels, "
                f"and {len(pc['no_source'])} crossings with no source.")
    if live.get("stale"):
        out += " Quiet for a long time: " + ", ".join(field_words(k)[1] for k in live["stale"]) + "."
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
        return _not_found(d)
    if not d.get("series"):
        return f"No saved history for {_nm(d, 'place')} yet."
    flow = d.get("flow_totals") or {}
    out = f"{_nm(d, 'place')}, last {d.get('days')} days"
    if flow:
        n = sum(flow.values())
        said = ", ".join(f"{v} {FLOW.get(k, k)}" for k, v in sorted(flow.items(), key=lambda kv: -kv[1]))
        out += f": {n} road reports — {said}"
        worst = max(d.get("series") or [{}], key=lambda day: ((day.get("kinds") or {})
                    .get("checkpoint_flow") or {}).get("values", {}).get("closed", 0))
        wc = ((worst.get("kinds") or {}).get("checkpoint_flow") or {}).get("values", {}).get("closed", 0)
        if wc:
            out += f"; worst day {worst.get('day')} ({wc} closed reports)"
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
        return _not_found(d)
    tally = d.get("usually_by_hour_tally") or {}
    if not tally:
        return f"Not enough reports about {_nm(d, 'place')} to infer a pattern."
    modal, n_modal = max(tally.items(), key=lambda kv: kv[1])
    known = [h for h in (d.get("hours") or []) if h.get("usually") not in (None, "unknown")]
    out = (f"{_nm(d, 'place')}: usually {FLOW.get(modal, modal)} — {n_modal} of {len(known)} "
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
