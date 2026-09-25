"""The PUBLIC tool surface: 16 names a first-time caller can hold in their head.

WHY (P0-A, 2026-09-24)
The server grew to 28 public tools, six of them named after the same idea
(`place_profile`, `place_history`, `place_pattern`, `where_is`, `area_history`,
`insights`), five of them about the system itself (`coverage`, `data_gaps`,
`stream_info`, `licenses`, `licence_tools`), two sharing one endpoint
(`latest_news`, `search`), and "a place" going by six parameter names. An LLM
client reads every description on every turn and then has to choose; a human
reading tools/list sees a control panel, not a service. The partner audit's
scorecard and our own first-time walk both said the same thing: say less.

WHAT THIS IS
A façade table over the existing `TOOLS`. Nothing underneath moves: every old
name stays callable for one release (an alias, hidden from tools/list), the
licence grade and the English renderer stay keyed on the tool that actually
answers, and the usage ledger records the PUBLIC name a caller used — which is
the demand signal the ledger exists to carry.

A façade is either a pure ROUTER (picks the old tool from the arguments and
drops the arguments that tool does not take) or, for `about`, a real composite
function registered in `TOOLS` like any other tool. `route()` is the single
seam both transports call before dispatch, so stdio and HTTP cannot disagree
about what a name means.

ONE NAME FOR A PLACE
Every façade that takes a place calls the argument `place`. Every parameter
carries a description, and every default is DECLARED in the schema rather than
buried in a Python signature — the schema is the only thing a client sees.
"""
from __future__ import annotations

from typing import Any, Callable

from serve.mcp_server import HOST_ONLY, TOOLS

# Internal names the façades absorb. Still callable by name (one release of
# aliases so nothing a tester tried breaks), hidden from tools/list.
ABSORBED: frozenset[str] = frozenset({
    "coverage", "data_gaps", "stream_info",                       # -> about
    "licenses", "licence_tools",                                  # -> licence
    "checkpoints_near", "checkpoints_summary",                    # -> checkpoints
    "incidents_near", "incidents_summary",                        # -> incidents
    "place_profile", "place_history", "place_pattern", "where_is",  # -> place
    "latest_news", "search",                                      # -> news
    "trend", "compare",                                           # -> series
    "what_correlates_with",                                       # -> correlate
    "area_history",                                               # -> insights scope=governorates
})

_PLACE = {"type": "string",
          "description": "a place name, Arabic or English — a town, a checkpoint, "
                         "a governorate (e.g. رام الله, Nablus, حوارة)"}
_LATLON = {"lat": {"type": "number", "description": "latitude, instead of `place`"},
           "lon": {"type": "number", "description": "longitude, instead of `place`"}}
_DIRECTION = {"type": "string", "enum": ["inbound", "outbound", "both"],
              "default": "both",
              "description": "direction of travel relative to the checkpoint"}


def _bad(msg: str) -> TypeError:
    # A TypeError is what the transports already treat as "bad arguments":
    # the caller gets the sentence, not a system error.
    return TypeError(msg)


# ── routers: (public args) -> (internal tool, internal args) ─────────────────

def _r_licence(a: dict) -> tuple[str, dict]:
    scope = a.get("scope") or ("sources" if a.get("source") else "tools")
    if scope == "sources":
        return "licenses", {"source": a.get("source")}
    if scope == "tools":
        return "licence_tools", {}
    raise _bad("scope must be `tools` or `sources`")


def _r_checkpoints(a: dict) -> tuple[str, dict]:
    if a.get("place") or a.get("lat") is not None or a.get("lon") is not None:
        return "checkpoints_near", a
    return "checkpoints_summary", {}


def _r_incidents(a: dict) -> tuple[str, dict]:
    if a.get("place") or a.get("lat") is not None or a.get("lon") is not None:
        return "incidents_near", a
    return "incidents_summary", {"hours": a.get("hours", 24)}


_PLACE_VIEWS = {"profile": "place_profile", "history": "place_history",
                "pattern": "place_pattern", "locate": "where_is"}


def _r_place(a: dict) -> tuple[str, dict]:
    view = a.get("view") or "profile"
    if view not in _PLACE_VIEWS:
        raise _bad("view must be one of " + ", ".join(_PLACE_VIEWS))
    return _PLACE_VIEWS[view], a


def _r_news(a: dict) -> tuple[str, dict]:
    # Both modes take the place and the kind (F047); `hours` reaches both.
    a = {**a, "area": a.get("place") or a.get("area")}
    if a.get("text"):
        return "search", {**a, "kind": a.get("kind") or "all"}
    return "latest_news", {**a, "kind": a.get("kind") or "news"}


def _r_crossings(a: dict) -> tuple[str, dict]:
    return "crossings", {"area": a.get("place") or a.get("area")}


def _r_series(a: dict) -> tuple[str, dict]:
    ind = str(a.get("indicators") or a.get("indicator") or "").strip()
    if not ind:
        raise _bad("`indicators` is required: one indicator string, or two to six "
                   "comma-separated to compare")
    if "," in ind:
        return "compare", {"indicators": ind, "place": a.get("place")}
    return "trend", {"indicator": ind, "days": a.get("days"), "place": a.get("place")}


def _r_correlate(a: dict) -> tuple[str, dict]:
    if a.get("indicator"):
        return "what_correlates_with", a
    return "correlate", a


def _r_insights(a: dict) -> tuple[str, dict]:
    scope = a.get("scope") or "place"
    if scope == "governorates":
        return "area_history", {"state_kind": a.get("state_kind"), "days": a.get("days")}
    if scope != "place":
        raise _bad("scope must be `place` or `governorates`")
    return "insights", a


FACADES: dict[str, dict[str, Any]] = {
    "licence": {
        "description": "What may be REUSED from here, and how. scope=tools (default): "
                       "what each public tool may hand a commercial partner — whole, "
                       "excerpt, per-row, or cited fact only. scope=sources: who owns "
                       "the databank's rows, each licence's obligation, attribution "
                       "text, and which publishers' terms nobody has read yet. Call it "
                       "before republishing anything.",
        "schema": {"type": "object", "properties": {
            "scope": {"type": "string", "enum": ["tools", "sources"], "default": "tools",
                      "description": "tools = per public tool; sources = per data owner"},
            "source": {"type": "string",
                       "description": "sources scope only: one source key or name"}}},
        "route": _r_licence},
    "checkpoints": {
        "description": "Checkpoints around a place, nearest first, with what is known "
                       "and how much is NOT known; with no place, the West-Bank-wide "
                       "picture (open / closed / congested / no recent reading, and "
                       "which are closed now). For ONE named checkpoint use "
                       "checkpoint_status.",
        "schema": {"type": "object", "properties": {
            "place": {**_PLACE, "description": "centre of the search; omit for the "
                                              "West-Bank-wide summary"},
            **_LATLON,
            "direction": _DIRECTION,
            "radius_km": {"type": "number", "default": 15,
                          "description": "search radius around the place"},
            "limit": {"type": "integer", "default": 6,
                      "description": "how many nearest checkpoints to list"}}},
        "route": _r_checkpoints},
    "incidents": {
        "description": "Located incidents — raids, settler attacks, closures, arrests, "
                       "demolitions — each with how many INDEPENDENT channels reported "
                       "it. Around a place when `place` (or lat/lon) is given; otherwise "
                       "West-Bank-wide counts by type and the worst-affected places. "
                       "Times are when a channel POSTED, precise to the hour.",
        "schema": {"type": "object", "properties": {
            "place": {**_PLACE, "description": "centre of the search; omit for the "
                                              "West-Bank-wide summary"},
            **_LATLON,
            "hours": {"type": "integer", "default": 12, "minimum": 1, "maximum": 168,
                      "description": "lookback window; default 12 around a place, "
                                     "24 for the summary; at most 168"},
            "radius_km": {"type": "number", "default": 25,
                          "description": "search radius around the place"},
            "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50,
                      "description": "how many incidents to list"}}},
        "route": _r_incidents},
    "place": {
        "description": "One place, four views. profile (default): everything both "
                       "tiers hold — live checkpoint state, recent history, hourly "
                       "pattern, nearby incidents. history: daily report counts and "
                       "what they said. pattern: what USUALLY happens by hour of day. "
                       "locate: the coordinates. A town and the checkpoint named after "
                       "it are different rows; the answer says which it covers.",
        "schema": {"type": "object", "properties": {
            "place": _PLACE,
            "view": {"type": "string",
                     "enum": ["profile", "history", "pattern", "locate"],
                     "default": "profile", "description": "which view to return"},
            "days": {"type": "integer", "default": 30, "minimum": 7, "maximum": 365,
                     "description": "lookback window for profile and history "
                                    "(pattern uses 60); 7 to 365"},
            "state_kind": {"type": "string",
                           "description": "history/pattern/locate: the kind of state, "
                                          "e.g. checkpoint_flow, road_closure, "
                                          "crossing_status"}},
            "required": ["place"]},
        "route": _r_place},
    "news": {
        "description": "The newest ingested messages (Telegram channels and RSS), "
                       "optionally filtered by area — or, with `text`, a literal search "
                       "for the words somebody used. Bodies are excerpted to 250 "
                       "characters for partners: the channels own their wording.",
        "schema": {"type": "object", "properties": {
            "text": {"type": "string",
                     "description": "words to match literally (a different spelling "
                                    "will not match); omit for the newest messages"},
            "place": {"type": "string",
                      "description": "a governorate or town, in either mode"},
            "hours": {"type": "integer", "default": 168, "minimum": 1, "maximum": 720,
                      "description": "lookback window in hours, in either mode"},
            "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 25,
                      "description": "how many messages to return (at most 25)"},
            "kind": {"type": "string", "enum": ["news", "roads", "all"],
                     "description": "news leaves out the road-status tables, roads returns "
                                    "only them, all returns everything; omit it and the newest "
                                    "messages use news, a word search uses all"}}},
        "route": _r_news},
    "series": {
        "description": "A databank series over time. One indicator: is it above or "
                       "below its own baseline (the last three readings against the "
                       "median of the rest), and how old the newest reading is. Two to "
                       "six comma-separated indicators: side by side in their own units "
                       "over the window they share — nothing is rescaled onto one axis. "
                       "Find indicator strings with correlate(search=...).",
        "schema": {"type": "object", "properties": {
            "indicators": {"type": "string",
                           "description": "one indicator string, or two to six "
                                          "comma-separated"},
            "place": {"type": "string", "description": "optional: restrict to one place"},
            "days": {"type": "integer", "default": 90, "minimum": 7, "maximum": 3650,
                     "description": "single-indicator mode: the window the comparison "
                                    "is computed over, 7 to 3650 days"}},
            "required": ["indicators"]},
        "route": _r_series},
    "correlate": {
        "description": "Concepts, indicator search, correlation and scanning over the "
                       "databank. No arguments: the concepts held. `search`/`concept`: "
                       "find an indicator string. `a` and `b`: correlate two series — "
                       "REFUSES rather than returning a misleading number (two cumulative "
                       "tolls correlate at ~1.0 and that measures time). `indicator` "
                       "alone: SCAN for series that move with it; results are hypotheses "
                       "to check pairwise, never findings, and the answer says how many "
                       "tests it ran.",
        "schema": {"type": "object", "properties": {
            "a": {"type": "string", "description": "first indicator (pair mode)"},
            "b": {"type": "string", "description": "second indicator (pair mode)"},
            "search": {"type": "string", "description": "substring of an indicator"},
            "concept": {"type": "string", "description": "filter the search by concept"},
            "indicator": {"type": "string",
                          "description": "scan mode: the series to scan around"},
            "place": {"type": "string", "description": "scan mode: restrict to one place"},
            "place_id": {"type": "integer", "description": "pair mode: restrict to one place"},
            "candidates": {"type": "integer", "default": 40,
                           "description": "scan mode: how many series to consider"},
            "max_lag": {"type": "integer", "minimum": 0, "maximum": 366,
                        "description": "pair mode: days to scan for a lagged fit "
                                       "(at most 366); adds a caveat"},
            "allow_same_concept": {"type": "boolean", "default": False,
                                   "description": "also test series of the same concept"}}},
        "route": _r_correlate},
    "crossings": {
        "description": "Status of Gaza and West Bank crossings (Rafah, Kerem Shalom, Erez, "
                       "Zikim, Kissufim, Allenby / King Hussein…): open / partial / closed / "
                       "unknown, where `partial` is NOT open. A crossing nobody reports reads "
                       "`unknown`, and the answer says which crossings have no source at all "
                       "— most Gaza crossings today.",
        "schema": {"type": "object", "properties": {
            "place": {"type": "string",
                      "description": "optional: a governorate or region, e.g. غزة, Jericho"}}},
        "route": _r_crossings},
    "insights": {
        "description": "ONE reduction of a place over a window: checkpoint status "
                       "distribution around it, which checkpoints actually changed, the "
                       "busiest hours, incident counts by type, and the measured "
                       "precision of each subject. Use it for 'what was happening around "
                       "X last month' instead of fetching rows and averaging them. "
                       "scope=governorates: totals per governorate instead of one place.",
        "schema": {"type": "object", "properties": {
            "place": _PLACE, **_LATLON,
            "days": {"type": "integer", "default": 30, "description": "lookback window"},
            "radius_km": {"type": "number", "default": 15,
                          "description": "radius around the place"},
            "scope": {"type": "string", "enum": ["place", "governorates"],
                      "default": "place",
                      "description": "place = around one place; governorates = per governorate"},
            "state_kind": {"type": "string",
                           "description": "governorates scope: one kind of state, "
                                          "e.g. checkpoint_flow"}}},
        "route": _r_insights},
}

# The order a first-time reader should meet them in.
ORDER = ["about", "checkpoint_status", "checkpoints", "can_i_travel", "incidents",
         "place", "insights", "news", "weather_now", "connectivity_now", "fuel_prices",
         "crossings", "databank", "series", "correlate", "licence"]

LISTED: list[str] = [n for n in ORDER
                     if n in FACADES or (n in TOOLS and n not in HOST_ONLY
                                         and n not in ABSORBED)]

# Nothing may be listed that neither exists nor routes, and nothing public may
# be left out of the order by accident: the difference is a build error.
_unlisted = (set(TOOLS) - HOST_ONLY - ABSORBED - set(FACADES)) - set(LISTED)
if _unlisted:
    raise RuntimeError(f"public tools missing from mcp_facades.ORDER: {sorted(_unlisted)}")


def route(name: str, args: dict | None) -> tuple[str, dict]:
    """(public name, public args) -> (internal tool, internal args).

    A name that is not a façade routes to itself unchanged — that is how the
    absorbed aliases keep working. Arguments the target does not take are
    dropped (the defaults differ per tool: `place_pattern` uses 60 days,
    `incidents_summary` 24 hours), and None is never passed through so a tool's
    own default applies.
    """
    args = dict(args or {})
    spec = FACADES.get(name)
    if spec is None:
        # `place` is the one name for a place everywhere (PLAN P0-A.1), but
        # checkpoint_status takes `name`: {place: "عصيرة"} failed with a bare
        # argument error and no answer (Claude web's test, 2026-09-25).
        props = set(((TOOLS.get(name) or (None, None, {}))[2] or {}).get("properties", {}))
        if "place" in args and "place" not in props and "name" in props and "name" not in args:
            args["name"] = args.pop("place")
        return name, args
    target, kwargs = spec["route"](args)
    allowed = set((TOOLS[target][2] or {}).get("properties", {}))
    return target, {k: v for k, v in kwargs.items() if k in allowed and v is not None}


def listed_tools(include_host_only: bool = False) -> list[dict]:
    """tools/list for both transports: the 16 public names, in reading order."""
    out = []
    for n in LISTED:
        if n in FACADES:
            d, s = FACADES[n]["description"], FACADES[n]["schema"]
        else:
            _, d, s = TOOLS[n]
        out.append({"name": n, "description": d, "inputSchema": s})
    if include_host_only:
        for n in sorted(HOST_ONLY):
            _, d, s = TOOLS[n]
            out.append({"name": n, "description": d, "inputSchema": s})
    return out


def public_name_for(internal: str) -> str | None:
    """Which listed name now answers for an absorbed tool (docs and errors)."""
    for n, spec in FACADES.items():
        if internal in spec.get("absorbs", ()):
            return n
    lookup = {"coverage": "about", "data_gaps": "about", "stream_info": "about",
              "licenses": "licence", "licence_tools": "licence",
              "checkpoints_near": "checkpoints", "checkpoints_summary": "checkpoints",
              "incidents_near": "incidents", "incidents_summary": "incidents",
              "place_profile": "place", "place_history": "place",
              "place_pattern": "place", "where_is": "place",
              "latest_news": "news", "search": "news",
              "trend": "series", "compare": "series",
              "what_correlates_with": "correlate", "area_history": "insights"}
    return lookup.get(internal)
