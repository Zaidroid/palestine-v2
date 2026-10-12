-- PROPOSED, NOT APPLIED (2026-10-12). FAO DIEM's licence, read at the publisher.
--
-- The store grades source `fao_diem` as `ask` (migration 094): HDX lists the licence as "Other" and the terms had
-- not been read, so 13,696 survey rows are held out of every partner payload. They were read on 2026-10-12:
--
--   HDX's own record for the dataset (package_show, field license_other):
--     "DIEM aggregated data are made available under the Creative Commons Attribution-4.0 International license
--      (CC BY 4.0). By using this database, you agree to be bound by the terms of this license and the FAO
--      Statistical Database Terms of Use (https://www.fao.org/contact-us/terms/db-terms-of-use/en)"
--
--   FAO Statistical Database Terms of Use (that URL):
--     "You may access, download, create copies, adapt and re-disseminate datasets subject to these Database terms."
--     "Datasets shall not be used for or in conjunction with the promotion of a commercial enterprise and/or its
--      product(s) or services (s), and/or in any way that suggests that FAO endorses any specific company,
--      products [...]"
--     Citation asked: "FAO. [YYYY (year of last update)]. [Name of database: Name of dataset]. [Accessed on
--      [DD Month YYYY]]. [URL] Licence: CC-BY-4.0."
--
-- So redistribution with attribution is granted (CC BY 4.0). Commercial use is the question: CC BY 4.0 allows it,
-- and FAO's database terms forbid use "for or in conjunction with the promotion of a commercial enterprise". The
-- statement below takes the cautious reading (republish with credit; not sellable). Setting commercial_use to
-- true is the other reading, and it is Zaid's to choose.
--
-- Rollback:
--   UPDATE source SET license_spdx = 'LicenseRef-HDX-Other', redistribution = 'ask', terms_verified_at = NULL,
--          terms_url = 'https://data.humdata.org/dataset/e9942071-bf80-4216-9175-044720b82e6f'
--    WHERE key = 'fao_diem';   -- and restore attribution_text and terms_evidence from migration 094

UPDATE source
   SET license_spdx = 'CC-BY-4.0',
       commercial_use = false,
       share_alike = false,
       attribution_required = true,
       redistribution = 'attribution',
       attribution_text = 'Household survey aggregates: FAO, Data in Emergencies Monitoring System (DIEM), via HDX. Licence: CC-BY-4.0, with FAO''s Statistical Database Terms of Use.',
       terms_url = 'https://www.fao.org/contact-us/terms/db-terms-of-use/en',
       terms_verified_at = '2026-10-12T20:55:00Z',
       terms_evidence = 'Read 2026-10-12. HDX package_show, license_other: "DIEM aggregated data are made available under the Creative Commons Attribution-4.0 International license (CC BY 4.0). By using this database, you agree to be bound by the terms of this license and the FAO Statistical Database Terms of Use". FAO''s database terms: "You may access, download, create copies, adapt and re-disseminate datasets subject to these Database terms" and "Datasets shall not be used for or in conjunction with the promotion of a commercial enterprise and/or its product(s) or services". Graded attribution; held not sellable on the cautious reading of the second sentence.'
 WHERE key = 'fao_diem';
