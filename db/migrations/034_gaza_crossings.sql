-- 034 — Gaza's crossings, and a state kind that fits them.
--
-- The Gaza geography was already loaded: 239 places across all five
-- governorates, full admin hierarchy, 100% admin2 coverage since 032. What was
-- missing was the part that actually determines whether anything moves — the
-- CROSSINGS. All three `crossing` rows in the database were West Bank (Allenby,
-- Jericho terminal, Te'enim). Rafah and Kerem Shalom, which everything and
-- everybody passes through, were simply not represented.
--
-- WHY A CROSSING IS NOT A CHECKPOINT
-- The checkpoint model assumes a road with two directions and a flow state that
-- decays in about ninety minutes. A crossing is a different object:
--
--   * It is asymmetric in KIND, not just direction. Kerem Shalom takes goods
--     and returns nothing; Rafah moves people. "inbound/outbound" does not
--     describe that.
--   * Its state persists for days or weeks, not ninety minutes. A crossing
--     announced closed on Monday is very likely still closed on Tuesday, which
--     is the opposite of a checkpoint queue.
--   * "Open" is rarely binary. It is open for medical evacuations, or for aid
--     lorries, or for a named list of people. Recording that as `open` would be
--     the most consequential kind of false reassurance this system can produce.
--
-- So `crossing_status` is its own kind with its own half-life, and its
-- vocabulary keeps `partial` distinct from `open` rather than rounding the
-- ambiguity away.
--
-- COORDINATES ARE PUBLIC GEOGRAPHY, RECORDED AS APPROXIMATE
-- These are well-known locations, but they are entered by hand from public
-- knowledge rather than surveyed, so each carries geo_precision 'approx' and
-- says where it came from. The serving layer already refuses to quote drive
-- times to anything short of street precision, so an approximate crossing can
-- carry status without pretending to be navigable to the metre.
--
-- WHAT THIS DOES NOT DO
-- It adds the places and the vocabulary. It does not invent data: there is no
-- Gaza source producing crossing status yet, so every one of these will read
-- `unknown` until one exists. That is the honest state and it is visible rather
-- than hidden — the alternative, leaving the crossings out entirely, makes the
-- same ignorance invisible.

-- ── the crossings ────────────────────────────────────────────────────────────

-- `centroid` is a GENERATED column derived from geom; supplying it is an error.
INSERT INTO place (kind, name_ar, name_en, geom, confidence,
                   source_refs, attrs, servable)
SELECT 'crossing', v.ar, v.en,
       ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326),
       0.9,
       jsonb_build_object('origin', 'public geography, entered by hand (034)'),
       jsonb_build_object('geo_precision', 'approx',
                          'crossing_role', v.role,
                          'note', v.note),
       true
FROM (VALUES
  ('معبر رفح',            'Rafah Crossing',
   31.2478, 34.2647, 'people',
   'Gaza-Egypt. The only crossing not controlled by Israel on both sides; movement of people.'),
  ('معبر كرم أبو سالم',   'Kerem Shalom Crossing',
   31.2233, 34.2683, 'goods',
   'Gaza-Israel-Egypt tri-point. Principal goods and aid crossing; asymmetric — takes lorries in.'),
  ('معبر بيت حانون (إيرز)', 'Erez Crossing (Beit Hanoun)',
   31.5606, 34.5450, 'people',
   'Northern Gaza-Israel. Historically the pedestrian and worker crossing.'),
  ('معبر زيكيم',          'Zikim Crossing',
   31.5936, 34.5169, 'goods',
   'Northern aid corridor.'),
  ('معبر كيسوفيم',        'Kissufim Crossing',
   31.3661, 34.3903, 'goods',
   'Central Gaza. Used for aid at various times.')
) AS v(ar, en, lat, lon, role, note)
WHERE NOT EXISTS (SELECT 1 FROM place p WHERE p.kind = 'crossing' AND p.name_en = v.en);

-- Attach each to its governorate from its own coordinates, the same spatial
-- method migration 032 used, so they inherit the admin hierarchy that makes
-- them queryable by area.
UPDATE place p
   SET admin2_pcode = g.admin2_pcode,
       admin1_pcode = COALESCE(p.admin1_pcode, g.admin1_pcode)
  FROM place g
 WHERE p.kind = 'crossing' AND p.admin2_pcode IS NULL
   AND g.kind = 'governorate' AND g.geom IS NOT NULL
   AND ST_Contains(g.geom::geometry, p.centroid::geometry);

-- ── the state kind ───────────────────────────────────────────────────────────

INSERT INTO state_kind_config
  (state_kind, half_life_seconds, confidence_floor, max_assert_seconds,
   serving_mode, note,
   crowd_reportable, crowd_values, crowd_gated_values, crowd_min_units,
   crowd_max_per_hour)
VALUES
  ('crossing_status',
   -- 12 hours. A crossing's state persists on the order of days, so decaying it
   -- like a checkpoint queue (90 min) would throw away information that is
   -- still true. The 72-hour assert ceiling still stops a week-old
   -- announcement being served as today's.
   43200, 0.30, 259200, 'state',
   'Gaza and West Bank crossings. Slow-moving by nature: half-life 12h, '
   || 'assert ceiling 72h. `partial` is deliberately NOT collapsed into '
   || '`open` — a crossing open only for medical evacuation is not open, and '
   || 'reporting it as open is the most costly false reassurance available.',
   true,
   ARRAY['open', 'partial', 'closed'],
   -- Both `open` and `partial` are reassuring and both are gated: somebody
   -- travelling to a crossing on a single unverified report may have nowhere
   -- to return to.
   ARRAY['open', 'partial'],
   2, 4)
ON CONFLICT (state_kind) DO NOTHING;

COMMENT ON TABLE place IS
  'Every place the system can talk about. Gaza crossings were added in 034: the '
  'geography had been loaded since the OCHA import but the crossings — the '
  'chokepoints that decide whether anything moves — were absent, so nothing '
  'could be said about them at all.';
