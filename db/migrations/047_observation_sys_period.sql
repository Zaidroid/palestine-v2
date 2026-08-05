-- 047 — observation learns validity time (T2.4, P2.4)
--
-- `event` has carried sys_period since 004; observation never needed it
-- because tier-1 rollups are append-only daily facts. The migrated databank
-- does need it: v1's upstream corrections DELETE the old record and publish
-- a new one (stable_id is a content hash), so "what did v1 serve on July 3"
-- is answerable only with validity ranges. The snapshot replay
-- (ops/replay_snapshots.py) writes them:
--   live rows      → [first snapshot day seen, ∞)
--   vanished rows  → [first seen, day after last seen)   — supersedence
-- Rows the replay never touches (tier-1 rollup, MoH) default to
-- [ingested_at, ∞), which is the truth for an append-only writer.
--
-- Three-step add: hypertables + volatile defaults do not mix in one ALTER.

ALTER TABLE observation ADD COLUMN IF NOT EXISTS sys_period tstzrange;

UPDATE observation SET sys_period = tstzrange(ingested_at, NULL)
WHERE sys_period IS NULL;

ALTER TABLE observation
    ALTER COLUMN sys_period SET DEFAULT tstzrange(now(), NULL),
    ALTER COLUMN sys_period SET NOT NULL;

-- as_of queries: WHERE sys_period @> %(at)s — served by this index for the
-- migrated population (the only one whose ranges ever close).
CREATE INDEX IF NOT EXISTS observation_sys_period_gist
    ON observation USING gist (sys_period)
    WHERE v1_stable_id IS NOT NULL;
