-- 077 — one governorate code scheme, taken from the ground.
--
-- The gazetteer carried two admin2 schemes side by side. OCHA's came in with
-- the governorate polygons and the PCBS localities (PS0101 Jenin, PS0105
-- Tubas, PS0110 Tulkarm, PS0115 Nablus, PS0120 Qalqilya, PS0125 Salfit,
-- PS0130 Ramallah, PS0135 Jericho, PS0140 Jerusalem, PS0145 Bethlehem,
-- PS0150 Hebron). v1's known_locations rows kept v1's own sequential scheme
-- (PS0101 Jenin … PS0107 Ramallah … PS0111 Hebron), and the OSM stations
-- inherited whichever code their parent row had. So Ramallah city read PS0107
-- while every village around it read PS0130, and two codes meant different
-- governorates depending on the row (PS0105 = Tubas or Qalqilya, PS0110 =
-- Tulkarm or Bethlehem). No lookup table can translate that; only the
-- governorate polygon a centroid sits in can.
--
-- Measured 2026-09-24: 187 servable rows (86 localities, 101 stations) carried
-- a code different from the polygon containing them. What that cost:
--   * the incident classifier's governorate hint (OCHA scheme, read from the
--     governorate row) never matched a v1 city row, so `_prefer` could not
--     use it there;
--   * the fuller-form village lookup filtered on the code of the CITY row it
--     resolved the governorate name to, and matched nothing — dead since it
--     landed;
--   * /v2/insights rolls incidents up by joining place.admin2_pcode to the
--     governorate row, which silently dropped every city.
--
-- Every row with a centroid inside a governorate polygon takes that polygon's
-- code. Rows outside every polygon (Jerusalem city west of the line, Gaza-edge
-- crossings and settlements, three Tulkarm rows rounded onto the Green Line)
-- keep their code unless it is one of the eight codes that exist ONLY in the
-- v1 scheme, which are translated by table. The previous code is kept in attrs
-- for review or rollback; nothing is deleted.

UPDATE place p
   SET admin2_pcode = g.admin2_pcode,
       admin1_pcode = COALESCE(g.admin1_pcode, p.admin1_pcode),
       attrs = COALESCE(p.attrs, '{}'::jsonb)
               || jsonb_build_object('admin2_before_077', p.admin2_pcode,
                                     'admin_source', 'spatial:077')
  FROM place g
 WHERE g.kind = 'governorate' AND g.servable AND g.geom IS NOT NULL
   AND p.kind NOT IN ('governorate', 'region', 'district_mandate')
   AND p.centroid IS NOT NULL
   AND ST_Within(p.centroid::geometry, g.geom::geometry)
   AND p.admin2_pcode IS DISTINCT FROM g.admin2_pcode;

-- Left over: only rows outside every polygon can still carry a v1-only code.
UPDATE place p
   SET admin2_pcode = t.ocha,
       attrs = COALESCE(p.attrs, '{}'::jsonb)
               || jsonb_build_object('admin2_before_077', p.admin2_pcode,
                                     'admin_source', 'table:077')
  FROM (VALUES ('PS0102', 'PS0105'), ('PS0103', 'PS0110'), ('PS0104', 'PS0115'),
               ('PS0106', 'PS0125'), ('PS0107', 'PS0130'), ('PS0108', 'PS0135'),
               ('PS0109', 'PS0140'), ('PS0111', 'PS0150')) AS t(v1, ocha)
 WHERE p.admin2_pcode = t.v1;

-- A locality promoted from the Palestine Open Maps reference set (see
-- ops/promote_named_localities.py) gets its alias keys from its own name
-- columns; the provenance is the loader, not a backfill, so it gets its own
-- value.
ALTER TABLE place_alias DROP CONSTRAINT IF EXISTS place_alias_origin_check;
ALTER TABLE place_alias ADD CONSTRAINT place_alias_origin_check
  CHECK (origin = ANY (ARRAY[
    'ocha', 'osm', 'pcbs', 'checkpoint_db', 'observed', 'manual',
    'backfill_self', 'backfill_twin', 'backfill_city', 'palopenmaps'
  ]));
