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
  * A per-channel failure never stops the loop; one dead handle must not take
    the poller down (v1 carries a dead `Almasshta` that errors every startup).

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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                     # noqa: E402
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
MEDIA_CHANNELS = {"palhubappfuel"}

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


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1, sort_keys=True))


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
            cur.execute("""
                INSERT INTO claim (source_id,external_id,raw_ref,raw_text,lang,claim_type,
                                   reported_at,attrs)
                VALUES (%s,%s,%s,%s,'ar','unclassified',%s,%s)
                RETURNING claim_id, ingested_at""",
                (source_id, ext_id, ref.ref, text, reported,
                 json.dumps({"channel": channel, "views": getattr(m, "views", None),
                             "fwd_from": _fwd_id(m),
                             # The image ingester finds its work by this key, so
                             # it is on the CLAIM rather than only in bronze.
                             "media_ref": media_refs.get(getattr(m, "id", None)),
                             "link_urls": _link_urls(m)})))
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
    for attempt in range(1, RECONNECT_ATTEMPTS + 1):
        delay = min(300, 15 * 2 ** (attempt - 1))
        print(f"reconnect attempt {attempt}/{RECONNECT_ATTEMPTS} in {delay}s")
        await asyncio.sleep(delay)
        if _stop:
            raise ConnectionError("stopping during reconnect")
        try:
            await client.connect()
            if not client.is_connected():
                continue
            # A restored socket is not a restored session. Checking this before
            # polling means a revoked account is reported as a revoked account,
            # instead of as ten channels that all mysteriously stopped working.
            if not await client.is_user_authorized():
                raise Deauthorised("session is no longer authorised")
            print(f"reconnected after {attempt} attempt(s)")
            return
        except Deauthorised:
            raise
        except Exception as exc:                        # noqa: BLE001
            print(f"  reconnect failed: {exc}")
    raise ConnectionError(
        f"could not reconnect after {RECONNECT_ATTEMPTS} attempts")


async def run(once: bool = False, backfill: int = 0) -> int:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError

    e = _env()
    api_id = int(e.get("V2_TELEGRAM_API_ID", "0") or 0)
    api_hash = e.get("V2_TELEGRAM_API_HASH", "")
    channels = [c.strip().lstrip("@") for c in e.get("V2_TELEGRAM_CHANNELS", "").split(",") if c.strip()]
    interval = float(e.get("V2_POLL_INTERVAL", "30"))
    if not channels:
        print("V2_TELEGRAM_CHANNELS is empty")
        return 1

    client = TelegramClient(str(SESSION), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Not authorised. Run: ./.venv/bin/python -m ingest.setup_session --request-code")
        return 1
    me = await client.get_me()
    print(f"Polling as {me.first_name} (id={me.id}) — {len(channels)} channel(s), {interval}s")

    entities: dict[str, object] = {}
    for ch in channels:
        try:
            entities[ch] = await client.get_entity(ch)
            print(f"  resolved @{ch}")
        except Exception as exc:                        # noqa: BLE001
            print(f"  UNRESOLVED @{ch}: {exc}")
        await asyncio.sleep(1.5)

    state = _load_state()
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
            except FloodWaitError as fw:
                print(f"  FLOOD WAIT {fw.seconds}s on @{ch} — stopping backfill")
                break
            except Exception as exc:                    # noqa: BLE001
                print(f"  backfill @{ch} failed: {exc}")
            await asyncio.sleep(3)
        _save_state(state)

    # A cycle where EVERY channel raised is a transport failure wearing a
    # channel failure's clothing — ten independent handles do not break at the
    # same instant. is_connected() reported the truth in the outage that
    # prompted this, but relying on it alone would leave the loop trusting one
    # flag to notice it has stopped working.
    dead_cycles = 0

    while not _stop:
        if not client.is_connected():
            print("transport is down — Telethon's own retries are exhausted")
            try:
                await _reconnect(client)
            except Deauthorised as exc:
                print(f"FATAL: {exc}")
                fail(HEARTBEAT, str(exc), int(interval), _GRACE)
                return 2
            except Exception as exc:                    # noqa: BLE001
                print(f"FATAL: {exc}")
                fail(HEARTBEAT, str(exc), int(interval), _GRACE)
                return 1
            dead_cycles = 0

        total, failures = 0, 0
        for ch, ent in entities.items():
            try:
                last = state.get(ch, 0)
                fresh = await _fetch_since(client, ent, last)   # oldest first
                if fresh:
                    refs, cutoff = await archive_media(client, ch, fresh)
                    if cutoff is not None:
                        # Truncate to the contiguous run whose media we took.
                        fresh = [m for m in fresh if m.id <= cutoff]
                    if fresh:
                        total += store(ch, fresh, refs)
                        state[ch] = max(m.id for m in fresh)
            except FloodWaitError as fw:
                # Respect it exactly. Blind retry is how a new account gets banned.
                print(f"FLOOD WAIT {fw.seconds}s on @{ch} — sleeping")
                # Beat before sleeping. Waiting out a flood is the poller doing
                # its job correctly, and a long one would otherwise trip the
                # watchdog into reporting a dead poller. The duration goes into
                # detail so a PERMANENT throttle — healthy heartbeats, no
                # claims, a flood_wait every cycle — is still legible.
                beat(HEARTBEAT, int(interval), _GRACE,
                     {"flood_wait_seconds": fw.seconds, "channel": ch})
                await asyncio.sleep(fw.seconds + 5)
            except Exception as exc:                    # noqa: BLE001
                failures += 1
                print(f"poll @{ch} failed: {exc}")
            # Stagger so five channels are not hit in the same instant.
            await asyncio.sleep(1.0 + random.random())

        if entities and failures == len(entities):
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
            # entire failure this is here to prevent.
            beat(HEARTBEAT, int(interval), _GRACE,
                 {"channels": len(entities), "claims": total,
                  "channel_failures": failures})

        if total:
            _save_state(state)
            print(f"[{datetime.now(timezone.utc):%H:%M:%S}] +{total} claim(s)")
        if once:
            break
        await asyncio.sleep(interval)

    await client.disconnect()
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
