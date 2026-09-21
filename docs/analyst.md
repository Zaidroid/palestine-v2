# analyst.md — THE LOCAL ANALYST, P0

Design: `~/lifeos-kernel/docs/LOCAL-ANALYST-2026-09.md`. This file is what was
built of it, how to run it, and the four hooks organs B–G attach to. Built
2026-09-19.

## What P0 is

Organ A (language, deterministic), the skeleton every later organ plugs into,
and a success-rate alarm retrofitted to v1's dead MiniMax path.

**DONE WHEN** `lang` is real on every claim, and a dashboard line shows analyst
health. Both hold: 99,412 claims re-measured (`ar` 68,767 → the truth was
`ar` 68,768 · `und` 30,484 · `en` 160 · `he` 1), and `analyst` is a row in
`ops_heartbeat`, on `ops/watchdog.py`'s board and in `/health`'s `checks.jobs`.

## Where it sits

A consumer of `claim`, not a collector. `palestine-v2-analyst.service` runs one
worker that ticks every 60 s: for each organ, read its watermark, take the next
200 claims past it, ask the organ about each, write a provenance row for every
claim it actually read, advance the watermark, commit, beat.

    .venv/bin/python -m analyst.loop                  # the service
    .venv/bin/python -m analyst.loop --once --json    # one tick, readable
    .venv/bin/python -m analyst.backfill_lang --dry-run

| file | what it is |
|---|---|
| `analyst/lang.py` | organ A's detector: lingua over {ar, he, en}, noise stripped first, `und` when nothing decides |
| `analyst/organs.py` | the organ contract (`name`, `version`, `needs_model`, `read`) and the registry |
| `analyst/store.py` | the cursor, the provenance row, the metrics — all the SQL |
| `analyst/backpressure.py` | is the PC free to think (`/running` on llama-swap) |
| `analyst/loop.py` | the schedule, the pause, the heartbeat |
| `analyst/backfill_lang.py` | the one-time corrective pass, batched and resumable |
| `db/migrations/068_analyst.sql` | `analyst_watermark`, `analyst_run`, `analyst_health`, `analyst_backlog` |
| `ops/minimax_alarm.py` | v1's MiniMax success rate, measured from outside the container |
| `ops/patches/v1-minimax-*.patch` | the counter, and the switch to the brain's gateway — Zaid's hand |

## The rules this component keeps

1. **It writes only proposals and provenance.** `claim.lang` +
   `attrs.lang_detector` today; `claim_classification` under
   `classifier='analyst-<organ>'` and quarantined `state_observation` rows
   later. Never `event`, `state_current`, `observation`, never the belief
   engine.
2. **Ingestion never waits for it.** The PC is a games machine that also
   thinks. A refused port is the system working; the organ is skipped, the
   reason is in the heartbeat, the watermark does not move.
3. **A rate over an empty denominator is NULL.** `analyst_health` says nothing
   rather than 1.0 about work nobody has done.
4. **A provenance row per reading, not a log line.** MiniMax failed 29,686
   times out of 29,687 and said so, truthfully, every time, in a log. It was
   invisible for three months because success had no denominator anywhere.

## Organ A, and why it may write to an immutable table

`claim` is immutable because it records what a source SAID (005). `lang` was
the literal `'ar'` in all three INSERT statements — including the one that
writes English MoH bulletins and the one that writes RSS. No source ever said
it; it was a constant wearing a measurement's name.

So it is measured now, at two places, and the second is the reason the first
can be trusted:

* **at ingest** — the poller, the RSS reader and the crowd door call
  `analyst.lang.detect_quietly()`. No detector → the claim is written with a
  NULL `lang`, never a guess, and the collector keeps collecting.
* **in the loop** — organ A reads exactly the claims that carry no
  `attrs.lang_detector` stamp. On a healthy system that is the empty set. It is
  the safety net: a new writer that forgets, a run where the library was
  missing, a row written before any of this existed. The insert sites can be
  changed by someone who has never read this file and the corpus stays true.

The stamp is also the idempotence key, which is what makes the backfill
resumable by simply being re-run.

## The health line

`analyst` beats once per tick into `ops_heartbeat` with the numbers, exactly
like the pollers, so three surfaces that already exist render it:

    .venv/bin/python -m ops.watchdog | grep analyst
    curl -s localhost:7870/health | jq '.checks.jobs[] | select(.name=="analyst")'
    psql -c "SELECT * FROM analyst_health"     -- per organ, last hour
    psql -c "SELECT * FROM analyst_backlog"    -- how far behind each organ is

`EXPECTED_JOBS["analyst"] = (60, 900)` in `ops/watchdog.py`, so a loop that
stops beating is `not_running` within sixteen minutes and alarms like anything
else. The detail carries `processed`, `errors`, `per_minute`, `backlog` per
organ, `organs_paused`, the PC's answer, and the three rates B–G will fill
(`success_rate_1h`, `json_valid_rate_1h`, `vote_agreement_1h` — None until
there is a denominator).

## How organs B–G attach

An organ is four things. Nothing else in the loop changes.

```python
class MoHBulletins:                       # organ C
    name = "moh"                          # its watermark and analyst_run.organ
    version = "c/1"                       # bump when the answer could change
    needs_model = True                    # -> the backpressure probe gates it

    def read(self, cur, claim) -> Reading | None:
        ...                               # None = nothing to say about this claim
        return Reading(verdict="believed", model="qwen3.6-35b-a3b",
                       prompt_version="c/1", votes=[...], agreed=True,
                       json_valid=True, latency_ms=ms, raw={...})
```

Register it in `analyst.organs.ORGANS` and it gets a watermark, a heartbeat
number, a health row and the gaming pause for free. What it must bring itself,
per §2 and §5 of the design:

* a JSON schema generated from the DB enums, `strict: true` — `json_valid` is
  the metric that proves the grammar is on;
* candidate `place_id`s from `resolve/geo.py`, never place text — the model
  picks an offered id or `null`, and coordinates never come from a model;
* three samples plus a verifier → `votes` and `agreed`; disagreement caps
  confidence at 0.5;
* a gold set of ≥200 scored claims and the §5 gate before anything it writes
  leaves shadow. Below the gate its `claim_classification` rows exist and do
  not feed events.

`LanguageOrgan` sets `votes`, `agreed` and `json_valid` to **None**, not False:
a deterministic organ has nothing to vote on, and `False` would report perfect
disagreement on every row it touches — a number §5's gate would then read.

## v1's MiniMax

`ops/minimax_alarm.py` measures the success rate of v1's `complete_json` from
outside the container: fallback lines in the container journal (both streams —
the client logs through `logging`, which writes to stderr, and reading stdout
alone reported a healthy zero failures over a path failing every call), new
`llm_cache` rows as successes, and `GET /quality/checkpoints` for context. It
is `minimax_check()` on the watchdog board, raised and resolved by the same
alarm reconciliation as everything else. `MINIMAX_CHECK=0` leaves it out on a
box where v1 does not run.

Measured 2026-09-19: **0 of 161 calls succeeded in one hour**, every failure
`'NoneType' object is not subscriptable` — a 200 carrying a quota body with no
`choices`. The two patches under `ops/patches/` put a real counter inside the
client and make the base URL point at the brain's gateway instead; both are
Zaid's to apply, with the commands in their headers. Neither has been applied.

## Known and not done

* The 68,668 never-classified claims are organ B's, which is P1.
* `analyst_run` is a plain table, not a hypertable. Organ B will add ~70k rows
  in its backfill; revisit if it passes a few million.
* The insert-site detection only takes effect for the poller after
  `palestine-v2-poller.service` is restarted — it is a long-running process
  holding the old module. Until then organ A corrects its rows on the next
  tick, which is the safety net doing exactly its job.
* This repo has no `requirements.txt` (the README's install line names one that
  does not exist). The new dependency is pinned here instead:
  **`lingua-language-detector==2.2.0`**, installed into `.venv` 2026-09-19.
