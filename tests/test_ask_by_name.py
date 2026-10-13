"""A series that is served when it is asked for by name (migration 114).

2026-10-13: Peace Now's population of each of 141 settlements was loaded as 141
ordinary series on the rehearsal copy, and the answer to "settlements" became
three single settlements' counts for May 2024; the West Bank total had left it.
One declared fact about a series, `ask_by_name`, keeps such a family out of its
category's rows unless it is asked for, and the answer says it is there."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAMILY = "settlements.population_by_settlement."


def test_the_settlement_rule_declares_it_and_the_total_s_rule_does_not():
    from ingest.databank import load_spec
    (rule,) = load_spec("settlements_by_settlement")["registry"]["rules"]
    assert rule["when"] == {"prefix": FAMILY} and rule["ask_by_name"] is True
    for r in load_spec("settlements")["registry"]["rules"]:
        assert not r.get("ask_by_name")


def test_the_parked_parent_rule_declares_it_and_the_status_series_rule_does_not():
    """Zaid, 2026-10-13: the spoken funding answer led with a parked parent,
    a contribution whose money is already counted under its child flows."""
    from ingest.databank import load_spec
    parked, status = load_spec("funding")["registry"]["rules"]
    assert parked["when"] == {"equals": "funding.parked_parent"} and parked["ask_by_name"] is True
    assert status["when"] == {"prefix": "funding."} and not status.get("ask_by_name")


def test_the_registry_loader_carries_the_flag_from_a_rule():
    from ops import load_registry as L
    assert "ask_by_name" in L.FIELDS


def test_the_migration_adds_one_column_and_gives_up_rather_than_wait():
    sql = (ROOT / "db/migrations/114_series_asked_for_by_name.sql").read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout = '5s'" in sql
    assert "ADD COLUMN IF NOT EXISTS ask_by_name boolean NOT NULL DEFAULT false" in sql
    body = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    assert "UPDATE" not in body and "DELETE" not in body      # declares nothing by itself


def test_the_spoken_answers_say_the_family_is_there():
    from serve import mcp_en
    d = {"by_name_only": {"series": 141, "example_en": "Population of the Israeli settlement of Ariel, West Bank (Peace Now)"}}
    said = mcp_en._by_name_note_en(d)
    assert "141 series" in said and "asked for by name" in said and "Ariel" in said
    assert mcp_en._by_name_note_en({}) == "" and mcp_en._by_name_note_en({"by_name_only": {"series": 0}}) == ""


def _flagged():
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM information_schema.columns
                        WHERE table_name = 'indicator_def' AND column_name = 'ask_by_name'""")
        if not cur.fetchone()[0]:
            pytest.skip("migration 114 not applied")
        # the settlements family alone: other categories hold series by name too
        # (a parked funding parent)
        cur.execute("""SELECT count(*) FROM indicator_def i WHERE i.ask_by_name AND EXISTS
                        (SELECT 1 FROM databank_serving ds WHERE ds.indicator = i.indicator
                            AND ds.v1_category = 'settlements')""")
        n = cur.fetchone()[0]
    if not n:
        pytest.skip("no series is served under the flag yet")
    return n


def test_a_category_answers_with_its_own_series_and_says_the_family_is_held(mcp_call, mcp_payload):
    n = _flagged()
    p = mcp_payload(mcp_call("databank", tier="house", category="settlements"))
    assert p["items"] and not any(i["indicator"].startswith(FAMILY) for i in p["items"])
    assert p["items"][0]["indicator"] == "settlements.settler_population"
    assert p["by_name_only"]["series"] == n and p["by_name_only"]["indicator_prefix"] == FAMILY
    assert f"{n:,} series" in p["answer_en"] and f"{n:,} سلسلة" in p["answer"]
    assert "settlers in" in p["answer_en"], "the West Bank total is the category's figure"


def test_asked_for_by_name_a_member_series_is_served(mcp_call, mcp_payload):
    _flagged()
    p = mcp_payload(mcp_call("databank", tier="house", category="settlements",
                             indicator=FAMILY + "pn0016", limit=3))
    assert p["items"] and {i["indicator"] for i in p["items"]} == {FAMILY + "pn0016"}
    assert "by_name_only" not in p and "Ariel" in p["answer_en"]
    # the family's own prefix lists its members; a prefix that also names the
    # total keeps them out
    fam = mcp_payload(mcp_call("databank", tier="house", category="settlements", indicator=FAMILY, limit=5))
    assert fam["items"] and all(i["indicator"].startswith(FAMILY) for i in fam["items"])
    both = mcp_payload(mcp_call("databank", tier="house", category="settlements", indicator="settlements.", limit=5))
    assert not any(i["indicator"].startswith(FAMILY) for i in both["items"])


def test_a_category_that_holds_no_such_series_is_untouched(mcp_call, mcp_payload):
    _flagged()
    p = mcp_payload(mcp_call("databank", tier="house", category="prisoners"))
    assert "by_name_only" not in p
