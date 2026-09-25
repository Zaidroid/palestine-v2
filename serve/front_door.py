"""P2-B — the front door (gate G6): one page for a person, one guide for a partner.

WHY THIS EXISTS
Until 2026-09-25 the bare hostname answered a browser with a JSON route map, the
partner guide lived only in the repository (the OAuth metadata pointed at
`/docs/PARTNER-API.md`, a 404, and every 401 carried a key-request link to
`zaidlab.xyz/palestine`, another 404), and the twelve questions the release is
measured on could be seen only by running a shell script with a key. A stranger
who found live-api.zaidlab.xyz could not tell what it was, whether it was alive,
or how to connect.

WHAT IT SERVES
* `GET /` negotiates (serve/app.py `root()` calls `wants_html`): a request that
  PREFERS text/html gets `webapp/front.html`; `application/json`, `*/*`, no
  Accept at all, or a tie get the JSON exactly as before. The API's contract does
  not move because a client also listed text/html.
* `/docs/partner` is docs/PARTNER-API.md rendered by the small renderer below (no
  dependency: every character is escaped first and only a closed set of tags is
  produced); `/docs/partner.md` is the file itself; `/docs/try-twelve.sh` is the
  script the guide tells a partner to run, which nobody off this host could
  download before. `/docs/PARTNER-API.md` — the URL the OAuth metadata used to
  publish — redirects to the rendered guide.
* `/v2/try/{n}` answers canonical question n through the pipeline a partner's MCP
  call takes (façade → tool → English → licence at the partner tier), remembered
  for two minutes. The questions are fixed, so no caller input reaches a tool:
  this opens nothing the keyless REST routes do not already serve, and the cost
  is bounded at twelve tool runs per two minutes however many people open the
  page. It does not write to the MCP usage ledger — that ledger is what real
  callers ask, and a page asking the same twelve questions would drown it (the
  40 %-test-fixture lesson in tests/conftest.py).

The page obeys docs/DESIGN.md — Arabic first, no external request (the CSP below
enforces that in the browser, not only in review), the three-state vocabulary,
a word and an age on every status chip.
"""
from __future__ import annotations

import html
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "serve" / "webapp" / "front.html"
PARTNER_DOC = ROOT / "docs" / "PARTNER-API.md"
TRY_SCRIPT = ROOT / "docs" / "try-twelve.sh"

NAME = "Palestine Data — live + databank"
NAME_AR = "بيانات فلسطين"

router = APIRouter()


# ── the twelve canonical questions (PLAN §10; docs/try-twelve.sh asks the same
# twelve in the same order — tests/test_front_door.py holds the two together) ──
TRY: tuple[dict, ...] = tuple(
    {"n": i, "tool": tool, "arguments": args, "ar": ar, "en": en}
    for i, (tool, args, ar, en) in enumerate((
        ("about", {},
         "شو عندكم، وشو اللي ما عندكم؟", "What do you hold — and what do you hold nothing for?"),
        ("checkpoint_status", {"name": "قلنديا"},
         "قلنديا هلّأ؟", "Qalandia, right now?"),
        ("checkpoint_status", {"name": "Huwara"},
         "حوارة — والسؤال بالإنجليزي", "Huwara, asked in English"),
        ("can_i_travel", {"origin": "رام الله", "destination": "نابلس"},
         "بقدر أروح من رام الله لنابلس؟", "Can I drive from Ramallah to Nablus?"),
        ("can_i_travel", {"origin": "Nablus", "destination": "Jenin"},
         "من نابلس لجنين — بالإنجليزي", "Nablus to Jenin, asked in English"),
        ("incidents", {"place": "رام الله", "hours": 12},
         "شو صار حوالين رام الله آخر 12 ساعة؟", "What happened around Ramallah in the last 12 hours?"),
        ("insights", {"place": "نابلس", "days": 7},
         "كيف كان الأسبوع حوالين نابلس؟", "What was this week like around Nablus?"),
        ("crossings", {"place": "رفح"},
         "معبر رفح؟", "The Rafah crossing?"),
        ("fuel_prices", {},
         "أسعار المحروقات الرسمية؟", "Official fuel prices?"),
        ("databank", {"category": "casualties", "limit": 3},
         "آخر أرقام الشهداء؟", "The latest fatality figures?"),
        ("databank", {"category": "demolitions", "limit": 5},
         "الهدم — آخر الأرقام؟", "Demolitions — the latest figures?"),
        ("place", {"place": "حوارة", "view": "history", "days": 30},
         "حوارة آخر 30 يوم؟", "Huwara over the last 30 days?"),
    ), start=1))

TRY_TTL = 120          # an answer is re-asked after two minutes
TRY_ERROR_TTL = 30     # a failure is retried soon, never remembered for long
_TRY_CACHE: dict[int, tuple[float, float, dict]] = {}      # n -> (asked, ttl, payload)
_TRY_LOCKS = {q["n"]: threading.Lock() for q in TRY}
_TRY_SLOTS = threading.BoundedSemaphore(3)                  # at most 3 tool runs at once


def _ask(tool: str, args: dict) -> tuple[dict, bool]:
    """One canonical question through the partner pipeline, minus the usage
    ledger (see the module note). Returns (payload, failed)."""
    from serve import mcp_http as m
    try:
        target, targs = m.route(tool, dict(args))
        out = m.PUBLIC_TOOLS[target][0](**targs)
        out = m.add_english(target, out)
        out = m.licence.apply(target, out, "partner", m._tool_grades().get(target),
                              shown_as=tool)
        return out, False
    except Exception:                                            # noqa: BLE001
        # No exception text: a public page is not where an address or a path
        # should surface. The words are the ones the MCP transport uses.
        return {"answer": "صار خطأ بالنظام، جرّب كمان شوي.",
                "answer_en": "Something failed inside the system; try again shortly."}, True


def try_answer(n: int) -> dict:
    q = TRY[n - 1]
    with _TRY_LOCKS[n]:
        hit = _TRY_CACHE.get(n)
        now = time.time()
        if not hit or now - hit[0] >= hit[1]:
            started = time.monotonic()
            with _TRY_SLOTS:
                out, failed = _ask(q["tool"], q["arguments"])
            lic = out.get("licence") if isinstance(out, dict) else None
            payload = {
                "n": n, "tool": q["tool"], "arguments": q["arguments"],
                "question_ar": q["ar"], "question_en": q["en"],
                "answer": out.get("answer") if isinstance(out, dict) else None,
                "answer_en": out.get("answer_en") if isinstance(out, dict) else None,
                "partner_tier": (lic or {}).get("partner_tier") if isinstance(lic, dict) else None,
                "failed": failed,
                "asked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "took_ms": int((time.monotonic() - started) * 1000),
            }
            hit = (time.time(), TRY_ERROR_TTL if failed else TRY_TTL, payload)
            _TRY_CACHE[n] = hit
    asked, _ttl, payload = hit
    return {**payload, "age_seconds": int(time.time() - asked),
            "note": "asked by this server with the partner tier's pipeline; "
                    "remembered for at most two minutes"}


@router.get("/v2/try/{n}", include_in_schema=False)
def try_question(n: int) -> dict:
    """The front page's twelve questions, answered live (see the module note)."""
    if not 1 <= n <= len(TRY):
        raise HTTPException(404, f"there are {len(TRY)} questions, numbered 1–{len(TRY)}")
    return try_answer(n)


# ── content negotiation ──────────────────────────────────────────────────────
def wants_html(accept: str | None) -> bool:
    """True only when the Accept header PREFERS text/html over JSON.

    Browsers send `text/html,…,*/*;q=0.8`; curl, httpx and requests send `*/*`;
    API clients send `application/json` or nothing. `*/*` counts for the JSON,
    because the JSON is what this URL has always answered, and a tie keeps it.
    """
    if not accept:
        return False
    html_q = json_q = 0.0
    for part in accept.split(","):
        media, *params = part.strip().split(";")
        media = media.strip().lower()
        q = 1.0
        for p in params:
            k, _, v = p.strip().partition("=")
            if k.strip().lower() == "q":
                try:
                    q = float(v)
                except ValueError:
                    q = 0.0
        if media in ("text/html", "application/xhtml+xml"):
            html_q = max(html_q, q)
        elif media in ("application/json", "application/*", "*/*"):
            json_q = max(json_q, q)
    return html_q > 0 and html_q > json_q


def _headers(csp: str) -> dict[str, str]:
    return {"Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "Vary": "Accept"}


_PAGE_CACHE: dict = {"mtime": 0.0, "text": ""}


def _page_text() -> str:
    mtime = PAGE.stat().st_mtime
    if mtime != _PAGE_CACHE["mtime"]:
        _PAGE_CACHE.update(mtime=mtime, text=PAGE.read_text(encoding="utf-8"))
    return _PAGE_CACHE["text"]


def _public_key() -> tuple[str, int]:
    """The published test key, read from the key file like the 401 body and the
    consent page read it, so rotating it is one edit and this page follows.
    Empty when none is published: the page must not name a key that does not work."""
    try:
        from serve.mcp_http import _public_test_record
        hit = _public_test_record()
    except Exception:                                            # noqa: BLE001
        return "", 0
    if not hit:
        return "", 0
    key, rec = hit
    return key, int(rec.get("daily_quota") or 0)


def landing() -> HTMLResponse:
    """The page, with the published key, the public base URL and the twelve
    questions filled in. The CSP is DESIGN.md law 5 made mechanical: the page
    can fetch from its own origin and nowhere else."""
    from serve.mcp_oauth import PUBLIC_BASE
    nonce = secrets.token_urlsafe(16)
    key, quota = _public_key()
    questions = json.dumps([{k: q[k] for k in ("n", "tool", "arguments", "ar", "en")}
                            for q in TRY], ensure_ascii=False).replace("</", "<\\/")
    text = (_page_text()
            .replace("__NONCE__", nonce)
            .replace("__BASE__", html.escape(PUBLIC_BASE))
            .replace("__PUBLIC_KEY__", html.escape(key))
            .replace("__KEY_OR_PLACEHOLDER__", html.escape(key or "<your key>"))
            .replace("__PUBLIC_QUOTA__", f"{quota:,}" if quota else "")
            .replace("__TRY_JSON__", questions))
    csp = ("default-src 'none'; "
           f"script-src 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
           "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
           "form-action 'none'; frame-ancestors 'none'")
    return HTMLResponse(text, headers=_headers(csp))


# ── the partner guide ────────────────────────────────────────────────────────
_SAFE_HREF = re.compile(r"^(https?://|/|#|mailto:)", re.I)
_LIST = re.compile(r"(\s*)([*-]|\d+\.)\s+(.*)")


def _slug(text: str) -> str:
    """GitHub's anchor rule, near enough: `## 8. Attribution and licence` →
    `8-attribution-and-licence`, so a link written against the repository
    works on the served page too."""
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).replace("`", "").lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s.strip())


def _inline(text: str) -> str:
    """Code spans, links, bold, italic and the literal `<br>` the generated
    tool list uses — nothing else. Everything is escaped before any tag is made."""
    held: list[str] = []

    def hold(fragment: str) -> str:
        held.append(fragment)
        return f"{len(held) - 1}"

    t = re.sub(r"`([^`]+)`", lambda m: hold(f"<code>{html.escape(m.group(1))}</code>"), text)
    t = t.replace("<br>", hold("<br>"))

    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        if not _SAFE_HREF.match(url):
            return m.group(0)
        return hold(f'<a href="{html.escape(url, quote=True)}">{_emph(html.escape(label))}</a>')

    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
    t = re.sub(r"<((?:https?://|mailto:)[^\s<>]+)>",
               lambda m: hold(f'<a href="{html.escape(m.group(1), quote=True)}">'
                              f'{html.escape(m.group(1))}</a>'), t)

    def bare(m: re.Match) -> str:
        url = m.group(1).rstrip(".,;:")
        tail = m.group(1)[len(url):]
        return hold(f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>') + tail

    t = re.sub(r"(https?://[^\s<>()\"'`]+)", bare, t)
    t = _emph(html.escape(t, quote=False))
    for _ in range(3):                         # a held link may hold a code span
        t = re.sub(r"(\d+)", lambda m: held[int(m.group(1))], t)
    return t


def _emph(t: str) -> str:
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    # An opening star must follow a space, an opening bracket or the start, so
    # `name`*, `origin`* (the starred required arguments) never turn italic.
    return re.sub(r"(?<![^\s(])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", r"<em>\1</em>", t)


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[1:]
    if body and all(re.fullmatch(r":?-{2,}:?", c) for c in body[0]):
        body = body[1:]
    th = "".join(f"<th>{_inline(c)}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f'<div class="table"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def render_markdown(md: str) -> str:
    """The subset PARTNER-API.md uses: headings (with ids), paragraphs, fenced and
    indented code, flat lists, one table shape, blockquotes, rules. Unknown syntax
    is shown as escaped text, never interpreted."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append("<p>" + _inline(" ".join(s.strip() for s in para)) + "</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            j, buf = i + 1, []
            while j < len(lines) and not lines[j].startswith("```"):
                buf.append(lines[j])
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            i = j + 1
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        if line.startswith("    ") and not para:
            buf = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                buf.append(lines[i][4:])
                i += 1
            while buf and not buf[-1].strip():
                buf.pop()
            out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            continue
        h = re.match(r"(#{1,4})\s+(.*)", line)
        if h:
            flush()
            n, txt = len(h.group(1)), h.group(2).strip()
            out.append(f'<h{n} id="{html.escape(_slug(txt))}">{_inline(txt)}</h{n}>')
            i += 1
            continue
        if re.fullmatch(r"\s*(-{3,}|\*{3,})\s*", line):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if line.startswith(">"):
            flush()
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote><p>" + _inline(" ".join(buf)) + "</p></blockquote>")
            continue
        if line.lstrip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        lm = _LIST.fullmatch(line)
        if lm:
            flush()
            ordered = lm.group(2)[0].isdigit()
            items: list[list[str]] = []
            while i < len(lines):
                cur = lines[i]
                m2 = _LIST.fullmatch(cur)
                if m2 and m2.group(2)[0].isdigit() == ordered:
                    items.append([m2.group(3)])
                    i += 1
                elif cur.strip() and cur.startswith((" ", "\t")) and items:
                    items[-1].append(cur.strip())
                    i += 1
                elif not cur.strip():
                    nxt = _LIST.fullmatch(lines[i + 1]) if i + 1 < len(lines) else None
                    if nxt and nxt.group(2)[0].isdigit() == ordered:
                        i += 1
                        continue
                    break
                else:
                    break
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(' '.join(it))}</li>" for it in items)
                       + f"</{tag}>")
            continue
        para.append(line)
        i += 1
    flush()
    return "\n".join(out)


_DOC_PAGE = """<!doctype html>
<html lang="en" dir="ltr" class="follows-scheme">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Partner guide · {name}</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/app/tokens.css">
<style>
 *{{box-sizing:border-box}}
 body{{margin:0;background:var(--g0);color:var(--ink);font:16px/1.65 var(--font-ui);
      padding:0 16px 48px;overflow-wrap:anywhere}}
 header,main{{max-inline-size:760px;margin-inline:auto}}
 header{{padding-block:18px 6px;border-block-end:1px solid var(--hairline);font-size:14px;
        display:flex;flex-wrap:wrap;gap:6px 16px}}
 header .ar{{font-weight:700}}
 a{{color:var(--accent)}}
 h1{{font-size:26px;line-height:1.3;margin-block:22px 8px}}
 h2{{font-size:20px;margin-block:30px 8px;padding-block-start:14px;border-block-start:1px solid var(--hairline)}}
 h3{{font-size:17px;margin-block:22px 6px}}
 code,pre{{font-family:var(--font-num);font-variant-numeric:tabular-nums;font-size:.9em}}
 code{{background:var(--g1);border-radius:var(--r-s);padding:0 4px}}
 pre{{background:var(--g1);border:1px solid var(--hairline);border-radius:var(--r-m);
     padding:12px;overflow-x:auto;line-height:1.5;max-inline-size:100%}}
 pre code{{background:none;padding:0;overflow-wrap:normal}}
 blockquote{{margin:0;padding:4px 14px;border-inline-start:3px solid var(--accent);color:var(--ink-muted)}}
 .table{{overflow-x:auto;max-inline-size:100%}}
 table{{border-collapse:collapse;font-size:14.5px}}
 th,td{{border:1px solid var(--hairline);padding:6px 10px;text-align:start;vertical-align:top}}
 hr{{border:0;border-block-start:1px solid var(--hairline);margin-block:24px}}
 li{{margin-block:4px}}
</style>
</head>
<body>
<header><a class="ar" href="/" lang="ar" dir="rtl">{name_ar}</a><a href="/">{name}</a>
<a href="/docs/partner.md">this guide as Markdown</a><a href="/docs/try-twelve.sh">try-twelve.sh</a></header>
<main>
{body}
</main>
</body>
</html>"""

_DOC_CACHE: dict = {"mtime": 0.0, "html": ""}


def partner_html() -> str:
    mtime = PARTNER_DOC.stat().st_mtime
    if mtime != _DOC_CACHE["mtime"]:
        body = render_markdown(PARTNER_DOC.read_text(encoding="utf-8"))
        _DOC_CACHE.update(mtime=mtime, html=_DOC_PAGE.format(
            name=html.escape(NAME), name_ar=html.escape(NAME_AR), body=body))
    return _DOC_CACHE["html"]


_DOC_CSP = ("default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


@router.get("/docs/partner", include_in_schema=False)
def partner_guide() -> HTMLResponse:
    """docs/PARTNER-API.md, rendered. Linked from the OAuth metadata
    (`resource_documentation`) and from the front page."""
    return HTMLResponse(partner_html(), headers=_headers(_DOC_CSP))


@router.get("/docs/partner.md", include_in_schema=False)
def partner_guide_markdown() -> Response:
    return Response(PARTNER_DOC.read_text(encoding="utf-8"),
                    media_type="text/markdown; charset=utf-8",
                    headers={"X-Content-Type-Options": "nosniff"})


@router.get("/docs/try-twelve.sh", include_in_schema=False)
def try_twelve_script() -> Response:
    """The script PARTNER-API §9 tells a partner to run. text/plain so a browser
    shows it and `curl -O` saves it; it never contains a key."""
    return Response(TRY_SCRIPT.read_text(encoding="utf-8"),
                    media_type="text/plain; charset=utf-8",
                    headers={"X-Content-Type-Options": "nosniff"})


@router.get("/docs/PARTNER-API.md", include_in_schema=False)
def partner_guide_old_url() -> RedirectResponse:
    """The address the OAuth metadata published until 2026-09-25 (a 404 then)."""
    return RedirectResponse("/docs/partner", status_code=301)
