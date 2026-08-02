-- 023 — remember which source messages have already been ingested.
--
-- THE DEFECT THIS CLOSES
-- ingest/sources/palhub_loader.py reads every *.ndjson in the v1 tee spool and
-- re-inserts every line, on every run, with no cursor. The timer runs every 5
-- minutes and palhub sweeps roughly every 30, so each sweep was written back
-- 6-90 times. Measured:
--
--     fuel rows                774,374
--     unique observations       11,765   (place, kind, time, source, value)
--     pure duplicates          762,609   = 98.48%
--     worst single observation     490 copies
--     distinct telegram msg_ids    432
--
--     non-fuel, same query:    174,965 rows / 174,535 unique = 0.25% dupes
--
-- So this is one loader, not a systemic problem. It is the same shape as the
-- news bug fixed earlier -- an incremental job whose filter did not actually
-- exclude what it had already done -- and it is worth a structural fix rather
-- than a third careful WHERE clause.
--
-- WHY NOT A UNIQUE INDEX ON state_observation
-- That was the first instinct and it is WRONG here. Checked before building:
--
--     672 (place_id, state_kind, source_id, observed_at) keys carry MORE THAN
--     ONE DISTINCT VALUE
--
-- and they are legitimate. Stations that OSM has no coordinates for resolve to
-- their locality centroid, so one sweep can produce several readings for the
-- same place_id at the same instant with genuinely different values. A unique
-- index would have silently dropped real readings to fix a duplication bug --
-- data loss caused by the fix for data bloat.
--
-- WHY THE EXISTING DUPLICATES ARE NOT DELETED HERE
-- "Nothing is deleted or overwritten" is a hard rule, and 762,609 rows is not a
-- rounding error to quietly discard. Migration 022 compresses them ~15x, so
-- they are cheap to keep. Whether to dedupe the history is [ZAID]'s call, not a
-- side effect of a schema migration.

CREATE TABLE IF NOT EXISTS ingest_seen (
  source_id    integer      NOT NULL REFERENCES source(source_id),
  external_id  text         NOT NULL,
  first_seen   timestamptz  NOT NULL DEFAULT now(),
  PRIMARY KEY (source_id, external_id)
);

COMMENT ON TABLE ingest_seen IS
  'One row per source message already ingested. Loaders that re-read an '
  'append-only spool consult this instead of reprocessing from the top. '
  'external_id is the source''s own id (telegram msg_id, RSS guid, ...).';

-- Backfill from what is already in the database, so the fix does not cause one
-- final full reprocess on the next run.
INSERT INTO ingest_seen (source_id, external_id, first_seen)
SELECT source_id, attrs->>'msg_id', min(observed_at)
FROM state_observation
WHERE attrs ? 'msg_id' AND attrs->>'msg_id' IS NOT NULL
GROUP BY source_id, attrs->>'msg_id'
ON CONFLICT DO NOTHING;
