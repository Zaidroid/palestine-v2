"""P5.2 — tell subscribers when the answer CHANGES, instead of making them ask.

    curl -N localhost:7870/v2/stream
    curl -N 'localhost:7870/v2/stream?state_kind=checkpoint_status'

Until now everything was polling: a frontend re-asked every 30 seconds and an
agent could not be told that a checkpoint had closed. This closes that.

WHY SSE AND NOT WEBSOCKETS
It is one-directional, which is exactly the shape of the problem — subscribers
read, they do not write; writing is what the crowd endpoint is for. In exchange
SSE survives Cloudflare without special configuration, reconnects itself in
every browser with no client library, degrades to a plain HTTP response an agent
can read with `httpx.stream`, and needs no protocol upgrade. A WebSocket would
buy bidirectionality nothing here wants and cost a dependency on both ends.

WHAT IS EMITTED — BELIEF, NOT OBSERVATIONS
The events are changes in what the system is WILLING TO ASSERT, not arrivals in
the raw feed. `a7walstreet` posting a thirty-eighth "Huwara open" is not news;
Huwara going from open to closed is. Streaming observations would flood a
subscriber with the corroboration machinery's inputs and make them reimplement
belief on the client to get back to the answer.

DECAY IS AN EVENT TOO, AND IT IS THE EASY ONE TO FORGET
A reading whose confidence falls below its floor stops being assertable, and
`state_serving` returns `unknown`. That is a real transition and subscribers are
told about it. Otherwise a phone that connected at noon would still be showing
"open" at midnight from an event it received once — which is precisely the v1
failure this whole architecture exists to fix, reintroduced through the
streaming layer.

ONE POLLER, MANY SUBSCRIBERS
A full scan of state_serving is ~37ms for 1,849 rows, so one shared task polls
and fans out over in-memory queues. Per-connection polling would multiply that
by the number of phones. The API runs as a single uvicorn process (no
--workers), which is what makes in-process fan-out correct; if it is ever
scaled to multiple workers this has to move to LISTEN/NOTIFY, and the comment on
POLL_SECONDS says so.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ops.heartbeat import beat
from resolve.db import dsn

# Fast enough that a closure reaches a phone while it still matters, slow enough
# that the database does not notice. The checkpoint pipeline itself only
# recomputes belief every 2 minutes, so polling faster than this would mostly
# re-read unchanged rows.
POLL_SECONDS = 10

# Proxies and phone networks drop idle connections. A comment line is not an
# event, so clients ignore it, but it keeps the socket alive.
KEEPALIVE_SECONDS = 25

# A subscriber that cannot keep up is disconnected rather than allowed to grow
# an unbounded queue in the server. Losing a slow client is better than losing
# the process that serves everyone else.
MAX_QUEUE = 200

WATCH_SQL = """
SELECT s.place_id, p.name_ar, p.name_en, p.kind AS place_kind,
       s.state_kind, s.direction, s.value, s.last_known_value,
       round(s.confidence::numeric, 3)::float8 AS confidence,
       s.observed_at, s.age_minutes, s.staleness_band, s.independent_sources
  FROM state_serving s
  JOIN place p USING (place_id)
"""


def _beat(watched: int) -> None:
    """Never allowed to fail the poll it reports on — monitoring that can take
    down the thing it monitors is worse than no monitoring."""
    beat("stream", POLL_SECONDS, 300, {"watched_states": watched})


def _key(r: dict) -> tuple:
    return (r["place_id"], r["state_kind"], r["direction"])


class Broadcaster:
    """Polls served belief, fans changes out to subscribers."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._last: dict[tuple, str] = {}
        self._task: asyncio.Task | None = None
        self._primed = False
        self.events_sent = 0
        self.last_poll_at: datetime | None = None

    # ── subscription ─────────────────────────────────────────────────────────
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def _publish(self, event: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer. Drop it rather than buffer without limit; SSE
                # clients reconnect on their own and get a fresh snapshot.
                self.unsubscribe(q)

    # ── the poll loop ────────────────────────────────────────────────────────
    def _fetch(self) -> list[dict]:
        with psycopg.connect(dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(WATCH_SQL)
            return cur.fetchall()

    async def _poll_once(self) -> None:
        rows = await asyncio.to_thread(self._fetch)
        self.last_poll_at = datetime.now(timezone.utc)
        seen = set()

        for r in rows:
            k = _key(r)
            seen.add(k)
            now_val = r["value"]
            was = self._last.get(k)
            self._last[k] = now_val

            # The first pass establishes the baseline. Emitting on it would
            # send 1,849 "changes" to whoever happened to be connected at
            # startup, none of which are changes.
            if not self._primed or was == now_val:
                continue

            self.events_sent += 1
            self._publish({
                "type": "state_change",
                "at": self.last_poll_at.isoformat(),
                "place_id": r["place_id"],
                "place": r["name_ar"] or r["name_en"],
                "place_kind": r["place_kind"],
                "state_kind": r["state_kind"],
                "direction": r["direction"],
                "from": was,
                "to": now_val,
                # `unknown` is not an error, it is the system declining to
                # assert a reading it can no longer stand behind.
                "decayed": now_val == "unknown",
                "last_known_value": r["last_known_value"],
                "confidence": r["confidence"],
                "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
                "age_minutes": float(r["age_minutes"]) if r["age_minutes"] is not None else None,
                "staleness_band": r["staleness_band"],
                "independent_sources": r["independent_sources"],
            })

        # A row that disappears entirely (a place merged, a kind retired) is
        # forgotten rather than left to fire a spurious change if it returns.
        for k in set(self._last) - seen:
            del self._last[k]

        self._primed = True

    async def run(self) -> None:
        while True:
            try:
                await self._poll_once()
                # The stream lives INSIDE the API process, so if this loop dies
                # while uvicorn keeps answering, /health stays green and every
                # subscriber simply hears nothing forever — a dead poller and a
                # quiet night are indistinguishable. That is precisely the trap
                # P3.1 exists for, so it reuses P3.1's answer rather than
                # inventing a second one: a positive heartbeat the watchdog
                # already knows how to miss.
                await asyncio.to_thread(_beat, len(self._last))
            except Exception as exc:                     # noqa: BLE001
                # A database blip must not kill the stream for everyone. It is
                # reported and retried; subscribers keep their connections and
                # simply hear nothing until it recovers.
                print(f"stream poll failed: {exc}", flush=True)
            await asyncio.sleep(POLL_SECONDS)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


broadcaster = Broadcaster()


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def event_source(state_kind: str | None = None,
                       place_id: int | None = None,
                       snapshot: bool = True):
    """The SSE body.

    Opens with a snapshot of everything currently asserted, so a subscriber is
    consistent from its first byte rather than only after the first thing
    happens to change. Without it a client that connects at 03:00 knows nothing
    until 06:00, and cannot tell "nothing has changed" from "not connected".
    """
    q = broadcaster.subscribe()
    try:
        yield _sse("hello", {
            "poll_seconds": POLL_SECONDS,
            "filter": {"state_kind": state_kind, "place_id": place_id},
            "note": "events are changes in what the system will ASSERT, not "
                    "raw reports. `decayed: true` means a reading aged out of "
                    "assertability — that is a real change, not a gap.",
        })

        if snapshot:
            rows = await asyncio.to_thread(broadcaster._fetch)
            current = [
                {"place_id": r["place_id"],
                 "place": r["name_ar"] or r["name_en"],
                 "state_kind": r["state_kind"], "direction": r["direction"],
                 "value": r["value"], "confidence": r["confidence"],
                 "age_minutes": float(r["age_minutes"]) if r["age_minutes"] is not None else None}
                for r in rows
                if r["value"] != "unknown"
                and (state_kind is None or r["state_kind"] == state_kind)
                and (place_id is None or r["place_id"] == place_id)
            ]
            yield _sse("snapshot", {"asserted": len(current), "states": current})

        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if state_kind and ev.get("state_kind") != state_kind:
                continue
            if place_id and ev.get("place_id") != place_id:
                continue
            yield _sse("state_change", ev)
    finally:
        broadcaster.unsubscribe(q)
