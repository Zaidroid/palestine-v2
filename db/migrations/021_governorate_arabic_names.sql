-- 021 — governorates had no Arabic names, so Arabic lookups against them failed.
--
-- Only 3 of 16 governorate rows carried name_ar, and 018 showed two of those
-- three were wrong. The gap surfaced when the weather endpoint — which is keyed
-- by governorate — could not answer "شو الطقس في اريحا": Jericho's row had a
-- NULL Arabic name to match against.
--
-- Safe to fill in: resolve_place matches through place_alias only (exact,
-- containment and fuzzy all query that table), and place.name_ar is a display
-- label. Populating it therefore cannot shift which place a name resolves to —
-- verified before applying, because doing this blind is exactly how 018's
-- Bethlehem/Tulkarm swap would have been made worse.
--
-- No aliases are added here. "بيت لحم" and "قلقيلية" deliberately continue to
-- resolve to their LOCALITIES, which have tighter centroids and place an
-- incident better than a governorate centroid does.

UPDATE place SET name_ar = v.ar, updated_at = now()
FROM (VALUES
  ('Jenin','جنين'), ('Tubas','طوباس'), ('Tulkarm','طولكرم'),
  ('Nablus','نابلس'), ('Qalqilya','قلقيلية'), ('Salfit','سلفيت'),
  ('Ramallah','رام الله'), ('Jericho','أريحا'), ('Jerusalem','القدس'),
  ('Bethlehem','بيت لحم'), ('Hebron','الخليل'),
  ('Gaza','غزة'), ('North Gaza','شمال غزة'), ('Deir Al-Balah','دير البلح'),
  ('Khan Younis','خان يونس'), ('Rafah','رفح')
) AS v(en, ar)
WHERE place.kind = 'governorate' AND place.name_en = v.en
  AND place.name_ar IS DISTINCT FROM v.ar;
