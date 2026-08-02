-- 016 — an absolute ceiling on how old an asserted reading may be.
--
-- 015 calibrated confidence from measurement, and the measurement says `open`
-- is ~0.87 likely to still be true no matter how much time passes, because
-- that is simply the base rate. Confidence therefore never retires an `open`
-- reading, and the freshness gate alone did not either: `expired` fires at
-- eight times a place's own cadence, and for quiet checkpoints the cadence
-- half-life hits its 12-hour clamp, putting the gate at ninety-six hours.
--
-- The result was 47 checkpoints asserting `open` on evidence over a day old,
-- the worst at 90 hours. That is v1's bug re-entering through the back door,
-- with a plausible-looking probability attached.
--
-- The missing idea is that plausibility is not currency. "Probably still open,
-- based on a report from Tuesday" is not an answer to "can I get through right
-- now" — and a voice assistant relaying it to someone about to drive cannot
-- convey the difference. Past some wall-clock age we are not observing the
-- place, whatever the base rate says.
--
-- Six hours, from the age distribution of currently-asserted readings:
--     <30m 18 · 30-60m 7 · 1-3h 23 · 3-6h 41 · 6-12h 9 · 12-24h 10 · >24h 54
-- The population thins sharply after six hours and the remainder is a long
-- tail of places that simply stopped being reported. Capping there keeps 89 of
-- 162 assertions and removes every one of the stale ones.
--
-- Presence gets two hours: soldiers, police and settlers move on far faster
-- than a closure lifts, and the cost of announcing a checkpoint that is no
-- longer manned is a traveller taking a longer route for no reason.
--
-- NULL means no cap — fuel keeps the behaviour its acceptance gate already
-- verifies, and is left alone here.

ALTER TABLE state_kind_config
  ADD COLUMN max_assert_seconds INTEGER CHECK (max_assert_seconds IS NULL OR max_assert_seconds > 0);

COMMENT ON COLUMN state_kind_config.max_assert_seconds IS
  'Hard ceiling on the age of an asserted reading, independent of confidence. NULL = no ceiling. Guards against values whose base rate keeps them plausible forever.';

UPDATE state_kind_config SET max_assert_seconds = 21600  -- 6h
  WHERE state_kind = 'checkpoint_flow';
UPDATE state_kind_config SET max_assert_seconds = 7200   -- 2h
  WHERE state_kind IN ('checkpoint_idf','checkpoint_police',
                       'checkpoint_settlers','checkpoint_inspection');
UPDATE state_kind_config SET max_assert_seconds = 21600  -- 6h, legacy kind
  WHERE state_kind = 'checkpoint_status';

DROP VIEW IF EXISTS checkpoint_serving;
DROP VIEW IF EXISTS state_serving;

CREATE VIEW state_serving AS
WITH base AS (
  SELECT
    sc.place_id, sc.state_kind, sc.direction, sc.value AS raw_value,
    sc.observed_at, sc.base_confidence, sc.independent_sources, sc.contradicted_by,
    p.name_en, p.name_ar, p.kind AS place_kind, p.centroid,
    k.confidence_floor, k.max_assert_seconds,
    COALESCE(c.half_life_seconds, k.half_life_seconds) AS half_life_seconds,
    c.median_gap_seconds,
    (c.place_id IS NOT NULL) AS cadence_measured,
    d.state_kind IS NOT NULL AS persistence_measured,
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
  -- THREE gates, each answering a different question:
  --   confidence — is it probably still true?
  --   staleness  — are we still watching this place at its own rhythm?
  --   max age    — is this recent enough to call current at all?
  -- Only the third retires a reading whose base rate keeps it plausible
  -- indefinitely, which is every `open` reading ever filed.
  CASE
    WHEN confidence < confidence_floor THEN 'unknown'
    WHEN staleness_band = 'expired'    THEN 'unknown'
    WHEN max_assert_seconds IS NOT NULL
         AND now() - observed_at > make_interval(secs => max_assert_seconds)
                                       THEN 'unknown'
    ELSE raw_value
  END AS value,
  staleness_band
FROM scored;

COMMENT ON VIEW state_serving IS
  'Serving contract. API MUST read from here, never state_current. Confidence is measured persistence scaled by corroboration; value collapses to unknown when confidence, freshness OR absolute age fails, with the reading preserved in last_known_value.';


-- checkpoint_serving rebuilt from 014 unchanged; it depends on state_serving,
-- which had to be dropped to add the third gate.

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
