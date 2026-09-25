"""P1-B.2 — the databank says whose data it is, and a partner gets only what may
be carried away (migration 086 + serve/licence.py ZAID-10)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import licence as L                                              # noqa: E402

MIGRATION = "086_databank_honesty.sql"


def _payload():
    return {"answer": "demolitions — آخر الأرقام: 678", "answer_en": "demolitions — latest: 678",
            "count": 3,
            "items": [{"indicator": "a", "redistribution": "no-redistribution", "source_key": "ocha_demolitions"},
                      {"indicator": "b", "redistribution": "attribution", "source_key": "worldbank"},
                      {"indicator": "c", "redistribution": "ask", "source_key": "ioda"}],
            "latest_by_indicator": [{"indicator": "a", "redistribution": "no-redistribution"}]}


def test_a_partner_payload_carries_only_redistributable_rows_and_says_so():
    out = L.apply("databank", _payload(), "partner")
    assert [it["indicator"] for it in out["items"]] == ["b"] and out["latest_by_indicator"] == []
    w = out["licence"]["withheld"]
    assert w["rows"] == 2 and "ZAID-10" in w["reason"]
    assert "محجوبة" in out["answer"] and "withheld" in out["answer_en"]
    assert "678" in out["answer"]                      # the cited fact stays


def test_the_house_tier_is_not_cut():
    out = L.apply("databank", _payload(), "house")
    assert len(out["items"]) == 3 and "withheld" not in out["licence"]


def test_an_unknown_category_names_the_real_ones(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("databank", category="nosuchthing"))
    assert "demolitions" in p["categories"] and "ما في فئة اسمها" in p["answer"]


def test_the_refusal_points_at_a_real_mechanism():
    from serve.correlate import check_comparable
    s = {"indicator": "x", "measure_kind": "cumulative", "place_grain": "region", "concept_key": None}
    t = {"indicator": "y", "measure_kind": "flow", "place_grain": "region", "concept_key": None}
    assert any("detrend=diff" in r for r in check_comparable(s, t))
    assert "v_flow" not in " ".join(check_comparable(s, t))


def _applied() -> bool:
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (MIGRATION,))
        return cur.fetchone() is not None


def test_pcbs_is_pcbs_and_the_world_bank_is_the_world_bank():
    if not _applied():
        pytest.skip(f"{MIGRATION} not applied")
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT source_key FROM databank_serving WHERE v1_category = 'pcbs'""")
        assert {r[0] for r in cur.fetchall()} == {"pcbs_direct"}
        cur.execute("""SELECT count(*) FROM databank_serving WHERE dataset_key = 'v1_pcbs_pcbs'
                        AND source_key <> 'worldbank'""")
        assert cur.fetchone()[0] == 0
        cur.execute("""SELECT count(*) FROM databank_serving p JOIN databank_serving e
                         ON e.dataset_key = 'v1_economic_worldbank' AND p.dataset_key = 'v1_pcbs_pcbs'
                        AND replace(e.indicator, 'economic.', '') = replace(p.indicator, 'pcbs.', '')
                        AND e.occurred_at = p.occurred_at AND e.value_num IS NOT DISTINCT FROM p.value_num""")
        assert cur.fetchone()[0] == 0                   # no double count left


def test_the_annual_casualty_figure_carries_its_warning(mcp_call, mcp_payload):
    if not _applied():
        pytest.skip(f"{MIGRATION} not applied")
    p = mcp_payload(mcp_call("databank", category="casualties", indicator="casualties.annual_total"))
    assert "ما بيشمل شهداء حرب غزة" in p["answer"] and "EXCLUDES the Gaza war dead" in p["answer_en"]


def test_the_pcbs_spec_no_longer_loads():
    import yaml
    spec = yaml.safe_load((ROOT / "db" / "mappings" / "pcbs.yaml").read_text())
    assert spec.get("migrate") is False and "086" in spec.get("skip_reason", "")
