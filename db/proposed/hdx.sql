-- PROPOSED, NOT RUN. Branch supply-hdx, 2026-10-12.
--
-- The publisher's vintage for the two register datasets that come from HDX,
-- written once per dataset. A register row (one school, one village boundary,
-- one barrier segment) has no date of its own: the store holds the day v1
-- downloaded it, marked `unknown`. What a reader needs is the date the
-- publisher says the register is as of. It is not written per row, because a
-- row's attrs are part of its content: stamping it there would make all 2,962
-- held rows a revision.
--
-- Every value below was read from HDX's CKAN API on 2026-10-12
-- (https://data.humdata.org/api/3/action/package_show?id=<slug>) and is the
-- same value the fetchers write into their raw files' `metadata`
-- (data/raw/hdx_schools/schools.json, data/raw/infrastructure/barrier.json,
-- data/raw/infrastructure/village_boundaries.json), so a later loader step can
-- keep dataset.attrs current from there.
--
-- serve/app.py (databank-rest 9883b34) already reads `dataset.attrs->>'vintage'`
-- as `dataset_vintage`, and view dataset_freshness (migration 104) reads it as
-- `publisher_vintage`.
--
-- Rollback (exact):
--   UPDATE dataset SET attrs = attrs - 'vintage' - 'vintage_basis' - 'vintage_url'
--          - 'vintage_checked_at' - 'vintage_by_indicator'
--    WHERE key IN ('v1_education_hdx', 'v1_infrastructure_hdx');

BEGIN;

-- 1. The West Bank school register: 2,359 rows, one HDX dataset, one date.
--    HDX `state-of-palestine-west-bank-schools`: dataset_date
--    "[2015-06-01T00:00:00 TO 2015-06-01T23:59:59]"; resource schools_WB.zip
--    last_modified 2021-06-10T09:47:11; the shapefile's own table was last
--    written 2021-06-10.
UPDATE dataset
   SET attrs = attrs || jsonb_build_object(
         'vintage', '2015-06-01',
         'vintage_basis', 'HDX dataset_date, the day the contributor says the register is as of; the file was last replaced on HDX on 2021-06-10 (resource last_modified)',
         'vintage_url', 'https://data.humdata.org/dataset/state-of-palestine-west-bank-schools',
         'vintage_checked_at', '2026-10-12T20:03:27+00:00')
 WHERE key = 'v1_education_hdx';

-- 2. v1_infrastructure_hdx holds TWO registers from two HDX datasets, with two
--    different dates, so one `vintage` for the dataset would be wrong for one
--    of them whichever was chosen:
--      infrastructure.barrier_segment  261 rows  HDX `west-bank-barrier`,
--        dataset_date 2018-01-01 ("West Bank Separation Barrier, January
--        2018"); file last replaced 2019-07-16; table last written 2018-01-24.
--      infrastructure.locality_record  342 rows  HDX `state-of-palestine-
--        village-boundary-in-the-west-bank`, dataset_date 2019-07-24, which is
--        the day OCHA oPt put the file on HDX; the dataset's own description
--        says "These historical boundaries were created during British
--        Mandate in Palestine."
--    The four keys are written (the task's shape), with `vintage` left out on
--    purpose, and the two dates go under `vintage_by_indicator`. Until the
--    category route reads that map, both registers keep saying "with no date
--    given by the source", which is what they say today. The one-line change
--    that makes each row give its own date, in serve/app.py's databank_category:
--      COALESCE(d.attrs->'vintage_by_indicator'->o.indicator->>'vintage',
--               d.attrs->>'vintage')                     AS dataset_vintage
UPDATE dataset
   SET attrs = attrs || jsonb_build_object(
         'vintage_basis', 'two registers with two dates: see vintage_by_indicator',
         'vintage_url', 'https://data.humdata.org/organization/ocha-opt',
         'vintage_checked_at', '2026-10-12T20:03:33+00:00',
         'vintage_by_indicator', jsonb_build_object(
           'infrastructure.barrier_segment', jsonb_build_object(
             'vintage', '2018-01-01',
             'vintage_basis', 'HDX dataset_date, the day the contributor says the register is as of; the file was last replaced on HDX on 2019-07-16 (resource last_modified)',
             'vintage_url', 'https://data.humdata.org/dataset/west-bank-barrier'),
           'infrastructure.locality_record', jsonb_build_object(
             'vintage', '2019-07-24',
             'vintage_basis', 'HDX dataset_date, which is the day the dataset was put on HDX (metadata_created); the dataset describes the boundaries as drawn under the British Mandate',
             'vintage_url', 'https://data.humdata.org/dataset/state-of-palestine-village-boundary-in-the-west-bank')))
 WHERE key = 'v1_infrastructure_hdx';

-- Both statements must touch exactly one row each.
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM dataset
   WHERE (key = 'v1_education_hdx' AND attrs->>'vintage' = '2015-06-01')
      OR (key = 'v1_infrastructure_hdx'
          AND attrs->'vintage_by_indicator'->'infrastructure.barrier_segment'->>'vintage' = '2018-01-01');
  IF n <> 2 THEN
    RAISE EXCEPTION 'hdx vintage: expected 2 datasets stamped, found %', n;
  END IF;
END $$;

COMMIT;
