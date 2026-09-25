"""G3: stable event identity (audit F084 — no test proved it). The key is a
pure function of (type, place, name key, first claim id) and independent of
the classifier version; on the real database every believed event that
records its first claim carries exactly that key, and the unique index that
makes 'one key, one event' true exists."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.sources import news_incidents as NI                             # noqa: E402


def test_the_key_is_deterministic_and_version_independent(monkeypatch):
    k = NI._stable_key("raid", 31, "huwara", 1000)
    assert k == NI._stable_key("raid", 31, "huwara", 1000) and len(k) == 20
    assert k != NI._stable_key("closure", 31, "huwara", 1000)
    assert k != NI._stable_key("raid", 32, "huwara", 1000)
    assert k != NI._stable_key("raid", 31, "huwwara", 1000)
    assert k != NI._stable_key("raid", 31, "huwara", 1001)
    assert NI._stable_key("raid", 31, None, 1000) == NI._stable_key("raid", 31, "", 1000)
    monkeypatch.setattr(NI, "CLASSIFIER_VERSION", "99.0.0")
    assert NI._stable_key("raid", 31, "huwara", 1000) == k


def test_every_event_that_records_its_first_claim_carries_its_key():
    try:
        from resolve.db import connect
        cm = connect()
        conn = cm.__enter__()
    except Exception as e:                                                  # noqa: BLE001
        pytest.skip(str(e))
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT 1 FROM pg_indexes WHERE indexname = 'event_stable_key_uniq'""")
            assert cur.fetchone(), "the one-key-one-event index is missing"
            cur.execute("""SELECT event_type, place_id, COALESCE(attrs->>'name_key',''),
                                  (attrs->>'first_claim_id')::bigint, attrs->>'stable_key'
                             FROM event
                            WHERE attrs->>'classifier' = %s AND status = 'believed'
                              AND attrs ? 'first_claim_id' AND attrs ? 'stable_key'
                            ORDER BY event_id DESC LIMIT 300""", (NI.CLASSIFIER,))
            rows = cur.fetchall()
            assert rows, "no events record first_claim_id yet"
            bad = [r for r in rows if NI._stable_key(r[0], r[1], r[2] or None, r[3]) != r[4]]
            assert not bad, bad[:3]
            cur.execute("""SELECT attrs->>'stable_key', count(*) FROM event
                            WHERE attrs ? 'stable_key' GROUP BY 1 HAVING count(*) > 1 LIMIT 3""")
            assert cur.fetchall() == []
    finally:
        cm.__exit__(None, None, None)
