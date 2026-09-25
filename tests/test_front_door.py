"""P2-B — the front door (gate G6): one name, one page, every link answering.

What these hold, and the failure behind each:

* `GET /` negotiates. The JSON route map is a contract API clients already
  parse, so a request that does not PREFER text/html — `application/json`,
  `*/*` (curl, httpx, requests), a tie — must get exactly the JSON it got
  before; only a browser gets the page.
* The page phones nobody. DESIGN.md law 5 (no external request) is checked on
  the served HTML: every src/href is this origin, a data: URI, or one of the
  documented connect targets.
* Every link resolves. The OAuth metadata pointed its one documentation link at
  /docs/PARTNER-API.md and every 401 at zaidlab.xyz/palestine — both 404 until
  2026-09-25 (PLAN R6). The links on the page, in PARTNER-API.md and in the
  OAuth metadata are walked against a running dev API (`PALESTINE_API`);
  external ones are listed and skipped.
* The twelve questions on the page are the twelve in docs/try-twelve.sh and in
  PARTNER-API §9, answered through the partner pipeline.

    PALESTINE_API=http://127.0.0.1:7873 .venv/bin/python -m pytest -q tests/test_front_door.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("fastapi")
import httpx                                                    # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

from serve import front_door as fd                              # noqa: E402
from serve.app import app, discovery                            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = "https://live-api.zaidlab.xyz"
DEV = os.environ.get("PALESTINE_API", "").rstrip("/")
needs_dev = pytest.mark.skipif(not DEV, reason="set PALESTINE_API to a running dev API")
client = TestClient(app, raise_server_exceptions=False)

BROWSERS = {
    "chrome": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "firefox": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "safari": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
BROWSER = BROWSERS["chrome"]
# The only places the page may point off this origin — each is a documented
# connect/contact target a person clicks, never something the page loads.
EXTERNAL_TARGETS = {"https://claude.ai/settings/connectors", "mailto:zaidsalem@live.com"}


def _page(base: str | None = None) -> httpx.Response:
    if base:
        return httpx.get(base + "/", headers={"accept": BROWSER}, timeout=30)
    return client.get("/", headers={"accept": BROWSER})


def _attrs(page: str, name: str) -> list[str]:
    return re.findall(rf'\b{name}="([^"]*)"', page)


# ── content negotiation ──────────────────────────────────────────────────────
@pytest.mark.parametrize("accept,html", [
    (None, False), ("", False), ("*/*", False), ("application/json", False),
    ("application/json, text/html", False),          # a tie keeps the contract
    ("text/html;q=0.5, application/json", False),
    ("application/json;q=0.9, text/html;q=0.9", False),
    ("text/html;q=0", False),
    ("text/html", True), ("application/xhtml+xml", True),
    ("text/html, application/json;q=0.9", True),
    *[(a, True) for a in BROWSERS.values()],
])
def test_only_a_preference_for_html_gets_the_page(accept, html):
    assert fd.wants_html(accept) is html


@pytest.mark.parametrize("accept", ["*/*", "application/json", "application/json, text/html",
                                    "text/html;q=0.1, */*"])
def test_api_clients_get_the_json_unchanged(accept):
    r = client.get("/", headers={"accept": accept})
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"].split(";")[0] == "application/json"
    assert "accept" in r.headers.get("vary", "").lower()
    got, want = r.json(), discovery()
    assert list(got) == list(want), "the route map's keys moved"
    got.pop("now"), want.pop("now")
    assert got == want


@pytest.mark.parametrize("browser", sorted(BROWSERS))
def test_a_browser_gets_the_page(browser):
    r = client.get("/", headers={"accept": BROWSERS[browser]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    page = r.text
    assert '<html lang="ar" dir="rtl"' in page
    assert fd.NAME_AR in page and fd.NAME in page
    assert not re.findall(r"__[A-Z_]+__", page), "a template placeholder was left unfilled"
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert f'<script nonce="{nonce}">' in page
    assert "accept" in r.headers.get("vary", "").lower()
    # the twelve questions ride in the page as data, not as a second request
    data = re.search(r'<script type="application/json" id="try-data">(.*?)</script>', page, re.S)
    qs = json.loads(data.group(1))
    assert [(q["tool"], q["arguments"]) for q in qs] == [(q["tool"], q["arguments"]) for q in fd.TRY]
    assert len(page.encode()) < 32 * 1024, "keep the front page small (2G, one hand)"


def test_the_page_names_the_published_key_or_hides_the_box():
    """The key is read from the key file, like the 401 body; when none is
    published the page says so instead of naming a key that does not work."""
    page = _page().text
    shown = re.search(r'<code id="key" dir="ltr">([^<]*)</code>', page).group(1)
    key, quota = fd._public_key()
    assert shown == key
    if key:
        assert key.startswith("pv2_") and f"{quota:,}" in page


def test_the_three_words_are_three_renderings():
    """value / unknown / no source (DESIGN.md law 2): three classes, and the
    unknown one has no fill — the absence of knowledge is not a state colour."""
    page = _page().text
    for cls, word in (("ok", "سالك"), ("unk", "غير معروف"), ("none", "لا مصدر")):
        assert re.search(rf'<span class="chip {cls}">{word} ', page), (cls, word)
    unk = re.search(r"\.chip\.unk\s*\{([^}]*)\}", page).group(1)
    assert "background" not in unk


# ── no external request ──────────────────────────────────────────────────────
def test_the_page_makes_no_external_request():
    page = _page().text
    for src in _attrs(page, "src"):
        assert src.startswith("/") and not src.startswith("//") or src.startswith("data:"), src
    for href in _attrs(page, "href"):
        ok = (href.startswith(("/", "#", "data:")) and not href.startswith("//")) \
            or href in EXTERNAL_TARGETS
        assert ok, f"href off this origin: {href}"
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', page)
    assert sheets == ["/app/tokens.css"]
    assert "@import" not in page and not re.search(r"url\(\s*['\"]?(https?:)?//", page)
    script = page.split('<script nonce=', 1)[1]
    assert not re.search(r"https?://", script), "the script names an absolute URL"
    # Absolute URLs in the text are the connect targets a reader copies — this
    # host's own MCP and REST addresses — and the documented links above.
    for url in re.findall(r"(?:https?://|mailto:)[^\s\"'<>`]+", page):
        assert url.startswith(PUBLIC) or url in EXTERNAL_TARGETS, url
    css = (ROOT / "serve" / "webapp" / "tokens.css").read_text()
    assert "@import" not in css and "url(" not in css


# ── the partner guide ────────────────────────────────────────────────────────
def test_docs_partner_renders():
    r = client.get("/docs/partner")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "script-src" not in r.headers["content-security-policy"]       # no script at all
    h = r.text
    assert "<script" not in h and fd.NAME in h and 'href="/"' in h
    for anchor in ("1-authentication", "3-the-tools", "8-attribution-and-licence",
                   "9-twelve-questions-to-try-first",
                   "11-availability-and-what-to-do-when-something-looks-wrong"):
        assert f'id="{anchor}"' in h, anchor
    assert "<table>" in h and "<pre><code>" in h and "<br>" in h
    from serve.mcp_facades import listed_tools
    for t in listed_tools():
        assert f"<code>{t['name']}</code>" in h, t["name"]
    body = h.split("<main>", 1)[1]
    assert "**" not in re.sub(r"<pre>.*?</pre>", "", body, flags=re.S)
    assert "&lt;br&gt;" not in body


def test_the_guide_and_the_script_are_served_as_files():
    md = client.get("/docs/partner.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.text == (ROOT / "docs" / "PARTNER-API.md").read_text(encoding="utf-8")
    sh = client.get("/docs/try-twelve.sh")
    assert sh.status_code == 200 and sh.headers["content-type"].startswith("text/plain")
    assert sh.text == (ROOT / "docs" / "try-twelve.sh").read_text(encoding="utf-8")
    old = client.get("/docs/PARTNER-API.md", follow_redirects=False)
    assert old.status_code == 301 and old.headers["location"] == "/docs/partner"


def test_the_renderer_escapes_everything_it_does_not_make():
    out = fd.render_markdown(
        "<script>alert(1)</script>\n\n[x](javascript:alert(1)) <img src=x onerror=alert(1)> "
        "**b** `<i>`\n\n| a | b |\n|---|---|\n| <b>1</b> | 2 |\n\n"
        "arguments: `origin`*, `destination`*\n")
    assert "<script" not in out and "<img" not in out and "<b>" not in out
    assert 'href="javascript' not in out and "&lt;script&gt;" in out
    assert "<strong>b</strong>" in out and "<code>&lt;i&gt;</code>" in out
    assert "<em>" not in out, "starred required arguments turned italic"


# ── the twelve questions ─────────────────────────────────────────────────────
def _script_calls() -> list[tuple[str, dict]]:
    sh = (ROOT / "docs" / "try-twelve.sh").read_text(encoding="utf-8")
    block = sh.split("calls=(", 1)[1].split("\n)", 1)[0]
    out = []
    for name, args in re.findall(r'^\s*"(\w+)\|(.*)"\s*$', block, re.M):
        out.append((name, json.loads(args.replace('\\"', '"'))))
    return out


def test_the_page_asks_the_scripts_twelve_and_the_guides_twelve():
    mine = [(q["tool"], q["arguments"]) for q in fd.TRY]
    assert len(mine) == 12 and [q["n"] for q in fd.TRY] == list(range(1, 13))
    assert _script_calls() == mine
    guide = (ROOT / "docs" / "PARTNER-API.md").read_text(encoding="utf-8")
    by_hand = [(n, json.loads(a)) for n, a in re.findall(r"^call (\w+) '(.*)'$", guide, re.M)]
    assert by_hand == mine


def test_the_script_carries_no_partner_name_and_the_old_one_is_gone():
    sh = (ROOT / "docs" / "try-twelve.sh").read_text(encoding="utf-8")
    assert "thaura" not in sh.lower()
    assert not (ROOT / "docs" / "try-ten-calls.sh").exists()
    for f in ("docs/PARTNER-API.md", "README.md", "ops/mcp-registration.md",
              "docs/HANDS-2026-09-24.md", "serve/webapp/front.html"):
        text = (ROOT / f).read_text(encoding="utf-8")
        assert "try-ten-calls.sh` until" not in text and "THAURA_KEY" not in text, f


@pytest.mark.parametrize("n,code", [(0, 404), (13, 404), ("x", 422)])
def test_the_try_route_answers_only_its_twelve(n, code):
    assert client.get(f"/v2/try/{n}").status_code == code


# ── one name ─────────────────────────────────────────────────────────────────
def test_one_name_everywhere_a_stranger_looks():
    from serve import mcp_http, mcp_oauth
    assert mcp_oauth._protected_resource()["resource_name"] == fd.NAME
    assert fd.NAME in mcp_oauth._PAGE
    src = (ROOT / "serve" / "mcp_oauth.py").read_text(encoding="utf-8")
    assert "Palestine live tracker" not in src
    init = mcp_http._handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["title"] == fd.NAME
    assert fd.NAME in (ROOT / "docs" / "PARTNER-API.md").read_text(encoding="utf-8").splitlines()[0]
    assert fd.NAME in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert fd.NAME in (ROOT / "ops" / "mcp-registration.md").read_text(encoding="utf-8")


# ── against the dev API: every link answers ──────────────────────────────────
# Paths a link may name that are not plain GETs: how each one is asked, and
# what "it exists" looks like. Nothing here writes — each is refused before
# any state is touched (no redirect_uris; no grant; no PKCE).
NOT_A_GET = {
    "/mcp": ("POST", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {200}),
    "/register": ("POST", {}, {400}),
    "/token": ("POST", None, {400}),
    "/authorize": ("GET", None, {400}),
}


def _resolve(base: str, path: str) -> int:
    path = path.split("#", 1)[0].split("?", 1)[0] or "/"
    if path in NOT_A_GET:
        method, body, _ = NOT_A_GET[path]
        return httpx.request(method, base + path, json=body, timeout=60).status_code
    if path == "/v2/stream":                                   # SSE never ends
        with httpx.stream("GET", base + path, timeout=30) as r:
            return r.status_code
    return httpx.get(base + path, timeout=60).status_code


def _expect(path: str) -> set[int]:
    path = path.split("#", 1)[0].split("?", 1)[0] or "/"
    return NOT_A_GET[path][2] if path in NOT_A_GET else {200}


def _local(url: str) -> str | None:
    """This host's path for a URL, or None for somewhere else."""
    if url.startswith(PUBLIC):
        return url[len(PUBLIC):] or "/"
    if url.startswith("/") and not url.startswith("//"):
        return url
    return None


@needs_dev
def test_every_link_on_the_page_answers():
    r = _page(DEV)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    ids = set(_attrs(page, "id"))
    for href in _attrs(page, "href"):
        if href.startswith("data:"):                       # the empty favicon
            continue
        if href.startswith("#") or href.startswith("/#"):
            assert href.split("#", 1)[1] in ids, href
            continue
        path = _local(href)
        if path is None:
            assert href in EXTERNAL_TARGETS, href           # listed, not walked
            continue
        assert _resolve(DEV, path) in _expect(path), href
    for path in re.findall(r'getJSON\("(/[^"]+)"\)', page):
        assert _resolve(DEV, path) == 200, path


@needs_dev
def test_the_twelve_answers_are_real():
    for q in fd.TRY:
        r = httpx.get(f"{DEV}/v2/try/{q['n']}", timeout=120)
        assert r.status_code == 200, (q["n"], r.text[:200])
        d = r.json()
        assert d["failed"] is False, (q["n"], d)
        assert d["answer"] and d["answer_en"], (q["n"], d)
        assert d["tool"] == q["tool"] and d["arguments"] == q["arguments"]
        assert d["age_seconds"] <= fd.TRY_TTL


@needs_dev
def test_the_partner_guide_links_resolve():
    guide = (ROOT / "docs" / "PARTNER-API.md").read_text(encoding="utf-8")
    rendered = httpx.get(f"{DEV}/docs/partner", timeout=30).text
    ids = set(_attrs(rendered, "id"))
    external = []
    for href in _attrs(rendered.split("<main>", 1)[1], "href"):
        if href.startswith("#"):
            assert href[1:] in ids, href
            continue
        path = _local(href)
        if path is None:
            external.append(href)
            continue
        assert _resolve(DEV, path) in _expect(path), href
    assert set(external) <= EXTERNAL_TARGETS, external
    # And every address the guide NAMES, links or not: its URLs on this host and
    # every absolute path in a code span, each asked the way it is served.
    named = {u for u in re.findall(r"https://live-api\.zaidlab\.xyz(/[^\s`)\"'<>]*)", guide)}
    named |= set(re.findall(r"`(?:GET |POST )?(/[A-Za-z.][^`\s]*)`", guide))
    named |= set(re.findall(r"\b(?:GET|POST) (/[A-Za-z.][^\s`]*)", guide))
    named = {p.rstrip(".,;:") for p in named if "..." not in p and "{" not in p}
    assert {"/mcp", "/health", "/v2/licence/tools", "/docs/partner"} <= named
    for path in sorted(named):
        assert _resolve(DEV, path) in _expect(path), path


@needs_dev
def test_the_oauth_metadata_links_resolve():
    urls = []
    for doc in ("/.well-known/oauth-protected-resource",
                "/.well-known/oauth-protected-resource/mcp",
                "/.well-known/oauth-authorization-server"):
        meta = httpx.get(DEV + doc, timeout=30).json()
        for v in meta.values():
            urls += [x for x in (v if isinstance(v, list) else [v])
                     if isinstance(x, str) and x.startswith("http")]
    assert urls and all(u.startswith(PUBLIC) for u in urls), urls
    assert any(u.endswith("/docs/partner") for u in urls)
    for u in urls:
        path = _local(u)
        assert _resolve(DEV, path) in _expect(path), u
    # The 401 a stranger gets names where to read and where to get a key.
    r = httpx.post(DEV + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                   headers={"x-forwarded-for": "203.0.113.9"}, timeout=30)
    assert r.status_code == 401
    assert "zaidlab.xyz/palestine" not in json.dumps(dict(r.headers))
    meta_url = re.search(r'resource_metadata="([^"]+)"', r.headers["www-authenticate"]).group(1)
    assert _resolve(DEV, _local(meta_url)) == 200
    ask = r.headers["x-key-request"]
    assert ask == f"{PUBLIC}/#connect"
    page = _page(DEV).text
    assert 'id="connect"' in page


@needs_dev
def test_the_page_answers_through_the_partner_pipeline():
    """The page's route and a partner's MCP call must say the same thing: the
    route composes the same steps as `_handle` minus the usage ledger."""
    from serve import mcp_http
    mine, failed = fd._ask("crossings", {"place": "رفح"})
    reply = mcp_http._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "crossings", "arguments": {"place": "رفح"}}},
                             None, "partner")
    theirs = reply["result"]["structuredContent"]
    assert failed is False
    assert mine["answer"] == theirs["answer"] and mine["answer_en"] == theirs["answer_en"]
    assert set(mine) == set(theirs)
    assert mine["licence"]["tier"] == theirs["licence"]["tier"] == "partner"
