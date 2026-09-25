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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALERTS = ROOT / "ops" / "alerts.ndjson"


def _notify(text: str, *, silent: bool = False) -> dict:
    """Best-effort delivery. Imported lazily and wrapped so this module keeps
    working — and keeps RECORDING — if ops/notify.py is broken or absent."""
    try:
        from ops.notify import send
        return send(text, silent=silent)
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


DEDUP_MINUTES = 30


def _recently_raised(unit: str, minutes: int) -> str | None:
    """ts of an alarm for `unit` raised within `minutes`, or None."""
    if not minutes:
        return None
    recs, _ = _read_log()
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    for r in reversed(recs):
        if r.get("unit") == unit and not r.get("delivery_of") and not r.get("resolves"):
            return r["ts"] if r["ts"] >= since else None
    return None


def raise_alert(unit: str, reason: str = "", *, dedup_minutes: int = DEDUP_MINUTES,
                silent: bool = False) -> dict:
    """Record an alarm and deliver it — unless the same unit raised within
    `dedup_minutes`: then it is recorded with `suppressed_after` and NOT
    delivered (audit F272: a failing 2-minute timer pushed 30 notifications an
    hour). The log keeps every occurrence either way."""
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
    prev = _recently_raised(unit, dedup_minutes)
    if prev:
        rec["suppressed_after"] = prev
        rec["delivered"] = False
        with ALERTS.open("a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"ALERT {unit}: repeated within {dedup_minutes} min — recorded, not sent",
              file=sys.stderr)
        return rec
    with ALERTS.open("a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    line = detail.splitlines()[-1] if detail else "failed"
    print(f"ALERT {unit}: {line}", file=sys.stderr)

    # THE SINK IS WRITTEN FIRST AND UNCONDITIONALLY. Delivery is best-effort on
    # top of it, never in place of it: the record must survive a dead network,
    # an expired token or a Telegram outage. `send` swallows everything and
    # returns a reason, so nothing here can raise into a systemd OnFailure
    # handler — an alarm path that can itself fail is a second outage.
    d = _notify(f"🔴 {unit}\n{line[:600]}", silent=silent)
    rec["delivered"] = d["ok"]
    # WHICH channel, and WHICH message. An alarm that records "delivered" and
    # nothing else cannot be checked after the fact — and on 2026-09-22 the
    # honest answer for every alarm in this file was "nowhere".
    rec["channel"] = d.get("channel", "unknown")
    if d.get("id"):
        rec["message_id"] = d["id"]
    # THE RECEIPT IS APPENDED, NOT BACKDATED. The line above is written before
    # delivery on purpose — a crash here must not cost the alarm — so the
    # outcome was never IN it: `delivered` existed only in this function's
    # return value, which means the ledger could not answer "did anyone hear
    # this?" for any alarm it held. This second line answers it. open_alerts()
    # steps over it: it completes a record, it is not another alarm.
    receipt = {"ts": rec["ts"], "delivery_of": unit, "delivered": d["ok"],
               "channel": rec["channel"]}
    if d.get("id"):
        receipt["message_id"] = d["id"]
    if not d["ok"]:
        receipt["reason"] = str(d.get("reason", ""))[:200]
    with ALERTS.open("a") as fh:
        fh.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    if not d["ok"] and d["reason"] and "unconfigured" not in d["reason"]:
        print(f"  (alert delivery failed: {d['reason']})", file=sys.stderr)
        rec["reason"] = str(d["reason"])[:200]
    return rec


def redeliver(unit: str, detail: str = "") -> dict:
    """A second delivery attempt for an OPEN alarm whose first failed; writes
    a receipt only (the alarm record already exists) — audit F285."""
    line = detail.splitlines()[-1] if detail else "still open"
    d = _notify(f"🔴 (retry) {unit}\n{line[:600]}")
    receipt = {"ts": datetime.now(timezone.utc).isoformat(), "delivery_of": unit,
               "delivered": d["ok"], "channel": d.get("channel", "unknown"), "retry": True}
    if not d["ok"]:
        receipt["reason"] = str(d.get("reason", ""))[:200]
    with ALERTS.open("a") as fh:
        fh.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    return receipt


def resolve(unit: str, note: str = "", *, notify: bool = True) -> dict:
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
    # Recoveries are delivered too, and SILENTLY — no notification sound.
    # An alerting channel that only ever tells you about failures leaves you
    # unable to tell "it recovered" from "it is still broken and has gone
    # quiet", and the second reading is the one that gets ignored. Silent so
    # good news never wakes anybody.
    if notify:
        _notify(f"🟢 recovered: {unit}\n{note[:300]}", silent=True)
    return rec


def _read_log() -> tuple[list[dict], int]:
    """Every record in the log, and a count of the lines that were not records.

    A LOG THAT CAN KILL ITS OWN READER IS NOT A SINK, IT IS A SECOND OUTAGE.
    The host lost power mid-append on 2026-08-08 and ext4's delayed allocation
    left one line as 3,275 NUL bytes. Every read of this file went through a
    bare `json.loads` per line, so from that instant `--list` raised, the
    watchdog printed a traceback where its alarm reconciliation belonged, and
    nothing anywhere said the alarm channel had stopped answering. Nine days.

    So a torn line is stepped over — but COUNTED, and reported by --list. The
    alarms written into a torn region are gone and no amount of care recovers
    them; silence about that is the same bug one layer down. The damaged line
    itself is never rewritten: it is the tombstone of a crash, and this log is
    append-only in both directions.
    """
    if not ALERTS.exists():
        return [], 0
    recs, damaged = [], 0
    for line in ALERTS.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            damaged += 1
            continue
        if isinstance(rec, dict) and isinstance(rec.get("ts"), str):
            recs.append(rec)
        else:
            damaged += 1
    return recs, damaged


def damaged_lines() -> int:
    return _read_log()[1]


def open_alerts() -> list[dict]:
    recs, _ = _read_log()
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
            and not r.get("delivery_of")          # a receipt completes an alarm
            and r["ts"] > cleared_at
            and r["ts"] > resolved.get(r.get("unit", ""), "")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("unit", nargs="?", default="")
    ap.add_argument("reason", nargs="?", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--test", action="store_true",
                    help="raise a real alarm down the real path and say where it landed")
    a = ap.parse_args()

    if a.test:
        # Deliberately NOT a bespoke one-line probe: this goes through
        # raise_alert, so it proves the ledger, the delivery and the channel all
        # at once. If it says delivered without a channel, nothing landed.
        rec = raise_alert("notify-test",
                          "palestine-v2 delivery test — a human should see this",
                          dedup_minutes=0)
        print(f"raised: delivered={rec['delivered']} "
              f"channel={rec.get('channel')} id={rec.get('message_id', '-')}")
        return 0 if rec["delivered"] else 1

    if a.clear:
        with ALERTS.open("a") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                 "clear_marker": True}) + "\n")
        print("acknowledged")
        return 0
    if a.list or not a.unit:
        alerts = open_alerts()
        damaged = damaged_lines()
        if damaged:
            print(f"WARNING: {damaged} unreadable line(s) in {ALERTS.name} — "
                  "any alarm written there is lost", file=sys.stderr)
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
