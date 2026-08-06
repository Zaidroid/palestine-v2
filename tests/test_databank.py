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


@needs_v1
def test_asof_harness_is_green():
    # P2.7 / Gate 2: sampled dates × categories against the archived
    # snapshots — counts exact, same-generation ids exact, served values
    # present at their as_of. Non-zero return = enumerated failures.
    from ops import asof_harness
    assert asof_harness.main() == 0


@needs_v1
def test_snapshot_tree_intact_zero_days_deleted():
    # Gate 2's no-data-loss bullet: v1's snapshot tree is read-only input;
    # the replay must never have consumed a day. 35 days existed when Tier 2
    # started (2026-06-25 onward); the count only grows.
    days = sorted(p.name for p in
                  (V1 / "snapshots").iterdir() if p.is_dir())
    assert len(days) >= 35
    assert days[0] == "2026-06-25"


@needs_v1
def test_nakba_places_never_capture_live_resolution():
    """The Nakba gazetteer's contract: 1,900+ historic localities exist as
    servable=false rows for historical joins, and the live name resolver
    can never return one."""
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM place
                       WHERE NOT servable AND merged_into IS NULL
                         AND attrs->>'historic' = 'mandate-palestine'""")
        assert cur.fetchone()[0] >= 1900
        # historical resolution reached 100% through them
        cur.execute("""SELECT count(*) - count(place_id) FROM observation o
                       JOIN dataset d ON d.dataset_id = o.dataset_id
                       WHERE d.v1_category = 'historical'""")
        assert cur.fetchone()[0] == 0
        # and the live resolver's name path structurally excludes them
        from resolve import geo
        assert "AND servable" in geo.NAME_SQL


# ── conflict_westbank: the raw WB cumulative series (Phase 4 brick 1) ────────

def _wb_rec(day, fs="un", **over):
    rec = {
        "report_date": day, "flash_source": fs,
        "killed_cum": 100, "injured_cum": 900,
        "killed_children_cum": 20, "injured_children_cum": 150,
        "settler_attacks_cum": 400,
        "displaced_households_cum": 50, "displaced_persons_cum": 300,
        "displaced_children_cum": 120,
    }
    rec.update(over)
    return rec


def test_westbank_fill_padding_dropped_moved_and_un_kept():
    """Law 1 on T4P's padding: a fill day repeating yesterday's numbers is
    not an observation; an 'un' day is one even when values hold; a fill
    day whose value moved carries information and stays."""
    spec = spec_for("conflict_westbank")
    recs = [
        _wb_rec("2026-01-01", "un"),
        _wb_rec("2026-01-02", "fill"),                    # unchanged → padding
        _wb_rec("2026-01-03", "fill", killed_cum=101),    # moved → kept
        _wb_rec("2026-01-04", "un", killed_cum=101),      # un, unchanged → kept
    ]
    databank.t_conflict_westbank.prepass(recs, spec, Counter())
    out = [databank.t_conflict_westbank(r, spec, PLACES, Counter())
           for r in recs]
    assert isinstance(out[1], Drop) and out[1].reason == "fill_padding"
    assert all(isinstance(o, list) for o in (out[0], out[2], out[3]))


def test_westbank_fan_is_region_grade_day_precision_suffixed_ids():
    spec = spec_for("conflict_westbank")
    rec = _wb_rec("2026-01-01")
    databank.t_conflict_westbank.prepass([rec], spec, Counter())
    rows = databank.t_conflict_westbank(rec, spec, PLACES, Counter())
    assert len(rows) == 8
    assert len({r.v1_stable_id for r in rows}) == 8   # 044-unique per field
    assert all(r.place_id == 2 and r.precision == "day" for r in rows)
    assert all(r.attrs["cumulative"] and r.attrs["flash_source"] == "un"
               for r in rows)
    by_ind = {r.indicator: r for r in rows}
    assert by_ind["conflict.westbank_cumulative_killed"].value_num == 100
    assert by_ind["conflict.westbank_cumulative_settler_attacks"].unit == \
        "attacks"


def test_westbank_missing_displaced_fields_shrink_the_fan():
    # the first three days of the real series predate displacement tracking
    spec = spec_for("conflict_westbank")
    rec = _wb_rec("2023-10-07", displaced_households_cum=None,
                  displaced_persons_cum=None, displaced_children_cum=None)
    databank.t_conflict_westbank.prepass([rec], spec, Counter())
    rows = databank.t_conflict_westbank(rec, spec, PLACES, Counter())
    assert len(rows) == 5


# ── water_gho: the water recovery's one genuinely-missing code ───────────────

def _gho_rec(**over):
    rec = {"IndicatorCode": "WSH_SANITATION_OD", "SpatialDim": "PSE",
           "TimeDim": 2020, "Dim1": "RESIDENCEAREATYPE_RUR",
           "Dim1Type": "RESIDENCEAREATYPE",
           "NumericValue": None, "Value": "1"}
    rec.update(over)
    return rec


def test_water_gho_parses_display_value_and_discloses_basis():
    """Measured: GHO ships this series with NumericValue null and the value
    in the display string — parsed, and the basis disclosed per row."""
    spec = spec_for("water_gho")
    [row] = databank.t_water_gho(_gho_rec(), spec, PLACES, Counter())
    assert row.indicator == "water.wsh_sanitation_od.residenceareatype_rur"
    assert row.value_num == 1.0 and row.unit == "percentage"
    assert row.attrs["value_basis"] == "gho_display_value"
    assert row.precision == "year" and row.occurred_at == "2020-01-01"
    assert row.place_id is None                      # law 3 honest NULL
    assert row.v1_stable_id == "gho-WSH_SANITATION_OD-2020-RESIDENCEAREATYPE_RUR"


def test_water_gho_prefers_numeric_and_drops_unparseable():
    spec = spec_for("water_gho")
    [row] = databank.t_water_gho(_gho_rec(NumericValue=0.73), spec, PLACES,
                                 Counter())
    assert row.value_num == 0.73 and row.attrs["value_basis"] == "numeric"
    out = databank.t_water_gho(_gho_rec(Value="No data"), spec, PLACES,
                               Counter())
    assert isinstance(out, Drop) and out.reason == "no_value"
