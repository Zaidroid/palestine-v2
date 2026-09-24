"""A name match must never answer confidently about the wrong place.

The partner's QA pass found the worst bug this system can have: asking for
"Zaatara" answered about عطارة (Atara) — 11 km away and in the opposite state —
with a match score of 0.738 that never left the database. These tests hold both
halves of the fix: the common spelling now resolves exactly, and any remaining
approximate match says so in the answer a human actually reads.
"""
from fastapi.testclient import TestClient

from serve.app import app
from serve.mcp_en import connectivity_now as connectivity_en

client = TestClient(app)


def _status(name: str) -> dict:
    from serve.mcp_server import checkpoint_status
    return checkpoint_status(name)


def test_the_common_english_spelling_finds_the_right_checkpoint():
    d = _status("Zaatara")
    assert "زعتر" in (d.get("name") or ""), f"resolved to {d.get('name')}, the wrong place"
    assert d["match"]["score"] > 0.9, "an exact alias should not be a fuzzy guess"
    assert "مش متأكد" not in d["answer"] and "تنبيه" not in d["answer"]


def test_other_spellings_of_the_same_junction_land_there_too():
    for spelling in ("zatar", "Zaatara checkpoint"):
        assert "زعتر" in (_status(spelling).get("name") or ""), spelling


def test_an_approximate_match_says_so_out_loud():
    d = _status("Hawara")
    answer = d["answer"]
    assert ("مش متأكد" in answer) or ("تنبيه" in answer), \
        f"a non-exact match must carry its doubt: {answer}"


def test_a_low_score_leads_with_the_doubt_rather_than_burying_it():
    d = _status("Hawara")
    if d.get("match") and d["match"]["score"] < 0.8:
        assert d["answer"].startswith("مش متأكد"), d["answer"]


def test_the_match_travels_in_the_payload():
    d = _status("Huwwara")
    assert d.get("match") and "score" in d["match"] and "resolved_to" in d["match"]


def test_the_english_connectivity_answer_never_invents_a_gap():
    assert "normally" in connectivity_en({"status": "normal"})
    assert "No current measurement" in connectivity_en({"status": "unknown"})
    # an unrecognised status says what it is instead of claiming silence
    assert "No current measurement" not in connectivity_en({"status": "weird"})


def test_the_news_area_filter_resolves_the_name_before_matching_text():
    r = client.get("/v2/news/latest", params={"area": "Ramallah", "limit": 3})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "resolving Ramallah must find the Arabic-language reports"
    assert any("رام الله" in i["text"] for i in items)
    newest = max(i["reported_at"] for i in items)
    assert newest[:10] >= "2026-09-23", f"stale literal match crept back: {newest}"


def test_crossings_and_checkpoints_stop_contradicting_each_other():
    """Allenby read "no source has ever reported this" while the checkpoint
    layer listed جسر الملك حسين with a reading minutes old: the same place,
    known to one layer and denied by the other."""
    d = client.get("/v2/crossings").json()
    allenby = [c for c in d["crossings"] if "الملك حسين" in (c["name"] or "")
               or "Allenby" in (c["name_en"] or "")]
    assert allenby, "the bridge is one of the crossings"
    b = allenby[0]
    # The reading may have DECAYED since (it did on 2026-09-24 at 14 hours old,
    # and this test failed on the data rather than on the defect). What must
    # hold is that the checkpoint layer answers for the bridge at all.
    assert b["basis"] == "checkpoint_flow", "the payload must say where it came from"
    assert b["value"] != "unknown" or b["last_known_value"] is not None, \
        "the checkpoint layer holds a reading (current or decayed) for it"
    assert b["age_minutes"] is not None
    assert len(d["crossings"]) >= 1
