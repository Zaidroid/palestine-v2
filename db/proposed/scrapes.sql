-- PROPOSED, NOT APPLIED — supply-scrapes (2026-10-12): land, settlements, prisoners, culture.
--
-- What this file is: the provenance and vintage of six datasets, as measured on 2026-10-12 from the publishers'
-- own records and from v1's fetch scripts, written where a served dataset can say them: dataset.attrs. Nothing here
-- touches an observation, a licence grade, a source row or a spec's routing. Each statement only adds keys to
-- dataset.attrs and is guarded by the dataset key. The jsonb expressions were evaluated read-only against
-- production on 2026-10-12 (as SELECTs); the UPDATEs themselves were not run.
--
-- Keys, the same on every dataset:
--   provenance        what the rows really are and where they came from, in one paragraph
--   vintage           the date the publisher says the data is as of
--   vintage_basis     where that date is stated
--   vintage_url       the page that states it
--   provenance_checked the day this was read
--   v1_defaults       attributes held on every row that are defaults in v1's code, not the publisher's statement
--
-- Rollback (exact), for all six:
--   UPDATE dataset SET attrs = attrs - 'provenance' - 'vintage' - 'vintage_basis' - 'vintage_url'
--                                    - 'provenance_checked' - 'v1_defaults' - 'supply'
--    WHERE key IN ('v1_culture_heritage_composite', 'v1_land_ocha', 'v1_land_peace_now', 'v1_land_goodshepherd',
--                  'v1_settlements_peace_now', 'v1_prisoners_addameer');

-- ── 1. culture: a frozen corpus, and not the compilation its label claims ────────────────────────────────────────
-- v1's scripts/fetch-culture-data.js runs ONE SPARQL query against query.wikidata.org every night (LIMIT 500, no
-- ORDER BY) and v1's unified step labels the result "UNESCO, Ministry of Tourism, NGO Reports". No row came from
-- any of the three. The corpus is frozen in the repository as of v1's fetch of 2026-10-12 (data/frozen/
-- culture.json.gz, 335 sites; the Wikidata item id of each is in data/frozen/culture_wikidata_items.json.gz).
UPDATE dataset
   SET attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object(
         'provenance', 'Wikidata. One SPARQL query (query.wikidata.org/sparql) for items located in the State of Palestine, the West Bank or the Gaza Strip that are an archaeological site, historic site, World Heritage Site, mosque or church and have a coordinate, LIMIT 500 with no ordering, de-duplicated by label. Not compiled from UNESCO, a ministry or NGO reports, whatever the dataset name says.',
         'vintage', '2026-10-12',
         'vintage_basis', 'Wikidata as it stood at v1''s last fetch (2026-10-12T02:42:49Z); Wikidata states no vintage of its own for a query result',
         'vintage_url', 'https://www.wikidata.org/',
         'provenance_checked', '2026-10-12',
         'v1_defaults', jsonb_build_array(
             'site_status: "Intact" is a constant in v1''s code on every row, the 50 Gaza Strip rows included; nobody observed it',
             'protection_level: "National Heritage" is the default for any item Wikidata does not mark World Heritage; no register was consulted',
             'site_type: keywords in the label and description (mosque/church/monastery, archaeolog/ruin/tell, else Cultural)',
             'region: the words gaza or jerusalem in the label or description, else a bounding box, else West Bank'),
         'supply', 'frozen 2026-10-12: data/frozen/culture.json.gz; no fetcher (query.wikidata.org/robots.txt disallows /sparql)')
 WHERE key = 'v1_culture_heritage_composite';

-- ── 2. land: three datasets, three real origins ──────────────────────────────────────────────────────────────────
-- 2a. The 261 "checkpoints" are the 261 segments of OCHA oPt's West Bank Separation Barrier file.
UPDATE dataset
   SET attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object(
         'provenance', 'HDX dataset west-bank-barrier, "West Bank Separation Barrier" (OCHA oPt), file Barrier_Jan2018: 261 line segments, 181 Constructed, 28 Under Construction, 52 Projected. Not checkpoints and not movement obstacles: v1 took the first shapefile an HDX search for "west bank closure" returned and named the rows land.checkpoint. The same 261 segments are also held as infrastructure.barrier_segment (v1_infrastructure_hdx).',
         'vintage', '2018-01-01',
         'vintage_basis', 'HDX dataset_date [2018-01-01 TO 2018-01-01]; notes "West Bank Separation Barrier, January 2018"; methodology "updated using aerial imagery (2018) and based on field observation"; file last modified 2019-07-16',
         'vintage_url', 'https://data.humdata.org/dataset/west-bank-barrier',
         'provenance_checked', '2026-10-12',
         'v1_defaults', jsonb_build_array(
             'permits_required: true on every row is a default in v1''s code; a barrier segment has no permit regime in the file',
             'checkpoint_type "Barrier", land_type "checkpoint", value 1 "sites": v1''s naming; the file gives status, type and length in metres'),
         'supply', 'ops/fetch_hdx_land.py since 2026-10-12 (HDX licence as stated there: cc-by)')
 WHERE key = 'v1_land_ocha';

-- 2b. The 199 settlement rows are OCHA oPt's HDX file of Peace Now's built-up areas.
UPDATE dataset
   SET attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object(
         'provenance', 'HDX dataset state-of-palestine-settlements, "State of Palestine Settlements", published by OCHA oPt, source "Peace Now and OCHA oPt", caveat "Settlements data provided by Peace Now": 201 built-up-area polygons, each with a name and an area and nothing else. Two unnamed polygons share name and rounded area with another and are held once (199 rows).',
         'vintage', '2018-12-31',
         'vintage_basis', 'HDX dataset_date [2018-12-30 TO 2018-12-31]; file last modified 2021-06-03; the shapefile''s own metadata was created 2019-01-21',
         'vintage_url', 'https://data.humdata.org/dataset/state-of-palestine-settlements',
         'provenance_checked', '2026-10-12',
         'v1_defaults', jsonb_build_array(
             'land_status "Authorized" and legal_status "Authorized" on every row: a default in v1''s code; the file has no status field',
             'settlement_type "Settlement" on every row: a default; the file has no type field'),
         'supply', 'ops/fetch_hdx_land.py since 2026-10-12 (HDX licence as stated there: cc-by-igo)')
 WHERE key = 'v1_land_peace_now';

-- 2c. Good Shepherd's daily counts are UN OCHA's demolition record, republished, West Bank and East Jerusalem.
UPDATE dataset
   SET attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object(
         'provenance', 'goodshepherdcollective.org/api/home_demolitions.json: one entry per day with an incident, in a rolling window of about thirteen months; days that left the window stay held. The collective''s page: "This data only represents information from UN OCHA, which focuses on the West Bank and East Jerusalem". Value = structures; the publisher''s incidents and people displaced per day are in the raw file and not loaded.',
         'vintage', '2026-10-08',
         'vintage_basis', 'newestDateofincident in the publisher''s answer; its page says "The data reflects the reporting as of 10.08.2026". Moves with every fetch: read the raw file''s metadata for today''s',
         'vintage_url', 'https://goodshepherdcollective.org/data/home_demolitions',
         'provenance_checked', '2026-10-12',
         'v1_defaults', jsonb_build_array(
             'structure_type "residential", structures_demolished 1 (whatever the count), reason "Administrative demolition", notification_given true, owner_type "Private": defaults in v1''s code on every row',
             'region "Palestine" (place NULL): v1''s default; the publisher says West Bank and East Jerusalem',
             'rows dated before 2025-09-08 can no longer be checked against the publisher (out of its window); v1 stored a day of 0 structures as 1'),
         'supply', 'ops/fetch_goodshepherd.py since 2026-10-12')
 WHERE key = 'v1_land_goodshepherd';

-- ── 3. settlements: end-of-year counts, under their own year ─────────────────────────────────────────────────────
UPDATE dataset
   SET attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object(
         'provenance', 'Peace Now, Settlement Watch, Population page: the line chart''s 51 points, 1967 to 2024, caption "Source: Israeli CBS". Each point is the Israeli CBS end-of-year count of the Judea and Samaria Area for the labelled year (checked against the CBS Statistical Abstract for 1972, 1983, 1995, 2008, 2021 and 2022). Held at the first day of that year with precision year.',
         'vintage', '2024',
         'vintage_basis', 'the last year on the chart''s axis (511,100). Two pie captions on the same page still read "end of 2023" beside the same 511,100; the CBS end-of-2023 figure is 501,100 Israelis (504,700 with foreigners), so the captions are stale, not the chart',
         'vintage_url', 'https://peacenow.org.il/en/settlements-watch/settlements-data/population',
         'provenance_checked', '2026-10-12',
         'supply', 'ops/fetch_peacenow.py since 2026-10-12')
 WHERE key = 'v1_settlements_peace_now';

-- NO RE-DATING OF THE 51 ROWS IS PROPOSED. The defect reported ("the 2023 figure sits at 2024-01-01") was measured
-- and is not there: the row at 2024-01-01 (precision year, attrs.year 2024) holds 511,100, which is the end-of-2024
-- count; the end-of-2023 count, 503,732, is the row at 2023-01-01. What is true is the databank-wide convention the
-- spec already names as its open question: a year-end stock is anchored at the START of its year
-- (attrs.reference 'period-end stock'). Moving these 51 rows to <year>-12-31 would change that convention for one
-- dataset only, and the identity of all 51 rows; it is Zaid's decision for every stock series at once, so no
-- statement is written here. What it would take, if he decides it: close the 51 current rows, insert 51 with
-- occurred_at = make_date(year, 12, 31), precision year, identity_key rebuilt on the new date, the old date kept in
-- attrs; and in db/mappings/settlements.yaml replace the rule's `truncate_to: year` so a later run produces the
-- same date (the engine has no "keep the date, year precision" rule that survives law 2 today).

-- ── 4. prisoners (Addameer) ──────────────────────────────────────────────────────────────────────────────────────
UPDATE dataset
   SET attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object(
         'provenance', 'addameer.ps/statistics. total and administrative: the page''s two charts, one point a month over a rolling window of about fourteen entries (months that left it stay held). child and female: the page''s dated block, filed under the month of the block''s own date. Until 2026-10-12 v1 filed child and female under the month it ran in, so the first days of 2026-08, -09 and -10 carried the previous month''s two figures until Addameer posted.',
         'vintage', '2026-10-05',
         'vintage_basis', 'the page''s own "date of statistics" on its current block (05-10-2026). Moves with every post: read the raw file''s metadata for today''s',
         'vintage_url', 'https://www.addameer.ps/statistics',
         'provenance_checked', '2026-10-12',
         'v1_defaults', jsonb_build_array(
             'reference "period-end stock": the figures are as of the block''s date, early in the labelled month, not the month''s end'),
         'supply', 'ops/fetch_addameer.py since 2026-10-12')
 WHERE key = 'v1_prisoners_addameer';

-- ── Not SQL, and why ─────────────────────────────────────────────────────────────────────────────────────────────
-- * land.demolition 2026-01-04 and 2026-07-26 are held as 1 structure; Good Shepherd reports 0 (one incident, people
--   displaced, nothing demolished). The first loader run on the fetched file supersedes both by itself (dry run of
--   2026-10-12: revisions 2). No migration.
-- * Renaming land.checkpoint (it is the barrier), dropping the v1 defaults listed above from the rows, and placing
--   Good Shepherd's rows in the West Bank are each a change to held rows and to what is served. They are described
--   in the hand-over report with their counts and left for a decision; none is written here.
