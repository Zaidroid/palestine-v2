"""The OAuth surface a hosted MCP client needs — and the gate it must not become.

The failure these exist to prevent: a key-gated /mcp returns 401 to a client
that cannot send a header, the client walks the spec's discovery URLs, finds
404 at every one, and reports "Authentication failed". Every step of that walk
is asserted here, including the two that must NOT succeed — an unknown key and
a replayed code.
"""
import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from serve import mcp_http
from serve import mcp_oauth as oauth
from serve.app import app
from serve.mcp_http import _KEY_STATE

client = TestClient(app)
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"   # RFC 7636 appendix B
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
GOOD_KEY = "pv2_test_key"


@pytest.fixture(autouse=True)
def _clean_state(tmp_path, monkeypatch):
    """Never touch the real .keys/ files from a test.

    The key is written to a real (temporary) key file rather than declared valid
    by patching `_partner_key_ok`: since the 2026-09-25 audit (F090) every use
    of a token re-reads the key it was minted from, so a key that exists only
    in a patched function would — correctly — not keep its token alive.
    """
    keys = tmp_path / "partner-keys.json"
    keys.write_text(json.dumps({"keys": [{"key": GOOD_KEY, "name": "test",
                                          "daily_quota": 0}]}))
    monkeypatch.setattr(mcp_http, "KEYS_PATH", keys)
    monkeypatch.setattr(oauth, "STATE_PATH", tmp_path / "oauth-state.json")
    monkeypatch.setattr(oauth, "_STATE", {"clients": {}, "tokens": {}, "refreshes": {}})
    monkeypatch.setattr(oauth, "_CODES", {})
    monkeypatch.setitem(_KEY_STATE, "keys", {})
    monkeypatch.setitem(_KEY_STATE, "mtime", 0.0)
    yield


def _register() -> str:
    r = client.post("/register", json={"client_name": "Claude",
                                       "redirect_uris": [REDIRECT]})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _authorize(cid: str, key: str = GOOD_KEY):
    return client.post("/authorize", data={
        "client_id": cid, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "response_type": "code", "key": key}, follow_redirects=False)


def _code(cid: str) -> str:
    r = _authorize(cid)
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    assert loc.startswith(REDIRECT) and "state=xyz" in loc
    return loc.split("code=", 1)[1].split("&", 1)[0]


def test_the_client_can_find_the_authorization_server():
    for path in ("/.well-known/oauth-protected-resource",
                 "/.well-known/oauth-protected-resource/mcp"):
        d = client.get(path).json()
        assert d["resource"].endswith("/mcp")
        assert d["authorization_servers"]
    asd = client.get("/.well-known/oauth-authorization-server").json()
    assert asd["registration_endpoint"].endswith("/register")
    assert asd["code_challenge_methods_supported"] == ["S256"]
    assert "authorization_code" in asd["grant_types_supported"]


def test_registration_needs_a_redirect_uri_and_returns_a_client_id():
    assert client.post("/register", json={"client_name": "x"}).status_code == 400
    assert client.post("/register", json={"client_name": "x",
                                          "redirect_uris": [REDIRECT]}).status_code == 201


def test_the_consent_page_names_the_client_and_carries_the_flow_parameters():
    cid = _register()
    page = client.get("/authorize", params={
        "client_id": cid, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "response_type": "code"}).text
    assert "Claude" in page
    for field in ("client_id", "redirect_uri", "state", "code_challenge"):
        assert f'name="{field}"' in page
    assert 'name="key"' in page


def test_the_gate_is_still_a_gate():
    """Auto-approving would make this a public endpoint wearing a token."""
    cid = _register()
    assert _authorize(cid, key="pv2_wrong").status_code == 401
    assert _authorize(cid, key="").status_code == 401


def test_a_registered_client_gets_a_code_and_a_token():
    cid = _register()
    code = _code(cid)
    r = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                    "client_id": cid, "redirect_uri": REDIRECT,
                                    "code_verifier": VERIFIER})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer" and body["access_token"]
    listed = client.post("/mcp", headers={"authorization": f"Bearer {body['access_token']}",
                                          "cf-connecting-ip": "198.51.100.9"},
                         json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed.status_code == 200, listed.text
    from serve.mcp_facades import LISTED
    assert len(listed.json()["result"]["tools"]) == len(LISTED)


def test_pkce_is_verified_and_a_replayed_code_is_refused():
    cid = _register()
    code = _code(cid)
    bad = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                      "client_id": cid, "redirect_uri": REDIRECT,
                                      "code_verifier": "not-the-verifier"})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    # the failed exchange burned it: a code is single use, whatever happened to it
    again = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                        "client_id": cid, "redirect_uri": REDIRECT,
                                        "code_verifier": VERIFIER})
    assert again.status_code == 400


def test_a_code_is_not_exchanged_without_its_verifier():
    """PKCE is only a protection if the token endpoint insists on the verifier:
    a code seen in a redirect must be worthless on its own."""
    cid = _register()
    code = _code(cid)
    r = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                    "client_id": cid, "redirect_uri": REDIRECT})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_authorize_without_a_challenge_is_refused_before_a_key_is_asked_for():
    """PKCE was optional; a client that sent no challenge got a code anyone who
    saw the redirect could exchange (audit F359/F399)."""
    cid = _register()
    page = client.get("/authorize", params={"client_id": cid, "redirect_uri": REDIRECT,
                                            "state": "xyz", "response_type": "code"})
    assert page.status_code == 400 and 'name="key"' not in page.text


def test_an_unregistered_redirect_uri_is_refused():
    cid = _register()
    r = client.post("/authorize", data={
        "client_id": cid, "redirect_uri": "https://evil.example/cb", "state": "x",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "response_type": "code", "key": GOOD_KEY}, follow_redirects=False)
    assert r.status_code == 400


def test_an_unknown_bearer_token_is_refused():
    r = client.post("/mcp", headers={"authorization": "Bearer pv2t_nope",
                                     "cf-connecting-ip": "198.51.100.9"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    # RFC 9728 §5.1: the 401 tells the client where the metadata is, which is
    # the difference between a client completing the flow and guessing four URLs
    assert "oauth-protected-resource" in r.headers["www-authenticate"]


def test_a_refresh_token_issues_a_new_access_token():
    cid = _register()
    code = _code(cid)
    first = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                        "client_id": cid, "redirect_uri": REDIRECT,
                                        "code_verifier": VERIFIER}).json()
    r = client.post("/token", data={"grant_type": "refresh_token",
                                    "refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["access_token"] != first["access_token"]


def test_unsupported_grant_type_is_a_clean_error():
    r = client.post("/token", data={"grant_type": "client_credentials"})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
