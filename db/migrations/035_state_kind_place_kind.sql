-- 035 — which kind of PLACE a field's data lives on, declared once.
--
-- This is the third appearance of the same bug, so it stops being a bug and
-- becomes a missing column.
--
--   1. Crowd checkpoint reports resolved "الظاهرية" to the TOWN while every
--      channel report sits on the CHECKPOINT — accepted, stored, and
--      structurally incapable of corroborating anything (P2).
--   2. The MCP history tools did the same with "حوارة", so place_history and
--      place_pattern returned empty while looking healthy (P5.3).
--   3. Crowd crossing reports resolved "معبر رفح" to Rafah the CITY rather
--      than Rafah the crossing (P7.2, today).
--
-- Each time the fix was to add a line to PREFER_PLACE_KIND, a dict in Python
-- that nothing forced anyone to update. A new state kind could always be added
-- without it, and the failure is silent every single time: the report is
-- accepted, the place exists, the name matches, and the row lands where no
-- other source will ever meet it.
--
-- So the mapping moves next to the other per-kind configuration, where adding a
-- kind means answering the question. `crowd_reportable` already lives here;
-- "and where does it live" belongs beside it.
--
-- NULL means locality-level and is a real answer, not an omission: power,
-- water, internet and weather genuinely describe a town rather than a point
-- inside it. Gate G2.11 asserts that every CROWD-REPORTABLE kind has been
-- considered, because those are the ones a stranger can file against.

ALTER TABLE state_kind_config
  ADD COLUMN IF NOT EXISTS place_kind text;

COMMENT ON COLUMN state_kind_config.place_kind IS
  'The kind of place this field''s observations attach to, so a name can be '
  'resolved to the row where the data actually lives. NULL = locality-level, '
  'which is a decision rather than a gap. Read by '
  'resolve.geo.resolve_for_state_kind; three separate silent failures came from '
  'this being a hand-maintained dict in Python instead.';

UPDATE state_kind_config SET place_kind = 'checkpoint'
 WHERE state_kind LIKE 'checkpoint%';

UPDATE state_kind_config SET place_kind = 'station'
 WHERE state_kind IN ('fuel_diesel', 'fuel_gasoline', 'cooking_gas');

UPDATE state_kind_config SET place_kind = 'crossing'
 WHERE state_kind = 'crossing_status';

-- power, water, internet, weather, road_closure stay NULL: they describe a
-- locality, and the general resolver is right for them.
