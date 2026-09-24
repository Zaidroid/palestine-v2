-- 078 — a place that has an Arabic key has an Arabic name.
--
-- 457 servable localities came from v1 with a Latin name only; the alias
-- backfill (075) and the twin promotion (P0-C.1b) gave many of them the Arabic
-- key the channels write — so they RESOLVE — but `name_ar` stayed NULL, and
-- every answer built from it printed the Latin name inside an Arabic sentence
-- ("هدم في Bayt Rima", 2026-09-24). The name is taken from the place's own
-- Arabic keys: curated origins first, then the longest key (the normalised
-- full form, before the article was stripped). Rows that were already named
-- are not touched; the provenance is recorded in attrs.
UPDATE place p
   SET name_ar = a.alias_norm,
       attrs = COALESCE(p.attrs, '{}'::jsonb) || jsonb_build_object('name_ar_from', 'alias:078')
  FROM (
    SELECT DISTINCT ON (pa.place_id) pa.place_id, pa.alias_norm
      FROM place_alias pa
     WHERE pa.alias_norm ~ '[؀-ۿ]'
     ORDER BY pa.place_id,
              CASE pa.origin WHEN 'pcbs' THEN 0 WHEN 'manual' THEN 1 WHEN 'backfill_twin' THEN 2
                             WHEN 'palopenmaps' THEN 3 WHEN 'ocha' THEN 4 WHEN 'checkpoint_db' THEN 5
                             WHEN 'osm' THEN 6 ELSE 7 END,
              length(pa.alias_norm) DESC
  ) a
 WHERE p.place_id = a.place_id AND p.name_ar IS NULL AND p.servable AND p.merged_into IS NULL;

-- A twin promoted through attrs.twin_keys holds its Arabic there, not in place_alias.
UPDATE place p
   SET name_ar = p.attrs->'twin_keys'->>0,
       attrs = p.attrs || jsonb_build_object('name_ar_from', 'twin_keys:078')
 WHERE p.name_ar IS NULL AND p.servable AND p.merged_into IS NULL
   AND jsonb_typeof(p.attrs->'twin_keys') = 'array' AND jsonb_array_length(p.attrs->'twin_keys') > 0;
