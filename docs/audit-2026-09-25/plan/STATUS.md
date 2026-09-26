# Status of the audit fix plan — what is done, what is open

Generated 2026-09-25 from the plan files and the fix commits on `claude/system-analysis-complete-mzpu2r`.
Read this before starting an area: a task marked **done** is fixed and has a test that failed before the change;
do not redo it. **partial** says what is left. Everything is proven only on the schema-only local database and
offline fixtures — none of it is live until `HANDS-NEEDED.md` is worked through on main-server.

**Confirmed tasks: 147 done · 5 partial · 8 open** (of 160; 2026-09-26: DATABANK-03/-04 + V09/V11 in `6e47e60`, DATABANK-02 + V08 in `b28948a`). Main-server 2026-09-25 09:50 UTC: the branch is merged to master and live for the timers (see `HANDS-NEEDED.md` top); CLASSIFIER-16 (F206) done in `f572be8`; the ROUTE age regression fixed in `5d55ed8`. Local suite: 927 passed / 99 failed; the 99 are the baseline's production-data and live-API tests (the baseline was 821 / 99).

## Commits

| commit | what | findings |
|---|---|---|
| `74d914b` | parser: closures, questions and forecasts no longer read as open | F001 F005 F006 F002 F003 F019 F020 F021 F013 F022 F014 F023 F015 F024 |
| `d952350` | route: G2 coverage, doubts for slow, direction reconciliation; exit closures always spoken | F071 F318 F320 F011 |
| `932004f` | belief: the both row is the worse direction; crowd never feeds incidents; a stranger cannot blind a channel | F008 F016 F377 F012 F017 |
| `c530211` | renderers: per-direction ages, honest not-found, no closure behind an unknown direction | F009 F035 F044 F045 F046 F049 F050 F052 F053 |
| `1d5115c` | renderers: crossings decayed vs no source; place_profile window, kind, anchor, age, failures | F010 F055 F058 F059 F060 |
| `a348ccf` | transport: bounded batches/bodies, tokens die with their key, PKCE required, SSE reset | F078 F088 F087 F357 F359 F396 F402 F031 |
| `f650da8` | rest: read paths never learn, crowd notes are not news, max_lag and note bounded | F076 F081 F085 F075 F079 F077 F083 |
| `be66fb2` | classifier 1.9.0: a reopening is not a closure; bounded regexes | F039 F074 |
| `646746c` | classifier: a re-read no longer duplicates closure observations | F205 |
| `3d77f79` | ingest: poller honours FloodWait resolving/downloading, fails with nothing resolved, atomic cursor | F042 F224 F226 F218 |
| `f5fd58d` | ingest: the v1 import cursor is its own and re-reads behind itself | F007 |
| `6e47e60` | databank: demolition ladder runs; indistinguishable copies kept; same-run conflicts; crashes isolated | F028 F029 F135 F137 |
| `b28948a` | databank: a complete source's withdrawn rows close; value_num keys need a declaration | F027 F134 |

Docs-only commits: `d273191` (the plan), `7188a2f`, `81d0b1f` (rollout runbook), and the commit that adds this file.

## Per area

### 01 · Checkpoint status parser (the sign of every road fact) — `01-parser.md`

14 done · 0 partial · 0 open of 14 confirmed; 0 of 15 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| PARSER-01 | F001 | critical | **done** | `74d914b` | 'ما' as the conjunction in بعد ما / قبل ما / زي ما / حسب ما / كل ما is read as a negator and fl |
| PARSER-02 | F005 | critical | **done** | `74d914b` | 'ما' as a relative particle is read as a negator and inverts closed to open |
| PARSER-03 | F006 | critical | **done** | `74d914b` | Uncertainty and conditionals without an interrogative particle are asserted as open |
| PARSER-04 | F002 | critical | **done** | `74d914b` | Negators are not recognised behind a fused waw or in fused spellings, so 'ومش سالك' serves OPEN |
| PARSER-05 | F003 | critical | **done** | `74d914b` | An emoji-only per-direction line collapses to one 'both' reading and the FIRST emoji in dict or |
| PARSER-06 | F019 | high | **done** | `74d914b` | 'فتح النار' (opened fire) is read as the checkpoint being open |
| PARSER-07 | F020 | high | **done** | `74d914b` | Dual/plural/dialect closure forms and 'ممنوع/منع الدخول' are not in the lexicon, so closures ar |
| PARSER-08 | F021 | high | **done** | `74d914b` | 'The closure was lifted / the jam is over' asserts closed or congested and restarts the closure |
| PARSER-09 | F013 | high | **done** | `74d914b` | 'راح' (dialect future particle) is a CLEARING word: 'راح يسكروا الحاجز' (they are going to clos |
| PARSER-10 | F022 | high | **done** | `74d914b` | 'X سالك ولا لا' (a question) reads as open, while 'X سالك ولا زحمة' (a reassurance) reads as a  |
| PARSER-11 | F014 | high | **done** | `74d914b` | 'لا يوجد جيش' and 'لا جيش ولا تفتيش' record the army PRESENT; a negator after the noun ('الجيش  |
| PARSER-12 | F023 | high | **done** | `74d914b` | Negated existentials in the commonest spellings ('مافي', 'مفيش', 'لا يوجد', 'لا X ولا Y', 'ما ف |
| PARSER-13 | F015 | high | **done** | `74d914b` | A clearing verb never clears a FLOW noun: 'انتهت الازمه' / 'خلصت الازمه' / 'راحت الازمه' serve  |
| PARSER-14 | F024 | high | **done** | `74d914b` | Clearing verbs used as future/aspect markers ('راح ي…', 'تركوا') infer `open` |

### 02 · Belief engine, serving views, crowd engine (SQL + Python) — `02-belief.md`

5 done · 0 partial · 0 open of 5 confirmed; 0 of 28 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| BELIEF-01 | F012 | critical | **done** | `932004f` | Crowd-report notes are classified into believed incidents and road_closure states (feeds_incide |
| BELIEF-02 | F008 | critical | **done** | `932004f` | checkpoint_serving's 'both' row ignores direction-specific readings, so the default answer can  |
| BELIEF-03 | F016 | high | **done** | `932004f` | checkpoint_serving's 'both' travel row (the default for every caller) never sees explicit direc |
| BELIEF-04 | F017 | high | **done** | `932004f` | Any anonymous crowd account can overwrite a channel's fresh reading with a caution and blind th |
| BELIEF-05 | F377 | medium | **done** | `932004f` | The direction merge in checkpoint_serving (a fresher `both` reading overrides an older explicit |

### 03 · Route verdict (corridor) — `03-route.md`

4 done · 0 partial · 0 open of 4 confirmed; 0 of 14 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| ROUTE-01 | F071 | high | **done** | `d952350` | `likely_open` is produced with coverage far below G2's 0.6 on routes shorter than ~25 km: the c |
| ROUTE-02 | F318 | medium | **done** | `d952350` | `slow` asserts the road is passable (سالك) without the coverage or exit-closure checks that `op |
| ROUTE-03 | F320 | medium | **done** | `d952350` | The corridor reconciles directions differently from checkpoint_serving: a stale direction-speci |
| ROUTE-04 | F322 | medium | **partial** | `d952350` | `passes` does not label settlements and lists Hebrew/Latin-only names; the ledger marks P0-A.4  — *Hebrew/Latin-only names dropped from `passes`; the settlement LABEL needs a data source (HANDS-NEEDED §5)* |

### 04 · MCP tool answers (Arabic + English renderers, façades) — `04-renderers.md`

26 done · 2 partial · 1 open of 29 confirmed; 0 of 37 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| RENDERERS-01 | F009 | critical | **done** | `c530211` | checkpoint_status ignores a fresh direction-specific closure when the other direction is unknow |
| RENDERERS-02 | F011 | critical | **done** | `d952350` | Exit closures are spoken in NEITHER language unless the verdict is `unverified` — the audit's 1 |
| RENDERERS-03 | F010 | critical | **done** | `1d5115c` | place_profile anchors on one resolver and reads live checkpoint state through another, with no  |
| RENDERERS-04 | F044 | high | **done** | `c530211` | The direction-split checkpoint sentence carries no age in either language |
| RENDERERS-05 | F045 | high | **done** | `c530211` | EN checkpoints_near turns 'place not resolved' into 'No recent checkpoint reports around None' |
| RENDERERS-06 | F046 | high | **done** | `c530211` | EN incidents_near turns 'place not resolved' into 'No incidents recorded around None in the las |
| RENDERERS-07 | F047 | high | **done** | `81acc75` | news façade silently drops place/kind in search mode and hours in newest mode; declared limit d |
| RENDERERS-08 | F049 | high | **done** | `c530211` | checkpoint_status blurs 'unknown name' with 'known checkpoint that has never been read' |
| RENDERERS-09 | F035 | high | **done** | `c530211` | MCP checkpoint_status omits the reading's age whenever inbound and outbound differ (Arabic and  |
| RENDERERS-10 | F050 | high | **done** | `c530211` | The direction-split answer carries no age at all |
| RENDERERS-11 | F051 | high | **done** | `81acc75` | Per-call boilerplate notes the plan moved to the reading-contract resource are still attached t |
| RENDERERS-12 | F052 | high | **done** | `c530211` | checkpoints (near) lists flows with no age, and says '0 checkpoints in the area but their news  |
| RENDERERS-13 | F053 | high | **done** | `c530211` | incidents_near speaks a village_ambiguous event as if it happened in the governorate city |
| RENDERERS-14 | F054 | high | **done** | `81acc75` | Façade arguments are forwarded past the REST validation caps and turn into tool errors instead  |
| RENDERERS-15 | F055 | high | **done** | `1d5115c` | crossings says 'no source at all' when every sourced crossing has merely decayed |
| RENDERERS-16 | F056 | high | **done** | `81acc75` | can_i_travel never speaks the age of its evidence and leaks an English verdict token into the A |
| RENDERERS-17 | F057 | high | **open** |  | Route waypoints are not labelled as settlements although the ledger marks P0-A.4 done |
| RENDERERS-18 | F058 | high | **done** | `1d5115c` | place_profile's hourly pattern still uses the legacy mixed `checkpoint_status` kind |
| RENDERERS-19 | F059 | high | **done** | `1d5115c` | place_profile never shows incidents for days > 7: hours=days*24 exceeds the REST cap and the 42 |
| RENDERERS-20 | F060 | high | **done** | `1d5115c` | Swallowed REST failures render as 'no recent information about it' |
| RENDERERS-21 | F061 | high | **done** | `81acc75` | series/trend declares and accepts `days` but never applies it |
| RENDERERS-22 | F062 | high | **done** | `81acc75` | databank headline's 'series from X to Y' is computed over the returned page, not the series |
| RENDERERS-23 | F268 | medium | **partial** | `81acc75` | Composite tools have no overall deadline: up to six sequential 30 s calls per request | — *api() 8 s per call, about() degrades to `partial`; the wall-clock bound on `_handle` is still open*
| RENDERERS-24 | F305 | medium | **done** | `81acc75` | `series(..., days=N)` is declared in the façade schema and ignored by `trend`; ledger P0-A.1 ma |
| RENDERERS-25 | F269 | medium | **done** | `81acc75` | about() counts every `place` row of kind checkpoint as 'tracked', not the servable set |
| RENDERERS-26 | F270 | medium | **done** | `81acc75` | The stdio transport still diverges from HTTP: no ping, no instructions, no outputSchema, no lic |
| RENDERERS-27 | F271 | medium | **done** | `81acc75` | test_absorbed_names_are_off_the_menu_but_still_answer cannot fail: the envelope never has a top |
| RENDERERS-28 | F504 | low | **partial** | `81acc75` | Arabic age phrases ignore dual/plural and can go negative; flow vocabulary differs per tool | — *counted ages (dual/plural, negatives → الآن) done; one flow/event lexicon across renderers still open*
| RENDERERS-29 | F505 | low | **done** | `81acc75` | correlate's `answer` is English in two of its three modes |

### 05 · MCP transport, OAuth, rate limit, SSE, licence — `05-transport.md`

10 done · 0 partial · 0 open of 10 confirmed; 0 of 36 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| TRANSPORT-01 | F086 | high | **open** |  | ZAID-10 partner tiers `filtered` and `cited_fact_only` are labels only: nothing filters databan |
| TRANSPORT-02 | F048 | high | **open** |  | No per-tool payload byte cap exists, and every reply is serialised twice (text + structuredCont |
| TRANSPORT-03 | F087 | high | **done** | `a348ccf` | OAuth tokens skip the per-key quota and never re-check the key: a revoked partner key keeps its |
| TRANSPORT-04 | F088 | high | **done** | `a348ccf` | One POST can carry an unbounded JSON-RPC batch: quota, limiter and body size are all counted pe |
| TRANSPORT-05 | F078 | high | **done** | `a348ccf` | JSON-RPC batches bypass the rate limiter and the per-key daily quota; request body and batch si |
| TRANSPORT-06 | F301 | medium | **open** |  | Licence-grade refresh runs three full-table scans on the MCP request path once a minute, ahead  |
| TRANSPORT-07 | F357 | medium | **done** | `a348ccf` | OAuth tokens skip the daily quota and key revocation; refresh tokens are never rotated, not bou |
| TRANSPORT-08 | F396 | medium | **done** | `a348ccf` | _save() rewrites .keys/oauth-state.json with mode 0644 on every token issue, so the planned chm |
| TRANSPORT-09 | F359 | medium | **done** | `a348ccf` | PKCE is optional and dynamic registration is open with any redirect_uri, while the consent page |
| TRANSPORT-10 | F402 | medium | **done** | `a348ccf` | A dropped slow SSE subscriber is never disconnected: it keeps receiving keepalives forever and  |

### 06 · REST API handlers (serve/app.py), correlation statistics, precision annotation — `06-rest.md`

18 done · 2 partial · 0 open of 20 confirmed; 0 of 78 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| REST-01 | F070 | high | **done** | `36f75a8` | checkpoint_status still answers the nearest Latin lookalike for any spelling 074 did not list,  |
| REST-02 | F089 | high | **done** | `36f75a8` | checkpoints/summary counts only direction='both' rows, so a checkpoint closed in one direction  | — *079 made the default row the worse direction; closed_now rows now carry reported_for + differs_by_direction*
| REST-03 | F075 | high | **done** | `f650da8` | Crowd-report text is served verbatim as the newest 'news' and quoted into the spoken `answer` ( |
| REST-04 | F079 | high | **done** | `f650da8` | Crowd reports (and their free-text notes) are served as public news on /v2/news/latest and quot |
| REST-05 | F034 | high | **done** | `36f75a8` | insights counts governorate-fallback events under the city although the ledger records P0-C.2 ( |
| REST-06 | F080 | high | **done** | `36f75a8` | /v2/insights counts governorate-only incidents (pinned at the city centroid) as events around t |
| REST-07 | F076 | high | **done** | `f650da8` | Public read routes and the crowd path write to the gazetteer: resolve_place(learn=True) inserts |
| REST-08 | F081 | high | **done** | `f650da8` | /v2/insights writes to place_alias on a public read path (learn=True) — ledger says P0-A.2 done |
| REST-09 | F085 | high | **done** | `f650da8` | /v2/insights still calls resolve_place with learn=True, so every test run writes into the produ |
| REST-10 | F082 | high | **done** | `36f75a8` | Incident CSV/GeoJSON exports drop place_precision/named_place: governorate-only events export a |
| REST-11 | F030 | high | **done** | `36f75a8` | Litre-priced food series are served labelled `ILS_per_kg`: the value is converted per litre by  |
| REST-12 | F043 | high | **done** | `36f75a8` | Pairwise correlation collapses multi-row dates with 'last row wins', so the served rho for brea | — *the median per date, stated in caveats (the audit's aggregate option), not a refusal*
| REST-13 | F077 | high | **done** | `f650da8` | `max_lag` is unbounded: one request pins a worker thread for hours; 40 such requests block ever |
| REST-14 | F083 | high | **done** | `f650da8` | /v2/databank/correlate max_lag is unbounded: one request can hold a worker thread for minutes ( |
| REST-15 | F293 | medium | **partial** | `36f75a8` | One connection per statement against max_connections=20: the real concurrency ceiling is ~17 se | — *pool wired behind an optional psycopg_pool import (PG_POOL_MAX); Zaid: `pip install psycopg-pool` in .venv + max_connections in db/tuning.sql*
| REST-16 | F287 | medium | **partial** | `36f75a8` | No connection pool against max_connections=20: each query opens a connection, /health opens fiv | — *same pool; /health cached 10 s via watchdog.all_checks; the fuel queries are gone*
| REST-17 | F288 | medium | **done** | `36f75a8` | /health evaluates only the job and feed families; capacity, v1-db, Valhalla, gateway and fuel-p |
| REST-18 | F296 | medium | **done** | `36f75a8` | `_resolve_checkpoint` aggregates every checkpoint_flow observation ever stored on every checkpo |
| REST-19 | F143 | medium | **done** | `36f75a8` | /v2/databank/{category} reads licence and attribution from `source`, bypassing the 054 dataset- |
| REST-20 | F251 | medium | **done** | `36f75a8` | Only the `cumulative` label is refused: two unrelated trending `stock` series read as 'a very s |

### 07 · Incident classifier and event writer — `07-classifier.md`

17 done · 0 partial · 0 open of 17 confirmed; 0 of 44 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| CLASSIFIER-01 | F039 | high | **done** | `be66fb2` | A reopening report is served as a closure and writes road_closure='closed' |
| CLASSIFIER-02 | F074 | high | **done** | `be66fb2` | Catastrophic backtracking in the settler_attack pattern: one 4 KB token stalls the classifier f |
| CLASSIFIER-03 | F072 | high | **done** | `c178d67` | Four writers bypass the modality filter and the P2.4 crowd gate for crowd-reportable kinds (pow |
| CLASSIFIER-04 | F033 | high | **done** | `c178d67` | News-channel mirrors are counted as independent sources: independence_group is never fitted for |
| CLASSIFIER-05 | F040 | high | **done** | `c178d67` | No time is read from the text: 'مساء أمس' incidents and closures get the posting time and are s |
| CLASSIFIER-06 | F041 | high | **done** | `c178d67` | A house siege writes road_closure='closed' for the whole village |
| CLASSIFIER-07 | F096 | medium | **done** | `c178d67` | The closure rule's clause guard `[^.،؛]{0,40}` is dead — normalize() removed every full stop an |
| CLASSIFIER-08 | F097 | medium | **done** | `c178d67` | Settler verbal nouns اقتلاع / احراق / تخريب / تحطيم and the verb قطع (trees) do not contain the |
| CLASSIFIER-09 | F190 | medium | **done** | `c178d67` | Army action near a settlement is filed as a settler attack (actor inverted) |
| CLASSIFIER-10 | F192 | medium | **done** | `c178d67` | The bare verbal noun اعتقال never matches the arrest pattern |
| CLASSIFIER-11 | F099 | medium | **done** | `c178d67` | 'international' reject matches اليمن inside اليمنى (right hand/leg) and الاردن inside غور الارد |
| CLASSIFIER-12 | F100 | medium | **done** | `c178d67` | 'statement', 'court', 'legal' and 'gaza' rejects fire on unanchored short branches: طالب (stude |
| CLASSIFIER-13 | F196 | medium | **done** | `c178d67` | 'مدخل <city>' loses both the governorate and the place: entrance closures of Nablus/Jenin are d |
| CLASSIFIER-14 | F203 | medium | **done** | `c178d67` | Cross-batch dedup re-introduces the 'anchored on the first report' defect: long streams split a |
| CLASSIFIER-15 | F205 | medium | **done** | `646746c` | Closure observations are re-inserted on every join and every re-read: a version bump without -- |
| CLASSIFIER-16 | F206 | medium | **done** | `f572be8` | Events are hard-deleted outside the versioning trigger: no history, as-of replay and cached eve |
| CLASSIFIER-17 | F477 | low | **done** | `c178d67` | The 'stable' key is overwritten on every join, so it no longer names the first claim and the le |

### 08 · Place resolution and gazetteer tooling — `08-gazetteer.md`

4 done · 0 partial · 0 open of 4 confirmed; 0 of 20 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| GAZETTEER-01 | F067 | high | **done** | `d19a3b2` | A twin promoted through attrs.twin_keys is invisible to every caller without a governorate hint |
| GAZETTEER-02 | F068 | high | **done** | `d19a3b2` | The resolver learns from untrusted and quarantined callers by default, launders a guess into an — *read paths and resolve_for_state_kind no longer learn; resolve_place still defaults learn=True (08-gazetteer)* |
| GAZETTEER-03 | F069 | high | **done** | `d19a3b2` | load_gazetteer.py TRUNCATE ... CASCADE would empty every observation table, and its pcode table |
| GAZETTEER-04 | F315 | medium | **done** | `d19a3b2` | place_merge steals aliases from other places with ON CONFLICT DO UPDATE, contrary to every othe |

### 09 · Telegram poller and ingestion framework (the scarce account) — `09-ingest.md`

9 done · 0 partial · 2 open of 11 confirmed; 1 of 22 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| INGEST-01 | F007 | critical | **done** | `f5fd58d` | The v1 import cursor is MAX(observed_at) of a kind the crowd also writes with now(), and v1 row |
| INGEST-02 | F213 | medium | **done** | `95a4b6f` | Hard rule 4 (one Telethon client per session file) is enforced by nothing: discovery, --status  |
| INGEST-03 | F217 | medium | **done** | `95a4b6f` | The poller still downloads every @palhubappfuel photo (hundreds to ~1,000 GetFile requests and  |
| INGEST-04 | F218 | medium | **done** | `3d77f79` | Cursor state file is written non-atomically and only on cycles that stored something; a truncat |
| INGEST-05 | F219 | medium | **open** |  | Source identity and the poll cursor are keyed on the mutable Telegram username, not the channel |
| INGEST-06 | F221 | medium | **done** | `95a4b6f` | Forwarded messages are recorded (attrs.fwd_from) but never used: a report forwarded through N n |
| INGEST-07 | F222 | medium | **open** |  | Message edits and deletions are invisible: a corrected or retracted report keeps feeding events |
| INGEST-08 | F223 | medium | **done** | `95a4b6f` | The exit-2 'deauthorised, do not restart' path is dead: startup deauth returns 1, and the mid-r |
| INGEST-09 | F225 | medium | **done** | `95a4b6f` | A database outage is treated as a channel failure: Telegram is polled and media downloaded ever |
| INGEST-10 | F226 | medium | **done** | `3d77f79` | A poller with zero resolved channels beats a healthy heartbeat forever; a channel that fails to |
| INGEST-11 | F438 | low | **done** | `95a4b6f` | Fuel-station locality anchor is resolved with no kind preference and an existing station is ret |
| INGEST-V13 | F224 | medium | **done** | `3d77f79` | get_entity FloodWait at startup is swallowed and the loop keeps resolving the remaining channel |

### 10 · External feed parsers (fuel prices, MoH Gaza, power, weather, connectivity, fires) — `10-feeds.md`

7 done · 0 partial · 0 open of 7 confirmed; 0 of 18 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| FEEDS-01 | F036 | high | **done** | `f05f9bf` | One outlet can self-corroborate a fuel price: its RSS item is a claim and its page is a web uni |
| FEEDS-02 | F037 | high | **done** | `f05f9bf` | A power cut keeps being served for ~22 hours after its announced end |
| FEEDS-03 | F038 | high | **done** | `f05f9bf` | power.py's state_current rebuild ignores modality, so a future scheduled cut is served as activ |
| FEEDS-04 | F073 | high | **done** | `f05f9bf` | power.py rebuilds state_current from 'scheduled' rows: a future announced cut is served as an a |
| FEEDS-05 | F174 | medium | **done** | `f05f9bf` | A comma decimal ('8,15 شيكل') is split as a clause boundary and the tail reads as a wrong price |
| FEEDS-06 | F176 | medium | **done** | `f05f9bf` | MoH cascade parser files an unknown section's totals under the previous tier (the 72,274-in-one |
| FEEDS-07 | F182 | medium | **done** | `f05f9bf` | MoH ingest overwrites revised values and clobbers reported_at on every hourly run |

### 11 · Operability: watchdog, alerts, backups, shell steps, systemd units — `11-ops.md`

15 done · 0 partial · 1 open of 16 confirmed; 0 of 21 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| OPS-01 | F063 | high | **open** |  | The unattended maintainer is an internet-reading agent with --dangerously-skip-permissions and  |
| OPS-02 | F064 | high | **done** | `d34217d` | mcp-audit.sh hands OK_EXIT_CODES to the audit process instead of the wrapper: every critical ni |
| OPS-03 | F065 | high | **done** | `d34217d` | The Valhalla IP sync — the fixer for the routing outage that already happened — has no OnFailur |
| OPS-04 | F066 | high | **done** | `d34217d` | A watchdog crash and a watchdog that found a fault are the same exit code, so the watchdog cann |
| OPS-05 | F272 | medium | **done** | `d34217d` | OnFailure alarms have no dedup or rate limit — a 2-minute timer that keeps failing pushes 30 no |
| OPS-06 | F273 | medium | **done** | `d34217d` | The 'monthly' full bronze set is cut every ~8 days because the last-full reference is read from |
| OPS-07 | F274 | medium | **done** | `d34217d` | Backup pruning runs after the upload it must make room for, and the first-of-month rule pins ev |
| OPS-08 | F275 | medium | **done** | `d34217d` | databank-sync.sh keeps six `\|\| echo` steps whose only reader is the weekly maintainer that has  |
| OPS-09 | F276 | medium | **done** | `d34217d` | The as_of vault's index files and manifest, and the partner-key store, are not in the backup se |
| OPS-10 | F345 | medium | **done** | `d34217d` | repair_generations.py's demolitions rule deletes every current row ingested since 2026-08-07 —  |
| OPS-11 | F277 | medium | **done** | `d34217d` | The weekly restore test never restores bronze or the full+increment chain — only the DB dump is |
| OPS-12 | F278 | medium | **done** | `d34217d` | sync-valhalla-ip.sh rewrites the single secrets file non-atomically every 15 minutes, and resta |
| OPS-13 | F283 | medium | **done** | `d34217d` | Feed freshness ignores modality: palhub's quarantined checkpoint_flow rows keep the served chec |
| OPS-14 | F284 | medium | **done** | `d34217d` | A feed alarm is auto-resolved with a 'recovered' push when its collector degrades, although the |
| OPS-15 | F285 | medium | **done** | `d34217d` | A failed delivery is never retried and nothing ever proves the doorbell works — a dead ntfy tok |
| OPS-16 | F286 | medium | **done** | `d34217d` | The heartbeat records the attempt only after the job returns, so a job killed by TimeoutStartSe |

### 12 · Tier 2 databank loader, mappings, export — `12-databank.md`

0 done · 0 partial · 5 open of 5 confirmed; 0 of 32 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| DATABANK-01 | F026 | high | **open** |  | The open-data release ships 2,060 World Bank rows as `by-source/pcbs.csv.gz` credited to PCBS |
| DATABANK-02 | F027 | high | **done** | `b28948a` | value_num inside the identity makes a publisher revision an un-supersedable second current row  |
| DATABANK-03 | F028 | high | **done** | `6e47e60` | t_demolitions has no lat/lon rung: since v1 dropped admin2_pcode (frozen 2026-08-08), all 516 l |
| DATABANK-04 | F029 | high | **done** | `6e47e60` | A fresh real load of an `indistinguishable` dataset silently drops every identical-content row  |
| DATABANK-05 | F133 | medium | **open** |  | Event identity excludes dyad, actors and the source's own id, and has no injectivity invariant: |
| DATABANK-V09 | F135 | medium | **done** | `6e47e60` | Two same-identity rows with different content in one run: None reached the supersede list and both rows one key (reproduced, fixed) |
| DATABANK-V11 | F137 | medium | **done** | `6e47e60` | run_all isolated only SpecRefused; any other exception skipped every later category (reproduced, fixed) |
| DATABANK-V08 | F134 | medium | **done** | `b28948a` | Upstream deletions never superseded: opt-in `identity.generation: complete` closes what a whole-publication source stopped sending, capped (reproduced in production, fixed) |

### 13 · Learning loop, analyst, self-measurement — `13-learning.md`

4 done · 0 partial · 0 open of 4 confirmed; 0 of 30 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| LEARNING-01 | F004 | critical | **done** | `908d08d` | Nightly copy-collapse can lift a crowd submitter out of crowd:unverified, granting independence |
| LEARNING-02 | F229 | medium | **done** | `908d08d` | Plan/ledger present '196/199' as the deterministic MoH reader's score; it is a brain model's ag |
| LEARNING-03 | F110 | medium | **done** | `908d08d` | Loop A can never record a miss in a two-unit bucket and scores each unit against a consensus th |
| LEARNING-04 | F242 | medium | **done** | `908d08d` | The nightly accuracy audit calls tool functions in-process; answer_en is only attached by the t |

### 14 · Documentation a partner or a new session follows — `14-docs.md`

0 done · 1 partial · 9 open of 10 confirmed; 0 of 28 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| DOCS-01 | F031 | high | **done** | `db5c400` | PARTNER-API promises one-revocation and 90-day refresh; OAuth tokens skip key revocation, skip  — *code now matches PARTNER-API (one revocation, 90-day refresh); the doc itself not re-read* |
| DOCS-02 | F084 | high | **done** | `db5c400` | No test that a --rebuild preserves event ids; the stable-key path has no test at all while the  |
| DOCS-03 | F146 | medium | **done** | `db5c400` | ATTRIBUTION.md lists IODA and OONI as 'redistributable, commercially or otherwise'; the registr |
| DOCS-04 | F150 | medium | **done** | `db5c400` | README 'Running it' fails at every step: no requirements.txt, compose file not at the root, mig |
| DOCS-05 | F153 | medium | **done** | `db5c400` | PARTNER-API.md teaches the retired 28-tool surface (§3, §8, §9, try-ten-calls.sh) as the integr |
| DOCS-06 | F155 | medium | **done** | `db5c400` | Ledger marks P0-A.2 (answer contract) done; tests/test_answer_contract.py does not exist and /v |
| DOCS-07 | F245 | medium | **done** | `db5c400` | Ledger marks P0-A.2 'answer contract, enforced' done but tests/test_answer_contract.py does not |
| DOCS-08 | F379 | medium | **done** | `db5c400` | Ledger marks P0-A.2 done but tests/test_answer_contract.py does not exist and the call/payload  |
| DOCS-09 | F159 | medium | **done** | `db5c400` | ops/systemd/README.md install procedure enables a retired timer and never starts 10 of the 19 t |
| DOCS-10 | F279 | medium | **done** | `db5c400` | The systemd README a rebuild would follow enables a retired timer and omits ten live ones; its  |

### 15 · Public web pages (serve/webapp) — `15-webapp.md`

4 done · 0 partial · 0 open of 4 confirmed; 0 of 13 verify-first done.

| task | finding | severity | status | commit | title |
|---|---|---|---|---|---|
| WEBAPP-01 | F090 | high | **done** | `908d08d` | pulse.html pairs the worst flow with the freshest row's age, so a three-hour-old closure can re |
| WEBAPP-02 | F091 | high | **done** | `908d08d` | pulse.html's SSE consumer is dead: `es.onmessage` never fires for named events, and it reads fi |
| WEBAPP-03 | F092 | high | **done** | `908d08d` | Pages fetch once and never refresh: age strings freeze and decay events are ignored, so a stale |
| WEBAPP-04 | F413 | medium | **done** | `908d08d` | A failed or rate-limited fetch leaves a silent '…' / hint panel that reads as 'no closures', wi |

## Refuted findings that were still worth a change

- F042 (FloodWait during media download): refuted as a wire storm (Telethon's own flood guard), but the batch was
  stored without media and the cursor moved past it; fixed in `3d77f79`.

