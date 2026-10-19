"""Migration 131: arrests as the prisoners' organisations count them, read from
the archive (2026-10-19). Pure tests run anywhere; the store tests skip until
the migration is applied and the loader has run."""
from __future__ import annotations

import json

import pytest

from ops import load_arrests_press as L


def test_monthly_rows_become_total_children_women_on_the_scoped_place():
    rows = [{"doc_id": 1, "date": "2022-02-01T10:00:00+00:00", "publisher": "x", "url": "u", "period": "2022-01", "basis": "named",
             "authority": "pcps", "total": 570, "children": 72, "women": 8, "by_governorate": None, "quote": "570 حالة اعتقال خلال شهر يناير",
             "where": "title", "scope": "West Bank", "outlets": 1, "doc_ids": [1]},
            {"doc_id": 2, "date": "2026-06-02T10:00:00+00:00", "publisher": "y", "url": "v", "period": "2026-05", "basis": "named",
             "authority": None, "total": 101, "children": None, "women": None, "by_governorate": None, "quote": "101 حالة اعتقال في القدس خلال مايو",
             "where": "title", "scope": "Jerusalem", "outlets": 1, "doc_ids": [2]}]
    obs = L.monthly_observations(rows)
    got = {(o["indicator"], o["place_id"]): o["value"] for o in obs}
    assert got == {("prisoners.arrests_reported.total", 2): 570, ("prisoners.arrests_reported.children", 2): 72,
                   ("prisoners.arrests_reported.women", 2): 8, ("prisoners.arrests_reported.total", 11): 101}
    first = obs[0]
    assert first["occurred"].isoformat() == "2022-01-01T00:00:00+00:00" and first["precision"] == "month"
    assert first["stable"] == "arrests_press:total:pcps:2:2022-01"
    assert json.loads(first["attrs"])["authority"] == "pcps" and json.loads(obs[3]["attrs"])["authority"] == "unnamed"


def test_daily_rows_are_one_value_a_day_on_the_west_bank():
    obs = L.daily_observations([{"date": "2023-12-26", "arrests_overnight": 55, "statements": 6, "agree": 6, "doc_ids": [1, 2], "quote": "q"}])
    assert len(obs) == 1 and obs[0]["indicator"] == "prisoners.arrests_reported.overnight"
    assert obs[0]["value"] == 55 and obs[0]["place_id"] == 2 and obs[0]["precision"] == "day"
    assert obs[0]["stable"] == "arrests_press:overnight:2023-12-26"


@pytest.fixture
def db():
    try:
        from resolve.db import connect
        cm = connect(); c = cm.__enter__()
    except Exception as e:                                             # noqa: BLE001
        pytest.skip(f"no database here: {type(e).__name__}")
    try:
        c.execute("SET default_transaction_read_only = on"); yield c
    finally:
        cm.__exit__(None, None, None)


def test_arrests_served_with_quotes_and_authorities(db):
    ds = db.execute("SELECT dataset_id FROM dataset WHERE key = 'arrests_press'").fetchone()
    if not ds:
        pytest.skip("migration 131 not applied")
    n = db.execute("SELECT count(*) FROM databank_serving WHERE dataset_key = 'arrests_press'").fetchone()[0]
    if not n:
        pytest.skip("not loaded yet")
    assert n >= 600
    rows = db.execute("""SELECT indicator, attrs->>'authority', attrs->>'quote' FROM databank_serving
                         WHERE dataset_key = 'arrests_press' AND indicator = 'prisoners.arrests_reported.total' LIMIT 50""").fetchall()
    assert all(r[1] and r[2] for r in rows)
    jan22 = db.execute("""SELECT value_num FROM databank_serving WHERE dataset_key = 'arrests_press'
                          AND indicator = 'prisoners.arrests_reported.total' AND occurred_at = '2022-01-01' AND attrs->>'authority' = 'pcps'""").fetchone()
    assert jan22 and float(jan22[0]) == 570
    days = db.execute("SELECT count(*) FROM databank_serving WHERE dataset_key = 'arrests_press' AND indicator = 'prisoners.arrests_reported.overnight'").fetchone()[0]
    assert days >= 200
