"""An OnFailure alarm lives exactly as long as the failure (2026-09-25)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import alert as A                                                  # noqa: E402


def _ledger(tmp_path, monkeypatch, recs):
    p = tmp_path / "alerts.ndjson"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    monkeypatch.setattr(A, "ALERTS", p)
    monkeypatch.setattr(A, "_notify", lambda text, silent=False: {"delivered": False})
    return p


def test_resolve_if_open_is_a_silent_no_op_without_an_alarm(tmp_path, monkeypatch):
    p = _ledger(tmp_path, monkeypatch, [])
    assert A.resolve_if_open("palestine-v2-backup.service") is None
    assert p.read_text() == ""


def test_resolve_if_open_answers_an_open_alarm_once(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch, [
        {"ts": "2026-09-25T02:33:57+00:00", "unit": "palestine-v2-backup.service", "detail": "exit 1"}])
    assert A.resolve_if_open("palestine-v2-backup.service") is not None
    assert A.open_alerts() == []
    assert A.resolve_if_open("palestine-v2-backup.service") is None


def test_sweep_resolves_only_alarms_older_than_the_last_ok(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch, [
        {"ts": "2026-09-20T02:00:00+00:00", "unit": "palestine-v2-fuel.service"},
        {"ts": "2026-09-25T02:33:57+00:00", "unit": "palestine-v2-backup.service"},
        {"ts": "2026-09-25T03:00:00+00:00", "unit": "watchdog:feed:checkpoint_status"}])
    done = A.sweep({"fuel": "2026-09-24T00:00:00+00:00", "backup": "2026-09-24T02:31:50+00:00"})
    assert done == ["palestine-v2-fuel.service"]
    left = {r["unit"] for r in A.open_alerts()}
    assert left == {"palestine-v2-backup.service", "watchdog:feed:checkpoint_status"}


def test_wrapper_resolves_on_success_only():
    src = (ROOT / "ops" / "with-heartbeat.sh").read_text()
    ok_block = src.split('if [ "$ok" -eq 1 ]; then', 1)[1].split("else", 1)[0]
    assert "ops.alert --resolve" in ok_block
    assert 'palestine-v2-$name.service' in ok_block
