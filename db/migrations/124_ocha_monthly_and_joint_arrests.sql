-- 124 · two datasets of sources already held (2026-10-14; Zaid: "do 2 and whatever ready from 3")
--
-- ocha_fatalities_monthly  OCHA oPt's casualty report, read through its incident table into monthly series
--                          (db/mappings/ocha_monthly.yaml). Source row ocha_casualties: OCHA's terms of use,
--                          non-commercial, no redistribution (graded in 042), as the totals it already serves.
-- arrests_joint_monthly    the prisoner institutions' joint monthly report, January 2016 to January 2024
--                          (db/mappings/arrests_joint.yaml). Source row addameer: "All rights reserved",
--                          no-redistribution, as the prisoner statistics.
-- No licence is decided here: both take the grade their source already has.
--
-- Rollback: DELETE FROM dataset WHERE key IN ('ocha_fatalities_monthly', 'arrests_joint_monthly') AND NOT EXISTS
--             (SELECT 1 FROM observation o WHERE o.dataset_id = dataset.dataset_id);

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'ocha_fatalities_monthly', 'OCHA oPt — Palestinians killed by Israelis, by month, area, perpetrator, age and governorate',
       s.source_id, 'casualties', 'daily', true,
       jsonb_build_object('publisher_window_from', '2008-01-01',
         'not_a_continuation_of', jsonb_build_array('v1_casualties_ocha_casualties'),
         'scope_note', 'Counted by month from the casualty report''s incident table (names never read). Gaza''s dead since 7 October 2023 are not in OCHA''s record.')
  FROM source s WHERE s.key = 'ocha_casualties'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'ocha_fatalities_monthly');

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'arrests_joint_monthly', 'Palestinian prisoner institutions — arrests and administrative orders by month (joint report)',
       s.source_id, 'prisoners', 'irregular', true,
       jsonb_build_object('publisher_window_from', '2016-01-01',
         'scope_note', 'The joint monthly report''s lead sentence: arrests, children, women, Jerusalem, administrative orders (new, renewed), January 2016 to January 2024 as Addameer indexes it; West Bank only from October 2023. Year, half-year and two-month reports are not read as months.')
  FROM source s WHERE s.key = 'addameer'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'arrests_joint_monthly');
