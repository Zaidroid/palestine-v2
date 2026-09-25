"""Audit 2026-09-25, area 11 — OPS-02..16 (OPS-01 is Zaid's hand)."""
from __future__ import annotations

import inspect
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import alert as A, backup as B, gap_radar, heartbeat as H, repair_generations as RG   # noqa: E402
from ops import restore_test as RT, watchdog as W                                              # noqa: E402


# ── OPS-02 / OPS-04: exit codes agree between script, wrapper and unit ───────
def test_ops_02_04_every_ok_exit_code_is_known_to_its_unit():
    units = {p.name: p.read_text() for p in (ROOT / "ops" / "systemd").glob("*.service")}
    for sh in (ROOT / "ops").glob("*.sh"):
        txt = sh.read_text()
        m = re.search(r"^export OK_EXIT_CODES=(\d+)", txt, re.M)
        if not m:
            continue
        code = m.group(1)
        unit = next((u for u, t in units.items() if f"/ops/{sh.name}" in t), None)
        assert unit, f"{sh.name} sets OK_EXIT_CODES but no unit runs it"
        assert re.search(rf"^SuccessExitStatus=.*\b{code}\b", units[unit], re.M), \
            f"{unit} lacks SuccessExitStatus for exit {code}"
    assert "env OK_EXIT_CODES=1 .venv" not in (ROOT / "ops" / "mcp-audit.sh").read_text()


def test_ops_04_a_fault_and_a_crash_have_different_exit_codes(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["watchdog", "--dry-run"])
    for fn in ("job_checks", "capacity_check", "dependency_checks", "routing_check",
               "minimax_check", "fuel_price_check", "backup_check", "fetch_check",
               "source_checks"):
        monkeypatch.setattr(W, fn, lambda *a, **k: [])
    monkeypatch.setattr(W, "doorbell_check", lambda send=False: [])
    monkeypatch.setattr(W, "measure_cadence", lambda: {})
    monkeypatch.setattr(W, "feed_checks", lambda jobs, cad=None: [
        {"check": "feed", "name": "x", "status": "silent", "fault": True, "detail": "", "age_minutes": 1}])
    assert W.main() == W.FAULT_EXIT == 3
    monkeypatch.setattr(W, "feed_checks", lambda jobs, cad=None: [])
    assert W.main() == 0
    raised = []
    monkeypatch.setattr(W, "job_checks", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(W, "raise_alert", lambda unit, reason="": raised.append(unit))
    assert W.main() == 1 and raised == ["watchdog:self"]


# ── OPS-05: dedup ────────────────────────────────────────────────────────────
def test_ops_05_a_repeated_alarm_is_recorded_but_not_sent(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ALERTS", tmp_path / "alerts.ndjson")
    sent = []
    monkeypatch.setattr(A, "_notify", lambda text, silent=False: sent.append(text) or {"ok": True, "channel": "t", "id": "1"})
    A.raise_alert("palestine-v2-x.service", "exited 1")
    rec = A.raise_alert("palestine-v2-x.service", "exited 1")
    assert len(sent) == 1 and rec.get("suppressed_after")
    A.raise_alert("palestine-v2-x.service", "exited 1", dedup_minutes=0)
    assert len(sent) == 2
    recs, _ = A._read_log()
    assert sum(1 for r in recs if r.get("unit") == "palestine-v2-x.service" and not r.get("delivery_of")) == 3


# ── OPS-06 / OPS-07 / OPS-09: backup ─────────────────────────────────────────
def test_ops_07_prune_keeps_the_newest_and_one_per_month_never_below_the_floor(monkeypatch):
    names = [f"2026-08-01T0{i}-00-00Z" for i in range(9)] + \
            [f"2026-08-{d:02d}T02-00-00Z" for d in range(2, 30)] + \
            [f"2026-09-{d:02d}T02-00-00Z" for d in range(1, 25)]
    purged = []
    def fake_run(cmd, **kw):
        class R: stdout = ("\n".join(n + "/" for n in names)).encode()
        if cmd[1] == "purge":
            purged.append(cmd[2].rsplit("/", 1)[1])
        return R()
    monkeypatch.setattr(B, "_run", fake_run)
    B.prune_remote("hetzner:x")
    kept = [n for n in names if n not in purged]
    assert kept[-30:] == sorted(names)[-30:]
    assert "2026-08-01T00-00-00Z" in kept and "2026-08-01T01-00-00Z" not in kept   # one per month
    assert len(kept) >= B.MIN_REMOTE_SETS


def test_ops_06_the_last_full_is_read_from_the_marker_first(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "STAGING", tmp_path)
    monkeypatch.setattr(B, "LAST_FULL_MARKER", tmp_path / "last-full.json")
    assert B._last_full_bronze() is None
    (tmp_path / "last-full.json").write_text(json.dumps({"set": "s", "bronze_from": 1700000000.0}))
    assert B._last_full_bronze() == 1700000000.0
    src = inspect.getsource(B.run)
    assert src.index("prune_remote(remote)") < src.index("upload(set_dir, remote)")
    assert "prune_local()" in src[src.index("finally:"):]
    assert "evidence" in inspect.getsource(B.archive_evidence) and ".keys" in inspect.getsource(B.archive_secrets)


# ── OPS-10 ───────────────────────────────────────────────────────────────────
def test_ops_10_the_generation_rule_is_one_closed_day():
    sql = RG.generation_sql("2026-08-07")
    assert "BETWEEN '2026-08-07' AND '2026-08-07'" in sql and ">=" not in sql
    assert "identity_key IS NOT NULL" in inspect.getsource(RG)


# ── OPS-11 ───────────────────────────────────────────────────────────────────
def test_ops_11_the_restore_test_replays_the_bronze_chain(tmp_path):
    for name, kind in (("2026-09-01T02-00-00Z", "full"), ("2026-09-02T02-00-00Z", "incremental"),
                       ("2026-09-03T02-00-00Z", "incremental")):
        d = tmp_path / name; d.mkdir()
        (d / "manifest.json").write_text(json.dumps({"bronze_kind": kind}))
    import ops.restore_test as R
    old = R.STAGING
    try:
        R.STAGING = tmp_path
        chain = R.bronze_chain(tmp_path / "2026-09-03T02-00-00Z")
        assert [p.name[:10] for p in chain] == ["2026-09-01", "2026-09-02", "2026-09-03"]
        assert R.bronze_chain(tmp_path / "2026-08-31T02-00-00Z") == []
    finally:
        R.STAGING = old
    src = inspect.getsource(R.main)
    assert "sample_bronze_refs" in src and src.index("shutil.rmtree(set_dir") > src.rindex("finally:")


# ── OPS-12 / OPS-03 ──────────────────────────────────────────────────────────
def test_ops_12_03_the_valhalla_sync_is_atomic_wrapped_and_registered():
    sh = (ROOT / "ops" / "sync-valhalla-ip.sh").read_text()
    assert 'mv -f "$tmp" .env' in sh and "cmp -s" in sh and "umask 077" in sh and 'cat "$tmp" > .env' not in sh
    wrap = (ROOT / "ops" / "valhalla-ip.sh").read_text()
    assert "with-heartbeat.sh valhalla-ip 900 1800" in wrap and W.EXPECTED_JOBS["valhalla-ip"] == (900, 1800)
    unit = (ROOT / "ops" / "systemd" / "palestine-v2-valhalla-ip.service").read_text()
    assert "ops/valhalla-ip.sh" in unit and "OnFailure=" in unit


# ── OPS-13 / OPS-14 ──────────────────────────────────────────────────────────
def test_ops_13_feed_freshness_reads_assertions_only():
    for sql in (W.CURRENT_SQL, W.CADENCE_SQL, W.CEILING_SQL):
        assert "modality = 'assertion'" in sql


def test_ops_14_collector_down_keeps_its_alarm_and_unmonitored_expected_is_a_fault(monkeypatch):
    src = inspect.getsource(W._main)
    assert "still_down" in src and "unit not in still_down" in src
    monkeypatch.setattr(W, "_q", lambda sql: [
        {"name": "backup", "status": "unmonitored", "ok_age_minutes": None,
         "expected_interval_seconds": None, "consecutive_failures": 0, "last_error": None},
        {"name": "some-old-job", "status": "unmonitored", "ok_age_minutes": None,
         "expected_interval_seconds": None, "consecutive_failures": 0, "last_error": None}])
    rows = {r["name"]: r for r in W.job_checks()}
    assert rows["backup"]["fault"] is True and rows["some-old-job"]["fault"] is False


# ── OPS-15: the doorbell ─────────────────────────────────────────────────────
def test_ops_15_three_undelivered_receipts_are_a_fault_and_open_alarms_are_retried(monkeypatch, tmp_path):
    log = tmp_path / "alerts.ndjson"
    monkeypatch.setattr(A, "ALERTS", log)
    now = datetime.now(timezone.utc)
    recs = [{"ts": (now - timedelta(hours=3)).isoformat(), "unit": "u1", "detail": "x", "acknowledged": False}]
    for i in range(3):
        recs.append({"ts": (now - timedelta(hours=2, minutes=i)).isoformat(), "delivery_of": "u1",
                     "delivered": False, "channel": "ntfy", "reason": "401"})
    log.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    row = W.doorbell_check()[0]
    assert row["fault"] and row["status"] == "undelivered"
    sent = []
    monkeypatch.setattr(A, "_notify", lambda text, silent=False: sent.append(text) or {"ok": True, "channel": "ntfy", "id": "9"})
    assert W.resend_undelivered() == 1 and "(retry) u1" in sent[0]
    assert W.resend_undelivered() == 0                    # an hour of backoff


# ── OPS-16: the attempt is stamped first ─────────────────────────────────────
def test_ops_16_the_attempt_is_recorded_before_the_job_runs():
    sh = (ROOT / "ops" / "with-heartbeat.sh").read_text()
    assert sh.index("--attempt") < sh.index('\n"$@"\n') and "trap " in sh and "killed (TERM" in sh
    assert "last_attempt = now()" in H.UPSERT_ATTEMPT and "last_ok" not in H.UPSERT_ATTEMPT.split("DO UPDATE")[1]


# ── OPS-08: supply lines are counted ─────────────────────────────────────────
def test_ops_08_fetch_failures_are_counted_and_a_streak_is_a_fault(monkeypatch, tmp_path):
    sh = (ROOT / "ops" / "databank-sync.sh").read_text()
    assert "fails=$((fails+1))" in sh and "HEARTBEAT_DETAIL" in sh and "|| echo \"gho-wash" not in sh
    ev = tmp_path / "fetch-events.ndjson"
    rows = [{"label": "ooni:ps_daily", "at": "t", "outcome": "ok"}] + \
           [{"label": "gho:wash", "at": "t", "outcome": "failed"}] * 3
    ev.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(W, "FETCH_EVENTS", ev)
    out = W.fetch_check()
    assert [r["name"] for r in out] == ["gho:wash"] and out[0]["fault"]
    assert "newly_stalled" in inspect.getsource(gap_radar.main) and "return 4" in inspect.getsource(gap_radar.main)
