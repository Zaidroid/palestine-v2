\echo '=== GATE 6 — identity is law, and the database enforces it ==='
-- Born 2026-08-07. Two failures on one day: v1 re-hashed every stable_id and
-- the databank re-inserted 19,451 rows; the guard written to stop that then
-- silently froze five datasets, because an identity that cannot separate two
-- rows does not de-duplicate — it deletes the second one forever while the
-- run reports success.
--
-- These gates run without the loader, so they hold even if the Python guard
-- is ever bypassed, refactored, or wrong.

\echo '--- G6.1: no dataset is PARTIALLY keyed ---'
-- A whole dataset may be exempt: `collision_kind: indistinguishable` means
-- the source records genuinely different things identically (aid_access's
-- 50,059 UNRWA consignments have no per-consignment id anywhere), so no
-- unique key exists and 044 + expect.max_observations guard it instead.
--
-- What must never happen is a dataset where SOME rows carry a key and others
-- do not: that is the state a half-finished backfill or a mid-run crash
-- leaves behind, and it reads as healthy from every angle while the unkeyed
-- rows are unprotected. Expressed as a whole-dataset property so no name is
-- hardcoded and a new exempt dataset needs no gate edit.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (every dataset is fully keyed or wholly exempt)'
            ELSE 'FAIL: ' || string_agg(key || ' (' || unkeyed || ' of '
                 || total || ' rows unkeyed)', ', ')
                 || ' — partially keyed, so those rows are unguarded'
       END AS g6_1_no_partial_keying
FROM (
    SELECT d.key,
           count(*) FILTER (WHERE o.identity_key IS NULL) AS unkeyed,
           count(*) AS total
    FROM observation o
    JOIN dataset d ON d.dataset_id = o.dataset_id
    WHERE o.v1_stable_id IS NOT NULL AND upper_inf(o.sys_period)
    GROUP BY d.key
    HAVING count(*) FILTER (WHERE o.identity_key IS NULL) > 0
       AND count(*) FILTER (WHERE o.identity_key IS NOT NULL) > 0
) x;

\echo '--- G6.2: the uniqueness index exists ---'
-- If this index is ever dropped, the loader''s in-memory guard becomes the
-- only defence, and an in-memory guard cannot survive a bug in itself.
SELECT CASE WHEN count(*) = 1
            THEN 'PASS (observation_identity_uniq present)'
            ELSE 'FAIL: 052''s unique index is missing — the database can no '
                 || 'longer refuse a re-insert' END AS g6_2_index_exists
FROM pg_indexes
WHERE indexname = 'observation_identity_uniq';

\echo '--- G6.3: no two CURRENT rows of a dataset share an identity ---'
-- The index enforces this per chunk; this asserts it across the hypertable
-- as a whole, which is what a consumer actually experiences.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (identity is injective across every dataset)'
            ELSE 'FAIL: ' || count(*) || ' (dataset, identity) pairs are held '
                 || 'by more than one current row' END AS g6_3_injective
FROM (
    SELECT dataset_id, identity_key
    FROM observation
    WHERE identity_key IS NOT NULL AND upper_inf(sys_period)
    GROUP BY 1, 2 HAVING count(*) > 1
) x;

\echo '--- G6.4: no dataset is frozen (the freeze detector) ---'
-- The shape of the 2026-08-07 freeze, expressed without the loader: a healthy
-- dataset has about as many distinct identities as it has distinct source
-- records. infrastructure had 4 identities for 5,840 rows — a ratio of
-- 0.0007 — and looked fine from every other angle. Below 0.9 means rows are
-- being collapsed onto each other and the dataset can no longer grow.
-- Datasets declaring collisions are exempt by name, as in G6.1.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (no dataset is collapsing rows onto shared identities)'
            ELSE 'FAIL: ' || string_agg(key || ' (' || ratio || ')', ', ')
                 || ' — identities per row below 0.9; these datasets cannot '
                 || 'accept new rows' END AS g6_4_no_frozen_dataset
FROM (
    SELECT d.key,
           round(count(DISTINCT o.identity_key)::numeric
                 / nullif(count(*), 0), 4) AS ratio
    FROM observation o
    JOIN dataset d ON d.dataset_id = o.dataset_id
    WHERE o.identity_key IS NOT NULL AND upper_inf(o.sys_period)
    GROUP BY d.key
    HAVING count(*) > 10
       AND count(DISTINCT o.identity_key)::numeric / count(*) < 0.9
) x;

\echo '--- G6.5: superseding preserved history, it did not delete it ---'
-- The repair closed 8,057 rows'' validity rather than removing them. If a
-- future repair ever deletes instead, this is where it shows: superseded rows
-- must still be readable, and their windows must be closed, not empty.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (every superseded row keeps a valid closed window)'
            ELSE 'FAIL: ' || count(*) || ' superseded rows have an empty or '
                 || 'inverted sys_period — history was damaged, not closed'
       END AS g6_5_supersedence_is_lossless
FROM observation
WHERE NOT upper_inf(sys_period)
  AND (isempty(sys_period) OR upper(sys_period) <= lower(sys_period));
