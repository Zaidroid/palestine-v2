-- 013 — a place name has to be a place name.
--
-- 90 of the 374 imported checkpoint places are not distinct places. They fall
-- into two kinds, both visible as clusters sharing one identical centroid:
--
--   SPELLING VARIANTS — one gate stored eight times:
--     الطيبة كارميلو ¦ كرميلو الطيبه ¦ كراملو الطيبة ¦ كراميلو الطيبه ¦
--     بوابة الطيبه ¦ بوابات الطيبة ¦ …
--
--   SENTENCE FRAGMENTS — whole clauses captured as names by v1's matcher:
--     "الجيش نزل ع صره"      the army went down to Sarra
--     "انسحب الجيش عن صرة"    the army withdrew from Sarra
--     "الشرطة العيزرية راحت"  the Eizariya police left
--     "عطارة شالو الحاجز بس"  Atara, they removed the checkpoint but…
--     "سيارتين عمدخل العيزرية" two cars at the Eizariya entrance
--
-- The صرة cluster alone holds 17 of these against 4,918 observations.
--
-- Three costs. Evidence splits across fragments, so corroboration undercounts
-- and each fragment decays on a fraction of the real reporting rate. A
-- nearest-checkpoint query returns the same place several times, crowding out
-- genuine neighbours. And a voice assistant reads "الجيش نزل ع صره" aloud as
-- the name of a checkpoint, which is not a thing anyone can act on.
--
-- Fragments are NOT deleted — that would lose the spelling, which is exactly
-- what future text will contain. Each keeps its row, gains a merged_into
-- pointer, and is registered in place_alias so the string still resolves; it
-- simply stops being a servable answer. The merge itself is in
-- resolve/place_merge.py; this migration owns the schema it writes to.

ALTER TABLE place
  -- Set on a fragment; points at the place that should be served instead.
  ADD COLUMN merged_into BIGINT REFERENCES place(place_id),
  -- False for fragments and for names that are not names. Serving filters on
  -- this; resolution deliberately does not, so the strings still match.
  ADD COLUMN servable BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN quality_note TEXT;

CREATE INDEX place_merged_into_idx ON place (merged_into) WHERE merged_into IS NOT NULL;
CREATE INDEX place_servable_idx    ON place (kind) WHERE servable;

-- A place cannot be merged into itself, and a fragment is never servable.
ALTER TABLE place
  ADD CONSTRAINT place_merge_not_self CHECK (merged_into IS NULL OR merged_into <> place_id),
  ADD CONSTRAINT place_merged_not_servable CHECK (merged_into IS NULL OR NOT servable);

COMMENT ON COLUMN place.merged_into IS
  'Fragment/variant pointer to the canonical place. Observations are re-pointed at the canonical; the row is kept so its spelling still resolves.';
COMMENT ON COLUMN place.servable IS
  'Whether this row may be returned as an answer. Resolution ignores it deliberately — a bad name is still a real string people type.';

-- Resolve a place to whatever should actually be served for it.
CREATE OR REPLACE FUNCTION canonical_place(p BIGINT) RETURNS BIGINT
LANGUAGE sql STABLE AS $fn$
  SELECT COALESCE(merged_into, place_id) FROM place WHERE place_id = p
$fn$;
