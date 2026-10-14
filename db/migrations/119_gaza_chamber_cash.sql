-- 119 · the Gaza Chamber of Commerce's cash-out commission: a third dataset of the source added by 117
-- 2026-10-14
--
-- The commission paid in Gaza to turn a bank or wallet balance into cash in hand, as the Chamber's
-- weekly reports record it: db/mappings/cash_gazacham.yaml, built by ops/build_gazacham_cash.py from
-- the reports the archive holds. The source row and its terms (all rights reserved: held for the
-- house, withheld from partners) are 117's.
--
-- Rollback: DELETE FROM dataset WHERE key = 'gazacham_cash' AND NOT EXISTS
--             (SELECT 1 FROM observation o JOIN dataset d USING (dataset_id) WHERE d.key = 'gazacham_cash');
--           (with rows loaded, deactivate instead: UPDATE dataset SET active = false WHERE key = 'gazacham_cash')

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'gazacham_cash',
       'Gaza Chamber of Commerce — the commission paid to turn a balance into cash, by day, week and month',
       s.source_id, 'economic', 'irregular', true,
       jsonb_build_object(
         'publisher_window_from', '2025-01-19',
         'publisher_window_to', '2026-07-19',
         'scope_note', 'Daily from 17 June 2025 to 19 July 2026, the commission''s own weeks from the ceasefire of 19 January 2025, and the whole months of 2025. The reports of August 2026 say the commission had become largely insignificant as electronic payment spread and print no table after July 2026.')
  FROM source s
 WHERE s.key = 'gaza_chamber'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'gazacham_cash');
