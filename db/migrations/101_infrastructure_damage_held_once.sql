-- 101 — Tech for Palestine's Gaza damage series is held once (2026-10-12).
--
-- v1_infrastructure_tech4palestine holds every day of its four series twice:
-- 2,920 rows filed under Gaza GOVERNORATE (place 15) on 2026-06-25, and the
-- same 2,920 under the Gaza STRIP (place 1) since 2026-08-07, when the place
-- ladder was corrected. The dataset's identity includes the place, so the June
-- copy was a different row to the loader and was never closed. Measured
-- 2026-10-12: 2,920 of 2,920 June rows have a current twin at place 1 with the
-- same indicator, day, value and damage level; it is the only dataset in the
-- databank holding one fact at two places. A question about Gaza governorate
-- answered with the Strip's 416,000 housing units, and a sum over places
-- doubled it.
--
-- The June rows are CLOSED (sys_period ends now), never deleted; each keeps
-- the id of the row that stands for it in attrs.duplicate_of_101. The loader
-- emits place 1 only, so nothing re-opens them.
--
-- The four series are running totals (0 falls in 729 steps; a rise on 91 to
-- 153 of them) and were labelled a daily flow per governorate: the registry
-- rule in db/mappings/infrastructure.yaml now says cumulative, per region,
-- which is what makes the correlate tool refuse to pair two of them.
-- `ops.load_registry --apply` writes that.
--
-- Rollback (exact):
--   UPDATE observation SET sys_period = tstzrange(lower(sys_period), NULL),
--          attrs = attrs - 'duplicate_of_101'
--    WHERE attrs ? 'duplicate_of_101';

UPDATE observation o
   SET sys_period = tstzrange(lower(o.sys_period), now()),
       attrs = COALESCE(o.attrs, '{}'::jsonb)
             || jsonb_build_object('duplicate_of_101', t.observation_id)
  FROM dataset d, observation t
 WHERE d.key = 'v1_infrastructure_tech4palestine'
   AND o.dataset_id = d.dataset_id AND o.place_id = 15 AND upper_inf(o.sys_period)
   AND t.dataset_id = o.dataset_id AND t.place_id = 1 AND upper_inf(t.sys_period)
   AND t.indicator = o.indicator AND t.occurred_at = o.occurred_at
   AND t.value_num IS NOT DISTINCT FROM o.value_num
   AND t.value_text IS NOT DISTINCT FROM o.value_text
   AND t.unit IS NOT DISTINCT FROM o.unit;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM observation o JOIN dataset d USING (dataset_id)
   WHERE d.key = 'v1_infrastructure_tech4palestine' AND o.place_id = 15
     AND upper_inf(o.sys_period);
  IF n > 0 THEN
    RAISE EXCEPTION '101: % rows at place 15 have no twin at place 1 and stay open — read them before closing anything', n;
  END IF;
END $$;
