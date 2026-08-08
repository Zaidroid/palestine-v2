-- 061 — a superseded row must not block its own correction
--
-- Found 2026-08-08 while repairing four West Bank figures that had been
-- stored inside the Gaza cumulative series. The sanctioned correction
-- mechanism in this project is SUPERSEDE, NEVER DELETE: close the wrong
-- row's validity, let the loader write the right one, keep both readable at
-- their own as_of. That mechanism did not work, and had never worked for a
-- migrated row.
--
-- 044's index:
--     UNIQUE (dataset_id, v1_stable_id, occurred_at)
--     WHERE v1_stable_id IS NOT NULL
--
-- No validity predicate. So a superseded row goes on occupying the slot, the
-- corrected row hits ON CONFLICT DO NOTHING, and the run reports `written 0`
-- — success, with the correction silently discarded. The old value stays
-- closed and the new value never arrives, which is strictly worse than
-- having done nothing: the fact disappears from the current surface
-- entirely.
--
-- 052 got this right for identity_key three days ago (`AND upper(sys_period)
-- IS NULL`) because that index was written after supersedence existed. 044
-- predates it.
--
-- The predicate does not weaken idempotency. What 044 exists to prevent is
-- the SAME FACT being served twice, and that is a property of the CURRENT
-- generation; a superseded row is history, and history is allowed to repeat
-- a stable_id across generations. Indeed it must: without this, a source
-- that re-publishes a value we once corrected can never restate it, which is
-- the same silent freeze Stage 2 spent a day removing.

DROP INDEX IF EXISTS observation_v1_stable_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS observation_v1_stable_uniq
    ON observation (dataset_id, v1_stable_id, occurred_at)
    WHERE v1_stable_id IS NOT NULL AND upper(sys_period) IS NULL;

COMMENT ON INDEX observation_v1_stable_uniq IS
  'One CURRENT row per (dataset, v1 stable id, date). The validity predicate '
  'added by 061: without it a superseded row blocks its own correction and '
  'the fact vanishes from the current surface while the run reports success.';

-- The event table has the same latent bug (046). Fixed here rather than
-- waiting for it to cost something.
--
-- 046's KEY IS PRESERVED EXACTLY — the expression alone, with no
-- occurred_at. `event` is not a hypertable (its primary key is event_id
-- alone), so the partition column that 044 must carry is not required here,
-- and adding it would WEAKEN the constraint: one v1_stable_id could then
-- exist once per date instead of once. The first draft of this migration did
-- exactly that. Only the validity predicate is new.
DROP INDEX IF EXISTS event_v1_stable_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS event_v1_stable_uniq
    ON event ((attrs->>'v1_stable_id'))
    WHERE attrs ? 'v1_stable_id' AND upper(sys_period) IS NULL;
