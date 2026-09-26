-- 087 — three checkpoints served in the wrong governorate, placed by the messages that name them.
--
-- Found 2026-09-26 by the roads gold reader (P1-A.5) and checked against 21 days of v1's tee spool:
--
--   كراميلو الطيبه (1759). Migration 082 moved it from Jenin's الطيبة to a "Karmel checkpoint" south-east
--     of Yatta. WRONG: the 846 messages that name it say "يبرود سلواد الطيبة كراميلو سالك", "المعرجات كرملوا
--     سالكين", "بوابة الطيبة كراميلو" — it is the gate of Taybeh, RAMALLAH, on the Mu'arrajat road. 418
--     readings in the last 7 days were being filed in Hebron.
--   الفحص (1499). v1's registry put it near Nablus (32.12, 35.28). 659 messages list it between زيف and
--     سعير ("✅ زيف سالكة. | ✅ الفحص سالكة. | ✅ سعير سالكة.") and the southern channel carries it: HEBRON.
--   البنانا (1531). v1's registry put it beside al-Fahs near Nablus (32.127, 35.283). Its 69 messages list
--     it with Jericho's exits ("✅ أريحا Dco | ✅ بنانا | ✅ حاجز الهيئة", "المعرجات لحاجز البنانا"): JERICHO.
--
-- Positions are ANCHORED to the town (geo_precision 'approx-anchor', the 081 convention), never guessed
-- to a street: the governorate is certain, the metre is not.
--
-- Rollback (exact; the before-values are kept on each row):
--   UPDATE place SET geom = ST_GeomFromText(attrs->>'geom_before_087', 4326),
--                    admin2_pcode = attrs->>'admin2_before_087', name_en = attrs->>'name_en_before_087',
--                    quality_note = attrs->>'quality_note_before_087',
--                    attrs = attrs - 'geom_before_087' - 'admin2_before_087' - 'name_en_before_087'
--                                  - 'quality_note_before_087' - 'moved_by_087' - 'anchored_to_087'
--    WHERE attrs ? 'moved_by_087';

UPDATE place p
   SET attrs = COALESCE(p.attrs, '{}'::jsonb) || jsonb_build_object(
                 'geom_before_087', ST_AsText(p.geom), 'admin2_before_087', p.admin2_pcode,
                 'name_en_before_087', p.name_en, 'quality_note_before_087', p.quality_note,
                 'geo_precision', 'approx-anchor', 'anchored_to_087', v.anchor, 'moved_by_087', true),
       geom = ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326),
       admin1_pcode = 'PS01', admin2_pcode = v.admin2, name_en = v.name_en,
       quality_note = v.note
  FROM (VALUES
    (1759, 884,  35.3002, 31.9545, 'PS0130', 'Taybeh gate (Karmelo), Ramallah',
     'moved 087: 082 had put it south-east of Yatta; its messages place it at Taybeh (Ramallah) on the Mu''arrajat road — anchored to Taybeh'),
    (1499, 5063, 35.1093, 31.5244, 'PS0150', 'Al-Fahs (Hebron)',
     'moved 087: v1 put it near Nablus; its messages list it between Zif and Sa''ir — anchored to Hebron city'),
    (1531, 5108, 35.4608, 31.8559, 'PS0135', 'Al-Banana (Jericho)',
     'moved 087: v1 put it near Nablus; its messages list it with Jericho''s exits and the Mu''arrajat road — anchored to Jericho city')
  ) AS v(place_id, anchor, lon, lat, admin2, name_en, note)
 WHERE p.place_id = v.place_id
   AND NOT (p.attrs ? 'moved_by_087');
