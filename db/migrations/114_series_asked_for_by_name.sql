-- 114 · a series that is served when it is asked for by name
-- 2026-10-13
--
-- Some datasets are one figure for each of many things: Peace Now's population
-- of each of 141 settlements is 141 series. Held as ordinary series, they take
-- over their category: the newest rows of `settlements` became three single
-- settlements' counts for May 2024, and the West Bank total (511,100 for 2024,
-- the number the category is asked for) left the answer. Measured on the
-- rehearsal copy on 2026-10-13, the day the dataset was built.
--
-- This column is one declared fact about a series: it is one member of such a
-- family, and it is served when it is asked for by name. A registry rule
-- declares it (`ask_by_name: true` in a spec's registry.rules);
-- ops/load_registry.py writes it; serve/app.py reads it in the category route:
-- such a series stays out of a category's rows unless the `indicator` filter
-- names only series of that kind, and the answer says how many are held that
-- way. It is found by its name in /v2/databank/indicators like any other, and
-- series, compare and correlate read it like any other. Nothing else changes.
--
-- Applied alone it changes no answer: every row is false until a rule says so.
-- The column is added with a constant default (no table rewrite); the lock is
-- on indicator_def only, and it gives up after five seconds rather than wait
-- behind a reader.
--
-- Rollback: ALTER TABLE indicator_def DROP COLUMN ask_by_name;
--   (with the code of this commit, a missing column means "no such series".)

SET LOCAL lock_timeout = '5s';

ALTER TABLE indicator_def
  ADD COLUMN IF NOT EXISTS ask_by_name boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN indicator_def.ask_by_name IS
  'true = one member of a family of per-entity series (a settlement, not the West Bank): served when asked for by name, left out of a category''s newest rows. Declared by a registry rule, written by ops/load_registry.py. 114.';
