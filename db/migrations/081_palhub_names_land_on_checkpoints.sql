-- 081 — palhub's names land on CHECKPOINT rows, never on towns.
--
-- P1-A.1b (PLAN §7 P1-A.1 "fix the unresolved names"). The palhub bulletin
-- names ~190 points every 15 minutes. 113 resolved to a checkpoint row; 25
-- resolved to nothing; and 54 resolved to the TOWN the point is named after
-- (the loader's fallback is the general resolver, and "بوابة دير دبوان" has no
-- checkpoint row, so it took Dayr Dibwan the village at 0.89). A reading on a
-- town is the 035 bug class: stored, believed, and structurally unable to meet
-- any channel's report of the same gate. Since the earn-out (decision A,
-- 2026-09-25 15:49) those town rows carry ASSERTIONS, so checkpoint_serving
-- began listing 55 towns, roads and a fuel station as checkpoints — 47 of the
-- 177 "known" rows at 17:00 UTC sat on a place that is not a checkpoint.
--
-- What this does, all reversible:
--   1. Declares palhub's exact names on the checkpoint rows they mean
--      (`place.attrs.palhub_names`), for 27 rows that already exist — the
--      same name, or the checkpoint / junction / bridge row at that town's
--      entrance. The loader reads this first (ingest/sources/palhub_roads.py).
--   2. Creates 34 checkpoint rows for the gates and junctions v1's list never
--      had, anchored at the centroid of the town they are named after
--      (`attrs.geo_precision = 'approx-anchor'`, `attrs.anchored_to`), plus
--      checkpoint 300 at Bethlehem from public geography (034 precedent).
--   3. Moves palhub's checkpoint_flow observations of the last two days off
--      the town rows onto the declared rows — all the serving layer can still
--      read; the older (compressed) history stays where it is, keyed by
--      attrs.palhub_name for a later join.
--   4. Drops the beliefs (state_current) that those town rows had built; the
--      next palhub tick rebuilds belief on the checkpoint rows.
--
-- 17 palhub names stay unresolved on purpose (no row and no anchor to place
-- them: نصار, الهيئة, البوابة الصفراء, عين جدي شارع 90, البقّاريّة, العمور,
-- مسافر يطّا, الجمعيّة العربيّة, السدر, المناشير, قبر حلوة, الشعراوية,
-- طريق الغرس, حاجز حداد, حاجز دوار البادية, دوار الطنيب, بوابة المهلل); the
-- loader now counts and names them every tick.
--
-- Rollback (exact):
--   UPDATE state_observation SET place_id = (attrs->>'moved_from')::int,
--          attrs = attrs - 'moved_from' - 'moved_by'
--    WHERE attrs->>'moved_by' = '081';
--   UPDATE state_observation SET modality = 'assertion',
--          attrs = attrs - 'requarantined_by'
--    WHERE attrs->>'requarantined_by' = '081';
--   DELETE FROM state_current WHERE place_id IN
--         (SELECT place_id FROM place WHERE attrs->>'migration' = '081');
--   DELETE FROM place_alias WHERE place_id IN
--         (SELECT place_id FROM place WHERE attrs->>'migration' = '081');
--   DELETE FROM place WHERE attrs->>'migration' = '081';
--   UPDATE place SET attrs = attrs - 'palhub_names' - 'palhub_names_by'
--    WHERE attrs->>'palhub_names_by' = '081';

-- 1. declared names on rows that already exist
UPDATE place p
   SET attrs = COALESCE(p.attrs, '{}'::jsonb)
             || jsonb_build_object('palhub_names', to_jsonb(v.names),
                                   'palhub_names_by', '081')
  FROM (VALUES
    (1704, ARRAY['السموع (سيميا)']::text[]),
    (1703, ARRAY['الظاهرية – مثلث السموع']::text[]),
    (1495, ARRAY['دورا – الرئيسية']::text[]),
    (1665, ARRAY['بيت جالا (DCO)']::text[]),
    (1564, ARRAY['جناتا']::text[]),
    (1644, ARRAY['اشارات شيلو']::text[]),
    (1666, ARRAY['عيلي']::text[]),
    (1645, ARRAY['إشارات أرئيل']::text[]),
    (1472, ARRAY['جسر اودلا']::text[]),
    (1618, ARRAY['عطارة البلد - فوق الجسر']::text[]),
    (1510, ARRAY['بيت ليد الرئيسية']::text[]),
    (1507, ARRAY['إشارات حارس']::text[]),
    (1610, ARRAY['عبارة كفل حارس']::text[]),
    (1634, ARRAY['بوابة جماعين الرئيسية']::text[]),
    (1479, ARRAY['عين شبلي - الحمرا']::text[]),
    (1662, ARRAY['العروب – أبو شمعة']::text[]),
    (1477, ARRAY['زيف']::text[]),
    (1520, ARRAY['بوابة كفر الديك']::text[]),
    (1522, ARRAY['دير استيا']::text[]),
    (1749, ARRAY['حاجز الجيب']::text[]),
    (1805, ARRAY['عناتا - شعفاط']::text[]),
    (1511, ARRAY['مدخل رامین', 'مدخل رامين']::text[]),
    (1762, ARRAY['جسر جيوس - النبي الياس']::text[]),
    (1550, ARRAY['التفافي زواتا']::text[]),
    (1631, ARRAY['بيتا تحت الجسر (الحسبة)']::text[]),
    (1739, ARRAY['اللبن الشرقية']::text[]),
    (1767, ARRAY['شافي شومرون']::text[])
) AS v(place_id, names)
 WHERE p.place_id = v.place_id
   AND p.kind IN ('checkpoint', 'crossing', 'road') AND p.servable AND p.merged_into IS NULL;

-- 2. checkpoint rows that v1's list never had, anchored at the town they name
INSERT INTO place (kind, name_ar, name_en, admin1_pcode, admin2_pcode, oslo_area,
                   geom, confidence, source_refs, attrs, servable)
SELECT 'checkpoint', v.ar, v.en, q.admin1_pcode, q.admin2_pcode, q.oslo_area,
       q.centroid::geometry, 0.8,
       jsonb_build_object('origin', 'palhub bulletin, anchored by hand (081)',
                          'anchor_place_id', v.anchor),
       jsonb_build_object('geo_precision', 'approx-anchor',
                          'anchored_to', v.anchor,
                          'palhub_names', to_jsonb(v.names),
                          'palhub_names_by', '081',
                          'migration', '081'),
       true
  FROM (VALUES
    ('بيت سوريك', 'Bayt Surik checkpoint', 693, ARRAY['بيت سوريك']::text[]),
    ('أم الشقحان', 'Umm ash Shaqhan checkpoint', 1037, ARRAY['أم الشقحان']::text[]),
    ('أبو العسجا', 'Abu al Asja checkpoint', 1075, ARRAY['ابو العسجا']::text[]),
    ('الرماضين – الطور', 'Ar Ramadin – at Tur checkpoint', 420, ARRAY['الرماضين الطَّوَر']::text[]),
    ('العروب – العجوري', 'Al Arrub camp – al Ajjuri entrance', 112, ARRAY['العروب – العجّوري']::text[]),
    ('خلة المية', 'Khallat al Mayyah checkpoint', 522, ARRAY['خلة المية']::text[]),
    ('عبدة', 'Abdah checkpoint', 852, ARRAY['عبدة']::text[]),
    ('واد الشاجنة', 'Wadi ash Shajinah checkpoint', 1030, ARRAY['واد الشاجنة']::text[]),
    ('بوابة دير دبوان', 'Dayr Dibwan gate', 655, ARRAY['بوابة دير دبوان']::text[]),
    ('بوابة دير عمار', 'Dayr Ammar gate', 659, ARRAY['بوابة دير عمار']::text[]),
    ('بوابة شبتين', 'Shabtin gate', 264, ARRAY['بوابة شبتين']::text[]),
    ('بوابة شقبا', 'Shuqba gate', 255, ARRAY['بوابة شقبا']::text[]),
    ('حاجز الطيبة', 'Taybeh checkpoint (Ramallah)', 884, ARRAY['حاجز الطيبة', 'حاجة الطيبة']::text[]),
    ('راس كركر', 'Ras Karkar checkpoint', 286, ARRAY['راس كركر']::text[]),
    ('عين عريك – بيتونيا', 'Ayn Arik – Beitunia', 739, ARRAY['عين عريك - بيتونيا']::text[]),
    ('مخماس', 'Mikhmas checkpoint', 361, ARRAY['مخماس']::text[]),
    ('معبر رنتيس', 'Rantis crossing point', 287, ARRAY['معبر رنتيس']::text[]),
    ('بوابة مردا الشرقية', 'Marda east gate', 388, ARRAY['بوابة مردا الشرقية']::text[]),
    ('بوابة مردا الغربية', 'Marda west gate', 388, ARRAY['بوابة مردا الغربية']::text[]),
    ('السواحرة الشرقية', 'As Sawahirah ash Sharqiyah checkpoint', 1401, ARRAY['السواحرة الشرقية']::text[]),
    ('بوابة بدو', 'Biddu gate', 677, ARRAY['بوابة بدو']::text[]),
    ('بيت إكسا', 'Bayt Iksa checkpoint', 707, ARRAY['بيت اكسا']::text[]),
    ('بيت ليد – اللدائن', 'Bayt Lid – al Ladain', 700, ARRAY['بيت ليد - اللدائن', 'اللدائن']::text[]),
    ('سهل رامين', 'Ramin plain', 290, ARRAY['سهل رامين']::text[]),
    ('كفر اللبد', 'Kafr al Labad checkpoint', 546, ARRAY['كفر اللبد']::text[]),
    ('بوابة أوصرين', 'Awsarin gate', 741, ARRAY['بوابة اوصرين']::text[]),
    ('بوابة جماعين الكسارة', 'Jammain quarry gate', 564, ARRAY['بوابة جماعين الكسارة']::text[]),
    ('بوابة دوما', 'Duma gate', 643, ARRAY['بوابة دوما']::text[]),
    ('مجدل بني فاضل', 'Majdal Bani Fadil checkpoint', 397, ARRAY['مجدل بني فاضل']::text[]),
    ('مفرق الـ17 – عصيرة', 'The 17 junction – Asira', 755, ARRAY['الـ 17 - عصيرة']::text[]),
    ('برطعة', 'Barta''a checkpoint', 722, ARRAY['برطعة']::text[]),
    ('بيت عور', 'Bayt Ur checkpoint', 689, ARRAY['بيت عور']::text[]),
    ('مدخل جنصافوط', 'Jinsafut entrance', 946, ARRAY['مدخل جينصافوط']::text[])
) AS v(ar, en, anchor, names)
  JOIN place q ON q.place_id = v.anchor
 WHERE NOT EXISTS (SELECT 1 FROM place x WHERE x.attrs->>'migration' = '081'
                                          AND x.attrs->'palhub_names' = to_jsonb(v.names));

-- 2b. public geography entered by hand
INSERT INTO place (kind, name_ar, name_en, admin1_pcode, admin2_pcode, oslo_area,
                   geom, confidence, source_refs, attrs, servable)
SELECT 'checkpoint', v.ar, v.en, v.a1, v.a2, v.oslo,
       ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326), 0.85,
       jsonb_build_object('origin', 'public geography, entered by hand (081)'),
       jsonb_build_object('geo_precision', 'approx',
                          'palhub_names', to_jsonb(v.names),
                          'palhub_names_by', '081',
                          'migration', '081'),
       true
  FROM (VALUES
    ('حاجز الـ300', 'Checkpoint 300 (Bethlehem)', 31.7225, 35.202, 'PS01', 'PS0145', 'C', ARRAY['حاجز الـ 300']::text[])
) AS v(ar, en, lat, lon, a1, a2, oslo, names)
 WHERE NOT EXISTS (SELECT 1 FROM place x WHERE x.attrs->>'migration' = '081'
                                          AND x.attrs->'palhub_names' = to_jsonb(v.names));

-- the declared names are also aliases for the general resolver, where the
-- alias is free (a town already owns 'مخماس'; the checkpoint owns 'حاجز مخماس'
-- only if nothing else does — the loader does not depend on this)
INSERT INTO place_alias (alias_norm, place_id, confidence, origin)
SELECT DISTINCT n, p.place_id, 0.9, 'manual'
  FROM place p, jsonb_array_elements_text(p.attrs->'palhub_names') n
 WHERE p.attrs->>'migration' = '081' AND length(n) >= 4
ON CONFLICT (alias_norm) DO NOTHING;

-- 3. move the recent palhub observations off the town rows. Two days is
-- inside the uncompressed chunk window (chunks compress after ~3 days) and
-- longer than anything the serving layer still reads (checkpoint_flow decays
-- to unknown within hours). The limit below is a safety net should a chunk
-- at the edge already be compressed: decompressing it is slow, not wrong.
SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;
UPDATE state_observation o
   SET place_id = t.place_id,
       attrs = COALESCE(o.attrs, '{}'::jsonb)
             || jsonb_build_object('moved_from', o.place_id, 'moved_by', '081')
  FROM (SELECT p.place_id, n AS palhub_name
          FROM place p, jsonb_array_elements_text(p.attrs->'palhub_names') n
         WHERE p.attrs->>'palhub_names_by' = '081') t,
       source s, place old
 WHERE s.source_id = o.source_id AND s.key = 'tg_palhubapproad'
   AND o.state_kind = 'checkpoint_flow'
   AND o.attrs->>'palhub_name' = t.palhub_name
   AND old.place_id = o.place_id AND old.kind NOT IN ('checkpoint', 'crossing', 'road')
   AND o.observed_at >= now() - interval '2 days';

-- 3b. what could not be moved (a name with no row, e.g. نصار on a fuel
-- station) goes back to quarantine so the next belief refresh cannot rebuild
-- a town's "checkpoint" from it. Reversible by attrs.requarantined_by.
UPDATE state_observation o
   SET modality = 'quarantined',
       attrs = COALESCE(o.attrs, '{}'::jsonb) || jsonb_build_object('requarantined_by', '081')
  FROM source s, place p
 WHERE s.source_id = o.source_id AND s.key = 'tg_palhubapproad'
   AND o.state_kind = 'checkpoint_flow' AND o.modality = 'assertion'
   AND p.place_id = o.place_id AND p.kind NOT IN ('checkpoint', 'crossing', 'road')
   AND o.observed_at >= now() - interval '2 days';

-- 4. the beliefs those town rows had built are gone; the next tick rebuilds
DELETE FROM state_current sc
 USING place p
 WHERE p.place_id = sc.place_id AND sc.state_kind = 'checkpoint_flow'
   AND p.kind NOT IN ('checkpoint', 'crossing', 'road');
