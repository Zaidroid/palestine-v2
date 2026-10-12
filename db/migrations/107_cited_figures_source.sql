-- 107 · a source and a dataset for figures cited from named publications
-- 2026-10-12 20:20 UTC
--
-- «العدّ / The Count» typed its historical figures into the film. The audit of
-- 2026-10-11 asked that each be held "as a dated, sourced row" so the next
-- production reads it instead of typing it. db/reference/cited_figures.yaml
-- is the file a person edits; db/mappings/cited_figures.yaml loads it.
--
-- WHAT THE GRADE SAYS. A row is one publisher's figure with a short quotation
-- and its citation: a credited fact, which migration 066 treats as reporting,
-- not redistribution. The publishers are many (UN bodies, PCBS, B'Tselem, the
-- Institute for Palestine Studies, authors), and no single licence covers
-- them, so this source is graded `attribution` (each row names its publisher
-- and document) and NOT sellable: commercial_use is false, which keeps the
-- rows out of a partner payload while the cited figure can still be said.
-- This grade is Zaid's to change.
--
-- Rollback (before any row is loaded):
--   DELETE FROM dataset WHERE key = 'cited_figures';
--   DELETE FROM source  WHERE key = 'cited_reference';
-- (with rows loaded: UPDATE source SET active = false WHERE key = 'cited_reference')

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'cited_reference', 'Cited figures (hand-entered, each with its publisher)', 'manual', 3,
       'LicenseRef-Cited-Figures', false, false, true,
       'Figures cited from named publications; each row names its publisher, its document and the day it was read.',
       'attribution',
       NULL,
       '2026-10-12T20:20:00Z',
       'Not one publisher''s data: single figures quoted with their citation from many publications (UN documents, PCBS, B''Tselem, the Institute for Palestine Studies, named authors). Each row carries publisher, document, url, quote and a verification tag (read, via_wikipedia, secondary). Graded attribution and not sellable on 2026-10-12; no publisher was asked.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'cited_reference');

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'cited_figures',
       'Cited figures: one publisher''s statement per row',
       s.source_id, 'historical', 'irregular', true,
       jsonb_build_object(
         'edited_in', 'db/reference/cited_figures.yaml',
         'scope_note', 'Hand-entered. One row is one publisher''s figure with its document, URL, sentence and the day it was read. Several publishers on one question are several rows and are never added or averaged.')
  FROM source s
 WHERE s.key = 'cited_reference'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'cited_figures');
