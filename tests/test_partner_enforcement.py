"""Audit TRANSPORT-01 (F086): ZAID-10's partner tiers were labels on two paths —
compare returned a no-redistribution publisher's POINTS under "filtered", and
connectivity_now returned IODA's raw signals under "cited_fact_only"."""
from __future__ import annotations


from serve import licence


def test_TRANSPORT_01_withheld_series_points_leave_a_partner_payload_and_the_cut_is_named():
    out = {"answer": "x", "answer_en": "x", "series": [
        {"indicator": "casualties.annual_total", "redistribution": "no-redistribution",
         "sources": ["UN OCHA oPt"], "points": [{"at": "2008-01-01", "value": 877}] * 19,
         "n": 19, "first": "2008-01-01", "last": "2026-01-01"},
        {"indicator": "economic.sp_pop_totl", "redistribution": "attribution",
         "sources": ["World Bank"], "points": [{"at": "1990-01-01", "value": 1}] * 36}]}
    entry = {"grade": "no-redistribution", "partner_tier": "filtered"}
    got = licence.apply("compare", out, "partner", entry)
    ocha, wb = got["series"]
    assert ocha["points"] == [] and ocha["points_withheld"] == 19 and ocha["n"] == 19
    assert len(wb["points"]) == 36
    assert got["licence"]["withheld"]["rows"] == 19
    assert "19" in got["answer_en"]


def test_TRANSPORT_01_the_house_tier_keeps_every_point():
    out = {"series": [{"redistribution": "no-redistribution", "points": [{"v": 1}] * 3}]}
    got = licence.apply("compare", out, "house", {"grade": "no-redistribution",
                                                  "partner_tier": "filtered"})
    assert len(got["series"][0]["points"]) == 3


def _ioda():
    return {"answer": "reachable", "answer_en": "reachable", "attribution": "IODA",
            "observed_at": "2026-09-26T10:00:00Z", "age_minutes": 11,
            "signals": [{"bgp": 1}], "method": "3 signals", "signals_total": 3}


def test_TRANSPORT_01_a_cited_fact_only_payload_is_the_fact_its_source_and_its_age():
    got = licence.apply("connectivity_now", _ioda(), "partner",
                        {"grade": "ask", "partner_tier": "cited_fact_only"})
    assert "signals" not in got and "method" not in got
    assert got["answer_en"] == "reachable" and got["attribution"] == "IODA" and got["age_minutes"] == 11
    assert set(got["licence"]["stripped"]["keys"]) == {"signals", "method", "signals_total"}
    house = licence.apply("connectivity_now", _ioda(), "house",
                          {"grade": "ask", "partner_tier": "cited_fact_only"})
    assert "signals" in house
