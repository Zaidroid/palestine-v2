"""P6 — the palhub loader must never starve behind its own LIMIT.

    ./.venv/bin/python -m pytest tests/test_palhub_backlog.py -q

WHAT WENT WRONG (2026-08-17)
`ops/ingest-palhub-roads.sh` runs the loader with `--limit 500` every five
minutes. The loader asked for the oldest 500 claims and only THEN discarded the
ones already in `ingest_seen`. From the moment the timer was installed
(2026-08-02 09:04) the seen set already covered 1,816 claims — the hand-run
backfill twenty minutes earlier — so every scheduled run fetched 500 rows that
were all seen, did nothing, and reported success. Fifteen days of a green
collector that had never once written a row, and the source went dark behind it.

A LIMIT is a batch size. Applied before the cursor, it is a ceiling on how far
the source may ever be read — and the failure is invisible from outside,
because "no new work" and "no work reachable" print the same zero.

So the pending set is computed in SQL, and the LIMIT applies to what is left.
These run against the real database inside a transaction that is rolled back,
because the thing under test is the query.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.sources.palhub_roads import PENDING_SQL, SOURCE_KEY   # noqa: E402
from resolve.db import dsn                                        # noqa: E402


@pytest.fixture()
def tx():
    """A transaction that is always rolled back. Never commits."""
    with psycopg.connect(dsn()) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


def _fixture_source(cur, n_claims: int, n_seen: int) -> None:
    """A synthetic source carrying `n_claims` claims, the oldest `n_seen` of
    which have already been processed."""
    key = f"tg_test_palhub_{uuid.uuid4().hex[:8]}"
    cur.execute("""INSERT INTO source (key, name, kind, license_spdx,
                                       commercial_use, attribution_text,
                                       authority_rank)
                   VALUES (%s,'test palhub','telegram','NONE',false,'test',4)
                   RETURNING source_id""", (key,))
    source_id = cur.fetchone()[0]
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    ids = []
    for i in range(n_claims):
        cur.execute(
            """INSERT INTO claim (source_id, external_id, raw_ref, raw_text,
                                  lang, claim_type, reported_at)
               VALUES (%s,%s,%s,%s,'ar','road_status',%s) RETURNING claim_id""",
            (source_id, f"m{i}", f"test:{i}", f"bulletin {i}",
             base + timedelta(minutes=i)))
        ids.append(cur.fetchone()[0])
    for cid in ids[:n_seen]:
        cur.execute("INSERT INTO ingest_seen (source_id, external_id) "
                    "VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (source_id, str(cid)))
    return key, ids


def test_the_batch_advances_past_everything_already_seen(tx):
    """The regression itself: 600 claims, the oldest 520 already processed, a
    batch size of 500. The buggy query returned 500 rows of which 500 were
    seen — zero work, forever. The fix must return the 80 unseen ones."""
    with tx.cursor() as cur:
        key, ids = _fixture_source(cur, n_claims=600, n_seen=520)
        cur.execute(PENDING_SQL, (key, 500))
        rows = cur.fetchall()
    assert len(rows) == 80, (
        "the loader can only ever reach the oldest `limit` claims — "
        "the seen filter must run in SQL, before the LIMIT")
    assert [r[0] for r in rows] == ids[520:]


def test_the_batch_size_still_caps_a_large_backlog(tx):
    """The LIMIT must still be a batch size. A source that has been dark for a
    week must not try to load its whole backlog in one five-minute tick."""
    with tx.cursor() as cur:
        key, _ = _fixture_source(cur, n_claims=600, n_seen=0)
        cur.execute(PENDING_SQL, (key, 500))
        assert len(cur.fetchall()) == 500


def test_the_batch_is_the_oldest_pending_first(tx):
    """Order matters beyond tidiness: the loader skips an unchanged restatement
    by comparing against the last value it wrote, so replaying a source out of
    order would record a stale state as the newest one."""
    with tx.cursor() as cur:
        key, ids = _fixture_source(cur, n_claims=60, n_seen=10)
        cur.execute(PENDING_SQL, (key, 500))
        rows = cur.fetchall()
    assert [r[0] for r in rows] == ids[10:]
    assert [r[2] for r in rows] == sorted(r[2] for r in rows)


def test_the_live_road_source_has_no_unreachable_backlog(tx):
    """The property that actually broke, asserted against the real source: with
    the scheduled batch size, the claims the loader can see must include
    everything it has not yet processed — or it has silently stopped."""
    with tx.cursor() as cur:
        cur.execute("SELECT source_id FROM source WHERE key = %s", (SOURCE_KEY,))
        row = cur.fetchone()
        if row is None:
            pytest.skip("palhub road source not present in this database")
        cur.execute(
            """SELECT count(*) FROM claim c
                WHERE c.source_id = %s
                  AND NOT EXISTS (SELECT 1 FROM ingest_seen g
                                   WHERE g.source_id = c.source_id
                                     AND g.external_id = c.claim_id::text)""",
            (row[0],))
        pending = cur.fetchone()[0]
        cur.execute("SELECT external_id FROM ingest_seen WHERE source_id = %s",
                    (row[0],))
        seen = {r[0] for r in cur.fetchall()}
        cur.execute(PENDING_SQL, (SOURCE_KEY, 500))
        batch = cur.fetchall()
    usable = [r for r in batch if str(r[0]) not in seen]
    assert len(usable) == min(pending, 500), (
        f"{pending} claims unprocessed, but a 500-row batch reaches only "
        f"{len(usable)} of them — the loader is starving behind its own LIMIT")
