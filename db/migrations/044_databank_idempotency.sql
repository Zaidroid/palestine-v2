-- 044 — migrated rows get a real idempotency constraint
--
-- T2.3. 007 reserved v1_stable_id with only an INDEX, so nothing in the
-- schema stopped a re-run from writing every migrated observation twice
-- (health alone is 69% byte-duplicates upstream — the loader dedupes, and
-- this constraint is what makes "the loader dedupes" a property of the
-- database rather than a promise). occurred_at is in the key because unique
-- indexes on a hypertable must include the partition column.
--
-- Fan-out rows (one v1 record → several observations) carry a suffixed
-- stable id ('<stable_id>:<segment>'), so uniqueness holds per emitted row.

CREATE UNIQUE INDEX IF NOT EXISTS observation_v1_stable_uniq
    ON observation (dataset_id, v1_stable_id, occurred_at)
    WHERE v1_stable_id IS NOT NULL;
