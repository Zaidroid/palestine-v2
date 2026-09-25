# Plan 07 · Incident classifier and event writer

Phase 3 — Incident accuracy and place resolution. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `cascade/news.py`, `ingest/sources/news_incidents.py`, `tests/test_news.py`, `tests/test_incident_clustering.py`, `tests/test_place_extraction.py`
- **Tests to run after every task:** `tests/test_news.py tests/test_incident_clustering.py tests/test_place_extraction.py tests/test_quality.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Bump CLASSIFIER_VERSION to 1.9.0 if any reading can change (serve/quality.py then reports 1.9.0 as unmeasured — correct). Measure with `python3 ops/rescore_round.py 7` and `python3 ops/rescore_round.py 8` BEFORE and AFTER (no DB needed) and report both numbers as projections on tuning sets, never as measurements; do not write the rescore output files into ops/ unless the script does so by design — if it does, keep them out of the commit by restoring them (git checkout -- ops/...) and put the numbers in your report. Catastrophic-backtracking fixes must come with a timing test (a 20 KB adversarial token classified in < 1 s). Event-lifecycle changes that need a migration: write the SQL into your report as a proposal, do not create migration files. Findings in applied migrations (004/017/076) go in `proposals` with the exact SQL.

- Confirmed tasks: 17 · verify-first tasks: 44 · refuted (skip): 0

- Findings located in these files belong here too (fix them through the files you may edit, or with a NEW migration in your range — never edit an applied migration): `db/migrations/004_event.sql`, `db/migrations/017_*.sql`, `db/migrations/076_*.sql`, `ops/place_measure.py`

## A. Confirmed tasks (independently verified — do these first, in order)

### CLASSIFIER-01 · F039 · high · safety
**A reopening report is served as a closure and writes road_closure='closed'**

- **Where:** `cascade/news.py:118`
- **What goes wrong:** A channel posts 'إعادة فتح حاجز حوارة بعد إغلاقه لساعات'. The feed serves 'إغلاق في حوارة قبل 5 دقائق' (serve/mcp_server.py:477 INCIDENT_AR + age from occurred_at) and state_current road_closure=closed for Huwara for up to the 24 h assert ceiling. A traveller is told the checkpoint that just reopened is closed — the inverted-sign shape of HANDOFF §4 (مش سالك / ما زال).
- **Fix:** Add a reopening reader before the closure arm: `(?:اعاده|اعادت|[يت]عيد|تمت?|تم)\s+فتح|فتح\s+(?:ال)?(?:حاجز|طريق|شارع|بوابه|معبر|مدخل)|ازاله\s+(?:ال)?(?:ساتر|سواتر|بوابه|مكعبات)|الحركه\s+طبيعيه|سالك` → when it matches and the closure verb is inside a 'بعد/عقب/منذ' clause, emit is_closure=False and a new reading field state='open' that news_incidents writes as road_closure='open'. Add the two probe sentences to tests/test_news.py asserting incident_type != 'closure'.
- **Evidence (audited code):**
```
_CLOSURE_PATTERN arm 2: `r"|" + _MOVE_OBJECT + r"[^.،؛]{0,40}?" + _CLOSE_VERB` (news.py:117-118); no reopening vocabulary exists anywhere in the file (grep for فتح finds only the dead `\bفتح\s*:` at :384). Probe with the current code: read('اعادة فتح حاجز حوارة جنوب نابلس بعد اغلاقه صباح اليوم لعدة ساعات') → verdict=incident, incident_type=closure, matched='حاجز حواره جنوب نابلس بعد اغلاق'; read('الحركة طبيعية على حاجز عطارة شمال رام الله بعد ازالة السواتر الترابية التي اغلقت الطريق امس') → closure at عطاره. news_incidents.py:642-650 then INSERTs state_observation road_closure VALUES (... 'closed' ...) at that place and REFRESH_CLOSURE_SQL puts it in state_current.
```
- **Verifier's check:** Reproduced with the current tree: read('اعادة فتح حاجز حوارة جنوب نابلس بعد اغلاقه صباح اليوم لعدة ساعات') → verdict=incident, incident_type=closure, is_closure=True, matched='حاجز حواره جنوب نابلس بعد اغلاق'; read('الحركة طبيعية على حاجز عطارة ... بعد ازالة السواتر الترابية التي اغلقت الطريق امس') → closure at عطاره; read('إعادة فتح حاجز حوارة بعد إغلاقه لساعات') → closure. cascade/news.py:117-118 is arm 2 of _CLOSURE_PATTERN (_MOVE_OBJECT ... _CLOSE_VERB) and the only فتح in the file is the faction-statement reject `\bفتح\s*:` at :384; no reopening vocabulary, no 'بعد/عقب' clause guard, and …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-02 · F074 · high · performance
**Catastrophic backtracking in the settler_attack pattern: one 4 KB token stalls the classifier for a minute, a 15 KB one past the unit timeout, forever**

- **Where:** `cascade/news.py:176`
- **What goes wrong:** Any polled Telegram channel post (max 4,096 chars -> ~67 s), an RSS item (text[:4000], rss_news.py:172) or — via the previous finding — a crowd note of up to ~15 KB (uvicorn/h11 request-line cap 16 KiB) containing a single word like 'عتدعتد…' with no spaces. A 15 KB token costs roughly 130 s x (15000/5100)^3 ≈ 3,300 s: the timer is killed at 900 s, the transaction rolls back, the claim stays unclassified, and every subsequent 5-minute run repeats — the incident and road_closure pipeline stops permanently until someone deletes or hand-classifies the claim.
- **Fix:** Bound the quantifiers to token shapes: replace `\\w*` with `\\w{0,12}`, `\\S+` with `\\S{1,30}`, `\\S*` with `\\S{0,20}` in both arms (:169-181) and audit the other `\\S*`/`\\w*` uses; in read() (:874) pre-pass `re.sub(r"\\S{60,}", " ", norm)` so no token longer than 60 chars reaches any pattern (no real Arabic word is that long); add tests/test_news.py cases asserting read('عتد'*1400) and read('قتح'*1400) finish in < 0.2 s.
- **Evidence (audited code):**
```
cascade/news.py:176-177 second arm: `(عتد|هاجم|هجوم|عربد|عربده|قتح|رشق|قتلع|ضرم|شعال)\\w*(?:\\s+\\S+){0,3}?\\s*\\S*(مستوطن|قطعان)` — greedy \\w* followed by \\S* on the same token with a literal after, tried at every occurrence of the 3-letter stem. Measured in this checkout (scratchpad/security/redos2.py): the compiled settler_attack regex alone on 'عتد'*n: 900 chars 716 ms, 1800 chars 5.8 s, 3600 chars 45.7 s (x8 per doubling = cubic); news.read() on a 5,100-char 'عتد' token 130.8 s, on a 4,800-char 'قتح' token 125.6 s. read() runs the reject patterns first (:877) but every incident pattern in order (:143-208) before returning. ops/classify-news.sh runs under TimeoutStartSec=900 (ops/syste …
```
- **Verifier's check:** Confirmed cubic backtracking in the second arm of settler_attack (cascade/news.py:176-177). Pattern: `(عتد|…)\w*(?:\s+\S+){0,3}?\s*\S*(مستوطن|قطعان)`. My measurements of the compiled pattern on 'عتد'*n: 450 chars 0.094 s, 900 chars 0.713 s, 1800 chars 5.89 s, roughly 8x per doubling. read() itself took 0.715 s at 900 chars and 5.75 s at 1800. read() tries the patterns in order through _first_match (:608) with no length cap. One correction: the '~15 KB crowd note' overstates the per-note size. Arabic percent-encodes to 6 URL bytes per character, so a 16 KiB URL carries about 2,700 Arabic charac …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-03 · F072 · high · safety
**Four writers bypass the modality filter and the P2.4 crowd gate for crowd-reportable kinds (power, internet, road_closure)**

- **Where:** `ingest/sources/news_incidents.py:384`
- **What goes wrong:** One registered submitter files road_closure='open' (gated) for a village at 12:00. crowd-refresh at 12:02 correctly withholds it (belief.py:196-200). The news timer at 12:05 produces closure_states, runs REFRESH_CLOSURE_SQL: the newest road_closure observation for that place is the crowd row → state_current = 'open' at the resolver's confidence, independent_sources=1; the `>=` guard then keeps it (belief.py:212). Identical path for internet via connectivity.py 15 minutes later (and /v2/connectivity then returns rows[0] of an unordered two-row state_serving result, app.py:685-693). A rate_limited or rejected row qualifies too, because nothing filters modality. Latent today only because PLAN R3 counts 0 submitters.
- **Fix:** Remove the private rebuilds; every kind's belief goes through resolve.belief.refresh(kinds) (already scoped per kind and gated). Until then add `AND modality='assertion'` to each and make G2.4/G2.5 kind-agnostic (drop the `sc.state_kind IN (...)` list at tests/test_gate2_checkpoints.sql:62 and `LIKE 'checkpoint%'` at :86). Consider a BEFORE INSERT OR UPDATE trigger on state_current that rejects rows not grounded in an assertion observation, so the invariant is the database's, not each writer's.
- **Evidence (audited code):**
```
news_incidents.py:373-391 REFRESH_CLOSURE_SQL: `SELECT DISTINCT ON (place_id, state_kind) place_id, state_kind, 'both', value, observed_at, source_id, confidence, 1, 0, now() FROM state_observation WHERE state_kind = %(closure)s ORDER BY place_id, state_kind, observed_at DESC` — no modality predicate, independent_sources hard-coded 1, no crowd_gated_values check. Same shape at connectivity.py:163-175 and power.py:339-351. Migration 030:118-166 makes power, water, internet and road_closure crowd_reportable with gated values ('available', 'open'); crowd/engine.py:236 writes `modality = "rate_limited" if over_cap else "assertion"` and :274-280 inserts with observed_at now() at `float(res.confid …
```
- **Verifier's check:** Confirmed by reading and by replaying the repo's own SQL on a throwaway Postgres 16. Three writers rebuild state_current from every observation of their kind with no modality, crowd or gate check: REFRESH_CLOSURE_SQL (news_incidents.py:373-391, run at :730-738 whenever closure_states>0 or a sweep ran), connectivity.py:163-175 (independent_sources=len(signals), not 1) and power.py:336-351. Migration 030:147-157 makes power/internet/road_closure crowd-reportable with gated 'available'/'open'. Registration is open to the public (app.py:1965), POST is allowed by CORS (app.py:62-66), and crowd/engi …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-04 · F033 · high · accuracy
**News-channel mirrors are counted as independent sources: independence_group is never fitted for incident channels, yet the ledger records P0-C as done**

- **Where:** `ingest/sources/news_incidents.py:424`
- **What goes wrong:** Fact B mirrored verbatim by a second channel 3 minutes later: one event (correct), independent_sources=2, confidence 0.91, counted as 'corroborated' in /v2/incidents/summary and 'not single-source' in the incidents_near sentence — a copy is served as corroboration on the death type whose measured precision is 0.60.
- **Fix:** Run a claim-level copy fit (near-duplicate text within a short lag, per PLAN P0-C.5 / ARCHITECTURE §3.9 guardrail) over feeds_incidents sources and write independence_group; until then cap independent_sources at 1 for units with no measured group or say 'unmeasured' in the answer; correct the §11 P0-C line to name what is still open.
- **Evidence (audited code):**
```
COALESCE(s.independence_group, 'src:' || s.source_id::text) AS unit (:424); units = {m[2] for m in cluster}; conf = _confidence(len(units)) (:522-525) → 1-(0.3)^n. learn/source_independence.py measures only state_observation kinds (MEASURE_SQL over state_observation). PLAN §4 R2: 'News channels never tested for copying (independence_group NULL)'; §7 P0-C.5 lists the fit as a P0-C item; §11 line 227 records 'P0-C · done (measured)' without it.
```
- **Verifier's check:** Confirmed in code. news_incidents.py:424 sets unit = COALESCE(independence_group, 'src:'||source_id). Units are counted at :521-523, and _confidence (:344-345) gives 1-(0.3)^n, so two units = 0.91. The only fitter that writes independence_group for channels is learn/source_independence.py. Its MEASURE_SQL reads state_observation only, and ops/learn-checkpoints.sh runs it with `--kinds checkpoint_flow`, so news-only channels never get a group. crowd_independence only touches crowd sources. There is no mirror or near-duplicate handling in the clustering (:405-525). One served caveat is now false …
- **Already in the release plan:** PLAN §4 :55 (R2 'News channels never tested for copying'), §7 P0-C.5 (:127); §11 :227 marks P0-C done without it
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-05 · F040 · high · safety
**No time is read from the text: 'مساء أمس' incidents and closures get the posting time and are served fresh**

- **Where:** `ingest/sources/news_incidents.py:524`
- **What goes wrong:** At 09:00 a channel writes 'أغلق الاحتلال حاجز بيت فوريك مساء أمس'. occurred_at=09:00 today, precision 'hour'; /v2/incidents?hours=6 lists it as a closure 'قبل 10 دقائق'; state_current road_closure=closed observed_at 09:00 asserts for a further 24 h. The DESIGN law 'age changes the answer' is defeated at the source because the age is wrong.
- **Fix:** In cascade/news.py add a small time reader over the normalized tokens (فجر/صباح/ظهر/مساء/ليل + اليوم/امس/الليله الماضيه, قبل قليل, الان, a dd/mm date) returning (offset_days, hour_band, precision); news_incidents shifts occurred_at accordingly and sets occurred_precision 'day' for امس-class readings; never write a road_closure observation from a report whose time reading is yesterday. Unit-test the reader in tests/test_news.py.
- **Evidence (audited code):**
```
`occurred = cluster[0][1]` (:524) is the earliest claim's reported_at; the INSERT stamps `'hour'` precision (:605); the closure observation uses the same value: `(place_id, STATE_KIND_CLOSURE, reading.matched, occurred, cluster[0][3], conf, ...)` (:647-650). cascade/news.py has no time reader at all (no امس/الليله/فجر handling; NewsReading has no time field). Corpus: 17 of 928 sampled texts carry مساء امس / ليلة امس / الليلة الماضية / امس (e.g. 13270 'الكرفان الزراعي الذي تم هدمه ... ليلة أمس', 12563 'الليلة الماضية'), and read('الاحتلال يغلق حاجز بيت فوريك شرق نابلس مساء أمس') → closure with no time.
```
- **Verifier's check:** Code does what is claimed: NewsReading (cascade/news.py:550-561) has no time field; امس/مساء/ليله appear only as name-stop tokens in _STOP_TOKENS (:508-510) and the aftermath reject knows only الاسبوع الماضي/قبل ايام etc. (:296-313), so read('الاحتلال يغلق حاجز بيت فوريك شرق نابلس مساء أمس') → incident/closure with matched='يغلق حاجز' and nothing about time (reproduced). ingest/sources/news_incidents.py:524 `occurred = cluster[0][1]` is claim.reported_at, which ingest/telegram_poller.py:259 sets from the Telegram message date (posting time); :605 stamps 'hour'; :647-648 writes the closure obse …
- **Already in the release plan:** PLAN-2026-09-21 §W2 F-21 (organ B schema carries occurred_at + time_precision; shadow only, not built)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-06 · F041 · high · safety
**A house siege writes road_closure='closed' for the whole village**

- **Where:** `ingest/sources/news_incidents.py:642`
- **What goes wrong:** Settlers surround one family's house in Qusra. The event is right (the human marked these real), but state_current gets road_closure=closed for Qusra with confidence 0.7–0.97 for up to 24 h; any consumer of the place's state (MCP place view=history state_kind=road_closure, the planned route link P2-C.1) reads the village as closed.
- **Fix:** Write road_closure only for `closure`, and for `siege` only when the besieged object is a town/road/entrance (`(حصار|محاصره|[يت]حاصر\w*)\s+(?:\S+\s+){0,2}?(بلده|قريه|مخيم|مدينه|حاجز|طريق|مدخل|مداخل)`); a house siege stays an event only. Pin with a test on the Qusra sentence.
- **Evidence (audited code):**
```
`if itype in ("closure", "siege"):` then `INSERT INTO state_observation (place_id, state_kind, value, ...) VALUES (%s,%s,'closed', ...)` (:642-650) with place_id = the resolved village; cascade/news.py:215 `("siege", r"(حصار|طوق|محاصرة|[يت]حاصر)")` and :990 `is_closure=itype in ("closure", "siege")`. Measured on the 928 sampled texts: of 35 rows the current code labels siege, 6 are sieges of HOUSES ('مستوطنون يحاصرون منزلاً في بلدة قصرة', 'حصار منازل في بلدة قصرة يدخل أسبوعه الثاني', 'أصحاب المنازل المحاصرة في بلدة قُصرة'), all resolving to the village row.
```
- **Verifier's check:** Reproduced: read('مستوطنون يحاصرون منزلاً في بلدة قصرة جنوب نابلس') → incident, siege, place=قصره (place_word), is_closure=True; read('حصار منازل في بلدة قصرة يدخل أسبوعه الثاني') → siege, is_closure=True. cascade/news.py:215 `("siege", r"(حصار|طوق|محاصرة|[يت]حاصر)")` has no object test, :990 sets is_closure for siege, and ingest/sources/news_incidents.py:642-650 writes state_observation road_closure='closed' for `itype in ("closure", "siege")` at place_id = the resolved village with the cluster's confidence (0.7–0.97 via _confidence). The MCP place tool's history view accepts state_kind=road_ …
- **Already in the release plan:** PLAN-2026-09-24 §7 P0-B.4 (road_closure + closure/siege events to become route cautions; only a governorate-precision filter planned, not a house-siege filter)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-07 · F096 · medium · correctness
**The closure rule's clause guard `[^.،؛]{0,40}` is dead — normalize() removed every full stop and comma before the regex runs — and _MOVE_OBJECT is unanchored, so 'hung up the phone', 'سكرتير الحركة', 'في اجتماع مغلق تطرق' and the idiom 'قطع الطريق على' all file as road closures**

- **Where:** `cascade/news.py:117`
- **What goes wrong:** A closure event writes a road_closure state_observation with value 'closed' (news_incidents.py:604-612) that is served as a caution and, under P0-B.4, will feed the route verdict. The documented wave-3 defence ('the governor hung up the phone' → not a closure) does not exist at runtime: any road noun within 40 characters, across sentence boundaries, and any word containing طرق/معبر/الحركه/بلده, produces a closure at a named place. No corpus text in the 928 sampled rows triggers these exact shapes; the risk is latent but the guard the comment promises is absent.
- **Fix:** Either split sentences before normalising (keep a sentinel for ./،/؛ or classify per sentence) and replace `[^.،؛]{0,40}?` with a token bound `(?:\S+\s+){0,6}?`, and anchor every _MOVE_OBJECT noun and _CLOSE_VERB inflection to token boundaries (`(?<!\S)(?:ال)?(?:شارع|...)(?!\S)` and `(?<!\S)سكرت(?!\S)`); drop the idiomatic 'قطع الطريق' unless followed by a road object (امام المركبات/على المواطنين) rather than 'على' + abstract noun. Add the four sentences as rejections in tests/test_news.py.
- **Evidence (audited code):**
```
cascade/news.py:116-120 `_CLOSURE_PATTERN = (r"(" + _CLOSE_VERB + r"[^.،؛]{0,40}?" + _MOVE_OBJECT + r"|" + _MOVE_OBJECT + r"[^.،؛]{0,40}?" + _CLOSE_VERB + ... r"|منع الحركة|قطع الطريق)")` with the comment ':113 keeps the two inside one clause: crossing a full stop or a comma is usually crossing into a different sentence'. resolve/arabic.py:33-34 _PUNCT includes `.,;:` and `،؛` and :86 replaces them with spaces before news.py:921 `norm = normalize(text)`. Verified: normalize keeps '.'? False, '،'? False. read("اغلق المحافظ الهاتف. وأعلن ان شارع القدس سيعبد في بلدة بيتا جنوب نابلس") -> incident closure matched 'اغلق المحافظ الهاتف واعلن ان شارع'; read("في اجتماع مغلق تطرق المحافظ الى اوضاع بلد …
```
- **Verifier's check:** Confirmed. _CLOSURE_PATTERN (cascade/news.py:116-120) relies on `[^.،؛]{0,40}?` to stay inside one clause. news.read runs it on `norm = normalize(text)` (news.py:923, not 921). resolve/arabic.py:33-34 and :86 replace . , ، ؛ with spaces, so the guard can never trigger. Checked: normalize('a. b') keeps no '.', and it keeps no '،'. Run here: the phone sentence followed by '…شارع القدس…' gives incident closure, matched 'اغلق المحافظ الهاتف واعلن ان شارع'. 'في اجتماع مغلق تطرق…' matches 'غلق تطرق', because both _CLOSE_VERB and _MOVE_OBJECT (طرق inside تطرق) are unanchored. 'اعتقال سكرتير الحركة…' …
- **Already in the release plan:** cascade/news.py:87-104 documents wave 3 as fixed; HANDOFF §4 'Arabic orthography must match on both sides' is the same family (a pattern written for characters the normalised text can never contain).
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-08 · F097 · medium · accuracy
**Settler verbal nouns اقتلاع / احراق / تخريب / تحطيم and the verb قطع (trees) do not contain the stems the settler_attack pattern lists, so a settler action written as a masdar is 'no incident verb'**

- **Where:** `cascade/news.py:171`
- **What goes wrong:** Uprooting olive trees, arson of vehicles, vandalising water lines and smashing car windows are the four commonest settler acts in the Nablus/Ramallah channels; written nominally ('قاموا باقتلاع…') they are dropped, written with a bulldozer they become demolitions. The file documents this exact trap three times (اقتحام, استشهاد, اشعال) and misses it for these stems.
- **Fix:** Add the masdars and the cut/steal verbs to both settler alternations: `اقتلاع|احراق|تخريب|تحطيم|[يت]قطع\w*|قطع\s+(?:اشجار|عشرات)|سرق\w*|[يت]سرق\w*|تسميم|[يت]سمم\w*`; add 'اقتلاع اشجار' with settlers as settler_attack (not demolition) in the type-precedence tests. Regressions for the five sentences.
- **Evidence (audited code):**
```
cascade/news.py:169-179 settler stems `(عتد|هاجم|هجوم|عربد|حرق|شعل|شعال|ضرم|رشق|قتلع|خرب|حطم|دهس|قتح|سيطر|ستيلا|ستول|دشن|...)`. اقتلاع = ا-ق-ت-ل-ا-ع (no قتلع), احراق = ا-ح-ر-ا-ق (no حرق), تخريب = ت-خ-ر-ي-ب (no خرب), تحطيم = ت-ح-ط-ي-م (no حطم); قطع is absent. Run: read("مستوطنون يقومون باقتلاع عشرات اشجار الزيتون في اراضي بلدة بورين جنوب نابلس") -> unclear/no incident verb; same for باحراق مركبة, بتخريب خط مياه, بتحطيم زجاج مركبات, يقطعون عشرات اشجار الزيتون. Corpus: اقتلاع in 6 texts — 83657 'جرافات الاحتلال تواصل اقتلاع اشجار الزيتون في بلده عرابه' served as DEMOLITION via جرافات (hand note: 'demolition by the lexicon's design'); احراق 4, تخريب 4, all rescued only by a neighbouring word (ال …
```
- **Verifier's check:** Confirmed at cascade/news.py:169-177. The settler stems are contiguous consonant strings (حرق, قتلع, خرب, حطم), and the verbal nouns احراق, اقتلاع, تخريب and تحطيم put an alif or ya inside them. قطع is absent entirely. Run here, all with 'مستوطنون' plus the verbal noun or verb and a place: 'باقتلاع عشرات اشجار الزيتون', 'باحراق مركبة', 'بتخريب خط مياه', 'بتحطيم زجاج مركبات' and 'يقطعون عشرات اشجار الزيتون' each give verdict unclear / 'no incident verb'. No other incident pattern catches them.
- **Already in the release plan:** DECISIONS 2026-08-03 P1.1 v1.6 ('اشعال does not contain شعل — the third verbal noun to hide its own verb') names the shape, not these words.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-09 · F190 · medium · accuracy
**Army action near a settlement is filed as a settler attack (actor inverted)**

- **Where:** `cascade/news.py:176`
- **What goes wrong:** 'قرب مستوطنة X' is the standard locator for villages beside settlements (Burin/Yitzhar, Beita/Evyatar, Yatta/Ma'on). Every army raid or beating so located is served as a settler attack — the single fact the docstring says a reader most needs is wrong.
- **Fix:** Require a settlers-not-settlement form in both arms: `(?:مستوطن(?:ون|ين|ا|ه?\b(?!\s))|مستوطنو\b|مستوطنا\b|قطعان)` — concretely `(مستوطنون|مستوطنين|مستوطنا|مستوطن\b|مستوطنو|قطعان)`; add the two probe sentences as tests asserting raid/injury.
- **Evidence (audited code):**
```
Second settler arm: `r"|(عتد|هاجم|هجوم|عربد|عربده|قتح|رشق|قتلع|ضرم|شعال)\w*" r"(?:\s+\S+){0,3}?\s*\S*(مستوطن|قطعان))"` — `مستوطن` also matches مستوطنه/مستوطنات (a SETTLEMENT). Probes: read('قوات الاحتلال تقتحم بلدة بورين قرب مستوطنة يتسهار جنوب نابلس وتعتقل شابا') → settler_attack, matched 'قتحم بلده بورين قرب مستوطن'; read('جنود الاحتلال يعتدون على الرعاة قرب مستوطنة معون شرق يطا جنوب الخليل') → settler_attack. The file's own comment (:70-72) promises 'the ACTOR outranks the action so a settler attack is never recorded as an army raid' — this is the reverse error. Corpus row 43181 ('عودة مستوطنتي جانيم وكاديم، وسيطرة الاحتلال') is served settler_attack the same way.
```
- **Verifier's check:** Reproduced: read('قوات الاحتلال تقتحم بلدة بورين قرب مستوطنة يتسهار جنوب نابلس وتعتقل شابا') → settler_attack, matched='قتحم بلده بورين قرب مستوطن'; read('جنود الاحتلال يعتدون على الرعاة قرب مستوطنة معون شرق يطا جنوب الخليل') → settler_attack; control without the locator ('...تقتحم بلدة بورين جنوب نابلس وتعتقل شابا') → raid. cascade/news.py:176-177 second arm ends in `\S*(مستوطن|قطعان)`, which matches the settlement noun مستوطنه/مستوطنات after normalize(); the actor-first arm (:165-166) also uses `مستوطن\w*` so the corpus row 'عودة مستوطنتي جانيم وكاديم، وسيطرة الاحتلال' is settler_attack via …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-10 · F192 · medium · accuracy
**The bare verbal noun اعتقال never matches the arrest pattern**

- **Where:** `cascade/news.py:214`
- **What goes wrong:** 'اعتقال X من بلدة Y' is the commonest arrest headline in the corpus; every such message with no conjugated form is 'unclear' (dropped) or takes whatever other verb is present. Arrest recall is silently low while arrest precision reads 0.933.
- **Fix:** `("arrest", r"([اتين]عتقل\w*|اعتقال\w*)")` (the release/aftermath gates already handle الافراج/بعد اعتقاله). Add the probe sentence to tests/test_news.py.
- **Evidence (audited code):**
```
`("arrest", r"([اتين]عتقل\w*|اعتقالات?)")` — `اعتقالات?` is the literal اعتقالا plus an optional ت, so 'اعتقال' (ا-ع-ت-ق-ا-ل, which does not contain عتقل) matches nothing; the same verbal-noun trap the file documents for اقتحام/استشهاد/اشعال. Probe: read('اعتقال شاب من بلدة بيتا جنوب نابلس على حاجز حوارة') → unclear 'no incident verb'. Corpus: 19 of 928 texts contain اعتقال with no arrest match; e.g. 43299 'مشاهد توثّق لحظة اعتقال الفتى أحمد ... عقب مداهمة منزله' is served as raid, the arrest lost.
```
- **Verifier's check:** cascade/news.py:214 is exactly `("arrest", r"([اتين]عتقل\w*|اعتقالات?)")`. Direct regex test after _norm_pat/normalize: اعتقال → no match; اعتقالات, اعتقالا, يعتقل, اعتقلت → match. Reproduced read('اعتقال شاب من بلدة بيتا جنوب نابلس على حاجز حوارة') → verdict=unclear, reject_reason='no incident verb', and read('مشاهد توثّق لحظة اعتقال الفتى أحمد ... عقب مداهمة منزله') → raid (matched 'مداهمه'), the arrest lost. No other pattern or gate recovers the bare maṣdar. Corpus count (19/928) not verifiable here; the mechanism is.
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-11 · F099 · medium · accuracy
**'international' reject matches اليمن inside اليمنى (right hand/leg) and الاردن inside غور الاردن — injuries and Jordan-Valley demolitions are rejected as foreign news**

- **Where:** `cascade/news.py:353`
- **What goes wrong:** 'أصيب بعيار ناري في قدمه اليمنى' is the stock phrase of Red Crescent injury bulletins; every such report is dropped before the injury/shooting pattern can see it. A demolition 'في غور الأردن' (the Jordan Valley, West Bank) is dropped as Jordan. HANDOFF §4 states the rule for exactly this shape ('SHORT ARABIC STRINGS MUST BE ANCHORED') and cites راي; these two were not anchored.
- **Fix:** `(?<!\S)اليمن(?!\S)`, `(?<!غور )(?<!وادي )(?<!نهر )(?<!\S)الاردن(?!\S)`, same for العراق/سوريا/لبنان; add both sentences to tests/test_news.py::test_short_reject_terms_do_not_match_inside_longer_words.
- **Evidence (audited code):**
```
cascade/news.py:349-353 `("international", r"(ايران|إيران|العراق|الاردن|الأردن|" ... r"سوريا|لبنان|حزب الله|اليمن|الحوثي)")` — no boundary on اليمن or الاردن, and REJECT runs before INCIDENT (:925-929). Run: read("اصيب شاب برصاص الاحتلال في قدمه اليمنى خلال اقتحام بلدة بيتا جنوب نابلس") -> rejected/international matched 'اليمن'; read("قوات الاحتلال تهدم بركسات في خربة الحديدية في غور الاردن الشمالي") -> rejected/international matched 'الاردن'. Corpus: 1 of 928 texts contains اليمن (a real Yemen story); 0 contain غور الاردن.
```
- **Verifier's check:** Confirmed. The 'international' reject (cascade/news.py:349-353) has no boundary on اليمن or الاردن, and _REJECT_RE runs before _INCIDENT_RE (news.py:925-929). Run here: 'اصيب شاب … في قدمه اليمنى خلال اقتحام بلدة بيتا جنوب نابلس' is rejected as international, matched 'اليمن'. 'قوات الاحتلال تهدم بركسات في خربة الحديدية في غور الاردن الشمالي' is rejected, matched 'الاردن'. The same demolition written 'الأغوار الشمالية' comes out as incident demolition, which isolates the cause. tests/test_news.py passes (103) and has no case for these words.
- **Already in the release plan:** HANDOFF §4 names the shape (راي in اسراييلي) but not these words.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-12 · F100 · medium · accuracy
**'statement', 'court', 'legal' and 'gaza' rejects fire on unanchored short branches: طالب (student), تصريح (permit), تبرير, الحكم على, خط التماس, شارع غزة**

- **Where:** `cascade/news.py:380`
- **What goes wrong:** Arrests of university students ('اعتقال طالب بجامعة'), injuries of schoolgirls ('اصابة طالبة ب...'), arrests for lacking a permit, clashes on the seam line and shootings on Ramallah's Gaza Street are all rejected before classification. Each branch was written for one meaning of a homograph and matches the other.
- **Fix:** Anchor and disambiguate: `(?<!\S)(?:طالبت?|[يت]طالب\w*|مطالب\w*)\s+ب` (the request verb, not the noun student); `(?<!\S)تصريحات?(?!\S)` only with `صحفي|رسمي|ل?وسائل` or drop it; `(?<!\S)[يت]بري?ئ?ه?(?!\S)|تبرئه|براءه\s+`; `(?<!خط )التماس\w*`; `(?<!شارع )(?<!حي )غزه(?!\S)`; `الحكم\s+علي\s+(?:الاسير|المعتقل|الشاب)` only. Add the seven sentences as regressions.
- **Evidence (audited code):**
```
cascade/news.py:380-381 `("statement", r"(نادي الاسير|نادي الأسير|تصريح|بيان صحفي|...|طالب\w* ب|دعا\w* الى|ناشد|"`; :337 `("court", r"([يت]برئ\w*|...|الحكم\s+علي|`; :343 `("legal", r"(المحكمه العليا|التماس\w*)")`; :289 `("gaza", r"(غزة|غزه|...`. Run: read("قوات الاحتلال تعتقل طالبا بجامعة بيرزيت من بلدة كوبر") -> rejected/statement 'طالبا ب'; read("اصابة طالبة بالرصاص الحي خلال اقتحام قوات الاحتلال بلدة سلواد") -> rejected/statement 'طالبه ب'; read("اعتقال شاب بحجة عدم حمله تصريح على حاجز الكونتينر") -> rejected/statement 'تصريح'; read("الاحتلال يعتقل شابا لتبرير اقتحام بلدة سبسطية") -> rejected/court 'تبرير' (_norm_pat turns [يت]برئ into [يت]بري); read("الاحتلال يعتقل الشاب احمد بعد الحكم ع …
```
- **Verifier's check:** Confirmed for every quoted example (cascade/news.py:248 gaza, :337 court, :343 legal, :380 statement). Run here: 'قوات الاحتلال تعتقل طالبا بجامعة بيرزيت…' is rejected as statement ('طالبا ب'). 'اصابة طالبة بالرصاص الحي…' is rejected as statement ('طالبه ب'). '…عدم حمله تصريح على حاجز الكونتينر' is rejected as statement ('تصريح'). '…لتبرير اقتحام…' is rejected as court ('تبرير'): after _norm_pat folds ئ→ي, `[يت]برئ\w*` becomes `[يت]بري\w*`. '…بعد الحكم على شقيقه…' is rejected as court. '…خط التماس…' is rejected as legal. 'اطلاق نار على شارع غزة في رام الله…' is rejected as gaza. I cannot verif …
- **Already in the release plan:** HANDOFF §4 anchoring rule; none of these words is named.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-13 · F196 · medium · accuracy
**'مدخل <city>' loses both the governorate and the place: entrance closures of Nablus/Jenin are dropped**

- **Where:** `cascade/news.py:468`
- **What goes wrong:** The most movement-relevant closure shape — the eastern/western entrance of a city being shut — is neither placed nor governorate-located and never becomes an event or a road_closure state.
- **Fix:** Remove مدخل from _STREET_HEADS (keep شارع/طريق), or treat 'مدخل <governorate>' as the city with how='cue' and gov_ok=True; add both probe sentences as tests expecting closure/shooting with governorate set.
- **Evidence (audited code):**
```
`_STREET_HEADS = frozenset(["شارع", "طريق", "مدخل"])` and `_find_governorate`: `if i > 0 and _bare(toks[i - 1]) in _STREET_HEADS: continue` (:474); in `capture()` a cue word followed by a governorate returns nothing (`if not gov_head: return`, :709). Probes: read('الاحتلال يغلق مدخل نابلس الشرقي امام المركبات') → unclear 'no resolvable West Bank place' (incident_type closure was read); read('اطلاق نار على مدخل جنين الشرقي') → unclear. The round-8 justification (:466-467) names only شارع القدس / شارع نابلس; the test at tests/test_news.py:625-631 covers شارع only.
```
- **Verifier's check:** Reproduced: read('الاحتلال يغلق مدخل نابلس الشرقي امام المركبات') → unclear, incident_type=closure, reason='no resolvable West Bank place', governorate=None, place_candidates=[]; read('اطلاق نار على مدخل جنين الشرقي') → unclear, shooting, no place, no governorate. Mechanism: _STREET_HEADS at cascade/news.py:468 includes مدخل; _find_governorate skips a governorate token whose predecessor is a street head (:474-475); and in capture() a cue word followed by a governorate returns nothing because `if not gov_head: return` — that check is at :749, not :709 as the evidence states (corrected). مدخل is …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-14 · F203 · medium · data-integrity
**Cross-batch dedup re-introduces the 'anchored on the first report' defect: long streams split at 90 min from the earliest report**

- **Where:** `ingest/sources/news_incidents.py:566`
- **What goes wrong:** Four channels report one raid at 20:00, 21:00, 22:00, 23:00, each in its own timer tick: 21:00 joins E1 (60 min), 22:00 is 120 min from 20:00 → new event E2, 23:00 joins E2. Two events, corroboration split 2/2 instead of one event with 4 units (confidence 0.91 vs 0.96) — the DECISIONS 09-24 correction's failure, smaller.
- **Fix:** Compare against the event's LATEST linked claim: `occurred_at` stays earliest, but store attrs.last_report_at on every join/insert and use `ABS(EXTRACT(EPOCH FROM (COALESCE((attrs->>'last_report_at')::timestamptz, occurred_at) - %s)))`.
- **Evidence (audited code):**
```
Fallback join: `AND ABS(EXTRACT(EPOCH FROM (occurred_at - %s::timestamptz))) <= %s` (:566-567) compares the new cluster's earliest report with the EXISTING event's occurred_at, which 'KEEPS its earliest report time' (:578-580). cluster_by_window (:132-160) documents that comparing against the first member 'is not a rule' and chains on the neighbour instead — but only within one batch, and the timer's batches are 5-minute slices.
```
- **Verifier's check:** Code confirmed: the fallback at ingest/sources/news_incidents.py:556-567 compares the incoming cluster's earliest reported_at with the existing event's occurred_at, and :577-584 deliberately keeps occurred_at at the earliest report. cluster_by_window (:132-160) chains on the neighbour but only within one batch; ops/classify-news.sh:10 runs the classifier every tick with no --rebuild, so reports arriving in separate ticks hit the fallback path. Walking the scenario through the code: 21:00 joins E1 (60 min ≤ 90), 22:00 is 120 min from E1.occurred_at → no prior → INSERT E2, 23:00 joins E2. Two ev …
- **Already in the release plan:** DECISIONS 2026-09-24 CORRECTION entry (fixed in-batch only)
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-15 · F205 · medium · data-integrity
**Closure observations are re-inserted on every join and every re-read: a version bump without --rebuild duplicates them**

- **Where:** `ingest/sources/news_incidents.py:644`
- **What goes wrong:** CLASSIFIER_VERSION 1.8.1 → 1.8.2 run by the timer (no --rebuild): all 33k claims are re-read, each closure cluster joins its existing event and inserts a second identical (place, road_closure, observed_at, source, 'closed') row — the HANDOFF §4 fuel-spool shape ('a comment claiming idempotence'). count(*) vs count(distinct …) on road_closure rows diverges by one full corpus per bump.
- **Fix:** Skip the insert when a row with attrs->>'from_event' = event_id and the same source_id/observed_at exists, or add a partial unique index on (place_id, state_kind, source_id, observed_at) WHERE attrs ? 'from_event' with ON CONFLICT DO NOTHING.
- **Evidence (audited code):**
```
`INSERT INTO state_observation (place_id, state_kind, value, raw_value, observed_at, source_id, confidence, direction, direction_explicit, modality, attrs) VALUES (...)` (:644-650) runs for every cluster after both the join branch and the insert branch, with no ON CONFLICT and no existence check; the only cleanup is the rebuild step `DELETE FROM state_observation WHERE state_kind = %(closure)s AND attrs ? 'from_event'` (:358). The cc upsert at :656 is what the 'Re-runnable' comment (:653) refers to.
```
- **Verifier's check:** Code confirmed: the INSERT INTO state_observation at ingest/sources/news_incidents.py:642-650 sits after the join/insert if-else at the cluster-loop level, so it runs on every cluster including those that joined an existing event by stable_key; it has no existence check and no ON CONFLICT, and 006_state.sql:19-20 defines only non-unique indexes (023 explicitly rejects a unique one). Cleanup exists only in REBUILD_STEPS[0] (:358-359, --rebuild only) and sweep (3) (:708-714, only observations whose event was deleted). The SELECT filter (:404-408, classifier_version = current) means a CLASSIFIER_ …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-16 · F206 · medium · data-integrity
**Events are hard-deleted outside the versioning trigger: no history, as-of replay and cached event_ids lose them (hard rule 2)**

- **Where:** `ingest/sources/news_incidents.py:700`
- **What goes wrong:** A partner stores event_id 65803 from /v2/incidents; a rule change makes claim 65803's verdict 'rejected'; the sweep deletes the event, sys_period is never closed, the id 404s, and an as-of query for yesterday no longer shows an incident that was served yesterday. The event table's SCD-2 design (status, superseded_by, correction_note) exists to avoid exactly this.
- **Fix:** Replace the sweep DELETE with `UPDATE event SET status='retracted' (or the existing 'superseded'), correction_note='no claim stands behind it after classifier X'` so the versioning trigger records it; serving already filters status='believed'. If deletion is kept as policy, add a BEFORE DELETE trigger that writes the row into event_history with a closed sys_period. Migration required.
- **Evidence (audited code):**
```
`DELETE FROM event e WHERE e.attrs->>'classifier' = %(clf)s AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.event_id = e.event_id) AND NOT EXISTS (SELECT 1 FROM claim_classification cc WHERE cc.event_id = e.event_id)` (:700-704), preceded by `DELETE FROM state_observation ...` (:708). db/migrations/004_event.sql:76-77 `CREATE TRIGGER event_versioning_trg BEFORE UPDATE ON event` — there is no DELETE trigger, so event_history never receives the deleted row and `event_as_of(at)` (004:84-89) cannot return it. The code comment says 'Deleting a stale conclusion is not data loss'.
```
- **Verifier's check:** Code confirmed: ingest/sources/news_incidents.py:699-704 `DELETE FROM event e WHERE e.attrs->>'classifier' = ... AND NOT EXISTS claim ... AND NOT EXISTS claim_classification`, followed by :708-714 deleting the derived state_observation rows. db/migrations/004_event.sql:76-78 creates event_versioning_trg BEFORE UPDATE only; grep of all migrations finds no DELETE trigger on event, so a deleted row never reaches event_history and event_as_of (004:81-86, event ∪ event_history) cannot return it. event_status already has 'retracted' (002:18) and test_no_data_loss.sql T4 (:39-56) is written around re …
- **Already in the release plan:** Deliberate, documented policy: DECISIONS 2026-08-03 · 038 ('Deleting a conclusion is not data loss: every claim stays'); migrations 037/038 (038:30-55 is the same sweep); PLAN §7 P0-C.4 relies on 'the sweep ... removes orphaned events'
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### CLASSIFIER-17 · F477 · low · data-integrity
**The 'stable' key is overwritten on every join, so it no longer names the first claim and the ledger's identity guarantee does not hold**

- **Where:** `ingest/sources/news_incidents.py:590`
- **What goes wrong:** Run 1 creates E1 from claim 1 (key K1); 30 min later claim 2 arrives alone, the key lookup misses, the fallback joins E1 and rewrites its key to K2. Every subsequent lookup by the true key K1 misses and identity rests on the ±90-min fallback; after any extraction change (name_key moves) the fallback misses too, a new event is minted and E1 is swept (hard-deleted). 'ids survive a rebuild' (§11 17:05 'P0-C done', '0 duplicate keys') is true only while nothing changes; '0 duplicate keys' is guaranteed by the unique index regardless.
- **Fix:** Never include stable_key in the join UPDATE (keep the event's original key); if the incoming cluster's first claim id is lower than the event's, keep the lower. Record `first_claim_id` in attrs and derive the key from it. Add a DB-backed test on main-server: run classify(), --rebuild, assert the set of (event_id, stable_key) is unchanged.
- **Evidence (audited code):**
```
On the join path the UPDATE merges `json.dumps({"channels": sorted(merged_units), "merged_reports": (prev_n + len(cluster)), "stable_key": stable_key, "name_key": name_key or ""})` into attrs (:588-592) where `stable_key = _stable_key(itype, place_id, name_key, min(m[0] for m in cluster))` (:532) is computed over THIS batch's cluster — a later claim id whenever the prior was found through the fallback lookup (:556-567). Migration 076 and PLAN P0-C.4 define the key as sha1(...|first claim). tests/test_incident_clustering.py:102 only asserts the SQL string exists in the source; no test rebuilds and compares ids.
```
- **Verifier's check:** Code confirmed: ingest/sources/news_incidents.py:532 computes stable_key from min(claim_id) of THIS batch's cluster; when the key lookup (:548-552) misses and the ±90-min fallback (:556-567) finds the event, the join UPDATE at :585-592 merges `"stable_key": stable_key` into attrs, replacing the event's original key with one derived from a later claim. Migration 076 and ops/backfill_stable_keys.py:31-46 (MIN(c.claim_id)) define the key as first claim. tests/test_incident_clustering.py:98-104 only asserts a SQL substring exists, as claimed. The '0 duplicate keys' proof is indeed guaranteed by th …
- **Already in the release plan:** PLAN §7 P0-C.4 (key = first claim; 'test that a --rebuild preserves ids' was never written); §11 2026-09-24 17:05 'P0-C done' proves only '0 duplicate keys'; migration 076 header
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **CLASSIFIER-V01 · F188 · medium** — Unanchored ارتقاء / داهم: 'للارتقاء بمستوى المدارس' is a death, 'الخطر الداهم' is a raid — `cascade/news.py:138`
  - scenario: Municipal/education posts on the governorate channels ('الارتقاء بالخدمات') become deaths in the named village; 'خطر داهم' features become raids.
  - suggested fix: `\bارتقاء\b` and `\b[تي]?داهم\w*` with a negative lookbehind for `ال` (`(?<!ال)داهم`), plus a regression test for each.
- **CLASSIFIER-V02 · F189 · medium** — Shooting pattern misses إطلاق النار (with article) and أطلقت/أطلقوا النار — `cascade/news.py:148`
  - scenario: Shots fired at a vehicle with no casualty word are dropped; where another verb exists the shooting is mislabelled (siege/settler_attack).
  - suggested fix: `اطلاق\s+(?:ال)?(?:نار|رصاص)|اطلق\w*\s+(?:\S+\s+){0,3}?(?:النار|الرصاص)|[يت]طلق\w*\s+(?:\S+\s+){0,2}?(?:النار|الرصاص)`; add the probe sentence as a test.
- **CLASSIFIER-V03 · F191 · medium** — Flying checkpoints and troop positions — the traveller's most needed shape — are 'no incident verb' — `cascade/news.py:191`
  - scenario: A flying checkpoint on Ramallah's exits is reported by a channel and never becomes an event or a state; the route/checkpoint layers cannot see it.
  - suggested fix: Add a `checkpoint` (flying) shape as a closure-class event: `حاجز\s+(?:طيار|عسكري|ل?قوات\s+الاحتلال|للاحتلال|للجيش)\s+(?:\S+\s+){0,3}?(?:علي|عند|قرب|بين|للخارج|للداخل)` and `احتجاز|[يت]حتجز\w*|تنكيل|[يت]فجر\w*` verbs; measure on round 9.
- **CLASSIFIER-V04 · F098 · medium** — 'احصائيه' anywhere rejects a same-day Red Crescent casualty tally as period statistics — `cascade/news.py:314`
  - scenario: The Red Crescent's running count of today's injuries in Husan ('حتى اللحظة' — up to this moment) is dropped; the injury count for an active raid never becomes an event.
  - suggested fix: Require a period frame: `احصائيه\s+(?:\S+\s+){0,3}?(?:خلال|منذ|شهر|عام|اسبوع|النصف)` or exclude when `حتي اللحظه|حتي الان|اليوم` is present. Add claim 33's text as an injury regression.
- **CLASSIFIER-V05 · F193 · medium** — A drone strike at the head of the text is rejected as a 'gathering' (مسيرة = march and = drone) — `cascade/news.py:340`
  - scenario: Drone strikes in Jenin/Tulkarm/Tubas (a real class since 2024) and suppressed weekly marches with casualties are dropped when the text opens with them.
  - suggested fix: Exclude the drone reading: `(?<!طايره )(?<!طايرات )مسيره(?!\s+(?:اسراييليه|للاحتلال|تستهدف|تقصف))`, and exempt the head rule when a harm/shooting pattern also matches.
- **CLASSIFIER-V06 · F194 · medium** — Reject list substrings: اليمن inside اليمنى, الاردن inside غور الأردن — injuries and Jordan Valley incidents rejected as foreign news — `cascade/news.py:353`
  - scenario: Injury reports naming a limb (اليد/القدم/الساق اليمنى) and settler attacks on herders in the Jordan Valley (غور الأردن, an everyday locator for Tubas/Jericho) are dropped before any incident pattern runs.
  - suggested fix: Anchor: `\bاليمن\b`, `\bالاردن\b(?<!غور الاردن)(?<!نهر الاردن)` (or a negative lookbehind for غور/نهر/وادي), and generally give every ≤5-letter reject term \b on both sides.
- **CLASSIFIER-V07 · F195 · medium** — 'statement' reject drops students, summonses, settlers 'heading to' a village and Health-Ministry death announcements — `cascade/news.py:381`
  - scenario: Student casualties and arrests (the university towns Birzeit/Nablus/Hebron), arrests after a summons, settler movements toward a village, and the authoritative death announcer are all silently dropped as 'statements'.
  - suggested fix: `طالب\w* ب` → `(?:ي|ت)طالب\w*\s+ب|طالبت?\s+(?:ال\S+\s+)?ب` (the verb needs a subject/tense form), `دعا\w* الى` → `\bدعا\s+الي|\bدعت\s+الي|يدعو\s+الي`, drop `توجهوا\s+الي` (keep the first-person `توجهوا` only at head with an imperative marker), and remove `وزارة الصحة تعلن` (the casualty frame at :140-145 already reads these).
- **CLASSIFIER-V08 · F101 · medium** — The governorate reader takes القدس from organisation names (اذاعة/سرايا/كتائب/جامعة القدس) and جنين from 'الجنين' (the fetus): the named village is then rejected as 'outside stated governorate' and the event pins to Jerusalem — `cascade/news.py:471`
  - scenario: A raid on Yabad (Jenin) posted by 'اذاعة القدس' or a PIJ 'سرايا القدس' clash bulletin from Tulkarm is stored as an incident 'somewhere in Jerusalem governorate'; a miscarriage at Huwara checkpoint is filed under Jenin. The bearing reader already knows the right governorate ('جنوب غرب جنين') but _find_governorate ignores it.
  - suggested fix: Extend _STREET_HEADS with organisation heads (سرايا, كتائب, اذاعه, صحيفه, قناه, شبكه, جامعه, مستشفي, نادي, مركز, بلديه) and skip the definite 'الجنين' (governorates that take the article are only الخليل/القدس/البيره); prefer a governorate anchored by a bearing word or a settlement word over a bare first mention. Tests for the three sentences.
- **CLASSIFIER-V09 · F102 · medium** — Funeral gate rejects a death reported 'moments ago' when the post opens with وداع, and `\bنزف\b` (bled) is a funeral word — `cascade/news.py:580`
  - scenario: The first report of a killing at Askar camp, which says the man was shot 'قبل قليل', is dropped as an obituary; a death by bleeding at a checkpoint is dropped because نزف (we announce a martyr) is also نزف (bled). Deaths are the type the round-8 gate found weakest (0.60), and these are the recall side of the same rule.
  - suggested fix: Exempt fresh-time markers from both funeral regexes: if `قبل (?:قليل|لحظات|دقائق)|فجر اليوم|صباح اليوم|الان` occurs within ~8 tokens of ارتقي/استشه, do not reject. Replace `\bنزف\b` with `\bنزف\s+(?:حركه|كتائب|سرايا|شهيد)` (the eulogy frame only). Add 54949's text and the bleeding sentence as regressions.
- **CLASSIFIER-V10 · F306 · medium** — 'مدينة بيت لحم' can never be a named place: the two-token governorate is dropped by the reader — `cascade/news.py:748`
  - scenario: Every raid, arrest or shooting reported as 'في مدينة بيت لحم' has no candidate, falls to `resolve_place(r.governorate)` (news_incidents.py:337-341) and is stored with place_precision='governorate', so it is excluded from by_place (serve/app.py:892) and counted as 'located only to the governorate', while the same sentence about Nablus, Jerusalem or Ramallah is a named pin — Bethlehem city disappear …
  - suggested fix: In `capture()` test the two-token head first: `two = " ".join(head); if two in _GOV_TOKENS or head[0] in _GOV_TOKENS:` and keep `gov_head` semantics; add `test_a_two_word_city_named_with_a_settlement_word_is_a_candidate` to tests/test_place_extraction.py.
- **CLASSIFIER-V11 · F197 · medium** — First-match single label drops the closure STATE whenever a casualty or arrest is in the same message — `cascade/news.py:929`
  - scenario: Most raid messages that say the entrance was closed also report injuries or arrests, which outrank closure — so exactly the closures embedded in the busiest events never reach state_current.
  - suggested fix: Compute is_closure independently: `is_closure = bool(_CLOSURE_RE.search(norm)) and not _REOPEN_RE.search(norm)` regardless of the event label (and keep the label for the event); news_incidents writes the road_closure observation from is_closure, not from itype.
- **CLASSIFIER-V12 · F198 · medium** — A raid that mentions the house of a martyr killed weeks ago is served as a fresh death — `cascade/news.py:940`
  - scenario: Every raid on a martyr's family home ('تداهم منزل الشهيد X الذي ارتقى …') — a routine punitive-raid shape — creates a second death event at that village on the raid's date; deaths are the weakest measured type and the plan's first gate.
  - suggested fix: When a raid/arrest/demolition verb matches AND the death verb occurs inside `(?:منزل|منازل|بيت|عائله|والد|ذوي|نجل|شقيق)\s+(?:ال)?شهيد\S*\s+(?:\S+\s+){0,4}?(?:الذي|التي|الذين)\s+(?:استشهد|ارتقي)`, demote death and re-run first-match on the remaining patterns; add الشهر الماضي/قبل اسبوع(ين)/قبل شهر to aftermath.
- **CLASSIFIER-V13 · F199 · medium** — The funeral gate rejects the whole message, losing casualties at the funeral and a real death it also carries — `cascade/news.py:941`
  - scenario: Injuries during a funeral procession and deaths reported through a farewell line ('يودّع والده الذي ارتقى … خلال تصدي الأهالي') are dropped entirely rather than demoted from death to the next matching type.
  - suggested fix: On a funeral match, remove 'death' from consideration and re-run _first_match over the other patterns (keeping the head-funeral reject as is); treat `قبل قليل|قبل لحظات` as overriding the funeral gate.
- **CLASSIFIER-V14 · F200 · medium** — Traffic-accident reject contradicts 9 hand verdicts from rounds 1/5 and the rescore hides it by re-reading round 8 only — `cascade/news.py:957`
  - scenario: A crash blocking Route 60 with fatalities — precisely movement information — is dropped; the labelling policy changed between rounds without being recorded, so the projected 0.876 is computed against one round's policy while earlier rounds say the opposite.
  - suggested fix: Keep road-blocking crashes: if _ACCIDENT_RE and a road object (شارع|طريق|الالتفافي|مفرق) are present, emit `closure`-class or a new `road_accident` type instead of rejecting; record the policy in the scored files' notes and re-judge the 9 rows.
- **CLASSIFIER-V15 · F103 · medium** — Testimony carve-out is keyed on a siege WORD anywhere, not on the served type: an interview with a council head is served as a settler attack — `cascade/news.py:963`
  - scenario: Any feature that mentions a siege in passing keeps its testimony verdict alive for every other type; the carve-out was measured for sieges (2 vs 2 in round 7) and applied to all nine types. The corpus row above is a hand-labelled false positive that the current classifier still serves.
  - suggested fix: `if tm and itype != "siege":` (the served type, not a word anywhere), and add claim 43181's text as a rejection regression.
- **CLASSIFIER-V16 · F308 · medium** — _fuller_form treats a checkpoint's 'حاجز X' alias as the fuller form of village X and labels the result kind='locality' — `ingest/sources/news_incidents.py:203`
  - scenario: 'قوات الاحتلال تقتحم قرية بيت ايبا غرب نابلس' where the village row still has only Latin keys: exact and containment miss, `_fuller_form` finds '% بيت ايبا' on the checkpoint's alias 'حاجز بيت ايبا', returns its place_id with kind hard-coded 'locality', and locate() files a village raid on the checkpoint row as precision 'named' — the case test_locate_prefers_the_camp_over_the_checkpoint guards on …
  - suggested fix: Exclude checkpoint/crossing/road kinds from `_fuller_form` unless `how == 'station_word'`, return the row's real kind, and prefer aliases whose extra token is not a station word (حاجز/معبر/مفرق/بوابة); measure with ops/place_measure.py how many current 'fuller' placements sit on checkpoint rows.
- **CLASSIFIER-V17 · F201 · medium** — Copies across news channels count as independent corroboration (no independence groups for news sources) — `ingest/sources/news_incidents.py:424`
  - scenario: A single report mirrored by three sister channels is served with independent_sources=4 and confidence 0.96 ('4 channels agree'); the MCP answer says only solo events are single-source.
  - suggested fix: Run learn/source_independence over the incident channels (P0-C.5) and, until then, collapse units by claim content_hash within a cluster (two claims with the same content_hash are one unit).
- **CLASSIFIER-V18 · F289 · medium** — A classifier version bump on the 5-minute timer re-reads the whole corpus in one transaction under TimeoutStartSec=900; the ledger already records the kill→rollback→retry loop and the timer still passes no --limit — `ingest/sources/news_incidents.py:445`
  - scenario: The corpus grows ~500 claims/day from 14 channels; the next CLASSIFIER_VERSION bump at ~60–80k claims exceeds 900 s on the timer, systemd kills it, the transaction rolls back, the advisory lock is released, and five minutes later the same full pass starts again — an alert every tick and no new claims classified until someone runs it by hand.
  - suggested fix: Have the timer pass `--limit 4000` (a bump then drains across ticks, each committing) or commit inside `classify()` every N claims — safe now that events join by stable key (P0-C.4) and the orphan sweep is idempotent; keep `--rebuild` as a hand operation with no timeout.
- **CLASSIFIER-V19 · F202 · medium** — One claim that raises stops the whole feed with no provenance — `ingest/sources/news_incidents.py:456`
  - scenario: A claim whose candidate makes a resolver query error (or any future exception in _extract_places) aborts the run; OnFailure alerts (good), but every 5-minute tick fails on the same claim and no newer claim is classified until someone edits code. The failure is noticed but the feed is dead, and nothing in claim_classification says why.
  - suggested fix: Wrap the per-claim read+locate in try/except that records verdict 'unclear', reject_reason 'classifier error', place_text = exception summary, increments stats['errors'] and continues; fail the run (non-zero) if errors exceed a small fraction so systematic breakage still alarms.
- **CLASSIFIER-V20 · F309 · medium** — Run-on candidate text keys event identity: two channels naming the same village group into different events — `ingest/sources/news_incidents.py:502`
  - scenario: Channel A: 'اقتحام بلدة بيرزيت' → name_key 'بيرزيت'; channel B, two minutes later: 'اقتحام بلدة بيرزيت اثر اغلاق حاجز عطارة' → name_key 'بيرزيت اثر اغلاق'. Same type, same place_id, different key → two events, each claim_count 1 and confidence 0.70 instead of one corroborated event at 0.91, and different stable_keys across rebuilds — the same split DECISIONS 2026-09-24 CORRECTION diagnosed for حبل …
  - suggested fix: When `res.method == 'contains'` (or the alias is shorter than the candidate) set `named_place` for grouping to `res.matched_alias` / the place's own folded name and keep the raw capture in attrs.place_text only; make `capture()` stop at tokens that are not Arabic/Latin letters and at '@'/'#' handles; add a test that 'بلدة بيرزيت' and 'بلدة بيرزيت اثر اغلاق' produce one name_key.
- **CLASSIFIER-V21 · F343 · medium** — Event stable_key embeds place_id and name_key: every resolver improvement re-mints ids, the join fallback overwrites keys, and the orphan sweep deletes the old events — `ingest/sources/news_incidents.py:532`
  - scenario: A partner stores event_id 65803 (raid at حبلة). Migration 078/promote_named_localities moves حبلة reports to a different place row; the next --rebuild computes a new key, finds no event by key, the fallback fails on place_id, a new event is minted, the old one ends with claim_count 0 and no claim pointing at it and is DELETEd by the sweep. The partner's id now 404s with no forwarding; G3's 'stable …
  - suggested fix: Mint the key from (classifier, type, earliest claim id) only and carry place_id/name_key as mutable attrs; when re-clustering moves an event, UPDATE place_id in place (the 004 trigger keeps history); replace the orphan DELETE with status='superseded' + superseded_by so an old id forwards; add a test that a rebuild after a forced place move preserves event_id.
- **CLASSIFIER-V22 · F204 · medium** — attrs.channels only grows: demoted claims keep inflating independent_sources and confidence until a full --rebuild — `ingest/sources/news_incidents.py:583`
  - scenario: Two channels A and B report a raid → independent_sources 2, confidence 0.91. A rule change (timer, no rebuild) reclassifies B's claim as 'roundup'; the claim is unlinked (:690-694) and claim_count corrected to 1, but channels stays [A,B], independent_sources 2, confidence 0.91 — a single-source event served as corroborated.
  - suggested fix: Derive channels/independent_sources/confidence from the linked claims at the end of every run, exactly as claim_count is (one UPDATE ... FROM (SELECT event_id, array_agg(DISTINCT unit) …)).
- **CLASSIFIER-V23 · F158 · medium** — Joining a later batch overwrites the existing event's stable_key with a key derived from the later claim — `ingest/sources/news_incidents.py:590`
  - scenario: Run 1: claim 100 (raid, place P) → event E with key K(100). Run 2, 40 min later: claim 140 about the same raid → K(140) ≠ K(100) → fallback finds E → UPDATE sets E.stable_key = K(140). A consumer that stored K(100) can no longer find E by key; on the next `--rebuild` the whole cluster keys K(100) again, the key lookup misses, the fallback re-joins E and flips the key back. The identity is stable o …
  - suggested fix: Never overwrite an existing key: in the UPDATE use `attrs = attrs || <jsonb without stable_key>` and set stable_key only when absent (`CASE WHEN attrs ? 'stable_key' THEN attrs ELSE attrs || jsonb_build_object('stable_key', %s)`); compute the key from the earliest claim already pointing at the event (`MIN(claim_id) FROM claim WHERE event_id = E`) rather than the current batch's minimum. Cover with …
- **CLASSIFIER-V24 · F165 · medium** — An event's stable_key is overwritten with the joining cluster's key on every incremental join — `ingest/sources/news_incidents.py:590`
  - scenario: Fact B at 14:00 (claim 100) mints key K100; the mirror at 14:03 arrives in the next tick, misses K100 lookup? no — it computes K105, misses, joins via the ±90-min fallback (:548-561) and sets the event's stable_key to K105. An external reference stored as K100 (the documented identity) now finds nothing; a --rebuild recomputes K100 and again only reaches the event through the window fallback, whic …
  - suggested fix: On join, keep the existing stable_key (drop it from the attrs merge, or set it only when the event has none) and add a test that a two-tick ingest of one event leaves attrs.stable_key unchanged.
- **CLASSIFIER-V25 · F336 · medium** — DELETE FROM event (038 and every classifier run) bypasses SCD-2: event_as_of loses the deleted generation and event_history is orphaned, while the no-data-loss gate lists event as protected — `ingest/sources/news_incidents.py:700`
  - scenario: /v2/incidents served event 81,203 (believed, 3 sources) from 09:00 to 09:40; a classifier bump re-clusters its claims into a new stable key at 09:45; the sweep deletes 81,203. `event_as_of('2026-09-24 09:20')` — the harness that ARCHITECTURE §3.3 and 004 promise — returns nothing for it, and event_history holds two orphaned earlier versions with confidences that were never the served one. Any exte …
  - suggested fix: Retire instead of delete: `UPDATE event SET status='superseded', correction_note='orphaned by classifier <ver> on <date>' WHERE ...` (the trigger then versions it and event_as_of stays complete; the enum already has 'superseded' and 'merged'); serve only status='believed'. Keep 038's from_event observation sweep as a marker (attrs.retracted_by) rather than a DELETE. Extend test_no_data_loss.sql wi …
- **CLASSIFIER-V26 · F207 · medium** — The whole run is one transaction under a 15-minute kill: a slow re-read rolls back and retries forever — `ingest/sources/news_incidents.py:739`
  - scenario: A version bump lands in the tree; the next tick re-reads 34k claims with per-candidate resolver queries; the DB is busy (nightly rollup) and the run passes 900 s → SIGTERM → nothing committed → the next tick starts over; an alert every 15 min and no incident classified until a human runs it by hand. Raising the timeout to 3600 (HANDS §8) moves the cliff, it does not remove it.
  - suggested fix: Commit per chunk: loop `classify(limit=500)` until read==0 inside one lock, so every tick makes durable progress and a kill loses at most one chunk (the incremental filter already makes this safe).
- **CLASSIFIER-V27 · F208 · medium** — A locked tick exits 0 and heartbeats green: a stuck lock is invisible — `ingest/sources/news_incidents.py:753`
  - scenario: A hand-run --rebuild in a shell (as on 09-24) or a hung session holds the advisory lock; every tick for hours records a successful heartbeat while zero claims are classified — 'health inferred from the absence of a complaint' (HANDOFF §4).
  - suggested fix: Return a distinct exit code (e.g. 3) on locked, add it to OK_EXIT_CODES only with a counter: heartbeat --note locked, and let the watchdog alarm after N consecutive locked ticks; or have the lock holder write its own heartbeat.
- **CLASSIFIER-V28 · F471 · low** — Dead clause boundary: `[^.،؛]{0,40}?` cannot stop at a sentence because normalize() already stripped the punctuation — `cascade/news.py:117`
  - scenario: 'the governor hung up the phone. He said the road …' reads as a road closure; the protection the comment describes does not exist.
  - suggested fix: Either state the rule as a 40-character proximity (fix the comment/test) or match the closure rule on a punctuation-preserving normalisation (apply the letter folds only, keep ،؛. as clause marks).
- **CLASSIFIER-V29 · F419 · low** — 'ارتقاء' unanchored in the death pattern: 'الارتقاء بالخدمات' (improving services) is a death — `cascade/news.py:138`
  - scenario: A municipal announcement containing the idiom الارتقاء بـ (raise the level of) is served as a death in the named town; the funeral gate does not catch it and the count feeds the death precision that is already the weakest type.
  - suggested fix: `(?<!\S)ارتقاء\s+(?:شهيد|الشهيد|شاب|الشاب|طفل|فتي|مواطن|\S+\s+برصاص)` or `ارتقاء(?!\s+ب)`; regression.
- **CLASSIFIER-V30 · F472 · low** — Cumulative death tallies ('حصيلة الشهداء … منذ بداية العملية') are served as a death event — `cascade/news.py:143`
  - scenario: A running total since an operation began becomes one 'death' event pinned to the governorate each time the tally is reposted.
  - suggested fix: Add `منذ\s+بدايه\s+(?:ال)?(?:عمليه|عدوان|حرب|الاجتياح)|منذ\s+بدء` to statistical; keep the per-village tally shape (tests/test_news.py:154).
- **CLASSIFIER-V31 · F420 · low** — Shooting requires the verb and النار to be adjacent: the MSA VSO order 'اطلقت قوات الاحتلال النار' has no incident verb — `cascade/news.py:148`
  - scenario: Wire-style reports (Wafa, Maan) put the subject between verb and object; every such shooting without a casualty noun is dropped.
  - suggested fix: `اطلق\w*\s+(?:\S+\s+){0,3}?(?:النار|الرصاص)` and `[يت]طلق\w*\s+(?:\S+\s+){0,3}?(?:النار|الرصاص)`; also the definite 'الرصاص الحي' beside 'رصاص حي'. Regression.
- **CLASSIFIER-V32 · F421 · low** — 'اختناق' is an injury in news.py and a jam in checkpoint_text.py: a traffic-jam bulletin that reaches the news classifier becomes an injury at the checkpoint — `cascade/news.py:181`
  - scenario: News channels routinely post 'ازمة خانقة واختناق مروري على حاجز قلنديا'; it is served as an injury event at the checkpoint (the status-bulletin reject only knows 'احوال').
  - suggested fix: `اختناق(?!\w*\s+مروري)` or require the gas frame `اختناق\w*\s+(?:بالغاز|جراء|نتيجه)`; add the sentence as a rejection/unclear regression.
- **CLASSIFIER-V33 · F422 · low** — 'gathering' reject at the head of the text drops the weekly-march injury reports ('مسيرة كفر قدوم الاسبوعية: اصابات…') — `cascade/news.py:340`
  - scenario: The Kafr Qaddum and Beita weekly marches are reported as 'مسيرة X: N اصابات' every Friday; the head-anchored reject drops the injuries with the march.
  - suggested fix: Do not reject a gathering when a harm/shooting word (_HARM_RE, قمع, قنابل الغاز, رصاص) follows; or move 'gathering' to a check after the incident type and apply it only when itype is None. Regression.
- **CLASSIFIER-V34 · F423 · low** — Dead reject branches `\bحماس\s*:` and `\bفتح\s*:` — normalize() turns the colon into a space before matching — `cascade/news.py:384`
  - scenario: A faction-headed statement ('فتح: تعلن الحداد …') is rejected only if another branch happens to fire (نبارك, ندين); the two branches written for it are unreachable, and the comment implies they work.
  - suggested fix: Write the head form on normalized text: `^\W*(?:حركه\s+)?(?:حماس|فتح|الجهاد)\s+(?:تعلن|تدين|تبارك|تنعي|تزف|تحذر)` or match the colon in read() before normalising. Test with the sentence above.
- **CLASSIFIER-V35 · F473 · low** — Dead reject arms `\bحماس\s*:` / `\bفتح\s*:` — the colon is stripped before matching — `cascade/news.py:384`
  - scenario: 'حماس: اقتحام المستوطنين للأقصى جريمة' (a faction reacting to an event) is not rejected as intended.
  - suggested fix: Match `^\W*(?:\S+\s+)?(?:حماس|فتح|الجهاد الاسلامي)\s+(?!تقتحم|تعتقل)` at the head, or keep punctuation for reject matching.
- **CLASSIFIER-V36 · F424 · low** — _STOP_TOKENS keeps ة/ى spellings whose normalized forms are missing: 'على' never ends a name, so captures run on ('المواطنين علي', 'جبل علي طاهر') — `cascade/news.py:503`
  - scenario: 'قرية X على الطريق الالتفافي' captures 'X علي' and a prefix/bearing candidate (exact-only) then fails to resolve; the exact-only readers lose the name entirely.
  - suggested fix: Build the frozenset through normalize() (`frozenset(normalize(w) for w in [...])`) exactly as _GOV_TOKENS and PLACE_WORDS' twins are, and add 'علي' + 'الاسراييلي(ه)' + 'بحمايه' + 'بوره'. One assertion in tests/test_place_extraction.py that every stop token is normalize-stable.
- **CLASSIFIER-V37 · F474 · low** — `\bنزف\b` in the funeral lexicon is also 'haemorrhage': a death by bleeding is an obituary — `cascade/news.py:580`
  - scenario: Health-ministry style death reports that name the cause of death ('نزف حاد') are dropped.
  - suggested fix: `\bنزف\b(?=\s+(?:الي|شعبنا|جماهير|ابناء))` or `نزف\s+(?:الي|شعبنا)` only; keep تزف/يزف.
- **CLASSIFIER-V38 · F475 · low** — 'testimony' reject drops a medic narrating a child's injury; `[يت]روي\s+` is not testimony-specific — `cascade/news.py:599`
  - scenario: Wire phrasing 'مصادر/تقارير تتحدث عن' and first-responder accounts are dropped as testimony.
  - suggested fix: Require a person/subject noun before the verb (`(?:المواطن|الشاب|السيده|الاسير|\S+ من بلده)\s+\S+\s+[يت]تحدث`) and exempt `مصادر|تقارير|شهود` subjects.
- **CLASSIFIER-V39 · F536 · low** — event_versioning's 'the INSERT will fail loudly' guarantee is false: adding a column to event silently stops versioning it, and no test asserts event/event_history column parity — `db/migrations/004_event.sql:42`
  - scenario: A migration adds `event.verified_by TEXT`. Postgres accepts 18 values into the 18-column event_history (or, if someone also adds the column there, fills it with DEFAULT): every UPDATE succeeds and the new column's history is silently absent from event_as_of. No SQL gate compares information_schema.columns of the two tables; test_schema.sql T2/T3 only check confidence.
  - suggested fix: Change the trigger to `INSERT INTO event_history SELECT (OLD).*` with `sys_period` overridden via a row-type assignment (`OLD.sys_period := closed; INSERT INTO event_history SELECT OLD.*`), which fails on column-count mismatch as the comment promises, and add a test_schema check that event and event_history have identical column lists.
- **CLASSIFIER-V40 · F538 · low** — claim_classification keeps only the latest verdict per (claim, classifier), so 017's 'classifier_version makes those runs comparable' cannot be true from the table — `db/migrations/017_claim_classification.sql:34`
  - scenario: After 1.8.1's corpus re-read (ledger 19:12) the 1.8.0 verdicts are gone; the only record of what 1.7.1 said about a claim is the hand-scored ndjson rounds. A question like 'which claims did 1.8.1 newly reject as obituary that 1.8.0 filed as death' needs a re-run of the old code, and a bad version cannot be rolled back to the previous generation's classifications.
  - suggested fix: Either make classifier_version part of the key (PK (claim_id, classifier, classifier_version), with a `current` flag or a view picking the newest) or drop the comparability claim from 017 and point at ops/incident-rounds.ndjson as the record.
- **CLASSIFIER-V41 · F459 · low** — news_incidents claims its 0.70 single-source trust is 'the same … used for checkpoint state'; the checkpoint value is the measured 0.85 — `ingest/sources/news_incidents.py:126`
  - scenario: A reader comparing event confidence 0.70 with checkpoint confidence 0.85 believes the two are on one scale; a future edit 'aligns' one to the other in the wrong direction.
  - suggested fix: Either import the constant from resolve.belief with a note that events are not backtested, or state that 0.70 is an unmeasured assumption for events.
- **CLASSIFIER-V42 · F476 · low** — stable_key lookup cannot use the partial index (missing `attrs ? 'stable_key'` predicate) — `ingest/sources/news_incidents.py:551`
  - scenario: Rebuild time grows quadratically with the event table; not visible at 5k events, will be at 50k.
  - suggested fix: Add `AND attrs ? 'stable_key'` to the query (or make the index non-partial).
- **CLASSIFIER-V43 · F506 · low** — A lock-skipped classifier run exits 0 and beats 'classify-news ok' though nothing ran; a wedged lock holder keeps the job green indefinitely — `ingest/sources/news_incidents.py:753`
  - scenario: A hand-run `--rebuild` session is suspended (laptop lid, `kill -STOP`, an idle psql that took the key): every 5-minute tick returns 0 and beats; `classify-news` reads ok in /health and the watchdog for hours while no claim is classified; only `road_closure`'s own cadence (collector 'healthy', so `silent` after its threshold) can notice.
  - suggested fix: Return a distinct code (e.g. 4) on `locked` and record `detail={"locked": 1}` via a beat only if the holder's own heartbeat is fresh; or in with-heartbeat treat N consecutive locked ticks (detail) as a failure.
- **CLASSIFIER-V44 · F479 · low** — Clustering test file: tautological source-grep assertion and a docstring stating the falsified cause — `tests/test_incident_clustering.py:102`
  - scenario: The join lookup could be broken in any way that keeps the string (e.g. the window predicate changed) and the test stays green; a new session reads the docstring and re-derives the wrong cause.
  - suggested fix: Replace the grep with a DB-backed test on main-server (create two claims 30 min apart in two classify() calls, assert one event; then --rebuild and assert ids unchanged); fix the docstring.
