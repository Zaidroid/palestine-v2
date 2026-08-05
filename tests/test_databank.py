"""T2.3 — the databank migration loader honors its reviewed specs.

Unit tests run on synthetic records everywhere; the integration tests that
read v1's real files skip when /opt/stacks/palestine is absent (CI, laptops).
"""
from collections import Counter
from pathlib import Path

import pytest

from ingest import databank
from ingest.databank import Drop, Row, SpecRefused, load_spec, slug

V1 = Path("/opt/stacks/palestine/public/data/unified")

PLACES = {
    "region": {"Gaza Strip": 1, "West Bank": 2},
    "governorate": {"Jerusalem": 11, "Qalqilya": 7, "Hebron": 13},
    "pcode": {"PS0150": 13},
}


def spec_for(cat):
    return load_spec(cat)


def test_skipped_categories_are_refused():
    for cat in ("water", "westbank", "news"):
        with pytest.raises(SpecRefused, match="migrate=false"):
            load_spec(cat)


def test_unknown_category_is_refused():
    with pytest.raises(SpecRefused, match="no spec"):
        load_spec("definitely_not_a_category")


def test_reviewed_spec_without_transformer_is_refused_not_improvised(monkeypatch):
    # every migrating category has a transformer now; simulate the gap to
    # prove a reviewed spec without one refuses rather than improvising.
    monkeypatch.delitem(databank.TRANSFORMERS, "funding")
    with pytest.raises(SpecRefused, match="no transformer"):
        databank.run("funding", dry_run=True)


def test_slug_is_the_global_convention():
    assert slug("Rice (small grain, imported)") == "rice_small_grain_imported"
    assert slug("Deir Al-Balah") == "deir_al_balah"
    assert slug("annual_total") == "annual_total"


def _prisoner_rec(**over):
    rec = {
        "stable_id": "sid1", "prisoner_metric_type": "administrative",
        "date": "2026-06-01",
        "location": {"region": "Palestine", "name": "Palestine"},
        "metrics": {"count": 3629},
        "sources": [{"name": "HaMoked", "fetched_at": "2026-08-05T03:00:00Z"}],
    }
    rec.update(over)
    return rec


def test_prisoners_month_bucket_and_null_place():
    spec = spec_for("prisoners")
    [row] = databank.t_prisoners(_prisoner_rec(), spec, PLACES, Counter())
    assert row.indicator == "prisoners.administrative"
    assert row.precision == "month"          # 1st-of-month bucket, never day
    assert row.occurred_at == "2026-06-01"
    assert row.place_id is None and not row.located   # law 3 honest NULL
    assert row.value_num == 3629 and row.unit == "persons"
    assert row.attrs["reference"] == "period-end stock"


def _casualty_rec(**over):
    rec = {
        "stable_id": "sidc", "casualty_dimension": "annual_total",
        "casualty_breakdown_label": None, "date": "2024-12-31",
        "location": {"region": "Palestine"},
        "metrics": {"killed": 242, "unit": "fatalities"},
        "sources": [{"name": "UN OCHA oPt — Data on Casualties"}],
    }
    rec.update(over)
    return rec


def test_casualties_year_bucket_law2():
    spec = spec_for("casualties")
    [row] = databank.t_casualties(_casualty_rec(), spec, PLACES, Counter())
    assert row.indicator == "casualties.annual_total"
    assert row.occurred_at == "2024-01-01" and row.precision == "year"
    assert "partial_year" not in row.attrs


def test_casualties_partial_current_year_is_flagged():
    spec = spec_for("casualties")
    [row] = databank.t_casualties(_casualty_rec(date="2026-12-31"), spec,
                                  PLACES, {})
    assert row.attrs["partial_year"] is True


def test_casualties_undated_breakdown_anchors_at_series_start():
    spec = spec_for("casualties")
    rec = _casualty_rec(casualty_dimension="demographic",
                        casualty_breakdown_label="Boys", date=None)
    [row] = databank.t_casualties(rec, spec, PLACES, Counter())
    assert row.indicator == "casualties.demographic.boys"
    assert row.occurred_at == "2008-01-01" and row.precision == "unknown"
    assert row.attrs["coverage_start"] == "2008-01-01"


def test_casualties_governorate_resolves_and_misspelling_is_crosswalked():
    spec = spec_for("casualties")
    rec = _casualty_rec(casualty_dimension="governorate",
                        casualty_breakdown_label="Qalqiliya", date=None,
                        location={"region": "West Bank",
                                  "governorate": "Qalqiliya"})
    [row] = databank.t_casualties(rec, spec, PLACES, Counter())
    assert row.place_id == 7 and row.located     # OCHA spelling → Qalqilya


def test_casualties_israel_is_an_honest_null_not_a_failure():
    spec = spec_for("casualties")
    counts = Counter()
    rec = _casualty_rec(casualty_dimension="governorate",
                        casualty_breakdown_label="Israel", date=None,
                        location={"region": "Israel", "governorate": "Israel"})
    [row] = databank.t_casualties(rec, spec, PLACES, counts)
    assert row.place_id is None
    assert row.attrs["breakdown_place"] == "Israel"
    assert not counts                            # not a resolution failure


def _demo_rec(**over):
    rec = {
        "stable_id": "sidd", "demolition_dimension": "locality", "date": None,
        "location": {"region": "East Jerusalem", "admin2_pcode": None},
        "metrics": {"demolished": 416, "displaced": 1080, "affected": 0},
        "sources": [{"name": "UN OCHA oPt — Data on Demolitions"}],
    }
    rec.update(over)
    return rec


def test_demolitions_fan_out_and_stable_id_suffixes():
    spec = spec_for("demolitions")
    rows = databank.t_demolitions(_demo_rec(), spec, PLACES, Counter())
    assert [r.indicator for r in rows] == [
        "demolitions.locality.structures", "demolitions.locality.displaced"]
    assert {r.v1_stable_id for r in rows} == {"sidd:structures",
                                              "sidd:displaced"}
    # affected == 0 emits nothing — measured: affected is annual-rows-only
    assert all(r.occurred_at == "2009-01-01" and r.precision == "unknown"
               for r in rows)


def test_demolitions_pcode_beats_region_and_ej_keeps_its_name():
    spec = spec_for("demolitions")
    counts = Counter()
    rows = databank.t_demolitions(
        _demo_rec(location={"region": "East Jerusalem",
                            "admin2_pcode": "PS0150"}), spec, PLACES, counts)
    assert all(r.place_id == 13 and r.located for r in rows)   # pcode rung
    rows = databank.t_demolitions(_demo_rec(), spec, PLACES, counts)
    assert all(r.place_id == 11 for r in rows)   # EJ → Jerusalem governorate
    assert rows[0].attrs["region"] == "East Jerusalem"


def test_demolitions_annual_row_law2_and_coverage_area():
    spec = spec_for("demolitions")
    rows = databank.t_demolitions(
        _demo_rec(demolition_dimension="annual_total", date="2010-12-31",
                  location={"region": "West Bank", "admin2_pcode": None},
                  metrics={"demolished": 431, "displaced": 593,
                           "affected": 14229}), spec, PLACES, Counter())
    assert len(rows) == 3
    assert all(r.occurred_at == "2010-01-01" and r.precision == "year"
               for r in rows)
    assert rows[0].attrs["coverage_area"] == "West Bank + East Jerusalem"


needs_v1 = pytest.mark.skipif(not V1.exists(), reason="v1 databank not mounted")


@needs_v1
def test_pilot_dry_runs_reproduce_spec_arithmetic():
    r = databank.run("prisoners", dry_run=True)
    assert r["records_read"] == r["observations_emitted"] == 890
    r = databank.run("casualties", dry_run=True)
    assert r["records_read"] == r["observations_emitted"] == 49
    r = databank.run("demolitions", dry_run=True)
    assert r["records_read"] == 534
    # fan-out: 534 structures + 352 displaced + 18 affected — the spec's
    # measured non-zero fills, exactly
    assert r["observations_emitted"] == 904
    assert r["notes"].get("locality_resolution_miss") == 1    # Al Malha
