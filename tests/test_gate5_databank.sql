-- Gate 5 (Tier 2, databank) — license governance assertions.
--
-- The databank serves data from ~50 upstreams whose licenses disagree about
-- commercial use. v1 kept that knowledge in a JSON file and enforced nothing;
-- these gates make the ported registry load-bearing. They run from 042
-- onward and grow with each Tier 2 phase.
\set ON_ERROR_STOP on

\echo '--- G5.1: no unverified license carries commercial_use=true ---'
-- Quarantine-by-default. 'verify-required' / 'varies' / 'unknown' are honest
-- strings meaning "a human has not read the terms"; a row that is both
-- unread and sellable is the exact lie the license filter exists to prevent.
-- Flipping one to true is a recorded human decision, never an ETL default.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' unverified-license sources marked commercial'
       END AS g5_quarantine_by_default
FROM source
WHERE commercial_use
  AND license_spdx IN ('verify-required', 'varies', 'unknown');

\echo '--- G5.2: every source can be credited ---'
-- The serving decision (2026-08-05) is free public serving WITH attribution;
-- a source without attribution text cannot be served under that decision.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' sources with empty attribution_text'
       END AS g5_attribution_present
FROM source
WHERE btrim(attribution_text) = '';

\echo '--- G5.3: the 042 port landed and DO NOTHING protected Tier 1 ---'
-- ioda existed before the port with a STRICTER reading of its terms than v1's
-- registry carried; the port must not have relaxed it. This pinned the exact
-- string CC-BY-NC-4.0 until 2026-08-08, when the terms were actually read and
-- turned out to be stricter again — IODA's API answers every request with
-- "All Rights Reserved" (067). Pinning a specific licence made a CORRECTION
-- look like a regression, so the gate now checks the property it always
-- meant: ioda stays non-commercial, is never graded more permissively than
-- `ask`, and carries the evidence for whatever it does say. A licence may
-- tighten freely; loosening one needs a reading on the record.
SELECT CASE
         WHEN (SELECT count(*) FROM source
               WHERE key IN ('worldbank', 'btselem', 'zochrot')) = 3
          AND (SELECT NOT commercial_use
                  AND redistribution IN ('ask', 'no-redistribution')
                  AND terms_evidence IS NOT NULL
               FROM source WHERE key = 'ioda')
         THEN 'PASS'
         ELSE 'FAIL: port incomplete or ioda relaxed'
       END AS g5_port_landed;

\echo '--- G5.4: non-commercial licenses are never marked sellable ---'
-- The explicit -NC- family and fair-use news. If one of these is true, the
-- filter T2.5 builds on this column sells someone else''s NC data.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' NC/fair-use sources marked commercial'
       END AS g5_nc_never_commercial
FROM source
WHERE commercial_use
  AND (license_spdx LIKE '%-NC-%'
       OR license_spdx LIKE 'fair-use%'
       OR license_spdx LIKE 'copyright-fair-use%');

\echo '--- G5.5: the commercial view can never leak a non-commercial row ---'
-- The test the whole tier decision rests on: B'Tselem, WHO, every
-- verify-required source — zero rows reachable through databank_commercial.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' non-commercial rows in the commercial view'
       END AS g5_commercial_no_leaks
FROM databank_commercial
WHERE NOT commercial_use
   OR license_spdx IN ('verify-required', 'varies', 'unknown')
   OR license_spdx LIKE '%-NC-%';

\echo '--- G5.6: every served databank row carries its attribution ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' served rows with empty attribution'
       END AS g5_serving_attribution
FROM databank_serving
WHERE btrim(attribution_text) = '';

\echo '--- G5.7: superseded rows are as_of-only, never on the default surface ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' closed-validity rows served as current'
       END AS g5_superseded_hidden
FROM databank_serving
WHERE NOT upper_inf(sys_period);

\echo '--- G5.8: the tiers are real — the commercial view is a strict subset ---'
-- If these numbers are ever equal, either every source became sellable
-- (Zaid read 24 licenses) or the filter died. Either way a human looks.
SELECT CASE
         WHEN (SELECT count(*) FROM databank_commercial)
              < (SELECT count(*) FROM databank_serving)
          AND (SELECT count(*) FROM databank_commercial) > 0
         THEN 'PASS'
         ELSE 'FAIL: commercial subset is empty or not a strict subset'
       END AS g5_strict_subset;

-- ═══ Added 2026-08-08 (Stage 4). Four things break at 40 sources that do
-- ═══ not at 15, and one of them was already live: 6,562 rows in the
-- ═══ commercial view carried a share-alike obligation nothing mentioned.

\echo '--- G5.9: no share-alike row sits in the permissive commercial tier ---'
-- The measured hole. ODbL-1.0 and CC-BY-SA permit commercial use AND require
-- a derived database to carry the same licence. A customer reading
-- `commercial_use = true` had no way to learn the second half, and that is
-- not their mistake. 6,548 Palestine Open Maps rows — the whole Mandate-era
-- gazetteer — plus 14 UNOSAT rows.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (the permissive tier carries no copyleft obligation)'
            ELSE 'FAIL: ' || count(*) || ' share-alike rows are being offered '
                 || 'as unencumbered — a buyer who builds on them and ships '
                 || 'closed is in breach, and we told them nothing'
       END AS g5_9_no_sharealike_in_permissive
FROM v_tier_commercial_permissive WHERE share_alike;

\echo '--- G5.10: every served row resolves a licence after the coalesce ---'
-- 054 made licence a dataset-grained COALESCE. A dataset whose source row was
-- deleted, or a NULL that fell through both levels, would serve rows with no
-- licence at all — which reads as permissive to anyone not looking.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (every served row knows its licence and its grade)'
            ELSE 'FAIL: ' || count(*) || ' served rows resolve to no licence '
                 || 'or no redistribution grade after COALESCE'
       END AS g5_10_licence_always_resolves
FROM databank_serving
WHERE license_spdx IS NULL OR btrim(license_spdx) = ''
   OR redistribution IS NULL;

\echo '--- G5.11: commercial sources have had their terms READ, and recently ---'
-- 050 read twelve sources at their publishers and recorded the operative
-- sentences. The rest carry licences ported from v1's registry, which was
-- itself never verified — and a ported guess is indistinguishable from a
-- verified fact once it is in a column. Terms also change: 365 days is the
-- re-read interval, and a NULL is not "fine", it is "never checked".
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (every commercial source''s terms were read within a year)'
            ELSE 'FAIL: ' || count(*) || ' commercial source(s) unverified or '
                 || 'stale: ' || string_agg(key || COALESCE(
                      ' (' || terms_verified_at::date::text || ')',
                      ' (never read)'), ', ' ORDER BY key)
       END AS g5_11_commercial_terms_verified
FROM source
WHERE commercial_use
  AND (terms_verified_at IS NULL
       OR terms_verified_at < now() - interval '365 days')
  AND EXISTS (SELECT 1 FROM databank_serving ds WHERE ds.source_key = source.key);

\echo '--- G5.12: an unlicensed source is either granted or serves nothing ---'
-- LicenseRef-* and no-license-found mean "the publisher has not given anyone
-- permission". Such a source may still be commercially served IF we hold a
-- specific, dated, unexpired grant — which is what 057's ledger is for. No
-- grant, no commercial rows. An EXPIRED grant is no grant.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (no unlicensed source is being sold without a grant)'
            ELSE 'FAIL: ' || count(*) || ' rows from unlicensed sources in a '
                 || 'commercial tier with no live grant' END
       AS g5_12_unlicensed_needs_grant
FROM (SELECT * FROM v_tier_commercial_permissive
      UNION ALL SELECT * FROM v_tier_commercial_sharealike) t
WHERE (t.license_spdx LIKE 'LicenseRef-%'
       OR t.license_spdx IN ('no-license-found', 'verify-required', 'varies',
                             'unknown'))
  AND NOT EXISTS (
        SELECT 1 FROM source_permission p
        WHERE p.source_key = t.source_key AND p.status = 'granted'
          AND (p.expires_at IS NULL OR p.expires_at >= current_date));

\echo '--- G5.13: attribution text exists wherever attribution is required ---'
-- G5.2 checks the source table; this checks what is actually SERVED, after
-- 054's coalesce, and only where credit is an obligation rather than a
-- courtesy. CC0 and Unlicense rows are exempt by right — we credit them
-- anyway, and 053 records that as a choice rather than a duty.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (every row owing credit carries it)'
            ELSE 'FAIL: ' || count(*) || ' served rows require attribution '
                 || 'and have none' END AS g5_13_attribution_where_owed
FROM databank_serving
WHERE attribution_required AND btrim(COALESCE(attribution_text, '')) = '';

\echo '--- G5.14: share-alike on a served row agrees with its grade (audit V19) ---'
-- A row that carries share-alike obligations must be graded share-alike, and a
-- share-alike grade must carry the obligation — otherwise the tier views and
-- the licence block disagree about what a partner may do with it.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (share_alike and the share-alike grade agree on every served row)'
            ELSE 'FAIL: ' || count(*) || ' served rows where share_alike and the grade disagree' END
       AS g5_14_share_alike_matches_grade
FROM databank_serving
WHERE COALESCE(share_alike, false) <> (redistribution IS NOT DISTINCT FROM 'share-alike');
