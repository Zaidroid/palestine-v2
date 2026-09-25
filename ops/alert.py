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
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALERTS = ROOT / "ops" / "alerts.ndjson"

# F273 — an OnFailure alarm for a unit that already pushed within this window
# is RECORDED and not pushed again. OnFailure alarms had no dedup at all: the
# checkpoint and crowd timers fire every two minutes, so one unit failing all
# night (a v1 redeploy leaving checkpoints.db unreadable) was thirty pushes an
# hour until morning — and a phone that buzzes thirty times an hour gets
# muted, after which the next unrelated critical lands in a muted channel.
# One push, then one reminder an hour while it keeps failing. Only a push that
# was DELIVERED quiets its repeats; an undelivered one is retried, not trusted.
REPEAT_QUIET_SECONDS = 3600

# F286 — an alarm whose push FAILED is re-sent, on this backoff, up to this
# many times. It used to be sent exactly once: a rotated ntfy token turned the
# first alarm of an outage into a receipt reading `HTTP 403` and then
# silence, because the watchdog only asks whether an alarm is OPEN, and an
# undelivered alarm is open. Forty-eight half-hours is a day of trying; past
# that the doorbell row in the watchdog is what says the channel is dead.
REDELIVER_EVERY_SECONDS = 1800
REDELIVER_MAX = 48

# How many consecutive failed deliveries mean the doorbell itself is broken.
DOORBELL_RECEIPTS = 3


def _notify(text: str, *, silent: bool = False, priority: str | None = None) -> dict:
    """Best-effort delivery. Imported lazily and wrapped so this module keeps
    working — and keeps RECORDING — if ops/notify.py is broken or absent."""
    try:
        from ops.notify import send
        return send(text, silent=silent, priority=priority)
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


def _ts(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _receipts(recs: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Delivery receipts per alarm, keyed (unit, alarm ts). The first receipt
    carries the alarm's own ts; a re-send says which alarm it was for."""
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in recs:
        if r.get("delivery_of"):
            out[(r["delivery_of"], r.get("alarm_ts", r["ts"]))].append(r)
    return out


def _recently_delivered(unit: str, now: datetime, window: float) -> str | None:
    """ts of the newest OPEN alarm for `unit` that reached someone within
    `window` seconds, or None."""
    recs, _ = _read_log()
    receipts = _receipts(recs)
    best = None
    for a in _open_from(recs):
        if a.get("unit") != unit or a.get("suppressed"):
            continue
        if not any(x.get("delivered") for x in receipts.get((unit, a["ts"]), [])):
            continue
        if (now - _ts(a["ts"])).total_seconds() <= window:
            best = max(best or "", a["ts"])
    return best


def raise_alert(unit: str, reason: str = "", *, quiet_repeats: bool = False) -> dict:
    """Record an alarm, then try to deliver it.

    `quiet_repeats` is the OnFailure path's: an EVENT from a timer that can fire
    every two minutes. The watchdog's conditions never need it — it raises a
    key only when no alarm for it is open.
    """
    repeat_of = None
    if quiet_repeats:
        # Best-effort: a ledger that cannot be read must cost the dedup, never
        # the alarm.
        try:
            repeat_of = _recently_delivered(unit, datetime.now(timezone.utc),
                                            REPEAT_QUIET_SECONDS)
        except Exception:                                       # noqa: BLE001
            repeat_of = None
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
    if repeat_of:
        rec["suppressed"] = True
        rec["repeat_of"] = repeat_of
    with ALERTS.open("a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    line = detail.splitlines()[-1] if detail else "failed"
    print(f"ALERT {unit}: {line}", file=sys.stderr)
    if repeat_of:
        print(f"  (recorded, not pushed: {unit} already reached someone at "
              f"{repeat_of[:19]}Z; a reminder goes out once an hour while it "
              f"keeps failing)", file=sys.stderr)
        rec["delivered"] = False
        rec["channel"] = "suppressed-repeat"
        return rec

    # THE SINK IS WRITTEN FIRST AND UNCONDITIONALLY. Delivery is best-effort on
    # top of it, never in place of it: the record must survive a dead network,
    # an expired token or a Telegram outage. `send` swallows everything and
    # returns a reason, so nothing here can raise into a systemd OnFailure
    # handler — an alarm path that can itself fail is a second outage.
    # HIGH, explicitly. The priority used to be inferred from a `!!` in the
    # text — the watchdog's console mark, which never appears in an alarm —
    # so every alarm, a dead poller included, went out at `default`, the
    # level a phone is most often told to keep quiet.
    d = _notify(f"🔴 {unit}\n{line[:600]}", priority="high")
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
    # Recoveries are delivered too, and SILENTLY — no notification sound.
    # An alerting channel that only ever tells you about failures leaves you
    # unable to tell "it recovered" from "it is still broken and has gone
    # quiet", and the second reading is the one that gets ignored. Silent so
    # good news never wakes anybody.
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
    return _open_from(recs)


def _open_from(recs: list[dict]) -> list[dict]:
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


def redeliver_undelivered(now: datetime | None = None) -> list[dict]:
    """Re-send every OPEN alarm that has not reached anyone yet (F286).

    Called by the watchdog every run. An alarm counts as delivered once any of
    its receipts says so; one with no receipt at all (the process died between
    the record and the push) counts as undelivered. `unconfigured` is not
    retried — nothing has changed that a retry could fix — and a suppressed
    repeat is not an alarm in its own right. Returns the receipts written.
    """
    now = now or datetime.now(timezone.utc)
    recs, _ = _read_log()
    receipts = _receipts(recs)
    written = []
    for a in _open_from(recs):
        unit = a.get("unit", "")
        if not unit or a.get("suppressed"):
            continue
        rs = receipts.get((unit, a["ts"]), [])
        if any(r.get("delivered") for r in rs):
            continue
        if rs and "unconfigured" in str(rs[-1].get("reason", "")):
            continue
        if len(rs) > REDELIVER_MAX:
            continue
        last = max([a["ts"]] + [r["ts"] for r in rs])
        if (now - _ts(last)).total_seconds() < REDELIVER_EVERY_SECONDS:
            continue
        detail = a.get("detail") or ""
        line = detail.splitlines()[-1] if detail else "failed"
        d = _notify(f"🔴 {unit}\n{line[:600]}\n(re-sent: raised {a['ts'][:16]}Z and "
                    f"not delivered)", priority="high")
        receipt = {"ts": now.isoformat(), "delivery_of": unit, "alarm_ts": a["ts"],
                   "delivered": d["ok"], "channel": d.get("channel", "unknown"),
                   "retry": len(rs)}
        if d.get("id"):
            receipt["message_id"] = d["id"]
        if not d["ok"]:
            receipt["reason"] = str(d.get("reason", ""))[:200]
        with ALERTS.open("a") as fh:
            fh.write(json.dumps(receipt, ensure_ascii=False) + "\n")
        written.append(receipt)
    return written


def delivery_health(n: int = DOORBELL_RECEIPTS) -> dict:
    """Did the last `n` delivery attempts reach anyone? The doorbell's own row.

    Nothing proved the channel worked except a hand-run `--test`, so a dead
    token read exactly like a quiet week. `ok` is False only when there are at
    least `n` receipts and NONE of the last `n` was delivered — one failure is
    weather, `n` in a row is the channel.
    """
    recs, _ = _read_log()
    rs = [r for r in recs if r.get("delivery_of")][-n:]
    out = {"checked": len(rs), "ok": True, "last": rs[-1] if rs else None}
    if len(rs) >= n and not any(r.get("delivered") for r in rs):
        out["ok"] = False
        out["reasons"] = sorted({str(r.get("reason", ""))[:120] for r in rs})
    return out


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
                          "palestine-v2 delivery test — a human should see this")
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

    raise_alert(a.unit, a.reason, quiet_repeats=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
