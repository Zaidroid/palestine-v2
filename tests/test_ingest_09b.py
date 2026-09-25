"""Audit 2026-09-25, area 09 — INGEST-02 03 06 08 09 11 (05 and 07 are Zaid's decisions)."""
from __future__ import annotations

import fcntl
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import session_lock, telegram_poller as TP                        # noqa: E402
from ingest.sources import news_incidents as NI, palhub_loader as PL         # noqa: E402


def test_ingest_02_one_client_per_session_file(tmp_path):
    sess = tmp_path / "v2_ingest"
    session_lock.acquire(sess, who="test")
    assert (tmp_path / "v2_ingest.lock").read_text().startswith("pid ")
    with open(tmp_path / "v2_ingest.lock", "a+") as other:          # a second opener
        with pytest.raises(BlockingIOError):
            fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    session_lock.acquire(sess, who="test")                           # idempotent in-process
    session_lock.release(sess)
    with open(tmp_path / "v2_ingest.lock", "a+") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # free again
    for mod in ("ingest/telegram_poller.py", "ingest/setup_session.py", "ingest/discover_channels.py"):
        assert "session_lock import" in (ROOT / mod).read_text(), mod


def test_ingest_03_no_media_channel_without_a_reader():
    assert TP.MEDIA_CHANNELS == set()


def test_ingest_08_deauthorised_is_exit_2_and_recognised_everywhere():
    class AuthKeyUnregisteredError(Exception): ...
    class FloodWaitError(Exception): ...
    assert TP._is_deauth(AuthKeyUnregisteredError("x")) and not TP._is_deauth(FloodWaitError("x"))
    src = inspect.getsource(TP.run)
    head = src[:src.index("me = await client.get_me()")]
    assert "return 2" in head and "return 1\n" not in head.split("is_user_authorized")[1]
    assert "_is_deauth(exc)" in src and "client._authorized = None" in inspect.getsource(TP._reconnect)


def test_ingest_09_the_database_is_checked_first_and_a_batch_survives_a_failed_store(monkeypatch):
    src = inspect.getsource(TP.run)
    assert src.index("_db_reachable()") < src.index("total, failures, moved = 0, 0, False")
    assert "pending[ch] = (fresh, refs)" in src and "fresh, refs = pending.pop(ch)" in src
    monkeypatch.setattr(TP, "connect", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert TP._db_reachable() is False


def test_ingest_06_a_forwarded_report_is_its_origins_voice():
    src = inspect.getsource(NI.classify)
    assert "'fwd:' || (c.attrs->>'fwd_from')" in src


def test_ingest_11_the_station_anchor_prefers_a_locality():
    assert '{"prefer_kind": "locality"}' in inspect.getsource(PL)
