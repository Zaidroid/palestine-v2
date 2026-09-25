"""P1-A.2 — a fresh inspection sighting is said as a state word beside the flow.

"حوارة: سالك مع تفتيش" / "Huwara: open, searching under way". To a traveller a
search is a queue even when the road is open; it used to sit in the payload's
`present` list, or trail the sentence without an age. Presence stays its own
axis in the payload (`present`, `searching`); only the words change.

Most tests here build the payload by hand, so they run anywhere; the last one
reads the live summary on main-server.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import mcp_en as EN                                               # noqa: E402
from serve import mcp_server as S                                            # noqa: E402


def _status(flow, present=(), presence_age=15, age=3, last=None):
    return {"found": True, "query": "حوارة", "match": {"resolved_to": "حوارة", "score": 1.0},
            "name": "حوارة", "name_en": "Huwara", "direction": "both",
            "flow": flow, "passable": flow != "closed", "last_known_flow": last or flow,
            "age_minutes": age, "staleness_band": "live", "confidence": 0.9,
            "independent_sources": 2, "present": list(present),
            "presence_age_minutes": presence_age if present else None,
            "by_direction": {}, "lat": 32.15, "lon": 35.25}


def _ask(monkeypatch, payload):
    monkeypatch.setattr(S, "api", lambda path, **kw: payload)
    out = S.checkpoint_status("حوارة")
    return out, EN.checkpoint_status(out)


def test_open_with_a_search_leads_with_both(monkeypatch):
    ar, en = _ask(monkeypatch, _status("open", ["inspection"]))
    assert "سالك مع تفتيش" in ar["answer"]
    assert "والتفتيش قبل 15 دقيقة" in ar["answer"]
    assert "open, searching under way" in en and "the search seen 15 min ago" in en
    assert ar["searching"] is True and ar["present"] == ["inspection"]   # still its own axis
    assert ar["answer"].count("تفتيش") == 2 and "وفي تفتيش" not in ar["answer"]


def test_congested_with_a_search(monkeypatch):
    ar, en = _ask(monkeypatch, _status("congested", ["inspection", "idf"]))
    assert "فيه أزمة وتفتيش" in ar["answer"]
    assert "وفي جيش" in ar["answer"]                  # the army is still said, once
    assert "congested, searching under way" in en and "Seen there: army" in en


def test_a_closed_checkpoint_with_a_search_says_two_facts(monkeypatch):
    ar, en = _ask(monkeypatch, _status("closed", ["inspection"]))
    assert "مغلق." in ar["answer"] and "وفي تفتيش (قبل 15 دقيقة)." in ar["answer"]
    assert "مع تفتيش" not in ar["answer"]
    assert "closed." in en and "Seen there: a search (15 min ago)." in en


def test_a_search_with_no_current_flow_is_still_current(monkeypatch):
    ar, en = _ask(monkeypatch, _status("unknown", ["inspection"], age=300, last="open"))
    assert ar["answer"].startswith("حوارة: فيه تفتيش (قبل 15 دقيقة)")
    assert "كان سالك" in ar["answer"]
    assert "a search reported (15 min ago)" in en and "said open" in en


def test_no_search_no_word(monkeypatch):
    ar, en = _ask(monkeypatch, _status("open"))
    assert "تفتيش" not in ar["answer"] and "search" not in en
    assert ar["searching"] is False


def test_the_route_speaks_who_was_seen_searching_first():
    cautions = [
        {"place": "حوارة", "place_en": "Huwara", "seen": "checkpoint_idf", "age_minutes": 30},
        {"place": "حوارة", "place_en": "Huwara", "seen": "checkpoint_idf", "age_minutes": 31},
        {"place": "زعترة", "place_en": "Za'tara", "seen": "checkpoint_inspection", "age_minutes": 12},
        {"place": "حوارة", "place_en": "Huwara", "seen": "checkpoint_inspection", "age_minutes": 40},
    ]
    seen = EN.seen_on_route(cautions)
    assert [c["place"] for c, _, _ in seen] == ["زعترة", "حوارة"]
    assert seen[1][1] == ["checkpoint_inspection", "checkpoint_idf"]    # each kind once
    assert seen[1][2] == 30                                             # the newest sighting
    en = EN.can_i_travel({"verdict": "likely_open", "cautions": cautions, "routes": [{}]})
    assert "On the way: searching at Za'tara (12 min ago); searching and army at Huwara" in en


def test_searching_is_in_every_checkpoint_row_the_api_serves():
    import inspect

    from serve import app as A
    assert '"searching": "inspection" in' in inspect.getsource(A._checkpoint_out)


def test_the_summary_names_where_searching_is_going_on(mcp_call, mcp_payload):
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM checkpoint_serving
                        WHERE direction = 'both' AND 'inspection' = ANY(present)""")
        n = cur.fetchone()[0]
    p = mcp_payload(mcp_call("checkpoints"))
    assert len(p["searching_now"]) == min(n, 20)
    if n:
        assert "فيه تفتيش هلأ عند" in p["answer"] and "Searching now at" in p["answer_en"]
    else:
        pytest.skip("no search reported anywhere right now")
