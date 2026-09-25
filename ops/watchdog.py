"""P3.1 — notice when something has stopped, before a human would.

    .venv/bin/python -m ops.watchdog             # check; alarm on faults
    .venv/bin/python -m ops.watchdog --dry-run   # check; never alarm
    .venv/bin/python -m ops.watchdog --json

Exit 0 when everything is within its own expected cadence, 3 when it FOUND
something that is not, 1 when the watchdog itself could not finish. Faults are
recorded through ops/alert.py, de-duplicated so a fault that persists for a
week produces one alarm rather than two thousand.

WHY "FOUND A FAULT" IS NOT EXIT 1
It was, and 1 is also what Python exits with on any uncaught exception. The
unit said SuccessExitStatus=0 1 and the heartbeat wrapper said OK_EXIT_CODES=1
— both correct for "ran and found a fault", and both therefore recorded a
watchdog that CRASHED as a watchdog that ran fine. A Postgres restart that
makes job_checks() raise, a /status body that is a JSON array: a traceback,
exit 1, a success beat, no alarm raised or resolved, every family only the
watchdog judges unwatched — and nothing anywhere saying so, which is the
nine-day shape of 2026-08-08..17 with the torn line replaced by any other
exception. A fault found is now 3; a crash is 1 and nothing maps it to success.

WHAT PROMPTED THIS, AND WHAT IT MEANS
On 2026-08-01 the Telegram poller lost its connection at 08:35 and ran for
EIGHT HOURS as `active (running)` with a dead transport. systemd was satisfied.
The news classifier ran every five minutes and reported "read 0 unclassified
claims", which is also what a quiet news day looks like. Every signal available
said healthy, and the entire news vertical was dark. It was found by hand, by
accident, while writing this file.

The lesson is not "add monitoring". It is that a system built from jobs that
each report their own success cannot detect a job that is no longer reporting.
Absence of evidence arrives as silence, and silence is indistinguishable from
peace. Something has to be looking for the silence itself.

TWO KINDS OF CHECK, BECAUSE THERE ARE TWO KINDS OF WRONG

  jobs   Is the collector alive? Answered from ops_heartbeat, which the jobs
         write on every successful cycle including empty ones. This is the
         only signal that disappears exactly when a collector dies, so it is
         the only one that can distinguish a dead poller from a quiet feed.

  feeds  Is the collector alive AND producing nothing it should be producing?
         Answered from the data, against a cadence measured from the feed's
         own history rather than a number somebody chose.

A feed is only reported as silent when its collector's heartbeat is healthy.
Otherwise a single dead poller would raise one alarm per downstream vertical —
ten alarms for one fault, which is how an alerting channel teaches people to
ignore it.

WHY THE BASELINE EXCLUDES THE RECENT WINDOW
Thresholds learned from history have a specific failure mode: a feed that
degrades slowly drags its own threshold down with it and never trips. So the
cadence is measured over BASELINE_DAYS ending JUDGE_HOURS ago, and the last
JUDGE_HOURS are judged against it. The period under test never contributes to
the standard it is tested against — the same held-out discipline the precision
measurements use, for the same reason.

WHAT IS DELIBERATELY NOT WATCHED
A feed whose arrivals are too irregular to have a meaningful "late" is listed
as UNWATCHED and never alarms. Percentiles over a handful of observations
describe the handful, not the feed. Listing them is the point: an unwatched
feed that is silently skipped reads, on a status page, exactly like a healthy
one — which is the failure this whole file exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg                                          # noqa: E402
from psycopg.rows import dict_row                       # noqa: E402

from ops.alert import (delivery_health, open_alerts,    # noqa: E402
                       raise_alert, redeliver_undelivered, resolve)
from resolve.db import dsn, env_value                   # noqa: E402

# Cadence is measured over three weeks ending six hours ago; the last six hours
# are what gets judged. Long enough that a weekly rhythm is visible, short
# enough that a feed's cadence changing for real is picked up within days.
BASELINE_DAYS = 21
JUDGE_HOURS = 6

# A feed needs this many distinct arrival minutes in the baseline before a
# percentile over its gaps means anything. Below it, the feed is UNWATCHED and
# said to be so.
MIN_ARRIVALS = 60

# How late is late. p99 of the feed's own gaps is by construction exceeded ~1%
# of the time while healthy; the multiplier buys the margin that turns "unusual"
# into "wrong". Tuned so today's live verticals sit far inside it — a watchdog
# whose first act is to cry wolf is a watchdog that gets switched off.
LATE_MULTIPLE = 3.0

# A threshold derived honestly can still be useless. checkpoint_settlers is
# reported so irregularly that its own p99 puts the deadline at 9.7 DAYS: the
# check is real, it is measured, and it would take a week and a half to notice
# the feed had died. Reporting that as a plain `ok` claims an assurance that
# does not exist. Past this ceiling the check is labelled for what it is —
# still not a fault, because there is nothing wrong, but not evidence of health
# either. The distinction between "we checked" and "we would have noticed" is
# the whole subject of this file.
WEAK_THRESHOLD_SECONDS = 48 * 3600

# THE HOLE THIS CLOSES, found the hard way on 2026-08-02.
#
# `collector_only` was supposed to mean "too irregular to judge by cadence, so
# we watch the collector instead". In practice it meant NOT WATCHED AT ALL,
# because a collector that runs fine and finds nothing is indistinguishable
# from a healthy one. The fuel vertical — the flagship, the thing a family most
# needs — sat dark for 23 hours reading `collector_only ... ok` the entire time.
# Its upstream had stopped publishing and nothing said so.
#
# That is exactly the failure P3.1 exists to prevent, inside the one category
# P3.1 exempted from itself. "We cannot judge its rhythm" was allowed to become
# "it can never be late", and those are not the same statement.
#
# So an unwatchable feed still gets a ceiling: silence this long, while its
# collector is demonstrably healthy, is a fault whatever the feed's rhythm.
#
# 24 hours is the FLOOR, and it is also the fallback while a feed is too new
# for its own rhythm to mean anything. Above it, the ceiling is measured from
# the feed's own p95 inter-arrival (F-08, CEILING_DAYS below) and the detail
# states which of the two is in force, with the arrival count behind it. A
# chosen number presented as a measured one is how a threshold stops being
# questioned — which is also why the old measured branch, which read a key no
# column ever held, is recorded here as having never fired once.
SILENT_AFTER_SECONDS = 24 * 3600

# F-08 — the silence ceiling for feeds too irregular to judge by a late
# threshold. Measured over a LONGER window than the late-threshold, because the
# question is a different one: not "is it late yet", but "how long may this feed
# legitimately say nothing at all".
CEILING_DAYS = 60
# A ceiling needs FEWER points than a threshold does, and that asymmetry is
# deliberate. A percentile that is somewhat wrong makes a merely quiet feed
# slightly noisier; a late-threshold that is too tight alarms every week on a
# healthy feed. Not zero either: four gaps is not a p95.
MIN_CEILING_ARRIVALS = 30

# Every job that is supposed to report, and the cadence it reports at.
#
# Without this list the watchdog can only check heartbeats that EXIST, and a
# job that stops reporting entirely — or was never wired up — leaves no row to
# find. The absence of a heartbeat then reads as the absence of a problem,
# which is the same mistake at one remove: it is not enough to watch what is
# running, something has to hold the list of what is SUPPOSED to be running.
#
# The numbers duplicate what each job passes to ops/with-heartbeat.sh, and the
# duplication is the point — test_watchdog.py asserts the two agree, so a timer
# whose cadence changes without its watchdog entry fails the tests instead of
# silently drifting.
EXPECTED_JOBS = {
    "telegram-poller":   (30, 900),
    "sync-checkpoints":  (120, 600),
    # `ingest-fuel` and `fuel-images` were RETIRED 2026-09-23 with the fuel
    # availability vertical (migration 070); their heartbeat rows stay in the
    # table with `retired_at` set and are no longer judged.
    "classify-news":     (300, 900),
    "ingest-external":   (900, 1800),
    "watchdog":          (600, 900),
    "crowd-refresh":     (120, 600),
    "ingest-palhub-roads": (300, 900),
    "ingest-gaza":       (3600, 7200),
    "stream":            (10, 300),
    "rollup":            (86400, 10800),
    "measure-accuracy":  (86400, 10800),
    # The accuracy audit of the served surface: daily, and its exit 1 means
    # "ran fine, found criticals" — the same OK_EXIT_CODES contract the
    # watchdog itself uses, so the harness records a working job and the
    # audit's own alert is the single paging path.
    "mcp-audit":         (86400, 10800),
    "learn-checkpoints": (86400, 10800),
    "backup":            (86400, 10800),
    "restore-test":      (604800, 86400),
    "measure-review":    (604800, 86400),
    "maintain":          (604800, 172800),
    "databank":          (86400, 21600),
    "scout":             (604800, 259200),
    # The analyst (P0 of LOCAL-ANALYST-2026-09) is a consumer loop, not a
    # timer: it beats once per tick from inside `analyst.loop`, like the poller,
    # so it has no entry in any *.sh and the cadence is duplicated from
    # analyst/loop.py's INTERVAL/GRACE — tests/test_analyst.py asserts the two
    # agree, the same way test_watchdog does it for the wrapped jobs.
    "analyst":           (60, 900),
    # The Valhalla IP sync (ops/sync-valhalla-ip.sh), every 15 minutes. It is
    # the fixer for the eleven-hour routing outage of 2026-08-07 and it ran
    # unwatched — no heartbeat, no OnFailure — so an API restart that failed
    # after .env was rewritten left routing dead behind a green board.
    "valhalla-ip":       (900, 1800),
}

# ops/watchdog.sh maps this to success for systemd; see the module docstring.
FAULTS_FOUND = 3

# State kinds that are no longer collected. Their observations stay in the
# database; the watchdog stops judging their freshness. Mirrors
# state_kind_config.retired_at (migration 070) — duplicated here so the check
# needs no query, and tests/test_watchdog.py asserts the two agree.
RETIRED_FEEDS = frozenset({"fuel_diesel", "fuel_gasoline", "cooking_gas"})

# Fuel PRICES replaced them (071-073). Monthly, so judged by fuel_price_check.
FUEL_PRICE_GRACE_DAYS = 4

# Which collector's heartbeat covers which state kinds. A feed is only judged
# silent when its collector is demonstrably alive; without this mapping one
# dead poller becomes one alarm per vertical.
FEED_COLLECTOR = {
    "checkpoint_status":     "sync-checkpoints",
    "checkpoint_flow":       "sync-checkpoints",
    "checkpoint_idf":        "sync-checkpoints",
    "checkpoint_police":     "sync-checkpoints",
    "checkpoint_settlers":   "sync-checkpoints",
    "checkpoint_inspection": "sync-checkpoints",
    "road_closure":          "classify-news",
    "weather":               "ingest-external",
    "internet":              "ingest-external",
    # "power", not "electricity" — the mapping held a name no state kind has
    # ever had, so the day power came alive (040) it alarmed as "uncovered"
    # while its collector was green in the same report.
    "power":                 "ingest-external",
    "fire":                  "ingest-external",
}

# P3.3 — the upstream files v2 does not own and cannot restart.
#
# Checkpoints come from a SQLite database written by v1's parser; fuel comes
# from a tee spool written by the same stack. The plan's recommendation was to
# accept the dependency and monitor it explicitly rather than port 2,564 lines
# of tuned Arabic to remove it, and this is that monitoring.
#
# The feed checks would catch a v1 stall eventually — checkpoint_status would
# drift past its 42-minute threshold. But that reports the SYMPTOM: it says the
# checkpoint feed is silent, which is equally consistent with a quiet night on
# the road channels. The file mtime says which, immediately, and points at the
# stack that has to be restarted. An alarm that names the wrong system costs
# more time than one that arrives slightly later.
#
# Thresholds are generous multiples of each file's observed write rhythm — v1
# parses every few seconds, the spool is appended continuously.
DEPENDENCIES = {
    "v1-checkpoints-db": (
        "/opt/stacks/palestine/services/westbank-alerts/data/checkpoints.db",
        3600, "v1's checkpoint parser writes this; checkpoints stop if it does"),
}

# QUARANTINED ROWS ARE NOT ARRIVALS OF THE FEED. palhub writes checkpoint_flow
# every five minutes as `quarantined` (migration 033: collected, never
# believed — 72,763 readings in the week to 2026-09-24 moved nothing served).
# Counting them made the served checkpoint_flow feed read `ok`, age three
# minutes, for as long as palhub kept posting — however long v1's road
# channels, the only source belief counts, had been dark. The rhythm, the
# ceiling and the freshness are all measured on the rows that can reach a
# served answer; `question`/`unparsed` stay in because they are the same
# channels speaking, which is what "is the source alive" asks.
_JUDGED = "modality <> 'quarantined'"

CADENCE_SQL = f"""
WITH arrival AS (
  -- One batch write is one arrival, not six hundred. Without the bucket, gaps
  -- are dominated by microseconds inside a single transaction and every
  -- percentile collapses to zero.
  SELECT state_kind, date_trunc('minute', observed_at) AS t
    FROM state_observation
   WHERE observed_at >  now() - interval '{BASELINE_DAYS} days'
     AND observed_at <= now() - interval '{JUDGE_HOURS} hours'
     AND {_JUDGED}
   GROUP BY 1, 2
), gaps AS (
  SELECT state_kind, t,
         t - lag(t) OVER (PARTITION BY state_kind ORDER BY t) AS gap
    FROM arrival
)
SELECT state_kind,
       count(gap)                                                    AS arrivals,
       extract(epoch FROM percentile_cont(0.50)
               WITHIN GROUP (ORDER BY gap))                          AS p50,
       extract(epoch FROM percentile_cont(0.99)
               WITHIN GROUP (ORDER BY gap))                          AS p99
  FROM gaps
 GROUP BY 1
"""

# F-08 — how long each feed may legitimately say NOTHING. Same minute-bucketed
# arrivals, a longer window, the 95th percentile rather than the 99th: a p99 is
# the right shape for "is it late yet" and the wrong one for "has it stopped",
# because it is dominated by the single worst gap in the window.
CEILING_SQL = f"""
WITH arrival AS (
  SELECT state_kind, date_trunc('minute', observed_at) AS t
    FROM state_observation
   WHERE observed_at > now() - interval '{CEILING_DAYS} days'
     AND {_JUDGED}
   GROUP BY 1, 2
), gaps AS (
  SELECT state_kind, t - lag(t) OVER (PARTITION BY state_kind ORDER BY t) AS gap
    FROM arrival
)
SELECT state_kind,
       count(gap)                                                    AS arrivals,
       extract(epoch FROM percentile_cont(0.95)
               WITHIN GROUP (ORDER BY gap))                          AS p95
  FROM gaps
 GROUP BY 1
"""

# One probe per configured kind rather than `max() GROUP BY` over the whole
# hypertable: Postgres has no loose index scan, so the grouped form read every
# chunk on every /health call, a cost that grows without bound under the
# no-retention rule. Each probe below is an index-ordered LIMIT 1 on
# (state_kind, observed_at DESC) that stops at the newest judged row. Kinds
# with no judged row at all are left out, as the grouped form left them out.
CURRENT_SQL = f"""
SELECT k.state_kind,
       o.latest,
       extract(epoch FROM (now() - o.latest))                        AS age_seconds
  FROM state_kind_config k
  CROSS JOIN LATERAL (
        SELECT max(observed_at) AS latest
          FROM state_observation s
         WHERE s.state_kind = k.state_kind AND s.{_JUDGED}) o
 WHERE o.latest IS NOT NULL
"""

JOB_SQL = "SELECT * FROM ops_heartbeat_status ORDER BY name"


STORE_SQL = """
INSERT INTO feed_cadence (state_kind, arrivals, p50_seconds, p99_seconds,
                          threshold_seconds, watchable, measured_at,
                          baseline_days, judge_hours, p95_seconds,
                          silence_ceiling_seconds, ceiling_basis,
                          ceiling_window_days)
VALUES (%s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s, %s, %s)
ON CONFLICT (state_kind) DO UPDATE SET
  arrivals = EXCLUDED.arrivals, p50_seconds = EXCLUDED.p50_seconds,
  p99_seconds = EXCLUDED.p99_seconds,
  threshold_seconds = EXCLUDED.threshold_seconds,
  watchable = EXCLUDED.watchable, measured_at = now(),
  baseline_days = EXCLUDED.baseline_days, judge_hours = EXCLUDED.judge_hours,
  p95_seconds = EXCLUDED.p95_seconds,
  silence_ceiling_seconds = EXCLUDED.silence_ceiling_seconds,
  ceiling_basis = EXCLUDED.ceiling_basis,
  ceiling_window_days = EXCLUDED.ceiling_window_days
"""

LOAD_SQL = "SELECT * FROM feed_cadence"


def _q(sql: str) -> list[dict]:
    with psycopg.connect(dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def measure_cadence() -> dict[str, dict]:
    """Re-measure every feed's rhythm and record it in feed_cadence.

    Costs ~400ms against 21 days of state_observation, which is why it is done
    here on a 10-minute timer rather than inside /health on every request.
    """
    rows = _q(CADENCE_SQL)
    ceilings = {r["state_kind"]: r for r in _q(CEILING_SQL)}
    out = {}
    with psycopg.connect(dsn()) as conn, conn.cursor() as cur:
        for r in rows:
            arrivals = int(r["arrivals"] or 0)
            p99 = float(r["p99"]) if r["p99"] is not None else None
            watchable = arrivals >= MIN_ARRIVALS and bool(p99)
            threshold = p99 * LATE_MULTIPLE if watchable else None
            c = ceilings.get(r["state_kind"]) or {}
            ceiling, basis = measured_ceiling(c.get("p95"), int(c.get("arrivals") or 0))
            cur.execute(STORE_SQL, (r["state_kind"], arrivals,
                                    r["p50"], p99, threshold, watchable,
                                    BASELINE_DAYS, JUDGE_HOURS,
                                    c.get("p95"), ceiling, basis, CEILING_DAYS))
            out[r["state_kind"]] = {
                "arrivals": arrivals, "p50_seconds": r["p50"],
                "p99_seconds": p99, "threshold_seconds": threshold,
                "watchable": watchable, "p95_seconds": c.get("p95"),
                "silence_ceiling_seconds": ceiling, "ceiling_basis": basis,
                "measured_at": r.get("measured_at"),
            }
        conn.commit()
    return out


def load_cadence() -> dict[str, dict]:
    """Read the recorded cadence. Cheap; used by /health.

    If the watchdog has stopped refreshing this, the `watchdog` job's own
    heartbeat goes stale and alarms — the cache cannot go quietly out of date.
    """
    return {r["state_kind"]: dict(r) for r in _q(LOAD_SQL)}


def job_checks() -> list[dict]:
    """Collector liveness, straight from the heartbeats.

    `not_running` and `failing` are separated because they are different
    problems: one means the scheduler is not firing the job, the other means it
    fires and the job cannot do its work. The view computes the distinction so
    that /health and this agree by construction.
    """
    out, seen = [], set()
    for r in _q(JOB_SQL):
        status = r["status"]
        seen.add(r["name"])
        fault = status in ("failing", "not_running", "never_succeeded")
        detail = r["last_error"] or ""
        # `unmonitored` means the row carries no cadence. For a job on the
        # expected list that is a hole, not a state: a first-ever `--fail`
        # written without --interval (the maintainer's seat-probe path did
        # exactly that) inserts NULL, and from then on the job could fail
        # every week without ever being judged — present, so never
        # `never_reported`, and unmonitored, so never a fault.
        if status == "unmonitored" and r["name"] in EXPECTED_JOBS:
            fault = True
            iv, gr = EXPECTED_JOBS[r["name"]]
            detail = (f"its heartbeat row has no cadence, so nothing judges it "
                      f"(registered at {iv}s + {gr}s grace)"
                      + (f"; last error: {detail}" if detail else ""))
        elif not detail and status in ("failing", "not_running"):
            # No error text is itself information. The wrapper stamps the
            # attempt before the job runs and the outcome after, so an
            # attempt with no outcome is a run that never came back.
            att = r.get("attempt_age_minutes")
            att = f"{float(att):.0f}m ago" if att is not None else "at an unknown time"
            detail = (f"last attempt {att} recorded no outcome — killed before it "
                      f"finished (journal: 'result: timeout'?) or still running"
                      if status == "failing" else
                      f"last attempt {att} — the scheduler is not starting it")
        out.append({
            "check": "job",
            "name": r["name"],
            "status": status,
            "fault": fault,
            "age_minutes": float(r["ok_age_minutes"]) if r["ok_age_minutes"] is not None else None,
            "expected_seconds": r["expected_interval_seconds"],
            "consecutive_failures": r["consecutive_failures"],
            "detail": detail,
        })

    # A job on the expected list with no row at all has never reported once.
    # Either it is not wired to the heartbeat, or it has not run since it was —
    # and both mean it is currently unwatched, which is a fault in its own
    # right rather than a gap to be quietly tolerated.
    for name, (interval, grace) in sorted(EXPECTED_JOBS.items()):
        if name in seen:
            continue
        out.append({
            "check": "job", "name": name, "status": "never_reported",
            "fault": True, "age_minutes": None, "expected_seconds": interval,
            "consecutive_failures": 0,
            "detail": "no heartbeat has ever been recorded for this job",
        })
    return sorted(out, key=lambda r: r["name"])


def measured_ceiling(p95, arrivals: int) -> tuple[float, str]:
    """F-08 — the ceiling a feed is judged against, and where it came from.

    Returned WITH its basis so the caller can say which it is: a chosen number
    reported as a measured one stops being questioned, and this project has been
    bitten by exactly that (0.70 "trust", 0.95 fuel confidence).

    The 24 h default is a FLOOR as well as a fallback, so this can only ever
    make a legitimately irregular feed quieter — never a real outage quieter
    than a day. Below MIN_CEILING_ARRIVALS the honest answer is the default and
    the count that explains why.
    """
    if p95 and arrivals >= MIN_CEILING_ARRIVALS:
        measured = float(p95)
        if measured >= SILENT_AFTER_SECONDS:
            return measured, f"measured p95({CEILING_DAYS}d), n={arrivals}"
        # Measured, but under the floor. Say BOTH, because "default" here would
        # hide a number we actually measured and "measured" would hide that the
        # floor is what is in force.
        return (SILENT_AFTER_SECONDS,
                f"floor 24h: p95({CEILING_DAYS}d) is {measured / 3600:.1f}h, n={arrivals}")
    return (SILENT_AFTER_SECONDS,
            f"default, {arrivals} arrivals in {CEILING_DAYS}d is too few for a p95")


def _silence_ceiling(cad: dict | None) -> tuple[float, str]:
    """How long an unwatchable feed may say nothing before it counts as dead.

    F-08: measured from the feed's OWN p95 inter-arrival and stored in
    `feed_cadence` with the basis and the date it was measured, so the number
    travels with its evidence.

    This used to read `cad["max_gap_seconds"]`, a key no column of `feed_cadence`
    has ever held — `INSERT`/`LOAD` never carried it — so the measured branch
    could not fire and every unwatchable feed sat on the 24 h default. That is
    why `checkpoint_settlers` alarmed on quiet weeks: measured 2026-09-22, its
    own p95 gap is 45.9 h and its longest 8 days, while `power`'s p95 is 6.2
    days and its longest 14.8. Both were being judged against a day.
    """
    if cad and cad.get("silence_ceiling_seconds"):
        ceiling = float(cad["silence_ceiling_seconds"])
        return max(ceiling, SILENT_AFTER_SECONDS), (cad.get("ceiling_basis")
                                                    or "measured")
    return SILENT_AFTER_SECONDS, "default, too little history to measure"


def feed_checks(jobs: list[dict], cadence: dict[str, dict] | None = None) -> list[dict]:
    """Data freshness against each feed's own measured cadence.

    `cadence` defaults to the recorded measurement so callers that only need an
    answer — /health — pay 90ms instead of 500ms. The watchdog passes a freshly
    measured one, because it is the component responsible for the measurement
    being current.
    """
    healthy = {j["name"] for j in jobs if j["status"] == "ok"}
    cadence = load_cadence() if cadence is None else cadence
    current = {r["state_kind"]: r for r in _q(CURRENT_SQL)}
    # A retired state kind is no longer collected, so its silence is the
    # intended state, not an outage (070: fuel availability, 2026-09-23).
    retired = RETIRED_FEEDS

    out = []
    for kind in sorted(set(cadence) | set(current)):
        if kind in retired:
            continue
        cad, cur = cadence.get(kind), current.get(kind)
        age = float(cur["age_seconds"]) if cur and cur["age_seconds"] is not None else None
        collector = FEED_COLLECTOR.get(kind)
        row = {
            "check": "feed",
            "name": kind,
            "collector": collector,
            "age_minutes": round(age / 60, 1) if age is not None else None,
            "arrivals": int(cad["arrivals"]) if cad else 0,
        }

        if not cad or not cad.get("watchable") or not cad.get("threshold_seconds"):
            # Too irregular to judge by its own gaps — fuel arrives in bursts
            # when the channel happens to post, so "late" is not a thing that
            # can be defined for it. That does not mean nothing is watched:
            # the collector still is, and "the collector ran and there was
            # nothing" is the strongest true claim available for such a feed.
            #
            # A feed with NO working collector heartbeat is different. Nothing
            # watches it at all, and that is reported as a FAULT — a hole in
            # the monitoring is itself an outage, and one that would otherwise
            # be invisible for exactly as long as nobody thought to check.
            why = (f"{row['arrivals']} baseline arrivals is too few for a "
                   f"percentile to mean anything")
            if collector and collector in healthy:
                # Unwatchable by rhythm is not unwatchable at all. See
                # SILENT_AFTER_SECONDS: fuel read `collector_only ... ok` for 23
                # hours while its upstream had stopped publishing entirely.
                ceiling, basis = _silence_ceiling(cad)
                if age is not None and age > ceiling:
                    row.update(status="silent", fault=True,
                               threshold_minutes=round(ceiling / 60, 1),
                               detail=f"nothing at all for {age / 3600:.0f}h "
                                      f"(ceiling {ceiling / 3600:.0f}h, {basis}) "
                                      f"while {collector} is healthy — the "
                                      f"upstream has stopped, not the collector")
                else:
                    row.update(status="collector_only", fault=False,
                               threshold_minutes=round(ceiling / 60, 1),
                               detail=f"{why}; covered by {collector}, which is "
                                      f"healthy, plus a {ceiling / 3600:.0f}h "
                                      f"silence ceiling ({basis})")
            else:
                row.update(status="uncovered", fault=True, threshold_minutes=None,
                           detail=f"{why}, and " + (
                               f"its collector {collector} is not healthy"
                               if collector else
                               "no collector is mapped to it in FEED_COLLECTOR"))
            out.append(row)
            continue

        threshold = float(cad["threshold_seconds"])
        row["threshold_minutes"] = round(threshold / 60, 1)
        row["typical_minutes"] = round(float(cad.get("p50_seconds") or 0) / 60, 1)

        if age is None:
            row.update(status="no_data", fault=True, detail="no observations at all")
        elif age <= threshold and threshold > WEAK_THRESHOLD_SECONDS:
            row.update(status="watched_loosely", fault=False,
                       detail=f"within cadence, but the deadline is "
                              f"{threshold / 86400:.1f} days — this feed is too "
                              f"irregular for the check to be worth much")
        elif age <= threshold:
            row.update(status="ok", fault=False, detail="")
        elif collector and collector not in healthy:
            # The collector is already faulting and will already have alarmed.
            # Reporting this too would multiply one fault into many.
            row.update(status="collector_down", fault=False,
                       detail=f"stale, but {collector} is already reported")
        else:
            row.update(status="silent", fault=True,
                       detail=f"{row['age_minutes']:.0f}m since last observation, "
                              f"threshold {row['threshold_minutes']:.0f}m "
                              f"(typical gap {row['typical_minutes']:.0f}m)"
                              + (f"; {collector} is healthy, so the source itself "
                                 f"has gone quiet" if collector else ""))
        out.append(row)
    return out


# P3.4 turned out differently than the plan expected, and the capacity check
# below is what came of it.
#
# The plan recorded bronze as "14 MB today and unbounded by design" and asked
# whether to compress it. Measured: 3,945 files holding 1.3 MB of content and
# occupying 22 MB on disk. The bytes are not the problem and compressing them
# would not help — the average payload is ~330 bytes in a 4 KB block, so the
# archive costs 17x its content in filesystem slack, and a compressed 300-byte
# file still occupies one block. The lever would be ARCHIVING many files into
# one, not compressing each: the whole of bronze tars to 0.77 MB, 28x smaller
# and 3,945 inodes down to one.
#
# It is not worth doing yet. At the observed ~8 MB and ~2,000 inodes per day
# there are decades of headroom on this filesystem, and bronze.get() resolves
# claim.raw_ref straight to a path — putting an archive in front of the
# immutable raw layer is a change that has to be right, not quick. What was
# missing was not compression but a trigger, so the disk is watched instead and
# the decision waits for evidence it is needed.
#
# Watching the disk is worth more than watching bronze in any case: a full
# filesystem stops Postgres, the backups and every collector at the same
# moment, and nothing here was looking at it.
DISK_PATH = str(ROOT)
DISK_FAULT_GB = 10.0     # ~500 nightly backup sets, with the database's growth on top
DISK_WARN_GB = 25.0


def capacity_check() -> list[dict]:
    """Free space on the filesystem holding the database, backups and bronze.

    An absolute floor rather than a percentage: 10% of a 466 GB disk is 46 GB,
    which would alarm with a year of headroom left, and an alarm that fires a
    year early is one that gets muted long before the disk actually fills.
    """
    try:
        st = os.statvfs(DISK_PATH)
    except OSError as exc:
        return [{"check": "capacity", "name": "disk-free", "status": "unreadable",
                 "fault": True, "age_minutes": None, "detail": str(exc)}]
    free_gb = st.f_bavail * st.f_frsize / 1024 ** 3
    row = {"check": "capacity", "name": "disk-free", "age_minutes": None,
           "free_gb": round(free_gb, 1)}
    if free_gb < DISK_FAULT_GB:
        return [{**row, "status": "critical", "fault": True,
                 "detail": f"{free_gb:.1f} GB free — below {DISK_FAULT_GB} GB; "
                           f"Postgres, the backups and every collector fail together"}]
    if free_gb < DISK_WARN_GB:
        return [{**row, "status": "low", "fault": False,
                 "detail": f"{free_gb:.1f} GB free — below the {DISK_WARN_GB} GB "
                           f"warning line, not yet a fault"}]
    return [{**row, "status": "ok", "fault": False,
             "detail": f"{free_gb:.0f} GB free"}]


def routing_check() -> list[dict]:
    """Valhalla, which every corridor and route answer depends on.

    Not a DEPENDENCIES entry because those are judged by file mtime, and a
    routing engine has no file to age. It is checked by asking it who it is.

    THE FAILURE THIS EXISTS FOR IS NOT "VALHALLA IS DOWN". It is that
    `VALHALLA_URL` pointed at `127.0.0.1:8002`, a host port belonging to
    honcho-api-1 — an unrelated application on this machine — which answered
    every routing request with a perfectly well-formed 404. Nothing was down.
    Something was LISTENING, and it was the wrong thing. So a reachability
    check is not enough: the response has to identify itself as Valhalla, or
    the next port collision passes the check while /v2/route returns 503.

    Production escaped this only by accident: the systemd unit sets no
    VALHALLA_URL, so it fell through to the correct default in code while every
    shell that sourced .env got the stranger. That is precisely the kind of
    divergence a monitor is supposed to close.
    """
    # TWO URLS, BECAUSE THERE ARE TWO .env FILES AND ONLY ONE IS HOST-SCOPED.
    # `env_value` prefers the ambient environment over the repo file, which is
    # right for serving and wrong here: v1's /opt .env carries
    # `VALHALLA_URL=http://valhalla:8002`, a name that resolves only inside
    # v1's compose network. Any host run that sources that file (every ingest
    # script does, for the DB credentials) therefore exports a routing address
    # that cannot work from here, and the check reported "unreachable" against
    # a router answering perfectly at 172.22.0.4 — measured 2026-09-23.
    # So: judge the URL the SERVING layer will use, and fall back to the repo's
    # .env when the ambient one cannot answer. Production sets no
    # VALHALLA_URL, so this changes nothing there.
    row = {"check": "dep", "name": "valhalla", "age_minutes": None,
           "threshold_minutes": None}
    primary = env_value("VALHALLA_URL", "http://wb-valhalla:8002")
    from resolve.db import _env as _repo_env
    repo_url = _repo_env().get("VALHALLA_URL")
    candidates = [primary] + ([repo_url] if repo_url and repo_url != primary else [])
    import httpx
    url, r, exc = candidates[0], None, None
    for cand in candidates:
        try:
            r = httpx.get(f"{cand}/status", timeout=10.0)
            url = cand
            break
        except Exception as e:                                  # noqa: BLE001
            exc = e
    if r is None:
        return [{**row, "status": "unreachable", "fault": True,
                 "detail": f"{' and '.join(candidates)}: {type(exc).__name__} — "
                           f"/v2/route and every corridor answer will 503"}]
    if r.status_code != 200:
        return [{**row, "status": "wrong-service", "fault": True,
                 "detail": f"{url}/status returned {r.status_code} — something "
                           f"is listening but it is not Valhalla; check for a "
                           f"port collision before assuming an outage"}]
    try:
        payload = r.json()
    except ValueError:
        payload = None
    # A 200 whose body is JSON but not an object (a list, a bare string) used
    # to raise AttributeError here and take the whole watchdog run down with
    # it. It is a different application answering, which is what this says.
    version = payload.get("version") if isinstance(payload, dict) else None
    if not version:
        return [{**row, "status": "wrong-service", "fault": True,
                 "detail": f"{url}/status answered 200 but names no valhalla "
                           f"version — this is a different application"}]
    return [{**row, "status": "ok", "fault": False,
             "detail": f"valhalla {version}"}]


def dependency_checks() -> list[dict]:
    """P3.3 — the upstream files v2 reads but does not control.

    A directory is judged by its newest file, because the spool rolls daily and
    yesterday's file stops changing the moment today's is created.
    """
    out = []
    for name, (path, max_age, why) in sorted(DEPENDENCIES.items()):
        p = Path(path)
        row = {"check": "dep", "name": name, "age_minutes": None,
               "threshold_minutes": round(max_age / 60, 1)}
        try:
            if p.is_dir():
                candidates = [f for f in p.iterdir() if f.is_file()]
            else:
                # SQLite in WAL mode does NOT touch the database file on write —
                # it appends to `<name>-wal` and only folds that back in at a
                # checkpoint. Measured here: checkpoints.db was 40 minutes stale
                # while checkpoints.db-wal was 24 seconds old and v1 was writing
                # normally. Judging the .db alone would have raised "v1 has
                # stopped" within the hour, against a perfectly healthy v1, and
                # sent whoever read it to restart the wrong stack.
                candidates = [f for f in (p, p.with_name(p.name + "-wal"))
                              if f.exists()]
            mtime = max((f.stat().st_mtime for f in candidates), default=None)
        except OSError as exc:
            out.append({**row, "status": "unreadable", "fault": True,
                        "detail": f"{path}: {exc}"})
            continue

        if mtime is None:
            out.append({**row, "status": "missing", "fault": True,
                        "detail": f"{path} does not exist — {why}"})
            continue

        age = time.time() - mtime
        row["age_minutes"] = round(age / 60, 1)
        if age > max_age:
            out.append({**row, "status": "stale", "fault": True,
                        "detail": f"not written in {age / 60:.0f}m "
                                  f"(limit {max_age / 60:.0f}m) — {why}"})
        else:
            out.append({**row, "status": "ok", "fault": False, "detail": ""})
    return out


def minimax_check() -> list[dict]:
    """v1's MiniMax path, which had no success metric and no watchdog at all.

    It belongs with the dependency checks rather than the jobs: it is a thing
    v2 reads and does not control, like v1's checkpoint database. The measuring
    lives in ops/minimax_alarm.py, which is also a CLI; here it is one more row
    on the same board, raised and resolved by the same alarm reconciliation as
    everything else, so it cannot become a second monitoring system with its
    own silence.

    `safe_check` cannot raise: a bug in a check that was added to notice a
    three-month outage must not be able to stop the watchdog that notices
    everything else. Set MINIMAX_CHECK=0 to leave it out entirely — for a box
    where v1 does not run.
    """
    if os.environ.get("MINIMAX_CHECK", "1") == "0":
        return []
    from ops.minimax_alarm import safe_check
    rows = safe_check()
    # `measure` carries the raw evidence and is useful from --json; it is not
    # part of the row shape the printer and the alarm path expect.
    return [{k: v for k, v in r.items() if k != "measure"} for r in rows]


def fuel_price_check() -> list[dict]:
    """Fuel prices (071-073) are monthly, so feed cadence cannot judge them.

    The question is: has this month's official list been confirmed? The
    Corporation publishes on the last evening of the month before, and outlets
    carry it within hours, so three days into a month with no confirmed list
    means the reader or the outlets have failed, not that the list is late.
    Before the 4th it is `awaiting`, not a fault.
    """
    try:
        rows = _q("""SELECT count(*) FILTER (WHERE status = 'confirmed')     AS confirmed,
                            count(*) FILTER (WHERE status = 'conflicting')   AS conflicting,
                            count(*)                                         AS products,
                            max(newest_list)                                 AS newest,
                            extract(day FROM (now() AT TIME ZONE 'Asia/Hebron'))::int AS day
                       FROM fuel_price_current""")
    except Exception as e:                                  # noqa: BLE001
        return [{"check": "dep", "name": "fuel-prices", "status": "unreadable",
                 "age_minutes": None, "fault": True, "detail": f"query failed: {e}"}]
    r = rows[0]
    detail = (f"{r['confirmed']}/{r['products']} products confirmed this month, "
              f"newest list {r['newest']}")
    if r["conflicting"]:
        detail += f", {r['conflicting']} conflicting"
    if r["confirmed"] == 0 and r["day"] >= FUEL_PRICE_GRACE_DAYS:
        status, fault = "no_list", True
        detail = f"day {r['day']} of the month and no confirmed list — {detail}"
    elif r["confirmed"] == 0:
        status, fault = "awaiting", False
    elif r["conflicting"]:
        status, fault = "conflicting", True
    else:
        status, fault = "ok", False
    return [{"check": "dep", "name": "fuel-prices", "status": status,
             "age_minutes": None, "fault": fault, "detail": detail}]


def doorbell_check() -> list[dict]:
    """F286 — is anybody hearing the alarms this board raises?

    The only proof the channel worked was a `--test` run by hand. A rotated
    ntfy token answers 403 to every push, the ledger records `delivered:
    false` once per alarm, and the board stays exactly as green as it was.
    Judged from the delivery receipts the alarms already leave behind.
    """
    row = {"check": "dep", "name": "doorbell", "age_minutes": None,
           "threshold_minutes": None}
    try:
        h = delivery_health()
    except Exception as exc:                                    # noqa: BLE001
        return [{**row, "status": "unreadable", "fault": True,
                 "detail": f"the alarm ledger cannot be read: {exc}"}]
    last = h.get("last") or {}
    if not h["ok"]:
        return [{**row, "status": "failing", "fault": True,
                 "detail": f"the last {h['checked']} alarm deliveries all failed "
                           f"({'; '.join(h.get('reasons') or [])[:160]}) — alarms "
                           f"are recorded in ops/alerts.ndjson and reach nobody; "
                           f"fix the channel, then `python -m ops.alert --test`"}]
    if not last:
        return [{**row, "status": "unproven", "fault": False,
                 "detail": "no delivery on record yet"}]
    return [{**row, "status": "ok", "fault": False,
             "detail": f"last delivery {'ok' if last.get('delivered') else 'failed'} "
                       f"via {last.get('channel', '?')} at {str(last.get('ts', ''))[:16]}"}]


def _already_open(key: str) -> bool:
    return any(r.get("unit") == key for r in open_alerts())


def _key(r: dict) -> str:
    return f"watchdog:{r['check']}:{r['name']}"


def reconcile(rows: list[dict]) -> None:
    """Raise what is newly faulting, close what has recovered, re-send what
    was never heard."""
    faults = [r for r in rows if r["fault"]]
    faulting = {_key(r) for r in faults}
    for key in sorted(faulting):
        if not _already_open(key):
            r = next(x for x in faults if _key(x) == key)
            raise_alert(key, f"{r['status']} — {r['detail']}")
    # F285 — `collector_down` is NOT a recovery. It is a stale feed that is not
    # reported separately because its collector's own alarm covers it. It used
    # to fall into the loop below and close an open feed alarm with "check
    # returned to within cadence" and a 🟢 push while the feed was exactly as
    # silent as before — then re-raise it the moment the collector healed. A
    # held alarm stays open, and says nothing new, until the feed itself moves.
    held = {_key(r) for r in rows if r.get("status") == "collector_down"}
    # Everything this watchdog raised that is now green gets closed. These
    # are conditions, not events: see ops.alert.resolve for why leaving
    # them red is worse than closing them. Once per key, however many open
    # records it has.
    for unit in sorted({r.get("unit", "") for r in open_alerts()}):
        if unit.startswith("watchdog:") and unit not in faulting and unit not in held:
            resolve(unit, "check returned to within cadence")
            print(f"resolved {unit}")
    for d in redeliver_undelivered():
        print(f"re-sent {d['delivery_of']}: "
              f"{'delivered' if d['delivered'] else 'FAILED ' + d.get('reason', '')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="check every job and feed")
    ap.add_argument("--dry-run", action="store_true", help="report, never alarm")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        return _run(a)
    except Exception:                                           # noqa: BLE001
        # A crash is not a finding. Print the traceback where the report would
        # have been and exit 1, which neither the unit nor the heartbeat
        # wrapper accepts as success any more — so OnFailure fires and the
        # `watchdog` row goes `failing` instead of beating green over a run
        # that checked nothing.
        traceback.print_exc()
        print("\nwatchdog did NOT finish: nothing above was raised, resolved or "
              "re-sent this run", file=sys.stderr)
        return 1


def _run(a: argparse.Namespace) -> int:
    jobs = job_checks()
    # The watchdog re-measures; /health reads what the watchdog recorded.
    feeds = feed_checks(jobs, measure_cadence())
    rows = (jobs + capacity_check() + dependency_checks() + routing_check()
            + minimax_check() + fuel_price_check() + doorbell_check() + feeds)
    faults = [r for r in rows if r["fault"]]

    if a.json:
        print(json.dumps({"faults": len(faults), "checks": rows},
                         indent=2, ensure_ascii=False, default=str))
    else:
        print(f"{'':<4}{'name':<24}{'status':<16}{'age':>9}  detail")
        for r in rows:
            age = f"{r['age_minutes']:.0f}m" if r.get("age_minutes") is not None else "-"
            mark = "!!" if r["fault"] else ("  " if r["status"] in ("ok", "unwatched") else " ~")
            print(f"{mark:<4}{r['name']:<24}{r['status']:<16}{age:>9}  {r['detail'][:70]}")

    if not a.dry_run:
        reconcile(rows)

    if faults:
        print(f"\n{len(faults)} fault(s)", file=sys.stderr)
        return FAULTS_FOUND
    print(f"\nall {len(rows)} checks within cadence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
