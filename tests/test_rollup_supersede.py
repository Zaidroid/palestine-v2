"""DATABANK-V15 (audit 2026-09-25, F142): the nightly rollup was the one mutable
path into `observation` — ON CONFLICT DO UPDATE SET value_num, no versioning.
After 088 it supersedes; before 088 it keeps the old update so the nightly
still runs. Proven on production in a rolled-back transaction 2026-09-26:
before 088 2,914 upserts; after, 50 stale rows closed and 0 rewritten, and a
second run touched nothing."""
from __future__ import annotations

from ops import rollup


class _Cur:
    def __init__(self, ready, pending):
        self.ready, self.pending, self.sql, self.rowcount = ready, pending, [], 0
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None):
        self.sql.append(sql)
        self._last = sql
    def fetchone(self):
        if "to_regclass" in self._last:
            return (self.ready,)
        return (7,)                                   # dataset id
    def fetchall(self):
        return [(d,) for d in self.pending]


class _Conn:
    def __init__(self, cur): self.cur = cur
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return self.cur
    def commit(self): pass


def _run(monkeypatch, ready):
    cur = _Cur(ready, ["2026-09-24"])
    monkeypatch.setattr(rollup, "connect", lambda: _Conn(cur))
    r = rollup.run(2)
    return r, "\n".join(cur.sql)


def test_DATABANK_V15_after_088_nothing_is_updated_in_place(monkeypatch):
    r, sql = _run(monkeypatch, ready=True)
    assert r["mode"] == "supersede"
    assert "DO UPDATE" not in sql
    assert "SET sys_period = tstzrange(lower(o.sys_period), now())" in sql
    assert "IS NOT DISTINCT FROM o.value_num" in sql      # unchanged rows untouched


def test_before_088_the_nightly_still_runs_the_old_way(monkeypatch):
    r, sql = _run(monkeypatch, ready=False)
    assert r["mode"].startswith("update-in-place")
    assert "DO UPDATE SET value_num" in sql


def test_the_migration_narrows_the_index_to_current_rows():
    text = open("db/migrations/088_rollup_rows_supersede.sql").read()
    assert "upper(sys_period) IS NULL" in text
    assert "DROP INDEX IF EXISTS observation_rollup_uniq;" in text
