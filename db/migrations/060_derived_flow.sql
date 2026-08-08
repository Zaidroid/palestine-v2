-- 060 — differencing a cumulative series, without inventing a single number
--
-- 41 indicators and 4,361 rows are CUMULATIVE: a running toll since some
-- epoch. Almost every interesting question about them is about the flow —
-- "how many were killed in March" — and the flow is not published. It has to
-- be derived, and deriving it is where databanks lie.
--
-- conflict.yaml carries the lesson in full. A naive difference over a
-- cumulative series with a gap, a revision, or an epoch change produces
-- numbers that are not merely wrong but grotesque; the note there records a
-- ~35-million-dead artifact from exactly this arithmetic. So:
--
--   A VIEW, NEVER ROWS. A derived number that lands in `observation` is
--   indistinguishable from a published one within a week. This never
--   materialises, and every row it returns says how it was made.
--
--   ONLY BETWEEN CONSECUTIVE PUBLISHED POINTS. No interpolation across a
--   gap. If the source skipped eleven days, the flow covers eleven days and
--   `gap_days` says so — it is not spread across them.
--
--   ONLY FOR measure_kind = 'cumulative'. Differencing a stock gives change,
--   which is a different thing with a different name; differencing a flow is
--   meaningless. The registry is what makes this distinction available at
--   all.
--
--   A DECREASE IS A REVISION, NOT A NEGATIVE FLOW. A running total that
--   falls means the publisher corrected it. Nobody was un-killed. The row
--   returns NULL with derivation='revision' and keeps both endpoints
--   visible, so the correction is a fact you can see rather than a negative
--   number you have to explain.

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

COMMENT ON VIEW v_flow IS
  'First differences of CUMULATIVE series only, between consecutive '
  'published points only, within one indicator + dataset + place. Never '
  'materialised. A decrease is a revision and yields NULL, never a negative '
  'flow — nobody was un-killed. Every row carries basis_from, basis_to, '
  'gap_days and how it was derived.';
