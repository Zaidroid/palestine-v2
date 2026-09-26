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
    "Distances, durations and route geometry are computed over OpenStreetMap "
    "roads: a PRODUCED WORK under ODbL — '© OpenStreetMap contributors' is owed, "
    "no ODbL obligation lands on a database you build from these numbers.")

# The same obligation, minus a datum this tool does not return. `checkpoints_near`
# puts a `km` on each row but no route geometry, and the shared text above claims
# both — so reusing it here would assert an obligation against data the payload
# never carries, which is the defect this whole licence layer exists to prevent.
_OSM_DISTANCES_ONLY = (
    "The per-row `km` is computed over OpenStreetMap roads: a PRODUCED WORK "
    "under ODbL — attribution owed, no obligation on your database. This tool "
    "returns no route geometry; the coordinates are this platform's own registry.")

TOOLS: dict[str, dict] = {
    # ── the live tracker: our own reductions. The clean core. ──
    # The OSM Produced-Work obligation belongs ONLY on the tools that actually
    # return a distance or route geometry. It was attached to checkpoint_status
    # and checkpoints_summary too, which return neither — measured 2026-09-24:
    # `checkpoints_near` carries `km` per row, `checkpoint_status` and
    # `checkpoints_summary` carry no distance field at all. An obligation
    # asserted where no such datum exists is the same defect as a licence claim
    # the payload cannot support, pointed the other way.
    "checkpoint_status":   {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_CHECKPOINT]},
    "checkpoints_near":    {"emits": DERIVED, "sources": [GROUP_STATE],
                            "obligations": [_OSM_DISTANCES_ONLY]},
    "checkpoints_summary": {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_CHECKPOINT]},
    "can_i_travel":        {"emits": DERIVED, "sources": [GROUP_STATE],
                            "obligations": [_OSM_PRODUCED_WORK],
                            "note": "carries no geometry: a verdict, named checkpoints, "
                                    "a distance and a duration."},
    "crossings":           {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_CHECKPOINT]},
    "incidents_near":      {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_ANY],
                            "note": "echoes the resolved place's coordinates, which may "
                                    "be an ODbL locality."},
    "incidents_summary":   {"emits": DERIVED, "sources": [GROUP_STATE]},
    "fuel_prices":         {"emits": DERIVED, "sources": [GROUP_STATE],
                            "note": "our reduction of two independent outlets; the "
                                    "official ceiling itself is an act, not a dataset."},
    "where_is":            {"emits": DERIVED, "sources": [GROUP_GEO_ANY],
                            "note": "may hand back an ODbL locality centroid (Palestine "
                                    "Open Maps rows)."},
    "place_history":       {"emits": DERIVED, "sources": [GROUP_STATE]},
    "place_pattern":       {"emits": DERIVED, "sources": [GROUP_STATE]},
    "area_history":        {"emits": DERIVED, "sources": [GROUP_STATE]},
    "insights":            {"emits": DERIVED,
                            "sources": [GROUP_STATE, GROUP_GEO_ANY],
                            "note": "the scope block echoes the resolved place's "
                                    "coordinates, which may be an ODbL locality."},
    "stream_info":         {"emits": METADATA, "sources": []},
    "about":               {"emits": METADATA, "sources": []},
    "coverage":            {"emits": METADATA, "sources": []},
    "licenses":            {"emits": METADATA, "sources": []},
    "licence_tools":       {"emits": METADATA, "sources": []},
    "data_gaps":           {"emits": METADATA, "sources": []},

    # ── a third party's measurement, served with their grade ──
    "weather_now":      {"emits": MEASURED, "sources": ["open_meteo"]},
    "connectivity_now": {"emits": MEASURED, "sources": ["ioda"],
                         "note": "IODA: All Rights Reserved, permission not yet asked; "
                                 "served as a cited fact, not ours to redistribute."},

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
                      "note": "resolves a place name and its incident rows carry "
                              "lat/lon, so this payload DOES carry coordinates."},
}

# One line per class. The long form lives in /v2/licence/tools; the per-call
# block is read on every reply and was 40-60 % of a short payload.
_EMIT_NOTE = {
    DERIVED: "our own reduction over other people's claims; carries no third party's licence",
    MEASURED: "a third party's measurement served as a cited fact; their grade governs reuse",
    VERBATIM: "somebody else's wording; the partner tier gets an excerpt and a pointer, never the body",
    DATABANK: "historical rows graded per source; see licence(scope=sources)",
    METADATA: "describes this system itself, not the country; no third party's data is served",
}

# Said out loud on every share-alike payload, because a grade that names a
# copyleft and a payload that never mentions it leaves the reader to find out
# after they have shipped. `full` and `share-alike` are both sellable; only one
# of them travels into the database the partner builds.
_SHARE_ALIKE_OBLIGATION = (
    "SHARE-ALIKE: sellable, but a DERIVED DATABASE built on it must carry the "
    "same licence (ODbL / CC-BY-SA); copying numbers into a product is fine.")


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

def apply(tool: str, out: Any, tier: str, entry: dict | None = None, *,
          shown_as: str | None = None) -> Any:
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
    block: dict[str, Any] = {"tool": shown_as or tool, "graded": True, "emits": emits,
                             "emits_note": _EMIT_NOTE[emits], "tier": tier,
                             "ref": f"/v2/licence/tools#{tool}"}
    if shown_as and shown_as != tool:
        # The caller used a public façade name; the grade is the answering
        # tool's, and saying which one keeps /v2/licence/tools readable.
        block["via"] = tool
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
                f"{cut} of {len(items)} message bodies cut to {EXCERPT_CHARS} "
                "characters: every source here is graded no-redistribution, so "
                "the excerpt, source and time are a citation and the body is not.")
            # The spoken answer quotes the newest message, so it carries the
            # same cut. An `answer` that reproduces in full what the payload
            # withheld is the whole control defeated by one f-string.
            for ak in ("answer", "answer_en"):
                a = out.get(ak)
                if isinstance(a, str) and len(a) > EXCERPT_CHARS:
                    out[ak] = a[:EXCERPT_CHARS].rstrip() + "…"
    if tier == "partner" and emits == DATABANK:
        # ZAID-10 (answered 2026-09-23), enforced here since 2026-09-25 (P1-B.2):
        # rows from a publisher graded `ask` or `no-redistribution` stay out of a
        # partner payload. 066's line still holds — a credited FACT answering a
        # question is reporting — so the spoken answer keeps its figure and its
        # source; what leaves is the ROWS, and the cut is named, never silent.
        dropped: dict[str, int] = {}
        total = 0
        for key in ("items", "latest_by_indicator"):
            rows = out.get(key)
            if not isinstance(rows, list):
                continue
            keep = []
            for it in rows:
                g = it.get("redistribution") if isinstance(it, dict) else None
                if isinstance(it, dict) and "redistribution" in it and g not in PARTNER_ALLOWED:
                    if key == "items":
                        k = f"{it.get('source_key') or '?'} ({g or 'ungraded'})"
                        dropped[k] = dropped.get(k, 0) + 1
                        total += 1
                    continue
                keep.append(it)
            out[key] = keep
        # A series' POINTS are rows too (compare returned OCHA's no-redistribution
        # casualty points to partners under "filtered", audit TRANSPORT-01): the
        # points leave, the series' summary, span and citation stay.
        for s_ in out.get("series") or []:
            if not isinstance(s_, dict) or "redistribution" not in s_:
                continue
            g = s_.get("redistribution")
            if g not in PARTNER_ALLOWED and s_.get("points"):
                n = len(s_["points"])
                s_["points"] = []
                s_["points_withheld"] = n
                src = ", ".join(s_.get("sources") or []) or "?"
                k = f"{src} ({g or 'ungraded'})"
                dropped[k] = dropped.get(k, 0) + n
                total += n
        if total:
            out["count"] = len(out.get("items") or [])
            block["withheld"] = {
                "rows": total, "by_source": dropped,
                "reason": ("these publishers do not grant redistribution (or their terms "
                           "are unread): the rows stay out of a partner payload (ZAID-10). "
                           "The answer's figure is a cited fact with its source; read the "
                           "rows at the publisher."),
            }
            # Said where it is read: "newest 10 rows shown" over an empty list
            # would be the quietly-short payload this module exists to prevent.
            if isinstance(out.get("answer"), str):
                out["answer"] += (f" ({total} من السجلات محجوبة عن هاد الرد: ناشرها ما بيسمح "
                                  "بإعادة النشر — الرقم مقتبس مع مصدره.)")
            if isinstance(out.get("answer_en"), str):
                out["answer_en"] += (f" ({total} rows withheld from this payload: their publisher "
                                     "does not grant redistribution — the figure is cited with its source.)")
    if tier == "partner" and entry and entry.get("partner_tier") == "cited_fact_only":
        # ZAID-10 for a MEASURED tool whose publisher grades `ask` (IODA): a
        # partner gets the credited FACT — the answer, who measured it, how old
        # it is — not the measurement series (audit TRANSPORT-01: the payload
        # said cited_fact_only and still carried IODA's raw signals).
        keep = {"answer", "answer_en", "attribution", "source", "license",
                "redistribution", "observed_at", "age_minutes", "staleness_band",
                "confidence", "region", "error"}
        cut = sorted(k for k in list(out) if k not in keep)
        for k in cut:
            out.pop(k, None)
        if cut:
            block["stripped"] = {"keys": cut,
                                 "reason": "the publisher grants no redistribution of its "
                                           "measurements: a partner receives the cited fact, "
                                           "not the series (ZAID-10)."}
    out["licence"] = block
    return out
