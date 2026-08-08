-- 066 — the filter goes where the risk is: BULK, not query
--
-- Zaid, 2026-08-08: the project is going open source, for a small circle,
-- non-commercial. That does not relax the licence work — ODbL's share-alike
-- binds any public distribution of a derived database whether money changes
-- hands or not, so the 6,548 Palestine Open Maps rows matter MORE once a
-- repo is public. It sharpens the question of WHERE the licence line falls.
--
-- 2,602 rows (1.27%) are graded not-redistributable or terms-unread, after
-- reading 2,962 others down from `varies` to CC-BY at the publisher (065).
-- The first draft of this migration simply removed them from
-- databank_serving. That was wrong, and the measurement said so: it took
-- FIVE CATEGORIES completely dark — demolitions (847), prisoners (890),
-- culture (329), casualties (49), settlements (51) — which is most of what a
-- Palestine databank exists to hold.
--
-- THE DISTINCTION THAT MATTERS is not commercial vs free. It is:
--
--   REDISTRIBUTING A DATABASE — a bulk export, a CSV of the whole table, a
--   data dump in an open-source repo. This is what a licence governs, and
--   this is where an all-rights-reserved source must not appear.
--
--   REPORTING A FACT WITH ATTRIBUTION — a query returning twenty demolition
--   records for Hebron, each crediting OCHA and linking their terms. This is
--   much closer to what HaMoked, Peace Now, Addameer and OCHA publish these
--   numbers IN ORDER TO make happen.
--
-- So the filter lands on the bulk path and not on the query path. That is
-- also the shape of the sources' own terms: the IMF's general terms permit
-- "non-systematic" access and forbid systematic download; OCHA's forbid
-- resale and redistribution, not citation.
--
-- NOT A FINAL LEGAL POSITION, and it should not be read as one. Zaid's
-- standing rule is "lawyer before ads"; this migration is written so that
-- one page describes the whole policy and a lawyer can overturn it by
-- changing one WHERE clause. Everything remains queryable either way —
-- nothing is deleted, ever.

-- Everything current and migrated. Unchanged in extent from 048/054; renamed
-- in intent so the next reader knows this is the corpus, not the product.
CREATE OR REPLACE VIEW databank_internal AS
SELECT o.observation_id, o.occurred_at, o.occurred_precision,
       o.indicator, o.value_num, o.value_text, o.unit,
       o.place_id, o.attrs, o.reported_at, o.sys_period,
       d.key AS dataset_key, d.v1_category,
       s.key AS source_key, s.name AS source_name,
       COALESCE(d.license_spdx,         s.license_spdx)         AS license_spdx,
       COALESCE(d.commercial_use,       s.commercial_use)       AS commercial_use,
       COALESCE(d.attribution_text,     s.attribution_text)     AS attribution_text,
       COALESCE(d.share_alike,          s.share_alike)          AS share_alike,
       COALESCE(d.attribution_required, s.attribution_required) AS attribution_required,
       COALESCE(d.redistribution,       s.redistribution)       AS redistribution,
       COALESCE(d.terms_url,            s.terms_url)            AS terms_url,
       COALESCE(d.terms_verified_at,    s.terms_verified_at)    AS terms_verified_at
FROM observation o
JOIN dataset d ON d.dataset_id = o.dataset_id
JOIN source s  ON s.source_id  = d.source_id
WHERE o.v1_stable_id IS NOT NULL AND upper_inf(o.sys_period);

COMMENT ON VIEW databank_internal IS
  'Every current migrated row. The corpus, not the product.';

-- The QUERY surface. Extent unchanged: a credited fact answering a question
-- is not a redistributed database. Every row carries its grade so a consumer
-- can see what it may then do with it.
CREATE OR REPLACE VIEW databank_serving AS
SELECT * FROM databank_internal;

COMMENT ON VIEW databank_serving IS
  'Free public QUERY tier: current rows, each carrying its licence, its '
  'redistribution grade and its attribution. Unfiltered by design — a query '
  'returning credited facts is reporting, not redistribution. What may be '
  'BULK EXPORTED is databank_bulk, which is narrower.';

-- The BULK surface. Exports, dumps, and anything that ships inside an
-- open-source repository read THIS.
CREATE OR REPLACE VIEW databank_bulk AS
SELECT * FROM databank_internal
WHERE redistribution IN ('open', 'attribution', 'share-alike');

COMMENT ON VIEW databank_bulk IS
  'What may leave as a DATABASE: exports, dumps, the open-source data '
  'release. Excludes sources that grant no redistribution right and sources '
  'whose terms nobody has read. 2,602 rows at 2026-08-08 — enumerated in '
  'v_withheld, never silently absent. NOTE for any open-source release: this '
  'still contains 6,562 ODbL and CC-BY-SA rows, whose share-alike travels '
  'with a derived database regardless of price.';

-- What bulk withholds, and why, and what has been asked about it.
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
         ELSE 'the publisher grants no redistribution right, or grants one '
              'that is conditional and revocable'
       END                      AS reason
FROM databank_internal i
LEFT JOIN source_permission p ON p.source_key = i.source_key
WHERE i.redistribution NOT IN ('open', 'attribution', 'share-alike')
GROUP BY 1,2,3,4,5,6,7,11,12;

COMMENT ON VIEW v_withheld IS
  'Held, and excluded from bulk export, counted by reason. An export that is '
  'quietly short reads as "no data exists" — the exact lie v1''s silent '
  'failures told for 57 days.';
