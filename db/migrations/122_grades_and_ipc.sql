-- 122 · Zaid's grades for the three sources of 121, and IPC as a source (2026-10-14)
--
-- 1. Zaid, asked whether partners may see WHO's attacks on health care, ILO's quarters and the World
--    Bank's night lights: "1. yes". Graded as their publishers state:
--      who_ssa                "Permission from WHO is not required for the use of the ... dashboard material
--                             or data available for download" (read on the dashboard 2026-10-14): attribution,
--                             commercial use not restricted by those words.
--      ilostat                CC BY 4.0 (ILO's rights and permissions, 3 May 2023 on).
--      worldbank_space2stats  CC BY 4.0 (the World Bank data catalog, dataset 0066940).
-- 2. IPC's acute food insecurity analyses, through HDX's dataset (Zaid on HDX's robots file: "we need this
--    data for our own research and data collections and relations"). HDX states "Public Domain / No
--    restrictions (CC0)"; held at ask until Zaid grades it, as 121's were.
--
-- Rollback: UPDATE source SET redistribution = 'ask', commercial_use = false, license_spdx = 'verify-required'
--             WHERE key IN ('who_ssa', 'ilostat', 'worldbank_space2stats');
--           DELETE FROM dataset WHERE key = 'ipc_phases' AND NOT EXISTS
--             (SELECT 1 FROM observation o WHERE o.dataset_id = dataset.dataset_id);
--           DELETE FROM source WHERE key = 'ipc_hdx' AND NOT EXISTS
--             (SELECT 1 FROM dataset d WHERE d.source_id = source.source_id);

UPDATE source
   SET license_spdx = 'WHO-SSA-terms', redistribution = 'attribution', commercial_use = true,
       terms_evidence = terms_evidence || ' Graded by Zaid on 2026-10-14 ("yes": partners may see it), as WHO states it: attribution.'
 WHERE key = 'who_ssa' AND redistribution = 'ask';

UPDATE source
   SET license_spdx = 'CC-BY-4.0', redistribution = 'attribution', commercial_use = true,
       terms_evidence = terms_evidence || ' Graded by Zaid on 2026-10-14 ("yes": partners may see it): CC BY 4.0, attribution.'
 WHERE key IN ('ilostat', 'worldbank_space2stats') AND redistribution = 'ask';

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'ipc_hdx', 'Integrated Food Security Phase Classification (IPC), via HDX', 'api', 5,
       'verify-required', false, false, true,
       'Acute food insecurity: Integrated Food Security Phase Classification (IPC), National IPC Technical Working Group, via HDX.',
       'ask', 'https://data.humdata.org/dataset/state-of-palestine-acute-food-insecurity-country-data',
       '2026-10-14T16:00:00Z',
       'Read 2026-10-14 through HDX''s CKAN API: license_title "Public Domain / No restrictions (CC0)", contributed by IPC (source: National IPC Technical Working Group). Held at ask until Zaid grades it.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'ipc_hdx');

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'ipc_phases', 'IPC — people in each phase of acute food insecurity in the Gaza Strip, by analysis and area',
       s.source_id, 'food', 'irregular', true,
       jsonb_build_object('publisher_window_from', '2023-11-01',
         'scope_note', 'Each IPC analysis since December 2023: the current period and its projection, the people and the share in phases 1 to 5 and 3 or worse, by the areas that analysis used (single governorates, combined areas, the Strip). The West Bank rows analyse nobody and are not held.')
  FROM source s WHERE s.key = 'ipc_hdx'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'ipc_phases');
