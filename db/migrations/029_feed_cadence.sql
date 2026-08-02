-- 029 — each feed's measured rhythm, recorded rather than recomputed.
--
-- P3.2 needs /health to report every vertical against its expected cadence,
-- and ops/watchdog.py already measures exactly that. Two implementations of
-- "is this feed late" would eventually disagree, and the disagreement would
-- surface as a status page that is red while the watchdog is silent — so
-- there is one measurement, written here, and both read it.
--
-- WHY IT IS CACHED AND NOT COMPUTED PER REQUEST
-- The measurement scans 21 days of state_observation to build a gap
-- distribution per kind: 411ms, against 90ms for the current-age query beside
-- it. /health is polled; putting a half-second sequential scan behind a
-- liveness endpoint is how a health check becomes the thing that needs
-- watching. The watchdog refreshes this every 10 minutes, which is far more
-- often than a 21-day baseline can meaningfully move.
--
-- THE CACHE CANNOT ROT UNNOTICED
-- Stale thresholds would be dangerous — a feed judged against a cadence from
-- last month is not really being judged. That risk is already covered rather
-- than accepted: the watchdog reports its OWN heartbeat, so if it stops
-- refreshing this table, the `watchdog` job goes to not_running and alarms.
-- measured_at is kept anyway so the age of the judgement is inspectable
-- alongside the judgement itself.
--
-- watchable is stored, not inferred at read time, for the same reason the
-- threshold is: whether a feed can be judged at all is a conclusion drawn from
-- the arrival count, and a conclusion recorded next to its evidence is one
-- that can be argued with later.

CREATE TABLE IF NOT EXISTS feed_cadence (
  state_kind         text PRIMARY KEY,
  arrivals           integer     NOT NULL,
  p50_seconds        double precision,
  p99_seconds        double precision,
  threshold_seconds  double precision,
  watchable          boolean     NOT NULL,
  measured_at        timestamptz NOT NULL DEFAULT now(),
  baseline_days      integer     NOT NULL,
  judge_hours        integer     NOT NULL
);

COMMENT ON TABLE feed_cadence IS
  'Per-kind arrival rhythm measured from history by ops/watchdog.py. Read by '
  'both the watchdog and /health so the two cannot disagree about lateness.';

COMMENT ON COLUMN feed_cadence.threshold_seconds IS
  'How old an observation may be before the feed counts as silent. Derived '
  'from the feed OWN p99 gap times a margin — never a chosen number.';

COMMENT ON COLUMN feed_cadence.watchable IS
  'False when there are too few arrivals for a percentile to describe the '
  'feed rather than the sample. Such feeds are covered by their collector''s '
  'heartbeat instead, and are listed as such rather than silently skipped.';

COMMENT ON COLUMN feed_cadence.judge_hours IS
  'The baseline ENDS this many hours before now, and those hours are what gets '
  'judged. A feed degrading slowly would otherwise drag its own threshold down '
  'with it and never trip.';
