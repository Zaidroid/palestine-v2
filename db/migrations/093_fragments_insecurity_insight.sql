-- 093 — The fragments come into the databank (Zaid, 2026-10-11: "I want all of those included, the
-- databank right now is for personal use, build these as part of it").
--
-- The audit of 2026-10-11 found nine bodies of data held in the house but outside the databank. This
-- migration is the schema half of the first two:
--   1. a source row for Insecurity Insight (db/mappings/insecurity_insight.yaml — 20,836 incidents
--      with weapon, perpetrator and victims, 2002 → today; ops/fetch_insecurity_insight.py);
--   2. the event serving view widened so those `attack.*` events are served beside UCDP's.
-- B'Tselem's per-person file (db/mappings/btselem_fatalities.yaml) needs no schema change: source
-- row 7856 exists (053) and stays no-redistribution / commercial_use = false, so the partner and bulk
-- tiers never carry it; the letter (db/scout/letters/btselem_bulk.md) is still to send.
--
-- Terms, as read on 2026-10-11 through HDX's CKAN API (package b36e1975-4428-4caa-9b00-e0d8793130d0):
-- license_title "Creative Commons Attribution Share-Alike (CC BY-SA)", license_id cc-by-sa, package last
-- modified 2026-10-05. Publisher's caveat, verbatim: "The incidents reported are not a complete nor a
-- representative list of all incidents and have not been independently verified."
--
-- Rollback: DELETE FROM source WHERE key = 'insecurity_insight' AND NOT EXISTS (SELECT 1 FROM dataset d
--             JOIN source s USING (source_id) WHERE s.key = 'insecurity_insight');
--           (with rows loaded, deactivate instead: UPDATE source SET active = false WHERE key = 'insecurity_insight')
--           and re-run 083's CREATE OR REPLACE VIEW databank_event_rows to narrow the view again.

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'insecurity_insight', 'Insecurity Insight — State of Palestine incident data', 'api', 3,
       'CC-BY-SA-4.0', true, true, true,
       'Incident data: Insecurity Insight (insecurityinsight.org) via HDX, CC BY-SA. Not a complete or representative list; not independently verified.',
       'share-alike',
       'https://data.humdata.org/dataset/b36e1975-4428-4caa-9b00-e0d8793130d0',
       '2026-10-11T11:30:00Z',
       'HDX CKAN package_show on 2026-10-11: license_title "Creative Commons Attribution Share-Alike (CC BY-SA)", license_id cc-by-sa, last_modified 2026-10-05. Caveat on the package: "The incidents reported are not a complete nor a representative list of all incidents and have not been independently verified." Derived databases inherit share-alike (see unosat, palopenmaps).',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'insecurity_insight');

-- The event view (083) served five UCDP / Open Maps / T4P event types by name. Insecurity Insight's
-- events are `attack.<category>` (healthcare, explosive_weapons, aid_worker, education, food_systems,
-- water_systems, protection, sexual_violence). Each is served as ONE INCIDENT (value 1, unit
-- 'incidents') under the indicator that is its event type; the victims (killed, injured, kidnapped,
-- arrested) ride in attrs.victims, never as the row's value, so nothing sums people as incidents or
-- incidents as people. Every other branch of the view is unchanged.
CREATE OR REPLACE VIEW databank_event_rows AS
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
  FROM event e
  JOIN dataset d ON d.key = e.attrs->>'dataset_key'
  JOIN source s ON s.source_id = d.source_id
  LEFT JOIN place p ON p.place_id = e.place_id
 WHERE (e.event_type IN ('conflict.state_based', 'conflict.one_sided', 'conflict.non_state',
                         'conflict.village_depopulation', 'conflict.killing_of_journalist')
        OR e.event_type LIKE 'attack.%')
   AND e.status = 'believed'
   AND upper_inf(e.sys_period);

COMMENT ON VIEW databank_event_rows IS
  'Held events in observation''s shape, current rows only: UCDP, Palestine Open Maps localities, journalists (083) and Insecurity Insight attack.* incidents (093, one incident = value 1, victims in attrs). observation_id = -event_id.';
