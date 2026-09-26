-- 088 — the nightly rollup supersedes instead of overwriting (audit DATABANK-V15, F142).
--
-- ops/rollup.py re-rolls the last two days every night (so a missed night is caught) and wrote with
-- ON CONFLICT ... DO UPDATE SET value_num: the one mutable path into the databank table. Measured
-- 2026-09-26: 12,133 of the last ten days' 13,697 tier1_daily rows were rewritten a day or more after
-- the day they count, and `observation` has no versioning trigger, so any count a re-roll changed (a
-- poller recovering a backlog, v1's cursor re-reading behind itself) lost its earlier value — as_of
-- yesterday could return a number that did not exist yesterday.
--
-- The unique index now holds CURRENT rows only (as 052/061 do for the identity and stable-id keys), so a
-- changed count closes the old row and inserts the new one; an unchanged count touches nothing. The code
-- (ops/rollup.py) switches to superseding when it sees this index, and keeps its old update until then.
--
-- Rollback (possible only while no closed rollup row shares a key with a current one):
--   CREATE UNIQUE INDEX observation_rollup_uniq ON observation (dataset_id, place_id, indicator, occurred_at)
--     WHERE place_id IS NOT NULL AND v1_stable_id IS NULL;
--   DROP INDEX observation_rollup_uniq_current;

CREATE UNIQUE INDEX IF NOT EXISTS observation_rollup_uniq_current
    ON observation (dataset_id, place_id, indicator, occurred_at)
 WHERE place_id IS NOT NULL AND v1_stable_id IS NULL AND upper(sys_period) IS NULL;

DROP INDEX IF EXISTS observation_rollup_uniq;
