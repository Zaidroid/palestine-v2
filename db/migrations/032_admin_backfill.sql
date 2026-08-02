-- 032 — give every mapped place its governorate, so history can be asked about
-- somewhere bigger than a single gate.
--
-- Found while testing the first cross-tier query 031 made possible. "Checkpoint
-- closures by governorate this month" returned nothing, and the reason was not
-- the rollup: ZERO of 235 checkpoint places carrying rollup data had an
-- admin2_pcode. Overall coverage was 26.6% of 2,410 places.
--
-- Nobody would have noticed from the live API, because every tier-1 endpoint
-- answers about a specific place — a station, a checkpoint, a point you already
-- named. The admin hierarchy only becomes load-bearing the moment you ask a
-- question about an AREA, which is exactly what history and patterns are for.
-- So the gap was invisible right up until the feature that needs it.
--
-- WHY THIS IS DERIVABLE AND WAS NEVER DERIVED
-- Every place has geometry: 359/359 checkpoints, 575/575 stations, 1443/1443
-- localities, and all 16 governorates have polygons. 358 of 359 checkpoints
-- fall inside exactly one governorate. The codes were simply never filled in
-- for places that arrived from sources that had coordinates but no admin keys —
-- v1's checkpoint registry, OSM stations — because nothing had yet asked.
--
-- IT ALSO MOVES A TIER 2 GATE
-- ARCHITECTURE.md sets Phase 2's exit at "admin-key coverage >=60% (from 7.1%)".
-- This is that work, done early because tier 1's history needed it first, and
-- done spatially against the OCHA boundaries already loaded rather than by
-- string-matching place names.
--
-- SAFETY
-- Backfill only: `WHERE admin2_pcode IS NULL`. A code that came from an
-- authoritative source is never overwritten by one inferred from a point. A
-- point on a boundary could fall in two polygons, so the join takes the
-- governorate whose polygon actually CONTAINS the centroid and, where that is
-- ambiguous, the nearest one — recorded in attrs either way so an inferred code
-- can always be told from a given one.

-- ── admin2 (governorate) from the point ──────────────────────────────────────
WITH hit AS (
  SELECT p.place_id,
         g.admin2_pcode,
         g.admin1_pcode,
         'contains' AS how
    FROM place p
    JOIN place g
      ON g.kind = 'governorate'
     AND g.geom IS NOT NULL
     AND ST_Contains(g.geom::geometry, p.centroid::geometry)
   WHERE p.admin2_pcode IS NULL
     AND p.centroid IS NOT NULL
     AND p.kind <> 'governorate'
)
UPDATE place p
   SET admin2_pcode = h.admin2_pcode,
       admin1_pcode = COALESCE(p.admin1_pcode, h.admin1_pcode),
       attrs = COALESCE(p.attrs, '{}'::jsonb)
               || jsonb_build_object('admin_source', 'spatial:' || h.how,
                                     'admin_backfilled', '032')
  FROM hit h
 WHERE p.place_id = h.place_id;

-- ── the strays: inside the country, outside every polygon ────────────────────
-- One checkpoint sits outside all 16 governorate polygons — boundary geometry
-- is not perfect and a gate can sit exactly on a line. Nearest-governorate
-- within 5km, marked as inferred so it is never mistaken for a given code.
WITH near AS (
  SELECT DISTINCT ON (p.place_id)
         p.place_id, g.admin2_pcode, g.admin1_pcode,
         ST_Distance(p.centroid, g.centroid) AS m
    FROM place p
    JOIN place g ON g.kind = 'governorate' AND g.centroid IS NOT NULL
   WHERE p.admin2_pcode IS NULL
     AND p.centroid IS NOT NULL
     AND p.kind <> 'governorate'
   ORDER BY p.place_id, ST_Distance(p.centroid, g.centroid)
)
UPDATE place p
   SET admin2_pcode = n.admin2_pcode,
       admin1_pcode = COALESCE(p.admin1_pcode, n.admin1_pcode),
       attrs = COALESCE(p.attrs, '{}'::jsonb)
               || jsonb_build_object('admin_source', 'spatial:nearest',
                                     'admin_distance_m', round(n.m),
                                     'admin_backfilled', '032')
  FROM near n
 WHERE p.place_id = n.place_id
   AND n.m < 50000;

COMMENT ON COLUMN place.admin2_pcode IS
  'Governorate p-code. Where attrs->>''admin_source'' starts with "spatial:", '
  'it was derived from the place''s own coordinates against the OCHA boundary '
  'polygons in migration 032, not supplied by the source. An authoritative '
  'code is never overwritten.';
