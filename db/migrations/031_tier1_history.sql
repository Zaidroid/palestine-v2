-- 031 — tier 1 grows a memory, and writes it where tier 2 will look for it.
--
-- Until now every endpoint answered "right now". There was no way to ask what
-- has been happening at a checkpoint this month, or whether a station usually
-- has diesel on a Tuesday. That is the gap this closes.
--
-- ============================================================================
-- WHY THIS IS NOT A tier1_rollup TABLE
-- ============================================================================
-- The obvious build is a private daily-summary table shaped for the charts we
-- happen to want. It would work, and tier 2 would then have to throw it away.
--
-- `observation` — dataset_id, place_id, indicator, value_num, occurred_at — is
-- already in this schema. It is the DATABANK's table, the one all 244,461
-- records collapse into, and ARCHITECTURE.md sets Phase 2's gate as:
--
--     "a cross-tier query (alerts x databank, joined on place and time)
--      returns correct results — the thing that is impossible today"
--
-- If tier 1's history is written as `observation` rows against the same
-- `place_id` and the same clock, that gate is satisfied BY CONSTRUCTION rather
-- than by a migration written months later, and "checkpoint closures vs water
-- availability in Hebron, monthly" becomes one GROUP BY on day one. So tier 1's
-- memory is databank data that happens to have arrived first.
--
-- ============================================================================
-- WHAT IS COUNTED, AND WHAT IS DELIBERATELY NOT
-- ============================================================================
-- Counts of REPORTS, not shares of TIME.
--
-- "Huwara was closed 40% of yesterday" requires replaying the decay curve to
-- know what was believed at every instant, and it invites a reader to treat
-- sparse reporting as measured time — a checkpoint with three reports a day
-- cannot support a claim about the other 23 hours. "Of 37 reports about Huwara
-- yesterday, 15 said closed" is directly measurable, cannot be misread as
-- coverage it does not have, and the share is one division away for anyone who
-- wants it.
--
-- Counts are also additive, which shares are not: a weekly figure is the sum of
-- seven daily rows, and no rollup of a rollup ever has to be recomputed.
--
-- INDICATOR VOCABULARY (controlled, per ARCHITECTURE §governance):
--     <state_kind>.reports            total assertion observations that day
--     <state_kind>.reports.<value>    how many carried each value
--     <state_kind>.units              distinct INDEPENDENCE units reporting
--
-- `units` is the honesty column. Nine road channels reposting each other are
-- one observer, and a day with 200 reports from one unit is a thinner day than
-- one with 12 reports from four. Without it a chart of report volume would
-- read as a chart of confidence.
--
-- ============================================================================
-- ONLY COMPLETE DAYS
-- ============================================================================
-- A day still in progress would be written, then rewritten as more reports
-- arrive, and `observation` is an immutable record. So the rollup covers
-- yesterday and earlier only; today is served live from `state_observation`,
-- which is retained forever anyway. The boundary is what makes "written once,
-- never mutated" true rather than aspirational.
--
-- Hour-of-day patterns ("usually closed 07:00-09:00") are computed from
-- `state_observation` on demand rather than stored at an hourly grain. Inventing
-- a second grain for a question we can answer from the raw record would be
-- premature aggregation, and the raw record is compressed and retained anyway.

-- ── the dataset this history belongs to ──────────────────────────────────────
-- Registered like any other databank dataset, so tier 2 inherits it with its
-- provenance rather than finding an unexplained table.

INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                    attribution_text, authority_rank, active)
VALUES ('tier1_rollup', 'Palestine v2 tier-1 daily rollup', 'derived',
        'NONE', false,
        'Derived from Palestine v2 tier-1 observations', 3, true)
ON CONFLICT (key) DO NOTHING;

INSERT INTO dataset (key, name, source_id, cadence, active, attrs)
SELECT 'tier1_daily',
       'Tier 1 daily state rollup',
       s.source_id,
       'daily',
       true,
       jsonb_build_object(
         'grain', 'place x state_kind x day',
         'counts', 'reports, not time shares',
         'complete_days_only', true,
         'note', 'Written by ops/rollup.py. Immutable: only days that have '
              || 'ended are written, so a row never needs revising.')
FROM source s WHERE s.key = 'tier1_rollup'
ON CONFLICT (key) DO NOTHING;

-- ── idempotency ──────────────────────────────────────────────────────────────
-- The rollup runs nightly and may be re-run by hand after a backfill. Without a
-- uniqueness constraint that produces silent duplicates, which is exactly the
-- failure the fuel loader had: 98.48% of its rows were copies, and it took
-- sizing the backup to notice. A constraint is cheaper than that lesson twice.
--
-- Partial unique index rather than a table constraint, because `observation` is
-- a hypertable and its primary key must include occurred_at. Scoped to rows
-- carrying a place, since a place-less rollup row would not be meaningful here.

CREATE UNIQUE INDEX IF NOT EXISTS observation_rollup_uniq
  ON observation (dataset_id, place_id, indicator, occurred_at)
  WHERE place_id IS NOT NULL;

COMMENT ON INDEX observation_rollup_uniq IS
  'Makes the nightly rollup idempotent: re-running a day updates rather than '
  'duplicates. Also the guard against the failure mode that put 762,609 '
  'duplicate rows in state_observation before anyone noticed.';

-- Reading a place''s history is a range scan over one indicator; the existing
-- indexes are on each column separately, which makes the planner choose one and
-- filter the rest.
CREATE INDEX IF NOT EXISTS observation_place_indicator_idx
  ON observation (place_id, indicator, occurred_at DESC);
