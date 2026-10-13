-- 111 · the held events as they stood on a past day (`as_of`)
-- 2026-10-13
--
-- `databank_event_rows` (083, 093) serves CURRENT event rows only, and the
-- databank route applies `as_of` to them by `sys_period @> day`. An event that
-- was ever changed in place has a current version that begins on the day of
-- the change, so an `as_of` before that day found nothing where it should have
-- found the version before: on 2026-10-13 event_history held 30,776 earlier
-- versions of databank events (20,171 Insecurity Insight incidents from the
-- re-key of 12 October, 7,860 UCDP events from the names backfill and 083,
-- 2,483 depopulated localities, 262 journalists), and none of them could be
-- reached. From today the loader also revises UCDP's events in place when
-- UCDP does (`event_reading`): without this view each revision would remove
-- the event from every `as_of` answer before it.
--
-- This view is `databank_event_rows` word for word over the current rows AND
-- event_history, without the "current only" line. A version is a row;
-- `sys_period` says when it stood; the route reads it only under `as_of`.
-- The two definitions must change together (tests/test_event_reading.py holds
-- their columns equal). The licence columns are today's: a grade is not
-- versioned, and what may be republished is decided by today's reading.
--
-- Nothing is written; no table is locked beyond the view's own creation.
-- Rollback: DROP VIEW databank_event_versions;

CREATE OR REPLACE VIEW databank_event_versions AS
SELECT (-e.event_id)::bigint                                          AS observation_id,
       e.occurred_at,
       CASE WHEN (e.attrs->>'date_is_placeholder')::boolean
            THEN 'unknown'::time_precision ELSE e.occurred_precision END AS occurred_precision,
       CASE
         WHEN e.event_type LIKE 'attack.%'                THEN e.event_type
         WHEN e.event_type = 'conflict.state_based'           THEN 'conflict.deaths.state_based'
         WHEN e.event_type = 'conflict.one_sided'             THEN 'conflict.deaths.one_sided'
         WHEN e.event_type = 'conflict.non_state'             THEN 'conflict.deaths.non_state'
         WHEN e.event_type = 'conflict.village_depopulation'  THEN 'displacement.locality_depopulated'
         WHEN e.event_type = 'conflict.killing_of_journalist' THEN 'conflict.journalists_killed'
       END                                                            AS indicator,
       CASE
         WHEN e.event_type LIKE 'attack.%' THEN 1::double precision
         WHEN e.event_type = 'conflict.village_depopulation'
           THEN COALESCE((e.attrs->>'population_1945')::double precision,
                         (e.metrics->>'displaced')::double precision)
         WHEN e.event_type = 'conflict.killing_of_journalist' THEN 1::double precision
         ELSE (e.metrics->>'killed')::double precision
       END                                                            AS value_num,
       e.attrs->>'name'                                               AS value_text,
       CASE WHEN e.event_type LIKE 'attack.%' THEN 'incidents'::text ELSE 'persons'::text END AS unit,
       e.place_id,
       (e.attrs - 'raw_ref' - 'v1_stable_id' - 'enriched_by' - 'dataset_key' - 'raw_lat' - 'raw_lon')
         || jsonb_build_object('event_id', e.event_id, 'event_type', e.event_type)
         || CASE WHEN e.event_type LIKE 'attack.%' THEN jsonb_build_object('victims', e.metrics)
                 ELSE '{}'::jsonb END
         || CASE WHEN e.event_type = 'conflict.village_depopulation' THEN
                 jsonb_build_object('value_is', 'population_1945 (all residents, Village Statistics 1945) — not a refugee count',
                                    'lat', e.attrs->'raw_lat', 'lon', e.attrs->'raw_lon')
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
  FROM (SELECT * FROM event UNION ALL SELECT * FROM event_history) e
  JOIN dataset d ON d.key = e.attrs->>'dataset_key'
  JOIN source s ON s.source_id = d.source_id
  LEFT JOIN place p ON p.place_id = e.place_id
 WHERE (e.event_type IN ('conflict.state_based', 'conflict.one_sided', 'conflict.non_state',
                         'conflict.village_depopulation', 'conflict.killing_of_journalist')
        OR e.event_type LIKE 'attack.%')
   AND e.status = 'believed';

COMMENT ON VIEW databank_event_versions IS
  'Every version of a held event in observation''s shape: the current rows and event_history. Read only under as_of (sys_period @> day); databank_event_rows is the same projection over current rows. 111.';
