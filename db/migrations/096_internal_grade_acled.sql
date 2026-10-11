-- 096 — The `internal` grade: held for Zaid's own analysis, served by no view (2026-10-11).
--
-- Until now every grade a source could carry (open, attribution, share-alike, ask, no-redistribution)
-- was served on the free public QUERY tier, because a credited fact is reporting. ACLED's EULA, read at
-- the publisher on 2026-08-07 (db/scout/verdicts.yaml, rejected.acled-serving), forbids exactly that:
-- "no direct access to Licensed Content; reorganizing or dashboarding is explicitly insufficient; ML/AI
-- use prohibited regardless of intent". Zaid's decision of 2026-10-11 is that the databank holds
-- everything we have fetched and the licence decides who may see a row — and for ACLED "who" is
-- nobody but him. So: a sixth grade, strictest of all, excluded from databank_serving (and so from
-- every tier built on it), listed in v_withheld with its own reason, and a source row for ACLED's
-- public monthly aggregates on HDX (db/mappings/acled_hdx.yaml, ops/fetch_acled_file.py).
--
-- serve/licence.py GRADE_ORDER gains "internal" in the same commit; the API reads grades from the
-- database at call time, so the restart is for the ranking table only.
--
-- Rollback: UPDATE source SET redistribution = 'no-redistribution' WHERE redistribution = 'internal';
--           then re-create the three constraints without 'internal' and re-run 066's two views.

ALTER TABLE source  DROP CONSTRAINT IF EXISTS source_redistribution_grade;
ALTER TABLE source  ADD  CONSTRAINT source_redistribution_grade
    CHECK (redistribution IS NULL OR redistribution IN
           ('open', 'attribution', 'share-alike', 'no-redistribution', 'ask', 'internal'));

ALTER TABLE dataset DROP CONSTRAINT IF EXISTS dataset_redistribution_grade;
ALTER TABLE dataset ADD  CONSTRAINT dataset_redistribution_grade
    CHECK (redistribution IS NULL OR redistribution IN
           ('open', 'attribution', 'share-alike', 'no-redistribution', 'ask', 'internal'));

-- 091's rule, unchanged in spirit: a dataset may NARROW its source without evidence; `internal` is the
-- narrowest there is.
ALTER TABLE dataset DROP CONSTRAINT IF EXISTS dataset_widening_needs_evidence;
ALTER TABLE dataset ADD  CONSTRAINT dataset_widening_needs_evidence CHECK (
    (commercial_use IS NOT TRUE
     AND share_alike IS NOT FALSE
     AND (redistribution IS NULL OR redistribution IN ('no-redistribution', 'ask', 'internal')))
    OR (terms_evidence IS NOT NULL AND terms_url IS NOT NULL AND terms_verified_at IS NOT NULL));

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'acled', 'ACLED — Armed Conflict Location & Event Data Project (HDX monthly aggregates)', 'api', 3,
       'LicenseRef-ACLED-EULA', false, false, true,
       'ACLED — Armed Conflict Location & Event Data Project (acleddata.com), via HDX. Held under ACLED''s Terms of Use; not served.',
       'internal',
       'https://acleddata.com/terms-of-use',
       '2026-08-07T00:00:00Z',
       'EULA read at source 2026-08-07 (scout): no direct access to Licensed Content; reorganizing or dashboarding is explicitly insufficient; building a functional substitute prohibited; ML/AI use prohibited regardless of intent. Only route to serving is a paid corporate licence. The HDX monthly aggregates carry the same Terms of Use notice. Held for personal analysis under the internal grade; never served.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'acled');

-- The free public QUERY tier now excludes `internal`. Every narrower surface (bulk, commercial, the
-- per-category views) already reads through this or applies a stricter grade list.
CREATE OR REPLACE VIEW databank_serving AS
SELECT * FROM databank_internal
 WHERE redistribution IS DISTINCT FROM 'internal';

COMMENT ON VIEW databank_serving IS
  'Free public QUERY tier: current rows, each carrying its licence, its '
  'redistribution grade and its attribution. Unfiltered by design — a query '
  'returning credited facts is reporting, not redistribution — except the '
  '`internal` grade (096), which is held for the owner''s own analysis and '
  'served by nothing. What may be BULK EXPORTED is databank_bulk, which is narrower.';

CREATE OR REPLACE VIEW v_withheld AS
SELECT i.v1_category, i.dataset_key, i.source_key, i.source_name,
       i.license_spdx, i.redistribution, i.terms_url,
       count(*)                 AS rows_held,
       min(i.occurred_at)::date AS from_date,
       max(i.occurred_at)::date AS to_date,
       p.status                 AS permission_status,
       p.letter_path,
       CASE i.redistribution
         WHEN 'ask' THEN 'the publisher''s terms have not been read; '
                         'quarantined by default rather than assumed'
         WHEN 'internal' THEN 'held for the owner''s own analysis under terms that '
                              'forbid serving it in any form; no view carries it'
         ELSE 'the publisher grants no redistribution right, or grants one '
              'that is conditional and revocable'
       END                      AS reason
FROM databank_internal i
LEFT JOIN source_permission p ON p.source_key = i.source_key
WHERE i.redistribution NOT IN ('open', 'attribution', 'share-alike')
GROUP BY 1,2,3,4,5,6,7,11,12;
