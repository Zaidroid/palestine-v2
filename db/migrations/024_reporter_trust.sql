-- 024 — record what Loop A measured, and the weight actually used for it.
--
-- `source.reliability` has existed since migration 003 with the instruction
-- "NULL until measured — never seed by hand". It was never measured. Loop A
-- (learn/reliability.py) now measures it, and it needs two more columns because
-- the posterior MEAN is not the number that should be used.
--
--   reliability        posterior mean of Beta(1+hits, 1+misses)   [003]
--   reliability_n      how much evidence is behind it             [003]
--   reliability_trust  LOWER BOUND of the interval  <- new
--   trust_weight       that bound, normalised to an established
--                      reporter; this is what multiplies confidence  <- new
--
-- WHY THE LOWER BOUND AND NOT THE MEAN
-- This is what makes reputation EARNED rather than seeded, with no rule that
-- says so. One correct report out of one has a posterior mean of 0.67 but a
-- lower bound of 0.21; ninety out of a hundred has a mean of 0.89 and a bound
-- of 0.82. A brand-new reporter is therefore cautious automatically, and climbs
-- only by being repeatedly right about things others independently confirm.
-- P2.3 requires exactly this behaviour for crowd submitters and now gets it for
-- free, because nothing in the loop knows whether a reporter is a Telegram
-- channel or a person with a phone.
--
-- WHY A SEPARATE trust_weight AND NOT A FORMULA IN SQL
-- The Wilson bound would then exist twice, in Python and in SQL, and this
-- project has already been bitten by two implementations of one rule drifting
-- apart — which is why the serving gates live in SQL and are never duplicated.
-- One writer, one formula, SQL only reads.
--
-- NULL MEANS UNMEASURED AND MUST BEHAVE AS IT DID BEFORE. 27 of 42 sources
-- produce claims rather than state observations and cannot be scored this way
-- at all; every consumer coalesces a NULL weight to 1.0 so an unmeasured source
-- keeps exactly the confidence it had before this migration.

ALTER TABLE source ADD COLUMN IF NOT EXISTS reliability_trust real;
ALTER TABLE source ADD COLUMN IF NOT EXISTS trust_weight real;

COMMENT ON COLUMN source.reliability_trust IS
  'Lower bound of the 95% interval on reliability. Written by learn/reliability.py. '
  'Use this, not reliability — it is what makes a new reporter start cautious.';
COMMENT ON COLUMN source.trust_weight IS
  'reliability_trust normalised against an established reporter, clamped to '
  '(0,1]. Multiplies single-unit base confidence. NULL = unmeasured = 1.0.';

ALTER TABLE source ADD CONSTRAINT source_trust_weight_range
  CHECK (trust_weight IS NULL OR (trust_weight > 0 AND trust_weight <= 1));
