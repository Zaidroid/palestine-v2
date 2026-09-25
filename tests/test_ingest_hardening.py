"""Ingestion hardening — the v1 checkpoint cursor, the one-client session lock,
and the exit statuses the timers and systemd act on.

    ./.venv/bin/python -m pytest tests/test_ingest_hardening.py -q

The database tests run inside a transaction that is always rolled back (the
pattern of tests/test_crowd.py). v1's SQLite is never opened: every test that
imports checkpoints points `V1_DB` at a throwaway file it builds itself, because
/opt/stacks/palestine is live production and is read by nothing here.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── shared: a transaction that never commits ────────────────────────────────

class _NoCommit:
    """Stands in for `connect()`: hands the test's transaction to code that
    opens its own connection and commits, and swallows both, so the rollback
    at the end of the test really does undo everything."""

    def __init__(self, conn):
        self._c = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass

    def cursor(self, *a, **k):
        return self._c.cursor(*a, **k)

    def __getattr__(self, name):
        return getattr(self._c, name)


@pytest.fixture()
def tx():
    psycopg = pytest.importorskip("psycopg")
    from resolve.db import dsn
    try:
        conn = psycopg.connect(dsn())
    except Exception as exc:                            # noqa: BLE001
        pytest.skip(f"no database: {exc}")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


# ── the v1 checkpoint import cursor (F007, F125) ─────────────────────────────
#
# The cursor used to be MAX(observed_at) over EVERY checkpoint_status row, and
# the crowd path writes checkpoint_status rows stamped now(). One crowd report
# therefore moved the importer's cursor past v1 rows it had not read yet, and
# `WHERE timestamp > cursor` skipped them forever. A v1 row inserted later than
# a newer one (catch-up after an outage) was skipped the same way, and the
# whole-second string cursor re-read or skipped the boundary second depending
# on how v1 spells a timestamp.

V1_SCHEMA = """CREATE TABLE checkpoint_updates (
    canonical_key TEXT, status TEXT, status_raw TEXT, direction TEXT,
    source_channel TEXT, source_msg_id INTEGER, timestamp TEXT, raw_line TEXT)"""

# Far enough ahead that nothing else in a shared test database is newer, so
# the importer's cursor is the one these tests set up.
T0 = datetime(2031, 3, 4, 9, 0, 0, tzinfo=timezone.utc)


def _v1(path: Path, rows) -> None:
    """Append rows to a fake v1 database: (key, status, msg_id, timestamp, line)."""
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS " + V1_SCHEMA[len("CREATE TABLE "):])
    db.executemany(
        "INSERT INTO checkpoint_updates VALUES (?,?,?,?,?,?,?,?)",
        [(k, st, st, "", "test_roads_chan", mid, ts, line)
         for k, st, mid, ts, line in rows])
    db.commit()
    db.close()


@pytest.fixture()
def importer(tx, tmp_path, monkeypatch):
    """The checkpoint importer wired to the rolled-back transaction and to a
    fake v1 database, with one checkpoint place carrying v1's key."""
    from ingest.sources import checkpoints
    v1 = tmp_path / "checkpoints.db"
    monkeypatch.setattr(checkpoints, "V1_DB", str(v1))
    monkeypatch.setattr(checkpoints, "connect", lambda: _NoCommit(tx))
    key = f"test_cp_{os.getpid()}_{time.monotonic_ns()}"
    with tx.cursor() as cur:
        cur.execute("""INSERT INTO place (kind, name_ar, geom, source_refs)
                       VALUES ('checkpoint', 'حاجز اختبار',
                               ST_SetSRID(ST_MakePoint(35.25, 32.2), 4326), %s)
                       RETURNING place_id""",
                    (f'{{"v1_canonical_key": "{key}"}}',))
        place_id = cur.fetchone()[0]

    def legacy_rows():
        with tx.cursor() as cur:
            cur.execute("""SELECT observed_at, attrs->>'msg_id' FROM state_observation
                            WHERE place_id = %s AND state_kind = 'checkpoint_status'
                              AND attrs ? 'canonical_key'
                            ORDER BY observed_at, 2""", (place_id,))
            return cur.fetchall()

    return checkpoints, v1, key, place_id, legacy_rows


def _iso(dt: datetime, sep: str = "T", frac: bool = False) -> str:
    fmt = f"%Y-%m-%d{sep}%H:%M:%S" + (".%f" if frac else "")
    return dt.astimezone(timezone.utc).strftime(fmt)


def test_a_crowd_report_does_not_move_the_v1_cursor(importer, tx):
    """F007. v1 files a report dated between the last import and a crowd
    report; the old cursor (the crowd report's now()) skipped it forever."""
    checkpoints, v1, key, place_id, legacy_rows = importer
    _v1(v1, [(key, "open", 1, _iso(T0), "حاجز اختبار سالك")])
    checkpoints.import_updates()
    assert len(legacy_rows()) == 1

    # A crowd report on the same kind, stamped later than anything v1 has.
    with tx.cursor() as cur:
        cur.execute("SELECT source_id FROM source LIMIT 1")
        row = cur.fetchone()
        if row is None:
            cur.execute("""INSERT INTO source (key,name,kind,license_spdx,
                                               commercial_use,attribution_text,
                                               authority_rank)
                           VALUES ('test_crowd_src','t','crowd','NONE',false,'t',5)
                           RETURNING source_id""")
            row = cur.fetchone()
        cur.execute("""INSERT INTO state_observation
                         (place_id, state_kind, value, observed_at, source_id,
                          confidence, modality, attrs)
                       VALUES (%s,'checkpoint_status','open',%s,%s,0.5,
                               'assertion','{"crowd": true}')""",
                    (place_id, T0 + timedelta(minutes=10), row[0]))

    _v1(v1, [(key, "closed", 2, _iso(T0 + timedelta(minutes=5)), "حاجز اختبار مغلق")])
    s = checkpoints.import_updates()
    assert s["legacy"] == 1, "the v1 report filed before the crowd report was skipped"
    assert [m for _, m in legacy_rows()] == ["1", "2"]


def test_a_late_v1_row_is_imported_and_nothing_is_imported_twice(importer):
    """F007. A v1 row that arrives after a newer one (catch-up, clock skew)
    lands below the cursor. It must still be imported, and the rows already
    imported must not be imported again."""
    checkpoints, v1, key, _pid, legacy_rows = importer
    _v1(v1, [(key, "open", 10, _iso(T0), "حاجز اختبار سالك"),
             (key, "open", 12, _iso(T0 + timedelta(minutes=20)), "حاجز اختبار سالك")])
    checkpoints.import_updates()
    _v1(v1, [(key, "closed", 11, _iso(T0 + timedelta(minutes=10)), "حاجز اختبار مغلق")])
    s = checkpoints.import_updates()
    assert s["legacy"] == 1
    assert [m for _, m in legacy_rows()] == ["10", "11", "12"]


@pytest.mark.parametrize("sep,frac", [("T", True), (" ", False)])
def test_the_cursor_does_not_depend_on_how_v1_spells_a_timestamp(importer, sep, frac):
    """F125. With sub-second stamps the whole-second string cursor re-read
    the newest second on every tick and inserted it again; with a space
    separator every later same-day row sorted BELOW the 'T' cursor and was
    skipped. Either way the answer depended on a format v2 does not control."""
    checkpoints, v1, key, _pid, legacy_rows = importer
    _v1(v1, [(key, "open", 20, _iso(T0, sep, frac), "حاجز اختبار سالك")])
    checkpoints.import_updates()
    again = checkpoints.import_updates()
    assert again["legacy"] == 0, "the boundary row was imported a second time"
    _v1(v1, [(key, "closed", 21, _iso(T0 + timedelta(hours=2), sep, frac),
              "حاجز اختبار مغلق")])
    later = checkpoints.import_updates()
    assert later["legacy"] == 1, "a later same-day row was skipped"
    assert [m for _, m in legacy_rows()] == ["20", "21"]


# ── one Telethon client per session file (F214) ──────────────────────────────
#
# HANDOFF rule 4 was enforced by nothing: discovery, `setup_session --status`
# and the poller's CLI modes all opened the live session while the service
# might be running. The lock is tested across two real processes, because a
# lock that only excludes its own process excludes nothing.

def _hold(session: Path):
    code = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        from ingest.setup_session import session_lock
        with session_lock({str(session)!r}, 'test-holder'):
            print('held', flush=True)
            sys.stdin.read()
    """)
    p = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def _release(p) -> None:
    p.stdin.close()
    p.wait(timeout=10)


def test_a_second_process_is_refused_and_told_who_holds_the_session(tmp_path):
    from ingest.setup_session import SessionBusy, session_lock
    session = tmp_path / "v2_ingest"
    p = _hold(session)
    try:
        with pytest.raises(SessionBusy) as exc:
            with session_lock(session, "second"):
                pass
        assert f"pid {p.pid}" in str(exc.value) and "test-holder" in str(exc.value)
    finally:
        _release(p)
    # The kernel releases a flock when its holder exits: no stale lock.
    with session_lock(session, "after"):
        pass


def test_the_lock_is_reentrant_within_one_process(tmp_path):
    from ingest.setup_session import session_lock
    session = tmp_path / "v2_ingest"
    with session_lock(session, "outer"):
        with session_lock(session, "inner"):
            pass
        p = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(f"""
                import sys; sys.path.insert(0, {str(ROOT)!r})
                from ingest.setup_session import SessionBusy, session_lock
                try:
                    with session_lock({str(session)!r}, 'x'):
                        print('got it')
                except SessionBusy:
                    print('refused')
            """)], capture_output=True, text=True, timeout=30)
        assert p.stdout.strip() == "refused", "leaving the inner block released the lock"


class _NoClient:
    """A telethon stand-in whose client must never be built."""

    def __init__(self, *a, **k):
        raise AssertionError("a Telegram client was built on a session "
                             "another process holds")


def _fake_telethon(monkeypatch):
    import types
    tl = types.ModuleType("telethon")
    errors = types.ModuleType("telethon.errors")
    for name in ("FloodWaitError", "PhoneCodeExpiredError",
                 "PhoneCodeInvalidError", "SessionPasswordNeededError"):
        setattr(errors, name, type(name, (Exception,), {}))
    tl.TelegramClient, tl.errors, tl.functions = _NoClient, errors, object()
    monkeypatch.setitem(sys.modules, "telethon", tl)
    monkeypatch.setitem(sys.modules, "telethon.errors", errors)


CREDS = {"V2_TELEGRAM_API_ID": "1", "V2_TELEGRAM_API_HASH": "x",
         "V2_TELEGRAM_PHONE": "+970500000000"}


def test_discovery_refuses_while_the_session_is_held(tmp_path, monkeypatch):
    from ingest import discover_channels as dc
    session = tmp_path / "v2_ingest"
    Path(f"{session}.session").write_bytes(b"")
    _fake_telethon(monkeypatch)
    monkeypatch.setattr(dc, "SESSION", session, raising=False)
    monkeypatch.setattr(dc, "ROOT", tmp_path)         # the old code built its path from ROOT
    (tmp_path / "data" / "session").mkdir(parents=True)
    Path(f"{tmp_path / 'data' / 'session' / 'v2_ingest'}.session").write_bytes(b"")
    monkeypatch.setattr(dc, "_env", lambda: dict(CREDS))
    monkeypatch.setattr(dc, "v1_channels", lambda: set())
    monkeypatch.setattr(sys, "argv", ["discover_channels", "--category", "fuel"])
    p = _hold(session)
    try:
        assert dc.main() == 1
    finally:
        _release(p)


def test_setup_session_status_refuses_while_the_session_is_held(tmp_path, monkeypatch):
    """`--status` is the command an operator reaches for while the poller
    runs — which is exactly when it must not open the session."""
    from ingest import setup_session as ss
    session = tmp_path / "v2_ingest"
    Path(f"{session}.session").write_bytes(b"")
    _fake_telethon(monkeypatch)
    monkeypatch.setattr(ss, "SESSION", session)
    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "_env", lambda: dict(CREDS))
    monkeypatch.setattr(sys, "argv", ["setup_session", "--status"])
    p = _hold(session)
    try:
        assert ss.main() == 1
    finally:
        _release(p)


# ── the RSS reader must be able to fail (F216) ───────────────────────────────
#
# A dead feed printed FEED FAILED and main() returned 0, so ops/ingest-
# external.sh — which counts a step as failed only on a non-zero exit —
# recorded success, and the one independent newsroom in the corroboration
# model could vanish without an alarm.

def _rss(tx, monkeypatch, fetch):
    from ingest.sources import rss_news
    monkeypatch.setattr(rss_news, "connect", lambda: _NoCommit(tx))
    monkeypatch.setattr(rss_news, "fetch", fetch)
    monkeypatch.setattr(sys, "argv", ["rss_news", "--dry-run"])
    return rss_news


def test_a_feed_that_cannot_be_fetched_fails_the_run(tx, monkeypatch):
    def fetch(feed):
        raise ConnectionError(f"{feed['url']} moved")
    assert _rss(tx, monkeypatch, fetch).main() == 1


def test_a_feed_with_no_items_fails_the_run(tx, monkeypatch):
    """A live news feed always carries items; an empty one is a moved or
    broken feed answering 200."""
    assert _rss(tx, monkeypatch, lambda feed: []).main() == 1


def test_rss_timestamps_and_ids():
    import xml.etree.ElementTree as ET
    from ingest.sources.rss_news import _external_id, _parsed_at

    def item(xml):
        return ET.fromstring(f"<item>{xml}</item>")
    assert _parsed_at(item("<pubDate>Wed, 24 Sep 2026 10:00:00 +0300</pubDate>")) \
        == datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)
    naive = _parsed_at(item("<pubDate>2026-09-24T10:00:00</pubDate>"))
    assert naive.tzinfo is not None and naive.hour == 10
    before = datetime.now(timezone.utc)
    assert _parsed_at(item("<pubDate>not a date</pubDate>")) >= before
    assert _external_id(item("<guid> g-1 </guid><link>l</link>"), "rss_x") == "g-1"
    assert _external_id(item("<link>https://x/1</link>"), "rss_x") == "https://x/1"
    a = _external_id(item("<title>خبر</title>"), "rss_x")
    assert a.startswith("rss_x:") and a == _external_id(item("<title>خبر</title>"), "rss_x")
