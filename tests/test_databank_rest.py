"""The rest of the databank's defects from the 2026-10-11 audit (finding 08 and
plan H), fixed on 2026-10-12/13. One section per defect; each test says in its
name the thing a reader of an answer would have got wrong."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import licence                                                    # noqa: E402

FILTERED = {"grade": "share-alike", "partner_tier": "filtered"}


# ── the partner tier is a commercial one ─────────────────────────────────────
# Measured 2026-10-12: 22,140 served rows are licensed for non-commercial use
# only and graded attribution or share-alike (WHO 12,577, UCDP 7,638, OONI
# 1,376, IMF 474, the UNRWA camp rows 75). The partner filter asked for the
# grade alone, so every one of them travelled in a partner payload.

def _who_row(**over):
    return {"indicator": "health.x", "source_key": "who", "redistribution": "share-alike",
            "commercial_use": False, "value_num": 1.0} | over


def test_a_non_commercial_row_stays_out_of_a_partner_payload_and_the_cut_says_why():
    out = {"answer": "x", "answer_en": "x", "count": 3, "items": [
        _who_row(), _who_row(),
        {"indicator": "economic.y", "source_key": "worldbank",
         "redistribution": "attribution", "commercial_use": True}]}
    got = licence.apply("databank", out, "partner", FILTERED)
    assert [it["source_key"] for it in got["items"]] == ["worldbank"]
    w = got["licence"]["withheld"]
    assert w["rows"] == 2 and w["non_commercial_rows"] == 2
    assert w["by_source"] == {"who (share-alike, non-commercial)": 2}
    assert "non-commercial use only" in got["answer_en"]
    assert "الاستخدام التجاري" in got["answer"]
    assert got["count"] == 1


def test_a_non_commercial_series_keeps_its_summary_and_loses_its_points():
    out = {"answer": "x", "answer_en": "x", "series": [
        {"indicator": "connectivity.ooni", "redistribution": "share-alike",
         "commercial_use": False, "sources": ["OONI"],
         "points": [{"at": "2026-10-01", "value": 1}] * 7, "n": 7},
        {"indicator": "economic.y", "redistribution": "attribution",
         "commercial_use": True, "sources": ["World Bank"],
         "points": [{"at": "2020-01-01", "value": 1}] * 4, "n": 4}]}
    got = licence.apply("compare", out, "partner", FILTERED)
    ooni, wb = got["series"]
    assert ooni["points"] == [] and ooni["points_withheld"] == 7 and ooni["n"] == 7
    assert len(wb["points"]) == 4
    assert got["licence"]["withheld"]["non_commercial_rows"] == 7


def test_the_house_keeps_every_non_commercial_row():
    out = {"items": [_who_row(), _who_row()], "count": 2}
    got = licence.apply("databank", out, "house", FILTERED)
    assert len(got["items"]) == 2 and "withheld" not in got["licence"]


def test_a_row_that_does_not_say_is_judged_on_its_grade_as_before():
    # the live tier's rows and older payloads carry no flag at all
    assert licence.partner_may_carry("attribution", None) is None
    assert licence.partner_may_carry("ask", None) == "grade"
    assert licence.partner_may_carry("share-alike", False) == "non-commercial"
    assert licence.partner_may_carry("no-redistribution", False) == "grade"
    assert licence.partner_may_carry("open", True) is None


def test_the_mixed_cut_names_both_reasons():
    out = {"answer": "x", "answer_en": "x", "items": [
        _who_row(),
        {"indicator": "casualties.annual_total", "source_key": "ocha_casualties",
         "redistribution": "no-redistribution", "commercial_use": False}]}
    got = licence.apply("databank", out, "partner", FILTERED)
    assert got["items"] == []
    assert got["licence"]["withheld"]["rows"] == 2
    assert got["licence"]["withheld"]["non_commercial_rows"] == 1
    assert "redistribution or commercial use" in got["answer_en"]


def test_the_routes_hand_the_flag_to_the_licence_layer():
    src = (ROOT / "serve" / "app.py").read_text()
    assert "COALESCE(d.commercial_use, s.commercial_use)     AS commercial_use" in src
    assert '"license_spdx", "redistribution", "commercial_use")' in src
    assert '"commercial_use": commercial_use}' in src
    assert licence.table(lambda *a, **k: [], set())["partner_requires_commercial_use"] is True
