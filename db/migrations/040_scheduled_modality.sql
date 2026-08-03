-- 040 — a SCHEDULED state is neither an assertion nor a question.
--
-- NEDCO announces electricity cuts in advance. The power module promised to
-- record the announcement whenever found and assert `cut` only inside the
-- window — and kept only the second half: future-window notices were printed
-- and DISCARDED, so `power` sat at zero observations for a week while the
-- scraper found cuts on every run, and nothing could say "a cut is scheduled
-- for Tuesday morning". The announcement gets a modality of its own:
-- excluded from belief exactly like question/quarantined (resolve/belief.py
-- counts only 'assertion'), but present, so discovery is observable and the
-- schedule is servable.
ALTER TABLE state_observation DROP CONSTRAINT IF EXISTS state_observation_modality_check;
ALTER TABLE state_observation ADD CONSTRAINT state_observation_modality_check
  CHECK (modality = ANY (ARRAY['assertion'::text, 'question'::text,
                               'unparsed'::text, 'rate_limited'::text,
                               'rejected'::text, 'quarantined'::text,
                               'scheduled'::text]));
