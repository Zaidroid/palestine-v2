-- 113 · FAO DIEM's licence, read at the publisher: CC BY 4.0 with FAO's database terms; rows released
-- 2026-10-13. Zaid's decision of that day, in his words: "this is still for testing and personal use
-- so far, so add it too". The reading is db/proposed/fao_diem.sql of 2026-10-12.
--
-- The store graded source `fao_diem` as `ask` (migration 094): HDX lists the licence as "Other" and the
-- terms had not been read, so 13,696 survey rows were held out of every partner payload. Read 2026-10-12:
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
-- TWO READINGS, AND WHICH ONE THIS IS. Redistribution with attribution is granted either way (CC BY 4.0).
-- The second FAO sentence can be read as making the rows not sellable (the cautious reading, which the
-- proposal of 12 October took), or as a ban on using the data to PROMOTE a company or to suggest FAO's
-- endorsement, which leaves the licence's own commercial permission standing. A partner payload carries
-- only rows graded commercial_use = true (serve/licence.py partner_may_carry), so under the cautious
-- reading the rows would have stayed withheld from partners. Zaid chose the second reading on
-- 2026-10-13, on the ground that the databank is for testing and personal use so far.
-- THIS IS A DECISION TO REVISIT before the first partner who is a commercial enterprise is served: what
-- such a partner may do with FAO's rows is exactly what the clause is about.
--
-- Back to the cautious reading (one statement; partners stop receiving the rows, credit stays):
--   UPDATE source SET commercial_use = false WHERE key = 'fao_diem';
-- Full rollback to 094's state:
--   UPDATE source SET license_spdx = 'LicenseRef-HDX-Other', redistribution = 'ask', commercial_use = false,
--          terms_verified_at = NULL,
--          terms_url = 'https://data.humdata.org/dataset/e9942071-bf80-4216-9175-044720b82e6f'
--    WHERE key = 'fao_diem';   -- and restore attribution_text and terms_evidence from migration 094


UPDATE source
   SET license_spdx = 'CC-BY-4.0',
       commercial_use = true,
       share_alike = false,
       attribution_required = true,
       redistribution = 'attribution',
       attribution_text = 'Household survey aggregates: FAO, Data in Emergencies Monitoring System (DIEM), via HDX. Licence: CC-BY-4.0, with FAO''s Statistical Database Terms of Use. Not to be used to promote a commercial enterprise or to suggest FAO''s endorsement.',
       terms_url = 'https://www.fao.org/contact-us/terms/db-terms-of-use/en',
       terms_verified_at = '2026-10-12T20:55:00Z',
       terms_evidence = 'Read 2026-10-12. HDX package_show, license_other: "DIEM aggregated data are made available under the Creative Commons Attribution-4.0 International license (CC BY 4.0). By using this database, you agree to be bound by the terms of this license and the FAO Statistical Database Terms of Use". FAO''s database terms: "You may access, download, create copies, adapt and re-disseminate datasets subject to these Database terms" and "Datasets shall not be used for or in conjunction with the promotion of a commercial enterprise and/or its product(s) or services". Graded attribution. Commercial use: Zaid''s decision of 2026-10-13 reads the second sentence as a ban on promotional use and endorsement, not on the licence''s own commercial permission, while the databank is for testing and personal use; to be revisited before a commercial partner is served (migration 113).'
 WHERE key = 'fao_diem';
