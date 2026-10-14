-- 121 · three sources with a free, keyless route (2026-10-14): WHO's attacks on health care, ILO's
-- quarterly labour figures, and the World Bank's night lights by governorate
--
-- Each is HELD FOR THE HOUSE (redistribution 'ask', commercial_use false) until Zaid grades it: a
-- licence grade is his word (his rule), and these come with open terms he has not yet seen:
--   who_ssa      the row migration 042 declared as "CC-BY-IGO via HDX", never verified and used by no
--                dataset. Read on 2026-10-14 at extranet.who.int/ssa/Index.aspx: "© World Health
--                Organization 2017, All rights reserved. ... Permission from WHO is not required for the
--                use of the Surveillance System for Attacks on Health Care dashboard material or data
--                available for download." WHO Country Offices can have records withdrawn at any time.
--   ilostat      ILO, www.ilo.org/rights-and-permissions (read 2026-10-14 through a search index; the
--                ILOSTAT site sits behind a challenge): "As of 3 May 2023, databases and datasets
--                together with the accompanying referential metadata are covered by the Creative
--                Commons CC BY 4.0 licence."
--   worldbank_space2stats  the World Bank data catalog's dataset 0066940 (Space2Stats Black Marble
--                night lights); its catalog page lists CC BY 4.0 (read by the scout on 2026-10-14, not
--                reread: the catalog API answered 429).
--
-- Rollback: DELETE FROM dataset WHERE key IN ('who_ssa_monthly','ilostat_quarterly','nightlights_monthly')
--             AND NOT EXISTS (SELECT 1 FROM observation o WHERE o.dataset_id = dataset.dataset_id);
--           DELETE FROM source WHERE key IN ('ilostat','worldbank_space2stats') AND NOT EXISTS
--             (SELECT 1 FROM dataset d WHERE d.source_id = source.source_id);
--           who_ssa's old row: license_spdx 'CC-BY-IGO', redistribution 'attribution', commercial_use true,
--             attribution 'Attacks on health care: WHO SSA via HDX (CC-BY-IGO).' (042)

UPDATE source
   SET license_spdx = 'verify-required', redistribution = 'ask', commercial_use = false,
       attribution_text = 'Attacks on health care: WHO Surveillance System for Attacks on Health Care (SSA).',
       terms_url = 'https://extranet.who.int/ssa/Index.aspx',
       terms_verified_at = '2026-10-14T15:00:00Z',
       terms_evidence = 'Read 2026-10-14 on the dashboard (#copyright): "© World Health Organization 2017, All rights reserved. ... Permission from WHO is not required for the use of the Surveillance System for Attacks on Health Care dashboard material or data available for download." WHO Country Offices can request the withdrawal of data at any time. Migration 042 graded the row CC-BY-IGO via HDX, never verified; held at ask until Zaid grades it.'
 WHERE key = 'who_ssa' AND terms_verified_at IS NULL
   AND NOT EXISTS (SELECT 1 FROM dataset d JOIN source s USING (source_id) WHERE s.key = 'who_ssa');

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'ilostat', 'ILOSTAT (International Labour Organization)', 'api', 4,
       'verify-required', false, false, true,
       'Labour statistics: ILOSTAT (ILO), from the Palestinian Central Bureau of Statistics'' Labour Force Survey.',
       'ask', 'https://www.ilo.org/rights-and-permissions', '2026-10-14T15:00:00Z',
       'Read 2026-10-14 through a search index (ilostat.ilo.org sits behind a challenge): "As of 3 May 2023, databases and datasets together with the accompanying referential metadata are covered by the Creative Commons CC BY 4.0 licence." Held at ask until Zaid grades it.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'ilostat');

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'worldbank_space2stats', 'World Bank Space2Stats — Black Marble night lights (data catalog 0066940)', 'file', 4,
       'verify-required', false, false, true,
       'Night lights: World Bank Space2Stats, from NASA''s Black Marble (VNP46A3).',
       'ask', 'https://datacatalog.worldbank.org/search/dataset/0066940', '2026-10-14T15:00:00Z',
       'The catalog page lists CC BY 4.0 (read by a scout on 2026-10-14; not reread: the catalog API answered 429). Held at ask until Zaid grades it.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'worldbank_space2stats');

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'who_ssa_monthly', 'WHO — attacks on health care in the occupied Palestinian territory, by month',
       s.source_id, 'health', 'daily', true,
       jsonb_build_object('publisher_window_from', '2017-07-06',
         'not_a_continuation_of', jsonb_build_array('insecurity_insight_incidents'),
         'scope_note', 'WHO''s surveillance of attacks on health care in the oPt, counted by month from its incident records: attacks, killed, injured, attacks by what was hit and by type (an attack under each it carries), health workers and patients abducted, arrested or detained. No West Bank / Gaza split. The newest month is partial.')
  FROM source s WHERE s.key = 'who_ssa'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'who_ssa_monthly');

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'ilostat_quarterly', 'ILO — unemployment and labour force participation in Palestine, by quarter',
       s.source_id, 'economic', 'quarterly', true,
       jsonb_build_object('publisher_window_from', '2000-01-01',
         'scope_note', 'ILO''s quarterly series from PCBS''s Labour Force Survey, by sex and age. From 2023Q4 the survey excludes the Gaza Strip (ILO note S4:6333): those quarters are series of their own, placed in the West Bank.')
  FROM source s WHERE s.key = 'ilostat'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'ilostat_quarterly');

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'nightlights_monthly', 'World Bank — night lights by governorate and month (Black Marble)',
       s.source_id, 'infrastructure', 'irregular', true,
       jsonb_build_object('publisher_window_from', '2012-01-01',
         'scope_note', 'The sum and the mean of night-time radiance per governorate and month, 2012 onward, from yearly files the World Bank releases about February of the next year.')
  FROM source s WHERE s.key = 'worldbank_space2stats'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'nightlights_monthly');
