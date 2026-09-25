"""OAuth 2.0 for the MCP endpoint — the door a hosted client can actually open.

WHY THIS EXISTS
On 2026-09-23 the endpoint went from open to key-gated and Claude's own connector
stopped dead with "Authentication failed". The access log shows exactly what it
did, and it is not a client being difficult — it is the MCP authorization spec
being followed:

    POST /mcp                                          401
    GET  /.well-known/oauth-protected-resource/mcp     404
    GET  /.well-known/oauth-protected-resource         404
    GET  /.well-known/oauth-authorization-server       404
    POST /register                                     404
    POST /mcp                                          401  -> give up

A hosted client cannot be handed a static header, so the spec gives it a
discovery-and-registration flow instead: RFC 9728 protected-resource metadata,
RFC 8414 authorization-server metadata, RFC 7591 dynamic client registration,
then authorization code + PKCE. Serving 404 to those four URLs IS the failure —
the client has nowhere to send a key.

THE GATE STAYS A GATE
Auto-approving the authorization request would make this a public endpoint again
wearing a token. So `/authorize` renders one page with one field: the partner
key, the same string the header path accepts. A key is required to get a code,
and the code is what becomes a token. Nothing is granted to an anonymous caller.

WHAT IS STORED, AND WHY IT IS A FILE
Registered clients and issued tokens live in `.keys/oauth-state.json` (outside
the repo, gitignored) so a deploy does not silently log every connector out
mid-release. Authorization codes live in memory only: they last five minutes and
a restart invalidating them costs nothing but a retry.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()

PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://live-api.zaidlab.xyz")
NAME = "Palestine Data — live + databank"          # one name (PLAN Z-4)
RESOURCE = f"{PUBLIC_BASE}/mcp"
STATE_PATH = Path(os.environ.get("OAUTH_STATE_PATH",
                                 "/home/zaid/palestine-v2/.keys/oauth-state.json"))

CODE_TTL = 300                 # five minutes: enough for a redirect, no more
TOKEN_TTL = 30 * 24 * 3600     # a release cycle
REFRESH_TTL = 90 * 24 * 3600
SCOPE = "read"

_CODES: dict[str, dict] = {}
_STATE: dict = {"clients": {}, "tokens": {}, "refreshes": {}}


def _load() -> None:
    try:
        _STATE.update(json.loads(STATE_PATH.read_text()))
    except Exception:                                            # noqa: BLE001
        pass                        # a missing or broken file is a cold start


def _save() -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        # 0600 from the first byte: the file holds live bearer tokens, and
        # write_text() created it with the umask's 0644 on every issue (F396).
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(_STATE, indent=1))
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)            # an older tmp file keeps its old mode
        tmp.replace(STATE_PATH)
    except Exception:                                            # noqa: BLE001
        pass                        # never let bookkeeping fail a live request


def _now() -> float:
    return time.time()


def _prune() -> None:
    # Each store by its own lifetime. Both used TOKEN_TTL before, so a refresh
    # token died with its access token and REFRESH_TTL was never read.
    t = _now()
    for store, ttl in ((_STATE["tokens"], TOKEN_TTL), (_STATE["refreshes"], REFRESH_TTL)):
        dead = [k for k, v in store.items() if t - v.get("issued", 0) > ttl]
        for k in dead:
            store.pop(k, None)


def _partner_key_ok(key: str) -> str | None:
    """The same keys the header path accepts; returns the key's NAME, or None.

    Imported here rather than at module scope: mcp_http imports this module for
    token checks, and a module-level import both ways is a cycle.
    """
    if not key:
        return None
    from serve.mcp_http import _partner_keys
    rec = _partner_keys().get(key)
    return rec.get("name") if rec else None


def current_key(who: str) -> dict | None:
    """The partner-key record a token was issued under, if it still exists.

    A token is only as alive as the key that earned it: removing a key from the
    key file must end every OAuth session opened with it, at once, and the
    token must spend that key's quota rather than none (F087, F357). Looked up
    by NAME, which is what a token records.
    """
    if not who:
        return None
    from serve.mcp_http import _partner_keys
    for rec in _partner_keys().values():
        if rec.get("name") == who:
            return rec
    return None


def _test_key_note() -> str:
    """Name the published test key on the consent page.

    A tester who already walked the OAuth discovery flow is sitting on this page
    with a password box and nothing to type into it, and the page previously
    told them only that a key exists. Read from the key file like every other
    key, so publishing or rotating it is one edit and this page follows; empty
    string when nothing is published, because the page must not name a key that
    does not work.
    """
    try:
        from serve.mcp_http import _public_test_record
        hit = _public_test_record()
    except Exception:                                            # noqa: BLE001
        return ""
    if not hit:
        return ""
    key, rec = hit
    return ('<p class="who">Testing? Use the public key '
            '<code>%s</code> — shared, no signup, %s calls a day across everyone '
            'using it.</p>' % (html.escape(key),
                               f"{int(rec.get('daily_quota') or 0):,}"))


def token_record(token: str) -> dict | None:
    """The stored record for a live access token, or None."""
    if not token:
        return None
    _prune()
    return _STATE["tokens"].get(token)


def valid_token(token: str) -> bool:
    rec = token_record(token)
    return bool(rec) and current_key(rec.get("who", "")) is not None


async def _form(request: Request) -> dict:
    """Form-encoded body, parsed with the stdlib.

    The token endpoint is form-encoded by spec and the consent page posts a
    plain form, so `application/x-www-form-urlencoded` is all that arrives
    here — and Starlette's own parser would drag in `python-multipart` for
    that. One dependency less on a box that takes deploys on a whim.
    """
    raw = (await request.body()) or b""
    return dict(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True))


# ── RFC 9728: what protects this resource ────────────────────────────────────
def _protected_resource() -> dict:
    return {
        "resource": RESOURCE,
        "resource_name": NAME,
        "authorization_servers": [PUBLIC_BASE],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
        # Served by this API (serve/front_door.py). Until 2026-09-25 this named
        # /docs/PARTNER-API.md, a 404: the one link a client is given to read.
        "resource_documentation": f"{PUBLIC_BASE}/docs/partner",
        "resource_policy_uri": f"{PUBLIC_BASE}/docs/partner#8-attribution-and-licence",
    }


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/{rest:path}", include_in_schema=False)
def protected_resource(rest: str = "") -> dict:
    """Claude asks for the path-suffixed form first, then the bare one."""
    return _protected_resource()


# ── RFC 8414: where to authorize and where to get a token ────────────────────
def _as_metadata() -> dict:
    return {
        "issuer": PUBLIC_BASE,
        "authorization_endpoint": f"{PUBLIC_BASE}/authorize",
        "token_endpoint": f"{PUBLIC_BASE}/token",
        "registration_endpoint": f"{PUBLIC_BASE}/register",
        "scopes_supported": [SCOPE],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        # public client: the connector ships no secret, PKCE is the protection
        "token_endpoint_auth_methods_supported": ["none"],
        "service_documentation": f"{PUBLIC_BASE}/docs/partner",
    }


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
@router.get("/.well-known/oauth-authorization-server/{rest:path}", include_in_schema=False)
def as_metadata(rest: str = "") -> dict:
    return _as_metadata()


# ── RFC 7591: dynamic client registration ────────────────────────────────────
@router.post("/register", include_in_schema=False)
async def register(request: Request) -> JSONResponse:
    """A hosted client registers itself. Public metadata, so nothing to guard:
    registration is not authorization, and a client_id alone opens no door."""
    try:
        body = json.loads(await request.body() or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "invalid_client_metadata",
                             "error_description": "body must be JSON"}, status_code=400)
    uris = [u for u in (body.get("redirect_uris") or []) if isinstance(u, str) and u]
    if not uris:
        return JSONResponse({"error": "invalid_redirect_uri",
                             "error_description": "redirect_uris must list at least one"},
                            status_code=400)
    _load()
    cid = "pv2c_" + secrets.token_hex(12)
    _STATE["clients"][cid] = {
        "client_name": str(body.get("client_name") or "unnamed client")[:120],
        "redirect_uris": uris,
        "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save()
    return JSONResponse({
        "client_id": cid,
        "client_name": _STATE["clients"][cid]["client_name"],
        "redirect_uris": uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    }, status_code=201)


# ── the consent page: one field, the partner key ─────────────────────────────
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect to Palestine Data — live + databank</title>
<style>
 body{{font:16px/1.5 system-ui,sans-serif;margin:0;display:flex;min-height:100vh;
      align-items:center;justify-content:center;background:#0f1115;color:#e8e8e8}}
 main{{max-width:34rem;padding:2rem;background:#171a21;border:1px solid #262b36;
       border-radius:14px}}
 h1{{font-size:1.15rem;margin:0 0 .5rem}}
 p{{color:#a8b0bf;margin:.4rem 0 1.2rem}}
 label{{display:block;font-size:.85rem;color:#a8b0bf;margin-bottom:.35rem}}
 input{{width:100%;padding:.7rem;border-radius:9px;border:1px solid #2c3341;
        background:#0f1115;color:#e8e8e8;font-family:ui-monospace,monospace}}
 button{{margin-top:1rem;width:100%;padding:.8rem;border:0;border-radius:9px;
         background:#3ddc97;color:#08130d;font-weight:700;font-size:1rem;cursor:pointer}}
 .who{{font-size:.8rem;color:#6d7686;margin-top:1rem}}
 .who a{{color:#a8b0bf}}
</style></head><body><main>
<h1>Palestine Data — live + databank · <span lang="ar" dir="rtl">بيانات فلسطين</span></h1>
<p><strong>{client}</strong> is asking for <strong>read</strong> access to live
checkpoint, incident and road data and the historical databank.</p>
<form method="post" action="{action}">
  {hidden}
  <label for="key">Partner key</label>
  <input id="key" name="key" type="password" autocomplete="off"
         placeholder="pv2_..." required autofocus>
  <button type="submit">Connect</button>
</form>
<p class="who">No account, no password, nothing stored about you. The key says
which integration is calling, for rate limiting and attribution. How to get
one: <a href="/#connect">the front page</a>.</p>
{test_note}
</main></body></html>"""


def _hidden(params: dict, drop: str) -> str:
    return "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in params.items() if k != drop and isinstance(v, str) and v)


@router.get("/authorize", include_in_schema=False)
def authorize_page(request: Request) -> HTMLResponse:
    q = dict(request.query_params)
    wanted = ("client_id", "redirect_uri", "state", "code_challenge",
              "code_challenge_method", "response_type", "scope")
    params = {k: q.get(k, "") for k in wanted}
    # PKCE is required, not offered: without a challenge the flow issued a token
    # to whoever held the code (F359). The metadata already says S256 only.
    if not params["code_challenge"] or params["code_challenge_method"] != "S256":
        return HTMLResponse("<p>PKCE is required: send code_challenge with "
                            "code_challenge_method=S256.</p>", status_code=400)
    _load()
    client = _STATE["clients"].get(params["client_id"])
    name = (client or {}).get("client_name") or "An application"
    return HTMLResponse(_PAGE.format(client=html.escape(name),
                                     action="/authorize",
                                     test_note=_test_key_note(),
                                     hidden=_hidden(params, "state") +
                                            _hidden({"state": params["state"]}, "")))


@router.post("/authorize", include_in_schema=False, response_model=None)
async def authorize_submit(request: Request):
    form = await _form(request)
    cid = str(form.get("client_id") or "")
    ruri = str(form.get("redirect_uri") or "")
    _load()
    client = _STATE["clients"].get(cid)
    if not client:
        return HTMLResponse("<p>Unknown client. Re-add the connector.</p>",
                            status_code=400)
    if ruri not in client["redirect_uris"]:
        return HTMLResponse("<p>redirect_uri is not registered for this client.</p>",
                            status_code=400)
    if not str(form.get("code_challenge") or ""):
        return HTMLResponse("<p>PKCE is required: send code_challenge with "
                            "code_challenge_method=S256.</p>", status_code=400)
    who = _partner_key_ok(str(form.get("key") or "").strip())
    if not who:
        return HTMLResponse(
            _PAGE.replace("Connect</button>", "Try again</button>")
                 .replace("Partner key", "That key was not recognised — partner key")
                 .format(client=html.escape(client["client_name"]), action="/authorize",
                         test_note=_test_key_note(),
                         hidden=_hidden({k: str(v) for k, v in form.items()}, "key")),
            status_code=401)
    code = secrets.token_urlsafe(32)
    _CODES[code] = {"client_id": cid, "redirect_uri": ruri,
                    "challenge": str(form.get("code_challenge") or ""),
                    "who": who, "at": _now()}
    params = {"code": code}
    if form.get("state"):
        params["state"] = str(form["state"])
    sep = "&" if "?" in ruri else "?"
    return RedirectResponse(f"{ruri}{sep}{urlencode(params)}", status_code=302)


# ── the token endpoint ───────────────────────────────────────────────────────
def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not challenge:
        return False                   # PKCE is required (F359): no challenge, no token
    if not verifier:
        return False
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == challenge


def _issue(cid: str, who: str) -> dict:
    tok = "pv2t_" + secrets.token_urlsafe(32)
    ref = "pv2r_" + secrets.token_urlsafe(32)
    _STATE["tokens"][tok] = {"client_id": cid, "who": who, "issued": _now(),
                             "scope": SCOPE}
    _STATE["refreshes"][ref] = {"client_id": cid, "who": who, "issued": _now()}
    _save()
    return {"access_token": tok, "token_type": "Bearer", "expires_in": TOKEN_TTL,
            "refresh_token": ref, "scope": SCOPE}


@router.post("/token", include_in_schema=False)
async def token(request: Request) -> JSONResponse:
    form = await _form(request)
    grant = str(form.get("grant_type") or "")
    _load()

    if grant == "refresh_token":
        _prune()
        ref = str(form.get("refresh_token") or "")
        rec = _STATE["refreshes"].get(ref)
        if not rec:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        cid = str(form.get("client_id") or "")
        if cid and cid != rec["client_id"]:
            return JSONResponse({"error": "invalid_grant",
                                 "error_description": "refresh token was issued to "
                                                      "another client"}, status_code=400)
        if current_key(rec["who"]) is None:
            return JSONResponse({"error": "invalid_grant",
                                 "error_description": "the partner key behind this "
                                                      "token was revoked"}, status_code=400)
        # Rotation: a refresh token is spent by its use, so a copy stolen from a
        # log or a backup stops working the moment the client refreshes (F087).
        _STATE["refreshes"].pop(ref, None)
        return JSONResponse(_issue(rec["client_id"], rec["who"]))

    if grant != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    rec = _CODES.pop(str(form.get("code") or ""), None)      # single use, always
    if not rec or _now() - rec["at"] > CODE_TTL:
        return JSONResponse({"error": "invalid_grant",
                             "error_description": "unknown or expired code"},
                            status_code=400)
    if str(form.get("client_id") or "") != rec["client_id"]:
        return JSONResponse({"error": "invalid_grant",
                             "error_description": "code was issued to another client"},
                            status_code=400)
    if str(form.get("redirect_uri") or "") != rec["redirect_uri"]:
        return JSONResponse({"error": "invalid_grant",
                             "error_description": "redirect_uri mismatch"},
                            status_code=400)
    if not _pkce_ok(str(form.get("code_verifier") or ""), rec["challenge"]):
        return JSONResponse({"error": "invalid_grant",
                             "error_description": "PKCE verification failed"},
                            status_code=400)
    return JSONResponse(_issue(rec["client_id"], rec["who"]))


load_on_import = _load()
