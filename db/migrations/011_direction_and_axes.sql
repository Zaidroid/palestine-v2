-- 011 — direction becomes part of the state key, and presence stops
-- overwriting flow.
--
-- TWO MEASURED DEFECTS, BOTH STRUCTURAL.
--
-- (a) DIRECTION WAS COLLAPSED. v1 keys its live status by
--     (canonical_key, direction) — 786 rows for 403 checkpoints — and 109
--     checkpoints currently hold DIFFERENT statuses per direction. v2 keyed
--     state by (place_id, state_kind) alone, so "open inbound / closed
--     outbound" resolved to whichever report landed last. 15,894 of the
--     imported observations carry a direction; all of them were competing for
--     one slot.
--
-- (b) PRESENCE AND FLOW WERE THE SAME FIELD. `idf` and `open` displaced each
--     other on the same place within 10 minutes 1,889 times. They are not
--     rival values — "soldiers are here" and "traffic is moving" are both true
--     at once. Forcing them into one column meant every army sighting erased
--     the answer to "can I get through?", which is the question a traveller is
--     actually asking.
--
-- So: direction joins the primary key, and each presence type becomes its own
-- state_kind. That reuses the existing decay/cadence/serving machinery instead
-- of adding a parallel one, and it gets the semantics right for free — a
-- three-hour-old army sighting decays to `unknown` on its own timer while the
-- flow reading, which has its own cadence, is untouched.
--
-- Rollback: DROP the new state_kind_config rows; ALTER TABLE ... DROP COLUMN
-- direction; restore the PKs and the state_serving body from 009.

-- (db/migrate.sh runs each file with psql -1; no explicit BEGIN needed.)

-- ── direction on observations ────────────────────────────────────────────────
ALTER TABLE state_observation
  ADD COLUMN direction TEXT NOT NULL DEFAULT 'both'
    CHECK (direction IN ('inbound','outbound','both')),
  -- Whether the source SAID the direction or we defaulted to it. An explicit
  -- report must be able to outrank a general one for its own direction.
  ADD COLUMN direction_explicit BOOLEAN NOT NULL DEFAULT false,
  -- assertion | question | unparsed. Questions are retained (they are a real
  -- demand signal — which places people worry about) but never counted as
  -- evidence. See cascade/checkpoint_text.py.
  ADD COLUMN modality TEXT NOT NULL DEFAULT 'assertion'
    CHECK (modality IN ('assertion','question','unparsed'));

CREATE INDEX state_obs_dir_idx
  ON state_observation (place_id, state_kind, direction, observed_at DESC);

-- ── direction in the current-belief key ──────────────────────────────────────
DROP VIEW IF EXISTS state_serving;

ALTER TABLE state_current
  ADD COLUMN direction TEXT NOT NULL DEFAULT 'both'
    CHECK (direction IN ('inbound','outbound','both'));
ALTER TABLE state_current DROP CONSTRAINT state_current_pkey;
ALTER TABLE state_current ADD PRIMARY KEY (place_id, state_kind, direction);

-- Cadence is per direction too: a checkpoint reported constantly for 'both'
-- but twice for 'inbound' must not have its inbound belief kept alive by the
-- busy channel's rhythm.
ALTER TABLE place_state_cadence
  ADD COLUMN direction TEXT NOT NULL DEFAULT 'both'
    CHECK (direction IN ('inbound','outbound','both'));
ALTER TABLE place_state_cadence DROP CONSTRAINT place_state_cadence_pkey;
ALTER TABLE place_state_cadence ADD PRIMARY KEY (place_id, state_kind, direction);

-- ── the new kinds ────────────────────────────────────────────────────────────
-- Flow is an ordered, mutually-exclusive scale. Presence kinds are independent
-- booleans, each with its own half-life: soldiers move on faster than a road
-- reopens, so they must not share a decay curve.
INSERT INTO state_kind_config (state_kind, half_life_seconds, confidence_floor, note) VALUES
  ('checkpoint_flow',       5400, 0.25, 'Throughput: open|slow|congested|closed. Per-place cadence overrides this default.'),
  ('checkpoint_idf',        3600, 0.30, 'Army present. Shorter than flow — a patrol moves on well before a closure lifts.'),
  ('checkpoint_police',     3600, 0.30, 'Israeli police present.'),
  ('checkpoint_settlers',   3600, 0.35, 'Settler presence. Higher floor: only assert it on fresh, corroborated evidence.'),
  ('checkpoint_inspection', 3600, 0.30, 'ID checks / search in progress.')
ON CONFLICT (state_kind) DO NOTHING;

COMMENT ON COLUMN state_observation.direction IS
  'Which way the report is about. ''both'' is also the default when unstated — see direction_explicit.';
COMMENT ON COLUMN state_observation.modality IS
  'assertion is evidence; question and unparsed are retained but excluded from belief.';

-- ── serving contract, now direction-aware ────────────────────────────────────
CREATE VIEW state_serving AS
SELECT
  sc.place_id,
  p.name_en, p.name_ar, p.kind AS place_kind, p.centroid,
  sc.state_kind,
  sc.direction,
  sc.value                                   AS last_known_value,
  sc.observed_at,
  EXTRACT(EPOCH FROM (now() - sc.observed_at))::bigint / 60 AS age_minutes,
  sc.independent_sources,
  sc.contradicted_by,
  COALESCE(c.half_life_seconds, k.half_life_seconds)        AS half_life_seconds,
  c.median_gap_seconds,
  (c.place_id IS NOT NULL)                                  AS cadence_measured,
  state_confidence(sc.base_confidence, sc.observed_at,
                   COALESCE(c.half_life_seconds, k.half_life_seconds), now()) AS confidence,
  CASE
    WHEN state_confidence(sc.base_confidence, sc.observed_at,
                          COALESCE(c.half_life_seconds, k.half_life_seconds), now())
         < k.confidence_floor THEN 'unknown'
    ELSE sc.value
  END AS value,
  CASE
    WHEN now() - sc.observed_at
         < make_interval(secs => COALESCE(c.half_life_seconds, k.half_life_seconds))     THEN 'live'
    WHEN now() - sc.observed_at
         < make_interval(secs => COALESCE(c.half_life_seconds, k.half_life_seconds) * 2) THEN 'recent'
    WHEN now() - sc.observed_at
         < make_interval(secs => COALESCE(c.half_life_seconds, k.half_life_seconds) * 8) THEN 'stale'
    ELSE 'expired'
  END AS staleness_band
FROM state_current sc
JOIN state_kind_config k        ON k.state_kind = sc.state_kind
JOIN place p                    ON p.place_id   = sc.place_id
LEFT JOIN place_state_cadence c ON c.place_id   = sc.place_id
                               AND c.state_kind = sc.state_kind
                               AND c.direction  = sc.direction;

COMMENT ON VIEW state_serving IS
  'Serving contract. API MUST read from here, never state_current. Applies per-place-and-direction decay and returns value=unknown below the floor, with the last reading preserved in last_known_value.';
