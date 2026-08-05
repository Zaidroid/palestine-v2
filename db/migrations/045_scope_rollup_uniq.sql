-- 045 — the rollup uniqueness index learns it does not govern migrated rows
--
-- T2.3 pilot finding. 031's observation_rollup_uniq assumes one row per
-- (dataset, place, indicator, occurred_at) — true for tier-1 daily rollups
-- and the MoH series, where the writer produces exactly one row per place
-- per day. False for migrated locality AGGREGATES: demolitions has 85 East
-- Jerusalem localities that all resolve to the Jerusalem governorate place
-- with the same coverage-anchor date, and the first real run collided.
--
-- The two index predicates now partition the table exactly:
--   v1_stable_id IS NULL      → observation_rollup_uniq   (live writers)
--   v1_stable_id IS NOT NULL  → observation_v1_stable_uniq (migration, 044)
-- ops/rollup.py and ingest/sources/moh_gaza.py carry the matching predicate
-- in their ON CONFLICT clauses.

DROP INDEX IF EXISTS observation_rollup_uniq;
CREATE UNIQUE INDEX observation_rollup_uniq
    ON observation (dataset_id, place_id, indicator, occurred_at)
    WHERE place_id IS NOT NULL AND v1_stable_id IS NULL;
