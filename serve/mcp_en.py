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

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

FLOW = {"open": "open", "closed": "closed", "congested": "congested",
        "slow": "slow", "unknown": "no recent reading"}
PRESENCE = {"idf": "army", "police": "police", "settlers": "settlers",
            "inspection": "inspection"}
# The route payload names a sighting by its state kind, not by who was seen.
PRESENCE_KIND = {"checkpoint_idf": "idf", "checkpoint_settlers": "settlers",
                 "checkpoint_police": "police", "checkpoint_inspection": "inspection"}


def _age(minutes: Any) -> str:
    """119 minutes used to read "1h ago": a two-hour-old closure spoken at half
    its age. Under six hours the minutes are kept ("1h 59m ago"); past that the
    hour is rounded, not floored. A negative age is clock skew on a future
    timestamp and reads as now, never as "-3 min ago"."""
    if minutes is None:
        return "age unknown"
    m = int(minutes)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    if m < 360:
        h, rem = divmod(m, 60)
        return f"{h}h {rem}m ago" if rem else f"{h}h ago"
    if m < 1440:
        return f"{round(m / 60)}h ago"
    return f"{m // 1440}d ago"


# ── facts both languages speak, chosen once ──────────────────────────────────
# The Arabic sentence (serve/mcp_server.py) imports these. Deciding in two
# places WHICH facts a sentence carries is how the two answers drifted: a
# direction split said in one language, an alternate route in the other. The
# wording stays per language; the selection is made here, once.

def direction_split(d: dict) -> list[tuple[str, dict | None]] | None:
    """For a direction=both answer: the per-direction rows to speak, or None
    to speak the undirected row.

    The undirected row is built from undirected readings ONLY (migration 027,
    `s.direction = t.dir OR s.direction = 'both'` with t.dir = 'both'), so a
    fresh "قلنديا دخول مغلق" never reaches it: the answer read the decayed row
    and said "no new update — last report 3 h ago said open" while the
    payload's inbound row said closed nine minutes ago. A known direction is
    therefore never hidden behind the undirected row: whenever one is known
    and that row is unknown, disagrees with it, or the two directions differ,
    both directions are spoken, each with its own age."""
    if (d.get("direction") or "both") != "both":
        return None
    by = d.get("by_direction") or {}
    rows = {k: by.get(k) for k in ("inbound", "outbound")}
    known = {k: r for k, r in rows.items()
             if r and r.get("flow") not in (None, "unknown")}
    if not known:
        return None
    flows = {r["flow"] for r in known.values()}
    general = d.get("flow")
    if general in (None, "unknown") or len(flows) > 1 or general not in flows:
        return [(k, rows[k]) for k in ("inbound", "outbound")]
    return None


def general_also(d: dict, split: list) -> bool:
    """Whether a split answer should also give the undirected reading: only
    when it is current AND says something the directions do not."""
    general = d.get("flow")
    if general in (None, "unknown"):
        return False
    rows = [r for _, r in split]
    known = [r for r in rows if r and r.get("flow") not in (None, "unknown")]
    return len(known) < len(rows) or general not in {r["flow"] for r in known}


def exit_end(x: dict) -> str:
    """'origin' or 'destination' for an exit closure. Doubt records carry
    `end`; the payload's `exit_closures` carry `along` (0 at the origin)."""
    if x.get("end") in ("origin", "destination"):
        return x["end"]
    return "origin" if (x.get("along") or 0) <= 0.5 else "destination"


def spaced(items: list, n: int) -> list:
    """At most n items, evenly spaced, always keeping the first and the last.
    `passes` is sorted by position, so a plain [:5] of eight dropped the
    destination third of the road — the stretch with the decisive checkpoints."""
    if len(items) <= n:
        return list(items)
    idx = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
    return [items[i] for i in idx]


def route_facts(d: dict) -> dict:
    """What BOTH route answers speak, from the can_i_travel payload.

    EXIT CLOSURES ARE SPOKEN WHATEVER THE VERDICT. They were subtracted from
    the near-miss warning (as "already the reason") and then spoken only when
    the verdict was `unverified` — but `_score` returns slow/blocked/unknown
    before it computes doubts, so the audit's own case, "passable, congested
    at Za'tara" with Ein Siniya closed on the way out of Ramallah, went silent
    again. Every exit closure is now at least counted, the nearest three
    named, and none of them is repeated as a separate "nearby closure"."""
    cps = d.get("checkpoints") or []
    by_name = {c.get("name"): c for c in cps}
    known_ages = [c["age_minutes"] for c in cps
                  if c.get("flow") not in (None, "unknown")
                  and c.get("age_minutes") is not None]
    exits = list(d.get("exit_closures") or []) or \
        [x for x in (d.get("doubts") or []) if x.get("kind") == "exit_closure"]
    exits.sort(key=lambda x: x.get("off_route_m") or 0)
    exit_names = {x.get("name") for x in exits}
    near = [m for m in (d.get("near_misses") or [])
            if m.get("flow") == "closed" and m.get("name") not in exit_names]

    def named(names: list) -> list[dict]:
        return [{"name": n, "name_en": (by_name.get(n) or {}).get("name_en"),
                 "age_minutes": (by_name.get(n) or {}).get("age_minutes")}
                for n in names]

    routes = d.get("routes") or []
    # The best route is an ALTERNATE: the direct road ranked below it, and the
    # sentence has to say why rather than presenting a 66-minute detour as the
    # way to go.
    detour = (next((r for r in routes if r.get("is_alternate") is False), None)
              if d.get("is_alternate") else None)
    # Ranking puts `blocked` last, so a blocked best route means every route
    # is blocked; the old "بديل" branch looked for a passable one that cannot
    # exist and never spoke.
    others_blocked = (len(routes) - 1 if d.get("verdict") == "blocked" and len(routes) > 1
                      and all(r.get("verdict") == "blocked" for r in routes[1:]) else 0)
    return {
        "exits": exits, "exits_spoken": exits[:3], "exits_more": max(0, len(exits) - 3),
        "near": near,
        "blind": next((x for x in (d.get("doubts") or [])
                       if x.get("kind") == "blind_stretch"), None),
        "blocked": named(d.get("blocked_at") or [])[:2],
        "slow": named(d.get("congested_at") or [])[:2],
        "newest": min(known_ages, default=None), "oldest": max(known_ages, default=None),
        "cautions": (d.get("cautions") or [])[:3],
        "waypoints": spaced(d.get("passes") or [], 5),
        "detour": detour, "others_blocked": others_blocked,
    }


def _unanswered(tool: str, d: dict) -> str | None:
    """One English sentence for the failure shapes the tools return, rendered
    BEFORE any renderer sees them.

    `{answer: "ما عرفت وين X.", error: "place not resolved"}` went through
    checkpoints_near's empty branch and came out "No recent checkpoint reports
    around None. 0 are in range but their last news is old." — an unresolved
    name read, in English, as a quiet road. A failure is said as a failure and
    never as an absence of reports."""
    err, q = d.get("error"), d.get("query")
    named = f": {q}" if q else ""
    if err == "need place or lat/lon":
        return "Give a place name or coordinates."
    if err == "place not resolved" or (d.get("found") is False
                                       and tool not in _OWN_NOT_FOUND):
        return (f"Place not recognised{named} — try the Arabic spelling or a nearby "
                f"town. Nothing is being said about that area.")
    if err and tool == "databank":
        return (f"No databank category named{named}; call databank with no "
                f"category to list them.")
    if err:
        return f"This could not be answered: {err}."
    return None


def _n(d: dict, *keys, default=0):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


# ── live ─────────────────────────────────────────────────────────────────────

def checkpoint_not_found(d: dict) -> str:
    """The three found:false shapes of /v2/checkpoints/status are three facts.
    `resolved_to` is a checkpoint we know and nobody has ever reported — the
    `no source` state, not an unknown name; `nearest` is a lookalike the API
    refused to speak for; only a bare `query` is a name we do not know."""
    near = d.get("nearest") or {}
    if d.get("uncertain") and near.get("name"):
        return (f"No checkpoint has the name {d.get('query')}; the nearest-looking name "
                f"is {near['name']}, and its status is not given — a lookalike name is "
                f"not the checkpoint you asked about. Try the full or the Arabic name.")
    if d.get("resolved_to"):
        return (f"{d['resolved_to']} is a checkpoint we know, but no source has ever "
                f"reported it — that is unmeasured, not open.")
    return (f"No checkpoint found matching {d.get('query')}." if d.get("query")
            else "No checkpoint found matching that name.")


def checkpoint_body(d: dict) -> str:
    """Everything after "{name}: " — flow, age, direction split, sightings.
    Shared by checkpoint_status and place_profile so a checkpoint is described
    the same way wherever it is spoken."""
    flow = d.get("flow")
    who = [PRESENCE.get(p, p) for p in (d.get("present") or [])]
    tail = f"; {' and '.join(who)} present" if who else ""
    # THE SAME FACTS THE ARABIC SENTENCE CARRIES: a direction split and a
    # doubtful name match were said in Arabic and dropped here, so an English
    # reader of "Hawara" was told "عورتا: open" while an Arabic reader was
    # told the name was a guess. Two answers from one payload name one set
    # of facts — and each direction carries its OWN age: "open inbound,
    # closed outbound" with no age could be three minutes or five hours old.
    split = direction_split(d)
    if split:
        parts = [(f"{FLOW.get(r['flow'], r['flow'])} {k} ({_age(r.get('age_minutes'))})"
                  if r and r.get("flow") not in (None, "unknown")
                  else f"no recent reading {k}") for k, r in split]
        out = ", ".join(parts) + tail
        if general_also(d, split):
            out += (f". Last undirected report: {FLOW.get(flow, flow)} "
                    f"({_age(d.get('age_minutes'))})")
        return out
    if flow == "unknown":
        last = d.get("last_known_flow")
        if not last or last == "unknown":
            return f"nothing known about it{tail}"
        return (f"no current reading — last report {_age(d.get('age_minutes'))} "
                f"said {FLOW.get(last, last)}{tail}")
    return f"{FLOW.get(flow, flow)}, reported {_age(d.get('age_minutes'))}{tail}"


def checkpoint_status(d: dict) -> str:
    if d.get("found") is False:
        return checkpoint_not_found(d)
    name = d.get("name")
    # The Arabic says "قلنديا للخارج: مغلق"; this said "قلنديا: closed", which
    # read aloud asserts both directions while inbound was open.
    scope = f" ({d['direction']})" if d.get("direction") in ("inbound", "outbound") else ""
    out = f"{name}{scope}: {checkpoint_body(d)}."
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
    origin = d.get("origin") or "here"
    if not cps:
        # "0 are in range but their last news is old" was false twice over:
        # nothing is tracked there, so nothing is stale.
        if not counts.get("in_radius"):
            return f"No tracked checkpoint within range of {origin}."
        return (f"No recent checkpoint reports around {origin}. "
                f"{counts['in_radius']} are in range but their last news is old.")
    # Each flow with its own age and sightings, as the Arabic says it: "open"
    # three minutes ago and "open" three hours ago are different answers.
    parts = []
    for c in cps[:4]:
        who = [PRESENCE.get(p, p) for p in (c.get("present") or [])]
        parts.append(f"{c['name']} {FLOW.get(c['flow'], c['flow'])} "
                     f"({_age(c.get('age_minutes'))}"
                     + (f"; {' and '.join(who)} present" if who else "") + ")")
    out = f"Around {origin}: " + ", ".join(parts) + "."
    closed = [c["name"] for c in cps if c["flow"] == "closed"]
    if closed:
        out += f" Closed: {', '.join(closed)}."
    if counts.get("unknown"):
        out += f" {counts['unknown']} more have no recent reading."
    return out


def _closed_dirs(c: dict) -> str:
    """"(inbound)" when a checkpoint is closed in one direction only — the
    summary counts a place by its WORST direction, and "closed" alone would
    tell the other direction's traveller their road is shut."""
    dirs = set(c.get("closed_directions") or [])
    if not dirs or "both" in dirs or {"inbound", "outbound"} <= dirs:
        return ""
    return f" ({', '.join(sorted(dirs))})"


def checkpoints_summary(d: dict) -> str:
    t = d.get("totals") or {}
    bits = [f"{t[k]} {k}" for k in ("open", "closed", "congested") if t.get(k)]
    out = "West Bank checkpoints — " + ", ".join(bits) + "." if bits else \
        "No recent checkpoint reports."
    if t.get("unknown"):
        out += f" {t['unknown']} have no recent reading."
    # Named once, as the Arabic does: two distinct places share النبي يونس and
    # "النبي يونس, النبي يونس" read as a duplicated row.
    closed = d.get("closed_now") or []
    seen: dict[str, dict] = {}
    for c in closed:
        seen.setdefault(c["name"], c)
    if seen:
        out += " Closed now: " + ", ".join(
            f"{n}{_closed_dirs(c)}" for n, c in list(seen.items())[:6]) + "."
    dupes = len(closed) - len(seen)
    if dupes:
        out += (f" (and {dupes} more closed under a shared name — names are shared "
                f"between different places)")
    return out


VERDICT_EN = {"likely_open": "The route is probably passable",
              "slow": "The route is passable but congested",
              "blocked": "The route is blocked",
              # NOT "probably passable". Nothing seen is closed, but the
              # evidence does not cover the journey — see corridor._score.
              "unverified": "Cannot confirm this route is open",
              "unknown": "No recent reports on this route"}
VERDICT_WORD_EN = {"likely_open": "is probably passable", "slow": "is congested",
                   "blocked": "is blocked", "unverified": "cannot be confirmed open",
                   "unknown": "has no recent reports"}


def _place_of(end: Any) -> str | None:
    return (end or {}).get("place") if isinstance(end, dict) else None


def can_i_travel(d: dict) -> str:
    if d.get("found") is False:
        return (f"Could not place {d.get('query') or 'one of those places'}; "
                f"no route was computed.")
    o, t = _place_of(d.get("origin")), _place_of(d.get("destination"))
    if not d.get("verdict"):
        # "None. 0 of 0 checkpoints on it have recent reports." was this branch.
        return ("Could not compute a route"
                + (f" from {o} to {t}" if o and t else " between those places") + ".")
    f = route_facts(d)
    # THE RESOLVED PLACES, SAID. A fuzzy resolution of the origin answered about
    # a different journey and nothing in either sentence showed it.
    out = (f"From {o} to {t}: " if o and t else "") + \
        VERDICT_EN.get(d.get("verdict"), "No recent reports on this route")

    def nm(x: dict) -> str:
        return x.get("name_en") or x.get("name")

    def aged(x: dict) -> str:
        return nm(x) + (f" ({_age(x['age_minutes'])})" if x.get("age_minutes") is not None else "")
    # WHERE, AND HOW OLD. "blocked at Za'tara" with no age, and "congested"
    # with no place at all, left the traveller unable to weigh either.
    if f["blocked"]:
        out += " — blocked at " + ", ".join(aged(x) for x in f["blocked"])
    elif f["slow"] and d.get("verdict") == "slow":
        out += " — congested at " + ", ".join(aged(x) for x in f["slow"])
    out += "."
    if f["detour"]:
        p = f["detour"]
        out += (f" The direct road ({round(p.get('duration_minutes') or 0)} min) "
                f"{VERDICT_WORD_EN.get(p.get('verdict'), 'has no recent reports')}"
                + (f" at {', '.join((p.get('blocked_at') or [])[:2])}"
                   if p.get("blocked_at") else "")
                + ", so this is an alternative.")
    if f["others_blocked"]:
        out += f" Every alternative ({f['others_blocked']}) is blocked too."
    mins = d.get("duration_minutes")
    if mins:
        out += f" {round(mins)} min driving."

    exits = ""
    if f["exits_spoken"]:
        exits = "a closure on the way " + "; ".join(
            f"{'out of ' + (o or 'the origin') if exit_end(x) == 'origin' else 'into ' + (t or 'the destination')} at "
            f"{nm(x)} ("
            + ", ".join(v for v in (
                f"{int(x['off_route_m'])} m off the route" if x.get("off_route_m") is not None else "",
                _age(x["age_minutes"]) if x.get("age_minutes") is not None else "") if v)
            + ")" for x in f["exits_spoken"])
        more = f["exits_more"]
        if more:
            exits += (f"; and {more} more closures at the ends of the route" if more > 1
                      else "; and one more closure at an end of the route")
    blind = ""
    if f["blind"]:
        b = f["blind"]
        blind = (f"no tracked checkpoint for {b.get('km') or 0:.0f} km"
                 + (f" ({b['from_km']:.0f}–{b['to_km']:.0f} km in)"
                    if b.get("from_km") is not None and b.get("to_km") is not None else ""))
    if d.get("verdict") == "unverified":
        why = [w for w in (exits, blind) if w]
        if why:
            out += " Because " + "; and ".join(why) + " — check before travelling."
    elif exits:
        out += " Warning: " + exits + " — check before travelling."

    routes = d.get("routes") or [{}]
    r0 = routes[0]
    out += (f" {r0.get('known', 0)} of {r0.get('checkpoints_on_route', 0)} "
            f"checkpoints on it have recent reports")
    if f["newest"] is not None:
        out += (f" (newest {_age(f['newest'])}"
                + (f", oldest {_age(f['oldest'])}" if int(f["oldest"]) != int(f["newest"]) else "")
                + ")")
    out += "."
    if f["cautions"]:
        out += " Seen on the route: " + "; ".join(
            f"{PRESENCE.get(PRESENCE_KIND.get(c.get('seen'), c.get('seen')), c.get('seen'))} "
            f"at {c.get('place')}"
            + (f" ({_age(c['age_minutes'])})" if c.get("age_minutes") is not None else "")
            for c in f["cautions"]) + "."
    # WHICH ROAD THIS IS, AND WHERE THE VERDICT IS BLIND. Both qualify the
    # sentence above, so they follow it — and the measured case is in
    # resolve/corridor.py:_corridor_for: 53 km with the first on-route checkpoint
    # at 26.9 km, which "2 of 8 have recent reports" cannot convey.
    # `passes` and `coverage` are TOP-LEVEL on the payload. The registry does
    # not flag settlements, so the list is said as landmarks NEAR the road,
    # never as towns it goes through (the audit heard Ofra and Mevo Shillo).
    if f["waypoints"]:
        out += (f" It passes near {', '.join(w.get('name_en') or w['name'] for w in f['waypoints'])}"
                f" (landmarks along the road; the registry does not mark settlements).")
    cov = (d.get("routes") or [{}])[0].get("coverage") or {}
    if (not (blind and d.get("verdict") == "unverified")
            and cov.get("longest_gap_km") and cov.get("coverage_fraction", 1.0) < 0.8):
        out += (f" No checkpoint is tracked for {cov['longest_gap_km']:.0f} km of "
                f"this route ({cov['longest_gap_from_km']:.0f} to "
                f"{cov['longest_gap_to_km']:.0f} km in), so that stretch is "
                f"unverified.")
    # THE ENGLISH ANSWER HAS TO SAY WHAT THE ARABIC ONE SAYS. The Arabic sentence
    # names a closure just outside the corridor; the English one did not, so an
    # English reader was told "probably passable" with no mention of the closed
    # checkpoint 2 km away while an Arabic reader was told about it. Two answers
    # built from the same fields must carry the same facts.
    if f["near"]:
        w = f["near"][0]
        age = w.get("age_minutes")
        others = len(f["near"]) - 1
        extra = (f" and {others} more nearby closures" if others > 1
                 else " and one more nearby" if others == 1 else "")
        out += (f" Warning: {nm(w)} was closed"
                + (f" {_age(age)}" if age is not None else "")
                + f", {w.get('off_route_m')} m off this route — it may not stop you, "
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
            # A product nobody ever confirmed has no last price: formatting
            # None with :g raised, and the whole list lost its English.
            last = (f"last confirmed {r['last_confirmed_price']:g} from "
                    f"{r['last_confirmed_from']}"
                    if r.get("last_confirmed_price") is not None
                    else "no earlier confirmed price")
            gaps.append(f"{r['name_en']}: this month's list not read yet ({last})")
        elif r["status"] in ("unconfirmed", "conflicting"):
            # What the outlets printed, as the Arabic lists it.
            rep = ", ".join(f"{x['price']:g}" for x in (r.get("reported") or [])
                            if x.get("price") is not None)
            gaps.append(f"{r['name_en']}: {r['status']}" + (f" (published: {rep})" if rep else ""))
    # Kerosene and LPG came into force on 1 Sep, petrol and diesel on the 7th;
    # the Arabic was fixed for naming one date for every product and this was
    # not, so the English dated petrol's price six days early.
    dates = sorted({r["effective_from"] for r in rows
                    if r["price"] is not None and r.get("effective_from")})
    since = (dates[0] if len(dates) == 1 else
             f"{dates[0]} (the newest from {dates[-1]})" if dates else None)
    out = ("Official West Bank maximum fuel prices (Petroleum Corporation)"
           + (f", in force from {since}" if since else "") + ": "
           + ("; ".join(said) if said else "none confirmed right now"))
    return out + (". " + "; ".join(gaps) if gaps else "") + "."


def incident_where_en(i: dict) -> str:
    """Where an incident happened, as precisely as the pin was earned. Any
    precision other than `named` is a governorate row: a twin-named village
    (`village_ambiguous`) sits on its governorate's row, which for Ramallah is
    named "Ramallah", and read as "raid in Ramallah" — the city named as the
    site, exactly what gate G3 forbids."""
    where = i.get("place_en") or i.get("place")
    prec = i.get("place_precision") or "named"
    if prec == "named":
        return where
    if i.get("named_place"):
        return (f"{i['named_place']} ({where} governorate"
                + (" — more than one village has that name" if prec == "village_ambiguous" else "")
                + ")")
    return f"{where} governorate (village not resolved)"


def incidents_near(d: dict) -> str:
    items = d.get("incidents") or []
    if not items:
        return (f"No incidents recorded around {d.get('origin') or 'there'} in the last "
                f"{d.get('hours') or '?'} hours.")
    bits = []
    for i in items[:4]:
        where = incident_where_en(i)
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
    # the tool names the window `window_hours`; reading `hours` printed None —
    # fixed for the non-empty sentence first, and the empty one kept printing
    # "in the last None hours".
    hours = d.get("window_hours") or d.get("hours")
    if not bt:
        window = (f"the last {hours} hour{'' if hours == 1 else 's'}" if hours
                  else "this window")
        return f"No incidents recorded in {window}."
    bits = [f"{v['n']} {k.replace('_', ' ')}" for k, v in
            sorted(bt.items(), key=lambda kv: -kv[1]["n"])[:5]]
    out = f"In the last {hours}h: " + ", ".join(bits) + "."
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
    # Every weak type, not the first three: round 8 has four under the gate
    # and land_levelling (0.667) was dropped from speech. The list is short
    # by construction — only served types under the gate are in it.
    bits = [f"{w['type'].replace('_', ' ')} {round(w['precision'] * 100)} %" for w in weak]
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
    out = ("Crossings — " + "; ".join(
        f"{c.get('name_en') or c['name']}: {c['value']}"
        + (f" ({_age(int(c['age_minutes']))})" if c.get("age_minutes") is not None else "")
        for c in known[:6]) + "." if known
        else "No crossing has a current reading.")
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


_SECTION_EN = {"checkpoint": "checkpoint status", "history": "report history",
               "pattern": "hourly pattern", "incidents": "incidents"}


def place_profile(d: dict) -> str:
    if d.get("found") is False:
        return "Place not found."
    bits = []
    cp = d.get("checkpoint_now") or {}
    if cp.get("flow"):
        label = ("checkpoint" if cp.get("name") in (None, d.get("place"))
                 else f"{cp['name']} checkpoint")
        bits.append(f"{label}: {checkpoint_body(cp)}")
    n_inc, win = len(d.get("incidents") or []), d.get("incident_window_days")
    if "incidents" not in (d.get("errors") or {}) and d.get("incidents") is not None and win:
        bits.append(f"{n_inc} incidents within 10 km in the last {win} days" if n_inc
                    else f"no incidents recorded within 10 km in the last {win} days")
    days = len((d.get("history") or {}).get("series") or [])
    if days:
        bits.append(f"{days} days with reports")
    res = d.get("resolved") or {}
    which = ("the checkpoint" if res.get("as_checkpoint") else "the town")
    out = (f"{d.get('place')} ({which}): " + "; ".join(bits) + "."
           if bits else f"{d.get('place')}: nothing recent held.")
    # A section that failed is said as a failure — never as a quiet place.
    errs = [_SECTION_EN.get(k, k) for k in (d.get("errors") or {})]
    if errs:
        out = (f"{d.get('place')}: " + "; ".join(bits) + "." if bits else
               f"{d.get('place')}:") + f" Could not read: {', '.join(errs)}."
    return out


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
    win = d.get("window_days")
    if "recent_mean" not in d:
        # Not enough points: the Arabic says so; "None vs None" said nothing.
        return (f"Not enough readings to compare a trend (n={d.get('n', 0)}"
                + (f", within the last {win} days" if win else "") + ").")
    c = d.get("change_pct")
    word = ("flat" if c is None or abs(c) < 10 else
            ("higher" if c > 0 else "lower"))
    base = f"the median of the last {win} days" if win else "the historical median"
    out = (f"{d.get('indicator')}: the last readings are {word}"
           + (f" by {abs(c)}%" if c is not None else "")
           + f" against {base} ({d.get('recent_mean')} vs "
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
        skipped = d.get("skipped") or {}
        if not skipped and d.get("tested") is None:
            # No reasons and no tests is a scan that did not run — never
            # "nothing held is comparable", a false statement about the data.
            return "The scan did not run, so nothing is said about this series."
        return ("Nothing held is comparable to this series. Reasons: "
                + ", ".join(f"{v} {k}" for k, v in skipped.items()))
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
        # The lag and every caveat, not caveats[0]: the first is always "not
        # causation", and a lag-scanned fit — the best of up to 61 shifts —
        # read as a same-day finding while the Arabic said "lag 3d".
        lag = d.get("lag_days")
        return (f"{d['plain_english']} (n = {d.get('n')}, 95% CI {d.get('ci95')}"
                + (f", at a lag of {lag} days" if lag else "") + "). "
                + " ".join(d.get("caveats") or []))
    if d.get("indicators"):
        return (f"{len(d['indicators'])} series matched: "
                + ", ".join(i.get("indicator", "?") for i in d["indicators"][:6]) + ".")
    top = [c for c in (d.get("concepts") or []) if c.get("rows_served")][:8]
    if top:
        return ("Largest concepts in the databank: "
                + ", ".join(f"{c.get('name_en') or c.get('name_ar')} "
                            f"({int(c['rows_served']):,})" for c in top)
                + ". Pass search or concept to narrow.")
    return "Concepts held in the databank; pass search or concept to narrow."


def licenses(d: dict) -> str:
    if not d.get("tiers"):
        # A source filter that matched nothing carries no tiers; reading them
        # as zeros said "0 rows are republishable" — a licensing statement a
        # partner could act on.
        return (f"No served source matches {d.get('query')!r}." if d.get("query")
                else "No served source matches that name.")
    t = d.get("tiers") or {}
    return (f"{t.get('open', 0):,} rows are republishable with attribution, "
            f"{t.get('commercial_permissive', 0):,} are sellable with no further "
            f"obligation, and {t.get('commercial_sharealike', 0):,} carry a "
            f"share-alike licence: sellable, but a derived database must carry "
            f"the same licence.")


def data_gaps(d: dict) -> str:
    c = d.get("counts") or {}
    out = (f"Gap radar: of {c.get('datasets')} series — {c.get('fresh')} fresh, "
           f"{c.get('late')} late, {c.get('stalled')} stalled, "
           f"{c.get('dead_upstream')} whose upstream has died.")
    # The same gaps and candidates the Arabic names — counts alone told an
    # English reader nothing about WHICH supply lines are failing.
    top = [g for g in (d.get("gaps") or []) if (g.get("severity") or 0) >= 3][:5]
    if top:
        out += " Top gaps: " + "; ".join(
            f"{g.get('subject')} ({str(g.get('measure') or '')[:60]})" for g in top) + "."
    cands = (d.get("scout") or {}).get("top_candidates") or []
    if cands:
        out += (" The scout found candidate sources to fill them, notably: "
                + "; ".join(str(x.get("title") or "")[:50] for x in cands[:3]) + ".")
    return out


def databank_when(it: dict) -> str:
    """When a databank row happened, at the precision it was recorded with. A
    row of `unknown` precision is dated to its SERIES START (2009-01-01 for the
    OCHA locality totals) and was read as an event on that day; it is a
    cumulative total over its coverage window, which attrs carries."""
    prec = it.get("occurred_precision")
    attrs = it.get("attrs") or {}
    if prec == "unknown":
        if attrs.get("coverage_start") and attrs.get("coverage_end"):
            return f"cumulative {attrs['coverage_start']} to {attrs['coverage_end']}"
        return "date not recorded"
    return str(it.get("occurred_at") or "")[:4 if prec == "year" else 10]


def databank(d: dict) -> str:
    if d.get("categories"):
        top = sorted(d["categories"].items(), key=lambda kv: -kv[1])[:5]
        return ("Historical databank — largest categories: "
                + ", ".join(f"{k} ({v:,})" for k, v in top)
                + f". {sum(d['categories'].values()):,} rows total.")
    when = f" as of {d['as_of']}" if d.get("as_of") else ""
    latest = d.get("latest_by_indicator") or []
    if not latest:
        return f"No matching rows in {d.get('category') or 'that category'}{when}."
    # THE HEADLINE IS THE LATEST FIGURE, NOT A ROW COUNT — in English too.
    # "5 rows from demolitions" was the true-and-empty sentence the Arabic
    # was fixed for, and the English kept it.
    bits = []
    for it in latest:
        val = it.get("value_num") if it.get("value_num") is not None else it.get("value_text")
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        shown = f"{val:,}" if isinstance(val, (int, float)) else str(val)
        unit = f" {it['unit']}" if it.get("unit") else ""
        attrs = it.get("attrs") or {}
        partial = " (partial year)" if attrs.get("partial_year") else ""
        where = attrs.get("locality_name") or it.get("place_en") or it.get("place_ar")
        bits.append(f"{it.get('indicator')}: {shown}{unit}, {databank_when(it)}{partial}"
                    + (f", {where}" if where else ""))
    src = "; ".join(d.get("attribution") or [])[:120]
    out = f"{d.get('category')}{when} — latest figures: " + "; ".join(bits) + "."
    if src:
        out += f" Source: {src}."
    span = d.get("page_span") or {}
    if span.get("from"):
        out += (f" The series runs {span['from'][:4]} to {span['to'][:4]}."
                if span.get("whole") else
                f" These are the newest {d.get('count')} rows ({span['from']} to "
                f"{span['to']}); the series is longer.")
    return out


def insights(d: dict) -> str:
    scope = d.get("scope") or {}
    ck = d.get("checkpoints") or {}
    inc = d.get("incidents") or {}
    name = scope.get("name_en") or scope.get("name") or scope.get("query") or "that place"
    radius = scope.get("radius_km")
    out = (f"Last {scope.get('days') or '?'} days around {name}"
           + (f" ({radius:g} km)" if isinstance(radius, (int, float)) else "")
           + f": {ck.get('readings', 0):,} checkpoint "
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
    # The measured precision of each TYPE the sentence counts, beside the
    # overall gate: "5 death" with only "77 % overall" hid that deaths read at
    # 60 % — the other incident answers already said it.
    prec = _precision_en(d.get("incident_precision"))
    if prec:
        out += "." + prec.rstrip(".")
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
           f"{sum((live.get('live_states') or {}).values()):,} live states"
           + (f" over {live['checkpoints_tracked']} tracked checkpoints"
              + (f" ({live['checkpoints_with_reading']} with a current reading)"
                 if live.get("checkpoints_with_reading") is not None else "")
              if live.get("checkpoints_tracked") is not None else "")
           + ".")
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
        # The worst day, as the Arabic names it (أسوأ يوم).
        def closed_on(day: dict) -> int:
            return (((day.get("kinds") or {}).get("checkpoint_flow") or {})
                    .get("values") or {}).get("closed", 0)
        worst = max(d.get("series") or [], key=closed_on, default=None)
        if worst and closed_on(worst):
            out += f"; worst day {worst.get('day')} ({closed_on(worst)} closed reports)"
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


# Tools whose renderer says its own found:false — checkpoint_status names the
# resolved or lookalike checkpoint; can_i_travel names both ends.
_OWN_NOT_FOUND = frozenset({"checkpoint_status", "can_i_travel"})


def add_english(tool: str, out: Any) -> Any:
    """Attach `answer_en` when this tool has a renderer. Never raises: a
    formatting bug here must not take down an answer about a road."""
    if not isinstance(out, dict) or "answer_en" in out:
        return out
    fn = RENDERERS.get(tool)
    if fn is None:
        return out
    try:
        text = _unanswered(tool, out) or fn(out)
    except Exception:                                       # noqa: BLE001
        # Still never raises — but no longer silently: a renamed REST field
        # broke one renderer and every call of that tool lost its English with
        # the suite green and /health "ok". The log line names the tool.
        log.warning("answer_en: the %s renderer failed; the reply goes out "
                    "without English", tool, exc_info=True)
        return out
    if text:
        out["answer_en"] = text.strip()
    return out
