-- 083 — serve what is held: the Nakba localities, UCDP and the journalists (P1-B.1).
--
-- The event table holds the Palestine Open Maps depopulation record (localities
-- depopulated 1935–1967, most in the 1948 Nakba), UCDP's conflict events
-- (1989–2024) and Tech4Palestine's journalist killings. Every databank view read
-- the `observation` table only, so no route and no tool could reach any of them:
-- "the depopulated villages of Ramla district" had no answer while the rows sat
-- in the database (PLAN §4 R4). ops/backfill_conflict_names.py (2026-09-25)
-- restored the names the importer had dropped.
--
-- MEASURED BEFORE SERVING, and two things were wrong with what was held:
--   * The same v1 file was imported TWICE (two snapshots, re-minted ids): 574 of
--     the 1,163 "villages" and 74 of the 7,712 UCDP events are exact copies of
--     rows from the first import (same name and point; same date, place, dyad
--     and deaths). The held record is 589 localities and 7,638 UCDP events. The
--     copies are marked `superseded` (superseded_by = the original), never
--     deleted; the event versioning trigger keeps the prior row.
--   * The villages' "displaced" figure is each locality's TOTAL 1945 population
--     (Village Statistics), all residents: Jerusalem reads 157,080 and Haifa
--     138,300. It is served as `population_1945`, never as a refugee count, and
--     each row carries the locality's group (Palestinian / Mixed / Jewish) from
--     the gazetteer.
--
-- What this serves:
-- 1. databank_event_rows: the current events in observation's shape
--    (`observation_id` = the NEGATIVE event id, so the two never collide;
--    value_text = the name; the journalists' date is a placeholder in the source
--    — every row 2023-10-07 — and is served with precision 'unknown').
-- 2. databank_internal = observation rows UNION ALL databank_event_rows, so
--    databank_serving, the tier views, the category views, v_withheld and
--    v_observation_canonical inherit them.
-- 3. Five indicator_def rows and a `displacement` category (the localities are
--    served there; UCDP and the journalists stay under `conflict`).
-- 4. UCDP is served NON-COMMERCIAL until a human reads its terms page (gate
--    G5.11): the source row says CC-BY-IGO/commercial with terms_verified_at
--    NULL, and a licence nobody has read is not sold.
--
-- Rollback (exact):
--   CREATE OR REPLACE VIEW databank_internal AS <this file's first branch alone>;
--   DROP VIEW v_displacement; DROP VIEW databank_event_rows;
--   DELETE FROM indicator_def WHERE source_spec = '083';
--   DELETE FROM category WHERE key = 'displacement';
--   UPDATE dataset SET commercial_use = NULL, attrs = attrs - 'commercial_withheld_083'
--    WHERE key = 'v1_conflict_ucdp';
--   UPDATE event SET status = 'believed', superseded_by = NULL,
--          attrs = attrs - 'superseded_083'
--    WHERE attrs ? 'superseded_083';

-- 0. the second import, marked as the copy it is
WITH first AS (
  SELECT event_id, lower(attrs->>'name') AS n,
         round((attrs->>'raw_lat')::numeric, 3) AS la, round((attrs->>'raw_lon')::numeric, 3) AS lo,
         occurred_at::date AS d, metrics->>'killed' AS k, attrs->>'dyad_name' AS dy,
         attrs->>'dataset_key' AS ds
    FROM event
   WHERE attrs->>'dataset_key' IN ('v1_conflict_palopenmaps', 'v1_conflict_ucdp')
     AND attrs->>'raw_ref' = 'bronze://v1_conflict/498b2df09f29b94a9ac5dfb32ccdcefcab36ce2d70e77a404961d48ab2f2fb36'
     AND status = 'believed'
), twin AS (
  SELECT DISTINCT ON (e.event_id) e.event_id, f.event_id AS original
    FROM event e
    JOIN first f ON f.ds = e.attrs->>'dataset_key'
     AND (   (f.ds = 'v1_conflict_palopenmaps'
              AND f.n = lower(e.attrs->>'name')
              AND f.la = round((e.attrs->>'raw_lat')::numeric, 3)
              AND f.lo = round((e.attrs->>'raw_lon')::numeric, 3))
          OR (f.ds = 'v1_conflict_ucdp'
              AND f.d = e.occurred_at::date
              AND f.n IS NOT DISTINCT FROM lower(e.attrs->>'name')
              AND f.k IS NOT DISTINCT FROM e.metrics->>'killed'
              AND f.dy IS NOT DISTINCT FROM e.attrs->>'dyad_name'))
   WHERE e.attrs->>'dataset_key' IN ('v1_conflict_palopenmaps', 'v1_conflict_ucdp')
     AND e.attrs->>'raw_ref' = 'bronze://v1_conflict/6d0fd896bd94646728b4f9e84a299fd4fc2f202c45342892516477b226c0fa44'
     AND e.status = 'believed'
   ORDER BY e.event_id, f.event_id
)
UPDATE event e
   SET status = 'superseded', superseded_by = t.original,
       attrs = e.attrs || jsonb_build_object('superseded_083',
               'exact copy of event ' || t.original || ' from a second import of the same v1 file')
  FROM twin t WHERE e.event_id = t.event_id;

-- 1. the events in observation's shape
CREATE OR REPLACE VIEW databank_event_rows AS
SELECT (-e.event_id)::bigint                                          AS observation_id,
       e.occurred_at,
       CASE WHEN (e.attrs->>'date_is_placeholder')::boolean
            THEN 'unknown'::time_precision ELSE e.occurred_precision END AS occurred_precision,
       CASE e.event_type
         WHEN 'conflict.state_based'           THEN 'conflict.deaths.state_based'
         WHEN 'conflict.one_sided'             THEN 'conflict.deaths.one_sided'
         WHEN 'conflict.non_state'             THEN 'conflict.deaths.non_state'
         WHEN 'conflict.village_depopulation'  THEN 'displacement.locality_depopulated'
         WHEN 'conflict.killing_of_journalist' THEN 'conflict.journalists_killed'
       END                                                            AS indicator,
       CASE e.event_type
         WHEN 'conflict.village_depopulation'
           THEN COALESCE((e.attrs->>'population_1945')::double precision,
                         (e.metrics->>'displaced')::double precision)
         WHEN 'conflict.killing_of_journalist' THEN 1::double precision
         ELSE (e.metrics->>'killed')::double precision
       END                                                            AS value_num,
       e.attrs->>'name'                                               AS value_text,
       'persons'::text                                                AS unit,
       e.place_id,
       (e.attrs - 'raw_ref' - 'v1_stable_id' - 'enriched_by' - 'dataset_key' - 'raw_lat' - 'raw_lon')
         || jsonb_build_object('event_id', e.event_id, 'event_type', e.event_type)
         || CASE WHEN e.event_type = 'conflict.village_depopulation' THEN
                 jsonb_build_object('value_is', 'population_1945 (all residents, Village Statistics 1945) — not a refugee count',
                                    'lat', e.attrs->'raw_lat', 'lon', e.attrs->'raw_lon')
                 -- only from the locality's OWN gazetteer row: v1's importer fell
                 -- back to the governorate for some villages (Bayt Nuba -> رام الله)
                 || CASE WHEN p.source_refs->>'source' = 'palopenmaps' THEN
                         jsonb_strip_nulls(jsonb_build_object(
                           'name_ar', p.name_ar,
                           'subdistrict_1945', p.attrs->>'subdistrict_1945',
                           'locality_group', p.attrs->>'locality_group',
                           'locality_status', p.attrs->>'locality_status'))
                    ELSE '{}'::jsonb END
                 ELSE '{}'::jsonb END                                 AS attrs,
       e.created_at                                                   AS reported_at,
       e.sys_period,
       d.key                                                          AS dataset_key,
       CASE WHEN e.event_type = 'conflict.village_depopulation'
            THEN 'displacement' ELSE d.v1_category END                AS v1_category,
       s.key                                                          AS source_key,
       s.name                                                         AS source_name,
       COALESCE(d.license_spdx, s.license_spdx)                       AS license_spdx,
       COALESCE(d.commercial_use, s.commercial_use)                   AS commercial_use,
       COALESCE(d.attribution_text, s.attribution_text)               AS attribution_text,
       COALESCE(d.share_alike, s.share_alike)                         AS share_alike,
       COALESCE(d.attribution_required, s.attribution_required)       AS attribution_required,
       COALESCE(d.redistribution, s.redistribution)                   AS redistribution,
       COALESCE(d.terms_url, s.terms_url)                             AS terms_url,
       COALESCE(d.terms_verified_at, s.terms_verified_at)             AS terms_verified_at
  FROM event e
  JOIN dataset d ON d.key = e.attrs->>'dataset_key'
  JOIN source s ON s.source_id = d.source_id
  LEFT JOIN place p ON p.place_id = e.place_id
 WHERE e.event_type IN ('conflict.state_based', 'conflict.one_sided', 'conflict.non_state',
                        'conflict.village_depopulation', 'conflict.killing_of_journalist')
   AND e.status = 'believed'
   AND upper_inf(e.sys_period);

COMMENT ON VIEW databank_event_rows IS
  'Held conflict events (UCDP, Palestine Open Maps localities, journalists) in observation''s shape, current rows only. observation_id = -event_id. 083.';

-- 2. one view for the whole databank
CREATE OR REPLACE VIEW databank_internal AS
 SELECT o.observation_id,
    o.occurred_at,
    o.occurred_precision,
    o.indicator,
    o.value_num,
    o.value_text,
    o.unit,
    o.place_id,
    o.attrs,
    o.reported_at,
    o.sys_period,
    d.key AS dataset_key,
    d.v1_category,
    s.key AS source_key,
    s.name AS source_name,
    COALESCE(d.license_spdx, s.license_spdx) AS license_spdx,
    COALESCE(d.commercial_use, s.commercial_use) AS commercial_use,
    COALESCE(d.attribution_text, s.attribution_text) AS attribution_text,
    COALESCE(d.share_alike, s.share_alike) AS share_alike,
    COALESCE(d.attribution_required, s.attribution_required) AS attribution_required,
    COALESCE(d.redistribution, s.redistribution) AS redistribution,
    COALESCE(d.terms_url, s.terms_url) AS terms_url,
    COALESCE(d.terms_verified_at, s.terms_verified_at) AS terms_verified_at
   FROM observation o
     JOIN dataset d ON d.dataset_id = o.dataset_id
     JOIN source s ON s.source_id = d.source_id
  WHERE o.v1_stable_id IS NOT NULL AND upper_inf(o.sys_period)
 UNION ALL
 SELECT * FROM databank_event_rows;

-- 3. the indicators and the category
INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status, source_spec, notes)
VALUES
  ('conflict.deaths.state_based', 'mortality.conflict', 'Deaths in state-based conflict events (UCDP GED)',
   'قتلى أحداث نزاع بين دولة وطرف مسلّح (UCDP)', 'persons', 'flow', -1, 'event', 'point', 'generated', '083',
   'One row per UCDP GED event; value = best estimate of deaths.'),
  ('conflict.deaths.one_sided', 'mortality.conflict', 'Deaths in one-sided violence events (UCDP GED)',
   'قتلى أحداث عنف من طرف واحد (UCDP)', 'persons', 'flow', -1, 'event', 'point', 'generated', '083',
   'One row per UCDP GED event; value = best estimate of deaths.'),
  ('conflict.deaths.non_state', 'mortality.conflict', 'Deaths in non-state conflict events (UCDP GED)',
   'قتلى أحداث نزاع بين أطراف غير حكومية (UCDP)', 'persons', 'flow', -1, 'event', 'point', 'generated', '083',
   'One row per UCDP GED event; value = best estimate of deaths.'),
  ('conflict.journalists_killed', 'mortality.conflict', 'Journalists killed (Tech4Palestine)',
   'صحفيون استشهدوا (Tech4Palestine)', 'persons', 'flow', -1, 'event', 'region', 'generated', '083',
   'One row per journalist; value_text = name. The source gives no date: precision unknown.'),
  ('displacement.locality_depopulated', 'displacement.depopulation',
   'Localities depopulated 1935–1967, with their 1945 population (Palestine Open Maps)',
   'تجمعات مهجّرة ١٩٣٥–١٩٦٧ مع عدد سكانها سنة ١٩٤٥ (Palestine Open Maps)', 'persons', 'stock', NULL,
   'event', 'locality', 'generated', '083',
   'One row per locality; value = its TOTAL 1945 population (all residents, Village Statistics 1945), never a refugee count; value_text = name; attrs.district_1945, subdistrict_1945 and locality_group (Palestinian / Mixed / Jewish) where known.')
ON CONFLICT (indicator) DO NOTHING;

INSERT INTO category (key, name_en, name_ar, domain_rule, active, notes)
VALUES ('displacement', 'Displacement', 'التهجير', 'v1_category = ''displacement''', true,
        '083: the depopulation record (Palestine Open Maps), served from the event table.')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE VIEW v_displacement AS
SELECT occurred_at, occurred_precision, indicator, value_num, value_text, unit, place_id, attrs,
       source_name, license_spdx, attribution_text, share_alike, redistribution
  FROM databank_serving WHERE v1_category = 'displacement';

-- 4. UCDP: a licence nobody has read is not sold (G5.11)
UPDATE dataset
   SET commercial_use = false,
       attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object('commercial_withheld_083',
               'UCDP terms have not been read at the publisher (terms_verified_at NULL); served '
               'non-commercial until a human records the licence sentence (PLAN P1-B.1, G5.11)')
 WHERE key = 'v1_conflict_ucdp' AND commercial_use IS NULL;
