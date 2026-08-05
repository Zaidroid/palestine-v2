-- 046 — migrated events get the idempotency the observation table already has
--
-- T2.3 Batch C. `event` has no v1_stable_id column (its rows normally come
-- from claim clustering, which has its own identity), so migrated events
-- carry theirs in attrs and this expression index makes re-runs write zero.
-- event is not a hypertable, so no partition-column constraint applies.

CREATE UNIQUE INDEX IF NOT EXISTS event_v1_stable_uniq
    ON event ((attrs->>'v1_stable_id'))
    WHERE attrs ? 'v1_stable_id';
