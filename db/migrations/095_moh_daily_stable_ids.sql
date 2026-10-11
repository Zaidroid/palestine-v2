-- 095 — The Ministry's daily series gets stable ids, so it is served (2026-10-11).
--
-- gaza_moh_daily (dataset 41, ingest/sources/moh_gaza.py) is the only dataset written without a
-- v1_stable_id, and databank_internal/databank_serving carry only rows that have one — so the
-- Ministry's first-hand series (5,762 current rows after the archive re-read of 2026-10-11, back to
-- 2024-02-14) was never served beside T4P's compilation of the same bulletins. The ingest now writes
-- `moh-<indicator>-<day>` on every new row; this stamps the rows already held, current and closed
-- alike (the uniqueness index covers current rows only, and a revision closes the old row before the
-- new one lands, so no two current rows share an id).
--
-- Rollback: UPDATE observation SET v1_stable_id = NULL WHERE dataset_id = (SELECT dataset_id FROM dataset
--             WHERE key = 'gaza_moh_daily') AND v1_stable_id LIKE 'moh-%';

UPDATE observation o
   SET v1_stable_id = 'moh-' || o.indicator || '-' || to_char(o.occurred_at, 'YYYY-MM-DD')
  FROM dataset d
 WHERE d.dataset_id = o.dataset_id AND d.key = 'gaza_moh_daily'
   AND o.v1_stable_id IS NULL;
