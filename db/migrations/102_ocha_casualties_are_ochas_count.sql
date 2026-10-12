-- 102 — OCHA's casualty figures are credited to OCHA (2026-10-12).
--
-- Every row of v1_casualties_ocha_casualties is served with the attribution
-- "Palestinian fatalities: UN OCHA oPt, sourced from B'Tselem." The label came
-- from v1 (organization "UN OCHA (B'Tselem data)") and was carried through 042.
-- OCHA's own page for the report this dataset reads says whose count it is
-- (https://www.ochaopt.org/data/casualties, read 2026-10-12):
--   "Information about occupation and conflict-related casualties is regularly
--    collected by OCHA field staff and entered into OCHA's Protection of
--    Civilians database, following review and verification. As a rule, for an
--    incident to be entered into the database it needs to be validated by at
--    least two independent and reliable sources."
-- The page does not name B'Tselem. B'Tselem's own fatalities file is a
-- different dataset here (btselem_fatalities, a frozen copy awaiting consent).
--
-- The licence, the grade and the terms evidence do not change: UN terms of use,
-- no redistribution. Only the credit line does. The serve warnings of the same
-- dataset are declared in db/mappings/casualties.yaml and written by
-- `ops.load_registry --apply`.
--
-- Rollback (exact):
--   UPDATE source SET attribution_text = 'Palestinian fatalities: UN OCHA oPt, sourced from B''Tselem.'
--    WHERE key = 'ocha_casualties';

UPDATE source
   SET attribution_text = 'Palestinian fatalities: UN OCHA oPt, Protection of Civilians database.'
 WHERE key = 'ocha_casualties'
   AND attribution_text = 'Palestinian fatalities: UN OCHA oPt, sourced from B''Tselem.';
