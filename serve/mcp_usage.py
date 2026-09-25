"""What people actually ask this system — and what it could not answer.

Every MCP call used to leave one indistinguishable line in the access log:
`POST /mcp 200`. Thirty-four of them tell you nothing. Which tool ran, whether
it found anything, whether it took nine seconds, whether the same person asked
the same unanswerable question four times — all of it was invisible, so the
question "what should this system hold next?" could only be answered by
guessing.

THE POINT IS NOT A HIT COUNTER
The valuable column is `unmet`: a call that completed successfully and still had
nothing to say. `crossings` returns "no source reports this" every single time,
and every one of those is a person who wanted an answer that does not exist yet.
Ranked by how often they are asked, unanswered questions are an acquisition
roadmap written by the people who need it — the demand side of the gap radar,
which until now only measured supply.

WHAT IS NOT WRITTEN DOWN
No IP addresses. The caller is a salted daily digest, which is enough to tell
one visitor from twenty and useless for identifying anybody, and the salt rolls
at midnight so it cannot become a long-term identifier. That is not squeamishness:
this records people asking which checkpoints are closed, and in this place, at
this time, a log of who wanted to know that is not a neutral artifact. Argument
VALUES are kept — "everyone asks about حوارة" is the whole signal — but truncated,
and only for the small, fixed set of arguments the tools declare.

A LEDGER, NOT A TABLE
NDJSON beside the other ops ledgers, for the reason they are: this must never be
able to fail a user's question. A full disk or a locked file loses a usage line;
it must not lose an answer about a road. Every write is wrapped, and the
recorder swallows its own failures by design.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LEDGER = Path(__file__).resolve().parent.parent / "ops" / "mcp-usage.ndjson"
MAX_BYTES = 32 * 1024 * 1024            # roll at 32MB; keep one previous file
ARG_CHARS = 60                          # a place name, not an essay

_lock = threading.Lock()
# Rotates daily. A stable hash across months would be a tracking identifier;
# this only has to separate "one person asked twelve times" from "twelve people
# asked once", which is a question about a single day.
_salt = os.environ.get("MCP_USAGE_SALT") or os.urandom(16).hex()


def caller(ip: str | None) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return hashlib.sha256(f"{_salt}{day}{ip or '?'}".encode()).hexdigest()[:12]


def _args(args: dict) -> dict:
    """Keep what makes the question legible, drop what makes it personal."""
    out = {}
    for k, v in list(args.items())[:8]:
        if isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)[:ARG_CHARS]
    return out


def unmet(out: Any) -> bool:
    """Did this call succeed and still leave the caller with nothing?

    Deliberately generous about what counts. A tool that answers "I have no
    source for that" is doing its job perfectly and has still failed the person
    asking, and it is that second sense we need to count — the first is already
    visible in `ok`.
    """
    if not isinstance(out, dict):
        return False
    if out.get("error") or out.get("refused"):
        return True
    # `no_source` is a FLAG on crossings ("nobody reports this") and a LIST on
    # coverage (the fields nobody reports). Only the flag is a disappointed
    # caller; coverage naming its own blind spots is the tool working, and
    # counting it as failure would put the one honest tool at the top of the
    # roadmap forever.
    if out.get("no_source") is True:
        return True
    if out.get("found") is False:
        return True
    if out.get("count") == 0:
        return True
    # A live reading that has decayed past the point of assertion.
    if out.get("flow") == "unknown" and not out.get("last_known_flow"):
        return True
    for key in ("stations", "checkpoints", "incidents", "items", "series",
                "indicators", "crossings"):
        if key in out and isinstance(out[key], list) and not out[key]:
            return True
    return False


def record(tool: str, args: dict, ms: int, ok: bool, out: Any,
           ip: str | None = None, exempt: bool = False) -> None:
    """Append one line. Never raises — see the module note.

    `exempt`: a LOCAL caller sent `X-Usage-Exempt: 1` (a test run, the nightly
    audit through HTTP) — P1-C.2. Only this machine may ask not to be counted."""
    if exempt or os.environ.get("MCP_USAGE_EXEMPT") == "1":      # the audit's own calls (F242)
        return
    try:
        line = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "args": _args(args or {}),
            "ms": ms,
            "ok": ok,
            "unmet": unmet(out),
            "who": caller(ip),
        }, ensure_ascii=False)
        with _lock:
            if LEDGER.exists() and LEDGER.stat().st_size > MAX_BYTES:
                LEDGER.replace(LEDGER.with_suffix(".ndjson.1"))
            with LEDGER.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:                                       # noqa: BLE001
        pass


def _read(days: int) -> list[dict]:
    if not LEDGER.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = []
    for raw in LEDGER.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            r = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if r.get("ts", "") >= cutoff:
            rows.append(r)
    return rows


_PROBE = ("../", "..\\", "/", "%2e%2e")


def is_probe(r: dict) -> bool:
    """A call whose arguments try paths rather than ask a question: 94 databank
    calls with category '../../health' or 'a/b' (P1-C.2, measured 2026-09-25,
    from several different callers). Kept in the ledger — they are real
    traffic — and counted apart, never as demand."""
    for k in ("category", "indicator", "section"):
        v = (r.get("args") or {}).get(k)
        if isinstance(v, str) and any(p in v.lower() for p in _PROBE):
            return True
    return False


def summary(days: int = 7) -> dict:
    """Aggregates, with the unanswerable questions ranked first."""
    rows = _read(days)
    probes = [r for r in rows if is_probe(r)]
    rows = [r for r in rows if not is_probe(r)]
    if not rows:
        return {"calls": 0, "days": days,
                "note": "no MCP calls recorded in this window"}

    by_tool: dict[str, dict] = {}
    for r in rows:
        t = by_tool.setdefault(r["tool"], {"calls": 0, "errors": 0, "unmet": 0,
                                           "ms_total": 0, "slowest_ms": 0})
        t["calls"] += 1
        t["errors"] += 0 if r.get("ok") else 1
        t["unmet"] += 1 if r.get("unmet") else 0
        t["ms_total"] += r.get("ms") or 0
        t["slowest_ms"] = max(t["slowest_ms"], r.get("ms") or 0)
    for t in by_tool.values():
        t["avg_ms"] = round(t["ms_total"] / t["calls"])
        t["unmet_rate"] = round(t["unmet"] / t["calls"], 2)
        del t["ms_total"]

    # The acquisition roadmap: asked often, answered rarely. Sorted by the
    # NUMBER of disappointed calls rather than the rate, because a tool asked
    # once and empty once is noise, and one asked forty times and empty forty
    # times is a decision.
    unmet_rank = sorted(
        ({"tool": k, "unmet_calls": v["unmet"], "of_calls": v["calls"],
          "rate": v["unmet_rate"]} for k, v in by_tool.items() if v["unmet"]),
        key=lambda x: (-x["unmet_calls"], -x["rate"]))

    subjects = Counter()
    for r in rows:
        for k in ("place", "origin", "destination", "name", "area", "category"):
            v = (r.get("args") or {}).get(k)
            if isinstance(v, str) and v.strip():
                subjects[v.strip()] += 1

    return {
        "days": days,
        "calls": len(rows),
        "probes_set_apart": len(probes),
        "callers": len({r.get("who") for r in rows}),
        "errors": sum(1 for r in rows if not r.get("ok")),
        "unmet_calls": sum(1 for r in rows if r.get("unmet")),
        "tools_used": len(by_tool),
        "tools_never_used": sorted(_all_tools() - set(by_tool)),
        "by_tool": dict(sorted(by_tool.items(), key=lambda kv: -kv[1]["calls"])),
        "unanswered_demand": unmet_rank[:10],
        "most_asked_about": [{"subject": s, "times": n}
                             for s, n in subjects.most_common(12)],
        "reading": ("`unmet` counts calls that SUCCEEDED and still had nothing "
                    "to say. Ranked high here means people keep asking a "
                    "question this system cannot answer yet — that is the "
                    "demand side of ops/radar, which only measures supply."),
    }


def _all_tools() -> set[str]:
    """The tools this ledger could possibly see — the ledger records the HTTP
    transport, so the host-only ones are not 'unused', they are unreachable."""
    from serve.mcp_server import HOST_ONLY, TOOLS
    return set(TOOLS) - HOST_ONLY
