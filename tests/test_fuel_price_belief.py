"""The fuel-price belief rules (migrations 071-073), run against the real views.

Every case inserts transcriptions dated 2001 inside a transaction that is
rolled back, so the live series is never touched and never read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resolve.db import connect  # noqa: E402


@pytest.fixture
def cur():
    # connect() is a context manager; the rollback runs before it closes.
    with connect() as conn:
        try:
            with conn.cursor() as c:
                yield c
        finally:
            conn.rollback()


def add(cur, outlet, eff, price, *, named=True, clause=None, inferred=False,
        sha=None, version="fuel_price@3", fetched="2001-01-01 00:00+00"):
    clause = clause or f"{outlet} says diesel {price}"
    cur.execute("""INSERT INTO fuel_price_report
                     (outlet, independence_unit, content_sha256, reader_version, verdict,
                      attribution, effective_from, prices, evidence, fetched_at)
                   VALUES (%s, %s, %s, %s, 'prices', %s, %s, %s::jsonb, %s::jsonb, %s)""",
                (outlet, f"web:{outlet}", sha or f"sha-{outlet}-{eff}-{price}", version,
                 "named" if named else "implied", eff, json.dumps({"diesel": price}),
                 json.dumps({"diesel": {"clause": clause, "inferred": inferred}}), fetched))


def believed(cur, eff):
    cur.execute("""SELECT price::float FROM fuel_price_believed
                    WHERE product = 'diesel' AND effective_from = %s""", (eff,))
    return [r[0] for r in cur.fetchall()]


def test_one_outlet_is_not_enough(cur):
    add(cur, "a.test", "2001-01-01", 5.0)
    assert believed(cur, "2001-01-01") == []


def test_two_outlets_neither_naming_the_authority_are_not_enough(cur):
    add(cur, "a.test", "2001-02-01", 5.0, named=False)
    add(cur, "b.test", "2001-02-01", 5.0, named=False)
    assert believed(cur, "2001-02-01") == []


def test_two_copies_of_one_inferred_reading_are_one_reading(cur):
    same = "أسطوانة 2.5 كغم 18 شيكلا، و5 كغم 36"
    add(cur, "a.test", "2001-03-01", 5.0, clause=same, inferred=True)
    add(cur, "b.test", "2001-03-01", 5.0, clause=same, inferred=True)
    assert believed(cur, "2001-03-01") == []


def test_two_faithful_reprints_of_a_stated_line_are_two_readings(cur):
    same = "السولار: 8.39 شيكل/لتر"
    add(cur, "a.test", "2001-04-01", 5.0, clause=same)
    add(cur, "b.test", "2001-04-01", 5.0, clause=same, named=False)
    assert believed(cur, "2001-04-01") == [5.0]


def test_two_confirmed_rivals_are_a_conflict_and_neither_is_believed(cur):
    for o in ("a.test", "b.test"):
        add(cur, o, "2001-05-01", 5.0)
    for o in ("c.test", "d.test"):
        add(cur, o, "2001-05-01", 6.0)
    assert believed(cur, "2001-05-01") == []
    cur.execute("SELECT count(*) FROM fuel_price_conflicts WHERE effective_from = '2001-05-01'")
    assert cur.fetchone()[0] == 1


def test_a_newer_reading_of_the_same_document_withdraws_the_old_vote(cur):
    """fuel_price@1 dated a mid-month cut to the 1st; @2 re-read the same page
    and dated it to the 7th. The old reading must stop voting for the 1st."""
    add(cur, "a.test", "2001-06-01", 7.65, sha="doc", version="fuel_price@1")
    add(cur, "b.test", "2001-06-01", 7.65)
    assert believed(cur, "2001-06-01") == [7.65]
    add(cur, "a.test", "2001-06-07", 7.65, sha="doc", version="fuel_price@2",
        fetched="2001-01-02 00:00+00")
    assert believed(cur, "2001-06-01") == []
