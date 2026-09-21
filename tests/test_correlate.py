"""The correlation layer, as golden questions.

A correlation coefficient looks like a fact and is usually an artifact, so
most of this file tests REFUSALS. Each one exists because serving a number
there would be worse than serving nothing: a coefficient with a caveat
stapled to it gets quoted without the caveat.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from serve import correlate as C
from serve.app import app

client = TestClient(app)


def corr(**params):
    r = client.get("/v2/databank/correlate", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ── the arithmetic ───────────────────────────────────────────────────────────

def test_pearson_matches_a_known_value():
    xs = [1, 2, 3, 4, 5]
    assert C.pearson(xs, [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    assert C.pearson(xs, [10, 8, 6, 4, 2]) == pytest.approx(-1.0)


def test_spearman_is_rank_based_and_survives_a_monotone_transform():
    """The reason Spearman is the default here: a price series and a count
    series relate monotonically far more often than linearly."""
    xs = [1, 2, 3, 4, 5, 6]
    ys = [1, 4, 9, 16, 25, 36]            # perfectly monotone, not linear
    assert C.spearman(xs, ys) == pytest.approx(1.0)
    assert C.pearson(xs, ys) < 1.0


def test_ties_get_average_ranks():
    """Tied values are common — a checkpoint status series is mostly one
    number — and naive ranking would bias every such comparison."""
    assert C.rank([5, 5, 1]) == [2.5, 2.5, 1.0]


def test_a_constant_series_correlates_with_nothing():
    assert C.pearson([3, 3, 3, 3], [1, 2, 3, 4]) is None


def test_the_interval_widens_as_n_falls():
    """A rho of 0.6 from 13 points is not the same claim as 0.6 from 1,300,
    and the interval is what says so."""
    lo_small, hi_small = C.fisher_ci(0.6, 13)
    lo_big, hi_big = C.fisher_ci(0.6, 1300)
    assert (hi_small - lo_small) > (hi_big - lo_big) * 5


# ── the refusals ─────────────────────────────────────────────────────────────

def test_two_cumulative_series_are_refused():
    """Any two rising totals correlate at ~1.0. That is a fact about time,
    not about Palestine."""
    d = corr(a="conflict.gaza_cumulative_killed",
             b="conflict.gaza_cumulative_injured")
    assert d["refused"]
    assert any("CUMULATIVE" in r for r in d["reasons"])
    assert "rho" not in d


def test_two_measures_of_one_concept_are_refused_by_default():
    d = corr(a="food.price.bread", b="food.price.sugar")
    assert d["refused"]
    assert any("both series are food.price" in r for r in d["reasons"])


def test_the_same_concept_can_be_allowed_deliberately():
    """The override exists because "are two staples' prices related?" is a
    real question. It must be asked on purpose."""
    d = corr(a="food.price.bread", b="food.price.sugar",
             allow_same_concept="true")
    assert not d["refused"]
    assert d["n"] >= C.MIN_N


def test_an_unknown_indicator_says_so_rather_than_blaming_the_registry():
    """Falling through to 'nobody classified this' would send the caller to
    fix a spec instead of a typo."""
    d = corr(a="food.price.bread", b="food.price.does_not_exist")
    assert d["refused"]
    assert "no series named" in d["reasons"][0]


def test_unknown_precision_points_never_enter_a_correlation():
    """Law 1 at the serving layer: an 'unknown' date is v1's fetch stamp, so
    those rows cannot support a time comparison at all."""
    d = corr(a="education.school_record", b="culture.heritage_site.religious")
    assert d["refused"]


def test_too_few_points_is_a_refusal_not_a_wide_interval():
    """A window with SOME points but fewer than MIN_N. Distinct from a window
    with none, which says so in its own words — three absences, three
    answers, because "no such series", "no points here" and "not enough
    points" send the caller three different places."""
    d = corr(a="food.price.bread", b="food.price.oil_olive",
             allow_same_concept="true", frm="2026-01-01")   # 6 points
    assert d["refused"]
    assert str(C.MIN_N) in " ".join(d["reasons"])


def test_a_window_with_no_points_says_so_rather_than_counting():
    """The window opens the day after the newer series' last point, so it is
    empty on whatever the databank holds. It used to be a fixed
    frm=2026-07-01 — empty when written on 2026-08-08, because WFP had
    published through June — and WFP's July prices filled it, so the answer
    became "only 1 usable point", correctly. A window past the end of a live
    series is a date, not a property; this one is read off the data."""
    held = client.get("/v2/databank/compare",
                      params={"indicators": "food.price.bread,food.price.sugar"})
    last = max(p["at"] for s in held.json()["series"] for p in s["points"])
    after = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    d = corr(a="food.price.bread", b="food.price.sugar",
             allow_same_concept="true", frm=after)
    assert d["refused"]
    reasons = " ".join(d["reasons"])
    assert "no points" in reasons
    assert "usable overlapping" not in reasons      # said, not counted


def test_mixed_place_grain_is_refused():
    a = {"indicator": "x", "measure_kind": "flow", "place_grain": "region",
         "concept_key": "c1", "polarity": None}
    b = {"indicator": "y", "measure_kind": "flow", "place_grain": "locality",
         "concept_key": "c2", "polarity": None}
    assert any("place grains differ" in r for r in C.check_comparable(a, b))


def test_a_status_series_is_refused():
    a = {"indicator": "x", "measure_kind": "status", "place_grain": "region",
         "concept_key": "c1", "polarity": None}
    b = {"indicator": "y", "measure_kind": "flow", "place_grain": "region",
         "concept_key": "c2", "polarity": None}
    assert any("categorical" in r for r in C.check_comparable(a, b))


# ── what a successful answer must carry ──────────────────────────────────────

def test_a_result_always_carries_caveats_and_attribution():
    d = corr(a="food.price.bread", b="food.price.oil_olive",
             allow_same_concept="true")
    assert not d["refused"]
    assert d["caveats"], "a coefficient without caveats is a claim"
    assert any("not causation" in c for c in d["caveats"])
    assert d["attribution"], "every served number names its source"
    assert d["ci95"] and d["plain_english"]


def test_a_lagged_result_says_that_a_scan_was_run():
    """A lag scan tries many shifts and reports the best, which finds a
    correlation in noise reliably. The caveat is not optional."""
    d = corr(a="food.price.bread", b="food.price.oil_olive",
             allow_same_concept="true", max_lag=3)
    if d["refused"] or d["lag_days"] == 0:
        pytest.skip("best fit was at lag 0 on today's data")
    assert any("lag" in c for c in d["caveats"])


# ── the surrounding endpoints ────────────────────────────────────────────────

def test_concepts_lists_declared_gaps_not_just_populated_ones():
    """energy.supply has no series. It is in the taxonomy because the absence
    is the finding — the scout found no open source and two letters exist."""
    d = client.get("/v2/databank/concepts").json()
    keys = {c["key"] for c in d["concepts"]}
    assert "energy.supply" in keys


def test_indicator_search_finds_a_series_without_its_string():
    d = client.get("/v2/databank/indicators",
                   params={"q_": "bread"}).json()
    assert any("bread" in i["indicator"] for i in d["indicators"])


def test_compare_never_rescales_to_a_shared_axis():
    d = client.get("/v2/databank/compare", params={
        "indicators": "food.price.bread,food.price.sugar"}).json()
    assert len(d["series"]) == 2
    assert d["overlap"]["n"] > 0
    for s in d["series"]:
        assert s["canonical_unit"], "each series keeps its own unit"


def test_the_pack_size_conversion_reaches_the_api():
    """The whole point of the unit registry: a per-500g price and a per-kg
    price must arrive comparable."""
    d = client.get("/v2/databank/compare", params={
        "indicators": "food.price.labaneh,food.price.tea"}).json()
    units = {s["canonical_unit"] for s in d["series"]}
    assert units == {"ILS_per_kg"}
