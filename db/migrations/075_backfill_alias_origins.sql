-- 075 — origins for the alias backfill.
--
-- `place_alias.origin` records WHERE a key came from, and the check constraint
-- enumerates the loaders that may write one. The backfill (ops/backfill_aliases.py)
-- introduces three provenances that did not exist when the constraint was written:
--
--   backfill_self  the key came from the place's OWN name_ar / name_en column,
--                  which its loader never turned into an alias
--   backfill_twin  the key was borrowed from a co-located row that carried the
--                  missing language, accepted on name similarity AND distance
--   backfill_city  an existing key was MOVED from a governorate polygon to the
--                  city of the same name (see the function's docstring)
--
-- They are separate values rather than reusing 'manual' because the backfill is
-- inference, not curation: if one of these mappings is later found wrong, the
-- origin is what identifies the whole class for review or rollback.
ALTER TABLE place_alias DROP CONSTRAINT IF EXISTS place_alias_origin_check;
ALTER TABLE place_alias ADD CONSTRAINT place_alias_origin_check
  CHECK (origin = ANY (ARRAY[
    'ocha', 'osm', 'pcbs', 'checkpoint_db', 'observed', 'manual',
    'backfill_self', 'backfill_twin', 'backfill_city'
  ]));
