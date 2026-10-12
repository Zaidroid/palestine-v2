-- 105 · a month the source gave as a month is held as a month
-- 2026-10-12
--
-- The 1948 depopulation record (Palestine Open Maps) writes "May 1948" as
-- 1948-05-01 and marks no precision. Measured 2026-10-12 on the believed
-- events: 144 of 474 day-precision dates sit on the first of a month (74 on
-- 1 May 1948 alone, against two or three on an ordinary day), and each was
-- served as a day. Which of them are a real first of the month cannot be told
-- from the source, so all are held as the month: at month precision the
-- statement is true of every one of them.
--
-- The loader skips an event it already holds, so the held events are changed
-- here; the transformer does the same for a fresh load. The event table's own
-- trigger keeps the previous version of each row in event_history, and the
-- old precision stays readable in attrs.
--
-- The observation rows of the same villages (historical.locality_status) are
-- NOT touched here: the transformer now emits them at month precision with a
-- note, and the next load supersedes the 139 held rows itself.
--
-- Rollback:
--   UPDATE event SET occurred_precision = 'day', attrs = attrs - 'occurred_precision_before'
--    WHERE event_type = 'conflict.village_depopulation'
--      AND attrs->>'occurred_precision_before' = 'day';

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE n int;
BEGIN
  UPDATE event
     SET occurred_precision = 'month',
         attrs = attrs || jsonb_build_object(
                   'occurred_precision_before', 'day',
                   'date_basis', 'the first of a month in the source; held as the month')
   WHERE event_type = 'conflict.village_depopulation'
     AND status = 'believed'
     AND upper_inf(sys_period)
     AND occurred_precision = 'day'
     AND extract(day FROM occurred_at AT TIME ZONE 'UTC') = 1;
  GET DIAGNOSTICS n = ROW_COUNT;
  RAISE NOTICE '105: % depopulation events held as their month', n;
  IF n > 200 THEN
    RAISE EXCEPTION '105: % events would change, 144 were measured; stopping', n;
  END IF;
END $$;
