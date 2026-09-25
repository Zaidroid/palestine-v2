"""The surface must not claim more than the data underneath it shows.

Each test here comes from the partner's QA pass of 2026-09-23, where a
hand-checked claim became a fix. They are the ones a reviewer would otherwise
have to re-derive by reading the payload by hand.
"""
from fastapi.testclient import TestClient

from serve.app import app

client = TestClient(app)


def _tool(name, args=None):
    from serve.mcp_server import TOOLS
    return TOOLS[name][0](**(args or {}))


def test_the_pattern_headline_matches_the_hours_it_summarises():
    """It said "usually open most hours" for Qalandiya while the modal hour was
    `congested` — the state a traveller most needs to know about."""
    d = _tool("place_pattern", {"place": "قلنديا"})
    tally = d["usually_by_hour_tally"]
    modal = max(tally.items(), key=lambda kv: kv[1])[0]
    assert modal in d["answer"] or {"open": "سالك", "congested": "أزمة",
                                    "closed": "مسكّر", "slow": "بطيء"}.get(modal, "") in d["answer"]
    assert set(tally) <= {"open", "closed", "congested", "slow", "unknown", "partial"}


def test_pattern_answers_from_the_flow_grain_not_the_mixed_legacy_kind():
    d = _tool("place_pattern", {"place": "حوارة"})
    for h in d["hours"]:
        for value in (h.get("counts") or {}):
            assert value not in ("idf", "police", "inspection", "settlers"), \
                "presence in a flow histogram: the same two-axes bug as insights"


def test_search_reads_the_archive_not_the_last_hundred_messages():
    """0 hits for قلنديا over 24 hours while 49 matching messages sat in the
    claim store — a 100-message window never reaches the road channel."""
    d = _tool("search", {"text": "قلنديا", "hours": 24})
    assert d.get("count", 0) > 0, d.get("answer")
    newest = d["items"][0]["reported_at"]
    assert newest[:10] >= "2026-09-22"


def test_a_retired_field_is_not_reported_as_a_stale_one():
    """Fuel availability was retired on purpose; coverage called it `stale`,
    which read as a broken feed next to a working fuel-prices feature."""
    fields = {f["state_kind"]: f for f in client.get("/v2/coverage").json()["fields"]}
    assert fields["fuel_diesel"]["coverage_state"] == "retired"
    assert fields["fuel_gasoline"]["coverage_state"] == "retired"


def test_the_staleness_band_explains_itself_once_in_the_contract():
    """Audit F051: the band note was attached to every reply and absent from
    palestine://reading-contract, where P0-A.3 said it would live. Now the
    contract carries it and the payload does not repeat it."""
    from serve.mcp_http import READING_CONTRACT
    assert "reporting rhythm" in READING_CONTRACT["staleness_band"]
    d = _tool("checkpoint_status", {"name": "حوارة"})
    assert "staleness_note" not in d and "band_note" not in d


def test_the_news_endpoint_still_answers_its_old_shape():
    """`hours` and `text` are additive: a caller that passes neither keeps the
    behaviour it had."""
    r = client.get("/v2/news/latest", params={"limit": 3})
    assert r.status_code == 200 and "items" in r.json()
    r = client.get("/v2/news/latest", params={"area": "نابلس", "limit": 2})
    assert r.status_code == 200
