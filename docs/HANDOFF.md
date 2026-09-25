# HANDOFF — read this first

State as of 2026-08-01. Written to survive a context reset: everything here was
verified, not remembered.

> **Corrected for drift 2026-09-25.** §1 is unchanged — its rules are Zaid's to
> amend; two mechanisms they mention have moved and are noted directly under
> them. §2–§7 were re-read against the tree: a fact that stopped being true is
> marked *superseded* with what replaced it, never deleted, and a count that
> only the database or a run can give is replaced by the command that gives
> it. §8 is the record of 2026-08-01 and is left as that day wrote it. The plan
> is now `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md` (canonical, with the §11
> ledger); `CLAUDE.md` is the orientation for a session away from main-server.

**Next session's job:** the frontend. Everything it reads is built, public and
verified — one API at **https://live-api.zaidlab.xyz**, one MCP server, live
state + history + patterns + an SSE stream + crowd submission.

P0-P3 and P5 are done; **Gate T1 is 7 of 8**, and the last criterion (T1.8, a
human can see and export what the system holds) IS the frontend. Do not start
tier 2 until Gate T1 passes — though P5.1 already did tier 2's admin backfill
and cross-tier gate on the way past.

*Superseded (2026-09-24, PLAN §5 Z-1):* the first front door is MCP + API + one
landing/docs page; the human map/app comes later, and T1.8 stays parked behind
ZAID-2 (`docs/DESIGN.md` "Process state"). Tier 2 was built in the meantime
(the databank, 2026-08). The next job is whatever the PLAN's §7 and §11 say is
open.

---

## 1. Hard rules — violating any of these is the worst outcome

1. **`/opt/stacks/palestine` is LIVE PRODUCTION (v1).** Never develop there. v2
   reads v1's SQLite read-only (`?mode=ro`) and writes nothing to it.
2. **NO DATA LOSS.** Nothing is deleted or overwritten; corrections supersede.
   `tests/test_no_data_loss.sql` enforces it. Nightly encrypted off-host backups
   since 2026-08-01, restore-tested weekly from the remote copy.
3. **The Telegram account is the scarcest asset.** agent2 is new and ban-prone.
   Never join channels (public ones are readable without joining). Respect
   FloodWaitError exactly. `StartLimitBurst=3/600s` on the poller is deliberate
   — if it trips, `systemctl reset-failed` and understand why before restarting.
4. **Two Telethon clients must never share one session file.** Concurrent use of
   the same auth key can invalidate the account. Discovery STOPS the poller
   first; it does not copy the session.
5. **`claim` is immutable** — never updated after insert except `event_id`. Our
   *reading* of a claim lives in `claim_classification`.
6. **The API reads `state_serving` / `checkpoint_serving`, never `state_current`.**
7. **Secrets live in `.env` (chmod 600).** Contains DB password, Telegram
   api_hash, FIRMS key. Never print it; filter greps.

*Two mechanisms the rules above name have moved since they were written
(noted 2026-09-25; the rules themselves are unchanged and are Zaid's to amend):*

* **Rule 3.** The poller no longer has `StartLimitBurst=3/600s`. On 2026-08-02
  that limit killed it for seventeen hours after three minutes of network
  trouble, and it was reversed: `StartLimitIntervalSec=0`, restart with backoff
  from 30 s to a 15-minute ceiling, and `RestartPreventExitStatus=2` (exit 2 =
  the session lost its authorisation mid-run → stop, never retry). The unit's
  own header records why (`ops/systemd/palestine-v2-poller.service`). So there
  is no `reset-failed` to run: a poller in trouble is a slow restart loop, and
  the journal and the watchdog's `telegram-poller` row are where it shows.
  The rule's substance — never storm Telegram, respect FloodWait exactly —
  is exactly what the backoff serves.
* **Rule 5.** `claim` has one recorded, argued exception besides `event_id`:
  organ A writes `claim.lang` and `attrs.lang_detector` (a measurement of the
  text, stamped with its detector — not something the source said).
  `docs/analyst.md` "Organ A, and why it may write to an immutable table" is
  the argument; `analyst/organs.py` and `analyst/backfill_lang.py` are the only
  writers. Nothing else in a claim is ever updated.

---

## 2. What runs

| unit | cadence | does |
|:--|:--|:--|
| `palestine-v2-api` | daemon | FastAPI on :7870 — **public at https://live-api.zaidlab.xyz** |
| `palestine-v2-poller` | daemon | agent2 Telegram poller, 10 channels, 30s |
| `palestine-v2-checkpoints.timer` | 2 min | v1 SQLite → claims/state |
| `palestine-v2-news.timer` | 5 min | classify news claims → events |
| `palestine-v2-external.timer` | 15 min | RSS → **fuel prices** → weather → connectivity → power → fires → classify |
| ~~`palestine-v2-fuel{,-images}.timer`~~ | retired 2026-09-23 | fuel availability; units kept in `ops/retired/systemd/` (migration 070) |
| `palestine-v2-checkpoint-learn.timer` | nightly 03:20 | independence + persistence re-fit |
| `palestine-v2-accuracy.timer` | nightly 04:10 | precision backtest → `ops/accuracy.ndjson` |
| `palestine-v2-backup.timer` | nightly 02:30 | encrypted set → `gdrive:palestine-v2-backups` |
| `palestine-v2-restore-test.timer` | Sun 05:00 | restores the REMOTE copy, asserts it |
| `palestine-v2-crowd.timer` | 2 min | belief over the 13 crowd-reportable fields |
| `palestine-v2-rollup.timer` | nightly 04:40 | freeze yesterday into the databank |
| `palestine-v2-watchdog.timer` | 10 min | 27 checks over jobs/capacity/deps/feeds |
| `palestine-v2-alert@.service` | on failure | records alarms to `ops/alerts.ndjson` |

Unit files are copied into `ops/systemd/` — they used to exist only in `/etc`,
on the disk the backups exist to survive losing. See that directory's README for
installing and for checking the two have not drifted apart.

**Everything is watched (P3.1).** `OnFailure=` is on all twelve units, and
`ops/watchdog.py` runs every 10 minutes over four check families:

| family | asks | source |
|:--|:--|:--|
| jobs | is the collector alive? | `ops_heartbeat`, written by every job on every successful cycle |
| capacity | will the disk fill? | `statvfs`, fault below 10 GB free |
| dependencies | is v1 still writing? | mtime of the SQLite (+ its `-wal`) and the tee spool |
| feeds | is data arriving? | age vs the feed's own measured p99 gap x3 |

The heartbeat is the load-bearing part. "The collector died" and "the sources
are quiet" produce identical evidence — no new rows — so a job records success
on **every** cycle including empty ones, and that signal is the only one that
disappears exactly when a collector does. Run `.venv/bin/python -m ops.watchdog`
any time; `--dry-run` never alarms.

DB: Postgres in container `palestine-v2-db`, database `palestine_v2`.
Migrations: `db/migrate.sh` (guards against wrong DB).

**Backups.** `ops/backup.py` (nightly), `ops/restore_test.py` (weekly, pulls the
set back down from the remote). The passphrase is
`~/.config/palestine-v2/backup.key` — **it lives on the disk the backups exist
to survive losing, so it must also be in Zaid's password manager or the off-site
copies are unrecoverable noise.** Google Drive is the ONLY destination and that
is an accepted risk, not an oversight — there is no always-on second box on this
network. `BACKUP_REMOTE` in `.env` is comma-separated if one appears.

---

## 3. Verify state in one command

```bash
cd ~/palestine-v2 && set -a && . .env && set +a
for f in tests/test_gate*.sql tests/test_no_data_loss.sql \
         tests/test_schema.sql; do
  docker exec -i -e PGPASSWORD="$PGPASSWORD" palestine-v2-db \
    psql -tA -U "$PGUSER" -d "$PGDATABASE" -f - < "$f" | grep -c '^PASS'
done
.venv/bin/python -m pytest -q --deselect tests/test_evidence.py::test_vault_verifies_end_to_end
# ^ the vault re-hash (~30 min, 1.8k objects) runs alone:
#   .venv/bin/python -m pytest -q tests/test_evidence.py::test_vault_verifies_end_to_end
# It lives in tests/test_evidence.py. The `--ignore=tests/test_vault_verifies_end_to_end.py`
# used through 2026-09-22 named a file that does not exist and excluded nothing.
.venv/bin/python tests/test_arabic.py; .venv/bin/python tests/test_ingest.py
```
Expected: 60 SQL passes (9/19/10/9/4/9), 315 pytest, 34 + 27 standalone.
**436 total.** `test_crowd.py` takes ~48s — it exercises the real belief SQL in
rolled-back transactions, because a Python reimplementation of the model would
only prove the reimplementation safe.

Bare `pytest` is now the whole invocation. This section used to carry an
explicit 11-file list, because `test_arabic.py` and `test_ingest.py` are
standalone scripts whose `raise SystemExit(main())` fired at collection and
killed the run — and the list drifted TWICE, silently omitting first
`test_palhub_roads.py` and `test_corridor.py`, then `test_fuel_image.py`.
tests/conftest.py now excludes the two scripts at collection, so new test
files are picked up by existing, not by remembering. The pytest count above
still goes stale the ordinary way; trust the run, not this paragraph.

`test_api.py` needs the API's dependencies reachable but NOT the API service
running — it drives the ASGI app in-process. It does need Valhalla, and it
checks that `VALHALLA_URL` names something that identifies itself as Valhalla
rather than merely answering: the value in `.env` pointed at `honcho-api-1` on
127.0.0.1:8002 for two days, and both route endpoints returned 503 to anything
that sourced it.

Backups, separately — the second command genuinely restores and compares:
```bash
.venv/bin/python -m ops.backup --status        # last nightly result
.venv/bin/python -m ops.restore_test --from-remote
.venv/bin/python -m ops.restore_test --no-bracket   # MUST fail (8 missing FKs)
.venv/bin/python -m ops.alert --list           # exit 1 if any alarm is open
```

Liveness, separately — this is the one that tells you the system is still
collecting rather than merely still running:
```bash
.venv/bin/python -m ops.watchdog               # exit 1 if anything is late
curl -s localhost:7870/health | jq '.status, .faults'
curl -s https://live-api.zaidlab.xyz/v2 | jq '.route_count'   # public, from outside
```

The analyst (P0, 2026-09-19) is on that same board as the job `analyst`, and has
two views of its own — `analyst_health` per organ and `analyst_backlog`. What it
is, and how organs B–G attach to it: `docs/analyst.md`.

---

## 4. Traps that already bit once — they will bite again

These are not hypotheticals. Each cost real debugging time and several produced
silently WRONG data rather than errors.

**Arabic orthography must match on both sides.** Patterns are matched against
`normalize()`d text, so `إغلاق`, `خامنئي`, `قطاع غزة` can never match `اغلاق`,
`خامنيي`, `قطاع غزه`. `cascade/news.py` folds every pattern at import
(`_norm_pat`). The same bug hit SQL — `ILIKE` does not fold hamza, so `أريحا`
never matched `اريحا` until `translate()` was added.

**Arabic marks tense with a PREFIX.** `تقتحم` shares no leading letters with
`اقتحم`, and the verbal noun `اقتحام` contains neither (stem is `قتح`). Match
prefix + consonantal stem.

**Nouns and participles NAME people far more than they report events.** `الشهيد`
filed a cemetery attack as a death; `المعتقل` would file "the detained child" as
an arrest; `حاجز` (the noun "checkpoint") made naming a checkpoint report
soldiers at it. Require a verb.

**Match phrases on TOKEN boundaries.** `حومش سالك` ("Homesh is flowing")
contains the characters of `مش سالك` ("not flowing") across a word boundary and
inverted a busy checkpoint's status.

**`ما زال` means STILL, not NOT.** It turned "still closed" into open.

**Legacy encodings.** NEDCO serves windows-1256; decoded as UTF-8 the whole site
is mojibake and looks contentless. This nearly cost the entire power vertical.

**Rate ≠ recency.** A channel that posted 14/day and died 530 days ago still
scores 14/day. `discover_channels.py` gates on `STALE_AFTER_DAYS = 14`.

**IODA accepts relative time ranges and returns 200 with an EMPTY series.** Use
absolute epochs.

**Feeds sharing `state_observation` must scope their `state_current` rebuild to
their own `state_kind`.** The fuel loader rebuilt every kind and silently wiped
checkpoint corroboration.

**Incremental filters must key on `claim_classification`, not `claim_type`** —
precisely because we respect immutability and never stamp the verdict back. The
obvious filter reprocessed the whole corpus each run and duplicated every event.

**Guard decay EXPONENTS, not just outputs.** `power(0.5, 4800)` underflows
float8 before any output clamp runs.

**A state with ONE possible value is not a measurement.** `checkpoint_idf` only
ever held `present`, because the parser discarded every "بدون جيش" — 28.31% of
all presence mentions. Its persistence fit then returned 1.00 at every lag,
which looks like a beautifully stable signal and is an artifact of nothing else
being reportable. Before trusting any fitted curve, check the value has more
than one value.

**A negator is consumed by the first lexicon word it reaches.** "المربعة بدون
جيش سالكة" — "without army, FLOWING" — read the بدون two tokens back and
published the road as CLOSED.

**When a state_kind's NAME is the answer, the VALUE still has a sign.**
`checkpoint_serving` built its presence array with `WHERE value <> 'unknown'`
and took `checkpoint_idf` -> `idf`, so a fresh `absent` reading would publish as
army PRESENT. Gate G2.10 now asserts it cannot recur.

**Corroboration counts INDEPENDENT GROUPS.** Nine road channels agree 99.5–100%
and are ONE observer. This is the recurring theme — it reappears for crowd
reporting (P2), where the adversary is a person with five phones.

**A comment claiming idempotence is not idempotence.** `ops/ingest-fuel.sh` said
"re-reading the same spool lines produces the same observations". Re-reading
them INSERTED them again: 98.48% of all fuel rows were exact duplicates, one
observation stored 490 times, ~3.5M rows/day. The comment is most of why it
survived. Any loader that re-reads an append-only spool needs a cursor
(`ingest_seen`), and the way to check is `count(*)` against
`count(distinct (place_id, state_kind, observed_at, source_id, value))`.

**Do not "fix" duplication with a UNIQUE index without checking first.** The
obvious one here — `(place_id, state_kind, source_id, observed_at)` — is
violated by 672 keys carrying genuinely different values, because stations
without OSM coordinates share a locality centroid. It would have silently
dropped real readings to fix a bloat bug.

**Verify what a bracket/flag actually buys before building a test on it.**
TimescaleDB restore folklore says hypertables come back "hollow" without
`timescaledb_pre_restore`. On 2.29 they do not — rows arrive and hypertables
register either way. What is really lost is 8 FOREIGN KEYS, while `pg_restore`
exits 0 and every row count matches. A test written to the folklore would have
checked the wrong thing and passed.

**Compression is not automatically good for backups.** Columnstore made the dump
BIGGER on text-heavy Arabic chunks (19.25 → 22.61 bytes/row) because pg_dump's
gzip was already beating it and cannot re-compress the blobs. It halves the dump
on the 99.9%-repeated fuel rows. Measure the backup, not only the disk.

**SHORT ARABIC STRINGS MUST BE ANCHORED TO TOKEN BOUNDARIES.** This is the
`حومش سالك` trap and it keeps coming back, worse each time. `رأي` (opinion)
normalises to `راي`, which is a substring of `اسراييلي` — **إسرائيلي,
"Israeli"** — so 142 claims were silently rejected as commentary for containing
one of the commonest words in the corpus. It also sits inside `حرايق` (fires)
and `ترحيل` (deportation). Before adding any pattern under ~5 characters, grep
the corpus for what real words contain it.

**A held-out sample is not a formality.** Round 1 of the incident measurement
found 43 defects; fixing them meant editing the patterns those very claims came
from, which turns them into a tuning set. The two worst bugs in the whole
classifier — the `راي` substring and `استشهاد` not containing `استشهد` — were
found only by round 2, on claims that had never been looked at.
`learn/incident_precision.py` enforces disjointness in code.

**Imprecision does not vanish by being ignored.** Don't quote a drive time to a
governorate-centroid station; don't corroborate a fire against a report that
only said "south of Nablus".

**A `try/except` that keeps a loop alive will one day absorb the thing that
should have killed it.** The poller caught per-channel failures so one dead
channel could not stop it, and that handler silently swallowed one dead
*client*: it ran for eight hours calling into a disconnected Telethon session,
printing an error every 30 seconds, while `systemctl` said `active (running)`.
A transport failure is not a channel failure and must be checked separately,
above the loop. **A crash that gets noticed beats a run that does not.**

**"No new rows" has two causes and only one is a fault.** A dead collector and
a quiet source produce identical evidence, because both are defined by rows that
are not there. Nothing you can query distinguishes them. The only signal that
disappears exactly when the collector dies is the collector saying "I ran and
succeeded and there was nothing" — so `ops_heartbeat` is written on **every**
successful cycle, including empty ones. Beat only when there is something to
report and the ambiguity comes straight back.

**A paging API returns the NEWEST page.** `get_messages(limit=100, min_id=last)`
gives the newest hundred, not the oldest; advancing the cursor to `max(id)` then
skips everything below the page boundary permanently, and nothing reports it.
The 8-hour outage recovered 80 messages against a page size of 100 — a margin of
twenty. Page oldest-first, so the cursor only ever advances across a contiguous
run.

**A shell step that ends `|| echo "failed"` cannot fail.** `ingest-external.sh`
ran six feeds that way and ended `exit 0`, so all six could be dead while
systemd recorded success and `OnFailure=` could never fire. Count the failures
and re-raise.

**SQLite in WAL mode does not touch the .db file when it writes.** Judging
freshness by `checkpoints.db` reported v1 as 40 minutes stale while
`checkpoints.db-wal` was 24 seconds old and v1 was perfectly healthy. Check the
sidecar, or the alarm will name the wrong system confidently.

**A threshold learned from history must hold out the window it judges**, or a
feed that degrades slowly drags its own threshold down with it and never trips.
Same discipline as the held-out precision rounds.

**A "never penalise the unmeasured" default can invert when the population
changes.** `COALESCE(trust_weight, 1.0)` was right for curated channels — the
absence of a measurement is our failing, not theirs. Applied to the crowd it
would have handed a thirty-second-old anonymous account the same standing as a
two-year-old road channel. The default has to depend on who the reporter is.

**A formula that calls itself a noisy-OR should be one.** `(1 - 0.15^agree) *
trust(LATEST reporter)` was a fine approximation while every source was the same
kind, and inverted the moment they were not: a stranger AGREEING with a channel
dropped a checkpoint from 0.849 to 0.196, so corroboration reduced confidence and
anyone could blind any checkpoint by confirming it. Approximations encode
assumptions about the population; changing the population breaks them silently.

**A report can be accepted, stored, correct-looking, and structurally incapable
of ever mattering.** Crowd checkpoint reports resolved to the LOCALITY while
every channel report sits on a `checkpoint` place. Nothing errored, nothing
warned, and the reports could never corroborate or be served. Found by testing
the end-to-end path, not by reading the code.

**An honest threshold can still be useless.** `checkpoint_settlers`' measured
p99 puts its deadline at 9.7 days — real, derived, and it would take a week and
a half to notice the feed had died. Reporting that as `ok` overstates what is
known, hence `watched_loosely`. "We checked" and "we would have noticed" are
different claims.

---

## 5. Where things are

- `docs/TIER1_COMPLETION_PLAN.md` — **the plan. Start here.** Gate T1, P0–P4.
  Completed sections keep their original text in a `<details>` block.
- `docs/DECISIONS.md` — ~155 one-line decisions with their WHY. Append, never edit.
- `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAN.md` — original design.
- `cascade/` — text → structure (`checkpoint_text.py`, `news.py`, `palhub_fuel.py`)
- `ingest/sources/` — one module per source
- `data/evidence/` — **the as_of evidence base, and it is load-bearing.**
  `ops/asof_harness.py` is the only proof `observation.sys_period` tells the
  truth, and until 2026-08-07 that proof lived only inside v1's snapshot tree.
  `ops/vault_snapshots.py` copied it here (indexes hot, payloads
  content-addressed in bronze, sha256 per entry, `--verify` re-reads every
  byte); `ops/snapshot_inputs.py` keeps it growing nightly from v2's own
  loader inputs; `ops/evidence.py` is the seam both harnesses read through,
  vault first. Run with `PALESTINE_V1_ROOT=/nonexistent` to prove the cut is
  survivable. If this stops growing, history keeps answering and quietly
  stops being provable.
- `learn/` — everything that measures the system:
  - `accuracy.py` — precision backtest, replays the real serving gates.
    Imports `SINGLE_SOURCE_TRUST` from the serving path so it cannot drift.
  - `reliability.py` — **Loop A**, per-reporter Beta posterior. The reputation
    engine P2 runs on; written over "reporters", not channels.
  - `incident_precision.py` — hand-scored classifier precision, enforces
    disjoint sampling rounds.
  - `crowd_independence.py` — **P2.3.** Grants a submitter their own
    independence unit once they have earned it, and revokes it if they drift
    into lockstep with another. Independence is earned, never assumed.
  - `source_independence.py` (copy-collapse), `state_persistence.py` (decay)
- `crowd/` — **P2, the endgoal.** `engine.py` is the one submission path for
  every field; which fields it accepts is `state_kind_config`, not code.
- `resolve/belief.py` — **the ONE implementation of "what do we believe".**
  Independence units, per-unit noisy-OR, earned trust, the P2.4 gate. Shared by
  checkpoints, fuel and the crowd; there used to be three and they disagreed.
- `ops/` — operability:
  - `watchdog.py` — **P3.1.** 24 checks over jobs / capacity / dependencies /
    feeds. The measurement of each feed's cadence lives here and is written to
    `feed_cadence` for `/health` to read.
  - `heartbeat.py` + `with-heartbeat.sh` — how a job says "I ran and it worked".
    Never fails the job it reports on.
  - `alert.py` — the alarm sink. Conditions auto-close, events wait for
    `--clear`; append-only either way.
  - `backup.py`, `restore_test.py`, and `*.sh` for the timers
  - `systemd/` — copies of the installed units, which used to exist only in
    `/etc` on the disk the backups exist to survive losing

---

## 6. Measured facts worth not re-deriving

- Checkpoint precision **0.821**, independent cross-source, coverage 77%.
- Single-unit fresh precision **0.852** (<15m) — this is what
  `SINGLE_SOURCE_TRUST = 0.85` is, and it is measured, not chosen.
  Calibration error 0.309 → 0.181 after that change.
- Fuel is single-source (palhub) so it CANNOT be precision-measured; ~0.996 is
  self-consistency and is inflated by base rate.
- Persistence: `open` 0.96→0.88 flat, `closed` 0.92→0.69, `congested` 0.84→0.41.
  `open`'s flat tail is the BASE RATE, not knowledge.
  `checkpoint_idf present` half-life **15 min** — why presence is a sighting.
- Copyset: 9 Telegram road channels = 1 observer. `a7walstreet` is independent
  and is first-reporter 74% / sole 53%.
- **All 15 measurable reporters are equally good** (kappa 0.90–1.00). There is
  no bad source to demote; copy-collapse already handles the reposting problem.
  Loop A's value is as P2's engine, not as a discriminator among today's feeds.
- Incident classifier **0.864 held out** [0.77–0.92] on raid / injury /
  settler_attack / shooting. The other five types have NO held-out number.
  Miss rate 17.5% on non-mechanical rejects.
- Presence reporting gap per place: idf 34.7h, police 58.4h, settlers 115h —
  against a 15-minute half-life. A ~140x mismatch, unfixable by any cap.
- Feed cadence, measured (p50 gap → alarm threshold): `checkpoint_status`
  1m → 42m, `checkpoint_flow` 1m → 57m, `checkpoint_idf` 8m → 7.2h.
  Five of eleven feeds — fuel, weather, internet, road_closure — are too
  irregular for a percentile to mean anything and are covered by their
  collector's heartbeat instead. That is stated, not skipped.
- **Bronze is 3,945 files holding 1.3 MB and occupying 22 MB.** ~330 bytes per
  payload in a 4 KB block; compressing files cannot help, archiving many into
  one would (0.77 MB, 28x). Not worth doing yet — 250 GB and 29M inodes free
  against ~8 MB and ~2,000 inodes a day.
- `/health` costs ~140ms because the 21-day cadence scan is cached in
  `feed_cadence`; recomputing it per request was ~570ms.
- 28.31% of presence mentions are NEGATED. Absence is now recorded (1,997 obs).

---

## 7. Immediate next actions


P0, all of P1, P2 and all of P3 are done (2026-08-01) — see
`docs/TIER1_COMPLETION_PLAN.md`. **Gate T1 is 7 of 8**: only T1.8 (a human can
see and export what the system holds) remains, and that is P4. T1.2 is partial
— see item 4.

1. **P4 — being able to see it.** The last unbuilt gate (T1.8). Everything is
   API + MCP and there is no way for a person to look at the data or export it.
   **[ZAID] decision:** phone-first family page vs operator dashboard — they are
   different builds, and the crowd engine now gives either one something to
   submit to.
2. **P2.5 — backtest the crowd path.** Not possible yet and not urgent: an
   unverified submitter scores 0.17, below every floor, so the crowd can only
   corroborate today. It becomes both possible and necessary the moment the
   first submitter earns their own independence unit.
3. **P2 loose ends.** The MCP submission tool is not wired (HTTP is). There is
   deliberately no HTTP registration endpoint — onboarding is Zaid's call and an
   open endpoint would settle it by default; `crowd.engine.register()` works
   from the shell. And `palhubappfuel` is still unparsed: ~181 messages a day of
   real people reporting fuel, already in bronze, which would give P2.5 a
   backtest corpus that exists before the first submitter does.
4. **P1.1 round 3.** `death`, `arrest`, `siege`, `demolition` and `closure` have
   NO held-out precision: round 1 consumed the whole population of those types.
   `learn/incident_precision.py --sample` already refuses to reuse a scored
   claim, so this is just a matter of waiting for the feed to produce more.

**P2 is built.** 13 of 14 fields crowd-reportable by configuration; a
sock-puppet ring is one independence unit scoring 0.17, below every floor;
reassuring values need a second witness. See the plan's P2 section.

Two decisions are Zaid's, not mine:
- **P2.4** the abuse policy. A default is running and is documented in the plan
  — reassurance needs corroboration, cautions do not. It is a judgement about
  family safety, so confirm or change it.
- **P4.1** phone-first family page vs operator dashboard — different builds.

---

## 8. What changed on 2026-08-01, in one place

P0, P1.1, P1.2, P1.3, all of P2 and all of P3 completed.
Migrations 022–030. Tests 127 → **219**. Gate T1 4 of 8 → **7 of 8**.

| | before | after |
|:--|:--|:--|
| backups | **none** | nightly encrypted off-host, restore-tested weekly |
| fuel rows | 774,374 (98.48% exact duplicates) | cursor added; 0 new duplicates |
| `source.reliability` | NULL for all 42 | 15 measured, nightly |
| `SINGLE_SOURCE_TRUST` | 0.70 assumed | 0.85 measured |
| incident precision | unknown | 0.864 held out (4 of 9 types) |
| presence | a "state" with ONE value | a sighting, absence recorded |
| monitoring | `OnFailure=` on 2 of 12 units | all 12, plus a 24-check watchdog every 10 min |
| `/health` | fuel only | every vertical + every job, ~140ms |
| unit files | only in `/etc`, unbacked-up | `ops/systemd/`, with a drift check |
| crowd reporting | `source.kind='crowd'` was a valid enum with zero rows | 13 of 14 fields reportable by configuration |
| belief | three implementations that disagreed | one, `resolve/belief.py`, shared by all |
| fuel confidence | flat 0.95, a parse confidence in a belief's clothing | 0.85, measured, with real corroboration |

Five bugs found that were producing silently wrong data, not errors:
1. `رأي` inside `اسراييلي` — 142 claims rejected for containing "Israeli".
2. `settler_attack` stem `اقتحم` — settlers recorded as **army** raids.
3. `استشهاد` not containing `استشهد` — a death filed as an injury.
4. negator over-reach — "without army, **flowing**" published as **closed**.
5. `WHERE value <> 'unknown'` in `checkpoint_serving` — a fresh "no army"
   would have published as army **present**. Latent; gate G2.10 added.

Every one of them lost the SIGN of a fact while the fact still looked fine.
That is the single most useful pattern to carry forward.

### And then P3 found the same shape at the process level

**The Telegram poller had been dead for eight hours** when the watchdog work
started — disconnected at 08:35 by a network blip, then looping against a dead
client. `systemctl` said `active (running)`. `/health` said `{"status":"ok"}`.
The news classifier ran every five minutes and logged a clean run. The whole
news vertical was dark and every single indicator was green. It was found by
hand, by accident, while measuring cadence to build the thing that would have
caught it. Recovery restored 362 claims; nothing was lost.

The data bugs lost the sign of a fact. This lost the *fact that there was no
fact* — which is worse, because silence is what a healthy system also produces.
Three more of the same kind turned up once we went looking:

- the poller's recovery would have **silently dropped messages** past the page
  boundary; the outage came within twenty of proving it
- `ingest-external.sh` **could not fail** — six dead feeds, `exit 0`
- the v1 SQLite is in **WAL mode**, so the naive freshness check would have
  raised a confident alarm about a perfectly healthy v1

The rule that falls out: **never infer health from the absence of a complaint.**
Something has to positively assert it ran, and something else has to notice when
that assertion stops arriving.
