-- PROPOSED, NOT APPLIED. A licence grade is Zaid's decision; this file is not under db/migrations/
-- and db/migrate.sh does not see it. To apply it, copy it to the next migration number.
--
-- UCDP's terms, read at the publisher on 2026-10-12 (source `ucdp`, dataset `v1_conflict_ucdp`).
--
-- WHAT THE STORE SAYS TODAY (read from production on 2026-10-12, read-only):
--   source  ucdp              license_spdx 'CC-BY-IGO', commercial_use true, share_alike false,
--                             attribution_required true, redistribution 'attribution',
--                             attribution_text 'Conflict events: UCDP GED, Uppsala University.',
--                             terms_url NULL, terms_verified_at NULL, terms_evidence NULL
--   dataset v1_conflict_ucdp  commercial_use false, attrs.commercial_withheld_083 set (migration 083:
--                             "a licence nobody has read is not sold"); every other licence column NULL
--   so the 7,638 served rows read CC-BY-IGO, non-commercial, terms unverified, and gate G5.11
--   (tests/test_gate5_databank.sql) fails on `ucdp (never read)`.
--
-- WHAT THE PUBLISHER SAYS:
--   1. https://ucdp.uu.se/downloads/ (the page's HTTP Last-Modified is 2026-09-20), first paragraph:
--        "All datasets are free of charge and licensed under CC BY 4.0 — you are free to use and
--         redistribute them provided you cite the relevant publications listed with each dataset."
--      "CC BY 4.0" links to https://creativecommons.org/licenses/by/4.0/. The page lists both the GED
--      release and the Candidate Events Dataset, so the sentence covers both.
--   2. UCDP's FAQ, https://www.uu.se/en/department/peace-and-conflict-research/research/ucdp/frequently-asked-questions
--      (last modified 2026-05-06), under "What are the terms and conditions for using UCDP data?":
--        "Except where otherwise noted, content on this site is licensed under a Creative Commons
--         Attribution 4.0 International license (CC BY 4.0)"
--      and under "How do I cite UCDP data?":
--        "The preferred citation is listed for each dataset available on the UCDP Dataset Download Center."
--   3. The GED codebook, https://ucdp.uu.se/downloads/ged/ged261.pdf: it carries NO licence statement.
--      It says "All formats are available for download free of charge (no registration required)" and
--      "When using this data, please always cite: Sundberg, Ralph, and Erik Melander, 2013 ...".
--   4. Commercial use. No UCDP page uses the word. The permission is the licence's own: CC BY 4.0 lets
--      anyone "copy and redistribute the material in any medium or format for any purpose, even
--      commercially" and "remix, transform, and build upon the material for any purpose, even
--      commercially", on the condition of attribution (creativecommons.org/licenses/by/4.0/, the deed).
--
-- WHERE 'CC-BY-IGO' CAME FROM. v1 took UCDP through HDX's country extract "ucdp-data-for-israel", and
-- HDX's record carries license_id "cc-by-igo" (HDX package_show, read 2026-10-12). That is HDX's label
-- on its copy. UCDP is a university programme, not an intergovernmental organisation, and states
-- CC BY 4.0 for all its datasets. Both licences allow commercial use with attribution, so the
-- commercial flag was right and the variant was wrong (docs/DECISIONS.md already noted this).
--
-- THE API IS NOT PART OF THIS. https://ucdpapi.pcr.uu.se/ answers 401 "API token required" and a token
-- is requested by e-mail from its maintainer. ops/fetch_ucdp.py reads the public bulk files only; no
-- token was requested.

BEGIN;

UPDATE source
   SET license_spdx = 'CC-BY-4.0',
       commercial_use = true,                 -- unchanged; now on a read licence
       share_alike = false,                   -- unchanged
       attribution_required = true,           -- unchanged
       redistribution = 'attribution',        -- unchanged
       attribution_text = 'Conflict events: UCDP Georeferenced Event Dataset (GED) and UCDP Candidate '
                          'Events Dataset, Uppsala Conflict Data Program, Uppsala University '
                          '(ucdp.uu.se), licensed CC BY 4.0. Sundberg & Melander (2013), Journal of '
                          'Peace Research 50(4); Davies, Pettersson & Öberg (2026), Journal of Peace '
                          'Research; candidate events: Hegre, Croicu, Eck & Högbladh (2020), '
                          'Research & Politics.',
       terms_url = 'https://ucdp.uu.se/downloads/',
       terms_verified_at = '2026-10-12 00:00+00',
       terms_evidence = 'Read at the publisher on 2026-10-12. ucdp.uu.se/downloads/: "All datasets '
                        'are free of charge and licensed under CC BY 4.0 — you are free to use and '
                        'redistribute them provided you cite the relevant publications listed with '
                        'each dataset." UCDP FAQ (uu.se, last modified 2026-05-06): "Except where '
                        'otherwise noted, content on this site is licensed under a Creative Commons '
                        'Attribution 4.0 International license (CC BY 4.0)". The GED codebook 26.1 '
                        'states no licence, only free download and the citation. Commercial use is '
                        'not named by UCDP; it is permitted by CC BY 4.0 itself ("for any purpose, '
                        'even commercially"), with attribution. The earlier CC-BY-IGO was the label '
                        'on HDX''s copy (license_id cc-by-igo), which v1 fetched. The API needs a '
                        'token requested by e-mail; only the public bulk files are read.'
 WHERE key = 'ucdp';

-- Rollback (exact):
--   UPDATE source
--      SET license_spdx = 'CC-BY-IGO', commercial_use = true, share_alike = false,
--          attribution_required = true, redistribution = 'attribution',
--          attribution_text = 'Conflict events: UCDP GED, Uppsala University.',
--          terms_url = NULL, terms_verified_at = NULL, terms_evidence = NULL
--    WHERE key = 'ucdp';

COMMIT;

-- THE SECOND SWITCH, LEFT OFF. The statement above records the reading and turns gate G5.11 green. It
-- does NOT make a single UCDP row commercial: the served grade is COALESCE(dataset, source), and
-- migration 083 set the dataset's own commercial_use to false until the terms were read. Releasing
-- that is the actual decision, and it is one statement:
--
--   UPDATE dataset
--      SET commercial_use = NULL,
--          attrs = (attrs - 'commercial_withheld_083') || jsonb_build_object('commercial_released',
--                  'UCDP terms read at the publisher 2026-10-12: CC BY 4.0 (db/proposed/ucdp.sql)')
--    WHERE key = 'v1_conflict_ucdp';
--   -- rollback: UPDATE dataset SET commercial_use = false,
--   --   attrs = (attrs - 'commercial_released') || jsonb_build_object('commercial_withheld_083',
--   --   'UCDP terms have not been read at the publisher (terms_verified_at NULL); served '
--   --   'non-commercial until a human records the licence sentence (PLAN P1-B.1, G5.11)')
--   --   WHERE key = 'v1_conflict_ucdp';
--
-- If it is released, tests/test_held_events.py line 108 ("G5.11: unread terms, not sold": zero UCDP
-- rows in v_tier_commercial_permissive) states the old rule and has to be rewritten with it.
