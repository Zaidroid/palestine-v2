-- 003 — reference layer: source, place, place_alias, dataset.

CREATE TABLE source (
  source_id       SERIAL PRIMARY KEY,
  key             TEXT UNIQUE NOT NULL,
  name            TEXT NOT NULL,
  kind            source_kind NOT NULL,
  -- Governance. commercial_use is enforced in the query layer (Phase 2),
  -- which is what keeps ACLED/OpenSky structurally loop-only.
  license_spdx    TEXT NOT NULL,
  commercial_use  BOOLEAN NOT NULL,
  attribution_text TEXT NOT NULL,
  authority_rank  SMALLINT NOT NULL CHECK (authority_rank BETWEEN 0 AND 6),
  -- Learned, never hand-typed (ARCHITECTURE §3.9 Loop A). NULL until measured.
  reliability             REAL CHECK (reliability BETWEEN 0 AND 1),
  reliability_measured_at TIMESTAMPTZ,
  reliability_n           INTEGER NOT NULL DEFAULT 0,
  -- Copy-collapse (P3.1): sources sharing a group count as ONE independent
  -- voice when scoring corroboration. NULL = independent.
  independence_group TEXT,
  active          BOOLEAN NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX source_commercial_idx   ON source (commercial_use) WHERE active;
CREATE INDEX source_independence_idx ON source (independence_group)
  WHERE independence_group IS NOT NULL;

COMMENT ON COLUMN source.reliability IS
  'Beta-Bernoulli posterior from Loop A. NULL until measured — never seed by hand.';

CREATE TABLE place (
  place_id      BIGSERIAL PRIMARY KEY,
  kind          place_kind NOT NULL,
  name_en       TEXT,
  name_ar       TEXT,
  admin1_pcode  TEXT,
  admin2_pcode  TEXT,
  oslo_area     TEXT CHECK (oslo_area IN ('A','B','C','H1','H2','seam','none')),
  geom          geometry(Geometry,4326) NOT NULL,
  centroid      geography(Point,4326)
                GENERATED ALWAYS AS ((ST_Centroid(geom))::geography) STORED,
  source_refs   JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {ocha_pcode, osm_id, pcbs_code, v1_canonical_key}
  confidence    REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
  attrs         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT place_has_a_name CHECK (name_en IS NOT NULL OR name_ar IS NOT NULL)
);
CREATE INDEX place_geom_idx     ON place USING GIST (geom);
CREATE INDEX place_centroid_idx ON place USING GIST (centroid);
CREATE INDEX place_kind_idx     ON place (kind);
CREATE INDEX place_admin2_idx   ON place (admin2_pcode) WHERE admin2_pcode IS NOT NULL;
CREATE INDEX place_name_ar_trgm ON place USING GIN (name_ar gin_trgm_ops);
CREATE INDEX place_name_en_trgm ON place USING GIN (name_en gin_trgm_ops);

-- Every spelling that has ever resolved. Grows itself: resolve/geo.py inserts
-- origin='observed' rows and increments hits, so Arabic matching improves for free.
CREATE TABLE place_alias (
  alias_norm  TEXT PRIMARY KEY,
  place_id    BIGINT NOT NULL REFERENCES place(place_id) ON DELETE CASCADE,
  hits        INTEGER NOT NULL DEFAULT 0,
  confidence  REAL NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
  origin      TEXT NOT NULL CHECK (origin IN ('ocha','osm','pcbs','checkpoint_db','observed','manual')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX place_alias_place_idx ON place_alias (place_id);
CREATE INDEX place_alias_trgm_idx  ON place_alias USING GIN (alias_norm gin_trgm_ops);

CREATE TABLE dataset (
  dataset_id   SERIAL PRIMARY KEY,
  key          TEXT UNIQUE NOT NULL,
  name         TEXT NOT NULL,
  source_id    INTEGER NOT NULL REFERENCES source(source_id),
  v1_category  TEXT,          -- provenance back to v1 for dual-run comparison
  cadence      TEXT,
  active       BOOLEAN NOT NULL DEFAULT true,
  attrs        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX dataset_source_idx ON dataset (source_id);
