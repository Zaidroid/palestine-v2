"""v1's MiniMax path has a success rate. Measure it, and say so when it is zero.

    .venv/bin/python -m ops.minimax_alarm              # measure; alarm on fault
    .venv/bin/python -m ops.minimax_alarm --dry-run    # measure; never alarm
    .venv/bin/python -m ops.minimax_alarm --json

WHAT HAPPENED, AND WHY IT COULD
`westbank-alerts` (container `params-alerts-api`) calls MiniMax wherever its
Arabic rules return nothing. Over the fourteen days measured on 2026-09-19 it
made 29,687 calls and 29,686 of them failed — `'NoneType' object is not
subscriptable`, a quota or billing body that still passes `raise_for_status`,
so `data["choices"]` is None. `llm_cache` has gained ONE row since 2026-06-24.
The subscription is still paid.

Every one of those failures was reported, truthfully, as a single log line:
"MiniMax call failed (...) — falling back to rules". The client is fail-safe by
design and the pipeline kept working on rules, which is why nothing broke and
why nobody noticed for three months. The missing piece was never detection. It
was that success had no DENOMINATOR anywhere — no counter, no table, no metric —
so "it is degrading" and "it is completely dead" produced identical evidence.

WHAT THIS MEASURES, AND WHAT IT CANNOT
Read-only, from outside the container, so it can run today without touching a
live service:

  failures   the client's own fallback lines in the container journal
  successes  rows added to `llm_cache` in the same window. All three callers
             pass a `cache_key`, and `_cache_put` runs only after a parse
             succeeds, so a new row is a successful call. A cache HIT returns
             before the counter increments and is neither.
  context    `GET /quality/checkpoints` -> `llm.calls_today`, `enabled`, `model`

Both halves are lower bounds on the same window, which is why the verdict is
stated as a rate over what was OBSERVED and the detail says so. The exact
counter belongs inside the client — `ops/patches/v1-minimax-metrics.patch` adds
it — but that needs a rebuild, and a dead alarm waiting for a deploy window is
the failure this file exists about.

NOT A PASS, AND NOT A FAULT, ARE DIFFERENT ANSWERS
No calls in the window is `idle`: the check ran and learned nothing, which is
not evidence of health. Unreadable evidence is a FAULT, because a monitoring
hole is an outage that is invisible for exactly as long as nobody checks. A
client that is switched off is `disabled` and not a fault — off is not down.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.alert import open_alerts, raise_alert, resolve          # noqa: E402

CONTAINER = os.environ.get("V1_ALERTS_CONTAINER", "params-alerts-api")
V1_API = os.environ.get("V1_API_URL", "http://127.0.0.1:8081")
CHECKPOINT_DB = os.environ.get(
    "V1_CHECKPOINT_DB",
    "/opt/stacks/palestine/services/westbank-alerts/data/checkpoints.db")

# One hour is the watchdog's natural window here: v1 makes ~50 calls an hour, so
# a dead path is unmistakable within one run and a transient blip is not.
WINDOW_HOURS = 1

# Below this the window has not seen enough calls for a rate to mean anything.
# Reported as `idle`, never as `ok` — see the module docstring.
MIN_CALLS = 5

# The bar. A path that fails more than half its calls is not "degraded", it is
# broken and being paid for. The rules fallback means nothing downstream
# notices, which is exactly why the number has to be watched rather than the
# output.
FAULT_BELOW = 0.5

_FAIL = re.compile(r"MiniMax (?:call failed \((?P<why>[^)]*)\)|"
                   r"(?P<other>returned non-JSON|daily budget))")


def _failures(window_hours: int = WINDOW_HOURS) -> tuple[int, dict, str | None]:
    """Fallback lines in the container journal, counted and grouped by reason."""
    try:
        cp = subprocess.run(
            ["docker", "logs", CONTAINER, "--since", f"{window_hours}h"],
            capture_output=True, timeout=60)
    except Exception as exc:                                    # noqa: BLE001
        return 0, {}, f"could not read {CONTAINER}'s log: {type(exc).__name__}: {exc}"
    if cp.returncode != 0:
        err = cp.stderr.decode(errors="replace").strip().splitlines()
        return 0, {}, f"docker logs {CONTAINER} exited {cp.returncode}: " \
                      f"{err[-1] if err else 'no output'}"
    reasons: dict[str, int] = {}
    total = 0
    # BOTH streams. The client logs through `logging`, which writes to stderr,
    # and reading stdout alone reported a perfectly healthy zero failures over a
    # path that was failing every single call — the exact shape of lie this
    # whole file exists to catch, reproduced inside the catcher on the first
    # try. `docker logs` keeps the two streams apart; the journal does not care.
    stream = (cp.stdout.decode(errors="replace") + "\n"
              + cp.stderr.decode(errors="replace"))
    for line in stream.splitlines():
        m = _FAIL.search(line)
        if not m:
            continue
        total += 1
        why = (m.group("why") or m.group("other") or "unknown").strip()
        reasons[why] = reasons.get(why, 0) + 1
    return total, reasons, None


def _successes(window_hours: int = WINDOW_HOURS) -> tuple[int | None, str | None]:
    """Rows added to v1's llm_cache in the window. Read-only; never locks."""
    since = (datetime.now(timezone.utc) - timedelta(hours=window_hours))
    # created_at is written with datetime.utcnow().isoformat() — naive UTC.
    cutoff = since.replace(tzinfo=None).isoformat()
    try:
        con = sqlite3.connect(f"file:{CHECKPOINT_DB}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT count(*) FROM llm_cache WHERE created_at > ?",
                              (cutoff,)).fetchone()
        finally:
            con.close()
    except Exception as exc:                                    # noqa: BLE001
        return None, f"could not read llm_cache: {type(exc).__name__}: {exc}"
    return int(row[0]), None


def _client_state() -> tuple[dict, str | None]:
    """v1's own view of its client: enabled, model, calls today."""
    try:
        import httpx
        r = httpx.get(f"{V1_API}/quality/checkpoints", timeout=10.0)
        r.raise_for_status()
        return r.json().get("llm") or {}, None
    except Exception as exc:                                    # noqa: BLE001
        return {}, f"{V1_API}/quality/checkpoints: {type(exc).__name__}: {exc}"


def measure(window_hours: int = WINDOW_HOURS) -> dict:
    """Everything the verdict is made of, before any judgement is applied."""
    fails, reasons, log_err = _failures(window_hours)
    ok, db_err = _successes(window_hours)
    client, api_err = _client_state()
    observed = (ok or 0) + fails
    return {
        "window_hours": window_hours,
        "failures": fails,
        "failure_reasons": reasons,
        "successes": ok,
        "observed_calls": observed,
        "success_rate": round(ok / observed, 4) if ok is not None and observed else None,
        "client": client,
        # The two halves of the verdict are kept apart from the nice-to-have.
        # Evidence that cannot be read is a monitoring hole and a fault; the
        # context endpoint being down only costs the model name in the detail.
        "evidence_errors": [e for e in (log_err, db_err) if e],
        "context_errors": [e for e in (api_err,) if e],
        "errors": [e for e in (log_err, db_err, api_err) if e],
    }


def check(window_hours: int = WINDOW_HOURS) -> list[dict]:
    """One watchdog-shaped row, so this lives on the same board as everything else."""
    m = measure(window_hours)
    row = {"check": "dep", "name": "minimax", "age_minutes": None,
           "threshold_minutes": None, "measure": m}

    # The evidence itself is unreadable. That is a hole in the monitoring, and
    # a hole is a fault: it is invisible for exactly as long as nobody looks.
    if m["successes"] is None or m["evidence_errors"]:
        return [{**row, "status": "unreadable", "fault": True,
                 "detail": "; ".join(m["evidence_errors"] or m["errors"])[:400]}]

    client = m["client"]
    if client and client.get("enabled") is False:
        return [{**row, "status": "disabled", "fault": False,
                 "detail": "v1's MiniMax client is switched off — off is not down"}]

    rate, seen = m["success_rate"], m["observed_calls"]
    top = ""
    if m["failure_reasons"]:
        why, n = max(m["failure_reasons"].items(), key=lambda kv: kv[1])
        top = f"; commonest failure {n}× {why!r}"

    if seen < MIN_CALLS:
        return [{**row, "status": "idle", "fault": False,
                 "detail": f"only {seen} call(s) observed in {window_hours}h — "
                           f"too few to judge a rate, so this check saw nothing "
                           f"either way{top}"}]
    if rate is not None and rate < FAULT_BELOW:
        return [{**row, "status": "failing", "fault": True,
                 "detail": f"{m['successes']}/{seen} MiniMax calls succeeded in "
                           f"{window_hours}h ({rate:.0%}) — the pipeline is "
                           f"silently on rules and the subscription is still "
                           f"paid{top}"}]
    return [{**row, "status": "ok", "fault": False,
             "detail": f"{m['successes']}/{seen} calls succeeded ({rate:.0%})"}]


def safe_check(window_hours: int = WINDOW_HOURS) -> list[dict]:
    """check(), but a bug in here can never take the watchdog down with it."""
    try:
        return check(window_hours)
    except Exception as exc:                                    # noqa: BLE001
        return [{"check": "dep", "name": "minimax", "status": "unreadable",
                 "fault": True, "age_minutes": None, "threshold_minutes": None,
                 "detail": f"the MiniMax check itself failed: "
                           f"{type(exc).__name__}: {exc}"}]


def main() -> int:
    ap = argparse.ArgumentParser(description="v1's MiniMax success rate")
    ap.add_argument("--dry-run", action="store_true", help="report, never alarm")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hours", type=int, default=WINDOW_HOURS)
    a = ap.parse_args()

    rows = safe_check(a.hours)
    r = rows[0]
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"minimax  {r['status']}  {r['detail']}")

    if not a.dry_run:
        key = "watchdog:dep:minimax"
        already = any(x.get("unit") == key for x in open_alerts())
        if r["fault"] and not already:
            raise_alert(key, f"{r['status']} — {r['detail']}")
        elif not r["fault"] and already:
            resolve(key, f"now {r['status']}: {r['detail']}")
    return 1 if r["fault"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
