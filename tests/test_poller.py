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
import json
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


# ══ the account-safety paths, against a fake Telethon ════════════════════════
#
# Nothing below constructs a real client: `telethon` itself is replaced in
# sys.modules by a stand-in whose errors mirror Telethon 1.36's hierarchy
# (FloodWaitError < FloodError < RPCError; the 401 family < UnauthorizedError;
# AUTH_KEY_DUPLICATED < AuthKeyError), because the behaviour under test is
# which of those the poller treats as "wait", "this channel" and "stop".

import types                                                    # noqa: E402

import pytest                                                   # noqa: E402


class RPCError(Exception):
    pass


class UnauthorizedError(RPCError):
    pass


class AuthKeyUnregisteredError(UnauthorizedError):
    pass


class AuthKeyError(RPCError):
    pass


class AuthKeyDuplicatedError(AuthKeyError):
    pass


class FloodError(RPCError):
    pass


class FloodWaitError(FloodError):
    def __init__(self, request=None, capture=0):
        self.seconds = int(capture)
        super().__init__(f"A wait of {self.seconds} seconds is required")


class Me:
    first_name, id = "agent2", 1


class Ent:
    def __init__(self, name):
        self.username = name


class Photo(Msg):
    def __init__(self, i):
        super().__init__(i)
        self.photo = object()


class FakeClient:
    """One Telegram, scripted per test. `script` maps a method to a list of
    exceptions raised in order before it starts answering normally."""

    def __init__(self, history=None, me=Me(), script=None):
        self.history = history or {}
        self.me = me
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[tuple] = []
        self.connected = False
        self.built = 0

    # TelegramClient(session, api_id, api_hash) — the poller calls the class.
    def __call__(self, *_a, **_k):
        self.built += 1
        return self

    def _raise(self, name):
        pending = self.script.get(name)
        if pending:
            raise pending.pop(0)

    async def connect(self):
        self.calls.append(("connect",))
        self.connected = True

    def is_connected(self):
        return self.connected

    async def is_user_authorized(self):      # the cached flag the old code read
        return self.me is not None

    async def get_me(self):
        self.calls.append(("get_me",))
        self._raise("get_me")
        return self.me

    async def get_entity(self, ch):
        self.calls.append(("get_entity", ch))
        self._raise(f"get_entity:{ch}")
        return Ent(ch)

    async def get_messages(self, ent, limit=100, min_id=0, reverse=False, **kw):
        self.calls.append(("get_messages", ent.username, min_id))
        self._raise("get_messages")
        ids = sorted(i for i in self.history.get(ent.username, []) if i > min_id)
        window = ids[:limit] if reverse else ids[-limit:][::-1]
        return [Msg(i) for i in window]

    async def download_media(self, m, file=None):
        self.calls.append(("download_media", m.id))
        self._raise("download_media")
        return b"\xff\xd8jpeg"

    async def disconnect(self):
        self.connected = False

    def called(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture()
def tg(monkeypatch, tmp_path):
    """The poller wired to a fake Telegram, a fake database and a temp state
    directory. Returns a namespace the test drives and inspects."""
    tp = telegram_poller
    ns = types.SimpleNamespace(beats=[], fails=[], stored=[], naps=[],
                               sleeps=[], seeds={}, client=FakeClient(),
                               db_up=True, stop_after_beats=None, on_nap=None,
                               clock=[1000.0])

    errors = types.ModuleType("telethon.errors")
    for cls in (RPCError, UnauthorizedError, AuthKeyUnregisteredError,
                AuthKeyError, AuthKeyDuplicatedError, FloodError,
                FloodWaitError):
        setattr(errors, cls.__name__, cls)
    telethon = types.ModuleType("telethon")
    telethon.errors = errors
    telethon.TelegramClient = lambda *a, **k: ns.client(*a, **k)
    monkeypatch.setitem(sys.modules, "telethon", telethon)
    monkeypatch.setitem(sys.modules, "telethon.errors", errors)

    monkeypatch.setattr(tp, "SESSION", tmp_path / "v2_ingest")
    monkeypatch.setattr(tp.bronze, "BRONZE", tmp_path / "bronze")
    # Naps advance a fake clock, so "retry in 30 minutes" is testable without
    # waiting for it and a flood's window really has passed after the nap.
    monkeypatch.setattr(tp, "time", types.SimpleNamespace(
        monotonic=lambda: ns.clock[0], time=__import__("time").time),
        raising=False)
    monkeypatch.setattr(tp, "STATE", tmp_path / "poller_state.json")
    monkeypatch.setattr(tp, "_stop", False)
    monkeypatch.setattr(tp, "_env", lambda: {
        "V2_TELEGRAM_API_ID": "1", "V2_TELEGRAM_API_HASH": "x",
        "V2_TELEGRAM_CHANNELS": "chan_a,chan_b", "V2_POLL_INTERVAL": "30"})

    def beat(name, interval=None, grace=None, detail=None):
        ns.beats.append({"interval": interval, "grace": grace, **(detail or {})})
        if ns.stop_after_beats and len(ns.beats) >= ns.stop_after_beats:
            tp._stop = True
        return True

    def fail(name, error, interval=None, grace=None):
        ns.fails.append(error)
        return True

    def store(channel, messages, media_refs=None):
        if not ns.db_up:
            raise ConnectionError("database is down")
        ns.stored.append((channel, [m.id for m in messages]))
        return len(messages)

    class DeadDB:
        def __enter__(self):
            raise ConnectionError("database is down")

        def __exit__(self, *a):
            return False

    class LiveDB:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return self

        def execute(self, *a):
            pass

        def fetchone(self):
            return (1,)

    monkeypatch.setattr(tp, "beat", beat)
    monkeypatch.setattr(tp, "fail", fail)
    monkeypatch.setattr(tp, "store", store)
    monkeypatch.setattr(tp, "connect", lambda: LiveDB() if ns.db_up else DeadDB())
    monkeypatch.setattr(tp, "_stored_cursor", lambda ch: ns.seeds.get(ch, 0),
                        raising=False)

    async def nap(seconds):
        ns.naps.append(seconds)
        ns.clock[0] += seconds
        if ns.on_nap:
            ns.on_nap(seconds)
    monkeypatch.setattr(tp, "_nap", nap, raising=False)

    # The pre-fix poller slept with asyncio.sleep directly; recorded the same
    # way so a regression is caught rather than waited through.
    real_sleep = asyncio.sleep

    async def sleep(seconds, *a, **k):
        ns.sleeps.append(seconds)
        if ns.on_nap:
            ns.on_nap(seconds)
        await real_sleep(0)
    monkeypatch.setattr(tp.asyncio, "sleep", sleep)

    ns.run = lambda once=True, backfill=0: asyncio.run(tp.run(once, backfill))
    return ns


# ── exit 2: the session is gone (F224) ───────────────────────────────────────

def test_an_unauthorised_session_at_startup_exits_2(tg):
    """RestartPreventExitStatus=2 is the unit's only defence against
    reconnecting a dead session forever. Startup returned 1, which systemd
    restarts every 30 s to 15 min with an alarm each time."""
    tg.client = FakeClient(me=None)
    assert tg.run() == 2
    assert tg.fails and "authoris" in tg.fails[-1]
    assert not tg.client.called("get_entity"), "nothing is resolved on a dead session"


def test_a_session_revoked_mid_run_exits_2_at_once(tg):
    """A revocation arrives as AUTH_KEY_UNREGISTERED on the next request. It
    was counted as a failure of every channel, three cycles later the poller
    exited 1, and the restart loop began."""
    tg.client = FakeClient(history={"chan_a": [1], "chan_b": [1]},
                           script={"get_messages": [AuthKeyUnregisteredError("revoked")]})
    tg.stop_after_beats = 5          # bounds the pre-fix loop, which never exits
    assert tg.run(once=False) == 2
    assert len(tg.client.called("get_messages")) == 1, \
        "no further request may be made on a session Telegram has revoked"


def test_auth_key_duplicated_is_a_lost_session_not_a_channel_failure(tg):
    """AUTH_KEY_DUPLICATED is what two clients on one session earn."""
    tg.client = FakeClient(history={"chan_a": [1]},
                           script={"get_messages": [AuthKeyDuplicatedError("dup")]})
    tg.stop_after_beats = 5
    assert tg.run(once=False) == 2


def test_reconnect_asks_telegram_rather_than_a_cached_flag(tg):
    """Telethon caches is_user_authorized() for the life of the client and
    connect() never resets it, so the old check could not see a revocation."""
    tg.client = FakeClient(me=None)
    tg.client.is_user_authorized = lambda: _true()       # the stale cached answer
    with pytest.raises(telegram_poller.Deauthorised):
        asyncio.run(telegram_poller._reconnect(tg.client))


async def _true():
    return True


# ── FloodWait, wherever a request is made (rule 3) ───────────────────────────

def test_a_flood_while_resolving_stops_resolving(tg):
    """F225. The old loop printed the flood and resolved the next handle 1.5 s
    later — a request inside the window the flood forbade — and then left the
    rest UNRESOLVED for the life of the process."""
    tg.client = FakeClient(history={"chan_a": [], "chan_b": []},
                           script={"get_entity:chan_a": [FloodWaitError(capture=600)]})
    order = []
    tg.on_nap = lambda s: order.append(("nap", s))
    orig = tg.client.get_entity

    async def get_entity(ch):
        order.append(("get_entity", ch))
        return await orig(ch)
    tg.client.get_entity = get_entity
    assert tg.run() == 0
    first_nap = next((i for i, o in enumerate(order) if o[0] == "nap" and o[1] >= 600),
                     len(order))
    assert ("get_entity", "chan_b") not in order[:first_nap], \
        "a second ResolveUsername was issued inside the flood window"
    assert {c[1] for c in tg.client.called("get_messages")} == {"chan_a", "chan_b"}


def test_zero_resolved_channels_is_a_failure_not_a_healthy_heartbeat(tg):
    """F227. `{}` made `entities and ...` falsy, so every cycle beat
    channels=0 — healthy to systemd, /health and the watchdog."""
    tg.client = FakeClient(script={"get_entity:chan_a": [ValueError("no such user")],
                                   "get_entity:chan_b": [ValueError("no such user")]})
    assert tg.run() == 1
    assert tg.fails, "the failure must be recorded"
    assert not any(b.get("channels") == 0 for b in tg.beats)


def test_an_unresolved_channel_is_retried_and_named_in_the_heartbeat(tg, monkeypatch):
    """F227. A channel that failed to resolve at startup was never revisited."""
    monkeypatch.setattr(telegram_poller, "RESOLVE_RETRY", 0, raising=False)
    tg.client = FakeClient(history={"chan_a": [1], "chan_b": [5]},
                           script={"get_entity:chan_b": [ValueError("timeout"),
                                                         ValueError("timeout")]})
    tg.stop_after_beats = 2
    assert tg.run(once=False) == 0
    assert tg.beats[0]["unresolved"] == ["chan_b"]
    assert tg.beats[1]["unresolved"] == []
    assert ("chan_b", [5]) in tg.stored, "the retried channel was never read"


def test_the_flood_beat_carries_a_grace_longer_than_the_wait(tg):
    """F482. With the fixed 900 s grace, a one-hour flood read as `not_running`
    after 15 minutes — whose reflex is a restart that re-issues the request
    the flood forbade."""
    tg.client = FakeClient(history={"chan_a": [1], "chan_b": [1]},
                           script={"get_messages": [FloodWaitError(capture=3600)]})
    tg.run()
    flood = [b for b in tg.beats if b.get("flood_wait_seconds") == 3600]
    assert flood and flood[0]["grace"] > 3600 + 30
    assert any(s >= 3600 for s in tg.naps + tg.sleeps), "the wait was not honoured"
    assert tg.beats[-1]["grace"] == telegram_poller._GRACE, "grace is restored"


def test_a_flood_during_a_media_download_is_not_swallowed(tg, monkeypatch):
    """Swallowed per photo, the flood let the caller store the batch and step
    its cursor past every photo it never downloaded. Raised, the batch is
    fetched again whole after the wait."""
    monkeypatch.setattr(telegram_poller, "MEDIA_CHANNELS", frozenset({"chan_a"}))
    client = FakeClient(script={"download_media": [FloodWaitError(capture=120)]})
    with pytest.raises(FloodWaitError):
        asyncio.run(telegram_poller.archive_media(
            client, "chan_a", [Photo(i) for i in range(1, 6)]))
    assert len(client.called("download_media")) == 1


def test_the_retired_fuel_channel_downloads_no_media(tg):
    """F218. The image vertical was retired on 2026-09-23; its channel still
    cost up to 150 GetFile requests a cycle on the scarcest account."""
    client = FakeClient()
    refs, cutoff = asyncio.run(telegram_poller.archive_media(
        client, "palhubappfuel", [Photo(i) for i in range(1, 6)]))
    assert refs == {} and cutoff is None
    assert not client.called("download_media")


# ── a database outage is not a channel failure (F226) ────────────────────────

def test_a_database_outage_at_startup_never_touches_telegram(tg):
    tg.db_up = False
    tg.client = FakeClient(history={"chan_a": [1, 2, 3]})
    assert tg.run() == 1
    assert tg.client.built == 0 and not tg.client.calls


def test_a_database_outage_mid_run_stops_fetching_and_exits(tg):
    """The poller fetched up to 20 pages a channel (and every photo) per cycle
    for work it could not store, and a channel with nothing new never counted
    as a failure, so the three-cycle exit might never fire."""
    tg.client = FakeClient(history={"chan_a": [1], "chan_b": [1]})
    fetched = []

    def outage(seconds):
        fetched.append(len(tg.client.called("get_messages")))
        tg.db_up = False
    tg.on_nap = lambda s: outage(s) if s == 30 else None
    tg.stop_after_beats = 6          # bounds the pre-fix loop, which never exits
    assert tg.run(once=False) == 1
    assert len(tg.client.called("get_messages")) == fetched[0], \
        "Telegram was polled while nothing could be stored"
    assert tg.fails


# ── the cursor file (F219) ───────────────────────────────────────────────────

def test_a_corrupt_state_file_resumes_from_the_stored_claims_not_from_zero(tg):
    """A torn write read back as {}, every channel restarted at min_id=0, and
    the whole history was walked 2,000 messages a cycle."""
    telegram_poller.STATE.write_text('{"chan_a": 41')        # torn mid-write
    tg.seeds = {"chan_a": 900, "chan_b": 700}
    tg.client = FakeClient(history={"chan_a": [899, 900, 901], "chan_b": [701]})
    tg.run()
    mins = {c[1]: c[2] for c in tg.client.called("get_messages")}
    assert mins == {"chan_a": 900, "chan_b": 700}
    assert list(telegram_poller.STATE.parent.glob("poller_state.json.corrupt-*")), \
        "the unreadable file is kept, not overwritten"


def test_a_cursor_advanced_by_an_all_duplicate_batch_is_saved_that_cycle(tg, monkeypatch):
    """Saved only when a claim was WRITTEN, so a batch that deduplicated to
    zero advanced the cursor in memory only; a SIGKILL then lost it."""
    tg.client = FakeClient(history={"chan_a": [1, 2, 3], "chan_b": [4]})
    monkeypatch.setattr(telegram_poller, "store",
                        lambda ch, msgs, refs=None: 0)          # all duplicates
    on_disk = []

    def check(seconds):
        if seconds == 30:             # the inter-cycle sleep: where a kill lands
            p = telegram_poller.STATE
            on_disk.append(json.loads(p.read_text()) if p.exists() else {})
            telegram_poller._stop = True
    tg.on_nap = check
    tg.run(once=False)
    assert on_disk and on_disk[0] == {"chan_a": 3, "chan_b": 4}


def test_the_state_file_is_replaced_whole_or_not_at_all(tg, monkeypatch):
    telegram_poller._save_state({"chan_a": 5})

    def torn(fd):
        raise OSError("power cut")
    monkeypatch.setattr(telegram_poller.os, "fsync", torn)
    with pytest.raises(OSError):
        telegram_poller._save_state({"chan_a": 6})
    assert json.loads(telegram_poller.STATE.read_text()) == {"chan_a": 5}
    assert list(telegram_poller.STATE.parent.iterdir()) == [telegram_poller.STATE]


# ── one client per session file (F214) ───────────────────────────────────────

def test_the_poller_refuses_to_open_a_session_another_process_holds(tg):
    held = _hold_lock_in_another_process(str(telegram_poller.SESSION))
    try:
        tg.client = FakeClient(history={"chan_a": [1]})
        assert tg.run() == 1
        assert tg.client.built == 0, "a second client was built on a held session"
    finally:
        held.stdin.close()
        held.wait(timeout=10)


def _hold_lock_in_another_process(session: str):
    import subprocess
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from ingest.setup_session import session_lock\n"
            "with session_lock(%r, 'test-holder'):\n"
            "    print('held', flush=True); sys.stdin.read()\n") % (str(ROOT), session)
    p = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p
