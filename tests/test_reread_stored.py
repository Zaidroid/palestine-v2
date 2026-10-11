"""The stored road lines, read again (ingest/sources/checkpoints.py --reread).

    .venv/bin/python -m pytest tests/test_reread_stored.py -q

A line is read when it is imported, by the reader as it stood that day. When
the reader changes, what is already stored keeps the old reading until it is
re-read. The plan for one stored v1 update is pure, and tested here: what
becomes of its archival row, which of its facts are superseded, which facts
are written, and which are left to v2's own reader.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade.checkpoint_text import read  # noqa: E402
from ingest.sources.checkpoints import LEGACY_KIND, _reread_plan  # noqa: E402

AT = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)


def row(oid, kind, value, direction="both", modality="assertion"):
    """(state_obs_id, observed_at, place_id, state_kind, value, direction, modality, source_id, attrs)"""
    return (oid, AT, 7, kind, value, direction, modality, 3, {"channel": "c", "msg_id": 1})


def plan(line, rows, v2=()):
    p = _reread_plan(rows, read(line), set(v2))
    return ([(a[3], a[4]) for a in p["archival"]],
            sorted(s[0] for s in p["supersede"]),
            sorted((k, d, v) for (k, d, v), _ in p["insert"]))


def test_a_stored_question_stops_being_a_fact():
    """"بيت ايل لاي ساعة فاتح" was asserted as open 40 times."""
    arch, sup, ins = plan("بيت ايل لاي ساعة فاتح",
                          [row(1, LEGACY_KIND, "open"), row(2, "checkpoint_flow", "open")])
    assert arch == [("assertion", "question")] and sup == [2] and ins == []


def test_a_line_the_reader_can_now_read_gets_its_fact():
    arch, sup, ins = plan("عين سينيا حاجز للخارج",
                          [row(1, LEGACY_KIND, "idf", modality="unparsed")])
    assert arch == [("unparsed", "assertion")] and sup == []
    assert ins == [("checkpoint_idf", "outbound", "present")]


def test_a_changed_reading_supersedes_the_old_fact_and_writes_the_new():
    """"X حاجز للخارج ❌" was read as closed, off the emoji; it is a checkpoint."""
    arch, sup, ins = plan("عين سينيا حاجز للخارج ❌",
                          [row(1, LEGACY_KIND, "closed"),
                           row(2, "checkpoint_flow", "closed", "outbound")])
    assert arch == [] and sup == [2]
    assert ins == [("checkpoint_idf", "outbound", "present")]


def test_a_reading_that_stands_is_not_touched():
    assert plan("عطاره سالك", [row(1, LEGACY_KIND, "open"),
                               row(2, "checkpoint_flow", "open")]) == ([], [], [])


def test_what_v2s_reader_already_wrote_is_not_written_beside_it():
    arch, sup, ins = plan("عين سينيا حاجز للخارج",
                          [row(1, LEGACY_KIND, "idf", modality="unparsed")],
                          v2={"checkpoint_idf"})
    assert arch == [("unparsed", "assertion")] and ins == []


def test_a_fact_already_superseded_is_left_alone():
    """The second run finds nothing: a re-read is safe to repeat."""
    rows = [row(1, LEGACY_KIND, "open", modality="question"),
            row(2, "checkpoint_flow", "open", modality="superseded")]
    assert plan("بيت ايل لاي ساعة فاتح", rows) == ([], [], [])


def test_tomorrow_is_taken_back():
    arch, sup, _ = plan("الجسر يوم غد السبت مغلق بكلا الاتجاهين",
                        [row(1, LEGACY_KIND, "closed"), row(2, "checkpoint_flow", "closed")])
    assert arch == [("assertion", "unparsed")] and sup == [2]
