-- 062 — a spatial axis for 1922-1947, and containment that can be queried
--
-- TWO PROBLEMS, one table.
--
-- (1) ROLLUP IS IMPOSSIBLE. /correlate refuses a governorate series against a
-- national one, correctly, because they measure different things — but the
-- only reason it cannot instead AGGREGATE the finer one is that nothing in
-- the schema says which locality sits in which governorate. The geometry
-- knows; no query can ask.
--
-- (2) THE MANDATE ERA HAS NO GEOGRAPHY. Measured 2026-08-08: of 4,027
-- localities, 2,584 are the servable=false Mandate-era gazetteer and 1,954
-- carry no admin code, because most of them are inside 1948 Israel where
-- modern Palestinian governorates do not reach. So 4,351 historical
-- observations before 1948 — censuses, depopulations, the whole
-- pre-Nakba record — can be mapped as dots and aggregated by nothing.
--
-- The fix is the administrative geography those records were actually
-- collected under: Mandate Palestine's 1945 districts and sub-districts,
-- which Palestine Open Maps already carries on every locality
-- (attrs.district_1945 / attrs.subdistrict_1945).
--
-- SIX districts and SIXTEEN sub-districts, per the 1945 Village Statistics.
-- The source disagrees with itself on three localities — two file 'Jenin' as
-- a district and one files 'Nablus', when both are sub-districts of Samaria
-- — so the district comes from THIS table, not from the record. That is a
-- crosswalk, and like every crosswalk here it is keyed on the name the
-- source writes rather than on an id, so a rebuild cannot silently repoint
-- it.

-- place.kind is an ENUM, so the new kind is a schema change rather than a
-- string. Separate statement and separate transaction on purpose: Postgres
-- refuses to USE an enum value added in the same transaction that added it.
ALTER TYPE place_kind ADD VALUE IF NOT EXISTS 'district_mandate';

CREATE TABLE IF NOT EXISTS place_closure (
    ancestor_id    integer NOT NULL REFERENCES place(place_id),
    descendant_id  integer NOT NULL REFERENCES place(place_id),
    depth          smallint NOT NULL,
    relation       text NOT NULL,
    established_by text NOT NULL,
    PRIMARY KEY (ancestor_id, descendant_id),
    CONSTRAINT closure_no_self CHECK (ancestor_id <> descendant_id OR depth = 0),
    CONSTRAINT closure_relation CHECK (relation IN ('modern', 'mandate'))
);

COMMENT ON TABLE place_closure IS
  'Materialised containment. `relation` separates the modern Palestinian '
  'hierarchy from the Mandate-era one — they are different administrative '
  'geographies over overlapping ground and MUST NOT be mixed in one rollup.';
COMMENT ON COLUMN place_closure.established_by IS
  'How this edge was proven: pcode | st_contains | mandate_gazetteer. A row '
  'whose containment came from a polygon test is a different kind of claim '
  'from one that came from an authority-issued code, and a reader deserves '
  'to know which.';

CREATE INDEX IF NOT EXISTS place_closure_desc
    ON place_closure (descendant_id, relation);

-- ── the sixteen Mandate sub-districts ───────────────────────────────────────
-- servable=false, exactly like the localities beneath them: these are
-- reference geography for the historical record, and resolve/geo.py's live
-- capture path filters `AND servable` so a checkpoint report naming Safad
-- today still resolves as it did yesterday.
-- GEOMETRY IS DERIVED AND SAYS SO. place.geom is NOT NULL and no open source
-- carries the 1945 sub-district boundaries, so each one gets the CENTROID of
-- the localities the gazetteer places inside it. A centroid rather than a
-- convex hull deliberately: a hull would render as a boundary and be read as
-- one, and inventing a Mandate border is precisely the kind of confident
-- fabrication this databank exists not to do. attrs.geom_basis says what it
-- is on every row.
INSERT INTO place (kind, name_en, name_ar, servable, confidence, geom,
                   source_refs, attrs)
SELECT 'district_mandate', v.sub, v.sub_ar, false, 0.9,
       (SELECT ST_SetSRID(ST_Centroid(ST_Collect(l.geom::geometry)), 4326)
        FROM place l
        WHERE l.attrs->>'subdistrict_1945' = v.sub
          AND l.geom IS NOT NULL AND l.merged_into IS NULL
          AND ST_GeometryType(l.geom::geometry) = 'ST_Point'),
       jsonb_build_object('source', 'mandate-1945-village-statistics'),
       jsonb_build_object('historic', 'mandate-palestine',
                          'district_1945', v.district,
                          'subdistrict_1945', v.sub,
                          'geom_basis',
                          'centroid of the gazetteer localities in this '
                          'sub-district. NOT the 1945 administrative '
                          'boundary — no open source carries those — and it '
                          'must never be drawn as one.')
FROM (VALUES
    ('Galilee',   'Acre',       'عكا'),
    ('Galilee',   'Beisan',     'بيسان'),
    ('Galilee',   'Nazareth',   'الناصرة'),
    ('Galilee',   'Safad',      'صفد'),
    ('Galilee',   'Tiberias',   'طبريا'),
    ('Haifa',     'Haifa',      'حيفا'),
    ('Samaria',   'Jenin',      'جنين'),
    ('Samaria',   'Nablus',     'نابلس'),
    ('Samaria',   'Tulkarem',   'طولكرم'),
    ('Jerusalem', 'Hebron',     'الخليل'),
    ('Jerusalem', 'Jerusalem',  'القدس'),
    ('Jerusalem', 'Ramallah',   'رام الله'),
    ('Jerusalem', 'Bethlehem',  'بيت لحم'),
    ('Lydda',     'Jaffa',      'يافا'),
    ('Lydda',     'Ramle',      'الرملة'),
    ('Gaza',      'Gaza',       'غزة'),
    ('Gaza',      'Beersheba',  'بئر السبع')
) AS v(district, sub, sub_ar)
WHERE NOT EXISTS (
    SELECT 1 FROM place p
    WHERE p.kind = 'district_mandate' AND p.name_en = v.sub)
  -- Only sub-districts the gazetteer actually populates. BETHLEHEM is the
  -- one that fails this: it was a real 1945 sub-district and Palestine Open
  -- Maps files its localities under Jerusalem, so we hold zero. Creating an
  -- empty container would assert a geography we cannot fill and would give
  -- every "which sub-districts exist?" query a wrong answer; leaving it out
  -- and saying why here is the honest version. The full 1945 list stays
  -- above so a future source can populate it without rediscovering it.
  AND EXISTS (SELECT 1 FROM place l
              WHERE l.attrs->>'subdistrict_1945' = v.sub
                AND l.geom IS NOT NULL AND l.merged_into IS NULL);

COMMENT ON COLUMN place.kind IS
  'region | governorate | locality | station | checkpoint | crossing | road '
  '| district_mandate (062: the 1945 administrative geography, the only one '
  'the pre-1948 record was collected under).';
