"""Insecurity Insight incidents are identified by the publisher's own event
number (2026-10-12). v1's id missed that number under three of its four column
spellings: measured on the publisher's files, 9,627 incidents were dropped as
repeats of another (6,189 of the Protection file's 7,400) and 4,965 distinct
health-care incidents were held as 7,903 events."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.databank import EventRow, load_spec                              # noqa: E402
from ops import fetch_insecurity_insight as F                                # noqa: E402
from ops.rekey_insecurity_insight import plan                                # noqa: E402

_g = importlib.util.spec_from_file_location(
    "_guard_0926", Path(__file__).with_name("test_databank_guard_0926.py"))
guard = importlib.util.module_from_spec(_g)
_g.loader.exec_module(guard)

DAY = 45000.0          # an Excel serial date, as the sheets carry it


def test_two_incidents_of_one_day_with_their_own_numbers_are_two_incidents():
    a = {"Date": DAY, "Sind Event ID": 137196.0, "Reported Perpetrator Name": "x"}
    b = {"Date": DAY, "Sind Event ID": 137197.0, "Reported Perpetrator Name": "x"}
    iso = F.to_iso(DAY)
    # v1's rule read "SiND Event ID" only, so these two were one
    assert F.legacy_incident_id("food_systems", a, iso) == F.legacy_incident_id("food_systems", b, iso)
    assert F.incident_id("food_systems", a) != F.incident_id("food_systems", b)


def test_every_spelling_of_the_id_column_is_the_same_number():
    ids = {F.incident_id("healthcare", {col: 5512.0}) for col in F.ID_COLUMNS}
    assert len(ids) == 1
    assert F.publisher_id({"Event ID": 5512.0}) == "5512"


def test_one_incident_is_held_once_per_theme_it_is_filed_under():
    row = {"SiND Event ID": 9.0}
    assert F.incident_id("healthcare", row) != F.incident_id("explosive_weapons", row)


def test_a_file_with_no_numbers_tells_its_rows_apart_by_everything_they_say():
    a = {"Date": DAY, "Admin 1": "Gaza Strip", "Number of civilians killed": 3.0}
    b = {"Date": DAY, "Admin 1": "Gaza Strip", "Number of civilians killed": 5.0}
    assert F.incident_id("protection", a) != F.incident_id("protection", b)
    assert F.incident_id("protection", a) == F.incident_id("protection", dict(a))


def test_a_month_the_publisher_gave_as_a_month_stays_a_month():
    assert F.date_of("2019-01") == ("2019-01-01", "month")
    assert F.date_of(DAY) == (F.to_iso(DAY), "day")
    rec = F.normalise({"Incident date": "2019-01"}, "healthcare", "u", "2019 PSE SHCC Health Care Data.xlsx")
    assert rec["date"] == "2019-01-01" and rec["date_precision"] == "month"
    # the id the held event carries was built from the mid-month date
    assert rec["incident_id_legacy"] == F.legacy_incident_id(
        "healthcare", {"Incident date": "2019-01"}, "2019-01-15")


def test_the_copy_with_coordinates_is_the_one_kept(monkeypatch):
    thematic = [["SiND Event ID", "Date", "Latitude", "Longitude"], [77.0, DAY, None, None]]
    yearly = [["SiND Event ID", "Date", "Latitude", "Longitude"], [77.0, DAY, 31.5, 34.4]]
    files = {"u1": thematic, "u2": yearly}
    monkeypatch.setattr(F, "get_json", lambda *a, **k: {"result": {"resources": [
        {"format": "XLSX", "name": "2016-2026 PSE Attacks on Health Care Incident Data.xlsx", "url": "u1"},
        {"format": "XLSX", "name": "2023 PSE SHCC Health Care Data.xlsx", "url": "u2"}]}})
    monkeypatch.setattr(F, "get", lambda url, **k: url)
    monkeypatch.setattr(F, "sheet_rows", lambda url: files[url])
    rows, stamp, id_map = F.from_hdx()
    assert len(rows) == 1 and rows[0]["latitude"] == 31.5
    assert rows[0]["source_dataset"].startswith("2023 PSE SHCC")
    assert [f["duplicates"] for f in stamp["files"]] == [0, 1]
    # v1's id had the coordinates in it, so it held this incident twice:
    # both old ids lead to the one new id
    assert len(id_map) == 2 and len({v[0] for v in id_map.values()}) == 1


def test_v1s_own_file_is_no_longer_a_fallback(capsys):
    """It carries v1's ids: a night fed from it would write every incident twice."""
    assert F.main(["--from-v1"]) == 2
    assert "--stage" in capsys.readouterr().err


# ── moving what is already held ──────────────────────────────────────────────

def _held(eid, legacy, day="2024-01-05", precision="day", status="believed", moved=False):
    return (eid, f"ii-{legacy}", day, precision, status, moved)


def test_a_held_event_moves_to_the_publishers_id_and_keeps_the_old_one():
    p = plan([_held(1, "aaa")], {"aaa": ["N1", 0, False]}, {"N1": {"date": "2024-01-05"}})
    assert p["actions"] == {1: {"new": "ii-N1", "old": "ii-aaa", "keeper": None}}


def test_two_held_copies_of_one_incident_keep_the_located_one_and_retire_the_other():
    held = [_held(1, "thematic"), _held(2, "yearly")]
    id_map = {"thematic": ["N1", 1, False], "yearly": ["N1", 9, True]}
    p = plan(held, id_map, {"N1": {"date": "2024-01-05"}})
    assert p["actions"][2] == {"new": "ii-N1", "old": "ii-yearly", "keeper": None}
    assert p["actions"][1] == {"new": None, "old": "ii-thematic", "keeper": 2}
    assert p["counts"]["superseded_as_the_same_incident"] == 1


def test_an_event_whose_row_the_publisher_changed_is_left_exactly_as_it_is():
    p = plan([_held(1, "gone")], {}, {})
    assert p["actions"] == {} and p["counts"]["unmatched_left_as_is"] == 1


def test_running_it_twice_moves_nothing_twice():
    p = plan([_held(1, "N1", moved=True)], {"aaa": ["N1", 0, False]}, {"N1": {"date": "2024-01-05"}})
    assert p["actions"] == {} and p["counts"]["already_moved"] == 1


def test_a_month_only_incident_is_redated_with_its_old_date_kept():
    p = plan([_held(1, "aaa", day="2019-01-15")], {"aaa": ["N1", 0, False]},
             {"N1": {"date": "2019-01-01", "date_precision": "month"}})
    assert p["actions"][1] == {"new": "ii-N1", "old": "ii-aaa", "keeper": None,
                               "date": "2019-01-01", "precision": "month", "before": "2019-01-15"}


# ── the loader: the id decides, and nothing else ─────────────────────────────

def _incident(sid):
    # the Protection file: no coordinates, no victims, one region: every
    # incident of a day has the same type|day|place|lat|lon|metrics
    return EventRow("d", "attack.protection", "2024-01-05", "day", sid, place_id=1,
                    lat=None, lon=None, metrics={}, attrs={})


def test_coordinate_less_incidents_of_one_day_are_all_written(monkeypatch, tmp_path):
    held = [(_incident("ii-old"), "ii-held"), (_incident("ii-old2"), "ii-retired-copy")]
    emitted = [_incident("ii-held"), _incident("ii-new1"), _incident("ii-new2")]
    report, log = guard._event_run(monkeypatch, tmp_path, emitted, held=held,
                                   spec_extra={"event_identity": {"match": "stable_id"}})
    assert log["events"] == ["ii-new1", "ii-new2"]
    assert report["notes"]["event_already_held"] == 1 and report["notes"]["event_new"] == 2


def test_without_the_declaration_the_retired_copy_would_swallow_a_new_incident(monkeypatch, tmp_path):
    held = [(_incident("ii-old"), "ii-held"), (_incident("ii-old2"), "ii-retired-copy")]
    emitted = [_incident("ii-held"), _incident("ii-new1"), _incident("ii-new2")]
    report, log = guard._event_run(monkeypatch, tmp_path, emitted, held=held)
    assert len(log["events"]) == 1


def test_the_spec_declares_it():
    spec = load_spec("insecurity_insight")
    assert spec["event_identity"] == {"match": "stable_id"}
    assert not str(spec["input"]["root"]).startswith("/")


def test_a_load_before_the_rekey_is_refused_and_writes_nothing(monkeypatch, tmp_path):
    """The new fetch without the re-key: no held id is in the input. Written,
    it would hold all 24,305 incidents beside the 20,174 already there."""
    import pytest
    from ingest.spec import SpecRefused
    held = [(_incident(f"x{i}"), f"ii-legacy{i}") for i in range(10)]
    emitted = [_incident(f"ii-new{i}") for i in range(12)]
    with pytest.raises(SpecRefused, match="Re-key them first"):
        guard._event_run(monkeypatch, tmp_path, emitted, held=held,
                         spec_extra={"event_identity": {"match": "stable_id"}})
