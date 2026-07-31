# Palestine v2 — Implementation Plan

**Companion to:** `ARCHITECTURE.md` (same directory). Read `ARCHITECTURE.md` §8
(handoff notes) **before touching anything**. This file is the work breakdown;
the architecture doc is the *why*. When they seem to conflict, the architecture
doc wins — and if the conflict is real, stop and ask Zaid.

**How to use this file:** work one phase per session/model. Tick checkboxes as
tasks complete. Tasks marked **[ZAID]** block on his explicit approval — do not
proceed past them on your own judgment. Tags like **[TRAP-1]** reference
`ARCHITECTURE.md` §8.2.

---

## Session kickoff prompt (paste this when starting an implementation session)

> Read `~/palestine-v2/docs/ARCHITECTURE.md` fully (especially §8), then
> `~/palestine-v2/docs/IMPLEMENTATION_PLAN.md`. Implement **Phase N** only.
> Rules: (1) `/opt/stacks/palestine` and `~/lifeos` are LIVE production — never
> modify, restart, or stop anything there except tasks explicitly marked as v1
> honesty fixes, and each of those needs my approval before deploy. (2) All v2
> work stays under `~/palestine-v2`. (3) Tasks marked [ZAID] block on my
> approval. (4) Phase gates are renegotiation checkpoints — if a gate looks
> unreachable, stop and tell me; don't lower it and don't grind. (5) Tick
> checkboxes in IMPLEMENTATION_PLAN.md as you finish tasks, and log every
> non-obvious decision in docs/DECISIONS.md with one line of rationale.

**Model guidance per phase** — P0, P1, P2, P4: Sonnet 5 is sufficient (well-
specified, mechanical). P3: use Opus (most judgment: calibration, weak-label
hygiene, matching thresholds). P5: Sonnet, with Opus reviewing the dual-run
comparison methodology before cutover is proposed.

---

## Fixed decisions (do not re-decide these)

| Decision | Value |
|:--|:--|
| v2 root | `~/palestine-v2` |
| Language | Python 3.11+ throughout v2 (matches alerts service, ML tooling). Node fetchers are *ported*, not reused. |
| Database | One container: `timescale/timescaledb-ha:pg16` (bundles TimescaleDB + PostGIS) |
| DB port | `127.0.0.1:5433` (5432 is honcho's — verified free 2026-07-30) |
| v2 API port | `7870` (verified free 2026-07-30) |
| Migrations | Plain SQL files in `db/migrations/NNN_name.sql` + a small psql runner script. No new tooling deps. |
| LLM backend | Kilo Code subscription, OpenAI-compatible endpoint (same key as v1's `MINIMAX_API_KEY` — verified identical). Model name is config, never hardcoded. |
| Local LLM fallback | CPU-only (GPU has ~4.2 GB free; T2 encoder gets the GPU) [TRAP-2] |
| Valhalla | Reuse the running `wb-valhalla` container read-only over HTTP. Never rebuild its tiles from v2. |
| Repo layout | `docs/ db/ docker/ ingest/ resolve/ cascade/ serve/ learn/ ops/ data/{bronze,pg}` |
| Secrets | `~/palestine-v2/.env`, chmod 600, never committed, never printed in logs |

---

## Phase 0 — Foundation & honesty (~1 week) — model: Sonnet

### 0A. Homelab reclamation audit
- [x] **P0.1** Snapshot resource usage: `docker stats` sampled over 24h (cron a
      logger to `ops/audit/stats.ndjson`), plus host `free`, `swapon`, and
      per-container RSS. Identify the top RAM/swap consumers.
- [x] **P0.2** Identify the resident GPU python process (was pid 2854, 1.8 GB
      VRAM at audit time — `nvidia-smi`, `/proc/<pid>/cmdline`, container
      mapping). Name it in the audit; do not touch it.
- [x] **P0.3** Write `ops/audit/homelab-audit.md`: kill / keep / shrink table
      with measured RAM per container and total reclaimable estimate. Include
      candidates: Steam/Zomboid/pzserver (idle game servers), frigate (if Zaid
      agrees), hermes stack, wire-pod. Voice-*, honcho, vector-*, lifeos are
      presumed keep unless Zaid says otherwise.
- [x] **P0.4 [ZAID]** Present the audit. Zaid picks what gets stopped/shrunk.
      Apply only what he approves. Record final reclaimed RAM number.

### 0B. Database stack
- [x] **P0.5** `docker/compose.yml`: timescaledb-ha:pg16, port 127.0.0.1:5433,
      volume `~/palestine-v2/data/pg`, container name `palestine-v2-db`,
      restart unless-stopped, healthcheck. Memory limit set from P0.4's budget
      (default if audit not yet applied: 1.5 GB limit).
- [x] **P0.6** Tuning in `docker/postgresql.conf`: `shared_buffers=512MB`,
      `effective_cache_size=1536MB`, `work_mem=16MB`,
      `maintenance_work_mem=128MB`, `max_connections=20`,
      `timescaledb.telemetry_level=off`. Adjust upward only if P0.4 reclaimed
      real headroom.
- [x] **P0.7** Migration runner: `db/migrate.sh` (applies `db/migrations/*.sql`
      in order, records applied versions in a `schema_migrations` table,
      idempotent, refuses to run against any DB that isn't `palestine_v2`).
- [x] **P0.8** Write **complete** DDL (no `(...)` placeholders) [TRAP-3], in FK
      order `source` → `place`/`place_alias` → `dataset` → `event` → `claim` →
      `state_observation` → `observation`:
      - `001_extensions.sql` — postgis, timescaledb
      - `002_enums.sql` — place_kind, place_precision, time_precision, event_status
      - `003_reference.sql` — source, place, place_alias, dataset (+ GIST/GIN indexes)
      - `004_event.sql` — event with sys_period TSTZRANGE + GIST index
      - `005_claim.sql` — hypertable on ingested_at; PK includes partition column
      - `006_state.sql` — state_observation hypertable; `state_current` as a
        regular table maintained by trigger/upsert on write (decay is applied at
        read time by the API, not stored)
      - `007_observation.sql` — hypertable on occurred_at
      - Verify: fresh `migrate.sh` run from zero succeeds; `\d+` output matches
        ARCHITECTURE §3.3 semantics; a rollback note per file.

### 0C. Ingestion skeleton
- [x] **P0.9** Bronze store: `ingest/bronze.py` — content-addressed writes to
      `data/bronze/<source_key>/<sha256[:2]>/<sha256>.<ext>`, gzip for text,
      returns `raw_ref`. Never overwrites; duplicate content = same ref.
- [x] **P0.10** Fetcher framework: `ingest/framework.py` — `BaseFetcher` with
      conditional GET/ETag, exponential backoff, per-source rate limit, raw
      archival to bronze, schema-drift detection (hash of sorted field names),
      and a `FetchResult` where `ok=True` **requires** record count within the
      registry's `expect` range. Empty without `allow_empty: true` = failure.
- [x] **P0.11** `ingest/sources/registry.yaml` — schema per ARCHITECTURE §3.6.
      Seed with entries for every source that will exist by Phase 4 (status:
      `planned` / `active`), each with license + attribution filled in.
- [x] **P0.12** `ops/pipeline_report.py` — writes a run report where silent
      nulls are structurally impossible (every task ends `ok(count)` /
      `failed(reason)` / `skipped(reason)`).

### 0D. Gazetteer v1
- [x] **P0.13** Arabic normalizer: port from
      `/opt/stacks/palestine/services/westbank-alerts/app/checkpoint_matcher.py`
      (read it; do not import across repos). Unit tests: hamza/alef/teh-marbuta
      folding, diacritics, prefixes (ال، بـ، لـ), digit forms.
- [x] **P0.14** Load admin skeleton: OCHA admin1/admin2 geojson (copies exist at
      `/opt/stacks/palestine/services/westbank-alerts/data/admin/` — read-only)
      + `oslo.geojson` → `place` rows with pcodes and oslo_area.
- [x] **P0.15** Load localities: PCBS locality list + OSM places for WB+Gaza
      (Overpass query, archived to bronze). Dedupe against admin rows.
- [x] **P0.16** Load the 403 checkpoints from
      `/opt/stacks/palestine/services/westbank-alerts/data/checkpoints.db`
      (read-only) as `place.kind='checkpoint'`, keeping `canonical_key` in
      `source_refs` for later join-back.
- [x] **P0.17** Seed `place_alias` from: known_locations.json,
      checkpoint_directory.json aliases, OSM name:ar/alt names.
- [x] **P0.18** `resolve/geo.py` — `resolve_place(text, context) → (place_id,
      precision, confidence)`: exact alias → fuzzy (normalized trigram) →
      contextual tiebreak (prefer places near the claim's channel's usual
      area). Every successful resolve increments `place_alias.hits`; every new
      spelling that resolves gets inserted with `origin='observed'`.
- [x] **P0.19** Held-out test: sample 200 distinct `geo_source_phrase` values
      from v1 `alerts.db` (read-only), hand-check resolution of a random 50 —
      this is a one-off gate check, not an ongoing labeling pipeline.
      **Gate metric: ≥80% correct.**

### 0E. v1 honesty fixes (in-place, each individually approved) **[ZAID]**
Work in `/opt/stacks/palestine` on a branch; deploy = Zaid runs/approves the
restart. One PR-sized change each:
- [x] **P0.20** Freshness: stop stamping ingest date as event date
      (culture/education/westbank/land) — where no event date exists, emit
      `date: null` + `date_precision: 'unknown'` and let the gate treat the
      *fetch* success separately.
- [x] **P0.21** Freshness: fix year-bucket dates (`2026-12-31` → year precision;
      no more negative `freshness_days_since_latest`).
- [x] **P0.22** Freshness: include `aid_access`, `food`, `health` in
      `quality.json` (stream partitions one at a time — container has a memory
      cap).
- [x] **P0.23** ETL: the 8 silent-null tasks get expected-count contracts and
      fail loudly.
- [x] **P0.24** Billing: schedule `rollup-usage.js` (usage_daily currently 0
      rows against 120k events).
- [x] **P0.25** Alerts: normalize `channel_reliability` keys to lowercase;
      dedupe the case-variant rows.
- [x] **P0.26** Safety: add `staleness_band` + `observed_at` to every checkpoint
      status response; band `stale`/`unknown` when older than
      `CHECKPOINT_STALE_HOURS` ×4. Frontends may still show last-known, but the
      API stops asserting month-old `open` as current.

### Gate 0 (all must pass)
- [x] DB stack healthy inside the approved RAM budget (soak ongoing) (no OOM, no swap growth attributable to it).
- [x] Fresh-from-zero migration run succeeds.
- [x] Gazetteer ≥80% on the held-out sample (P0.19). **84.7%, 0 foreign leaks.**
- [x] v1 `/quality` returns no negative freshness and covers all 22 categories. **Deployed; takes effect at the 02:33 refresh.**
- [x] All 37 v1 ETL tasks report a real count or a loud failure. **Deployed 2026-07-31.**

---

## Phase 1 — Fuel vertical end-to-end (~2 weeks) — model: Sonnet

### 1A. Ingestion path
- [x] **P1.1 [ZAID] [TRAP-1]** Decide Telegram strategy before any ingestion
      code: **(a)** second Telegram session/account for v2 (cleaner, needs a
      number), or **(b)** tee — a ~30-line addition to v1's monitor that mirrors
      every raw message as NDJSON to a spool directory v2 tails (touches prod
      once, keeps one session). Present both; Zaid picks. If (b): the tee is a
      v1 honesty-fix-class change (approval + rollback plan).
- [x] **P1.2** v2 ingest daemon consuming the chosen feed → bronze → `claim`
      rows for *all* messages (unclassified claims are still stored with
      `claim_type='unclassified'` — they are the future training corpus).

### 1B. Station registry
- [x] **P1.3** Overpass: `amenity=fuel` for West Bank (+ Gaza) →
      `place.kind='station'` with brand/operator/name:ar tags; bronze-archive
      the raw response. Expect order-of-hundreds; sanity-check counts per
      governorate against reality (Nablus, Ramallah, Hebron should dominate).
- [x] **P1.4** Alias seeding for stations (brand names, colloquial forms,
      "محطة X" patterns) + `resolve_place` station-type bias when fuel vocab is
      present in the claim text.

### 1C. Fuel signal
- [x] **P1.5** Corpus mining: query v1 `corpus.db` FTS (read-only) for fuel
      vocab (بنزين، سولار، ديزل، محطة، غاز، طوابير…) — measure base rate per
      channel. Deliverable: `ops/fuel-signal-survey.md` with volume/day per
      channel. **If total volume < ~20 usable messages/day, flag to Zaid
      immediately** — the honest fallback posture is "last known + age" and the
      crowd socket moves up the roadmap (ARCHITECTURE §6).
- [x] **P1.6 [ZAID]** Propose new fuel/commerce channels found in P1.5 +
      candidate discovery. Zaid approves which the account joins.
- [x] **P1.7** T1 fuel rules in `cascade/t1_fuel.py`: claim types
      `fuel_available|fuel_empty|fuel_queue|fuel_price|fuel_delivery|cooking_gas`,
      quantity/price extraction, station/locality resolution. Unit tests from
      real corpus examples (≥50 cases including negations and forwards).
- [x] **P1.8** State wiring: fuel claims → `state_observation`
      (`fuel_gasoline|fuel_diesel|cooking_gas`) → `state_current` upsert.
      Half-lives from config (`fuel: 3h` default), decay computed at read.

### 1D. Serving + measurement
- [x] **P1.9** `serve/` FastAPI app on :7870: `GET /v2/fuel/nearby?lat&lon&fuel=`
      returning stations ranked by `confidence × 1/drive_time`, drive time via
      the running Valhalla (read-only HTTP); every row carries `value,
      confidence, observed_at, age_minutes, staleness_band, sources[]`;
      below-floor → `value:"unknown"` with last-known shown separately.
- [x] **P1.10** Mini corroboration scorer (Loop A preview, fuel only): agreement
      rate of fuel states that later claims confirm vs contradict within the
      half-life window. Daily job writing `ops/fuel-accuracy.ndjson`.
- [x] **P1.11** One-off gate check: 7-day window, ~50 fuel events spot-verified
      (corroboration + Zaid's optional 30-minute local-knowledge review).

### Gate 1
- [x] "Diesel near me now" returns a confidence-ranked, drive-time-sorted list.
- [x] **Zero** stations served `available` with age > 2× half-life. **tests/test_gate1_fuel.sql, 6/6 pass.**
- [ ] Measured precision proxy ≥0.80 on the 7-day window.
- [x] Fuel signal volume documented — superseded by palhubappfuel (structured feed, 200 stations, ~30min sweeps).

---

## Phase 2 — Databank migration (~2–3 weeks) — model: Sonnet

- [ ] **P2.1** Port `licenses.json` → `source`/`dataset` rows.
      **[ZAID]** for the 6 `verify-required` licenses: he reads/contacts;
      each dataset gets a real SPDX + `commercial_use` boolean or stays
      quarantined (served on research tier only).
- [ ] **P2.2 [TRAP-4]** Write 22 mapping specs, one per v1 category:
      `db/mappings/<category>.yaml` — indicator names, unit, `occurred_at`
      derivation + precision, place resolution strategy, attrs passthrough.
      These are reviewable documents *before* code runs.
- [ ] **P2.3** Migration ETL: treat v1 `all-data.json`/partitions as bronze
      input; per-category transform → `observation` (or `event` for
      event-shaped categories: conflict, demolitions); every record through
      geo/time resolvers; per-category run reports with resolved-percentage.
- [ ] **P2.4** History: replay every retained snapshot day chronologically to
      reconstruct `sys_period` ranges. The snapshot tree is then **KEPT, not
      deleted** — no-data-loss (ARCHITECTURE §3.10) applies to it too. It may be
      compressed in place (JSON gzips ~8-10x) once the replay is verified
      byte-for-byte, but the days themselves stay. v1's retention already
      destroyed ~15 days; v2 destroys none.
- [ ] **P2.5** Category views: `v_water`, `v_health`, … reproducing v1 response
      shapes from `observation` (used by the dual-run comparison and any legacy
      consumer).
- [ ] **P2.6** License enforcement middleware: tier → allowed `commercial_use`
      values, enforced in SQL (`WHERE`), not in app filtering. Test:
      a commercial-tier request can never return an ACLED/WHO-NC row, verified
      by test fixtures.
- [ ] **P2.7** `as_of` harness: for 5 sampled dates × 6 categories, v2
      `sys_period @> as_of` results must match the archived v1 snapshot files.

### Gate 2
- [ ] Admin-key coverage ≥60% overall (from 7.1%); per-category table published.
- [ ] `as_of` harness green.
- [ ] Postgres size grows only with actual change (no full-copy amplification);
      snapshot tree intact — zero days deleted.
- [ ] One cross-tier query (e.g. fuel/alert events × water observations joined
      on `place_id` + month, Hebron) returns demonstrably correct results.

---

## Phase 3 — Cascade & learning loops (~3 weeks) — model: **Opus**

Order matters here: **P3.1 before anything that learns** [TRAP-6].

- [ ] **P3.1** Copy-collapse: near-duplicate detection over normalized Arabic
      text (simhash/MinHash + short-lag window). Channels that repeatedly
      re-post another channel's content collapse into one *independence unit*
      for counting. Validate on known cross-posting pairs from the corpus.
- [ ] **P3.2** Event resolver: cluster claims → events on (type, place
      proximity, time window, text similarity); emit `independent_sources`
      (post-collapse), `contradicted_by`. Seed thresholds from v1's incident
      grouper (2h window) and tune on the 2,176 known same-day/area/type groups.
- [ ] **P3.3** Loop A: weak labels (corroborated≥N vs uncorroborated-after-T);
      nightly Beta-Bernoulli reliability posterior per source×claim_type with
      recency decay → `source.reliability`, and PMI keyword-weight suggestions
      → review file (not auto-applied to T1).
- [ ] **P3.4** T2: fine-tune an AraBERT-class encoder (CAMeL/AraBERT family) on
      Loop A labels for claim_type + a real/noise head. Constraints: fits in
      ~4.2 GB VRAM [TRAP-2]; calibrated (temperature scaling on a held-out
      split); exported to ONNX; served in-process. Target: ≥0.85 F1 vs weak
      labels *before* Loop B correction is available.
- [ ] **P3.5** T3 adjudicator: OpenAI-compatible client (Kilo endpoint from
      config), structured-output prompt for claim extraction/validation, daily
      budget, circuit breaker, **fail-closed to T2** on any error. Route: only
      Tier-1 alert types below confidence threshold + novel-pattern samples.
- [ ] **P3.6** Loop B: retrospective matchers — OCHA oPt sitrep parser
      (Wed/Thu), ACLED weekly (loop-only, non-commercial — the license
      middleware must make it unservable), B'Tselem, ReliefWeb. Match events on
      place-radius + time-window + type; emit TP/probable-FP/FN with authority
      coverage weights.
- [ ] **P3.7** `GET /v2/quality/accuracy` — continuous precision/recall bands
      from Loop B, replacing the hand-made `accuracy_audit.json`. This endpoint
      is a headline feature; make it good.
- [ ] **P3.8** Cascade evaluation: full cascade vs T1-only on a held-out window,
      scored by Loop B. Publish the comparison in `ops/`.

### Gate 3
- [ ] Reliability view live and sane (spot-check: channels known to copy others
      don't get inflated scores).
- [ ] Cascade precision ≥0.90 AND recall ≥0.90 on the held-out window —
      **if unreachable, stop and renegotiate with Zaid; do not grind or lower.**

---

## Phase 4 — Source expansion (~2 weeks) — model: Sonnet

Each new source: registry entry (license! `expect`!) → fetcher → resolver →
claims/observations/states → measured contribution.

- [ ] **P4.1** GDELT GEO/DOC poller (15-min, Palestine bbox + Arabic keywords) →
      corroboration claims. Expect noise; it feeds Loop A/B, not the public feed
      directly, until precision is measured.
- [ ] **P4.2** NASA FIRMS (free MAP_KEY) VIIRS 375m thermal → `strike_thermal`
      corroboration signals for Gaza events.
- [ ] **P4.3** NASA Black Marble VNP46 daily → power state per admin2 (Gaza
      focus; 500m resolution honesty note in metadata).
- [ ] **P4.4** IODA + Cloudflare Radar outage APIs → `internet` state per
      region/ASN; corroborate with the existing OONI databank category.
- [ ] **P4.5** HDX HAPI + ReliefWeb API → observations + Loop B corpus.
- [x] **P4.6** Telegram source-discovery loop productionized: forwarded-from
      graph + candidate scoring by corroboration contribution → weekly proposal
      list **[ZAID]** → join approved channels.
- [ ] **P4.7** Signal classes: movement (queue-time estimation from update
      cadence, closure-duration prediction baseline), displacement/demolition
      (notice vs execution as distinct claim types), utilities rollup endpoint.

### Gate 4
- [ ] Per-source recall/precision contribution table published (which source
      caught what that others missed).
- [ ] Every active source passes its `expect` contract and has a real license row.

---

## Phase 5 — Serving surface & cutover (~2 weeks) — model: Sonnet (+ Opus review of P5.3)

- [ ] **P5.1** Public API v2 on :7870: events, states (fuel/checkpoints/
      utilities), observations with `as_of`, full-text search, quality/accuracy,
      licenses, per-key tiers. OpenAPI docs generated.
- [ ] **P5.2** Webhooks (geo/type/confidence filters, retries, HMAC signatures)
      + SSE/WS fanout, ported from v1 design but on the event layer (subscribers
      get corrections/retractions as first-class events).
- [ ] **P5.3** Dual-run comparison harness: v1 vs v2 on identical windows —
      precision/recall (Loop-B scored), latency, geo coverage, staleness
      honesty. Daily report to `ops/dualrun/`. **Opus reviews the methodology
      before results count.**
- [ ] **P5.4** Cutover plan doc: cloudflared route switch steps, rollback steps,
      data-freeze notes. **[ZAID] executes cutover manually.**
- [ ] **P5.5** Public docs: API reference, data-ethics & licensing page,
      published accuracy page. Written to work for either future: commercial
      product or open-source release.

### Gate 5
- [ ] v2 ≥ v1 on precision, recall, latency, and staleness honesty for **7
      consecutive dual-run days**.
- [ ] Zaid approves and executes cutover. v1 stays runnable for 30 days after.

---

## Standing rules (every phase)

1. Production is sacred: `/opt/stacks/palestine`, `~/lifeos`, and every running
   container not explicitly approved for change in P0.4.
2. Every fetch archives raw to bronze before parsing. No exceptions.
2b. **NO DATA LOSS.** Never add a retention policy, TTL, prune job, or DELETE on
   any table holding observations (`claim`, `observation`, `state_observation`,
   `event`/`event_history`). Corrections supersede; they never overwrite.
   Timescale COMPRESSION is fine — it keeps rows queryable. Timescale RETENTION
   is forbidden — it drops chunks. If a task seems to require deleting
   observations, stop and ask. See ARCHITECTURE §3.10.
3. Every non-obvious decision → one line in `docs/DECISIONS.md`.
4. Secrets never printed, never committed; `.env` chmod 600.
5. ACLED / OpenSky / WHO-NC data must be structurally unservable on commercial
   tiers (SQL-level enforcement), from the day they are first ingested.
6. If a gate is unreachable or a trap fires: stop, write up what you found,
   ask Zaid. Renegotiation is success behavior, not failure.
