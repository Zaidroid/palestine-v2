"""The three supply lines that read HDX for themselves: WFP's food prices, the
West Bank school register, and the infrastructure category's four inputs.

Everything here is offline. The parsers run on real pieces of the publishers'
own files saved under tests/fixtures/supply_hdx/ (cut on 2026-10-12: a few
lines of WFP's CSV, a handful of shapes from each of OCHA's three shapefiles,
eight of UNOSAT's dataset records, and the four HDX dataset records). Beside
them sits `frozen_twins.json`: the records v1 made from those same lines and
shapes, which are what the databank's held rows were loaded from. The proof
each test repeats is the one the loader's dry run gives on the whole file: a
record written by the new fetcher and its v1 twin go through the SAME
transformer and come out with the same identity and the same content.

No network, no database.
"""
from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from ingest import databank
from ingest.databank import load_spec
from ops import fetch_hdx_infrastructure as fi
from ops import fetch_hdx_schools as fs
from ops import fetch_wfp_food as ff
from ops import fetchlib as fl
from ops import hdx
from ops import shp

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "supply_hdx"
TWINS = json.loads((FX / "frozen_twins.json").read_text())
FETCHED_AT = "2026-10-12T19:00:00+00:00"


class Pip:
    """Stands in for the point-in-governorate lookup. It records what it was
    asked, so a test can prove a rung was never tried."""

    def __init__(self, answer=None):
        self.answer, self.asked = answer, []

    def resolve(self, lat, lon):
        self.asked.append((lat, lon))
        return self.answer(lat, lon) if callable(self.answer) else self.answer


def places(pip=None) -> dict:
    return {"region": {"Gaza Strip": 1, "West Bank": 2},
            "governorate": {"Gaza": 15, "North Gaza": 14, "Qalqilya": 7, "Ramallah": 9,
                            "Khan Younis": 17, "Bethlehem": 12, "Jenin": 3},
            "pcode": {}, "_pip": pip or Pip()}


def held_form(category: str, rec: dict, pl: dict):
    """A record through its category's transformer → (identity key, content,
    row): the two strings the loader compares against a held row."""
    spec = load_spec(category)
    out = databank.TRANSFORMERS[category](rec, spec, pl, Counter())
    assert isinstance(out, list) and len(out) == 1, out
    r = out[0]
    ident = next(((d.get("overrides") or {}).get("identity") for d in spec["datasets"]
                  if d["key"] == r.dataset_key), None) or spec["identity"]
    key = databank.identity_key_for(ident, r.dataset_key, indicator=r.indicator,
                                    occurred_at=r.occurred_at, place_id=r.place_id,
                                    value_num=r.value_num, attrs=r.attrs)
    content = databank.content_of(value_num=r.value_num, value_text=r.value_text,
                                  unit=r.unit, place_id=r.place_id, attrs=r.attrs)
    return key, content, r


def package(name: str) -> dict:
    return json.loads((FX / name).read_text())["result"]


# ── the shapefile reader ─────────────────────────────────────────────────────

def test_text_is_read_in_the_encoding_the_publisher_declares():
    """v1 decoded these cells as Windows-1252. The .cpg says UTF-8."""
    parsed = shp.read_zip((FX / "schools_sample.zip").read_bytes())
    assert parsed["encoding"] == "utf-8" and parsed["cpg"] == "UTF-8"
    by_id = {f["properties"]["schid"]: f["properties"] for f in parsed["features"]}
    assert by_id[10111096]["Arabic_sch"] == "يوسف العظمة الاساسية للبنين"
    assert by_id[10111007]["English_Sc"] == "jenin sec. girls"
    # a cell that starts with no-break spaces is trimmed like any other
    assert by_id[23112030]["Arabic_sch"] == "بنات ذات النطاقين الاساسية"
    # a school with no English name has none, not an empty string
    assert by_id[20321726]["English_Sc"] is None
    assert isinstance(by_id[10111007]["schid"], int)          # 10111007, never 10111007.0
    assert parsed["table"]["last_update"] == "2021-06-10"
    assert parsed["table"]["rows_declared"] == 6


def test_shapes_come_out_as_v1s_reader_built_them():
    villages = shp.read_zip((FX / "village_boundaries_sample.zip").read_bytes())
    assert [f["geometry"]["type"] for f in villages["features"]] == \
        ["MultiPolygon", "MultiPolygon", "Polygon"]
    assert [f["properties"]["VNAME"] for f in villages["features"]] == \
        ["UM EL FAHM", "KH. UMM BURJ", "NITAF"]
    barrier = shp.read_zip((FX / "barrier_sample.zip").read_bytes())
    assert [f["geometry"]["type"] for f in barrier["features"]] == \
        ["LineString", "MultiLineString", "LineString", "LineString"]
    assert "UTM_Zone_36N" in barrier["prj"]                  # metres, not degrees
    schools = shp.read_zip((FX / "schools_sample.zip").read_bytes())
    assert {f["geometry"]["type"] for f in schools["features"]} == {"Point"}


def test_a_clockwise_ring_is_a_polygon_and_the_rest_are_its_holes():
    outer = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]              # clockwise
    hole = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]                   # counter-clockwise
    assert shp._ring_clockwise(outer) and not shp._ring_clockwise(hole)
    assert shp._ring_contains_some(outer, hole)
    assert not shp._ring_contains_some(hole, [[20, 20]])
    assert shp.first_ring({"type": "Polygon", "coordinates": [outer, hole]}) == outer
    assert shp.first_ring({"type": "MultiPolygon", "coordinates": [[outer], [hole]]}) == outer
    assert shp.first_ring({"type": "LineString", "coordinates": outer}) is None
    assert shp.first_ring(None) is None


def test_a_file_that_is_not_a_shapefile_is_refused_not_half_read():
    with pytest.raises(shp.ShapefileError):
        shp.read_zip(b"not a zip")
    with pytest.raises(shp.ShapefileError):
        shp.read_shp(b"\x00" * 120)
    # a zip cut short inside a record is refused whole, never read as a shorter register
    import io
    import zipfile
    whole = zipfile.ZipFile(FX / "barrier_sample.zip")
    cut = io.BytesIO()
    with zipfile.ZipFile(cut, "w") as z:
        for name in whole.namelist():
            data = whole.read(name)
            z.writestr(name, data[:len(data) - 40] if name.endswith(".shp") else data)
    with pytest.raises(shp.ShapefileError):
        shp.read_zip(cut.getvalue())
    assert shp._number("  12 ") == 12 and shp._number("1.5") == 1.5
    assert shp._number("") is None and shp._number("****") is None


# ── HDX: the vintage and the licence, as the publisher states them ───────────

def test_the_dataset_date_and_the_numbers_are_read_the_way_they_are_written():
    assert hdx.date_range("[2015-06-01T00:00:00 TO 2015-06-01T23:59:59]") == \
        ("2015-06-01", "2015-06-01")
    assert hdx.date_range("[2007-01-15T00:00:00 TO 2026-09-15T23:59:59]") == \
        ("2007-01-15", "2026-09-15")
    assert hdx.date_range("[2020-01-01T00:00:00 TO *]") == ("2020-01-01", None)
    assert hdx.date_range(None) == (None, None)
    assert hdx.day("2021-06-10T09:47:11.782170") == "2021-06-10" and hdx.day("") is None
    # JavaScript wrote 2, not 2.0; the databank compares attrs as text
    assert hdx.jsnum("2") == 2 and isinstance(hdx.jsnum("2"), int)
    assert hdx.jsnum("0.47") == 0.47 and hdx.jsnum("35.2") == 35.2
    assert hdx.jsnum("") is None and hdx.jsnum(None) is None and hdx.jsnum("n/a") is None
    assert json.dumps(hdx.jsnum("31.0")) == "31"


def test_a_registers_vintage_is_the_date_the_publisher_says_it_is_as_of():
    pkg = package("package_schools.json")
    s = hdx.stamp(pkg, hdx.resource(pkg, fmt="SHP"), kind="register", checked_at=FETCHED_AT)
    assert s["vintage"] == "2015-06-01"
    assert "last replaced on HDX on 2021-06-10" in s["vintage_basis"]
    assert s["vintage_url"] == "https://data.humdata.org/dataset/state-of-palestine-west-bank-schools"
    assert s["vintage_checked_at"] == FETCHED_AT
    assert s["publisher"] == "OCHA occupied Palestinian territory (oPt)"
    assert s["dataset_source"] == "Palestinian Authority - Ministry of Education and UNICEF"
    assert s["license_title"] == "Creative Commons Attribution International (CC BY)"
    assert s["license_id"] == "cc-by"

    pkg = package("package_barrier.json")
    s = hdx.stamp(pkg, hdx.resource(pkg, fmt="SHP"), kind="register")
    assert s["vintage"] == "2018-01-01" and s["license_id"] == "cc-by"
    assert "2019-07-16" in s["vintage_basis"]


def test_a_dataset_date_that_is_only_the_upload_day_says_so():
    """The village boundaries carry 2019-07-24, the day OCHA put them on HDX;
    the dataset's own text calls them Mandate-era. The basis must not let an
    upload day read as a survey date."""
    pkg = package("package_village_boundaries.json")
    s = hdx.stamp(pkg, hdx.resource(pkg, fmt="SHP"), kind="register", says=fi.VILLAGE_SAYS)
    assert s["vintage"] == "2019-07-24" == hdx.day(pkg["metadata_created"])
    assert "the day the dataset was put on HDX" in s["vintage_basis"]
    assert s["vintage_basis"].endswith("drawn under the British Mandate")
    assert "British Mandate" in pkg["notes"]
    assert s["dataset_source"] == "Palestinian Authority, Ministry of Planning"


def test_a_series_vintage_is_the_day_the_publisher_last_replaced_the_file():
    pkg = package("package_wfp.json")
    res = hdx.resource(pkg, name=ff.RESOURCE)
    assert res["name"] == "State of Palestine - Food Prices" and res["format"] == "CSV"
    s = hdx.stamp(pkg, res, kind="series")
    assert s["vintage"] == hdx.day(res["last_modified"])
    assert (s["data_from"], s["data_through"]) == hdx.date_range(pkg["dataset_date"])
    assert s["data_from"] == "2007-01-15"
    assert s["license_title"] == ("Creative Commons Attribution for Intergovernmental "
                                  "Organisations (CC BY-IGO)")
    assert s["publisher"] == "WFP - World Food Programme"
    with pytest.raises(ValueError):
        hdx.stamp(pkg, res, kind="snapshot")


def test_the_proposed_sql_carries_the_same_vintage_the_fetchers_write():
    """Migration 109 (the proposal, numbered on 2026-10-12): what it says is
    what the stamp says, and it does not open or close a transaction of its
    own (db/migrate.sh wraps each file in one)."""
    sql_path = ROOT / "db" / "migrations" / "109_vintage_of_two_hdx_registers.sql"
    sql = sql_path.read_text()
    assert not [ln for ln in sql.splitlines() if ln.strip() in ("BEGIN;", "COMMIT;")]
    for fixture, says in (("package_schools.json", None), ("package_barrier.json", None),
                          ("package_village_boundaries.json", fi.VILLAGE_SAYS)):
        pkg = package(fixture)
        s = hdx.stamp(pkg, hdx.resource(pkg, fmt="SHP"), kind="register", says=says)
        assert f"'vintage', '{s['vintage']}'" in sql, fixture
        assert f"'vintage_basis', '{s['vintage_basis']}'" in sql, fixture
        assert f"'vintage_url', '{s['vintage_url']}'" in sql, fixture
    # one dataset, two registers, two dates: no single date is asserted for it
    second = sql[sql.index("WHERE key = 'v1_education_hdx'"):]
    assert "'vintage_by_indicator'" in second
    top_level = second[:second.index("'vintage_by_indicator'")]
    assert "'vintage'," not in top_level
    statements = [ln for ln in sql.splitlines() if ln and not ln.lstrip().startswith("--")]
    assert sum(1 for ln in statements if ln.startswith("UPDATE dataset")) == 2
    assert not any(ln.upper().startswith(("DELETE", "INSERT", "DROP", "ALTER")) for ln in statements)


# ── food: WFP's CSV ──────────────────────────────────────────────────────────

def food_rows():
    return ff.parse_prices((FX / "wfp_food_prices_sample.csv").read_bytes())


def test_the_csv_keeps_what_v1_kept():
    """A tag row and a line with no price fall out; nothing else does."""
    raw = (FX / "wfp_food_prices_sample.csv").read_text().splitlines()
    assert raw[1].startswith("#date") and raw[-1].endswith(",ILS,,")
    rows = food_rows()
    assert len(rows) == len(raw) - 3 == 11
    assert rows[0]["price"] == 2 and isinstance(rows[0]["price"], int)
    assert rows[3]["price"] == 6.5


def test_a_food_record_is_the_row_the_databank_holds():
    """Each record and its v1 twin: same identity, same content."""
    recs = [ff.record(r) for r in food_rows()]
    assert len(recs) == len(TWINS["food"]) == 11
    for mine, twin in zip(recs, TWINS["food"]):
        k1, c1, row = held_form("food", mine, places())
        k2, c2, _ = held_form("food", twin, places())
        assert k1 == k2, (mine["stable_id"], k1, k2)
        assert c1 == c2, (mine["stable_id"], c1, c2)
        assert row.precision == "month" and row.occurred_at.endswith("-01")
    # the two region-wide markets land on their region, not on WFP's admin2
    _, _, wb = held_form("food", recs[-1], places())
    _, _, gs = held_form("food", recs[8], places())
    assert (wb.place_id, gs.place_id) == (2, 1) and wb.attrs["basket"] == "region-wide"
    # milk: one commodity, one market, two units eight years apart
    _, _, litre = held_form("food", recs[3], places())
    _, _, kilo = held_form("food", recs[4], places())
    assert litre.indicator == kilo.indicator == "food.price.milk_pasteurized"
    assert (litre.unit, kilo.unit) == ("ILS/L", "ILS/KG")


def test_the_food_stable_id_is_the_publishers_own_key():
    recs = [ff.record(r) for r in food_rows()]
    ids = [r["stable_id"] for r in recs]
    assert ids[0] == "wfp:2007-01-15:m2007:c55:retail"
    assert ids[-1] == "wfp:2026-09-15:m8216:c1354:retail"
    assert len(set(ids)) == len(ids)
    assert all(r["sources"][0]["name"] == "WFP Food Prices" for r in recs)   # the routed name
    # the publisher's own keys ride along and do not reach a row's attrs
    _, _, row = held_form("food", recs[0], places())
    assert recs[0]["market_id"] == "2007" and "market_id" not in row.attrs


def test_the_food_summary_names_every_commodity_for_the_registry():
    s = ff.summarise([ff.record(r) for r in food_rows()])
    assert (s["rows"], s["first_month"], s["last_month"]) == (11, "2007-01", "2026-09")
    names = {i["indicator"]: i for i in s["indicators"]}
    assert names["food.price.milk_pasteurized"]["indicator_name"] == "Milk (pasteurized)"
    assert names["food.price.milk_pasteurized"]["units"] == ["ILS/L", "ILS/KG"]
    assert names["food.price.rice_short_grain_low_quality_local"]["indicator_name"] == \
        "Rice (short grain, low quality, local)"
    assert s["markets"]["West Bank"] == {"rows": 2, "first_month": "2026-09",
                                         "last_month": "2026-09"}
    assert ff.FLOOR < 25814          # under the smallest file in 64 archived nights


def test_an_unchanged_file_is_not_written_again_every_night():
    """The loader archives its input by content; a raw file that differed only
    in its fetch time would be stored anew each night."""
    ref = "bronze://wfp_food_prices/b1ee0b"
    assert ff.already_written({"bronze": ref, "record_shape": ff.RECORD_SHAPE}, ref)
    assert not ff.already_written({"bronze": ref, "record_shape": ff.RECORD_SHAPE},
                                  "bronze://wfp_food_prices/another")
    assert not ff.already_written({"bronze": ref, "record_shape": ff.RECORD_SHAPE - 1}, ref)
    assert not ff.already_written({"bronze": ref}, ref)          # a file from older code
    assert not ff.already_written(None, ref)                     # never fetched


# ── education: the school register ───────────────────────────────────────────

def school_records():
    parsed = shp.read_zip((FX / "schools_sample.zip").read_bytes())
    return fs.records(parsed, FETCHED_AT)


def west_bank_pip():
    # every sample school but two sits in a governorate; those two are the ones
    # the gazetteer's polygons do not cover (measured: Jerusalem's Old City, Battir)
    return Pip(lambda lat, lon: None if round(lat, 3) in (31.778, 31.732) else 3)


def test_a_school_is_matched_on_the_publishers_school_number():
    recs = school_records()
    assert [r["school_id"] for r in recs] == [t["school_id"] for t in TWINS["schools"]]
    for mine, twin in zip(recs, TWINS["schools"]):
        k1, _, row = held_form("education", mine, places(west_bank_pip()))
        k2, _, _ = held_form("education", twin, places(west_bank_pip()))
        assert k1 == k2 == f"v1_education_hdx|{mine['school_id']}"
        assert mine["stable_id"] == f"hdx-school:{mine['school_id']}"
        # one placeholder day for the whole register, the one the held rows
        # carry: a corrected row must not split the register across two dates
        assert row.precision == "unknown" and row.occurred_at == fs.HELD_DAY == "2026-08-05"
        assert row.reported_at == FETCHED_AT


def test_a_school_v1_read_correctly_is_the_same_row():
    recs = {r["school_id"]: r for r in school_records()}
    twins = {t["school_id"]: t for t in TWINS["schools"]}
    for sid in (10111007, 22112108):
        _, mine, row = held_form("education", recs[sid], places(west_bank_pip()))
        _, held, _ = held_form("education", twins[sid], places(west_bank_pip()))
        assert mine == held, sid
    # the two schools no governorate polygon covers land on the West Bank, as held
    _, _, battir = held_form("education", recs[22112108], places(west_bank_pip()))
    assert battir.place_id == 2 and not battir.located


def test_a_name_v1_could_not_repair_is_corrected_not_reproduced():
    """The letter ف is 0xD9 0x81 in UTF-8, and 0x81 is not a Windows-1252
    character: v1's reading of these names never round-trips, so the databank
    holds them as mojibake. The publisher's text is what is written now."""
    recs = {r["school_id"]: r for r in school_records()}
    twins = {t["school_id"]: t for t in TWINS["schools"]}
    arabic = re.compile(r"[؀-ۿ]")
    for sid, name in ((10111096, "يوسف العظمة الاساسية للبنين"),
                      (10111180, "حيفا الاساسية للبنات")):
        key, mine, row = held_form("education", recs[sid], places(west_bank_pip()))
        key_held, held, held_row = held_form("education", twins[sid], places(west_bank_pip()))
        assert key == key_held                       # the same school
        assert row.attrs["school_name_ar"] == name
        assert not arabic.search(held_row.attrs["school_name_ar"])     # still mojibake
        assert mine != held                          # so the loader supersedes it
        assert {k for k in row.attrs if row.attrs[k] != held_row.attrs.get(k)} == \
            {"school_name_ar"}
    # a school with no English name is called by its Arabic one, in both fields
    _, _, row = held_form("education", recs[20321726], places(west_bank_pip()))
    assert row.attrs["school_name"] == row.attrs["school_name_ar"] == \
        "الفرير الثانوية-الباب الجديد"
    # leading no-break spaces, which v1 kept by accident, are trimmed
    _, _, row = held_form("education", recs[23112030], places(west_bank_pip()))
    _, _, held_row = held_form("education", twins[23112030], places(west_bank_pip()))
    assert held_row.attrs["school_name_ar"].startswith(" ")
    assert row.attrs["school_name_ar"] == held_row.attrs["school_name_ar"].strip()


def test_a_school_row_carries_the_publishers_columns_and_none_of_v1s_constants():
    """The record holds more than the row takes. "Active" and "Unknown" were
    v1's constants on every row (the file has no status or type column) and
    are no longer loaded (2026-10-12): a 2015 register cannot say a school is
    active today."""
    rec = school_records()[0]
    _, _, row = held_form("education", rec, places(west_bank_pip()))
    assert set(row.attrs) == {"school_id", "school_name", "school_name_ar"}
    assert (row.value_num, row.value_text, row.unit) == (1, None, "schools")
    assert rec["location"]["locality"] == "جنين" and rec["locality_code"] == "10180"
    assert "locality" not in rec and "admin2" not in rec and "vintage" not in rec


def test_a_register_whose_school_numbers_do_not_hold_is_refused():
    recs = school_records()
    fs.check(recs)
    with pytest.raises(fl.FetchRefused):
        fs.check(recs + [dict(recs[0])])
    with pytest.raises(fl.FetchRefused):
        fs.check(recs + [dict(recs[0], school_id=None)])
    assert fs.FLOOR == 2123 and fs.SOURCE["name"] == "HDX"


# ── infrastructure: two registers, UNOSAT, and the frozen T4P series ─────────

def test_a_village_boundary_is_matched_on_the_point_v1_computed():
    parsed = shp.read_zip((FX / "village_boundaries_sample.zip").read_bytes())
    recs = [fi.village_record(f, i, FETCHED_AT, "page")
            for i, f in enumerate(parsed["features"])]
    pip = Pip(3)
    for mine, twin in zip(recs, TWINS["village_boundaries"]):
        k1, c1, row = held_form("infrastructure", mine, places(pip))
        k2, c2, _ = held_form("infrastructure", twin, places(pip))
        # the same row (identity), saying what the publisher says: its name and
        # that it is one locality, where v1 wrote "Unknown Locality" and "persons"
        assert k1 == k2, (k1, k2)
        assert row.attrs["locality_name"] == mine["village_name"] and row.unit == "localities"
        assert "locality_type" not in row.attrs
        assert row.precision == "unknown" and row.occurred_at == fi.HELD_DAY == "2026-08-07"
        assert row.attrs["geo_key"] == f"{twin['location']['lat']:.6f},{twin['location']['lon']:.6f}"
        assert mine["stable_id"] == f"hdx-village:{row.attrs['geo_key']}"
    assert held_form("infrastructure", recs[0], places(pip))[0] == \
        "v1_infrastructure_hdx|infrastructure.locality_record|32.516870,35.178413"
    # the publisher names the village, and since 2026-10-12 the row does too
    assert recs[0]["village_name"] == recs[0]["location"]["name"] == "UM EL FAHM"
    assert recs[0]["locality_name"] == "Unknown Locality"          # v1's shape, still in the record
    assert held_form("infrastructure", recs[0], places(pip))[2].attrs["locality_name"] == "UM EL FAHM"


def test_a_barrier_segment_is_matched_on_its_middle_vertex_in_metres():
    parsed = shp.read_zip((FX / "barrier_sample.zip").read_bytes())
    recs = [fi.barrier_record(f, i, FETCHED_AT, "page")
            for i, f in enumerate(parsed["features"])]
    pip = Pip(3)
    for mine, twin in zip(recs, TWINS["barrier"]):
        k1, c1, row = held_form("infrastructure", mine, places(pip))
        k2, c2, _ = held_form("infrastructure", twin, places(pip))
        # the same row (identity), with the file's own length where v1 wrote "1 km"
        assert k1 == k2, (k1, k2)
        assert row.value_num == round(mine["shape_length_m"] / 1000, 3) and row.unit == "km"
        assert row.place_id == 2 and not row.located        # region: never a point
    assert pip.asked == []           # metres were never offered as degrees
    assert held_form("infrastructure", recs[0], places())[0] == \
        "v1_infrastructure_hdx|infrastructure.barrier_segment|3562238.081500,684672.975400"
    # a segment drawn as several lines has no middle vertex, as in v1
    assert recs[1]["location"]["lat"] is None
    assert "geo_key" not in held_form("infrastructure", recs[1], places())[2].attrs
    # v1's "Wall" for a segment the file leaves untyped is kept; the file's own
    # value and the segment's real length ride beside it
    assert recs[2]["barrier_type"] == "Wall" and recs[2]["barrier_type_published"] is None
    assert recs[0]["shape_length_m"] == 1911.588555 and recs[0]["metrics"] == {"count": 1, "unit": "km"}
    assert [r["stable_id"] for r in recs] == ["hdx-barrier:1", "hdx-barrier:40",
                                              "hdx-barrier:276", "hdx-barrier:15"]


def test_two_rows_on_one_point_break_the_registers_identity_and_are_refused():
    parsed = shp.read_zip((FX / "barrier_sample.zip").read_bytes())
    recs = [fi.barrier_record(f, i, FETCHED_AT, "page")
            for i, f in enumerate(parsed["features"])]
    fi.check_points("hdx:barrier", recs, 1)
    with pytest.raises(fl.FetchRefused):
        fi.check_points("hdx:barrier", recs, 0)
    with pytest.raises(fl.FetchRefused):
        fi.check_points("hdx:barrier", recs + [recs[0]], 1)


def test_unosat_assessments_are_read_from_the_datasets_own_description():
    packages = json.loads((FX / "unosat_search_sample.json").read_text())["result"]["results"]
    assert len(packages) == 8
    got = fi.unosat_assessments(packages)
    # the road network, the cropland and the live web map carry no building
    # totals; the two September 2025 datasets are one assessment
    assert [(a["date"], a["scope"]) for a in got] == [
        ("2023-10-10", "governorate"), ("2024-09-03", "strip"),
        ("2025-09-22", "governorate"), ("2025-10-11", "strip")]
    last = got[-1]
    assert (last["destroyed"], last["severely_damaged"], last["moderately_damaged"],
            last["possibly_damaged"], last["total_affected"]) == \
        (123464, 17116, 33857, 23836, 198273)
    assert last["housing_units_damaged"] == 320622 and last["percent_structures_damaged"] == 81
    assert last["license_id"] == "cc-by-sa"
    recs = [fi.unosat_record(a) for a in got]
    for mine, twin in zip(recs, TWINS["unosat"]):
        k1, c1, row = held_form("infrastructure", mine, places())
        k2, c2, _ = held_form("infrastructure", twin, places())
        assert k1 == k2 and c1 == c2, (k1, k2)
        assert row.place_id == 1 and row.unit == "structures"
    assert recs[-1]["stable_id"] == "unosat-cda:strip:2025-10-11"
    doc = fi.unosat_doc(got, FETCHED_AT)
    assert doc["metadata"]["vintage"] == "2025-10-11"
    assert doc["metadata"]["by_scope"] == {"strip": 2, "governorate": 2}
    assert doc["metadata"]["vintage_url"].endswith("damage-assessment-11-october-2025")


def test_the_imagery_date_and_the_totals_are_found_in_unosats_sentences():
    assert fi.assessment_date("based on images collected on 3 and 6 September 2024 when") == "2024-09-03"
    assert fi.assessment_date("an image collected on 15 October 2023 shows") == "2023-10-15"
    assert fi.assessment_date("damage as of 22-23 September 2025 in Gaza") == "2025-09-22"
    assert fi.assessment_date("images collected on the 7 November 2023") == "2023-11-07"
    assert fi.assessment_date("no date here") is None
    assert fi.assessment_date("images collected on 3 Smarch 2024") is None
    t = fi.damage_totals("UNOSAT identified 1,234 destroyed structures, 56 severely damaged "
                         "structures for a total of 1,290 affected structures.")
    assert (t["destroyed"], t["severely_damaged"], t["total_affected"]) == (1234, 56, 1290)
    assert t["moderately_damaged"] is None
    assert fi.damage_totals("12 km of roads were damaged") is None


def test_the_tech_for_palestine_series_is_the_frozen_corpus_unchanged():
    doc = fi.t4p_from_frozen()
    frozen = json.loads(gzip.decompress(fi.FROZEN.read_bytes()))["data"]
    mine = doc["data"]
    assert len(mine) == fi.T4P_RECORDS == 2920
    assert mine == [r for r in frozen if r["sources"][0]["name"] == "TechForPalestine"]
    m = doc["metadata"]
    assert (m["days"], m["first_day"], m["last_day"]) == (730, "2023-10-07", "2025-10-05")
    manifest = json.loads((ROOT / "data" / "frozen" / "manifest.json").read_text())
    assert m["frozen_sha256_uncompressed"] == manifest["infrastructure"]["sha256_uncompressed"]
    assert "fetched_at" not in m          # a copy: the file does not change night to night


def test_the_strips_damage_totals_land_on_the_strip_not_on_gaza_governorate():
    """Migration 101 kept the rows filed under the Gaza Strip (place 1) and
    closed their copies under Gaza governorate (place 15). The record's point
    is a centroid of the Strip; read as a place it is Gaza governorate, and
    the loader would offer 2,920 identities nobody holds."""
    rec = fi.t4p_from_frozen()["data"][0]
    assert rec["location"]["precision"] == "region"
    assert (rec["location"]["lat"], rec["location"]["lon"]) == (31.5, 34.466667)
    pip = Pip(15)                      # what the point-in-polygon lookup answers
    key, _, row = held_form("infrastructure", rec, places(pip))
    assert pip.asked == []             # the rung is skipped for this event type
    assert row.place_id == 1 and not row.located
    assert key == f"v1_infrastructure_tech4palestine|{row.indicator}|2023-10-07|1"
    spec = load_spec("infrastructure")
    assert spec["place"]["latlon_exclude"] == ["barrier_segment", "infrastructure_damage"]
    assert "min_located_pct" not in spec["place"]
    hdx_ds = next(d for d in spec["datasets"] if d["key"] == "v1_infrastructure_hdx")
    assert hdx_ds["overrides"]["place"]["min_located_pct"] == 0.56


# ── the specs ────────────────────────────────────────────────────────────────

def test_each_spec_reads_v2s_own_fetch_and_falls_back_to_the_frozen_corpus():
    want = {
        "food": ("data/raw/wfp_food", "food_prices.json", "food.json.gz"),
        "education": ("data/raw/hdx_schools", "schools.json", "education.json.gz"),
        "infrastructure": ("data/raw/infrastructure",
                           ["tech4palestine.json", "barrier.json",
                            "village_boundaries.json", "unosat.json"],
                           "infrastructure.json.gz"),
    }
    manifest = json.loads((ROOT / "data" / "frozen" / "manifest.json").read_text())
    for cat, (root, glob, frozen) in want.items():
        spec = load_spec(cat)                       # ingest.spec validates it
        assert spec["input"]["root"] == root and spec["input"]["glob"] == glob, cat
        assert spec["input"]["fallback"] == {"root": "data/frozen", "glob": frozen}, cat
        assert spec.get("cadence") == "daily", cat
        assert (ROOT / "data" / "frozen" / frozen).exists(), cat
        assert manifest[cat]["file"] == frozen, cat
    assert Path(ff.OUT).relative_to(ROOT).as_posix() == "data/raw/wfp_food/food_prices.json"
    assert Path(fs.OUT).relative_to(ROOT).as_posix() == "data/raw/hdx_schools/schools.json"
    assert Path(fi.RAW).relative_to(ROOT).as_posix() == "data/raw/infrastructure"
    assert [f"{f}.json" for f in fi.FEEDS] == want["infrastructure"][1]


def test_the_frozen_food_corpus_is_what_v1_held_on_the_day_of_the_cut():
    m = json.loads((ROOT / "data" / "frozen" / "manifest.json").read_text())["food"]
    doc = json.loads(gzip.decompress((ROOT / "data" / "frozen" / m["file"]).read_bytes()))
    assert len(doc["data"]) == m["records"] == 27235
    assert doc["metadata"]["date_range"] == {"earliest": "2007-01-15", "latest": "2026-09-15"}
    # the fallback and the live fetch speak the same shape: a frozen record
    # goes through the transformer untouched
    key, _, row = held_form("food", doc["data"][0], places())
    assert key == "v1_food_wfp|food.price.bread|2007-01-01|15" and row.value_num == 2


def test_the_identities_are_the_stored_ones_and_food_closes_nothing():
    """The fetchers changed where the records come from, not what a row is."""
    food = load_spec("food")
    assert food["identity"]["fields"] == ["indicator", "occurred_at", "place_id"]
    # WFP's weekly file comes back short every other week and is restored the
    # week after (measured over 64 archived nights); a missing point is not a
    # withdrawal, so the generation is never declared complete
    assert "generation" not in food["identity"] and "max_absent" not in food["identity"]
    assert load_spec("education")["identity"] == {"fields": [], "attrs": ["school_id"]}
    infra = {d["key"]: d["overrides"]["identity"] for d in load_spec("infrastructure")["datasets"]}
    assert infra["v1_infrastructure_tech4palestine"]["fields"] == \
        ["indicator", "occurred_at", "place_id"]
    assert infra["v1_infrastructure_hdx"] == {"fields": ["indicator"], "attrs": ["geo_key"]}
    assert infra["v1_infrastructure_unosat"]["fields"] == ["indicator", "occurred_at"]
