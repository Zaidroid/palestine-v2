-- 019 — weather as a first-class state, from a structured source.
--
-- Weather was going to be added by polling Telegram weather channels. Measuring
-- the corpus first killed that plan: across 978 claims from ten channels there
-- were ZERO weather advisories, and the two live weather channels that
-- discovery surfaced post prose forecasts ("أجواء جافة وصافية وارتفاع ملموس
-- على درجات الحرارة") that would need their own parser to yield a number.
--
-- Open-Meteo gives the same information as structured data, per coordinate,
-- free and without an API key or an account. It is strictly better here: no
-- parser, no Telegram rate-limit exposure, and a value for every governorate
-- rather than only the ones a channel happened to mention.
--
-- Thresholds are stored as config rather than buried in code because they are
-- judgement, not physics — the Palestinian Meteorological Department issues
-- heat warnings in the high 30s, so 38°C is where an advisory starts here. The
-- raw numbers are kept on every observation regardless, so a revised threshold
-- can be applied to history instead of only to new readings.

INSERT INTO state_kind_config (state_kind, half_life_seconds, confidence_floor, note,
                               max_assert_seconds) VALUES
  ('weather', 10800, 0.25,
   'Conditions per governorate from Open-Meteo. 3h half-life — the API refreshes hourly and conditions move.',
   21600)
ON CONFLICT (state_kind) DO NOTHING;

CREATE TABLE weather_threshold (
  advisory   TEXT PRIMARY KEY,
  severity   SMALLINT NOT NULL,          -- higher wins when several apply
  note       TEXT NOT NULL
);
COMMENT ON TABLE weather_threshold IS
  'Advisory bands and their ordering. Values are judgement about when weather becomes worth telling someone, not measurements — kept here so they are reviewable and revisable against retained raw readings.';

INSERT INTO weather_threshold (advisory, severity, note) VALUES
  ('normal',        0, 'Nothing worth mentioning.'),
  ('rain',          1, 'Daily precipitation >= 10mm — wadi crossings and unpaved approaches degrade.'),
  ('heat_wave',     2, 'Max >= 38C. The PMD warns in this band; it is also when an unshaded checkpoint queue becomes dangerous.'),
  ('cold',          2, 'Min <= 4C — matters most for families in tents and unheated structures.'),
  ('storm',         3, 'Wind gusts >= 60km/h or precipitation >= 30mm.'),
  ('frost',         3, 'Min <= 0C.'),
  ('extreme_heat',  4, 'Max >= 42C.');
