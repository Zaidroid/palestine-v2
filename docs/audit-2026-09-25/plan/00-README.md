# Fix plan for the 2026-09-25 audit — read this first

> **Handover state (2026-09-25 08:55 UTC).** 57 of the 160 confirmed tasks are done and 3 partial, on this branch,
> in 11 commits. **`STATUS.md` lists every task as done / partial / open with its commit — read it before starting an
> area and do not redo a done task.** Areas 01 parser, 02 belief and 03 route are finished; 04–07 and 09 are part
> done. **`HANDS-NEEDED.md`** is the go-live order for main-server (migrations 079/080, restarts, classifier 1.9.0's
> prerequisites, the rollout runbook). Suite on the local DB now: **927 passed / 99 failed** — regenerate your own
> `/tmp/baseline.txt` (§2) at the start of a session; the 99 are the production-data / live-API tests.
> Next migration numbers: **081–083** belief, 085–087 databank, 090–091 gazetteer, **092+** anything else.
> Recommended next: finish 04 renderers and 06 rest (answers and counts that state less or more than they know),
> then 07 classifier (F206 before any further version bump), 08 gazetteer, 11 ops.

This folder turns the audit's findings into tasks one executor can do in order, one area at a time. It is written for
a smaller model working alone (no sub-agents, no parallel fan-out). Each area file is self-contained: scope, the files
you may edit, the tests to run, and every task with the file, line, defect, fix and evidence.

- `../REPORT.md` — the audit's verdict, architecture, accuracy and safety-logic sections (context; read once).
- `../confirmed-findings.json` — every confirmed finding in full, with the verifier's reasoning.
- `../lead-session-probes.md` — inputs the lead session ran through the code, with outputs.
- `01-…15-*.md` — the tasks, one file per area, in execution order.

## 1 · How to work (the cost rules come first)

1. **One area file per session.** Open `NN-area.md`, do its section A in order, then section B, then stop and commit.
   Do not read other area files unless a task says to. Do not start sub-agents or workflows.
2. **Read only what a task needs.** Each task names a file and line; read ±60 lines around it with `sed -n`, and the
   functions it calls. Do not read whole large files (`serve/app.py` is 2,800 lines) unless the task needs it.
3. **Run the area's tests, not the whole suite, after each task.** Run the full suite once at the end of the file.
4. **Stop when blocked.** If a task needs production data, a restart, v1 or a decision, write it in `HANDS-NEEDED.md`
   (create it in this folder) and move on. Do not guess.

## 2 · Setup (once per machine, ~3 minutes)

```bash
git fetch origin claude/system-analysis-complete-mzpu2r && git checkout claude/system-analysis-complete-mzpu2r
bash docs/audit-2026-09-25/plan/local-test-db.sh install    # Postgres 16 + PostGIS + TimescaleDB + python deps
bash docs/audit-2026-09-25/plan/local-test-db.sh start
bash docs/audit-2026-09-25/plan/local-test-db.sh migrate    # 001–078 (+ any new ones you add)
source docs/audit-2026-09-25/plan/local-test-db.sh env      # every shell that runs tests needs this
python3 -m pytest -q -p no:cacheprovider tests --deselect tests/test_evidence.py::test_vault_verifies_end_to_end
```

**Baseline with the local database: 821 passed, 99 failed.** The 99 need production data or a running API; they are
not yours to fix. Without the database: 701 passed, 163 failed, 58 errors. Save the baseline list before you start:

```bash
python3 -m pytest -q -p no:cacheprovider tests --deselect tests/test_evidence.py::test_vault_verifies_end_to_end -rA \
  | grep -E '^(PASSED|FAILED|ERROR)' | awk '{print $1, $2}' | sort > /tmp/baseline.txt
```

After your work, a test that was PASSED in `/tmp/baseline.txt` must still pass. Compare with `comm`.

On main-server the same tests run with the real database. See CLAUDE.md "Tests on main-server".

## 3 · Rules that are never bent (from docs/HANDOFF.md §1 and CLAUDE.md)

- `/opt/stacks/palestine` (v1) is live production. Never write to it, never run anything there.
- **No data loss.** Nothing is deleted or overwritten. A correction supersedes and keeps the old value in `attrs`.
  Never UPDATE/DELETE `claim`, `state_observation` or `observation` rows in a migration.
- `claim` is immutable. Our reading of a claim lives in `claim_classification`.
- The API reads `state_serving` / `checkpoint_serving`, never `state_current`.
- The Telegram account is the scarcest asset: never add a join, a subscription, or a second client on the session file.
- Secrets live in `.env`. Never print, commit or log them.
- **Never edit an applied migration (001–078).** A change to a view is a NEW migration. Number ranges reserved by
  area: 079–083 belief (02), 085–087 databank (12), 090–091 gazetteer (08); anything else takes the next free
  number ≥ 092. A migration must be re-runnable (`CREATE OR REPLACE`, `IF NOT EXISTS`), keep a view's column order
  (append new columns at the end), and carry a rollback comment. Apply it to the LOCAL database only.
- Do not weaken, delete or skip a test to get green. If an existing test asserts the wrong behaviour, change that
  assertion and say so in the commit message.

## 4 · The loop, for every task

1. **Reproduce.** Write a test named after the task (e.g. `test_parser_01_relative_ma_is_not_a_negator`) that fails on
   the current code for the reason the task gives. Arabic findings: use the exact input strings from the task.
   Section B tasks: if you cannot make it fail, do not touch the code — add a line to `SKIPPED.md` and move on.
2. **Fix** minimally, in the file's own style: this codebase explains each decision in a short comment naming the
   failure that caused it. Keep that habit.
3. **Check:** the new test passes, the area tests pass, nothing that was passing now fails.
4. **Commit** one task (or one root cause) per commit:
   ```
   fix(<area>): <what changed> (<TASK-ID>, <F-id>)

   <one paragraph: the defect, the input that showed it, the fix>

   Co-Authored-By: <your model name> <noreply@anthropic.com>
   ```
5. **Ledger:** append one line to `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md` §11 per area when the file is done:
   `YYYY-MM-DD HH:MM UTC · audit NN-area · done|partial · proof: <test names> → <N passed>; skipped: <ids>`.

**Several findings share a root cause** because two independent readers reported them (for example PARSER-01/F001 and
PARSER-02/F005 are the same relative-ما defect). Fix it once, cite every id it closes, and mark the others done.

## 5 · Order, and why

| # | file | area | phase | confirmed | of which critical/high | verify-first |
|---:|---|---|---:|---:|---:|---:|
| 01 | `01-parser.md` | Checkpoint status parser | 1 | 14 | 14 | 15 |
| 02 | `02-belief.md` | Belief engine, serving views, crowd engine | 1 | 5 | 4 | 28 |
| 03 | `03-route.md` | Route verdict (corridor) | 1 | 4 | 1 | 14 |
| 04 | `04-renderers.md` | MCP tool answers (Arabic + English) | 1 | 29 | 22 | 37 |
| 05 | `05-transport.md` | MCP transport, OAuth, rate limit, SSE, licence | 2 | 10 | 5 | 36 |
| 06 | `06-rest.md` | REST handlers, correlation, precision annotation | 2 | 20 | 14 | 78 |
| 07 | `07-classifier.md` | Incident classifier and event writer | 3 | 17 | 6 | 44 |
| 08 | `08-gazetteer.md` | Place resolution and gazetteer tooling | 3 | 4 | 3 | 20 |
| 09 | `09-ingest.md` | Telegram poller and ingestion framework | 4 | 11 | 1 | 22 |
| 10 | `10-feeds.md` | External feed parsers | 4 | 7 | 4 | 18 |
| 11 | `11-ops.md` | Watchdog, alerts, backups, shell steps, systemd | 4 | 16 | 4 | 21 |
| 12 | `12-databank.md` | Tier 2 databank loader, mappings, export | 5 | 5 | 4 | 32 |
| 13 | `13-learning.md` | Learning loop, analyst, self-measurement | 5 | 4 | 1 | 30 |
| 14 | `14-docs.md` | Documentation | 6 | 10 | 2 | 28 |
| 15 | `15-webapp.md` | Public web pages | 6 | 4 | 3 | 13 |

- **Phase 1** is anything that can tell a traveller a closed road is open or hide a closure: the parser inverts
  ordinary phrasing; the default checkpoint row ignores direction-specific readings; the route verdict skips G2's
  coverage rule and speaks exit closures only when `unverified`; anonymous crowd input reaches belief and incidents.
- **Phase 2** is who can reach and abuse the surface (unbounded JSON-RPC batches, OAuth tokens that survive
  revocation, public read paths that write) and answers that state less than they know.
- **Phase 3** is incident accuracy (classifier rules, catastrophic regex backtracking, place resolution).
- **Phases 4–6** are silent failures, the databank, the learning loop, docs and the web pages.

If time is short, **01 → 04 → 03 → 02 → 05** is the order with the most safety per hour.

## 6 · Dependencies between areas (read before starting the named area)

- **03 route ↔ 04 renderers.** The corridor must fill `doubts` and `exit_closures` for EVERY verdict, and the
  renderers must speak them for every verdict, not only `unverified`. Do 03 first; 04's route tasks assume it.
- **02 belief → 04 renderers, 06 rest.** Once the `both` travel row reflects direction-specific readings (new
  migration), `checkpoint_status` and `/v2/checkpoints/summary` change what they say. Re-run 04/06 tests after 02.
- **08 gazetteer → 06, 07, 02.** If `resolve_place` stops learning by default, every caller that relies on learning
  must pass `learn=True` explicitly (serve/app.py, crowd/engine.py, ingest/sources/news_incidents.py). Read-only
  paths (`/v2/insights`, `/v2/route/between`, `/v2/geo/resolve`) must pass `learn=False` regardless.
- **02 belief ↔ 07 classifier.** Crowd sources must not feed incidents (`source.feeds_incidents=false` for kind
  `crowd`) — a migration in 02; the classifier's claim query in 07 must respect it.
- **07 classifier.** Any change that can alter a reading bumps `CLASSIFIER_VERSION` (to 1.9.0). On main-server that
  makes the 5-minute timer re-read the whole corpus: HANDS §8 (`TimeoutStartSec=3600`) must be in place first.
  Project the effect with `python3 ops/rescore_round.py 7` and `8` before and after; report those as projections on
  tuning sets, never as measurements (the next hand-scored round is the measurement).

## 7 · Things only Zaid's hands can do — collect them in `HANDS-NEEDED.md`

Nothing in this plan goes live until it is merged and main-server runs it. List, per area, what that needs:
new migrations to apply with `db/migrate.sh` (after a dry run), `sudo systemctl restart palestine-v2-api` for
`serve/` changes, unit files to copy into `/etc/systemd/system` + `daemon-reload`, the classifier timer timeout, and a
`python -m ingest.sources.checkpoints --full` re-import if the parser changed (it re-reads v1 and rebuilds only its own
rows — confirm with Zaid before running it).

## 8 · A draft you may consult, never copy wholesale

Commit `45c2b18` holds an UNREVIEWED partial attempt at many of these tasks by agents cut off mid-work; it was reverted
in `33703d3`. At that commit, the parser/route/renderer/belief test files had 106 failures. For a task, you may read
the draft for one file (`git show 45c2b18 -- cascade/checkpoint_text.py`) as a hint, but re-derive and test every
change yourself. It also contains three drafted migrations (079 crowd never feeds incidents, 080 serving refuses
future timestamps, 081 the `both` row sees every direction) — same rule, and **their numbers are taken**: the
committed 079 is the `both` row and 080 is crowd-never-feeds-incidents. A future-timestamp guard, if you write one,
is a new number (081+).
