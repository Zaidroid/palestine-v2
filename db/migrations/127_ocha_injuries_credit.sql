-- 127 · OCHA's injuries are credited as injuries (2026-10-15)
--
-- The injuries by month (126) inherit the source row ocha_casualties, whose credit was written for the deaths:
-- every injuries answer read "Palestinian fatalities: UN OCHA oPt, Protection of Civilians database." (asked
-- through the partner door after command 37). The dataset carries its own credit line instead, as other datasets
-- do (054: NULL inherits the source). The deaths keep theirs; no grade changes.
--
-- Rollback: UPDATE dataset SET attribution_text = NULL WHERE key = 'ocha_injuries_monthly';

UPDATE dataset
   SET attribution_text = 'Palestinian injuries: UN OCHA oPt, Protection of Civilians database.'
 WHERE key = 'ocha_injuries_monthly'
   AND attribution_text IS NULL;
