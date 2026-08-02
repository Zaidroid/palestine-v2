-- 028 — liveness becomes a fact the system asserts, instead of one inferred
-- from the absence of rows.
--
-- P3.1. Ten timers and one long-running poller, and nothing watched any of
-- them. The gap was demonstrated live while writing this: the Telegram poller
-- lost its connection at 08:35 and spent the next EIGHT HOURS reporting
-- `active (running)` to systemd while ingesting nothing. Every downstream
-- indicator agreed it was healthy — the news classifier ran on schedule every
-- 5 minutes and reported "read 0 unclassified claims", which is exactly what a
-- quiet news day also looks like.
--
-- WHY A HEARTBEAT AND NOT JUST DATA FRESHNESS
-- "No new claims for 8 hours" has two causes that produce IDENTICAL evidence:
--
--     the collector is dead        -> no rows
--     the sources are quiet        -> no rows
--
-- One is an emergency and one is a Saturday. Nothing in claim/state_observation
-- can separate them, because both are defined by rows that are not there. The
-- only way to tell them apart is for the collector to say "I ran, I succeeded,
-- and there was nothing" — a positive assertion of liveness that goes missing
-- when, and only when, the collector actually stops.
--
-- So a job records `last_ok` on every successful cycle regardless of whether it
-- produced anything, and `last_attempt` whether or not it succeeded. Then:
--
--     last_attempt stale                 -> the scheduler is not running it
--     last_attempt fresh, last_ok stale  -> it runs and it is failing
--     both fresh, no data                -> genuinely quiet. Not a fault.
--
-- That third row is the one that matters. Without it a watchdog either cries
-- wolf on every quiet night or is tuned so loose it sleeps through an outage,
-- and both of those end with the alarm being ignored.
--
-- expected_interval_seconds is the job's OWN cadence, recorded by the job
-- rather than configured centrally, so a timer and its watchdog cannot drift
-- apart. grace_seconds is how late is late; ops/watchdog.py compares
-- now() - last_ok against interval + grace and nothing else, so the policy
-- lives with the job that knows it.

CREATE TABLE IF NOT EXISTS ops_heartbeat (
  name                       text PRIMARY KEY,
  last_ok                    timestamptz,
  last_attempt               timestamptz NOT NULL DEFAULT now(),
  last_error                 text,
  consecutive_failures       integer NOT NULL DEFAULT 0,
  expected_interval_seconds  integer,
  grace_seconds              integer,
  detail                     jsonb NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE ops_heartbeat IS
  'One row per scheduled job or daemon. Positive liveness: a job reports that '
  'it ran and succeeded, so that "collector dead" and "sources quiet" — which '
  'produce identical evidence in the data tables — can be told apart.';

COMMENT ON COLUMN ops_heartbeat.last_ok IS
  'Last SUCCESSFUL cycle. Updated even when the cycle produced zero rows: '
  'producing nothing is a valid outcome, failing to run is not.';

COMMENT ON COLUMN ops_heartbeat.last_attempt IS
  'Last cycle attempted, successful or not. Stale last_attempt means the '
  'scheduler is not firing; fresh last_attempt with stale last_ok means the '
  'job is running and failing. Those need different responses.';

COMMENT ON COLUMN ops_heartbeat.expected_interval_seconds IS
  'Reported BY THE JOB, not configured centrally, so that changing a timer '
  'cannot silently leave the watchdog checking the old cadence.';

-- A view so both consumers — /health and ops/watchdog.py — compute lateness in
-- exactly one place. Two implementations of "is this late" would eventually
-- disagree, and the disagreement would surface as a watchdog that is quiet
-- while the status page is red.
CREATE OR REPLACE VIEW ops_heartbeat_status AS
SELECT
  h.name,
  h.last_ok,
  h.last_attempt,
  h.last_error,
  h.consecutive_failures,
  h.expected_interval_seconds,
  h.grace_seconds,
  h.detail,
  round(extract(epoch FROM (now() - h.last_ok)) / 60.0, 1)      AS ok_age_minutes,
  round(extract(epoch FROM (now() - h.last_attempt)) / 60.0, 1) AS attempt_age_minutes,
  (h.expected_interval_seconds + COALESCE(h.grace_seconds, 0))  AS deadline_seconds,
  CASE
    WHEN h.expected_interval_seconds IS NULL THEN 'unmonitored'
    WHEN h.last_ok IS NULL                   THEN 'never_succeeded'
    WHEN extract(epoch FROM (now() - h.last_ok))
         > h.expected_interval_seconds + COALESCE(h.grace_seconds, 0) THEN
      -- Distinguish the two failure shapes. Both are late; they are not the
      -- same problem and they do not have the same fix.
      CASE WHEN extract(epoch FROM (now() - h.last_attempt))
                > h.expected_interval_seconds + COALESCE(h.grace_seconds, 0)
           THEN 'not_running'      -- the scheduler stopped firing it
           ELSE 'failing'          -- it fires and it does not succeed
      END
    ELSE 'ok'
  END AS status
FROM ops_heartbeat h;

COMMENT ON VIEW ops_heartbeat_status IS
  'Lateness computed once, for both /health and ops/watchdog.py. status is one '
  'of ok | failing | not_running | never_succeeded | unmonitored.';
