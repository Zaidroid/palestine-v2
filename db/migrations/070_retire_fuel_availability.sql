-- 070 — fuel AVAILABILITY is retired; its monitoring retires with it.
--
-- Zaid, 2026-09-23: "fuel is not an issue to track anymore, lets change that to
-- track live updated prices of fuel in palestine". The availability vertical
-- (which station has diesel right now) had one signal left — the rendered cards
-- of one Telegram channel, measured once at 0.957 with every error a false
-- "available" — and no way to re-measure it after the text feed died on
-- 2026-08-28. Its collectors were stopped at 2026-09-23 07:40 UTC.
--
-- NOTHING IS DELETED. The 848k fuel observations, the heartbeat rows and the
-- state_kind_config rows all stay; what changes is that the system stops
-- EXPECTING them. Without this, a stopped collector reads as an outage and
-- pages a human about a vertical nobody wants — and an alarm that is always
-- expected trains people to skim the one that matters.
--
--   ops_heartbeat.retired_at   a retired job leaves ops_heartbeat_status, so
--                              /health, the watchdog and gate G3.7 stop judging
--                              it, and its last_ok stays readable in the table.
--   state_kind_config.retired_at  the record that a state kind is no longer
--                              collected; the watchdog's feed checks skip it.

BEGIN;

ALTER TABLE ops_heartbeat     ADD COLUMN IF NOT EXISTS retired_at     timestamptz;
ALTER TABLE ops_heartbeat     ADD COLUMN IF NOT EXISTS retired_reason text;
ALTER TABLE state_kind_config ADD COLUMN IF NOT EXISTS retired_at     timestamptz;
ALTER TABLE state_kind_config ADD COLUMN IF NOT EXISTS retired_reason text;

UPDATE ops_heartbeat
   SET retired_at = '2026-09-23 07:40:12+00',
       retired_reason = 'fuel availability retired by Zaid 2026-09-23; replaced by fuel prices'
 WHERE name IN ('ingest-fuel', 'fuel-images') AND retired_at IS NULL;

UPDATE state_kind_config
   SET retired_at = '2026-09-23 07:40:12+00',
       retired_reason = 'fuel availability retired by Zaid 2026-09-23; replaced by fuel prices'
 WHERE state_kind IN ('fuel_diesel', 'fuel_gasoline', 'cooking_gas') AND retired_at IS NULL;

-- Same columns, same order, same CASE as before; the only change is the WHERE.
CREATE OR REPLACE VIEW ops_heartbeat_status AS
 SELECT name, last_ok, last_attempt, last_error, consecutive_failures,
        expected_interval_seconds, grace_seconds, detail,
        round(EXTRACT(epoch FROM now() - last_ok) / 60.0, 1) AS ok_age_minutes,
        round(EXTRACT(epoch FROM now() - last_attempt) / 60.0, 1) AS attempt_age_minutes,
        expected_interval_seconds + COALESCE(grace_seconds, 0) AS deadline_seconds,
        CASE
            WHEN expected_interval_seconds IS NULL THEN 'unmonitored'::text
            WHEN last_ok IS NULL THEN 'never_succeeded'::text
            WHEN EXTRACT(epoch FROM now() - last_ok) > (expected_interval_seconds + COALESCE(grace_seconds, 0))::numeric THEN
            CASE
                WHEN EXTRACT(epoch FROM now() - last_attempt) > (expected_interval_seconds + COALESCE(grace_seconds, 0))::numeric THEN 'not_running'::text
                ELSE 'failing'::text
            END
            ELSE 'ok'::text
        END AS status
   FROM ops_heartbeat h
  WHERE retired_at IS NULL;

COMMIT;
