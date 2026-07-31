-- 004 — belief layer. `event` holds current rows; `event_history` holds
-- superseded versions. Together they replace v1's 15 GB of daily full copies:
-- an as-of query becomes a range lookup, not a different directory.

CREATE TABLE event (
  event_id            BIGSERIAL PRIMARY KEY,
  event_type          TEXT NOT NULL,
  place_id            BIGINT REFERENCES place(place_id),
  geom                geography(Point,4326),
  occurred_at         TIMESTAMPTZ,
  occurred_precision  time_precision NOT NULL DEFAULT 'unknown',
  -- belief, not fact
  status              event_status NOT NULL DEFAULT 'believed',
  confidence          REAL NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
  claim_count         INTEGER NOT NULL DEFAULT 0,
  -- Post-copy-collapse count. This is the corroboration signal v1 computed and
  -- discarded; here it is a first-class column that confidence depends on.
  independent_sources INTEGER NOT NULL DEFAULT 0,
  contradicted_by     INTEGER NOT NULL DEFAULT 0,
  superseded_by       BIGINT REFERENCES event(event_id),
  correction_note     TEXT,
  metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
  attrs               JSONB NOT NULL DEFAULT '{}'::jsonb,
  sys_period          TSTZRANGE NOT NULL DEFAULT tstzrange(clock_timestamp(), NULL),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX event_geom_idx     ON event USING GIST (geom);
CREATE INDEX event_sys_idx      ON event USING GIST (sys_period);
CREATE INDEX event_occurred_idx ON event (occurred_at DESC);
CREATE INDEX event_type_idx     ON event (event_type);
CREATE INDEX event_place_idx    ON event (place_id);
CREATE INDEX event_status_idx   ON event (status);

CREATE TABLE event_history (LIKE event INCLUDING DEFAULTS);
ALTER TABLE event_history ADD PRIMARY KEY (event_id, sys_period);
CREATE INDEX event_history_sys_idx ON event_history USING GIST (sys_period);
CREATE INDEX event_history_id_idx  ON event_history (event_id);

-- SCD-2 versioning. Column list written out explicitly (no dynamic SQL) so the
-- mapping is auditable; if `event` gains a column, this trigger must be updated
-- in the same migration — the INSERT will fail loudly otherwise.
CREATE OR REPLACE FUNCTION event_versioning() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE
  -- clock_timestamp(), NOT now(): now() is transaction-start time, so an
  -- insert-then-update inside one transaction would produce tstzrange(x,x) —
  -- an EMPTY range, which contains no instant (breaking as-of) and compares
  -- equal to every other empty range (colliding on event_history's PK).
  -- The resolver creates an event and updates its confidence in one
  -- transaction, so this is the normal path, not an edge case.
  now_ts    TIMESTAMPTZ := clock_timestamp();
  closed    TSTZRANGE;
BEGIN
  IF (to_jsonb(OLD) - 'sys_period' - 'updated_at')
     IS DISTINCT FROM (to_jsonb(NEW) - 'sys_period' - 'updated_at') THEN
    closed := tstzrange(lower(OLD.sys_period), now_ts);
    -- Belt and braces: if two updates land in the same microsecond the range is
    -- still empty. That version was never visible to another transaction, so
    -- there is no history worth keeping — skip the insert rather than fail.
    IF NOT isempty(closed) THEN
      INSERT INTO event_history VALUES (
        OLD.event_id, OLD.event_type, OLD.place_id, OLD.geom, OLD.occurred_at,
        OLD.occurred_precision, OLD.status, OLD.confidence, OLD.claim_count,
        OLD.independent_sources, OLD.contradicted_by, OLD.superseded_by,
        OLD.correction_note, OLD.metrics, OLD.attrs,
        closed, OLD.created_at, OLD.updated_at
      );
    END IF;
    NEW.sys_period := tstzrange(now_ts, NULL);
    NEW.updated_at := now_ts;
  END IF;
  RETURN NEW;
END $fn$;

CREATE TRIGGER event_versioning_trg
  BEFORE UPDATE ON event
  FOR EACH ROW EXECUTE FUNCTION event_versioning();

-- as-of surface used by the API and the Phase 2 verification harness.
CREATE OR REPLACE FUNCTION event_as_of(at TIMESTAMPTZ)
RETURNS SETOF event LANGUAGE sql STABLE AS $fn$
  SELECT * FROM event         WHERE sys_period @> at
  UNION ALL
  SELECT * FROM event_history WHERE sys_period @> at
$fn$;
