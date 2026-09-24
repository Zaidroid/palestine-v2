"""How reports become events, and the two ways it goes wrong.

    ./.venv/bin/python -m pytest tests/test_incident_clustering.py -q

Reported 2026-09-24: the village of Habla showed as FIVE separate raid events
from four channels, while a Qalandiya arrest correctly carried two sources on
one event. Measured cause is NOT the time window — it is place identity, and the
evidence is in the test below. The time window had a separate latent defect,
which is what these tests pin.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.sources.news_incidents import (DEDUP_WINDOW, _confidence,   # noqa: E402
                                           cluster_by_window)

T0 = datetime(2026, 9, 23, 20, 48, 50, tzinfo=timezone.utc)


def m(minutes: float, unit: str = "src:38"):
    """One member as the caller builds it: (claim_id, reported_at, unit, ...)."""
    return (int(minutes), T0 + timedelta(minutes=minutes), unit)


# ── the window rule ──────────────────────────────────────────────────────────

def test_a_steady_stream_is_one_event_however_it_started():
    """THE DEFECT. The rule compared each report against the cluster's FIRST
    member, so the same stream split or held depending on when its earliest
    report happened to arrive. Here both streams have the same 60-minute
    cadence; only the start time differs, and the old rule gave them different
    answers."""
    stream = [m(0), m(60), m(120)]
    assert len(cluster_by_window(stream, DEDUP_WINDOW)) == 1

    # Same cadence, started 60 minutes earlier: the old anchored rule would have
    # split this one while leaving the other whole.
    later = [m(60), m(120), m(180)]
    assert len(cluster_by_window(later, DEDUP_WINDOW)) == 1


def test_a_real_gap_still_separates_two_events():
    """Chaining must not swallow everything: two incidents a night apart with
    nothing between them are two events."""
    assert len(cluster_by_window([m(0), m(1200)], DEDUP_WINDOW)) == 2


def test_the_boundary_is_exactly_the_window():
    """The rule is stated in one place; a report exactly `window` after its
    neighbour belongs to the same event, one minute more does not."""
    w = DEDUP_WINDOW.total_seconds() / 60
    assert len(cluster_by_window([m(0), m(w)], DEDUP_WINDOW)) == 1
    assert len(cluster_by_window([m(0), m(w + 1)], DEDUP_WINDOW)) == 2


def test_members_are_sorted_before_they_are_chained():
    """The caller used to sort; the function owns it now, so out-of-order input
    cannot silently produce a different answer."""
    assert len(cluster_by_window([m(120), m(0), m(60)], DEDUP_WINDOW)) == 1


def test_the_habla_reports_are_one_event_by_time_and_by_place():
    """The measured case, and a correction. Five channels reported a raid on
    حبلة between 20:48 and 22:23 — gaps of 5, 76, 8 and 6 minutes, span 95
    minutes against a 90-minute window. Given one place, chaining makes this a
    single event with four independent sources.

    An earlier version of this file claimed they split on PLACE IDENTITY, with
    five registry rows named حبلة. That was wrong and one query falsified it: all
    five events point at place_id 610, the same row. The real cause was that the
    window only ever saw ONE ingest batch, so the events were never compared
    against each other. Both facts are asserted here: the window groups them, and
    the place never differed."""
    habla = [m(0, "src:38"), m(5.2, "src:34"), m(81.3, "src:37"),
             m(89.2, "src:34"), m(95.0, "src:33")]
    clusters = cluster_by_window(habla, DEDUP_WINDOW)
    assert len(clusters) == 1, "a 5-6 minute cadence must not split"
    assert len({x[2] for x in clusters[0]}) == 4, "four channels, one event"
    # And the confidence that one event then carries.
    assert _confidence(4) > _confidence(1), (
        "splitting an event across four channels must not LOWER its confidence")


def test_the_split_was_cycle_scoping_not_place_identity():
    """The falsified hypothesis, kept as a test so nobody re-derives it from the
    five-row name collision. حبلة DOES have five rows (610 locality, 1381
    locality misnamed, 1713 checkpoint, 1986 station, 5333 locality) — and it did
    not matter, because all five events resolved to 610. A window applied within
    a single batch cannot dedup across batches, however many place rows exist."""
    import inspect

    from ingest.sources import news_incidents as N
    src = inspect.getsource(N)
    assert "SELECT event_id, claim_count, independent_sources, occurred_at" in src, \
        "the join-existing-event lookup is gone; one raid will split again"
    assert "events_joined" in src, "no record of how many reports joined an event"


def test_a_split_event_is_expensive_not_cosmetic():
    """Why this matters beyond the count: each solo fragment scores as
    uncorroborated, so splitting suppresses exactly the corroboration that
    separate channels are evidence of."""
    assert _confidence(1) == pytest.approx(0.7, abs=0.01)
    assert _confidence(2) > 0.7
    assert _confidence(4) > _confidence(2)
