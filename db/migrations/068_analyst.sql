-- 068 — the analyst's own bookkeeping: a watermark, a provenance row per
-- reading, and the two views that make its health a number rather than a log.
--
-- P0 of docs/LOCAL-ANALYST-2026-09.md. The analyst is a CONSUMER of `claim`,
-- not a collector: it walks new rows past a watermark, and writes only
-- proposals and provenance. It never writes `event`, `state_current`,
-- `observation` or anything the belief engine owns.
--
-- WHY A WATERMARK PER ORGAN AND NOT ONE FOR THE COMPONENT
-- The organs move at wildly different speeds by design. Organ A (language) is
-- deterministic and keeps up with ingestion; organ B will spend five days of
-- idle GPU time walking 68,000 never-classified claims while A stays at the
-- head of the stream. One shared cursor would force the fast organ to the
-- speed of the slow one, and a new organ added later would either re-read the
-- whole corpus or silently skip everything written before it existed. The
-- cursor is (ingested_at, claim_id) because `claim` is a hypertable on
-- ingested_at: a claim_id alone does not order rows across chunks, and a
-- timestamp alone is not unique.
--
-- WHY A RUN ROW AND NOT A LOG LINE
-- The MiniMax failure this component exists to never repeat was invisible for
-- three months because its only record was a log line saying "falling back to
-- rules" — true, undramatic, and unaggregatable. 29,686 of 29,687 calls
-- failed and no query could say so. A row per reading, with its outcome and
-- its latency, makes the success rate a SELECT.
--
-- A row is written for every claim an organ actually READS. An organ that
-- declines a claim (organ A passing over a row whose language was already
-- detected at ingest) writes nothing — the claim's own attrs carry that
-- provenance, and a table with one "nothing to do" row per claim per organ
-- per pass would bury the readings that matter.

CREATE TABLE IF NOT EXISTS analyst_watermark (
  organ             TEXT PRIMARY KEY,
  last_ingested_at  TIMESTAMPTZ,
  last_claim_id     BIGINT,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  note              TEXT
);

COMMENT ON TABLE analyst_watermark IS
  'One cursor per analyst organ over `claim`, ordered by (ingested_at, claim_id). '
  'A NULL cursor means the organ has never run and starts at the oldest claim.';
COMMENT ON COLUMN analyst_watermark.note IS
  'Why the cursor is where it is — e.g. which backfill placed it. Read by humans only.';

CREATE TABLE IF NOT EXISTS analyst_run (
  run_id          BIGSERIAL PRIMARY KEY,
  claim_id        BIGINT      NOT NULL,
  organ           TEXT        NOT NULL,
  organ_version   TEXT        NOT NULL,
  -- What produced the answer. For a model organ this is the llama-swap model
  -- name; for a deterministic organ it is the library and version that decided
  -- (`lingua@2.2.0`). The column means "what to blame", and a deterministic
  -- detector is as blameable as a model.
  model           TEXT,
  prompt_version  TEXT,
  verdict         TEXT,
  -- The §2.5 redundancy: the individual samples, and whether they agreed.
  -- NULL for a deterministic organ, which has nothing to vote on — NOT false,
  -- which would report perfect disagreement on every row organ A touches.
  votes           JSONB,
  agreed          BOOLEAN,
  -- Grammar-enforced output cannot be invalid (§2.2), so this is the metric
  -- that proves the grammar is actually on. NULL where no JSON was asked for.
  json_valid      BOOLEAN,
  latency_ms      INTEGER,
  outcome         TEXT        NOT NULL CHECK (outcome IN ('ok','error','skipped')),
  error           TEXT,
  raw             JSONB       NOT NULL DEFAULT '{}'::jsonb,
  ran_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE analyst_run IS
  'Provenance: one row per claim an organ read. The analyst''s success rate, '
  'JSON-valid rate, vote agreement and latency are all SELECTs over this table, '
  'which is the difference between this component and the dead MiniMax path it '
  'was designed against.';
COMMENT ON COLUMN analyst_run.outcome IS
  'ok | error | skipped. There is no default: a status column that defaults to a '
  'happy value lies exactly when the writer dies mid-flight.';

CREATE INDEX IF NOT EXISTS analyst_run_organ_idx ON analyst_run (organ, ran_at DESC);
CREATE INDEX IF NOT EXISTS analyst_run_claim_idx ON analyst_run (claim_id);
CREATE INDEX IF NOT EXISTS analyst_run_outcome_idx ON analyst_run (outcome, ran_at DESC)
  WHERE outcome <> 'ok';

-- Health, computed in ONE place so the loop's heartbeat detail, the watchdog
-- and any later dashboard cannot disagree about what "healthy" means. The
-- window is deliberately short: an hourly rate that includes yesterday's good
-- run hides an organ that started failing twenty minutes ago.
CREATE OR REPLACE VIEW analyst_health AS
SELECT
  organ,
  count(*)                                                     AS runs_1h,
  count(*) FILTER (WHERE outcome = 'ok')                       AS ok_1h,
  count(*) FILTER (WHERE outcome = 'error')                    AS errors_1h,
  count(*) FILTER (WHERE outcome = 'skipped')                  AS skipped_1h,
  -- A rate over zero runs is not 0.0, it is unknown, and NULL is how SQL says
  -- so. A confident zero here would read as "everything failed".
  CASE WHEN count(*) FILTER (WHERE outcome IN ('ok','error')) > 0
       THEN round((count(*) FILTER (WHERE outcome = 'ok'))::numeric
                  / count(*) FILTER (WHERE outcome IN ('ok','error')), 4)
  END                                                          AS success_rate_1h,
  CASE WHEN count(*) FILTER (WHERE json_valid IS NOT NULL) > 0
       THEN round((count(*) FILTER (WHERE json_valid))::numeric
                  / count(*) FILTER (WHERE json_valid IS NOT NULL), 4)
  END                                                          AS json_valid_rate_1h,
  CASE WHEN count(*) FILTER (WHERE agreed IS NOT NULL) > 0
       THEN round((count(*) FILTER (WHERE agreed))::numeric
                  / count(*) FILTER (WHERE agreed IS NOT NULL), 4)
  END                                                          AS vote_agreement_1h,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)       AS latency_p50_ms,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)      AS latency_p95_ms,
  max(ran_at)                                                   AS last_run_at
FROM analyst_run
WHERE ran_at > now() - interval '1 hour'
GROUP BY organ;

COMMENT ON VIEW analyst_health IS
  'Per-organ health over the last hour. Every rate is NULL rather than 0 when '
  'its denominator is empty — see the honesty note in the view body.';

-- How far behind each organ is, in claims and in time. Backlog depth is the
-- one number that separates "the analyst is keeping up" from "the analyst is
-- running, succeeding, and falling a day further behind every day".
CREATE OR REPLACE VIEW analyst_backlog AS
SELECT
  w.organ,
  w.last_ingested_at,
  w.last_claim_id,
  (SELECT count(*) FROM claim c
    WHERE w.last_ingested_at IS NULL
       OR (c.ingested_at, c.claim_id) > (w.last_ingested_at, w.last_claim_id))
                                                               AS pending_claims,
  CASE WHEN w.last_ingested_at IS NOT NULL
       THEN round(extract(epoch FROM (now() - w.last_ingested_at)) / 60.0, 1)
  END                                                          AS lag_minutes
FROM analyst_watermark w;

COMMENT ON VIEW analyst_backlog IS
  'Claims each organ has not read yet. An organ with no watermark row does not '
  'appear here at all, which is why the loop writes its cursor on first tick.';
