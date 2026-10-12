-- 100 — the readings of a merged row follow it to the surviving row (2026-10-12).
--
-- `place.merged_into` promises it in its own comment: "Observations are
-- re-pointed at the canonical; the row is kept so its spelling still resolves."
-- 013 and 039 did that for every reading. 082 (20 rows) and 097 (19 rows) moved
-- only the last two days, on the grounds that "the resolver and the serving
-- views follow merged_into for history". The daily rollup does (since
-- 2026-10-11). Two served answers do not: the hourly pattern of a checkpoint
-- (serve/app.py PATTERN_SQL) and the area window behind `insights` read
-- state_observation by the row the place is now. Neither do the learners
-- (learn/place_trust, learn/state_persistence, learn/reliability).
--
-- Measured 2026-10-12 16:10 UTC: 30,295 readings (23,292 assertions) still sit
-- on 30 of those 39 merged rows, from 2026-06-09 to 2026-10-09. الكونتينر has
-- 5,140 assertions under its duplicate 1736 against 6,594 on its own row; ام
-- السلمونا has 277 on its own row and 978 assertions (3,907 readings) under
-- 1761; بوابة النبي صالح 2,188 assertions under 1658.
--
-- WHAT MOVES. A reading moves to the surviving row unless that row already
-- holds a reading from the same source, at the same moment, for the same kind
-- and direction. Those (the board and some channel lines named the place twice
-- in one message) stay where they are: moving them would put the same
-- statement on the row twice. The rollup already counts each statement once
-- either way.
--
-- Beliefs, cadence and trust rows on merged rows are derived; they are removed
-- here and rebuilt on the surviving row by
--   .venv/bin/python -m ingest.sources.checkpoints --state-only
--   bash ops/learn-checkpoints.sh          (nightly; cadence and trust by place)
--
-- The place a reading was filed under is kept on the row as
-- attrs.place_before_100 (its own key, so the rollbacks of 082 and 097, which
-- read attrs.moved_by, still find their rows).
--
-- Rollback (exact):
--   SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;
--   UPDATE state_observation
--      SET place_id = (attrs->>'place_before_100')::bigint,
--          attrs = attrs - 'place_before_100'
--    WHERE attrs ? 'place_before_100';
--   then --state-only and the learners, as above.

SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;

-- the importers and the belief rebuild wait while readings change rows
SELECT pg_advisory_xact_lock(hashtext('palestine-v2-belief'));

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM place a JOIN place b ON b.place_id = a.merged_into
              WHERE b.merged_into IS NOT NULL)
  THEN RAISE EXCEPTION '100: a merged row points at a merged row'; END IF;
END $$;

-- The readings that have a twin on the surviving row, found once (the UPDATE
-- below would otherwise see its own moved rows as twins of each other).
CREATE TEMP TABLE twin100 ON COMMIT DROP AS
SELECT o.state_obs_id, o.observed_at
  FROM state_observation o
  JOIN place p ON p.place_id = o.place_id AND p.merged_into IS NOT NULL
 WHERE EXISTS (SELECT 1 FROM state_observation t
                WHERE t.place_id = p.merged_into
                  AND t.state_kind = o.state_kind AND t.direction = o.direction
                  AND t.source_id = o.source_id AND t.observed_at = o.observed_at);

-- Two merged rows of one surviving row can also hold the same statement
-- (الكونتينر was held seven times). The first by id moves, the rest stay.
INSERT INTO twin100
SELECT state_obs_id, observed_at FROM (
  SELECT o.state_obs_id, o.observed_at,
         row_number() OVER (PARTITION BY p.merged_into, o.state_kind, o.direction,
                                         o.source_id, o.observed_at
                            ORDER BY o.state_obs_id) AS k
    FROM state_observation o
    JOIN place p ON p.place_id = o.place_id AND p.merged_into IS NOT NULL
   WHERE NOT EXISTS (SELECT 1 FROM twin100 w
                      WHERE w.state_obs_id = o.state_obs_id
                        AND w.observed_at = o.observed_at)) x
 WHERE k > 1;

UPDATE state_observation o
   SET place_id = p.merged_into,
       attrs = COALESCE(o.attrs, '{}'::jsonb)
             || jsonb_build_object('place_before_100', o.place_id)
  FROM place p
 WHERE p.place_id = o.place_id AND p.merged_into IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM twin100 w
                    WHERE w.state_obs_id = o.state_obs_id
                      AND w.observed_at = o.observed_at);

DELETE FROM state_current sc USING place p
 WHERE p.place_id = sc.place_id AND p.merged_into IS NOT NULL;
DELETE FROM place_state_cadence c USING place p
 WHERE p.place_id = c.place_id AND p.merged_into IS NOT NULL;
DELETE FROM source_place_trust t USING place p
 WHERE p.place_id = t.place_id AND p.merged_into IS NOT NULL;

COMMENT ON COLUMN place.merged_into IS
  'Fragment/variant pointer to the canonical place. Observations are re-pointed at the canonical (100 finished what 082 and 097 left); a reading stays on the merged row only where the canonical already holds the same statement. The row is kept so its spelling still resolves.';
