-- Gate 4 — P5.1. Can the system remember, and is the memory honest?
--
--   docker exec -i palestine-v2-db psql -U palestine -d palestine_v2 -tA \
--       < tests/test_gate4_history.sql
--
-- Tier 1's history is written into `observation`, the DATABANK's table, so that
-- tier 2 inherits it rather than rebuilding it and ARCHITECTURE's Phase 2 gate
-- — "a cross-tier query joined on place and time" — holds by construction.
-- These gates protect the properties that would rot quietly.

\echo '--- G4.1: history exists and lands in the databank table ---'
SELECT CASE WHEN count(*) > 0
            THEN 'PASS (' || count(*) || ' rows, ' ||
                 min(occurred_at)::date || ' .. ' || max(occurred_at)::date || ')'
            ELSE 'FAIL: no rolled-up history — has ops/rollup.py ever run?' END AS g4_1_exists
FROM observation o JOIN dataset d USING (dataset_id) WHERE d.key = 'tier1_daily';

\echo '--- G4.2: the rollup is idempotent ---'
-- The uniqueness constraint is the whole defence against re-running a backfill
-- and silently doubling every count. The fuel loader taught this the expensive
-- way: 762,609 duplicate rows, found only when sizing a backup.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' duplicated (place, indicator, day) keys' END AS g4_2_idempotent
FROM (
  SELECT place_id, indicator, occurred_at
    FROM observation o JOIN dataset d USING (dataset_id)
   WHERE d.key = 'tier1_daily'
   GROUP BY 1,2,3 HAVING count(*) > 1
) dup;

\echo '--- G4.3: counts are DEDUPED, not raw storage rows ---'
-- 762,609 retained duplicate fuel rows are real and stay. Counting them as
-- reports produced 59,100 "no diesel" reports for Tulkarm in a month — roughly
-- 66x the truth. Retention and honest counting are not in conflict: keep every
-- row, count every distinct thing that was SAID. If this gate fails, history is
-- confidently wrong and so is anything tier 2 builds on it.
WITH raw AS (
  SELECT count(*) AS n FROM state_observation
   WHERE state_kind = 'fuel_diesel' AND modality = 'assertion'
     AND observed_at >= CURRENT_DATE - 30 AND observed_at < CURRENT_DATE
), deduped AS (
  SELECT count(*) AS n FROM (
    SELECT DISTINCT place_id, state_kind, value, source_id, observed_at
      FROM state_observation
     WHERE state_kind = 'fuel_diesel' AND modality = 'assertion'
       AND observed_at >= CURRENT_DATE - 30 AND observed_at < CURRENT_DATE) x
), rolled AS (
  SELECT COALESCE(sum(o.value_num), 0) AS n
    FROM observation o JOIN dataset d USING (dataset_id)
   WHERE d.key = 'tier1_daily' AND o.indicator = 'fuel_diesel.reports'
     AND o.occurred_at >= CURRENT_DATE - 30
)
SELECT CASE
         WHEN (SELECT n FROM rolled) = 0 THEN 'SKIP: no fuel_diesel history yet'
         WHEN (SELECT n FROM rolled) <= (SELECT n FROM deduped) * 1.02
           THEN 'PASS (rolled ' || (SELECT n FROM rolled)::bigint
                || ' vs deduped ' || (SELECT n FROM deduped)
                || ', raw storage ' || (SELECT n FROM raw) || ')'
         ELSE 'FAIL: rollup counted ' || (SELECT n FROM rolled)::bigint
              || ' but only ' || (SELECT n FROM deduped)
              || ' distinct observations exist — duplicates are being counted'
       END AS g4_3_deduped;

\echo '--- G4.4: THE PHASE 2 GATE — cross-tier query joined on place and time ---'
-- ARCHITECTURE.md calls this "the thing that is impossible today". It is the
-- reason tier 1 history was written into `observation` rather than a private
-- table, and it must keep returning rows.
SELECT CASE WHEN count(*) > 0
            THEN 'PASS (' || count(*) || ' governorates answer a joined query)'
            ELSE 'FAIL: cross-tier query returns nothing — check admin coverage'
       END AS g4_4_cross_tier
FROM (
  SELECT g.admin2_pcode
    FROM observation o
    JOIN dataset d USING (dataset_id)
    JOIN place p ON p.place_id = o.place_id
    JOIN place g ON g.kind = 'governorate' AND g.admin2_pcode = p.admin2_pcode
   WHERE d.key = 'tier1_daily' AND o.occurred_at >= CURRENT_DATE - 30
   GROUP BY 1
) x;

\echo '--- G4.5: admin coverage stays above the tier-2 gate (60%) ---'
-- Was 26.6%, and ZERO of 235 checkpoint places carrying history had a code —
-- which is why the first cross-tier query returned an empty result while
-- looking perfectly healthy. Migration 032 derived them spatially. A new
-- unmapped source could quietly drag this back down.
SELECT CASE WHEN cov >= 0.60
            THEN 'PASS (' || round(cov * 100) || '% of places have admin2)'
            ELSE 'FAIL: admin2 coverage ' || round(cov * 100) || '%, below the 60% tier-2 gate'
       END AS g4_5_admin_coverage
-- Scoped to SERVABLE places 2026-08-07. The Nakba gazetteer added 1,953
-- Mandate-era localities as servable=false reference rows; villages depopulated
-- in 1948 have no modern admin2 code, and inventing one would be a lie about
-- geography. Including them dragged this gate to 55% while the LIVE spine —
-- the places the API actually resolves against — was unchanged. The gate
-- measures what it was written to measure: coverage of the serving spine.
FROM (SELECT count(*) FILTER (WHERE admin2_pcode IS NOT NULL)::float / count(*) AS cov
        FROM place WHERE servable) c;

\echo '--- G4.6: only COMPLETE days are frozen ---'
-- `observation` is an immutable record. A day still in progress would be
-- written and then rewritten, which is what "written once" is supposed to
-- exclude. Today is served live from state_observation instead.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' rows for today or later — a day still '
                 || 'running has been frozen and will need revising' END AS g4_6_complete_days
FROM observation o JOIN dataset d USING (dataset_id)
WHERE d.key = 'tier1_daily' AND o.occurred_at >= CURRENT_DATE;

\echo '--- G4.7: every rollup row carries provenance ---'
-- A number in the databank with no dataset and no state_kind is a number
-- nobody can audit later.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' rows without a state_kind in attrs' END AS g4_7_provenance
FROM observation o JOIN dataset d USING (dataset_id)
WHERE d.key = 'tier1_daily' AND (o.attrs->>'state_kind') IS NULL;

\echo '--- G4.8: Gaza MoH tiers are never conflated ---'
-- Daily, since-ceasefire and cumulative all use the words شهداء and إصابات. A
-- parser matching the words alone reads 73,356 as today's figure — wrong by
-- four orders of magnitude, in the direction that gets quoted. The tiers must
-- stay ordered: cumulative >= since_ceasefire >= daily, always.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' days where a tier is out of order' END AS g4_8_tiers_distinct
FROM (
  SELECT o.occurred_at,
         max(o.value_num) FILTER (WHERE o.indicator='gaza.moh.deaths.daily')            AS d,
         max(o.value_num) FILTER (WHERE o.indicator='gaza.moh.deaths.since_ceasefire')  AS sc,
         max(o.value_num) FILTER (WHERE o.indicator='gaza.moh.deaths.cumulative')       AS cu
    FROM observation o JOIN dataset ds USING (dataset_id)
   WHERE ds.key = 'gaza_moh_daily' GROUP BY 1
) t
WHERE (sc IS NOT NULL AND d  IS NOT NULL AND sc < d)
   OR (cu IS NOT NULL AND sc IS NOT NULL AND cu < sc);

\echo '--- G4.9: the daily figure reconciles against the cumulative delta ---'
-- The Ministry publishes both, so they check each other: on consecutive days
-- the change in the cumulative total should equal that day''s count. This is
-- the parser grading itself against the source, and it caught two real bugs —
-- "العدد التراكمي" being read as a section header, and a value sitting on the
-- line after its label. 90% allows for the Ministry's own revisions.
SELECT CASE
         WHEN pairs < 20 THEN 'SKIP: only ' || pairs || ' comparable day-pairs yet'
         WHEN exact::float / pairs >= 0.90
           THEN 'PASS (' || exact || '/' || pairs || ' reconcile exactly)'
         ELSE 'FAIL: only ' || exact || ' of ' || pairs || ' reconcile — the '
              || 'daily and cumulative figures disagree, so one is misparsed'
       END AS g4_9_moh_reconciles
FROM (
  SELECT count(*) pairs, count(*) FILTER (WHERE cum - prev = daily) exact
  FROM (
    SELECT dt, daily, cum, lag(cum) OVER (ORDER BY dt) prev,
           dt - lag(dt) OVER (ORDER BY dt) gap
    FROM (SELECT o.occurred_at::date dt,
                 max(o.value_num) FILTER (WHERE o.indicator='gaza.moh.deaths.daily')      daily,
                 max(o.value_num) FILTER (WHERE o.indicator='gaza.moh.deaths.cumulative') cum
            FROM observation o JOIN dataset ds USING (dataset_id)
           WHERE ds.key='gaza_moh_daily' GROUP BY 1) x
  ) y WHERE daily IS NOT NULL AND prev IS NOT NULL AND gap = 1
) z;

-- ═══ Added 2026-08-08 (Stage 5): the Mandate spine and the closure table.
-- ═══ 4,351 pre-1948 observations could be mapped as dots and aggregated by
-- ═══ nothing, because the geography they were collected under did not exist
-- ═══ in the schema.

\echo '--- G4.10: the 1945 sub-districts exist and are NOT servable ---'
-- servable=false is the whole safety property. resolve/geo.py's live capture
-- path filters on it, so a checkpoint report naming Safad today must resolve
-- exactly as it did before these rows existed.
SELECT CASE
         WHEN count(*) >= 16 AND count(*) FILTER (WHERE servable) = 0
         THEN 'PASS (' || count(*) || ' Mandate sub-districts, none servable)'
         ELSE 'FAIL: ' || count(*) || ' sub-districts, '
              || count(*) FILTER (WHERE servable) || ' of them SERVABLE — '
              || 'historical reference geography must never enter live capture'
       END AS g4_10_mandate_spine
FROM place WHERE kind = 'district_mandate';

\echo '--- G4.11: no place is contained in both geographies at one depth ---'
-- Mandate sub-districts and modern governorates are different administrative
-- geographies over overlapping ground. A locality summed into both would be
-- double-counted by any rollup that forgot to filter `relation`.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (the two geographies never mix in one rollup)'
            ELSE 'FAIL: ' || count(*) || ' place(s) have both a modern and a '
                 || 'Mandate parent at depth 1 — a rollup that forgets to '
                 || 'filter `relation` double-counts them'
       END AS g4_11_geographies_disjoint
FROM (SELECT descendant_id FROM place_closure WHERE depth = 1
      GROUP BY 1 HAVING count(DISTINCT relation) > 1) x;

\echo '--- G4.12: containment says how it was proven ---'
-- 'this locality is in Hebron because its pcode says so' and '…because its
-- point falls inside Hebron''s polygon' are different strengths of claim.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (every edge records its evidence)'
            ELSE 'FAIL: ' || count(*) || ' closure edges with no method'
       END AS g4_12_closure_evidence
FROM place_closure
WHERE established_by NOT IN ('pcode', 'st_contains', 'mandate_gazetteer');

\echo '--- G4.13: the pre-1948 record has a spatial axis ---'
-- The measurement this stage exists for. 0 before 062; a fall back to 0 means
-- the Mandate spine has been dropped or the gazetteer''s subdistrict_1945
-- field has gone the way of its gazetteer_key.
SELECT CASE WHEN n >= 2000
            THEN 'PASS (' || n || ' pre-1948 observations roll up to a 1945 '
                 || 'sub-district)'
            ELSE 'FAIL: only ' || n || ' pre-1948 observations reach a '
                 || 'Mandate container; the spine or the source field is gone'
       END AS g4_13_pre48_has_geography
FROM (SELECT count(*) AS n FROM observation o
      JOIN dataset d USING (dataset_id)
      JOIN place_closure c ON c.descendant_id = o.place_id
                          AND c.relation = 'mandate'
      WHERE d.v1_category = 'historical' AND upper_inf(o.sys_period)
        AND o.occurred_at < '1948-01-01') x;

\echo '--- G4.14: a derived geometry never claims to be a boundary ---'
-- The sub-district centroids are computed from member localities. Recording
-- that on the row is what stops one being drawn as a 1945 border.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (every derived geometry states its basis)'
            ELSE 'FAIL: ' || count(*) || ' Mandate sub-district(s) carry a '
                 || 'geometry with no geom_basis — an unlabelled derived '
                 || 'shape gets drawn as a boundary'
       END AS g4_14_derived_geometry_labelled
FROM place
WHERE kind = 'district_mandate' AND attrs->>'geom_basis' IS NULL;
