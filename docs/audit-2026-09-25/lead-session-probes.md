# First-hand findings by the orchestrating session (read directly, probes run here)

These were found by the lead session reading resolve/belief.py, db/migrations/006,010,014,015,016,026,027,036,069,
resolve/corridor.py, cascade/checkpoint_text.py, ingest/sources/checkpoints.py, serve/quality.py and serve/app.py's
route handler, and by running cascade.checkpoint_text.read() on adversarial sentences. Verified in code unless marked.

## Checkpoint text parser (cascade/checkpoint_text.py) — probe output, reproducible

| input | parsed | truth | class |
|---|---|---|---|
| حوارة ومش سالك | both:flow=open | closed | INVERSION — waw-fused negator "ومش" is not in NEGATORS (:154) and `_negated` (:461-488) compares whole tokens; `_lex` strips a leading و for lexicon words but `_negated` never does |
| اذا فتح حوارة بنمشي | both:flow=open | no fact (conditional) | reassurance manufactured from a hypothetical; no conditional/irrealis guard (اذا/إذا/لو/ان شاء الله/بكرا/رح) |
| لا يوجد جيش على حاجز حوارة | both:presence=idf | absence | MSA negation "لا يوجد"/"لا يوجد"/"لم"/"ليس" not a negator (:154, :476 handles only لا+في/فيه) — caution invented |
| لا يوجد ازمة على حوارة | both:flow=congested | open | same class, flow axis |
| ولا جيش على حوارة | both:presence=idf | absence | "ولا" only recognised before في/فيه |
| حوارة كان مغلق الصبح وهلا سالك | both:flow=closed | open (now) | tense: past-state word wins by severity collapse (:684-687); no كان/هلا/الان recency handling — conservative direction but wrong |
| حوارة سالك حسب آخر معلومات قبل ساعتين | both:flow=open @ message time | open @ −2h | relative time in text ignored; observed_at = message time |
| حوارة سالك، زعترة مغلق | closed for BOTH places if v1's raw_line is the whole message | per place | place binding is v1's (checkpoints.py:159-205 re-reads raw_line per v1 row); most-restrictive collapse then stamps every named checkpoint with the worst state. Needs v1's raw_line semantics to confirm (v1 code is not in this repo) |
| بيت فوريك مسكر للي طالع بس سالك للي نازل | both:flow=closed | out=closed,in=open | طالع/نازل (going up/down — the common colloquial direction words) not in DIRECTION_WORDS (:161-178) |

Correct behaviour confirmed on: مش سالك → closed, حومش سالك → open, مش مسكر → open, ولا في مستوطنين handled, questions, emoji-only lines, fuel lines.

## Belief and serving (resolve/belief.py + state_serving 026 + checkpoint_serving 027)

- Served value = the single freshest assertion per (place, kind, direction) (`latest`, belief.py:116-122). Corroboration counts units agreeing within 30 min BEFORE it; dissent discounts confidence by at most 25 % (:188). Consequence: three independent units saying `closed` at 14:00 are overridden by ONE curated unit saying `open` at 14:20, served at 0.85×0.8125 = 0.69, above every floor. "Latest wins" with a fixed, unmeasured 25 % ceiling on dissent — the reassuring flip is not gated for curated sources (P2.4 gates only the crowd).
- Persistence-informativeness (015/026): confidence = base × clamp((p(t)−0.5)/(p0−0.5)). With the measured curves (open p0 .96→.88; closed .92→.62): `open` never falls below 0.85×0.826 = 0.70 (only max_assert 6 h / the 8×half-life band retire it); `closed` falls to 0.85×0.286 = 0.24 < floor 0.25 and is retired by decay alone within a few persistence half-lives. The served model forgets a closure faster than an opening — the opposite of the P2.4 asymmetry. Needs the fitted half-lives from state_value_decay (DB) to quantify; the formula is in code.
- state_confidence (010) clamps a FUTURE observed_at to full base confidence, and the belief upsert guard `EXCLUDED.observed_at >= state_current.observed_at` (belief.py:212) means a future-stamped observation blocks every later correction until its time passes. Nothing validates observed_at ≤ now() on the write paths read here (checkpoints.py:167-171 takes v1's timestamp verbatim).
- checkpoint_serving (027) `flow` picks the freshest of {direction, both} by raw observed_at; per-direction cadence half-lives differ, so the freshest can already be `unknown` while the older direction-specific row is still live → serves `unknown` (fail-safe, but discards a valid reading).
- crossings (app.py `/v2/crossings`) joins checkpoint_flow with `cf.direction = 'both'` only — a crossing that is also a checkpoint with directional readings reads as no reading.

## Route verdict (resolve/corridor.py)

- G2 (PLAN §6) says `open` only when corridor coverage ≥ 0.6 AND no closure/congestion within 3 km of the first/last 10 km. Code: `coverage_fraction` (:562-574) is computed from the positions of ALL on-route checkpoints INCLUDING those whose flow is `unknown` — it measures registry density, not observation coverage. `_score` (:329-391) never compares any coverage fraction to 0.6; it only degrades on `longest_gap_km >= 10` or a closed near-miss at the ends. So a route with 1 of 8 checkpoints known-open and no 10 km gap returns `likely_open` ("1 of 8 checkpoints confirmed open; 7 have not been reported recently") — the exact "verdict is the same whether 2 or 8 are known" defect of PLAN §4 R2, and G2 is not met by the code. The verdict word is still `likely_open`, not the plan's `open`.
- `_closures_at_ends` (:434-459) deliberately ignores congestion; PLAN G2 names "closure/congestion". Documented divergence, but the gate text and the code disagree.
- Exceptions from Valhalla propagate to app.py:2049 → 503 (correct, no silent unknown).
- `routes()` ranking (:677): `unverified` (2) sorts below `slow` (1) — a congested-but-seen route outranks an unverified one; defensible, documented.

## v1 checkpoint reader (ingest/sources/checkpoints.py)

- Incremental cursor (:146-156): `WHERE timestamp > MAX(observed_at)` formatted to whole seconds. Any v1 row that arrives later with an older timestamp (delayed message, backfill, clock skew) is skipped forever; rows sharing the max second are re-read or skipped depending on v1's string format (needs v1 to confirm).
- `--full` DELETEs state_observation rows (:139-143) — reconstruction, but if v1's SQLite has since lost rows (its own retention) the v2 archive shrinks: the "no data loss" rule is only as strong as v1's retention.
- v1's own status is archived at a hard-coded 0.85 confidence (:181).

## Precision annotation (serve/quality.py)

- Reads ops/incident-precision.json; if the file's `classifier_version` ≠ serving CLASSIFIER_VERSION a note is added — correct. But `_load` is keyed only on mtime and never re-checks that the file is a *measured* round rather than a rescore projection (the projections are written to differently named files today; the guard is by filename convention only).

## Fresh rebuild of the schema (measured in this session on a local Postgres 16.15 + PostGIS 3.4.2 + TimescaleDB 2.30.1)

Applying db/migrations/001–078 in order to an empty database the way db/migrate.sh does (`psql -1`, ON_ERROR_STOP):
- 74 of 78 apply cleanly.
- 018_fix_governorate_names.sql:39 FAILS — inserts place_alias rows for hard-coded place_ids 4 and 5 that exist only in production (FK violation).
- 074_crossing_name_aliases.sql:19 FAILS — the same shape, place_id 1489.
- 062_place_closure.sql:120 FAILS under migrate.sh's own `-1` — "unsafe use of new value district_mandate of enum type place_kind" (ALTER TYPE … ADD VALUE used in the same transaction). It applies when run without `-1`, so production must have had it applied outside the runner.
- 077 fails only because 062 did.
So the migration chain cannot rebuild the database from scratch — the disaster-recovery and fresh-clone path is pg_dump restore only. After applying 062 without the transaction and skipping the two data-only migrations, all 78 are recorded, 43 views exist, and the suite runs against it: 821 passed / 99 failed (the 99 need production data or a live API); test_crowd's 13 real-belief-SQL tests all pass.

## Test suite, honest numbers for this checkout
- Without any database: 701 passed, 163 failed, 58 errors.
- Against the local empty database: 821 passed, 99 failed.
- docs/HANDOFF §3 / README / plan quote 315, 436, 557, 840, 928 at various dates; none is reproducible off main-server.
