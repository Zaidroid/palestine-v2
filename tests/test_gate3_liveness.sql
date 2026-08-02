-- Gate 3 — P3.1/P3.2. Can this system tell that it has stopped?
--
--   docker exec -i palestine-v2-db psql -U palestine -d palestine_v2 -tA \
--       < tests/test_gate3_liveness.sql
--
-- On 2026-08-01 the Telegram poller was dead for eight hours while systemd
-- reported `active (running)`, /health returned {"status":"ok"}, and the news
-- classifier logged a successful run every five minutes. Nothing was broken in
-- a way anything looked at. These gates cover the SQL half of the fix — the
-- classification in ops_heartbeat_status, which is the single decision point
-- both /health and ops/watchdog.py read, and therefore the one place where
-- getting it wrong makes every consumer wrong in the same direction at once.

\echo '--- G3.1: a job that ran recently and succeeded is ok ---'
BEGIN;
INSERT INTO ops_heartbeat (name,last_ok,last_attempt,expected_interval_seconds,grace_seconds)
VALUES ('_g3_fresh', now()-interval '1 min', now()-interval '1 min', 300, 600);
SELECT CASE WHEN (SELECT status FROM ops_heartbeat_status WHERE name='_g3_fresh') = 'ok'
            THEN 'PASS' ELSE 'FAIL: a healthy job was not reported healthy' END AS g3_1_ok;
ROLLBACK;

\echo '--- G3.2: a job the scheduler stopped firing is not_running ---'
BEGIN;
-- Both timestamps old: nothing has even attempted it.
INSERT INTO ops_heartbeat (name,last_ok,last_attempt,expected_interval_seconds,grace_seconds)
VALUES ('_g3_gone', now()-interval '8 hours', now()-interval '8 hours', 300, 600);
SELECT CASE WHEN (SELECT status FROM ops_heartbeat_status WHERE name='_g3_gone') = 'not_running'
            THEN 'PASS' ELSE 'FAIL: a job nothing is running was not reported as such' END AS g3_2_not_running;
ROLLBACK;

\echo '--- G3.3: a job that runs and keeps failing is failing, not not_running ---'
BEGIN;
-- Attempting recently but not succeeding. This is the distinction that decides
-- whether someone looks at the timer or at the job, so conflating the two
-- sends whoever reads the alarm to the wrong place.
INSERT INTO ops_heartbeat (name,last_ok,last_attempt,last_error,expected_interval_seconds,grace_seconds)
VALUES ('_g3_failing', now()-interval '8 hours', now()-interval '30 seconds', 'boom', 300, 600);
SELECT CASE WHEN (SELECT status FROM ops_heartbeat_status WHERE name='_g3_failing') = 'failing'
            THEN 'PASS' ELSE 'FAIL: a running-but-failing job was misclassified' END AS g3_3_failing;
ROLLBACK;

\echo '--- G3.4: grace is honoured, so a slightly late job does not cry wolf ---'
BEGIN;
INSERT INTO ops_heartbeat (name,last_ok,last_attempt,expected_interval_seconds,grace_seconds)
VALUES ('_g3_late', now()-interval '7 min', now()-interval '7 min', 300, 600);
SELECT CASE WHEN (SELECT status FROM ops_heartbeat_status WHERE name='_g3_late') = 'ok'
            THEN 'PASS' ELSE 'FAIL: a job inside interval+grace was reported late' END AS g3_4_grace;
ROLLBACK;

\echo '--- G3.5: a job that has never succeeded is never_succeeded, not ok ---'
BEGIN;
-- NULL last_ok must not be read as "no problem". A job wired up but never
-- working is the state that looks most like a healthy new deployment.
INSERT INTO ops_heartbeat (name,last_ok,last_attempt,expected_interval_seconds,grace_seconds)
VALUES ('_g3_never', NULL, now(), 300, 600);
SELECT CASE WHEN (SELECT status FROM ops_heartbeat_status WHERE name='_g3_never') = 'never_succeeded'
            THEN 'PASS' ELSE 'FAIL: a job that has never worked was not flagged' END AS g3_5_never;
ROLLBACK;

\echo '--- G3.6: a job with no declared cadence says so instead of passing ---'
BEGIN;
-- Silence about a job with no interval is the failure mode this whole gate
-- file exists for: it must read as "not being judged", never as "fine".
INSERT INTO ops_heartbeat (name,last_ok,last_attempt,expected_interval_seconds)
VALUES ('_g3_nocadence', now()-interval '30 days', now(), NULL);
SELECT CASE WHEN (SELECT status FROM ops_heartbeat_status WHERE name='_g3_nocadence') = 'unmonitored'
            THEN 'PASS' ELSE 'FAIL: a job with no cadence was silently treated as watched' END AS g3_6_unmonitored;
ROLLBACK;

\echo '--- G3.7: every live collector is reporting a heartbeat ---'
SELECT CASE WHEN count(*) FILTER (WHERE status <> 'ok') = 0
            THEN 'PASS (' || count(*) || ' jobs reporting)'
            ELSE 'FAIL: ' || string_agg(name || '=' || status, ', ')
                 FILTER (WHERE status <> 'ok') END AS g3_7_all_jobs_ok
FROM ops_heartbeat_status;

\echo '--- G3.8: the cadence cache /health reads is being refreshed ---'
-- /health reads feed_cadence instead of recomputing a 21-day scan per request.
-- A cache nobody refreshes would freeze the thresholds at whatever they were
-- the day it broke, and every feed would keep being judged against history.
SELECT CASE WHEN count(*) = 0 THEN 'FAIL: feed_cadence is empty — the watchdog has never run'
            WHEN max(measured_at) < now() - interval '2 hours'
              THEN 'FAIL: cadence last measured ' || max(measured_at)
            ELSE 'PASS (' || count(*) || ' feeds, measured '
                 || round(extract(epoch FROM now()-max(measured_at))/60) || 'm ago)'
       END AS g3_8_cadence_fresh
FROM feed_cadence;

\echo '--- G3.9: thresholds are derived from measurement, never hand-set ---'
-- Every watchable feed must have a threshold strictly greater than its own p99
-- gap. A threshold at or below p99 would fire on ordinary variation, and the
-- alarms would be tuned out within a week.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || string_agg(state_kind, ', ') END AS g3_9_thresholds_earned
FROM feed_cadence
WHERE watchable AND (threshold_seconds IS NULL OR threshold_seconds <= p99_seconds);

\echo '--- G3.10: an unwatchable feed carries no threshold at all ---'
-- Storing a threshold for a feed with too few arrivals would let a later reader
-- treat the sample as if it described the feed. Absent is the honest value.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || string_agg(state_kind, ', ')
                 || ' carry a threshold they did not earn' END AS g3_10_no_fake_thresholds
FROM feed_cadence
WHERE NOT watchable AND threshold_seconds IS NOT NULL;
