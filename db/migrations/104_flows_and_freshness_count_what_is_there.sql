-- 104 · v_flow and dataset_freshness count what is there
-- 2026-10-12 19:40 UTC
--
-- Two views that answered a different question from the one asked of them.
--
-- v_flow differences a cumulative series between consecutive published
-- points, per indicator, dataset and place. OCHA's demolition totals per
-- locality are declared cumulative and are 870 rows that all share ONE
-- placeholder date (1 January 2009, precision `unknown`: each is one total
-- for 2009 to date) and, per governorate, one place. Ordered by a date they
-- all share, the view subtracted one village's total from another's:
-- measured 2026-10-12, 443 "first differences" (15,560 displaced and 9,527
-- structures that never happened) and 405 "revisions". A row whose date is
-- disclaimed has no place on a time axis, so it has no flow.
--
-- dataset_freshness (007) counted every version of a row ever held, closed
-- ones included (OCHA demolitions: 3,589 for 924 live), and never looked at
-- `event`, so a dataset held as events (UCDP, the 1948 depopulations,
-- Insecurity Insight) showed zero records and no date at all. That is why
-- UCDP's stop at December 2024 was invisible to it. It now counts live rows,
-- reads events too, and reports beside them how many closed versions exist
-- and the publisher's own vintage where the dataset records one.
--
-- Rollback: db/migrations/060_derived_flow.sql and 007_observation.sql hold
-- the previous definitions; the three appended columns must be dropped first
-- (DROP VIEW dataset_freshness; then 007's CREATE).

CREATE OR REPLACE VIEW v_flow AS
WITH cumulative AS (
    SELECT v.indicator, v.place_id, v.occurred_at, v.occurred_precision,
           v.dataset_key, v.source_name, v.license_spdx, v.attribution_text,
           v.unit, v.value_num,
           i.concept_key, i.polarity,
           LAG(v.value_num)   OVER w AS prev_value,
           LAG(v.occurred_at) OVER w AS prev_at
    FROM v_observation_canonical v
    JOIN indicator_def i ON i.indicator = v.indicator
    WHERE i.measure_kind = 'cumulative'
      AND v.value_num IS NOT NULL
      -- a period total carries a placeholder date: nothing comes before or
      -- after it, so there is nothing to subtract
      AND v.occurred_precision <> 'unknown'
      -- A cumulative series is only cumulative WITHIN one publisher and one
      -- place. Differencing across two sources' tolls silently computes the
      -- gap between two methodologies and calls it a death count.
      WINDOW w AS (PARTITION BY v.indicator, v.dataset_key, v.place_id
                   ORDER BY v.occurred_at)
)
SELECT indicator, concept_key, place_id, unit, polarity,
       occurred_at            AS basis_to,
       prev_at                AS basis_from,
       occurred_precision,
       dataset_key, source_name, license_spdx, attribution_text,
       value_num              AS cumulative_to,
       prev_value             AS cumulative_from,
       CASE
           WHEN prev_value IS NULL             THEN NULL   -- series start
           WHEN value_num < prev_value         THEN NULL   -- a revision
           ELSE value_num - prev_value
       END                    AS flow,
       CASE
           WHEN prev_value IS NULL     THEN 'series_start'
           WHEN value_num < prev_value THEN 'revision'
           ELSE 'first_difference'
       END                    AS derivation,
       CASE WHEN prev_at IS NOT NULL
            THEN (occurred_at::date - prev_at::date)
       END                    AS gap_days
FROM cumulative;

CREATE OR REPLACE VIEW dataset_freshness AS
WITH obs AS (
    SELECT o.dataset_id,
           count(*) FILTER (WHERE upper_inf(o.sys_period))                 AS records,
           count(*) FILTER (WHERE NOT upper_inf(o.sys_period))             AS versions_closed,
           max(o.occurred_at) FILTER (
               WHERE upper_inf(o.sys_period)
                 AND o.occurred_precision IN ('exact', 'hour', 'day'))     AS latest_dated,
           max(o.ingested_at)                                              AS last_ingest,
           count(*) FILTER (WHERE upper_inf(o.sys_period)
                              AND o.place_id IS NOT NULL)                  AS placed
      FROM observation o
     GROUP BY 1
), ev AS (
    SELECT d.dataset_id,
           count(*)                                                        AS records,
           max(e.occurred_at) FILTER (
               WHERE e.occurred_precision IN ('exact', 'hour', 'day'))     AS latest_dated,
           max(e.created_at)                                               AS last_ingest,
           count(*) FILTER (WHERE e.place_id IS NOT NULL)                  AS placed
      FROM event e
      JOIN dataset d ON d.key = e.attrs->>'dataset_key'
     WHERE upper_inf(e.sys_period) AND e.status = 'believed'
     GROUP BY 1
)
SELECT d.dataset_id,
       d.key                                                   AS dataset_key,
       d.v1_category,
       d.active,
       COALESCE(obs.records, 0) + COALESCE(ev.records, 0)      AS records,
       GREATEST(obs.latest_dated, ev.latest_dated)             AS latest_dated_record,
       GREATEST(obs.last_ingest, ev.last_ingest)               AS last_ingest,
       EXTRACT(day FROM now() - GREATEST(obs.latest_dated, ev.latest_dated))::integer
                                                               AS days_since_latest,
       (COALESCE(obs.placed, 0) + COALESCE(ev.placed, 0))::double precision
         / NULLIF(COALESCE(obs.records, 0) + COALESCE(ev.records, 0), 0)::double precision
                                                               AS place_resolved_pct,
       COALESCE(ev.records, 0)                                 AS event_records,
       COALESCE(obs.versions_closed, 0)                        AS versions_closed,
       d.attrs->>'vintage'                                     AS publisher_vintage
  FROM dataset d
  LEFT JOIN obs ON obs.dataset_id = d.dataset_id
  LEFT JOIN ev  ON ev.dataset_id  = d.dataset_id;

COMMENT ON VIEW dataset_freshness IS
  'Per dataset: LIVE rows (observations plus believed events), the newest '
  'record dated to the day or finer, the last ingest, how many closed '
  'versions sit behind the live rows, and the publisher''s own vintage where '
  'the dataset records one (registers have no dated record). 104.';
