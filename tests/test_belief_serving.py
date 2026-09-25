"""The served answer, end to end through the real SQL (audit 2026-09-25, plan 02-belief).

Each test inserts synthetic observations inside a transaction, runs the belief
refresh (resolve/belief.py REFRESH_SQL) and reads what the API reads —
state_serving and checkpoint_serving — then rolls back. Needs a database with
the migrations applied (main-server, or the local test DB:
docs/audit-2026-09-25/plan/local-test-db.sh). Skipped when there is none.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KIND = "checkpoint_flow"


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


def _place(cur, name="T_serving") -> int:
    cur.execute("""INSERT INTO place (kind, name_en, geom, servable)
                   VALUES ('checkpoint', %s, ST_SetSRID(ST_MakePoint(35.2,32.2),4326), true)
                   RETURNING place_id""", (name,))
    return cur.fetchone()[0]


def _source(cur, key, kind="telegram", group=None, trust=None) -> int:
    cur.execute("""INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                                       attribution_text,authority_rank,
                                       independence_group,trust_weight)
                   VALUES (%s,%s,%s,'NONE',false,'t',5,%s,%s) RETURNING source_id""",
                (key, key, kind, group, trust))
    return cur.fetchone()[0]


def _observe(cur, pid, sid, value, direction="both", ago="1 minute"):
    cur.execute(f"""INSERT INTO state_observation
                     (place_id,state_kind,value,raw_value,observed_at,source_id,
                      confidence,direction,direction_explicit,modality)
                    VALUES (%s,%s,%s,%s, now() - interval '{ago}', %s, 0.9, %s, %s,
                            'assertion')""",
                (pid, KIND, value, value, sid, direction, direction != "both"))


def _refresh(cur):
    from resolve.belief import REFRESH_SQL
    cur.execute(REFRESH_SQL, {"kinds": [KIND]})


def _serving(cur, pid, direction="both"):
    cur.execute("""SELECT flow, reported_for, differs_by_direction
                     FROM checkpoint_serving WHERE place_id=%s AND direction=%s""",
                (pid, direction))
    return cur.fetchone()


def test_belief_01_both_row_is_the_worse_direction(db):
    """F008 — 'حوارة سالك' at 13:00, then closed inbound AND outbound at 14:05:
    the default row stayed 'open', because it only ever read 'both' reports."""
    with db.cursor() as cur:
        pid = _place(cur)
        ch = _source(cur, "_t_s1")
        _observe(cur, pid, ch, "open", "both", "65 minutes")
        _observe(cur, pid, ch, "closed", "inbound", "2 minutes")
        _observe(cur, pid, ch, "closed", "outbound", "1 minute")
        _refresh(cur)
        flow, _, differs = _serving(cur, pid)
    assert flow == "closed"
    assert differs is False


def test_belief_02_one_direction_closed_is_not_open_by_default(db):
    """F016 — a fresh inbound closure behind an older 'both' open: the default
    answer must not say open; it says closed and flags that directions differ."""
    with db.cursor() as cur:
        pid = _place(cur)
        ch = _source(cur, "_t_s2")
        _observe(cur, pid, ch, "open", "both", "60 minutes")
        _observe(cur, pid, ch, "closed", "inbound", "5 minutes")
        _refresh(cur)
        both = _serving(cur, pid)
        inbound = _serving(cur, pid, "inbound")
        outbound = _serving(cur, pid, "outbound")
    assert both[0] == "closed" and both[2] is True
    assert inbound[0] == "closed" and outbound[0] == "open"


def test_belief_03_a_fresher_both_report_wins_its_travel_direction(db):
    """F377 — the doctrine, pinned: per travel direction the freshest of
    {that direction, 'both'} wins, and reported_for says which it was."""
    with db.cursor() as cur:
        pid = _place(cur)
        ch = _source(cur, "_t_s3")
        _observe(cur, pid, ch, "closed", "outbound", "5 minutes")
        _observe(cur, pid, ch, "open", "both", "2 minutes")
        _refresh(cur)
        flow, reported_for, _ = _serving(cur, pid, "outbound")
    assert (flow, reported_for) == ("open", "both")


def test_belief_04_a_strangers_caution_cannot_blind_a_channel(db):
    """F017 — a channel says open 5 minutes ago; an unverified stranger says
    closed. The stranger's report (0.85 x 0.20 = 0.17, below the 0.25 floor)
    used to replace the channel's row and serve 'unknown'. It is dissent now."""
    with db.cursor() as cur:
        pid = _place(cur)
        ch = _source(cur, "_t_s4")
        stranger = _source(cur, "_t_s4c", "crowd", "crowd:unverified")
        _observe(cur, pid, ch, "open", "both", "5 minutes")
        _observe(cur, pid, stranger, "closed", "both", "1 minute")
        _refresh(cur)
        cur.execute("""SELECT value, last_known_value, contradicted_by
                         FROM state_serving WHERE place_id=%s AND state_kind=%s
                          AND direction='both'""", (pid, KIND))
        value, last, contradicted = cur.fetchone()
    assert value == "open" and last == "open"
    assert contradicted >= 1


def test_belief_05_a_lone_caution_with_nothing_to_contradict_is_still_recorded(db):
    """The P2.4 doctrine survives: with no reading to contradict, a stranger's
    caution is recorded (below the floor, so served as unknown-with-last-known)."""
    with db.cursor() as cur:
        pid = _place(cur)
        stranger = _source(cur, "_t_s5c", "crowd", "crowd:unverified")
        _observe(cur, pid, stranger, "closed", "both", "1 minute")
        _refresh(cur)
        cur.execute("""SELECT value, last_known_value FROM state_serving
                        WHERE place_id=%s AND state_kind=%s AND direction='both'""",
                    (pid, KIND))
        assert cur.fetchone() == ("unknown", "closed")


def test_belief_06_crowd_sources_never_feed_incidents(db):
    """F012 — a crowd note was classified as news: raid + road_closure from an
    anonymous POST. Crowd sources are registered with feeds_incidents=false,
    and migration 080 turns it off for the ones that already exist."""
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM source WHERE kind='crowd' AND feeds_incidents")
        assert cur.fetchone()[0] == 0
    import inspect
    from crowd import engine
    assert "feeds_incidents" in inspect.getsource(engine.register)
    from ingest.sources import news_incidents
    assert "s.kind <> 'crowd'" in inspect.getsource(news_incidents)
