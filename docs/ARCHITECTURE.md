# Palestine Data Platform v2 — Architecture & Phased Plan

**Status:** Draft for approval · **Date:** 2026-07-30 · **Author:** analysis of `/opt/stacks/palestine` @ 2026-07-30

This document specifies the concrete system that replaces the proof of concept.
Every number in the PoC assessment was measured directly from the running system
and its databases on 2026-07-30, not taken from the existing README (which is
substantially out of date).

---

## 0. Verdict in one paragraph

**Tier 1 (live alerts) is a real product with a fake learning loop.** It ingests
~400 classified alerts/day from 20 Arabic sources, clusters them into incidents,
and measures its own accuracy honestly — which is rarer and more valuable than
the accuracy itself. But nothing in it learns: source reliability is a hand-typed
constant table, the retraction pipeline has never fired once in 13,270 alerts, and
the single strongest truth signal available (1,956 event-groups independently
corroborated by 2–11 sources) is computed and then discarded.

**Tier 2 (databank) is a real corpus with a fake integration layer.** 244,461
records exist and 22 fetchers run nightly, but only **7.1%** carry an admin key and
**4.1%** a gazetteer key. The "canonical schema v3" is a shape agreement, not an
integration — the two tiers physically cannot be joined on space or time. It is
served by `JSON.parse()` of monolithic files (118 MB martyrs, 42 MB water) at
0.4–3.0 s per request, and versioned by 30 daily full copies occupying 15 GB for
~450 MB of data.

**The fix for both is the same work:** one canonical store with real join keys, a
claim/event separation that makes corroboration usable, and two automatic feedback
loops that close what is currently open. The fuel/gas-station vertical is the right
Phase 1 because it exercises every one of those subsystems at once and is urgently
useful today.

---

## 1. PoC assessment — measured, not claimed

### 1.1 Tier 2: the unifier does not unify

Coverage of join keys across all 244,461 records, all 22 categories:

| Join key | Coverage | Consequence |
|:--|--:|:--|
| `date` | 75.2% | 24.8% cannot enter any time series |
| lat/lon | 18.2% | 81.8% cannot be mapped |
| `admin1`/`admin2`/`admin2_pcode` | **7.1%** | 92.9% cannot be aggregated by governorate |
| `gazetteer_key` | **4.1%** | 95.9% cannot be joined to the live tier |

Thirteen of 22 categories have **zero** geographic resolution — including the
largest: `aid_access` (50,059), `health` (40,559), `water` (25,049), `food`
(23,967), `funding` (9,983), `economic`, `pcbs`, `prisoners`, `culture`, `land`,
`connectivity`, `settlements`, `casualties`. `martyrs_snapshot_2023` — 60,200
records, **24.6% of the entire corpus** — has 0% dates.

This is the central finding. The commercial premise of owning both tiers is the
join between them; that join does not currently exist.

### 1.2 The freshness gate — your credibility feature — is defeated three ways

1. **Ingest date masquerading as event date.** `culture`, `education`, `westbank`,
   `land` all report `date_range.start == date_range.end == today`. Their records
   are stamped with the fetch date, so they report `freshness_days_since_latest: 0`
   forever and can never go stale.
2. **Negative freshness.** `casualties`, `demolitions`, `economic` carry
   `latest_record_at: 2026-12-31` → **`freshness_days_since_latest: -154`**. An
   end-of-year aggregation bucket is being read as a record date.
3. **Missing entirely.** `quality.json` has 19 entries; the manifest has 22.
   `aid_access`, `food`, and `health` — 114,585 records, **47% of the corpus** —
   have no freshness entry at all, so the gate never evaluates them.

### 1.3 Silent failure is indistinguishable from success

8 of 37 ETL tasks report `status: "ok"` with `records: null`
(`ucdp_conflict`, `villages_1948`, `hdx`, `who`, `gaza_health_impact`,
`goodshepherd`, `idmc_displacement`, `documents`). A no-op and a success are the
same signal. The `documents` category directory is empty.

### 1.4 Provenance and licensing are asserted, not enforced

8 categories carry `sources: []`. 6 carry `license: "verify-required"`
(`casualties`, `demolitions`, `economic`, `historical`, `prisoners`,
`settlements`) — under a README claiming CI-enforced license coverage. There is
no query-time enforcement, so a non-commercial source can leak into any response.
**This must be fixed for either exit path** — selling requires it legally, and
open-sourcing requires it ethically.

### 1.5 Storage is 30× amplified

15 GB total: 30 daily *full copies* of every category under
`public/data/unified/snapshots/`. No deltas, no diffing. Actual current data is
~450 MB. `as_of` queries work by reading a different full copy.

### 1.6 Tier 1: what genuinely works

| Asset | Evidence |
|:--|:--|
| Live ingestion | ~400 alerts/day sustained, 13,270 total since 2026-06-10 |
| Incident clustering | 13,270 alerts → 5,310 incidents, **100% of alerts clustered** |
| Checkpoint telemetry | 91,568 status updates across 403 checkpoints |
| News collection | 7,227 articles from 14 outlets at ~150/day |
| Corpus for training | 21,058 Telegram messages, FTS-indexed, 32 channels |
| **Honest self-measurement** | `accuracy_audit.json`: precision 0.654 → 0.827, recall 0.78 → 0.88 |

The accuracy audit is the most valuable artifact in the repository. Keep it, and
make it automatic.

### 1.7 Tier 1: what is theatre

| Claim | Reality |
|:--|:--|
| "source reliability weight" | `channel_reliability` is 30 hand-typed rows; `last_updated` = seed date on every row. Never recomputed from 13,270 observed outcomes. |
| "retracted or corrected post-publication" | `status = 'active'` on **13,270 / 13,270**. Has never fired. The feedback loop has no input. |
| "geographic webhook filters" | `webhooks` table: **0 rows**. Never had a subscriber. |
| "self-learning" | `learner.py` is deterministic co-occurrence counting over *checkpoint vocabulary only*. It cannot improve the classifier. |
| Commercial surface | 1 customer (`local-test@zaidlab.xyz`), 1 key, 120,110 usage events, `usage_daily` rollup = **0 rows**. Cannot bill. |
| Confidence scoring | Blends source reliability + severity + locality. **Never uses cross-source agreement** — 1,956 corroborated event-groups (2–11 independent sources each) vs 1,940 single-source are treated identically. |

### 1.8 The safety bug

`checkpoint_status`: 786 rows. Freshness distribution:

| Age | Rows | Share |
|:--|--:|--:|
| < 24 h | 168 | 21% |
| 1–7 d | 287 | 37% |
| 7–30 d | 69 | 9% |
| **30 d+** | **262** | **33%** |

…and 488 of those rows read `open`. The system serves month-old "open" as current
status. The July audit already caught 5 "dangerous false opens". **This is the one
failure mode that can get someone hurt**, and it is a direct consequence of
modelling status as a value rather than as a belief with a decay function.

### 1.9 Other measured defects

- Max geo precision is `town` (8,324) / `region` (3,784). No `exact` tier exists — this caps any routing or corridor product.
- Config drift: `.env` declares 5 security channels; the DB shows 20 distinct sources actually producing alerts.
- Two disconnected news stores: `news.db` has 7,227 articles at ~150/day; the databank `news` category has 174 records.
- `channel_reliability` keys are case-inconsistent (`QudsN`/`qudsn`, `Shihab`/`shehabagency`), so lookups silently miss.
- 2,176 same-day/area/type alert groups contain 9,242 redundant rows that clustering catches but the API still serves individually.

### 1.10 Hardware envelope (binding constraint)

| Resource | Available |
|:--|:--|
| CPU | i7-11800H, 8C/16T |
| RAM | **15 GB total, 5.5 GB available, 2.6 GB already swapped** |
| GPU | RTX 3060 Laptop, **6 GB VRAM** |
| Disk | 260 GB free of 466 GB |
| Containers | 26 running; `params-alerts-api` capped at 256 MiB |

RAM is the binding constraint. The design below is sized to fit it, and Phase 0
includes a reclamation audit.

---

## 2. Design decisions (confirmed)

| Decision | Choice |
|:--|:--|
| Buyers | All four: NGO ops, civilian safety, media/OSINT, B2B API |
| Storage | **Postgres + PostGIS + TimescaleDB** |
| Classifier | **Cascade**: rules → fine-tuned model → LLM adjudicator |
| Ground truth | **Automatic only**: cross-source corroboration + retrospective matching. No human labelling, no crowd (socket left unwired) |
| Budget | Free/open sources + existing homelab |
| LLM backend | Kilo Code subscription via OpenAI-compatible endpoint (key already in use by two prod services); local fallback on the 3060 |
| Phase 1 vertical | **Fuel / gas stations** |
| Work mode | Parallel build at `~/palestine-v2`, dual-run, cut over on measured accuracy |
| Backward compat | **None required** — the only API key is the developer's own |
| Commercial posture | Build full capability; decide sell vs. open-source later. License correctness built in regardless |

---

## 3. Target architecture

### 3.1 Seven principles

1. **Separate what was *said* from what we *believe*.** A source's assertion (a claim) is immutable. Our belief about the world (an event/state) is derived, revisable, and versioned.
2. **One gazetteer, used by everything.** Geographic resolution is a service, not a per-fetcher afterthought.
3. **Four timestamps, never one.** `occurred_at` + precision, `reported_at`, `ingested_at`, `valid_from`/`valid_to`.
4. **State decays.** Never serve a status without its age and a confidence that has decayed since the last observation.
5. **Silence is failure.** A fetcher returning zero records without an explicit `allow_empty` declaration is an error, not a success.
6. **Raw is immutable.** Every fetch archives its raw payload so transforms can be re-run without re-fetching.
7. **The loop must close automatically.** Every published belief must be scoreable against something without a human in the path.
8. **Nothing observed is ever deleted.** No retention policy, no pruning job, no
   TTL on anything that records an observation. Corrections supersede, they do
   not overwrite. See §3.10 — this is a hard constraint, not a default.

### 3.2 The core model — claim / event separation

This is the central architectural change and it solves five problems at once.

```
       ┌──────────┐  asserts   ┌─────────┐  supports/refutes  ┌────────┐
       │  SOURCE  │───────────▶│  CLAIM  │───────────────────▶│ EVENT  │
       │ channel, │            │immutable│    (n : 1)         │ belief │
       │ feed, API│            │ raw+    │                    │revisable│
       └──────────┘            │ parsed  │                    └────┬───┘
             │                 └─────────┘                         │
             │                       │ at                          │ at
             │                       ▼                             ▼
             │                  ┌─────────────────────────────────────┐
             └─ reliability ◀───│  PLACE (gazetteer)  ·  TIME (4 cols) │
                (measured)      └─────────────────────────────────────┘
```

Today one Telegram message = one alert = one row, conflating claim and belief.
That single conflation is why:

- corroboration is unusable (no object to attach 11 sources to),
- retraction never fires (retracting a claim would falsify the historical record),
- dedup is a fingerprint hack rather than a resolution step,
- channel reliability cannot be measured (no claim→outcome pairs),
- confidence ignores agreement.

With the separation, all five become straightforward:

- 11 channels reporting one raid → 11 claims → **1 event with 11 supporting claims**
- `confidence(event) = f(independent claim count, source reliabilities, temporal spread, contradictions, prior)`
- Retraction flips the *event's* belief state; claims stay immutable and auditable
- **Channel reliability is a nightly materialized view** over claim→event outcomes — this is the self-learning engine, and it needs no humans

### 3.3 Schema (Postgres 16 + PostGIS 3 + TimescaleDB)

**Reference layer**

```sql
-- The single join key for the entire platform.
CREATE TABLE place (
  place_id        BIGSERIAL PRIMARY KEY,
  kind            place_kind NOT NULL,   -- locality|camp|checkpoint|station|facility|governorate|road|crossing
  name_en         TEXT,
  name_ar         TEXT,
  admin1_pcode    TEXT,
  admin2_pcode    TEXT,
  oslo_area       CHAR(1),               -- A|B|C|H1|H2|seam
  geom            GEOMETRY(Geometry,4326) NOT NULL,
  centroid        GEOGRAPHY(Point,4326) GENERATED ALWAYS AS (...) STORED,
  source_refs     JSONB NOT NULL,        -- OCHA pcode, OSM id, PCBS code...
  confidence      REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX ON place USING GIST (geom);
CREATE INDEX ON place USING GIN  (to_tsvector('arabic', coalesce(name_ar,'')));

-- Every alias/spelling that has ever resolved to a place, with observed hit counts.
-- This table is what makes Arabic fuzzy matching improve over time, for free.
CREATE TABLE place_alias (
  alias_norm   TEXT PRIMARY KEY,
  place_id     BIGINT REFERENCES place,
  hits         INT DEFAULT 0,
  confidence   REAL,
  origin       TEXT   -- ocha|osm|observed|manual
);
```

**Claim layer (immutable, append-only, Timescale hypertable on `ingested_at`)**

```sql
CREATE TABLE claim (
  claim_id      BIGSERIAL,
  source_id     INT NOT NULL REFERENCES source,
  external_id   TEXT,                -- telegram msg id, article guid, API row key
  raw_ref       TEXT NOT NULL,       -- pointer into the bronze archive
  raw_text      TEXT,
  lang          TEXT,
  -- what the claim asserts
  claim_type    TEXT NOT NULL,       -- raid|strike|closure|fuel_available|price|casualty|...
  place_id      BIGINT REFERENCES place,
  place_precision place_precision,   -- exact|street|station|town|admin2|admin1|region|unknown
  occurred_at   TIMESTAMPTZ,
  occurred_precision time_precision NOT NULL, -- exact|hour|day|month|year|unknown
  reported_at   TIMESTAMPTZ NOT NULL,
  ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  attrs         JSONB NOT NULL DEFAULT '{}',  -- type-specific payload
  extraction    JSONB NOT NULL,      -- which cascade tier produced this, scores
  event_id      BIGINT REFERENCES event,      -- resolution result, nullable
  PRIMARY KEY (claim_id, ingested_at)
);
SELECT create_hypertable('claim','ingested_at');
```

**Belief layer (revisable, versioned)**

```sql
CREATE TABLE event (
  event_id        BIGSERIAL PRIMARY KEY,
  event_type      TEXT NOT NULL,
  place_id        BIGINT REFERENCES place,
  geom            GEOGRAPHY(Point,4326),
  occurred_at     TIMESTAMPTZ,
  occurred_precision time_precision NOT NULL,
  -- belief
  status          event_status NOT NULL DEFAULT 'believed', -- believed|retracted|superseded|merged
  confidence      REAL NOT NULL,
  claim_count     INT  NOT NULL,
  independent_sources INT NOT NULL,     -- the corroboration signal, first-class
  contradicted_by INT  NOT NULL DEFAULT 0,
  superseded_by   BIGINT REFERENCES event,
  metrics         JSONB NOT NULL DEFAULT '{}',  -- killed/injured/detained/structures
  sys_period      TSTZRANGE NOT NULL             -- SCD-2: replaces 15GB of snapshots
);
CREATE INDEX ON event USING GIST (geom);
CREATE INDEX ON event USING GIST (sys_period);
```

`as_of` queries become `WHERE sys_period @> :as_of` — correct, cheap, and it
retires the entire 15 GB snapshot directory.

**State layer (things that are true until they aren't — checkpoints, stations, utilities)**

```sql
CREATE TABLE state_observation (   -- hypertable
  place_id     BIGINT NOT NULL REFERENCES place,
  state_kind   TEXT   NOT NULL,    -- checkpoint_status|fuel_gasoline|fuel_diesel|power|water|internet
  value        TEXT   NOT NULL,    -- open|closed|congested | available|queue|empty | up|down
  observed_at  TIMESTAMPTZ NOT NULL,
  source_id    INT NOT NULL REFERENCES source,
  claim_id     BIGINT,
  raw_value    TEXT
);
SELECT create_hypertable('state_observation','observed_at');

-- Current belief, recomputed on write, with decay applied at read time.
CREATE MATERIALIZED VIEW state_current AS ...;
```

**Observation layer (the databank — measurements, not events)**

```sql
CREATE TABLE observation (         -- hypertable on occurred_at
  observation_id BIGSERIAL,
  dataset_id     INT NOT NULL REFERENCES dataset,
  place_id       BIGINT REFERENCES place,
  indicator      TEXT NOT NULL,    -- controlled vocabulary
  value_num      DOUBLE PRECISION,
  value_text     TEXT,
  unit           TEXT,
  occurred_at    TIMESTAMPTZ NOT NULL,
  occurred_precision time_precision NOT NULL,
  reported_at    TIMESTAMPTZ,
  ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  attrs          JSONB,
  PRIMARY KEY (observation_id, occurred_at)
);
```

All 244,461 databank records collapse into this one table with an `indicator`
vocabulary. Categories become *views*, not directories. Cross-category queries
("water availability vs. demolitions in Hebron governorate, monthly") become a
single GROUP BY instead of impossible.

**Governance layer**

```sql
CREATE TABLE source (
  source_id INT PRIMARY KEY, key TEXT UNIQUE, kind TEXT,   -- telegram|rss|api|file
  license_spdx TEXT NOT NULL, commercial_use BOOLEAN NOT NULL,
  attribution_text TEXT NOT NULL, authority_rank INT NOT NULL,
  reliability REAL, reliability_measured_at TIMESTAMPTZ,   -- learned, not typed
  reliability_n INT
);
```

`commercial_use` is enforced **in the query layer**, not in CI: a request on a
commercial tier physically cannot return rows whose source is non-commercial.
That is what makes ACLED-as-ground-truth safe.

### 3.4 Time semantics — the root cause fix

Every freshness bug in §1.2 traces to one `date` column doing four jobs:

| Column | Meaning | Fixes |
|:--|:--|:--|
| `occurred_at` + `occurred_precision` | When the real-world thing happened. `precision` is NOT NULL, so an annual aggregate is `('2026-01-01','year')` — never `2026-12-31` | negative freshness |
| `reported_at` | When the source published | — |
| `ingested_at` | When we received it | ingest-date-as-event-date |
| `valid_from`/`valid_to` | For state | stale-open |

Freshness is then computed as `max(occurred_at) WHERE occurred_precision <= 'day'`
per dataset, and is correct by construction rather than by a patched snapshot file.

### 3.5 State decay — the safety fix

Never serve a bare status. Serve a decayed belief:

```
confidence(t) = base(source) · 0.5^((t − observed_at) / half_life(state_kind, source_kind))
                · corroboration_boost(independent_sources)
```

with `half_life` tuned per state kind — and this is exactly why fuel is the right
Phase 1:

| State kind | Half-life | Rationale |
|:--|:--|:--|
| `fuel_diesel` / `fuel_gasoline` | **2–4 h** | Stations run dry within hours of delivery |
| `checkpoint_status` (live feed) | 1.5 h peak / 6 h off-peak | Already the wbkb assumption; currently unapplied |
| `power` / `water` | 12 h | Slower-moving |
| `road_closure` | 6 h | — |

Serving contract: every state response carries `value`, `confidence`,
`observed_at`, `age`, `staleness_band`, and `sources[]`. Below a confidence floor
the API returns `unknown` — **not the last known value**. A month-old "open"
becomes `unknown (last seen open 31 days ago)`, which is honest and safe.

### 3.6 Ingestion framework — killing the silent-null class

Replace 37 hand-rolled scripts with a declarative registry plus a base class under
a medallion layout:

```
bronze/   raw immutable payloads, content-addressed, never rewritten
silver/   parsed + normalized into claim / observation
gold/     resolved events, state_current, materialized aggregates
```

```yaml
# sources/registry.yaml
- key: ocha_movement_obstacles
  kind: api
  license: {spdx: CC-BY-3.0-IGO, commercial_use: true}
  attribution: "UN OCHA oPt"
  cadence: monthly
  expect: {min_records: 500, max_records: 5000}   # violation = FAILURE
  allow_empty: false
  schema_ref: schemas/ocha_obstacles.json
```

The framework provides — once, for every source — conditional GET/ETag, retry with
backoff, rate limiting, raw archival, schema-drift detection, and a `FetchResult`
contract where `ok` requires a record count inside the declared range. The eight
`ok`-with-`null` tasks become eight loud failures on day one.

### 3.7 Resolution layer — the "unifier" that actually unifies

Three resolvers, each a service used by *every* fetcher and by the classifier:

**Geo resolver** — `resolve_place(text, context) → (place_id, precision, confidence)`.
Built from OCHA admin boundaries + OSM extract + your 403 checkpoints + PCBS
localities + a new station registry. Arabic normalization and fuzzy matching
generalized from the existing `checkpoint_matcher.py`, backed by `place_alias`,
which accumulates observed spellings automatically. Realistic target: **7.1% → 60–80%**
admin coverage across the databank after backfill.

**Time resolver** — parses Arabic relative expressions ("الآن", "منذ ساعة", "فجر
اليوم") into `occurred_at` + precision, and normalizes upstream aggregation buckets
correctly.

**Entity resolver** — dedupes people (the 60,200 martyrs vs. 10,066 B'Tselem vs.
273 classifier-derived records currently sit in one table with an `entity_key`
that is only partly populated), facilities, and stations across sources.

**Event resolver** — clusters claims into events on (type, place proximity, time
window, semantic similarity), producing `independent_sources` as a first-class
column. Your existing incident grouper is the seed for this.

### 3.8 The classifier cascade

```
        ┌─────────────┐  high-conf   ┌──────────────────────────────┐
 msg ──▶│ T1: rules   │─────────────▶│ accept                        │
        │ (existing   │              └──────────────────────────────┘
        │  2,564 ln)  │  uncertain
        └──────┬──────┘        │
               │               ▼
               │        ┌─────────────┐  high-conf   ┌──────────┐
               │        │ T2: AraBERT │─────────────▶│ accept    │
               │        │  fine-tuned │              └──────────┘
               │        │  (~0.5GB    │  uncertain
               │        │   VRAM)     │        │
               │        └─────────────┘        ▼
               │                        ┌──────────────┐
               └── hard negatives ─────▶│ T3: LLM      │
                                        │  adjudicator │
                                        │ (Kilo/OpenAI-│
                                        │  compatible) │
                                        └──────────────┘
```

- **T1 (rules)** stays as the safety floor — precision can never regress below today's.
- **T2 (AraBERT-class encoder)**, fine-tuned on weak labels from the corroboration loop, handles the middle. ~0.5 GB VRAM, ~10 ms/message on the 3060. **Measured 2026-07-30: only ~4.2 GB of the 6 GB VRAM is free** (frigate ONNX detector + a resident 1.8 GB python process). T2 fits easily; a quantized 7B local fallback does **not** fit comfortably alongside — the local fallback is therefore CPU-only (slow, emergencies) unless the Phase 0 audit reclaims the 1.8 GB process.
- **T3 (LLM)** adjudicates only low-confidence and high-stakes cases (Tier-1 alert types, novel patterns). Backend: the Kilo Code subscription via its OpenAI-compatible endpoint — **verified 2026-07-30**: the `MINIMAX_API_KEY` in the Palestine `.env` and the `LLM_OPENAI_API_KEY` in the honcho env are hash-identical, i.e. one subscription already powering two prod services. Budgeted; on budget exhaustion or API failure it fails *closed* to T2 rather than dropping the message.

Routing is by calibrated confidence, and every tier writes its scores into
`claim.extraction`, so the cascade's own routing decisions become trainable.

### 3.9 The two learning loops — self-learning without humans

**Loop A — corroboration (immediate, weak, free).** Available today from data you
already have.

```
For each resolved event:
  positives ← claims belonging to events with ≥N independent sources in window W
  negatives ← claims that no independent source corroborates within T

Then, nightly:
  source.reliability ← Beta-Bernoulli posterior over (corroborated, uncorroborated)
                       per source × claim_type, with recency weighting
  keyword weights    ← pointwise mutual information between n-grams and outcomes
  training set       ← weak labels for T2 fine-tuning
```

This replaces the 30 hand-typed reliability rows with a measured, per-type,
recency-weighted posterior that updates every night — and it produces the training
set for T2 at zero marginal cost. Your data already contains 1,956 corroborated
groups and 1,940 single-source claims: the loop has enough signal to start on day one.

Guardrails: independence must be *real*, so channels that systematically copy each
other are detected (near-duplicate text within short lag) and collapsed into a
single independence unit before counting. Without this, cross-posting inflates
confidence — a failure mode worth designing against explicitly.

**Loop B — retrospective matching (delayed, strong, defensible).** Only possible
once the gazetteer exists.

```
T+3..14 days: for each event, search authoritative records
              (OCHA sitreps, ACLED, B'Tselem, ReliefWeb) for the same
              place (within radius) and time (within window)
  matched   → true positive
  unmatched → probable false positive (weighted by authority coverage)
  authoritative record with no event → false negative (recall measurement)
```

This produces the numbers in `accuracy_audit.json` **automatically and continuously**,
rather than by hand once. That published, continuously-updated accuracy figure is
the single most credible thing the platform can offer to any of the four buyer
segments — and it is equally the right thing to publish if the project is
open-sourced instead.

**Licensing note:** ACLED and OpenSky are non-commercial-only. They belong in
Loop B (scoring ourselves) and must never appear in a served response. §3.3's
`commercial_use` enforcement is what makes that structurally safe rather than a
policy promise.

**Unwired socket:** `state_observation` accepts a `source.kind = 'crowd'` with no
schema change. If you later ship the safety app, crowd confirmations become a
third loop by inserting rows — nothing else changes.

### 3.10 Retention: none

**Requirement (Zaid, 2026-07-31): every piece of gathered data stays in the
database. No data loss.** This is a hard constraint on the design, and it
overrides storage convenience wherever the two conflict.

What that forbids:

| Forbidden | Why it is tempting, and why not |
|:--|:--|
| Timescale `add_retention_policy()` | The obvious way to bound hypertable growth. Not used on `claim`, `observation`, or `state_observation` — dropping a chunk destroys observations permanently. |
| TTL / prune jobs | v1 had two, both destroying data on a schedule (see below). None exist in v2. |
| `DELETE` on observation tables | Corrections are `event.status='retracted'` + a new version. The claim that was wrong stays, because "this source said X and was wrong" is exactly the training signal Loop A needs. |
| Overwriting in place | The v1 pipeline rewrites `all-data.json` nightly, so a record an upstream stops publishing simply vanishes. v2 writes new rows with a new `ingested_at`; the old row keeps its own. |
| Downsampling old data | Aggregates are additional tables, never replacements. |

What is still allowed, because it destroys nothing:

- **Timescale compression** on chunks older than ~90 days. Rows stay fully queryable; only the on-disk encoding changes. This is the main lever for keeping growth affordable.
- **Continuous aggregates** — derived, additive, rebuildable from the base table.
- **Rebuilding derived reference data** — `resolve/load_gazetteer.py` truncates `place`/`place_alias` and reloads. Legitimate: those are *derived* from OCHA/OSM/v1 inputs and hold no observations. `claim.place_id` must be re-resolved after any such rebuild.
- **Bronze de-duplication by content hash** — identical upstream bytes produce the same object and are stored once. Nothing is lost; the second copy never existed as distinct data.

**Why the growth is affordable anyway.** v1's 15 GB comes from writing a *full
copy of everything* nightly — 500 MB/day regardless of how little changed. v2
stores only what changed: a new `claim` row per message, and a new `event`
version only when a belief actually moves. Steady-state growth is proportional
to real change, not to corpus size × days.

**What v1 already destroyed** (found during this audit, now stopped):

| Path | Damage |
|:--|:--|
| `write-snapshot.js` `SNAPSHOT_RETENTION_DAYS=30` | Snapshots are v1's only historical record, so this was a 30-day memory. Oldest surviving snapshot 2026-06-25 against a 2026-06-10 start — **~15 days already gone, unrecoverable.** Default now 0 = keep all. |
| `keyStore.rollupYesterday()` | Deleted a day's `usage_events` after aggregating only keyed rows (3 of 120,336). Caught ~8 minutes before its first scheduled run; nothing lost. DELETE removed entirely. |

Confirmed **not** losing data: alerts pruning (`MAX_ALERTS_STORED=0`, disabled),
checkpoint `DELETE`s (canonical-key merges), push-subscription `DELETE`s (dead
endpoints, not observations).

---

## 4. Source expansion

### 4.1 New live sources (all free, all commercially usable unless noted)

| Source | Signal | Cadence | Feeds |
|:--|:--|:--|:--|
| **GDELT 2.0** (GEO/DOC APIs) | Geocoded events, 65 languages incl. Arabic | **15 min** | Recall boost + Loop B corroboration |
| **NASA FIRMS** (VIIRS 375 m) | Thermal anomalies → strike/fire | ~12 h NRT | Gaza strike corroboration |
| **NASA Black Marble** (VNP46) | Nighttime lights → power outage | Daily, 3 h NRT | Utilities state |
| **IODA** (Georgia Tech) | Region/ASN internet outage | Near-real-time | Utilities state |
| **Cloudflare Radar** | Traffic anomalies + verified outages | Near-real-time | Corroborates IODA |
| **HDX HAPI** | Standardized conflict/food/displacement | Varies | Databank (no account needed, just app identifier) |
| **ReliefWeb API** | Humanitarian reports | Continuous | Loop B |
| **OCHA oPt sitreps** | WB Humanitarian Situation Update, Wed/Thu | 2–3×/wk | Loop B (needs a parser — no clean API) |
| **ACLED** *(non-commercial)* | Geocoded political violence | Weekly | **Loop B only** |
| **OpenSky** *(non-commercial)* | ADS-B; OAuth2 since Mar 2026 | Live | Research tier only |

### 4.2 Telegram expansion

Current: 20 sources actually producing, against 5 declared in `.env`. Fix the
drift, then expand systematically — the `channel_candidates` discovery process
already exists in `checkpoints.db` (9,942 candidates, 308 vocab discoveries) and
should be promoted into a general **source discovery loop**: monitor forwarded-from
metadata and cross-references, score candidates by corroboration contribution, and
promote automatically above a threshold. New channel classes to target: fuel/
commerce, municipal/utility, governorate-local, medical/ambulance.

### 4.3 New signal classes

**Fuel (Phase 1, priority).** New `place.kind = 'station'` registry built from OSM
`amenity=fuel` in the WB extract, enriched with brand/operator. New claim types:
`fuel_available`, `fuel_queue`, `fuel_price`, `fuel_empty`, `fuel_delivery`,
`cooking_gas`. State kinds `fuel_gasoline`/`fuel_diesel`/`cooking_gas` with 2–4 h
half-life. Serving: "diesel within 15 km of me, observed in the last 3 h, ranked by
confidence × distance", wired into your existing Valhalla routing so the answer is
*drive time*, not straight-line distance.

**Movement & access.** Queue-time estimation from update cadence, closure-duration
prediction, corridor traversability scoring, gate schedules — building on 91,568
existing updates.

**Essential services.** Power/water cutoffs, internet blackouts (IODA + Cloudflare
Radar + your existing OONI), hospital capacity and generator status, bakery/market
status. Your `internet_status.py` and `market_data.py` stubs are the seed.

**Displacement & shelter.** Evacuation orders, demolition *notices* vs. *executions*
(currently indistinguishable), shelter capacity, land seizure orders — filling the
gap between the alert stream and the OCHA/IDMC databank.

---

## 5. Phased plan

Each phase ends with a measurable gate. Nothing proceeds until its gate passes.

### Phase 0 — Foundation & honesty (≈1 week)

1. **Homelab audit.** Inventory all 26 containers with real memory/CPU usage; produce a kill/keep/shrink list with reclaimed-RAM estimates. **Nothing stopped without your approval.**
2. Stand up Postgres 16 + PostGIS 3 + TimescaleDB at `~/palestine-v2`, tuned for a small RAM envelope; own ports, own volumes; v1 untouched.
3. Bronze archive + the fetcher base class with the `FetchResult` contract.
4. **Gazetteer v1** — OCHA admin + OSM + 403 checkpoints + PCBS localities + station registry.
5. **Cheap v1 fixes, shipped in place** (they make the current system honest while v2 is built): the three freshness bugs, the 8 silent-null tasks, `usage_daily` rollup, `channel_reliability` key-case normalization, and a `staleness_band` on checkpoint responses so nothing month-old is served as `open`.

**Gate:** DB up within the reclaimed RAM budget; gazetteer resolves a held-out sample of Arabic place strings at ≥80% accuracy; v1 freshness endpoints return no negative values.

### Phase 1 — Fuel vertical, end to end (≈2 weeks)

Proves every subsystem on one urgent, self-contained problem: station registry →
Telegram fuel classifier path → claim/event resolution → decayed state → routing-aware
serving → corroboration loop scoring its own accuracy.

**Gate:** "Where can I get diesel right now?" answered with a confidence-ranked,
drive-time-sorted list; measured precision ≥0.80 against a held-out week; **zero**
stations served as `available` on observations older than 2× half-life.

### Phase 2 — Databank migration (≈2–3 weeks)

All 244,461 records → `observation`; every record through the geo/time resolvers;
SCD-2 replaces the 15 GB snapshot tree; license enforcement in the query layer;
the 6 `verify-required` licenses resolved.

**Gate:** admin-key coverage ≥60% (from 7.1%); `as_of` queries correct against the
retained old snapshots; storage <2 GB; a cross-tier query (alerts × databank, joined
on place and time) returns correct results — the thing that is impossible today.

### Phase 3 — Cascade & learning loops (≈3 weeks)

T2 encoder trained on Loop A weak labels; T3 adjudicator wired; Loop B retrospective
matching against OCHA/ACLED/B'Tselem/ReliefWeb; `channel_reliability` becomes a
nightly materialized view; `accuracy_audit.json` becomes a generated endpoint.

**Gate:** measured precision ≥0.90 and recall ≥0.90 on a held-out window (from
0.827/0.88), with accuracy computed automatically rather than by hand.

### Phase 4 — Source expansion (≈2 weeks)

GDELT, FIRMS, Black Marble, IODA, Cloudflare Radar, HAPI, ReliefWeb; source
discovery loop for Telegram; movement/services/displacement signal classes.

**Gate:** recall improvement attributable per-source and measured; every new source
declares license and passes the `expect` contract.

### Phase 5 — Serving surface & cutover (≈2 weeks)

Public API v2, webhooks with the geo filters that have never had a subscriber,
tiered access, and dual-run comparison against v1.

**Gate:** v2 beats v1 on measured precision, recall, and latency across a full
week of dual-running. Only then does traffic move.

---

## 6. Open risks

| Risk | Mitigation |
|:--|:--|
| **RAM.** Postgres + Timescale + inference may not fit even after reclamation | Phase 0 gate is explicitly a resource gate. Fallback: move the analytical tier off-box; live tier stays local |
| **Correlated sources inflate confidence.** Telegram channels copy each other | Near-duplicate detection collapses copies into one independence unit *before* corroboration counting (§3.9) |
| **Weak labels encode the rules' existing biases.** T2 learns T1's blind spots | Loop B (independent authoritative sources) is the corrective; measure T2 against Loop B, not against T1 |
| **Retrospective sources have their own coverage gaps.** Absence ≠ false positive | Weight unmatched events by each authority's known coverage for that place/type; report recall bands, not point estimates |
| **Fuel signal may be too sparse in Telegram** to sustain a 2–4 h half-life | Phase 1 gate measures this directly. If sparse, the honest product is "last known + age", and the crowd socket becomes the answer sooner |
| **Four buyer segments at once** dilutes focus | One core, four serving surfaces. Phase 5 ships the surfaces; Phases 0–4 are shared regardless of who buys |
| **Dual-run drift** — v1 and v2 diverge silently during the build | Phase 5 comparison is automated and continuous, not a one-off check |

---

## 7. What this buys you

| | Today | After |
|:--|:--|:--|
| Cross-tier join | **Impossible** (4.1% shared keys) | Single SQL join on `place_id` |
| Geographic coverage | 7.1% admin | 60–80% admin |
| Query latency | 0.4–3.0 s (JSON.parse) | <50 ms (indexed) |
| Storage | 15 GB | <2 GB |
| Source reliability | 30 hand-typed constants | Nightly measured posterior per source × type |
| Accuracy measurement | Manual, once (2026-07-19) | Continuous, automatic, publishable |
| Precision / recall | 0.827 / 0.88 (estimated) | ≥0.90 / ≥0.90 (measured) |
| Stale-open safety bug | 262 rows 30 d+ served as `open` | Structurally impossible — decay returns `unknown` |
| Silent ETL failure | 8 of 37 tasks | Contract violation = loud failure |
| License enforcement | Asserted in a README | Enforced in the query layer |
| Fuel | Not modelled | First-class entity with hour-scale decay |

---

## 8. Handoff notes — read this before implementing

This section exists so a different model/session can implement the plan without
re-deriving context or silently drifting.

### 8.1 Fact ledger — what kind of claim each number is

**Measured facts (re-runnable).** Every number in §1 was queried directly from the
live system on 2026-07-30: the join-key coverage table (Python sweep over
`public/data/unified/*/all-data.json` + partitions), all row counts (sqlite3
against `alerts.db`, `checkpoints.db`, `news.db`, `corpus.db`, `keys.db`), the
corroboration distribution, the staleness bands, the pipeline-report nulls, and
the hardware envelope. If a number matters to a decision, re-run the query —
never trust the v1 README, which contradicts its own databases (claims 132,219
records/14 categories; reality 244,461/22; claims 10 channels; reality 20
producing sources).

**Verified since first draft.** (a) The Kilo Code key identity — hash-compared,
match. (b) GPU headroom — ~4.2 GB VRAM free, not 6 GB (see §3.8). (c)
`quality.json` has 19 entries, not 20 as first written — three categories
missing, not two; the substantive finding is unchanged.

**Estimates and targets — tunable, not physics.** The half-life table (§3.5), the
60–80% geo-coverage target (§3.7), the ≥0.90/≥0.90 Phase 3 gate, and all phase
durations are informed judgments. Gates are *renegotiation checkpoints with Zaid*:
if a gate proves unreachable, stop and discuss — do not quietly lower it, and do
not grind past it.

### 8.2 Implementation traps (known, decided, or must-decide)

1. **Telegram session sharing.** v1's Telethon session files must never be opened
   by two clients concurrently (session corruption / auth kicks). For the
   dual-run period, either (a) provision a second Telegram session/account for
   v2, or (b) keep v1 as the sole Telegram consumer and tee raw messages to v2
   via a local queue. **Must be decided with Zaid before any Phase 1 ingestion
   code.** Option (b) is safer for the account; option (a) is cleaner
   architecture.
2. **GPU contention.** Budget T2 against ~4.2 GB free VRAM. Local LLM fallback is
   CPU-only unless the Phase 0 audit reclaims the resident 1.8 GB python process
   (pid was 2854 at measurement; identify what it belongs to before touching).
3. **DDL sketches are sketches.** §3.3 contains `(...)` placeholders (centroid
   expression, `state_current` definition, enum types). Phase 0 writes complete
   migration files. FK creation order: `source` → `place` → `event` → `claim`
   (claim references event). Timescale hypertables need their PK to include the
   partition column — already reflected in the sketches.
4. **"All records → observation" hides 22 mapping jobs.** Each v1 category needs
   an explicit indicator-vocabulary mapping and a per-category decision about
   what `occurred_at`/precision means for that source. Budget this inside
   Phase 2; keep the v1 category name as a `dataset` attribute so views can
   reproduce v1 semantics exactly during dual-run comparison.
5. **Prod safety is absolute.** `/opt/stacks/palestine` (cloudflared tunnel) and
   `~/lifeos` are live. All v2 work stays in `~/palestine-v2` with its own ports
   and volumes. The *only* sanctioned v1 changes are the Phase 0 honesty fixes
   (§5, item 5), each individually approved by Zaid before deploy. No container
   is stopped without explicit sign-off.
6. **Corroboration independence.** Do not count corroboration before the
   near-duplicate/copy-detection collapse (§3.9) exists, even in a prototype —
   reliability numbers learned from inflated agreement are worse than the
   hand-typed constants they replace.

### 8.3 Open items that require Zaid, not a model

- Approval of the Phase 0 homelab kill/keep/shrink list.
- The Telegram second-session vs. tee decision (trap 1).
- Resolution of the 6 `verify-required` licenses — needs human reading of
  upstream terms, possibly contacting the publishers (OCHA, PCBS, Peace Now,
  HaMoked, Palestine Open Maps).
- Sell vs. open-source remains deliberately undecided; nothing in Phases 0–4 may
  foreclose either path (license enforcement in the query layer is what keeps
  both open).
