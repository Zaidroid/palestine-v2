# Tier 1 completion plan — what "ready" means, and what is left

Written 2026-07-31, updated 2026-08-01. Every number here was measured, not
estimated.

Tier 1 (the live tracker) answers fuel, checkpoints, incidents, road closures,
weather and internet reachability, from 43 sources across Telegram, RSS and
public APIs — plus, since 2026-08-01, anyone with a phone. Checkpoint precision
is **0.817 measured**, coverage 76%. **219 checks pass.** Gate T1 is **7 of 8**;
only T1.8, a way for a human to see and export it, is unbuilt.

---

## Gate T1 — the definition of ready

Tier 1 is ready when **all** of these hold. They are checks, not opinions.

| # | Criterion | Today |
|:--|:--|:--|
| T1.1 | The database survives losing its disk | **passes** — nightly encrypted off-host set, restore tested from the remote copy |
| T1.2 | Every serving vertical has a MEASURED precision, published | fuel, checkpoints, **incidents (0.864 held out, 4 of 9 types)** |
| T1.3 | No vertical asserts a reading it cannot stand behind | passes (3 gates, 12 checkpoint tests; presence demoted to sighting) |
| T1.4 | Source reliability is learned, not assumed | **passes** — Loop A nightly; 15 of 42 scored, the other 27 have no state observations to score against and say so |
| T1.5 | A silent pipeline failure raises an alarm | **passes** — `ops/watchdog.py` every 10 min, 24 checks over jobs/capacity/dependencies/feeds; `OnFailure=` on all 12 units. Proved against the live 8-hour poller outage it was written during |
| T1.6 | Coverage and blind spots are stated in every answer | passes |
| T1.7 | The crowd can contribute without being able to poison it | **passes** — engine live, 13 fields by configuration; a sock-puppet ring is one independence unit and scores 0.17, below every floor. P2.5 backtest pending the first earned submitter |
| T1.8 | A human can see and export what the system holds | **not built** |

One T1.1 caveat is still open, and it is Zaid's to close, not mine:

- **The backup passphrase is on the disk the backups exist to survive losing.**
  Until `~/.config/palestine-v2/backup.key` is in your password manager, the
  off-site copies are unrecoverable noise. `ops/backup.py --show-key-instructions`

Accepted risk, recorded rather than pending: backups go to **Google Drive only**.
There is no good second destination — no NAS, the Mac cannot be pushed to from
main-server, and every Tailscale Linux box is intermittent. A destination that is
often offline produces nightly alarms, and alarms that are always expected train
you to skim past the one that matters. `BACKUP_REMOTE` takes a comma-separated
list whenever an always-on box or a B2 account appears.

---

## P0 — Data safety. DONE 2026-08-01.

Built: `ops/backup.py`, `ops/restore_test.py`, `ops/alert.py`, migrations 022
and 023, four systemd units. What each item became:

- **P0.1 ✔** Nightly 02:30 (before the learn jobs, so the night's set predates
  anything they rewrite). `pg_dump` custom format + `pg_dumpall --globals-only`,
  gpg AES256, `rclone` to `gdrive:palestine-v2-backups`, checksum-verified after
  upload, 30 dailies plus every first-of-month kept forever.
- **P0.2 ✔** `data/bronze` and a `.backup`-consistent copy of the Telethon
  session and `.env` ship in the same set.
- **P0.3 ✔** `ops/restore_test.py`, weekly Sunday 05:00, **pulling the set back
  down from the remote**. Asserts exact row counts, hypertable chunk counts, and
  index/constraint parity against live.
- **P0.4 ✔** Sanity gates in the backup itself (dump under 50% of the previous
  run, or any table under 95% of its previous count, fails the run before
  anything is promoted or uploaded), plus `OnFailure=` into `ops/alert.py`.

### What P0 turned up on the way

Sizing the backup exposed a defect nothing else would have caught. The dump grew
12.0 → 18.5 MB in 19 hours; at that rate 30 retained sets breach the Drive quota
in about two months, so the growth rate was quietly disarming the thing meant to
protect the data. Chasing the growth:

    fuel rows                774,374
    unique observations       11,765
    pure duplicates          762,609  = 98.48%
    worst single observation     490 copies
    non-fuel, same query               0.25%

`palhub_loader` re-read the whole tee spool every 5 minutes and re-inserted
every line — ~3.5M rows/day to record roughly 6k real observations. Fixed with a
cursor (`ingest_seen`, migration 023). The comment in `ops/ingest-fuel.sh`
claiming it was "idempotent" is most of why this survived so long.

**This also had to be fixed before P1.2.** Loop A measures per-source reliability
from observation counts, and palhub carried ~66x the weight of every other
source. Running it first would have produced confident, wrong numbers.

Migration 022 additionally compresses `state_observation` (lossless — the
no-deletion rule stands). The 762,609 existing duplicates are **kept**; whether
to dedupe history is **[ZAID]'s** call.

---

## P1 — Trust. We cannot call it ready while we cannot state its accuracy.

### P1.1 Measure the incident classifier — DONE 2026-08-01

`learn/incident_precision.py`. Two disjoint rounds, hand-scored.

| | round 1 (tuning) | round 2 (held out) |
|:--|:--|:--|
| overall precision | **0.732** | **0.864** [0.77–0.92] |
| sample | 123 incidents + 40 rejects | 81 incidents + 40 rejects |
| miss rate on rejects | 25.0% | 17.5% |
| gate | **FAIL** — demolition 0.353, closure 0.500 | **PASS** |

Round 1's claims were spent finding 43 defects and then fixing the very patterns
they came from, which makes them a tuning set — `already_scored()` enforces that
later rounds are disjoint, because re-scoring them would measure how well the
rules were fitted to their own examples and would come back near 1.0.

Per type, held out: raid 1.00, injury 0.95, settler_attack 0.80, shooting 0.75.

**Three real bugs, the worst found by the held-out round:**
- `رأي` (opinion) normalises to `راي`, a **substring of `اسراييلي`** — إسرائيلي,
  "Israeli". **142 claims** were rejected as commentary for containing one of the
  commonest words in the corpus. Also inside `حرايق` (fires) and `ترحيل`
  (deportation). Same family as `حومش سالك` containing `مش سالك`.
- `settler_attack` spelled its raid stem `اقتحم` while `raid` correctly used the
  prefix-aware form, so settlers storming a village were recorded as **army**
  raids. settler_attack 35 → 103.
- `استشهاد` does not contain `استشهد`, so a man who died of his wounds was filed
  as an injury. death 2 → 16.

**Still open:** `death`, `arrest`, `siege`, `demolition` and `closure` have **no
held-out measurement** — round 1 consumed the entire population of those types.
They need a round 3 once the live feed has produced more. The 0.864 covers four
types, not nine.

**Known limitation, not a bug:** these events have two axes — action and outcome
— and one label cannot carry both, so a casualty during a raid must be filed as
one or the other. Pattern order now resolves it by harm, then actor, then
action. The real fix is to record both, which is a schema change.

<details><summary>Original plan text</summary>
302 classifications and **no precision number**. Yield (22%) is a rate, not an
accuracy — it says how often the classifier fires, not how often it is right.
Checkpoints and fuel were backtested; incidents were not, and I should not have
shipped without it.

Incidents are events, not state, so the checkpoint backtest does not apply.
Method: stratified sample of ~120 classified claims, hand-scored against four
questions — is it an incident at all, is the type right, is the place right, is
it West Bank. Publish precision per incident type, because the aggregate will
hide the weak ones exactly as it hid `slow` scoring 0/16 in the checkpoint
parser. Include a sample of REJECTED claims too, to measure what is being
thrown away.

**Gate: ≥0.80 overall and no type below 0.60, or the weak types stop being served.**
</details>

### P1.2 Run Loop A — learned reporter reliability — DONE 2026-08-01

`learn/reliability.py`, on the nightly learn cycle. 15 of 42 sources scored;
fuel, weather and internet are reported **unmeasurable** (one independence unit
each — no second observer), and 27 sources produce claims rather than state
observations and cannot be scored this way at all.

**The expected finding did not happen.** There is no bad source to demote: all
15 score kappa 0.90–1.00, the weakest with real evidence being `almasshta` at
0.904. The "channel that only reposts" problem this task expected to solve is
already handled by copy-collapse, which is a different mechanism. So per-source
weighting changes almost nothing today — its value is that it is the engine P2
runs on, where reporters *will* differ.

**What it did fix is the confidence scale.** `SINGLE_SOURCE_TRUST` was a flat
0.70; the backtest's freshest age band is by construction P(correct | single
unit, fresh) = **0.852**, so 0.70 was too low even at zero age and the whole
model was under-confident — it said 0.3 and was right 73% of the time. Now 0.85,
measured. Precision 0.820 and coverage 77% unchanged (the binding gate is
staleness, not the confidence floor); calibration error **0.309 → 0.181**.

Deliberately *not* 0.98, which is what Loop A measures for inter-unit agreement
and which would lower calibration error further: that number is consistency, not
correctness, and it would push a single source above `MAX_CONFIDENCE` so a
second independent group would add nothing.

`reliability_trust` / `trust_weight` (migration 024) give P2.3 its "earned,
never seeded" property for free — 1/1 correct yields a bound of 0.21, 90/100
yields 0.82 — with no rule anywhere that treats newcomers as suspicious.
`tests/test_reliability.py` pins that behaviour.

<details><summary>Original plan text</summary>
`source.reliability` is NULL for all 42 sources. Migration 003 says "NULL until
measured — never seed by hand", and it has never been measured, so every source
is currently trusted equally. `a7walstreet` (74% first-reporter, 53% sole) and a
channel that only reposts are treated identically.

The measurement already exists in another form: the checkpoint backtest computes
per-observation correctness against independent sources. Generalise it to a
per-reporter Beta-Bernoulli posterior and write `reliability` + `reliability_n`.
Then feed it into `base_confidence` in place of the flat 0.70.

**Build it generic over REPORTERS, not over Telegram channels.** [ZAID]'s scope
for P2 (below) makes this engine the thing crowd reputation runs on, so a
"source" here is anything that makes a claim — a channel, an API, a scraper, or
a person with a phone. Every design choice in this loop should read the same
whether the reporter is `a7walstreet` or submitter #4471, and it must work for
every state kind tier 1 tracks rather than being tuned to checkpoints. Doing
that now costs little; retrofitting it later means rewriting the confidence
model with live crowd data already flowing through it.
</details>

### P1.3 Decide what presence is for — DONE 2026-08-01

**Both framings in the original question were wrong**, because something more
basic was broken underneath them. `checkpoint_idf` had exactly ONE value in
6,226 observations: `present`. The parser discarded negated presence — "بدون
جيش", "ما في جيش" — which are the only statements of absence anybody makes.
**1,752 of 6,188 presence mentions in the corpus are negated: 28.31%.**

A single-valued state cannot be wrong, contradicted, or decay. Its persistence
fit returned **1.00 at every lag**, which reads as a beautifully stable signal
and was an artifact of there being nothing else to report — the same trap as
`open`'s flat tail being the base rate. It was measuring the vocabulary, not the
world.

With absence recorded (1,997 observations), the real curve appears:

| kind | value | 5m | 60m | half-life |
|:--|:--|:--|:--|:--|
| `checkpoint_idf` | present | 0.94 | 0.69 | **15 min** |
| `checkpoint_idf` | absent | 0.94 | 0.77 | 60 min |

**Decision: presence stops being served as a state.** A 15-minute half-life
against a 34.7-hour reporting gap is a ~140× mismatch. No cap fixes that, and
99% `unknown` is the system correctly saying "nobody has looked recently". The
cap was **tightened** 2h → 45min to match the measurement — the opposite of the
thing this plan forbade; it asserts less, not more.

It is now a **sighting** (`state_kind_config.serving_mode`, migrations 025–027):
*"IDF reported at Huwara 25 minutes ago"* is true and never expires into a lie,
because the age is part of the claim rather than a caveat on it. `absent` is
published in its own array — *"no army reported here ten minutes ago"* is worth
as much to a family as a sighting, and was being collected and thrown away.

police / settlers / inspection could **not** be fitted (18, 1 and 21 absence
pairs) and keep the conservative default rather than borrowing idf's curve.

**Two inversions found on the way**, both caught before reaching anyone:
- a negator reached past the word it belongs to, so "المربعة بدون جيش سالكة"
  ("without army, **flowing**") published the road as **closed**. 16 lines.
- `checkpoint_serving` built `present` with `WHERE value <> 'unknown'` and took
  the state_kind *name* as the answer, so a fresh `absent` reading would have
  been published as army **present**. It had not fired only because four
  readings clear the cap and all four happened to be `present`. Gate G2.10 now
  asserts it cannot recur.

<details><summary>Original plan text</summary>
`checkpoint_settlers` 0 known, `police` 2, `idf` 5. The 2-hour cap makes
presence almost always `unknown`. Two possible truths: the cap is wrong, or
presence is too sparse to be a product feature. Measure the persistence curve
for presence kinds the way it was measured for flow, then either recalibrate or
stop serving presence as a state and keep it only as an attribute of an
incident. **Do not loosen the cap to make the number look better.**
</details>

---

## P2 — The endgoal: a crowd reporting ENGINE

**[ZAID], 2026-08-01, verbatim scope:** *"a system/engine with self improvement
automated system to track crowd reports for all fields that we can track in this
tier"*.

Three commitments follow from that wording, and they are not negotiable details:

1. **An engine, not an endpoint.** One submission and scoring path that every
   field goes through. Not a fuel form plus a checkpoint form.
2. **All fields tier 1 tracks** — checkpoints (flow and presence), fuel, power,
   water, internet, weather, and incidents. A new state kind should become
   crowd-reportable by configuration, not by new code.
3. **Self-improving, automatically.** Reporter reliability, place aliases and
   the confidence model update from measured outcomes on a timer, with no human
   in the loop. Every existing loop in this project already works this way
   (`learn/accuracy.py`, `learn/source_independence.py`,
   `learn/state_persistence.py`); the crowd path joins them rather than being a
   special case.

The engine already has most of its parts, which is why P1.2 must be built
generic over reporters: copy-collapse (`learn/source_independence.py`) is the
defence against one person with five phones, the Beta-Bernoulli posterior from
P1.2 is the reputation model, and the three serving gates already refuse to
assert anything under-evidenced. What is missing is the submission path,
identity, and the abuse asymmetry in P2.4.

**There is already crowd data arriving that nothing reads.** `palhubappfuel` is
a group, not a broadcast channel: 181 messages on 2026-08-01, of which only a
handful were the structured sweep. The rest are people reporting — *"العطاري
فيها بنزين وسولار ازمة خفيفة هسة عبيت"* ("Al-Attari has petrol and diesel, light
crisis, just filled up"), *"وين في سولار في رام الله او بيتونيا"*. It is already
in bronze and currently parsed away. Start the crowd path by reading what is
already there rather than from an empty table — it also gives P2.5 a backtest
corpus that exists before the first real submitter does.

"Crowdbot by crowd for crowd" is the point of the project and none of it exists.
`source.kind='crowd'` is a valid enum value with zero rows.

The hard part is not the endpoint, it is that **a crowd report must not count as
an independent corroboration group per person**. Copy-collapse already showed
that nine channels agreeing at 99.5% are one observer; a crowd is the same
problem with an adversary instead of a copy-paste bot. One motivated person with
five phones would look exactly like five independent confirmations, and the
confidence model would believe them.

### Status 2026-08-01: the engine is BUILT and live. P2.5 is not done.

`crowd/engine.py` + `resolve/belief.py` + migration 030. 13 of the 14 fields are
crowd-reportable **by configuration** — `UPDATE state_kind_config`, no code —
and weather is the one exclusion, on the grounds that Open-Meteo is a better
observer than a person at a window.

What closed, and the one thing that has not:

| | |
|:--|:--|
| P2.1 submission path | **done** — `POST /v2/crowd/report`, one path for every field. MCP tool not yet wired |
| P2.2 identity + rate limiting | **done** — handle + hashed token, `crowd_max_per_hour` per place |
| P2.3 earned reputation | **done** — Loop A already generic over reporters; `learn/crowd_independence.py` grants and revokes independence units |
| P2.4 abuse gate | **done, default proposed — [ZAID] to confirm the policy** |
| P2.5 backtest before affecting served values | **NOT DONE.** There are no crowd reports to backtest yet |

**The one thing to know about P2.5:** the plan said the crowd path must be
backtested before it is allowed to affect served values. It currently *can*
affect them, and the reason that is not reckless is that an unverified submitter
is arithmetically incapable of moving anything — 0.85 × 0.20 = **0.17**, below
every confidence floor (0.25–0.35). The crowd can today only *corroborate* what
somebody else already reported. The backtest becomes both possible and necessary
at the moment the first submitter earns their own unit, and until then there is
nothing to measure.

### The defence, and why it is arithmetic rather than detection

The plan named the hard part: a crowd report must not count as an independent
corroboration group per person, or one motivated person with five phones looks
like five confirmations. The answer is the mirror of the rule this project
already applies to reputation:

> Reputation is earned, never seeded. **So is independence.**

Every submitter starts in one shared group, `crowd:unverified`, where *any
number of accounts count as one observer*. A ring of fifty gets the weight of
one anonymous stranger. Nothing detects sock puppets — they simply never had the
standing, and there is no detector to evade. Genuine newcomers are throttled the
same way, which is over-conservative and is the correct direction to be wrong in.

Separation is then earned on the evidence copy-collapse already uses for
channels, pointed the other way: `learn/source_independence.py` asks "do these
two agree so often they are one observer?" and merges; `learn/crowd_independence.py`
asks the same of a submitter against the shared unit and **splits** them out —
and merges them back if they later drift into lockstep. An attacker earns five
units only by running five accounts that genuinely disagree over hundreds of
observations, which is to say by being five people. The cost scales with the
thing being faked.

### P2.4 — the proposed policy. **[ZAID] decides; this is the default running now.**

Being wrong is not symmetric. A false "closed" costs a detour. A false "open"
sends a family toward a checkpoint that is shut. A false "no diesel" costs a
detour; a false "has diesel" spends a tank that could not be spared during a
shortage.

So **the reassuring values are the guarded ones** — `open`, `available`,
`absent` ("no army here"). A crowd report may:

* always **corroborate** a reassuring value somebody else reported,
* always **raise a caution** alone,
* never be the **sole author** of reassurance — that needs `crowd_min_units`
  (default 2) independent units, or one witness who is not the crowd.

Two unverified submitters do **not** satisfy it, because they are one unit. That
is the sock-puppet defence and the asymmetry meeting, and it is the case an
attacker would actually try.

The gate is applied when belief is **computed**, not at the door, so a report
that was alone at 14:02 starts counting the moment a second witness arrives at
14:09 — with no record of what anybody said ever being edited.

- **P2.1** Submission path (MCP tool + HTTP), writing to `claim` with
  `kind='crowd'` — the same immutable layer as everything else.
- **P2.2** Identity and rate limiting: one submitter is one independence unit
  regardless of volume, with a per-submitter cap per place per hour.
- **P2.3** Reputation via the same Beta-Bernoulli machinery as P1.2 — a
  submitter whose reports are contradicted by independent sources loses weight.
  Reputation must be *earned*, starting near zero, never seeded.
- **P2.4** Abuse gate: crowd reports may raise confidence in something already
  reported, but a lone unverified crowd report must not by itself flip a
  checkpoint to `closed`. State the asymmetry explicitly — the harm of a false
  "closed" is a wasted journey; the harm of a false "open" is worse.
- **P2.5** Backtest the crowd path against the same precision harness before it
  is allowed to affect served values at all.

**[ZAID]** — P2.4's policy is a judgement about your family's safety, not a
technical default. I will propose, you decide.

---

## P3 — Operability. DONE 2026-08-01.

The premise was demonstrated live, twenty minutes into the work. While measuring
per-source cadence to build the watchdog, the Telegram poller turned out to have
been **dead for eight hours** — disconnected at 08:35 by a network blip that
exhausted Telethon's retries, then looping against a dead client ever since.
systemd reported `active (running)`. `/health` returned `{"status":"ok"}`. The
news classifier ran every five minutes and logged a clean run. The entire news
vertical was dark and every indicator was green.

Nothing in P3 was hypothetical after that.

- **P3.1 Alerting — done.** `ops/watchdog.py`, every 10 minutes, 24 checks in
  four families: jobs (heartbeat liveness), capacity, dependencies (the v1
  files), feeds (data freshness against measured cadence). `OnFailure=` is now
  on all twelve units, not just the two backup ones. Alarms de-duplicate, and
  conditions auto-close when they clear so the list does not stay permanently
  red. `ops_heartbeat` (migration 028) is the load-bearing idea: a job records
  success on **every** cycle including empty ones, because "the collector died"
  and "the sources are quiet" are otherwise the same evidence — no new rows —
  and only one of them is a fault.
- **P3.2 Extend `/health` — done.** Every vertical, its age, its threshold and
  whether it is inside it, plus all ten jobs. It calls the same `job_checks()`
  and `feed_checks()` the alarm path uses, so a red status page and a silent
  watchdog cannot disagree. The 21-day cadence scan is read from `feed_cadence`
  (migration 029) rather than recomputed: 570ms → 140ms.
- **P3.3 The v1 dependency — accepted and monitored, as recommended.** Watched
  directly by file mtime rather than only through the downstream symptom, so an
  alarm names v1 instead of reporting "checkpoints look quiet". **Measuring it
  found a trap:** the SQLite is in WAL mode, so `checkpoints.db` was 40 minutes
  stale while `checkpoints.db-wal` was 24 seconds old and v1 was perfectly
  healthy. Judging the `.db` alone would have raised a confident alarm about a
  working system within the hour.
- **P3.4 Bronze growth — measured; the plan's premise was wrong.** Not 14 MB of
  content: **3,945 files holding 1.3 MB, occupying 22 MB on disk.** The average
  payload is ~330 bytes in a 4 KB block, so the archive costs 17x its content in
  filesystem slack, and compressing individual files cannot help — a compressed
  330-byte file still takes one block. The lever is *archiving many into one*:
  the whole of bronze tars to 0.77 MB, 28x smaller, 3,945 inodes down to 1.
  **Decision: not yet.** At ~8 MB and ~2,000 inodes per day there are decades of
  headroom (250 GB and 29M inodes free), and `bronze.get()` resolves
  `claim.raw_ref` straight to a path — putting an archive in front of the
  immutable raw layer is a change that must be right, not quick. What was
  actually missing was a trigger, so **disk capacity is now watched** instead,
  which is worth more anyway: a full filesystem stops Postgres, the backups and
  every collector at the same moment, and nothing was looking at it.

### What P3 turned up on the way

- **The poller could lose data on recovery, and nearly did.** `get_messages`
  returns the *newest* 100 above the cursor; the caller then advanced the cursor
  to the newest id it saw. The 8-hour outage recovered 80 messages on the
  busiest channel against a page size of 100. **Twenty more and the difference
  would have been skipped permanently**, with the system appearing to have fully
  recovered. Now pages oldest-first (`reverse=True`) so the cursor only ever
  advances across a contiguous run — direction is what makes an interrupted
  catch-up safe rather than silently lossy.
- **`ingest-external.sh` could not fail.** Six feeds each ended `|| echo "x
  failed"` and the script ended `exit 0`, so all six could be dead while systemd
  recorded success and `OnFailure=` could never fire. Failures are now counted,
  named, and re-raised.
- **The unit files were not backed up.** Twelve units and eight drop-ins existed
  only in `/etc`, on the same disk the backups exist to survive losing. A
  restore would have returned every row and had nothing to collect the next one.
  Copied to `ops/systemd/` with install and drift-check instructions.
- **A watchdog exits 1 when it finds a fault**, which systemd cannot distinguish
  from the watchdog itself failing — that would raise a second alarm about the
  alarm. Fixed with `SuccessExitStatus=0 1`.

---

## P4 — Being able to see it

Everything is API + MCP. There is no way to look at the data, and you have asked
for this twice.

- **P4.1** A read-only status page: current state per vertical, coverage,
  freshness, and the blind spots stated rather than implied.
- **P4.2** Export (CSV/GeoJSON) for checkpoints, incidents and fuel.
- **P4.3** Daily rollup snapshots for archive and trend, written once and never
  mutated.

**[ZAID]** — is this a phone-first page for family, or an operator dashboard for
you? They are different builds and the answer changes P4.1 entirely.

---

## Explicitly out of scope — documented dead ends

Not gaps to be closed; findings, so nobody re-investigates them.

- **Unannounced power outages.** No source exists in any form. The nearest proxy
  is connectivity, already built.
- **King Hussein Bridge / crossings.** No live feed on any platform probed.
- **HEPCO (Hebron) electricity.** Notices are scanned JPGs; needs Arabic OCR for
  a worse result than NEDCO already gives.
- **OpenSky aircraft.** Measured twice: 100% civil traffic. ADS-B is a
  cooperative civil system; military aircraft do not broadcast on it.
- **Telegram weather channels.** Superseded by Open-Meteo, which is structured,
  keyless and covers every governorate.

---

## Suggested order

P0 → P1.1 → P1.2 → P3.1/P3.2 → P1.3 → P2 → P4

P0 first because it is the only item where delay risks something unrecoverable.
P1.1 next because it is cheap and tells you whether the incident vertical can be
trusted before anything is built on top of it. P2 is the endgoal but depends on
P1.2's reliability machinery, and shipping it before P0 and P1 would mean
inviting people to contribute to a system that cannot survive a disk failure and
cannot say how accurate it is.

**Tier 2 (databank, 36 unchecked plan items) should not start until Gate T1
passes.** It is a much larger body of work and it will compete for the same
attention; tier 1 half-finished and unmonitored will quietly rot while it
proceeds.
