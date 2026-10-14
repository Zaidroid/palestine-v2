-- 117 · the Gaza Chamber of Commerce and Industry as a source, and its weekly trucks dataset
-- 2026-10-14
--
-- The Chamber's weekly "Gaza Movement of Goods" reports (81 reports, weeks 1 to 111, 1 August 2024
-- to 13 September 2026) are in the archive whole since command 18. Their truck figures become a
-- series here: db/mappings/aid_gazacham.yaml, built by ops/build_gazacham_series.py.
--
-- Terms, as read on 2026-10-14: no licence and no terms of use are stated on gazacham.ps; the
-- footer reads «جميع الحقوق محفوظة، 2023، غرفة تجارة وصناعة محافظة غزة» (all rights reserved).
-- Its robots file sets no rule and no content signal. So the row is no-redistribution and
-- commercial_use = false, like Addameer's: held for the house, withheld from partners.
--
-- Rollback: DELETE FROM dataset WHERE key = 'gazacham_trucks_weekly' AND NOT EXISTS
--             (SELECT 1 FROM observation o JOIN dataset d USING (dataset_id)
--               WHERE d.key = 'gazacham_trucks_weekly');
--           DELETE FROM source WHERE key = 'gaza_chamber' AND NOT EXISTS (SELECT 1 FROM dataset d
--             JOIN source s USING (source_id) WHERE s.key = 'gaza_chamber');
--           (with rows loaded, deactivate instead: UPDATE source SET active = false WHERE key = 'gaza_chamber')

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'gaza_chamber', 'Gaza Chamber of Commerce and Industry — Gaza Movement of Goods weekly reports', 'file', 4,
       'no-license-found', false, false, true,
       'Trucks into Gaza: Gaza Chamber of Commerce and Industry, Gaza Movement of Goods weekly reports (gazacham.ps). All rights reserved.',
       'no-redistribution',
       'https://gazacham.ps/InformationCenter/Reports',
       '2026-10-14T06:30:00Z',
       'Read 2026-10-14: no licence or terms of use on gazacham.ps; footer "جميع الحقوق محفوظة، 2023، غرفة تجارة وصناعة محافظة غزة"; robots.txt carries only the Cloudflare content-signal preamble, with no signal and no rule.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'gaza_chamber');

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'gazacham_trucks_weekly',
       'Gaza Chamber of Commerce — trucks entering Gaza, looted and delivered, by week',
       s.source_id, 'aid_access', 'irregular', true,
       jsonb_build_object(
         'publisher_window_from', '2024-08-01',
         'not_a_continuation_of', jsonb_build_array('v1_aid_access_unrwa_aid_trucks', 'un2720_aid_daily'),
         'scope_note', 'Every truck the Chamber recorded entering Gaza, commercial and humanitarian, all crossings, by week; looted and delivered trucks for the weeks a report states them. Weeks of March to mid-May 2025 are zero by the reports'' own sentences (the crossings closed on 2 March 2025).')
  FROM source s
 WHERE s.key = 'gaza_chamber'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'gazacham_trucks_weekly');
