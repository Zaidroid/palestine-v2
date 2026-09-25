-- 082 — one row per checkpoint: duplicates merged, fragments renamed, Karmelo moved.
--
-- Two testers on 2026-09-25 (Fawwaz through the partner door, Claude web through
-- the connector) hit the same class: a name lookup landing on the wrong twin.
-- "اللبن الشرقية" answered from row 1641 (a reading 10 hours old) while row 1739
-- (the one palhub and the channels feed) read 5 minutes old; "الكونتينر" existed
-- seven times (three Arabic, one Hebrew, three misspellings); nine names had two
-- or three servable rows. Some rows still carry the road-channel message they
-- were minted from as their name ('حادث سير جبع', 'ديرشرف بدون', 'صررره
-- نسحبوو', 'الجيب فاضي'); six carry Hebrew-only OSM names; and 'كراميلو
-- الطيبه' — the Karmel checkpoint south-east of Yatta — sat on الطيبة in JENIN
-- (row 746), 120 km north, with the Hebron Khirbat at Tayyibah's PCBS aliases
-- attached to that Jenin village.
--
-- What this does (039 is the precedent for the merge mechanics):
--   1. 20 rows merged into the row that carries the readings (merged_into set,
--      servable off; chains re-pointed so nothing points at a merged row).
--   2. Their observations of the last two days and their beliefs move to the
--      survivor; older observations stay (compressed chunks; the resolver and
--      the serving views follow merged_into for history).
--   3. Aliases of merged rows re-pointed to the survivor.
--   4. Six rows renamed from a message fragment / Hebrew-only name to the
--      place's name (previous name kept in attrs).
--   5. Two rows made unservable (not a place / unidentified).
--   6. Karmelo (1759) moved to Karmel with its fourteen aliases; a Hebron
--      locality خربة الطيبة created for the three PCBS aliases that belong to it.
--
-- Rollback (exact):
--   UPDATE place SET merged_into = NULL, servable = true, quality_note = NULL
--    WHERE attrs->>'merged_by' = '082';
--   UPDATE place SET name_ar = attrs->>'name_ar_before_082', name_en = attrs->>'name_en_before_082'
--    WHERE attrs ? 'name_ar_before_082';
--   UPDATE place SET servable = true WHERE attrs->>'unservable_by' = '082';
--   UPDATE place SET geom = ST_GeomFromText(attrs->>'geom_before_082', 4326),
--          admin1_pcode = attrs->>'admin1_before_082', admin2_pcode = attrs->>'admin2_before_082'
--    WHERE attrs ? 'geom_before_082';
--   UPDATE state_observation SET place_id = (attrs->>'moved_from')::int, attrs = attrs - 'moved_from' - 'moved_by'
--    WHERE attrs->>'moved_by' = '082';
--   UPDATE place_alias SET place_id = 746 WHERE alias_norm IN (<the seventeen aliases listed in section 6>);
--   DELETE FROM place WHERE attrs->>'migration' = '082';
--   (alias re-points of section 3 are recorded per row in place.attrs.aliases_moved_082)

SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;

-- 1. merges
CREATE TEMP TABLE m082 (loser int PRIMARY KEY, survivor int NOT NULL);
INSERT INTO m082 VALUES
  (1604, 1501),
  (1736, 1501),
  (1780, 1501),
  (1781, 1501),
  (1815, 1501),
  (1824, 1501),
  (1643, 1797),
  (1768, 1797),
  (1743, 1582),
  (1834, 1822),
  (1717, 1520),
  (1535, 1767),
  (1817, 1767),
  (1737, 1488),
  (1738, 1633),
  (1641, 1739),
  (1786, 1480),
  (1603, 1482),
  (1818, 1482),
  (1494, 1465);

-- a survivor must be a live row
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM m082 m JOIN place p ON p.place_id = m.survivor WHERE p.merged_into IS NOT NULL OR NOT p.servable)
  THEN RAISE EXCEPTION '082: a survivor is merged or unservable'; END IF;
END $$;

UPDATE place p
   SET attrs = COALESCE(p.attrs, '{}'::jsonb) || jsonb_build_object(
                 'merged_by', '082',
                 'aliases_moved_082', (SELECT COALESCE(jsonb_agg(a.alias_norm), '[]'::jsonb)
                                         FROM place_alias a WHERE a.place_id = p.place_id))
  FROM m082 m WHERE p.place_id = m.loser AND p.merged_into IS NULL;

-- chains: whatever pointed at a loser now points at its survivor
UPDATE place p SET merged_into = m.survivor
  FROM m082 m WHERE p.merged_into = m.loser;

UPDATE place p
   SET merged_into = m.survivor, servable = false,
       quality_note = COALESCE(quality_note || ' · ', '') || 'merged 082: duplicate of ' || m.survivor
  FROM m082 m WHERE p.place_id = m.loser;

-- 2. observations (two days: what the serving layer still reads) and beliefs
UPDATE state_observation o
   SET place_id = m.survivor,
       attrs = COALESCE(o.attrs, '{}'::jsonb) || jsonb_build_object('moved_from', o.place_id, 'moved_by', '082')
  FROM m082 m
 WHERE o.place_id = m.loser AND o.observed_at >= now() - interval '2 days';

UPDATE state_current sc SET place_id = m.survivor
  FROM m082 m
 WHERE sc.place_id = m.loser
   AND NOT EXISTS (SELECT 1 FROM state_current c2
                    WHERE c2.place_id = m.survivor AND c2.state_kind = sc.state_kind
                      AND c2.direction IS NOT DISTINCT FROM sc.direction);
DELETE FROM state_current sc USING m082 m WHERE sc.place_id = m.loser;

-- 3. aliases follow the survivor (an alias the survivor already owns is dropped)
DELETE FROM place_alias a USING m082 m
 WHERE a.place_id = m.loser
   AND EXISTS (SELECT 1 FROM place_alias b WHERE b.alias_norm = a.alias_norm AND b.place_id = m.survivor);
UPDATE place_alias a SET place_id = m.survivor FROM m082 m WHERE a.place_id = m.loser;
-- palhub's declared wording follows too
UPDATE place s
   SET attrs = COALESCE(s.attrs, '{}'::jsonb)
             || jsonb_build_object('palhub_names',
                  (SELECT jsonb_agg(DISTINCT x) FROM jsonb_array_elements_text(
                     COALESCE(s.attrs->'palhub_names', '[]'::jsonb) || COALESCE(l.attrs->'palhub_names', '[]'::jsonb)) x))
  FROM m082 m, place l
 WHERE s.place_id = m.survivor AND l.place_id = m.loser AND l.attrs ? 'palhub_names';

-- 4. names
UPDATE place p
   SET attrs = COALESCE(p.attrs, '{}'::jsonb)
             || jsonb_build_object('name_ar_before_082', p.name_ar, 'name_en_before_082', p.name_en),
       name_ar = v.ar, name_en = v.en
  FROM (VALUES
    (1749, 'حاجز الجيب', 'Al Jib checkpoint'),
    (1485, 'دوار تقوع', 'Tuqu'' roundabout'),
    (1765, 'أريحا الجنوبي (DCO)', 'Jericho South (DCO)'),
    (1814, 'بوابة يكير', 'Yakir gate'),
    (1816, 'حاجز رنتيس', 'Rantis checkpoint'),
    (1821, 'معبر مكابيم', 'Maccabim crossing')
) AS v(place_id, ar, en)
 WHERE p.place_id = v.place_id;

-- 5. not a place / unidentified
UPDATE place p
   SET servable = false,
       attrs = COALESCE(p.attrs, '{}'::jsonb) || jsonb_build_object('unservable_by', '082'),
       quality_note = v.why
  FROM (VALUES
    (1602, '''حادث سير عطريق المجدل'' is a traffic-accident message, not a place (082)'),
    (1823, 'Hebrew-only OSM name ''מחסום בל'' could not be identified (082)')
) AS v(place_id, why)
 WHERE p.place_id = v.place_id;

-- 6. Karmelo, south-east of Yatta, not in Jenin
UPDATE place
   SET attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object(
                 'geom_before_082', ST_AsText(geom), 'admin1_before_082', admin1_pcode,
                 'admin2_before_082', admin2_pcode, 'geo_precision', 'approx',
                 'moved_by', '082'),
       geom = ST_SetSRID(ST_MakePoint(35.13, 31.425), 4326),
       admin1_pcode = 'PS01', admin2_pcode = 'PS0150',
       name_en = 'Karmel checkpoint (Yatta)',
       quality_note = 'moved 082: sat on Jenin''s الطيبة; the Karmel checkpoint is south-east of Yatta (position approximate)'
 WHERE place_id = 1759;

INSERT INTO place (kind, name_ar, name_en, admin1_pcode, admin2_pcode, geom, confidence, source_refs, attrs, servable)
SELECT 'locality', 'خربة الطيبة', 'Khirbat at Tayyibah', 'PS01', 'PS0150',
       ST_SetSRID(ST_MakePoint(35.125, 31.428), 4326), 0.7,
       jsonb_build_object('origin', 'PCBS locality name; position entered by hand (082)'),
       jsonb_build_object('geo_precision', 'approx', 'migration', '082'), true
 WHERE NOT EXISTS (SELECT 1 FROM place WHERE attrs->>'migration' = '082' AND name_ar = 'خربة الطيبة');

UPDATE place_alias SET place_id = 1759
 WHERE place_id = 746 AND alias_norm IN ('الطيبه كارميلو', 'الطيبه كراميلو', 'بوابات الطيبه', 'بوابات طيبه', 'بوابه الطيبه', 'طيبه كارميلو', 'طيبه كراميلو', 'كراملو الطيبه', 'كراملو طيبه', 'كراميلو', 'كراميلو الطيبه', 'كراميلو طيبه', 'كرميلو الطيبه', 'كرميلو طيبه');
UPDATE place_alias SET place_id = (SELECT place_id FROM place WHERE attrs->>'migration' = '082' AND name_ar = 'خربة الطيبة')
 WHERE place_id = 746 AND alias_norm IN ('khirbat at tayyibah', 'khirbat aţ ţayyibah', 'khirbet at taiyiba');
-- palhub's 'حاجة الطيبة' (observed 1,343 times on the Jenin village) is the Ramallah gate declared in 081
UPDATE place_alias SET place_id = (SELECT place_id FROM place WHERE attrs->'palhub_names' ? 'حاجة الطيبة' LIMIT 1)
 WHERE alias_norm = 'حاجه طيبه' AND place_id = 746
   AND EXISTS (SELECT 1 FROM place WHERE attrs->'palhub_names' ? 'حاجة الطيبة');

DROP TABLE m082;
