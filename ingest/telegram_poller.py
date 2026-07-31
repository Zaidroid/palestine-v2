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
from resolve.db import connect                # noqa: E402

SESSION = ROOT / "data" / "session" / "v2_ingest"
STATE = ROOT / "data" / "session" / "poller_state.json"
_stop = False


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


def store(channel: str, messages) -> int:
    """Archive raw + insert claims. Idempotent via claim_dedup."""
    if not messages:
        return 0
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
                             "fwd_from": _fwd_id(m)})))
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
                n = store(ch, list(reversed(msgs)))
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

    while not _stop:
        total = 0
        for ch, ent in entities.items():
            try:
                last = state.get(ch, 0)
                msgs = await client.get_messages(ent, limit=100, min_id=last)
                fresh = [m for m in reversed(msgs) if m.id > last]
                if fresh:
                    total += store(ch, fresh)
                    state[ch] = max(m.id for m in fresh)
            except FloodWaitError as fw:
                # Respect it exactly. Blind retry is how a new account gets banned.
                print(f"FLOOD WAIT {fw.seconds}s on @{ch} — sleeping")
                await asyncio.sleep(fw.seconds + 5)
            except Exception as exc:                    # noqa: BLE001
                print(f"poll @{ch} failed: {exc}")
            # Stagger so five channels are not hit in the same instant.
            await asyncio.sleep(1.0 + random.random())
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
