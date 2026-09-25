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

A TOKEN IS ONLY AS GOOD AS THE KEY BEHIND IT (audit F090/F357, 2026-09-25)
A token records the NAME of the key that was typed on the consent page, and
every use resolves that name against the key file as it is now: a key removed
from the file takes its tokens with it, and a token is metered against its key's
daily quota exactly like the key itself. Before this a revoked key's token kept
working for 30 days, was never metered, and its refresh token renewed it forever
and could be replayed — revocation "by file edit" was false for every hosted
client. Refresh tokens are single-use and bound to the client they were issued
to, and PKCE (S256) is required, which is what the MCP spec already asks of
every client, Claude's connector included.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()

PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://live-api.zaidlab.xyz")
RESOURCE = f"{PUBLIC_BASE}/mcp"
# Beside the partner keys, in the checkout this module runs from — which on
# main-server is /home/zaid/palestine-v2, the path this used to hard-code. A
# second checkout (a dev API, a restore under another user) now finds its own
# `.keys/` instead of silently starting cold against a path that is not there.
STATE_PATH = Path(os.environ.get(
    "OAUTH_STATE_PATH",
    Path(__file__).resolve().parent.parent / ".keys" / "oauth-state.json"))

CODE_TTL = 300                 # five minutes: enough for a redirect, no more
TOKEN_TTL = 30 * 24 * 3600     # a release cycle
REFRESH_TTL = 90 * 24 * 3600
SCOPE = "read"

# Registration is open by design (RFC 7591; a client_id opens no door), which
# made the state file the one thing a stranger could grow without limit: every
# POST /register added a client forever, and every /token re-parses and rewrites
# the whole file. Clients that never got a token are dropped after a day, and
# past this many the oldest token-less ones go first. A client holding a live
# token is never evicted — that would log a real connector out.
MAX_CLIENTS = 2000
UNUSED_CLIENT_TTL = 24 * 3600

_CODES: dict[str, dict] = {}
_STATE: dict = {"clients": {}, "tokens": {}, "refreshes": {}}

# The handlers run on two kinds of thread — the async ones on the event loop,
# the consent page on the threadpool — and `_load()` replaces the in-memory
# dicts wholesale. Without a lock a `_load()` landing between another request's
# mutation and its `_save()` dropped a token that had just been handed out, and
# the client got 401 on the token it was given a second earlier.
_LOCK = threading.RLock()


def _load() -> None:
    with _LOCK:
        try:
            _STATE.update(json.loads(STATE_PATH.read_text()))
        except Exception:                                        # noqa: BLE001
            pass                    # a missing or broken file is a cold start


def _save() -> None:
    """Write the state file owner-only, atomically.

    It holds every live bearer and refresh token. `Path.write_text` created the
    temporary file with the process umask (0644 under systemd's default) and
    the rename carried that mode onto the target — so a `chmod 600` on the host
    was undone by the very next /token call. `mkstemp` creates the file 0600 and
    unique, so neither the mode nor a concurrent writer's temp file can leak.
    """
    with _LOCK:
        tmp = None
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=STATE_PATH.parent,
                                       prefix=".oauth-state.", suffix=".tmp")
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps(_STATE, indent=1))
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, STATE_PATH)
            tmp = None
        except Exception:                                        # noqa: BLE001
            pass                    # never let bookkeeping fail a live request
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


def _now() -> float:
    return time.time()


def _prune() -> None:
    """Forget what has expired.

    Each store by its OWN lifetime: both used to be pruned at the 30-day token
    TTL (a `keep` flag that was 1 for both), so the 90-day refresh token
    PARTNER-API.md promises died at 30. Authorization codes are pruned too —
    only an exchange removed them, so a code nobody exchanged lived in memory
    until the next restart.
    """
    t = _now()
    with _LOCK:
        for store, ttl in ((_STATE["tokens"], TOKEN_TTL),
                           (_STATE["refreshes"], REFRESH_TTL)):
            for k in [k for k, v in store.items() if t - v.get("issued", 0) > ttl]:
                store.pop(k, None)
        for c in [c for c, v in list(_CODES.items()) if t - v.get("at", 0) > CODE_TTL]:
            _CODES.pop(c, None)


def _prune_clients(keep: str = "") -> None:
    """Bound the client registry (see MAX_CLIENTS). Called on registration,
    the only path that grows it; `keep` is the client just registered."""
    with _LOCK:
        t = _now()
        live = {v.get("client_id") for v in _STATE["tokens"].values()} | \
               {v.get("client_id") for v in _STATE["refreshes"].values()} | {keep}
        clients = _STATE["clients"]

        def registered(cid: str) -> float:
            try:
                return datetime.fromisoformat(
                    clients[cid].get("registered_at", "")).timestamp()
            except (TypeError, ValueError):
                return float("-inf")        # unreadable date: oldest of all

        for cid in [c for c in clients
                    if c not in live and t - registered(c) > UNUSED_CLIENT_TTL]:
            clients.pop(cid, None)
        # Oldest first; equal timestamps keep registration order (stable sort).
        spare = sorted((c for c in clients if c not in live), key=registered)
        while len(clients) > MAX_CLIENTS and spare:
            clients.pop(spare.pop(0), None)


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


def _key_named(name: str | None) -> dict | None:
    """The key record a token was minted from, as the key file says NOW.

    By name, not by key string: the name is the partner's identity, so rotating
    a leaked key string keeps its holder's tokens while deleting the entry ends
    them — the same revocation a header key has always had.
    """
    if not name:
        return None
    from serve.mcp_http import _partner_keys
    for rec in _partner_keys().values():
        if rec.get("name") == name:
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


def token_key(token: str) -> dict | None:
    """The CURRENT key record behind a bearer token, or None.

    None for an unknown or expired token, and for one whose key has since been
    removed from the key file. The caller meters the returned record against
    its daily quota, so a token is never a way around the key's limits.
    """
    if not token:
        return None
    with _LOCK:
        _prune()
        rec = _STATE["tokens"].get(token)
    return _key_named(rec.get("who")) if rec else None


def valid_token(token: str) -> bool:
    return token_key(token) is not None


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
# Z-4 (PLAN-2026-09-24 §5): one name, the one serverInfo and the instructions
# already use. The consent page a Claude or ChatGPT user sees said "Palestine
# live tracker", a product no other surface names.
NAME = "Palestine Data — live + databank"


def _protected_resource() -> dict:
    return {
        "resource": RESOURCE,
        "resource_name": NAME,
        "authorization_servers": [PUBLIC_BASE],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
        "resource_documentation": f"{PUBLIC_BASE}/docs/PARTNER-API.md",
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
    }


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
@router.get("/.well-known/oauth-authorization-server/{rest:path}", include_in_schema=False)
def as_metadata(rest: str = "") -> dict:
    return _as_metadata()


# ── RFC 7591: dynamic client registration ────────────────────────────────────
# Where a code may be sent. Any non-empty string used to pass, including
# `javascript:` and plain http to any host; the code is appended to it and the
# browser is sent there. Allowed: https, http to this machine (RFC 8252 §7.3 —
# a desktop client's local listener), and an app's own private-use scheme
# (RFC 8252 §7.1). Never a fragment (RFC 6749 §3.1.2), never a scheme a browser
# executes or renders in place.
MAX_REDIRECT_URIS = 10
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
_NEVER_SCHEMES = ("javascript", "data", "vbscript", "file", "blob", "about")


def _redirect_ok(uri: str) -> bool:
    if len(uri) > 2000 or "#" in uri:
        return False
    try:
        parts = urlsplit(uri)
        host = parts.hostname
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if not scheme or scheme in _NEVER_SCHEMES:
        return False
    if scheme == "https":
        return bool(host)
    if scheme == "http":
        return host in _LOOPBACK_HOSTS
    return True                                  # an app's private-use scheme


def _destination(uri: str) -> str:
    """What the consent page names as the place the code goes."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return uri[:80]
    if parts.scheme in ("https", "http") and parts.netloc:
        return parts.netloc
    return f"{parts.scheme}:" if parts.scheme else uri[:80]


@router.post("/register", include_in_schema=False)
async def register(request: Request) -> JSONResponse:
    """A hosted client registers itself. Public metadata, so nothing to guard:
    registration is not authorization, and a client_id alone opens no door."""
    try:
        body = json.loads(await request.body() or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "invalid_client_metadata",
                             "error_description": "body must be JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid_client_metadata",
                             "error_description": "body must be a JSON object"},
                            status_code=400)
    listed = body.get("redirect_uris")
    uris = [u for u in (listed if isinstance(listed, list) else [])
            if isinstance(u, str) and u]
    if not uris:
        return JSONResponse({"error": "invalid_redirect_uri",
                             "error_description": "redirect_uris must list at least one"},
                            status_code=400)
    bad = [u for u in uris if not _redirect_ok(u)]
    if bad or len(uris) > MAX_REDIRECT_URIS:
        return JSONResponse({"error": "invalid_redirect_uri",
                             "error_description": (
                                 "a redirect_uri must be https://, a loopback "
                                 "http:// address, or an app's own scheme — no "
                                 "fragment, at most %d of them" % MAX_REDIRECT_URIS)},
                            status_code=400)
    with _LOCK:
        _load()
        cid = "pv2c_" + secrets.token_hex(12)
        _STATE["clients"][cid] = {
            "client_name": str(body.get("client_name") or "unnamed client")[:120],
            "redirect_uris": uris,
            "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _prune_clients(keep=cid)
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
</style></head><body><main>
<h1>Palestine Data — live + databank</h1>
<p><strong>{client}</strong> is asking for <strong>read</strong> access to live
checkpoint, incident and road data.</p>
<p>After you connect you will be sent to <strong>{dest}</strong>. If that is not
the application you are adding, stop here.</p>
<form method="post" action="{action}">
  {hidden}
  <label for="key">Partner key</label>
  <input id="key" name="key" type="password" autocomplete="off"
         placeholder="pv2_..." required autofocus>
  <button type="submit">Connect</button>
</form>
<p class="who">No account, no password, nothing stored about you. The key says
which integration is calling, for rate limiting and attribution.</p>
{test_note}
</main></body></html>"""


def _hidden(params: dict, drop: str) -> str:
    return "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in params.items() if k != drop and isinstance(v, str) and v)


# PKCE is REQUIRED, and only S256. It was optional: a client that sent no
# challenge got a code anyone who saw the redirect could exchange (a referrer, a
# log, a shared device), and the metadata's `token_endpoint_auth_methods:
# none` means there is no client secret behind it either. The MCP authorization
# spec already obliges every client to send S256, so this refuses only the
# clients that were never following it.
_PKCE_REQUIRED = ("<p>This server requires PKCE with S256 "
                  "(<code>code_challenge</code> and "
                  "<code>code_challenge_method=S256</code>).</p>")


def _pkce_asked(params: dict) -> bool:
    return bool(params.get("code_challenge")) and \
        params.get("code_challenge_method") == "S256"


@router.get("/authorize", include_in_schema=False)
def authorize_page(request: Request) -> HTMLResponse:
    q = dict(request.query_params)
    wanted = ("client_id", "redirect_uri", "state", "code_challenge",
              "code_challenge_method", "response_type", "scope")
    params = {k: q.get(k, "") for k in wanted}
    if not _pkce_asked(params):
        return HTMLResponse(_PKCE_REQUIRED, status_code=400)
    _load()
    client = _STATE["clients"].get(params["client_id"])
    name = (client or {}).get("client_name") or "An application"
    return HTMLResponse(_PAGE.format(client=html.escape(name),
                                     dest=html.escape(_destination(params["redirect_uri"])),
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
    if not _pkce_asked(form):
        return HTMLResponse(_PKCE_REQUIRED, status_code=400)
    who = _partner_key_ok(str(form.get("key") or "").strip())
    if not who:
        return HTMLResponse(
            _PAGE.replace("Connect</button>", "Try again</button>")
                 .replace("Partner key", "That key was not recognised — partner key")
                 .format(client=html.escape(client["client_name"]), action="/authorize",
                         dest=html.escape(_destination(ruri)),
                         test_note=_test_key_note(),
                         hidden=_hidden({k: str(v) for k, v in form.items()}, "key")),
            status_code=401)
    code = secrets.token_urlsafe(32)
    _prune()
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
    # No challenge is a refusal, not a pass: /authorize no longer issues a code
    # without one, so a code without one is a code from before this rule.
    if not challenge or not verifier:
        return False
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == challenge


def _issue(cid: str, who: str) -> dict:
    tok = "pv2t_" + secrets.token_urlsafe(32)
    ref = "pv2r_" + secrets.token_urlsafe(32)
    with _LOCK:
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
        # Single use and bound to its client (OAuth 2.1 §4.3.1 for public
        # clients). The used token is removed as the new pair is issued, so a
        # replayed or stolen one is dead the moment its owner refreshes; the
        # key it came from is re-checked, so a revoked key cannot refresh.
        ref = str(form.get("refresh_token") or "")
        with _LOCK:
            _prune()
            rec = _STATE["refreshes"].get(ref)
            if not rec:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            asked = str(form.get("client_id") or "")
            if asked and asked != rec.get("client_id"):
                return JSONResponse({"error": "invalid_grant",
                                     "error_description": "refresh token was issued "
                                                          "to another client"},
                                    status_code=400)
            if _key_named(rec.get("who")) is None:
                # Left in place rather than deleted: a key file that is briefly
                # missing (an edit in progress) must not log every connector
                # out for good. It is useless until the key is back.
                return JSONResponse({"error": "invalid_grant",
                                     "error_description": "the key this connection "
                                                          "was made with has been "
                                                          "revoked"},
                                    status_code=400)
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
