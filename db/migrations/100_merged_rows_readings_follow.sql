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

-- No statement of this file may hold production for long: past five minutes
-- it is cancelled, the transaction rolls back and nothing is changed.
SET LOCAL statement_timeout = '300s';

-- the importers and the belief rebuild wait while readings change rows
SELECT pg_advisory_xact_lock(hashtext('palestine-v2-belief'));

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM place a JOIN place b ON b.place_id = a.merged_into
              WHERE b.merged_into IS NOT NULL)
  THEN RAISE EXCEPTION '100: a merged row points at a merged row'; END IF;
END $$;

-- HOW IT IS WRITTEN, AND WHY (the first form of this file stalled production).
-- The twin search was one statement joining the hypertable to itself. On two
-- throwaway copies, one of them the full 2.1 M rows, it took 4 to 7 seconds:
-- their freshly gathered statistics gave a hash join. Production's planner
-- expected ONE row from the surviving side, got about 300,000, and probed
-- every chunk once for each. It ran for more than ten minutes holding the
-- belief lock, with the road importers waiting behind it (2026-10-12, from
-- 17:02 UTC). Nothing was changed: the file is one transaction. A rehearsal
-- copy proves the rows; it does not prove the plan. So:
--   * each side is read ONCE into a temporary table and the tables are joined,
--     which leaves the planner nothing to choose. This form was timed
--     read-only ON PRODUCTION: 2.5 s (30,295 readings on merged rows, 201,991
--     statements on surviving rows, 5,705 twins, 49 repeats between two
--     merged rows of one place);
--   * each merged row is updated by its own statement with its place_id as a
--     constant (production's plan for one: an anti join over one place's
--     segments);
--   * no statement may run past five minutes (statement_timeout above).
-- At full size on a compressed copy the whole file takes 5 s and its
-- rollback 2 s.
CREATE TEMP TABLE lo100 ON COMMIT DROP AS
SELECT o.state_obs_id, o.observed_at, o.place_id AS loser, p.merged_into AS survivor,
       o.state_kind, o.direction, o.source_id
  FROM place p JOIN state_observation o ON o.place_id = p.place_id
 WHERE p.merged_into IS NOT NULL;
ANALYZE lo100;

CREATE TEMP TABLE su100 ON COMMIT DROP AS
SELECT DISTINCT t.place_id, t.state_kind, t.direction, t.source_id, t.observed_at
  FROM state_observation t
 WHERE t.place_id = ANY (ARRAY(SELECT DISTINCT survivor FROM lo100));
ANALYZE su100;

-- the readings the surviving row already holds
CREATE TEMP TABLE twin100 ON COMMIT DROP AS
SELECT l.state_obs_id, l.observed_at
  FROM lo100 l JOIN su100 s
    ON s.place_id = l.survivor AND s.state_kind = l.state_kind
   AND s.direction = l.direction AND s.source_id = l.source_id
   AND s.observed_at = l.observed_at;

-- Two merged rows of one surviving row can also hold the same statement
-- (الكونتينر was held seven times). The first by id moves, the rest stay.
INSERT INTO twin100
SELECT state_obs_id, observed_at FROM (
  SELECT l.state_obs_id, l.observed_at,
         row_number() OVER (PARTITION BY l.survivor, l.state_kind, l.direction,
                                         l.source_id, l.observed_at
                            ORDER BY l.state_obs_id) AS k
    FROM lo100 l
   WHERE NOT EXISTS (SELECT 1 FROM twin100 w
                      WHERE w.state_obs_id = l.state_obs_id
                        AND w.observed_at = l.observed_at)) x
 WHERE k > 1;
ANALYZE twin100;

-- One UPDATE per merged row, with its place_id written as a constant: the
-- compressed chunks are segmented by place_id, and a constant is what lets
-- TimescaleDB open only that row's segments instead of every chunk whole.
DO $$
DECLARE r record; n bigint; moved bigint := 0;
BEGIN
  FOR r IN SELECT loser, survivor, count(*) AS readings FROM lo100 GROUP BY 1, 2 ORDER BY 1 LOOP
    EXECUTE format($f$
      UPDATE state_observation o
         SET place_id = %s,
             attrs = COALESCE(o.attrs, '{}'::jsonb) || jsonb_build_object('place_before_100', o.place_id)
       WHERE o.place_id = %s
         AND NOT EXISTS (SELECT 1 FROM twin100 w
                          WHERE w.state_obs_id = o.state_obs_id
                            AND w.observed_at = o.observed_at)$f$, r.survivor, r.loser);
    GET DIAGNOSTICS n = ROW_COUNT;
    moved := moved + n;
  END LOOP;
  RAISE NOTICE '100: % readings moved to their surviving row', moved;
  IF moved <> (SELECT count(*) FROM lo100) - (SELECT count(*) FROM twin100) THEN
    RAISE EXCEPTION '100: moved % readings, expected % — nothing is changed',
      moved, (SELECT count(*) FROM lo100) - (SELECT count(*) FROM twin100);
  END IF;
END $$;

DELETE FROM state_current sc USING place p
 WHERE p.place_id = sc.place_id AND p.merged_into IS NOT NULL;
DELETE FROM place_state_cadence c USING place p
 WHERE p.place_id = c.place_id AND p.merged_into IS NOT NULL;
DELETE FROM source_place_trust t USING place p
 WHERE p.place_id = t.place_id AND p.merged_into IS NOT NULL;

COMMENT ON COLUMN place.merged_into IS
  'Fragment/variant pointer to the canonical place. Observations are re-pointed at the canonical (100 finished what 082 and 097 left); a reading stays on the merged row only where the canonical already holds the same statement. The row is kept so its spelling still resolves.';
