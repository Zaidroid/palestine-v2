-- 010 — guard the decay EXPONENT, not just the result.
--
-- Migration 006 clamped state_confidence's OUTPUT to avoid a float4 underflow
-- on the cast. That fix was incomplete: it never guarded the INPUT.
--
-- power(0.5, n) is computed in float8, which underflows below ~1e-308, i.e.
-- around n = 1024 halvings. Fuel never reached it (45-min half-life, hours of
-- history — tens of halvings). Checkpoints did immediately: importing 50 days
-- of history against a 15-minute per-place half-life gives
--     4,320,000s / 900s = 4,800 halvings
-- and power() raises "value out of range: underflow" before any output clamp
-- can run. Every query touching state_serving failed.
--
-- Guarding the exponent is also just correct: beyond ~60 halvings the result is
-- ~8.7e-19, orders of magnitude below any confidence_floor, so computing it
-- precisely is meaningless work that can only fail.
--
-- Rollback: restore the state_confidence body from 006.

CREATE OR REPLACE FUNCTION state_confidence(
  base REAL, observed TIMESTAMPTZ, half_life_s INTEGER, at TIMESTAMPTZ
) RETURNS REAL LANGUAGE sql IMMUTABLE AS $fn$
  SELECT CASE
           WHEN half_life_s IS NULL OR half_life_s <= 0 THEN 0::real
           -- Observation in the future: clamp to full confidence rather than
           -- letting a negative exponent amplify it above 1.
           WHEN halvings <= 0    THEN LEAST(GREATEST(base, 0::real), 1::real)
           -- Far past any floor; computing it exactly risks float8 underflow.
           WHEN halvings > 60    THEN 0::real
           ELSE LEAST(GREATEST(
                  (base::float8 * power(0.5::float8, halvings))::real,
                0::real), 1::real)
         END
  FROM (
    SELECT EXTRACT(EPOCH FROM (at - observed))::float8
           / NULLIF(half_life_s, 0)::float8 AS halvings
  ) s
$fn$;

COMMENT ON FUNCTION state_confidence(REAL, TIMESTAMPTZ, INTEGER, TIMESTAMPTZ) IS
  'Exponential decay with the exponent guarded: >60 halvings returns 0 rather than underflowing float8 inside power().';
