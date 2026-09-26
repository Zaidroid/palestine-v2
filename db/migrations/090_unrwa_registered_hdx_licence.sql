-- 090 — UNRWA's registered-refugee release on HDX carries its own licence (P1-B.4).
--
-- The dataset `unrwa_registered_hdx` (db/mappings/refugees_unrwa_registered.yaml) is loaded from UNRWA's
-- "UNRWA Palestine Refugees" HDX record, whose license_id is cc-by-igo (read from HDX's API on 2026-09-26).
-- Without this row the dataset inherits UNRWA's source-level licence (UN attribution, non-commercial,
-- unverified) — cautious, and wrong for this release. The dataset-grain override (054) records the licence
-- and its evidence here.
--
-- Rollback: UPDATE dataset SET license_spdx = NULL, commercial_use = NULL, share_alike = NULL,
--             attribution_required = NULL, attribution_text = NULL, redistribution = NULL, terms_url = NULL,
--             terms_verified_at = NULL, terms_evidence = NULL WHERE key = 'unrwa_registered_hdx';

INSERT INTO dataset (key, name, source_id, v1_category)
SELECT 'unrwa_registered_hdx', 'v1 refugees_unrwa_registered — unrwa', s.source_id, 'refugees'
  FROM source s WHERE s.key = 'unrwa'
ON CONFLICT (key) DO NOTHING;

UPDATE dataset
   SET license_spdx = 'CC-BY-IGO-3.0', commercial_use = true, share_alike = false,
       attribution_required = true,
       attribution_text = 'UNRWA — Palestine Refugees, via the Humanitarian Data Exchange (data.humdata.org/dataset/unrwa-palestine-refugees)',
       redistribution = 'attribution',
       terms_url = 'https://data.humdata.org/dataset/unrwa-palestine-refugees',
       terms_verified_at = '2026-09-26T10:00:00Z',
       terms_evidence = 'HDX package_show for unrwa-palestine-refugees returns license_id "cc-by-igo" (Creative Commons Attribution for Intergovernmental Organisations); the dataset page shows the same licence.'
 WHERE key = 'unrwa_registered_hdx';
