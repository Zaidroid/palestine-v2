-- 007 — observation layer: the databank. All 244k v1 records collapse here.
-- Categories become views over `indicator`, not directories on disk.

CREATE TABLE observation (
  observation_id     BIGSERIAL,
  dataset_id         INTEGER NOT NULL REFERENCES dataset(dataset_id),
  place_id           BIGINT REFERENCES place(place_id),
  indicator          TEXT NOT NULL,
  value_num          DOUBLE PRECISION,
  value_text         TEXT,
  unit               TEXT,
  occurred_at        TIMESTAMPTZ NOT NULL,
  occurred_precision time_precision NOT NULL,
  reported_at        TIMESTAMPTZ,
  ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_ref            TEXT,
  v1_stable_id       TEXT,     -- provenance for the Phase 2 dual-run comparison
  attrs              JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (observation_id, occurred_at),
  CONSTRAINT observation_has_a_value CHECK (value_num IS NOT NULL OR value_text IS NOT NULL)
);
SELECT create_hypertable('observation','occurred_at',
  chunk_time_interval => INTERVAL '365 days');   -- data spans 1935 → present

CREATE INDEX observation_dataset_idx   ON observation (dataset_id, occurred_at DESC);
CREATE INDEX observation_indicator_idx ON observation (indicator, occurred_at DESC);
CREATE INDEX observation_place_idx     ON observation (place_id) WHERE place_id IS NOT NULL;
CREATE INDEX observation_v1id_idx      ON observation (v1_stable_id) WHERE v1_stable_id IS NOT NULL;

-- Freshness, computed correctly by construction (ARCHITECTURE §3.4): only
-- day-or-finer records count, so a year bucket can never report as fresh and
-- an ingest timestamp can never masquerade as an event date.
CREATE OR REPLACE VIEW dataset_freshness AS
SELECT
  d.dataset_id, d.key AS dataset_key, d.v1_category, d.active,
  COUNT(o.*)                                              AS records,
  MAX(o.occurred_at) FILTER (
    WHERE o.occurred_precision IN ('exact','hour','day')
  )                                                       AS latest_dated_record,
  MAX(o.ingested_at)                                      AS last_ingest,
  EXTRACT(DAY FROM now() - MAX(o.occurred_at) FILTER (
    WHERE o.occurred_precision IN ('exact','hour','day')
  ))::int                                                 AS days_since_latest,
  COUNT(*) FILTER (WHERE o.place_id IS NOT NULL)::float
    / NULLIF(COUNT(*),0)                                  AS place_resolved_pct
FROM dataset d
LEFT JOIN observation o ON o.dataset_id = d.dataset_id
GROUP BY d.dataset_id, d.key, d.v1_category, d.active;
