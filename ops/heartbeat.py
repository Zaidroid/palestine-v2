"""Record that a job ran, and whether it worked. The positive half of P3.1.

From Python:

    from ops.heartbeat import beat, fail
    beat("poller", interval=30, grace=300, detail={"claims": n})
    fail("poller", "could not reconnect")

From a shell script, which is how the timers use it:

    .venv/bin/python -m ops.heartbeat ingest-fuel --interval 300 --grace 600 \
        --detail '{"rows": 42}'
    .venv/bin/python -m ops.heartbeat ingest-fuel --fail "spool unreadable"

WHY THIS EXISTS
See db/migrations/028_ops_heartbeat.sql for the argument in full. Short version:
"the collector died" and "the sources are quiet" both show up as no new rows,
and no query over the data tables can tell them apart, because both are defined
by rows that are not there. A job saying "I ran and succeeded and there was
nothing" is the only signal that disappears exactly when the collector does.

So `beat()` is called on a successful cycle EVEN WHEN IT PRODUCED ZERO ROWS.
Calling it only when there is something to report would reintroduce the exact
ambiguity this table exists to remove.

FAILING TO RECORD A HEARTBEAT MUST NOT FAIL THE JOB
A monitoring write that can take down the thing it monitors is worse than no
monitoring. If the database is unreachable, `beat()` warns and returns False;
the ingest run it was reporting on is not affected. The watchdog notices the
missing heartbeat on its own, which is the correct outcome — a job that cannot
reach the database is genuinely unhealthy and should be reported as such.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect                          # noqa: E402

UPSERT = """
INSERT INTO ops_heartbeat (name, last_ok, last_attempt, last_error,
                           consecutive_failures, expected_interval_seconds,
                           grace_seconds, detail)
VALUES (%s, now(), now(), NULL, 0, %s, %s, %s)
ON CONFLICT (name) DO UPDATE SET
  last_ok = now(), last_attempt = now(), last_error = NULL,
  consecutive_failures = 0,
  -- COALESCE so a caller that omits the cadence does not erase a cadence
  -- another caller already established. An interval quietly becoming NULL
  -- would set status to 'unmonitored' and switch the watchdog off silently.
  expected_interval_seconds = COALESCE(EXCLUDED.expected_interval_seconds,
                                       ops_heartbeat.expected_interval_seconds),
  grace_seconds = COALESCE(EXCLUDED.grace_seconds, ops_heartbeat.grace_seconds),
  detail = EXCLUDED.detail
"""

UPSERT_FAIL = """
INSERT INTO ops_heartbeat (name, last_ok, last_attempt, last_error,
                           consecutive_failures, expected_interval_seconds,
                           grace_seconds)
VALUES (%s, NULL, now(), %s, 1, %s, %s)
ON CONFLICT (name) DO UPDATE SET
  last_attempt = now(),
  last_error = EXCLUDED.last_error,
  consecutive_failures = ops_heartbeat.consecutive_failures + 1,
  expected_interval_seconds = COALESCE(EXCLUDED.expected_interval_seconds,
                                       ops_heartbeat.expected_interval_seconds),
  grace_seconds = COALESCE(EXCLUDED.grace_seconds, ops_heartbeat.grace_seconds)
"""


def beat(name: str, interval: int | None = None, grace: int | None = None,
         detail: dict | None = None) -> bool:
    """Record a successful cycle. Never raises — see the module docstring."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(UPSERT, (name, interval, grace,
                                 json.dumps(detail or {}, ensure_ascii=False)))
            conn.commit()
        return True
    except Exception as exc:                            # noqa: BLE001
        print(f"heartbeat({name}) failed to record: {exc}", file=sys.stderr)
        return False


def fail(name: str, error: str, interval: int | None = None,
         grace: int | None = None) -> bool:
    """Record an attempted cycle that did not succeed.

    `last_ok` is deliberately left alone: the job's freshness is still measured
    from when it last actually WORKED, not from when it last tried and failed.
    """
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(UPSERT_FAIL, (name, error[:2000], interval, grace))
            conn.commit()
        return True
    except Exception as exc:                            # noqa: BLE001
        print(f"heartbeat fail({name}) failed to record: {exc}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="record a job heartbeat")
    ap.add_argument("name")
    ap.add_argument("--interval", type=int, help="expected seconds between runs")
    ap.add_argument("--grace", type=int, help="how late is late, in seconds")
    ap.add_argument("--detail", default="{}", help="JSON object")
    ap.add_argument("--fail", metavar="ERROR", help="record a failed attempt")
    a = ap.parse_args()

    if a.fail:
        return 0 if fail(a.name, a.fail, a.interval, a.grace) else 1
    try:
        detail = json.loads(a.detail)
    except json.JSONDecodeError:
        detail = {"raw": a.detail[:500]}
    return 0 if beat(a.name, a.interval, a.grace, detail) else 1


if __name__ == "__main__":
    raise SystemExit(main())
