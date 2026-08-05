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
-- ioda existed before the port with a STRICTER reading of its terms
-- (CC-BY-NC-4.0, non-commercial) than v1's registry carried; the port must
-- not have relaxed it. And the port itself must be present — spot keys from
-- each class: a UN portal, a non-commercial NGO, and an audit-discovered
-- source licenses.json never registered.
SELECT CASE
         WHEN (SELECT count(*) FROM source
               WHERE key IN ('worldbank', 'btselem', 'zochrot')) = 3
          AND (SELECT license_spdx = 'CC-BY-NC-4.0' AND NOT commercial_use
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
