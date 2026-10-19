"""Migration 129: PCBS's monthly CPI by region, PCBS's monthly fuel averages and
the World Bank's fuel price database (2026-10-19).

The pure tests run anywhere (no DB, no network): the two parsers on answers
shaped like the sources' own, and the workbook reader on a workbook built here.
The store tests need main-server and skip until the migration is applied.
"""
from __future__ import annotations

import io
import json
import zipfile
from xml.sax.saxutils import escape

import pytest

from ops import fetch_pcbs_monthly as P
from ops import fetch_worldbank_fuel as W


# ── pure: the dashboard answers ──────────────────────────────────────────────

def _overall(rows):
    return {"response": {"overall_table": {"data": rows}}}


def test_parse_overall_keeps_monthly_rows_of_the_base_year():
    rows = P.parse_overall(_overall([
        {"Period": "2026-09", "Region": "Palestine", "Base Year": 2018, "Frequency": "Monthly",
         "CPI (Index)": 158.04, "Percent Change (%)": 4.69},
        {"Period": "2026-09", "Region": "Gaza Strip", "Base Year": 2018, "Frequency": "Monthly",
         "CPI (Index)": 304.45, "Percent Change (%)": 11.36},
        {"Period": "2026", "Region": "Palestine", "Base Year": 2018, "Frequency": "Yearly",
         "CPI (Index)": 150.0, "Percent Change (%)": None},
        {"Period": "1996-01", "Region": "West Bank", "Base Year": 2018, "Frequency": "Monthly",
         "CPI (Index)": 46.25, "Percent Change (%)": None},
        {"Period": "2026-09", "Region": "Somewhere", "Base Year": 2018, "Frequency": "Monthly",
         "CPI (Index)": 1.0, "Percent Change (%)": None},
    ]))
    assert [(r["period"], r["region"], r["index"], r["change"]) for r in rows] == [
        ("2026-09", "Palestine", 158.04, 4.69), ("2026-09", "Gaza Strip", 304.45, 11.36),
        ("1996-01", "West Bank", 46.25, None)]


def test_parse_overall_refuses_a_rebased_index():
    with pytest.raises(ValueError):
        P.parse_overall(_overall([{"Period": "2026-09", "Region": "Palestine", "Base Year": 2025,
                                   "Frequency": "Monthly", "CPI (Index)": 100.0}]))


def test_parse_fuel_keeps_the_six_items_only():
    answer = {"response": {"commodity_table": {"data": [
        {"Period": "2026-09", "Region": "West Bank", "Item Code": "072200104", "Item": "Diesel",
         "Unit": "1 Liter", "Frequency": "Monthly", "Average Price": 8.39, "Percent Change (%)": -1.99},
        {"Period": "2026-09", "Region": "West Bank", "Item Code": "011100106", "Item": "Bread",
         "Unit": "1 kg", "Frequency": "Monthly", "Average Price": 5.0, "Percent Change (%)": 0.0},
        {"Period": "2019-01", "Region": "Palestine", "Item Code": "045200101",
         "Item": "Locally filled gas cylinder delivered to home", "Unit": "Cylinder /12 kg",
         "Frequency": "Monthly", "Average Price": 70.04, "Percent Change (%)": None},
    ]}}}
    rows = P.parse_fuel(answer)
    assert [(r["period"], r["region"], r["item_code"], r["price"]) for r in rows] == [
        ("2026-09", "West Bank", "072200104", 8.39), ("2019-01", "Palestine", "045200101", 70.04)]


def test_observations_carry_place_unit_and_stable_identity():
    cpi = P.cpi_observations([{"period": "2026-09", "region": "Jerusalem J1", "index": 123.91, "change": 0.44}], "2026-10-19T00:00:00+00:00")
    assert [(o["indicator"], o["place_id"], o["unit"], o["value"]) for o in cpi] == [
        ("economic.pcbs_cpi_monthly", 11, "index", 123.91),
        ("economic.pcbs_cpi_monthly_change", 11, "percent", 0.44)]
    assert cpi[0]["stable"] == "pcbs_cpi_monthly:index:east-jerusalem:2026-09"
    assert json.loads(cpi[0]["attrs"])["region"] == "East Jerusalem"
    fuel = P.fuel_observations([{"period": "2026-09", "region": "Palestine", "item_code": "045200101",
                                 "item": "cylinder", "unit_printed": "Cylinder /12 kg", "price": 88.9, "change": None}], "2026-10-19T00:00:00+00:00")
    assert fuel[0]["indicator"] == "fuel.price.average.lpg_12kg_delivered"
    assert fuel[0]["place_id"] is None and fuel[0]["unit"] == "ILS/cylinder"
    assert fuel[0]["occurred"].isoformat() == "2026-09-01T00:00:00+00:00"


# ── pure: the Bank's workbook ────────────────────────────────────────────────

def test_label_unit_and_month_rules():
    assert W.product_for_label("West Bank & Gaza (Gasoline Unleaded 95)") == "gasoline_95"
    assert W.product_for_label("West Bank & Gaza (LPG 12kg)") == "lpg_12kg"
    assert W.product_for_label("West Bank & Gaza (Natural gas)") is None
    assert W.product_for_label("Jordan (Diesel)") is None
    assert W.unit_for("Sheker/Liter") == "ILS/L" and W.unit_for("Sheker/Cylinder") == "ILS/cylinder"
    assert W.unit_for("USD/ton") is None
    assert W.serial_month(42339) == "2015-12"          # 2015-12-01
    assert W.serial_month(43437) == "2018-12"          # 2018-12-03: the Bank's header slips to the 3rd
    assert W.serial_month(42350) is None               # 2015-12-12 is not a month label


def _workbook(sheets: dict[str, list[list]]) -> bytes:
    """A minimal xlsx: shared strings for text, numbers inline, one sheet per name."""
    strings, buf = [], io.BytesIO()

    def sidx(s):
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    def col(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s
    sheet_xml = {}
    for n, (name, rows) in enumerate(sheets.items(), start=1):
        body = ""
        for ri, row in enumerate(rows, start=1):
            cells = ""
            for ci, v in enumerate(row):
                if v is None:
                    continue
                ref = f"{col(ci)}{ri}"
                cells += (f'<c r="{ref}" t="s"><v>{sidx(v)}</v></c>' if isinstance(v, str)
                          else f'<c r="{ref}"><v>{v}</v></c>')
            body += f'<row r="{ri}">{cells}</row>'
        sheet_xml[f"xl/worksheets/sheet{n}.xml"] = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{body}</sheetData></worksheet>')
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(name)}" sheetId="{n}" r:id="rId{n}"/>'
                             for n, name in enumerate(sheets, start=1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{n}" Type="x" Target="worksheets/sheet{n}.xml"/>'
                             for n in range(1, len(sheets) + 1)) + "</Relationships>")
        z.writestr("xl/sharedStrings.xml",
                   '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
        for path, xml in sheet_xml.items():
            z.writestr(path, xml)
    return buf.getvalue()


def test_parse_workbook_reads_west_bank_rows_by_sheet_name():
    hdr = ["Fuel", "Units", 42339, 42370, 43437]              # 2015-12, 2016-01, 2018-12 (dated the 3rd)
    blob = _workbook({
        "Title Page": [["x"]],
        "Premium Gasoline RON95 or above": [hdr, ["Jordan (Gasoline 95)", "JOD/liter", 0.7, 0.7, 0.7],
                                            ["West Bank & Gaza (Gasoline Unleaded 95)", "Sheker/Liter", None, 5.86, 6.08],
                                            ["West Bank & Gaza (Gasoline Unleaded 98)", "Sheker/Liter", None, 6.36, 6.7]],
        "Diesel": [hdr, ["West Bank & Gaza (Diesel)", "Sheker/Liter", None, 5.34, 4.99]],
        "LPG": [hdr, ["West Bank & Gaza (LPG 12kg)", "Sheker/Cylinder", None, 54, 62]],
        "Kerosene": [hdr, ["West Bank & Gaza (Kerosene)", "Sheker/liter", None, 5.34, 4.99]],
    })
    rows = W.parse_workbook(blob)
    got = {(r["product"], r["period"]): (r["value"], r["unit"]) for r in rows}
    assert got[("gasoline_95", "2016-01")] == (5.86, "ILS/L")
    assert got[("gasoline_98", "2018-12")] == (6.7, "ILS/L")
    assert got[("lpg_12kg", "2016-01")] == (54.0, "ILS/cylinder")
    assert ("gasoline_95", "2015-12") not in got                # an empty cell is no row
    assert all(r["sheet"] in W.SHEETS for r in rows) and len(rows) == 10


def test_parse_workbook_refuses_a_missing_sheet():
    with pytest.raises(ValueError):
        W.parse_workbook(_workbook({"Diesel": [["Fuel", "Units", 42339]]}))


# ── the store (main-server only; skips until migration 129 is applied) ───────

@pytest.fixture
def db():
    """A read-only connection held open for the test (the context manager must
    outlive the connection: a bare connect().__enter__() is collected at once,
    which closes it)."""
    try:
        from resolve.db import connect
        cm = connect()
        c = cm.__enter__()
    except Exception as e:                                             # noqa: BLE001
        pytest.skip(f"no database here: {type(e).__name__}")
    try:
        c.execute("SET default_transaction_read_only = on")
        yield c
    finally:
        cm.__exit__(None, None, None)


def _dataset_loaded(c, key):
    ds = c.execute("SELECT dataset_id FROM dataset WHERE key = %s", (key,)).fetchone()
    if not ds:
        pytest.skip(f"{key}: migration 129 not applied")
    n = c.execute("SELECT count(*) FROM observation WHERE dataset_id = %s AND upper_inf(sys_period)", (ds[0],)).fetchone()[0]
    if not n:
        pytest.skip(f"{key}: not loaded yet")
    return ds[0], n


def test_cpi_monthly_served_with_the_september_2026_release(db):
    c = db
    _dataset_loaded(c, "pcbs_cpi_monthly")
    rows = c.execute("""SELECT indicator, attrs->>'region', value_num FROM databank_serving
                        WHERE dataset_key = 'pcbs_cpi_monthly' AND occurred_at = '2026-09-01'""").fetchall()
    got = {(r[0], r[1]): round(float(r[2]), 2) for r in rows}
    assert got[("economic.pcbs_cpi_monthly", "Palestine")] == 158.04
    assert got[("economic.pcbs_cpi_monthly_change", "Palestine")] == 4.69
    assert got[("economic.pcbs_cpi_monthly_change", "Gaza Strip")] == 11.36
    assert got[("economic.pcbs_cpi_monthly", "East Jerusalem")] == 123.91
    first = c.execute("SELECT min(occurred_at)::date FROM databank_serving WHERE dataset_key = 'pcbs_cpi_monthly'").fetchone()[0]
    assert str(first) == "1996-01-01"


def test_fuel_monthly_served_with_the_september_2026_averages(db):
    c = db
    _dataset_loaded(c, "pcbs_fuel_monthly")
    rows = c.execute("""SELECT indicator, value_num, unit FROM databank_serving
                        WHERE dataset_key = 'pcbs_fuel_monthly' AND place_id = 2 AND occurred_at = '2026-09-01'""").fetchall()
    got = {r[0]: (round(float(r[1]), 2), r[2]) for r in rows}
    assert got["fuel.price.average.diesel"] == (8.39, "ILS/L")           # the September cap, held all month
    assert got["fuel.price.average.gasoline_95"] == (7.78, "ILS/L")      # 8.15 then 7.65 from the 7th: a blend
    assert got["fuel.price.average.lpg_12kg_delivered"] == (88.9, "ILS/cylinder")


def test_worldbank_rows_match_wafa_october_2020_and_ride_the_official_indicators(db):
    c = db
    _dataset_loaded(c, "worldbank_gfpd_fuel")
    rows = c.execute("""SELECT indicator, value_num, license_spdx FROM databank_serving
                        WHERE dataset_key = 'worldbank_gfpd_fuel' AND occurred_at = '2020-10-01'""").fetchall()
    got = {r[0]: round(float(r[1]), 2) for r in rows}
    assert got["fuel.price.official.gasoline_95"] == 5.32
    assert got["fuel.price.official.diesel"] == 4.79
    assert got["fuel.price.official.lpg_12kg"] == 58.0
    assert {r[2] for r in rows} == {"ODbL-1.0"}
    span = c.execute("SELECT min(occurred_at)::date, max(occurred_at)::date FROM databank_serving WHERE dataset_key = 'worldbank_gfpd_fuel'").fetchone()
    assert str(span[0]) == "2016-12-01" and str(span[1]) >= "2025-03-01"


def test_offline_reload_is_idempotent(db):
    c = db
    _, before = _dataset_loaded(c, "pcbs_cpi_monthly")
    if not (P.OUT_CPI.exists() and P.OUT_FUEL.exists()):
        pytest.skip("raw monthly files not on disk yet")
    assert P.main(["--offline"]) == 0
    assert P.main(["--offline"]) == 0
    after = c.execute("SELECT count(*) FROM observation o JOIN dataset d USING (dataset_id) WHERE d.key = 'pcbs_cpi_monthly' AND upper_inf(o.sys_period)").fetchone()[0]
    assert after == before
