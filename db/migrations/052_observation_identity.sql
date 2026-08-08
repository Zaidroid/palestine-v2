-- 052 — identity becomes a column, and the DATABASE refuses a re-insert.
--
-- WHY A COLUMN AND NOT A COMPUTED COMPARISON
-- The loader's first identity guard (2026-08-07) computed each row's key in
-- Python and compared it against the same key rendered in SQL. Those two
-- renderings are not equal: Python writes 106.0 where numeric::text writes
-- 106, and str(datetime) writes '+00:00' where timestamptz::text writes '+00'.
-- Every mismatch reads as "not held yet", so the guard silently FAILS OPEN and
-- re-inserts — which is the exact bug it was written to stop. Measured on
-- connectivity: 998 of 1,000 rows would have been written a second time.
--
-- Storing the key removes the second renderer. It is computed once, in one
-- place (ingest/databank.py identity_key_for), written on insert, and read
-- back verbatim.
--
-- WHY THE PREDICATE IS SHAPED THIS WAY
--   identity_key IS NOT NULL  — tier-1 live rows have no declared identity
--                               and must not be constrained by this index.
--   upper(sys_period) IS NULL — uniqueness applies to CURRENT rows only, so
--                               supersedence still works and the no-data-loss
--                               rule is untouched: a corrected row closes the
--                               old one's validity instead of deleting it.
--   occurred_at included      — a hypertable's unique index must contain the
--                               partition column (the same reason 044 has it).
--
-- WHAT THIS CHANGES ABOUT FAILURE
-- Before: a lossy identity froze a dataset silently and the run reported
-- success (infrastructure sat at 5,840 rows / 4 keys for a day). After: the
-- second insert raises, loudly, on the first run that hits it.

ALTER TABLE observation ADD COLUMN IF NOT EXISTS identity_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS observation_identity_uniq
    ON observation (dataset_id, identity_key, occurred_at)
    WHERE identity_key IS NOT NULL AND upper(sys_period) IS NULL;

COMMENT ON COLUMN observation.identity_key IS
    'Declared natural key from the spec''s identity: block — what makes this '
    'row THIS row, independent of v1''s content-hashed stable_id. Computed by '
    'ingest.databank.identity_key_for; NULL for tier-1 live rows.';
