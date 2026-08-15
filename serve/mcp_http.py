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
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from serve import mcp_usage as usage
from serve.mcp_en import add_english
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

INSTRUCTIONS = (
    "Live and historical data for the West Bank and Gaza: checkpoints, fuel, "
    "incidents, road routing, weather, connectivity, and a 186k-row historical "
    "databank with per-source licensing.\n\n"
    "Every tool returns a short Arabic `answer` written to be read aloud "
    "verbatim, plus the structured data behind it. The `answer` already carries "
    "the uncertainty — how old the reading is, whether anyone independent "
    "corroborated it, whether the field has any source at all. Do not rephrase "
    "it into something more confident. This system never asserts a decayed "
    "reading as current, and smoothing that away in your reply defeats the "
    "point: 'unknown' means nobody credible has looked recently, which is an "
    "answer, not a gap. Sending someone toward a checkpoint that closed three "
    "hours ago is the failure every layer here is built to prevent.\n\n"
    "Start with `coverage` to see what is held and what is held nothing for."
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
            "Call place_profile. Then say plainly: what is known right now, how "
            "old that knowledge is, and what is NOT known. If the place has both "
            "a town and a checkpoint of the same name, say which one the answer "
            "covers. Do not fill silence with inference — 'no recent reports' is "
            "a finding worth stating on its own.")


def _p_missing(a: dict) -> str:
    return ("Find out what this system CANNOT answer.\n\n"
            "Call coverage and data_gaps. Report three things: fields with no "
            "source at all, series that have gone stale, and upstreams that have "
            "died. Be specific that a field with no source will never answer, no "
            "matter how often it is asked — that is different from a field that "
            "is merely quiet today. Finish with which gap you would close first "
            "and why.")


def _p_relationship(a: dict) -> str:
    topic = a.get("topic", "")
    return (f"Explore what moves together in this data{', around ' + topic if topic else ''}.\n\n"
            "Use correlate with no arguments to see the concepts, then with "
            "`search` to find indicator strings, then what_correlates_with to "
            "scan, and finally correlate on the single most promising pair to "
            "get its caveats and attribution.\n\n"
            "Treat every scan row as a hypothesis. The scan reports how many "
            "tests it ran, and at forty tests a couple will look significant "
            "from noise alone. If a tool refuses, report the refusal and its "
            "reason as the result — a refusal is a finding about the data, not "
            "an obstacle to route around.")


def _p_reuse(a: dict) -> str:
    return (f"Can I reuse or sell figures from {a.get('source', 'this databank')}?\n\n"
            "Call licenses. Distinguish three things clearly: rows that are "
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
    return [{"name": n, "description": d, "inputSchema": s,
             "outputSchema": OUTPUT_SCHEMA}
            for n, (_, d, s) in PUBLIC_TOOLS.items()]


def _handle(msg: dict, ip: str | None = None) -> dict | None:
    """One JSON-RPC message in, one response out — or None for a notification.

    Runs on the MCP executor, so it may block.
    """
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _err(None, -32600, "not a JSON-RPC 2.0 message")

    method, rid = msg.get("method"), msg.get("id")
    params = msg.get("params") or {}

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
            "serverInfo": {"name": "palestine-live-tracker", "version": "2.0.0"},
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
        text = p["build"](params.get("arguments") or {})
        return _ok(rid, {"description": p["description"],
                         "messages": [{"role": "user",
                                       "content": {"type": "text", "text": text}}]})

    if method == "tools/call":
        name = params.get("name")
        if name in PRIVATE:
            return _err(rid, -32601,
                        f"{name} is not served over HTTP — it reports the "
                        f"health of the host, not the state of the country")
        if name not in PUBLIC_TOOLS:
            return _err(rid, -32602, f"unknown tool: {name}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _err(rid, -32602, "arguments must be an object")
        started = time.monotonic()
        try:
            out = PUBLIC_TOOLS[name][0](**args)
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
            out = add_english(name, out)
        result = {
            "content": [{"type": "text",
                         "text": json.dumps(out, ensure_ascii=False, default=str)}],
            "isError": failed,
        }
        # The text block stays for older clients, which is what the spec asks
        # for; structuredContent is the same object as data rather than as a
        # string a client has to parse back out of a message.
        if not failed and isinstance(out, dict):
            result["structuredContent"] = json.loads(
                json.dumps(out, ensure_ascii=False, default=str))
        return _ok(rid, result)

    if rid is None:
        return None
    return _err(rid, -32601, f"method not found: {method}")


@router.post("/mcp", include_in_schema=False)
async def mcp_endpoint(request: Request) -> Response:
    raw = await request.body()
    try:
        payload = json.loads(raw or b"")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(_err(None, -32700, "parse error"), status_code=400)

    batch = isinstance(payload, list)
    msgs = payload if batch else [payload]
    if not msgs:
        return JSONResponse(_err(None, -32600, "empty batch"), status_code=400)

    from serve.ratelimit import client_ip
    ip = client_ip(request)

    loop = asyncio.get_running_loop()
    replies = [r for r in await asyncio.gather(
        *(loop.run_in_executor(_POOL, _handle, m, ip) for m in msgs)) if r is not None]

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
