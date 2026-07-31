-- 006 — state layer: things true until they aren't (checkpoints, fuel, utilities).
-- ARCHITECTURE §3.5. This is where v1's stale-open safety bug is fixed
-- structurally: nothing is ever served as a bare value.

CREATE TABLE state_observation (
  state_obs_id  BIGSERIAL,
  place_id      BIGINT NOT NULL REFERENCES place(place_id),
  state_kind    TEXT NOT NULL,   -- checkpoint_status|fuel_gasoline|fuel_diesel|cooking_gas|power|water|internet
  value         TEXT NOT NULL,
  raw_value     TEXT,
  observed_at   TIMESTAMPTZ NOT NULL,
  source_id     INTEGER NOT NULL REFERENCES source(source_id),
  claim_id      BIGINT,
  confidence    REAL NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
  attrs         JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (state_obs_id, observed_at)
);
SELECT create_hypertable('state_observation','observed_at', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX state_obs_place_idx ON state_observation (place_id, state_kind, observed_at DESC);
CREATE INDEX state_obs_kind_idx  ON state_observation (state_kind, observed_at DESC);

-- Half-life registry. Values are config, not physics — tune from measurement.
CREATE TABLE state_kind_config (
  state_kind        TEXT PRIMARY KEY,
  half_life_seconds INTEGER NOT NULL CHECK (half_life_seconds > 0),
  confidence_floor  REAL NOT NULL DEFAULT 0.25 CHECK (confidence_floor BETWEEN 0 AND 1),
  note              TEXT
);
INSERT INTO state_kind_config (state_kind, half_life_seconds, confidence_floor, note) VALUES
  ('fuel_diesel',       10800, 0.30, 'Stations run dry within hours of delivery (3h)'),
  ('fuel_gasoline',     10800, 0.30, '3h'),
  ('cooking_gas',       21600, 0.30, '6h'),
  ('checkpoint_status',  5400, 0.25, '1.5h — the wbkb live_feed assumption, finally applied'),
  ('road_closure',      21600, 0.25, '6h'),
  ('power',             43200, 0.25, '12h'),
  ('water',             43200, 0.25, '12h'),
  ('internet',          21600, 0.25, '6h');

-- Current belief per (place, state_kind). Maintained on write; decay applied at read.
CREATE TABLE state_current (
  place_id            BIGINT NOT NULL REFERENCES place(place_id),
  state_kind          TEXT NOT NULL REFERENCES state_kind_config(state_kind),
  value               TEXT NOT NULL,
  observed_at         TIMESTAMPTZ NOT NULL,
  source_id           INTEGER NOT NULL REFERENCES source(source_id),
  base_confidence     REAL NOT NULL CHECK (base_confidence BETWEEN 0 AND 1),
  independent_sources INTEGER NOT NULL DEFAULT 1,
  contradicted_by     INTEGER NOT NULL DEFAULT 0,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (place_id, state_kind)
);

-- Exponential decay. IMMUTABLE (takes `at` explicitly) so it can be indexed.
-- Clamping is not cosmetic: at a 3h half-life a 30-day-old observation is
-- 0.5^240 ~= 5.6e-73, which is representable as float8 but UNDERFLOWS on the
-- cast to float4 and raises. v1 currently holds 262 checkpoint rows older than
-- 30 days, so the unclamped version would fail on real data immediately.
CREATE OR REPLACE FUNCTION state_confidence(
  base REAL, observed TIMESTAMPTZ, half_life_s INTEGER, at TIMESTAMPTZ
) RETURNS REAL LANGUAGE sql IMMUTABLE AS $fn$
  SELECT CASE
           WHEN d IS NULL   THEN 0::real
           WHEN d <= 1e-6   THEN 0::real   -- far below any floor; treat as zero
           WHEN d >= 1.0    THEN 1::real   -- observation in the future
           ELSE d::real
         END
  FROM (
    SELECT CASE WHEN half_life_s IS NULL OR half_life_s <= 0 THEN NULL::float8
                ELSE base::float8
                     * power(0.5::float8,
                             EXTRACT(EPOCH FROM (at - observed))::float8
                             / half_life_s::float8)
           END AS d
  ) s
$fn$;

-- THE SERVING CONTRACT. Never expose state_current directly — this view is what
-- makes "month-old open" structurally impossible: below the floor the served
-- value is 'unknown', with the last known value carried separately.
CREATE OR REPLACE VIEW state_serving AS
SELECT
  sc.place_id,
  p.name_en, p.name_ar, p.kind AS place_kind, p.centroid,
  sc.state_kind,
  sc.value                                   AS last_known_value,
  sc.observed_at,
  EXTRACT(EPOCH FROM (now() - sc.observed_at))::bigint / 60 AS age_minutes,
  sc.independent_sources,
  sc.contradicted_by,
  state_confidence(sc.base_confidence, sc.observed_at, k.half_life_seconds, now()) AS confidence,
  CASE
    WHEN state_confidence(sc.base_confidence, sc.observed_at, k.half_life_seconds, now())
         < k.confidence_floor THEN 'unknown'
    ELSE sc.value
  END AS value,
  CASE
    WHEN now() - sc.observed_at < make_interval(secs => k.half_life_seconds)     THEN 'live'
    WHEN now() - sc.observed_at < make_interval(secs => k.half_life_seconds * 2) THEN 'recent'
    WHEN now() - sc.observed_at < make_interval(secs => k.half_life_seconds * 8) THEN 'stale'
    ELSE 'expired'
  END AS staleness_band
FROM state_current sc
JOIN state_kind_config k ON k.state_kind = sc.state_kind
JOIN place p             ON p.place_id   = sc.place_id;

COMMENT ON VIEW state_serving IS
  'Serving contract. API MUST read from here, never from state_current.';
