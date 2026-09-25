"""The poller's catch-up path — the half of P3.1 that is about not losing data.

    ./.venv/bin/python -m pytest tests/test_poller.py -q

These run against a fake client. Exercising the real one would spend requests
on the agent2 account, which is the scarcest asset in the project and the one
thing here that cannot be replaced by rerunning something.

WHAT THEY GUARD
After the 8-hour outage on 2026-08-01 the poller recovered 362 messages, 80 of
them on the busiest channel — against a page size of 100. Twenty more and the
recovery would have silently dropped the difference: get_messages returns the
NEWEST hundred, the caller advances its cursor to the newest id it saw, and
everything below the page boundary is skipped permanently with nothing
reporting it. The margin was twenty messages.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import telegram_poller                             # noqa: E402
from ingest.telegram_poller import MAX_PAGES, PAGE, _fetch_since   # noqa: E402

# The inter-page pause is real and deliberate (see PAGE_PAUSE); waiting through
# it here would cost 73 seconds to assert nothing about it.
telegram_poller.PAGE_PAUSE = 0


class Msg:
    def __init__(self, i): self.id = i


class FakeChannel:
    """Serves messages the way Telegram does: a window of at most `limit`,
    taken from the newest end unless reverse=True asks for the oldest."""

    def __init__(self, ids):
        self.ids = sorted(ids)
        self.calls = []

    async def get_messages(self, ent, limit=100, min_id=0, reverse=False, **kw):
        self.calls.append({"limit": limit, "min_id": min_id, "reverse": reverse})
        above = [i for i in self.ids if i > min_id]
        window = above[:limit] if reverse else above[-limit:][::-1]
        return [Msg(i) for i in window]


def fetch(ids, last=0):
    ch = FakeChannel(ids)
    got = asyncio.run(_fetch_since(ch, object(), last))
    return [m.id for m in got], ch


# ── the ordinary case ────────────────────────────────────────────────────────

def test_a_small_batch_arrives_in_one_page():
    ids, ch = fetch(range(1, 11))
    assert ids == list(range(1, 11))
    assert len(ch.calls) == 1, "no reason to make a second request"


def test_nothing_new_makes_one_request_and_stops():
    ids, ch = fetch(range(1, 11), last=10)
    assert ids == []
    assert len(ch.calls) == 1


def test_messages_at_or_below_the_cursor_are_not_refetched():
    ids, _ = fetch(range(1, 21), last=15)
    assert ids == [16, 17, 18, 19, 20]


# ── the case that nearly bit ─────────────────────────────────────────────────

def test_a_backlog_larger_than_one_page_is_fetched_whole():
    """The actual bug. 250 messages against a 100-message page: the old code
    returned the newest 100 and the caller then advanced past the other 150."""
    n = PAGE * 2 + 50
    ids, ch = fetch(range(1, n + 1))
    assert ids == list(range(1, n + 1)), "a page boundary must not lose messages"
    assert len(ch.calls) == 3


def test_the_fetch_is_contiguous_with_no_hole_below_the_cursor():
    """What makes truncation safe is that the collected run has no gaps. If it
    did, the caller's `state[ch] = max(id)` would step over the hole and the
    missing messages would never be requested again."""
    ids, _ = fetch(range(1, PAGE * 3 + 7))
    assert ids == sorted(ids)
    assert ids == list(range(min(ids), max(ids) + 1))


def test_paging_runs_oldest_first():
    """Direction is not cosmetic: it is the reason an interrupted catch-up
    leaves the cursor at the end of an unbroken run instead of above a hole."""
    _, ch = fetch(range(1, PAGE * 2 + 1))
    assert all(c["reverse"] for c in ch.calls)
    # Each page resumes where the last ended, never from 0. An exactly-full
    # final page costs one more request to learn there is nothing after it,
    # which is the correct trade: the alternative is guessing.
    assert [c["min_id"] for c in ch.calls] == [0, PAGE, PAGE * 2]


def test_the_page_cap_defers_the_remainder_instead_of_dropping_it():
    """Hitting the cap must leave the caller able to resume. The returned run
    stops at a clean edge, so `max(id)` is the end of everything seen and the
    rest is still above the cursor next cycle."""
    total = PAGE * (MAX_PAGES + 5)
    ids, ch = fetch(range(1, total + 1))
    assert len(ch.calls) == MAX_PAGES, "the cap must actually bound the work"
    assert ids == list(range(1, PAGE * MAX_PAGES + 1))
    # The next cycle resumes exactly where this one stopped — nothing skipped.
    rest, _ = fetch(range(1, total + 1), last=max(ids))
    assert rest[0] == max(ids) + 1


def test_resuming_after_the_cap_eventually_collects_everything():
    """Follow the cursor to convergence, the way the loop does."""
    total = PAGE * MAX_PAGES * 2
    seen, cursor = [], 0
    for _ in range(5):
        ids, _ = fetch(range(1, total + 1), last=cursor)
        if not ids:
            break
        seen += ids
        cursor = max(ids)
    assert seen == list(range(1, total + 1))


# ── gaps in the id space, which Telegram produces on deletion ────────────────

def test_deleted_message_ids_do_not_stall_the_cursor():
    """Telegram ids skip over deletions and service messages. Paging must
    advance on what it RECEIVED, not on an assumed contiguous id space, or a
    channel with a deleted message loops on the same page forever."""
    ids = [i for i in range(1, PAGE * 2 + 20) if i % 7]
    got, ch = fetch(ids)
    assert got == ids
    assert len(ch.calls) <= 3


# ── audit 2026-09-25 (plan 09-ingest): the account-safety paths ─────────────
# Telethon is never imported: a fake FloodWaitError is recognised by class
# name exactly as the real one is.
import types                                                   # noqa: E402


class FloodWaitError(Exception):
    def __init__(self, seconds):
        super().__init__(f"A wait of {seconds} seconds is required")
        self.seconds = seconds


class Photo:
    def __init__(self, i):
        self.id, self.photo = i, object()


def test_ingest_f042_a_flood_during_media_download_reaches_the_poll_loop(monkeypatch):
    """It was swallowed: the batch was stored without media and the cursor
    moved past it. Now it propagates, so the loop sleeps and stores nothing.
    MEDIA_CHANNELS is empty since F217; the path is exercised with one added."""
    monkeypatch.setattr(telegram_poller, "MEDIA_CHANNELS", {"palhubappfuel"})
    class Client:
        calls = 0

        async def download_media(self, m, file=None):
            Client.calls += 1
            raise FloodWaitError(600)
    import pytest
    with pytest.raises(FloodWaitError):
        asyncio.run(telegram_poller.archive_media(Client(), "palhubappfuel",
                                                  [Photo(1), Photo(2), Photo(3)]))
    assert Client.calls == 1


def test_ingest_f224_a_flood_while_resolving_stops_the_round(monkeypatch):
    """The third ResolveUsername flooded and the loop fired the fourth, fifth…
    1.5 s later, inside the window."""
    monkeypatch.setattr(telegram_poller, "RESOLVE_PAUSE", 0)
    asked = []

    class Client:
        async def get_entity(self, ch):
            asked.append(ch)
            if ch == "c":
                raise FloodWaitError(1800)
            return ch
    ents: dict = {}
    left, not_before = asyncio.run(telegram_poller._resolve(Client(), list("abcde"), ents))
    assert asked == ["a", "b", "c"]
    assert left == ["c", "d", "e"] and set(ents) == {"a", "b"}
    import time
    assert not_before > time.monotonic() + 1700


def _fake_telethon(monkeypatch, client_cls):
    tele = types.ModuleType("telethon")
    tele.TelegramClient = client_cls
    errs = types.ModuleType("telethon.errors")
    errs.FloodWaitError = FloodWaitError
    monkeypatch.setitem(sys.modules, "telethon", tele)
    monkeypatch.setitem(sys.modules, "telethon.errors", errs)


def test_ingest_f226_nothing_resolved_is_a_failure_not_a_quiet_cycle(monkeypatch, tmp_path):
    """With every get_entity failing, the poller beat healthy (channels=0)
    forever and nothing re-resolved."""
    class Client:
        def __init__(self, *a, **k): pass
        async def connect(self): pass
        async def is_user_authorized(self): return True
        async def get_me(self): return types.SimpleNamespace(first_name="t", id=1)
        async def get_entity(self, ch): raise ValueError("Cannot find any entity")
        def is_connected(self): return True
        async def disconnect(self): pass
    _fake_telethon(monkeypatch, Client)
    monkeypatch.setattr(telegram_poller, "_env", lambda: {
        "V2_TELEGRAM_API_ID": "1", "V2_TELEGRAM_API_HASH": "h",
        "V2_TELEGRAM_CHANNELS": "a,b", "V2_POLL_INTERVAL": "30"})
    monkeypatch.setattr(telegram_poller, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(telegram_poller, "RESOLVE_PAUSE", 0)
    seen = []
    monkeypatch.setattr(telegram_poller, "beat", lambda *a, **k: seen.append("beat"))
    monkeypatch.setattr(telegram_poller, "fail", lambda *a, **k: seen.append("fail"))
    asyncio.run(telegram_poller.run(once=True))
    assert seen == ["fail"]


def test_ingest_f218_the_cursor_file_is_replaced_not_truncated(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_poller, "STATE", tmp_path / "state.json")
    telegram_poller._save_state({"a": 5})
    import inspect
    assert telegram_poller._load_state() == {"a": 5}
    assert "os.replace" in inspect.getsource(telegram_poller._save_state)
