-- 037 — which sources are NEWS, declared once.
--
-- Adding @palhubappfuel to the poller (P8, for the fuel cards) pushed 11,730
-- claims into the incident classifier, which had no source filter at all. 390
-- of them came out classified as INCIDENTS — more than any real news channel
-- in the system, the busiest of which produces 154.
--
-- They are not incidents. They are machine-generated fuel-station bulletins
-- ("جميع محطات المدينة مغلقة") and card captions, and the word مغلقة means a
-- petrol station is shut, not that a road was closed by anybody.
--
-- The classifier was never wrong to read what it was given. It was given the
-- wrong input, because "is this a news channel" was implicit in which channels
-- happened to exist rather than recorded anywhere. So it becomes a column: a
-- new source cannot be added without answering the question, and the answer
-- lives next to the source rather than in the shape of the channel list.
--
-- Same reasoning as 035's place_kind, and the third time this pattern has paid:
-- a rule that lives only in "which rows happen to be there" is a rule that
-- silently stops holding the moment somebody adds a row.

ALTER TABLE source
  ADD COLUMN IF NOT EXISTS feeds_incidents boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN source.feeds_incidents IS
  'Whether this source''s claims are read by the incident classifier. FALSE for '
  'machine-generated status feeds — a fuel bulletin saying stations are مغلقة '
  'is fuel data, and read as news it becomes a road closure that never '
  'happened. Default true so a normal news channel needs no ceremony; the '
  'exceptions are the ones that must be stated.';

-- The status feeds. All three are palhub's own machine output, in two forms:
-- the tee-spool loader's source and the poller's, which are the same channel.
UPDATE source SET feeds_incidents = false
 WHERE key IN ('tg_palhubappfuel', 'tg_palhubapproad', 'telegram_fuel');

-- Remove what the classifier produced from those sources. This is NOT a
-- retention exception: `claim_classification` is DERIVED and recomputable, and
-- every underlying `claim` row stays exactly where it is. What is deleted is a
-- conclusion we now know to be wrong, not evidence — the same distinction that
-- lets a belief be retracted while the observation behind it is kept forever.
DELETE FROM claim_classification cc
 USING claim c, source s
 WHERE cc.claim_id = c.claim_id
   AND s.source_id = c.source_id
   AND s.feeds_incidents = false;
