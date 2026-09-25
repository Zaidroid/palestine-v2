"""v2 Telegram poller — reads public channels on the agent2 account.

Writes every message straight into `claim`, the immutable layer: what a source
SAID, before anything decides what it means. Classification comes later and
never rewrites this.

    ./.venv/bin/python -m ingest.telegram_poller            # run forever
    ./.venv/bin/python -m ingest.telegram_poller --once     # one pass
    ./.venv/bin/python -m ingest.telegram_poller --backfill 50

ACCOUNT SAFETY — agent2 was registered hours ago and is the most rate-limit
fragile thing in this system; v1's Taqwa account is seasoned and therefore
safer per action. Accordingly:
  * Public channels are READ via get_entity/get_messages. Nothing is joined.
    Joining is the action that looks like scraping.
  * Poll interval defaults to 30s (v1 uses 5s) and channels are staggered.
  * FloodWaitError is caught, respected, and reported — never retried blindly.
    That holds wherever a request is made: startup, channel resolution, the
    history fetch, a media download, a reconnect.
  * One client per session file. run() holds ingest.setup_session's lock for
    its whole life, and discovery and setup_session take the same lock, so a
    second client on the live session refuses instead of starting.
  * A per-channel failure never stops the loop; one dead handle must not take
    the poller down (v1 carries a dead `Almasshta` that errors every startup).
    A channel that does not resolve is retried on a doubling schedule.

RECONNECTION, AND WHY IT IS NOT JUST A RETRY (added 2026-08-01, after a live
8-hour outage). A network blip at 08:35 exhausted Telethon's own connection
retries. The client then stayed permanently disconnected while THIS loop kept
running: every 30 seconds it called into the dead client, caught "Cannot send
requests while disconnected" in the per-channel handler above, printed it, and
carried on. systemd reported `active (running)` the whole time. The news
classifier ran every 5 minutes and cheerfully reported "read 0 unclassified
claims". Nothing anywhere said the feed was dark.

That is the same failure this project keeps finding in its data: the thing still
looks fine and its meaning has been lost. The per-channel handler exists so one
dead CHANNEL cannot stop the loop, and it silently absorbed one dead CLIENT.

So the loop now distinguishes the two. A transport failure is not a channel
failure: it is checked before the channel loop, repaired with backoff, and if it
cannot be repaired the process EXITS non-zero so systemd restarts it and
`OnFailure=` raises an alarm. A crash that gets noticed beats a run that does
not. Losing authorisation exits 2 instead, which the unit refuses to restart —
retrying an unauthorised session is exactly the behaviour that would put the
account at risk, and this account is the scarcest thing in the project.

Liveness is also asserted positively, not inferred: every completed cycle
records a heartbeat (`ops_heartbeat`) that ops/watchdog.py reads. Without it,
"the poller is dead" and "the channels are quiet" produce the identical
evidence — no new rows — and only one of them is a fault.

v1 is untouched by anything here. Separate account, separate session, separate
process — that separation is the whole reason for the second account.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                     # noqa: E402
from analyst.lang import detect_quietly    # noqa: E402
from ingest.setup_session import SessionBusy, session_lock   # noqa: E402
from ops.heartbeat import beat, fail          # noqa: E402
from resolve.db import connect                # noqa: E402

SESSION = ROOT / "data" / "session" / "v2_ingest"
STATE = ROOT / "data" / "session" / "poller_state.json"
_stop = False

HEARTBEAT = "telegram-poller"
# A cycle is ~10 channels x ~1.5s of stagger plus the 30s interval, so roughly
# 45s. 15 minutes of grace is deliberately loose: the poller is allowed to sit
# out a FloodWait without being declared dead, and an outage that matters lasts
# a great deal longer than fifteen minutes. A watchdog tuned tight enough to
# catch every blip is a watchdog whose alarms stop being read.
_GRACE = 900
# How many reconnect attempts before giving up and letting systemd restart the
# whole process. Backoff is 15s, 30s, 60s, 120s, 240s, 300s — about 12 minutes
# of patience, then a clean exit. A fresh process reconnects from a clean state,
# which is strictly more likely to work than the seventh attempt from a dirty
# one, and it produces the failure signal that this outage lacked.
RECONNECT_ATTEMPTS = 6

# Channels whose PHOTOS are archived, not just their text.
#
# @palhubappfuel stopped posting text bulletins on 2026-08-01 at 09:14 and
# switched to rendered cards, taking 196 fuel stations — the largest source in
# this system — dark in the same hour. The caption links to
# palhub.app/fuel-status, which answers 403 behind a Cloudflare challenge while
# their /road-status returns 200 to the same client in the same second. That
# page is closed on purpose and is not read. The image is, because it arrives
# over a channel this account already subscribes to.
#
# Kept to an explicit list rather than "download everything with media": the
# news channels post photos constantly and none of it is machine-readable, so a
# blanket rule would spend bandwidth and disk on nothing and slow every cycle.
#
# EMPTY SINCE THE VERTICAL WAS RETIRED (2026-09-23, migration 070; DECISIONS:
# "fuel is not an issue to track anymore"). The card reader that consumed
# attrs.media_ref moved to ops/retired/, but this set still named the channel,
# so the poller went on issuing up to 150 GetFile requests a cycle — 288-1,040
# photos a day — on the scarcest account, for images nothing reads. The text
# of every message is still stored; only the image download stops. Re-enabling
# is one entry here, and belongs with whatever job reads the images again.
MEDIA_CHANNELS: frozenset[str] = frozenset()

# One card is ~15 KB. A cap exists so a channel that starts posting video
# cannot fill the disk between watchdog runs — the capacity check is the
# backstop, not the first line of defence.
MAX_MEDIA_BYTES = 2 * 1024 * 1024

# Downloads PER CYCLE, not per message. Catching up on a new channel returns
# MAX_PAGES * PAGE = 2,000 messages at once, and palhubappfuel is roughly 40%
# photos — so a single cycle would fire ~700 sequential media requests at
# Telegram on an account Zaid described as one "we barely managed to have
# working". The remainder is not lost: the cursor only advances across messages
# that were STORED, so the un-downloaded tail arrives on later cycles.
MEDIA_PER_CYCLE = 150


class Deauthorised(Exception):
    """The session is no longer valid. Distinct from a transport failure because
    the correct response is the opposite one: stop, and do not retry."""


def _telethon_errors():
    """(FloodWaitError, the errors that mean the SESSION is gone).

    Imported lazily, like TelegramClient, so the module imports without
    Telethon. A 401 (revoked, expired, banned, unregistered key) is never about
    one channel, and AUTH_KEY_DUPLICATED is Telegram killing a key that two
    clients used at once. Every other 406 (FILEREF_UPGRADE_NEEDED, ...) is
    per-request and stays a channel failure.
    """
    from telethon.errors import (AuthKeyDuplicatedError, FloodWaitError,
                                 UnauthorizedError)
    return FloodWaitError, (UnauthorizedError, AuthKeyDuplicatedError)


async def _nap(seconds: float) -> None:
    """Sleep, waking for SIGTERM. A FloodWait can last hours and systemd's
    stop timeout is 90 s: an unwakeable sleep ends in a SIGKILL, which is how
    a state file gets torn mid-write."""
    end = time.monotonic() + max(0.0, seconds)
    while not _stop:
        left = end - time.monotonic()
        if left <= 0:
            return
        await asyncio.sleep(min(left, 1.0))


def _flood_grace(seconds: int, interval: float) -> int:
    """The heartbeat grace for a beat taken before sleeping out a flood.

    The fixed 900 s meant any flood over ~15 minutes read as `not_running` —
    "the scheduler is not firing it" — whose documented reflex is a restart,
    and a fresh process re-issues at once the request the flood forbade. The
    next ordinary beat puts _GRACE back.
    """
    return max(_GRACE, int(seconds) + int(interval) + 60)


async def _flood_pause(seconds: int, interval: float, detail: dict) -> None:
    """Respect a FloodWait exactly, having said so first. Blind retry is how a
    new account gets banned.

    Beat before sleeping. Waiting out a flood is the poller doing its job
    correctly, and a long one would otherwise trip the watchdog into reporting
    a dead poller. The duration goes into detail so a PERMANENT throttle —
    healthy heartbeats, no claims, a flood_wait every cycle — is still legible.
    """
    beat(HEARTBEAT, int(interval), _flood_grace(seconds, interval),
         {"flood_wait_seconds": int(seconds), **detail})
    await _nap(seconds + 5)


async def _whoami(client):
    """The logged-in user, or None when the session is no longer authorised.

    get_me() is a real request. is_user_authorized() is not: Telethon caches
    its answer in `_authorized` for the life of the client and connect() never
    resets it, so after a revocation _reconnect's check still read True and
    exit 2 was unreachable. FloodWaitError and transport errors propagate —
    neither says anything about authorisation.
    """
    _flood, deauth = _telethon_errors()
    try:
        return await client.get_me()
    except deauth:
        return None


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update(os.environ)
    return env


# THE CURSOR FILE, AND WHY LOSING IT NO LONGER MEANS 0.
#
# It was written with write_text — truncate, then write — and read back as {}
# on any parse error. A SIGKILL between the two (the 90 s stop timeout landing
# in a FloodWait sleep, a power cut) left a file that did not parse, every
# channel restarted at min_id=0, and each cycle walked 2,000 messages of
# history per channel on the fragile account. It was also saved only on cycles
# that wrote a claim, so cursors advanced across an all-duplicate batch were
# not persisted at all.
#
# Now: written to a temp file and renamed (bronze's pattern), saved whenever a
# cursor moved, and a corrupt file is moved aside, never silently read as
# empty. A channel with no cursor is resumed from the claims already stored
# for it (_stored_cursor): the cursor only ever advances across messages that
# were stored, so the newest stored id IS the cursor, and 0 remains the answer
# only for a channel that has never been read.
def _load_state() -> dict:
    try:
        s = json.loads(STATE.read_text())
        if not isinstance(s, dict):
            raise ValueError(f"expected an object, got {type(s).__name__}")
        return s
    except FileNotFoundError:
        return {}
    except ValueError as exc:                           # JSON and UTF-8 errors
        aside = STATE.with_name(f"{STATE.name}.corrupt-{int(time.time())}")
        try:
            STATE.rename(aside)
        except OSError:
            aside = STATE
        print(f"WARNING: {STATE.name} is unreadable ({exc}); kept as "
              f"{aside.name}. Cursors will be recovered from the claims "
              "already stored, not reset to 0.")
        return {}


def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(f"{STATE.name}.tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(s, indent=1, sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATE)
    finally:
        tmp.unlink(missing_ok=True)


def _stored_cursor(channel: str) -> int:
    """The newest message id already stored for a channel: its cursor,
    recovered from the claims themselves. 0 only if nothing was ever stored."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT max(d.external_id::bigint)
                         FROM claim_dedup d JOIN source s USING (source_id)
                        WHERE s.key = %s AND d.external_id ~ '^[0-9]+$'""",
                    (f"tg_{channel.lower()}",))
        return int(cur.fetchone()[0] or 0)


def _db_ok() -> bool:
    """Can a claim be stored right now? Asked BEFORE Telegram is, because a
    fetch whose result cannot be stored is a request spent on nothing."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception as exc:                            # noqa: BLE001
        print(f"database unreachable: {type(exc).__name__}: {exc}")
        return False


def _ensure_source(cur, channel: str) -> int:
    """One source row per channel. reliability stays NULL until Loop A measures
    it — never hand-seeded (that was v1's mistake)."""
    key = f"tg_{channel.lower()}"
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,attribution_text,
                            authority_rank)
        VALUES (%s,%s,'telegram','NONE',false,%s,4)
        ON CONFLICT (key) DO NOTHING""",
        (key, f"Telegram @{channel}", f"Telegram channel @{channel}"))
    cur.execute("SELECT source_id FROM source WHERE key=%s", (key,))
    return cur.fetchone()[0]


def _link_urls(m) -> list[str]:
    """The URLs behind a message's link text.

    Telegram puts a hyperlink's target in a MessageEntityTextUrl, NOT in the
    text, so a caption reading "🔗 التفاصيل والتحديث اللحظي" carries no URL at
    all in `message`. v1's tee spool records neither entities nor media, which
    is why the fuel channel's switch to images looked like it had simply gone
    quiet: the text was still arriving, it just no longer said anything.
    """
    out = []
    for e in (getattr(m, "entities", None) or []):
        u = getattr(e, "url", None)
        if u:
            out.append(u)
    return out


async def archive_media(client, channel: str, messages) -> tuple[dict, int | None]:
    """Download photos for MEDIA_CHANNELS into bronze.

    Returns ({msg_id: bronze_ref}, cutoff_id) where `cutoff_id` is the last
    message id this call is willing to see stored. None means "all of them".

    THE CUTOFF IS THE WHOLE POINT OF RETURNING A TUPLE. `messages` arrives
    oldest-first and the caller advances its cursor to the newest id it stored.
    If the per-cycle media cap simply stopped downloading, the caller would
    still store and skip past the remainder, and those images would be gone
    permanently with nothing reporting it — the identical failure that
    `_fetch_since` documents at length for text. So when the cap bites, the
    batch is TRUNCATED rather than partially enriched, and the cursor stays
    behind on a contiguous run.

    Separated from store() because downloading is async and storing is not, and
    because a failed download must never cost the claim: the text row is
    written either way and the image is an enrichment. bronze is
    content-addressed, so a card reposted unchanged costs one hash and no disk.
    """
    if channel.lower() not in MEDIA_CHANNELS:
        return {}, None
    flood_wait, deauth = _telethon_errors()
    refs: dict[int, str] = {}
    downloaded = 0
    for m in messages:
        # PHOTOS ONLY. `media` is also true for video, documents, stickers and
        # polls. The first run archived a 926 KB MP4 under a .jpg name, because
        # this checked `media` and then hardcoded the extension — so the file
        # was mislabelled AND the bandwidth was spent on something no OCR can
        # read. `photo` is set only for MessageMediaPhoto, and a Telegram photo
        # is always JPEG, which makes the extension honest by construction.
        if not getattr(m, "photo", None):
            continue
        if downloaded >= MEDIA_PER_CYCLE:
            # Stop the batch HERE, one message before the one we refused.
            print(f"  media cap reached for @{channel} at msg {m.id}; "
                  f"{downloaded} archived, rest deferred to the next cycle")
            return refs, m.id - 1
        try:
            blob = await client.download_media(m, file=bytes)
        except (flood_wait, *deauth):
            # Not a per-photo failure. Swallowed here, a flood let the caller
            # store the whole batch and step its cursor past every photo that
            # was never downloaded — permanently, contradicting the cutoff
            # above. Raised, the caller's flood handler sleeps once and the
            # batch is fetched again, whole, next cycle.
            raise
        except Exception as exc:                        # noqa: BLE001
            print(f"  media download failed for {channel}/{getattr(m,'id','?')}: "
                  f"{type(exc).__name__}: {exc}")
            continue
        if not blob or len(blob) > MAX_MEDIA_BYTES:
            continue
        try:
            refs[m.id] = bronze.put(f"tg_{channel.lower()}", blob, "jpg").ref
            downloaded += 1
        except Exception as exc:                        # noqa: BLE001
            print(f"  media archive failed for {channel}/{m.id}: {exc}")
    return refs, None


def store(channel: str, messages, media_refs: dict | None = None) -> int:
    """Archive raw + insert claims. Idempotent via claim_dedup."""
    if not messages:
        return 0
    media_refs = media_refs or {}
    written = 0
    with connect() as conn, conn.cursor() as cur:
        source_id = _ensure_source(cur, channel)
        for m in messages:
            text = getattr(m, "message", None) or ""
            ext_id = str(getattr(m, "id", ""))
            cur.execute("SELECT claim_id FROM claim_dedup WHERE source_id=%s AND external_id=%s",
                        (source_id, ext_id))
            if cur.fetchone():
                continue

            payload = json.dumps({
                "channel": channel, "id": getattr(m, "id", None),
                "date": m.date.isoformat() if getattr(m, "date", None) else None,
                "text": text, "views": getattr(m, "views", None),
                "fwd_from": _fwd_id(m),
                "media": type(getattr(m, "media", None)).__name__ if getattr(m, "media", None) else None,
                "media_ref": media_refs.get(getattr(m, "id", None)),
                "link_urls": _link_urls(m),
            }, ensure_ascii=False)
            ref = bronze.put(f"tg_{channel.lower()}", payload, "json")

            reported = getattr(m, "date", None) or datetime.now(timezone.utc)
            # `lang` was the literal 'ar' here for every claim this poller ever
            # wrote, which was never a measurement. It is one now, and it
            # carries what measured it — a value with no provenance is the same
            # unfalsifiable constant wearing a different number. A detector that
            # cannot be built returns (None, None) and the claim is written with
            # a NULL language: the analyst's organ A picks up exactly the rows
            # that carry no `lang_detector` stamp. Ingestion never waits for it.
            code, detector = detect_quietly(text)
            attrs = {"channel": channel, "views": getattr(m, "views", None),
                     "fwd_from": _fwd_id(m),
                     # The image ingester finds its work by this key, so
                     # it is on the CLAIM rather than only in bronze.
                     "media_ref": media_refs.get(getattr(m, "id", None)),
                     "link_urls": _link_urls(m)}
            # Kept because the claim is immutable and cannot gain them later:
            # an album's one caption sits on one member (grouped_id ties the
            # rest to it), and an edit reuses the id — a claim that does not
            # say its text was already edited cannot be told from the original.
            for k in ("grouped_id", "edit_date"):
                v = getattr(m, k, None)
                if v is not None:
                    attrs[k] = v.isoformat() if hasattr(v, "isoformat") else v
            if detector:
                attrs["lang_detector"] = detector
            cur.execute("""
                INSERT INTO claim (source_id,external_id,raw_ref,raw_text,lang,claim_type,
                                   reported_at,attrs)
                VALUES (%s,%s,%s,%s,%s,'unclassified',%s,%s)
                RETURNING claim_id, ingested_at""",
                (source_id, ext_id, ref.ref, text, code, reported,
                 json.dumps(attrs)))
            claim_id, ingested_at = cur.fetchone()
            cur.execute("""INSERT INTO claim_dedup (source_id,external_id,claim_id,ingested_at)
                           VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (source_id, ext_id, claim_id, ingested_at))
            written += 1
        conn.commit()
    return written


def _fwd_id(m):
    try:
        f = getattr(m, "fwd_from", None)
        if not f:
            return None
        frm = getattr(f, "from_id", None)
        return getattr(frm, "channel_id", None) or getattr(frm, "user_id", None)
    except Exception:                                   # noqa: BLE001
        return None


PAGE = 100
# 20 pages = 2,000 messages per channel per cycle. The busiest channel produces
# ~80 in eight hours, so this absorbs an outage of several days. It is a
# backstop against a runaway, not a working limit — and hitting it is printed,
# never silent.
MAX_PAGES = 20
# Seconds between pages of a catch-up. Channels are already staggered; a long
# backlog would otherwise fire twenty requests back to back, which is the shape
# of traffic that gets a young account throttled. Named so tests can set it to
# zero — the pacing is real behaviour worth keeping, not worth waiting for.
PAGE_PAUSE = 1.0


async def _fetch_since(client, ent, last: int) -> list:
    """Every message with id > last, oldest first, paging until caught up.

    A single get_messages(limit=100) returns the NEWEST hundred above `last`.
    After an outage that produced more than a hundred, the older remainder is
    never returned — and because the caller then advances its cursor to the
    newest id it saw, those messages are skipped PERMANENTLY. The gap does not
    reappear and nothing reports it.

    That nearly happened on 2026-08-01: the 8-hour outage recovered 80 messages
    on the busiest channel against a limit of 100. Twenty more and the system
    would have quietly dropped the difference while appearing to have fully
    recovered — a silent violation of the retain-everything rule, and the kind
    only discovered long after the data is gone.

    Paging must run OLDEST-FIRST (`reverse=True`) rather than newest-first.
    Both directions collect the same messages when the backlog fits inside the
    page cap, so the choice looks cosmetic; it is not. The cursor may only
    advance across a CONTIGUOUS run. Paging newest-first and stopping early
    leaves a hole below the cursor, so the cap would silently drop exactly what
    it claims to defer. Paging oldest-first means an interrupted catch-up
    leaves the cursor at the end of an unbroken run, and the remainder really
    does arrive next cycle.
    """
    out, cursor = [], last
    for page in range(MAX_PAGES):
        msgs = [m for m in await client.get_messages(
            ent, limit=PAGE, min_id=cursor, reverse=True) if m.id > cursor]
        if not msgs:
            break
        out.extend(msgs)
        cursor = max(m.id for m in msgs)
        if len(msgs) < PAGE:
            break
        if page == MAX_PAGES - 1:
            print(f"  WARNING: hit the {MAX_PAGES}-page cap on this channel; "
                  f"the remainder resumes from {cursor} next cycle")
        await asyncio.sleep(PAGE_PAUSE)    # pace the pages, not just the channels
    return out


async def _reconnect(client) -> None:
    """Restore the transport after Telethon's own retries are exhausted.

    Raises on failure rather than returning a flag, because every caller's
    correct response to "still disconnected" is to stop, and a flag is the kind
    of thing a later edit forgets to check.
    """
    flood_wait, _deauth = _telethon_errors()
    for attempt in range(1, RECONNECT_ATTEMPTS + 1):
        delay = min(300, 15 * 2 ** (attempt - 1))
        print(f"reconnect attempt {attempt}/{RECONNECT_ATTEMPTS} in {delay}s")
        await _nap(delay)
        if _stop:
            raise ConnectionError("stopping during reconnect")
        try:
            await client.connect()
            if not client.is_connected():
                continue
            # A restored socket is not a restored session. Checking this before
            # polling means a revoked account is reported as a revoked account,
            # instead of as ten channels that all mysteriously stopped working.
            # It must be a real request — see _whoami.
            if await _whoami(client) is None:
                raise Deauthorised("session is no longer authorised")
            print(f"reconnected after {attempt} attempt(s)")
            return
        except Deauthorised:
            raise
        except flood_wait as fw:
            print(f"  FLOOD WAIT {fw.seconds}s while reconnecting — sleeping")
            await _nap(fw.seconds + 5)
        except Exception as exc:                        # noqa: BLE001
            print(f"  reconnect failed: {exc}")
    raise ConnectionError(
        f"could not reconnect after {RECONNECT_ATTEMPTS} attempts")


# A channel that fails to resolve is tried again, not abandoned: it used to be
# resolved once at startup and a failure printed UNRESOLVED and was never
# revisited, so it stayed dark for the life of the process while the
# heartbeat read healthy. The retry doubles from 30 minutes to 6 hours, because
# a handle that is genuinely dead (v1's `Almasshta`) should cost a few
# ResolveUsername calls a day, not one a cycle.
RESOLVE_RETRY = 1800
RESOLVE_RETRY_MAX = 6 * 3600


async def _resolve_due(client, entities: dict, pending: dict, backoff: dict):
    """Resolve the channels in `pending` whose retry time has come.

    Returns the seconds of a FloodWait Telegram imposed, else None. On a flood
    it stops at once and moves every pending channel past the window: the old
    loop printed the flood and asked for the next handle 1.5 s later, each one
    a ResolveUsername inside the window the flood forbade — the most tightly
    limited method there is for a young account — and each one then
    UNRESOLVED for good. A lost session propagates (it is not about a channel).
    """
    flood_wait, deauth = _telethon_errors()
    for ch in [c for c, t in pending.items() if t <= time.monotonic()]:
        try:
            entities[ch] = await client.get_entity(ch)
            del pending[ch]
            backoff.pop(ch, None)
            print(f"  resolved @{ch}")
        except flood_wait as fw:
            until = time.monotonic() + fw.seconds + 5
            for c in pending:
                pending[c] = max(pending[c], until)
            print(f"  FLOOD WAIT {fw.seconds}s resolving @{ch} — no further "
                  f"resolves until it has passed ({len(pending)} pending)")
            return fw.seconds
        except deauth:
            raise
        except Exception as exc:                        # noqa: BLE001
            wait = min(backoff.get(ch, RESOLVE_RETRY // 2) * 2, RESOLVE_RETRY_MAX)
            backoff[ch] = wait
            pending[ch] = time.monotonic() + wait
            print(f"  UNRESOLVED @{ch}: {exc} — next try in {wait // 60} min")
        await _nap(1.5)
    return None


async def run(once: bool = False, backfill: int = 0) -> int:
    """Poll until stopped. Exit 0 on a clean stop, 1 for anything a restart
    may fix, 2 when the session is gone — which the unit refuses to restart
    (RestartPreventExitStatus=2)."""
    # One client per session file (HANDOFF rule 4), taken before anything —
    # the client, the database — so a second poller, a `--once` beside the
    # service, or a restart into a running discovery refuses without ever
    # opening the session.
    try:
        with session_lock(SESSION, "telegram_poller"):
            return await _run(once, backfill)
    except SessionBusy as exc:
        print(f"REFUSING: {exc}")
        return 1


async def _run(once: bool, backfill: int) -> int:
    from telethon import TelegramClient

    flood_wait, deauth = _telethon_errors()
    e = _env()
    api_id = int(e.get("V2_TELEGRAM_API_ID", "0") or 0)
    api_hash = e.get("V2_TELEGRAM_API_HASH", "")
    channels = [c.strip().lstrip("@") for c in e.get("V2_TELEGRAM_CHANNELS", "").split(",") if c.strip()]
    interval = float(e.get("V2_POLL_INTERVAL", "30"))
    if not channels:
        print("V2_TELEGRAM_CHANNELS is empty")
        return 1

    # The database first. A process restarted into a database outage used to
    # connect, resolve every channel and fetch every backlog before its first
    # store() failed — per restart. Waiting here costs Telegram nothing.
    delay = 15
    while not _db_ok():
        if once:
            return 1
        print(f"waiting {delay}s for the database before touching Telegram")
        await _nap(delay)
        if _stop:
            return 0
        delay = min(delay * 2, 300)

    client = TelegramClient(str(SESSION), api_id, api_hash)
    try:
        return await _poll(client, channels, interval, once, backfill)
    except (Deauthorised, *deauth) as exc:
        # Exit 2, which the unit does not restart. This path used to be dead:
        # startup returned 1 for an unauthorised session, and a revocation
        # mid-run surfaced as a channel failure in every channel until the
        # three-cycle exit returned 1 — so systemd reconnected a dead session
        # every 30 s to 15 min, forever, the one pattern rule 3 forbids.
        why = f"{type(exc).__name__}: {exc}"
        print(f"FATAL: the session is no longer authorised ({why}). Run: "
              "./.venv/bin/python -m ingest.setup_session --status")
        fail(HEARTBEAT, f"deauthorised — {why}"[:500], int(interval), _GRACE)
        return 2
    finally:
        try:
            await client.disconnect()
        except Exception:                               # noqa: BLE001
            pass


async def _poll(client, channels: list[str], interval: float, once: bool,
                backfill: int) -> int:
    flood_wait, deauth = _telethon_errors()
    await client.connect()
    while True:
        try:
            me = await _whoami(client)
            break
        except flood_wait as fw:
            print(f"FLOOD WAIT {fw.seconds}s at startup — sleeping")
            await _flood_pause(fw.seconds, interval, {"at": "startup"})
            if _stop:
                return 0
    if me is None:
        raise Deauthorised("not authorised. Run: ./.venv/bin/python -m "
                           "ingest.setup_session --request-code")
    print(f"Polling as {me.first_name} (id={me.id}) — {len(channels)} channel(s), {interval}s")

    entities: dict[str, object] = {}
    pending: dict[str, float] = {ch: 0.0 for ch in channels}
    backoff: dict[str, int] = {}
    while True:
        flood = await _resolve_due(client, entities, pending, backoff)
        if entities or _stop:
            break
        if flood is None:
            # Nothing resolved and Telegram did not ask for a wait. Beating
            # `channels: 0` every cycle — what this did — reads as healthy to
            # systemd, /health and the watchdog while nothing is ingested.
            msg = f"none of the {len(channels)} channel(s) resolved"
            print(f"FATAL: {msg}")
            fail(HEARTBEAT, msg, int(interval), _GRACE)
            return 1
        await _flood_pause(flood, interval, {"resolving": len(pending)})
    if _stop:
        return 0

    state = _load_state()
    saved = dict(state)
    try:
        if backfill:
            for ch, ent in entities.items():
                try:
                    msgs = await client.get_messages(ent, limit=backfill)
                    ordered = list(reversed(msgs))
                    refs, _ = await archive_media(client, ch, ordered)
                    n = store(ch, ordered, refs)
                    if msgs:
                        state[ch] = max(m.id for m in msgs)
                    print(f"  backfill @{ch}: {n} claim(s)")
                except flood_wait as fw:
                    print(f"  FLOOD WAIT {fw.seconds}s on @{ch} — stopping backfill")
                    break
                except deauth:
                    raise
                except Exception as exc:                # noqa: BLE001
                    print(f"  backfill @{ch} failed: {exc}")
                await _nap(3)
            _save_state(state)
            saved = dict(state)

        # A cycle where EVERY channel raised is a transport failure wearing a
        # channel failure's clothing — ten independent handles do not break at
        # the same instant. is_connected() reported the truth in the outage
        # that prompted this, but relying on it alone would leave the loop
        # trusting one flag to notice it has stopped working.
        dead_cycles = 0

        while not _stop:
            if not _db_ok():
                # Not a channel failure, and not Telegram's business. Counted
                # against the same three-cycle exit, so the outage is loud,
                # but nothing is fetched — or downloaded — that cannot be
                # stored. The restarted process then waits in _run, still
                # without touching Telegram, until the database is back.
                dead_cycles += 1
                print(f"not polling: database down ({dead_cycles} cycle(s) in a row)")
                if dead_cycles >= 3 or once:
                    fail(HEARTBEAT, "database unreachable", int(interval), _GRACE)
                    print(f"FATAL: the database has been unreachable for "
                          f"{dead_cycles} cycle(s) — exiting so systemd restarts "
                          "and the alarm fires")
                    return 1
                await _nap(interval)
                continue

            if not client.is_connected():
                print("transport is down — Telethon's own retries are exhausted")
                try:
                    await _reconnect(client)
                except Deauthorised:
                    raise
                except Exception as exc:                # noqa: BLE001
                    print(f"FATAL: {exc}")
                    fail(HEARTBEAT, str(exc), int(interval), _GRACE)
                    return 1
                dead_cycles = 0

            if pending:
                await _resolve_due(client, entities, pending, backoff)

            total, failures = 0, 0
            for ch, ent in list(entities.items()):
                try:
                    last = state.get(ch)
                    if last is None:
                        last = state[ch] = _stored_cursor(ch)
                    fresh = await _fetch_since(client, ent, last)   # oldest first
                    if fresh:
                        refs, cutoff = await archive_media(client, ch, fresh)
                        if cutoff is not None:
                            # Truncate to the contiguous run whose media we took.
                            fresh = [m for m in fresh if m.id <= cutoff]
                        if fresh:
                            total += store(ch, fresh, refs)
                            state[ch] = max(m.id for m in fresh)
                except flood_wait as fw:
                    print(f"FLOOD WAIT {fw.seconds}s on @{ch} — sleeping")
                    await _flood_pause(fw.seconds, interval, {"channel": ch})
                except deauth:
                    raise
                except Exception as exc:                # noqa: BLE001
                    failures += 1
                    print(f"poll @{ch} failed: {exc}")
                # Stagger so five channels are not hit in the same instant.
                await _nap(1.0 + random.random())

            if failures == len(entities):
                dead_cycles += 1
                print(f"every channel failed ({dead_cycles} cycle(s) in a row)")
                if dead_cycles >= 3:
                    fail(HEARTBEAT, f"all {failures} channels failing", int(interval), _GRACE)
                    print("FATAL: every channel has failed for 3 cycles — exiting "
                          "so systemd restarts and the alarm fires")
                    return 1
            else:
                dead_cycles = 0
                # Recorded on EVERY good cycle, including the ones that found
                # nothing. A heartbeat that only fires when there is news cannot
                # distinguish a dead poller from a quiet Saturday, which is the
                # entire failure this is here to prevent. `unresolved` names the
                # configured channels that are not being read at all.
                beat(HEARTBEAT, int(interval), _GRACE,
                     {"channels": len(entities), "claims": total,
                      "channel_failures": failures,
                      "configured": len(channels),
                      "unresolved": sorted(pending)})

            if state != saved:
                _save_state(state)
                saved = dict(state)
            if total:
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] +{total} claim(s)")
            if once:
                break
            await _nap(interval)
    finally:
        # Whatever ended the loop — a clean stop, an exit code, a lost session
        # — the cursors it advanced were earned by stored claims.
        if state != saved:
            _save_state(state)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--backfill", type=int, default=0)
    a = ap.parse_args()

    def _sig(*_):
        global _stop
        _stop = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    return asyncio.run(run(a.once, a.backfill))


if __name__ == "__main__":
    raise SystemExit(main())
