-- Enforces ARCHITECTURE §3.10 / standing rule 2b: no data loss.
--
-- Documentation does not stop a future session from adding
-- `add_retention_policy('claim', INTERVAL '90 days')` to make a disk-space
-- problem go away. This test does. Run it in CI and after every migration.
--
--   docker exec -i palestine-v2-db psql -U palestine -d palestine_v2 \
--       -f - < tests/test_no_data_loss.sql
\set ON_ERROR_STOP on

\echo '--- T1: no retention policy on any OBSERVATION hypertable ---'
-- policy_job_stat_history_retention is TimescaleDB's own internal
-- job-execution log cleanup (hypertable_name IS NULL). It touches no data of
-- ours and is expected. Anything attached to a real table is not.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: retention policy on ' || string_agg(hypertable_name, ', ')
       END AS t1_no_retention
FROM timescaledb_information.jobs
WHERE proc_name LIKE '%retention%'
  AND hypertable_name IS NOT NULL;

\echo '--- T2: the observation tables exist and are hypertables ---'
SELECT CASE WHEN count(*) = 3 THEN 'PASS'
            ELSE 'FAIL: expected 3 hypertables, found ' || count(*)
       END AS t2_hypertables
FROM timescaledb_information.hypertables
WHERE hypertable_name IN ('claim', 'state_observation', 'observation');

\echo '--- T3: no DELETE/TRUNCATE rule or trigger on observation tables ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' delete/truncate trigger(s) found'
       END AS t3_no_delete_triggers
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal
  AND c.relname IN ('claim', 'observation', 'state_observation', 'event')
  AND (t.tgtype & 8) <> 0;   -- bit 3 = DELETE

\echo '--- T4: event corrections SUPERSEDE, they do not remove claims ---'
-- Regression guard for the model itself: retracting an event must leave the
-- underlying claims intact, because "this source said X and was wrong" is the
-- training signal Loop A depends on.
BEGIN;
INSERT INTO source (key,name,kind,license_spdx,commercial_use,attribution_text,authority_rank)
VALUES ('_ndl_test','t','telegram','CC0-1.0',true,'t',5) RETURNING source_id \gset s_
INSERT INTO place (kind,name_en,geom)
VALUES ('locality','T',ST_SetSRID(ST_MakePoint(35.2,32.2),4326)) RETURNING place_id \gset p_
INSERT INTO event (event_type,place_id,confidence,claim_count,independent_sources)
VALUES ('t',:p_place_id,0.5,1,1) RETURNING event_id \gset e_
INSERT INTO claim (source_id,raw_ref,raw_text,claim_type,place_id,reported_at,event_id)
VALUES (:s_source_id,'bronze://t','x','t',:p_place_id,now(),:e_event_id);

UPDATE event SET status='retracted', correction_note='wrong' WHERE event_id=:e_event_id;

SELECT CASE WHEN (SELECT count(*) FROM claim WHERE event_id=:e_event_id) = 1
             AND (SELECT status FROM event WHERE event_id=:e_event_id) = 'retracted'
             AND (SELECT count(*) FROM event_history WHERE event_id=:e_event_id) >= 1
            THEN 'PASS'
            ELSE 'FAIL: retraction destroyed the claim or lost the prior version'
       END AS t4_retract_preserves;
ROLLBACK;

\echo '--- T5: compression is permitted (it keeps rows queryable) ---'
SELECT 'INFO: ' || count(*) || ' compression policies (allowed; retention is not)' AS t5_compression
FROM timescaledb_information.jobs
WHERE proc_name LIKE '%compression%';
