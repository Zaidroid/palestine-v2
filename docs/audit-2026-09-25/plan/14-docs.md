# Plan 14 · Documentation a partner or a new session follows

Phase 6 — Documentation and web pages. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `README.md`, `ATTRIBUTION.md`, `docs/PARTNER-API.md`, `docs/SECURITY-REVIEW.md`, `ops/systemd/README.md`, `.env.example`, `requirements.txt`, `docs/try-ten-calls.sh`, `ops/mcp-registration.md`, `ingest/sources/registry.yaml`, `docs/HANDOFF.md`, `docs/DESIGN.md`, `docs/analyst.md`, `CLAUDE.md`, `.gitignore`
- **Tests to run after every task:** `tests/test_security_review.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Every number and name must be what the code does TODAY (read the code; for counts that need the DB, say 'measured on main-server' and give the SQL instead of a number). Create requirements.txt from the real imports with the versions installed here (`pip freeze | grep -iE ...`) plus telethon and lingua-language-detector==2.2.0 (docs/analyst.md). The README install steps must run as written (compose path docker/compose.yml; migrations via db/migrate.sh). ATTRIBUTION must match the registry's licence records. You may correct factual drift in docs/HANDOFF.md §2–§8, CLAUDE.md, docs/analyst.md and docs/DESIGN.md (never change HANDOFF §1's hard rules, and never delete history — mark superseded facts). Do not edit docs/PLAN-*, docs/HANDS-* or docs/DECISIONS.md (the lead writes those; put their drift in `proposals`). ingest/sources/registry.yaml: only licence/attribution/status facts, and only where the code or DB migrations prove the current value.

- Confirmed tasks: 10 · verify-first tasks: 28 · refuted (skip): 1

- Findings located in these files belong here too (fix them through the files you may edit, or with a NEW migration in your range — never edit an applied migration): `ingest/sources/registry.yaml`, `docs/HANDOFF.md`, `docs/DESIGN.md`, `docs/analyst.md`, `CLAUDE.md`, `.gitignore`, `docs/DECISIONS.md`, `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md`, `docs/*.md`

## A. Confirmed tasks (independently verified — do these first, in order)

### DOCS-01 · F031 · high · security
**PARTNER-API promises one-revocation and 90-day refresh; OAuth tokens skip key revocation, skip quota, and refresh indefinitely**

- **Where:** `docs/PARTNER-API.md:55`
- **What goes wrong:** Zaid revokes a partner key by removing it from partner-keys.json; every connector that authorised with that key keeps calling for 30 days and forever if it refreshes before expiry. The 5,000/day shared quota applies only to header/`?key=` callers, so one OAuth connector on the public test key can run the DB-bound routes without a daily ceiling — the SECURITY-REVIEW §3 'hostile caller' case through the door it did not review.
- **Fix:** Store the key NAME in tokens (already `who`), and in `valid_token()` and the refresh grant require that `_partner_keys()` still contains a key with that name; apply `_quota_exceeded(record)` for token callers; fix `_prune` to `((tokens, TOKEN_TTL), (refreshes, REFRESH_TTL))`; rotate refresh tokens (delete the used one) so a stolen refresh dies on first legitimate use. tests/test_mcp_oauth.py exercises these flows without the database.
- **Evidence (audited code):**
```
docs/PARTNER-API.md:36-37 "One key per integration … a leak is one revocation rather than an outage"; :55 "Tokens last 30 days, refresh tokens 90". serve/mcp_oauth.py:87-93 `for store, keep in ((_STATE["tokens"], 1), (_STATE["refreshes"], 1)): … > (TOKEN_TTL if keep else REFRESH_TTL)` — `keep` is 1 for both stores, so refreshes are pruned at 30 days, REFRESH_TTL is dead; :133-137 `valid_token` = membership only, never re-reads `_partner_keys()`; :345-349 refresh grant `_issue(rec["client_id"], rec["who"])` with no key re-check and :328-336 `_issue` mints a new refresh record each time (rolling, never expires while used); serve/mcp_http.py:632-638 `if key and key in keys: … _quota_exceeded … …
```
- **Verifier's check:** Confirmed, and worse than claimed. In serve/mcp_oauth.py:89, `keep` is 1 for both stores, so REFRESH_TTL is dead. valid_token (:133-137) checks membership only and never re-checks _partner_keys(). The refresh grant (:345-349) reissues with no key check and without deleting the used refresh token. _issue (:328-336) mints a new refresh token every time. serve/mcp_http.py:632-638 applies _quota_exceeded only to header or ?key= callers; the `oauth.valid_token(key): pass` branch has no quota. Beyond the claim: token() calls _load() (:343), which reloads the state file, and _prune only ever runs in …
- **Already in the release plan:** PLAN §4 R6 :78 ('OAuth tokens skip the daily quota and revocation; refresh tokens pruned at 30 d not 90'); §7 P1-C.4 :151; no §11 line marks it done
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-02 · F084 · high · test-gap
**No test that a --rebuild preserves event ids; the stable-key path has no test at all while the ledger marks P0-C done and G3 requires it**

- **Where:** `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:227`
- **What goes wrong:** A later change to `_stable_key`'s inputs (e.g. including `name_key` after a gazetteer re-code, or the classifier version) re-mints every event id on the next `--rebuild`; `/v2/incidents/*` consumers and the databank event rows lose their references; the SQL count "0 duplicate keys" still reads clean because new keys are also unique.
- **Fix:** Add tests/test_stable_ids.py: (1) pure unit — `_stable_key(itype, place_id, name_key, first_claim_id)` is deterministic, changes with each input, and is independent of `CLASSIFIER_VERSION`; (2) DB, rolled back — insert two claims for one place, run the incremental path, record event ids, run with `--rebuild` into the same transaction, assert the set of `attrs->>'stable_key'` and event_ids is unchanged and `claim_count` equals the claims.
- **Evidence (audited code):**
```
PLAN §7 P0-C.4 (:126): "… backfill of the 4,675 current events; test that a `--rebuild` preserves ids." §6 G3 (:96): "stable event ids across rebuilds". §10 (:204): "New: … stable-id test". Ledger (:227): "P0-C · done (measured) · proof: … 4,684 events keyed, 0 duplicate keys". `grep -rn stable_key tests/` → nothing; `_stable_key` is defined at ingest/sources/news_incidents.py:163 and used at :532/:551/:590/:626 with no test importing news_incidents beyond `cluster_by_window`/`_confidence`/`DEDUP_WINDOW` (tests/test_incident_clustering.py:22-23).
```
- **Verifier's check:** Confirmed. Nothing under tests/ references stable_key. tests/test_incident_clustering.py:22-23 imports only DEDUP_WINDOW, _confidence and cluster_by_window, and :100 only greps the source. The missing test would fail today, not only after some future change. In news_incidents.py:520-640 an incremental run clusters only the claims that are new this tick (:436-441). Each new cluster's key is _stable_key(min(new claim)), so the stable_key lookup at :548-552 misses. The window fallback at :558-572 finds the older event and then overwrites attrs.stable_key with the new cluster's key (:584-593). Sep …
- **Already in the release plan:** PLAN §7 P0-C.4 (:126, 'test that a --rebuild preserves ids'); P0-C DONE WHEN (:127, 'ids survive a rebuild'); §6 G3 (:96); §10 (:204, 'stable-id test'); §11 17:05 P0-C 'done (measured)' (:227). The 18:07 and 19:12 rebuild entries prove only '0 duplicate keys'
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-03 · F146 · medium · accuracy
**ATTRIBUTION.md lists IODA and OONI as 'redistributable, commercially or otherwise'; the registry records All Rights Reserved and CC-BY-NC-SA, and nothing regenerates the file**

- **Where:** `ATTRIBUTION.md:55`
- **What goes wrong:** A partner or open-release consumer reads ATTRIBUTION.md (the file README and WITHHELD point to) and republishes IODA connectivity rows commercially with a credit line, against a publisher whose API states 'All Rights Reserved' in every response; OONI rows are used without the share-alike obligation the registry now records. The file says 'do not edit by hand' and has no regeneration hook, so it will keep saying this.
- **Fix:** Invoke `ops/gen_attribution.py` at the end of ops/databank-sync.sh (commit-free: write to the tree, the nightly job already owns that path) and make the section key `(redistribution, commercial_use)`: NC sources get a heading 'Attribution — non-commercial only', ARR/ask sources never appear under a 'redistributable' heading. Regenerate now on main-server.
- **Evidence (audited code):**
```
ATTRIBUTION.md:19-21 "## Attribution — credit required / Redistributable, commercially or otherwise, provided the credit below travels with the data."; :55-56 "**IODA (Georgia Tech) internet outage detection** — CC-BY-NC-4.0 · 1,000 rows"; :47-48 "**OONI** — free-with-attribution · 1,276 rows … CC-BY-SA"; :31 WHO "CC-BY-NC-SA-3.0-IGO" under the same heading; :146 "Generated 2026-08-08". db/migrations/067_connectivity_terms_read.sql header: "OONI … ACTUALLY CC-BY-NC-SA-4.0 … share-alike is the half that binds", "IODA … ACTUALLY All Rights Reserved … IODA's 1,000 rows leave `databank_bulk` and appear in `v_withheld`"; UPDATE sets `commercial_use = FALSE, redistribution = 'share-alike'` for OON …
```
- **Verifier's check:** Confirmed. ATTRIBUTION.md:19-21 is headed 'Redistributable, commercially or otherwise'. Under it, :31 lists WHO CC-BY-NC-SA, :47-48 OONI 'free-with-attribution', and :55-56 IODA CC-BY-NC-4.0; the file is 'Generated 2026-08-08' (:146). Migration 067 re-grades OONI to CC-BY-NC-SA-4.0 / share-alike / commercial_use FALSE and IODA to LicenseRef-IODA-All-Rights-Reserved / redistribution 'ask'. It also moves WHO from attribution to share-alike. No later migration touches these rows. ops/gen_attribution.py:29-48 picks the section heading from `redistribution` alone. Regenerating today would therefore …
- **Already in the release plan:** docs/QA-2026-09-23-partner-pass.md:112 'IODA licence conflict' (connectivity_now label vs registry, not ATTRIBUTION.md); PLAN §7 P1-B.2 honesty fixes does not name ATTRIBUTION.md; db/migrations/067 header documents the corrected terms
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-04 · F150 · medium · doc-drift
**README 'Running it' fails at every step: no requirements.txt, compose file not at the root, migration loop bypasses migrate.sh**

- **Where:** `README.md:100`
- **What goes wrong:** The repository was published on 2026-09-24 (ledger 20:04); anyone cloning it — including the cloud sessions CLAUDE.md addresses — follows README and fails on line 1, then line 3, then line 4, and the migration loop that does run leaves no `schema_migrations` rows so the guarded runner later reports every migration PENDING.
- **Fix:** Add requirements.txt (pins to be copied from main-server's `.venv/bin/pip freeze`; the set is): fastapi, uvicorn[standard], httpx, psycopg[binary], PyYAML, telethon, lingua-language-detector==2.2.0, pytest. README: `docker compose --project-directory . -f docker/compose.yml up -d db` and `db/migrate.sh` (with the note that it runs psql inside the container). Keep the pytest line but say which tests need the API/DB.
- **Evidence (audited code):**
```
README.md:100 `python -m venv .venv && .venv/bin/pip install -r requirements.txt` — `ls requirements.txt pyproject.toml setup.py setup.cfg` → none exist; docs/analyst.md:156-158 admits it and pins only `lingua-language-detector==2.2.0`. :102 `docker compose up -d db` — the only compose file is docker/compose.yml (compose: "no configuration file provided"); with `-f docker/compose.yml` the project directory becomes `docker/`, so root `.env` is not read and docker/compose.yml:15 `POSTGRES_PASSWORD: ${PGPASSWORD:?PGPASSWORD must be set in .env}` aborts. :103 `for f in db/migrations/*.sql; do psql -f "$f"; done` passes no host/port for 127.0.0.1:5433 and bypasses db/migrate.sh:8-22 (wrong-DB gua …
```
- **Verifier's check:** Confirmed. README.md:100 installs from requirements.txt, and there is no requirements.txt, pyproject.toml, setup.py or setup.cfg. README.md:102 runs `docker compose up -d db` at the root, but the only compose file is docker/compose.yml. Its :18 requires PGPASSWORD, and its volume `../data/pg` is relative to docker/. README.md:103's psql loop gives no host or port for 127.0.0.1:5433 and bypasses db/migrate.sh:11-37, which carries the .env load, the wrong-DB guard, the container exec and the schema_migrations ledger. A later `db/migrate.sh --status` would list every file PENDING. There are 79 mi …
- **Already in the release plan:** docs/analyst.md:156-158 (missing requirements.txt; lingua pinned there); PLAN §7 P1-C.7 :157 covers only the /opt/stacks/palestine dependency; README :112-117 already warns a fresh clone cannot fill its DB
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-05 · F153 · medium · doc-drift
**PARTNER-API.md teaches the retired 28-tool surface (§3, §8, §9, try-ten-calls.sh) as the integration contract**

- **Where:** `docs/PARTNER-API.md:83`
- **What goes wrong:** A partner builds against §3/§9 today: every name works (route() :322-324 passes unknown façade names through unchanged) so nothing warns them; when the alias release ends, every call returns -32602 `unknown tool`. A partner reading §3 never learns that `place`, `series`, `news`, `checkpoints`, `incidents`, `licence`, `about` exist, so the one-place-name (`place`) and default-declaring schemas P0-A built are invisible to the reader the document is for.
- **Fix:** Regenerate §3 from `listed_tools()` (name, description, inputSchema per tool), replace §8's `licence_tools` with `licence(scope=tools)`, §9 and try-ten-calls.sh with the 16 names (`about`, `checkpoints`, `checkpoint_status`, `incidents`, `insights`, `can_i_travel`, `crossings`, `weather_now`, `news`, `licence`), and add a deprecation table built from `public_name_for()` with the release in which aliases stop answering.
- **Evidence (audited code):**
```
docs/PARTNER-API.md:8 says "16 tools (since 2026-09-24; the 28 earlier names still answer as aliases for one release, off the menu)" but §3 :83-97 lists `checkpoints_near`, `checkpoints_summary`, `incidents_near`, `incidents_summary`, `place_history`, `place_pattern`, `area_history`, `trend`, `compare`, `what_correlates_with`, `data_gaps`, `licenses`, `where_is`; :137-140 `latest_news`, `search`, `stream_info`; :242 "Call **`licence_tools`** (or `GET /v2/licence/tools`)"; :255 "**`latest_news` and `search` return an excerpt**"; §9 :285-294 and docs/try-ten-calls.sh:33-38 call `coverage`, `checkpoints_summary`, `checkpoints_near`, `incidents_summary`, `incidents_near`. serve/mcp_facades.py:39 …
```
- **Verifier's check:** Confirmed. docs/PARTNER-API.md:8 says 16 tools, but §3 :83-97 and :137-140 list the absorbed names (checkpoints_near, checkpoints_summary, incidents_near, incidents_summary, place_history, place_pattern, area_history, trend, compare, what_correlates_with, data_gaps, licenses, where_is, latest_news, search, stream_info). :242 points to `licence_tools`, and §9 :285-290 plus docs/try-ten-calls.sh:33-38 call coverage, checkpoints_summary, checkpoints_near, incidents_summary and incidents_near. serve/mcp_facades.py:39-49 ABSORBED hides all of these from tools/list ('one release of aliases'). route( …
- **Already in the release plan:** PLAN §7 P0-A.1 (:107 names only PARTNER-API.md :8/:28 as text to update); §7 P2-B.2 (:165 'Docs fixed … try-ten-calls.sh → try-twelve.sh', no §11 line, still open); §4 R6 :77 (/docs/PARTNER-API.md 404)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-06 · F155 · medium · test-gap
**Ledger marks P0-A.2 (answer contract) done; tests/test_answer_contract.py does not exist and /v2/insights has no learn=false path**

- **Where:** `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:221`
- **What goes wrong:** The G1 guarantees (subject named, age present, AR/EN parity, no-source ≠ unknown ≠ refused) have no test; the exact regression class the plan measured on 09-24 (`trend` EN printing "None vs None", `checkpoint_status("Hawara")` AR doubting while EN asserted "عورتا: open") can ship again and the ledger says the guard exists. A test run of the insights path still writes `place_alias` rows into production.
- **Fix:** Either write tests/test_answer_contract.py as specified (shape assertions through `_handle` over the fixed input set from ops/mcp_accuracy_audit.py, run on main-server against the dev API) and add `learn: bool = Query(True)` to /v2/insights, or change the ledger line to `partial` naming both residues. A ledger line must quote the DONE WHEN it satisfies.
- **Evidence (audited code):**
```
docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:108 defines P0-A.2 as "New `tests/test_answer_contract.py` … For every public tool … `answer` and `answer_en` must (a) name the resolved subject, (b) contain ≥ 1 datum or one of the three refusal words … (e) name the same numbers and entities in both languages … give `/v2/insights` a `learn=false` path"; P0-A DONE WHEN (:112) "the contract test is green"; §10 :204 "New: `test_answer_contract.py`". Ledger :221 "2026-09-24 17:05 UTC · P0-A.2/A.4 · done · proof: `6f95df9`; test_headlines 16 passed." `ls tests/test_answer_contract.py` → No such file; `grep -rln answer_contract tests/` → nothing; `grep -n learn serve/app.py` → no Query parameter on /v2/insig …
```
- **Verifier's check:** Confirmed. tests/test_answer_contract.py does not exist (ls tests/; no 'answer_contract' reference in any .py). The /v2/insights handler at serve/app.py:1385-1400 takes no learn parameter and calls resolve_place(place), whose default is learn=True (resolve/geo.py:209). With learn=True, an exact hit bumps the alias hit count and commits (:262-264), and a contains or fuzzy hit also calls _observe (:326-329, :367-370). tests/test_insights.py:18 and tests/test_api.py:106 call /v2/insights with real places, so a suite run on main-server writes place_alias bumps into the production DB. Ledger :221 s …
- **Already in the release plan:** PLAN §7 P0-A.2 (:108) and DONE WHEN (:112 'the contract test is green'); §10 :204 names test_answer_contract.py; the §11 ledger :221 contradicts both
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-07 · F245 · medium · test-gap
**Ledger marks P0-A.2 'answer contract, enforced' done but tests/test_answer_contract.py does not exist and no test compares the two languages**

- **Where:** `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:221`
- **What goes wrong:** A partner reads §11, believes AR/EN parity is enforced, and ships the English answers; the next Arabic-only headline fix silently widens the gap again with the suite green.
- **Fix:** Write the test the plan specifies: for each public tool over ops/mcp_accuracy_audit.py's fixed inputs, extract numerals/ages/place names/refusal words from `answer` and `answer_en` and diff them; plus a pure-renderer half that feeds every renderer its tool's error/not-found/empty payloads and asserts no 'None' and no absence claim. Correct the ledger line to 'partial' until it is green.
- **Evidence (audited code):**
```
PLAN §7 P0-A.2 (line 108): 'New tests/test_answer_contract.py ... (e) name the same numbers and entities in both languages (diff of extracted numerals + place names)'; DONE WHEN (line 122): 'the contract test is green'. Ledger §11 line 227: '2026-09-24 17:05 UTC · P0-A.2/A.4 · done · proof: 6f95df9; test_headlines 16 passed.' `ls tests/test_answer_contract.py` -> No such file. tests/test_headlines.py is the only cross-language test and it checks a digit regex (:46, :79) or two hand-built payloads (:116-128). Every EN/AR divergence in this report (fuel dates, databank headline, alternate route, direction scope, lag, worst day, presence) is what clause (e) would have caught.
```
- **Verifier's check:** Confirmed, but the ledger line is 221, not 227. PLAN §7 P0-A.2 (line 108) specifies tests/test_answer_contract.py with clause (e) AR/EN parity; P0-A DONE WHEN (line 112) requires 'the contract test is green'. §11 line 221 records 'P0-A.2/A.4 · done · proof: 6f95df9; test_headlines 16 passed'. tests/test_answer_contract.py does not exist, no file in the repo references it, and 6f95df9 added only tests/test_headlines.py, which has 14 test functions (not 16) and checks digit presence plus two hand-built checkpoint payloads (:115-128). No test compares the numerals or entities in `answer` against …
- **Already in the release plan:** PLAN-2026-09-24 §7 P0-A.2 and DONE WHEN (line 112); §10 Tests (line 204); §11 ledger line 221 (claims done)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-08 · F379 · medium · test-gap
**Ledger marks P0-A.2 done but tests/test_answer_contract.py does not exist and the call/payload helpers were never promoted to conftest**

- **Where:** `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:221`
- **What goes wrong:** A renderer regresses so `answer_en` says "open" for a payload whose Arabic says `unknown` (the R1 divergence the plan measured: `checkpoint_status("Hawara")` AR leads with doubt, EN says open). No test compares the two languages' facts; test_headlines.py:116-128 checks two hand-built dicts only. The ledger reads as if the contract is enforced.
- **Fix:** Write tests/test_answer_contract.py as specified in §7 P0-A.2: iterate PUBLIC_TOOLS × the fixed input set from ops/mcp_accuracy_audit.py, assert the payload is not an error, then assert (a)-(e) on `answer`/`answer_en` (numerals extracted with one regex, place names from the payload's `name`/`resolved_to`). Promote `call`/`payload` to conftest.py fixtures. Until it exists, amend the §11 line to say P0-A.2's contract test is not built.
- **Evidence (audited code):**
```
PLAN §7 P0-A.2 (:108): "New `tests/test_answer_contract.py` built on the `call(name, tier, **args)`/`payload()` helpers from `tests/test_licence_tier.py:35-44` (promoted to `conftest.py`) … For every public tool … `answer` and `answer_en` must (a) name the resolved subject, (b) contain ≥ 1 datum or one of the three refusal words … (e) name the same numbers and entities in both languages". PLAN §10 (:204): "New: `test_answer_contract.py`". Ledger (:221): "2026-09-24 17:05 UTC · P0-A.2/A.4 · done · proof: `6f95df9`; test_headlines 16 passed". `ls tests/test_answer_contract.py` → no such file; conftest.py defines no `call`/`payload`; test_licence_tier.py:35-44, test_facades.py:23-29, test_headl …
```
- **Verifier's check:** Could not refute. `ls tests/test_answer_contract.py` fails and no commit ever touched that path (`git log --all -- tests/test_answer_contract.py` is empty). conftest.py defines only the usage-ledger and rate-limit fixtures. `call`/`payload` are copied in test_facades.py:23/28, test_headlines.py:26/31 and test_licence_tier.py:35/42, as the finding says. The only AR/EN checks are hand-built dicts (test_headlines.py:116-128) and one-field presence checks (test_facades.py:146/167, test_insights.py:103, test_mcp_http.py:168-169). Nothing extracts numbers or places from both answers and compares the …
- **Already in the release plan:** PLAN §7 P0-A.2 (:108) and P0-A DONE WHEN (:112, 'the contract test is green'); §9 step 2 (:195); §10 (:204, 'New: test_answer_contract.py'); §11 17:05 P0-A.2/A.4 marked done (:221)
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-09 · F159 · medium · operability
**ops/systemd/README.md install procedure enables a retired timer and never starts 10 of the 19 timers; its unit counts and F-05 section are stale**

- **Where:** `ops/systemd/README.md:26`
- **What goes wrong:** The README exists for the rebuild-after-disk-loss case it describes ("the worst moment to discover it"). Followed verbatim, the restored host runs the API, poller, checkpoints, news, external, backups and watchdog but no crowd belief refresh, no databank sync, no rollup, no Gaza bulletins, no palhub roads, no scout, no audits — and OnFailure never fires for any of them because they were never started; the watchdog would page for missing heartbeats, but the operator following this README believes the install is complete.
- **Fix:** Replace :25-30 with `for t in ops/systemd/*.timer; do sudo systemctl enable --now "$(basename "$t")"; done` plus the two daemons; delete `ops/systemd/palestine-v2-fuel.service.d/` and the F-05 section (or move it under ops/retired/); add `OnFailure=palestine-v2-alert@%n.service` to valhalla-ip; state the counts as `ls | wc -l` output with a date.
- **Evidence (audited code):**
```
ops/systemd/README.md:19 `sudo cp ops/systemd/palestine-v2-*.{service,timer} /etc/systemd/system/`; :26 `sudo systemctl enable --now palestine-v2-{checkpoints,news,fuel,external}.timer` — `palestine-v2-fuel.timer` is in ops/retired/systemd/ (docs/HANDOFF.md:48 "retired 2026-09-23"), so it is never copied and the enable line fails on that name; :25-30 never enable `crowd`, `rollup`, `databank`, `gaza`, `maintain`, `maintain-retry`, `measure-review`, `palhub-roads`, `scout`, `valhalla-ip` timers (all present in ops/systemd/); :7-8 "the twelve unit files and eight drop-ins" vs 23 services + 19 timers; :45 "`onfailure.conf` — `OnFailure=…` on every unit" vs 8 `.d` directories (one is `palestine- …
```
- **Verifier's check:** Confirmed. ops/systemd/README.md:26 enables palestine-v2-fuel.timer, which exists only in ops/retired/systemd/, so the glob copy at :19 never installs it and the enable line errors on it. ops/systemd has 23 services and 19 timers. The README enables only checkpoints, news, external, backup, restore-test, watchdog, accuracy, checkpoint-learn and mcp-audit, plus the poller and analyst daemons. It never enables crowd, databank, gaza, maintain, maintain-retry, measure-review, palhub-roads, rollup, scout or valhalla-ip (10 timers). :7-8 ('twelve unit files and eight drop-ins') and :45 ('onfailure.c …
- **Already in the release plan:** docs/DECISIONS.md 2026-09-21 F-03 (:393: install line for maintain-retry not added to the README; its drift check 'can never come back clean'); HANDOFF.md:48 retires the fuel units; not in the PLAN-2026-09-24 workstreams
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### DOCS-10 · F279 · medium · doc-drift
**The systemd README a rebuild would follow enables a retired timer and omits ten live ones; its drift check cannot come clean, skips drop-ins, and runs nowhere; HANDOFF counts are stale**

- **Where:** `ops/systemd/README.md:26`
- **What goes wrong:** A restore onto a new box follows 'Installing': `systemctl enable --now ...fuel.timer` fails on a missing unit, the operator moves on, and crowd belief, the rollup, the databank sync, Gaza MoH, palhub, the weekly measure/maintain/scout and the Valhalla sync never run; the watchdog reports them `never_reported` — if the watchdog timer was enabled, which the same list does cover.
- **Fix:** Generate the enable block from `ls ops/systemd/*.timer` (one line: `enable --now $(basename -a ops/systemd/*.timer)` plus the three daemons); fix the drift check to `for f in ops/systemd/**; diff -q $f /etc/systemd/system/${f#ops/systemd/}` including `.d/*.conf` and a reverse pass for /etc-only files; add a watchdog `dep:unit-drift` row that runs it; move the fuel drop-in to ops/retired; regenerate HANDOFF §2 numbers.
- **Evidence (audited code):**
```
ops/systemd/README.md:25-31 enables `palestine-v2-{checkpoints,news,fuel,external}.timer` (fuel retired 09-23 to ops/retired) and never mentions crowd, rollup, databank, gaza, palhub-roads, measure-review, maintain, maintain-retry, scout, valhalla-ip timers (10 of 19). :34 `diff -r <(ls /etc/...palestine-v2-*) <(ls ops/systemd/palestine-v2-*)` compares full paths (never equal; DECISIONS F-03); :35-38 loops only `.service`/`.timer`, so `/etc/.../palestine-v2-backup.service.d/memory.conf` (installed, no repo copy per F-03) is invisible; nothing scheduled runs either command. `ops/systemd/palestine-v2-fuel.service.d/onfailure.conf` is an orphan of a retired unit. docs/HANDOFF.md:55 '27 checks', …
```
- **Verifier's check:** Confirmed. ops/systemd/README.md:26 enables `palestine-v2-{checkpoints,news,fuel,external}.timer`; `palestine-v2-fuel.{service,timer}` live in ops/retired/systemd/ (ls), and only `ops/systemd/palestine-v2-fuel.service.d/onfailure.conf` remains — an orphan. ops/systemd holds 19 timers; the README's enable lines (:26-30) name 10 (one retired) and omit crowd, databank, gaza, maintain, maintain-retry, measure-review, palhub-roads, rollup, scout, valhalla-ip. :34 `diff -r <(ls /etc/...) <(ls ops/systemd/...)` diffs listings of different path prefixes (never equal; DECISIONS.md:393 F-03 says the sam …
- **Already in the release plan:** DECISIONS.md 2026-09-21 F-03 (memory.conf drift, diff command) — not in PLAN §7
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **DOCS-V01 · F145 · medium** — .env.example documents eight variables no code reads and omits FIRMS_MAP_KEY, NTFY_* and twelve others the code does read — `.env.example:10`
  - scenario: An operator fills .env from the example: the fires feed silently no-ops (ingest-external reports 7/7 steps ok — fires.py:198 prints a message and returns success), alarms are posted to a default ntfy at 127.0.0.1:8688 that a restored box does not run, `MCP_USAGE_SALT` unset means every API restart splits one caller into two in the usage ledger, and editing the V1_* paths changes nothing because no …
  - suggested fix: Delete the LLM_ and V1_*_DB blocks; add the read variables with their defaults and one line each; make the v1 path one setting (`PALESTINE_V1_ROOT`) consumed by ops/evidence.py, ingest/sources/checkpoints.py, ops/minimax_alarm.py and the rest (P1-C.7).
- **DOCS-V02 · F147 · medium** — CLAUDE.md lists test_facades.py and test_headlines.py as runnable without main-server; 7 of their 56 tests call the live API — `CLAUDE.md:21`
  - scenario: A session away from main-server follows CLAUDE.md, sees seven red tests in files it was told are pure, and either reports a false regression or edits working serving code to make them pass.
  - suggested fix: Mark the seven with `pytest.mark.skipif(not _api_up(), reason="needs PALESTINE_API")` (a 1-second `httpx.get(API + '/health')` probe in conftest), and word CLAUDE.md as 'test_facades.py and test_headlines.py except the tests marked needs_api'.
- **DOCS-V03 · F148 · medium** — README's tier sizes, category/source counts and test counts contradict the measured state and each other — `README.md:14`
  - scenario: A partner or reviewer quotes 340k rows / 101 sources from the README (the 101 is the whole `source` table incl. Telegram channels, not databank sources) and finds 206k / 25 in the API; the README's own two SQL-gate figures (66 vs 82) cannot both be right, so neither is trusted.
  - suggested fix: Generate the numbers: extend ops/gen_attribution.py (it already queries the registry) to emit a README block (rows, categories, sources feeding the databank, test count from `pytest --collect-only -q | tail -1`, gate count from `grep -c "'PASS'"`), and replace hand-typed counts with 'see ATTRIBUTION.md / /v2/databank/categories'.
- **DOCS-V04 · F149 · medium** — Missing documents: no dependency manifest, no changelog for the alias release, no fresh-clone runbook, no contributing rules — `README.md:99`
  - scenario: A partner cannot plan the alias migration (no date, no version); a new contributor (Fawwaz, a cloud session) cannot install, cannot know that `serve/` edits need a restart or that `tests/` is owned by one executor, and reads four 'start here' documents.
  - suggested fix: Add: requirements.txt (see the runbook finding); docs/CHANGELOG.md (2.1.0 — 16-name surface, aliases; 2.2.0 — aliases removed on <date>) referenced from serverInfo and PARTNER-API:8; docs/RUNBOOK-FRESH-CLONE.md (venv → .env → compose --project-directory → migrate.sh → uvicorn → the API-free test subset); CONTRIBUTING.md = HANDOFF §1 + one-pair-of-hands + ledger line format + commit trailer.
- **DOCS-V05 · F212 · medium** — Doc drift in the constitution: HANDOFF rule 3 and DECISIONS describe a StartLimitBurst=3/600s that the unit deliberately removed on 2026-08-02, and the poller docstring promises an exit 2 that cannot fire — `docs/HANDOFF.md:26`
  - scenario: A new session (or the weekly maintenance agent, which reads HANDOFF §1 as its hard rules) reasons about a restart storm from the constitution: it believes systemd will stop the poller after three failures and will run reset-failed, or believes a revoked session halts by itself, and does not check the journal for a slow infinite restart loop that is actually running.
  - suggested fix: Rewrite HANDOFF §1 rule 3 to describe the current posture (no start limit, exponential backoff to 15 min, exit 2 halts — once the exit-2 finding is fixed) and §2's channel count as 'see registry'; add a DECISIONS entry for the 08-02 reversal (the unit header holds the reasoning, DECISIONS does not); fix the poller docstring to match the code.
- **DOCS-V06 · F151 · medium** — HANDOFF.md ('read this first') carries 2026-08-01 counts, an obsolete plan pointer and a claim about the crowd endpoint the code contradicts — `docs/HANDOFF.md:44`
  - scenario: The document every new session is told to read first sends it to the superseded plan, describes a 12-unit system that is a 42-unit system, and states a security posture (no registration endpoint) that the security review says is the opposite — a reviewer reconciling the two has no way to know which is current.
  - suggested fix: Split HANDOFF into the timeless part (§1 rules, §4 traps) and a dated 'State as of' section regenerated from `ls ops/systemd/*.timer` + `grep OnCalendar|OnUnitActiveSec`, `pytest --collect-only`, and `grep -c "'PASS'"`; point §5 at PLAN-2026-09-24; delete :427 or say the endpoint exists and why (SECURITY-REVIEW §6).
- **DOCS-V07 · F378 · medium** — SQL gate counts in the docs are four different numbers (60 / 66 / 80 / 82) and none matches the 79 predicates in the tree; a session following HANDOFF §3 would misjudge a run — `docs/HANDOFF.md:107`
  - scenario: A gate errors out (its view renamed) and prints nothing; the operator compares the count to 60 or 82 from the docs, both already wrong, and cannot tell a missing PASS from a stale document; the property silently stops being checked.
  - suggested fix: Remove hand-typed counts from HANDOFF §3, README and the PLAN; have a runner (`ops/run_gates.sh`) count `THEN 'PASS`/`ELSE 'PASS` predicates per file and compare to the PASS lines it gets, printing INFO/SKIP separately; make the docs point at the runner.
- **DOCS-V08 · F152 · medium** — PARTNER-API documents PKCE S256 as part of the flow; the server issues codes and tokens without any code_challenge — `docs/PARTNER-API.md:52`
  - scenario: A registered public client that omits `code_challenge` receives a code that anyone who observes the redirect (browser history, referer, a shared device) can exchange at /token with no verifier and no client secret — the interception attack PKCE exists to stop, on a flow whose only other gate is the partner key typed on the consent page.
  - suggested fix: In `authorize_page`/`authorize_submit` refuse requests without `code_challenge` and `code_challenge_method=S256`; in `_pkce_ok` return False when the challenge is empty. Update PARTNER-API only if the behaviour is kept.
- **DOCS-V09 · F154 · medium** — DECISIONS (ZAID-10) and PARTNER-API §8 say no-redistribution databank sets are 'not part of this release'; the databank route serves every row to every caller — `docs/PARTNER-API.md:234`
  - scenario: A partner calls `databank(category=prisoners)` and receives HaMoked and Addameer rows with their `no-license-found` licence attached, having been told by both the decision record and the contract that those sets are excluded; they redistribute on the strength of the document.
  - suggested fix: Either enforce (MCP passes `tier=partner` to the databank routes; SQL filters `redistribution IN ('attribution','share-alike','open')` for that tier) or rewrite §8 and the decision to what 066 actually decided: queryable with licence attached, excluded from bulk export only.
- **DOCS-V10 · F307 · medium** — Ledger marks P0-A.2/A.4 done while three of their sub-items are absent from the code — `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:221`
  - scenario: A partner or the next session reads §11, treats the Hebrew rows, the score cap and the test-write path as closed, and the route waypoint still names 'מחסום דיר שרף', REST clients still receive 1.04, and every full test run keeps incrementing production `place_alias.hits` for 'رام الله'.
  - suggested fix: Append a §11 correction: P0-A.2/A.4 partial — list the three open sub-items; land them (learn=False at app.py:1400; a migration that merges the Hebrew rows through place_merge with a DO-NOTHING alias policy; the cap at app.py:502-508).
- **DOCS-V11 · F156 · medium** — Ledger marks P0-A.3 done while the licence block, per-call notes and payload-cap test it defines are not delivered — `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:224`
  - scenario: A reader of the ledger believes root cause R1 ("40–60 % of a typical short payload is boilerplate") is closed; the boilerplate remains on every call and no test caps payload size, so the 429 KB `compare` class of regression has no guard.
  - suggested fix: Mark the ledger line `partial` with the residue, or finish: drop `emits_note`/`note`/`graded`/`tool` from the block (keep `ref`, `grade`, `partner_tier`, `tier`, `obligations`), move `staleness_note`/`band_note`/`caveat` texts into READING_CONTRACT, and add a test asserting `len(json.dumps(payload)) < CAP[tool]` for each listed tool.
- **DOCS-V12 · F157 · medium** — Ledger marks P0-C 'done' including stable ids, but the 'a --rebuild preserves ids' test (P0-C.4, §10) does not exist — `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:227`
  - scenario: The rebuild path (ingest/sources/news_incidents.py:357-372 REBUILD_STEPS reset + re-cluster + join by key) is exercised only by hand; a change to `_stable_key` inputs or the fallback lookup can re-mint every event id on the next `--rebuild` (the 79,779→84,453 churn the fix was for) with the ledger still saying ids are stable.
  - suggested fix: On main-server, a DB-backed test: run `classify(limit=None, dry_run=False, rebuild=True)` twice inside a rolled-back transaction (the pattern test_crowd.py uses) and assert the sets of (event_id, attrs->>'stable_key') are identical; record it in the ledger as the PROVE line.
- **DOCS-V13 · F351 · medium** — SECURITY-REVIEW.md asserts 'No write path is exposed to agents' and 'nothing to protect but data we intend to publish' while agents can write aliases and strangers can publish text — `docs/SECURITY-REVIEW.md:129`
  - scenario: A partner (Thaura) reads the review as the threat model and integrates the `news`/`incidents` tools as trustworthy narrative; the next security pass starts from a document that says the agent surface is read-only.
  - suggested fix: Amend §6 and §8 to name the crowd-note -> classifier/news path and the resolver's learning as open items with owners; re-run the review after the fixes land.
- **DOCS-V14 · F214 · medium** — The source registry contract governs one fetcher (osm_fuel); the three telegram_* entries are 'planned' and unused, the RSS feeds are undeclared, and the live tier's licence/attribution/expect are hard-coded — `ingest/sources/registry.yaml:3`
  - scenario: A reader of registry.yaml or of test_ingest ('every source declares license+attribution+expect' passes) concludes the live channels are governed; they are not. The channel count cannot be read anywhere in code or config in this repository (PLAN §4 R6 already notes HANDOFF says 10 while 14 run), no expected rate exists per channel for the watchdog, and a channel can be added with no licence posture …
  - suggested fix: Move the live tier into the contract: one registry entry per polled channel (key, telegram id, kind, feeds_incidents, expected msgs/day, licence) and per RSS feed; have the poller and rss_news load their lists from it (with .env only for credentials) and refuse undeclared sources; retire the three planned telegram_* placeholders or mark them superseded. Generate the HANDOFF/PLAN channel counts fro …
- **DOCS-V15 · F450 · low** — Runtime ledgers (fetch-events, digests, measure-review) remain tracked after databank-runs.ndjson was untracked as 'runtime state' — `.gitignore:27`
  - scenario: Every nightly fetch and every Monday review dirties the working tree on main-server; a `git pull` after a cloud-session push conflicts on a ledger line, and the timer violates the one-pair-of-hands rule the ledger enforces on humans.
  - suggested fix: `git rm --cached ops/fetch-events.ndjson ops/digests.ndjson ops/measure-review.ndjson` and add them to .gitignore under the existing comment; keep ops/incident-*.ndjson, ops/incident-rounds.ndjson and ops/incident-precision.json tracked as the measurement record CLAUDE.md names.
- **DOCS-V16 · F577 · low** — pytest totals are stale in every document a new session is told to read (436 / 557 / 840 / 928 vs 964 collected) — `README.md:138`
  - scenario: A session or partner reads 557 or 436 as the expected count, sees 964 or 701, and either distrusts a good run or trusts a bad one.
  - suggested fix: Delete the numbers from README and HANDOFF §3 ("trust the run, not this paragraph" is already there — make it the only sentence), and have the ledger quote the count from the run it cites.
- **DOCS-V17 · F598 · low** — DECISIONS.md records 'T1.8 closes' while HANDOFF, PLAN-09-21 and DESIGN say the gate is open and the concept is not locked — `docs/DECISIONS.md:244`
  - scenario: A session that greps DECISIONS for T1.8 concludes Gate T1 is 8/8 and starts tier-2-only work; HANDOFF says do not start tier 2 until T1 passes.
  - suggested fix: Amend DECISIONS.md:244 with a dated note: 'T1.8's export half closed; the see-it half is the /app concept loop, open pending ZAID-2 (see 08-03 NOT LOCKED entry below)'.
- **DOCS-V18 · F451 · low** — DESIGN.md still specifies fuel-availability status chips and an unlocked 08-03 concept loop superseded by Z-1 — `docs/DESIGN.md:54`
  - scenario: Whoever builds P2-B's landing page from DESIGN.md renders a fuel-availability chip vocabulary for a feed that no longer exists and waits on a concept decision Z-1 already parked.
  - suggested fix: Replace the fuel line with the fuel-price states (`confirmed` / `awaiting_list` / `unconfirmed`, `conflicting`) and add a dated note: Z-1 — landing page first, `/app` concepts parked.
- **DOCS-V19 · F578 · low** — HANDOFF hard rule 5 ('claim is immutable except event_id') is contradicted by a recorded decision and a test that pins UPDATE claim SET lang — `docs/HANDOFF.md:26`
  - scenario: A session applying rule 5 literally reverts organ A's write (or refuses the language backfill) and the 99,376 rows return to the literal 'ar'; or, the other way, a session takes analyst.md as licence to write other columns.
  - suggested fix: Amend HANDOFF §1 rule 5 to: "never updated after insert except `event_id`, and `lang`/`attrs.lang_detector` by organ A (docs/analyst.md §Organ A)"; add a test that no other `UPDATE claim` exists outside those two files (grep-style like test_analyst.py:439-449).
- **DOCS-V20 · F443 · low** — HANDOFF §2 'What runs' predates Tier 2: no databank, gaza, maintain, scout, mcp-audit, measure-review, analyst or palhub-roads timers, and 'all twelve units' — `docs/HANDOFF.md:62`
  - scenario: A new session verifying 'everything is watched' checks twelve units and never looks at the nightly that writes the databank; HANDOFF §1's own rules point here as the constitution.
  - suggested fix: Regenerate the table from ops/systemd (a script that lists timers with OnCalendar and OnFailure), and date the section.
- **DOCS-V21 · F541 · low** — HANDOFF §3 expected SQL pass counts are stale (60 = 9/19/10/9/4/9) versus what the files can now emit (52 = 5/19/10/5/4/9) — `docs/HANDOFF.md:107`
  - scenario: A new session runs the §3 block, sees 5 and 5 where the doc promises 9 and 9, concludes eight gate checks are failing (or that the files are truncated), and spends the session chasing a regression that is documentation. Conversely a real loss of four gate2 checks would now read as 'closer to expected'.
  - suggested fix: Replace the hard-coded expectation with a script that prints per-file PASS/FAIL/INFO counts and fails on any FAIL (e.g. `grep -c '^FAIL'` must be 0 per file), and update the sentence to 'every file 0 FAIL'.
- **DOCS-V22 · F485 · low** — HANDOFF §6/§7 still quote 0.864 (round 2) as the incident classifier's precision; the round-2/3 sample files were never committed so the number cannot be reproduced — `docs/HANDOFF.md:389`
  - scenario: A new session or a partner reading HANDOFF §6 — the section titled 'Measured facts worth not re-deriving' — quotes 0.864 for a classifier three versions and two failed gates later.
  - suggested fix: Replace both lines with the round-8 numbers and a pointer to ops/incident-precision.json as the only quotable source; note that rounds 1–3 are scored files without samples and are history.
- **DOCS-V23 · F452 · low** — PARTNER-API §1 line 47 embeds a zero-width non-joiner inside the `.well-known` URL — `docs/PARTNER-API.md:47`
  - scenario: A partner copies the documented path into a client or curl and requests `/‌.well-known/oauth-protected-resource` → 404, then reports that discovery is broken.
  - suggested fix: Delete the character (`sed -i 's/\xe2\x80\x8c//' docs/PARTNER-API.md`) and add a doc-lint test that greps docs/ for U+200B–U+200F.
- **DOCS-V24 · F453 · low** — PARTNER-API quotes the round-7 precision (0.717) and calls the classifier fix 'in progress'; round 8 measured 0.767 and 1.8.1 is live — `docs/PARTNER-API.md:197`
  - scenario: A partner cites 0.717 in their own risk note while every live incident payload says round 8 / 0.767 with per-type numbers (death 0.60) — the two disagree in the direction that makes the live answer look inflated.
  - suggested fix: Remove static precision numbers from §4/§5/§10; say 'every incident payload carries `precision` (round, measured version, serving version, weak types) — quote that'.
- **DOCS-V25 · F454 · low** — PLAN §7 P0-A.1 specifies a `conditions` façade and `crossings` unchanged; the shipped set has no `conditions` and `crossings` is a façade — the ledger records 'done' without the deviation — `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:107`
  - scenario: A reader planning P1 work on 'conditions' (power is still unreachable by any listed tool; `power` has no façade or TOOLS entry) cannot tell from the ledger whether it was dropped or forgotten.
  - suggested fix: One ledger line: 'P0-A.1 deviation: `conditions` not built (weather_now/connectivity_now kept; power has no tool); `crossings` became a façade for the `place` argument.'
- **DOCS-V26 · F455 · low** — SECURITY-REVIEW.md proves 'tools/list returns 28 tools'; it returns 16 since P0-A — `docs/SECURITY-REVIEW.md:41`
  - scenario: A reviewer re-running the note's probe gets 16 and doubts the rest of the 'proved' column; the note also omits that hidden aliases are still reachable, which matters for an enumeration reader.
  - suggested fix: Update :41 to '16 listed; 19 absorbed names answer by name until <release>; the three host-only names refused (-32601)'.
- **DOCS-V27 · F590 · low** — Docs and tests still state the pre-P0-A tool counts and the wrong refresh TTL — `docs/SECURITY-REVIEW.md:41`
  - scenario: A partner or a new session reads the security review as current and expects 28 names; a connector author plans around a 90-day refresh.
  - suggested fix: Regenerate the numbers from `mcp_facades.LISTED`/`ABSORBED` and fix the TTL line once _prune is corrected.
- **DOCS-V28 · F486 · low** — docs/analyst.md shows organ C as a model organ (needs_model = True, a llama model, votes) while Z-2 wires it as the deterministic parser; test_analyst pins the registry to ['lang'] — `docs/analyst.md:103`
  - scenario: Whoever executes P2-A.1 from the analyst doc registers organ C behind the backpressure probe, so the Gaza series pauses whenever the PC is gaming although the reader needs no PC; the pinned test goes red and is 'fixed' by loosening rather than by asserting needs_model is False for 'moh'.
  - suggested fix: Rewrite the example around organ C as built (needs_model=False, model='organ_c@c/2', votes None) and change the test to assert the registry set and that every deterministic organ has needs_model False.

## C. Refuted — do not fix

- F458 Ledger says P0-C is done while two of its five numbered items are not in the code (`docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:227`) — Confirmed. docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:227 reads 'P0-C · done (measured)'. P0-C.2 for insights (see [3]) and P0-C.5 (see [4]) have no code, and no §11 line lists them as open (grep for P0-C.2/P0-C.5 in §11 finds nothing). P0-C's own DONE WHEN (:128: round 8 ≥ 0.80, named ≥ 90%) was also n …
