"""P5.2 — the properties that decide whether a subscriber can trust the stream.

    ./.venv/bin/python -m pytest tests/test_stream.py -q

A stream is worse than polling if it is subtly wrong, because a subscriber stops
checking. These cover the four ways that happens: it says nothing changed when
something did, it says something changed when nothing did, it forgets to mention
that a reading expired, or it falls over and looks identical to a quiet night.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import stream as S                                    # noqa: E402


def row(place_id, kind, value, direction="both", conf=0.8, last_known=None,
        age=5.0):
    return {"place_id": place_id, "name_ar": f"مكان{place_id}", "name_en": None,
            "place_kind": "checkpoint", "state_kind": kind,
            "direction": direction, "value": value,
            "last_known_value": last_known or value, "confidence": conf,
            "observed_at": None, "age_minutes": age,
            "staleness_band": "fresh", "independent_sources": 2}


def drive(b: S.Broadcaster, batches):
    """Run the poller over fabricated batches; collect what a subscriber sees."""
    seen = []

    async def go():
        q = b.subscribe()
        for batch in batches:
            b._fetch = lambda batch=batch: batch          # noqa: ARG005
            await b._poll_once()
        while not q.empty():
            seen.append(q.get_nowait())
    asyncio.run(go())
    return seen


# ── it must not shout on connect ─────────────────────────────────────────────

def test_the_first_poll_establishes_a_baseline_and_emits_nothing():
    """Otherwise whoever is connected at startup receives 1,849 "changes",
    none of which are changes, and learns to ignore the stream."""
    b = S.Broadcaster()
    seen = drive(b, [[row(1, "checkpoint_status", "open"),
                      row(2, "checkpoint_status", "closed")]])
    assert seen == []
    assert b.events_sent == 0


def test_an_unchanged_value_emits_nothing():
    b = S.Broadcaster()
    batch = [row(1, "checkpoint_status", "open")]
    seen = drive(b, [batch, batch, batch])
    assert seen == []


# ── it must report what actually changed ─────────────────────────────────────

def test_a_real_transition_is_emitted_once_with_both_sides():
    b = S.Broadcaster()
    seen = drive(b, [[row(1, "checkpoint_status", "open")],
                     [row(1, "checkpoint_status", "closed")],
                     [row(1, "checkpoint_status", "closed")]])
    assert len(seen) == 1, "a change must fire once, not on every subsequent poll"
    e = seen[0]
    assert (e["from"], e["to"]) == ("open", "closed")
    assert e["place_id"] == 1 and e["state_kind"] == "checkpoint_status"


def test_direction_is_part_of_identity():
    """A checkpoint can be open outbound and closed inbound. Collapsing the two
    would make one direction's change silently overwrite the other's."""
    b = S.Broadcaster()
    seen = drive(b, [
        [row(1, "checkpoint_status", "open", "inbound"),
         row(1, "checkpoint_status", "open", "outbound")],
        [row(1, "checkpoint_status", "open", "inbound"),
         row(1, "checkpoint_status", "closed", "outbound")]])
    assert len(seen) == 1
    assert seen[0]["direction"] == "outbound"


# ── the transition everyone forgets ──────────────────────────────────────────

def test_decay_to_unknown_is_an_event_and_is_labelled():
    """The one most easily missed. A reading that ages out of assertability is
    real news: without it a phone connected at noon still shows "open" at
    midnight from an event it received once — the exact v1 failure this
    architecture exists to fix, reintroduced through the streaming layer."""
    b = S.Broadcaster()
    seen = drive(b, [[row(1, "checkpoint_status", "open")],
                     [row(1, "checkpoint_status", "unknown",
                          last_known="open", conf=0.1, age=400)]])
    assert len(seen) == 1
    e = seen[0]
    assert e["to"] == "unknown"
    assert e["decayed"] is True, "a subscriber must be able to tell decay from a report"
    assert e["last_known_value"] == "open", "and must still be told what it was"


def test_recovering_from_unknown_is_also_an_event():
    b = S.Broadcaster()
    seen = drive(b, [[row(1, "checkpoint_status", "unknown")],
                     [row(1, "checkpoint_status", "open")]])
    assert len(seen) == 1 and seen[0]["to"] == "open"
    assert seen[0]["decayed"] is False


# ── bookkeeping that would leak or misfire ───────────────────────────────────

def test_a_disappearing_row_is_forgotten_not_remembered():
    """A place merged away or a kind retired must not fire a spurious change
    if it ever comes back, and must not grow the snapshot forever."""
    b = S.Broadcaster()
    drive(b, [[row(1, "checkpoint_status", "open"),
               row(2, "checkpoint_status", "open")],
              [row(1, "checkpoint_status", "open")]])
    assert (2, "checkpoint_status", "both") not in b._last
    assert len(b._last) == 1


def test_a_slow_subscriber_is_dropped_rather_than_buffered_forever():
    """An unbounded queue behind a phone on a dead connection is a memory leak
    that takes down the process serving everyone else. SSE clients reconnect."""
    b = S.Broadcaster()

    async def go():
        q = b.subscribe()
        for i in range(S.MAX_QUEUE + 50):
            b._publish({"type": "state_change", "n": i})
        return q
    q = asyncio.run(go())
    assert b.subscribers == 0, "the slow subscriber must have been dropped"
    assert q.qsize() <= S.MAX_QUEUE


def test_a_database_failure_does_not_kill_the_stream():
    """A blip must not end the poll loop for everyone. Subscribers keep their
    connections and simply hear nothing until it recovers."""
    b = S.Broadcaster()

    def boom():
        raise RuntimeError("connection refused")

    async def go():
        b._fetch = boom
        task = asyncio.create_task(b.run())
        await asyncio.sleep(0.05)
        alive = not task.done()
        task.cancel()
        return alive
    assert asyncio.run(go()) is True


# ── filters must not silently drop everything ────────────────────────────────

def test_events_carry_the_fields_a_filter_needs():
    b = S.Broadcaster()
    seen = drive(b, [[row(7, "fuel_diesel", "available")],
                     [row(7, "fuel_diesel", "unavailable")]])
    e = seen[0]
    for f in ("place_id", "state_kind", "place", "confidence", "age_minutes",
              "staleness_band", "independent_sources"):
        assert f in e, f"the stream filters and the UI both need {f}"
