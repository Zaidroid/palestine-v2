-- 025 — presence stops being served as a STATE. It is a sighting.
--
-- P1.3 asked whether the 2-hour cap on presence was wrong, or whether presence
-- is too sparse to be a product feature. Measured, it is neither of those, and
-- the first answer was wrong for a reason worth writing down.
--
-- WHAT WAS ACTUALLY BROKEN FIRST
-- `checkpoint_idf` had exactly ONE value in 6,226 observations: `present`.
-- cascade/checkpoint_text.py discarded negated presence outright — "ما في جيش",
-- "بدون جيش" — so the only statements of absence anybody ever makes were thrown
-- away. Measured across the 94,622-line corpus: 1,752 of 6,188 presence
-- mentions are negated, 28.31%.
--
-- A single-valued state cannot be wrong, cannot be contradicted, and cannot
-- decay: the persistence fit returned 1.00 at EVERY lag, which looked like a
-- beautifully stable signal and was an artifact of there being nothing else to
-- report. That is the same trap as `open`'s flat tail being the base rate, and
-- as kappa being undefined when only one value was ever seen.
--
-- Absence is now recorded (1,948 `absent` for idf), and only then could the
-- real curve be measured:
--
--     checkpoint_idf present   0.94@5m -> 0.69@60m   half-life  15 min
--     checkpoint_idf absent    0.94@5m -> 0.74@120m  half-life  60 min
--
-- WHY IT STILL CANNOT BE A STATE
-- A patrol has a FIFTEEN MINUTE half-life. Presence reports arrive for a given
-- place every 34.7 hours (idf), 58.4 (police), 115.0 (settlers). That is a
-- ~140x mismatch between how fast the fact decays and how often anybody looks.
-- No cap setting fixes it: the honest answer to "is the army at Huwara now?"
-- is almost always "nobody has looked recently", and 99% `unknown` is the
-- system correctly saying so.
--
-- Loosening the cap would make the coverage number look better by asserting
-- 30-hour-old patrol sightings as current. The plan explicitly forbade that,
-- and the measurement is why.
--
-- WHAT IT IS INSTEAD
-- A timestamped sighting. "IDF reported at Huwara 25 minutes ago" is true,
-- useful, and never expires into a lie, because the age is part of the claim
-- rather than a caveat attached to it. Consumers must read `last_known_value`
-- WITH `age_minutes` and must not read `value` as a current state.
--
-- Nothing is deleted and nothing stops being collected: 8,238 presence and
-- absence observations remain, they still contradict each other through the
-- ordinary corroboration path, and they remain available as attributes of an
-- incident. Only the claim that they describe the PRESENT is withdrawn.

ALTER TABLE state_kind_config
  ADD COLUMN IF NOT EXISTS serving_mode text NOT NULL DEFAULT 'state'
  CHECK (serving_mode IN ('state', 'sighting'));

COMMENT ON COLUMN state_kind_config.serving_mode IS
  'state = the value describes now, gated by confidence/staleness/max_assert. '
  'sighting = the value describes a moment that was OBSERVED; read it with '
  'age_minutes and never as current. Presence kinds are sightings because a '
  'patrol has a 15-minute half-life and is reported every 34+ hours.';

UPDATE state_kind_config SET serving_mode = 'sighting'
WHERE state_kind IN ('checkpoint_idf', 'checkpoint_police',
                     'checkpoint_settlers', 'checkpoint_inspection');

-- The cap now reflects the measured half-life instead of a round guess. This
-- TIGHTENS idf from 2h to 45min (3 half-lives, persistence ~0.69 by then).
-- Tightening toward a measurement is the opposite of the thing the plan
-- forbade; it asserts less, not more.
UPDATE state_kind_config SET max_assert_seconds = 2700, half_life_seconds = 900,
  note = 'Army present/absent. 15-min half-life MEASURED (P1.3); served as a '
         'SIGHTING, not a state — reports arrive every ~35h.'
WHERE state_kind = 'checkpoint_idf';

-- police, settlers and inspection could NOT be fitted — 18, 1 and 21 absence
-- pairs respectively. They keep the conservative default and say so, rather
-- than borrowing idf's curve on the assumption that a police car behaves like
-- a patrol.
UPDATE state_kind_config
SET note = note || ' Persistence UNFITTED (too few pairs); served as a sighting.'
WHERE state_kind IN ('checkpoint_police', 'checkpoint_settlers',
                     'checkpoint_inspection');
