-- 067 — the two connectivity sources' terms, READ at the publisher.
--
-- Found while scoping the Stage 7 cut for `connectivity`. Before writing a
-- fetcher that pulls from a publisher directly, the question "may we" has to
-- be answered from the publisher's own words rather than from the guess in
-- our table — and both guesses were wrong, in opposite directions.
--
-- Neither row had `terms_url`, `terms_verified_at` or `terms_evidence`. That
-- is the tell 053 was built to expose: a licence nobody read is a licence
-- nobody can defend, however confident the SPDX string looks.
--
--   OONI   recorded free-with-attribution, share_alike FALSE
--          ACTUALLY CC-BY-NC-SA-4.0. ooni.org/about/data-policy points at
--          "the license under which the data is released, see
--          github.com/ooni/license/data", and that file says in one sentence:
--          "This work is licensed under a Creative Commons
--          Attribution-NonCommercial-ShareAlike 4.0 International License".
--          The NC half we already had right (commercial_use false). The SA
--          half we did not, and share-alike is the half that binds an open
--          release: 1,276 rows carrying a copyleft obligation the tier
--          machinery could not see, because the column said FALSE.
--
--   IODA   recorded CC-BY-NC-4.0, an assumption with no evidence behind it.
--          ACTUALLY All Rights Reserved. IODA states its own terms in every
--          single API response, in a top-level `copyright` field: "This data
--          is Copyright (c) 2021-2025 Georgia Tech Research Corporation. All
--          Rights Reserved." A machine-readable statement from the publisher
--          on the very endpoint we would fetch from is the strongest evidence
--          available, and it grants nothing.
--
-- WHAT CHANGES, AND WHAT DOES NOT. Both sources stay QUERYABLE — 066's line
-- is that returning a credited fact is reporting, not redistributing, and
-- that argument is untouched by either correction. What changes is the bulk
-- release: IODA's 1,000 rows leave `databank_bulk` and appear in
-- `v_withheld` with the publisher's own sentence as the reason, and OONI's
-- 1,276 rows are now correctly counted as share-alike, which is what keeps
-- ops/export_open_data.py from folding them into an incompatible aggregate.
--
-- IODA IS ASKABLE, not closed: it is an academic research project that
-- publishes an open API and asks to be cited. That is a letter, not a wall —
-- the same posture the IMF got in 063.

BEGIN;

UPDATE source SET
  license_spdx        = 'CC-BY-NC-SA-4.0',
  share_alike         = TRUE,
  attribution_required= TRUE,
  commercial_use      = FALSE,
  redistribution      = 'share-alike',
  attribution_text    = 'Censorship measurements: OONI (ooni.org), '
                        'CC-BY-NC-SA-4.0.',
  terms_url           = 'https://github.com/ooni/license/blob/master/data/'
                        'LICENSE.md',
  terms_verified_at   = DATE '2026-08-08',
  terms_evidence      = 'Read 2026-08-08 at the licence file ooni.org/about/'
    'data-policy names: "This work is licensed under a Creative Commons '
    'Attribution-NonCommercial-ShareAlike 4.0 International License '
    '(http://creativecommons.org/licenses/by-nc-sa/4.0/)." Corrects '
    'free-with-attribution + share_alike FALSE, which understated a copyleft '
    'obligation on 1,276 rows.'
WHERE key = 'ooni';

UPDATE source SET
  license_spdx        = 'LicenseRef-IODA-All-Rights-Reserved',
  share_alike         = FALSE,
  attribution_required= TRUE,
  commercial_use      = FALSE,
  redistribution      = 'ask',
  attribution_text    = 'Internet outage detection: IODA, Georgia Tech '
                        'Internet Intelligence Lab. Copyright (c) 2021-2025 '
                        'Georgia Tech Research Corporation.',
  terms_url           = 'https://api.ioda.inetintel.cc.gatech.edu/v2/entities/'
                        'query?entityType=country&entityCode=PS',
  terms_verified_at   = DATE '2026-08-08',
  terms_evidence      = 'Read 2026-08-08 from IODA''s own API, which returns '
    'a top-level copyright field on every response: "This data is Copyright '
    '(c) 2021-2025 Georgia Tech Research Corporation. All Rights Reserved." '
    'No grant of any kind is stated, so redistribution is ask rather than '
    'attribution. NOT a closed door: IODA is an academic project publishing '
    'an open API and asking to be cited, so this is a letter (see '
    'db/scout/letters/ioda.md). CC-BY-NC-4.0 was an assumption recorded with '
    'no terms_url and no evidence — exactly what 053''s evidence columns '
    'exist to make visible.'
WHERE key = 'ioda';

-- AND ONE MORE, FOUND BY THE FIRST. Grading OONI `share-alike` made a test
-- fail that asserted every CC-BY-NC* source is graded `attribution` — and the
-- test was half right. 064's rule is that NC forbids COMMERCIAL
-- redistribution, not redistribution; it is not that every NC licence is
-- plain attribution. The SA variants carry a copyleft on top, and WHO's
-- CC-BY-NC-SA-3.0-IGO was sitting at `attribution` with `share_alike = TRUE`:
-- two columns disagreeing about the same 12,577 rows. The row count was
-- always right because the tier views read `share_alike`, so nothing served
-- wrongly — but a grade that contradicts its own flag is one refactor away
-- from doing so.
UPDATE source SET
  redistribution = 'share-alike',
  terms_evidence = COALESCE(terms_evidence || ' ', '') ||
    'Grade corrected 2026-08-08 from attribution to share-alike: the licence '
    'is CC-BY-NC-SA and share_alike was already TRUE, so the two columns '
    'disagreed. Found when OONI''s terms were read and the NC-family test '
    'refused the share-alike grade.'
WHERE key = 'who' AND share_alike AND redistribution = 'attribution';

-- No source may claim a copyleft in one column and deny it in another.
DO $$
DECLARE n INT;
BEGIN
  SELECT count(*) INTO n FROM source
   WHERE share_alike AND redistribution <> 'share-alike';
  IF n > 0 THEN
    RAISE EXCEPTION '067: % share-alike source(s) are not graded share-alike',
                    n;
  END IF;
END $$;

-- A licence read is worth nothing if the row it should have produced is
-- missing. Both must now carry evidence, or this migration failed.
DO $$
DECLARE n INT;
BEGIN
  SELECT count(*) INTO n FROM source
   WHERE key IN ('ooni', 'ioda')
     AND (terms_evidence IS NULL OR terms_verified_at IS NULL
          OR terms_url IS NULL);
  IF n > 0 THEN
    RAISE EXCEPTION '067: % connectivity source(s) still carry no evidence', n;
  END IF;
END $$;

COMMIT;

-- The thirteenth letter. IODA is askable, so the ledger says so — a source
-- whose rows we hold back should never sit in `no-redistribution` silently
-- when there is a published address and a research group that asks to be
-- cited. Sends stay Zaid's; this row moves to `asked` only when he sends.
BEGIN;
INSERT INTO source_permission (source_key, status, scope, contact, letter_path,
                               notes)
VALUES ('ioda', 'not_asked',
        'redistribute the 1,000 IODA outage records held for Palestine, the '
        'Gaza Strip and the West Bank in a public non-commercial data release',
        'https://ioda.inetintel.cc.gatech.edu/', 'db/scout/letters/ioda.md',
        'Raised 2026-08-08 when the terms were read: IODA''s API states All '
        'Rights Reserved on every response. Rows stay QUERYABLE with '
        'attribution (066''s query-vs-bulk line) and leave the bulk export '
        'until this is answered.')
ON CONFLICT (source_key) DO NOTHING;
COMMIT;
