-- 103 — the Ministry's own bulletins can be asked for (2026-10-12).
--
-- gaza_moh_daily (ingest/sources/moh_gaza.py: the Gaza Ministry of Health's
-- «التقرير الإحصائي», 30 indicators, 5,775 rows since February 2024) is in the
-- serving view and in the dataset listing, and no question reaches it: the
-- category route needs a category and the dataset has none, and the series
-- tools need a definition and its indicators had none (db/registry/
-- datasets.yaml gives them one). On 2026-10-11 the audit page called it
-- "served beside T4P's series". It was held beside it.
--
-- It is filed under `conflict`, where Tech for Palestine's relay of the same
-- bulletins already is. The two agree on 814 of 819 days; each row names its
-- own source, so an answer that shows both says whose figure each is.
--
-- Rollback (exact):
--   UPDATE dataset SET v1_category = NULL WHERE key = 'gaza_moh_daily';

UPDATE dataset SET v1_category = 'conflict'
 WHERE key = 'gaza_moh_daily' AND v1_category IS NULL;
