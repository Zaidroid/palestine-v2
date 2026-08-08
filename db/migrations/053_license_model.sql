-- 053 — a licence is more than one boolean
--
-- `commercial_use` answered one question well and hid three others. At 15
-- sources that was survivable; at 40+ it is not, and one of the three is
-- already live:
--
--   SHARE-ALIKE IS INVISIBLE. Measured 2026-08-08: 6,562 of the 184,611 rows
--   in databank_commercial (3.6%) carry a share-alike obligation — 6,548 from
--   Palestine Open Maps under ODbL-1.0, which is the entire Nakba/historical
--   corpus, and 14 UNOSAT rows under CC-BY-SA. Both are correctly marked
--   commercial: ODbL and CC-BY-SA permit commercial use. What they also
--   require is that a DERIVED DATABASE be released under the same licence —
--   and a customer reading `commercial_use = true` has no way to learn that.
--   Selling a derived database built on those rows without releasing it under
--   ODbL is a breach, and the schema was silent about it.
--
--   ATTRIBUTION WAS ASSUMED, NOT RECORDED. CC0 and Unlicense sources need no
--   credit; we give it anyway, by choice (see tech4palestine's attribution
--   text). That is a courtesy, and a courtesy stored in the same field as an
--   obligation cannot be told apart from one.
--
--   TERMS ROT AND NOTHING NOTICED. 050 read twelve sources' published terms
--   on 2026-08-05 and recorded the operative sentences IN A COMMENT. A
--   comment cannot be queried, cannot expire, and cannot tell you that the
--   other twenty-eight were never read at all.
--
-- So: three booleans that mean different things, a redistribution grade, and
-- the evidence as ROWS. `terms_evidence` carries the operative sentence — the
-- one a lawyer would point at — not a summary of it.

ALTER TABLE source
    ADD COLUMN IF NOT EXISTS share_alike          boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS attribution_required boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS redistribution       text,
    ADD COLUMN IF NOT EXISTS terms_url            text,
    ADD COLUMN IF NOT EXISTS terms_verified_at    timestamptz,
    ADD COLUMN IF NOT EXISTS terms_evidence       text;

COMMENT ON COLUMN source.share_alike IS
  'A derived database must carry the same licence. ODbL, CC-BY-SA. '
  'Compatible with commercial use and NOT implied by it.';
COMMENT ON COLUMN source.attribution_required IS
  'Credit is an OBLIGATION, not a courtesy. False for CC0/Unlicense, where '
  'we credit anyway by choice.';
COMMENT ON COLUMN source.redistribution IS
  'What we may do with the rows, as a grade rather than a boolean.';
COMMENT ON COLUMN source.terms_evidence IS
  'The operative sentence from the published terms, verbatim. Not a summary '
  '— a summary is the thing that drifts.';

DO $$ BEGIN
    ALTER TABLE source ADD CONSTRAINT source_redistribution_grade
        CHECK (redistribution IS NULL OR redistribution IN (
            'open',               -- CC0, Unlicense, our own data
            'attribution',        -- CC-BY family: redistribute, credit
            'share-alike',        -- ODbL, CC-BY-SA: redistribute, credit,
                                  --   and a derived DB inherits the licence
            'no-redistribution',  -- UN-ToU-NC, fair-use, all-rights-reserved
            'ask'));              -- terms unread, or the publisher wants a
                                  --   conversation. NEVER a default flip.
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ── grade every source from the licence it already carries ──────────────────
-- Derived, not typed by hand, so a new source with a known SPDX string is
-- graded the same way the existing forty were and cannot quietly disagree.

UPDATE source SET share_alike = true
 WHERE license_spdx LIKE 'ODbL%'
    OR license_spdx LIKE '%-SA'
    OR license_spdx LIKE '%-SA-%';

UPDATE source SET attribution_required = false
 WHERE license_spdx IN ('CC0-1.0', 'Unlicense');

UPDATE source SET redistribution = CASE
    WHEN license_spdx IN ('CC0-1.0', 'Unlicense')            THEN 'open'
    WHEN license_spdx LIKE 'ODbL%'
      OR license_spdx LIKE '%-SA'
      OR license_spdx LIKE '%-SA-%'                          THEN 'share-alike'
    WHEN license_spdx LIKE 'CC-BY%'                          THEN 'attribution'
    WHEN license_spdx IN ('UN-attribution', 'free-with-attribution',
                          'metadata-free-with-attribution',
                          'fair-use-attribution')            THEN 'attribution'
    WHEN license_spdx IN ('varies', 'verify-required', 'unknown')
                                                             THEN 'ask'
    ELSE 'no-redistribution'                                 -- the safe end
END
WHERE redistribution IS NULL;

-- A share-alike licence that is ALSO non-commercial redistributes on the
-- strictest of its two constraints. CC-BY-NC-SA-3.0-IGO (WHO) is graded by
-- the -SA branch above, which would read as more permissive than the -NC
-- reality; the NC family always wins.
UPDATE source SET redistribution = 'no-redistribution'
 WHERE license_spdx LIKE '%-NC-%' OR license_spdx LIKE '%-NC';

-- Fair-use news headlines are quoted under fair dealing, never redistributed
-- as a dataset. Explicit rather than falling through the ELSE, because this
-- is the class with the most rows and the least licence.
UPDATE source SET redistribution = 'no-redistribution', attribution_required = true
 WHERE license_spdx LIKE 'fair-use%' OR license_spdx LIKE 'copyright-fair-use%';

-- v2's OWN derived artifacts, ported from v1 (Zaid's own platform). `NONE`
-- here means "no third party's licence applies", which is the opposite of
-- what NONE means on a Telegram channel — hence naming them rather than
-- grading the string.
UPDATE source SET redistribution = 'open', attribution_required = false,
       terms_evidence = 'v2''s own derived reference data (v1 gazetteer and '
                        'checkpoint registry, Zaid''s platform). No third '
                        'party licence attaches.'
 WHERE key IN ('v1_checkpoints', 'v1_known_locations');

-- Telegram channels and crowd feeds: the messages are other people''s, we
-- hold no licence to redistribute them, and we do not.
UPDATE source SET redistribution = 'no-redistribution'
 WHERE license_spdx = 'NONE' AND key NOT IN ('v1_checkpoints',
                                             'v1_known_locations');

-- ── 050's comment block becomes queryable rows ──────────────────────────────
-- Same twelve sources, same reading, same date — now with the operative
-- sentence attached to the row it governs and a date that can expire.

UPDATE source SET
    terms_url = 'https://github.com/TechForPalestine/palestine-datasets/blob/main/LICENSE',
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = 'Unlicense: "Anyone is free to copy, modify, publish, '
                     'use, compile, sell, or distribute this software … for '
                     'any purpose, commercial or non-commercial". The '
                     'embedded "varies" was a PROVENANCE field misread '
                     '(h=MoH, c=submission), not a licence field.'
 WHERE key = 'tech4palestine';

UPDATE source SET
    terms_url = 'https://www.pcbs.gov.ps/en/reference/terms-of-use',
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = '"Editing and using for commercial or non-commercial '
                     'purposes", attribution required. Aggregates only — '
                     'Statistics Law 4/2000 Art. 17 forbids publishing '
                     'individual records.'
 WHERE key IN ('pcbs', 'pcbs_direct');

UPDATE source SET
    terms_url = 'https://data.palopenmaps.org/copyright',
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = 'ODbL-1.0. Commercial use permitted WITH SHARE-ALIKE: a '
                     'derived database must itself be ODbL. Zochrot and '
                     'PalestineRemembered layers are CREDITED, not licensed '
                     '— their ids stay provenance, never content.'
 WHERE key = 'palopenmaps';

UPDATE source SET
    terms_url = 'https://www.ochaopt.org/page/terms-use',
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = 'UN Terms of Use: personal, non-commercial, "without '
                     'any right to resell or redistribute". The HDX escape '
                     'hatch (21 OCHA-oPt datasets at CC-BY) was measured '
                     'DEAD 2026-08-06 — those datasets are not on HDX under '
                     'any name, org or topic. See db/scout/verdicts.yaml.'
 WHERE key IN ('ocha_casualties', 'ocha_demolitions');

UPDATE source SET
    terms_url = 'https://www.btselem.org/about_btselem/license_to_use',
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = 'Bespoke licence STRICTER than CC-BY-NC: bulk use is '
                     '"expansive use, which requires express written '
                     'consent". Exposure is 6 event rows.'
 WHERE key = 'btselem';

UPDATE source SET
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = '"Liberation License": purpose-conditional AND '
                     'revocable. A revocable grant can never be the basis '
                     'for commercial serving.'
 WHERE key = 'goodshepherd';

UPDATE source SET
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = 'No licence statement exists on the publisher''s site. '
                     'All rights reserved by default. Recorded as CHECKED so '
                     'nobody re-checks it, and as unlicensed so nobody serves '
                     'it.'
 WHERE key IN ('peace_now', 'hamoked');

UPDATE source SET
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = 'No statement (government bulletins). Consumed via '
                     'Tech4Palestine''s public-domain compilation rather '
                     'than directly.'
 WHERE key = 'gaza_moh';

UPDATE source SET
    terms_verified_at = '2026-08-05 00:00+00',
    terms_evidence = 'No statement. REGISTRY BUG found in the same pass: '
                     'addameer.org is NXDOMAIN; the organisation lives at '
                     'addameer.ps.'
 WHERE key = 'addameer';
