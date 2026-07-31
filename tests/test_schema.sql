-- Gate 0 schema verification. Exercises the parts most likely to be subtly
-- wrong: the generated centroid, SCD-2 versioning + as-of, hypertable inserts,
-- and the decay/serving contract. Runs in a transaction and rolls back.
BEGIN;

\echo '--- fixtures ---'
INSERT INTO source (key,name,kind,license_spdx,commercial_use,attribution_text,authority_rank)
VALUES ('test_src','Test','telegram','CC-BY-4.0',true,'Test',5) RETURNING source_id \gset src_

INSERT INTO place (kind,name_en,name_ar,geom,admin2_pcode,oslo_area)
VALUES ('station','Test Station','محطة اختبار',
        ST_GeomFromText('POINT(35.26 32.22)',4326),'PS3401','A')
RETURNING place_id \gset pl_

\echo '--- T1: generated centroid populated from geom ---'
SELECT CASE WHEN ST_X(centroid::geometry) BETWEEN 35.25 AND 35.27
            THEN 'PASS' ELSE 'FAIL' END AS t1_centroid
FROM place WHERE place_id = :pl_place_id;

\echo '--- T2: event insert + SCD-2 versioning on update ---'
INSERT INTO event (event_type,place_id,occurred_at,occurred_precision,confidence,claim_count,independent_sources)
VALUES ('idf_raid',:pl_place_id,now()-interval '2 hours','hour',0.6,1,1)
RETURNING event_id \gset ev_

SELECT pg_sleep(0.05);
UPDATE event SET confidence=0.9, independent_sources=4 WHERE event_id=:ev_event_id;

SELECT CASE WHEN (SELECT count(*) FROM event_history WHERE event_id=:ev_event_id)=1
             AND (SELECT confidence FROM event_history WHERE event_id=:ev_event_id)::numeric(3,1)=0.6
             AND (SELECT confidence FROM event WHERE event_id=:ev_event_id)::numeric(3,1)=0.9
            THEN 'PASS' ELSE 'FAIL' END AS t2_scd2;

\echo '--- T3: as-of returns the OLD version for a past timestamp ---'
SELECT CASE WHEN (SELECT confidence FROM event_as_of(lower(
                    (SELECT sys_period FROM event_history WHERE event_id=:ev_event_id))
                  ) WHERE event_id=:ev_event_id)::numeric(3,1) = 0.6
            THEN 'PASS' ELSE 'FAIL' END AS t3_as_of;

\echo '--- T4: retraction flips belief without destroying claims ---'
INSERT INTO claim (source_id,raw_ref,raw_text,claim_type,place_id,reported_at,event_id)
VALUES (:src_source_id,'bronze://test','نص','idf_raid',:pl_place_id,now(),:ev_event_id);
UPDATE event SET status='retracted', correction_note='test' WHERE event_id=:ev_event_id;
SELECT CASE WHEN (SELECT status FROM event WHERE event_id=:ev_event_id)='retracted'
             AND (SELECT count(*) FROM claim WHERE event_id=:ev_event_id)=1
            THEN 'PASS' ELSE 'FAIL' END AS t4_retract_keeps_claims;

\echo '--- T5: decay — fresh observation is served, 30-day-old is NOT ---'
INSERT INTO state_current (place_id,state_kind,value,observed_at,source_id,base_confidence)
VALUES (:pl_place_id,'fuel_diesel','available',now()-interval '10 minutes',:src_source_id,0.9);
SELECT CASE WHEN value='available' AND staleness_band='live'
            THEN 'PASS' ELSE 'FAIL: '||value||'/'||staleness_band END AS t5a_fresh_served
FROM state_serving WHERE place_id=:pl_place_id AND state_kind='fuel_diesel';

UPDATE state_current SET observed_at = now()-interval '30 days'
 WHERE place_id=:pl_place_id AND state_kind='fuel_diesel';
SELECT CASE WHEN value='unknown' AND last_known_value='available' AND staleness_band='expired'
            THEN 'PASS' ELSE 'FAIL: '||value||'/'||staleness_band END AS t5b_stale_suppressed
FROM state_serving WHERE place_id=:pl_place_id AND state_kind='fuel_diesel';

\echo '--- T6: v1 stale-open bug reproduced against v2 = suppressed ---'
-- v1 serves 488 rows as "open", 262 of them 30+ days old. Same input here:
UPDATE state_current SET state_kind='checkpoint_status', value='open',
       observed_at = now()-interval '31 days'
 WHERE place_id=:pl_place_id AND state_kind='fuel_diesel';
SELECT CASE WHEN value='unknown' THEN 'PASS' ELSE 'FAIL — v1 bug reproduced!' END AS t6_no_stale_open
FROM state_serving WHERE place_id=:pl_place_id AND state_kind='checkpoint_status';

\echo '--- T7: observation freshness ignores year-precision buckets ---'
INSERT INTO dataset (key,name,source_id,v1_category) VALUES ('test_ds','Test DS',:src_source_id,'economic')
RETURNING dataset_id \gset ds_
-- A 2026-12-31 year-bucket row: v1 read this as "fresh", giving -154 days.
INSERT INTO observation (dataset_id,indicator,value_num,occurred_at,occurred_precision)
VALUES (:ds_dataset_id,'gdp',1.0,'2026-12-31','year');
INSERT INTO observation (dataset_id,indicator,value_num,occurred_at,occurred_precision)
VALUES (:ds_dataset_id,'gdp',2.0,'2026-06-01','day');
SELECT CASE WHEN latest_dated_record::date = '2026-06-01' AND days_since_latest >= 0
            THEN 'PASS' ELSE 'FAIL: '||coalesce(latest_dated_record::text,'null')
                            ||' d='||coalesce(days_since_latest::text,'null') END AS t7_freshness
FROM dataset_freshness WHERE dataset_id=:ds_dataset_id;

\echo '--- T8: claim + observation are hypertables with chunks ---'
SELECT CASE WHEN count(*)=3 THEN 'PASS' ELSE 'FAIL' END AS t8_hypertables
FROM timescaledb_information.hypertables
WHERE hypertable_name IN ('claim','state_observation','observation');

ROLLBACK;
