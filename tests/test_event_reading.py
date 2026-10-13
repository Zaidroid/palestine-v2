"""Events that follow their publisher (`event_reading`, 2026-10-13).

Until this rule an event was taken once: held under its id, it was skipped
whatever the publisher said about it later, and a withdrawn one stayed current.
UCDP's GED 26.1 revised 812 of the 7,638 held events in a field the store
keeps, withdrew 18 and added 493; none of it could be loaded. Pure: no
connection is opened."""
import json

import pytest

from ingest import databank as D
from ingest.spec import SpecRefused

RULE = {"dataset": "ds", "label": "UCDP",
        "content_attrs": ["name", "deaths_a"],
        "content_attrs_when": {"held_has": "ucdp_id", "attrs": ["ucdp_date_prec", "ucdp_date_end"]}}


def held(eid, status="believed", note=None, day="2023-10-20", lat=31.5, lon=34.46,
         killed=4, attrs=None, etype="conflict.state_based"):
    return D.HeldEvent(eid, status, note, etype, day, "day", lat, lon,
                       {"unit": "persons", "killed": killed},
                       {"name": "Gaza city", "deaths_a": 0, **(attrs or {})})


def emitted(sid, day="2023-10-20", lat=31.5, lon=34.46, killed=4, attrs=None,
            etype="conflict.state_based"):
    return D.EventRow("ds", etype, day, "day", sid, place_id=7, lat=lat, lon=lon,
                      metrics={"unit": "persons", "killed": killed},
                      attrs={"name": "Gaza city", "deaths_a": 0, **(attrs or {})})


def test_a_held_event_that_says_the_same_is_left_alone_and_a_new_id_is_new():
    d = D.decide_event_reading({"a": held(1)}, [emitted("a"), emitted("b")], RULE)
    assert d["same"] == 1 and [e.v1_stable_id for e in d["new"]] == ["b"]
    assert not d["revised"] and not d["withdrawn"]


def test_a_changed_count_day_point_or_named_field_is_a_revision_and_says_which():
    d = D.decide_event_reading(
        {"a": held(1), "b": held(2), "c": held(3), "d": held(4)},
        [emitted("a", killed=9), emitted("b", day="2023-10-21"),
         emitted("c", lat=31.52), emitted("d", attrs={"name": "al-Shati refugee camp"})], RULE)
    assert {h.event_id: ch for h, _, ch in d["revised"]} == {
        1: ["metrics"], 2: ["day"], 3: ["lat"], 4: ["name"]}


def test_the_place_row_is_ours_and_is_not_what_the_event_states():
    e = emitted("a")
    e.place_id = 999                       # the gazetteer moved; the publisher did not
    assert D.decide_event_reading({"a": held(1)}, [e], RULE)["same"] == 1


def test_a_field_the_held_row_never_had_is_not_the_publisher_changing_its_mind():
    """The 7,638 events loaded from v1's file carry no ucdp_id and none of
    UCDP's precision codes; the release gives every event both."""
    new = emitted("a", attrs={"ucdp_id": "1", "ucdp_date_prec": 1})
    assert D.decide_event_reading({"a": held(1)}, [new], RULE)["same"] == 1
    # a row written since does carry them, and then they count
    h = held(1, attrs={"ucdp_id": "1", "ucdp_date_prec": 1})
    later = emitted("a", attrs={"ucdp_id": "1", "ucdp_date_prec": 4, "ucdp_date_end": "2023-10-31"})
    (rev,) = D.decide_event_reading({"a": h}, [later], RULE)["revised"]
    assert rev[2] == ["ucdp_date_end", "ucdp_date_prec"]


def test_a_held_event_the_reading_no_longer_holds_is_withdrawn():
    d = D.decide_event_reading({"a": held(1), "gone": held(2)}, [emitted("a")], RULE)
    assert [h.event_id for h in d["withdrawn"]] == [2]


def test_a_duplicate_retired_by_hand_is_neither_revised_nor_withdrawn_nor_revived():
    retired = held(3, status="superseded", note="083: the same event twice")
    d = D.decide_event_reading({"old": retired, "x": held(4, status="superseded")},
                               [emitted("x", killed=50)], RULE)
    assert d["left_as_held"] == 1 and not d["revised"] and not d["withdrawn"] and not d["new"]


def test_an_event_this_rule_withdrew_comes_back_when_the_publisher_holds_it_again():
    mine = held(5, status="retracted", note="UCDP 2026-11-20: no longer in the publisher's current reading")
    other = held(6, status="retracted", note="retracted by hand: not a real event")
    d = D.decide_event_reading({"a": mine, "b": other}, [emitted("a"), emitted("b")], RULE)
    assert [h.event_id for h, _ in d["reinstated"]] == [5]
    assert d["left_as_held"] == 1, "a retraction this rule did not make is not undone by it"


def test_a_revised_event_keeps_what_the_store_added_and_loses_what_the_publisher_dropped():
    h = held(1, attrs={"enriched_by": "P1-B.1", "raw_lat": 31.5, "raw_lon": 34.46,
                       "ucdp_id": "1", "ucdp_date_end": "2023-10-31", "gazetteer_key": "gaza"})
    e = emitted("a", lat=31.6, lon=34.5, killed=9, attrs={"ucdp_id": "1", "ucdp_release": "26.1"})
    e.raw_ref = "bronze://x"
    a = D.revised_event_attrs(h, e, RULE)
    assert a["enriched_by"] == "P1-B.1" and a["gazetteer_key"] == "gaza"
    assert "ucdp_date_end" not in a, "the event no longer spans several days"
    assert (a["raw_lat"], a["raw_lon"]) == (31.6, 34.5)
    assert a["v1_stable_id"] == "a" and a["dataset_key"] == "ds" and a["raw_ref"] == "bronze://x"
    assert a["ucdp_release"] == "26.1"


def test_half_a_reading_is_refused_and_none_of_it_lets_the_frozen_copy_load(tmp_path):
    spec = {"input": {"root": str(tmp_path)},
            "event_reading": [{"dataset": "ds", "label": "UCDP", "files": ["a.json", "b.json"]}]}
    assert D.event_readings(spec, "conflict") == ({}, {})          # never fetched
    (tmp_path / "a.json").write_text("{}")
    with pytest.raises(SpecRefused, match="half a reading"):
        D.event_readings(spec, "conflict")
    (tmp_path / "b.json").write_text("{}")
    rules, files = D.event_readings(spec, "conflict")
    assert list(rules) == ["ds"] and files["ds"] == {tmp_path / "a.json", tmp_path / "b.json"}
    assert D.event_readings(spec, "conflict", from_fallback=True) == ({}, {}), \
        "a fallback input is an old answer and revises nothing"


def test_the_conflict_spec_declares_ucdps_three_files_and_reads_each_of_them():
    spec = D.load_spec("conflict")
    (rule,) = spec["event_reading"]
    assert set(rule["files"]) <= set(spec["input"]["glob"])
    assert "ucdp_release" not in rule["content_attrs"] + rule["content_attrs_when"]["attrs"]
    assert "ucdp_candidate_version" not in rule["content_attrs_when"]["attrs"]
    for a in rule["content_attrs"] + rule["content_attrs_when"]["attrs"]:
        assert a in spec["attrs_passthrough"] or a == "region", a


def test_the_warning_names_the_last_year_of_the_release_the_fetcher_loads():
    from ops.fetch_ucdp import LOADS_RELEASE
    spec = D.load_spec("conflict")
    (rule,) = [r for r in spec["registry"]["rules"]
               if "deaths" in json.dumps(r.get("when"))]
    last_year = str(2000 + int(LOADS_RELEASE.split(".")[0]) - 1)
    assert f"after {last_year}" in rule["serve_warning"]
    assert f"بعد {last_year}" in rule["serve_warning_ar"]
    assert "ucdp_candidate" in rule["serve_warning"] and "ucdp_candidate" in rule["serve_warning_ar"]


def test_an_event_dataset_fed_by_files_of_two_dates_keeps_a_vintage(tmp_path):
    """The yearly release and the monthly candidate file feed one dataset. Events
    have no indicator, so `vintage_by_indicator` came out empty and would have
    taken the dataset's vintage away."""
    spec = {"datasets": [{"key": "ucdp"}, {"key": "other"}]}
    a, b = tmp_path / "ged.json", tmp_path / "candidate.json"
    a.write_text(json.dumps({"metadata": {"vintage": "2026-03-30", "vintage_basis": "the codebook."}, "data": []}))
    b.write_text(json.dumps({"metadata": {"vintage": "2026-09-20", "vintage_basis": "Last-Modified"}, "data": []}))
    v = D.read_vintage(spec, [a, b], {a: {("ucdp", None)}, b: {("ucdp", None)}})
    assert v["ucdp"]["vintage"] == "2026-09-20"
    assert "vintage_by_indicator" not in v["ucdp"]
    assert v["ucdp"]["vintage_basis"].endswith("(the others: 2026-03-30)")


# ── the versions view (migration 111) ────────────────────────────────────────

def _view(path, name):
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / path).read_text(encoding="utf-8")
    i = src.index(f"CREATE OR REPLACE VIEW {name} AS")
    return src[i:src.index(";", i)]


def test_the_versions_view_is_the_current_view_over_history_too():
    """An `as_of` answer must read an event exactly as the present answer does.
    The two definitions are kept word for word, apart from where they read."""
    rows = _view("db/migrations/093_fragments_insecurity_insight.sql", "databank_event_rows")
    versions = _view("db/migrations/111_event_versions_for_as_of.sql", "databank_event_versions")
    want = (rows.replace("VIEW databank_event_rows AS", "VIEW databank_event_versions AS")
                .replace("  FROM event e\n",
                         "  FROM (SELECT * FROM event UNION ALL SELECT * FROM event_history) e\n")
                .replace("\n   AND upper_inf(e.sys_period)", ""))
    assert versions == want


def test_the_current_rows_read_through_the_versions_are_the_current_view():
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('databank_event_versions') IS NOT NULL")
        if not cur.fetchone()[0]:
            pytest.skip("migration 111 not applied")
        cur.execute("""SELECT (SELECT count(*) FROM databank_event_versions WHERE upper_inf(sys_period)),
                              (SELECT count(*) FROM databank_event_rows)""")
        a, b = cur.fetchone()
        assert a == b and b > 0
        # no event stands twice on any one day: its versions do not overlap
        cur.execute("""SELECT count(*) FROM databank_event_versions a
                         JOIN databank_event_versions b
                           ON a.observation_id = b.observation_id
                          AND a.sys_period && b.sys_period
                          AND lower(a.sys_period) < lower(b.sys_period)""")
        assert cur.fetchone()[0] == 0
