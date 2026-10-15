-- 126 · OCHA's injuries by month (2026-10-15)
--
-- ocha_injuries_monthly  OCHA oPt's record of Palestinians injured by Israelis, read through the casualty page's
--                        "Palestinian injuries" report into monthly series (db/mappings/ocha_injuries.yaml): by area,
--                        perpetrator, age and governorate, January 2008 on (167,092 injured, measured 2026-10-15).
--                        Source row ocha_casualties: OCHA's terms of use, non-commercial, no redistribution (graded in
--                        042), as the deaths by month (124). No licence is decided here.
--
-- Rollback: DELETE FROM dataset WHERE key = 'ocha_injuries_monthly' AND NOT EXISTS
--             (SELECT 1 FROM observation o WHERE o.dataset_id = dataset.dataset_id);

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'ocha_injuries_monthly', 'OCHA oPt — Palestinians injured by Israelis, by month, area, perpetrator, age and governorate',
       s.source_id, 'casualties', 'daily', true,
       jsonb_build_object('publisher_window_from', '2008-01-01',
         'scope_note', 'Counted by month from the casualty page''s injuries table (names never read). Gaza''s injured since 7 October 2023 are not in OCHA''s record.')
  FROM source s WHERE s.key = 'ocha_casualties'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'ocha_injuries_monthly');
