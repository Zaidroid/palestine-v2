-- 009 — per-place staleness, because reporting cadence is bimodal.
--
-- Measured on 92,763 v1 checkpoint updates (2026-06-09 → 07-31, 364 places):
--   عورتا  5,956 updates, ~12.5 min average gap
--   جبع    5,112 updates, ~14.6 min
--   …yet only 96 of 364 places were updated in the last 6h at all.
--
-- One half-life per state_kind cannot serve both ends. Two hours of silence
-- from عورتا means something changed or reporting stopped; two hours from a
-- rarely-mentioned checkpoint means nothing. Applying the busy figure to the
-- tail marks quiet-but-fine places stale; applying the tail figure to the busy
-- ones keeps a dead reading alive — the stale-open bug all over again.
--
-- So each place gets a half-life derived from ITS OWN observed rhythm, with the
-- state_kind default as fallback for places not yet measured.
--
-- Rollback: DROP TABLE place_state_cadence; recreate state_serving from 006.

CREATE TABLE place_state_cadence (
  place_id           BIGINT  NOT NULL REFERENCES place(place_id) ON DELETE CASCADE,
  state_kind         TEXT    NOT NULL REFERENCES state_kind_config(state_kind),
  median_gap_seconds INTEGER NOT NULL CHECK (median_gap_seconds > 0),
  observations       INTEGER NOT NULL,
  half_life_seconds  INTEGER NOT NULL CHECK (half_life_seconds > 0),
  computed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (place_id, state_kind)
);
COMMENT ON TABLE place_state_cadence IS
  'Per-place half-life from observed reporting rhythm. Recomputed nightly; state_serving falls back to state_kind_config where absent.';

DROP VIEW IF EXISTS state_serving;
CREATE VIEW state_serving AS
SELECT
  sc.place_id,
  p.name_en, p.name_ar, p.kind AS place_kind, p.centroid,
  sc.state_kind,
  sc.value                                   AS last_known_value,
  sc.observed_at,
  EXTRACT(EPOCH FROM (now() - sc.observed_at))::bigint / 60 AS age_minutes,
  sc.independent_sources,
  sc.contradicted_by,
  COALESCE(c.half_life_seconds, k.half_life_seconds)        AS half_life_seconds,
  c.median_gap_seconds,
  (c.place_id IS NOT NULL)                                  AS cadence_measured,
  state_confidence(sc.base_confidence, sc.observed_at,
                   COALESCE(c.half_life_seconds, k.half_life_seconds), now()) AS confidence,
  CASE
    WHEN state_confidence(sc.base_confidence, sc.observed_at,
                          COALESCE(c.half_life_seconds, k.half_life_seconds), now())
         < k.confidence_floor THEN 'unknown'
    ELSE sc.value
  END AS value,
  CASE
    WHEN now() - sc.observed_at
         < make_interval(secs => COALESCE(c.half_life_seconds, k.half_life_seconds))     THEN 'live'
    WHEN now() - sc.observed_at
         < make_interval(secs => COALESCE(c.half_life_seconds, k.half_life_seconds) * 2) THEN 'recent'
    WHEN now() - sc.observed_at
         < make_interval(secs => COALESCE(c.half_life_seconds, k.half_life_seconds) * 8) THEN 'stale'
    ELSE 'expired'
  END AS staleness_band
FROM state_current sc
JOIN state_kind_config k        ON k.state_kind = sc.state_kind
JOIN place p                    ON p.place_id   = sc.place_id
LEFT JOIN place_state_cadence c ON c.place_id   = sc.place_id
                               AND c.state_kind = sc.state_kind;

COMMENT ON VIEW state_serving IS
  'Serving contract. API MUST read from here, never state_current. Applies per-place decay and returns value=unknown below the floor, with the last reading preserved in last_known_value.';
