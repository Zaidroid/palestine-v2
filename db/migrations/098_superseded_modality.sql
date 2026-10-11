-- 098 — `superseded`: a fact the reader no longer reads from its own line (2026-10-11).
--
-- The road line reader changed on 2026-10-11 (questions that had been asserted,
-- "closed tomorrow" served as closed today, the checkpoint noun, forms by stem).
-- The messages since 31 July were re-read by v2's own reader, which wrote what
-- was MISSING. What that could not do is take back a fact the importer wrote
-- under an older reading. Measured on 2026-10-11 over the 253,326 stored lines:
-- 561 questions and 191 non-reports ("closed tomorrow", opening hours) still
-- stand as assertions, 2,598 stored facts are no longer what their line reads
-- (army "present" on «بدون جيش», a direction bound the wrong way, a closure read
-- off an emoji), and 3,852 lines the reader can now read carry no fact, 1,386
-- of them from before 31 July, where no raw message exists to re-read.
--
-- Nothing is deleted. `ingest.sources.checkpoints --reread` reads every stored
-- line again and, where the reading differs, marks the old fact `superseded`
-- (what it was is kept on the row: attrs.modality_before, attrs.superseded_by)
-- and writes the new one. Belief, the daily rollup and the learners count only
-- 'assertion', so a superseded fact stops being evidence everywhere at once and
-- stays readable as history.
--
-- Rollback (exact):
--   UPDATE state_observation SET modality = attrs->>'modality_before',
--          attrs = attrs - 'modality_before' - 'superseded_by'
--    WHERE modality = 'superseded';
--   UPDATE state_observation SET modality = attrs->>'modality_before_reread',
--          attrs = attrs - 'modality_before_reread' - 'reread'
--    WHERE attrs ? 'modality_before_reread';
--   DELETE FROM state_observation WHERE attrs ? 'written_by_reread';
--   then re-create the constraint without 'superseded'.
ALTER TABLE state_observation DROP CONSTRAINT IF EXISTS state_observation_modality_check;
ALTER TABLE state_observation ADD CONSTRAINT state_observation_modality_check
  CHECK (modality = ANY (ARRAY['assertion'::text, 'question'::text,
                               'unparsed'::text, 'rate_limited'::text,
                               'rejected'::text, 'quarantined'::text,
                               'scheduled'::text, 'superseded'::text]));

COMMENT ON COLUMN state_observation.modality IS
  'assertion: evidence. question / unparsed: kept, not evidence. quarantined: collected, '
  'not yet trusted. scheduled: announced for later. rate_limited / rejected: the crowd '
  'gate. superseded: was an assertion under an older reading of its own line; what it '
  'was is in attrs.modality_before (098).';
