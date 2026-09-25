# Security review — the partner surface (F-84)

Scope: `https://live-api.zaidlab.xyz` as Thaura will reach it — the MCP endpoint
at `/mcp`, the public REST surface at `/v2/...`, the OAuth discovery endpoints,
and the key gate in front of them. Reviewed 2026-09-24, after F-80 (the door) and
F-81 (what may leave the building).

Every item below is either **proved** by a live probe or a test, or **accepted**
with the reason it is not worth closing now. Nothing is left implied. The
assertions that keep these claims honest live in
`tests/test_security_review.py`; run them or the note is only a document.

## 1. What an unauthenticated stranger can reach

| surface | result | proof |
|---|---|---|
| `POST /mcp` with no key | **401**, body names the published test key | live |
| `POST /mcp` with a bad key | **401** | live |
| `POST /mcp?key=` with a good key | 200 | live |
| `GET /v2/...` read routes | **200, no key** — by design | live |
| `GET /v2/usage` | **404** — local-only | live + test |
| `POST /v2/crowd/report` with `{}` | **422** | live |

**Accepted: the read API is not key-gated and never was.** The key gates `/mcp`,
which is the agent surface a partner integrates; `/v2/...` is a public read
endpoint, and gating it would break every existing browser client for no gain —
there is nothing to protect but data we intend to publish. The key buys
attribution, a quota and revocation, not exclusivity. What changed under F-81 is
not *access* but *redistribution*: the licence tier is applied per caller, and
`latest_news` / `search` return an excerpt to every external caller (§8 of
`PARTNER-API.md`).

## 2. The three host-only tools

`system_health`, `ops_digest` and `mcp_usage` describe THIS MACHINE — failing
units, feed faults, the maintenance ledger. Over stdio the caller is already on
the host; over the open internet that is infrastructure detail handed to a
stranger, answering a question nobody outside asked.

**Proved, from the open internet, with a valid key:**
* `tools/list` returns **28** tools and none of the three (`listed: false` ×3).
* Calling each by name returns **`-32601`** with the message "is not served over
  HTTP" — absent from the menu is not the same as unreachable, so the name is
  refused too.
* The REST route behind `mcp_usage`, `GET /v2/usage`, answers **404** to a
  non-local caller: the MCP hide is not bypassable through the REST layer.
* `/v2/usage` is not in the published `openapi.json` schema either.

## 3. What a hostile caller can make the server spend

Measured on the live box, single `uvicorn` worker, `q()` opens **one database
connection per query** with no pool. Warm figures, because cold is a one-time
cost and quoting it as steady state is the misleading direction.

| route | before | after |
|---|---|---|
| `/v2/databank/licenses` warm serial | 3.5–4.0 s, every call | **0.01 s** |
| `/v2/databank/licenses`, 10 concurrent | median 5.59 s, max 5.97 s | **median 0.11 s, max 0.30 s** |
| `/v2/coverage` warm serial | ~1.0 s | 0.00 s |
| four heaviest routes, 10 concurrent | — | median 0.09–0.10 s, **max 0.19 s**, all `200` |

Two defects were found and fixed rather than accepted:

- **`/v2/databank/licenses` was never cached.** Five whole-dataset aggregates
  over 206k serving rows on every call — and it is the route the `licenses` tool
  calls. Now `q_cached`, keyed on the databank sync watermark, so a nightly load
  invalidates it immediately. Warm serial 4.0 s → 0.01 s; under ten concurrent
  callers the median went 5.59 s → 0.11 s.

  **Read the cache's 60 s TTL with those numbers, or they overclaim.** The first
  call after a 60-second gap still rebuilds (measured 4.1 s through the tunnel
  after an idle minute); what changed is that everyone inside that window shares
  the answer instead of each paying for it. At the limiter's ceiling of 120
  read-requests a minute that is **one** rebuild a minute instead of 120 — which
  is the hostile-caller case the fix is for. The "before" column paid 5.5 s for
  all ten concurrent callers because all ten missed.
- **The query cache was unbounded.** Its key includes the caller's parameters,
  and a stranger controls `limit` (1..2000), `indicator` and `days`. One
  `limit=2000` entry holds **276 KB** of rows, so varying `limit` in a loop grew
  the process's memory with no ceiling — a one-line trigger on a long-lived
  single-worker process. Now an LRU bounded at `QUERY_CACHE_MAX = 400`, with a
  test that exercises the bound through HTTP, not by hand.
- **The watermark had no lock.** Every caller that found it stale ran the same
  ~380 ms `max(upper(sys_period))` aggregate at the same instant, so a burst
  multiplied the most expensive query on the cheapest path — exactly when the
  server is busiest. Now double-checked under a lock: a 12-thread barrier test
  asserts **one** read for one burst.

**Accepted: no request-level timeout or concurrency cap beyond the rate limiter.**
A single-worker server with per-query connections means ~40 Starlette worker
threads is the practical ceiling before the database's own connection limit
bites. The per-IP limiter (below) caps sustained abuse, the heavy aggregates are
now effectively free, and this box serves one partner and its own agents.
Revisit if a second partner onboards.

**Accepted: `correlate` / `what_correlates_with` are the most expensive tools
left.** A scan is `candidates` (≤120) series of points and is not cached, because
caching it keyed on the caller's window would be the unbounded-cache problem
again wearing a different hat. Bounded by `candidates ≤ 120`, by `check_comparable`
dropping series before arithmetic, and by the rate limiter. Measured 2.5 s for
`candidates=120`.

## 4. Rate limiting

`mcp` 300 per 60 s per Cloudflare client IP; `read` 120 per 60 s; localhost
exempt, so monitoring never rate-limits itself into reporting the system
unhealthy. The client IP is `CF-Connecting-IP`, trusted **only** because the API
binds `127.0.0.1` behind the tunnel, so a forged header cannot arrive from
outside. `?key=` is scrubbed from uvicorn's access record before it reaches
journald.

## 5. CORS

`allow_origins=["*"]`, methods `GET`/`POST`, headers `*`, **`allow_credentials`
absent (False)**.

**Accepted, with the condition that matters.** `*` on a public read-only API is
nearly free: there are no cookies and no auth state, so there is nothing a
browser would attach on a visitor's behalf. The dangerous pair is `*` beside
`allow_credentials=True`, which is both what browsers refuse and what would turn
this into a credentialed cross-origin surface. A test asserts credentials stay
False, so widening it has to be a deliberate act with a red build rather than a
one-word edit. `POST` is allowed because the crowd engine takes submissions from
a browser; without it a phone's report dies silently at the CORS layer while the
endpoint tests fine with curl.

## 6. The write surface

**No write path is exposed to agents.** The crowd endpoints (`/v2/crowd/register`,
`/v2/crowd/report`) exist for browsers and are reachable by anyone — a deliberate
push target, not an oversight. The structural mitigation is that every unverified
submitter shares **one** independence unit and scores `0.85 × 0.20 = 0.17`, below
every confidence floor, so a thousand registrations carry the weight of one
anonymous stranger. An agent cannot reach them at all: no MCP tool contains
`report`, `submit`, `register` or `crowd`, asserted by test.

## 7. Published by design, and known

- **`/docs`, `/redoc`, `/openapi.json` are public** (46 routes). This is a
  partner-facing API and its schema is documentation, not a secret. It does mean
  the route map is enumerable — nothing on it is sensitive, and `/v2/usage` does
  not appear in it.
- **`/health` is public but narrowed.** External callers get counts only —
  `status`, `faults_total`, `jobs_ok/jobs_total`, `feeds_ok/feeds_total`,
  `feed_age_minutes`, `fuel_states`. The `checks` block, which names each job and
  its error detail, is local-only. A status endpoint was an F-83 deliverable; the
  unauthenticated form discloses no job names, paths or messages.
- **`/v2/databank/radar` and `/v2/databank/scout` are public** (25 KB, 34 KB).
  They describe where our own record is thin — a partner-facing honesty feature,
  and thinness of coverage is not a secret worth keeping from the people being
  told not to over-trust it.

## 8. Not reviewed here

Injecting hostile content into the corpus that gets served back (a channel
writing a payload that survives into an `answer`) is a real class this note does
not close: it is about ingestion trust rather than the HTTP surface. Filed for
the next pass with the classifier work.

## 9. Residual risk, stated plainly

1. A single worker and no connection pool: a sustained 120 read-requests/min from
   one address is allowed by design, and while the heavy paths are cached, a
   caller walking uncached parameter space still holds threads and connections.
   Mitigation is the limiter and Cloudflare; revisit with a second partner or a
   second worker.
2. The read API is unauthenticated, so scraping is bounded by rate and licence
   rather than by a key. F-81's per-caller licence tier is what makes the
   distinction meaningful now.
3. Ingestion trust (§8) is unaddressed here.
