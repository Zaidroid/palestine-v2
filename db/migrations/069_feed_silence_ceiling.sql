-- 069 — a silence ceiling measured from each feed's own rhythm
--
-- F-08. `checkpoint_settlers` and `power` have been chased three Mondays
-- running and found innocent both times. They are genuinely irregular: over
-- 60 days settlers arrive 139 times (p50 87 min, p95 45.9 h, longest gap
-- 8 days) and power 59 times (p50 15 min, p95 6.2 days, longest 14.8 days).
-- Both sit under MIN_ARRIVALS, so no percentile-based threshold is derived for
-- them and the 24 h DEFAULT ceiling applies — which fires on a merely quiet
-- week. That is an alarm about the ceiling, not about the feed, and the
-- watchdog's own comment (SILENT_AFTER_SECONDS) says so.
--
-- So the ceiling becomes a property of the feed, measured from the feed, and
-- stored WITH the date it was measured — a chosen number reported as a
-- measured one is exactly what this project has been bitten by twice (0.70
-- "trust", 0.95 fuel confidence). The floor stays 24 h: nothing here may make
-- a real outage quieter than a day, and `collector_only` stays until a feed
-- has 200 arrivals.
--
-- Read by ops/watchdog.py: measure_cadence() writes it, _silence_ceiling()
-- reads it, and the basis travels with it so a report can say which it is.

ALTER TABLE feed_cadence
    ADD COLUMN IF NOT EXISTS p95_seconds             DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS silence_ceiling_seconds DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ceiling_basis           TEXT,
    ADD COLUMN IF NOT EXISTS ceiling_window_days     INTEGER;

COMMENT ON COLUMN feed_cadence.p95_seconds IS
    '95th percentile inter-arrival over ceiling_window_days, minute-bucketed.';
COMMENT ON COLUMN feed_cadence.silence_ceiling_seconds IS
    'How long this feed may legitimately say nothing: max(p95, 24 h).';
COMMENT ON COLUMN feed_cadence.ceiling_basis IS
    'measured p95(Nd) or the 24 h default with the reason it could not be measured.';
