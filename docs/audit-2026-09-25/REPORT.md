# System audit 2026-09-25 — partial report

23 subsystem readers produced 605 findings. 160 were confirmed by independent adversarial verifiers (12 critical, 76 high, 68 medium, 4 low), 9 were refuted, and 436 are reader-reported only and NOT independently verified.

Sections written: verdict, architecture, accuracy, safety-logic. The data-integrity, security, operability, performance and roadmap sections were not written (usage limit). Every confirmed finding, with its evidence and the verifier's reasoning, is in `confirmed-findings.json`; `digest.md` lists them by severity.

## Verdict and the ten things that matter most

### Verdict

palestine-v2 is built on the right ideas and implements most of them well. Its failures cluster where Arabic text becomes a fact and where anonymous input can write. The serving core is genuinely strong:

- The three serving gates (confidence floor, cadence-relative staleness, absolute assert ceiling) live in SQL views the API cannot bypass (`db/migrations/026:97-102`), and the decay exponents are guarded at the input (`010:27-29`).
- Belief is one implementation behind an advisory lock. It uses a per-unit noisy-OR, trust earned through the Wilson lower bound, and a P2.4 asymmetry that points the right way (`resolve/belief.py`, `030:125`).
- Absence is its own axis. Questions and unparsed lines are kept as modalities, not believed (`027`).
- `claim` stays immutable.
- Measured precision is served beside every incident count (`serve/quality.py`), from precision rounds whose disjointness the code enforces (`learn/incident_precision.py:183-197`).
- The databank spec registry refuses unknown keys and supersedes a row in one transaction.
- The poller pages contiguously and honours FloodWait.
- No SQL injection was found.

The doctrine "never send someone toward a closed checkpoint" is enforced downstream of the component that decides what a message says, and that component is where it breaks. `cascade/checkpoint_text.py` reads ordinary Palestinian phrasing as `open` at 0.8–0.9: a relative ما, a waw-fused مش, "if it opens", "they're going to close it", "opened fire". Nothing downstream catches it, for three reasons:

- belief serves the single freshest assertion (`resolve/belief.py:116-122`);
- dissent discounts that assertion by at most 25 % (`:188`);
- the P2.4 gate holds back only crowd sources (`:199-203`).

The lead session verified that three independent "closed" reports lose to one later curated "open", which is served at 0.69.

Four structural problems sit behind the rest:

- The open crowd endpoints reach four places the gate does not guard. There are 0 submitters today (PLAN §4 R3).
- The default checkpoint answer discards direction-specific readings, which the plan's own P1-A.1 will make the majority.
- The §11 ledger overstates progress: about 30 confirmed findings contradict a 2026-09-24 17:05 "done".
- The database cannot be rebuilt from the repository.

121 of the 160 confirmed findings can be fixed without main-server, most in a few lines plus a regression test.

### The ten findings that matter most

Ranked by what a traveller or the archive would suffer. Findings that share a root cause are grouped under one lead id.

1. **F005 · F001 · F002: the checkpoint parser negates the wrong word (critical, NEW).**
   - **Defect:** `NEGATORS` includes the relative ما, and `_negated` exempts only ما زال (`cascade/checkpoint_text.py:154`, `:461-490`). A negator fused to a waw is never seen, because `:478` compares the raw token while `_lex` peels the و (`:255`).
   - **Probes:** 'زي ما هو مسكر' and 'حسب ما سمعت مسكر' give `open`@0.8. 'عطارة ومش سالك' gives `open`@0.9. 'سالك وما في جيش' gives army *present*.
   - **Why it matters:** this is the only parser for every v1 channel line (`ingest/sources/checkpoints.py:172`, 2-minute timer). With latest-wins belief and no gate on channels, one mis-read line replaces a real closure and is served as `passable=true`. How often it happens needs main-server.

2. **F006 · F013/F024 · F019 · F022 · F020: lines that are not reports are asserted as "open" (critical/high, NEW).**
   - **Defect:** `QUESTION_PHRASES` lacks ما بعرف / حدا بعرف, and nothing handles اذا/لو (`:192`). راح and تركوا count as clearing words (`:146`, `:631`). فتح/فتحوا are flow words even in فتح النار (`:62`). 'سالك ولا لا' passes as an assertion (`:353`).
   - **Probes:** 'ما بعرف اذا حوارة سالك' gives `open`@0.90. 'راح يسكروا الحاجز' gives `open`@0.72 with army absent. 'فتحوا النار على الشباب عند الحاجز' gives `open`.
   - **Also:** F020 (`:83`) finds مسكرين, مقفول, مغلقان and ممنوع الدخول missing from the lexicon. The closure is dropped and a stale `open` keeps serving.
   - **Why it matters:** a question, a hypothetical or a warning becomes evidence, and the bias lands on exactly the checkpoints people fear are closed.

3. **F011 · F071 (+F318): the route verdict still under-warns (critical, known; §11 17:05 marks P0-B.2/3 done).**
   - **Defect:** both renderers subtract exit closures from the near-miss warning (`serve/mcp_server.py:950-951`) and speak them only when the verdict is `unverified` (`:984`; `serve/mcp_en.py:133`, `:176-178`). A `slow`, `blocked` or `unknown` route never names a closed exit. This is the audit's 15:27 Za'tara/Ein Siniya case, reintroduced by 978ca3b.
   - **G2 not in the code:** G2's "coverage ≥ 0.6" is never checked. `_doubts` tests only `longest_gap_km >= 10` (`resolve/corridor.py:420-421`), so an 11 km route with coverage 0.10 reads `likely_open`. `slow` returns before `_doubts` runs (`:376-380`, F318).
   - **Why it matters:** can_i_travel gives one of the two answers PLAN §4 R2 says a traveller needs, and it is live now.

4. **F008 · F009 · F003: direction is lost on the default answer (critical; F008 and F003 NEW, F009's renderer defect unnamed).**
   - **Defect:** checkpoint_serving builds the `both` row only from readings filed as `both` (`db/migrations/027_absence_is_not_presence.sql:43`), and every default surface reads that row (`serve/app.py:562`, `:576`, `:602`, `:2144`).
   - **Example:** 'حوارة سالك' at 13:00, then 'حوارة مغلق للداخل ومغلق للخارج' at 14:05, serves `open`, and MCP says 'حوارة: سالك'.
   - **Renderer (F009):** checkpoint_status splits by direction only when both directions are known and differ (`serve/mcp_server.py:182`), so a fresh inbound closure hides behind a decayed `both`.
   - **Emoji lines (F003):** 'الداخل ✅ الخارج ❌' is stored as `open` for both directions. The first emoji in dict order wins (`cascade/checkpoint_text.py:617-621`).
   - **Why it matters:** only 9 % of readings are directional today (PLAN §4 R3). Shipping P1-A.1 (palhub promotion) before this fix turns a rare false open into the common case, and none of the promoted data would count toward G4.

5. **F012: an anonymous crowd note becomes a believed incident and a road closure (critical; not in the plan, and SECURITY-REVIEW §6 claims the opposite).**
   - **Defect:** crowd sources are created without `feeds_incidents` (`crowd/engine.py:120-128`), so the default `true` from `037:23` applies. The classifier reads every crowd note (`ingest/sources/news_incidents.py:423-435`), and a closure note writes road_closure='closed' at 0.7.
   - **Why it matters:** within five minutes a stranger puts "raid at Huwara" on `/v2/incidents/recent` and into the MCP answer. If the note lands inside the dedup window of a real event, it joins that event and is served as "2 sources".

6. **F004 · F017 · F072: the P2.4 crowd gate has three side doors (critical/high, NEW).**
   - **(a) Nightly independence fit.** The nightly `learn/source_independence.py --apply` measures every source with no kind filter and writes `independence_group=NULL` for singletons (`:144`, `:154-157`). That frees sock puppets from `crowd:unverified`. Two accounts clear `crowd_min_units=2` for `open` at 0.311, still 0.285 against a channel's "closed", which is above the floor. The intended writer of crowd groups, `learn/crowd_independence.py`, is scheduled nowhere.
   - **(b) Latest-wins.** One anonymous "closed" at 0.149 replaces a channel's fresh "open" and blanks the checkpoint to `unknown` (`resolve/belief.py:117-121`, `:212`).
   - **(c) Private rebuilds.** Three state_current rebuilds (`news_incidents.py:373-391`, `connectivity.py:163-175`, `power.py:339-351`) ignore both modality and the gate.
   - **Why it matters:** "independence is earned" holds only on the main path. `tests/test_crowd.py:102` sets the group by hand, so the suite cannot see (a).

7. **F007: the v1 checkpoint import skips rows forever (critical, NEW).**
   - **Defect:** the cursor is `MAX(observed_at)` over every `checkpoint_status` row (`ingest/sources/checkpoints.py:146-148`). Crowd reports on that same kind are stamped `now()` (`crowd/engine.py:271-276`; `030:126`), so any v1 row dated earlier fails `timestamp > ?` (`:155`) and is never imported.
   - **Why it matters:** the archive gets silent gaps, breaking hard rule 2. A skipped "closed" leaves an earlier "open" serving. One poster can starve the import. The only recovery is a manual `--full`.

8. **F010: `place` speaks another checkpoint's state under the town's name (critical, known; §11 marks P0-A.1 done).**
   - **Defect:** place_profile anchors on `/v2/geo/resolve`, where kind is a +3.0 bonus rather than a filter (`serve/mcp_server.py:1179-1182`; `resolve/geo.py:190-203`). It then re-fetches the live status by the raw string through a second, difflib matcher (`serve/app.py:445-509`) and speaks a bare flow word (`:1197`).
   - **Example:** 'Hawara' resolves to عورتا at 0.707, and the answer reads 'حوارة: الحاجز سالك' with no age and no doubt.
   - **Why it matters:** `place` is the default view, and Huwara is one of the 12 canonical questions (PLAN §10).

9. **F074: one crafted word stops the incident pipeline for every source (high, NEW).**
   - **Defect:** the settler_attack arm `\w*(?:\s+\S+){0,3}?\s*\S*(مستوطن|قطعان)` backtracks cubically (`cascade/news.py:176-177`). Measured: 1,800 characters take 5.9 s, and a 5,100-character token takes 131 s in `read()`.
   - **Why it matters:** a killed run rolls back (`news_incidents.py:739`) and the next run re-reads the same claim. So 20–45 unbounded crowd notes (`serve/app.py:1138`) keep the 900 s unit failing, and raids and closures stop reaching `/v2/incidents`, MCP and the corridor.

10. **F029 + first-hand + F069: the rebuild path loses data (high; NEW / "not recognised as a defect").**
    - **Silent databank loss:** a real load into an empty `observation` skips identical-content rows of an `indistinguishable` dataset, because the identity map is seeded from the run itself (`ingest/databank.py:1808-1817`, `:1835`). aid_access writes 25,872 of 50,059 rows and reports success (measured on the frozen corpus).
    - **Migrations cannot rebuild:** migrations 001–078 fail on an empty database. `018:39` and `074:19` insert aliases for place_ids that exist only in production, and `062:120` fails under `migrate.sh -1` (lead session, local Postgres 16 + TimescaleDB).
    - **Destructive loader:** `resolve/load_gazetteer.py:215-218` runs `TRUNCATE place, place_alias RESTART IDENTITY CASCADE` on a populated database. That empties claim, event, state_observation and observation, yet `docs/ARCHITECTURE.md:563` calls it safe.
    - **Why it matters:** disaster recovery is pg_dump restore only, and each documented alternative halves or destroys data.

### Counts

605 findings from 23 readers. Every finding a reader rated critical or high went through the refute and impact passes; the 436 unverified findings are all reader-rated medium or low. Results: 160 confirmed, 8 refuted, 1 no-impact. 121 of the confirmed findings are fixable without main-server.

| category (confirmed) | critical | high | medium | low | total |
|---|---:|---:|---:|---:|---:|
| safety | 10 | 33 | 3 | 0 | 46 |
| accuracy | 0 | 14 | 15 | 1 | 30 |
| data-integrity | 1 | 6 | 14 | 1 | 22 |
| operability | 0 | 2 | 13 | 0 | 15 |
| security | 1 | 10 | 3 | 0 | 14 |
| correctness | 0 | 6 | 5 | 1 | 12 |
| test-gap | 0 | 1 | 7 | 0 | 8 |
| doc-drift | 0 | 2 | 4 | 1 | 7 |
| performance | 0 | 2 | 4 | 0 | 6 |
| **total** | **12** | **76** | **68** | **4** | **160** |
| of which NEW (not in any plan) | 8 | 23 | 27 | 0 | 58 |

**What was rejected.**

- F018: open crowd registration is a recorded decision (DECISIONS.md:205).
- F025 and F032: both depend on v1 raw_line and timestamp semantics that this repository does not contain.
- F042: Telethon raises FloodWait client-side, so the claimed retry storm cannot happen.
- F281: the measured re-read takes 2.5–9 min, under the 900 s timeout.
- F280, F425 and F426: the behaviour is intended, or the scenario cannot occur.
- F458 (no impact): subsumed by the ledger list below.

**The test suite off main-server:**

- without a database: 701 passed, 163 failed, 58 errors;
- against the local empty schema: 821 passed, 99 failed.

None of the 315/436/557/840/928 counts quoted in HANDOFF, README and the plan can be reproduced off main-server.

### What the plan does not know

**NEW critical and high findings, by theme (31):**

*Checkpoint parser: false opens* (`cascade/checkpoint_text.py`)
- F001/F005 `:154`: relative ما (زي ما / حسب ما / مثل ما) negates the next status, so closed reads as open.
- F002 `:478`: fused negators (ومش, وما في, وبدون, مافي) are not recognised.
- F006 `:192`: conditionals and "I don't know if…" are asserted as `open`@0.90.
- F013 `:146` / F024 `:631`: future راح and تركوا are inferred as clearing words.
- F019 `:62`: 'فتح النار' reads as the checkpoint open.
- F022 `:353`: the question 'سالك ولا لا' reads as open, while the reassurance 'سالك ولا زحمة' is dropped as a question.
- F020 `:83`: dual, plural and dialect closure forms and ممنوع الدخول are missing, so closures are lost.
- F003 `:617`: on an emoji-only per-direction line, dict order picks the value, giving open both ways.

*Checkpoint parser: false cautions*
- F014 / F023 `:476`: 'لا يوجد جيش', 'مافي', 'مفيش' and 'لا X ولا Y' record the army present or congestion.
- F015 `:559` / F021 `:86`: "the jam is over" and "closure lifted" are served as congested or closed, and restart the clock.

*Direction and freshness on the surface*
- F008 `027:43`: the `both` row never sees directional readings.
- F035 `serve/mcp_server.py:182`: the direction-split answer has no age in either language.
- F090 `serve/webapp/pulse.html:234`: the worst flow is shown with the freshest row's age, so a 3-hour-old closure reads 'مغلق · قبل 5د'.
- F091 `pulse.html:241`: the SSE consumer is dead (`onmessage` never fires for named events), so the page never updates under a green dot.

*Crowd and belief trust boundary*
- F004 `learn/source_independence.py:144`: the nightly `--apply` frees crowd sock puppets.
- F017 `resolve/belief.py:117`: one anonymous caution blanks a channel's fresh reading.
- F072 `ingest/sources/news_incidents.py:384`: with `connectivity.py` and `power.py`, private rebuilds bypass modality and P2.4.
- F007 `ingest/sources/checkpoints.py:146`: crowd writes stamped `now()` advance the v1 import cursor.

*Other live feeds*
- F039 `cascade/news.py:118`: 'إعادة فتح حاجز حوارة بعد إغلاقه' becomes a closure incident plus road_closure='closed'.
- F073 `ingest/sources/power.py:345` / F038 `:342`: an announced future cut is served as active.
- F037 `power.py:317`: a cut is served for ~22 h after its announced end.
- F036 `ingest/sources/fuel_prices.py:233`: one outlet corroborates itself (an RSS claim plus its web page count as 2 units).
- F074 `cascade/news.py:176`: ReDoS halts the incident pipeline.

*Exports, correlation, databank*
- F082 `serve/app.py:1813`: the incident CSV/GeoJSON exports drop `place_precision`, so governorate fallbacks export as city pins.
- F043 `serve/app.py:2517`: correlate keeps the last row per date, so rho depends on physical row order.
- F029 `ingest/databank.py:1808`: a fresh load silently loses 48 % of aid_access.

**Verified by the lead session, not in the plan:**
- Persistence scoring (`015`/`026`) lets `closed` decay faster than `open`. With the measured curves, `open` floors near 0.70 while `closed` falls to 0.24, under the 0.25 floor. That is the opposite of the P2.4 asymmetry; the magnitude needs the fitted half-lives from main-server.
- A future-stamped `observed_at` is served at full confidence (`010`). The `>=` guard at `resolve/belief.py:212` then blocks every later correction until that time passes, and no write path checks `observed_at ≤ now()` (`checkpoints.py:167-171`; also filed unverified as F114/F331).
- The migration chain cannot rebuild an empty database (item 10).

**Filed as "known", but no plan task fixes them:**
- F012: crowd notes feed the classifier (item 5).
- F069: the gazetteer TRUNCATE CASCADE (item 10).
- F077/F083: unbounded `max_lag` pins a worker (`serve/app.py:2520`).
- F078/F088: JSON-RPC batches bypass the limiter, the quota and the body limit (`serve/mcp_http.py:643-644`).
- F075/F079: crowd-note text is served verbatim as news and quoted into `answer`, a prompt-injection path.
- F009/F016/F089: direction renderer and summary omissions.
- F067: a twin village promoted via `twin_keys` is invisible without a governorate hint ('المغير' answers Jenin's at 0.92; `resolve/geo.py:253`).
- F066: a watchdog crash and a watchdog that found a fault share one exit code (`ops/watchdog.py:817`).
- F060: swallowed REST failures render as "no recent information" (`serve/mcp_server.py:1228`).
- F092: the web pages never refresh.
- F063: the maintainer runs with `--dangerously-skip-permissions` and a root `systemd-run` path (`ops/maintain.sh:155`), accepted by design.

**§11 says "done"; the code says otherwise.** Before building on any 2026-09-24 17:05 entry, re-prove it.

| ledger entry | contradicting findings |
|---|---|
| P0-A.1 | F010 (one anchor row); F061/F305 (`days` ignored); F047 (`news` search drops place/kind); F054 and F059 (façade bounds) |
| P0-A.2 | F155/F245/F379 (`tests/test_answer_contract.py` does not exist); F068/F076/F081/F085 (`/v2/insights` still `learn=True` at `serve/app.py:1400`, so every test run writes production `place_alias`); F044/F052/F056 (no age) |
| P0-A.3 | F048 (no byte caps); F051 (per-call boilerplate) |
| P0-A.4 | F057/F322 (settlements unlabelled); F062 (span computed over the returned page); F055 (crossings); F070 (REST score uncapped) |
| P0-B.2/3 | F011, F071 |
| P0-C | F034/F080 (insights counts fallbacks under the city); F033 (news channels never independence-fitted); F084 (no stable-id test); F477 (stable key overwritten on every join) |
| PLAN-09-21 F-86 | F064 |

## Architecture

### Verdict

The data model suits a safety-critical tracker. The chain is: an immutable `claim` → versioned readings (`claim_classification`) → `state_observation` → one belief row per (place, kind, direction) in `state_current` → gated `*_serving` views that apply decay when read. Tier 2 sits beside it on `observation`, where a correction supersedes the old row instead of overwriting it.

The problem is enforcement. Each invariant lives in a docstring or in HANDOFF §1, and every writer has to keep it on its own. The confirmed critical and high findings sit exactly where a second path goes around an invariant:
- five writers of `state_current`;
- the highest-stakes input never becomes a claim;
- the default checkpoint row is a separate belief that directional reports never touch;
- crowd text reaches the incident classifier through a flag that defaults to true;
- every answer is written twice, once per language, over two transports.

The safety core has one hard external dependency: v1's place binding. That dependency is what blocks P3.

**Strengths any restructuring must keep** (maps: e2e-tracer, belief-decay):
- The three serving gates live in SQL views that the API cannot bypass (016/026/027).
- `resolve/belief.py` is a real per-unit noisy-OR. It collapses copied channels into one witness, applies the P2.4 asymmetry and holds an advisory lock.
- The news path respects claim immutability.
- `ingest/databank.py` tells a re-fetch from a correction and supersedes inside one transaction.
- The new local test database runs the suite at 821 passed / 99 failed (first-hand), with the 13 tests in `test_crowd.py` that run the real belief SQL all passing. Changes to views and to the belief SQL can now be proven away from main-server.

### The model, layer by layer

**Claim (ingest).**
- Road messages skip the claim layer. `ingest/sources/checkpoints.py:223` inserts into `state_observation` with no `claim_id`. The message's identity survives only as `attrs.channel`, `attrs.msg_id` and `raw_line[:300]` (:175).
- The import cursor is `MAX(observed_at)` of the legacy kind, which the crowd also writes. v1 rows that arrive out of timestamp order are lost for good (F007, critical, NEW).
- Trust is not a class that consumers of `claim` filter on. Crowd sources inherit `feeds_incidents DEFAULT true` (`037:23`), so a crowd note becomes a believed raid plus a `road_closure` assertion (F012, critical, NEW).
- The poller keys a source on its mutable Telegram username (F219, NEW).
- An edit or a deletion on Telegram produces no superseding claim (F222, NEW). The immutable-claim rule has no way to correct a claim.

**Reading.** `cascade/checkpoint_text.read(raw_line)` returns facts with no subject. The place comes from v1's `canonical_key`, mapped through `place.source_refs->>'v1_canonical_key'` (`checkpoints.py:100-110`). Keys that do not map are dropped (:161-165). The parser computes a confidence that belief never reads (F123, unverified).

**Belief.**
- **Several writers.** `resolve/belief.py:1-5` calls itself "the only place in the system that decides what we think is true". At the audited HEAD, `connectivity.py:163`, `news_incidents.py:377`, `power.py:339` and `weather.py:212` each rebuild `state_current` with their own `DISTINCT ON`. None filters on modality or applies the P2.4 gate (F072, F038, F073; all high, NEW).
- **Newest wins.** The newest assertion sets the value and dissent can discount it by at most 25 % (`belief.py:117-121`, `:188`). One anonymous crowd caution therefore turns a fresh channel reading into `unknown` (F017, NEW).
- **Future timestamps.** The `>=` upsert guard (`:212`) and migration 010's clamp together let a future-stamped observation block every correction until its time passes (first-hand, NEW).
- **Direction.** Direction is a third value of the belief key, not a fan-out. The `both` row of `checkpoint_serving` sees only `both` reports (`027:43`), so the default answer can say open while both directions are closed (F008, critical). The plan knows directional data is rare (R3). It does not know the default row can never see it. The corridor reconciles direction by a different rule (F320).
- **Independence groups.** Two learners write `source.independence_group`, and `learn/crowd_independence.py` is scheduled nowhere (no hit under `ops/`). The nightly copy-collapse can therefore promote a crowd account to independence (F004, critical, NEW).

**Serving.** Hard rule 6 mostly holds, and the bypasses are where defects show:
- `/v2/databank/{category}` reads `source` instead of `databank_serving` and credits the wrong attribution (F143).
- `/checkpoints/summary` and `/crossings` read only `direction='both'` (F089; first-hand).
- The browser pages rebuild belief themselves and pair the worst flow with the freshest age (F090, NEW).

**Surfaces.**
- MCP is an HTTP client of its own API (`mcp_server.py:57-66`). A tool makes 1–6 sequential loopback calls with no overall deadline (F268, NEW), and neither side has a connection pool (F287, NEW; F293).
- MCP post-processes REST numbers (fires stripped, scores capped), so the two surfaces disagree (serve-rest map).
- The direction-split sentence with no age exists wherever a sentence is hand-written: F035 (NEW), F044, F050 and F009 are one defect, in the Arabic renderer, the English renderer and the branch selection.
- stdio and HTTP use two separate dispatchers (F270).
- `place_profile` resolves the place twice, through different resolvers (F010).

**Tier 2 and the seam between tiers.** "Supersede, never overwrite" is a per-writer habit here too:
- The MoH ingest uses `DO UPDATE` and resets `reported_at` on every run (F182, NEW).
- `repair_generations.py --apply` deletes a repaired generation (F345, NEW).
- Event identity has no injectivity invariant (F133, NEW).
- The classifier sweep hard-deletes incident events (F206, deliberate policy).
- The stable event key is rewritten on every join (F477).

**The learning loop.** Only two automated edges carry measurement into serving: the nightly independence fit and Loop A's `trust_weight` (`belief.py:146`). The first can lift a crowd account (F004). The second can never record a miss in a two-unit bucket and scores each unit against its own vote (F110, NEW). The rest of the loop does not reach serving:
- Incident precision annotates answers (`serve/quality.py`) but gates nothing, so classifier 1.8.1 serves unmeasured. P2-A.3 plans the gate; it is not built.
- Organ C's "196/199" is a model agreeing with the reader, not the reader's own accuracy (F229).
- The nightly audit bypasses the transports it is meant to check (F242).

**Rebuild.** The migration chain cannot rebuild the schema from scratch (first-hand, NEW):
- `018:39` and `074:19` insert aliases for place_ids that exist only in production.
- `062:120` adds an enum value inside `migrate.sh`'s single transaction.

Disaster recovery is therefore `pg_dump` restore only. P1-C.7 covers the `/opt/stacks/palestine` paths (21 `.py`/`.sh` files at HEAD; the plan says 17) but not this.

### Confirmed findings with an architectural root cause

The readers tagged 20 findings `architecture`. None of them reached adversarial verification; all 20 are `unverified`. The table below groups confirmed findings by the structural cause they share.

| structural cause | findings (severity · plan status) | where |
|---|---|---|
| Direction is a third key value, not a fan-out | F008 crit NEW · F016 high (R3 knows the data shape only) · F089 high known · F320 med (inconsistency NEW) · F009/F035/F044/F050 | `db/migrations/027…:43`, `resolve/corridor.py:525`, `serve/app.py:605` |
| Belief has several writers | F072 high NEW · F038 high NEW · F073 high NEW | `news_incidents.py:384`, `power.py:342`, `:345` |
| Newest reading wins | F017 high NEW | `resolve/belief.py:117` |
| Trust class not enforced on claim consumers | F012 crit NEW · F075/F079 high known | `crowd/engine.py:120`, `serve/app.py:945`, `:966` |
| Two owners of independence groups | F004 crit NEW | `learn/source_independence.py:144` |
| v1 seam keyed on time; legacy lane shared | F007 crit NEW · F058 high known | `ingest/sources/checkpoints.py:146`, `serve/mcp_server.py:1206` |
| Mutable source identity; no way to supersede a claim | F219 med NEW · F222 med NEW | `ingest/telegram_poller.py:150`, `:343` |
| Supersede by habit, not by schema | F182 med NEW · F345 med NEW · F133 med NEW · F206 med policy · F477 low known | `moh_gaza.py:92`, `repair_generations.py:86`, `databank.py:1677`, `news_incidents.py:700`, `:590` |
| Serving view bypassed | F143 med (COALESCE bypass NEW) · F090 high NEW | `serve/app.py:2769`, `webapp/pulse.html:234` |
| Several resolvers; read paths that write | F010 crit known · F067 high known · F068/F076 high known | `mcp_server.py:1197`, `resolve/geo.py:253`, `:561`, `serve/app.py:1400` |
| MCP over loopback HTTP, no pool | F268 med NEW · F287 med NEW · F293 med known | `mcp_server.py:63`, `serve/app.py:70`, `resolve/db.py:49` |
| Rendering duplicated per language and transport | F270 med known · F245/F379 known (contract test missing) | `mcp_server.py:2056` |
| Loop confirms itself or measures the wrong thing | F110 med NEW · F229 med known · F242 med known | `learn/reliability.py:175`, `analyst/gold_moh.py:116`, `ops/mcp_accuracy_audit.py:48` |
| Migration chain not replayable (first-hand) | NEW | `db/migrations/018:39`, `074:19`, `062:120` |

**Unverified, but backed by a confirmed sibling or by code read at HEAD:**
- F164: road messages bypass the claim layer (the INSERT at `checkpoints.py:223`).
- F116: newest-wins belief (F017).
- F120: the crowd timer refreshes the legacy lane (`030:126`, F007).
- F316/F330: four resolvers, and `place_alias.alias_norm` is a global primary key.
- F343: the event key embeds `place_id`.
- F214: the source registry governs one fetcher.
- F095: four Arabic normalisers.

**Checked and not confirmed:**
- F025 (a multi-checkpoint bulletin collapses to one verdict) and F032 (string cursor) both depend on v1's `raw_line` and timestamp formats, which this checkout cannot see.
- F425 was refuted outright.

### The coupling that blocks P3

P3 says v2 "parses the raw road messages from v1's tee spool with its own cascade", with v1's parser as the control. Four couplings stand in the way, and the plan names none of them:

1. **The subject lives in v1.** v2's cascade reads *what state* a checkpoint is in; v1 decides *which* checkpoint. The importer can only land a report on a place that carries a v1 `canonical_key`. The module says it deliberately did not reimplement v1's "2,564 lines" (`checkpoints.py:8-10`). Parsing raw messages needs a v2 segmenter/binder that does not exist. P1-A.5's roads gold set measures a reader, not a binder. (NEW)
2. **No shared message key.** With no claim per road message, v1's reading and v2's reading of the same message cannot be joined, so "v1 as control" cannot be measured (F164, F007).
3. **The legacy kind carries weight.** `checkpoint_status` is at once the archive of v1's verdict, the import cursor (F007), a crowd-reportable kind (`030:126`) and a served grain (F058). Retiring v1's parser means undoing all four.
4. **Direction has to come first.** A v2 parser, like palhub under P1-A.1, produces direction-explicit readings. Under F008 none of them reaches the default row, the summary or G4's known-fraction. Unifying before fixing F008 makes the default answers staler.

v1 also feeds much more than the checkpoint parser:
- Tier 2's supply: the unified tree and the four dead fetches (P1-B.3).
- The fuel tee (`palhub_loader.py:40`).
- Routing's `restrictions.geojson`.
- The public map at roads.zaidlab.xyz (DECISIONS 2026-08-02).
- The Telegram session that reads the road channels.

Whether the tee spool carries every road channel with message ids needs main-server, or the private palestine-v1 repo, to confirm. Today v2 reads the tee only for fuel.

### Target structure

One owner per layer, enforced by the database or by a single function rather than by convention:

- **Ingest:** every input is a `claim` with a bronze copy. Each source has a stable id and a trust class (`curated | wire | crowd | structured`), and every consumer filters on that class as an allowlist. An edit becomes a superseding claim.
- **Read:** readers are pure `claim → reading` functions. A reading holds:
  - subject candidates per clause;
  - axis, value and direction;
  - modality (report, question, conditional, forecast);
  - a time reading;
  - a confidence and the reader version.

  Readings are stored like `claim_classification`, and v1's verdict becomes one more reader, named `v1`.
- **Believe:** `belief.refresh` is the only writer of `state_current`, for every kind. A trigger rejects rows not grounded in an `assertion`, and rejects future `observed_at`. The value is chosen per value, not by recency: the argmax of a per-value noisy-OR over a kind-scaled window, weighted by parse confidence × unit trust. Beliefs are kept per direction, and `both` is derived as the worse of the two with a `differs` flag (belief-decay target).
- **Serve:**
  - the views as today, plus page-shaped ones;
  - one pooled query layer and one resolver;
  - a typed fact record per tool, rendered by thin Arabic and English functions;
  - MCP calling the route functions in-process;
  - stdio a thin shell over `_handle`.
- **Measure:** rounds, gold sets and accuracy results live in tables, with provenance and with versions read from the rows. A reader below its gate cannot hold `modality='assertion'`, so the loop gates instead of annotating.
- **Rebuild:** a replayable migration chain, and the test database in CI.

### A sequence that keeps the hard rules

| step | what | why it is safe |
|---|---|---|
| 0 | v2-internal invariants: derive `both` (F008); make belief the only writer, with a trigger (F072/F038); choose the value per value (F017); trust-class allowlist (F012); make `crowd_independence` the owner of crowd groups (F004); clamp `observed_at`. Prove each on the local test DB | View replacement and code only; nothing deleted (rule 2); the API still reads `*_serving` (rule 6); no contact with v1 |
| 1 | Make the seam lossless: cursor on v1's rowid or (channel, msg_id) via `ingest_seen` (F007); write each road message as a claim with `external_id = msg_id` and `claim_type='road'`, so step 0's allowlist keeps it out of the incident classifier (where اختناق reads as injury — arabic-patterns map); store v1's verdict as reader `v1`; retire `checkpoint_status` from the crowd kinds and the defaults while keeping its rows; archive unmatched keys | v1 still opened `?mode=ro` (rule 1); claims are only ever inserted (rule 5) |
| 2 | Build the v2 binder, `read(line, candidates)`, and score it against v1 on the 200-message roads gold (P1-A.5); it writes `modality='shadow'` | Stored, never believed |
| 3 | Shadow run from the tee. If the tee lacks road channels, extending it is a change to v1 and needs Zaid's hands and a rollback plan (the P1.1(b) precedent) | No second Telethon client (rules 3 and 4) |
| 4 | Switch by modality once v2 matches or beats v1 on the gold set and in live agreement; v1 stays as the control | One reversible flag (the ZAID-1 fuel-images precedent) |
| 5 | Retire v1 in the reversible stages of DECISIONS 2026-08-02, after Tier 2 supply, the fuel tee, the restrictions and roads.zaidlab.xyz have successors. The road-channel Telegram session moves last, and that is Zaid's call | Nothing deleted; each stage can be undone |

Surface consolidation (one fact record, in-process MCP, a connection pool, one resolver) does not depend on v1 and can run beside steps 0–2. It lives in `serve/`, so the one-pair-of-hands rule applies.

## Accuracy: classifier, parsers, place resolution

The part of the system that gets measured is not the part that can send a traveller toward a closed checkpoint. The incident classifier has hand-scored rounds, confidence intervals, and a precision figure served beside every count. The checkpoint text parser decides the served `open`/`closed` value for every road line that v1 matches to a place. It has had one hand audit, there is no gold set for it in the repo, and no plan workstream covers it. It has the worst confirmed defects in this section. Code citations are to the committed tree (HEAD `3d3ca14`).

### What is measured today

| component | measurement | gap |
|---|---|---|
| Incident classifier (`cascade/news.py`) | Round 8 on classifier 1.8.0: **0.767** [0.693–0.827], n=150. Weak types: death 0.60, siege 0.60, demolition 0.667, land_levelling 0.667. 7 of 40 sampled rejects were real incidents. Adversarial rows 0.50, n=48. Source: `ops/incident-precision.json`. | 1.8.1 is served unmeasured until round 9. The scorer gates each type at 0.60 (`gate.per_type_required`) while PLAN §6 G3 says 0.70. So the file reports `types_below_floor: []` while four types fail G3 (raised as F235, not verified; the file itself shows it). Recall is measured only on the 40 sampled rejects. |
| Checkpoint parser (`cascade/checkpoint_text.py`) | Hand audit 78/83 (0.940), 2026-08-03 (`docs/DECISIONS.md:231`). 45 unit tests. | No road-text gold set in the repo. P1-A.5's 200-line set is scoped to organ D. Every finding below is proven on constructed lines. How often each shape occurs needs main-server. |
| Place resolution | named 82.7 % (4,191 of 5,069 events; PLAN §11 2026-09-24 19:12, a main-server number) | Covers the classifier's placement only. Hint-less lookups are not measured (F067). There is no held-out place round. |
| Fuel price reader | 23-document fixture corpus | None of the 23 documents uses a comma decimal (F174). |
| MoH Gaza reader | "196/199" | That is a gateway model agreeing with the reader's own output (`analyst/gold_moh.py:88,116`, F229). The reader's independent evidence is 20 human reads plus the T4P cross-check (188/199 days agree). |
| Databank | Gaza cross-check and a 6-category as_of replay (PLAN §4 R4) | Place, unit and date correctness are not measured. |

### Why one misread line becomes the served answer

- `ingest/sources/checkpoints.py:174` re-reads v1's `raw_line` with v2's own parser, and writes every fact as an `assertion` (`:205`). v1 only picks the place.
- Belief gives each unit `0.85 × trust_weight` (`resolve/belief.py:146-148`) and never reads parse confidence. An emoji-only guess stored at 0.65 is served at 0.85.
- The newest assertion wins, and dissent lowers its confidence by at most 25 % (`:188`).
- The P2.4 gate holds back only crowd sources (first-hand; F005 verification).
- PLAN §4 R3 counts only 10 of 103 current statuses on two or more sources. For most checkpoints, the parser's error rate is therefore the served error rate.
- Changes under `cascade/` go live on the next 2–5-minute tick (CLAUDE.md), with no measurement step in between.

**Correction to the plan:** PLAN §4 R6 calls v1 "still the only checkpoint parser", and no plan item names `checkpoint_text.py`. The served value actually comes from v2's own parser.

### Checkpoint parser: lines served with the wrong sign

Reproduced on HEAD in this session and by the verifiers. All are **NEW** and fixable here with DB-free tests. `tests/test_checkpoint_text.py` has 45 passing tests, and none covers these lines.

| channel line | means | parsed as | cause (`cascade/checkpoint_text.py`) | id · sev |
|---|---|---|---|---|
| زي ما هو مسكر · عطارة حسب ما سمعت مسكر | still closed | **open** 0.80 | `ما` is in NEGATORS (`:154`); two-token look-back (`:461-490`) | F001 · F005 crit |
| عطارة ومش سالك · حوارة سالك للداخل ومش سالك للخارج | not flowing | **open** 0.90 (second line: both lanes open) | `_negated` compares the raw token (`:478`); only `_lex` peels و (`:255`) | F002 crit |
| الداخل ✅ الخارج ❌ | outbound closed | **open**, both directions, 0.65 | first emoji in dict order wins; position −1 becomes `both` (`:617-622`) | F003 crit |
| اذا فتح الحاجز خبرونا · ما بعرف اذا حوارة سالك | conditional; "I don't know" | **open** 0.90 | no conditional reader; ما بعرف/حدا بعرف absent from QUESTION_PHRASES (`:192-199`) | F006 crit |
| راح يسكروا حوارة · الجيش راح يسكر الحاجز | about to close | **open** 0.72, army absent | future راح is in CLEARING_WORDS (`:144-149`); open inferred at `:629-631` | F013 · F024 high |
| الجيش فتح النار … عند حاجز حوارة | opened fire | **open** 0.90, army present | فتح/فتحوا = open (`:62-63`); no phrase entry for فتح النار | F019 high |
| عورتا سالك ولا لا | a question | **open** 0.90; "سالك ولا زحمة" (open, no jam) is dropped as a question | ولا counts as a question only when two flow values are present (`:353-356`) | F022 high |
| الحواجز مسكرين · اغلقت قوات الاحتلال حاجز حوارة · ممنوع الدخول | closed | unparsed, so the earlier open stays served until it decays; mixed lines read open | no dual, plural or verb forms (`:82-86`); no ممنوع الدخول (`:128-136`) | F020 high |
| تم رفع الاغلاق عن حاجز حوارة · خلصت الازمه | lifted; jam over | closed / congested 0.90, with a fresh clock | a clearing word never touches a flow noun (`:559`, `:629-631`) | F021 · F015 high |
| مافي جيش · لا يوجد جيش · لا جيش ولا تفتيش · الجيش مش موجود | no army | army **present** 0.88; مافي ازمة reads congested | لا negates only before في/فيه; no fused مافي/مفيش; no forward look (`:476-478`) | F014 · F023 high |
| حوارة كان مغلق الصبح وهلا سالك | open now | closed | severity collapse ignores كان/هلا (`:684-687`) | first-hand |
| بيت فوريك مسكر للي طالع بس سالك للي نازل | outbound closed, inbound open | closed, both directions | طالع/نازل not in DIRECTION_WORDS (`:161-178`) | first-hand |

The first eight rows give a false open, or keep a stale open alive. The rest give false cautions: detours, lost reports that the army left, or a lost open lane.

They share one root cause. Negation, tense, condition and question are handled as exceptions inside a two-token window. There is no clause grammar and no "forecast" modality. The 78/83 audit suggests these shapes are a minority of lines; their actual frequency needs main-server.

One defect sits upstream of the parser. The v1 import cursor is `MAX(observed_at)` over `checkpoint_status`, a kind the crowd writes with `now()`. So v1 rows are skipped for good (`ingest/sources/checkpoints.py:146-155`, F007, crit, NEW, needs main-server).

### Incident classifier, place resolution, feeds, databank

"here" means fixable without main-server.

| id | sev | where | what is served or stored wrong | vs plan | here |
|---|---|---|---|---|---|
| F039 | high | `cascade/news.py:117-118` | A reopening ("اعادة فتح حاجز حوارة … بعد اغلاقه") becomes a closure event plus `road_closure=closed`, served ~9–12 h. The file has no reopening vocabulary. | NEW | yes |
| F190 | med | `news.py:176-177` | "تقتحم بورين قرب مستوطنة يتسهار" is filed as a settler attack: `مستوطن` matches the settlement. Actor inverted. 0 real misfiles in 928 sampled texts. | NEW | yes |
| F041 | high | `ingest/sources/news_incidents.py:642` | A house siege writes `road_closure=closed` for the whole village (~15 of 35 sampled siege rows are one Qusra house). | P0-B.4 would turn it into a route caution | yes |
| F040 | high | `news_incidents.py:524` | No time reader: "مساء أمس" is served as minutes old at `hour` precision (10 of 928 sampled incidents). | designed 09-21 (F-21), not scheduled | yes |
| F074 | high | `news.py:176-177` | Cubic backtracking: 900 chars 0.71 s, 1,800 chars 5.8 s; a 4,096-char Telegram token takes ~69 s. A run killed at 900 s rolls back (commit only at `news_incidents.py:739`) and retries forever, so the whole incident feed stops. | NEW | yes |
| F096 | med | `news.py:116-120` | The clause guard `[^.،؛]{0,40}` never fires, because `normalize()` has already stripped punctuation (`resolve/arabic.py:86`). "سكرتير الحركة" and "اجتماع مغلق تطرق" become closures. | the file documents it as fixed (`:87-104`) | yes |
| F099 · F100 | med | `news.py:289,337,343,349-353,380` | Unanchored rejects: قدمه اليمنى, غور الاردن, طالبا ب, تصريح, تبرير, خط التماس and شارع غزة delete real injuries, arrests and demolitions, because rejects run first (`:925-929`). | rule known (HANDOFF §4), these words are not | yes |
| F097 · F192 | med | `news.py:169-179`, `:214` | The verbal nouns اقتلاع/احراق/تخريب/تحطيم and bare اعتقال match nothing. Recall only (19 of 928 texts carry اعتقال). | shape known (DECISIONS 08-03 P1.1), words not | yes |
| F196 | med | `news.py:468,709` | "مدخل نابلس/جنين/البيرة" loses both the place and the governorate, so entrance closures are dropped. | NEW | yes |
| F012 | crit | `crowd/engine.py:120`; `news_incidents.py:423-435` | Anonymous crowd notes are classified into believed incidents and `road_closure` rows (`feeds_incidents` defaults to true). | NEW | no |
| F072 | high | `news_incidents.py:373-391`; `power.py:339-351`; `connectivity.py:163-175` | Private `state_current` rebuilds ignore modality and the P2.4 gate. A crowd `open` replaces a news closure. A crowd internet row can make MCP say "internet working normally" during a real outage. | NEW | no |
| F033 | high | `news_incidents.py:424` | News mirrors count as independent sources (two units give 0.91). | P0-C.5; ledger says P0-C done | no |
| F203 · F205 · F477 | med/low | `news_incidents.py:566`, `:644`, `:590` | A join across batches anchors on the earliest report and splits long incidents. Each version bump without `--rebuild` duplicates every closure observation. `stable_key` is rewritten on every join. | F203 fixed in-batch only; F477 is under P0-C.4 (ledger says done) | F477 yes |
| F206 | med | `news_incidents.py:700` | Swept events are hard-deleted and leave no history row. | deliberate (DECISIONS 038); Zaid's call | no |
| F067 | high | `resolve/geo.py:252-265` | Hint-less "المغير" answers Jenin's village (9 of 241 events) at ~0.96 with `ambiguous_with=0`, on `/v2/geo/resolve`, insights, route and MCP place. | twins noted in P0-C.1; the hint-less path is not | no |
| F068 | high | `geo.py:209,561`; `serve/app.py:1400` | `learn=True` by default. Public, crowd and palhub callers write aliases and commit the caller's transaction, and a guess comes back later as "exact" at 0.885–0.955. | P0-A.2 marked done; the code disagrees | yes |
| F070 | high | `serve/app.py:492-502,586` | REST resolves "Zatara" to عطارة (0.738) and "Hawara" to عورتا (0.707) with `found:true` and scores up to 1.04. | P0-A.4 cap marked done; REST is uncapped | yes |
| F069 | high | `resolve/load_gazetteer.py:215-218` | The "rebuild" runs `TRUNCATE place … CASCADE`, which empties claim, event, state_observation and observation, and uses pre-077 pcodes. | docs call it safe (`ARCHITECTURE.md:563`) | yes |
| F315 · F438 | med/low | `resolve/place_merge.py:170-177`; `palhub_loader.py:70` | The merge moves a town's key to its entrance checkpoint (`DO UPDATE`). The station anchor accepts a checkpoint as its locality. Both latent. | NEW / feed retired | yes |
| F036 · F174 | high/med | `ingest/sources/fuel_prices.py:177,233`; `cascade/fuel_price.py:230` | One outlet's RSS lede plus its web page count as two units, so its price is "confirmed". "8,15 … 8,39 شيكلا" is read as `{diesel: 15.0}` (reproduced on HEAD). Together, one outlet's misread can be served as the official price. | NEW | yes |
| F038 · F073 | high | `ingest/sources/power.py:336-351` | The rebuild has no modality filter, so a cut announced for a future date is served as a cut now for up to ~22 h. | NEW (contradicts `040:8-10`) | yes |
| F037 | high | `power.py:317` | No end event: a cut that has ended stays "active" for ~21–22 h. | NEW | no |
| F176 · F182 | med | `cascade/moh_gaza.py:126-148`; `ingest/sources/moh_gaza.py:90-92` | An unknown section header files a running total as a daily figure (16,000 injuries "in one day", synthetic bulletin). `DO UPDATE` overwrites revised values and resets `reported_at` every hour (hard rule 2). | P1-B.1 would publish it | F176 yes |
| F229 | med | `analyst/gold_moh.py:88,116` | "196/199" is cited as the parser's score. | the plan carries the mislabel (§4 R5, P2-A.1) | no |
| F028 | high | `ingest/databank.py:556-562` | No lat/lon rung: 431 locality demolition rows sit on the West Bank row, so governorate series see none of them. | measured 08-08, left unfixed | yes |
| F030 | high | `serve/app.py:2428-2429` | Litre prices are labelled `ILS_per_kg`; cubic-metre water is divided by 1,000 (~2,909 rows). | QA-09-23 | no |
| F027 | high | `db/mappings/refugees.yaml:287` | `value_num` is part of the identity, so an IDMC revision becomes a second current row and is double-counted. | fixed for IODA only | no |
| F029 | high | `ingest/databank.py:1808-1817` | A fresh load of aid_access writes ~25.7k of 50,059 rows and reports success. | NEW | yes |
| F133 | med | `ingest/databank.py:1677-1680` | Event identity has no source id: the 262 journalist events collapse to about one per region on a fresh load. | NEW; P1-B.1 would serve the result | no |
| F026 · F143 | high/med | `data/open-release/manifest.json:68`; `serve/app.py:2765-2782` | World Bank rows are credited to PCBS. Category payloads credit the HDX portal, not the OCHA/UNICEF CC-BY attribution. | P1-B.2 | no |

**`road_closure` is not yet fit to feed routes.** It has only one value ("closed"), and five confirmed paths write a false one: F039, F040, F041, F012 and F072. P0-B.4 plans to make it a route caution, filtered only on `place_precision='named'`. That filter stops none of the five.

**Weather, connectivity and fires have no confirmed accuracy finding** apart from F072. Readers raised six leads that were not adversarially verified:
- F177: the connectivity baseline contains the outage it judges.
- F178: the FIRMS bounding box counts Israeli farmland.
- F185: weather writes "normal" at 0.95 when forecast fields are missing.
- F184: power "12:00 من ظهر" parses as midnight.
- F173: fuel `effective_from` lands a day early.
- F465: MoH `occurred_at` is the claim's UTC date.

**Databank date, precision and measure_kind:** nothing is confirmed. Three unverified leads:
- F128: `demolitions.locality.*` cumulative totals are registered `flow` (`db/mappings/demolitions.yaml:230-235`).
- F138: a record with no date takes v1's fetch stamp (`ingest/engine.py:188`).
- F141: the rollup day uses the DB clock, while the patterns use Asia/Hebron (`ops/rollup.py:105`).

F128 matters because correlate refuses only `measure_kind='cumulative'` (`serve/correlate.py:92`, F251, confirmed).

**Checked and not confirmed:**
- F025 (a multi-checkpoint bulletin collapses to the worst state): the mechanism is real (`:684-687`), but the evidence came from sample files whose writer strips newlines (`learn/incident_precision.py:112-117`). It needs v1's `raw_line` semantics.
- F426 (fuel withholding): by design (`073:21-25`).

**Verifier corrections carried above:**
- F039 and F041 are served for 9–12 h, not 24 h.
- F074's crowd note holds ~2,700 Arabic characters (~20 s each); it still stalls the unit, through volume.
- F192 and F196 change zero served incidents on the 928-text sample.

### Ordered fixes

1. **Parser inversions (DB-free, now).** Changes to `_negated`:
   - Peel one و/ف before testing NEGATORS.
   - Add مافي/مافيش/مفيش/فش to NEGATORS.
   - Skip ما after زي/مثل/حسب. Do not skip it after بعد: in Levantine, "بعد ما فتح" means "not yet", which is the F001 verifier's warning against F005's proposed fix.
   - Treat لا/ولا before يوجد or a presence noun as negation, and add a forward check for مش موجود / ما في.

   Other rules:
   - اذا/لو/في حال and ما بعرف/حدا بعرف map to the existing `question` modality. A new `conditional` or `forecast` modality would need migration 040's CHECK changed, which needs main-server.
   - راح/رح followed by an imperfect verb is never a clearing.
   - Add فتح النار phrases.
   - A clearing word next to a flow noun gives open, but "ازمه وراح الجيش" must still read congested.
   - Bind emoji to the nearest direction word, or refuse the line.
   - Add closure inflections and ممنوع الدخول.

   Every probe above becomes a regression test. The change is live within one tick, so ship it together with step 2.
2. **Measure the parser (main-server).** Every row already stores v1's verdict (`checkpoints.py:180`) beside v2's re-parse, keyed by `attrs.msg_id`. Their disagreements are the population to hand-score. Retarget P1-A.5's 200-line roads gold set at `checkpoint_text.py`, commit it under `tests/fixtures/`, and add a DB-free projection script like `ops/rescore_round.py`.
3. **Stop a single parse from being served at 0.85 (main-server).** Multiply unit trust by the observation's confidence at `belief.py:146-148`. This changes served confidences, so it needs DB validation.
4. **Before P0-B.4, make `road_closure` trustworthy.** Read reopenings as `open` (F039). Check the object of a siege (F041). Write no `road_closure` from a reading dated yesterday (F040). Set `feeds_incidents=false` for crowd sources and allowlist source kinds (F012). Replace `REFRESH_CLOSURE_SQL` with `belief.refresh` with crowd excluded (F072). Adding `modality='assertion'` alone does not close F072, because crowd rows are assertions.
5. **Before the next `CLASSIFIER_VERSION` bump**, which re-reads ~33k claims in one transaction under a 900 s timeout: land F074 (drop tokens of 60+ characters, bound the quantifiers) and F205 (existence check). Then fix F096, F099, F100, F097, F192, F196 and F190 in one version. Align the scorer's per-type gate with G3's 0.70, and let round 9 measure the result.
6. **Place resolution.**
   - F068: default `learn=False`, and no `commit()` inside `resolve_place`.
   - F070: gate and cap the REST score.
   - F067: return ambiguity for twin names.
   - F069: refuse to run when referencing tables have rows.
   - F315: `DO NOTHING` on conflict.
   - Correct the §11 lines for P0-A.2 and P0-A.4.
7. **Feeds.**
   - Add a modality filter at `power.py:345` (F038/F073).
   - Write a restored reading at the window end (F037).
   - Key fuel independence on the publisher (F036).
   - Split clauses in a way that respects digits (F174).
   - Reset the tier on an unknown header (F176) before P1-B.1.
   - Supersede instead of overwrite (F182), which needs main-server.
   - Restate "196/199" for what it is (F229).
8. **Databank.** F029 and F028 can be proven DB-free with the frozen corpora. F027, F030 and F133 need main-server and must land before P1-B.1/P1-B.2 publish those rows.

## Safety logic: belief, decay, serving views, route verdicts

Line numbers refer to the audited code, which matches HEAD `3d3ca14`. **FH** means the lead session verified it itself (first-hand.md). **NEW** means PLAN-2026-09-24 §4–§7 does not mention it.

### The formula as served

Write side: `resolve/belief.py` REFRESH_SQL, once per (place, kind, direction).

```
latest  = the single newest modality='assertion' row                 :116-122  (no now() bound, no tie-break)
unit    = COALESCE(independence_group, 'src:'||source_id)            :112
p_u     = max over the unit's agreeing rows of
          0.85 × COALESCE(trust_weight, crowd ? 0.20 : 1.0)          :144-161
C       = 1 − Π(1 − p_u) over AGREEING units, window = the 30 min
          ending at `latest`, the same for every kind                :67, :138, :176-180
base    = min(0.97, C × (1 − 0.25·d/(a+d)))   a, d = unit counts, with no weight for trust or age   :185-189
P2.4    = do not write if value ∈ crowd_gated_values ('open' for flow)
          ∧ no non-crowd unit agrees ∧ a < 2; the old row stays      :199-203
upsert  = only when the new observed_at ≥ the stored one             :212
```

For reference: one channel = 0.85, two independent units = 0.97 (the cap), one unverified stranger = 0.17.

Read side: `state_serving` (026), then `checkpoint_serving` (027).

- **h:** the place's cadence half-life (1.5× the median gap, clamped to 15 min–12 h; `ingest/sources/checkpoints.py:250-275`). Without one, the kind default applies (5,400 s for flow).
- **p(t):** the fitted per-value curve asym + (p0−asym)·0.5^(t/H_v) (015:62-77). Without a fit, 0.5^(t/h).
- **confidence:** base × clamp((p(t) − 0.5)/(p0 − 0.5), 0, 1) (026:72-76).
- **Three gates.** The value becomes `unknown` when confidence < floor (0.25 for flow), when the band is `expired` (age ≥ 8h), or when age > max_assert (6 h for flow, 45 min for presence) (026:97-102). Through the `stale` band (2h–8h) the value is still served. `last_known_value` is always the raw belief (026:86).
- **Direction fallback** (027:43-44). The inbound and outbound travel rows each take the freshest row filed for that direction *or* for `both`; on a tie the specific direction wins. The `both` travel row reads **only** rows filed `both`. Rows that have decayed to `unknown` are not skipped. `passable` is true for open, slow and congested (027:84-90), and presence never changes it.

Route verdict: `resolve/corridor.py`.

- **On route:** within a 300 m tube. **Near miss:** 300–3,000 m away, and only if closed, congested or slow (:113-154).
- **Per checkpoint:** the worst value across its `state_serving` direction rows. Age is ignored (:512-529).
- **coverage_fraction:** 1 − the longest gap between consecutive on-route checkpoints, **whether their state is known or not**, with both ends counted (:561-574).
- **`_score`** (:362-391):
  - any closed → `blocked`;
  - none known → `unknown`;
  - any congested or slow → `slow`, returned before doubts are computed;
  - otherwise `unverified` if the longest gap is ≥ 10 km, or if a *closed* near miss sits within min(0.5, 10/length) of either end (:415-459);
  - otherwise `likely_open`.
- `doubts` is filled only for `unverified`. `exit_closures` is always filled (:646-647).
- **Ranking:** likely_open < slow < unverified < unknown < blocked, then by travel time (:677).

### Where it breaks DESIGN laws 1/2/8 and G2

**A. Reassurance the evidence does not support.** This is the direction of error that sends someone toward a closed checkpoint.

| id · sev | rule | what happens | plan |
|---|---|---|---|
| F011 crit | G2, P0-B.2 | Za'tara is slow and Ein Siniya is closed 2.3 km off the route at the exit. The Arabic answer is "الطريق سالك بس فيه ازمة" and neither language names Ein Siniya. `mcp_server.py:950-951` removes every `exit_closures` name from the near-miss warning, and the only place those names are spoken is gated on `unverified` (:984; `mcp_en.py:133`, :176-178). The same happens for `blocked` and `unknown`. This undoes 978ca3b. | ledger says done |
| F071 high | G2 | A 12 km route with one open checkpoint at km 9 has coverage 0.25 and returns `likely_open`. Nothing compares coverage_fraction with 0.6 (`corridor.py:420-421`). | ledger says done |
| FH | G2, R2 | Coverage counts **unknown** checkpoints. A 53 km route with 8 evenly spaced checkpoints and 1 known open has coverage 0.88 and no 10 km gap, so it reads `likely_open` ("1 of 8 confirmed open"). F071's proposed fix (`coverage_fraction < 0.6`) would therefore still not meet G2. | NEW |
| F008 crit / F016 high | law 1 | 13:00 "حوارة سالك"; 14:05 "مغلق للداخل ومغلق للخارج". The `both` row is never touched, so REST returns flow=open, passable=true, and MCP says "حوارة: سالك. آخر تحديث قبل 1 ساعة" (027:43; `app.py:576`). The route is not affected because it takes the worst direction. | NEW |
| F009 crit | law 1 | Inbound closed 9 min ago and the `both` row decayed. The answer is "ما في تحديث جديد — آخر معلومة قبل 3 ساعة: كان سالك" (`mcp_server.py:182-192`). | NEW |
| F089 high | law 1 | `closed_now` and the totals read `direction='both'` only (`app.py:601-609`). A closure in one direction never appears on the road page's "المغلق الآن". Crossings has the same shape (`app.py:2144`, FH). | NEW |
| FH | P2.4 | Latest report wins. Three units say "closed" at 14:00, one curated unit says "open" at 14:20: 0.85×(1−0.25·¾) = 0.69, and "open" is served. P2.4 gates only the crowd. So every confirmed single-message parser inversion (F001, F002, F003, F006, F013) becomes the served value at once. The belief layer is the one place that could absorb an inversion, and it does not. | NEW |
| F004 crit | P2.4 | The nightly copy-collapse writes `independence_group=NULL` for any source without a ≥0.98 partner, crowd sources included (`source_independence.py:144`, :154-157, run with `--apply` nightly). Two sock-puppet accounts become two units: 1−0.83² = 0.311, or 0.285 against a channel's "closed". That is above the 0.25 floor, and a=2 clears the P2.4 gate, so a false open is served. `crowd_independence.py` is scheduled nowhere. | NEW |
| F072 high | P2.4 | Three writers rebuild state_current from the newest observation of their kind, with no modality, no gate and no units: `news_incidents.py:373-391`, `power.py:336-351`, `connectivity.py:163-175`. Replayed: one crowd `open` turned a news `road_closure=closed` into `open` @0.95. Adding `modality='assertion'` would not close this, because crowd rows are assertions. | NEW |
| F318 med | G2 | `slow` returns before doubts are computed, so a 45 km blind stretch plus a closed exit reads "passable but congested". Keeping the word is a decision (P0-B.1). Dropping the reasons is not. | reasons NEW |

**B. Age does not change the answer (law 1)**

- **Informativeness is measured against the wrong reference (FH plus this section's derivation). NEW.**
  - The 015 comment says informativeness should reach 0 "once the reading tells us nothing the base rate did not already" (015:33-36). The code measures it against 0.5 instead (026:75).
  - With 015's measured points, `open` (0.96→0.88) never drops below 0.826 informativeness, so its confidence stays ≥ 0.70 until the ceiling. `closed` (0.92→0.62) falls to 0.286 × 0.85 = 0.24, below the floor.
  - So the model forgets a closure faster than an opening, the opposite of P2.4.
  - The formula is proven from code. The ages at which this bites need the fitted `state_value_decay` rows (main-server).
- **The `stale` band is served as the value.** At a busy checkpoint (h = 15 min), an `open` reading between 30 min and 2 h old is served at confidence ≥ 0.70. Zaid has to say whether law 1's "staleness band" means `stale` or `expired`. Either way, the confidence served for `open` says nothing about its age. NEW.
- **Future timestamps.**
  - An observation dated in the future gets full confidence: `state_confidence` returns base (010:27), `value_persistence` returns p0 (015:68), the band reads `live`, and max_assert never fires.
  - The `>=` guard (`belief.py:212`) then refuses every real correction until the clock passes that time.
  - No write path checks observed_at ≤ now() (`checkpoints.py:167-171`). It has happened once before (`belief.py:216-225`). FH, NEW.
- **F037 (high):** a power cut stays served for 12·log2(0.9/0.25) = 22.2 h after its announced end, because nothing writes a "restored" observation at `window_end` (`power.py:317`). NEW.
- **Ages dropped when rendering:**
  - F035 and F050 (high): the direction-split sentence carries no age (`mcp_server.py:185-187`, `mcp_en.py:68-73`).
  - F056 (high): `can_i_travel` never states the age of its evidence.
  - F090 (high): `pulse.html:224-235` pairs the worst flow with the freshest sibling row's age, so a 170-minute-old closure reads "مغلق · 5د".
  - F092 (high): the pages fetch once and never refresh.
  - Status: F050 and F056 are known-in-plan (G1, P0-A.2c); F035 and F090 are NEW; F092 is parked.

**C. The three states blurred (law 2)**

- **F017 (high).** A stranger's `closed` against a channel's `open` from 5 minutes earlier scores 0.17×(1−0.25·½) = 0.149, below the floor. Two things follow:
  - The channel's fresh reading is erased. Registration is open and each account can report 6 times per hour per place, so anyone can blind any checkpoint this way.
  - A value that never cleared the floor is then presented as the last known fact (026:86): "آخر معلومة قبل دقيقة: كان مغلق".
  - The error runs in the cautious direction. It contradicts `belief.py:98-99`. NEW.
- **F008/F016:** a checkpoint with only directional readings has no `both` row. REST answers found:false with "no checkpoint reading has ever been recorded here", and MCP says "ما عرفت حاجز اسمه …".
- **F049 (high):** a checkpoint that resolves by name but has never been read is answered as an unknown name.
- **F055 (high):** when every sourced crossing has decayed, the answer says "no source" (the ledger says this was fixed).
- **F060 (high):** swallowed REST failures render as "ما في معلومات حديثة".

**D. Presence (law 8).** The formula itself respects law 8. `passable` reads flow only (027:84-90), the corridor never blocks on presence (`corridor.py:107-111`, :541), and F425 was refuted. The real violations are sign errors upstream in the parser (F014, F023), covered in the parser section. One small residue, from this section's reading of 027:50 and not in the verified set: `presence_age_minutes` is a single min() over all present and absent sightings, so an army chip can carry the age of a different sighting. The 45-minute cap bounds the error.

**E. Tools contradict each other**

- **F320 (medium).** The corridor merges direction rows by severity only. An inbound closure at 10:00 (one source) and a `both` open at 14:55 (three groups) give checkpoint_status "open" but can_i_travel "مسكّر عند بيت ايل", until 16:00. The error runs in the cautious direction. NEW.
- **F377 (medium).** Nothing tests the "freshest wins" direction rule (014:1-11), and test_crowd only ever writes `both`. Its scenario's claim that can_i_travel says open is wrong: the corridor takes the worst direction (F320).

**F. What enters the model**

- **F007 (critical).** The v1 import cursor is MAX(observed_at) over a kind the crowd also writes with now() (`checkpoints.py:146-156`). Any v1 row dated earlier than that maximum is skipped forever. This breaks hard rule 2 (no data loss). NEW.
- **F012 (critical).** Crowd notes reach the incident classifier (the 037:23 default is true, and `engine.py:120-128` never sets it false). They become believed incidents and a `road_closure` of `closed` @0.7, outside belief entirely (`news_incidents.py:423-435`, :640-651). NEW.
- **F073/F038 (high).** The power rebuild reads `scheduled` rows, so tomorrow's announced cut is served as active today. Replayed. NEW.
- **F110 (medium).** Loop A scores each unit against a consensus that includes its own vote, and discards two-unit disagreements (`reliability.py:172-183`). A stub run gave 50 hits, 0 misses and 100 ties, which yields trust_weight ≈ 1.0. NEW.

### Proof: code, local DB, or main-server

- **Proven from code** (pure Python or arithmetic, runnable anywhere): F011, F071, coverage counting unknowns, F318, F009, F035, F050, F056, F090, F110, F012 (via `read()`), F037, and every confidence figure above.
- **Mechanism provable on the local schema-only DB with synthetic rows:** F008, F016, F089, F377, F017, the latest-wins case, F004, and future timestamps. F072, F073 and F038 were already replayed on a throwaway Postgres.
- **Magnitude needs main-server:**
  - how many checkpoints currently have a directional reading fresher than their `both` row (PLAN R3's pre-audit figures: 1,279 explicit readings, 4 places differing);
  - the fitted `state_value_decay` curves;
  - the share of served rows in the `stale` band;
  - `SELECT count(*) FROM state_current WHERE observed_at > now()`;
  - the Loop A tie share and the trust weights actually served;
  - v1 rows lost to F007 (this also needs v1's SQLite);
  - how many live route answers read `likely_open` below 0.6 known coverage (`ops/route_coverage_measure.py`, which needs Valhalla);
  - whether any crowd source has already lost its group (R3 counts 0 submitters, but the path is open).

### Target formula, by risk

1. **Route: earn `open` from what is known, and say everything the payload knows** (F011, F071, FH, F318, F056).
   - Known coverage = 1 − the longest gap between consecutive on-route checkpoints whose value is not `unknown`.
   - `open` only when known coverage ≥ 0.6, that gap is < 10 km, and there is no closed near miss at either end.
   - `slow` computes and carries the same doubts.
   - One ordered `reasons` list is rendered in both languages: exit closures for every verdict, the blind stretch, and the newest and oldest reading ages.
   - Congestion at the ends needs a decision: amend G2, or add a spoken doubt that does not change the verdict (`corridor.py:438-440`).
   - Fixable here. Expect more `unverified` until P1-A lands.
2. **One direction rule everywhere** (F008, F016, F009, F089, F320, F377).
   - Travel row d = the freshest *asserted* row filed for d or `both`.
   - Travel row `both` = the worse of the two travel rows, with a `differs_by_direction` flag and each direction's age.
   - The corridor, summary, crossings, insights and MCP all read that row.
   - Needs a view migration and a local-DB test.
3. **Belief by value, not arrival order** (FH, F017).
   - For each candidate value v: C_v = 1 − Π_u(1 − p_u·0.5^(age_u/h)), counting each unit's latest assertion, inside a window W_k = clamp(h/3, 30 min, 6 h).
   - Serve argmax C_v, with base = min(0.97, C_max·(1 − 0.25·C₂/(C_max+C₂))).
   - Extend P2.4 to every source: a reassurance contradicted by caution mass ≥ floor needs ≥ 2 units; otherwise serve `unknown` with the reason `contested`.
   - This is a doctrine change: record it in DECISIONS and re-measure SINGLE_SOURCE_TRUST on main-server.
4. **Trust boundary.**
   - F004: copy-collapse must never write over `kind='crowd'` sources; schedule `crowd_independence`.
   - F012: set `feeds_incidents` false for the crowd and allowlist source kinds in the classifier query.
   - F072, F073, F038: send those kinds through `belief.refresh`, and add a `state_current` trigger that rejects rows not grounded in an assertion.
   - F110: score each unit against the other units only (leave-one-out).
5. **Decay that follows P2.4.**
   - Informativeness = (p_v(t) − π_v)/(p0_v − π_v), where π_v is the value's base rate. `open` then retires once it says no more than the base rate; `closed` stays until the ceiling.
   - Ceiling = min(max_assert, 4h).
   - Settle whether law 1 means `stale` or `expired`.
   - Needs main-server. G4's known fraction will fall, honestly.
6. **Time integrity.**
   - Reject observed_at > now()+5 min on every write path and in `latest`.
   - `state_confidence` returns 0 for a future reading, not base.
   - F007: page v1 by rowid.
   - F037: write "restored" at `window_end`.
7. **Vocabulary at the edges.** `last_known` must be a value that was once served (F017). Fix F049, F055 and F060.
8. **Pin it.** One synthetic-row test of the whole pipeline on the local DB, replacing the SQL gates that pass whenever the data is quiet.

### Checked and rejected

- **F018:** open crowd registration is a recorded decision (DECISIONS:205). What remains is stale text in HANDOFF §7 ("the crowd can only corroborate"), which F017, F004, F012 and F072 show is untrue.
- **F425:** refuted. Presence arrays are ordered freshest first, and the age cap grows with age.
- **F426:** withholding the fuel price is by design (073:21-25).
- **F032:** the string-format behaviour of the v1 cursor cannot be proven without v1's writer. The out-of-order data loss survives as F007.