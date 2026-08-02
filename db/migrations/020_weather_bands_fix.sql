-- 020 — a storm needs rain, and wind must not outrank heat.
--
-- 019's bands fired `storm` on gusts alone at 60km/h. West Bank hill country
-- gusts 35-68km/h on an ordinary clear afternoon, so on the first real run two
-- dry summer days were reported as storms with 0.0mm of precipitation.
--
-- The worse half was the ordering. `storm` outranked `heat_wave`, so Tubas at
-- 38.8C and 0mm read as `storm` and LOST its heat warning — the fact that
-- matters to someone standing in a checkpoint queue, displaced by the one that
-- does not. The same axis-collapse that made an army sighting erase whether a
-- road was passable.
--
-- Storm now requires precipitation. Dry wind gets its own band, ranked below
-- the temperature bands so it can never displace them.

UPDATE weather_threshold SET
  severity = 3,
  note = 'Precipitation >= 30mm, or >= 5mm with gusts >= 70km/h. Rain is required: gusts alone are ordinary summer weather here.'
WHERE advisory = 'storm';

INSERT INTO weather_threshold (advisory, severity, note) VALUES
  ('high_wind', 1,
   'Dry gusts >= 70km/h. Deliberately ranked BELOW the temperature bands — a hot windy day is a heat problem first.')
ON CONFLICT (advisory) DO UPDATE SET severity = EXCLUDED.severity, note = EXCLUDED.note;
