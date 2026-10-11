-- 094 — The fragments, second batch (Zaid, 2026-10-11): a source row for FAO's Data in Emergencies
-- Monitoring System (db/mappings/fao_diem.yaml, ops/fetch_fao_diem.py). UNHCR's six HDX tables
-- (db/mappings/unhcr_population.yaml) load under the existing `unhcr` source row and need no change.
--
-- Terms, as read on 2026-10-11 through HDX's CKAN API (package e9942071-bf80-4216-9175-044720b82e6f,
-- organisation "Food and Agriculture Organization (FAO) of the United Nations", last modified 2026-10-11):
-- license_title "Other", license_id hdx-other. FAO's own DIEM terms were NOT read, so the row is `ask`,
-- commercial_use = false, share_alike unknown (false), and terms_verified_at records what was read, not a
-- verdict. Public tier serves with attribution; partner and bulk tiers withhold (v_withheld).
--
-- Rollback: DELETE FROM source WHERE key = 'fao_diem' AND NOT EXISTS (SELECT 1 FROM dataset d
--             JOIN source s USING (source_id) WHERE s.key = 'fao_diem');
--           (with rows loaded, deactivate instead: UPDATE source SET active = false WHERE key = 'fao_diem')

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'fao_diem', 'FAO Data in Emergencies Monitoring System (DIEM) — household surveys', 'api', 4,
       'LicenseRef-HDX-Other', false, false, true,
       'Household survey aggregates: FAO Data in Emergencies Monitoring System (DIEM) via HDX. Licence listed as "Other" on HDX; FAO''s terms apply.',
       'ask',
       'https://data.humdata.org/dataset/e9942071-bf80-4216-9175-044720b82e6f',
       '2026-10-11T12:30:00Z',
       'HDX CKAN package_show on 2026-10-11: license_title "Other", license_id hdx-other, organisation FAO. The DIEM portal''s own terms page was not read; redistribution is therefore "ask" until it is.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'fao_diem');
