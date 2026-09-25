# Plan 03 · Route verdict (corridor)

Phase 1 — Safety inversions — a wrong 'open' or a hidden closure. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `resolve/corridor.py`, `tests/test_corridor.py`, `tests/test_route_omissions.py`
- **Tests to run after every task:** `tests/test_corridor.py tests/test_route_omissions.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Implement PLAN §6 G2 as written: `likely_open` only when coverage measured on checkpoints WITH a current reading is >= 0.6 and no closure within ENDS_KM at either end; `slow` must also carry doubts; direction reconciliation must match checkpoint_serving. Keep verdict vocabulary stable (likely_open stays the token; renderers own words). Pure-function tests on _score/_doubts/_closures_at_ends with synthetic CheckpointOnRoute lists.

- Confirmed tasks: 4 · verify-first tasks: 14 · refuted (skip): 0

## A. Confirmed tasks (independently verified — do these first, in order)

### ROUTE-01 · F071 · high · safety
**`likely_open` is produced with coverage far below G2's 0.6 on routes shorter than ~25 km: the code checks an absolute 10 km gap, never coverage_fraction**

- **Where:** `resolve/corridor.py:421`
- **What goes wrong:** Ramallah→Bir Zeit (~10 km) with one tracked checkpoint at km 1 reported open and nothing for the remaining 9 km: coverage_fraction 0.1, verdict `likely_open`, AR 'الطريق سالك على الأغلب'. The code's own comment (:93-95) says a 10 km gap is where 'the unwatched part … starts being most of the drive' — on a 10 km drive a 9 km gap IS most of the drive. The ledger records this gate as done; the code does not implement it.
- **Fix:** In _doubts and doubt_records add a second reason: `frac = (coverage or {}).get('coverage_fraction'); if frac is not None and frac < 0.6 and gap > 0: out.append(...)` (record kind 'low_coverage' with the fraction), so `open` requires both the fraction and the absolute gap; add tests for a 12 km route with a 9 km gap (→ unverified) and keep the 53 km / 9 km case open (coverage 0.83).
- **Evidence (audited code):**
```
corridor.py:420-421: `gap = float((coverage or {}).get("longest_gap_km") or 0.0)` / `if gap >= UNVERIFIED_GAP_KM:` — the only coverage test; `coverage_fraction` is never read by _doubts/doubt_records (:394-431). Executed: dist 12 km, gap 9 km, coverage_fraction 0.25 → likely_open; dist 11 km, gap 9.9 km, coverage 0.10 → likely_open; dist 20 km, gap 9.9, coverage 0.51 → likely_open. PLAN §6 G2: '`open` only when corridor coverage ≥ 0.6'; §11 17:05 'P0-B.2/3 · done'; §7 P0-B.3 '`open` only under G2 (coverage ≥ 0.6 and no exit closure)'.
```
- **Verifier's check:** Confirmed. The only coverage test in `_doubts` (corridor.py:420-421) and `doubt_records` (:400-401) is the absolute longest_gap_km >= 10. Nothing reads coverage_fraction when deciding the verdict: it is used only for the `verdict_covers` note and the summary suffix (:582-590). Run on verify/v1.py: 12 km route, one open checkpoint at 0.75 → coverage 0.25, gap 9.0 km → likely_open; 11 km route, along 0.1 → coverage 0.10, gap 9.9 → likely_open. On routes of 25 km or more a coverage below 0.6 implies a gap over 10 km, so only short routes escape. Two mitigations exist but do not refute it. First, …
- **Already in the release plan:** PLAN §6 G2 ('open only when corridor coverage ≥ 0.6'); §7 P0-B.3; §11 2026-09-24 17:05 claims P0-B.2/3 done, which the code contradicts
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### ROUTE-02 · F318 · medium · safety
**`slow` asserts the road is passable (سالك) without the coverage or exit-closure checks that `open` must pass — it returns before `_doubts` is computed**

- **Where:** `resolve/corridor.py:376`
- **What goes wrong:** A route whose only watched checkpoint is a congested one 45 km in, with the first 45 km unwatched and the exit closed: answer 'the road is passable but congested', no blind-stretch reason, no exit closure (see the critical finding). `slow` is the same permission-shaped claim as `open` plus a delay; PLAN G2 restricts 'open' only because the vocabulary assumed slow implies open.
- **Fix:** Keep the word `slow` (a reported delay is evidence) but compute doubts for it: in _score call _doubts before the slow branch and append them to the sentence; in _corridor_for populate `doubts` when verdict in ('slow','unverified'); renderers already speak doubts when present if the :984/:133 gate becomes `if best.get('doubts')`. Alternatively emit `slow_unverified`; either way add a test: slow + exit closure → the closure is in doubts and in both answers.
- **Evidence (audited code):**
```
corridor.py:376-380: `if slow: … return "slow", (f"Passable but congested at {names}…")` precedes :384 `doubts = _doubts(coverage, near_misses, distance_km)`. Executed: one open at 0.9, one congested at 0.95, 45 km blind stretch, Beit El closed 2 km off at along 0.03 → ('slow', 'Passable but congested at B. 2 of 2 checkpoints reported.'). AR renderer :927 says 'الطريق سالك بس فيه ازمة'. tests/test_corridor.py:163-172 pins that slow survives doubts (the verdict WORD), and the docstring (:357-360) justifies not degrading it — but nothing attaches the doubts to a slow route either (:647 gates `doubts` on unverified).
```
- **Verifier's check:** The code claim is correct: corridor.py:376-380 returns 'slow' before `_doubts` runs at :384, and :647 attaches doubts only for unverified. The failure scenario overstates the harm, though. On verify/v1.py (open at 0.9, congested at 0.95, 50 km, gap 45 km, Beit El closed at along 0.03), both answers DO speak the blind stretch through cover_note: 'ما في حاجز مسجّل على 45 كيلو ... فهالمسافة بلا تحقّق' / 'No checkpoint is tracked for 45 km'. corridor.py:585-590 also appends it to the summary. The missing exit closure is finding [0]'s defect in the renderers and is fixed there. Keeping `slow` undeg …
- **Already in the release plan:** PLAN §7 P0-B.1 (in-flight tests deliberately pin slow surviving doubts); §6 G2 restricts only `open`
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### ROUTE-03 · F320 · medium · correctness
**The corridor reconciles directions differently from checkpoint_serving: a stale direction-specific `closed` outranks a fresh `both`=open, so can_i_travel says blocked while checkpoint_status says open**

- **Where:** `resolve/corridor.py:525`
- **What goes wrong:** 10:00 a channel writes 'بيت ايل مغلق للداخل' (inbound=closed); 14:55 nine channels write 'بيت ايل سالك' (both=open, 3 independent groups). checkpoint_status(بيت ايل) → open for both travel directions (freshest wins). can_i_travel through Beit El → worst = closed → `blocked`, 'مسكّر عند بيت ايل' with the 295-minute-old reading, until 16:00 when max_assert retires the inbound row. Two headline tools contradict each other on the same checkpoint at the same minute; the traveller told 'blocked' takes a 66-minute detour for nothing.
- **Fix:** Reconcile per travel direction exactly as checkpoint_serving does: for each of inbound/outbound pick the freshest of (that direction, 'both'); then take the worse of the two (travel direction still unknown). Simplest: read `checkpoint_serving` (one row per (place, travel direction), already resolved) in ON_ROUTE_SQL instead of raw state_serving rows, and merge its two rows by severity. Testable with the FakeConn harness (rows for both/inbound with different observed_at).
- **Evidence (audited code):**
```
corridor.py:512-529: rows come per (place, direction) from state_serving (`ORDER BY cp.along, f.direction`, :136) and are merged by `if order.get(v, -1) > order.get(c.flow, -1):` — severity only, age ignored. state_current is keyed (place_id, state_kind, direction) (011:55) so 'both' and 'inbound' rows coexist for up to max_assert 6 h each. checkpoint_serving (014/016) instead takes `DISTINCT ON (s.place_id, t.dir) … WHERE (s.direction = t.dir OR s.direction = 'both') ORDER BY … s.observed_at DESC` — freshest of specific-or-both per travel direction.
```
- **Verifier's check:** Confirmed. state_current is keyed on (place_id, state_kind, direction) (011:55), and belief.py REFRESH_SQL upserts per direction, so a later 'both' reading never retires an 'inbound' row. The corridor merge (corridor.py:519-529) keeps the most severe reading across direction rows and ignores age. checkpoint_serving (027:24-44) picks the freshest of {dir, 'both'} per travel direction, and its 'both' row reads only 'both'. On verify/v3.py, _corridor_for with a fake conn and rows both=open (5 min, 3 sources) plus inbound=closed (295 min, 1 source) returned verdict 'blocked', 'Closed at بيت ايل (2 …
- **Already in the release plan:** PLAN §4 R3 (direction essentially unused, 9% of readings) and §7 P1-A.1 (direction-resolved readings to become the majority); the inconsistency itself is not recorded
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### ROUTE-04 · F322 · medium · doc-drift
**`passes` does not label settlements and lists Hebrew/Latin-only names; the ledger marks P0-A.4 ('label settlements (`settlement:`)') done**

- **Where:** `resolve/corridor.py:618`
- **What goes wrong:** Ramallah→Nablus: settlements that carry an Arabic name in the gazetteer (عوفرا, بيت إيل, شيلو, معاليه لبونة) rank equal to Palestinian towns and are spoken as 'يمر عبر: …' with no label; a Palestinian traveller is told the route 'passes' a settlement they cannot enter. A partner reading §11 believes the labelling exists.
- **Fix:** Either correct the ledger (P0-A.4 partial: settlement labelling not built, needs a registry flag) or build it: add `place.attrs->>'settlement'` (from OSM place=… + name:he-only heuristics or Peace Now's list, migration), select it in PASSES_SQL, emit `{'name':…, 'settlement': true}` and render 'مستوطنة X' / 'settlement X'; drop rows whose only name is Hebrew script from `passes` (regex [֐-׿]).
- **Evidence (audited code):**
```
corridor.py:608-618: 'a place that has an Arabic name in the gazetteer outranks one that has only a Latin one … The registry does not flag settlements, so this is a preference, not a claim about what a place is.' `sorted(cands, key=lambda c: (not c[4], c[1]))`. No `settlement` string is emitted anywhere in resolve/ or serve/ (grep). PLAN §7 P0-A.4: 'waypoints list Palestinian localities first and label settlements (`settlement:`) — `Corridor.passes`'; §11 17:05 'P0-A.2/A.4 · done · proof: 6f95df9' — that commit does not touch resolve/corridor.py (git show 6f95df9 -- resolve/corridor.py is empty). :604 `nm = (par or pen or "")` lets a row whose name_en holds Hebrew script (PLAN R1: 'מחסום דיר …
```
- **Verifier's check:** The doc-drift is confirmed. `git show 6f95df9 --stat` does not touch resolve/corridor.py. The Arabic-name preference (corridor.py:608-618) arrived later, in 211bbd4, whose commit message admits 'the registry has no settlement flag'. Grep finds no settlement label emitted in resolve/ or serve/; the only hits are the comment at :612-614. :604 `nm = (par or pen)` does let a Latin or Hebrew-only name into `passes` when a bucket has no Arabic-named candidate. The noise list catches only a few Hebrew words (junction, fuel brands). Two data-dependent claims cannot be confirmed without the DB: which s …
- **Already in the release plan:** PLAN §7 P0-A.4 and P0-B.3 ('settlements labelled'); §11 2026-09-24 17:05 'P0-A.2/A.4 · done · proof: 6f95df9' — contradicted by the code
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **ROUTE-V01 · F380 · medium** — G2's stated route rule (open only when corridor coverage ≥ 0.6) is neither implemented nor tested; the code and test_corridor enforce a 10-km longest-gap rule instead — `resolve/corridor.py:96`
  - scenario: A 19 km route with tracked checkpoints at km 9 and km 18 (longest gap 9 km, coverage_fraction 0.53) reads `likely_open`; by the gate as written it must be `unverified`. Nothing red tells anyone the gate and the code disagree.
  - suggested fix: Either add the fraction rule to `_doubts` (`coverage_fraction < 0.6` → blind-stretch doubt) and a test in test_corridor.py for the 19 km case, or rewrite G2 to state the longest-gap rule and the congestion exception that the code actually implements; then add a test that reads the G2 thresholds from one constant set shared by the gate text.
- **ROUTE-V02 · F317 · medium** — road_closure readings, incidents and v1's restrictions are still invisible to the verdict (P0-B.4 not built; G2 names them) — `resolve/corridor.py:113`
  - scenario: A village on the route is under a reported siege (incident type closure/siege, place_precision='named', 2 h old) or a road_closure reading names the road itself; no checkpoint changes; the route reads likely_open. The router also draws through gated settler roads because restrictions.geojson is unused.
  - suggested fix: Add a CAUTIONS query: state_serving road_closure rows and `event` rows (closure/siege/raid, place_precision='named', ≤ 3 h) within 2 km of the line, attached as `cautions` and spoken; pass restriction polygons as Valhalla `exclude_polygons`/avoid_locations. Needs the DB to validate.
- **ROUTE-V03 · F292 · medium** — Route answers recompute the static half every time: the Valhalla trip, the polyline buffering and the town list are re-derived on every can_i_travel, with a 30-second router timeout on a pool thread — `resolve/corridor.py:322`
  - scenario: `can_i_travel(رام الله, نابلس)` costs one router round trip plus 12 spatial queries over multi-thousand-vertex geographies plus 5 connections, although only the `state_serving` joins can change between calls; when Valhalla hangs (as it did for two days pointing at honcho, HANDOFF §3) each caller pins a threadpool thread for 30 s, and 40 such callers (within the limiter) exhaust the pool for every …
  - suggested fix: Cache `(origin, dest, alternates) → (trips, wkt, passes, on-route checkpoint ids/along/off_route_m)` in-process for hours keyed on a tile-version stamp; per call run only PRESENCE/state joins by place_id and the near-miss state filter; `ST_Simplify` the line to ~20 m before buffering; lower the router timeout to ~8 s; pass one connection from `route_between` through `resolve_place(conn=)` so a rou …
- **ROUTE-V04 · F319 · medium** — Congestion in the exit window does not withhold `open`, contradicting the G2 gate as written ('no closure/congestion within 3 km of the first/last 10 km') — `resolve/corridor.py:450`
  - scenario: A partner replaying G2 from the plan marks the gate failed on the first congested exit; or, reading the ledger, believes congestion at the exit is covered when it is not. Either the plan's gate or the code's rule is wrong, and the ledger claims the gate.
  - suggested fix: Decide and reconcile: either amend G2 in PLAN §6 to 'closure' with the reasoning from :438-440, or add exit congestion as a soft doubt (kind 'exit_congestion') that does not change the word but is spoken. Record the decision in DECISIONS.md.
- **ROUTE-V05 · F321 · medium** — On-route merge keeps the FIRST row on equal severity (ordered by direction name), so the blocked sentence can report a stale solo reading over a fresh corroborated one — the defect the near-miss path fixed at :478-503 is still present here — `resolve/corridor.py:525`
  - scenario: Beit El closed in both directions: the inbound row is a 5-hour-old single-channel report, the outbound row a 5-minute corroborated one. The route says 'مسكّر عند بيت ايل' with age 300 min and 1 source; a reader applying the tool's own 'read it with its age' rule discounts a closure the system actually knows well. Conversely oldest_known_minutes overstates staleness for open routes.
  - suggested fix: Merge on-route rows with the same `_rank` used for near misses: replace the `>` test with `if _rank(cand) > _rank(current)` where rank = (severity, independent_sources or 0, −age); keep `directions[direction] = v` as is. Add a FakeConn test asserting the corroborated fresh reading is reported.
- **ROUTE-V06 · F328 · medium** — The Arabic renderer is untested; the only renderer test is English, and the live test's 'تنبيه' assertion can only be met by a non-exit closure — `tests/test_corridor.py:251`
  - scenario: The critical omission above passed '56 tests green' (§11 16:20) and the 928-test full suite because nothing exercises the Arabic sentence with a constructed payload; the one live assertion that would catch it depends on today's closures.
  - suggested fix: Add tests that monkeypatch `serve.mcp_server.api` (as in the probe) for each verdict × exit closure and assert the name in `answer` and `answer_en`; add a 12 km/9 km-gap _score test; check in the four audit payloads as fixtures (P0-B.5); relax :108 to accept either 'تنبيه' or 'السبب' + the name.
- **ROUTE-V07 · F390 · medium** — test_route_omissions skips 8 of its 9 tests on any exception, and test_api skips the Valhalla identity check when unreachable — the route-truth tests vanish exactly when routing is broken — `tests/test_route_omissions.py:38`
  - scenario: Valhalla's container is down (or `VALHALLA_URL` points at nothing) on main-server; the suite reports N passed, 10 skipped, and the ledger records a green run; `can_i_travel` meanwhile answers every journey with the generic system error.
  - suggested fix: Make the skip conditional on the environment: if `PALESTINE_API`/`VALHALLA_URL` is set or a `PALESTINE_REQUIRE_ROUTING=1` marker is present (true on main-server), turn both skips into `pytest.fail(...)`; keep the skip only for a checkout with no routing at all. Print skips as a separate count in HANDOFF §3's expected line.
- **ROUTE-V08 · F526 · low** — Positions along the route are computed in degree space (planar 4326), so km, the blind stretch and the ENDS_KM window are distorted on E–W legs — `resolve/corridor.py:117`
  - scenario: Nablus→Tulkarm→Jenin style routes: a closure genuinely 9 km from the origin can project to 'along' ≥ 10 km and fall outside the ends window; `longest_gap_from_km` is reported a few km off.
  - suggested fix: Locate in a metric CRS: `ST_LineLocatePoint(ST_Transform(line.m, 32636), ST_Transform(p.centroid::geometry, 32636))` (UTM 36N) in the three queries; validate on main-server against ops/route_coverage_measure.py, which already does the metric maths.
- **ROUTE-V09 · F527 · low** — Junction checkpoints just outside the tube never count toward coverage even when freshly reported open, so a watched route can read `unverified` — `resolve/corridor.py:153`
  - scenario: Ofra, Beit El DCO and Ein Siniya all reported open 10 minutes ago: the primary Ramallah→Nablus route still shows a 27 km blind stretch and `unverified`, while a closure at the same places IS seen (near-miss). Safe in direction, but it makes the verdict less useful than the data and hides that the first half is in fact watched.
  - suggested fix: A second 'junction' band (≤ 600 m, measured) whose checkpoints contribute marks to coverage and are listed as `watched_nearby` with age, without entering the scored set; keep 300 m for scoring.
- **ROUTE-V10 · F528 · low** — PASSES_SQL admits every non-checkpoint kind; stations, roads and governorate centroids are filtered only by a name-noise substring list — `resolve/corridor.py:216`
  - scenario: The spoken 'يمر عبر' list names a forecourt or the Ramallah governorate centroid as a waypoint; a new station brand re-creates the 'wall of petrol stations' the comment describes.
  - suggested fix: Filter by kind (`p.kind IN ('locality', …)` — whichever kinds denote towns/camps) and keep the noise list only as a backstop; validate the kind set on main-server.
- **ROUTE-V11 · F529 · low** — Verdict vocabulary drift: the code and both transports emit `likely_open` while the plan fixes `open` and marks the vocabulary task done — `resolve/corridor.py:250`
  - scenario: A partner or an agent following the plan tests for `verdict == 'open'` and never matches; the 'open' gate G2 is described in a word the API does not emit.
  - suggested fix: Pick one word and say so in PLAN §7/§6 and PARTNER-API.md; if changing to `open`, keep `likely_open` accepted in the renderers' `say` maps for one release.
- **ROUTE-V12 · F530 · low** — `_score` treats any flow value it does not recognise as confirmed open — `resolve/corridor.py:389`
  - scenario: A future crowd/palhub value ('partial', 'checking') or a `_score` caller that bypasses `_corridor_for` (tests do) reads as 'confirmed open'.
  - suggested fix: Define OPEN = ('open',) and compute `known = [c for c in cps if c.flow in OPEN + SLOWING + (BLOCKING,)]`, treating anything else as unknown and counting it in `unreported`; assert the vocabulary in a test.
- **ROUTE-V13 · F531 · low** — `verdict_covers` uses an 0.8 fraction while the verdict uses a 10 km gap: a route can be `unverified` for a blind stretch and say 'the whole route' — `resolve/corridor.py:582`
  - scenario: A partner UI shows 'verdict covers: the whole route' beside 'Cannot confirm this route is open — because most of the route has no tracked checkpoint'.
  - suggested fix: Derive verdict_covers from the same doubt: 'part of the route' whenever a blind_stretch doubt exists or coverage_fraction < 0.8.
- **ROUTE-V14 · F580 · low** — P0-B.5's four audit replay fixtures (24 Sep 09:00/15:27/16:24/16:47) do not exist; test_corridor holds two synthetic approximations — `tests/test_corridor.py:107`
  - scenario: A future change to how `near_misses` are assembled (e.g. the `along` computation at corridor.py:139-154) reintroduces the 16:47 reading; `_score` unit tests still pass because their inputs are fabricated after the bug was understood.
  - suggested fix: Record the four `Corridor` inputs (cps, coverage, near_misses, distance) as JSON fixtures under tests/fixtures/corridor/ and parametrize a test that each replays to `unverified` and names the exit closure; ledger P0-B.5 stays open until then.
