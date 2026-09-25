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
