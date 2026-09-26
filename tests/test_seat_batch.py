"""P2-A.2 — the nightly seat batch (analyst/seat_batch.py): a pure function,
never an agent (audit OPS-01), whose proposals nothing serves."""
from __future__ import annotations

import os

from analyst import seat_batch as sb


def test_the_seat_runs_with_no_tools_no_settings_and_no_bypass():
    cmd = sb.seat_command()
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""
    for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in cmd
    assert not any("dangerously" in c or "bypass" in c for c in cmd)


def test_the_seat_environment_carries_no_secrets(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setenv("TELEGRAM_API_HASH", "y")
    env = sb._clean_env()
    assert "PGPASSWORD" not in env and "TELEGRAM_API_HASH" not in env
    assert set(env) <= {"HOME", "PATH", "LANG", "LC_ALL", "USER", "LOGNAME",
                        "XDG_CONFIG_HOME"}


def test_parse_tolerates_a_fence_and_refuses_prose():
    assert sb.parse_items('```json\n[{"id": 1}]\n```') == [{"id": 1}]
    assert sb.parse_items("I cannot help with that.") is None


def test_validate_keeps_only_closed_vocabulary_answers_for_known_ids():
    items = [{"id": 1, "verdict": "incident", "incident_type": "arrest", "confidence": 0.9},
             {"id": 2, "verdict": "incident", "incident_type": "massacre"},   # not a type
             {"id": 3, "verdict": "maybe"},                                    # not a verdict
             {"id": 9, "verdict": "not_incident"},                             # unknown id
             {"id": 1, "verdict": "not_incident"},                             # second answer
             {"id": 4, "verdict": "not_incident", "incident_type": "raid"},
             {"id": 5, "verdict": "unclear", "confidence": 3}]                 # out of range
    clean, dropped = sb.validate(items, {1, 2, 3, 4, 5})
    assert set(clean) == {1, 4}
    assert clean[4]["incident_type"] is None           # a type only with an incident
    assert dropped == 5


class _Cur:
    def __init__(self, log, todo):
        self.log, self.todo = log, todo
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None):
        self.log.append((sql, params))
    def fetchall(self):
        return self.todo


class _Conn:
    def __init__(self, log, todo):
        self.log, self.todo = log, todo
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return _Cur(self.log, self.todo)
    def commit(self): pass


def _run(monkeypatch, tmp_path, caller, todo):
    log = []
    import resolve.db
    monkeypatch.setattr(resolve.db, "connect", lambda: _Conn(log, todo))
    monkeypatch.setattr(sb, "LEDGER", tmp_path / "seat.ndjson")
    return sb.nightly(limit=10, chunk=2, caller=caller), log


def test_nightly_writes_only_seat_rows_and_never_the_claim(monkeypatch, tmp_path):
    todo = [(1, "اعتقال شاب من بيت أمر"), (2, "تشييع جثمان"), (3, "نص")]

    def caller(part):
        return [{"id": m["id"], "verdict": "incident" if m["id"] == 1 else "not_incident",
                 "incident_type": "arrest" if m["id"] == 1 else None,
                 "place": "", "confidence": 0.9} for m in part], {"latency_ms": 10}

    s, log = _run(monkeypatch, tmp_path, caller, todo)
    assert s["read"] == 3 and s["proposed_incident"] == 1 and s["proposed_not"] == 2
    writes = [sql for sql, _ in log if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert writes and all("claim_classification" in w or "analyst_run" in w for w in writes)
    assert not any("INTO claim " in w or "UPDATE claim " in w for w in writes)
    upserts = [p for sql, p in log if "INSERT INTO claim_classification" in sql]
    assert {p["verdict"] for p in upserts} == {"incident", "rejected"}
    assert (tmp_path / "seat.ndjson").exists()


def test_a_capped_seat_stops_the_night(monkeypatch, tmp_path):
    calls = []

    def caller(part):
        calls.append(len(part))
        return None, {"capped": True, "error": "usage limit reached"}

    s, _ = _run(monkeypatch, tmp_path, caller, [(i, "x" * 20) for i in range(6)])
    assert s["capped"] and len(calls) == 1 and s["read"] == 0
