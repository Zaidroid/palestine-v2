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
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from serve.mcp_server import API, TOOLS

# Tools that describe the machine rather than the country. See the module note.
PRIVATE = {"system_health", "ops_digest"}
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


def _tool_list() -> list[dict]:
    return [{"name": n, "description": d, "inputSchema": s}
            for n, (_, d, s) in PUBLIC_TOOLS.items()]


def _handle(msg: dict) -> dict | None:
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
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "palestine-live-tracker", "version": "2.0.0"},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(rid, {"tools": _tool_list()})
    # Declared in no capability, but clients probe for them anyway. An empty
    # list is a true answer; an error here shows up as a red server in the UI.
    if method in ("resources/list", "resources/templates/list"):
        return _ok(rid, {"resources": [], "resourceTemplates": []})
    if method == "prompts/list":
        return _ok(rid, {"prompts": []})

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
        return _ok(rid, {
            "content": [{"type": "text",
                         "text": json.dumps(out, ensure_ascii=False, default=str)}],
            "isError": failed,
        })

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

    loop = asyncio.get_running_loop()
    replies = [r for r in await asyncio.gather(
        *(loop.run_in_executor(_POOL, _handle, m) for m in msgs)) if r is not None]

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
