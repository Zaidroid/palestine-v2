"""IPC's analyses (ops/fetch_ipc.py, 2026-10-14). No network: the pure part on
rows cut down from HDX's files."""
from __future__ import annotations

from pathlib import Path

import yaml

from ops import fetch_ipc as ipc
from ops import gap_radar

ROOT = Path(__file__).resolve().parent.parent


def row(analysis, validity, start, end, area, phase, number, share):
    return {"Date of analysis": analysis, "Country": "PSE", "Total country population": "2148200",
            "Level 1": "", "Area": area, "Validity period": validity, "From": start, "To": end,
            "Phase": phase, "Number": number, "Percentage": share}


def test_single_governorates_are_placed_and_combined_areas_are_their_own():
    rows = [row("Jul 2025", "current", "2025-07-01", "2025-08-31", "Gaza", "5", "300000", "0.32"),
            row("Feb 2024", "current", "2024-02-01", "2024-03-31", "North gaza & gaza governorates", "5", "210000", "0.7"),
            row("Sep 2024", "current", "2024-09-01", "2024-10-31", "Northern Governorates", "5", "100", "0.0"),
            row("Dec 2023", "current", "2023-11-01", "2023-12-31", "Southern Governorate IDPs", "4", "500000", "0.39")]
    recs, notes = ipc.records(rows, [])
    by = {(r["measure"], r["date"]): r for r in recs}
    g = by[("population_phase5_gaza", "2025-07-01")]
    assert g["location"] == {"governorate": "Gaza", "region": "Gaza Strip"} and g["value"] == 300000
    assert by[("share_phase5_gaza", "2025-07-01")]["value"] == 32.0 and by[("share_phase5_gaza", "2025-07-01")]["unit"] == "percent"
    n = by[("population_phase5_north_and_gaza", "2024-02-01")]
    assert n["location"] == {"region": "Gaza Strip"}                 # two governorates: never one of them
    assert ("population_phase5_north_and_gaza", "2024-09-01") in by  # the other spelling, the same area
    assert ("population_phase4_south_displaced", "2023-11-01") in by
    assert notes["areas_not_known"] == []


def test_may_2024s_single_names_are_its_combined_areas():
    rows = [row("May 2024", "current", "2024-05-01", "2024-06-30", "North Gaza", "all", "300000", "1.0"),
            row("May 2024", "current", "2024-05-01", "2024-06-30", "Deir Al-Balah", "all", "1751457", "1.0"),
            row("May 2024", "current", "2024-05-01", "2024-06-30", "Rafah", "all", "200000", "1.0"),
            row("Apr 2025", "current", "2025-04-01", "2025-05-31", "North gaza", "all", "310000", "1.0")]
    recs, _ = ipc.records(rows, [])
    got = {(r["measure"], r["date"]) for r in recs}
    assert got == {("population_analysed_north_and_gaza", "2024-05-01"),
                   ("population_analysed_middle_and_khan_younis", "2024-05-01"),
                   ("population_analysed_rafah", "2024-05-01"),
                   ("population_analysed_north_gaza", "2025-04-01")}      # a year later, North Gaza alone


def test_projections_are_series_of_their_own_and_the_west_bank_rows_are_left_out():
    rows = [row("Jul 2025", "first projection", "2025-08-01", "2025-09-30", "Gaza", "3+", "900000", "0.98"),
            row("Dec 2023", "current", "2023-11-01", "2023-12-31", "West bank", "all", "0", "1.0")]
    national = [row("Jul 2025", "current", "2025-07-01", "2025-08-31", None, "5", "513720", "0.26")]
    for r in national:
        r.pop("Area")
    recs, notes = ipc.records(rows, national)
    got = {r["measure"] for r in recs}
    assert {"population_phase3plus_gaza_projected", "share_phase3plus_gaza_projected",
            "population_phase5_gaza_strip", "share_phase5_gaza_strip"} == got
    assert notes["west_bank_rows_left_out"] == 1


def test_an_area_no_one_has_named_is_refused_by_the_reader():
    recs, notes = ipc.records([row("Jan 2027", "current", "2027-01-01", "2027-02-28", "Middle Area", "5", "1", "0.1")], [])
    assert recs == [] and notes["areas_not_known"] == ["Middle Area"]


def test_the_night_reads_ipc_with_an_allowance_and_the_spec_names_every_series():
    assert "step .venv/bin/python -m ops.fetch_ipc" in (ROOT / "ops" / "databank-sync.sh").read_text()
    assert gap_radar.SUPPLY_LINES["ipc"]["feeds"] == ["ipc_phases"]
    assert gap_radar.ALLOWANCE_OVERRIDE_DAYS["ipc_phases"] == 365
    assert ipc.PAUSE >= 10                                   # HDX's Crawl-Delay
    spec = yaml.safe_load((ROOT / "db" / "mappings" / "ipc.yaml").read_text(encoding="utf-8"))
    rules = spec["registry"]["rules"]
    assert len(rules) >= 200 and all(r["name_ar"] and r["serve_warning_ar"] for r in rules)
    proj = [r for r in rules if r["when"]["equals"].endswith("_projected")]
    assert proj and all("PROJECTION" in r["serve_warning"] for r in proj)


def test_the_night_reads_the_chambers_new_reports_and_builds_its_three_series():
    sync = (ROOT / "ops" / "databank-sync.sh").read_text()
    steps = ["ops.fetch_gazacham --new-only", "ops.build_gazacham_series", "ops.build_gazacham_prices",
             "ops.build_gazacham_cash"]
    at = [sync.index(f"step .venv/bin/python -m {s}") for s in steps]
    assert at == sorted(at) and at[-1] < sync.index("ingest.databank --all")   # read, built, then loaded
    line = gap_radar.SUPPLY_LINES["gazacham"]
    assert line["labels"] == ["reports:gazacham"]
    assert set(line["feeds"]) == {"gazacham_trucks_weekly", "gazacham_prices", "gazacham_cash"}

