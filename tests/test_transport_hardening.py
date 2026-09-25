"""Transport hardening (audit 2026-09-25, plan 05-transport).

What a stranger with the published key could do before: send one POST carrying
any number of JSON-RPC calls (one limiter hit, one quota unit), keep using OAuth
tokens after their partner key was revoked, refresh forever, skip PKCE; and a
slow SSE subscriber was silently cut off while its connection stayed open.
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest
from fastapi.testclient import TestClient

from serve import mcp_http, mcp_oauth as oauth
from serve.app import app

client = TestClient(app)
IP = {"cf-connecting-ip": "198.51.100.77"}
KEY = "pv2_hardening_key"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "STATE_PATH", tmp_path / "oauth-state.json")
    monkeypatch.setattr(oauth, "_STATE", {"clients": {}, "tokens": {}, "refreshes": {}})
    monkeypatch.setattr(oauth, "_CODES", {})
    record = {"key": KEY, "name": "hardening", "daily_quota": 3}
    keys = {KEY: record}
    monkeypatch.setattr(mcp_http, "_partner_keys", lambda: keys)
    monkeypatch.setitem(mcp_http._KEY_STATE, "counts", {})
    yield keys


def _call(i, name="no_such_tool"):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": name, "arguments": {}}}


def test_t_01_a_batch_is_capped(_isolated):
    """F078/F088 — one POST carried an unbounded batch."""
    r = client.post("/mcp", headers={"x-api-key": KEY, **IP},
                    json=[{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(9)])
    assert r.status_code == 400 and r.json()["error"]["code"] == -32600


def test_t_02_the_body_is_capped(_isolated):
    big = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"pad": "x" * 300_000}}
    r = client.post("/mcp", headers={"x-api-key": KEY, **IP}, json=big)
    assert r.status_code == 413


def test_t_03_each_call_in_a_batch_counts_against_the_quota(_isolated):
    """quota 3; a batch of 4 tools/call used to cost one unit."""
    r = client.post("/mcp", headers={"x-api-key": KEY, **IP}, json=[_call(i) for i in range(4)])
    assert r.status_code == 429


def _token(who="hardening"):
    return oauth._issue("cid-1", who)


def test_t_04_revoking_the_key_revokes_its_tokens(_isolated):
    """F087/F357 — a revoked partner key kept its OAuth tokens for 30 days."""
    tok = _token()["access_token"]
    ok = client.post("/mcp", headers={"authorization": f"Bearer {tok}", **IP},
                     json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert ok.status_code == 200, ok.text
    _isolated.clear()                                   # the key is removed from the file
    gone = client.post("/mcp", headers={"authorization": f"Bearer {tok}", **IP},
                       json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert gone.status_code == 401


def test_t_05_a_token_is_held_to_its_keys_quota(_isolated):
    tok = _token()["access_token"]
    r = client.post("/mcp", headers={"authorization": f"Bearer {tok}", **IP},
                    json=[_call(i) for i in range(4)])
    assert r.status_code == 429


def test_t_06_refresh_tokens_are_single_use_bound_and_die_with_the_key(_isolated):
    first = _token()
    r = client.post("/token", data={"grant_type": "refresh_token",
                                    "refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    replay = client.post("/token", data={"grant_type": "refresh_token",
                                         "refresh_token": first["refresh_token"]})
    assert replay.status_code == 400                    # rotated: the used one is gone
    second = r.json()
    other = client.post("/token", data={"grant_type": "refresh_token", "client_id": "cid-OTHER",
                                        "refresh_token": second["refresh_token"]})
    assert other.status_code == 400                     # bound to its client
    _isolated.clear()
    dead = client.post("/token", data={"grant_type": "refresh_token",
                                       "refresh_token": second["refresh_token"]})
    assert dead.status_code == 400                      # the key is gone


def test_t_07_refresh_tokens_live_ninety_days_not_thirty(_isolated):
    t = _token()
    for store in ("tokens", "refreshes"):
        for rec in oauth._STATE[store].values():
            rec["issued"] = time.time() - 45 * 24 * 3600
    oauth._prune()
    assert t["refresh_token"] in oauth._STATE["refreshes"]
    assert t["access_token"] not in oauth._STATE["tokens"]


def test_t_08_pkce_is_required():
    """F359 — with no code_challenge the flow issued tokens without PKCE."""
    r = client.get("/authorize", params={"client_id": "c", "redirect_uri": "https://x/cb",
                                         "response_type": "code", "state": "s"})
    assert r.status_code == 400
    assert oauth._pkce_ok("", "") is False


def test_t_09_the_state_file_is_private(_isolated):
    """F396 — every token issue rewrote .keys/oauth-state.json as 0644."""
    _token()
    assert os.stat(oauth.STATE_PATH).st_mode & 0o777 == 0o600


def test_t_10_a_dropped_sse_subscriber_is_disconnected(monkeypatch):
    """F402 — a slow subscriber was removed from the broadcaster but its stream
    stayed open on keepalives, so it believed it was live and received nothing."""
    from serve import stream

    async def run():
        b = stream.Broadcaster()
        monkeypatch.setattr(stream, "broadcaster", b)
        gen = stream.event_source(snapshot=False)
        await gen.__anext__()                           # hello
        for i in range(stream.MAX_QUEUE + 2):           # overflow its queue
            b._publish({"type": "state_change", "n": i})
        out = []
        async for chunk in gen:
            out.append(chunk)
            if len(out) > stream.MAX_QUEUE + 5:
                break
        return out

    out = asyncio.run(asyncio.wait_for(run(), timeout=5))
    assert out and "reset" in out[-1]
