-- 033 — a source can be COLLECTED without being BELIEVED.
--
-- P2.5 said the crowd path must be backtested before it affects served values.
-- The same rule obviously applies to any new source, and there was no mechanism
-- for it — a source either wrote `modality='assertion'` and immediately moved
-- belief, or it was not ingested at all.
--
-- WHAT FORCED IT, on 2026-08-02
-- Palhub's road bulletin was added as a 13th checkpoint source: pre-structured,
-- 12 areas, 184 named checkpoints, inbound and outbound stated separately,
-- 6,058 of 6,060 lines parsing exactly. It lifted checkpoint_flow coverage from
-- 23% to 64% in one pass, which is exactly the result that stops people asking
-- questions.
--
-- Then the control was measured, and the control is the whole story:
--
--     channel vs channel, 5-minute window   1,868 / 1,930  = 96.8%
--     palhub  vs channel, 5-minute window      21 /    45  = 46.7%
--
-- The existing road channels agree with each other 96.8% of the time. Palhub
-- agrees with them less than half. Whatever it is describing, it is not what
-- the channels are describing — or the name mapping is wrong in a way that
-- sampling did not reveal. Either way it is not fit to move a value that tells
-- a family whether a road is passable.
--
-- The measurement was only meaningful because of the BASELINE. 46.7% read alone
-- looks like a source with a different threshold for congestion; against 96.8%
-- it is a source that disagrees with reality. A new source must always be
-- judged against how well the existing ones agree with each other, never
-- against perfection.
--
-- WHY QUARANTINE RATHER THAN DELETE
-- The retention rule has no exception for data that turned out to be
-- disappointing, and the 26,162 rows already collected are exactly the corpus
-- needed to work out WHY it disagrees. They stay, queryable, clearly labelled,
-- and structurally incapable of reaching a served value — `resolve/belief.py`
-- counts `modality='assertion'` and nothing else.

-- Re-labelling 26,162 rows spread across compressed chunks needs Timescale to
-- decompress more tuples than one DML transaction allows by default, and the
-- migration aborts halfway with the constraint changed and the rows untouched —
-- which would leave palhub still asserting. Lifted for this transaction only.
SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0;

ALTER TABLE state_observation DROP CONSTRAINT IF EXISTS state_observation_modality_check;
ALTER TABLE state_observation ADD CONSTRAINT state_observation_modality_check
  CHECK (modality IN ('assertion','question','unparsed','rate_limited',
                      'rejected','quarantined'));

COMMENT ON COLUMN state_observation.modality IS
  'assertion = counts toward belief. question/unparsed = recorded, not '
  'believed. rate_limited/rejected = a crowd report the engine would not act '
  'on. quarantined = a source being collected while its accuracy is still '
  'being established — retained in full, never served. The retention rule has '
  'no exception for data we did not like or cannot yet trust.';

-- Quarantine everything palhub-roads has written. Nothing is deleted.
UPDATE state_observation o
   SET modality = 'quarantined'
  FROM source s
 WHERE s.source_id = o.source_id
   AND s.key = 'tg_palhubapproad'
   AND o.modality = 'assertion';
