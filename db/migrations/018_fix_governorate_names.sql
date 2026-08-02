-- 018 — two governorates carry the wrong Arabic name, and it misplaces events.
--
-- The OCHA governorate load attached Arabic names to the wrong rows:
--
--   place_id 4  name_en Tubas    (PS0105, 32.304/35.464)  name_ar قلقيلية
--   place_id 5  name_en Tulkarm  (PS0110, 32.313/35.083)  name_ar بيت لحم
--
-- pcode, geometry and English name all agree with each other, so the English
-- names are right and only the Arabic ones are wrong — they hold Qalqilya's and
-- Bethlehem's names. The matching aliases were written from the same bad rows.
--
-- The effect is not cosmetic. `resolve_place('بيت لحم')` returned the TULKARM
-- governorate, ~70 km north of Bethlehem, and `قلقيلية` returned TUBAS, on the
-- opposite side of the West Bank. Fifteen incidents were filed against those
-- two rows — someone asking what had happened near Bethlehem would have been
-- told about Tulkarm.
--
-- The aliases are repointed at the LOCALITIES that own those names (Bethlehem
-- #26, Qalqilya #27) rather than at the corrected governorates. That matches
-- how every other name already behaves — "نابلس" resolves to Nablus city, not
-- Nablus governorate — and a city centroid places an incident far better than
-- a governorate centroid does.

UPDATE place SET name_ar = 'طوباس',  updated_at = now()
 WHERE place_id = 4 AND name_en = 'Tubas'   AND name_ar = 'قلقيلية';
UPDATE place SET name_ar = 'طولكرم', updated_at = now()
 WHERE place_id = 5 AND name_en = 'Tulkarm' AND name_ar = 'بيت لحم';

-- Repoint the two misassigned aliases onto the localities that own the names.
UPDATE place_alias SET place_id = 26
 WHERE alias_norm = 'بيت لحم' AND place_id = 5;
UPDATE place_alias SET place_id = 27
 WHERE alias_norm = 'قلقيليه' AND place_id = 4;

-- And index the corrected governorate names, so the Arabic still reaches them.
INSERT INTO place_alias (alias_norm, place_id, origin, confidence) VALUES
  ('طوباس',  4, 'ocha', 0.9),
  ('طولكرم', 5, 'ocha', 0.9)
ON CONFLICT (alias_norm) DO NOTHING;

-- Events sitting on the two bad rows are re-resolved by re-running the news
-- cascade (`--rebuild`); nothing here deletes them.
