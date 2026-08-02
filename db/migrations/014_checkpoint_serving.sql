-- 014 — one row per (checkpoint, travel direction), with both axes resolved.
--
-- state_serving is keyed by the direction a report was ABOUT. A traveller asks
-- about the direction they are GOING, and the two are not the same question: a
-- report tagged 'both' applies to someone heading inbound, and if it is fresher
-- than the last inbound-specific report it is the better answer. Resolving that
-- in each caller would mean every consumer reimplementing the fallback, and
-- getting it subtly different.
--
-- So this view fans each place out over the two travel directions and picks, per
-- direction, the freshest applicable reading from {that direction, 'both'}.
--
-- It also answers the question people actually ask. "Can I get through?" is not
-- the same as "what is the status?": `congested` is passable, `closed` is not,
-- and `idf` — which v1 returned INSTEAD of a flow value — says nothing either
-- way. passable is derived from the flow axis alone; who is standing there is
-- reported alongside it, never in place of it.
--
-- Unservable places (merged fragments, names that are really sentences — see
-- 013) are excluded here rather than in each caller.

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
