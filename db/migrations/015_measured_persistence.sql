-- 015 — decay calibrated from measurement, and freshness separated from truth.
--
-- The half-life was a guess (1.5x a place's median reporting gap). Measured
-- against 69,616 consecutive report pairs, that guess was wrong in both
-- directions at once, because HOW LONG A STATUS STAYS TRUE DEPENDS ON THE
-- STATUS. P(next report carries the same value), by elapsed time:
--
--     elapsed:      5m    10m   20m   30m    1h    2h    4h    8h   24h
--     open        0.96  0.89  0.88  0.89  0.88  0.88  0.88  0.87  0.88
--     closed      0.92  0.75  0.74  0.75  0.77  0.74  0.70  0.64  0.62
--     congested   0.84  0.64  0.64  0.57  0.55  0.48  0.40  0.34  0.38
--
-- Congestion is genuinely transient — at two hours it is more likely gone than
-- not. A closure holds around 0.70 for hours. And `open` flattens at 0.88 and
-- stays there indefinitely, which is not persistence at all: it is the BASE
-- RATE. Most checkpoints are open most of the time, so a day-old "open" reading
-- agrees with the next report for the same reason a coin agrees with itself.
--
-- Two consequences, and they pull opposite ways:
--
--   The old model was far TOO AGGRESSIVE. A place reported every 8 minutes got
--   a 15-minute half-life and went `unknown` after ~22 minutes of quiet, while
--   the measurement says the value still held 82% of the time at 20-30 minutes.
--   Good information was being discarded.
--
--   And it would be too LENIENT if we simply believed the persistence curve,
--   because `open` never decays — a three-day-old reading would still serve as
--   open at high confidence. That is v1's bug wearing a probability.
--
-- The resolution is that CONFIDENCE and FRESHNESS answer different questions,
-- so both must gate:
--
--   confidence  = base_confidence x informativeness, where informativeness is
--                 how far the reading beats a coin flip, (p(t) - 0.5) / (p0 - 0.5).
--                 It is 1 when the report lands and 0 once the reading tells us
--                 nothing the base rate did not already.
--
--   freshness   = are we still WATCHING this place? Independent of whether the
--                 value probably still holds. Past `expired` — eight times the
--                 place's own observed cadence — we are not watching, and the
--                 value is not asserted however plausible it remains.
--
-- Rollback: DROP TABLE state_value_decay; restore state_serving from 011.

CREATE TABLE state_value_decay (
  state_kind        TEXT NOT NULL REFERENCES state_kind_config(state_kind),
  value             TEXT NOT NULL,
  p0                REAL NOT NULL CHECK (p0 BETWEEN 0 AND 1),
  asymptote         REAL NOT NULL CHECK (asymptote BETWEEN 0 AND 1),
  half_life_seconds INTEGER NOT NULL CHECK (half_life_seconds > 0),
  observations      INTEGER NOT NULL,
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (state_kind, value),
  CHECK (asymptote <= p0)
);
COMMENT ON TABLE state_value_decay IS
  'Measured persistence per (state_kind, value): p(t) = asymptote + (p0-asymptote)*0.5^(t/half_life). Fitted by learn/state_persistence.py, never hand-set.';

-- p(t) for a value, with the same exponent guard as state_confidence: past ~60
-- halvings power() underflows float8 before any clamp can run, which took every
-- query down when 50 days of history met a 15-minute half-life.
CREATE OR REPLACE FUNCTION value_persistence(
  p0 REAL, asymptote REAL, half_life_s INTEGER,
  observed TIMESTAMPTZ, at TIMESTAMPTZ
) RETURNS REAL LANGUAGE sql IMMUTABLE AS $fn$
  SELECT CASE
           WHEN half_life_s IS NULL OR half_life_s <= 0 THEN asymptote
           WHEN halvings <= 0  THEN p0
           WHEN halvings > 60  THEN asymptote
           ELSE LEAST(GREATEST(
                  (asymptote::float8
                   + (p0 - asymptote)::float8 * power(0.5::float8, halvings))::real,
                0::real), 1::real)
         END
  FROM (SELECT EXTRACT(EPOCH FROM (at - observed))::float8
               / NULLIF(half_life_s, 0)::float8 AS halvings) s
$fn$;

COMMENT ON FUNCTION value_persistence(REAL, REAL, INTEGER, TIMESTAMPTZ, TIMESTAMPTZ) IS
  'Measured probability a reading still holds after elapsed time. Decays toward the base rate, not toward zero.';

DROP VIEW IF EXISTS checkpoint_serving;
DROP VIEW IF EXISTS state_serving;

CREATE VIEW state_serving AS
WITH base AS (
  SELECT
    sc.place_id, sc.state_kind, sc.direction, sc.value AS raw_value,
    sc.observed_at, sc.base_confidence, sc.independent_sources, sc.contradicted_by,
    p.name_en, p.name_ar, p.kind AS place_kind, p.centroid,
    k.confidence_floor,
    COALESCE(c.half_life_seconds, k.half_life_seconds) AS half_life_seconds,
    c.median_gap_seconds,
    (c.place_id IS NOT NULL) AS cadence_measured,
    d.state_kind IS NOT NULL AS persistence_measured,
    -- How likely the reading is still true. Falls back to the flat exponential
    -- where no curve has been fitted yet.
    CASE
      WHEN d.state_kind IS NOT NULL
        THEN value_persistence(d.p0, d.asymptote, d.half_life_seconds,
                               sc.observed_at, now())
      ELSE state_confidence(1.0::real, sc.observed_at,
                            COALESCE(c.half_life_seconds, k.half_life_seconds), now())
    END AS persistence,
    d.p0 AS persistence_p0
  FROM state_current sc
  JOIN state_kind_config k        ON k.state_kind = sc.state_kind
  JOIN place p                    ON p.place_id   = sc.place_id
  LEFT JOIN place_state_cadence c ON c.place_id   = sc.place_id
                                 AND c.state_kind = sc.state_kind
                                 AND c.direction  = sc.direction
  LEFT JOIN state_value_decay d   ON d.state_kind = sc.state_kind
                                 AND d.value      = sc.value
), scored AS (
  SELECT base.*,
         EXTRACT(EPOCH FROM (now() - observed_at))::bigint / 60 AS age_minutes,
         CASE
           WHEN now() - observed_at < make_interval(secs => half_life_seconds)     THEN 'live'
           WHEN now() - observed_at < make_interval(secs => half_life_seconds * 2) THEN 'recent'
           WHEN now() - observed_at < make_interval(secs => half_life_seconds * 8) THEN 'stale'
           ELSE 'expired'
         END AS staleness_band,
         -- Informativeness: how far past a coin flip this reading still is.
         -- 1.0 on arrival, 0.0 once it says no more than the base rate does.
         (base_confidence * CASE
            WHEN persistence_p0 IS NULL OR persistence_p0 <= 0.5 THEN persistence
            ELSE GREATEST(0::real,
                   LEAST(1::real, (persistence - 0.5) / (persistence_p0 - 0.5)))
          END)::real AS confidence
  FROM base
)
SELECT
  place_id, name_en, name_ar, place_kind, centroid,
  state_kind, direction,
  raw_value AS last_known_value,
  observed_at, age_minutes,
  independent_sources, contradicted_by,
  half_life_seconds, median_gap_seconds, cadence_measured,
  persistence, persistence_measured,
  confidence,
  -- BOTH gates. Confidence answers "is it probably still true"; staleness
  -- answers "are we still watching". `open` is plausible almost forever, so
  -- without the freshness gate it would be asserted indefinitely — which is
  -- exactly the v1 failure this whole layer exists to prevent.
  CASE
    WHEN confidence < confidence_floor THEN 'unknown'
    WHEN staleness_band = 'expired'    THEN 'unknown'
    ELSE raw_value
  END AS value,
  staleness_band
FROM scored;

COMMENT ON VIEW state_serving IS
  'Serving contract. API MUST read from here, never state_current. Confidence is measured persistence scaled by corroboration; value collapses to unknown when either confidence or freshness fails, with the reading preserved in last_known_value.';


-- checkpoint_serving is rebuilt verbatim from 014 — it depends on
-- state_serving and had to be dropped to replace it. The definition is
-- unchanged; only the confidence it reads through is.

CREATE VIEW checkpoint_serving AS
WITH travel AS (SELECT unnest(ARRAY['inbound','outbound','both']) AS dir),
flow AS (
  SELECT DISTINCT ON (s.place_id, t.dir)
         s.place_id, t.dir AS direction,
         s.value, s.last_known_value, s.observed_at, s.age_minutes,
         s.confidence, s.staleness_band, s.half_life_seconds,
         s.independent_sources, s.contradicted_by, s.cadence_measured,
         s.direction AS reported_for
  FROM state_serving s
  CROSS JOIN travel t
  WHERE s.state_kind = 'checkpoint_flow'
    AND (s.direction = t.dir OR s.direction = 'both')
  -- Freshest wins; on a tie the direction-specific report beats the general one.
  ORDER BY s.place_id, t.dir, s.observed_at DESC,
           (s.direction = t.dir) DESC
),
presence AS (
  SELECT place_id, direction,
         array_agg(who ORDER BY who)                    AS present,
         MIN(age_minutes)                               AS presence_age_minutes,
         MAX(confidence)                                AS presence_confidence
  FROM (
    SELECT DISTINCT ON (s.place_id, t.dir, s.state_kind)
           s.place_id, t.dir AS direction,
           replace(s.state_kind, 'checkpoint_', '') AS who,
           s.value, s.age_minutes, s.confidence
    FROM state_serving s
    CROSS JOIN travel t
    WHERE s.state_kind IN ('checkpoint_idf','checkpoint_police',
                           'checkpoint_settlers','checkpoint_inspection')
      AND (s.direction = t.dir OR s.direction = 'both')
    ORDER BY s.place_id, t.dir, s.state_kind, s.observed_at DESC,
             (s.direction = t.dir) DESC
  ) x
  WHERE value <> 'unknown'        -- decayed presence is not presence
  GROUP BY place_id, direction
)
SELECT
  p.place_id,
  p.name_ar,
  p.name_en,
  p.kind AS place_kind,
  p.centroid,
  f.direction,
  f.value                       AS flow,
  f.last_known_value            AS last_known_flow,
  f.reported_for,
  f.observed_at,
  f.age_minutes,
  f.confidence,
  f.staleness_band,
  f.half_life_seconds,
  f.cadence_measured,
  f.independent_sources,
  f.contradicted_by,
  COALESCE(pr.present, ARRAY[]::text[]) AS present,
  pr.presence_age_minutes,
  -- The traveller's question. NULL means we do not know — never guessed from
  -- a decayed reading, and never inferred from presence.
  CASE f.value
    WHEN 'open'      THEN true
    WHEN 'slow'      THEN true
    WHEN 'congested' THEN true
    WHEN 'closed'    THEN false
    ELSE NULL
  END AS passable
FROM flow f
JOIN place p ON p.place_id = f.place_id
LEFT JOIN presence pr ON pr.place_id = f.place_id AND pr.direction = f.direction
WHERE p.servable;

COMMENT ON VIEW checkpoint_serving IS
  'One row per (checkpoint, travel direction). Resolves the direction fallback (specific report, else ''both''), keeps flow and presence on separate axes, and exposes passable derived from flow alone. API reads this, never state_current.';
