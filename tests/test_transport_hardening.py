"""The transport's own limits, as assertions — what one caller can make it do.

    ./.venv/bin/python -m pytest tests/test_transport_hardening.py -q

Every test here was written against a defect the 2026-09-25 audit found and
reproduced, and failed on the code as it stood before the fix beside it:

  * a JSON-RPC batch was charged as ONE request by the limiter and ONE unit of
    the daily quota, whatever it carried, and neither the batch nor the body
    had a size — one POST could queue thousands of tool calls;
  * an OAuth token never looked at the key it was minted from again: a revoked
    key's token worked for 30 days, was never metered, and its refresh token
    renewed it forever and could be replayed;
  * PKCE was optional, the consent page never said where the code would go, and
    the token file was rewritten world-readable on every issue;
  * a stream subscriber dropped for being slow kept its connection and heard
    keepalives forever, believing it was live; the reconnect snapshot could not
    tell it that something it held had decayed; and a dead poller was silence;
  * a databank reply told a partner `filtered` when nothing had been filtered,
    and an ungraded source read as `open`.

Nothing here needs the database or a running API: the key file, the token file
and the usage ledger are redirected to a temporary directory, and every tool the
transport would call is either unknown (refused before it runs) or a stub.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import licence as L                                    # noqa: E402
from serve import mcp_http as m                                   # noqa: E402
from serve import mcp_oauth as oauth                              # noqa: E402
from serve import mcp_usage as u                                  # noqa: E402
from serve import ratelimit as rl                                 # noqa: E402
from serve import stream as S                                     # noqa: E402
from serve.app import app                                         # noqa: E402

client = TestClient(app)
lenient = TestClient(app, raise_server_exceptions=False)

STRANGER = {"cf-connecting-ip": "198.51.100.23"}
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"   # RFC 7636 appendix B
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

QUOTA_KEY = {"key": "pv2_quota_key", "name": "quota-test", "daily_quota": 3}
OPEN_KEY = {"key": "pv2_open_key", "name": "open-test", "daily_quota": 0}
_bump = itertools.count(1)


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """A real key file and a real token file, both in a temporary directory.

    Returns a writer: call it with key records to replace the file's contents,
    which is exactly what revoking or issuing a key is on the host.
    """
    path = tmp_path / "partner-keys.json"
    monkeypatch.setattr(m, "KEYS_PATH", path)
    monkeypatch.setitem(m._KEY_STATE, "mtime", 0.0)
    monkeypatch.setitem(m._KEY_STATE, "keys", {})
    monkeypatch.setitem(m._KEY_STATE, "counts", {})
    monkeypatch.setattr(oauth, "STATE_PATH", tmp_path / "oauth-state.json")
    monkeypatch.setattr(oauth, "_STATE", {"clients": {}, "tokens": {}, "refreshes": {}})
    monkeypatch.setattr(oauth, "_CODES", {})

    def write(*records):
        path.write_text(json.dumps({"keys": list(records)}))
        # Two writes inside one clock tick would share an mtime, and the reader
        # re-reads on a CHANGED mtime — so each write moves it on explicitly.
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + next(_bump) * 1_000_000))

    write(QUOTA_KEY, OPEN_KEY)
    return write


def rpc(method, rid=1, **params):
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params:
        msg["params"] = params
    return msg


def unknown_tool_call(rid):
    """A tools/call that is refused before any tool runs — enough to exercise
    the door without an API behind it."""
    return rpc("tools/call", rid, name="no_such_tool", arguments={})


def post(body, key=None, headers=None, raw=None, c=client):
    h = dict(STRANGER)
    if key:
        h["authorization"] = f"Bearer {key}"
    h.update(headers or {})
    if raw is not None:
        return c.post("/mcp", content=raw, headers={**h, "content-type": "application/json"})
    return c.post("/mcp", json=body, headers=h)


# ── one POST is not one call ─────────────────────────────────────────────────

def test_a_batch_is_charged_per_tool_call_against_the_daily_quota(keys):
    """Measured before the fix: a key with daily_quota=1 answered 500 calls in
    one batch and its counter read 1. The published test key's '5,000 a day'
    meant 5,000 POSTs of any size."""
    r = post([unknown_tool_call(i) for i in range(5)], key=QUOTA_KEY["key"])
    assert r.status_code == 200, r.text
    codes = [x["error"]["code"] for x in r.json()]
    assert codes.count(-32002) == 2, codes             # quota 3: two refused
    assert codes.count(-32602) == 3, codes             # three reached the tool table


def test_the_handshake_is_not_charged_against_the_quota(keys):
    """A connector's initialize + tools/list is not a question answered; a
    quota spent on handshakes is a quota a partner cannot plan with."""
    for _ in range(QUOTA_KEY["daily_quota"] + 2):
        assert post(rpc("tools/list"), key=QUOTA_KEY["key"]).status_code == 200
    r = post(unknown_tool_call(1), key=QUOTA_KEY["key"])
    assert r.status_code == 200 and r.json()["error"]["code"] == -32602


def test_a_single_call_past_the_quota_is_still_a_429(keys):
    for i in range(QUOTA_KEY["daily_quota"]):
        assert post(unknown_tool_call(i), key=QUOTA_KEY["key"]).status_code == 200
    r = post(unknown_tool_call(99), key=QUOTA_KEY["key"])
    assert r.status_code == 429 and r.json()["error"]["code"] == -32002


def test_a_batch_is_charged_per_message_against_the_rate_limiter(keys):
    """The limiter saw one request per POST, so a batch multiplied the
    allowance by its length."""
    r = post([rpc("ping", i) for i in range(6)], key=OPEN_KEY["key"])
    assert r.status_code == 200
    hits = rl._buckets["mcp"].get(STRANGER["cf-connecting-ip"]) or []
    assert len(hits) == 6, f"a 6-message batch was charged {len(hits)} limiter hits"


def test_a_batch_that_crosses_the_limit_is_refused(keys, monkeypatch):
    monkeypatch.setitem(rl.LIMITS, "mcp", (5, 60))
    r = post([rpc("ping", i) for i in range(8)], key=OPEN_KEY["key"])
    assert r.status_code == 429, r.text
    assert int(r.headers["retry-after"]) > 0


def test_an_oversized_batch_is_refused_whole(keys):
    r = post([rpc("ping", i) for i in range(m.MAX_BATCH + 1)], key=OPEN_KEY["key"])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32600


def test_an_oversized_body_is_refused_before_it_is_parsed(keys):
    """Cloudflare lets 100 MB through; json.loads of that in the one process
    serving REST, SSE and MCP is the outage."""
    big = json.dumps(rpc("ping", 1, pad="x" * (300 * 1024)))
    r = post(None, key=OPEN_KEY["key"], raw=big)
    assert r.status_code == 413


# ── a malformed message is that message's error, not the whole POST's ────────

@pytest.mark.parametrize("bad", [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": [1]},
    {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": "x"},
    {"jsonrpc": "2.0", "id": 1, "method": 5},
    {"jsonrpc": "2.0", "id": 1, "method": "prompts/get",
     "params": {"name": "route_check", "arguments": [1]}},
])
def test_malformed_params_are_a_json_rpc_error_not_a_500(keys, bad):
    reply = m._handle(bad)
    assert reply["error"]["code"] in (-32600, -32602), reply


def test_one_bad_message_does_not_take_its_batch_down(keys):
    r = post([rpc("ping", 1),
              {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": [1]}],
             key=OPEN_KEY["key"], c=lenient)
    assert r.status_code == 200, r.text
    by_id = {x["id"]: x for x in r.json()}
    assert by_id[1]["result"] == {}
    assert by_id[2]["error"]["code"] == -32602


def test_an_unexpected_exception_is_one_messages_internal_error(keys, monkeypatch):
    def boom(msg, ip=None, tier="partner", structured=True):
        raise RuntimeError("/home/zaid/palestine-v2 exploded")
    monkeypatch.setattr(m, "_handle", boom)
    r = post(rpc("ping", 7), key=OPEN_KEY["key"], c=lenient)
    assert r.status_code == 200
    err = r.json()["error"]
    assert err["code"] == -32603 and "/home/zaid" not in err["message"]


# ── an OAuth token is only as good as the key behind it ─────────────────────

def _register(uris=(REDIRECT,)):
    r = client.post("/register", json={"client_name": "Claude", "redirect_uris": list(uris)})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _tokens(key=QUOTA_KEY["key"]):
    cid = _register()
    r = client.post("/authorize", data={
        "client_id": cid, "redirect_uri": REDIRECT, "state": "s",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "response_type": "code", "key": key}, follow_redirects=False)
    assert r.status_code == 302, r.text
    code = r.headers["location"].split("code=", 1)[1].split("&", 1)[0]
    t = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                    "client_id": cid, "redirect_uri": REDIRECT,
                                    "code_verifier": VERIFIER})
    assert t.status_code == 200, t.text
    return cid, t.json()


def test_a_token_dies_with_its_key(keys):
    """Revocation is a file edit — for header keys it always was. A token minted
    from a removed key kept working for 30 days and refreshed forever."""
    cid, tok = _tokens()
    assert post(rpc("tools/list"), key=tok["access_token"]).status_code == 200
    keys(OPEN_KEY)                                     # QUOTA_KEY revoked
    assert post(rpc("tools/list"), key=tok["access_token"]).status_code == 401
    r = client.post("/token", data={"grant_type": "refresh_token", "client_id": cid,
                                    "refresh_token": tok["refresh_token"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_a_token_is_metered_against_its_keys_quota(keys):
    """Anyone who ran the consent flow once with the published key held an
    unmetered token."""
    _, tok = _tokens()
    for i in range(QUOTA_KEY["daily_quota"]):
        assert post(unknown_tool_call(i), key=tok["access_token"]).status_code == 200
    r = post(unknown_tool_call(99), key=tok["access_token"])
    assert r.status_code == 429


def test_a_refresh_token_is_single_use(keys):
    cid, tok = _tokens()
    first = client.post("/token", data={"grant_type": "refresh_token", "client_id": cid,
                                        "refresh_token": tok["refresh_token"]})
    assert first.status_code == 200
    assert first.json()["refresh_token"] != tok["refresh_token"]
    again = client.post("/token", data={"grant_type": "refresh_token", "client_id": cid,
                                        "refresh_token": tok["refresh_token"]})
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


def test_a_refresh_token_is_bound_to_its_client(keys):
    _, tok = _tokens()
    r = client.post("/token", data={"grant_type": "refresh_token",
                                    "client_id": "pv2c_someoneelse",
                                    "refresh_token": tok["refresh_token"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_refresh_tokens_live_ninety_days_as_documented(keys, monkeypatch):
    """docs/PARTNER-API.md: 'Tokens last 30 days, refresh tokens 90'. The prune
    used the 30-day figure for both."""
    now = time.time()
    day = 24 * 3600
    oauth._STATE["refreshes"].update({
        "pv2r_40d": {"client_id": "c", "who": "x", "issued": now - 40 * day},
        "pv2r_91d": {"client_id": "c", "who": "x", "issued": now - 91 * day}})
    oauth._prune()
    assert "pv2r_40d" in oauth._STATE["refreshes"]
    assert "pv2r_91d" not in oauth._STATE["refreshes"]


def test_expired_authorization_codes_are_pruned(keys):
    oauth._CODES["old"] = {"client_id": "c", "at": time.time() - oauth.CODE_TTL - 5}
    oauth._CODES["new"] = {"client_id": "c", "at": time.time()}
    oauth._prune()
    assert "old" not in oauth._CODES and "new" in oauth._CODES


# ── PKCE, and a consent page that says where the code goes ───────────────────

def test_authorize_without_a_pkce_challenge_is_refused(keys):
    cid = _register()
    base = {"client_id": cid, "redirect_uri": REDIRECT, "state": "s",
            "response_type": "code"}
    assert client.get("/authorize", params=base).status_code == 400
    assert client.get("/authorize", params={**base, "code_challenge": CHALLENGE,
                                            "code_challenge_method": "plain"}).status_code == 400
    r = client.post("/authorize", data={**base, "key": QUOTA_KEY["key"]},
                    follow_redirects=False)
    assert r.status_code == 400, r.status_code
    assert oauth._pkce_ok("", "") is False


def test_the_consent_page_names_where_the_code_will_be_sent(keys):
    """A registrant can call itself 'Claude'. The host it redirects to is the
    one thing on the page it cannot fake."""
    cid = _register(uris=("https://evil.example/cb",))
    page = client.get("/authorize", params={
        "client_id": cid, "redirect_uri": "https://evil.example/cb", "state": "s",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "response_type": "code"}).text
    visible = page.split("<form", 1)[0]
    assert "evil.example" in visible


@pytest.mark.parametrize("uri", ["javascript:alert(1)", "http://attacker.example/cb",
                                 "https://claude.ai/cb#frag", "data:text/html,x"])
def test_a_redirect_uri_must_be_a_real_callback(keys, uri):
    r = client.post("/register", json={"client_name": "x", "redirect_uris": [uri]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"


@pytest.mark.parametrize("uri", [REDIRECT, "http://127.0.0.1:33418/callback",
                                 "http://localhost:6274/oauth/callback"])
def test_the_callbacks_real_clients_use_still_register(keys, uri):
    assert client.post("/register", json={"client_name": "x",
                                          "redirect_uris": [uri]}).status_code == 201


def test_open_registration_cannot_grow_the_token_file_without_bound(keys, monkeypatch):
    monkeypatch.setattr(oauth, "MAX_CLIENTS", 5)
    cid, _ = _tokens()                                 # this one holds a live token
    for _ in range(12):
        _register()
    clients = oauth._STATE["clients"]
    assert len(clients) <= 5
    assert cid in clients, "a client with a live token was evicted"


def test_the_token_file_is_written_owner_only(keys):
    """`chmod 600 .keys/*` was undone by the next /token call: the temporary file
    took the umask and was renamed over the target."""
    _tokens()
    assert stat.S_IMODE(oauth.STATE_PATH.stat().st_mode) == 0o600
    os.chmod(oauth.STATE_PATH, 0o644)
    _tokens()
    assert stat.S_IMODE(oauth.STATE_PATH.stat().st_mode) == 0o600
    leftovers = [p for p in oauth.STATE_PATH.parent.iterdir() if p.suffix == ".tmp"]
    assert not leftovers


def test_the_key_file_path_is_not_tied_to_one_home_directory():
    want = Path(os.environ.get("PARTNER_KEYS_PATH")
                or ROOT / ".keys" / "partner-keys.json")
    assert m.KEYS_PATH == want


def test_a_broken_key_file_keeps_the_old_keys_and_says_so(keys, caplog):
    """Fail-open is deliberate (a typo must not revoke every partner), but a
    revocation that did not take must not be silent either."""
    assert QUOTA_KEY["key"] in m._partner_keys()
    m.KEYS_PATH.write_text('{"keys": [}')
    st = m.KEYS_PATH.stat()
    os.utime(m.KEYS_PATH, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    with caplog.at_level("ERROR"):
        assert QUOTA_KEY["key"] in m._partner_keys()
    assert any("partner-keys" in r.getMessage() for r in caplog.records)
    assert m._KEY_STATE.get("error")


# ── the payload a tool call puts on the wire ─────────────────────────────────

def _stub_tool(monkeypatch, name, payload):
    fn, desc, schema = m.PUBLIC_TOOLS[name]
    monkeypatch.setitem(m.PUBLIC_TOOLS, name, (lambda **kw: json.loads(json.dumps(payload)),
                                               desc, schema))
    monkeypatch.setattr(m, "_tool_grades", lambda: {})


def test_an_oversized_databank_reply_is_cut_and_says_so(monkeypatch):
    """databank(limit=2000) was ~276 KB, carried twice (text and structured),
    and nothing between the tool and the wire bounded it."""
    rows = [{"indicator": "prices.x", "occurred_at": "2024-01-01", "value_num": i,
             "unit": "ILS", "attrs": {"note": "n" * 60}} for i in range(3000)]
    _stub_tool(monkeypatch, "databank", {"answer": "٣٠٠٠ سجل", "count": 3000, "items": rows})
    reply = m._handle(rpc("tools/call", name="databank", arguments={"category": "prices"}))
    text = reply["result"]["content"][0]["text"]
    assert len(text.encode("utf-8")) <= 128 * 1024
    body = json.loads(text)
    cut = body["payload_cut"]["items"]
    assert cut["of"] == 3000 and cut["kept"] == len(body["items"]) < 3000
    # Named in the payload AND in the sentence read aloud: a list that is
    # quietly short reads as the whole answer.
    assert body["payload_cut"]["note"]
    assert body["answer"] != "٣٠٠٠ سجل"
    assert reply["result"]["structuredContent"] == body


def test_a_live_list_of_closures_is_never_cut_at_the_databank_budget(monkeypatch):
    """Shortening `closed_now` hides a closed checkpoint. The live tools get a
    runaway guard, not a trim."""
    closed = [{"place_id": i, "name": f"حاجز {i}", "name_en": f"cp {i}",
               "age_minutes": 5, "present": True, "lat": 31.9, "lon": 35.2}
              for i in range(1500)]
    _stub_tool(monkeypatch, "checkpoints_summary",
               {"answer": "وضع الحواجز", "totals": {"closed": 1500}, "closed_now": closed})
    reply = m._handle(rpc("tools/call", name="checkpoints", arguments={}))
    body = json.loads(reply["result"]["content"][0]["text"])
    assert len(body["closed_now"]) == 1500
    assert "payload_cut" not in body


def test_an_older_client_is_not_sent_the_payload_twice(keys, monkeypatch):
    """structuredContent is a 2025-06-18 field. A client that declared an older
    protocol cannot read it, and carrying it doubles every reply."""
    _stub_tool(monkeypatch, "fuel_prices", {"answer": "x", "items": [{"p": 1}]})
    old = post(rpc("tools/call", name="fuel_prices", arguments={}), key=OPEN_KEY["key"],
               headers={"mcp-protocol-version": "2025-03-26"}).json()["result"]
    new = post(rpc("tools/call", name="fuel_prices", arguments={}), key=OPEN_KEY["key"],
               headers={"mcp-protocol-version": "2025-06-18"}).json()["result"]
    assert "structuredContent" not in old
    assert new["structuredContent"]["answer"] == "x"


def test_a_stale_grade_table_is_served_while_it_refreshes_off_the_request_path(monkeypatch):
    """The refresh ran three whole-table scans synchronously inside the first
    tool call after every quiet minute — ahead of checkpoint_status."""
    import serve.mcp_server as s
    calls = []

    def slow_api(path, **kw):
        calls.append(path)
        time.sleep(0.5)
        return {"tools": [{"tool": "databank", "grade": "fresh"}]}
    monkeypatch.setattr(s, "api", slow_api)
    monkeypatch.setitem(m._GRADES, "tools", {"databank": {"tool": "databank", "grade": "stale"}})
    monkeypatch.setitem(m._GRADES, "at", time.monotonic() - m._GRADES_TTL - 1)
    monkeypatch.setitem(m._GRADES, "tried", float("-inf"))
    monkeypatch.setitem(m._GRADES, "busy", False)
    t0 = time.monotonic()
    got = m._tool_grades()
    assert time.monotonic() - t0 < 0.2, "the caller waited for the refresh"
    assert got["databank"]["grade"] == "stale"
    for _ in range(5):
        m._tool_grades()
    deadline = time.monotonic() + 3
    while m._GRADES["tools"]["databank"]["grade"] != "fresh" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert m._GRADES["tools"]["databank"]["grade"] == "fresh"
    assert len(calls) == 1, f"a burst made {len(calls)} refreshes"


# ── the licence block must state what was done, not what is policy ───────────

def _dbrow(i, grade):
    return {"indicator": f"x.{i}", "occurred_at": f"2024-01-0{i}", "value_num": i,
            "unit": None, "place_en": None, "place_ar": None, "attrs": {},
            "source_key": f"src{i}", "redistribution": grade}


ENTRY = {"grade": "no-redistribution", "partner_tier": "filtered"}


def test_a_databank_reply_without_per_row_grades_does_not_claim_a_filter():
    """The block said `partner_tier: filtered` over rows nobody filtered —
    exactly the 'quietly full' lie the licence module exists to stop."""
    out = L.apply("databank", {"answer": "x", "count": 1,
                               "items": [{"indicator": "a", "value_num": 1}]},
                  "partner", dict(ENTRY))
    lic = out["licence"]
    assert lic["partner_tier"] != "filtered"
    assert "no per-row" in lic["filter"] or "not filtered" in lic["filter"]
    assert len(out["items"]) == 1


def test_a_partner_databank_reply_withholds_rows_graded_outside_the_tier():
    """ZAID-10: ungraded and no-redistribution databank sets stay out of partner
    payloads, and the cut is named."""
    items = [_dbrow(1, "open"), _dbrow(2, "no-redistribution"), _dbrow(3, None),
             _dbrow(4, "ask"), _dbrow(5, "attribution")]
    out = L.apply("databank", {"answer": "x", "count": 5, "items": [dict(r) for r in items],
                               "latest_by_indicator": [dict(items[1])]},
                  "partner", dict(ENTRY))
    kept = {r["redistribution"] for r in out["items"]}
    assert kept <= set(L.PARTNER_ALLOWED) and len(out["items"]) == 2
    assert out["count"] == 2
    assert out["latest_by_indicator"] == []
    lic = out["licence"]
    assert lic["partner_tier"] == "filtered" and lic["filtered_rows"] == 3
    assert "3 of 5" in lic["refused"]
    # The grade is the payload's own, not the worst in the whole databank.
    assert lic["grade"] == "attribution"
    # The spoken answer was built from rows that were withheld; it must not
    # carry them past the cut.
    assert out["answer"] != "x"
    house = L.apply("databank", {"answer": "x", "items": [dict(r) for r in items]},
                    "house", dict(ENTRY))
    assert len(house["items"]) == 5


def test_a_headline_built_only_from_kept_rows_survives_the_cut():
    """The answer quotes the newest row per indicator. When none of those was
    withheld the headline is still true — only its row count is not — so it is
    kept and the cut is added to it rather than the figures thrown away."""
    items = [_dbrow(1, "open"), _dbrow(2, "no-redistribution")]
    out = L.apply("databank", {"answer": "آخر الأرقام: x.1: 1", "answer_en": "x.1: 1",
                               "count": 2, "items": [dict(r) for r in items],
                               "latest_by_indicator": [dict(items[0])]},
                  "partner", dict(ENTRY))
    assert out["answer"].startswith("آخر الأرقام: x.1: 1")
    assert "حجبنا 1 من 2" in out["answer"]
    assert "1 of 2 rows were withheld" in out["answer_en"]
    assert len(out["latest_by_indicator"]) == 1


def test_a_filtered_share_alike_payload_names_its_copyleft():
    """The obligation is attached from the grade; after a cut the grade is the
    payload's own, so the obligation must follow it."""
    items = [_dbrow(1, "share-alike"), _dbrow(2, "no-redistribution")]
    out = L.apply("databank", {"answer": "x", "items": [dict(r) for r in items]},
                  "partner", dict(ENTRY))
    assert out["licence"]["grade"] == "share-alike"
    assert "DERIVED DATABASE" in " ".join(out["licence"]["obligations"])


def test_an_ungraded_or_missing_source_is_not_open():
    """_worst() of nothing was `open`, so a NULL grade, a renamed source key or
    an empty databank group advertised `full` to partners."""
    def fake_q(sql, params=()):
        if "databank_internal" in sql:
            return []                                   # empty after a failed sync
        if "state_observation" in sql or "claim c" in sql:
            return [{"g": None}]
        if "located" in sql:
            return [{"g": "open"}]
        return [{"key": "open_meteo", "redistribution": None, "license_spdx": None,
                 "attribution_text": None, "verified_on": None}]
        # `ioda` is absent from the source table altogether
    g = L.grade_tools(fake_q)
    assert g["weather_now"]["grade"] == "ask"
    assert g["weather_now"]["partner_tier"] == "cited_fact_only"
    assert g["connectivity_now"]["grade"] == "ask"
    assert g["connectivity_now"]["unresolved_sources"] == ["ioda"]
    assert g["databank"]["grade"] == "ask"
    assert g["latest_news"]["grade"] == "ask"
    # Our own metadata still grades open, and a reduction is still ours.
    assert g["about"]["grade"] == "open"
    assert g["incidents_summary"]["grade"] == "open"


# ── the stream: a subscriber must be able to tell it is no longer live ───────

def _row(pid, value, last_known=None, age=5.0):
    return {"place_id": pid, "name_ar": f"مكان{pid}", "name_en": None,
            "place_kind": "checkpoint", "state_kind": "checkpoint_status",
            "direction": "both", "value": value,
            "last_known_value": last_known or value, "confidence": 0.8,
            "observed_at": None, "age_minutes": age, "staleness_band": "fresh",
            "independent_sources": 2}


def test_a_dropped_subscriber_is_disconnected_not_kept_on_keepalives(monkeypatch):
    """Before: the queue was removed from the set and the generator went on
    yielding keepalives for ever — a pulsing 'live' dot over states frozen at
    the moment of the drop, and no reconnect to fetch a fresh snapshot."""
    b = S.Broadcaster()
    monkeypatch.setattr(S, "broadcaster", b)
    monkeypatch.setattr(S, "KEEPALIVE_SECONDS", 0.01)

    async def go():
        gen = S.event_source(snapshot=False)
        frames = [await anext(gen)]                      # hello; now subscribed
        for i in range(S.MAX_QUEUE + 5):
            b._publish({"type": "state_change", "n": i, "state_kind": "x"})
        assert b.subscribers == 0
        try:
            for _ in range(S.MAX_QUEUE + 50):
                frames.append(await asyncio.wait_for(anext(gen), 1.0))
        except StopAsyncIteration:
            return frames, True
        return frames, False

    frames, ended = asyncio.run(go())
    assert ended, "the dropped subscriber's connection never ended"
    assert frames[-1].startswith("event: reset")
    assert not any(f.startswith(": keepalive") for f in frames)


def test_the_snapshot_names_what_is_no_longer_asserted(monkeypatch):
    """A phone that slept through a decay reconnects to a snapshot that lists
    only asserted rows; its cached 'open' survived with no server signal."""
    b = S.Broadcaster()
    b._fetch = lambda: [_row(1, "open"), _row(2, "unknown", last_known="open", age=400)]
    monkeypatch.setattr(S, "broadcaster", b)

    async def go():
        gen = S.event_source(snapshot=True)
        try:
            return [await anext(gen), await anext(gen)]
        finally:
            await gen.aclose()
    _, snap = asyncio.run(go())
    payload = json.loads(snap.split("data:", 1)[1])
    assert payload["asserted"] == len(payload["states"]) == 1
    assert payload["complete"] is True
    gone = {r["place_id"]: r for r in payload["unknown_states"]}
    assert gone[2]["value"] == "unknown" and gone[2]["last_known_value"] == "open"
    assert gone[2]["age_minutes"] == 400


def test_a_stalled_poller_is_announced_not_silent(monkeypatch):
    """A dead database and a quiet night looked identical to a subscriber."""
    b = S.Broadcaster()
    monkeypatch.setattr(S, "POLL_SECONDS", 0.001)
    monkeypatch.setattr(S, "_beat", lambda watched: None)
    state = {"fail": True}

    def fetch():
        if state["fail"]:
            raise RuntimeError("connection refused")
        return [_row(1, "open")]
    b._fetch = fetch

    async def go():
        q = b.subscribe()
        task = asyncio.create_task(b.run())
        seen = []
        try:
            ev = await asyncio.wait_for(q.get(), 2.0)
            seen.append(ev)
            state["fail"] = False
            seen.append(await asyncio.wait_for(q.get(), 2.0))
        finally:
            task.cancel()
        return seen
    seen = asyncio.run(go())
    assert seen[0]["type"] == "stalled" and seen[0]["failed_polls"] >= S.STALL_AFTER
    assert seen[1]["type"] == "resumed"


def test_a_stall_reaches_a_filtered_subscriber(monkeypatch):
    b = S.Broadcaster()
    monkeypatch.setattr(S, "broadcaster", b)

    async def go():
        gen = S.event_source(state_kind="checkpoint_status", place_id=7, snapshot=False)
        await anext(gen)
        b._publish({"type": "stalled", "since": "t", "failed_polls": 3})
        try:
            return await asyncio.wait_for(anext(gen), 1.0)
        finally:
            await gen.aclose()
    assert asyncio.run(go()).startswith("event: stalled")


# ── who the caller is, and how many of them there are ────────────────────────

def test_an_unknown_peer_is_not_local():
    """`unknown` is what a missing socket address looks like, not proof the
    caller is on this machine — and local means no key, no limit, house tier."""
    assert rl.is_local("unknown") is False
    assert rl.is_local("127.0.0.1") and rl.is_local("::1")


def test_one_ipv6_64_is_one_visitor():
    """Measured: 400 calls from 2001:db8:1:1::0…18f all passed a 300/min
    limit. One subscriber's /64 is 2^64 addresses."""
    limit, _ = rl.LIMITS["register"]
    for i in range(limit):
        assert rl.check(f"2001:db8:1:1::{i + 1:x}", "register")[0]
    assert not rl.check("2001:db8:1:1:ffff::9", "register")[0]
    assert rl.check("2001:db8:1:2::1", "register")[0], "the next /64 is somebody else"


# ── the usage ledger ─────────────────────────────────────────────────────────

def test_the_ledger_does_not_keep_a_callers_exact_position():
    """`checkpoints(lat, lon)` several times a day was a metre-precision track
    of one caller beside a per-day identity."""
    a = u._args({"lat": 31.90412345, "lon": 35.20398765, "place": "حوارة", "limit": 5})
    assert a["lat"] == 31.9 and a["lon"] == 35.2
    assert a["place"] == "حوارة" and a["limit"] == 5


def test_the_summary_reads_across_a_rotation(tmp_path, monkeypatch):
    ledger = tmp_path / "mcp-usage.ndjson"
    monkeypatch.setattr(u, "LEDGER", ledger)
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    line = lambda t: json.dumps({"ts": now, "tool": t, "args": {}, "ms": 1,  # noqa: E731
                                 "ok": True, "unmet": False, "who": "w"})
    ledger.with_suffix(".ndjson.1").write_text(line("databank") + "\n" + line("news") + "\n")
    ledger.write_text(line("checkpoints") + "\n")
    assert u.summary(7)["calls"] == 3


def test_never_used_is_counted_in_the_names_callers_use(tmp_path, monkeypatch):
    """The ledger records public names (`checkpoints`); the universe was the
    internal ones (`checkpoints_near`), so absorbed tools read as never used
    forever and the façades did not exist."""
    from serve.mcp_facades import LISTED
    ledger = tmp_path / "mcp-usage.ndjson"
    monkeypatch.setattr(u, "LEDGER", ledger)
    for t in ("checkpoints", "latest_news"):
        u.record(t, {}, 1, True, {"answer": "x"}, "203.0.113.1")
    never = set(u.summary(7)["tools_never_used"])
    assert never <= set(LISTED)
    assert "checkpoints" not in never and "news" not in never
    assert "checkpoints_near" not in never
