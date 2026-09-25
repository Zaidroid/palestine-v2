# Steps only Zaid's hands can do (collected while executing the plan)

Nothing below is live until the branch is merged and main-server runs it. In order:

1. **Apply the new migrations** (after reading them): `cd ~/palestine-v2 && db/migrate.sh --status && db/migrate.sh`
   - `079_checkpoint_both_row_is_the_worse_direction.sql` — view only (checkpoint_serving); no data touched.
   - `080_crowd_never_feeds_incidents.sql` — sets `feeds_incidents=false` for `kind='crowd'` sources (rollback in the file).
2. **Restart the API** so serve/ changes load: `sudo systemctl restart palestine-v2-api` (route renderers, F011).
3. **Parser changes (01-parser) reach old rows only after a re-import**: `python -m ingest.sources.checkpoints --full`
   re-reads v1 and rebuilds only this importer's rows. It is a large rebuild; decide when. New rows use the new
   parser at the next 2-minute tick with no action.
4. **Blinded checkpoints do not self-heal (F017)**: a checkpoint whose current belief is a stranger's below-floor
   caution keeps it until the next channel report (the belief upsert refuses an older `observed_at`). No action
   needed unless one is noticed; a fresh channel report fixes it.
5. **Settlement labels on route waypoints (F322)** need data, not code: a `place.attrs->>'settlement'` flag from a
   source such as Peace Now's list or OSM `landuse=residential` + Hebrew-only names. Hebrew-only names are already
   dropped from `passes`.
6. **Ledger**: PLAN §11 marks P0-A.4 (settlement labelling) and P0-B.2/3 as done; the code did not do them until
   these commits (and settlement labelling is still not done). Correct the ledger lines.

## Rollout runbook for the agent on main-server (live test, then live, then history)

Everything on this branch was proven only on a schema-only local database with synthetic rows (rolled back) and
offline fixtures. No real data was read or written. The steps below prove it on the real data before it serves.

**A. Before touching anything**
1. `python -m ops.backup` (or confirm last night's set: `python -m ops.backup --status`).
2. Snapshot what is served now, for the before/after diff:
   `psql -c "\copy (SELECT place_id, direction, flow, observed_at FROM checkpoint_serving) TO '/tmp/cs_before.csv' CSV HEADER"`

**B. Test on the real database without serving it**
3. `git fetch && git checkout claude/system-analysis-complete-mzpu2r` in a SEPARATE worktree, never the tree the timers run.
4. Full suite against the real DB with a dev API on :7871 (CLAUDE.md "Tests on main-server"). Expect the local
   baseline's 99 data/API failures to pass there; anything red is a stop.
5. Apply `079` and `080` with `db/migrate.sh`, then diff the served checkpoints:
   `\copy (SELECT place_id, direction, flow, observed_at FROM checkpoint_serving) TO '/tmp/cs_after.csv' CSV HEADER`.
   Expected: only rows whose 'both' direction had a fresher direction-specific reading change, toward the more
   restrictive value. Read a sample of the changed rows against their raw messages before going on.
6. Crowd-derived incidents that already exist (F012): `SELECT count(*) FROM claim c JOIN source s USING (source_id)
   JOIN claim_classification cc USING (claim_id) WHERE s.kind = 'crowd' AND cc.verdict = 'incident'`. Expect 0
   (PLAN §4 R3: 0 submitters). If not 0, list them before any rebuild.

**C. Go live**
7. Merge, pull into the live tree, `sudo systemctl restart palestine-v2-api`, then ask the canonical questions
   (قلنديا, حوارة, رام الله→نابلس, crossings) through the connector and read the answers.

**D. History (retroactive), only after C holds for a day**
- Beliefs and serving views need nothing: they are recomputed from the stored observations on every refresh.
- **Parser fixes** reach history by re-deriving from the raw text, never by editing rows:
  1. Measure first: re-parse every stored `raw_line` with the new parser (read-only) and count how many
     observations would change value, by old→new value, with samples. Review the closed↔open flips by hand.
  2. Check v1 still holds every row v2 imported (`SELECT count(*) FROM checkpoint_updates` in v1's SQLite ≥ the
     importer's rows in v2) — `--full` rebuilds from v1, so anything v1 has lost would be lost from v2 too.
  3. Stop `palestine-v2-checkpoints.timer`, run `python -m ingest.sources.checkpoints --full`, start the timer.
- **Classifier changes** (none yet that change readings; a future `CLASSIFIER_VERSION` bump) re-read the corpus
  on the next tick — HANDS §8's `TimeoutStartSec=3600` must be in place first, and the audit's F-findings on the
  rebuild (event rows hard-deleted, stable keys overwritten) should be fixed before relying on a rebuild for history.
- **Nightly rollups already frozen into the databank** keep the values served at the time. Re-running
  `ops/rollup.py` for past days after the parser re-import would restate them; decide whether the databank should
  record what was served then or what is believed now, and say which in its attrs.
