# Plan 05 · MCP transport, OAuth, rate limit, SSE, licence

Phase 2 — Security and honesty of served answers. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `serve/mcp_http.py`, `serve/mcp_oauth.py`, `serve/mcp_usage.py`, `serve/ratelimit.py`, `serve/stream.py`, `serve/licence.py`, `tests/test_mcp_http.py`, `tests/test_mcp_oauth.py`, `tests/test_ratelimit.py`, `tests/test_stream.py`, `tests/test_licence_tier.py`, `tests/test_security_review.py`, `tests/test_transport_hardening.py`
- **Tests to run after every task:** `tests/test_mcp_http.py tests/test_mcp_oauth.py tests/test_ratelimit.py tests/test_stream.py tests/test_security_review.py tests/test_transport_hardening.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Security fixes: bound JSON-RPC batch size and request body; count each batch element against limiter and quota; OAuth tokens re-check the underlying key (revocation) and its quota on every use; state files written 0600 atomically; PKCE required (S256); refresh-token rotation if small. A dropped SSE subscriber must be disconnected. Keep the published test key working. New tests in tests/test_transport_hardening.py.

- Confirmed tasks: 10 · verify-first tasks: 36 · refuted (skip): 0

## A. Confirmed tasks (independently verified — do these first, in order)

### TRANSPORT-01 · F086 · high · safety
**ZAID-10 partner tiers `filtered` and `cited_fact_only` are labels only: nothing filters databank rows or IODA payloads, and databank items carry no per-row licence**

- **Where:** `serve/licence.py:471`
- **What goes wrong:** Thaura calls `databank(category=demolitions)` over the tunnel. The payload block reads `grade: no-redistribution, partner_tier: filtered` and the rows include OCHA UN-ToU-NC rows (graded no-redistribution, DECISIONS 2026-08-08). The partner reads 'filtered' as 'what is left is fine to carry', republishes, and cannot even tell which row came from which source. The payload states a cut that did not happen — the exact 'quietly full' lie the module docstring says it exists to stop.
- **Fix:** Make /v2/databank/{category} return source_key, dataset and redistribution per row (the SELECT already joins source), then in licence.apply for DATABANK at partner tier drop rows whose redistribution is not in PARTNER_ALLOWED and record `filtered_rows: n` + reason; for MEASURED `ask` tools, strip to the figure + citation. Until enforced, do not emit `partner_tier: filtered/cited_fact_only`; emit `partner_tier: "unfiltered — see ref"`. Needs the DB route change, so full validation is on main-server.
- **Evidence (audited code):**
```
serve/licence.py:361-365 `"partner_tier": ("full" if ... else "excerpt" if emits == VERBATIM else "filtered" if emits == DATABANK else "cited_fact_only")`; the only enforcement branch is :471 `if tier == "partner" and emits == VERBATIM:`. The per-call block (:463-464) copies `partner_tier` from the table, so a `databank` reply to an external caller says `partner_tier: "filtered"` while its `items` are the full unfiltered rows; serve/app.py:2780-2785 builds those items from `("indicator", "occurred_at", ..., "attrs")` only — no source_key, dataset or redistribution per row, only a merged `attribution` list. connectivity_now says `cited_fact_only` and ships the whole IODA payload.
```
- **Verifier's check:** Could not refute. serve/licence.py:360-364 sets partner_tier 'filtered' for DATABANK and 'cited_fact_only' for non-allowed MEASURED. :463-464 copies it into every per-call block. The only enforcement branch is :471 (`tier == 'partner' and emits == VERBATIM`). mcp_http.py:448 applies it to the internal tool, and the databank tool (serve/mcp_server.py:1425-1487) passes /v2/databank/{category} items straight through. The route (serve/app.py:2764-2785) SELECTs s.attribution_text and s.license_spdx but emits per item only indicator, occurred_at, precision, value, unit, place, attrs and a merged `at …
- **Already in the release plan:** PLAN §4 R4 ('ZAID-10 ... answered but not enforced (licence.apply only trims quoted text)'; '/v2/databank/{category} drops source/dataset/licence per row') and §7 P1-B.2. DECISIONS 2026-09-23 ZAID-10. Not marked done in §11.
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-02 · F048 · high · performance
**No per-tool payload byte cap exists, and every reply is serialised twice (text + structuredContent)**

- **Where:** `serve/mcp_http.py:450`
- **What goes wrong:** databank(category="prisoners", limit=2000) or place(view=profile) returns hundreds of KB, and the wire carries it twice; a model client reads all of it on every turn. The ledger records P0-A.3 done with proof only for the licence block and series sizes.
- **Fix:** Add a per-tool byte budget (e.g. 48 KB default, declared per tool) enforced after add_english by truncating list fields with a `truncated: n` marker; emit structuredContent only for clients that negotiated ≥2025-03-26 and drop the text duplicate for them; add the test the plan names.
- **Evidence (audited code):**
```
result = {
            "content": [{"type": "text",
                         "text": json.dumps(out, ensure_ascii=False, default=str)}],
            "isError": failed,
        }
        if not failed and isinstance(out, dict):
            result["structuredContent"] = json.loads(
                json.dumps(out, ensure_ascii=False, default=str))

No size check anywhere in _handle; grep for a byte cap in tests/test_mcp_http.py, tests/test_licence_tier.py and serve/mcp_http.py finds none. databank accepts limit up to 2000 rows with attrs (app.py:2720), incidents_near limit ≤200, latest_news limit*4 up to 100 × 500 chars, about(section=fields) the whole coverage table.
```
- **Verifier's check:** Confirmed. serve/mcp_http.py:437-461 runs the tool, add_english, licence.apply (:448), then builds content[0].text = json.dumps(out) (:450-453) AND structuredContent = json.loads(json.dumps(out)) (:459-460) — the same object serialised twice on the wire. No byte check exists: grep for byte/truncat/cap across mcp_http.py, licence.py, mcp_server.py, mcp_facades.py, tests/test_mcp_http.py and tests/test_licence_tier.py finds only licence.py:471-482, which trims message text for VERBATIM tools at partner tier only, not a size budget. databank passes limit straight through (mcp_server.py:1452, sche …
- **Already in the release plan:** PLAN §7 P0-A.3 ('hard caps on payload bytes per tool with a test'); ledger §11 2026-09-24 17:05 P0-A.3 done (proof covers licence block 267–390 B and series 6 KB only); PLAN §7 P1-C.5 (nightly audit 'payload size caps', not done)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-03 · F087 · high · security
**OAuth tokens skip the per-key quota and never re-check the key: a revoked partner key keeps its tokens for 30 days and can refresh forever**

- **Where:** `serve/mcp_http.py:637`
- **What goes wrong:** A partner key is deleted from .keys/partner-keys.json after a leak. Any connector that already completed OAuth with that key keeps calling /mcp unquota'd and unrevoked; every 30 days it refreshes with a still-valid refresh token, indefinitely. Revocation 'by file edit' (docs/PARTNER-API.md:40) is false for OAuth callers, and there is no revocation endpoint.
- **Fix:** Store the key's name in the token record (already `who`), and in mcp_endpoint resolve `who` back to the current key record: refuse if the name is no longer present in `_partner_keys()`, and run `_quota_exceeded` on that record. Rotate refresh tokens: pop the used refresh token in the refresh grant, and revoke the chain when the key is gone. Add tests: token refused after key removal; refresh token single-use.
- **Evidence (audited code):**
```
serve/mcp_http.py:637-638 `elif key and oauth.valid_token(key):\n            pass                          # an OAuth token from /token, per client`; serve/mcp_oauth.py:133-137 `def valid_token(token): ... _prune(); return token in _STATE["tokens"]` never consults `_partner_keys()`; :345-349 the refresh grant `rec = _STATE["refreshes"].get(...)` → `_issue(rec["client_id"], rec["who"])` issues a NEW refresh token each time and never removes the old one, so the chain never ends. Probe: after monkeypatching `_partner_key_ok` to reject every key, `valid_token(access_token)` still returned True; the used refresh token was still in the store.
```
- **Verifier's check:** Could not refute. serve/mcp_http.py:637-638: when the presented key is not in _partner_keys() but `oauth.valid_token(key)` is true, the request passes with no quota check. serve/mcp_oauth.py:133-137 valid_token only runs _prune() and checks membership in _STATE['tokens']. It never resolves the stored `who` against the key file. The refresh grant at :345-349 looks up the refresh token, does not pop it, does not re-check the key and calls _issue(), which mints a fresh access and refresh pair (:325-334). _prune (:89) gives both stores keep=1, so refresh tokens also die at 30 days (TOKEN_TTL), and …
- **Already in the release plan:** PLAN §4 R6 ('OAuth tokens skip the daily quota and revocation') and §7 P1-C.4 ('re-check the key on every token use, mcp_oauth.py:133-137, :345-349'). Not marked done in §11.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-04 · F088 · high · security
**One POST can carry an unbounded JSON-RPC batch: quota, limiter and body size are all counted per POST**

- **Where:** `serve/mcp_http.py:643`
- **What goes wrong:** A caller with the published public-test key posts one ~100 MB body (Cloudflare's cap) holding ~600k `tools/call can_i_travel` messages. All are queued on the 16-thread MCP executor (serve/mcp_http.py:73) and each one drives a Valhalla route + corridor query through the REST API; every other MCP caller (Thaura, the connector) waits behind them for hours, and the POST is repeatable 300 times a minute because the limiter saw one request. The per-key '5,000 calls a day' promised in docs/PARTNER-API.md:27 is meaningless.
- **Fix:** In mcp_endpoint: reject bodies larger than ~256 KB (check Content-Length and len(raw)) with 413; cap batch length (e.g. 8) with -32600; charge `rl.check(ip, 'mcp')` and `_quota_exceeded` once per message of type tools/call, not per POST; consider refusing batches entirely for protocolVersion 2025-06-18 (the spec removed batching). Add a TestClient test that a 50-message batch with quota=10 is refused after 10.
- **Evidence (audited code):**
```
serve/mcp_http.py:606 `raw = await request.body()` (no size cap anywhere in serve/app.py or serve/mcp_http.py); :609-611 `batch = isinstance(payload, list); msgs = payload if batch else [payload]`; :633 `if _quota_exceeded(keys[key]):` runs once per POST; :643-644 `replies = [r for r in await asyncio.gather(*(loop.run_in_executor(_POOL, _handle, m, ip, tier) for m in msgs)) ...]`. The middleware at serve/app.py:1936-1938 charges one `mcp` hit per request. Probe (scratchpad/transport-auth-licence/probe_batch2.py): a batch of 500 `ping` messages with a key whose daily_quota=1 returned 500 replies, quota counter `{'probe': 1}`, limiter hits for the IP = 1.
```
- **Verifier's check:** Could not refute. serve/mcp_http.py:606 reads the whole body with no size cap (no max-body anywhere in serve/, and the uvicorn unit ops/systemd/palestine-v2-api.service sets no limit). :612-613 accepts a list of any length. :633 `_quota_exceeded(keys[key])` runs once per POST, and its counter goes up by exactly 1 (:514-527). The limiter middleware (serve/app.py:1937, `rl.check(ip, cls)`) and serve/ratelimit.py:check add one hit per HTTP request, allowing 300/60s for the 'mcp' class. :643-644 `asyncio.gather` then submits every message to the 16-worker _POOL (:76), and that queue has no bound. …
- **Already in the release plan:** PLAN §4 R6 ('shared test key can be exhausted in 17 min by one script') and §7 P1-C.4 (per-key limiter). Neither names the batch or body-size bypass. §11 has no P1-C.4 entry.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-05 · F078 · high · security
**JSON-RPC batches bypass the rate limiter and the per-key daily quota; request body and batch size are unbounded**

- **Where:** `serve/mcp_http.py:644`
- **What goes wrong:** With the published test key, one POST carrying a 20,000-element batch of `tools/call correlate`/`insights` runs 20,000 tool calls through the 16-thread pool against the localhost API and database while counting as 1 of 300/min and 1 quota tick; alternatively a 100 MB body (Cloudflare's limit) of pings is json.loads'ed and 10^7 futures are created — memory exhaustion of the single-worker process. The SECURITY-REVIEW §3 numbers ('one rebuild a minute at 120 read-requests') assume one call per request.
- **Fix:** Reject bodies over ~256 KB (read with a limit or check content-length), reject batches over N=10 (the 2025-06-18 protocol removed batching; -32600 for lists is acceptable), and charge the limiter and `_quota_exceeded` once per tools/call message rather than per request; keep the quota counter for the shared key per key AND per IP (plan P1-C.4).
- **Evidence (audited code):**
```
serve/mcp_http.py:606 `raw = await request.body()` (no size cap); :610-611 `batch = isinstance(payload, list); msgs = payload if batch else [payload]`; :633 `_quota_exceeded(keys[key])` is evaluated once per HTTP request; :644 `*(loop.run_in_executor(_POOL, _handle, m, ip, tier) for m in msgs)` submits every message. serve/ratelimit.py:94-118 counts one hit per HTTP request in the middleware (app.py:1929). Proved in this checkout (scratchpad/security/oauth_probe.py): a key with daily_quota=2 answered two batches of 500 pings (1,000 calls, 200 each) and only the third request got 429.
```
- **Verifier's check:** Reproduced without a DB (scratchpad verify/sec0/f45.py). With daily_quota=2, two 300-ping batches both returned 200 with 300 replies each. Only the third request got 429, and the limiter bucket held 3 hits for the IP. Code check: the body is read with no cap (mcp_http.py:606); a list payload becomes msgs (:610-611); _quota_exceeded runs once per HTTP request (:633); every message goes to the 16-thread pool (:644); ratelimit.check counts one hit per HTTP request (app.py:1929-1936). Each tools/call then calls the localhost API, which ratelimit.is_local exempts from rate limiting. A test with a p …
- **Already in the release plan:** PLAN-09-24 §4 R6 and §7 P1-C.4 cover shared-test-key exhaustion and a per-key limiter. Neither names batch amplification or the unbounded body. Not done in §11.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-06 · F301 · medium · performance
**Licence-grade refresh runs three full-table scans on the MCP request path once a minute, ahead of every tool including checkpoint_status and can_i_travel**

- **Where:** `serve/mcp_http.py:331`
- **What goes wrong:** A traveller's client calls `checkpoint_status("قلنديا")` 61 s after the last MCP call. `_handle` runs the tool (fast), then `_tool_grades()` finds the 60-s TTL expired and makes a loopback GET to /v2/licence/tools, whose `q_cached` entries are also >60 s old, so the server scans the whole state_observation hypertable, the whole claim hypertable and the whole databank before the licence block can be attached; the reply arrives seconds later (SECURITY-REVIEW measured 2.7 s for a single claim scan). This repeats every minute of activity and the scans grow with retention forever. G1 (p50 < 1.5 s) cannot be met on the first call after any quiet minute.
- **Fix:** (a) Rewrite `_group_grades` to source-level questions: `SELECT DISTINCT s.redistribution FROM source s WHERE EXISTS (SELECT 1 FROM claim c WHERE c.source_id = s.source_id)` (claim_source_idx) and a writer-maintained `source.first_observation_at` (or a `source_activity` table) for state_observation; (b) raise `_GRADES_TTL` and the licence-table cache to hours (grades change at migration time) and refresh them from a background task (the broadcaster loop already exists) so no caller pays; serve the stale table while refreshing.
- **Evidence (audited code):**
```
serve/mcp_http.py:322 `_GRADES_TTL = 60.0`; :331 `fresh = {t["tool"]: t for t in _api("/v2/licence/tools").get("tools", [])}`; :448 `out = licence.apply(target, out, tier, _tool_grades().get(target), shown_as=name)` runs synchronously inside `_handle` for every tools/call. serve/app.py:2356 `return L.table(q_cached, set(PUBLIC_TOOLS))` (q_cached TTL 60 s). serve/licence.py:236-243 `_group_grades`: `SELECT DISTINCT s.redistribution AS g FROM state_observation o JOIN source s ON s.source_id = o.source_id` (no index on state_observation.source_id; every compressed 1-day chunk decompressed), `SELECT DISTINCT s.redistribution AS g FROM claim c JOIN source s ...` (full claim scan), `SELECT DISTINC …
```
- **Verifier's check:** Confirmed call chain. _handle calls licence.apply(..., _tool_grades().get(target)) synchronously for every tools/call (mcp_http.py:448), including failed calls. _tool_grades has a 60 s TTL (:322) and on expiry does a loopback GET /v2/licence/tools (:331). That route runs L.table(q_cached, ...) (app.py:2356), and q_cached's TTL is also 60 s (app.py:83,143). The only caller of that route is this refresh (and the licence_tools tool), so by the time _GRADES expires its q_cached entries are older than 60 s and every refresh recomputes from scratch. The recomputation runs grade_tools (licence.py:311 …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-07 · F357 · medium · security
**OAuth tokens skip the daily quota and key revocation; refresh tokens are never rotated, not bound to the client, and pruned at 30 d not 90**

- **Where:** `serve/mcp_http.py:637`
- **What goes wrong:** Anyone who ever completed the consent page with the published key (or a partner's leaked key) holds a 30-day access token plus a refresh token that mints new pairs indefinitely, immune to the daily quota and to revoking the key. Revocation as documented ('a file edit, not a deploy', mcp_http.py:479-482) does not end access.
- **Fix:** On every bearer use: look up the token, then re-validate `who` against the current key file and apply `_quota_exceeded(record)`; on refresh: require the client_id to match, delete the used refresh token and issue a new one, use REFRESH_TTL in _prune; add tests for each.
- **Evidence (audited code):**
```
serve/mcp_http.py:632-638: `if key and key in keys: if _quota_exceeded(keys[key]): ...` / `elif key and oauth.valid_token(key): pass  # an OAuth token from /token, per client`. serve/mcp_oauth.py:133-137 `def valid_token(token): ... return token in _STATE["tokens"]` (never re-checks the issuing key in `who`); :345-349 refresh grant `rec = _STATE["refreshes"].get(...)` then `_issue(rec["client_id"], rec["who"])` with no client_id check and no revocation of the used refresh; :89-91 `for store, keep in ((_STATE["tokens"], 1), (_STATE["refreshes"], 1)): ... (TOKEN_TTL if keep else REFRESH_TTL)` — keep is 1 for both so REFRESH_TTL is dead code. Proved: 5 token calls at daily_quota=2 all 200; refr …
```
- **Verifier's check:** Reproduced without a DB. Five bearer calls after the key's quota was spent all returned 200. A refresh with a wrong client_id returned 200. Reusing the same refresh token returned 200. After the key was removed from the file, ?key= returned 401 but the token minted from it still returned 200. Code check: valid_token (mcp_oauth.py:133-137) only tests membership and never re-checks `who` or applies the quota, and mcp_http.py:637 skips _quota_exceeded. The refresh grant (:345-349) has no client_id check and neither deletes nor rotates the used token. _prune (:89-91) uses keep=1 for both stores, s …
- **Already in the release plan:** PLAN-09-24 §4 R6 ('OAuth tokens skip the daily quota and revocation; refresh tokens pruned at 30 d not 90') and §7 P1-C.4. Not done in §11. PLAN-09-21's 'F-80 done' ledger claims 'revocation needs no restart'; OAuth tokens contradict it.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-08 · F396 · medium · security
**_save() rewrites .keys/oauth-state.json with mode 0644 on every token issue, so the planned chmod 600 is undone at the next /token call**

- **Where:** `serve/mcp_oauth.py:77`
- **What goes wrong:** Zaid applies P1-C.4 (`chmod 600 .keys/*`). The next connector refresh calls /token → _issue → _save, and the file with every live bearer token and refresh token is world-readable again; the hermes user (or any process on the box) reads it and holds valid tokens for 30 days.
- **Fix:** Write the temp file with `os.open(tmp, O_WRONLY|O_CREAT|O_TRUNC, 0o600)` + `os.fdopen`, fsync, then replace; also set `UMask=0077` in the api unit. Add a test asserting `stat(STATE_PATH).st_mode & 0o777 == 0o600` after `_save()`.
- **Evidence (audited code):**
```
serve/mcp_oauth.py:73-78 `tmp = STATE_PATH.with_suffix(".tmp"); tmp.write_text(json.dumps(_STATE, indent=1)); tmp.replace(STATE_PATH)`. `Path.write_text` creates the temp file with 0666 & ~umask, and `replace` moves that inode over the target, so the target inherits the temp file's mode. Probe (probe_oauth.py, umask 022): mode after `_save()` = 0o644; after `chmod 600` then another `_save()` = 0o644 again. The unit runs without a UMask= line (ops/systemd/palestine-v2-api.service). The stdio MCP server runs as a different, less-privileged user by design (serve/mcp_server.py:1918 'This process runs as the HERMES user').
```
- **Verifier's check:** Could not refute the mechanism. serve/mcp_oauth.py:73-78 _save() writes `tmp = STATE_PATH.with_suffix('.tmp')` with Path.write_text, which gets 0666 & ~umask, then `tmp.replace(STATE_PATH)`, so the target takes the new inode's mode. The unit (ops/systemd/palestine-v2-api.service) sets no UMask=, and the only drop-in is onfailure.conf, so systemd's 0022 default applies. My probe (verify/tal0/oauth.py, umask 0022) found the mode after issue was 0o644; after os.chmod(0o600) followed by one refresh it was 0o644 again. _issue() calls _save() on every /token (auth code and refresh). The hermes user …
- **Already in the release plan:** PLAN §4 R6 (files world-readable with live tokens) and §7 P1-C.4 (`.keys/*` mode 600). Neither notes that _save() reverts the mode.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-09 · F359 · medium · security
**PKCE is optional and dynamic registration is open with any redirect_uri, while the consent page never shows where the code will be sent**

- **Where:** `serve/mcp_oauth.py:321`
- **What goes wrong:** Phishing: the attacker sends a partner a link to https://live-api.zaidlab.xyz/authorize?client_id=<attacker cid>&redirect_uri=https://evil.example/cb&response_type=code. The page looks like the real connector consent ('Claude is asking for read access'); the partner types their key; the code lands on evil.example and is exchanged without PKCE. The attacker now holds a token attributed to that partner (usage ledger, quota-exempt per the previous finding) and, if the partner's key is later rotated, keeps it until the token store is wiped.
- **Fix:** Require `code_challenge` with `code_challenge_method=S256` at GET and POST /authorize (400 otherwise) and refuse /token without a verifier; show the redirect host and client_id on the consent page; consider limiting /register to redirect URIs on an allowlist or at least rate-limiting it as 'register'. Add tests: missing challenge -> 400.
- **Evidence (audited code):**
```
serve/mcp_oauth.py:319-321 `def _pkce_ok(verifier, challenge): if not challenge: return True  # no challenge asked for: nothing to verify`; :195-224 /register accepts any `redirect_uris` list and a free `client_name` with no auth; :246-257 the page renders `<strong>{client}</strong> is asking for read access` and hidden fields only — the redirect_uri is not displayed. Proved: registered client_name 'Claude' with redirect https://evil.example/cb, GET /authorize showed 'Claude' and not the host, POST with the key 302'd the code to evil.example, /token issued access+refresh with no code_verifier. tests/test_mcp_oauth.py:115 only checks a WRONG verifier is refused, not that a missing challenge i …
```
- **Verifier's check:** The code facts hold. serve/mcp_oauth.py:319-321 `_pkce_ok` returns True when no challenge was stored. GET /authorize (:268-282) only rejects a non-S256 method and does not require a challenge. POST /authorize (:286-313) stores `challenge=""`. /register (:194-224) is unauthenticated and takes any redirect_uris and a free client_name. The consent page (:246) shows only the client name, never the redirect host. I reproduced it DB-free with TestClient (scratchpad/verify/test_oauth_phish.py): I registered 'Claude' with redirect https://evil.example/cb. The page names 'Claude' and shows the host now …
- **Already in the release plan:** PLAN-2026-09-24 §4 R6 ('OAuth tokens skip the daily quota and revocation … PKCE optional'); §7 P1-C.4 ('OAuth tokens honour quota + revocation … PKCE required'). Not marked done in §11. Showing the redirect host and restricting /register are not in the plan.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### TRANSPORT-10 · F402 · medium · safety
**A dropped slow SSE subscriber is never disconnected: it keeps receiving keepalives forever and believes it is live**

- **Where:** `serve/stream.py:120`
- **What goes wrong:** A phone's socket stalls (tunnel, sleep) while a mass decay flips >200 states (an ingestion outage lets hundreds of checkpoints age out at once). The queue overflows, the subscriber is dropped; when the socket resumes the client drains 200 events and then sees keepalives every 25 s — its UI shows a pulsing 'live' dot with the checkpoint states as of the drop. A later 'closed' or a decay to unknown never arrives, and the client never reconnects to get a snapshot. This is the v1 failure the module docstring says it exists to prevent, reintroduced on the overflow path.
- **Fix:** Mark the queue as dropped (e.g. a `dropped` set on the broadcaster, or try `q.put_nowait(None)` after clearing one slot) and in event_source break out of the loop — returning from the generator ends the StreamingResponse, so EventSource reconnects and gets a fresh snapshot; alternatively emit `event: reset` before closing. Extend the test to drive event_source and assert the generator finishes after the drop.
- **Evidence (audited code):**
```
serve/stream.py:113-120 `def _publish(self, event): for q in list(self._subs): try: q.put_nowait(event) except asyncio.QueueFull: ... self.unsubscribe(q)` only removes the queue from the set. The consumer at :247-257 `ev = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_SECONDS) except asyncio.TimeoutError: yield ": keepalive\n\n"; continue` has no way to learn it was dropped and never returns. Probe (probe_stream.py): after overflowing MAX_QUEUE the broadcaster reports 0 subscribers, and the same generator then yields only `: keepalive` frames indefinitely. tests/test_stream.py:133 asserts `b.subscribers == 0` but not that the connection ends.
```
- **Verifier's check:** Could not refute. serve/stream.py:113-120 on QueueFull only calls unsubscribe(q), which discards q from _subs. event_source (:247-257) keeps awaiting q.get() with a 25 s timeout and yields ': keepalive' forever. It has no dropped flag and no return, so the StreamingResponse never ends and EventSource never reconnects. The comment at :118-119 ('SSE clients reconnect on their own and get a fresh snapshot') does not hold for this path. My probe (verify/tal0/sse.py, snapshot=False) overflowed the queue with MAX_QUEUE+5 events: subscribers dropped to 0, the generator drained exactly 200 events, and …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **TRANSPORT-V01 · F347 · medium** — An ungraded source reads as `open`: _worst() ignores NULL grades, no live-source inserter sets redistribution, and the column has no default — `serve/licence.py:224`
  - scenario: A new weather or connectivity provider is added by config; its `_ensure_source` inserts a row with redistribution NULL. grade_tools appends None, _worst returns 'open', /v2/licence/tools advertises partner_tier 'full' for that tool and every payload carries grade 'open' until someone notices the pytest failure on the next full run. For group sources one NULL is masked by the others; for a single n …
  - suggested fix: Treat None as 'ask' in grade_tools (`grades.append(by_key[src]["redistribution"] or "ask")`) and in _group_grades (map NULL → 'ask' instead of filtering); add a migration `ALTER TABLE source ALTER COLUMN redistribution SET DEFAULT 'ask'` + NOT NULL after backfilling; make every inserter pass 'no-redistribution' (telegram/rss/crowd) or 'ask' explicitly. Unit-test _worst/grade_tools with a stub retu …
- **TRANSPORT-V02 · F393 · medium** — A missing source row or an empty source group grades a tool `open` / `full` — `serve/licence.py:228`
  - scenario: A source key is renamed (open_meteo → openmeteo) or the databank_internal view is empty after a failed nightly sync: /v2/licence/tools and every per-call block advertise the tool as `open` and `full` for up to 60 s of cache TTL and beyond. This is the failure test_an_unknown_tool_is_labelled_ungraded_rather_than_clean says it guards, one level down.
  - suggested fix: In grade_tools: if `unknown` is non-empty or a group returned no grades for a non-DERIVED tool, set grade `ask` and partner_tier `cited_fact_only`, and add `graded: false`/`unresolved_sources`. Add stub-q tests for the missing-source and empty-group cases.
- **TRANSPORT-V03 · F394 · medium** — Databank tools are graded per TOOL as the worst grade in the whole databank, never per payload — `serve/licence.py:353`
  - scenario: `databank(category=prices)` whose rows are all Tech4Palestine Unlicense (public domain) is labelled `grade: no-redistribution` because OCHA's UN-ToU rows exist elsewhere in the databank; a partner is told not to redistribute public-domain figures, while the same block tells them a no-redistribution set was 'filtered' when it was not (previous finding). The block can be wrong in both directions for …
  - suggested fix: Grade DATABANK payloads from the rows returned: have /v2/databank/{category} (and compare/trend) return per-row source_key + redistribution, and let licence.apply compute `grade = _worst(row grades)` and the obligations from the sources actually present; keep the table as documentation only.
- **TRANSPORT-V04 · F170 · medium** — Partner tier is labelled 'filtered' for databank tools but licence.apply cuts only verbatim text — `serve/licence.py:471`
  - scenario: A partner-key MCP call databank(category='demolitions') returns every OCHA row (ocha_demolitions: commercial_use=false, verify-required per yaml:191-192) under a licence block reading partner_tier 'filtered' and emits_note 'graded per source' — the caller reads it as 'these rows passed the filter' and redistributes them.
  - suggested fix: Either filter rows by redistribution grade for tier='partner' at the route (databank_bulk semantics) and report `dropped: n, reason`, or relabel the tier 'unfiltered-cited' and remove the docstring's per-datum claim until ZAID-10 is enforced (PLAN P1-B.2).
- **TRANSPORT-V05 · F348 · medium** — partner_tier 'filtered' for databank tools is a label: apply() cuts only VERBATIM payloads, so no-redistribution/ask rows reach partner callers in full — `serve/licence.py:471`
  - scenario: A partner key calls `databank(category=demolitions)`: OCHA UN-ToU-NC rows (redistribution='no-redistribution', 050/053) are returned in full with `licence.partner_tier: 'filtered'` and no row dropped, no count of what was withheld — the payload asserts a filter that did not run.
  - suggested fix: Implement the DATABANK branch: when tier=='partner', drop rows whose resolved redistribution ∉ PARTNER_ALLOWED, and add `licence.filtered_rows` + reason (mirroring `excerpted_items`); requires the category route to carry redistribution per row (previous finding). Test on a dev API that a partner call never returns a UN-ToU-NC row.
- **TRANSPORT-V06 · F395 · medium** — Malformed `params` (non-object) or non-string `method` crashes the whole POST with 500, including every other message in the batch — `serve/mcp_http.py:355`
  - scenario: A client bug (or a hostile caller) sends `params: []`; instead of a -32602 per message the server logs a traceback and returns a non-JSON-RPC 500; in a batch the valid messages lose their answers too.
  - suggested fix: In _handle: `if not isinstance(params, dict): return _err(rid, -32602, "params must be an object")`; `if not isinstance(method, str): return _err(rid, -32600, ...)`; wrap the executor call so an unexpected exception becomes `_err(rid, -32603, ...)` for that message only. Add tests through TestClient.
- **TRANSPORT-V07 · F382 · medium** — No test that can_i_travel answers honestly when routing is down — the MCP layer turns the 503 into a generic system error and the only live-route tests skip — `serve/mcp_http.py:437`
  - scenario: Valhalla is down for an hour; a traveller asking رام الله→نابلس gets "صار خطأ بالنظام" with no verdict word and no reason; nothing in the suite or the nightly audit asserts that the answer names routing as unavailable rather than reading as a transient glitch to retry.
  - suggested fix: Add a test that monkeypatches `serve.mcp_server.api` to raise `httpx.HTTPStatusError` with status 503 for `/v2/route*` and asserts `can_i_travel` returns `verdict='unknown'`, a `reason` naming routing, an Arabic answer containing 'ما بقدر' and never 'سالك'/'likely'; make `can_i_travel` catch that status and produce it. Runs without a database.
- **TRANSPORT-V08 · F161 · medium** — Partner keys, OAuth state and the ntfy token are hardcoded to /home/zaid paths; mcp-registration.md says the keys live 'outside the repo' — `serve/mcp_http.py:476`
  - scenario: A second checkout (the dev API CLAUDE.md describes if started from another directory, a restore under a different user, a staging box) answers 401 to every partner because `_partner_keys()` returns {} on OSError (:484-486), and OAuth starts with an empty state — silently, since both failures are caught. A partner following mcp-registration.md looks for the key file in the wrong place.
  - suggested fix: `KEYS_PATH = Path(os.environ.get("PARTNER_KEYS_PATH", Path(__file__).resolve().parent.parent / ".keys/partner-keys.json"))`, same shape for OAUTH_STATE_PATH's default; document both in .env.example; mcp-registration.md: 'in `.keys/` at the repo root, gitignored'.
- **TRANSPORT-V09 · F302 · medium** — A JSON-RPC batch counts as one rate-limited request but fans out to every MCP executor thread, so one POST per second can saturate the agent surface — `serve/mcp_http.py:643`
  - scenario: A keyed caller (the published shared test key suffices) sends one POST holding 64 `tools/call` entries for `correlate(indicator=..., candidates=120)` (2.5 s each per SECURITY-REVIEW §3); all 16 MCP threads are busy for minutes, every other agent's call queues, and the limiter has counted a single request out of 300/min.
  - suggested fix: Cap batch size (e.g. 8; reply -32600 above it) and charge each message against the `mcp` bucket; add a test posting a 20-message `ping` batch through `_handle`/TestClient expecting the cap.
- **TRANSPORT-V10 · F358 · medium** — oauth-state.json is written 0644, grows without bound from open /register, and is read-modify-written without a lock — `serve/mcp_oauth.py:77`
  - scenario: Live access and refresh tokens (30-day bearer secrets) are readable by every local user on the host, including the `admin` user that runs hermes. A script POSTing /register at the write-class rate (and more via IPv6) makes the file megabytes, and every OAuth request re-parses and rewrites it. Two concurrent /token calls race load/save: one issued token is dropped from the file and, at the next _lo …
  - suggested fix: Write with `os.open(tmp, O_WRONLY|O_CREAT|O_TRUNC, 0o600)`; hold a threading.Lock around load-mutate-save; cap clients (e.g. 500) and prune clients with no token issued in 30 days; rate-limit /register in the `register` class; test the file mode.
- **TRANSPORT-V11 · F397 · medium** — Refresh tokens are pruned at 30 days, not the documented 90: `keep` is 1 for both stores — `serve/mcp_oauth.py:89`
  - scenario: A connector idle for 31 days tries to refresh and gets invalid_grant; the user must re-run the consent flow. The doc promise is false.
  - suggested fix: `for store, ttl in ((_STATE["tokens"], TOKEN_TTL), (_STATE["refreshes"], REFRESH_TTL))` and use `ttl`; test with a 40-day-old refresh token.
- **TRANSPORT-V12 · F162 · medium** — Both partner-facing URLs advertised by the server 404 live, and the server names itself three different things — `serve/mcp_oauth.py:160`
  - scenario: A hosted client following RFC 9728 shows the user a dead documentation link; a stranger who gets the 401 and follows `x-key-request` to ask for their own key lands on a 404 — the only documented path to a non-shared key is broken. The consent page a Claude/ChatGPT user sees names a product the instructions and README do not.
  - suggested fix: Serve docs/PARTNER-API.md at /docs/PARTNER-API.md (a `FileResponse` route or StaticFiles mount) with a test that GETs it; point `x-key-request` at a page that exists (or `mailto:` per PARTNER-API §11); use the Z-4 name in `_protected_resource`, the consent page and the attribution string.
- **TRANSPORT-V13 · F398 · medium** — Open dynamic registration grows oauth-state.json without bound, and every /register and /token rewrites the whole file synchronously on the event loop — `serve/mcp_oauth.py:210`
  - scenario: One address registers 20 clients a minute for a week: ~200k entries, tens of MB. Every subsequent /token call parses and rewrites that file while the event loop is blocked, stalling the SSE stream, /health and every request for the duration; the disk fills slowly and nothing alarms.
  - suggested fix: Prune clients that have no token issued within N days; cap registrations per IP per day (a `register`-class limit like the crowd one); run _load/_save in `asyncio.to_thread`; keep only the last-N clients. Test that registrations beyond the cap are refused and clients are pruned.
- **TRANSPORT-V14 · F399 · medium** — PKCE is optional: a public client with no challenge gets a code exchangeable by anyone who intercepts the redirect — `serve/mcp_oauth.py:320`
  - scenario: A registered client omits code_challenge; the code in the 302 Location (:315) leaks via a referrer, a log, or a shared device; the interceptor posts it to /token with the public client_id and redirect_uri and obtains a 30-day token with unlimited refresh (see the revocation finding).
  - suggested fix: Require `code_challenge` (S256) at both GET and POST /authorize and refuse without it; in _pkce_ok return False when the challenge is empty. Update tests.
- **TRANSPORT-V15 · F400 · medium** — The usage ledger stores callers' exact coordinates and free-text queries beside a per-day identity hash — `serve/mcp_usage.py:65`
  - scenario: A phone calls `checkpoints(lat, lon)` or `incidents(lat, lon)` several times in a day: the ledger holds a timestamped ~1 m-precision track of one anonymised caller for that day — a location log of an individual on a machine whose files are world-readable by default (see the _save finding). PARTNER-API §7 promises 'no locations of individuals' are served; the ledger is not served but it is retained …
  - suggested fix: Round lat/lon to 2 decimals (~1 km) or bucket to the resolved place name; store `text` as a length + a hash or drop it; document the retention. Test `_args` rounding.
- **TRANSPORT-V16 · F401 · medium** — CF-Connecting-IP trust and the localhost carve-out are unconditional; `unknown` counts as local — `serve/ratelimit.py:91`
  - scenario: A future dev instance is started with `--host 0.0.0.0` on the LAN (or a docker bridge exposes the port), or `request.client` is None (UDS / a proxy that drops it → 'unknown'): any caller sends `CF-Connecting-IP: 127.0.0.1` and gets unauthenticated, unlimited, house-tier access plus the usage ledger and the fault list. docs/SECURITY-REVIEW.md §4 documents the assumption but nothing enforces it.
  - suggested fix: Honour CF-Connecting-IP only when an env flag `TRUST_CF_HEADER=1` is set (documented as 'only behind the tunnel'); treat `unknown` as NOT local; at startup assert the bound host is loopback when the flag is set (uvicorn passes it via `--host`; read from `server.config` or an env var) and refuse to start otherwise. Add a test that `is_local("unknown")` is False.
- **TRANSPORT-V17 · F360 · medium** — Per-address rate limiting is defeated by IPv6 rotation inside one /64 and by the 20k-entry eviction — `serve/ratelimit.py:102`
  - scenario: A script iterating addresses in its own /64 never sees a 429 on any class — including `register` (3/hour) and the crowd `write` class — so the 'three accounts an hour' and '20 reports a minute' defences documented in SECURITY-REVIEW §4/§6 do not exist for IPv6 clients; beyond 20,000 distinct addresses even IPv4 buckets are evicted and reset.
  - suggested fix: Normalise the key: `ipaddress.ip_network(f"{ip}/64", strict=False)` for IPv6 (/48 for register), /32 for IPv4; treat an unparseable address as one shared bucket; add a test that two addresses in one /64 share a bucket.
- **TRANSPORT-V18 · F403 · medium** — Snapshot omits every `unknown` row, so a reconnecting client never learns a decay it missed — `serve/stream.py:241`
  - scenario: A client subscribes at noon and receives Huwara=open in the snapshot; the phone sleeps at 13:00; Huwara decays to unknown at 14:00 (the state_change is never received); the client reconnects at 15:00 and the snapshot does not mention Huwara at all, so its cached 'open' survives with no server signal. The stream promises decay events (docstring, DESIGN law 1) but its recovery path cannot deliver on …
  - suggested fix: Include unknown rows in the snapshot with `value: "unknown"`, `last_known_value`, `age_minutes` (the three-state vocabulary), and add `complete: true` to the snapshot so clients drop anything not listed. Test with a fabricated _fetch.
- **TRANSPORT-V19 · F388 · medium** — Ten assertions pass vacuously when the tool answers with an error or an empty payload — measured: they were green in a run where every tool returned {"error": "Connection refused"} — `tests/test_licence_tier.py:272`
  - scenario: The partner-tier cut on `search` stops applying (or `search` starts returning full bodies) while the API is unreachable from the test host, or `search` returns zero items for the query on a quiet day: `test_search_is_cut_the_same_way_as_latest_news` passes and other people's articles are republished in full to partners.
  - suggested fix: In every such test assert first `assert "error" not in out and out.get("items") is not None, out` (or `pytest.fail` on empty) before the conditional; for facades assert `out["result"].get("isError") is not True`; for the licence-cut tests seed a message in a rolled-back transaction or use a query the fixture guarantees non-empty.
- **TRANSPORT-V20 · F389 · medium** — No test that a partner-tier databank payload omits no-redistribution rows; the licence test only checks the label 'filtered' — `tests/test_licence_tier.py:508`
  - scenario: A partner key calls `databank(category="casualties")`; OCHA rows graded `no-redistribution` (UN-ToU-NC, test_license_model.py:83-96) are returned in full under a block that says `partner_tier: filtered`; the partner republishes them.
  - suggested fix: Add a test (rolled back or against a fixture source graded `no-redistribution`) that `call("databank", tier="partner", category=X)` returns none of that source's rows and names them in `licence.refused`, while `tier="house"` returns them; then implement the filter in `licence.apply` / the route.
- **TRANSPORT-V21 · F361 · medium** — Security-review tests do not cover the write surface or the classifier's inputs, so the two worst findings cannot go red — `tests/test_security_review.py:99`
  - scenario: The review document (SECURITY-REVIEW §6 'No write path is exposed to agents') stays green while a stranger's note is served as an incident; a future pattern edit re-introduces cubic backtracking with no test to catch it.
  - suggested fix: Add: (a) tests/test_news.py ReDoS budget (read('عتد'*1400) < 0.2 s); (b) test_mcp_http batch-quota test (daily_quota=1, batch of 5 -> second request 429 or per-call refusal); (c) test_mcp_oauth: /authorize without code_challenge -> 400; (d) test_crowd (DB, rolled back): a submitted note is absent from the classifier's claim query and from /v2/news/latest; (e) test_security_review: `source.kind='cr …
- **TRANSPORT-V22 · F392 · medium** — test_the_query_cache_cannot_be_grown_without_bound reimplements the eviction it claims to test — it passes even if q_cached never evicts — `tests/test_security_review.py:121`
  - scenario: Delete lines 149-150 of serve/app.py (the `while … popitem`); this test still passes; a scraper varying `limit`/`indicator`/`days` grows `_QUERY_CACHE` without bound (276 KB per `limit=2000` entry per the docstring) until the API process is OOM-killed.
  - suggested fix: Monkeypatch `A.q` to a stub returning `[]`, clear the cache, call `A.q_cached(f"sql-{i}", (i,))` for `QUERY_CACHE_MAX + 50` distinct keys (and a cached watermark), and assert `len(A._QUERY_CACHE) == A.QUERY_CACHE_MAX` and that key 0 was evicted; this runs without a database.
- **TRANSPORT-V23 · F404 · medium** — No test exercises the HTTP endpoint's batch, size, malformed-message or dropped-subscriber behaviour; the slow-subscriber and refresh tests pass without the safety property — `tests/test_stream.py:133`
  - scenario: Each of the high findings above (batch bypass, dropped subscriber, revocation gap, 0644 state file) can regress or persist with the suite green; the tests describe the properties in their docstrings but assert weaker ones.
  - suggested fix: Add TestClient tests: batch cap and per-message quota; 413 on oversize body; -32602 for params:[]; event_source terminates after a drop; token refused after key removal; refresh token single-use; `stat(STATE_PATH).st_mode & 0o777 == 0o600`; snapshot includes unknown rows.
- **TRANSPORT-V24 · F560 · low** — A JSON-RPC message with non-object `params` or `arguments` raises inside _handle and 500s the whole request (and batch) — `serve/mcp_http.py:355`
  - scenario: A buggy or hostile client sends params as a list; instead of -32602 it gets a 500, and any well-formed messages sharing the batch lose their answers.
  - suggested fix: Validate `isinstance(params, dict)` and `isinstance(arguments, dict)` up front and return -32602; wrap the per-message dispatch in try/except returning -32603 so one message cannot fail a batch.
- **TRANSPORT-V25 · F519 · low** — Each MCP reply is serialised three to four times (text block, structuredContent round-trip, response envelope) — `serve/mcp_http.py:459`
  - scenario: `databank(category=..., limit=2000)` (≈276 KB of rows per SECURITY-REVIEW §3) costs ≈ 1 MB of JSON work and two full copies in memory per call on the 16-thread executor; multiplied by a batch, this is CPU the single process cannot spare.
  - suggested fix: Serialise once (`text = json.dumps(out, default=str)`), build `structuredContent` with one `json.loads(text)` only for clients that negotiated ≥ 2025-03-26, or return a pre-serialised `Response` so the envelope is not re-encoded.
- **TRANSPORT-V26 · F592 · low** — A broken partner-keys.json silently keeps the previous key set, so a revocation typo leaves the key valid with no alarm — `serve/mcp_http.py:490`
  - scenario: Zaid edits the file to remove a leaked key and leaves a trailing comma; the process keeps serving the leaked key until the next successful parse and nothing says so.
  - suggested fix: Log at ERROR and expose `keys_file_error` in local /health; keep the fail-open behaviour.
- **TRANSPORT-V27 · F593 · low** — The per-key daily quota lives only in process memory and is also charged for handshake messages — `serve/mcp_http.py:525`
  - scenario: A restart resets every key's count to zero mid-day, so the '5,000 a day' ceiling (docs/PARTNER-API.md:27) is per uptime segment; conversely a connector's handshake burns several units per session.
  - suggested fix: Persist counts (append to the usage ledger and derive, or a small JSON beside the keys) and charge only tools/call.
- **TRANSPORT-V28 · F594 · low** — redirect_uris are accepted with no scheme or host validation — `serve/mcp_oauth.py:203`
  - scenario: An attacker registers a client named like a real partner with an http:// or custom-scheme redirect and phishes a key holder to the consent page; the issued code (and thus a token attributed to that partner's key name) lands on the attacker's URI. Impact is bounded because the resource is public read data, but the token then bypasses quota (see above).
  - suggested fix: Require https:// (or http://localhost / 127.0.0.1 per RFC 8252), no fragment, and cap the list length; reject otherwise with invalid_redirect_uri.
- **TRANSPORT-V29 · F595 · low** — Expired authorization codes are never pruned from _CODES — `serve/mcp_oauth.py:308`
  - scenario: Anyone with the published test key posts /authorize (write class, 20/min) and never exchanges: ~28k entries a day per address accumulate in process memory until restart.
  - suggested fix: Prune `_CODES` entries older than CODE_TTL inside `_prune()` (or on each insert).
- **TRANSPORT-V30 · F596 · low** — summary() reads only the current ledger file; after a 32 MB rotation the previous window disappears silently — `serve/mcp_usage.py:131`
  - scenario: The day after a rotation, `/v2/usage?days=7` reports a near-empty week with no note that the older file exists.
  - suggested fix: Read `.ndjson.1` too when the cutoff precedes the first line of the current file, or note the truncation in the summary.
- **TRANSPORT-V31 · F597 · low** — `tools_never_used` in the usage summary is computed from internal names while the ledger records façade names, so the 19 absorbed tools read as never used forever — `serve/mcp_usage.py:203`
  - scenario: The weekly usage report (P1-C.2) lists `checkpoints_near`, `incidents_near`, `latest_news`… as never used and does not know `checkpoints`/`news` exist, so the 'acquisition roadmap' is misread.
  - suggested fix: Build the universe from `serve.mcp_facades.LISTED` (plus ABSORBED as aliases) instead of TOOLS.
- **TRANSPORT-V32 · F561 · low** — is_local() treats 'unknown' as local and trusts X-Forwarded-For whenever the Cloudflare header is absent — `serve/ratelimit.py:91`
  - scenario: Correct only while the sole path to :7870 is cloudflared. A dev instance on :7871 (CLAUDE.md), an nginx in front, or serving on a unix socket (request.client is None) makes every stranger 'local' — or lets one become local by sending `X-Forwarded-For: 127.0.0.1` — and the shared test key, the quota, the partner licence cut and the usage-ledger privacy all switch off silently.
  - suggested fix: Remove 'unknown'; consult X-Forwarded-For only when an explicit TRUSTED_PROXY setting is on; treat an absent CF header from a non-loopback socket as the socket address.
- **TRANSPORT-V33 · F521 · low** — The stream broadcaster opens two connections every 10 s forever (state_serving scan + heartbeat upsert) with zero subscribers — `serve/stream.py:186`
  - scenario: ≈17,280 connections and 8,640 heartbeat writes per day are spent maintaining a change feed nobody is connected to, out of the same 17-session budget the serving paths compete for (finding 1).
  - suggested fix: Poll only while `self._subs` is non-empty (prime on first subscribe) and beat every 60 s regardless (`beat("stream", 60, 300, {...})` stays inside the 10+300 s deadline the watchdog derives), or switch to LISTEN/NOTIFY raised by `belief.refresh`.
- **TRANSPORT-V34 · F562 · low** — SSE subscribers are unbounded and each connect runs a full state_serving scan on the shared threadpool — `serve/stream.py:222`
  - scenario: A client opens a few thousand idle SSE connections (kept alive by :251 keepalives) across an IPv6 /64: each holds a 200-slot queue and a task, and the connects run thousands of full scans on the 40-thread default pool that the sync routes also need.
  - suggested fix: Cap concurrent subscribers (e.g. 500, 503 beyond), cap per-address connections, and serve the snapshot from the broadcaster's last poll (`_last`) instead of a fresh scan.
- **TRANSPORT-V35 · F584 · low** — OAuth tests never exercise the negative PKCE case or the quota path; every authorize call sends a code_challenge — `tests/test_mcp_oauth.py:47`
  - scenario: An authorization request without PKCE is accepted; an intercepted code is exchangeable by anyone; a token-holding script exhausts the shared key's budget with no quota applied.
  - suggested fix: Add tests: `/authorize` without `code_challenge` → 400 `invalid_request`; `/token` without `code_verifier` → 400; N+1 `/mcp` calls with a bearer token → 429 at the same N as the key; refresh older than the pruning window is refused. Make them pass in serve/mcp_oauth.py.
- **TRANSPORT-V36 · F586 · low** — test_a_database_failure_does_not_kill_the_stream pins the behaviour that a dead database is indistinguishable from a quiet night for a subscriber — `tests/test_stream.py:148`
  - scenario: A phone subscribed at noon shows the noon snapshot at midnight while the DB has been unreachable for hours; the pill still reads `open` from an event received once — the v1 failure re-entering through the stream, this time as a pinned test.
  - suggested fix: Emit `event: stalled` (with `since`) after N consecutive failed polls and `event: resumed` on recovery; extend this test to assert the stalled event reaches the queue; the UI renders it as `unknown`.
