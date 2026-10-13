"""more-settlements (2026-10-13): Peace Now's population of each settlement,
year by year (ops/fetch_peacenow_settlements.py,
db/mappings/settlements_by_settlement.yaml).

Everything here is offline. The workbook is a cut of the real export read on
2026-10-13 ("Settlements and Outposts Peace Now 07.2026.xlsx"): the header and
12 of the 152 rows of its Settlements sheet, 3 of the 413 outposts and 2 of
the 81 legalization rows, every kept row cell for cell as Peace Now wrote it
(only the shared-string table was renumbered to the strings those rows use).
The page is three pieces of the real Population page of the same day. Where a
test needs a row the sheet does not have (a total, a footnote), it adds it in
memory and says so. No network, no database.
"""
from __future__ import annotations

import copy
import functools
import io
import json
import math
import os
import time
import zipfile
from collections import Counter
from pathlib import Path

import pytest
import yaml

from ingest import bronze, databank
from ingest import spec as spec_mod
from ingest.databank import load_spec
from ops import fetch_peacenow_settlements as ps
from ops import fetchlib as fl
from ops import load_registry

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "more_settlements"
AT = "2026-10-13T09:35:07+00:00"
NAME = "Settlements and Outposts Peace Now 07.2026.xlsx"
CATEGORY = "settlements_by_settlement"
DATASET = "peacenow_settlement_population"
INDICATOR = "settlements.population_by_settlement"


def xlsx() -> bytes:
    return (FX / "settlements_and_outposts_cut.xlsx").read_bytes()


def page() -> str:
    return (FX / "population_page_cut.html").read_text(encoding="utf-8")


@functools.lru_cache(maxsize=None)
def parsed():
    """(settlements, records, info) of the cut. Read once; no test changes it."""
    return ps.parse_settlements(ps.workbook(xlsx())[ps.SHEET], AT)


@functools.lru_cache(maxsize=None)
def spec_of(category: str) -> dict:
    return load_spec(category)


def of(records, name, period=None):
    out = [r for r in records if r["settlement_name"] == name
           and (period is None or r["period"] == period)]
    return out


class Pip:
    """The loader's point resolver, without a database: every point north of
    31.4 is in governorate 14, the rest in none."""

    def resolve(self, lat, lon):
        if lat is None or lon is None:
            return None
        return 14 if lat > 31.4 else None


PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2}, "governorate": {},
          "pcode": {}, "_pip": Pip()}


def engine(rec):
    return databank.t_engine(rec, spec_of(CATEGORY), PLACES, Counter())


def identity(row) -> str:
    return databank.identity_key_for(
        spec_of(CATEGORY)["identity"], row.dataset_key, indicator=row.indicator,
        occurred_at=row.occurred_at, place_id=row.place_id,
        value_num=row.value_num, attrs=row.attrs)


# ── the door ─────────────────────────────────────────────────────────────────

def test_the_sheet_is_found_on_the_page_and_the_known_id_is_only_the_fallback():
    links = ps.sheet_links(page())
    # the page also links a Google FORM (Volunteer): not a spreadsheet
    assert "docs.google.com/forms" in page()
    assert links == [(ps.KNOWN_SHEET_ID, "Download the list of settlements and outposts here")]
    assert ps.choose_sheet(links) == (ps.KNOWN_SHEET_ID, "page")
    # the page is the door: a new document behind the same words is followed
    other = "1" + "x" * 43
    assert ps.choose_sheet(ps.sheet_links(page().replace(ps.KNOWN_SHEET_ID, other))) == (other, "page")
    # no link at all: the known id, and the door says it was a fallback
    sid, door = ps.choose_sheet(ps.sheet_links("<html>maintenance</html>"))
    assert sid == ps.KNOWN_SHEET_ID and door.startswith("fallback:")
    # several spreadsheets: the one named as the list, else the known one, else nothing
    a = f'<a href="https://docs.google.com/spreadsheets/d/{other}/edit">Budget</a>'
    assert ps.choose_sheet(ps.sheet_links(page() + a)) == (ps.KNOWN_SHEET_ID, "page")
    unnamed = page().replace("Download the list of settlements and outposts here", "here")
    sid, door = ps.choose_sheet(ps.sheet_links(unnamed + a))
    assert sid == ps.KNOWN_SHEET_ID and door.startswith("page (several")
    b = a.replace(other, "2" + "y" * 43).replace("Budget", "Plan")
    with pytest.raises(ps.PageChanged, match="none is named"):
        ps.choose_sheet(ps.sheet_links(a + b))


def test_the_page_dates_itself_and_the_export_names_its_month():
    assert ps.page_says(page()) == ["Peace Now's count, 1/8/2026", "Updated: August 1, 2026"]
    disp = ('attachment; filename="SettlementsandOutpostsPeaceNow07.2026.xlsx"; '
            "filename*=UTF-8''Settlements%20and%20Outposts%20Peace%20Now%2007.2026.xlsx")
    assert ps.file_name(disp) == NAME
    assert ps.file_name('attachment; filename="list.xlsx"') == "list.xlsx"
    assert ps.file_name(None) is None
    assert ps.vintage_of(NAME) == "2026-07"
    assert ps.vintage_of("Settlements 13.2026.xlsx") is None      # not a month
    assert ps.vintage_of("Settlements and Outposts.xlsx") is None


def test_a_sign_in_page_is_a_login_wall_and_never_a_workbook():
    ok = "https://doc-0o-b4-sheets.googleusercontent.com/export/abc"
    xl = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert ps.check_export(ok, xl, xlsx()) == xlsx()
    with pytest.raises(ps.LoginWall, match="sign-in"):
        ps.check_export("https://accounts.google.com/ServiceLogin?continue=x", "text/html", b"<html>")
    with pytest.raises(ps.LoginWall, match="sign-in"):
        ps.check_export("https://accounts.google.com/v3/signin/identifier", xl, xlsx())
    with pytest.raises(ps.LoginWall, match="not an xlsx"):
        ps.check_export(ok, "text/html; charset=utf-8", b"<!doctype html>")
    with pytest.raises(ps.LoginWall, match="not an xlsx"):
        ps.check_export(ok, xl, b"<html>Before you continue</html>")
    with pytest.raises(ps.SheetChanged, match="bytes, over"):
        ps.check_export(ok, xl, b"PK" + b"0" * ps.MAX_EXPORT_BYTES)


# ── the workbook ─────────────────────────────────────────────────────────────

def test_the_workbook_has_three_sheets_and_only_settlements_is_read():
    wb = ps.workbook(xlsx())
    assert list(wb) == ["Settlements", "Outposts", "Outpost Legalization"]
    rows = dict(wb["Settlements"]["rows"])
    header = rows[1]
    assert len(header) == 68
    assert [header[i] for i in range(13)] == list(ps.DESCRIPTIVE)
    assert header[13] == "Population 1969" and header[67] == "Population May 2024"
    assert "H12:I12" in wb["Settlements"]["merged"]          # Elmatan's "January 2002"
    # numbers are numbers, text is text, a cell with nothing in it is absent
    assert rows[2][0] == "Avnei Hefetz" and rows[2][2] == 1.0 and rows[2][66] == 2454.0
    assert 24 not in rows[2] and 25 not in rows[2]            # Population 1980, 1981: blank
    doc = ps.document(xlsx(), NAME, "page", ps.KNOWN_SHEET_ID, "Download", ps.page_says(page()), AT)
    not_taken = doc["metadata"]["sheets_not_taken"]
    assert list(not_taken) == ["Outposts", "Outpost Legalization"]
    assert not_taken["Outposts"]["rows"] == 3
    assert not_taken["Outposts"]["columns"][:4] == ["Name", "Name Hebrew", "DB_ID", "Settlement Type"]
    assert "Population" not in " ".join(not_taken["Outposts"]["columns"])
    assert not_taken["Outpost Legalization"]["columns"][4] == "Legalization Process Start"
    assert doc["metadata"]["columns_not_taken"] == []
    assert doc["metadata"]["columns_taken"][:13] == list(ps.DESCRIPTIVE)
    with pytest.raises(ps.SheetChanged, match="no sheet named 'Settlements'"):
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(xlsx())) as z, zipfile.ZipFile(buf, "w") as o:
            for n in z.namelist():
                data = z.read(n)
                if n == "xl/workbook.xml":
                    data = data.replace(b'name="Settlements"', b'name="Settlements 2026"')
                o.writestr(n, data)
        ps.document(buf.getvalue(), NAME, "page", ps.KNOWN_SHEET_ID, None, [], AT)


def test_a_population_column_is_dated_by_its_own_label_or_the_fetch_stops():
    assert ps.period_of("Population 2023") == {
        "period": "2023", "period_kind": "year_end", "year": 2023, "date": "2023-12-31"}
    assert ps.period_of("Population May 2024") == {
        "period": "2024-05", "period_kind": "month", "year": 2024, "date": "2024-05-01"}
    assert ps.period_of("Population Smarch 2024") is None
    assert ps.period_of("Municipality") is None
    _, _, info = parsed()
    cols = info["population_columns"]
    assert len(cols) == 55 and cols[0] == "Population 1969" and cols[-2:] == [
        "Population 2023", "Population May 2024"]
    assert "Population 1984" not in cols                      # the sheet has none
    sheet = copy.deepcopy(ps.workbook(xlsx())[ps.SHEET])
    sheet["rows"][0][1][67] = "Population mid-2024 (est.)"
    with pytest.raises(ps.SheetChanged, match="cannot date"):
        ps.parse_settlements(sheet, AT)
    sheet["rows"][0][1][67] = "Population 2023"
    with pytest.raises(ps.SheetChanged, match="two columns are headed"):
        ps.parse_settlements(sheet, AT)
    sheet["rows"][0][1][67] = "Households"                    # not ours: named, not read
    _, recs, info = ps.parse_settlements(sheet, AT)
    assert info["columns_not_taken"] == ["Households"]
    assert not [r for r in recs if r["period"] == "2024-05"]
    sheet["rows"][0][1].pop(2)                                # DB_ID gone
    with pytest.raises(ps.SheetChanged, match="no 'DB_ID' column"):
        ps.parse_settlements(sheet, AT)


# ── what a cell is ───────────────────────────────────────────────────────────

def test_a_blank_is_nothing_and_a_zero_is_counted_and_never_loaded():
    settlements, records, info = parsed()
    c = info["counts"]
    assert c["settlements"] == len(settlements) == 12
    assert c["cell:blank"] + len(records) == 12 * 55          # every cell is one or the other
    # Avnei Hefetz, established 1990: 0 for 1969-79 and 1982-89 (before), blank
    # for 1980 and 1981, 0 for 1990-92 (it existed), 147 in 1993
    av = {r["period"]: r for r in of(records, "Avnei Hefetz")}
    assert "1980" not in av and "1981" not in av
    assert av["1979"]["cell_kind"] == av["1989"]["cell_kind"] == "zero_before_established"
    assert [av[y]["cell_kind"] for y in ("1990", "1991", "1992")] == ["zero_no_figure"] * 3
    assert (av["1993"]["cell_kind"], av["1993"]["value"]) == ("figure", 147)
    assert Counter(r["cell_kind"] for r in av.values()) == {
        "zero_before_established": 18, "zero_no_figure": 3, "figure": 32}
    # Ovnat, established 1983: 0 in every column to 2007, then an estimate.
    # The sheet's zero is its "no figure", not a count of nobody.
    ov = {r["period"]: r for r in of(records, "Ovnat")}
    assert all(ov[str(y)]["cell_kind"] == "zero_no_figure" for y in range(1985, 2008))
    assert (ov["2008"]["cell_kind"], ov["2008"]["value"]) == ("estimated", 100)
    # Almog: a zero BETWEEN two figures (57 in 1983, 0 for 1985-92, 103 in 1993)
    al = {r["period"]: r for r in of(records, "Almog")}
    assert (al["1983"]["value"], al["1985"]["cell_kind"], al["1993"]["value"]) == (57, "zero_no_figure", 103)
    # ...and from the 2008 column on the sheet writes no zero at all
    assert max(r["period"] for r in records if r["cell_kind"].startswith("zero")) == "2007"
    # the spec loads none of them, and counts each by its reason
    out = Counter()
    for r in records:
        res = engine(r)
        out[res.reason if isinstance(res, databank.Drop) else "row"] += 1
    assert out == {"row": 218, "zero_before_established": 104, "zero_no_figure": 59,
                   "approximate_placeholder": 14, "unknown_marker": 5}
    assert all(row.value_num > 0 for r in records
               if not isinstance(engine(r), databank.Drop) for row in engine(r))


def test_text_cells_are_read_for_what_they_say():
    assert ps.read_cell(2454.0, 2023, 1990) == ("figure", 2454, None)
    assert ps.read_cell(0.0, 1989, 1990) == ("zero_before_established", 0, None)
    assert ps.read_cell(0.0, 1990, 1990) == ("zero_no_figure", 0, None)
    assert ps.read_cell(0.0, 1990, None) == ("zero_no_figure", 0, None)
    assert ps.read_cell("100 (estimated)", 2008, 1983) == ("estimated", 100, "100 (estimated)")
    assert ps.read_cell("1,250 (Estimated)", 2008, 1983) == ("estimated", 1250, "1,250 (Estimated)")
    assert ps.read_cell("כ-50", 1975, 1977) == ("approximate", 50, "כ-50")
    assert ps.read_cell("?", 1975, 1972) == ("unknown_marker", None, "?")
    # a number typed as text, with or without commas, is that number
    assert ps.read_cell("1,234", 2023, 1990) == ("figure", 1234, None)
    assert ps.read_cell("87486", 2023, 1990) == ("figure", 87486, None)
    assert ps.read_cell("0", 1980, 1990) == ("zero_before_established", 0, None)
    # anything else is counted, never guessed
    assert ps.read_cell("n/a", 2023, 1990) == ("unreadable", None, "n/a")
    assert ps.read_cell("about 50", 1975, 1977) == ("unreadable", None, "about 50")
    assert ps.read_cell(-3.0, 2023, 1990)[0] == "unreadable"
    assert ps.read_cell(True, 2023, 1990)[0] == "unreadable"
    assert ps.established_year(1990.0) == 1990
    assert ps.established_year("January 2002") == 2002
    assert ps.established_year("1984 (as a military ouptost; established as a civilian settlement in 1997)") == 1984
    assert ps.established_year(None) is None
    # in the sheet: Kiryat Arba's «כ-50» for 1972-74 and "?" for 1975-79
    _, records, _ = parsed()
    ka = {r["period"]: r for r in of(records, "Kiryat Arba")}
    assert [ka[str(y)]["cell_text"] for y in (1972, 1974, 1975, 1979)] == ["כ-50", "כ-50", "?", "?"]
    assert ka["1975"]["value"] is None and ka["1972"]["value"] == 50
    # ...and Almog carries «כ-50» from 1969, eight years before the sheet says it was established
    al = of(records, "Almog", "1969")[0]
    assert (al["cell_kind"], al["year_established"]) == ("approximate", 1977)
    # an estimate is loaded and says it is one
    [row] = engine(of(records, "Shani", "2008")[0])
    assert row.value_num == 400 and row.attrs["value_note"] == "estimated"
    assert row.attrs["cell_text"] == "400 (estimated)"
    [plain] = engine(of(records, "Adora", "2023")[0])
    assert "value_note" not in plain.attrs and "cell_text" not in plain.attrs


# ── the date ─────────────────────────────────────────────────────────────────

def test_a_year_is_a_year_and_may_2024_is_a_month_never_2024s_year_end():
    _, records, _ = parsed()
    y = of(records, "Adora", "2023")[0]
    m = of(records, "Adora", "2024-05")[0]
    assert (y["date"], y["period_kind"], y["sheet_column"]) == ("2023-12-31", "year_end", "Population 2023")
    assert (m["date"], m["period_kind"], m["sheet_column"]) == ("2024-05-01", "month", "Population May 2024")
    [ry], [rm] = engine(y), engine(m)
    # the house convention of settlements.settler_population: the year's start,
    # precision year, "period-end stock"
    assert (ry.occurred_at, ry.precision, ry.value_num) == ("2023-01-01", "year", 534)
    assert ry.attrs["reference"] == "period-end stock" and ry.attrs["year"] == 2023
    [total] = databank.t_engine(
        {"stable_id": "peacenow-settlers:2023", "date": "2023-12-31", "year": 2023,
         "event_type": "settler_population", "location": {"region": "West Bank"},
         "metrics": {"count": 503732, "unit": "settlers"},
         "sources": [{"name": "Peace Now — Settlement Watch"}]},
        load_spec("settlements"), PLACES, Counter())
    assert (total.occurred_at, total.precision, total.attrs["reference"]) == (
        ry.occurred_at, ry.precision, ry.attrs["reference"])
    assert (rm.occurred_at, rm.precision, rm.value_num) == ("2024-05-01", "month", 541)
    assert "not that year's year-end" in rm.attrs["reference"]
    assert "year" not in m and "year" not in rm.attrs          # a month's figure is no year's
    assert rm.attrs["sheet_column"] == "Population May 2024" and rm.attrs["period"] == "2024-05"
    assert not [r for r in records if r["date"] == "2024-12-31"]     # nobody filed it as 2024


# ── a row ────────────────────────────────────────────────────────────────────

def test_a_row_carries_the_settlement_as_the_sheet_writes_it():
    _, records, _ = parsed()
    [row] = engine(of(records, "Avnei Hefetz", "2023")[0])
    assert (row.dataset_key, row.indicator, row.unit) == (DATASET, INDICATOR, "persons")
    assert row.v1_stable_id == "peacenow-settlement-pop:1:2023"
    assert (row.value_num, row.value_text, row.place_id, row.located) == (2454, None, 14, True)
    assert row.attrs == {
        "settlement_id": 1, "settlement_name": "Avnei Hefetz", "settlement_name_he": "אבני חפץ",
        "year_established": 1990, "municipality": "Shomron", "urban_pattern": "Urban",
        "distance_from_green_line_km": 4.2, "elevation_m": 200,
        "lat": 32.28517186, "lon": 35.0750225, "itm_x": 207331, "itm_y": 687989,
        "sheet_column": "Population 2023", "period": "2023", "year": 2023,
        "coverage": "West Bank settlements; East Jerusalem settlements are not in the list",
        "reference": "period-end stock"}
    # nothing about OUR fetch is in what a row says: a re-fetch is not a revision
    assert "fetched_at" not in json.dumps(row.attrs)
    again = ps.parse_settlements(ps.workbook(xlsx())[ps.SHEET], "2026-10-20T03:40:00+00:00")[1]
    [later] = engine(of(again, "Avnei Hefetz", "2023")[0])
    assert (later.attrs, later.value_num, identity(later)) == (row.attrs, row.value_num, identity(row))
    # the sheet's own spellings stay: comments, a text year, a council in odd capitals
    [tz] = engine(of(records, "Tel Zion", "2023")[0])
    assert tz.attrs["comments"] == "In 2023 splited from the settlement of Kochav Yaacov"
    settlements, _, _ = parsed()
    by = {s["settlement_name"]: s for s in settlements}
    assert by["Elmatan"]["year_established"] == "January 2002" and by["Elmatan"]["figures"] == 0
    assert by["Sa-Nur"]["municipality"] == "SHOmron" and by["Ibei Hanahal"]["municipality"] == "GUsh Etzion"
    # a figure the sheet states for a year before its own year of establishment is loaded as written
    mi = of(records, "Modi'in Ilit", "1994")[0]
    assert (mi["year_established"], mi["cell_kind"], mi["value"]) == (1996, "figure", 2400)


def test_the_identity_is_the_settlement_and_the_period_and_is_injective():
    _, records, _ = parsed()
    rows = [row for r in records if not isinstance(engine(r), databank.Drop) for row in engine(r)]
    assert len(rows) == 218
    keys = [identity(r) for r in rows]
    assert len(set(keys)) == 218
    [row] = engine(of(records, "Adora", "2023")[0])
    assert identity(row) == f"{DATASET}|{INDICATOR}|2023-01-01|3|2023"
    [may] = engine(of(records, "Adora", "2024-05")[0])
    assert identity(may) == f"{DATASET}|{INDICATOR}|2024-05-01|3|2024-05"
    # the value is not in the key: a revised figure is the same row
    revised = dict(of(records, "Adora", "2023")[0], value=540)
    assert identity(engine(revised)[0]) == identity(row)
    # neither is the name or the place: Peace Now respelling a settlement, or a
    # redrawn governorate, does not make a second row
    renamed = dict(of(records, "Adora", "2023")[0], settlement_name="Adura")
    assert identity(engine(renamed)[0]) == identity(row)
    # a month and a year that would share a stored date still have two keys
    base = of(records, "Adora", "2023")[0]
    jan = dict(base, **ps.period_of("Population January 2025"), sheet_column="Population January 2025")
    year = dict(base, **ps.period_of("Population 2025"), sheet_column="Population 2025")
    [rj], [ry] = engine(jan), engine(year)
    assert rj.occurred_at == ry.occurred_at == "2025-01-01"
    assert (rj.precision, ry.precision) == ("month", "year")
    assert identity(rj) != identity(ry)
    # one DB_ID on two rows of the sheet would be two settlements under one key: refused
    sheet = copy.deepcopy(ps.workbook(xlsx())[ps.SHEET])
    sheet["rows"][2][1][2] = 1.0                              # Ovnat given Avnei Hefetz's number
    with pytest.raises(ps.SheetChanged, match="DB_ID 1 is on rows 2 and 3"):
        ps.parse_settlements(sheet, AT)


# ── the place ────────────────────────────────────────────────────────────────

def test_the_place_is_the_sheets_own_point_or_nothing():
    settlements, records, info = parsed()
    by = {s["settlement_name"]: s for s in settlements}
    # "x (UTM)" is the latitude and "y (UTM)" the longitude, in degrees
    assert by["Adora"]["location"] == {"name": "Adora", "lat": 31.55238961, "lon": 35.01648338,
                                       "itm_x": 201676, "itm_y": 606742}
    [row] = engine(of(records, "Adora", "2023")[0])
    assert (row.place_id, row.located) == (14, True)
    # a point in no governorate: place NULL, the name still on the row
    [shani] = engine(of(records, "Shani", "2008")[0])
    assert (shani.place_id, shani.located) == (None, False)
    assert shani.attrs["settlement_name"] == "Shani" and shani.attrs["lat"] == 31.35764549
    assert "region" not in shani.attrs                        # never the whole territory's row
    # no point at all in the sheet: no place, and (today) no figure either
    assert by["Ibei Hanahal"]["location"] == {"name": "Ibei Hanahal"}
    assert by["Ibei Hanahal"]["figures"] == 0
    no_point = dict(of(records, "Adora", "2023")[0], location={"name": "Adora"})
    [np_row] = engine(no_point)
    assert (np_row.place_id, np_row.located) == (None, False) and "lat" not in np_row.attrs
    spec = load_spec(CATEGORY)
    assert (spec["place"]["strategy"], spec["place"]["fallback"]) == ("latlon", ["none"])
    assert info["counts"]["settlements_with_a_point"] == 11
    assert info["counts"]["settlements_without_a_point"] == 1


def test_the_sheets_degrees_are_its_own_grid_point_and_tel_zion_gets_them_the_same_way():
    settlements, records, info = parsed()
    worst = {}
    for s in settlements:
        loc = s["location"]
        if "itm_x" in loc and "lat" in loc and "coord_basis" not in loc:
            la, lo = ps.itm_to_latlon(loc["itm_x"], loc["itm_y"])
            worst[s["settlement_name"]] = math.hypot((la - loc["lat"]) * 111_000,
                                                     (lo - loc["lon"]) * 94_000)
    assert len(worst) == 10
    far = {n: round(m) for n, m in worst.items() if m >= 1.0}
    assert far == {"Sa-Nur": 81}                              # typed by hand, it seems; kept as written
    assert max(m for n, m in worst.items() if n != "Sa-Nur") < 0.7
    # Tel Zion: a grid point and no degrees in the sheet
    tz = next(s for s in settlements if s["settlement_name"] == "Tel Zion")
    assert (tz["location"]["itm_x"], tz["location"]["itm_y"]) == (222587, 642791)
    assert (tz["location"]["lat"], tz["location"]["lon"]) == (31.87763458, 35.23682984)
    assert "GRS80, no datum shift" in tz["location"]["coord_basis"]
    assert info["counts"]["degrees_from_grid"] == 1
    [row] = engine(of(records, "Tel Zion", "2023")[0])
    assert row.place_id == 14 and row.attrs["coord_basis"] == tz["location"]["coord_basis"]
    # degrees that are not in this country are not a point
    sheet = copy.deepcopy(ps.workbook(xlsx())[ps.SHEET])
    sheet["rows"][1][1][5], sheet["rows"][1][1][6] = 207331.0, 687989.0   # metres in the degree columns
    s2, _, i2 = ps.parse_settlements(sheet, AT)
    assert i2["counts"]["degrees_out_of_range"] == 1
    assert s2[0]["location"]["lat"] == pytest.approx(32.28517, abs=1e-5)  # from the grid instead
    assert "coord_basis" in s2[0]["location"]


# ── what is not a settlement ─────────────────────────────────────────────────

def test_a_total_a_footnote_and_a_nameless_row_are_dropped_by_rule_and_counted():
    """The sheet has none of these today. The three rows are added here, in
    memory, after the last real row."""
    sheet = copy.deepcopy(ps.workbook(xlsx())[ps.SHEET])
    real = len(parsed()[1])
    sheet["rows"] += [
        (154, {0: "Total", 66: 503732.0, 67: 496852.0}),
        (155, {66: 503732.0}),                                         # a sum under no label
        (156, {0: "* Population figures are rounded"}),                # a footnote
        (157, {0: "New settlement", 1: "יישוב חדש", 66: 120.0}),       # named, numbered by nobody
        (158, {0: 'סה"כ', 2: 9999.0, 66: 503732.0}),                   # a total with a number in DB_ID
        (160, {70: "see the note on the map"}),                        # a stray cell beyond the table
    ]
    settlements, records, info = ps.parse_settlements(sheet, AT)
    assert len(settlements) == 12 and len(records) == real
    assert info["rows_dropped"] == {
        "total_row": [{"row": 154, "name": "Total"}, {"row": 158, "name": 'סה"כ'}],
        "row_without_name": [155],
        "row_without_id": [{"row": 156, "name": "* Population figures are rounded"},
                           {"row": 157, "name": "New settlement"}]}
    assert not [r for r in records if r["value"] in (503732, 496852, 120)]
    # a settlement whose name merely starts like a sum is still a settlement
    assert not ps._TOTAL_NAME.search("Susiya") and not ps._TOTAL_NAME.search("Totem Farm")
    assert ps._TOTAL_NAME.search("TOTAL West Bank") and ps._TOTAL_NAME.search("Grand total")


# ── the raw file and the fetch ───────────────────────────────────────────────

def test_the_raw_file_says_its_vintage_its_door_and_everything_it_left():
    doc = ps.document(xlsx(), NAME, "page", ps.KNOWN_SHEET_ID,
                      "Download the list of settlements and outposts here",
                      ps.page_says(page()), AT)
    m = doc["metadata"]
    assert (m["vintage"], m["vintage_url"]) == ("2026-07", ps.PAGE)
    assert f'"{NAME}"' in m["vintage_basis"]
    assert "the page says: Peace Now's count, 1/8/2026 / Updated: August 1, 2026" in m["vintage_basis"]
    assert '"Population 1969" to "Population May 2024"' in m["vintage_basis"]
    assert (m["sheet_link"], m["sheet_id"], m["file_name"]) == ("page", ps.KNOWN_SHEET_ID, NAME)
    assert (m["settlements"], m["settlements_with_a_figure"], m["figures"], m["records"]) == (12, 9, 218, 400)
    assert m["cells"] == {"approximate": 14, "blank": 260, "estimated": 2, "figure": 216,
                          "unknown_marker": 5, "zero_before_established": 104, "zero_no_figure": 59}
    assert (m["first_period"], m["last_year_end"], m["data_through"]) == ("1980", "2023", "2024-05")
    assert m["column_sums"]["2023"] == sum(
        r["value"] for r in doc["data"] if r["period"] == "2023" and r["cell_kind"] in ps.LOADABLE)
    assert m["license"].startswith("no licence stated") and "Peace Now" in m["attribution"]
    assert len(doc["settlements"]) == 12 and len(doc["data"]) == 400
    # the loader's vintage reader takes it from the raw file as written
    assert ps.document(xlsx(), "list.xlsx", "page", ps.KNOWN_SHEET_ID, None, [], AT)[
        "metadata"]["vintage"] == "2024-05"                   # no month in the name: the newest column
    rec = doc["data"][0]
    assert rec["sources"][0]["name"] == ps.SOURCE_NAME
    assert load_spec(CATEGORY)["source_routing"]["by_name"] == {ps.SOURCE_NAME: "peace_now"}


def test_the_fetch_is_atomic_floored_and_ledgered(tmp_path, monkeypatch):
    out = tmp_path / "raw" / "settlement_population.json"
    ledger = tmp_path / "fetch-events.ndjson"
    monkeypatch.setattr(ps, "OUT", out)
    monkeypatch.setattr(fl, "EVENTS", ledger)
    monkeypatch.setattr(bronze, "BRONZE", tmp_path / "bronze")
    monkeypatch.setattr(fl, "get", lambda url, timeout=120: page().encode("utf-8"))
    asked = []

    def download(sheet_id):
        asked.append(sheet_id)
        return xlsx(), NAME
    monkeypatch.setattr(ps, "download", download)

    def lines():
        return [json.loads(x) for x in ledger.read_text().splitlines()] if ledger.exists() else []

    # the cut holds 12 settlements: below the floor, refused, nothing written
    assert ps.main([]) == 1
    assert not out.exists()
    assert lines()[-1] == {**lines()[-1], "label": ps.LABEL, "outcome": "refused",
                           "rows": 12, "floor": ps.MIN_SETTLEMENTS, "what": "settlements"}
    # a dry run writes no ledger line and no file, and stages what it would write
    n = len(lines())
    monkeypatch.setattr(ps, "MIN_SETTLEMENTS", 10)
    monkeypatch.setattr(ps, "MIN_FIGURES", 200)
    assert ps.main(["--dry-run", "--stage", str(tmp_path / "stage")]) == 0
    assert len(lines()) == n and not out.exists()
    assert json.loads((tmp_path / "stage" / out.name).read_text())["metadata"]["vintage"] == "2026-07"
    # a real one writes the file, one bronze payload and one line
    assert ps.main([]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["metadata"]["sheet_link"] == "page" and doc["metadata"]["bronze"].startswith("bronze://peace_now/")
    assert lines()[-1] == {**lines()[-1], "label": ps.LABEL, "outcome": "ok", "rows": 400,
                           "figures": 218, "settlements": 12, "data_through": "2024-05",
                           "vintage": "2026-07", "sheet_link": "page"}
    assert asked == [ps.KNOWN_SHEET_ID] * 3
    assert not list(out.parent.glob("*.tmp"))
    # a held file younger than a week is not fetched again: no request, no line
    n = len(lines())
    assert ps.main([]) == 0 and len(asked) == 3 and len(lines()) == n
    assert ps.main(["--force"]) == 0 and len(asked) == 4
    assert "sheet_id" not in lines()[-1]                      # the document known on 2026-10-13
    # the page links another document one day: it is followed, and the line says so
    other = "1" + "x" * 43
    monkeypatch.setattr(fl, "get", lambda url, timeout=120:
                        page().replace(ps.KNOWN_SHEET_ID, other).encode("utf-8"))
    assert ps.main(["--force"]) == 0 and asked[-1] == other
    assert lines()[-1]["sheet_id"] == other and lines()[-1]["sheet_link"] == "page"
    assert json.loads(out.read_text(encoding="utf-8"))["metadata"]["sheet_id"] == other
    monkeypatch.setattr(fl, "get", lambda url, timeout=120: page().encode("utf-8"))
    # a figures floor of its own: a sheet that kept its rows and lost its numbers
    monkeypatch.setattr(ps, "MIN_FIGURES", 219)
    held = out.read_text(encoding="utf-8")
    assert ps.main(["--force"]) == 1
    assert lines()[-1]["outcome"] == "refused" and lines()[-1]["what"] == "figures"
    assert out.read_text(encoding="utf-8") == held            # yesterday's file stands
    monkeypatch.setattr(ps, "MIN_FIGURES", 200)
    # the page down: the known id is still a door, and the file says it was used
    def no_page(url, timeout=120):
        raise TimeoutError("timed out")
    monkeypatch.setattr(fl, "get", no_page)
    assert ps.main(["--force"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["metadata"]["sheet_link"].startswith(
        "fallback: the page could not be read (TimeoutError)")
    assert lines()[-1]["sheet_link"] == "fallback"
    # a sign-in page: stop, say so, keep the file
    held = out.read_text(encoding="utf-8")

    def wall(sheet_id):
        raise ps.LoginWall("redirected to accounts.google.com: the spreadsheet asks for a sign-in")
    monkeypatch.setattr(ps, "download", wall)
    assert ps.main(["--force"]) == 1
    assert lines()[-1]["outcome"] == "error" and lines()[-1]["error"].startswith("LoginWall:")
    assert out.read_text(encoding="utf-8") == held
    # an old held file is fetched again without --force
    monkeypatch.setattr(ps, "download", download)
    old = time.time() - (ps.MAX_AGE_DAYS + 1) * 86400
    os.utime(out, (old, old))
    assert ps.main([]) == 0 and len(asked) == 8


# ── the spec and the registry ────────────────────────────────────────────────

def test_the_spec_is_engine_driven_and_declares_what_it_measured():
    raw = yaml.safe_load((ROOT / "db" / "mappings" / f"{CATEGORY}.yaml").read_text(encoding="utf-8"))
    assert spec_mod.validate(raw, CATEGORY) == []
    spec = load_spec(CATEGORY)
    assert spec["transform"] == "engine" and databank.TRANSFORMERS[CATEGORY] is databank.t_engine
    assert spec["v1_category"] == "settlements" and spec["shape"] == "observation"
    assert spec["datasets"] == [{"key": DATASET, "source": "peace_now"}]
    assert spec["input"] == {"root": "data/raw/peacenow", "glob": ps.OUT.name}
    assert ps.OUT == fl.ROOT / "data" / "raw" / "peacenow" / "settlement_population.json"
    assert spec["indicator"]["template"] == INDICATOR        # the settlement is never in the key
    assert spec["identity"] == {"fields": ["indicator", "occurred_at"],
                                "attrs": ["settlement_id", "period"],
                                "generation": "complete", "max_absent": 150}
    # the floors are the fetcher's own, set from the cells that are LOADED
    drops = {d["reason"]: d["measured"] for d in spec["drop"]}
    assert drops == {"zero_before_established": 1433, "zero_no_figure": 815,
                     "approximate_placeholder": 261, "unknown_marker": 5, "unreadable_cell": 0}
    loaded = spec["records_measured"] - sum(drops.values())
    assert loaded == 4370
    assert spec["expect"]["min_records"] == ps.MIN_FIGURES == math.ceil(0.9 * loaded)
    assert ps.MIN_SETTLEMENTS == math.ceil(0.9 * 152)
    assert loaded < spec["expect"]["max_observations"] < 2 * loaded
    # every kind of cell the fetcher can write is either loaded or a declared drop
    dropped_kinds = {d["when"]["value"] for d in spec["drop"]}
    assert dropped_kinds == {"zero_before_established", "zero_no_figure", "approximate",
                             "unknown_marker", "unreadable"}
    assert not dropped_kinds & set(ps.LOADABLE)
    for kind in dropped_kinds:
        rec = dict(parsed()[1][0], cell_kind=kind)
        assert isinstance(engine(rec), databank.Drop), kind
    # a record of another source is refused, not filed here
    stray = dict(parsed()[1][0], sources=[{"name": "Peace Now — Settlement Watch"}])
    assert engine(stray).reason == "unroutable"
    # the nightly walks it
    assert CATEGORY in sorted(databank.TRANSFORMERS)


def test_each_of_the_two_settlement_indicators_meets_exactly_one_rule():
    mine = load_spec(CATEGORY)["registry"]
    total = load_spec("settlements")["registry"]
    pairs = [(INDICATOR, "persons", 4370), ("settlements.settler_population", "settlers", 51)]
    for ind, unit, _n in pairs:
        hits = [(name, r["when"]) for name, reg in (("mine", mine), ("total", total))
                for r in reg["rules"] if load_registry.matches(r, ind, unit)]
        assert len(hits) == 1, (ind, hits)
    got_mine, c1 = load_registry.classify(pairs, mine["rules"])
    got_total, c2 = load_registry.classify(pairs, total["rules"])
    assert set(got_mine) == {INDICATOR} and set(got_total) == {"settlements.settler_population"}
    assert c1 == c2 == []
    # both files are handed the whole `settlements` category: nothing is left over
    assert load_registry.unclassified_by_reader(
        [("settlements", pairs, got_total), (CATEGORY, pairs, got_mine)]) == {
            "settlements": [], CATEGORY: []}
    assert mine["max_unclassified"] == total["max_unclassified"] == 0
    m = got_mine[INDICATOR]
    assert (m["concept"], m["measure_kind"], m["polarity"], m["grain"], m["place_grain"],
            m["canonical_unit"]) == ("settlement", "stock", -1, "year", "point", "persons")
    concepts = yaml.safe_load((ROOT / "db/registry/concepts.yaml").read_text(encoding="utf-8"))["concepts"]
    units = yaml.safe_load((ROOT / "db/registry/units.yaml").read_text(encoding="utf-8"))["units"]
    assert m["concept"] in concepts and m["canonical_unit"] in units
    # the total keeps the meaning it had
    t = got_total["settlements.settler_population"]
    assert (t["concept"], t["measure_kind"], t["grain"], t["place_grain"], t["canonical_unit"]) == (
        "settlement", "stock", "year", "region", "persons")


def test_the_series_has_a_name_and_a_warning_in_both_languages():
    names = load_registry.load_names()
    rule = load_spec(CATEGORY)["registry"]["rules"][0]
    en, ar = load_registry.name_for(INDICATOR, {f: rule.get(f) for f in load_registry.FIELDS}, None, names)
    assert en == ("Population of each Israeli settlement in the West Bank, excluding East "
                  "Jerusalem, by year (Peace Now)")
    assert ar == "عدد سكان كل مستوطنة إسرائيلية في الضفة الغربية دون القدس الشرقية، حسب السنة (السلام الآن)"
    w, w_ar = rule["serve_warning"], rule["serve_warning_ar"]
    # what a reader must know, in both: whose figures, the source Peace Now names,
    # East Jerusalem, May 2024, and that the sums are not the total series
    for must in ("Peace Now", "Israeli CBS (Central Bureau of Statistics)", "names no source",
                 "East Jerusalem settlements are not in it", "May 2024", "not the end of 2024",
                 "settlements.settler_population", "only for 2023", "484,340 against 478,600",
                 "2,698 to 14,881", "not a year with no residents", "governorate"):
        assert must in w, must
    for must in ("السلام الآن", "دائرة الإحصاء المركزية الإسرائيلية", "القدس الشرقية", "أيار 2024",
                 "settlements.settler_population", "2023", "484,340", "478,600", "2,698", "14,881",
                 "المحافظة"):
        assert must in w_ar, must
    assert "\n" not in w and "\n" not in w_ar
