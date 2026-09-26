-- 089 — UN DESA's World Population Prospects as a databank source (P1-B.4, the 1950s).
--
-- The databank held 5 rows for the whole 1950s. WPP 2024 carries modelled annual estimates for the State of
-- Palestine from 1950 (ops/fetch_wpp.py keeps 1950-2023, never the projections; db/mappings/population_wpp.yaml
-- loads them). This is the source row the loader requires; the spec flips to `migrate: true` once it exists.
--
-- Terms, as read on 2026-09-26: "Figures and tables in this publication can be reproduced without prior permission
-- under a Creative Commons license (CC BY 3.0 IGO)" — WPP 2024 Summary of Results, copyright page. The data portal's
-- own terms page renders client-side and could not be read; that is recorded in terms_evidence, not hidden.
--
-- Rollback: DELETE FROM source WHERE key = 'un_wpp' AND NOT EXISTS (SELECT 1 FROM dataset d
--             JOIN source s USING (source_id) WHERE s.key = 'un_wpp');
--   (with rows loaded, deactivate instead: UPDATE source SET active = false WHERE key = 'un_wpp')

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'un_wpp', 'UN DESA Population Division — World Population Prospects 2024', 'file', 4,
       'CC-BY-IGO-3.0', true, false, true,
       'United Nations, Department of Economic and Social Affairs, Population Division (2024). World Population Prospects 2024. Modelled estimates.',
       'attribution',
       'https://population.un.org/wpp/assets/Files/WPP2024_Summary-of-Results.pdf',
       '2026-09-26T09:40:00Z',
       'WPP 2024 Summary of Results, copyright page: "Figures and tables in this publication can be reproduced without prior permission under a Creative Commons license (CC BY 3.0 IGO)". The data portal''s terms page renders client-side and was not readable; the statement is the publication''s, applied to the same tables in CSV form.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'un_wpp');
