-- 059 — indicators get a meaning, so two series can be compared at all
--
-- "Electricity vs casualties vs displacement in Khan Younis" is unanswerable
-- today, and not for want of data. Measured 2026-08-08:
--
--   1,408 free-text indicator strings and 45 unit strings, of which:
--     · persons / people           — one unit, two spellings
--     · count / number / units     — one unit, three spellings
--     · percentage / percent       — one unit, two spellings
--     · TWELVE ILS/<pack> strings  — ILS/KG, ILS/500 G, ILS/25 KG, ILS/2 KG,
--       ILS/3 L, ILS/Cubic meter, ILS/L, ILS/60 KG, ILS/50 KG, ILS/2.5 KG,
--       ILS/380 G, ILS/12 KG. Each bakes a PACK SIZE into the unit, so two
--       flour prices are incomparable unless a human happens to notice that
--       one is per 25 kg and the other per kilo.
--
--   And nothing anywhere records what KIND of number a series holds. A
--   cumulative death toll and a daily death count are both "persons"; adding
--   them is meaningless and nothing stops it. That distinction — measure_kind
--   — is what makes the difference between a comparison and a category error.
--
-- Four tables, and one rule that governs all of them:
--
--   NORMALISATION IS A VIEW, NEVER AN OVERWRITE. `observation.unit` and
--   `observation.value_num` keep exactly what the source said, forever.
--   v_observation_canonical exposes the converted pair beside the raw one.
--   A databank that rewrites its own values to make them comparable has
--   destroyed the thing it was built to preserve.

-- ── concepts: what a series is ABOUT ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS concept (
    key         text PRIMARY KEY,
    parent      text REFERENCES concept(key),
    name_en     text NOT NULL,
    name_ar     text,
    definition  text NOT NULL,
    notes       text
);
COMMENT ON TABLE concept IS
  'A reviewed taxonomy of what the databank measures. Loaded from '
  'db/registry/concepts.yaml — a document, reviewed before it is data.';

-- ── units: what a number IS ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS unit_def (
    key         text PRIMARY KEY,
    name_en     text NOT NULL,
    name_ar     text,
    dimension   text NOT NULL,   -- count | mass | volume | price_per_mass …
    notes       text
);

CREATE TABLE IF NOT EXISTS unit_alias (
    raw         text PRIMARY KEY,          -- exactly as the source writes it
    unit_key    text NOT NULL REFERENCES unit_def(key),
    -- An EXACT rational, never a rounded float. ILS/380 G → ILS/kg is
    -- 1000/380, and ILS/12 KG is 1/12; storing 2.6315789 or 0.0833333 puts a
    -- rounding error into every converted price. Postgres does numeric
    -- division exactly at high precision — the same lesson as the identity
    -- renderer, where Python's 106.0 and SQL's 106 disagreed.
    factor_num  numeric NOT NULL DEFAULT 1,
    factor_den  numeric NOT NULL DEFAULT 1,
    note        text,
    CONSTRAINT unit_alias_den_nonzero CHECK (factor_den <> 0)
);
COMMENT ON COLUMN unit_alias.factor_num IS
  'canonical_value = value_num * factor_num / factor_den. Exact rational.';

-- ── indicators: the join between a string and a meaning ─────────────────────
CREATE TABLE IF NOT EXISTS indicator_def (
    indicator     text PRIMARY KEY,
    concept_key   text REFERENCES concept(key),
    name_en       text,
    name_ar       text,
    canonical_unit text REFERENCES unit_def(key),
    measure_kind  text NOT NULL DEFAULT 'unclassified',
    polarity      smallint,      -- +1 more is better, -1 worse, NULL neither
    grain         text,          -- the period a single row covers
    place_grain   text,          -- region | governorate | locality | point
    status        text NOT NULL DEFAULT 'generated',
    source_spec   text,          -- which spec's registry block produced it
    notes         text,
    updated_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT indicator_measure_kind CHECK (measure_kind IN (
        'stock',        -- a level at a moment (population, prisoners held)
        'flow',         -- an amount during a period (killed that day)
        'cumulative',   -- a running total since some epoch
        'rate',         -- per-something (per 1,000 live births)
        'index',        -- unitless, relative to a base
        'ratio',        -- a proportion or percentage
        'status',       -- categorical (open / closed / partial)
        'unclassified'  -- COUNTED, never silently ignored
    )),
    CONSTRAINT indicator_polarity CHECK (polarity IN (-1, 1) OR polarity IS NULL),
    CONSTRAINT indicator_status CHECK (status IN ('reviewed', 'generated'))
);
COMMENT ON COLUMN indicator_def.measure_kind IS
  'The distinction that makes comparison possible. A cumulative death toll '
  'and a daily death count are both "persons"; adding them is a category '
  'error, and only this column can tell them apart.';
COMMENT ON COLUMN indicator_def.polarity IS
  'Whether a rise is good or bad. Needed so a correlation can be described '
  'in words without a human deciding the sign each time. NULL where the '
  'question is meaningless (a population count is neither).';

CREATE INDEX IF NOT EXISTS indicator_def_concept ON indicator_def (concept_key);
CREATE INDEX IF NOT EXISTS indicator_def_kind ON indicator_def (measure_kind);

-- ── the canonical view: raw values untouched, converted values beside them ──
CREATE OR REPLACE VIEW v_observation_canonical AS
SELECT ds.*,
       i.concept_key,
       i.measure_kind,
       i.polarity,
       i.grain            AS indicator_grain,
       i.place_grain,
       i.canonical_unit,
       CASE WHEN ds.value_num IS NOT NULL AND ua.unit_key IS NOT NULL
            THEN ds.value_num * ua.factor_num / ua.factor_den
       END                AS value_canonical,
       ua.unit_key        AS resolved_unit,
       -- Visible so a consumer can see that a conversion happened and by
       -- how much, rather than being handed a number that quietly differs
       -- from the one in `value_num`.
       CASE WHEN ua.factor_num <> ua.factor_den
            THEN ua.factor_num || '/' || ua.factor_den
       END                AS unit_conversion
FROM databank_serving ds
LEFT JOIN indicator_def i ON i.indicator = ds.indicator
LEFT JOIN unit_alias   ua ON ua.raw      = ds.unit;

COMMENT ON VIEW v_observation_canonical IS
  'databank_serving plus meaning: concept, measure_kind, polarity, and the '
  'unit-converted value. value_num and unit are the source''s own and are '
  'never rewritten — this view adds, it does not replace.';
