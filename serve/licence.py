"""F-81 — what may leave the building, per tool and per datum.

The door is shut (F-80) and the docs exist (F-83), so the question that remains
before a partner gets a key is not *whether* they can call, it is *what they are
allowed to carry away*. That is a licence decision and it belongs BEFORE the
payload, not in a paragraph a reader may skip.

THE LINE 066 DREW, AND WHERE IT DOES NOT REACH
Migration 066 settled the databank question: the filter lands on BULK, not on
query, because a credited FACT answering a question is reporting rather than
redistribution. That reasoning is about facts — a demolition count, a price, a
prisoner total. It does not reach the other thing this API serves, which is
somebody else's WORDING: `latest_news` and `search` return the message body a
Telegram channel wrote, measured here at a median of 376 characters and a
maximum of 4,094. A whole article is not a cited fact, and all 67,193 of those
messages come from sources graded `no-redistribution` — the channels' words are
theirs, and we hold no licence to republish them.

So this module grades three DIFFERENT things rather than one:

  derived   Our own belief, computed here from many claims: a checkpoint's flow,
            an incident event, a fuel-price belief, a resolved place. The claims
            underneath are other people's; the reduction is ours and carries no
            third party's licence. This is the clean core of the live surface.
  measured  A third party's measurement, served with their grade: Open-Meteo
            (CC-BY-4.0, attribution) and IODA (all rights reserved, `ask`).
  verbatim  A third party's EXPRESSION, reproduced. This is the one the partner
            tier cannot carry in full, and the only one that gets cut.
  databank  Per-row licences, already graded in the database (053/066).

WHAT A GRADE IS NOT
It is not typed in here. Every grade is read from `source.redistribution` at
call time, the same column the databank tiers read, so a re-graded source
changes this surface without a deploy and cannot quietly disagree with
`/v2/databank/licenses`. What IS declared here is the mapping from a tool to the
kind of thing it emits — that is a fact about our own code, not about anybody's
licence, and it is the one thing a database cannot tell us.

THE PARTNER TIER
ZAID-10, answered 2026-09-23: live trackers plus insights now; ungraded and
`no-redistribution` databank sets stay out of the partner payloads. Applied
per-datum here, and the cut is always NAMED: an excerpt says it is an excerpt,
a filtered list says how many rows it dropped and why. A payload that is quietly
short is the exact lie this system was built to stop telling.
"""
from __future__ import annotations

from typing import Any

# Grades in order of how much they permit. A tool inherits the WORST grade among
# the sources it reads, because a payload is as redistributable as its least
# redistributable datum.
GRADE_ORDER = ("open", "attribution", "share-alike", "ask", "no-redistribution")

# What the commercial partner tier may carry as DATA. `ask` is excluded on
# purpose: a publisher whose terms nobody has read has not said no, which is not
# the same as having said yes, and a partner release is the wrong place to find
# out which it was.
PARTNER_ALLOWED = ("open", "attribution", "share-alike")

# How much of somebody else's wording is a citation rather than a reproduction.
# 250 characters sits below the 25th percentile of the corpus (142) for a short
# message and well under the median (376) for a long one, so a partner sees
# enough to know what a message is about and has to come here to read it.
EXCERPT_CHARS = 250

# ── what each public tool emits ───────────────────────────────────────────────
# `emits` is the class; `sources` names the source keys or a group to resolve
# from the database. A tool missing from this table fails the test that walks
# PUBLIC_TOOLS, so a new tool cannot ship ungraded.

DERIVED = "derived"
MEASURED = "measured"
VERBATIM = "verbatim"
DATABANK = "databank"
# Not every tool answers about the country. Some answer about THIS SYSTEM — what
# it holds, what it cannot answer, which publisher's terms nobody has read, what
# this very table says. Telling a reader those were "computed from many reports"
# is boilerplate that is simply false, and a payload whose own description is
# false teaches the reader to distrust the parts that are true.
METADATA = "own-metadata"

# Source GROUPS, resolved live from the database rather than listed, because the
# channel roster changes with every ingest spec and a hand-list would rot.
GROUP_STATE = "group:state_observation"      # every source feeding live state
GROUP_CLAIM = "group:claim"                  # every source whose text we hold
GROUP_DATABANK = "group:databank"            # every dataset source

# THE GAZETTEER, IN TWO PARTS, BECAUSE THE GRADES GENUINELY DIFFER.
# Measured 2026-09-24 over `place` rows carrying a centroid: 2,584 localities
# come from Palestine Open Maps (ODbL, share-alike) and 402 fuel stations from
# OpenStreetMap (ODbL), while all 359 checkpoints, 3 of the crossings and 12
# roads come from `v1_checkpoints` — this platform's own registry, graded open.
#
# So a tool that emits the coordinates of a CHECKPOINT is not ODbL-encumbered,
# and a tool that resolves an arbitrary place NAME may land on an ODbL locality
# and is. Grading every coordinate-bearing tool the same way would have been
# wrong in one direction or the other whichever value was chosen; which resolver
# a tool calls is a fact about our code, and the grades behind it are read here.
GROUP_GEO_ANY = "group:gazetteer_any"        # any resolvable place name
GROUP_GEO_CHECKPOINT = "group:gazetteer_checkpoint"   # checkpoint/crossing/road

# The place kinds whose coordinates come from this platform's own registry.
GEO_CHECKPOINT_KINDS = ("checkpoint", "crossing", "road")

# Sources whose grade PROPAGATES INTO a derived payload, rather than being
# absorbed by the reduction. The 066 reasoning — our belief over other people's
# claims is ours to give — holds for a value we COMPUTED. It does not hold for a
# datum we COPIED: a coordinate echoed out of the gazetteer is that gazetteer's
# row, not a reduction of it, so an ODbL locality centroid stays ODbL however
# many claims were reduced beside it.
PROPAGATING_GROUPS = (GROUP_GEO_ANY, GROUP_GEO_CHECKPOINT)

# The ODbL distinction that decides whether a partner inherits an obligation.
# ODbL separates a DERIVATIVE DATABASE (you copied OSM's data and built on it —
# your database must be ODbL) from a PRODUCED WORK (you computed a result from
# it — attribution is owed, your database is your own). Getting this backwards
# either burdens a partner with a licence they do not owe, or hides one they do.
_OSM_PRODUCED_WORK = (
    "Distances and route geometry here are computed over OpenStreetMap road "
    "data, which ODbL treats as a PRODUCED WORK: the '© OpenStreetMap "
    "contributors' attribution is owed and travels in `source`/`attribution`, "
    "but it places no ODbL obligation on a database you build from these "
    "numbers. This platform's own checkpoint coordinates are a separate case — "
    "they come from its own registry, not from OSM.")

TOOLS: dict[str, dict] = {
    # ── the live tracker: our own reductions. The clean core. ──
    "checkpoint_status":   {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_CHECKPOINT],
                            "obligations": [_OSM_PRODUCED_WORK]},
    "checkpoints_near":    {"emits": DERIVED, "sources": [GROUP_STATE],
                            "obligations": [_OSM_PRODUCED_WORK],
                            "note": "the `km` on each row is a distance over "
                                    "OpenStreetMap road geometry, which is why "
                                    "the attribution credits OSM even though the "
                                    "coordinates themselves are this platform's "
                                    "own checkpoint registry (provenance "
                                    "v1_checkpoints, graded open)."},
    "checkpoints_summary": {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_CHECKPOINT],
                            "obligations": [_OSM_PRODUCED_WORK]},
    "can_i_travel":        {"emits": DERIVED, "sources": [GROUP_STATE],
                            "obligations": [
                                "Distances, durations and route geometry are "
                                "computed over OpenStreetMap road data by Valhalla. "
                                "ODbL calls that a PRODUCED WORK: the attribution "
                                "below is owed, but it does not place an ODbL "
                                "obligation on a database YOU build from these "
                                "numbers. Copying OSM's data itself would — which "
                                "is why the fuel-station rows ARE graded "
                                "share-alike."],
                            "note": "the payload carries no geometry — verified "
                                    "2026-09-24: a verdict, named checkpoints, a "
                                    "distance and a duration."},
    "crossings":           {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_CHECKPOINT]},
    "incidents_near":      {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_ANY],
                            "note": "echoes the coordinates of the place name it "
                                    "resolved, which may be an ODbL locality."},
    "incidents_summary":   {"emits": DERIVED, "sources": [GROUP_STATE]},
    "fuel_prices":         {"emits": DERIVED, "sources": [GROUP_STATE],
                            "note": "the believed price is our reduction of two "
                                    "independent outlets; the Petroleum "
                                    "Corporation's figure itself is an official "
                                    "act, not a licensed dataset."},
    "where_is":            {"emits": DERIVED, "sources": [GROUP_GEO_ANY],
                            "note": "resolves any place name and returns its "
                                    "coordinates, so it can hand back an ODbL "
                                    "locality centroid: 2,584 of the gazetteer's "
                                    "located places are Palestine Open Maps."},
    "place_history":       {"emits": DERIVED, "sources": [GROUP_STATE]},
    "place_pattern":       {"emits": DERIVED, "sources": [GROUP_STATE]},
    "area_history":        {"emits": DERIVED, "sources": [GROUP_STATE]},
    "insights":            {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_ANY],
                            "note": "the scope block echoes the resolved place's "
                                    "coordinates, which may be an ODbL locality."},
    "stream_info":         {"emits": METADATA, "sources": []},
    "coverage":            {"emits": METADATA, "sources": [],
                            "note": "metadata about this system, not data from "
                                    "anyone's dataset."},
    "licenses":            {"emits": METADATA, "sources": [],
                            "note": "the licence register itself: our own record "
                                    "of what we read and when."},
    "licence_tools":       {"emits": METADATA, "sources": [],
                            "note": "this grading table. Our own policy record, "
                                    "and the first tool that had to grade "
                                    "itself — the coverage test caught it "
                                    "missing, which is the gate working."},
    "data_gaps":           {"emits": METADATA, "sources": [],
                            "note": "freshness measurements of our own holdings."},

    # ── a third party's measurement, served with their grade ──
    "weather_now":      {"emits": MEASURED, "sources": ["open_meteo"]},
    "connectivity_now": {"emits": MEASURED, "sources": ["ioda"],
                         "note": "IODA state All Rights Reserved on every API "
                                 "response and a letter is drafted, not sent "
                                 "(source_permission: ioda, not_asked). The "
                                 "measurement is served with attribution as a "
                                 "cited fact; it is not ours to redistribute."},

    # ── a third party's WORDING, reproduced. The only class that gets cut. ──
    "latest_news": {"emits": VERBATIM, "sources": [GROUP_CLAIM],
                    "field": "items", "text_key": "text"},
    "search":      {"emits": VERBATIM, "sources": [GROUP_CLAIM],
                    "field": "items", "text_key": "text"},

    # ── the databank: per-row licences, graded in the database since 053 ──
    "databank":             {"emits": DATABANK, "sources": [GROUP_DATABANK]},
    "trend":                {"emits": DATABANK, "sources": [GROUP_DATABANK]},
    "compare":              {"emits": DATABANK, "sources": [GROUP_DATABANK]},
    "correlate":            {"emits": DATABANK, "sources": [GROUP_DATABANK]},
    "what_correlates_with": {"emits": DATABANK, "sources": [GROUP_DATABANK]},

    # ── both tiers in one call ──
    "place_profile": {"emits": DERIVED,
                      "sources": [GROUP_STATE, GROUP_GEO_ANY],
                      "note": "joins live state and history; both are derived "
                              "observations, not reproduced text. It resolves a "
                              "place name, so the gazetteer's grade travels with "
                              "it, AND when the place has incidents each incident "
                              "row carries its own latitude and longitude — so "
                              "this payload DOES carry coordinates and must not "
                              "be described as if it did not."},
}

_EMIT_NOTE = {
    DERIVED: ("This system's own derived observation, computed from many "
              "reports. The reports are other people's; the reduction is ours "
              "and carries no third party's licence."),
    MEASURED: ("A third party's measurement, served as a cited fact with their "
               "attribution. Their grade governs what you may do with it."),
    VERBATIM: ("Somebody else's wording, reproduced. The channels hold their "
               "own copyright and we hold no licence to republish them, so the "
               "partner tier receives an excerpt and a pointer, never the body."),
    DATABANK: ("Historical rows, each graded in the database. Per-row licences "
               "and their obligations are in `licenses` / "
               "/v2/databank/licenses."),
    METADATA: ("This describes THIS SYSTEM, not the country — what it holds, "
               "what it cannot answer, whose terms nobody has read, what this "
               "grading table says. No third party's data is being served, so "
               "no third party's licence attaches; the counts are ours and "
               "come with the caveats printed beside them."),
}

# Said out loud on every share-alike payload, because a grade that names a
# copyleft and a payload that never mentions it leaves the reader to find out
# after they have shipped. `full` and `share-alike` are both sellable; only one
# of them travels into the database the partner builds.
_SHARE_ALIKE_OBLIGATION = (
    "SHARE-ALIKE: this is sellable, but a DERIVED DATABASE built on it must be "
    "released under the same licence (ODbL / CC-BY-SA). Copying the numbers into "
    "a product is fine; treating the output as a database you own is not.")


def _worst(grades: list[str]) -> str:
    """The least permissive grade present — a payload is as redistributable as
    its least redistributable datum."""
    seen = [g for g in grades if g in GRADE_ORDER]
    if not seen:
        return "open"
    return max(seen, key=GRADE_ORDER.index)


def _group_grades(q, group: str) -> list[str]:
    """Grades of a whole class of sources, read live from the database."""
    if group == GROUP_STATE:
        rows = q("""SELECT DISTINCT s.redistribution AS g
                      FROM state_observation o
                      JOIN source s ON s.source_id = o.source_id""")
    elif group == GROUP_CLAIM:
        rows = q("""SELECT DISTINCT s.redistribution AS g
                      FROM claim c JOIN source s ON s.source_id = c.source_id""")
    elif group == GROUP_DATABANK:
        rows = q("SELECT DISTINCT redistribution AS g FROM databank_internal")
    elif group in (GROUP_GEO_ANY, GROUP_GEO_CHECKPOINT):
        # The gazetteer's provenance lives in `place.source_refs->>'source'`
        # (falling back to `attrs`), which is a source KEY, so the grade is the
        # same `source.redistribution` everything else here reads.
        #
        # ONLY `servable` ROWS, because only those can reach a payload.
        # `resolve/geo.py` filters on `servable` and so does the checkpoint
        # query in app.py: the Nakba gazetteer's 2,584 Palestine Open Maps
        # localities are servable=false reference rows, there so a live report
        # naming طنطورة does not resolve to a village destroyed in 1948. They
        # are ODbL, and grading the live tools share-alike because of rows no
        # tool can return would be a false obligation — the mirror image of the
        # error this table exists to prevent. Measured 2026-09-24, the SERVABLE
        # located gazetteer is: 1,443 v1_known_locations (open), 402 OSM fuel
        # stations (ODbL share-alike), 287 v1_checkpoints (open), 186 palhub
        # stations (no source row), 18 ocha_admin (attribution), 5 hand-entered
        # crossings (ours).
        #
        # The `ask` default applies only to a row that NAMES a third-party
        # provenance we hold no source row for — genuinely unchecked. A row
        # carrying no `source` key at all is this platform's own hand-entered
        # public geography (migration 034), graded open; defaulting those to
        # `ask` would withhold our own work from the partner tier.
        # A STATION'S COORDINATE IS ITS ANCHOR'S COORDINATE.
        # `ingest/sources/palhub_loader.py` creates each fuel station by copying
        # the centroid of the place it resolved to (`geo_anchor_place_id`), so
        # `"source": "palhub"` records where the NAME came from, not where the
        # geometry came from — there is no palhub coordinate dataset to hold a
        # licence. Grading those 186 rows `ask` on an unmatched key would invent
        # an obligation over coordinates we took from our own open gazetteer.
        # Following the anchor is what makes the grade true rather than cautious.
        sql = """
            WITH located AS (
                SELECT p.place_id, p.kind::text AS kind,
                       COALESCE(a.source_refs->>'source', a.attrs->>'source',
                                p.source_refs->>'source', p.attrs->>'source')
                         AS provenance
                  FROM place p
                  LEFT JOIN place a
                    ON a.place_id = (p.source_refs->>'geo_anchor_place_id')::bigint
                 WHERE p.centroid IS NOT NULL
                   AND p.servable
                   AND p.merged_into IS NULL
            )
            SELECT DISTINCT CASE
                     WHEN s.redistribution IS NOT NULL THEN s.redistribution
                     WHEN l.provenance IS NULL THEN 'open'
                     ELSE 'ask'
                   END AS g
              FROM located l
              LEFT JOIN source s ON s.key = l.provenance
             WHERE 1 = 1
        """
        if group == GROUP_GEO_CHECKPOINT:
            # Inlined rather than parameterised, and it has to be: psycopg3
            # adapts a tuple as a RECORD (`malformed array literal`) while a
            # list is unhashable and breaks `q_cached`'s key. These three values
            # are module constants with no caller input anywhere near them, so
            # there is nothing here to inject.
            kinds = ", ".join(f"'{k}'" for k in GEO_CHECKPOINT_KINDS)
            rows = q(sql + f" AND l.kind IN ({kinds})")
        else:
            rows = q(sql)
    else:
        return []
    return [r["g"] for r in rows if r["g"]]


def grade_tools(q) -> dict:
    """The per-tool licence table. Every grade read from the database.

    `q` is the app's query function, injected so this module needs no database
    handle of its own and can be tested against a stub.
    """
    named = q("SELECT key, redistribution, license_spdx, attribution_text, "
              "       terms_verified_at::date AS verified_on "
              "  FROM source")
    by_key = {r["key"]: r for r in named}
    cache: dict[str, list[str]] = {}

    out = {}
    for tool, spec in sorted(TOOLS.items()):
        grades, unknown, copied = [], [], []
        for src in spec["sources"]:
            if src.startswith("group:"):
                if src not in cache:
                    cache[src] = _group_grades(q, src)
                grades += cache[src]
                if src in PROPAGATING_GROUPS:
                    copied += cache[src]
            elif src in by_key:
                grades.append(by_key[src]["redistribution"])
            else:
                unknown.append(src)

        emits = spec["emits"]
        # A DERIVED tool's grade is `open` — the reduction is ours — and the
        # grades underneath are reported beside it rather than hidden, because
        # the reason a reader can trust the `open` is that they can see what it
        # was derived FROM.
        #
        # What a reduction does NOT absorb is a datum it copied rather than
        # computed. A coordinate echoed out of the gazetteer is that gazetteer's
        # row, so its grade propagates in full: ODbL localities make a tool
        # share-alike, and an unmatched provenance makes it `ask`. Reductions
        # over claims stay ours either way.
        if emits == DERIVED:
            grade = _worst(copied) if copied else "open"
        else:
            grade = _worst(grades)

        entry = {
            "tool": tool,
            "emits": emits,
            "emits_note": _EMIT_NOTE[emits],
            "grade": grade,
            "partner_tier": (
                "full" if grade in PARTNER_ALLOWED and emits != VERBATIM
                else "excerpt" if emits == VERBATIM
                else "filtered" if emits == DATABANK
                else "cited_fact_only"),
            "underlying_grades": sorted(set(g for g in grades if g),
                                        key=GRADE_ORDER.index),
        }
        if emits == VERBATIM:
            entry["excerpt_chars"] = EXCERPT_CHARS
        if spec.get("note"):
            entry["note"] = spec["note"]
        if unknown:
            entry["unresolved_sources"] = unknown
        out[tool] = entry
    return out


def table(q, public_tools: set[str]) -> dict:
    """The whole answer for the route and for the MCP tool."""
    graded = grade_tools(q)
    ungraded = sorted(public_tools - set(TOOLS))
    by_tier: dict[str, list[str]] = {}
    for t, e in graded.items():
        if t in public_tools:
            by_tier.setdefault(e["partner_tier"], []).append(t)
    return {
        "tools": [graded[t] for t in sorted(graded) if t in public_tools],
        "public_tools": len(public_tools),
        "graded": len([t for t in graded if t in public_tools]),
        "ungraded": ungraded,
        "partner_tier_counts": {k: len(v) for k, v in sorted(by_tier.items())},
        "grades_read_from": "source.redistribution — the same column "
                            "/v2/databank/licenses reports, read per call, so a "
                            "re-graded source changes this table without a deploy.",
        "partner_allowed_grades": list(PARTNER_ALLOWED),
        "policy": {
            "query_vs_bulk": "A credited FACT answering a question is reporting, "
                             "not redistribution (migration 066). That is why "
                             "the free query tier is unfiltered and the BULK "
                             "export is narrower.",
            "expression_is_not_a_fact": "Reproducing somebody's WORDING is not "
                                        "covered by that reasoning. Message "
                                        "bodies are the channels' copyright, so "
                                        "the partner tier gets an excerpt of "
                                        f"{EXCERPT_CHARS} characters, the source "
                                        "name and the timestamp — never the body.",
            "ask_is_not_yes": "A publisher whose terms nobody has read has not "
                              "refused, which is not the same as having agreed. "
                              "`ask` is outside the partner tier until the "
                              "letter in source_permission is answered.",
            "cuts_are_named": "Every reduction states itself in the payload: an "
                              "excerpt says so, a filtered list says how many "
                              "rows it dropped and why. A payload that is "
                              "quietly short is the lie this system exists to "
                              "avoid telling.",
        },
    }


# ── applying it to one payload ────────────────────────────────────────────────

def apply(tool: str, out: Any, tier: str, entry: dict | None = None) -> Any:
    """Attach the licence block and enforce it, per datum.

    Never raises: a licence-labelling bug must not take down an answer about a
    road. Called after the tool has produced its payload, so a tool function
    cannot be talked into raising its own tier by a caller-supplied argument.

    `entry` is this tool's row from the grading table when the caller has it
    (`/v2/licence/tools`). Passing it is what lets the payload state the GRADE
    and its OBLIGATION rather than only what class of thing it emits — a
    share-alike tool whose payload never mentions the copyleft leaves the reader
    to discover it after they ship. Optional, because the table needs a database
    and an answer about a road must not depend on one.
    """
    if not isinstance(out, dict) or out.get("error"):
        return out
    spec = TOOLS.get(tool)
    if spec is None:
        # Not a licence decision we can make, so say that rather than implying
        # a clean one. The test that walks PUBLIC_TOOLS stops this shipping.
        out["licence"] = {"tool": tool, "graded": False,
                          "note": "this tool carries no licence grading yet — "
                                  "treat its payload as ungraded and do not "
                                  "redistribute it."}
        return out

    emits = spec["emits"]
    block: dict[str, Any] = {"tool": tool, "graded": True, "emits": emits,
                             "emits_note": _EMIT_NOTE[emits], "tier": tier,
                             "table": "/v2/licence/tools"}
    if spec.get("note"):
        block["note"] = spec["note"]
    for key in ("obligations",):
        if spec.get(key):
            block[key] = list(spec[key])
    if entry:
        block["grade"] = entry.get("grade")
        block["partner_tier"] = entry.get("partner_tier")
        if entry.get("grade") == "share-alike":
            block.setdefault("obligations", [])
            block["obligations"] = [_SHARE_ALIKE_OBLIGATION] + block["obligations"]
        if entry.get("note") and entry["note"] != spec.get("note"):
            block["grade_note"] = entry["note"]

    if tier == "partner" and emits == VERBATIM:
        field, key = spec.get("field", "items"), spec.get("text_key", "text")
        items = out.get(field)
        if isinstance(items, list):
            cut = 0
            for it in items:
                if not isinstance(it, dict):
                    continue
                text = it.get(key)
                if isinstance(text, str) and len(text) > EXCERPT_CHARS:
                    it[key] = text[:EXCERPT_CHARS].rstrip() + "…"
                    it["excerpted"] = True
                    # The row was already shortened by the route's own storage
                    # cap before this saw it, so `len(text)` is that CAP and not
                    # the message length — measured 2026-09-24: every excerpted
                    # item reported exactly 500, which is the route's limit
                    # wearing the name of a fact. Prefer the true length when
                    # the payload carries it.
                    it["full_text_chars"] = int(
                        it.get("text_full_chars") or len(text))
                    if it["full_text_chars"] <= EXCERPT_CHARS:
                        # A cap that hides the reason for the cut is worse than
                        # no cut: we would be excerpting text we could have
                        # served whole.
                        it["truncated_by_route"] = True
                    cut += 1
            block["excerpted_items"] = cut
            block["excerpt_chars"] = EXCERPT_CHARS
            block["refused"] = (
                f"{cut} of {len(items)} message bodies were cut to "
                f"{EXCERPT_CHARS} characters. The channels hold their own "
                "copyright and every source feeding this tool is graded "
                "`no-redistribution`, so the wording is not ours to republish. "
                "The excerpt, the source name and the timestamp are a citation; "
                "the body is not.")
            # The spoken answer quotes the newest message, so it carries the
            # same cut. An `answer` that reproduces in full what the payload
            # withheld is the whole control defeated by one f-string.
            for ak in ("answer", "answer_en"):
                a = out.get(ak)
                if isinstance(a, str) and len(a) > EXCERPT_CHARS:
                    out[ak] = a[:EXCERPT_CHARS].rstrip() + "…"
    out["licence"] = block
    return out
