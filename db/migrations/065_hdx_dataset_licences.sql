-- 065 — `varies` was a shrug, and behind it were two open licences
--
-- Zaid, 2026-08-08: the project is going OPEN SOURCE, for a small circle, and
-- non-commercial. That changes what matters. It does NOT relax the licence
-- work — ODbL's share-alike binds any public distribution of a derived
-- database whether or not money changes hands, so the 6,548 Palestine Open
-- Maps rows matter MORE once the repo is public, not less. And it makes the
-- unread terms worth reading rather than worth deleting.
--
-- 2,962 rows sat behind the source-level `varies` on `hdx`, which is not a
-- licence at all — it is the honest admission that a PORTAL does not have
-- one. Read at the publisher today, through HDX's own CKAN API:
--
--   education     → "State of Palestine - West Bank schools", OCHA oPt,
--                   cc-by. 2,359 rows.
--   infrastructure→ "State of Palestine Closures Barriers", OCHA oPt,
--                   cc-by-igo. 603 rows (261 barrier segments + 342
--                   locality records).
--
-- Both fully redistributable with attribution. So the fix for 2,962 rows on
-- the wrong side of the line is three UPDATE statements, not a deletion —
-- which is the whole reason 054 put licence at the dataset grain instead of
-- leaving a portal to speak for its publishers.
--
-- This is the third time OCHA oPt has turned out to publish openly on HDX
-- while a different OCHA dataset is UN-ToU non-commercial. The verdict in
-- db/scout/verdicts.yaml now says it plainly: OCHA publishes some oPt data
-- openly and some not, and which is which is a per-dataset fact.

UPDATE dataset SET
    license_spdx      = 'CC-BY-4.0',
    commercial_use    = true,
    share_alike       = false,
    attribution_required = true,
    redistribution    = 'attribution',
    attribution_text  = 'School register: OCHA occupied Palestinian territory '
                        '(source UNICEF Jerusalem) via HDX, CC-BY.',
    terms_url         = 'https://data.humdata.org/dataset/'
                        'state-of-palestine-west-bank-schools',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence    = 'OCHA oPt''s own HDX record for "State of Palestine - '
                        'West Bank schools" states cc-by (Creative Commons '
                        'Attribution International). Dataset notes: "schools '
                        'in the West Bank, source UNICEF in Jerusalem, '
                        'Palestine". Read via the HDX CKAN API 2026-08-08. '
                        'This OVERRIDES the source-level `varies` on hdx, '
                        'which is a portal and holds no licence of its own.'
 WHERE key = 'v1_education_hdx';

UPDATE dataset SET
    license_spdx      = 'CC-BY-IGO-3.0',
    commercial_use    = true,
    share_alike       = false,
    attribution_required = true,
    redistribution    = 'attribution',
    attribution_text  = 'Closures and barriers: OCHA occupied Palestinian '
                        'territory via HDX, CC-BY-IGO 3.0.',
    terms_url         = 'https://data.humdata.org/dataset/'
                        'occupied-palestinian-territory-closures-barriers',
    terms_verified_at = '2026-08-08 00:00+00',
    terms_evidence    = 'OCHA oPt''s own HDX record for "State of Palestine '
                        'Closures Barriers" states cc-by-igo '
                        '(creativecommons.org/licenses/by/3.0/igo/legalcode). '
                        'Dataset notes: "Closures, Barriers in the occupied '
                        'Palestinian territory." Read via the HDX CKAN API '
                        '2026-08-08. Overrides the portal-level `varies`.'
 WHERE key = 'v1_infrastructure_hdx';

-- The third HDX dataset holds no rows, so there is nothing to grade and
-- nothing to guess. Left at the portal default deliberately: an override
-- asserted without reading would be the exact failure 054's evidence
-- constraint exists to prevent.
