# Steps only Zaid's hands can do (collected while executing the plan)

> **Main-server state, 2026-09-25 09:50 UTC (Fable, after verifying the branch on the real database from the
> worktree `~/palestine-v2-audit`):** the branch is **merged into `master` (fast-forward, `f572be8`) and pushed**; the
> checkpoints timer runs the new parser and importer (item 8 checked: 0 duplicate v1 identities); the classifier
> **1.9.0 corpus re-read ran by hand under the advisory lock** (the timer skips while it holds it), so item 9's
> timeout is not needed for this bump — HANDS §8 stays wanted for the next one. The F206 decision: **fixed
> permanently** (`f572be8` — retract, never delete). 079 changed before applying: `unknown` outranks `open` in the
> default row (Zaid's decision). Verification: full suite on the real DB 1045 passed / 17 failed → 13 were
> worktree-missing files, 4 wait for 079/080, 1 real regression fixed (`5d55ed8`).
>
> **2026-09-25 (later):** items 1–3 below DONE by Zaid at 09:54 UTC (079/080 applied, API + poller restarted; verified
> live). Area 04 renderers then landed on master (`81acc75`, 13 more tasks) — all in `serve/`, so **one more
> `sudo systemctl restart palestine-v2-api`** puts them live; nothing else is needed for it.
>
> **Area 06 rest landed on master (`36f75a8`, 13 tasks, 11:25 UTC)** — `serve/` + `resolve/db.py` + `ops/watchdog.py`:
> one more `sudo systemctl restart palestine-v2-api` puts it live. Optional, for the connection pool (REST-15/16):
> `~/palestine-v2/.venv/bin/pip install psycopg-pool` then restart the API; /health `db.pooled` turns true. Then raise
> `max_connections` in `db/tuning.sql` to 40 and run `db/migrate.sh --tuning` (needs the DB container restart it prints).
>
> **Area 07 classifier → 1.10.0 LIVE (`c178d67`, 12:46 UTC):** re-read by hand under the lock (8 min; the timer tick
> skipped on the lock), 34,032 claims at 1.10.0, 5,354 believed events, 48 retracted and kept. Nothing for Zaid's hands
> here. **Round 9** (`learn/incident_precision.py --sample --round 9 --adversarial 50`) is the measurement, after a week
> of 1.10.0 output — the numbers above are projections on tuning sets.
>
> **Area 08 gazetteer landed (`d19a3b2`):** resolve/ is live for the timers; the /v2/geo/resolve change (twins named) needs
> the next `sudo systemctl restart palestine-v2-api` — bundle it with the next serving restart, no urgency.
>
> **Area 11 ops landed (`d34217d`):** scripts are live at their next tick (watchdog now exits 3 on faults — its unit
> and wrapper agree once the unit is installed). **Install the changed units** (one block):
> ```
> cd ~/palestine-v2 && sudo cp ops/systemd/palestine-v2-{mcp-audit,watchdog,valhalla-ip}.service /etc/systemd/system/ \
>   && sudo mkdir -p /etc/systemd/system/palestine-v2-valhalla-ip.service.d \
>   && sudo cp ops/systemd/palestine-v2-valhalla-ip.service.d/onfailure.conf /etc/systemd/system/palestine-v2-valhalla-ip.service.d/ \
>   && sudo systemctl daemon-reload
> ```
> Until then a watchdog run that finds faults exits 3 and systemd will fire ONE OnFailure alarm per run (the wrapper
> already records it correctly). **OPS-01 (F063)** stays yours: the unattended maintainer runs with
> `--dangerously-skip-permissions` and a `sudo -n /usr/bin/systemd-run` rule; the fix is a dedicated user with a
> read-mostly DB role, an explicit `--allowedTools` list, and a static `palestine-v2-maintain-retry@.timer` instead of
> the sudo rule — decide whether the weekly maintainer is worth that, or retire it.
>
> **Area 09 ingest landed (`95a4b6f`):** the poller changes (session lock, no media, DB-first, exit 2) are in the tree and
> reach the running poller at its next restart: `sudo systemctl restart palestine-v2-poller` (bundle with the API
> restart). The classifier's forwarded-message unit applies to new claims at the next tick. **Two decisions:**
> INGEST-05 — key channels by numeric Telegram id (a rename today silently darkens a channel; the fix is a migration
> adding the id to `source` and cursors keyed on it — say go and I write it); INGEST-07 — track edits/deletions,
> which costs extra get_messages calls per cycle on the scarce account (say how many per cycle you accept, or no).
>
> **Areas 13 learning + 15 webapp landed (`908d08d`):** the web pages (`serve/webapp/`) and the audit path are served by the
> API — they go live with the next `restart palestine-v2-api`; the learning jobs run the tree at their next tick.
>
> **Still Zaid's hands, in this order** (the auto-mode classifier refused them for the agent):
> 1. `cd ~/palestine-v2 && db/migrate.sh --status && db/migrate.sh` — applies 079 + 080 (both re-runnable; rollback
>    notes inside each file). The running API serves the new `checkpoint_serving` at once (column appended, order kept).
> 2. `sudo systemctl restart palestine-v2-api` — the serving fixes (renderers, route, transport, REST). Item 7 below.
> 3. `sudo systemctl restart palestine-v2-poller` — the FloodWait/atomic-cursor poller.
> 4. HANDS-2026-09-24 §8 — `TimeoutStartSec=3600` drop-in for `palestine-v2-news.service` (for the NEXT version bump).
> After 1–2: `PALESTINE_API=http://127.0.0.1:7871 .venv/bin/python -m pytest -q tests/test_belief_serving.py` should
> read 8 passed, and جبع / عناب / قلنديا / رام الله→نابلس through the connector should read as HANDS-NEEDED describes.


Nothing below is live until the branch is merged and main-server runs it. `STATUS.md` says which plan tasks are done
and by which commit. What each commit needs on main-server, in the order to do it:

| # | what | which commits | how it goes live | before it goes live |
|---:|---|---|---|---|
| 1 | migrations `079`, `080` | `932004f` | `db/migrate.sh --status && db/migrate.sh` | read both files; runbook B5–B6 |
| 2 | API code (`serve/`) | `d952350` `932004f` `c530211` `1d5115c` `a348ccf` `f650da8` | `sudo systemctl restart palestine-v2-api` | runbook B4; item 7 below (OAuth behaviour) |
| 3 | checkpoint parser + v1 import cursor (`cascade/checkpoint_text.py`, `ingest/sources/checkpoints.py`) | `74d914b` `f5fd58d` | automatic: `palestine-v2-checkpoints.timer` runs the working tree | item 8 below (first tick after the pull) |
| 4 | belief SQL (`resolve/belief.py`) | `932004f` | automatic: next belief refresh | runbook B5 |
| 5 | **classifier 1.9.0** (`cascade/news.py`, `ingest/sources/news_incidents.py`) | `be66fb2` `646746c` | automatic: `palestine-v2-news.timer` runs the working tree — **the pull itself starts a whole-corpus re-read** | item 9 below — do NOT pull into the live tree before it |
| 6 | Telegram poller (`ingest/telegram_poller.py`) | `3d77f79` | `sudo systemctl restart palestine-v2-poller` (a long-running process) | one restart = one reconnect + one resolve of every channel, 1.5 s apart — the same cost as any restart |

7. **OAuth behaviour changes with item 2** (`a348ccf`): an OAuth token now spends its partner key's daily quota (it
   spent none — the shared public-test key's quota now counts connector traffic too), and dies when its key is removed
   from `.keys/partner-keys.json` (it lived 30 days). Refresh tokens rotate on use and are bound to their client; PKCE
   is required. Claude's connector already sends PKCE and handles rotation. A connector whose token was issued under a
   key that no longer exists gets a 401 and re-authorises. `.keys/oauth-state.json` is rewritten 0600 on the next issue.
   A JSON-RPC batch over 8 messages or a body over 256 KB is refused.
8. **v1 import cursor, first tick after the pull** (`f5fd58d`): the importer re-reads the last 12 h of v1 and must
   recognise every row it already has. Before the pull, and again after the first tick, run
   `SELECT count(*) FROM state_observation WHERE state_kind='checkpoint_status' AND attrs ? 'canonical_key' AND observed_at > now() - interval '13 hours'`
   — the second count may exceed the first only by rows v1 wrote in between. The tick's stats print `already_imported`;
   it should be about the number of v1 rows in those 12 h. If rows were duplicated, stop the checkpoints timer and
   report; the duplicates carry the same attrs and are identifiable.
9. **Classifier 1.9.0 needs three things before the live tree gets it** (`be66fb2`, `646746c`):
   - HANDS §8 in place: `TimeoutStartSec=3600` on `palestine-v2-news.service` (the re-read is the whole corpus).
   - A decision on F206: the version-bump sweeps in `news_incidents.py` (after the classification upsert) DELETE
     superseded events, as every earlier bump did. The audit rates that a hard-rule-2 violation (no history, no as-of
     replay). Either accept it for this bump, or fix F206 first (07-classifier.md, CLASSIFIER-16).
   - F205 is fixed: the re-read no longer inserts a second copy of every closure observation.
   Project it first, read-only, from the separate worktree: `python ops/project_classifier.py` re-reads every stored
   claim with 1.9.0 in a READ ONLY session and prints each verdict change with sample claim ids (never run
   `ingest.sources.news_incidents` from the worktree — it writes verdicts and runs the sweeps, which is going live).
   Expected: `closure -> rejected:reopening` and nothing else of size; read every reopening sample (each was served
   as a closure). 1.9.0 is unmeasured until a fresh round is drawn (`learn/incident_precision.py --sample --round 9`).
10. **Parser changes reach old rows only after a re-import**: `python -m ingest.sources.checkpoints --full` re-reads
    v1 and rebuilds only this importer's rows. A large rebuild; runbook D says how to measure it first.
11. **Blinded checkpoints do not self-heal (F017)**: a checkpoint whose current belief is a stranger's below-floor
    caution keeps it until the next channel report (the belief upsert refuses an older `observed_at`). A fresh channel
    report fixes it; nothing to do unless one is noticed.
12. **Settlement labels on route waypoints (F322)** need data, not code: a `place.attrs->>'settlement'` flag from a
    source such as Peace Now's list or OSM `landuse=residential` + Hebrew-only names. Hebrew-only names are already
    dropped from `passes`.
13. **Ledger**: the corrections to PLAN §11's "done" claims are in the 2026-09-25 entry at the end of §11 (append-only).

## Rollout runbook for the agent on main-server (live test, then live, then history)

Everything on this branch was proven only on a schema-only local database with synthetic rows (rolled back) and
offline fixtures. No real data was read or written. The steps below prove it on the real data before it serves.

**A. Before touching anything**
1. `python -m ops.backup` (or confirm last night's set: `python -m ops.backup --status`).
2. Snapshot what is served now, for the before/after diff. psql runs inside the container, as `db/migrate.sh` does
   (PGUSER/PGPASSWORD from `.env`, never printed):
   ```
   PSQL="docker exec -i -e PGPASSWORD=$PGPASSWORD palestine-v2-db psql -q -v ON_ERROR_STOP=1 -U $PGUSER -d palestine_v2"
   echo "\copy (SELECT place_id, direction, flow, observed_at FROM checkpoint_serving ORDER BY 1,2) TO STDOUT CSV HEADER" \
     | $PSQL > /tmp/cs_before.csv
   ```

**B. Test on the real database without serving it**
3. `git fetch && git checkout claude/system-analysis-complete-mzpu2r` in a SEPARATE worktree, never the tree the timers run.
4. Full suite against the real DB with a dev API on :7871 (CLAUDE.md "Tests on main-server"). Expect the local
   baseline's 99 data/API failures to pass there; anything red is a stop.
5. Dry-run `079` and the new belief SQL INSIDE A TRANSACTION THAT IS ROLLED BACK — applying them for real changes
   what the production API serves at once (it reads `checkpoint_serving`). From the separate worktree, with psql
   reaching the real DB the way `db/migrate.sh` does (through the container):
   ```
   { echo "BEGIN;"; cat db/migrations/079_checkpoint_both_row_is_the_worse_direction.sql
     echo "\copy (SELECT place_id, direction, flow, observed_at FROM checkpoint_serving ORDER BY 1,2) TO STDOUT CSV HEADER"
     echo "ROLLBACK;"; } | $PSQL > /tmp/cs_after.csv
   ```
   The view is locked for the seconds this takes. Diff `/tmp/cs_before.csv` against `/tmp/cs_after.csv`. Expected:
   only rows whose 'both' direction had a fresher direction-specific reading change, toward the more restrictive
   value. Read a sample of the changed rows against their raw messages before going on. The belief change (F017) is
   the same shape: run `resolve.belief.REFRESH_SQL` inside `BEGIN … ROLLBACK` from the worktree's Python, compare
   `state_current` for `checkpoint_flow`/`checkpoint_status` before the rollback. `080` is a one-line UPDATE of
   `source.feeds_incidents`; read it and apply it with the rest in C.
6. Crowd-derived incidents that already exist (F012): `SELECT count(*) FROM claim c JOIN source s USING (source_id)
   JOIN claim_classification cc USING (claim_id) WHERE s.kind = 'crowd' AND cc.verdict = 'incident'`. Expect 0
   (PLAN §4 R3: 0 submitters). If not 0, list them before any rebuild.

**C. Go live**
7. Only with item 9's prerequisites in place (HANDS §8 timeout, the F206 decision): `db/migrate.sh` (079, 080),
   merge, pull into the live tree (the checkpoints and news timers pick up their code at the next tick — item 8 and
   item 9 say what to watch), `sudo systemctl restart palestine-v2-api`, `sudo systemctl restart palestine-v2-poller`,
   then ask the canonical questions (قلنديا, حوارة, رام الله→نابلس, crossings) through the connector and read the
   answers.

**D. History (retroactive), only after C holds for a day**
- Beliefs and serving views need nothing: they are recomputed from the stored observations on every refresh.
- **Parser fixes** reach history by re-deriving from the raw text, never by editing rows:
  1. Measure first: re-parse every stored `raw_line` with the new parser (read-only) and count how many
     observations would change value, by old→new value, with samples. Review the closed↔open flips by hand.
  2. Check v1 still holds every row v2 imported (`SELECT count(*) FROM checkpoint_updates` in v1's SQLite ≥ the
     importer's rows in v2) — `--full` rebuilds from v1, so anything v1 has lost would be lost from v2 too.
  3. Stop `palestine-v2-checkpoints.timer`, run `python -m ingest.sources.checkpoints --full`, start the timer.
- **Classifier 1.9.0** re-reads the whole corpus on the first tick after the pull (item 9 above): that IS the
  retroactive pass for incidents — every stored claim is re-read from its immutable text. Reopenings the old
  classifier served as closures become `reopening` rejections. Before it: HANDS §8, and the F206 decision (the sweep
  deletes superseded events); F477 (stable keys overwritten on join) means event ids are not guaranteed stable
  across the re-read.
- **Nightly rollups already frozen into the databank** keep the values served at the time. Re-running
  `ops/rollup.py` for past days after the parser re-import would restate them; decide whether the databank should
  record what was served then or what is believed now, and say which in its attrs.
