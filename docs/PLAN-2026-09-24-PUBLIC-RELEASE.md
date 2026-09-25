# PLAN 2026-09-24 · Palestine Data — the public release

**Canonical executor document.** Supersedes W8 of `PLAN-2026-09-21-PALESTINE-FOCUS.md` (whose §8 ledger stays as history)
and re-orders the rest of that plan under the gates below. Executor: Fable (this session) with Zaid's hands where marked
[ZAID]; Fawwaz reports against it and appends to §11 in the same ledger format. **One pair of hands per file:** while P0 is
open, nobody but the executor edits `serve/`, `resolve/`, `cascade/` or `tests/` (D-1).

Approved by Zaid 2026-09-24 (plan mode). Shareable copy: the "Palestine Data — public release plan" artifact.


Plan v1 · 2026-09-24 · Fable. Everything in §3–§4 is measured today (live MCP calls, SQL, journals, three explore reports); nothing is remembered from docs alone. Zaid's four answers (§5) are folded in.

---

## 1 · Context — what Zaid asked for, in his words

- **The goal.** One unified, accurate, automated, updated, self-learning, self-improving system for Palestine. **Tier 2** = a databank honest about Palestine under occupation since 1948, from Palestinian, Arabic and humanitarian sources that are trusted and free of propaganda, unified and categorised so an API/MCP reads it fast and accurately. **Tier 1** = the live tracker of the West Bank (Gaza later): crowd messages, news, RSS → checkpoints (location, status per direction in/out: open / closed / searching / congested…), settler attacks, demolitions, military operations, injuries, killings, arrests — analysed with correlation and logic. The tiers feed each other.
- **The end goal.** An MCP server + API layer (a chatbot later) that hands all of this to any user: accurate, transparent, fresh, fast.
- **The problem.** "Most of this is working" — but after two days on the MCP with Fawwaz it is still not presentable and cannot be shared with the public.

## 2 · What was examined (2026-09-24, 15:00–16:00 UTC)

- All **28 public MCP tools** run through the live connector as a first-time user (Ramallah→Nablus, Nablus→Jenin, قلنديا, Huwara, incidents, insights, databank, crossings, news, search, licences…).
- `docs/PLAN-2026-09-21-PALESTINE-FOCUS.md` §1–§8 incl. the whole 09-23/09-24 ledger; `docs/QA-2026-09-23-partner-pass.md`; `docs/QA-2026-09-24-agent-audit.docx` (five-round black-box audit); DECISIONS headings; README; HANDOFF §1; DESIGN.md.
- Public endpoints, systemd units/timers, `ops/mcp-usage.ndjson`, `ops/alerts.ndjson`, `ops/accuracy.ndjson`, v1's nightly refresh journal, the palhub quarantine reasoning, the source registry.
- Three read-only explore reports: Tier 2 pipeline (25 sources, 32 datasets, schema, licence views, nightly job), Tier 1 pipeline (14+16 channels, belief/decay, incidents, routing, news, health), serving layer (transports, auth, tool contract, AR/EN divergence, audits, tests, partner doc vs reality).
- **Hazard found:** another agent (`admin` = Fawwaz) was changing live state during the audit: a full incident rebuild at 15:21, `backfill_aliases --apply`, migration 075 applied while untracked, and uncommitted admin-owned edits in `resolve/corridor.py`, `serve/mcp_server.py`, `serve/mcp_en.py` (the `unverified` route verdict) that the running API (started 13:39) does not load. **Step 0 of execution is to take over or freeze that work — two hands in the same files is how the last two days were spent.**

## 3 · Verdict

The system is unusually honest and unusually hard to use. The two-day push fixed real defects (wrong-checkpoint fuzzy match, dedup, licence grading, OAuth, an audit instrument), but what still makes it unpresentable is structural:

1. **The surface is designed for honesty, not for a person with a question** — 28 overlapping tools, a licence/caveat block on every reply (355 bytes median, up to 1 KB, plus notes), headline sentences that say nothing, English answers weaker than the Arabic ones, leaks (`src:36`, Hebrew duplicate rows, settlement waypoints, satellite fire pixels counted as incidents).
2. **The two answers a traveller needs are the two still wrong**: the route verdict says "likely open" over unwatched roads with closures at the exits; a third of village incidents are pinned to the city centre; the classifier is below its own gate (0.717 vs 0.80; deaths 0.35).
3. **Coverage is thin and the lever is in quarantine**: 35 % of the 272 servable checkpoints have a current status; per-direction data is 9 % of readings; Gaza crossings have no source; the one feed that carries every checkpoint with in/out status every 15 minutes (palhub) is quarantined with no per-value diagnosis after seven weeks.
4. **Tier 2 is big but thin where the mission is**: 206 k rows, 65 % of them two datasets; the 1950s hold 5 rows; the Nakba depopulation record (1,163 events) and UCDP (7,712 events) sit in the database and are served by no route; four supply lines (OCHA casualties, OCHA demolitions, PCBS, HaMoked) have failed 31 nights; a category is mislabelled; 13 permission letters unsent.
5. **The self-learning half does not run**: organ A only; organ C built and scored but not wired; B/D/F/G unbuilt; v1's live classifier exhausts its 3,000/day budget by noon and runs on regex the rest of the day.
6. **No front door, two systems**: five names, no landing page, docs links 404, MCP behind a key, v1 still the only checkpoint parser and still running a two-hour nightly refresh that ends in failures.

None of this is fixed by another round of one-off MCP defects. The plan below is ordered so that each week ends with something a stranger can use.

## 4 · Diagnosis — six root causes, measured

### R1 · Surface: built for honesty, not for use
- Empty headlines: `databank(demolitions)` → "5 سجلاً من demolitions."; `area_history` → "تاريخ 7 يوم عبر 12 محافظة." over 6 KB; `crossings` → "استراحة أريحا: open" while Rafah/Erez/Kerem Shalom/Zikim/Kissufim are unknown or have no source and the sentence never says so; `stream_info` → "البث شغال."
- Boilerplate: every reply carries a `licence` block (`emits_note`, `obligations`, `table`…; measured median 355 bytes, up to 1,032) plus `staleness_note`/`caveat`/`source`: together 40–60 % of a typical short payload; `licence_tools` ≈ 10 KB; `compare` returns **429 KB** for two series; `coverage` (the recommended first call) 6 KB and 3 s cold from outside.
- 28 tools, six names for "a place" (`place`, `name`, `area`, `origin`, `place_id`, `indicator`), no schema declares a default, ~40 parameters undescribed, `trend.days` silently ignored, `correlate` is three tools in one, `search`/`latest_news` share one endpoint, `licenses`/`licence_tools`/`coverage`/`data_gaps`/`stream_info` overlap, `place_profile`/`place_history`/`place_pattern`/`area_history`/`insights` overlap.
- Arabic/English divergence (contract says parity): 5 tools have no `answer_en` at all; `checkpoint_status("Hawara")` AR leads with doubt, EN says "عورتا: open"; `trend(...)` EN prints "None: the last readings are flat (None vs None)"; EN weather ignores the governorate filter; EN route omits the alternate; English names "Huwara"/"Qalandiya" fail on `place_history`/`place_pattern` while Arabic works; `place_profile("Huwara")` — the tool that promises to handle town-vs-checkpoint — returns the town, 24 empty hours and no incidents.
- Leaks/noise: incident channels shown as `src:36`; Hebrew-named duplicate registry rows on Nablus→Jenin (`מחסום דיר שרף حاجز ديار شرف` + `دير شرف` at the same km); waypoints naming settlements (Ofra, Mevo Shillo, Givat harel, Homesh) to a Palestinian traveller; `fire_detection` (NASA FIRMS pixels, 0 corroboration) listed as "13 fires" beside raids; mixed-script place lists; match scores > 1.0 (1.04, 1.011); `latest_news` returns road-status tables; `search` returns five copies of the same 15-minute bulletin.
- Descriptions contradict data: `crossings` says "every crossing reads unknown"; `licenses` hard-codes 6,562; README says 340 k rows/21 categories/101 sources vs 206 k/20/25 measured.
- Connector named "Westbank Live Tracker": undersells Gaza and the databank. Two transports diverge (stdio: 31 tools, 2024-11-05 only, no instructions/licence/structuredContent/ping).

### R2 · The two answers a traveller needs
- **Route.** Live now: `can_i_travel(رام الله→نابلس)` = "likely open", 2 of 8 checkpoints reported, 26.8 km blind at the origin, three closures 1.2–2.3 km off route; Nablus→Jenin = "likely open", 1 of 6 known, 32 km unverified. Cause: `CORRIDOR_METRES=300` tube; exit checkpoints sit on junctions off it; the verdict word is the same whether 2 or 8 checkpoints are known. The router never routes around a closure, ignores `road_closure` readings and incidents, and uses OSM tiles from 2026-06-14 with no gate/permit/settler-road restrictions (v1's `restrictions.geojson` unused). The `unverified` downgrade exists only in Fawwaz's uncommitted edit (`resolve/corridor.py` `UNVERIFIED_GAP_KM`/`ENDS_KM`) and is **not live**.
- **Incidents.** 27–29 % of located incidents fall to the governorate centre (بيت عور fails while بيت عور التحتا resolves) and are counted under the city → Ramallah tops every "worst affected" list. Classifier 1.6: **0.717 [0.647–0.777] vs 0.80 gate; death 0.35**; ZAID-9 (obituary/funeral ≠ death report) decided 09-23, **not built** (`cascade/news.py` still 1.6, no funeral patterns). Bulldozing filed as demolition; gate installation as settler attack. News channels never tested for copying (`independence_group` NULL) so the 25 % multi-source share is inflated. Event ids are re-minted on every `--rebuild` (79,779–84,453 today) so nothing external can reference an event. Incidents and checkpoints are not linked anywhere in code.

### R3 · Coverage
- 272 servable checkpoints (359 rows, 86 merged): **95 (35 %) current status, 141 decayed to unknown, 36 never had a flow reading**; only 10 of 103 current statuses rest on ≥ 2 independent sources. `checkpoints_summary` reads 76/22/5 known vs 148 unknown. Jenin + Tubas: 2 tracked each.
- **Direction is essentially unused**: 13,096 flow readings are `both` vs 1,279 explicit; 4 places currently differ by direction. Zaid's stated need is in/out status.
- `ingest/sources/palhub_roads.py` parses the structured bulletin (name: دخول 🟢 | خروج 🔴, every governorate, every 15 min) at 6,058/6,060 lines and **lifted checkpoint_flow coverage from 23 % to 64 % in one pass** — then quarantined (`MODALITY="quarantined"`, migration 033) because palhub agreed with the road channels 46.7 % vs 96.8 % channel-vs-channel. Weekly re-measure prints 0.73–0.78 vs a 0.90 gate, **never broken down by value or by checkpoint**; 13.5 % of its names don't resolve; 72,763 readings in 7 days move nothing.
- 84 % of road-channel messages (6,777 of 8,046 today) match none of v1's whitelist; 17,057 candidate checkpoints pending with auto-promote off; 28,205 road bulletins never classified (organ D unbuilt).
- No source: `crossing_status`, `water`; retired: fuel availability, `cooking_gas`. Four v2 Telegram sources silent since 07-31 and two v1 road channels going quiet — nothing flags them. Crowd path: 0 submitters.

### R4 · Tier 2
- 206,157 serving rows · 20 categories · 32 datasets · 25 sources. T4P = 40 %; T4P + UNRWA aid trucks (upstream dead since 2025-01-16) = 65 %. Rows per decade: 1920s 652 · 1930s 705 · 1940s 3,466 · **1950s 5** · 1960s 114 · 1970s 187 · 1980s 754 · 1990s 2,583 · 2000s 7,312 · 2010s 27,457 · 2020s 162,922.
- Pillars: casualties **49 rows** (OCHA annual 2008→); demolitions 904 (850 undated); prisoners 910 (2008→); settlements **51** (settler population only); land 726 (mostly one date); water 75. Concepts with zero indicators: `displacement.depopulation`, `land.confiscation`, `injury`, `food.security`, `mortality.general`.
- **Held but served nowhere**: UCDP 7,712 events (1989–2024); Palestine Open Maps depopulated villages **1,163 events (1935–1967) — the Nakba record**; T4P journalists 262; B'Tselem aggregates 6; Telegram `gaza_moh_daily` 1,248 rows outside the databank (no stable id).
- Honesty defects: `pcbs` category is World Bank data relabelled (its own spec says "THIS DATA IS NOT FROM PCBS"), served under PCBS's name and marked sellable; `casualties.annual_total` (548/503) excludes the Gaza war dead and the spec's mandatory warning is not served (`attrs` = `{}`); 262 journalist events all dated 2023-10-07; `/v2/databank/{category}` drops source/dataset/licence per row so multi-source categories cannot say whose row is whose; ZAID-10 (no-redistribution sets out of partner payloads) answered but **not enforced** (`licence.apply` only trims quoted text); no per-figure "who says what"; `reliability`/`trust_weight`/`independence_group` NULL for all databank sources; accuracy measured only by the Gaza cross-check and a 6-category as_of replay.
- Supply lines: v1 steps `ocha-casualties`, `ocha-demolitions`, `pcbs-indicators`, `hamoked-detention` FAIL 31 nights (rc 1, 0 s); seven `databank-*` + `learn-corrections` + `validate` FAIL 29 nights (rc 127); v1's refresh runs 7,415 s to end there; none fails the job or pages; the radar headline still says "27 fresh of 32". Scout memory marks ACLED, Insecurity Insight, AWSD, FAO DIEM, healthsites, HDX HAPI, ReliefWeb as "adopted" though none has a dataset. 78 of 101 sources terms-unverified; 13 letters `not_asked`. A fresh clone cannot rebuild the DB (17 files read `/opt/stacks/palestine`). Cache TTL 60 s, cleared by any write to `databank-runs.ndjson` incl. dry runs → most public calls are cold (`categories` 0.9 s, `licenses` 2.3 s).

### R5 · The loop does not run
- Analyst: organ A (language) only; `analyst_run` has 42 rows, all from 09-19. Organ C built; the brain engine agrees with the deterministic reader on **196/199 gold rows** (the reader itself is human-verified on 20 rows — audit F229) offline, not registered in the loop; the `f11-night` larger-model run failed. B/D/F/G design-only; `tests/gold` holds only `moh_c.jsonl`.
- v1's live classifier on the brain gateway: 5,828 ok / 2,802 failed today, 2,566 = "budget reached" — v1's own **3,000/day cap** from the MiniMax era, hit by 12:20 UTC; regex-only for the rest of the day. The watchdog alarm is still named `minimax` and says "subscription still paid". v2 uses no model at all.
- `/health` says `ok`, 0 faults, while the watchdog holds that fault: it evaluates only job+feed checks (`serve/app.py:219-224`); minimax/valhalla/v1-db/disk families are left out; `feed_age_minutes: 1917` is the retired fuel feed.

### R6 · Front door and two systems
- Names: "Westbank Live Tracker" (MCP) · "Palestine Data Platform v2" (API root) · "Palestine data platform" (README) · "Palestine Data Observatory" (v1 :7860) · `wb-alerts.zaidlab.xyz` · `roads.zaidlab.xyz` · `live-api.zaidlab.xyz`. API root is JSON; `/app` is the unlocked concept chooser (since 08-04); `/docs/PARTNER-API.md` and `zaidlab.xyz/palestine` (the key-request URL in OAuth metadata) **404**; no public repo; the Thaura kit not handed over.
- Auth/ops leftovers: OAuth tokens skip the daily quota and revocation; refresh tokens pruned at 30 d not 90; PKCE optional; `.keys/partner-keys.json` and `oauth-state.json` world-readable on the host with live tokens; the shared test key can be exhausted in 17 min by one script; usage ledger 40 % test fixtures (`../../health`, `a/b` × 39) — purge never done; `tmp/probe_en.py` writes to the production ledger; the accuracy audit reports 0/0/0 on the day the black-box audit rated 4 tools broken (it never tests English inputs, cross-tool agreement, parity, description drift, payload size).
- v1 still the only checkpoint parser (v2 reads its SQLite every 2 min), still polls 7 news channels + 3 RSS feeds v2 never sees (safaps 571/7 d, qudsn 593, alkofiyatv 269), still fills `news.db` (15.9 k articles, 4 feeds failing) that nothing joins. Doc drift: plan says 10 poller channels (14); LOCAL-ANALYST says regex 0.897 (0.717); corridor docstring says coverage 23 % (35 %); ZAID-6 listed open though settled 08-05; `ops/mcp-registration.md` says 24 tools, no auth.

## 5 · Zaid's four decisions (2026-09-24)

| # | decision | what it fixes in the plan |
|---|---|---|
| Z-1 | **First front door = MCP + API + one landing/docs page.** Human map/app later. | P2-B builds the page; T1.8 stays parked behind ZAID-2 |
| Z-2 | **Local models: the Claude/Codex seats score the gold sets and run small nightly batches; the brain stays a fallback.** | P2-A designs the loop around bounded seat batches; full-volume organ D waits for the PSU; organ C (deterministic) wires now |
| Z-3 | **Consolidate to ~12–16 tools, old names as aliases for one release.** | P0-A (the merges below give 16: 9 new façades + 7 unchanged) |
| Z-4 | **One name: "Palestine Data — live + databank" (بيانات فلسطين).** | P0-A (serverInfo, instructions), P2-B (page), docs |

## 6 · Definition of "public-ready" — gates

| gate | measure (script or nightly audit) |
|---|---|
| **G1 answers** | The 12 canonical questions (AR + EN) each answered correctly in ≤ 2 tool calls, p50 < 1.5 s from outside; every `answer` names the resolved subject, a datum or the reason there is none (no-source ≠ unknown ≠ refused), the age of the newest datum, and what is missing; AR and EN name the same facts (parity test) |
| **G2 routes** | `open` only when corridor coverage ≥ 0.6 AND no closure/congestion within 3 km of the first/last 10 km; else `unverified` (with the blind stretch) or `blocked`; the audit's four Ramallah→Nablus cases replay green; road_closure readings and incidents near the corridor named |
| **G3 incidents** | Precision ≥ 0.80 overall, every served type ≥ 0.70 (deaths first); ≥ 80 % of NEW located incidents `place_precision=named` (73 % today; the rest is place extraction, measured weekly); governorate fallbacks never counted under a city; stable event ids across rebuilds |
| **G4 coverage** | Known-fraction ≥ 0.60 at 09:00 and 18:00 Hebron time (0.35–0.41 now), recorded in `ops_heartbeat`; ≥ 30 % of current statuses direction-resolved; Jenin + Tubas ≥ 6 tracked each |
| **G5 databank** | Each pillar (casualties, Nakba/depopulation, prisoners, demolitions, settlements+outposts, land, displacement, health/water) has ≥ 1 living source with verified terms; zero dead supply lines or each one retired with its successor named; every category answer is a sentence (latest value, span, source); every served row carries source + licence; no mislabelled category |
| **G6 front door** | One name; one page (what · status · try · connect · docs · licence · contact); MCP + REST + docs reachable from it; all links 200; v1 public surfaces link back |
| **G7 loop** | Organ C in the loop; incident gold round 8 scored; nightly seat batch running with provenance rows in `analyst_run`; nightly audit extended and paging on regressions; `/health` reports every watchdog family |

## 7 · Workstreams

Order: P0 (week 1) → P1 (weeks 2–3) → P2 (weeks 3–4) → P3 (after). Every task has DONE WHEN + PROVE; the executor appends to the ledger (§10). Files are named where the explore reports located them.

### P0-A · Surface: say less, mean more (Z-3, Z-4)
1. **Tool map 28 → 16, aliases kept.** New façades: `about` (← coverage + data_gaps + stream_info) · `licence` (← licenses + licence_tools; `scope=tools|sources`, `source=`) · `checkpoints` (← checkpoints_near + checkpoints_summary; no place = summary) · `incidents` (← incidents_near + incidents_summary) · `place` (← place_profile + place_history + place_pattern + where_is; `view=profile|history|pattern|locate`; returns BOTH the town and the checkpoint row when both exist) · `news` (← latest_news + search; `text=` optional; bulletins deduped by source+15-min window; road tables excluded unless `kind=roads`) · `conditions` (← weather_now + connectivity_now + power) · `series` (← trend + compare; the age of the last reading in the headline; `days` honoured) · `correlate` (← correlate + what_correlates_with; `indicator=` routes to the scan; refuses with the real expected-false-positive count, never "0 tests run" silently). Unchanged: `checkpoint_status`, `can_i_travel`, `insights` (+ `scope=governorates` ← area_history), `fuel_prices`, `crossings`, `databank`, `stream` folded into `about`. One parameter name for a place everywhere: `place`; every parameter described, every default declared. **Mechanism (validated):** leave `TOOLS` (`serve/mcp_server.py:1257-1540`) untouched so old names stay callable and licence/English/usage stay keyed on them; add a `FACADES` table + `route(name, args) → (internal name, args)` after `HOST_ONLY` (:1546) — each router picks the old tool from `view`/present args and drops args the target does not accept (defaults differ: `place_pattern.state_kind`, the two `hours`); stdio lists façades + unchanged + `HOST_ONLY` and calls `route()` before :1670; HTTP `_tool_list` (`mcp_http.py:302-305`) lists the same set minus `HOST_ONLY`, `route()` runs right after the argument check (:408) with the :400/:404 checks moved below it. `correlate` is both a façade and an existing key: the façade table is checked first. Text to update: `INSTRUCTIONS` (`mcp_http.py:77-95`), the prompts (:171-224), `PARTNER-API.md` :8/:28 ("28 tools"). Tests that go red by design: `tests/test_mcp_http.py:41`, `tests/test_mcp_oauth.py:111`; extend `test_licence_tier.py:298-305` to the new schemas.
2. **Answer contract, enforced.** New `tests/test_answer_contract.py` built on the `call(name, tier, **args)`/`payload()` helpers from `tests/test_licence_tier.py:35-44` (promoted to `conftest.py`; everything through `_handle` is already kept out of the production ledger by the session fixture) — the only path that adds `answer_en` (`mcp_en.add_english` :443-457). For every public tool and the fixed input set from `ops/mcp_accuracy_audit.py:448-461` (minus the stale `fuels` key): `answer` and `answer_en` must (a) name the resolved subject, (b) contain ≥ 1 datum or one of the three refusal words (no-source / unknown / refused), (c) contain an age when the payload has one, (d) name the gap when coverage < threshold, (e) name the same numbers and entities in both languages (diff of extracted numerals + place names). Shape, not values, is asserted (tools call the live API over HTTP). Prerequisite: `mcp_en.py` renderers for the 5 tools without one (place_history, place_pattern, area_history, stream_info, latest_news). Also fix the audit's own English checks (`mcp_accuracy_audit.py:340/:357/:367` read raw output and test nothing today) and give `/v2/insights` a `learn=false` path so a test run does not write `place_alias` (`app.py:1352`).
3. **Boilerplate out.** `licence` block (`serve/licence.py:473-560`, assembled :499-515; attached at `mcp_http.py:430` and, on REST, only `/v2/news/latest` `app.py:936`) collapses to `{grade, partner_tier, tier, obligations: [codes], ref}` (~90 bytes), keeping `graded:false`, `excerpted_items` and a one-line `refused` for quoted news, and obligation codes (`share-alike`, `osm-produced-work`) because the reviewer's complaint was a block that never named the obligation. `ref` needs the per-tool text somewhere readable: extend `_read_licensing` (`mcp_http.py:152-154`) or add a resource to both `RESOURCES` and `READERS` (`test_mcp_http.py:187` checks they match); REST callers get `ref: /v2/licence/tools#<tool>`. `staleness_note`/`band_note`/`caveat` move to `palestine://reading-contract` and the server `instructions` — served once, not per call; `series` attribution once per series (429 KB → < 40 KB); hard caps on payload bytes per tool with a test. Tests that go red by design: the `emits`/`emits_note`/wording assertions in `tests/test_licence_tier.py` (:200, :240, :281, :293, :312, :348-349, :361-363, :377-378, :391-396, :483-484); the field-presence ones survive.
4. **Leaks and noise.** Channel names instead of `src:N` (source key → name in `incidents`); merge the Hebrew-duplicate checkpoint rows into aliases (migration; the 86-merged mechanism exists); waypoints list Palestinian localities first and label settlements (`settlement:`) — `Corridor.passes`; `fire_detection` moves out of `by_type` into a separate `fires` field; cap match score at 1.0 and show `match` only below 0.9; consistent script in `by_place` (Arabic name + `name_en` field); `crossings` headline names what has no source; `databank` headline = latest value per indicator + span + source ("آخر رقم: 678 مبنى مهدّم في 2026 (سنة ناقصة)، OCHA؛ السلسلة 2009→2026"); `stream_info` folds into `about`.
5. **Rename.** `serverInfo.name` = "Palestine Data — live + databank"; `instructions` rewritten (what it is, the three-state vocabulary, call `about` first, AR/EN); README/PARTNER numbers regenerated from the DB, not typed.
- DONE WHEN `tools/list` shows ≤ 15 tools, every old name still answers, the contract test is green, and the 12 canonical questions pass. PROVE the test names + `docs/try-twelve.sh` output.

### P0-B · Route verdict truth (G2)
1. **Land the in-flight fix first**: Fawwaz's uncommitted `resolve/corridor.py` already does most of this — `ENDS_KM=10` (:105), `_closures_at_ends` (:405-425), near-miss SQL returning `along` (:139-154), coverage before `_score` (:527-542), a closed near-miss within 10 km of either end → `unverified` (deliberately not `blocked`; `tests/test_route_omissions.py:89-92/:126` and the in-flight `tests/test_corridor.py:162-172` pin that). Review, `chown zaid`, commit, restart `palestine-v2-api`, verify رام الله→نابلس reads `unverified` live.
2. **`exit_checkpoints` named, not merely counted**: new `Corridor` field after `near_misses` (:263) filled at :605 from `_closures_at_ends` without its 3-item cap; added to the tool output (`mcp_server.py:816`) and the per-route fields (:822-824); REST inherits. Never merged into `blocked_at`/`near_misses`.
3. **Verdict vocabulary** = `blocked | slow | open | unverified | unknown`; `open` only under G2 (coverage ≥ 0.6 and no exit closure). **The reason a route is `unverified` must be SPOKEN in both answers** — today it exists only in `Corridor.summary`, which neither renderer (`mcp_server.py:734-787`, `mcp_en.py:100-153`) uses. Headline order: verdict → what blocks/doubts it → the blind stretch → alternatives. `passes` (:559-588): Palestinian localities first, settlements labelled.
4. **Read the rest of Tier 1**: `road_closure` (same `state_serving` view, 88 rows) and recent incidents (`event`, spatial index; closure/siege/raid within 2 km and 3 h) become cautions — **filtered to `place_precision='named'`** (via `state_observation.attrs.from_event` → `event.attrs.place_precision`), because a governorate-level siege at نابلس would otherwise taint every Nablus route. v1's `restrictions.geojson` (gates, permit roads) as Valhalla avoid-locations or a post-filter.
5. **Regression set**: the audit's evidence-log cases (24 Sep 09:00 / 15:27 / 16:24 / 16:47) as fixtures in `tests/test_corridor.py` — each must not read `open`.
- DONE WHEN the four cases replay as specified and no live call says `open` below the G2 thresholds. PROVE `ops/route_coverage_measure.py` before/after + test names.

### P0-C · Incident truth (G3)
1. **Placement — the real lever is extraction, not the fallback.** Measured: of 1,260 governorate-precision events, **881 have no named place at all** (the extractor `_extract_place`, `cascade/news.py:486-542`, misses phrases like "طريق حزما - عناتا", "بين سلفيت واللبن الشرقية", خربة-suffix names); fuller-form matching alone reaches ~8 names / ~60 events (and twin villages — المزرعه, بيت عور, طوره — have no single answer). So, in order: (a) fix `_prefer` (`resolve/geo.py:97-99`) which ignores the `admin` governorate hint the classifier passes; (b) extraction: multi-place phrases, road/between patterns, خربة/عزبة/مخيم suffixes, measured on the 881; (c) the fuller-form step between `news_incidents.py:280-282` (classifier only; whole-word match inside longer aliases, restricted to the message's governorate, ≥ 4 chars, stations skipped; one candidate → `named`, several → precision `village_ambiguous` with candidates stored); (d) the join-existing-event lookup (:344-356) keyed on the named place too (43 governorate events currently merge different villages). Migration 075 (alias origins) and `ops/backfill_aliases.py` land committed.
2. **Never count a fallback under the city**: `incidents_summary`/`insights` `by_place` counts `named` only; governorate fallbacks are reported as "N incidents located only to the governorate".
3. **Classifier 1.7** (`cascade/news.py`; version constant `news_incidents.py:120` — a bump re-reads the whole corpus, :232-236, regex-cheap): the obituary/funeral gate in `read()` between :556 and :560 **applied to deaths only** (funeral words appear in 32 of 518 death claims but also in 14 raid and 11 settler-attack claims — a global reject would drop real events; تنعى/ذكرى are already rejected at :319/:324); `land_levelling` as a new type inserted above demolition (:187) taking تجريف/يجرف/تجرف with a land object (155 of 670 demolition claims are تجريف without هدم; 22 have both) — no DB change needed (`event_type`/`incident_type` are free text; only `verdict` is CHECKed); `تخطر بهدم` added to the notice-not-act reject (:252); `gate installation` → `closure`; Arabic labels at `mcp_server.py:307-310/:416-429` and `absent_types` at `app.py:1438`. Re-score round 7 → expect ≈ 0.896; then **gold round 8: 200 claims incl. 50 adversarial** scored on the Claude seat (Z-2), `ops/incident-precision-round8.json`; per-type precision beside any count below its gate (deaths first) in every incident answer.
4. **Stable event identity** (validated design): `attrs.stable_key = sha1("news|type|place_id|name_key|first_claim_id")` — the existing grouping key (:306) plus the earliest claim id (an hour bucket would flip across the boundary; the classifier KEY, never its version). Computed at :325-329, matched at :344-356, partial unique index in migration 076 (precedent: `event_v1_stable_uniq`), the rebuild's delete at :180 replaced by a reset of `claim_count`/channels (the sweep at :477-486 already removes orphaned events), backfill of the 4,675 current events; test that a `--rebuild` preserves ids.
5. **Copy detection for news channels**: run `learn/` independence fit over the incident channels (it exists for road channels: 22 of 46 pairs ≥ 98 %) so `independent_sources` stops counting mirrors.
- DONE WHEN round 8 ≥ 0.80 overall and every served type ≥ 0.70, `place_precision=named` ≥ 90 %, ids survive a rebuild. PROVE the JSON scores + SQL counts.

### P1-A · Coverage and direction (G4)
1. **Palhub earn-out by value class** (`ops/measure_review.py` + `ingest/sources/palhub_roads.py`): re-measure agreement against the channel-vs-channel control **separately for closed / open / congested and per checkpoint**, and per direction. Promote (`MODALITY="assertion"`) the classes that pass ≥ 0.90 — closed/open are the likely passers; keep congested quarantined if its threshold differs. Fix the 13.5 % unresolved names (alias backfill). Expected: known-fraction 0.35 → ≥ 0.60 and direction-resolved readings from 9 % to the majority, because the bulletin carries دخول/خروج for every row.
2. **Present `searching`**: fresh `checkpoint_inspection` presence renders as the state word تفتيش / "searching" in the checkpoint headline (presence stays a separate fact in the payload).
3. **Silent-source flags**: the watchdog's feed family gains per-source silence (4 v2 channels since 07-31, v1 road channels) — never again a source that dies unflagged.
4. **North + crossings sources** [ZAID hands]: candidate road channels for Jenin/Tubas and the crossings authority channel (الهيئة العامة للمعابر والحدود) — agent2 subscriptions are Zaid's call (scarce asset); Gaza crossings stay "no source" and the tool says who publishes it (OCHA/UNRWA situation reports) until a source is chosen.
5. **Organ D scope under Z-2**: full-volume free-text road parsing waits for the PSU; a **200-message roads gold set** is built now (seat) so D can be measured the day the GPU is back.
- DONE WHEN G4 numbers are recorded twice daily in `ops_heartbeat` and pass. PROVE the measure-review lines by class.

### P1-B · Tier 2 pillars (G5)
1. **Serve what is held** (validated path, migration 076): a view `databank_event_rows` in `observation`'s shape (`-event_id` as id, the existing `v1_stable_id`, value from `killed`/`displaced`) `UNION ALL`-ed into `databank_internal` so serving/bulk/tier/withheld views inherit it; `indicator_def` rows under `mortality.conflict` (UCDP 7,712: state_based 7,145 / one_sided 461 / non_state 106, `killed` on 7,474) and `displacement.depopulation` (Palestine Open Maps 1,163 villages 1935–1967, `displaced` on 920, 585 linked to a place); `app.py:2715` reads the union. Both datasets (176, 178) are registered under `conflict`; **there is no `displacement` category** — add a `category` row with its rule (or accept concept-only reach until then) so "the 1948 depopulated villages" is a category answer, not a concept lookup. Journalists 262 served with `occurred_precision=unknown` until real dates; `gaza_moh_daily` given a stable id. **Gate G5.11 will fail until UCDP's terms are read** (`terms_verified_at` NULL while marked commercial): a human reads the UCDP terms page and records the sentence [ZAID/F-71], or the rows serve non-commercial until then.
2. **Honesty fixes**: `pcbs` → renamed/merged into `economic` with the World Bank attribution (real PCBS = 116 rows stays `pcbs`); `casualties.annual_total` carries the spec's warning in `attrs` and in the headline ("excludes the Gaza war dead"); per-row `source`, `dataset`, `licence` in `{category}` payloads; ZAID-10 enforced at the route for partner callers (`serve/licence.py` :39-43 promise → real filter); `/v2/databank/flow` reference fixed; unknown category → 404; the 3 OCHA demolition indicators get definitions; scout verdicts corrected (7 "adopted" sources that never landed).
3. **Supply lines**: v2 takes over the four dead v1 fetches — OCHA casualties + demolitions (ochaopt.org data pages; frozen fallback kept), PCBS direct (exists: `pcbs_direct`), HaMoked (site scrape or declared dead with Addameer as successor); the seven `databank-*` + `learn-corrections` + `validate` steps are **retired from v1's `refresh-data.sh`** [ZAID hand — v1 is live; copy-paste block]. Gap radar: a dead supply line FAILS the nightly job and pages; headline counts failures.
4. **The 1948 spine** (new sources, open licences first): UNRWA registered refugees series (HDX, CC-BY-IGO — already scouted), World Population Prospects 1950s demographics (filed candidate), B'Tselem fatalities (letter), Prisoners' Society / Detainees Commission (Arabic, letter), OCHA closures & barriers history (HDX, held as one date → time series), Peace Now outposts (letter). Each lands as a reviewed mapping spec in `db/mappings/`.
5. **Letters and terms** [ZAID hands]: send the 13 drafted permission letters; F-71 five-a-week terms reads continue; IMF flip or quarantine.
6. **Cache**: databank aggregates keyed on the sync watermark only (dry runs must not clear it) so public calls are warm; `categories` < 100 ms p50 from outside.
- DONE WHEN G5 holds and README/PARTNER numbers are generated. PROVE SQL counts per pillar + `data_gaps` with zero unflagged dead steps.

### P1-C · Operability and trust
1. `/health` evaluates every watchdog family (`ops/watchdog.py:784-786` list) and drops the retired `feed_age_minutes`; a maintenance field for the 99 % carve-out.
2. Usage ledger: purge fixture rows, exempt calls carrying a test header, delete `tmp/probe_en.py`; the weekly usage report reads clean.
3. v1's daily model budget raised from 3,000 (MiniMax-era) to unlimited on the local gateway [ZAID hand: `/opt/stacks/palestine/.env` + `docker compose up -d alerts` from `/opt/stacks/palestine`]; alarm renamed `gateway`, text corrected.
4. Keys: `.keys/*` mode 600; OAuth tokens honour quota + revocation (re-check the key on every token use, `mcp_oauth.py:133-137`, `:345-349`); refresh 90 d as documented (`_prune` :89-91); PKCE required; per-key limiter for the shared test key (e.g. 60/min) so one script cannot lock everyone out.
5. Nightly accuracy audit extended: English inputs, AR/EN parity, cross-tool agreement (route vs checkpoint_status; crossings vs checkpoint row), payload size caps, description-vs-data drift; the `fuels` phantom probe removed.
6. Backup key custody (ZAID-8): Zaid copies `~/.config/palestine-v2/backup.key` to his password manager [ZAID hand]; the vault hot-copy moved after v1's 04:05 write (the flapping test).
7. Fresh-clone rebuild: the 17 `/opt/stacks/palestine` reads behind one `V1_ROOT` setting with a documented "no v1" mode.

### P2-A · The loop, on the seats (Z-2, G7)
1. **Organ C wired**: registered in `analyst/loop.py` (deterministic parser; 196/199 = brain-vs-reader agreement, not a precision — hand-read ≥100 rows first, audit F229), writes `analyst_run` provenance; the Gaza per-day series (stopped 08-09) resumes from the bulletins; the T4P cross-check stays as the control.
2. **Seat batches**: a nightly headless run (the maintainer pattern, Opus, pinned) that (a) re-judges the day's `unclear` verdicts plus a bounded backlog slice (≤ 300/night), (b) proposes place resolutions for the `village_ambiguous` rows, (c) never writes to `claim` — proposals go through `claim_classification` with `classifier=seat-YYYYMMDD`, validated by code, gated by the gold score. Budget guard: skip when the seat reports a cap (the 09-21 failure class).
3. **Gold sets as the contract**: incidents round 8 (P0-C), roads 200 (P1-A), MoH (exists); `ops/measure_review.py` scores every classifier version against them weekly; a version below gate cannot serve.
4. **Brain fallback**: organs B/D full-volume + backfills stay on `PSU_REPLACED=1`; the brain keeps serving v1's live calls.
5. **Red-team loop** (from the 09-19 design) stays after G1–G6; not in this plan's calendar.

### P2-B · Front door (Z-1, Z-4, G6)
1. **Landing page** at `https://live-api.zaidlab.xyz/` for browsers (content negotiation; JSON unchanged for API clients): what it is (AR/EN), live status from `/health`, "try these 12 questions" with real answers, "connect" (Claude connector with the public key + OAuth, ChatGPT, curl), docs (`/docs/partner` serving `PARTNER-API.md` rendered), licence posture, contact. Built to `docs/DESIGN.md` laws (Arabic-first, no external requests, three-state vocabulary, status chips with age). Later a `palestine.zaidlab.xyz` alias [ZAID: Cloudflare].
2. **Docs fixed**: every link in OAuth metadata and PARTNER-API resolves; `ops/mcp-registration.md` rewritten; `try-ten-calls.sh` → `try-twelve.sh` without the partner's name; README numbers generated.
3. **Thaura handover** (F-85 second half) after G1–G3 pass [ZAID].
4. `/app` (the human map) stays parked on ZAID-2; v1's tracker and `roads.zaidlab.xyz` link to the page.

### P2-C · Correlation, honestly ("both tiers feed each other")
1. Nightly link job: events ↔ checkpoints within 2 km / 3 h (`related` on incidents and checkpoint answers: "closed since 14:30, 2 km from a raid reported 14:05 by 2 channels"), labelled co-occurrence, never cause.
2. News ↔ incidents (organ F, deterministic first): `news.db` articles and RSS items matched to events by place + hour + type words → `sources` on the event; full organ F (model) after the PSU.
3. Tier 1 → Tier 2: the nightly rollup keeps writing history; the databank gains `movement.checkpoint` daily series per checkpoint (closed-hours/day) so `series` can answer "is Huwara getting worse this year".

### P3 · Unification (after G1–G7)
- v2 parses the raw road messages from v1's tee spool with its own cascade (+ organ D when the GPU is back) and v1's parser becomes the control until v2 beats it on the roads gold; v1's nightly refresh retired step by step; one Telegram plan (agent accounts documented, hard rule 3 respected); `news.db` folded into v2 sources; one API, one DB; the v1 public tracker redirects.

## 8 · Decisions and hands (defaults run until Zaid says otherwise)

| id | question | default now |
|---|---|---|
| D-1 | Fawwaz's in-flight edits (corridor `unverified`, migration 075, alias backfill) | Fable commits them as the first act of P0-B; Fawwaz stops editing `serve/` and `resolve/` until P0 lands (one pair of hands per file) |
| D-2 | v1 `.env` daily model budget → unlimited on the local gateway; retire the 9 dead v1 refresh steps | **Zaid's hand** (v1 is live): copy-paste blocks prepared in `docs/HANDS-2026-09-24.md` |
| D-3 | The 13 permission letters | **Zaid sends**; drafts exist in `source_permission` |
| D-4 | agent2 subscriptions: north road channels, crossings authority | **Zaid's call** (scarce account); until then the tools say "no source" and who publishes |
| D-5 | Backup key custody | **Zaid**: copy the key file to the password manager (one action) |
| D-6 | `palestine.zaidlab.xyz` alias | later; the page lives on `live-api` root first |
| D-7 | Thaura handover date | after G1–G3 pass; Zaid sends |
| D-8 | `land_levelling` as a new event type vs a demolition subtype | new closed-vocab type (the doctrine: closed vocabularies, no free text) |
| D-9 | Gaza crossings | stay "no source" with the publisher named; not in G4 |

## 9 · Execution order for this session (after approval)

0. **Freeze/take over** the admin-owned uncommitted work (D-1): `git status`, review the corridor diff, `chown`, commit, restart API, verify live.
1. Write the canonical executor doc `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md` (this plan + ledger §8 template), point `PLAN-2026-09-21` §0 at it, add `docs/HANDS-2026-09-24.md` (Zaid's copy-paste blocks), publish the shareable artifact.
2. P0-A tool map + answer contract test (red first) → renderers → boilerplate → leaks → rename. Full suite + SQL gates green after each commit.
3. P0-B ends snapping + vocabulary + regression fixtures.
4. P0-C resolver + classifier 1.7 + stable ids; round 7 re-score; round 8 gold prepared for the seat run.
5. P1-A palhub value-class measurement (read-only first, numbers into the ledger) → promotion decision → G4 recording.
6. P1-B/P1-C/P2 in the order above; each lands with its PROVE line in the ledger.

## 10 · Verification

- **Canonical questions**: `docs/try-twelve.sh` (extends `try-ten-calls.sh`) from a clean machine with the public key: قلنديا now · Huwara (EN) · رام الله→نابلس · Nablus→Jenin · incidents around Ramallah 12 h · what happened around Nablus this week · Rafah crossing · fuel prices · Gaza deaths latest · demolitions since 2009 · the 1948 depopulated villages of Ramla district · is Huwara getting worse — each with the expected shape asserted (verdict word, presence of age, no fallback in by_place, both languages naming the same facts).
- **Tests**: `.venv/bin/python -m pytest -q tests` as `zaid` (840 collected today; the 30-min vault test deselected as before) + `psql -f tests/test_gate*.sql`, `test_no_data_loss.sql`, `test_schema.sql` (80 PASS). New: `test_answer_contract.py`, corridor regression fixtures, stable-id test, palhub value-class measurement test, licence-cut test at the route.
- **Live**: `mcp__claude_ai_Westbank_Live_Tracker__*` calls from this session for the 12 questions (this is how §4 was measured; the same calls prove the fix), plus `curl` timings from outside for G1.
- **Nightly**: the extended `ops/mcp_accuracy_audit.py` at 04:40 (exit 1 on a critical pages via ntfy) and G4 known-fraction twice daily in `ops_heartbeat`.
- **Ledger**: every task closes with `YYYY-MM-DD HH:MM UTC · task · done|blocked|partial · proof: <command → number>` in the new plan's §8, and a ≤ 10-line Arabic summary to Zaid per workstream, never a claim without a number.
- **Tests that go red by design and are rewritten, not deleted**: `test_mcp_http.py:41`, `test_mcp_oauth.py:111` (tool set/count); the `emits`/wording assertions in `test_licence_tier.py` (licence shape); `tests/test_gate5_databank.sql` G5.11 (UCDP terms) until the terms are recorded. Nothing else is expected to go red; a red elsewhere is a regression and stops the slice.


## 11 · Progress ledger (append-only; `YYYY-MM-DD HH:MM UTC · task · done|blocked|partial · proof: <command → number>`)

2026-09-24 16:20 UTC · step 0 · done · proof: `git log --oneline -2` → `ffa1994`, `2bf77d4`. Fawwaz's in-flight route fix
(`unverified` verdict, ENDS_KM/UNVERIFIED_GAP_KM, coverage before verdict), migration 075 and the alias backfill landed;
two scratch probes that wrote into the production usage ledger removed; `tmp/` and `ops/mcp-accuracy.json` ignored.
56 tests green on the corridor/route/MCP files. **NOT LIVE until `palestine-v2-api` is restarted (Zaid, HANDS §1).**

2026-09-24 17:05 UTC · P0-A.1 · done · proof: `5d598bd`; `tools/list` → 16 names; test_facades 33 passed. Palestine Data
— live + databank; façade table + `route()` on both transports; 28 old names alias; every parameter described,
defaults declared; `about` composite (headline says how many supply lines FAIL).
2026-09-24 17:05 UTC · P0-A.2/A.4 · done · proof: `6f95df9`; test_headlines 16 passed. Databank latest-figure headline;
crossings names the no-source crossings; place_history/area_history/stream/latest_news headlines; fires apart from
incidents; `src:N` → source keys; five English renderers added; EN carries fuzzy doubt + direction split; trend no None.
2026-09-24 17:05 UTC · P0-A.3 + P0-B.2/3 · done · proof: `978ca3b`; licence block 267–390 B (was ≤1 KB), series 6 KB (was
228 KB); route `doubts` + `exit_closures` spoken in both languages (live on dev: "إغلاق عند بيت ايل على طريق الخروج من
رام الله (2014 متر، قبل 3 ساعة)؛ ونص الطريق تقريباً بلا حاجز متابَع").
2026-09-24 17:05 UTC · P0-C · done (measured) · proof: `ae86ea7` + follow-up; classifier 1.7.1; migration 076 applied;
4,684 events keyed, 0 duplicate keys; the timer's first 1.7 pass read 33,621 claims in 93 s → 5,103 events, 1,134
corroborated, 88 `land_levelling`; **round-7 projection 0.717 → 0.83 (death 0.35 → ≥0.85)**
(`ops/rescore_round.py 7`, `ops/incident-precision-round7-rescored-1.7.1.json`); placement 28 % governorate-only
(unchanged: extraction is the lever, P0-C.1b remains). NOT a new round: gold round 8 on the seat is next (Z-2).
2026-09-24 17:05 UTC · hands · waiting on Zaid · `docs/HANDS-2026-09-24.md` §1 (API restart — nothing serving-side is
live until then), §2 (v1 budget), §3 (retire 7 dead v1 steps), §4 (backup key), §5 (letters), §6 (UCDP terms).
2026-09-24 16:59 UTC · P0-C live · done · proof: journal `palestine-v2-news.service` 16:57:35→16:59:19 — classifier 1.7.1 read
33,629 claims → 5,078 events from 8,523 reports, 1,123 corroborated, no errors, 26.6 s CPU (the timer runs the tree, so
classification is live; serving is not until HANDS §1). Round-7 projection under the final rules: 0.826, 21 wrong rows
dropped, 0 right rows dropped, 10 type moves to re-judge (`ops/incident-precision-round7-rescored-1.7.1.json`).
2026-09-24 17:15 UTC · HANDS §1 · done · proof: `systemctl is-active palestine-v2-api` → active; `/health` ok; live
`/v2/route/between` رام الله→نابلس → `unverified` with the reason; `/mcp` tools/list → 16, serverInfo `palestine-data`.
P0-A/B/C are LIVE on https://live-api.zaidlab.xyz. Remaining hands: §2–§6.
2026-09-24 18:05 UTC · P0-C.1b place extraction + gazetteer · done (code, commit e6da6b7; corpus re-read running) · proof:
measured before: 1,414 of 5,080 news events governorate-only (27.8 %) — 936 with NO name read, 478 with a name the
gazetteer failed (`ops/place_measure.py`, read-only). Root causes found and fixed: (1) the reader took only the first
settlement word — now every candidate: settlement words, duals, site words, "<name> جنوب نابلس", toponym prefixes, "بين
X وY"; (2) two admin2 code schemes in `place` (migration 077: 187 servable rows re-coded from the polygons; the
fuller-form village lookup had been dead since it landed); (3) the governorate's bare Arabic name lives on the city
row, so the twin check never fired — 223 Ramallah reports sat on Jenin's المغير; (4) 457 of 1,443 servable localities
have no Arabic key at all — `ops/promote_named_localities.py` promoted 8 Open Maps rows, 23 aliases, 14 twin keys
(evidence-driven from the corpus, dry-run first); (5) `event.claim_count` was 4× inflated by the re-reads (5,069 of
5,082 events; 34,044 vs 8,528 real) — now derived from the claims at the end of each run; (6) one run at a time (pg
advisory lock) because a corpus re-read outlives the 5-min timer. Projection (`--scope gov_only|named|unlocated`):
named 72.2 % → 83.4 % (4,237 of 5,081); 642 of the 1,414 now named; 590 named events move (المغير 222 → Ramallah's
row, برقا 70, camps over checkpoints 62); 55 demoted honestly; 70 new placements hand-checked → 66 right (94 %).
Tests: `tests/test_place_extraction.py` (16) + `tests/test_place_locate.py` (9) + test_news 75 green. NOTE: killing the
timer's own 1.8.0 re-read (it would have hit `TimeoutStartSec=900` and rolled back in a loop) fired one ntfy alert
at 18:04 UTC — expected, see HANDS §8.
2026-09-24 18:07 UTC · P0-C.1b corpus re-read (1.8.0, `--rebuild`, 2.5 min) · done · proof: `read 33659 unclassified
claims · incident 9068 · located 8661 · dropped 407 · 5098 distinct events from 8661 reports (1147 corroborated) · 459
closure states`. DB after: `place_precision` named 4,172 / governorate 909 / village_ambiguous 17 of 5,098 → **named
81.8 %, governorate-only 17.8 % (was 27.8 %)**; claim_count off 0 of 5,098 (was 5,069); duplicate stable keys 0; events
on stations 0 (was 5), on governorate polygons 0 (was 327); المغير: 221 events on Ramallah's row, 36 on Jenin's.
Live `/v2/incidents/summary?hours=168`: 755 incidents, 153 located to a governorate only, by_place led by المغير 26 ·
برقة 19 · جبع 17 · سلواد 14 — the Ramallah villages count as themselves now. G3 placement line (≥ 80 % named) met;
precision of new placements 94 % on a 70-row hand check (a real round-8 gold set is still the next step). The serving
API keeps the 09-24 17:15 process: it reads the new events live, but its own resolver (place, checkpoint_status) loads
the 1.8.0 `resolve/geo.py` only at the next restart (HANDS §1b).
2026-09-24 18:27 UTC · full suite after the re-read · done · proof: `PALESTINE_API=http://127.0.0.1:7870 pytest -q tests`
(vault schedule tests deselected) → 928 passed, 2 skipped, 0 failed in 8:13. The news timer's tick at 18:07:53 read 1
claim and finished; the only failed run today is the one killed at 18:04 (the alert Zaid received).
2026-09-24 19:00 UTC · P0-C.3 gold round 8 · done (measured; gate FAILED) · proof: `learn/incident_precision.py --sample --round 8
--per-type-cap 15 --adversarial 50 --rejects 40` → 238 rows (150 core, 48 adversarial, 40 rejects), every row judged by hand
against the text (`ops/incident-scored-round8.ndjson`, notes on each). `--score --round 8` → **core precision 0.767 [0.69–0.83]**:
death 0.60, siege 0.60, demolition 0.667, land_levelling 0.667, closure/injury/settler_attack 0.80, raid 0.867,
arrest/shooting 0.933; adversarial 0.50 (long features 0/5, funerals 4/12, notices 5/10, origin 8/10); miss rate 17.5 % (7 of
40 rejects real). Failure classes were specific: farewells/obituaries (6 deaths), official statements (5), orders/threats
(5), roundups/features (7), releases (2), court news, a vigil, a traffic accident; places: street names read as
governorates (2), a reference town (1), no-governorate twins (2), run-on captures into الأغوار (2). Round 7 re-judged under
1.8.0 (10 type moves) → 0.805 (`ops/incident-rejudged-round7-1.8.0.ndjson`).
2026-09-24 19:12 UTC · classifier 1.8.1 (one rule per measured class) · done · proof: commit `6f71d50`; 128 tests green
(test_news 103 incl. 26 round-8 regressions); projection over round 8 with the 6 type moves re-judged → 0.876
(`ops/rescore_round.py 8` → `ops/incident-precision-round8-rescored-1.8.1.json`; 35 wrong rows dropped, 2 right rows lost by
design). Corpus re-read (the timer's own incremental run at 19:08–19:10, then `--rebuild` 19:11–19:20): 33,683 claims →
incident 9,155 · rejected 15,491 · unclear 9,037 · 5,069 events · named 4,191 / governorate 861 / ambiguous 17 → **named
82.7 %**; claim_count exact; 0 duplicate keys; المغير 232 on Ramallah's row, 9 on Jenin's; new reject reasons live:
obituary 222, court 90, propaganda 75, testimony 65. **The honest precision number is round 8's 0.767 until round 9 draws a
fresh sample of 1.8.1**; the projection is a tuning-set number. Next: round 9 after a week of 1.8.1 output.
2026-09-24 19:30 UTC · P0-C.3 per-type precision in every incident answer + migration 078 · done · proof: commit `1b3804c`;
`serve/quality.py` reads the latest round (`ops/incident-precision.json`, now stamped round + measured version); live
`/v2/incidents/summary` → `precision: {round 8, measured 1.8.0, serving 1.8.1, weak: death 0.60 · siege 0.60 · demolition
0.667 · land_levelling 0.667}` and `by_type.<type>.precision`; MCP `incidents` answer ends with "دقّة القراءة الآلية بآخر فحص
يدوي (جولة 8): استشهاد 60%، حصار 60%، هدم 67%" (English: "Machine-read precision on the last hand check (round 8): …");
the insights quality block reads the latest round instead of a hard-coded round-7 file. 078: 38 servable rows with an
Arabic key but no Arabic name now display it ("هدم في Bayt Rima" → بيت ريما); 417 Latin-only rows remain. Serving tests
141 green on a dev instance; test_quality 5.
2026-09-24 19:26 UTC · INCIDENT (mine) · the production API restarted · while stopping the dev instance I matched every
`uvicorn serve.app:app` process, which killed the production API at 19:26:36; systemd (`Restart=always`) had it back at
19:26:38 (NRestarts=1, `/health` 200, no alert fired). Two seconds of downtime, no data touched. The restarted process runs
the current tree, so **HANDS §1b (the serving-resolver restart) is done — by this accident, not by Zaid's hand**; the
per-type precision answers above are therefore live too. Lesson recorded: never kill by a pattern the production unit
also matches; use the dev instance's port/pid.
2026-09-24 20:04 UTC · repository published (private) · done · proof: https://github.com/Zaidroid/palestine-v2, `master`, 183
commits, tree clean. Audit before the push: `.env`, `.keys/`, the Telegram session and the usage ledgers were never committed;
no DB password, api_hash or private key in any commit; the one key in history is the deliberately published public test key
(`docs/PARTNER-API.md`, f0fe881). The nightly run ledger `ops/databank-runs.ndjson` is no longer tracked; `CLAUDE.md` tells a
session away from main-server what it can and cannot run. The GitHub CLI lives in `~/.local/bin/gh` (logged in as Zaidroid,
https); an SSH key `~/.ssh/github-main-server` exists unused. v1 (`/opt/stacks/palestine`) is not in this repo.
2026-09-24 20:35 UTC · v1's code published too (private) · done · proof: https://github.com/Zaidroid/palestine-v1, one snapshot
commit, 461 files, 23 MB, copied out of `/opt/stacks/palestine` (never a git repo, 41 GB on disk) with its data, `.env`
files, Telegram sessions, SQLite databases, backups, tiles and the 40 GB `public/data` left out; no credential in any file
(the CI placeholder key is a dummy). `SNAPSHOT.md` there says what is in, what is out, and that production is the tree on
main-server, not the checkout. The old Actions workflow was moved to `ci/github-workflows/` so no CI runs on the snapshot.
Together the two repositories are the whole project: v2 = Tier 1 + Tier 2 + API/MCP; v1 = the road-channel parser v2 still
reads, the old site and the nightly refresh (P3 folds the parser into v2).
2026-09-25 08:55 UTC · audit 2026-09-25 fixes, 11 commits on branch `claude/system-analysis-complete-mzpu2r` (NOT merged,
NOT live) · partial · proof: every fix has a test that failed on the old code; full suite on a schema-only local DB with
synthetic rolled-back rows 927 passed / 99 failed, the 99 being the baseline's production-data and live-API tests
(baseline 821 / 99); no real data read or written. Of the audit's 160 confirmed findings, 57 are done and 3 partial
(`docs/audit-2026-09-25/plan/STATUS.md` maps each to its commit). By area: 01 parser 14/14 (`74d914b`); 02 belief 5/5
with migrations 079 (the `both` row is the worse direction) and 080 (crowd never feeds incidents) (`932004f`); 03 route
3/4 + 1 partial (`d952350`: G2 coverage ≥ 0.6 enforced, doubts for `slow`, exit closures spoken for every verdict);
04 renderers 15/29 (`c530211`, `1d5115c`); 05 transport 7/10 (`a348ccf`: batch ≤ 8 and body ≤ 256 KB, quota per
tools/call, OAuth tokens die with their key and spend its quota, refresh rotation + client binding + 90 d, PKCE
required, state file 0600, SSE `reset` on drop); 06 rest 7/20 (`f650da8`: /v2/insights and the kind-scoped resolver no
longer learn, crowd notes are not news, max_lag ≤ 366, note ≤ 280); 07 classifier 3/17 → **CLASSIFIER_VERSION 1.9.0**
(`be66fb2`: a reopening is not a closure; bounded regexes — the audit measured 45.7 s for one 3,600-char token; every pattern stem now reads 4,000 chars in < 0.1 s;
`646746c`: a re-read no longer duplicates closure observations); 09 ingest 3/11 + F224 (`3d77f79`: poller FloodWait
honoured while resolving and downloading, 0 channels resolved fails the heartbeat, atomic cursor file; `f5fd58d`: the v1
import cursor ignores crowd rows and re-reads 12 h behind itself with dedup). 1.9.0 projection on the tuning sets: all
1,045 sampled claims of rounds 1–8 read identically to 1.8.1 (a projection, not a measurement; 1.9.0 is unmeasured
until round 9). Go-live steps, in order, with the classifier's prerequisites (HANDS §8 timeout, the F206 event-delete
decision, `ops/project_classifier.py` read-only projection): `docs/audit-2026-09-25/plan/HANDS-NEEDED.md`.
2026-09-25 08:55 UTC · ledger corrections (earlier lines stand as written; this records what the code showed) ·
partial (fixed or open per item) · proof: audit 2026-09-25, `docs/audit-2026-09-25/confirmed-findings.json`. Claims above marked
done that the code contradicted: **P0-A.1** (17:05) — place_profile anchored on one resolver (F010, now fixed
`1d5115c`); `news` search mode drops place/kind (F047, open); `series` ignores `days` (F061/F305, open); façade
arguments bypass the REST caps (F054, open). **P0-A.2/A.4** (17:05, `6f95df9`) — /v2/insights still learned into
place_alias (F076/F081/F085, now fixed `f650da8`); `tests/test_answer_contract.py` never existed (F155, open); ages
missing from answers (F052 fixed `c530211`; F056 can_i_travel, open); crossings said "no source" for decayed crossings
(F055, fixed `1d5115c`); route waypoints not labelled as settlements (F057/F322, open — needs a data source); databank
headline span computed over the page (F062, open). **P0-A.3** — no per-tool payload byte cap (F048, open); per-call
boilerplate still attached (F051, open). **P0-B.2/3** — G2's coverage rule not checked on short routes (F071, fixed
`d952350`). **P0-C** (17:05, "measured") — insights counts governorate fallbacks under the city (F034/F080, open);
independence never fitted for news channels (F033, open); the stable key is overwritten on join and no test proves a
rebuild keeps event ids (F477/F084, open). PLAN-09-21 **F-86** — mcp-audit's OK_EXIT_CODES reach the wrong process
(F064, open).
2026-09-25 09:55 UTC · audit branch `claude/system-analysis-complete-mzpu2r` verified on the real DB and MERGED to master
(fast-forward `f572be8`), live for the timers · partial (serving waits for Zaid's hands) · proof: from the worktree
`~/palestine-v2-audit`, full suite on the real DB 1045 passed / 17 failed → 13 worktree-missing files (167 pass with the
files linked), 4 belief tests wait for 079/080, 1 real regression fixed `5d55ed8` (corridor gave `unknown` an age);
079 dry run rolled back: 5 of 753 `checkpoint_serving` rows change (عناب both→closed, جبع both unknown→open on an
inbound-only reading → 079 changed: `unknown` outranks `open`, a never-read direction counts unknown — Zaid's decision);
belief F017 SQL dry run: 0 value changes; parser old→new on 7 d of raw lines: 158 of 19,703 readings change
(37 unparsed→closure, 36 assertion→question, 18 congested→open on فش ازمة; 2 residual misreads: `ما رح يفتح` lost,
`سالك مش مغلق … بس مسكرين بوابة` read closed); classifier 1.9.0 projection (fixed tool `ops/project_classifier.py`):
9 closure→rejected:reopening are the only rule change (7 right, 2 = activists reopening a settler-closed road);
crowd-derived incidents 0. F206 FIXED PERMANENTLY `f572be8` (Zaid: "fix it permanently"): the sweep retracts
(`retire_unreferenced_events`, versioning trigger files the believed version), derived closure rows → modality
`rejected` with `attrs.withdrawn_by`, a returning stable key revives the event (`reassert_closure_observations`);
`tests/test_event_sweep.py` 3 + `test_belief_serving` 07/08. 1.9.0 corpus re-read by hand under the advisory lock
09:48:40→09:52:13 UTC (3.5 min; the timer never collided): 33,952 claims → incident 9,221 · rejected 15,642 · unclear
9,089; 5,106 believed events (named 4,225 = 82.7 %), 7 retracted and KEPT (event_history +10,217 versions), 9 reopening
rejections, 5 derived closure rows withdrawn, 0 deleted. Item 8 (v1 import cursor): 0 duplicate identities over 13 h.
ZAID'S HANDS (classifier-refused): `db/migrate.sh` (079+080) → `restart palestine-v2-api` → `restart palestine-v2-poller`
→ HANDS §8 timeout; the block is at the top of `docs/audit-2026-09-25/plan/HANDS-NEEDED.md`.
2026-09-25 10:00 UTC · audit branch LIVE end to end (Zaid's hands: `db/migrate.sh` 079+080 at 09:54, `restart
palestine-v2-api` 09:54:35, `restart palestine-v2-poller`) · done · proof: `/health` 200 from outside; poller resolved its
channels; `tests/test_belief_serving.py` + `test_route_omissions.py` against :7870 → 17 passed; `checkpoint_serving` both
rows: unknown 134 · open 96 · closed 21; جبع default row `unknown` (last known congested) with inbound open spoken per
direction; live connector: قلنديا "ما في تحديث جديد — آخر معلومة قبل 2 ساعة: كان فيه أزمة"; رام الله→نابلس `unverified`
with the blind 27 km, 3 of 8 reported and سلواد يبرود closed 2 km off spoken; crossings separates 3 decayed from 5
no-source. Open from the audit: 99 findings (STATUS.md), HANDS §8 timeout still wanted for the next version bump.
2026-09-25 11:05 UTC · audit 04-renderers · done 11 + partial 2 of the 14 left open (F047 F051 F054 F056 F061 F062 F268
F269 F270 F271 F305 F504 F505; F057 settlement labels stays open — needs a data source) · proof: `81acc75`,
tests/test_renderers_04b.py 10 new + 3 assertions corrected; full suite on the real DB 1082 passed / 0 failed. Serving
change → needs Zaid's `restart palestine-v2-api` (not live yet). Next: audit 06-rest (13 open), then P1-A palhub.
2026-09-25 11:25 UTC · audit 06-rest · done 11 + partial 2 of the 13 left open (F070 F089 F034 F080 F082 F030 F043 F251
F288 F296 F143; F293/F287 pool wired behind an optional psycopg_pool import — Zaid installs the package) · proof: `36f75a8`,
tests/test_rest_06b.py 12 new; on the real registry Hawara/Huwwara → حوارة served with doubt, Zatara → Za'tara exact,
insights رام الله carries located_to_governorate_only, incident exports carry place_precision, /health reports 6 watchdog
families; full suite on the real DB 1093 passed / 0 failed. Serving change → needs Zaid's `restart palestine-v2-api`.
Audit tally 80 done · 7 partial · 73 open of 160. Next: 07 classifier (14 open), 08 gazetteer, 11 ops; then P1-A palhub.
2026-09-25 12:50 UTC · audit 07-classifier · done 13 of 13 left open → CLASSIFIER_VERSION 1.10.0 LIVE (`c178d67`) ·
done · proof: stated time (مساء أمس → yesterday 19:00 local, precision day/hour), house sieges no longer close roads,
anchored closure clause (emoji-glued tokens need \w boundaries), settler verbal nouns + settlers-not-settlements, bare
اعتقال, whole-word rejects with nationality forms (عراق بورين is a village), مدخل <city>, mirrors = one voice,
last_report_at window, stable key never rewritten, closure belief from assertions only; tests/test_classifier_07b.py 27
new, test_news 103 green. Projections (tuning sets): round 7 0.826→0.848, round 8 0.876→0.877; corpus projection read by
hand seven times (1,009 changes, mostly unclear→arrest 235 and unclear→settler_attack 163 recall; three regressions found
and fixed before shipping: emoji anchors, bare عراق, re-arrests of released prisoners). Re-read by hand 12:38→12:46 UTC
under the lock: 34,032 claims → incident 9,638 · rejected 15,893 · unclear 8,501; 5,354 believed events (named 82.1 %),
48 retracted and kept (10,195 history versions), 14 day-precision events, 49 mirrors collapsed, 26 closure states written.
Honest precision stays round 8's 0.767 until round 9. Audit tally 93 done · 7 partial · 60 open of 160. Also today:
last night's backup had refused (event rows shrank under the 09-24 DELETE sweeps) → run with `--accept-shrink`, set
2026-09-25T11-31-07Z uploaded and verified. Next: 08 gazetteer (4), 11 ops (16), 09 ingest (8), then P1-A palhub.
2026-09-25 13:35 UTC · audit 08-gazetteer · done 4 of 4 · proof: `d19a3b2`; المغير without a hint → ambiguous_with 1,
alternatives [Jenin's], confidence 0.72 (was 0.92 Jenin-only); with رام الله / جنين hints → each twin at 0.96; learn
defaults False and never commits a borrowed transaction; load_gazetteer refuses a populated DB (no TRUNCATE) and carries
the 077 codes; place_merge first-writer-wins; tests/test_gazetteer_08b.py 4; full suite 1124 passed / 0 failed. Serving
part (/v2/geo/resolve) waits for the next API restart. Tally 97 done · 6 partial · 57 open. Next: 11 ops (16), 09 ingest (8).
2026-09-25 13:55 UTC · audit 11-ops · done 15 of 16 (OPS-01 maintainer sudo/permissions = Zaid's hand) · proof: `d34217d`;
tests/test_ops_11b.py 12; `ops.watchdog --dry-run` from the worktree reads every family; full suite 1137 passed / 1
(the route test widened for the F011 exit-closure sentence). Zaid: install the three changed units + the valhalla-ip
drop-in (block in HANDS-NEEDED). Tally 112 done · 6 partial · 42 open. Next: 09 ingest (8), 10 feeds (7), 12 databank (5),
13 learning (4), 14 docs (10), 15 webapp (4); then P1-A palhub.
2026-09-25 14:05 UTC · audit 09-ingest · done 6 of 8 left (F213 F217 F221 F223 F225 F438; INGEST-05 id-keying and
INGEST-07 edits = Zaid's decisions) · proof: `95a4b6f`; tests/test_ingest_09b.py 6; full suite 1144 passed / 0 failed. The
running poller picks the changes up at Zaid's next restart. Tally 118 done · 6 partial · 36 open. Next: 10 feeds (7),
12 databank (5), 13 learning (4), 14 docs (10), 15 webapp (4); then P1-A palhub.
2026-09-25 14:12 UTC · audit 10-feeds · done 7 of 7 · proof: `f05f9bf`; tests/test_feeds_10b.py 6; full suite 1149 passed /
0 failed. Live for the timers at their next tick (power/weather/connectivity/fuel/MoH loaders run the tree); the power
cut's 'normal' at window_end appears on the next power tick. Tally 125 done · 6 partial · 29 open. Next: 12 databank
(5), 13 learning (4), 14 docs (10), 15 webapp (4); then P1-A palhub.
2026-09-25 14:30 UTC · audit 13-learning + 15-webapp · done 8 of 8 · proof: `908d08d`; tests 7; full suite 1155 passed.
Crowd sources can no longer be lifted out of crowd:unverified by the nightly collapse (F004, critical); reliability is
leave-one-out; the nightly audit runs through the transport; pulse/road pages carry the verdict row's age, consume the
stream's named events, refresh, and say when a fetch fails. Web pages + audit go live at the next API restart. Tally 133
done · 6 partial · 21 open (12 databank 5 — migrations + Zaid's World Bank re-route decision; 14 docs 10; the partials).
2026-09-25 14:45 UTC · audit 14-docs · done 10 of 10 — and G1's two open items with it: `tests/test_answer_contract.py`
(16 tools, contract (a)–(e), found the connectivity age gap in both languages, fixed) and `docs/try-twelve.sh` (all
twelve canonical questions answered 200 against the dev API, p50 ≈ 0.5 s) · proof: `db5c400`; full suite 1173 passed.
Serving side (renderers, resolver tie-break) goes live at the next API restart. Tally 144 done · 5 partial · 11 open:
12 databank (5, migrations + Zaid's World Bank re-route), INGEST-05/07 (2 decisions), OPS-01 (his hand), REST-15/16
(pool package), RENDERERS-17 (settlement data), the 3 partials. Next: P1-A palhub earn-out (G4).
2026-09-25 16:00 UTC · P1-A.1 palhub earn-out — MEASURED, read-only (`ops/palhub_earnout.py --days 28 --window 90`,
`ops/palhub-earnout.json`) · partial (decision pending) · proof: 70,735 palhub↔channel pairs agree 0.735; the
channel↔channel CONTROL measured the same way agrees 0.829 — so the 0.90 gate is above what two channels achieve. By class
(palhub vs control): open 0.861 vs 0.889 (gap −0.03, 49,374 pairs) · closed 0.646 vs 0.778 (−0.13, 11,187) · congested
0.222 vs 0.590 (−0.37, 10,174). Congested splits by phrase: أزمة متوسطة agrees 0.12 (channels say open 81 %), أزمة خانقة
0.51. Window ±10/20/45/90 min changes nothing (real disagreement, not lag). Direction: palhub's in/out is NOT inverted
(same-direction beats opposite) but where a channel states a direction explicitly agreement is ~0.50 either way — those
are the contested moments; the undirected reading is what agrees. Per checkpoint (103 with ≥20 pairs): from 0.46 (تياسير)
to 0.86. Projection on today's serving view (known 95 of 251 = 0.38): promote open → 0.52 (6 contradictions with a
current channel value), open+closed → 0.54 (8), all three → 0.57 (26). 49 more palhub places ≤3 h old resolve to rows
that are not in checkpoint_serving (the 13.5 % unresolved/non-servable names) — the alias/promotion backfill is the
other half of G4. Decision for Zaid: A promote open+closed (recommended), B open only, C stay quarantined.
2026-09-25 16:00 UTC · P1-A.1 palhub earn-out — DECISION A (Zaid) LIVE at 15:49 (`e82a176`): open + closed asserted,
congested quarantined · done · proof: first two palhub ticks wrote 254 rows (139 open + 61 closed asserted, 54 congested
quarantined); `checkpoint_serving` known 95 of 251 (0.38) → **167 of 287 (0.58)**, direction-resolved among known 0 →
**96** (36 checkpoints that had only palhub readings now enter the view). G4 gate 0.60 within reach; the remaining lever
is the 49 palhub places that resolve to non-servable rows (alias/promotion backfill, P1-A.1 second half). The watchdog now
records known-fraction + direction share every run (`ops_heartbeat` 'coverage', `ops/coverage.ndjson`). Watch: palhub's
closed agrees with channels 0.65 (control 0.78) — the weekly measure-review keeps measuring every palhub row by class.
2026-09-25 17:40 UTC · P1-A.1b palhub names land on CHECKPOINT rows (migration 081 + loader guard) · partial (waits
for `db/migrate.sh`) · proof: the latest bulletins name 191 points; before: 113 on a checkpoint row, 25 unresolved,
54 on the TOWN the point is named after (the loader's fallback was the general resolver — the 035 bug class), and since
decision A those town rows carried assertions: at 17:00 `checkpoint_serving` listed 55 towns/roads/a fuel station as
checkpoints, 47 of its 177 "known" rows (the honest known fraction was 130/237 = 0.55, not 0.58). Now: the loader accepts
only checkpoint/crossing/road rows (a name it cannot put on one is counted + printed as unresolved), reads palhub's exact
wording declared on the row it means (`place.attrs.palhub_names`) and every accepted row's own name first; 081 declares 27
names on existing rows (junctions, bridges, the gate at the town's entrance), creates 34 checkpoint rows anchored at the
town centroid (`geo_precision approx-anchor`) + checkpoint 300 by hand, moves the last 2 days of readings (6,310 rows,
inside the uncompressed chunks), re-quarantines the 2 that had nowhere to go, drops the towns' beliefs. Rolled-back dry
run with a belief rebuild: 273 rows, 0 off-kind, known 161 (0.59) at once; with the new loader 174 of 191 names resolve,
17 stay unresolved on purpose (no row, no anchor — listed in the migration). Tests: `tests/test_palhub_names.py` (5; four
skip until 081). Zaid's hand: `cd ~/palestine-v2 && db/migrate.sh` (HANDS-NEEDED top).
2026-09-25 16:45 UTC · P1-A.1b migration 081 APPLIED by Zaid (16:39) · done · proof: `checkpoint_serving` both rows 273,
**0 off-kind** (was 55 towns/roads/a station), known **164 of 273 = 0.601** — the G4 gate on honest rows, 20 of the 34
new gate rows already known from the moved readings; 0 palhub rows on a town since; `tests/test_palhub_names.py` 5 passed
against the live API (`faeea57`, the test reads a whole 12-bulletin cycle). Weekly measure-review keeps measuring.
2026-09-25 18:30 UTC · Two testers' round (Fawwaz via the partner door, Claude web via the connector; both ran BEFORE 081)
· partial · what was already fixed by 081: "road bulletins don't update checkpoints" (Beita, al-Lubban, the 17 junction
now 5 min old) · gazetteer: migration 082 written + dry-run (20 duplicate/fragment/Hebrew rows merged into the row with the
readings, 6 renamed, 2 retired, Karmelo moved from Jenin to Yatta with its 14 aliases, Hebron خربة الطيبة created for the 3
PCBS aliases): 265 serving rows, known 0.634, 0 duplicate names — waits for `db/migrate.sh` · ops: an OnFailure alarm is
now resolved by the unit's next successful run (`ops/alert.py --resolve`, called by with-heartbeat.sh), and `--sweep`
reconciles the 664 unit alarms that piled up since 08-06 against ops_heartbeat.last_ok (tests/test_alert_resolve.py 4) ·
still open, serving layer (one commit, mine): databank drops indicator/as_of without category; English answers print
Arabic names (nearby query has name_en, closed-now list ignores it); English refusal strings inside Arabic answers;
AR/EN content divergence (databank overview 6 vs 5, "32 sources" vs datasets, summary caveat); fuel effective dates per
language; crossings Arabic area filter (matches name_en only → "أريحا" = nothing); place "Huwara" history view; series with
a place = 0 points; correlate scan "941 of 235 dates" + 0-tests text; insights "152,926 minutes"; route "most of the
route" at 50 %; about says crossings have no source.
2026-09-25 18:50 UTC · alarm pile reconciled · done · proof: `ops/alert.py --sweep` (heartbeat last_ok, retired jobs, systemd's
own result) resolved 13 units' alarms — 664 → 5 open (measure-review ×2, f11-night, notify-test, watchdog:job:backup which the
watchdog closes on its next run); the manual 11:31 backup recorded as its heartbeat → `/health` ok, 0 faults. From now on
with-heartbeat.sh resolves a unit's alarm on its next good run. system_health through the MCP will read the same once the API
restarts (Fawwaz's `48537a6` is also waiting on that restart).
2026-09-25 17:35 UTC · migration 082 APPLIED + API restarted by Zaid (17:32) · done · proof: 20 rows merged, 0 duplicate
checkpoint names, `checkpoint_serving` known 169 of 265 = 0.638; Karmelo now in Hebron governorate; live
`/v2/checkpoints/status` اللبن الشرقية → row 1739, 15 min old (was the 10-hour-old twin), الكونتينر → one row; /health ok,
0 faults, pool on. Fawwaz's `48537a6` (system_health) live with this restart.
2026-09-25 19:40 UTC · Testers' serving-layer set (Fawwaz via the partner door + Claude web via the connector) · done on
master, waits for one API restart · proof: each reported case replayed through the MCP dispatcher before and after
(`tests/test_testers_round_0925.py`, 24 tests, one per defect): databank `indicator` alone reaches its category and `as_of`
alone is said; English answers use English names (nearby, closed-now, insights, locate, history, profile, status); every
correlation refusal and scan reason is Arabic inside Arabic (`serve/correlate.reason_ar`); AR/EN carry the same facts
(databank overview six categories + "datasets" not "sources", closed-now shared-name caveat, insights corroboration, about's
count with a reading); fuel dates grouped by product in both languages; crossings match the area in Arabic or English and an
unmatched area is not "no source"; about no longer denies the Allenby bridge, fields spoken as words; "Huwara" in English
reaches the checkpoint in history/pattern/profile and locate names it; `series` with a city reads its governorate and says
so; the date-collapse note counts dates; zero scan tests says so; insights ages as ages; the route's blind stretch is one
size in both languages; `signals_agreeing` counts IODA's signals (3 of 3); checkpoint_status takes `place`; bad arguments
answer in both languages. Full suite 1205 passed before 4 structure-pinned tests were updated (now green).
2026-09-25 18:50 UTC · testers' serving set LIVE (API restarted by Zaid 18:45) · done · proof: production passes tests/test_testers_round_0925.py + test_facades + test_answer_contract (76 passed against :7870); through the public connector `crossings(أريحا)` returns the bridge closed and the rest stop open, `place(Huwara, history)` returns the checkpoint with place_en Huwara. Fawwaz can re-test.
2026-09-25 20:10 UTC · P1-A.2 "searching" presented · done on master, waits for the API restart · proof: a fresh inspection
sighting is said as a state word beside the flow — "حوارة: سالك مع تفتيش. آخر تحديث قبل 3 دقايق، والتفتيش قبل 15 دقيقة." /
"Huwara: open, searching under way. Reported 3 min ago; the search seen 15 min ago." — closed + search said as two facts, a
search with no current flow leads the sentence; every checkpoint row carries `searching` (presence stays its own axis); the
summary names where a search is going on (`searching_now`, 2 now: المربعة، عين سينيا); the route now reads inspection
sightings and speaks who was seen on the way, searching first (it spoke none before). Measured: inspection is reported
30–130 times a day (561 in 7 days). tests/test_searching.py (8); full suite 1219 passed.
2026-09-25 20:45 UTC · P1-A.3 silent-source flags · done (live at the next watchdog tick; /health shows it after the API
restart) · proof: every active Telegram/RSS source judged against its own rhythm over 60 days of claims + observations
(p95 gap, or 3× mean gap when sparse, never under a day): 30 of 31 watched sources within rhythm; SILENT: tg_areenablus
(nothing for 776 h, ceiling 122 h — stopped 2026-08-24 and nothing said so for a month); dormant, listed not alarmed:
tg_palmoh, tg_palrcs, tg_gedcogaza, tg_jdeconet (registered, but v2's poller does not read them — the Gaza MoH / PRCS
channels; re-poll is Zaid's call on the scarce account), tg_almasshta (nothing in 60 d), telegram_fuel (its kind was
retired); 17 registry-only news feeds with no collector. A silent source raises watchdog:source:<key> once and is
resolved when it speaks again; verdicts recorded in ops_heartbeat 'sources' (EXPECTED_JOBS) so /health reads them in
milliseconds. tests/test_source_silence.py (10); full suite 1229 passed.
2026-09-25 21:40 UTC · P1-B.1 serve what is held (migration 083 + route + tool) · partial (waits for `db/migrate.sh` + API
restart) · proof: `ops/backfill_conflict_names.py --apply` restored the names the importer had dropped on all 9,137 held
conflict events (1,159 localities also got their 1945 district), additive, 9,785 prior versions kept in event_history.
MEASURED BEFORE SERVING: the v1 conflict file had been imported twice — 574 of the "1,163 villages" and 74 of the "7,712"
UCDP events are exact copies (same name+point; same date+place+dyad+deaths) → 083 marks them `superseded`, never deletes:
the record is 589 localities (509 Palestinian, 38 Mixed, 10 Jewish, 32 unclassified; 1935–1967) and 7,638 UCDP events;
and the "displaced" figure is each locality's TOTAL 1945 population (Jerusalem 157,080) → served as population_1945, never
summed, never called refugees. 083: databank_event_rows (observation's shape, id = −event_id) UNION ALL'd into
databank_internal so every tier/category view inherits it; a `displacement` category; 5 indicator_def rows; UCDP served
non-commercial until its terms are read (G5.11). Route: the category read serves events beside observations, summarises
registers (`event_summary`), counts localities by 1945 district/subdistrict/group, `district=` filter (Arabic or English).
Rolled-back end-to-end harness: databank(district="الرملة") → "70 تجمّع هُجّر سنة 1948 بقضاء/لواء الرملة — 65 فلسطيني، 5
مختلط. منها: المنصورة، النبي روبين، القبيبة…"; conflict adds "7,071 state-based events 1989–2024, 55,490 deaths…; 262
journalists (no dates in the source)". tests/test_held_events.py (7; one live, skips until 083); full suite 1235 passed.
2026-09-25 21:30 UTC · P1-B.1 LIVE (083 applied + API restarted by Zaid 21:16) + follow-up · done · proof: through the public
connector `databank(displacement)` → "589 تجمّع هُجّر بين 1935 و1967 … حسب لواء 1945 … الرقم مع كل تجمّع هو عدد سكانه سنة
1945 (كل السكان)، مش عدد اللاجئين"; production passes tests/test_held_events.py + databank/facades/testers (105). Seen in the
live payload and fixed: 28 localities v1 had filed on a governorate or a same-named town (Imwas, Bayt Nuba, al-Latrun →
"رام الله") re-linked to their own Palestine Open Maps rows (`ops/relink_depopulated_localities.py --apply`, prior place_id
kept) → Ramle subdistrict 70 → 77, unclassified group 32 → 4; the payload's event_summary no longer offers a sum of 1945
populations (route change → next API restart).
2026-09-25 22:05 UTC · P0-B.4 + P0-B.5 route cautions from the rest of Tier 1 + the audit's four cases · done on master,
waits for the API restart · proof: the route now also reads (a) believed incidents placed on a NAMED place within 2 km in
the last 3 h (closure/siege/raid/settler attack/shooting) — live on dev: Ramallah→Nablus "قرب الطريق بآخر 3 ساعات: اقتحام
ببيتا (قبل ساعة، 844 متر عن المسار)" / "raid in Beita (1h ago, 844 m off the route)"; (b) road_closure readings within 3
km (none current today); (c) OCHA's 431 recorded obstacles (v1's restrictions.geojson, verified 2025-12) — measured: 22 sit
within 200 m of Road 60 and almost all block a VILLAGE's access to it, so they are named only within 300 m of the origin or
destination. All three are cautions, never blockers. tests/test_route_audit_cases.py (7): 16:47, 16:24, 15:27 and 09:00
replayed with the audit's numbers — none reads open, the 09:00 decayed row does not block.
2026-09-25 22:50 UTC · P1-B.2 honesty fixes + P1-B.6 cache · done on master, waits for `db/migrate.sh` (086) + API restart ·
proof: (1) PCBS (audit DATABANK-01/F026): 086 closes the 1,856 v1_pcbs_pcbs rows byte-identical to economic's World Bank
rows (never deleted), moves the dataset and its 204 unique rows to the worldbank source under `economic`, makes the 116
real pcbs.gov.ps rows the `pcbs` category (renamed), and pcbs.yaml is `migrate: false` so the frozen v1 file cannot
re-insert the copies (rolled-back dry run: 1,856 closed; pcbs = pcbs_direct only; 0 double counts). (2) serve warnings:
indicator_def.serve_warning(_ar); casualties.annual_total now says it EXCLUDES the Gaza war dead in both answers. (3)
ZAID-10 enforced: a partner payload drops rows graded ask/no-redistribution (OCHA demolitions/casualties, HaMoked,
Addameer, Peace Now, Good Shepherd, IODA, heritage — 3,716 of 214,689 rows) with a named count in the licence block AND
the spoken answer; the cited figure stays (066's line); the house tier is not cut. (4) unknown category → 404 with the
real list (the route smoke test had been requesting the literal "{category}" and passing vacuously — fixed). (5) the
cumulative refusal pointed at a /v2/databank/flow route that never existed → detrend=diff. (6) demolition indicators
defined. (7) scout: 7 sources listed "adopted" with no dataset (ACLED, Insecurity Insight, AWSD, FAO DIEM, healthsites, HDX
HAPI, ReliefWeb) moved to `listed_never_landed`. P1-B.6: the databank cache is keyed on the last load that WROTE rows +
a watermark that sees inserts and held events; dry runs (2,258 of 3,545 ledger records) no longer invalidate it; TTL 60 s
→ 6 h as a bound; categories warm 0.1 ms. Full suite 1243 passed + 3 by-design test updates.
