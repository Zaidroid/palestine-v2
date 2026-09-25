"""Audit 2026-09-25 F206 (CLASSIFIER-16): a version bump retracts the events
nothing stands behind — it never deletes them (hard rule 2). Real database,
every test rolled back."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.sources.news_incidents import (CLASSIFIER, STATE_KIND_CLOSURE,   # noqa: E402
                                           reassert_closure_observations,
                                           retire_unreferenced_events)


@pytest.fixture()
def db():
    try:
        from resolve.db import dsn
        import psycopg
        conn = psycopg.connect(dsn())
    except Exception as e:                                          # noqa: BLE001
        pytest.skip(f"no database: {e}")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _fixture(cur):
    cur.execute("""INSERT INTO place (kind, name_en, geom, servable)
                   VALUES ('locality', 'T_sweep', ST_SetSRID(ST_MakePoint(35.2,32.2),4326), true)
                   RETURNING place_id""")
    pid = cur.fetchone()[0]
    cur.execute("""INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                                       attribution_text,authority_rank)
                   VALUES ('_t_sweep','t','telegram','NONE',false,'t',5) RETURNING source_id""")
    sid = cur.fetchone()[0]
    cur.execute("""INSERT INTO event (event_type, place_id, occurred_at, occurred_precision,
                                      status, confidence, claim_count, independent_sources, attrs)
                   VALUES ('closure', %s, now(), 'hour', 'believed', 0.7, 0, 0, %s)
                   RETURNING event_id""",
                (pid, json.dumps({"classifier": CLASSIFIER, "stable_key": "t_sweep_key"})))
    eid = cur.fetchone()[0]
    cur.execute("""INSERT INTO state_observation
                     (place_id,state_kind,value,raw_value,observed_at,source_id,
                      confidence,direction,direction_explicit,modality,attrs)
                   VALUES (%s,%s,'closed','x',now(),%s,0.7,'both',false,'assertion',%s)""",
                (pid, STATE_KIND_CLOSURE, sid, json.dumps({"from_event": eid})))
    return pid, sid, eid


def test_sweep_retracts_and_keeps_history_instead_of_deleting(db):
    with db.cursor() as cur:
        pid, sid, eid = _fixture(cur)
        stats: dict = {}
        retire_unreferenced_events(cur, stats)
        assert stats["stale_events_swept"] >= 1
        cur.execute("SELECT status, correction_note FROM event WHERE event_id=%s", (eid,))
        status, note = cur.fetchone()
        assert status == "retracted" and "no claim stands behind it" in note
        # the believed version is filed, so an as-of query for a minute ago still returns it
        cur.execute("SELECT count(*) FROM event_history WHERE event_id=%s AND status='believed'", (eid,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT modality, attrs->>'withdrawn_reason' FROM state_observation "
                    "WHERE attrs->>'from_event' = %s", (str(eid),))
        assert cur.fetchone() == ("rejected", "event retracted")


def test_a_referenced_event_is_left_alone(db):
    with db.cursor() as cur:
        pid, sid, eid = _fixture(cur)
        cur.execute("""INSERT INTO claim (source_id,raw_ref,raw_text,claim_type,place_id,reported_at,event_id)
                       VALUES (%s,'bronze://t','x','t',%s,now(),%s)""", (sid, pid, eid))
        retire_unreferenced_events(cur, {})
        cur.execute("SELECT status FROM event WHERE event_id=%s", (eid,))
        assert cur.fetchone()[0] == "believed"


def test_a_revived_event_gets_its_closure_observation_back(db):
    with db.cursor() as cur:
        pid, sid, eid = _fixture(cur)
        retire_unreferenced_events(cur, {})
        # what the join branch does when the same stable key comes back
        cur.execute("""UPDATE event SET status='believed', correction_note=NULL
                        WHERE event_id=%s AND status='retracted'""", (eid,))
        assert reassert_closure_observations(cur, eid) == 1
        cur.execute("SELECT modality, attrs ? 'withdrawn_by' FROM state_observation "
                    "WHERE attrs->>'from_event' = %s", (str(eid),))
        assert cur.fetchone() == ("assertion", False)
        cur.execute("SELECT count(*) FROM event_history WHERE event_id=%s", (eid,))
        assert cur.fetchone()[0] == 2          # believed → retracted → believed, every version kept
