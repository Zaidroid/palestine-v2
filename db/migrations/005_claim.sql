-- 005 — claim layer: immutable record of what a source asserted.
-- Never updated after insert (except event_id on resolution). Retraction
-- happens on `event`, so the historical record of what was said stays intact.

CREATE TABLE claim (
  claim_id          BIGSERIAL,
  source_id         INTEGER NOT NULL REFERENCES source(source_id),
  external_id       TEXT,                       -- telegram msg id, article guid, API row key
  raw_ref           TEXT NOT NULL,              -- pointer into data/bronze
  raw_text          TEXT,
  lang              TEXT,
  claim_type        TEXT NOT NULL DEFAULT 'unclassified',
  place_id          BIGINT REFERENCES place(place_id),
  place_precision   place_precision NOT NULL DEFAULT 'unknown',
  place_phrase      TEXT,                       -- the literal string we resolved from
  occurred_at       TIMESTAMPTZ,
  occurred_precision time_precision NOT NULL DEFAULT 'unknown',
  reported_at       TIMESTAMPTZ NOT NULL,
  ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  attrs             JSONB NOT NULL DEFAULT '{}'::jsonb,
  extraction        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {tier:'t1'|'t2'|'t3', scores:{}}
  event_id          BIGINT REFERENCES event(event_id),
  content_hash      TEXT,                       -- simhash/minhash for copy-collapse (P3.1)
  PRIMARY KEY (claim_id, ingested_at)
);
SELECT create_hypertable('claim','ingested_at', chunk_time_interval => INTERVAL '7 days');

CREATE INDEX claim_source_idx   ON claim (source_id, ingested_at DESC);
CREATE INDEX claim_event_idx    ON claim (event_id) WHERE event_id IS NOT NULL;
CREATE INDEX claim_type_idx     ON claim (claim_type, ingested_at DESC);
CREATE INDEX claim_place_idx    ON claim (place_id) WHERE place_id IS NOT NULL;
CREATE INDEX claim_occurred_idx ON claim (occurred_at DESC) WHERE occurred_at IS NOT NULL;
CREATE INDEX claim_hash_idx     ON claim (content_hash) WHERE content_hash IS NOT NULL;

-- Idempotent ingest. A unique index on a hypertable must include the partition
-- column, which would not actually prevent re-ingest across chunks — so
-- dedup lives in this small plain table instead.
CREATE TABLE claim_dedup (
  source_id   INTEGER NOT NULL REFERENCES source(source_id),
  external_id TEXT NOT NULL,
  claim_id    BIGINT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (source_id, external_id)
);

COMMENT ON TABLE claim IS
  'Immutable. What a source SAID. Beliefs live in `event`; never edit history here.';
