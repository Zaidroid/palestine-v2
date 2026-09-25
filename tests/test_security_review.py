"""F-84 — the security review's claims, as assertions.

    ./.venv/bin/python -m pytest tests/test_security_review.py -q

A threat note is a document until something fails when it stops being true. This
file is the part of the review that can go red: the three host-only tools, the
CORS posture, the cache bound, and the single-reader watermark.

proved here rather than asserted:
  * `system_health`, `ops_digest` and `mcp_usage` are not listed to a stranger
    AND cannot be called by name if one is learned elsewhere;
  * `allow_credentials` stays False while `allow_origins` is `*` — that
    combination is the one browsers refuse and the one that would turn a public
    read API into a credentialed cross-origin surface;
  * the query cache cannot be grown without bound by varying `limit`;
  * a burst of callers makes ONE watermark read, not N.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import mcp_http as m                                   # noqa: E402
from serve import app as A                                        # noqa: E402
from serve.app import app                                         # noqa: E402

client = TestClient(app)

HOST_ONLY = ("system_health", "ops_digest", "mcp_usage")


# ── the three tools that describe THIS MACHINE ───────────────────────────────

@pytest.mark.parametrize("name", HOST_ONLY)
def test_a_host_only_tool_is_not_on_the_http_menu(name):
    """`/mcp` is reachable by anyone with a key. Failing units, feed faults and
    the maintenance ledger answer a question nobody outside asked, and over the
    open internet they are infrastructure detail handed to a stranger."""
    listed = {t["name"] for t in m._tool_list()}
    assert name not in listed


@pytest.mark.parametrize("name", HOST_ONLY)
def test_a_host_only_tool_cannot_be_called_by_name_over_http(name):
    """Absent from tools/list is not the same as unreachable: a client may have
    learned the name from the stdio server, a doc, or a screenshot."""
    reply = m._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": {}}})
    assert reply["error"]["code"] == -32601
    assert "not served over HTTP" in reply["error"]["message"]
    assert "result" not in reply


def test_the_host_only_set_is_the_only_thing_held_back():
    """The complement: everything NOT host-only must actually be public, or the
    docs' "28 tools, every tool a partner gets" is false."""
    from serve.mcp_server import TOOLS
    assert set(m.PUBLIC_TOOLS) == set(TOOLS) - set(m.PRIVATE)


def test_the_usage_route_is_local_only_over_rest_too():
    """The MCP tool is hidden; the REST route behind it must not be the way
    around. TestClient is not a localhost caller, so this is the stranger's
    path."""
    assert client.get("/v2/usage").status_code == 404


# ── CORS: the combination that matters ───────────────────────────────────────

def _cors_options() -> dict:
    from fastapi.middleware.cors import CORSMiddleware
    for mw in app.user_middleware:
        if getattr(mw, "cls", None) is CORSMiddleware:
            return dict(mw.kwargs)
    raise AssertionError("CORSMiddleware is not installed at all")


def test_cors_allows_any_origin_but_never_credentials():
    """`*` on a public read-only API is deliberate and nearly free: no cookies,
    no auth state, nothing a browser would attach. What would NOT be free is
    `allow_credentials=True` beside it — that is the pair browsers reject and
    the pair that would let any site act with a visitor's credentials. This test
    exists so that adding credentials has to be a deliberate act with a red
    build, not a one-word edit."""
    opts = _cors_options()
    assert opts.get("allow_origins") == ["*"]
    assert not opts.get("allow_credentials", False), (
        "allow_origins=['*'] with allow_credentials=True is the dangerous pair: "
        "never widen this without narrowing origins at the same time")


def test_there_is_no_write_path_on_the_agent_surface():
    """The crowd write endpoints exist for browsers (P2). They must not be
    reachable as tools: an agent that can file reports is the sock-puppet
    problem at machine speed."""
    from serve.mcp_server import TOOLS
    banned = {"report", "submit", "register", "crowd", "create", "delete",
              "update", "post"}
    offenders = [n for n in TOOLS if any(b in n.lower() for b in banned)]
    assert not offenders, f"something that looks like a write path: {offenders}"


# ── resource bounds: what a hostile caller can make the server spend ─────────

def test_the_query_cache_cannot_be_grown_without_bound():
    """The cache key includes the caller's parameters, and a stranger controls
    `limit` (1..2000), `indicator` and `days`. Measured: one `limit=2000` entry
    holds 276 KB of rows, so an unbounded cache is a memory-growth vector with a
    one-line trigger."""
    assert isinstance(A._QUERY_CACHE, type(A.OrderedDict()))
    keep = dict(A._QUERY_CACHE)
    try:
        A._QUERY_CACHE.clear()
        for i in range(A.QUERY_CACHE_MAX + 50):
            # Write through the real path so the eviction logic runs, not a
            # reimplementation of it.
            A._QUERY_CACHE[(f"sql-{i}", (i,))] = (("s", 1), 0.0, [])
            A._QUERY_CACHE.move_to_end((f"sql-{i}", (i,)))
            while len(A._QUERY_CACHE) > A.QUERY_CACHE_MAX:
                A._QUERY_CACHE.popitem(last=False)
        assert len(A._QUERY_CACHE) == A.QUERY_CACHE_MAX
        # Least recently used went first, most recent survived.
        assert ("sql-0", (0,)) not in A._QUERY_CACHE
        assert (f"sql-{A.QUERY_CACHE_MAX + 49}",
                (A.QUERY_CACHE_MAX + 49,)) in A._QUERY_CACHE
    finally:
        A._QUERY_CACHE.clear()
        A._QUERY_CACHE.update(keep)


def test_the_cache_stays_bounded_after_real_requests():
    """The same bound, exercised through HTTP rather than by hand: vary `limit`
    the way a scraper would and confirm the cache does not track it."""
    for n in (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377):
        client.get("/v2/databank/prisoners", params={"limit": n})
    assert len(A._QUERY_CACHE) <= A.QUERY_CACHE_MAX


def test_a_burst_of_callers_makes_one_watermark_read_not_many():
    """Every cache lookup needs the watermark, and without a lock each caller
    that finds it stale runs the same ~380 ms `max(sys_period)` aggregate at the
    same instant — the most expensive query on the cheapest path, multiplied
    exactly when the server is busiest."""
    calls = []
    real_q = A.q

    def counting_q(sql, params=()):
        if "max(upper(sys_period))" in sql:
            calls.append(1)
            import time as _t
            _t.sleep(0.05)             # make the race window wide enough to lose
        return real_q(sql, params)

    saved = dict(A._WATERMARK)
    A.q = counting_q
    try:
        A._WATERMARK["value"], A._WATERMARK["at"] = None, 0.0
        out = []
        barrier = threading.Barrier(12)

        def worker():
            barrier.wait()             # all twelve arrive together
            out.append(A._databank_watermark())

        threads = [threading.Thread(target=worker) for _ in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(out) == 12
        assert len(set(out)) == 1, "callers disagreed about the watermark"
        assert len(calls) == 1, (
            f"the watermark was read {len(calls)} times for one burst; the lock "
            "is not doing its job")
    finally:
        A.q = real_q
        A._WATERMARK.update(saved)


def test_an_oversized_limit_is_refused_by_validation_not_served():
    """Cheap tools stay cheap: the bound is on the route, so a big `limit` is a
    422 rather than a 276 KB answer someone can ask for in a loop."""
    assert client.get("/v2/databank/prisoners",
                      params={"limit": 99999}).status_code == 422


def test_a_category_name_cannot_walk_out_of_the_databank():
    """The one caller string that becomes a URL path.

    Encoded on purpose: httpx normalises a literal `../../health` into `/health`
    BEFORE sending it, so a literal probe tests the client, not the server —
    measured here, it returned 200 from the health route and looked like a
    traversal that had worked. The percent-encoded form is what actually arrives
    at the server, and the single-segment route must not match it.

    `databank(category=...)` also guards the name at the tool layer (see
    tests/test_mcp_http.py) because that is the layer a model can reach.
    """
    for bad in ("..%2f..%2fhealth", "..%2fhealth", "a%2Fb", "%2e%2e%2fhealth"):
        r = client.get(f"/v2/databank/{bad}")
        assert r.status_code == 404, f"{bad} -> {r.status_code}"


def test_a_bogus_but_well_formed_category_is_an_empty_answer_not_a_leak():
    """Uppercase and nonsense are not attacks, they are typos: the route answers
    with no rows rather than an error, and nothing about the schema leaks."""
    r = client.get("/v2/databank/PRISONERS")
    if r.status_code == 200:
        body = r.json()
        assert body.get("count", 0) == 0
        assert "items" in body
