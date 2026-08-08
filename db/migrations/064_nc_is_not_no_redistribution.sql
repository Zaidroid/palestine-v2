-- 064 — "non-commercial" is not "do not redistribute"
--
-- My own bug, from 053, found 2026-08-08 while measuring what skipping the
-- licence letters would cost.
--
-- 053 graded the whole -NC- family as `no-redistribution`, on the reasoning
-- that the NC half always wins over the SA half. The first part of that is
-- right; the conclusion is wrong. CC-BY-NC does not forbid redistribution —
-- it forbids COMMERCIAL redistribution, and expressly permits the
-- non-commercial kind with attribution. That is precisely what this databank
-- is: free, public, credited, not for sale.
--
-- The effect of the mistake was to label 13,577 perfectly servable rows as
-- forbidden — WHO's 12,577 (CC-BY-NC-SA-3.0-IGO) and IODA's 1,000
-- (CC-BY-NC-4.0) — while `commercial_use = false` was already doing the
-- actual work of keeping them out of every commercial tier.
--
-- Two columns, two questions, and 053 answered the second with the first:
--   commercial_use  = false   may we SELL it?          no
--   redistribution  = ...     may we SHARE it at all?  yes, with credit
--
-- WHAT IS NOT CHANGED, deliberately: UN-ToU-NC stays `no-redistribution`,
-- because OCHA's terms do not merely say non-commercial — they say
-- "without any right to resell or redistribute", in those words (050's
-- evidence). A family-wide rule cannot see that distinction; only reading
-- the terms can, which is the argument for terms_evidence being a column.

UPDATE source SET redistribution = 'attribution'
 WHERE (license_spdx LIKE 'CC-BY-NC%')
   AND redistribution = 'no-redistribution';

-- Belt and braces: whatever the grade says, an NC source is never sellable.
UPDATE source SET commercial_use = false
 WHERE license_spdx LIKE '%-NC-%' OR license_spdx LIKE '%-NC';
