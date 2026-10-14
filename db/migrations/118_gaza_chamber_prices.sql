-- 118 · the Gaza Chamber of Commerce's prices: a second dataset of the source added by 117
-- 2026-10-14
--
-- The Chamber's weekly reports price 30 goods against their pre-war prices and keep a price index
-- (GCPI) of a basket of essential goods. db/mappings/price_gazacham.yaml, built by
-- ops/build_gazacham_prices.py from the reports the archive holds. The source row and its terms
-- (all rights reserved: held for the house, withheld from partners) are 117's.
--
-- Rollback: DELETE FROM dataset WHERE key = 'gazacham_prices' AND NOT EXISTS
--             (SELECT 1 FROM observation o JOIN dataset d USING (dataset_id) WHERE d.key = 'gazacham_prices');
--           (with rows loaded, deactivate instead: UPDATE dataset SET active = false WHERE key = 'gazacham_prices')

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'gazacham_prices',
       'Gaza Chamber of Commerce — market prices of 30 goods against pre-war, and its price index (GCPI)',
       s.source_id, 'food', 'irregular', true,
       jsonb_build_object(
         'publisher_window_from', '2025-01-31',
         'not_a_continuation_of', jsonb_build_array('v1_food_wfp'),
         'scope_note', 'Week prices of 30 goods in Gaza''s markets from 1 April 2025, each with the pre-war price the report compares it with; the weeks a table printed NA for a good; the GCPI daily from 27 May 2025, by the index''s weeks from 31 January 2025 and by month from February 2025. Weeks 62-65 (October 2025) were priced for North and South apart and are not here, nor are weeks 1-35.')
  FROM source s
 WHERE s.key = 'gaza_chamber'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'gazacham_prices');
