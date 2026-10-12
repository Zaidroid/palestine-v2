-- db/proposed/who.sql — a PROPOSAL. Nothing in this file has been run.
-- Written 2026-10-12 with db/mappings/health.yaml (WHO GHO's own rows, every
-- dimension kept). It is not a migration and is not picked up by db/migrate.sh.
--
-- ── 1. NO STORED identity_key NEEDS REWRITING ───────────────────────────────
-- The 12,502 current rows of v1_health_who carry the old key
--     v1_health_who|<indicator>|<year>-01-01||<value>|<value_high>|<value_low>
-- and the new one is
--     v1_health_who|<indicator with every dimension>|<year>-01-01||<dim_key>
-- No rewrite can carry the held rows across:
--   * 4,521 of them (1,050 groups of indicator and year) lack the dimension
--     that completes the new key. It is not in the row; it can only be guessed
--     from the value, and 1,003 of those values WHO has since revised.
--   * the rest would still be superseded on the first run, because every new
--     row says more than the held one (its dimensions, its unit), and a row
--     that says something else under the same identity is a revision.
-- So the first run does it inside the loader, in ONE transaction: it closes
-- all 12,502 held rows (identity.generation: complete, with the transition
-- ceiling identity.max_absent: 12502) and writes the 13,014 rows that name
-- their dimensions. Closed rows keep their values and their sys_period.
--
-- The order, on main-server:
--     .venv/bin/python -m ops.fetch_gho_health
--     .venv/bin/python -m ops.gho_health_transition          -- read-only: what becomes of each held row
--     .venv/bin/python -m ingest.databank health --dry-run   -- must NOT say input_fallback; absent_upstream 12502
--     .venv/bin/python -m ingest.databank health
--     .venv/bin/python -m ops.load_registry --apply
-- then delete the line `max_absent: 12502` from db/mappings/health.yaml.

-- ── 2. BEFORE THE RUN (read-only) ───────────────────────────────────────────
-- expected: 12502 current rows, 12502 distinct keys, every key in the old shape
SELECT count(*)                                              AS current_rows,
       count(DISTINCT o.identity_key)                        AS keys,
       count(*) FILTER (WHERE o.attrs ? 'dim_key')           AS already_new_shape
  FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
 WHERE d.key = 'v1_health_who' AND upper_inf(o.sys_period);

-- the defect, as measured on 2026-10-12: 1050 groups holding 4521 rows
SELECT count(*) AS groups, sum(n) AS rows_in_them
  FROM (SELECT count(*) AS n
          FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
         WHERE d.key = 'v1_health_who' AND upper_inf(o.sys_period)
         GROUP BY o.indicator, o.occurred_at, o.place_id
        HAVING count(*) > 1) x;

-- ── 3. AFTER THE RUN (read-only) ────────────────────────────────────────────
-- expected: every current row names its dimensions (without_dim = 0), no
-- group of indicator and year holds two rows (0 rows), and the 12,502 rows
-- the run closed are still in the table.
SELECT count(*)                                        AS current_rows,
       count(*) FILTER (WHERE NOT o.attrs ? 'dim')     AS without_dim,
       count(*) FILTER (WHERE o.reported_at IS NULL)   AS without_vintage,
       count(*) FILTER (WHERE o.unit IS NULL)          AS without_unit
  FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
 WHERE d.key = 'v1_health_who' AND upper_inf(o.sys_period);

SELECT o.indicator, o.occurred_at, count(*)
  FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
 WHERE d.key = 'v1_health_who' AND upper_inf(o.sys_period)
 GROUP BY 1, 2 HAVING count(*) > 1 LIMIT 5;

SELECT upper(o.sys_period) AS closed_at, count(*)
  FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
 WHERE d.key = 'v1_health_who' AND NOT upper_inf(o.sys_period)
 GROUP BY 1 ORDER BY 1 DESC LIMIT 3;

-- ── 4. ROLLBACK OF THE FIRST RUN ────────────────────────────────────────────
-- The run's closes and its inserts share one timestamp: the loader closes
-- with now() and observation.sys_period defaults to tstzrange(now(), NULL),
-- both the transaction's start. Take it from the last query of section 3 and
-- put it in place of :t. The run report lists only the first 500 closed ids,
-- so the timestamp, not the list, is the handle. Nothing is deleted: the new
-- rows are closed, the old ones reopened.
--
-- BEGIN;
-- SET LOCAL statement_timeout = '60s';
-- UPDATE observation SET sys_period = tstzrange(lower(sys_period), now())
--  WHERE dataset_id = (SELECT dataset_id FROM dataset WHERE key = 'v1_health_who')
--    AND upper_inf(sys_period) AND lower(sys_period) = :t;        -- expect 13014
-- UPDATE observation SET sys_period = tstzrange(lower(sys_period), NULL)
--  WHERE dataset_id = (SELECT dataset_id FROM dataset WHERE key = 'v1_health_who')
--    AND upper(sys_period) = :t;                                  -- expect 12502
-- COMMIT;
-- and restore db/mappings/health.yaml and ingest/databank.py to the commit
-- before this branch, or the next night runs the transition again.

-- ── 5. OPTIONAL: record where WHO's terms were read (no grade is changed) ────
-- The source row `who` has no terms_url and no terms_verified_at. This writes
-- the page and the sentence; license_spdx, commercial_use and redistribution
-- are left exactly as they are. Zaid's decision.
--
-- UPDATE source
--    SET terms_url = 'https://www.who.int/about/policies/publishing/data-policy/terms-and-conditions',
--        terms_verified_at = '2026-10-12',
--        terms_evidence = 'Read 2026-10-12. WHO datasets terms: "WHO grants to you the royalty-free, worldwide, '
--          'non-exclusive right to use, reproduce, extract, download, copy, distribute, display or include the '
--          'Datasets and data contained therein in other products for public health purposes." and "Datasets shall '
--          'not be used for or in conjunction with the promotion of a commercial enterprise and/or its product(s) '
--          'or service(s)". WHO''s own HDX page for this data (data.humdata.org/dataset/who-data-for-pse) states '
--          'CC BY-NC-SA 3.0 IGO.'
--  WHERE key = 'who';
