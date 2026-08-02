"""Record an operational alarm. Invoked by systemd `OnFailure=`.

    .venv/bin/python -m ops.alert <unit-name> [reason]
    .venv/bin/python -m ops.alert --list          # open alarms
    .venv/bin/python -m ops.alert --clear         # acknowledge all

WHY A SINK BEFORE A CHANNEL
Ten timers run and nothing watches them (P3.1). A dead poller, a failed dump and
a feed that quietly stopped all look identical to healthy from outside, which is
the failure mode that lets a system rot while appearing fine.

Delivery is P3.1's job and it is not built yet. Not raising the alarm until the
delivery exists would mean the first weeks of nightly backups fail silently, so
this writes the alarm down now: append-only to ops/alerts.ndjson, plus a
journal line at error priority. P3.1 adds a reader; nothing here changes.

Deliberately NOT delivered over the agent2 Telegram account. That account is the
scarcest asset in the project and using it for machine chatter is how it gets
rate-limited or banned — and an alerting channel that dies under load is worse
than none, because its silence reads as good news.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALERTS = ROOT / "ops" / "alerts.ndjson"


def raise_alert(unit: str, reason: str = "") -> dict:
    detail = reason
    if not detail and unit:
        cp = subprocess.run(["systemctl", "status", "--no-pager", "-n", "15", unit],
                            capture_output=True)
        detail = cp.stdout.decode()[-1500:]
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "unit": unit,
        "detail": detail.strip(),
        "acknowledged": False,
    }
    with ALERTS.open("a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"ALERT {unit}: {detail.splitlines()[-1] if detail else 'failed'}",
          file=sys.stderr)
    return rec


def resolve(unit: str, note: str = "") -> dict:
    """Close an alarm whose CONDITION no longer holds.

    Conditions and events need different lifetimes. "The poller has not
    succeeded in eight hours" is a condition: once it succeeds again the alarm
    is answered, and leaving it red forever teaches whoever reads the list to
    stop reading it — the precise outcome an alerting system cannot afford.
    A unit that failed at 03:00 is an event; it does not un-happen, and it
    waits for --clear.

    So ops/watchdog.py resolves its own alarms when the check goes green, and
    nothing resolves the ones systemd's OnFailure= raised. The log stays
    append-only either way: resolving writes a record, it never deletes one, so
    a fault that came and went at 3am is still in the history.
    """
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "resolves": unit,
        "note": note,
    }
    with ALERTS.open("a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def open_alerts() -> list[dict]:
    if not ALERTS.exists():
        return []
    recs = [json.loads(line) for line in ALERTS.read_text().splitlines() if line.strip()]
    cleared_at = max((r["ts"] for r in recs if r.get("clear_marker")), default="")
    # Last resolution per unit. An alarm re-raised AFTER its resolution is open
    # again — comparing timestamps rather than keeping a resolved set means a
    # flapping fault reports every time it comes back, instead of being
    # permanently silenced by the one time it recovered.
    resolved: dict[str, str] = {}
    for r in recs:
        if r.get("resolves"):
            resolved[r["resolves"]] = max(resolved.get(r["resolves"], ""), r["ts"])
    return [r for r in recs
            if not r.get("clear_marker") and not r.get("resolves")
            and r["ts"] > cleared_at
            and r["ts"] > resolved.get(r.get("unit", ""), "")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("unit", nargs="?", default="")
    ap.add_argument("reason", nargs="?", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()

    if a.clear:
        with ALERTS.open("a") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                 "clear_marker": True}) + "\n")
        print("acknowledged")
        return 0
    if a.list or not a.unit:
        alerts = open_alerts()
        if not alerts:
            print("no open alarms")
            return 0
        for r in alerts:
            first = r["detail"].splitlines()[0] if r["detail"] else ""
            print(f"{r['ts'][:19]}  {r['unit']}  {first[:80]}")
        return 1

    raise_alert(a.unit, a.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
