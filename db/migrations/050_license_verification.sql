-- 050 — licenses verified at their sources, corrected in both directions
--
-- Zaid delegated the verify-required reading (2026-08-05); an Opus research
-- pass read each source's PUBLISHED terms (URLs below, operative sentences
-- in ops/license-verification noted in DECISIONS). Flips are evidence-based;
-- "no statement found" stays quarantined with the finding recorded.
--
-- UPGRADES (verified more permissive than recorded):
--   tech4palestine  → Unlicense (public domain; "sell … for any purpose,
--                     commercial or non-commercial" — verbatim from
--                     github.com/TechForPalestine/palestine-datasets LICENSE).
--                     The embedded "varies" was a PROVENANCE field misread
--                     (h=MoH, c=submission…), not a license field.
--   pcbs, pcbs_direct → CC-BY-4.0 (pcbs.gov.ps/en/reference/terms-of-use:
--                     "Editing and using for commercial or non-commercial
--                     purposes", attribution required; aggregates only per
--                     Statistics Law 4/2000 Art.17).
--   palopenmaps     → ODbL-1.0 (data.palopenmaps.org/copyright). Commercial
--                     permitted WITH SHARE-ALIKE: a derived database must be
--                     ODbL. Zochrot/PalestineRemembered layers are credited,
--                     not licensed — their ids stay provenance, not content.
--
-- DOWNGRADES / CORRECTIONS (verified stricter than assumed):
--   ocha_casualties, ocha_demolitions → UN Terms of Use: personal,
--                     non-commercial, "without any right to resell or
--                     redistribute" (ochaopt.org/page/terms-use). The HDX
--                     escape hatch (21 OCHA-oPt datasets at CC-BY) is a
--                     Phase-4 re-sourcing note, not a flip.
--   btselem         → bespoke license STRICTER than CC-BY-NC: bulk use is
--                     "expansive use, which requires express written
--                     consent" (btselem.org/.../license_to_use). Recorded
--                     as LicenseRef-BTselem; exposure is 6 event rows.
--   goodshepherd    → "Liberation License": purpose-conditional AND
--                     revocable — never a basis for commercial serving.
--   peace_now, hamoked → no license statement exists on their sites;
--                     all-rights-reserved by default. Recorded as checked.
--   gaza_moh        → no statement (government bulletins); consume via
--                     T4P's public-domain compilation.
--   addameer        → no statement; REGISTRY BUG: addameer.org is NXDOMAIN,
--                     the organisation lives at addameer.ps.

UPDATE source SET license_spdx = 'Unlicense', commercial_use = true,
       attribution_text = 'Data: Tech4Palestine (data.techforpalestine.org), public domain (Unlicense); credited by choice.'
 WHERE key = 'tech4palestine';

UPDATE source SET license_spdx = 'CC-BY-4.0', commercial_use = true,
       attribution_text = 'Data: Palestinian Central Bureau of Statistics (pcbs.gov.ps), CC-BY-4.0.'
 WHERE key IN ('pcbs', 'pcbs_direct');

UPDATE source SET license_spdx = 'ODbL-1.0', commercial_use = true,
       attribution_text = 'Locality data: Palestine Open Maps (palopenmaps.org) and contributors, ODbL 1.0 — derived databases must remain ODbL.'
 WHERE key = 'palopenmaps';

UPDATE source SET license_spdx = 'UN-ToU-NC'
 WHERE key IN ('ocha_casualties', 'ocha_demolitions');

UPDATE source SET license_spdx = 'LicenseRef-BTselem'
 WHERE key = 'btselem';

UPDATE source SET license_spdx = 'LicenseRef-Liberation-License'
 WHERE key = 'goodshepherd';

UPDATE source SET license_spdx = 'no-license-found'
 WHERE key IN ('peace_now', 'hamoked', 'gaza_moh');

UPDATE source SET license_spdx = 'no-license-found',
       name = 'Addameer Prisoner Support and Human Rights Association (addameer.ps)'
 WHERE key = 'addameer';
