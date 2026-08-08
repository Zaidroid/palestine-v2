-- 054 — the licence's real grain is the DATASET, not the source
--
-- `hdx` is not a licence-holder. It is a portal, and the three datasets we
-- take through it carry three publishers' terms. Measured 2026-08-08: the
-- source row says `varies`, and that one word currently blankets 2,962 rows
-- (v1_education_hdx 2,359 and v1_infrastructure_hdx 603) whose real terms are
-- whatever the uploading organisation chose. `heritage_composite` and
-- `historical_archives` have the same shape.
--
-- It gets worse with Wave A, which is why this lands before the sources and
-- not after: IPC arrives at CC0 and WASH Cluster at CC-BY, both through
-- HDX-shaped keys. Under a source-grained model they would inherit `varies`
-- and be quarantined — or somebody would flip `hdx` to CC0 and quietly
-- relicense 2,962 unrelated rows.
--
-- So the dataset may OVERRIDE, never widen by accident: the columns are
-- nullable, NULL means "inherit the source", and every consumer reads
-- COALESCE. 048's column list and names are preserved exactly, so 049's
-- nineteen category views, 051's v_water, and every endpoint keep working
-- without knowing this happened.

ALTER TABLE dataset
    ADD COLUMN IF NOT EXISTS license_spdx         text,
    ADD COLUMN IF NOT EXISTS commercial_use       boolean,
    ADD COLUMN IF NOT EXISTS share_alike          boolean,
    ADD COLUMN IF NOT EXISTS attribution_required boolean,
    ADD COLUMN IF NOT EXISTS attribution_text     text,
    ADD COLUMN IF NOT EXISTS redistribution       text,
    ADD COLUMN IF NOT EXISTS terms_url            text,
    ADD COLUMN IF NOT EXISTS terms_verified_at    timestamptz,
    ADD COLUMN IF NOT EXISTS terms_evidence       text;

COMMENT ON COLUMN dataset.license_spdx IS
  'NULL = inherit the source. Set only when this dataset''s publisher is not '
  'the portal we fetched it through, and only with terms_evidence.';

DO $$ BEGIN
    ALTER TABLE dataset ADD CONSTRAINT dataset_redistribution_grade
        CHECK (redistribution IS NULL OR redistribution IN (
            'open', 'attribution', 'share-alike', 'no-redistribution', 'ask'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- An override that widens the source's grant without evidence is precisely
-- the failure this table exists to prevent: it would let a portal-level
-- `varies` become CC0 for one dataset because somebody was in a hurry. If
-- you know it well enough to override it, you know where you read it.
DO $$ BEGIN
    ALTER TABLE dataset ADD CONSTRAINT dataset_override_needs_evidence
        CHECK (license_spdx IS NULL
               OR (terms_evidence IS NOT NULL AND terms_url IS NOT NULL
                   AND terms_verified_at IS NOT NULL));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ── the serving surface coalesces ───────────────────────────────────────────
-- Same columns, same names, same order as 048. The only change a consumer
-- can observe is that the values are now correct at the dataset grain.

CREATE OR REPLACE VIEW databank_serving AS
SELECT o.observation_id, o.occurred_at, o.occurred_precision,
       o.indicator, o.value_num, o.value_text, o.unit,
       o.place_id, o.attrs, o.reported_at, o.sys_period,
       d.key           AS dataset_key,
       d.v1_category,
       s.key           AS source_key,
       s.name          AS source_name,
       COALESCE(d.license_spdx,         s.license_spdx)         AS license_spdx,
       COALESCE(d.commercial_use,       s.commercial_use)       AS commercial_use,
       COALESCE(d.attribution_text,     s.attribution_text)     AS attribution_text,
       -- added by 054; the three questions commercial_use could not answer
       COALESCE(d.share_alike,          s.share_alike)          AS share_alike,
       COALESCE(d.attribution_required, s.attribution_required) AS attribution_required,
       COALESCE(d.redistribution,       s.redistribution)       AS redistribution,
       COALESCE(d.terms_url,            s.terms_url)            AS terms_url,
       COALESCE(d.terms_verified_at,    s.terms_verified_at)    AS terms_verified_at
FROM observation o
JOIN dataset d ON d.dataset_id = o.dataset_id
JOIN source s  ON s.source_id  = d.source_id
WHERE o.v1_stable_id IS NOT NULL          -- the migrated databank
  AND upper_inf(o.sys_period);            -- superseded rows are as_of-only

COMMENT ON VIEW databank_serving IS
  'Free-tier databank surface: current rows only, attribution attached, '
  'licence resolved at the dataset grain (054) and falling back to the '
  'source.';
