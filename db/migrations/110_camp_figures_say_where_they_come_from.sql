-- 110 · the refugee-camp figures say where they come from
-- 2026-10-12
--
-- v1_refugees_unrwa (75 rows) is credited to UNRWA and dated 10 June 2026.
-- Read on 2026-10-12 by the supply agent: v1 scraped Wikipedia's table
-- "Palestinian refugee camps" once, on 2026-06-10. The table entered Wikipedia
-- on 2020-07-08, each row citing UNRWA's camp profile page; archived copies of
-- those pages carry the held values from 2018 to 2020 (Rafah 125,304 from
-- June 2019; Ein el-Hilweh's 59,660 "as of June 2018") and no date of their
-- own. So these are UNRWA's registered-refugee counts of about 2018 to 2020,
-- not current populations, and they reached us through Wikipedia.
--
-- This migration writes that on the dataset: its provenance, the vintage as
-- far as it is known, and a credit line that names Wikipedia and UNRWA's camp
-- pages. It changes no licence GRADE (redistribution, commercial_use stay as
-- they are): Wikipedia's text is CC BY-SA 4.0 and UNRWA's pages state no
-- reuse licence, and which of the two governs these numbers is Zaid's call.
--
-- The eleven mislabelled "summary" rows of the same scrape are not touched
-- here: the transformer stops emitting them and the dataset's complete
-- generation closes them on the next load.
--
-- Rollback:
--   UPDATE dataset SET attribution_text = NULL,
--          attrs = attrs - 'provenance' - 'vintage' - 'vintage_basis' - 'vintage_url' - 'provenance_checked' - 'supply'
--    WHERE key = 'v1_refugees_unrwa';

UPDATE dataset
   SET attribution_text = 'Camp populations as listed in Wikipedia''s "Palestinian refugee camps" table (revision of 26 May 2026, CC BY-SA 4.0), copied there in July 2020 from UNRWA''s camp profile pages: UNRWA''s undated counts of registered refugees from about 2018 to 2020. Not a UNRWA release.',
       attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object(
         'provenance', 'Wikipedia, "Palestinian refugee camps" (revision 1356227162 of 2026-05-26), scraped once by v1 on 2026-06-10: the sixth cell of every row of three tables. The 64 camp rows entered Wikipedia on 2020-07-08 (revision 966661999), each citing UNRWA''s camp profile page; archived unrwa.org pages carry the held values from 2018 to 2020. unrwa.org answers automated readers with a challenge, and UNRWA''s HDX datasets hold no camp-level figures, so nothing can refresh these rows.',
         'vintage', 'about 2018 to 2020',
         'vintage_basis', 'archived copies of UNRWA''s camp profile pages (Rafah 125,304 from 2019-06-16; Jabalia 113,990 and Baqa''a 119,000 on 2020 captures; Ein el-Hilweh 59,660 "as of June 2018"); the pages give no date of their own',
         'vintage_url', 'https://en.wikipedia.org/wiki/Palestinian_refugee_camps',
         'provenance_checked', '2026-10-12',
         'supply', 'frozen: carried unchanged from data/frozen/refugees.json.gz by ops/fetch_idmc.py; no fetcher')
 WHERE key = 'v1_refugees_unrwa';

DO $$ BEGIN
  IF (SELECT count(*) FROM dataset WHERE key = 'v1_refugees_unrwa' AND attrs ? 'provenance') <> 1 THEN
    RAISE EXCEPTION '110: v1_refugees_unrwa was not found';
  END IF;
END $$;
