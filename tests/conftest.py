"""Make bare `pytest tests/` work.

test_arabic.py and test_ingest.py are standalone scripts ending in
`raise SystemExit(main())`, which fires at collection and kills the whole
run with `INTERNALERROR> SystemExit: 0`. HANDOFF.md's answer was a warning
paragraph and an 11-file explicit list that has already drifted twice —
first silently missing two new test files, then missing test_fuel_image.py.
A list a human must remember to update is not a fix; a collector that
cannot pick up the scripts is.
"""
collect_ignore = ["test_arabic.py", "test_ingest.py", "eval_geo.py"]

import pytest                                                        # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _isolate_the_usage_ledger(tmp_path_factory):
    """Tests must not write into PRODUCTION telemetry.

    `serve/mcp_usage.LEDGER` is `ops/mcp-usage.ndjson`, the record of what real
    callers actually ask. Every test that calls a tool through the HTTP transport
    goes through `_handle`, which calls `usage.record`, which appends to that
    same file — so a test run lands in the same ledger as a partner's traffic.

    Measured 2026-09-24: 329 of 817 entries were crafted abuse cases from
    tests/test_mcp_http.py (`../../health`, `a/b`, `PRISONERS`, `limit=999999`).
    That is 40% of the file, and it made the tool-usage summary unreadable in the
    worst possible way: `databank` showed 162 calls with 140 "unmet" and 86% of
    them were the guard tests, so the number that should describe what real
    people struggle with described what we deliberately break. Telemetry
    contaminated by its own test suite cannot answer "is this solid before I hand
    it over" — which is the only question this ledger exists for.

    Session-scoped and redirected rather than deleted: a run still exercises the
    recording path, it just writes it somewhere disposable.
    """
    from serve import mcp_usage
    real = mcp_usage.LEDGER
    mcp_usage.LEDGER = tmp_path_factory.mktemp("usage") / "mcp-usage.ndjson"
    yield
    mcp_usage.LEDGER = real


@pytest.fixture(autouse=True)
def _clear_rate_limit_buckets():
    """TestClient is not a localhost caller, so its requests count against the
    per-address limiter like a real client's. Running several test files back to
    back then fails on `429` instead of on the behaviour under test — measured
    2026-09-23, when a four-file run tripped the write class and a single-file
    run of the same test passed. Cleared per test; the limiter has its own tests
    that build the state they need.
    """
    from serve import ratelimit
    for book in ratelimit._buckets.values():       # keep the class keys: the
        book.clear()                               # middleware indexes them
    yield
    for book in ratelimit._buckets.values():
        book.clear()


# ── the two helpers every transport-level test uses (promoted here, P0-A.2) ──
@pytest.fixture(scope="session")
def mcp_call():
    """(name, tier='partner', **args) -> the JSON-RPC reply through the HTTP
    dispatcher — the only path that attaches answer_en and the licence block."""
    from serve import mcp_http as m

    def call(tool_name, tier="partner", **args):
        return m._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool_name, "arguments": args}}, None, tier)
    return call


@pytest.fixture(scope="session")
def mcp_payload():
    import json as _json

    def payload(reply):
        return _json.loads(reply["result"]["content"][0]["text"])
    return payload
