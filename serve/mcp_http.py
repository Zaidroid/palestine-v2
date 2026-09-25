"""MCP over streamable HTTP — the same tools, without a clone and a venv.

    POST https://live-api.zaidlab.xyz/mcp      (JSON-RPC 2.0, stateless)

`serve/mcp_server.py` speaks MCP over stdio, which means the caller needs this
repository, a Python, an environment and a path. That is fine for Fawwaz and
Sameera, who run on this machine, and it is a wall for anybody else: a room of
people who want to see what an MCP server is should be one line from talking to
one, not twenty minutes from it.

So the same TOOLS table is served over HTTP as well. One table, two transports —
if the tools drift apart the stdio and the HTTP surface start disagreeing about
what this system knows, which is the failure that makes people stop trusting
either one.

THE OPS TOOLS ARE NOT HERE
`system_health` and `ops_digest` describe THIS MACHINE — failing units, feed
faults, the maintenance ledger. Over stdio the caller is already on the host.
Over the open internet that is infrastructure detail handed to anyone with the
URL, and it answers a question nobody outside asked. The road tools stay; the
machine tools stay home.

STILL NO WRITE PATH
The crowd write endpoints are absent here exactly as they are absent from the
stdio server. An agent that can file reports is the sock-puppet problem at
machine speed. Read surface at parity, write surface human — and now that the
read surface is public, that line matters more, not less.

WHY IT CALLS ITSELF OVER HTTP
The tool functions reach the API over localhost, including when the API is this
same process. Importing the query layer directly would be one less hop and a
second data path — two ways to get an answer that can disagree after a change to
one of them. The hop is cheap and localhost callers are exempt from the limiter.

It does cost a thread, though, and that is the one real trap: a tool call holds
a worker while the endpoint it calls needs a worker of its own. Sharing one pool
means enough simultaneous callers deadlock the pool against itself, so MCP calls
run on their own executor and can only ever queue behind each other.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from serve import mcp_oauth as oauth
from serve import mcp_usage as usage
from serve import licence
from serve.mcp_en import add_english
from serve.mcp_facades import FACADES, LISTED, listed_tools, route
from serve.mcp_server import API, HOST_ONLY, TOOLS

# Defined beside TOOLS rather than here, so adding a tool there cannot publish
# it by forgetting to update a list over here.
PRIVATE = HOST_ONLY
PUBLIC_TOOLS = {n: t for n, t in TOOLS.items() if n not in PRIVATE}

# Protocol versions this transport can speak. The client's choice is echoed when
# we know it, because a server that answers a 2024 client with a 2025 version
# string is telling it to expect framing it cannot parse.
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = "2025-06-18"

# Bounded, and separate from the pool serving the endpoints these tools call.
# Sixteen simultaneous MCP calls is far past a room of people exploring; the
# seventeenth waits rather than starving the API underneath it.
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="mcp")

# ── what one POST may carry (audit F091/F081/F302, 2026-09-25) ───────────────
# Measured before these existed: a key with daily_quota=1 answered a 500-message
# batch in one POST, its quota counter read 1 and the limiter had seen one
# request; the body had no size at all, so Cloudflare's 100 MB was the only cap
# in front of `json.loads` in the single process serving REST, SSE and MCP.
# The 2025-06-18 protocol removed batching; older clients still batch a
# handshake, which is a handful of messages, so ten is generous. The largest
# honest request is a tools/call with a few short arguments — a few hundred
# bytes — so 256 KB refuses nothing real.
MAX_BATCH = 10
MAX_BODY_BYTES = 256 * 1024
_log = logging.getLogger("serve.mcp_http")

# ── what one reply may carry (audit F051, 2026-09-25) ────────────────────────
# PLAN P0-A.3 asked for "hard caps on payload bytes per tool with a test", and
# there was neither: databank(limit=2000) was ~276 KB, carried twice on the wire
# (text and structured). The budget is by what the tool EMITS, because a cut
# means different things to different payloads. Shortening a databank list is a
# paging problem, stated in the payload. Shortening `closed_now` hides a closed
# checkpoint — so the live, derived tools get a runaway guard far above any
# real answer instead of a trim, and a cut, when it happens, always says so.
PAYLOAD_BYTES = {
    licence.DERIVED: 1024 * 1024,
    licence.METADATA: 256 * 1024,
    licence.MEASURED: 128 * 1024,
    licence.VERBATIM: 128 * 1024,
    licence.DATABANK: 96 * 1024,
}
PAYLOAD_BYTES_DEFAULT = 96 * 1024

# Protocol versions that predate `structuredContent` (added in 2025-06-18). A
# client that says it speaks one of these cannot read the field, so sending it
# only doubles the reply. A client that says nothing still gets both.
_PRE_STRUCTURED = ("2024-11-05", "2025-03-26")

INSTRUCTIONS = (
    "Palestine Data — live + databank (بيانات فلسطين). Tier 1: what is happening "
    "NOW on the West Bank's roads — checkpoints per direction, journeys, incidents "
    "— read from crowd and news channels, corroborated across independent "
    "reporters and decayed with age. Tier 2: a historical databank of 200,000+ rows "
    "(1922 → today: casualties, demolitions, prisoners, displacement, food prices, "
    "funding, health…) with a licence on every row.\n\n"
    "Every tool returns `answer` (Palestinian Arabic, written to be read aloud "
    "verbatim) and `answer_en` (the same facts in English), plus the structured "
    "data behind them. The answer already carries the uncertainty — how old the "
    "reading is, how many independent reporters agree, whether the field has any "
    "source at all. Do not rephrase it into something more confident. Three words "
    "are never blurred: a VALUE we assert now; `unknown` — nobody credible looked "
    "recently, which is an answer, not a gap, and never the last value; `no source` "
    "— nothing measures this, ever. Sending someone toward a checkpoint that closed "
    "three hours ago is the failure every layer here is built to prevent.\n\n"
    "Start with `about`. For one checkpoint use `checkpoint_status`; for a journey "
    "`can_i_travel` and read its `verdict` — `unverified` means we could not see "
    "enough of the road to call it open. For a place over a period call `insights` "
    "and do not fetch rows to average them yourself. `place` gives one place in four "
    "views; `incidents`, `checkpoints` and `news` take a place or answer West-Bank-"
    "wide; `databank`, `series` and `correlate` are the historical side; `licence` "
    "says what you may republish."
)

# ── resources ────────────────────────────────────────────────────────────────
# Three things a caller should read BEFORE asking a question, offered as
# attachable context rather than as a tool call they have to think to make. The
# first two are live; the third is the contract that makes the other two
# readable, and getting it wrong is the single most dangerous way to consume
# this system.

RESOURCES = [
    {"uri": "palestine://coverage", "name": "coverage",
     "title": "What is held, and what is held nothing for",
     "description": "Sources, live states, and the fields NO source reports. "
                    "Read before answering anything about power, water, "
                    "cooking gas or crossings.",
     "mimeType": "application/json"},
    {"uri": "palestine://licensing", "name": "licensing",
     "title": "Who owns this data and what each licence obliges",
     "description": "Open / commercial-permissive / share-alike tiers and "
                    "per-source attribution. Read before telling anyone they "
                    "may reuse or sell a figure.",
     "mimeType": "application/json"},
    {"uri": "palestine://reading-contract", "name": "reading-contract",
     "title": "How to read a value from this system",
     "description": "What value, unknown, last_known_value, confidence and "
                    "independent_sources mean, and the one misreading that "
                    "puts somebody on a closed road.",
     "mimeType": "application/json"},
]

READING_CONTRACT = {
    "value": ("What we are willing to assert RIGHT NOW. 'unknown' means nobody "
              "credible has looked recently — it is an answer, not a gap, and "
              "must never be rendered as the last value."),
    "last_known_value": ("What it was before it decayed. Show it WITH "
                         "age_minutes or not at all."),
    "confidence": ("Decayed from corroboration by independent observers. Below "
                   "the kind's floor, value becomes 'unknown'."),
    "independent_sources": ("How many INDEPENDENT units agree. Nine channels "
                            "reposting each other count as one."),
    "answer": ("Arabic, written to be read aloud, and already carrying the "
               "uncertainty. Do not rephrase it into something more confident."),
    "answer_en": "The same facts rendered in English, not a translation of the above.",
    "refused": ("Some tools decline rather than return a misleading number. A "
                "refusal with reasons is the answer; do not substitute an "
                "estimate for it."),
    "the_one_mistake": ("Reading `value` and ignoring everything beside it. "
                        "During a fuel shortage that costs somebody a tank of "
                        "petrol; at a checkpoint it can cost more."),
}


def _read_coverage() -> str:
    from serve.mcp_server import coverage
    return json.dumps(coverage(), ensure_ascii=False, default=str)


def _read_licensing() -> str:
    from serve.mcp_server import licenses
    return json.dumps(licenses(), ensure_ascii=False, default=str)


READERS = {
    "palestine://coverage": _read_coverage,
    "palestine://licensing": _read_licensing,
    "palestine://reading-contract":
        lambda: json.dumps(READING_CONTRACT, ensure_ascii=False),
}


# ── prompts ──────────────────────────────────────────────────────────────────
# Guided explorations, which arrive in a client as slash commands. Each one
# encodes the ORDER the tools should be called in and how to read what comes
# back — the part a first-time caller gets wrong, and the part that decides
# whether an answer is honest.

def _p_route(a: dict) -> str:
    return (f"Work out whether someone can travel from {a.get('origin', '?')} to "
            f"{a.get('destination', '?')} right now.\n\n"
            "Call can_i_travel first. Then read the result carefully: a journey "
            "needs EVERY checkpoint on it passable, so one confirmed closure "
            "blocks the route, while checkpoints nobody has reported recently "
            "never block it and must be named as unknown rather than assumed "
            "open. If it is blocked, report the alternate route and its verdict. "
            "State how many checkpoints on the route actually have recent "
            "reports — that number is the honesty of the whole answer.")


def _p_place(a: dict) -> str:
    return (f"Give a briefing on {a.get('place', '?')}.\n\n"
            "Call place (view=profile). Then say plainly: what is known right now, how "
            "old that knowledge is, and what is NOT known. If the place has both "
            "a town and a checkpoint of the same name, say which one the answer "
            "covers. Do not fill silence with inference — 'no recent reports' is "
            "a finding worth stating on its own.")


def _p_missing(a: dict) -> str:
    return ("Find out what this system CANNOT answer.\n\n"
            "Call about, then about with section=gaps. Report three things: fields with no "
            "source at all, series that have gone stale, and upstreams that have "
            "died. Be specific that a field with no source will never answer, no "
            "matter how often it is asked — that is different from a field that "
            "is merely quiet today. Finish with which gap you would close first "
            "and why.")


def _p_relationship(a: dict) -> str:
    topic = a.get("topic", "")
    return (f"Explore what moves together in this data{', around ' + topic if topic else ''}.\n\n"
            "Use correlate with no arguments to see the concepts, then with "
            "`search` to find indicator strings, then correlate with `indicator` "
            "to scan, and finally correlate with `a` and `b` on the single most "
            "promising pair to get its caveats and attribution.\n\n"
            "Treat every scan row as a hypothesis. The scan reports how many "
            "tests it ran, and at forty tests a couple will look significant "
            "from noise alone. If a tool refuses, report the refusal and its "
            "reason as the result — a refusal is a finding about the data, not "
            "an obstacle to route around.")


def _p_reuse(a: dict) -> str:
    return (f"Can I reuse or sell figures from {a.get('source', 'this databank')}?\n\n"
            "Call licence with scope=sources. Distinguish three things clearly: rows that are "
            "republishable with attribution, rows that are sellable outright, "
            "and rows under a share-alike licence, which are sellable but force "
            "any derived DATABASE to carry the same licence. Name the sources "
            "whose terms nobody has verified at the publisher — those are the "
            "risky ones. Quote the attribution text that must travel with the "
            "figures.")


PROMPTS = [
    {"name": "route_check", "title": "Can I travel?",
     "description": "Check a journey end to end, including what is unknown along it.",
     "arguments": [{"name": "origin", "description": "e.g. رام الله, Ramallah",
                    "required": True},
                   {"name": "destination", "description": "e.g. نابلس, Nablus",
                    "required": True}],
     "build": _p_route},
    {"name": "place_briefing", "title": "Brief me on a place",
     "description": "Live state, recent history, hourly pattern and incidents for one place.",
     "arguments": [{"name": "place", "description": "e.g. حوارة, Huwara",
                    "required": True}],
     "build": _p_place},
    {"name": "whats_missing", "title": "What can't this answer?",
     "description": "The blind spots: fields with no source, stale series, dead upstreams.",
     "arguments": [], "build": _p_missing},
    {"name": "find_a_relationship", "title": "What moves with what?",
     "description": "Concepts to indicators to a scan to one careful pair, with the refusals kept.",
     "arguments": [{"name": "topic",
                    "description": "optional: a subject to start from",
                    "required": False}],
     "build": _p_relationship},
    {"name": "reuse_check", "title": "May I reuse this data?",
     "description": "Licence tiers, share-alike obligations and attribution before you publish.",
     "arguments": [{"name": "source", "description": "optional: one source key or name",
                    "required": False}],
     "build": _p_reuse},
]


router = APIRouter()


def _scrub(text: str) -> str:
    """Keep the host out of the reply.

    An httpx failure quotes the URL it was fetching, which is this API's
    internal address, and a filesystem error quotes the path it touched. Both
    are the kind of detail that tells a stranger where to push next, and
    neither helps the model recover — it cannot reach either one.
    """
    text = text.replace(API, "the API")
    return re.sub(r"(?:/home|/opt|/etc|/var|/root)/\S*", "<path>", text)[:400]


def _ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


# Declared so a client gets typed data instead of a JSON string it has to parse
# out of a chat message. Deliberately has no `required` list: the tools return
# different shapes and a schema that fails validation on a true answer would
# turn a working reply into a client-side error.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string",
                   "description": "Arabic, written to be read aloud. Already "
                                  "contains the caveat — do not rephrase it "
                                  "into something more confident."},
        "answer_en": {"type": "string",
                      "description": "The same answer built from the same "
                                     "fields in English. Not a translation."},
        "caveat": {"type": "string"},
        "refused": {"type": "boolean",
                    "description": "true means no number was returned ON "
                                   "PURPOSE. Report the reason, not a guess."},
    },
}


def _tool_list() -> list[dict]:
    """The 16 public names (serve/mcp_facades.py). Absorbed old names still
    answer by name; they are simply not on the menu any more."""
    return [{**t, "outputSchema": OUTPUT_SCHEMA} for t in listed_tools()]


# ── the grading table, read once in a while rather than per call ─────────────
# The per-payload licence block should carry the tool's GRADE and its
# OBLIGATION, and those are read from the database by /v2/licence/tools. Asking
# for that table on every tool call would cost a round trip per request, so it is
# held: grades move when a publisher's terms are re-read or a migration re-grades
# a source, which is not an event that needs to be seen within minutes. A failure
# to read it leaves the block without the grade rather than failing an answer
# about a road.
#
# OFF THE REQUEST PATH (audit F301). The refresh used to run synchronously
# inside the first tool call after the minute expired, and the table behind it
# scans state_observation, claim and the databank whole — so under sparse
# traffic every checkpoint_status paid three table scans before it could answer,
# and a burst paid them once per caller. Now a stale table is served while ONE
# background thread refreshes it; only the very first read in a process, which
# has nothing to serve, waits. A failed read is retried no sooner than
# _GRADES_RETRY, so an unreachable API does not make every call wait for it.
_GRADES: dict = {"at": 0.0, "tried": float("-inf"), "tools": {}, "busy": False}
_GRADES_TTL = 600.0
_GRADES_RETRY = 30.0
_GRADES_LOCK = threading.Lock()


def _refresh_grades() -> None:
    try:
        from serve.mcp_server import api as _api
        fresh = {t["tool"]: t for t in _api("/v2/licence/tools").get("tools", [])}
        if fresh:
            _GRADES["tools"] = fresh
            _GRADES["at"] = time.monotonic()
    except Exception:                                       # noqa: BLE001
        pass
    finally:
        _GRADES["busy"] = False


def _tool_grades() -> dict:
    now = time.monotonic()
    tools = _GRADES["tools"]
    if tools and (now - _GRADES["at"]) < _GRADES_TTL:
        return tools
    with _GRADES_LOCK:
        if _GRADES["busy"] or (now - _GRADES["tried"]) < _GRADES_RETRY:
            return _GRADES["tools"]
        _GRADES["busy"] = True
        _GRADES["tried"] = now
    if tools:
        threading.Thread(target=_refresh_grades, name="licence-grades",
                         daemon=True).start()
        return tools
    _refresh_grades()               # nothing to serve yet: this caller reads it
    return _GRADES["tools"]


def _fit(target: str, out: dict) -> tuple[dict, str]:
    """(payload, its JSON) within the tool's byte budget — serialised once.

    Over budget, the longest top-level lists are halved until it fits, and the
    cut is written into the payload and into the sentence read aloud: a list
    that is quietly short reads as the whole answer. A payload that is still
    over budget with nothing left to halve goes out as it is — the budget is a
    guard against runaway lists, not a reason to drop an answer.
    """
    text = json.dumps(out, ensure_ascii=False, default=str)
    emits = (licence.TOOLS.get(target) or {}).get("emits")
    budget = PAYLOAD_BYTES.get(emits, PAYLOAD_BYTES_DEFAULT)
    if len(text.encode("utf-8")) <= budget:
        return out, text
    cut: dict[str, dict] = {}
    while len(text.encode("utf-8")) > budget:
        lists = [(len(json.dumps(v, ensure_ascii=False, default=str)), k)
                 for k, v in out.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            break
        _, k = max(lists)
        cut.setdefault(k, {"of": len(out[k])})
        out[k] = out[k][: len(out[k]) // 2]
        cut[k]["kept"] = len(out[k])
        text = json.dumps(out, ensure_ascii=False, default=str)
    if cut:
        shown = "; ".join(f"{k}: {c['kept']} of {c['of']}" for k, c in cut.items())
        out["payload_cut"] = {
            **cut, "budget_bytes": budget,
            "note": (f"this reply was cut to fit {budget // 1024} KB ({shown}). "
                     "Nothing was filtered — narrow the question (an indicator, "
                     "a place, a smaller limit) to see the rest.")}
        if isinstance(out.get("answer"), str):
            out["answer"] += (" (الرد مختصر لحجمه: " + "؛ ".join(
                f"{c['kept']} من {c['of']} في {k}" for k, c in cut.items()) + ")")
        if isinstance(out.get("answer_en"), str):
            out["answer_en"] += f" (Reply cut to fit: {shown}.)"
        text = json.dumps(out, ensure_ascii=False, default=str)
    return out, text


def _handle(msg: dict, ip: str | None = None, tier: str = "partner",
            structured: bool = True) -> dict | None:
    """One JSON-RPC message in, one response out — or None for a notification.

    Runs on the MCP executor, so it may block.

    `tier` is the LICENCE tier of the caller, not a permission level: everything
    on this surface is readable by everyone, and the tier decides only what may
    be carried away (F-81). It defaults to `partner`, the narrower of the two, so
    a future call path that forgets to pass it cuts too much rather than
    republishing somebody's article.

    `structured` is False for a client that declared a protocol older than
    `structuredContent`; it gets the text block alone.
    """
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _err(None, -32600, "not a JSON-RPC 2.0 message")

    method, rid = msg.get("method"), msg.get("id")
    # A non-object `params` or a non-string `method` used to raise inside the
    # first `.get` and 500 the whole POST, batch-mates included (audit F395).
    if method is not None and not isinstance(method, str):
        return _err(rid, -32600, "method must be a string")
    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _err(rid, -32602, "params must be an object")

    # A notification has no id and takes no reply, ever — answering one is how
    # a client ends up waiting for a response it will never correlate.
    if rid is None and method and method.startswith("notifications/"):
        return None

    if method == "initialize":
        asked = params.get("protocolVersion")
        return _ok(rid, {
            "protocolVersion": asked if asked in SUPPORTED else DEFAULT_PROTOCOL,
            "capabilities": {"tools": {"listChanged": False},
                             "resources": {"listChanged": False,
                                           "subscribe": False},
                             "prompts": {"listChanged": False}},
            "serverInfo": {"name": "palestine-data",
                           "title": "Palestine Data — live + databank",
                           "version": "2.1.0"},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(rid, {"tools": _tool_list()})
    if method == "resources/list":
        return _ok(rid, {"resources": RESOURCES})
    if method == "resources/templates/list":
        return _ok(rid, {"resourceTemplates": []})
    if method == "resources/read":
        uri = params.get("uri")
        if uri not in READERS:
            return _err(rid, -32602, f"unknown resource: {uri}")
        try:
            text = READERS[uri]()
        except Exception as exc:                            # noqa: BLE001
            return _err(rid, -32603, _scrub(str(exc)))
        return _ok(rid, {"contents": [{"uri": uri, "mimeType": "application/json",
                                       "text": text}]})
    if method == "prompts/list":
        return _ok(rid, {"prompts": [{k: v for k, v in p.items() if k != "build"}
                                     for p in PROMPTS]})
    if method == "prompts/get":
        name = params.get("name")
        p = next((x for x in PROMPTS if x["name"] == name), None)
        if p is None:
            return _err(rid, -32602, f"unknown prompt: {name}")
        pargs = params.get("arguments") or {}
        if not isinstance(pargs, dict):
            return _err(rid, -32602, "arguments must be an object")
        text = p["build"](pargs)
        return _ok(rid, {"description": p["description"],
                         "messages": [{"role": "user",
                                       "content": {"type": "text", "text": text}}]})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _err(rid, -32602, "arguments must be an object")
        # A public name is a façade over the tool that answers (P0-A). The
        # façade decides the target from the arguments and drops what the target
        # does not take; everything after this line sees the INTERNAL name, so
        # the licence grade and the English renderer stay keyed on the tool that
        # produced the payload.
        try:
            target, targs = route(name, args)
        except TypeError as exc:
            return _err(rid, -32602, _scrub(str(exc)))
        if name in PRIVATE or target in PRIVATE:
            return _err(rid, -32601,
                        f"{name} is not served over HTTP — it reports the "
                        f"health of the host, not the state of the country")
        if target not in PUBLIC_TOOLS:
            return _err(rid, -32602, f"unknown tool: {name}")
        started = time.monotonic()
        try:
            out = PUBLIC_TOOLS[target][0](**targs)
            failed = False
        except TypeError as exc:                            # bad arguments
            out, failed = {"error": _scrub(str(exc))}, True
        except Exception as exc:                            # noqa: BLE001
            # Reported as a tool error rather than a protocol error: the call
            # was well-formed and the model should see what went wrong and
            # decide, not be told its request was malformed.
            out, failed = {"error": _scrub(str(exc)),
                           "answer": "صار خطأ بالنظام."}, True
        usage.record(name, args, int((time.monotonic() - started) * 1000),
                     not failed, out, ip)
        if not failed:
            out = add_english(target, out)
        # F-81: the licence block goes on LAST, after the tool and its English
        # have produced everything they are going to produce, and it enforces
        # the tier on the payload rather than describing it. A tool function
        # cannot raise its own tier: the tier is decided from who is calling
        # (below), never from an argument the caller supplied. Graded on the
        # tool that answered; labelled with the name the caller used.
        out = licence.apply(target, out, tier, _tool_grades().get(target),
                            shown_as=name)
        # Serialised ONCE, inside the byte budget; the structured copy is parsed
        # back from that one string rather than dumped a second time (F519).
        if isinstance(out, dict):
            out, text = _fit(target, out)
        else:
            text = json.dumps(out, ensure_ascii=False, default=str)
        result = {"content": [{"type": "text", "text": text}], "isError": failed}
        # The text block stays for older clients, which is what the spec asks
        # for; structuredContent is the same object as data rather than as a
        # string a client has to parse back out of a message.
        if structured and not failed and isinstance(out, dict):
            result["structuredContent"] = json.loads(text)
        return _ok(rid, result)

    if rid is None:
        return None
    return _err(rid, -32601, f"method not found: {method}")


def _dispatch(msg: Any, ip: str | None, tier: str, structured: bool) -> dict | None:
    """`_handle` for one message of a POST, whose failure stays its own.

    `asyncio.gather` re-raises the first exception, so one message that raised
    turned the whole request — every batch-mate's answer with it — into a bare
    500 with no JSON-RPC body (audit F395/F560).
    """
    try:
        return _handle(msg, ip, tier, structured)
    except Exception as exc:                                # noqa: BLE001
        _log.exception("mcp message failed")
        rid = msg.get("id") if isinstance(msg, dict) else None
        return _err(rid, -32603, "internal error: " + _scrub(str(exc)))


# ── the door (W8, 2026-09-23) ────────────────────────────────────────────────
# Until today this endpoint answered anyone who had the URL: a public
# tools/list, a public call, no key anywhere in `serve/`. For a partner release
# that is the first finding their test writes, so every POST now needs a key
# unless it comes from this machine. Keys live in `.keys/` at the root of the
# checkout — gitignored, so this file stays committable — and revocation is a
# file edit, not a deploy.
#
# Resolved from this checkout rather than hard-coded to /home/zaid (audit F164):
# on main-server that is the same path, and a second checkout — a dev API, a
# restore under another user — reads its own keys instead of silently answering
# 401 to every partner. PARTNER_KEYS_PATH overrides it.
KEYS_PATH = Path(os.environ.get("PARTNER_KEYS_PATH")
                 or Path(__file__).resolve().parent.parent / ".keys" / "partner-keys.json")
_KEY_STATE: dict = {"mtime": 0.0, "keys": {}, "counts": {}, "error": None}


def _partner_keys() -> dict:
    """name -> record, re-read when the file changes, so revocation is instant."""
    import json as _json
    try:
        m = KEYS_PATH.stat().st_mtime
    except OSError:
        return {}
    if m != _KEY_STATE["mtime"]:
        try:
            data = _json.loads(KEYS_PATH.read_text())
            _KEY_STATE["keys"] = {k["key"]: k for k in data.get("keys", [])}
            _KEY_STATE["mtime"] = m
            _KEY_STATE["error"] = None
        except Exception as exc:                                 # noqa: BLE001
            # A broken file must not revoke a working key — but it must not be
            # silent either: the edit that broke it may have been the one
            # REMOVING a leaked key, which is then still being served (F592).
            # Logged once per broken version of the file, kept for /health.
            if _KEY_STATE.get("error_mtime") != m:
                _KEY_STATE["error_mtime"] = m
                _log.error("partner-keys file %s is unreadable (%s); still serving "
                           "the %d keys read before it broke — a revocation in "
                           "this edit has NOT taken effect",
                           KEYS_PATH.name, type(exc).__name__, len(_KEY_STATE["keys"]))
            _KEY_STATE["error"] = (f"{KEYS_PATH.name} unreadable since mtime {m:.0f}: "
                                   f"{type(exc).__name__}; previous keys still served")
    return _KEY_STATE["keys"]


def _presented_key(request: Request) -> str | None:
    """Header first, `?key=` second — because a browser-hosted client cannot
    send a header.

    Claude's own connector UI takes ONE url and no header field, and it reacts
    to a 401 by starting an OAuth discovery flow this server does not have: the
    failure it shows is "Authentication failed", which reads like a broken
    server rather than a client that needs a different url shape. So the key is
    accepted as a query parameter too, and `?key=` is scrubbed from the access
    log below so it does not end up in journald.
    """
    auth = request.headers.get("authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return request.headers.get("x-api-key") or request.query_params.get("key")


def _quota_exceeded(record: dict) -> bool:
    """Per-key calls per UTC day, counted in memory, reset by date.

    Charged once per tools/call MESSAGE — not per POST, which let a batch carry
    any number of calls for one unit, and not for the handshake, which is not a
    question answered. Still in memory: a restart resets the day's counts.
    """
    quota = int(record.get("daily_quota") or 0)
    if not quota:
        return False
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slot = _KEY_STATE["counts"]
    if slot.get("day") != day:
        _KEY_STATE["counts"] = {"day": day, "n": {}}
        slot = _KEY_STATE["counts"]
    n = int(slot["n"].get(record["name"], 0))
    slot["n"][record["name"]] = n + 1
    return n >= quota


PUBLIC_KEY_NAME = "public-test"


def _public_test_record() -> tuple[str, dict] | None:
    """(key, record) for the published test key, or None if there is not one.

    Published means it is printed in the 401 body and named on the OAuth consent
    page, so a tester needs to ask nobody before trying the server. It is still
    an ordinary entry: quota'd, attributable by name, and revoked by editing the
    file — an open door cannot be un-opened later, this is the shape that stays
    open on purpose.

    Read rather than written down in code, so publishing or rotating it stays a
    one-line file edit. Absent, the sentence goes away entirely: a 401 must never
    advertise a key that does not work.
    """
    for key, rec in _partner_keys().items():
        if rec.get("name") == PUBLIC_KEY_NAME:
            return key, rec
    return None


def _public_test_key() -> str | None:
    hit = _public_test_record()
    return hit[0] if hit else None


def _no_key_message() -> str:
    """The 401 body — a tester should be able to act on it without asking us."""
    hit = _public_test_record()
    if hit:
        key, rec = hit
        head = ("To test it, use the public key `%s` (%s calls a day, shared, no "
                "signup) as `Authorization: Bearer <key>` or `X-Api-Key`, or "
                "connect through OAuth at "
                "/.well-known/oauth-protected-resource."
                % (key, f"{int(rec.get('daily_quota') or 0):,}"))
    else:
        head = ("Send a key as `Authorization: Bearer <key>` or `X-Api-Key`, or "
                "connect through OAuth at "
                "/.well-known/oauth-protected-resource.")
    return ("this endpoint needs a key. " + head +
            " For a key of your own, ask us — the data is free to read, we only "
            "need to know who is calling.")


# A key in a url must not become a key in a log file. uvicorn's access record
# carries the full path as a positional argument, so the scrub is on the args.
class _ScrubKeys(logging.Filter):
    _RE = re.compile(r"([?&]key=)[A-Za-z0-9_\-]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._RE.sub(r"\1[redacted]", a) if isinstance(a, str) else a
                for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_ScrubKeys())


def _unauthenticated(why: str) -> JSONResponse:
    """A 401 that says how to get a key instead of a bare refusal."""
    # The header is the spec's own pointer (RFC 9728 §5.1): it tells a hosted
    # client where the protected-resource metadata is, which is how Claude's
    # connector finds /register and completes the flow. Without it a client can
    # only guess the well-known URLs — and it did guess, four 404s deep, before
    # this existed.
    return JSONResponse(_err(None, -32001, why), status_code=401, headers={
        "www-authenticate": f'Bearer resource_metadata="{oauth.RESOURCE.rsplit("/mcp", 1)[0]}'
                             f'/.well-known/oauth-protected-resource", error="invalid_token"',
        "x-key-request": "https://zaidlab.xyz/palestine"})


def _too_large() -> JSONResponse:
    return JSONResponse(_err(None, -32600, f"request body over {MAX_BODY_BYTES // 1024} KB"),
                        status_code=413)


async def _read_capped(request: Request) -> bytes | None:
    """The body, or None past MAX_BODY_BYTES — refused before it is held whole.

    Content-Length is checked first because it costs nothing; the stream is
    counted anyway, because a chunked body has no Content-Length to believe.
    """
    try:
        if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
            return None
    except ValueError:
        return None
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_BODY_BYTES:
            return None
    return bytes(buf)


_QUOTA_MSG = "daily quota for this key is used up; it resets at midnight UTC"


@router.post("/mcp", include_in_schema=False)
async def mcp_endpoint(request: Request) -> Response:
    raw = await _read_capped(request)
    if raw is None:
        return _too_large()
    try:
        payload = json.loads(raw or b"")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(_err(None, -32700, "parse error"), status_code=400)

    batch = isinstance(payload, list)
    msgs = payload if batch else [payload]
    if not msgs:
        return JSONResponse(_err(None, -32600, "empty batch"), status_code=400)
    if len(msgs) > MAX_BATCH:
        return JSONResponse(_err(None, -32600, f"a batch may carry at most {MAX_BATCH} "
                                 "messages; send them in separate requests"),
                            status_code=400)

    from serve import ratelimit as rl
    from serve.ratelimit import client_ip, is_local
    ip = client_ip(request)

    # The licence tier (F-81). `house` is this machine's own callers — Fawwaz,
    # Sameera, the watchdog — who are inside the system rather than consuming
    # it, and who need the full message body to do the classification work the
    # published answers are built from. Everyone reaching this endpoint over the
    # tunnel is `partner`, whatever their key says: the cut is a copyright
    # question about somebody else's wording, and a key we issued cannot grant
    # a licence we do not hold.
    tier = "house" if is_local(ip) else "partner"

    # The limiter middleware charged this POST once. A batch is that many
    # requests' worth of work, so every further message is charged too, before
    # any of it runs; local callers stay exempt inside `check`.
    for _ in msgs[1:]:
        ok, retry = rl.check(ip, "mcp")
        if not ok:
            return JSONResponse(
                _err(None, -32003, "rate limited: every message in a batch counts "
                                   "as a request"),
                status_code=429, headers={"Retry-After": str(retry)})

    record = None
    if not is_local(ip):
        key = _presented_key(request)
        keys = _partner_keys()
        if key and key in keys:                       # a partner key: quota per key
            record = keys[key]
        elif key:
            # An OAuth token answers to the key it was minted from, as the key
            # file says NOW: revoked with it, metered against its quota (F090).
            record = oauth.token_key(key)
        if record is None:
            return _unauthenticated(_no_key_message())

    # Quota per tools/call, decided before anything runs. A single call past
    # the quota is a 429 as it always was; in a batch, the calls past it are
    # refused one by one and the rest are answered.
    refused: dict[int, dict] = {}
    if record is not None:
        for i, msg in enumerate(msgs):
            if isinstance(msg, dict) and msg.get("method") == "tools/call" \
                    and _quota_exceeded(record):
                refused[i] = _err(msg.get("id"), -32002, _QUOTA_MSG)
    if refused and not batch:
        return JSONResponse(refused[0], status_code=429)

    declared = (request.headers.get("mcp-protocol-version") or "").strip()
    structured = declared not in _PRE_STRUCTURED

    loop = asyncio.get_running_loop()

    async def one(i: int, msg: Any) -> dict | None:
        if i in refused:
            return refused[i]
        return await loop.run_in_executor(_POOL, _dispatch, msg, ip, tier, structured)

    replies = [r for r in await asyncio.gather(*(one(i, x) for i, x in enumerate(msgs)))
               if r is not None]

    # Nothing but notifications: the spec wants an accepted-with-no-body, and a
    # client that gets `null` back instead treats it as a malformed response.
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if batch else replies[0])


@router.get("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
async def mcp_no_stream() -> Response:
    """No server-initiated stream and no session to end.

    This transport is stateless: every POST carries its own context, which is
    what lets it sit behind a tunnel with no sticky routing. 405 is the
    spec's way of saying so, and clients fall back to POST-only cleanly.

    Live changes are not lost — they are on /v2/stream as SSE, which is a
    better fit for them anyway.
    """
    return JSONResponse(
        {"error": "this MCP endpoint is stateless — POST JSON-RPC to /mcp",
         "stream": "/v2/stream (server-sent events)"},
        status_code=405, headers={"Allow": "POST"})
