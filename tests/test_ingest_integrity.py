"""Writers that must neither skip a row nor write one twice (audit 2026-09-25).

Hard rule 2 — no data loss. F007: the v1 checkpoint importer's cursor was
MAX(observed_at) over a state kind the crowd also writes with now(), and v1
rows inserted out of message-date order fell below it; either way they were
skipped forever. F205: the incident writer re-inserted every closure
observation on each re-read. These run the writers' own SQL against the
database inside a transaction that is rolled back (main-server, or the local
test DB). Skipped without one.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.sources import checkpoints as ck                      # noqa: E402


@pytest.fixture()
def cur():
    try:
        import psycopg
        from resolve.db import dsn
        conn = psycopg.connect(dsn())
    except Exception as e:                                          # noqa: BLE001
        pytest.skip(f"no database: {e}")
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO place (kind, name_en, geom, servable)
                         VALUES ('checkpoint','_t_v1cursor',
                                 ST_SetSRID(ST_MakePoint(35.2,32.2),4326), true)
                         RETURNING place_id""")
            pid = c.fetchone()[0]
            c.execute("""INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                                             attribution_text,authority_rank)
                         VALUES ('_t_v1cursor','t','telegram','NONE',false,'t',5)
                         RETURNING source_id""")
            sid = c.fetchone()[0]
            yield c, pid, sid
    finally:
        conn.rollback()
        conn.close()


def _insert(cur, observed, attrs):
    c, pid, sid = cur
    c.execute("""INSERT INTO state_observation
                   (place_id,state_kind,value,raw_value,observed_at,source_id,confidence,
                    direction,direction_explicit,modality,attrs)
                 VALUES (%s,%s,'open','open',%s,%s,0.85,'both',false,'assertion',%s)""",
              (pid, ck.LEGACY_KIND, observed, sid, json.dumps(attrs, ensure_ascii=False)))


def test_ingest_01_a_crowd_row_does_not_move_the_v1_cursor(cur):
    """A crowd report on checkpoint_status at now() moved the cursor past v1
    rows dated a few seconds earlier that v1 had not written yet."""
    far_future = datetime.now(timezone.utc) + timedelta(days=3650)
    imported = far_future - timedelta(hours=1)
    _insert(cur, imported, ck._legacy_attrs("ch", 7, "k1", "حوارة سالك", "open", ""))
    _insert(cur, far_future, {"handle": "stranger"})             # no canonical_key
    c = cur[0]
    c.execute(ck.CURSOR_SQL, (ck.LEGACY_KIND,))
    assert c.fetchone()[0] == imported


def test_ingest_01b_a_row_already_imported_is_recognised_on_re_read(cur):
    """The overlap re-read must know a row it already has, or it imports it
    twice. The identity is rebuilt from v1's columns exactly as stored."""
    observed = datetime(2099, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    raw = "حوارة سالك بالاتجاهين " * 30                      # longer than the 300 kept
    _insert(cur, observed, ck._legacy_attrs("ch", 12345, "k1", raw, "open", ""))
    _insert(cur, observed, ck._legacy_attrs(None, None, "k2", None, "closed", "inbound"))
    c = cur[0]
    c.execute(ck.SEEN_SQL, (ck.LEGACY_KIND, observed - ck.OVERLAP))
    seen = {tuple(r) for r in c.fetchall()}
    assert ck._v1_identity("ch", 12345, "k1", "", raw, observed) in seen
    assert ck._v1_identity(None, None, "k2", "inbound", None, observed) in seen
    # a different line of the same message is a different row
    assert ck._v1_identity("ch", 12345, "k1", "", "حوارة مسكر", observed) not in seen


def test_ingest_01c_the_re_read_reaches_behind_the_cursor():
    import inspect
    src = inspect.getsource(ck.import_updates)
    assert "since - OVERLAP" in src and ck.OVERLAP >= timedelta(hours=8)


def test_classifier_15_a_re_read_does_not_duplicate_a_closure_observation(cur):
    """F205 — every version bump without --rebuild inserted one more identical
    road_closure 'closed' row per closure event."""
    from ingest.sources.news_incidents import CLOSURE_OBS_SQL, STATE_KIND_CLOSURE
    c, pid, sid = cur
    params = {"place_id": pid, "kind": STATE_KIND_CLOSURE, "raw": "اغلاق",
              "at": datetime(2099, 5, 6, 7, 8, 9, tzinfo=timezone.utc),
              "source_id": sid, "conf": 0.7, "event": "424242",
              "attrs": json.dumps({"from_event": 424242, "incident_type": "closure"})}
    c.execute(CLOSURE_OBS_SQL, params)
    first = c.rowcount
    c.execute(CLOSURE_OBS_SQL, params)                              # the re-read
    assert (first, c.rowcount) == (1, 0)
    c.execute("SELECT count(*) FROM state_observation WHERE place_id=%s AND state_kind=%s",
              (pid, STATE_KIND_CLOSURE))
    assert c.fetchone()[0] == 1
