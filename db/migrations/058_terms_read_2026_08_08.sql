-- 058 — the second reading: eight commercial sources, at their publishers
--
-- G5.11 (added by Stage 4) asked a question 050 had only answered for twelve
-- sources: has anyone actually READ the terms of the data we sell? For nine
-- commercial sources serving 92,639 rows the answer was no. Their licences
-- came from v1's licenses.json via 042, and a ported guess is
-- indistinguishable from a verified fact once it sits in a column.
--
-- That distinction is not academic here. The three licences this project has
-- actually verified all moved: tech4palestine's "varies" was a PROVENANCE
-- field misread as a licence field; OCHA casualties/demolitions turned out
-- non-commercial, not CC-BY; B'Tselem turned out stricter than CC-BY-NC.
--
-- Read 2026-08-08, each at the publisher's own published statement. All
-- eight AGREED with what we had recorded — which is the good outcome and
-- still worth the hour, because "probably fine" and "checked" only look the
-- same until one of them isn't.
--
-- METHOD (db/scout/verdicts.yaml): read what a browser would render and what
-- a publisher chose to publish. Five of these were read from the
-- publisher's OWN dataset record on HDX via its documented public CKAN API —
-- that record IS the uploading organisation's licence statement for the
-- dataset we consume, which is a better authority for THIS data than a
-- generic corporate terms page.

UPDATE source SET
    terms_url = 'https://datacatalog.worldbank.org/public-licenses',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence = 'CC-BY-4.0: "allows users to copy, modify and distribute '
                     'data in any format for any purpose, including '
                     'commercial use", attribution required, no share-alike. '
                     'NOTE the page''s own wording — "CC-BY 4.0, with the '
                     'additional terms below, is the DEFAULT license for all '
                     'Datasets produced by the World Bank itself" — so this '
                     'is a per-dataset default, not a blanket grant. Exactly '
                     'the case 054''s dataset-grained override exists for if '
                     'a future World Bank series differs.'
 WHERE key = 'worldbank';

UPDATE source SET
    terms_url = 'https://data.unhcr.org/en/about',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence = '"Except where otherwise indicated, the datasets made '
                     'available by UNHCR on the Operational Data Portal are '
                     'licensed under the Creative Commons Attribution 4.0 '
                     'International Public License." Commercial use '
                     'permitted, attribution required, no share-alike.'
 WHERE key = 'unhcr';

UPDATE source SET
    terms_url = 'https://data.humdata.org/dataset/wfp-food-prices-for-state-of-palestine',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence = 'WFP''s own HDX dataset record for "State of Palestine - '
                     'Food Prices" states cc-by-igo (Creative Commons '
                     'Attribution for Intergovernmental Organisations, '
                     'creativecommons.org/licenses/by/3.0/igo/legalcode). '
                     'Commercial use permitted with attribution; no '
                     'share-alike.'
 WHERE key = 'wfp';

UPDATE source SET
    terms_url = 'https://data.humdata.org/dataset/pse-idmc-idu-events',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence = 'IDMC''s own HDX records for the oPt displacement '
                     'datasets (pse-idmc-idu-events, idmc-idp-data-pse) state '
                     'cc-by-igo. Commercial use permitted with attribution; '
                     'no share-alike.'
 WHERE key = 'idmc';

UPDATE source SET
    terms_url = 'https://data.humdata.org/dataset/pse-requirements-and-funding-data',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence = 'OCHA FTS''s own HDX record for "PSE - Requirements and '
                     'Funding Data" states cc-by-igo. Commercial use '
                     'permitted with attribution; no share-alike.'
 WHERE key = 'unfts';

UPDATE source SET
    terms_url = 'https://data.humdata.org/dataset/state-of-palestine-humanitarian-access',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence = 'OCHA oPt''s own HDX record for "State of Palestine - '
                     'Humanitarian Access" — closures, crossing points and '
                     'buffer zones, which is what this source''s 261 '
                     'land.checkpoint rows are — states cc-by. Commercial '
                     'use permitted with attribution. SEPARATE from '
                     'ocha_casualties / ocha_demolitions, which 050 verified '
                     'as UN-ToU non-commercial and which the scout confirmed '
                     'are NOT on HDX under any name: OCHA publishes some oPt '
                     'data openly and some not, and the source key is where '
                     'that distinction lives. CAVEAT: the HDX record was last '
                     'updated 2023-10-19, so it is a live licence over stale '
                     'data.'
 WHERE key = 'ocha';

UPDATE source SET
    terms_url = 'https://data.humdata.org/dataset/state-of-palestine-gaza-aid-truck-data',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence = 'UNRWA''s own HDX record for "State of Palestine - Gaza '
                     'Aid Truck Data" states cc-by. Commercial use permitted '
                     'with attribution; no share-alike. This is the licence '
                     'covering the largest commercial block in the databank '
                     '(50,059 consignment rows).'
 WHERE key = 'unrwa_aid_trucks';

UPDATE source SET
    terms_url = 'https://data.humdata.org/dataset/unosat-gaza-governorate-damage-assessment-gaza-strip',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence = 'UNOSAT''s own HDX records for the Gaza damage '
                     'assessments state cc-by-sa. SHARE-ALIKE CONFIRMED at '
                     'the publisher — a derived database must carry the same '
                     'licence, which is why 055 routes these 14 rows to '
                     'v_tier_commercial_sharealike rather than the permissive '
                     'tier.'
 WHERE key = 'unosat';

-- ── the one that could not be read ──────────────────────────────────────────
-- terms_verified_at stays NULL, deliberately: nobody has read these terms and
-- the gate must keep saying so. What IS recorded is the attempt, so the next
-- person does not spend the same hour discovering the same wall — and so the
-- decision that follows has an owner.
UPDATE source SET
    terms_url = 'https://www.imf.org/en/About/copyright-and-terms',
    terms_evidence = 'NOT VERIFIED, 2026-08-08. imf.org returns HTTP 403 to '
                     'this host on every terms path tried '
                     '(/en/About/copyright-and-terms, /external/terms.htm, '
                     'datahelp.imf.org), and the IMF publishes no HDX record '
                     'for these series. The CC-BY-4.0 currently recorded came '
                     'from v1''s licenses.json and has never been checked '
                     'against the publisher. Exposure is 474 rows in '
                     'v1_economic_imf. THIS IS A LICENCE DECISION AND '
                     'THEREFORE ZAID''S: either read the page from a browser '
                     'and record the sentence here, or quarantine the source '
                     '(commercial_use = false) until someone does. I have not '
                     'flipped it, because flipping a licence on a guess in '
                     'either direction is the thing this column exists to '
                     'prevent.'
 WHERE key = 'imf';
