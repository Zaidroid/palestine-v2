"""Migrations 132–134: PCBS's school statistics by year, and the host countries
as places (2026-10-19). Pure tests run anywhere; the store tests skip until
the migrations are applied and the loaders have run."""
from __future__ import annotations

import pytest
import yaml

from ops import fetch_pcbs_education as E

ROOT = E.fl.ROOT


def test_school_year_reads_both_orders():
    assert E.school_year("1995/1994") == "1994/1995"
    assert E.school_year("2024/2025") == "2024/2025"
    assert E.school_year("2012/2011") == "2011/2012"
    assert E.school_year("2025/2023") is None and E.school_year("x") is None


def test_long_sheet_sums_school_columns_without_kindergartens():
    rows = [["أعداد المدارس"], [], [], ["المنطقة", "حكومة", "", "وكالة", "", "خاصة", "", "المجموع", "Region"],
            ["فلسطين"], ["1995/1994", "1084", "-", "259", "-", "131", "436", "1910", "1994/1995"],
            ["قطاع غزة "], ["2024/2023", "..", "..", "..", "..", "..", "..", "..", "2023/2024"]]
    got = {(r["authority"], r["region"], r["school_year"]): r["value"] for r in E.long_sheet(rows, "schools")}
    assert got[("total", "فلسطين", "1994/1995")] == 1474            # 1084 + 259 + 131, not the printed 1910
    assert got[("unrwa", "فلسطين", "1994/1995")] == 259
    assert not [k for k in got if k[1].startswith("قطاع")]              # ".." is not a row


def test_governorate_sheet_stops_at_the_first_repeated_year_and_maps_places():
    rows = [["توزيع"], [], [], ["الجهة", "كلا الجنسين"], [None, "2012/2011", "2013/2012", "2012/2011", "2013/2012"],
            ["كافة الجهات"], ["فلسطين", "1", "2", "3", "4"], ["الخليل", "100", "110", "60", "66"],
            ["حكومة"], ["القدس*", "50", "55", "30", "33"]]
    got = {(r["authority"], r["place_id"], r["school_year"]): r["value"] for r in E.governorate_sheet(rows, "students")}
    assert got == {("total", 13, "2011/2012"): 100, ("total", 13, "2012/2013"): 110,
                   ("government", 11, "2011/2012"): 50, ("government", 11, "2012/2013"): 55}


def test_observations_sit_on_first_september_of_the_first_year():
    obs = E.observations([{"measure": "teachers", "authority": "unrwa", "place_id": 1, "region": "قطاع غزة", "school_year": "2022/2023", "value": 8246.0, "file": "long"}], "2026-10-19T00:00:00+00:00")
    assert obs[0]["indicator"] == "education.teachers.unrwa" and obs[0]["unit"] == "persons"
    assert obs[0]["occurred"].isoformat() == "2022-09-01T00:00:00+00:00"
    assert obs[0]["stable"] == "pcbs_education_yearly:teachers:unrwa:1:2022"


def test_countries_table_is_sound():
    d = yaml.safe_load(open(ROOT / "db" / "reference" / "countries.yaml"))["countries"]
    codes = [c["iso3"] for c in d]
    assert len(codes) == len(set(codes)) == 116
    assert all(c["name_ar"] and c["name_en"] for c in d)
    assert sum(1 for c in d if "lat" in c) == 115 and [c["iso3"] for c in d if "lat" not in c] == ["PSE"]


@pytest.fixture
def db():
    try:
        from resolve.db import connect
        cm = connect(); c = cm.__enter__()
    except Exception as e:                                             # noqa: BLE001
        pytest.skip(f"no database here: {type(e).__name__}")
    try:
        c.execute("SET default_transaction_read_only = on"); yield c
    finally:
        cm.__exit__(None, None, None)


def test_education_served_with_pcbs_known_values(db):
    ds = db.execute("SELECT dataset_id FROM dataset WHERE key = 'pcbs_education_yearly'").fetchone()
    if not ds:
        pytest.skip("migration 134 not applied")
    n = db.execute("SELECT count(*) FROM databank_serving WHERE dataset_key = 'pcbs_education_yearly'").fetchone()[0]
    if not n:
        pytest.skip("not loaded yet")
    rows = db.execute("""SELECT indicator, place_id, occurred_at::date::text, value_num FROM databank_serving
                         WHERE dataset_key = 'pcbs_education_yearly' AND occurred_at IN ('1994-09-01', '2022-09-01', '2024-09-01')
                         AND indicator IN ('education.schools.total', 'education.students.total', 'education.teachers.total')""").fetchall()
    got = {(r[0], r[1], r[2]): float(r[3]) for r in rows}
    assert got[("education.schools.total", None, "1994-09-01")] == 1474
    assert got[("education.schools.total", None, "2022-09-01")] == 3190
    assert got[("education.teachers.total", None, "1994-09-01")] == 21045
    assert got[("education.schools.total", 13, "2024-09-01")] == 674         # Hebron, 2024/2025
    assert got[("education.students.total", 15, "2022-09-01")] == 219468     # Gaza governorate, 2022/2023
    assert ("education.schools.total", 1, "2024-09-01") not in got           # Gaza Strip stops at 2022/23


def test_refugee_rows_sit_on_their_host_country(db):
    try:
        n = db.execute("SELECT count(*) FROM place WHERE kind = 'country'").fetchone()[0]
    except Exception:                                                  # noqa: BLE001
        pytest.skip("migration 132 not applied")
    if not n:
        pytest.skip("migration 133 not applied")
    assert n == 115
    placed, unplaced = db.execute("""SELECT count(*) FILTER (WHERE place_id IS NOT NULL), count(*) FILTER (WHERE place_id IS NULL)
                                     FROM databank_serving WHERE dataset_key = 'unhcr_population_hdx'""").fetchone()
    assert placed >= 40000
    pse = db.execute("""SELECT count(*) FROM databank_serving WHERE dataset_key = 'unhcr_population_hdx'
                        AND attrs->>'asylum_country_code' = 'PSE' AND place_id IS NOT NULL""").fetchone()[0]
    assert pse == 0                                                    # people residing in Palestine keep the honest NULL
    jor = db.execute("""SELECT p.name_ar FROM databank_serving s JOIN place p USING (place_id)
                        WHERE s.dataset_key = 'unhcr_population_hdx' AND s.attrs->>'asylum_country_code' = 'JOR' LIMIT 1""").fetchone()
    assert jor and jor[0] == "الأردن"
