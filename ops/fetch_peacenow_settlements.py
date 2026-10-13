"""Fetch Peace Now's population of each West Bank settlement, year by year:
the `Settlements` sheet of the spreadsheet Settlement Watch links from its
Population page.

    .venv/bin/python -m ops.fetch_peacenow_settlements            # weekly at most
    .venv/bin/python -m ops.fetch_peacenow_settlements --force    # now
    .venv/bin/python -m ops.fetch_peacenow_settlements --dry-run [--stage DIR]

WHY (2026-10-13). The store held Peace Now's yearly West Bank total (51 rows,
ops/fetch_peacenow.py) and 199 settlement footprints of 2018 (ops/
fetch_hdx_land.py), and nothing per settlement and year. Peace Now publishes
exactly that, in a spreadsheet beside the chart.

WHAT PEACE NOW PUBLISHES (measured 2026-10-13). The Population page says
"Download the list of settlements and outposts here" and links a Google
spreadsheet. Its xlsx export is served to a plain GET, no login, under the
name "Settlements and Outposts Peace Now 07.2026.xlsx". Three sheets:

  Settlements           152 named rows, 68 columns: 13 that describe the
                        settlement (Name, Name Hebrew, DB_ID, x/y (ITM),
                        x/y (UTM), Year established, Distance from Green Line,
                        Municipality, Urban Pattern, Elevation, Comments) and
                        55 of population: "Population 1969" to "Population
                        2023" with no 1984, then "Population May 2024".
                        THIS SHEET IS WHAT IS READ.
  Outposts              413 rows, 13 columns (name, type, year, point, nearest
                        settlement, district, municipality). No population.
  Outpost Legalization  81 rows, 12 labelled columns of dates and plan numbers.

The other two are described in the raw file's metadata (`sheets_not_taken`)
and not read further. DB_ID is Peace Now's own number for a place: the site's
page for Adora is /en/settlements/settlement3-en and its DB_ID is 3.

A SERIES PER SETTLEMENT. Every record carries `series_key`, "pn" and the DB_ID
in four digits (pn0003; the ids reach 1397, and three digits would not sort),
and the spec makes it the last part of the indicator:
settlements.population_by_settlement.pn0003. The id is the stable part: a name
can change its spelling and the series stays the same series. Each series is
named, in English and Arabic, from db/reference/peacenow_settlement_names.yaml
(ops/build_settlement_names.py). A settlement with a figure and no entry in
that table still loads; it is listed in the raw file (`series_without_a_name`)
and counted in the ledger line (`unnamed`), and so is a settlement whose name
the sheet now spells differently from the table (`series_renamed`).

THE DOOR. The spreadsheet's address is read from the page on every run, and
the document id known on 2026-10-13 is only the fallback for a night the page
shows no link; the raw file and the ledger line say which was used
(`sheet_link`). A redirect to a Google sign-in, an HTML answer or anything that
is not an xlsx is a LoginWall: nothing is written and the line says so. This
fetcher never signs in.

WHAT A CELL IS, decided from the sheet itself:

  a number above 0     a figure. One record, kind `figure`.
  blank                nothing. No record.
  0                    NOT a count of nobody. The sheet writes 0 in every
                       column up to "Population 2007" where it has no figure,
                       and from "Population 2008" on it leaves such a cell
                       blank: not one 0 in the 17 columns from 2008. Of the
                       2,248 zeros, 1,433 stand in years before the sheet's own
                       "Year established", 513 between that year and the
                       settlement's first stated cell (Ovnat, established 1983:
                       0 in every column to 2007, then "100 (estimated)") and
                       302 between two stated cells (Almog: 57 in 1983, 0 for
                       1985 to 1992, 103 in 1993). None follows a settlement's
                       last figure. So no zero is the sheet clearly stating
                       that an existing settlement had no residents. Each is
                       still written here as a record, kind
                       `zero_before_established` or `zero_no_figure`, so the
                       spec's declared drops count them and no reader of the
                       raw file has to trust this paragraph.
  "N (estimated)"      a figure the sheet marks as an estimate (15 cells, all
                       in "Population 2008"). Kind `estimated`, value N,
                       `value_note` "estimated", the cell kept in `cell_text`.
  "כ-50"               Hebrew for "about 50": 261 cells, every one in the
                       columns 1969 to 1979, the same text for 48 settlements
                       (Ma'ale Adumim carries it to 1979 and has 1,700 in 1982;
                       Kiryat Arba to 1974, then "?", then 3,340), in 10 cells
                       for years before the sheet's own year of establishment
                       (Almog, established 1977, from 1969; Elon More). A
                       placeholder, not a count: the 47 of them in "Population
                       1979" come to 2,350 where the chart holds 10,000 for
                       that year. Kind `approximate`, value 50, cell kept; the
                       spec does not load them.
  "?"                  5 cells (Kiryat Arba 1975 to 1979). Kind
                       `unknown_marker`, no value.
  any other text       kind `unreadable`, counted, no value. None today. A
                       number typed as text ("1,234") is read as that number.

WHICH DATE. A column "Population <year>" is that year's figure, written
`<year>-12-31` as ops/fetch_peacenow.py writes the chart's years (the spec
stores it as the year, precision year). The sheet does not say "end of year";
the reading rests on the chart, whose labels are the Israeli CBS end-of-year
counts: the sheet's columns sum to within 0.23 % of the chart's totals for 2005
to 2007 and 2009 to 2021, and to the chart's 503,732 exactly for 2023 (every
comparison is in db/mappings/settlements_by_settlement.yaml). "Population May
2024" is a different thing, a count as of a month: `2024-05-01`, precision
month, never 2024's year-end. A population header this parser cannot date
stops the fetch (SheetChanged); it is never guessed.

WHERE. The sheet's "x (UTM)" and "y (UTM)" columns hold LATITUDE and LONGITUDE
in degrees (32.28517186, 35.0750225 for Avnei Hefetz), not UTM metres, and x
is the latitude. They are the sheet's own Israeli grid point ("x (ITM)",
"y (ITM)") projected on GRS80 with no datum shift: itm_to_latlon() below
reproduces 144 of the 146 rows that carry both to under 0.7 m (the other two,
Shaar Shomron and Sa-Nur, are 43 m and 81 m off). So they sit 31 to 78 m
(median 78 m) from the same grid point shifted to WGS84 (measured with PostGIS,
EPSG:2039 to 4326). For 146 of the 147 points both fall in the same
governorate; the one that differs is Shani, on the Green Line: the sheet's
degrees fall in no governorate, the shifted grid point in Hebron's. The
degrees are used AS THE SHEET WRITES THEM, and the grid point is kept beside
them. Where a row has the grid point and no degrees (Tel Zion), the same
projection gives them and the record says so (`coord_basis`). Five rows have
neither; none of the five has a population figure.

WHAT IS NOT A SETTLEMENT. A row with no Name that carries numbers, a row whose
Name is a total ("Total", "Sum", «סה"כ»), and a named row with no DB_ID are
not settlements: each is dropped by that rule, counted and named in the raw
file's metadata (`rows_dropped`). There is none today.

WHAT IT WRITES. data/raw/peacenow/settlement_population.json: `metadata`
(the publisher's vintage, the door used, every count above, the sheets and
columns not taken), `settlements` (all 152 rows as the sheet describes them,
with or without a figure) and `data` (one record per non-blank population
cell, in the shape db/mappings/settlements_by_settlement.yaml reads).

LICENCE: the site states none; its footer reads "© 2026 Peace Now". Source
row `peace_now`: no licence found, no redistribution.

Posture (ops/fetchlib.py): atomic, floored, ledgered. Two requests on a night
it fetches, with the project's own User-Agent; a held file younger than
MAX_AGE_DAYS is not re-fetched (the population columns move about once a
year).
"""
from __future__ import annotations

import html as htmllib
import io
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

PAGE = "https://peacenow.org.il/en/settlements-watch/settlements-data/population"
KNOWN_SHEET_ID = "1Hs_JdYPEs4oXs09zG3Hd4tWBpYo0ImkJ6WuXAEgMi0U"   # linked on 2026-10-13
EXPORT = "https://docs.google.com/spreadsheets/d/{id}/export?format=xlsx"
VIEW = "https://docs.google.com/spreadsheets/d/{id}"
OUT = fl.ROOT / "data" / "raw" / "peacenow" / "settlement_population.json"
LABEL = "peacenow:settlement_population"
SOURCE_NAME = "Peace Now — Settlements and Outposts list"   # as the spec routes it
SHEET = "Settlements"
INDICATOR_PREFIX = "settlements.population_by_settlement."
NAMES_TABLE = fl.ROOT / "db" / "reference" / "peacenow_settlement_names.yaml"
PARSER = 2                    # raise it when a held file must be read again
                              #   (2: every record carries its series_key)
MAX_AGE_DAYS = 6              # fetched weekly from a nightly job

MAX_EXPORT_BYTES = 20_000_000    # the export is 319,282 bytes on 2026-10-13
MAX_PART_BYTES = 100_000_000     # its largest part unzips to 1,633,869

MIN_SETTLEMENTS = 137         # 0.9 x 152 named rows, 2026-10-13
MIN_FIGURES = 3933            # 0.9 x 4,370 cells the spec loads (4,355 numbers above 0, 15 estimates)

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_M = "{%s}" % NS["m"]

# header label, as the sheet spells it -> the record's key
DESCRIPTIVE = {
    "Name": "settlement_name",
    "Name Hebrew": "settlement_name_he",
    "DB_ID": "settlement_id",
    "x (ITM)": "itm_x",
    "y (ITM)": "itm_y",
    "x (UTM)": "lat",             # degrees of latitude, whatever the label says
    "y (UTM)": "lon",             # degrees of longitude
    "Year established": "year_established",
    "Distance from Green Line (Kilometers)": "distance_from_green_line_km",
    "Municipality": "municipality",
    "Urban Pattern": "urban_pattern",
    "Elevation": "elevation_m",
    "Comments": "comments",
}
MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
_YEAR_COL = re.compile(r"^Population (\d{4})$")
_MONTH_COL = re.compile(r"^Population ([A-Z][a-z]+) (\d{4})$")
_TOTAL_NAME = re.compile(r"^(grand\s+)?(total|sum)\b|^סה\"?כ", re.I)

_PLAIN = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d+$")
_ESTIMATED = re.compile(r"^(\d[\d,]*)\s*\(\s*estimated\s*\)$", re.I)
_APPROX = re.compile(r"^כ\s*-?\s*(\d[\d,]*)$")
_UNKNOWN = re.compile(r"^\?+$")
LOADABLE = ("figure", "estimated")

_LINK = re.compile(
    r'<a\b[^>]*\bhref="(https://docs\.google\.com/spreadsheets/d/'
    r'([A-Za-z0-9_-]{20,})[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_SAID = re.compile(r"Updated: [A-Z][a-z]+ \d{1,2}, \d{4}"
                   r"|Peace Now['’]s count, \d{1,2}/\d{1,2}/\d{2,4}")
_NAME_MONTH = re.compile(r"(?<!\d)(\d{2})\.(\d{4})(?!\d)")


class PageChanged(ValueError):
    """The page links the spreadsheet in a way this was not written against."""


class SheetChanged(ValueError):
    """The workbook no longer has the shape this was written against."""


class LoginWall(Exception):
    """Google or Peace Now asked for a sign-in, a consent or a key."""


# ── the door ─────────────────────────────────────────────────────────────────

def sheet_links(page: str) -> list[tuple[str, str]]:
    """(document id, the link's own words) for every Google spreadsheet the
    page links, in page order."""
    return [(m.group(2), " ".join(htmllib.unescape(_TAG.sub("", m.group(3))).split()))
            for m in _LINK.finditer(page)]


def choose_sheet(links: list[tuple[str, str]]) -> tuple[str, str]:
    """(document id, how it was found). The page is the door; the known id is
    the fallback for a page with no spreadsheet link, and a page that links
    several spreadsheets none of which is named as the list or is the known
    one is refused rather than guessed."""
    named = {i for i, text in links if re.search(r"list of settlements", text, re.I)}
    if len(named) == 1:
        return named.pop(), "page"
    ids = {i for i, _ in links}
    if len(ids) == 1:
        return ids.pop(), "page"
    if not ids:
        return KNOWN_SHEET_ID, "fallback: the page shows no spreadsheet link, the id known on 2026-10-13 was used"
    if KNOWN_SHEET_ID in ids:
        return KNOWN_SHEET_ID, "page (several spreadsheets linked; the id known on 2026-10-13 is one of them)"
    raise PageChanged(f"{len(ids)} spreadsheets linked and none is named as the "
                      "list of settlements")


def page_says(page: str) -> list[str]:
    """The page's own "Updated: ..." and "Peace Now's count, ..." lines, as it
    words them, in order, each once."""
    text = htmllib.unescape(_TAG.sub(" ", _SCRIPT.sub(" ", page)))
    out: list[str] = []
    for m in _SAID.finditer(text):
        if m.group(0) not in out:
            out.append(m.group(0))
    return out


def file_name(disposition: str | None) -> str | None:
    """The name Google serves the export under (Content-Disposition)."""
    d = disposition or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", d, re.I)
    if m:
        return urllib.parse.unquote(m.group(1)).strip() or None
    m = re.search(r'filename="([^"]+)"', d, re.I)
    return m.group(1).strip() if m else None


def check_export(final_url: str, content_type: str | None, body: bytes) -> bytes:
    """The export, or LoginWall. A public sheet answers with a zip; a sheet
    that is not public redirects to accounts.google.com and answers HTML."""
    host = urllib.parse.urlparse(final_url or "").netloc.lower()
    if host.startswith(("accounts.google.", "consent.google.")) or "ServiceLogin" in (final_url or ""):
        raise LoginWall(f"redirected to {host}: the spreadsheet asks for a sign-in")
    if (content_type or "").lower().startswith("text/html") or body[:2] != b"PK":
        raise LoginWall(f"the export answered {content_type or 'no content type'}, "
                        "not an xlsx: a sign-in or consent page")
    if len(body) > MAX_EXPORT_BYTES:
        raise SheetChanged(f"the export is {len(body):,} bytes, over {MAX_EXPORT_BYTES:,}")
    return body


def download(sheet_id: str) -> tuple[bytes, str | None]:
    req = urllib.request.Request(EXPORT.format(id=sheet_id),
                                 headers={"User-Agent": fl.UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            final, ctype = r.geturl(), r.headers.get("Content-Type")
            name = file_name(r.headers.get("Content-Disposition"))
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise LoginWall(f"HTTP {e.code} on the export: the spreadsheet is not public") from e
        raise
    return check_export(final, ctype, body), name


def vintage_of(name: str | None) -> str | None:
    """"Settlements and Outposts Peace Now 07.2026.xlsx" -> "2026-07"."""
    m = _NAME_MONTH.search(name or "")
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{m.group(1)}"
    return None


# ── the workbook (zip + XML, as ops/fetch_insecurity_insight.py reads one) ───

def _col(ref: str) -> int:
    idx = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def workbook(xlsx: bytes) -> dict[str, dict]:
    """Sheet name -> {"rows": [(row number, {column index: value})], "merged":
    [ranges]}, in the workbook's order. A number is a float, text is the text
    with its ends trimmed, a cell with nothing in it is absent."""
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    big = [i.filename for i in z.infolist() if i.file_size > MAX_PART_BYTES]
    if big:
        raise SheetChanged(f"parts of the workbook unzip to over {MAX_PART_BYTES:,} bytes: {big}")
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(_M + "t")))
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out: dict[str, dict] = {}
    for s in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
        target = rels[s.get("{%s}id" % NS["r"])]
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        root = ET.fromstring(z.read(path))
        rows = []
        for r in root.find("m:sheetData", NS):
            vals: dict[int, object] = {}
            for c in r.findall("m:c", NS):
                t, v = c.get("t"), c.find("m:v", NS)
                if t == "s" and v is not None:
                    val: object = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(_M + "t"))
                elif v is None or v.text is None or v.text == "":
                    continue
                elif t in ("str", "e"):
                    val = v.text
                elif t == "b":
                    val = v.text == "1"
                else:
                    try:
                        val = float(v.text)
                    except ValueError:
                        val = v.text
                if isinstance(val, str):
                    val = val.strip()
                    if not val:
                        continue
                vals[_col(c.get("r"))] = val
            rows.append((int(r.get("r")), vals))
        out[s.get("name")] = {
            "rows": rows,
            "merged": [m.get("ref") for m in root.iter(_M + "mergeCell")]}
    return out


def describe(sheet: dict) -> dict:
    """What a sheet that is not read holds: its filled rows and its header."""
    filled = [(n, v) for n, v in sheet["rows"] if v]
    header = filled[0][1] if filled else {}
    return {"rows": max(len(filled) - 1, 0),
            "columns": [str(header[i]) for i in sorted(header)],
            "cells_outside_the_header": sum(
                1 for _, v in filled[1:] for i in v if i not in header)}


# ── the Israeli grid, as the sheet itself turns it into degrees ──────────────
# Israeli Transverse Mercator (EPSG:2039) on GRS80, inverse, NO datum shift:
# that is what the sheet's own degree columns are (see WHERE above).
_A, _F = 6378137.0, 1 / 298.257222101
_K0 = 1.0000067
_LON0 = math.radians(35 + 12 / 60 + 16.261 / 3600)
_LAT0 = math.radians(31 + 44 / 60 + 3.817 / 3600)
_FE, _FN = 219529.584, 626907.39
_E2 = _F * (2 - _F)


def _arc(phi: float) -> float:
    e2 = _E2
    return _A * ((1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * phi
                 - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * phi)
                 + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * phi)
                 - (35 * e2**3 / 3072) * math.sin(6 * phi))


def itm_to_latlon(x: float, y: float) -> tuple[float, float]:
    e2 = _E2
    mu = (_arc(_LAT0) + (y - _FN) / _K0) / (_A * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
          + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
          + (151 * e1**3 / 96) * math.sin(6 * mu) + (1097 * e1**4 / 512) * math.sin(8 * mu))
    ep2 = e2 / (1 - e2)
    c1, t1 = ep2 * math.cos(p1)**2, math.tan(p1)**2
    n1 = _A / math.sqrt(1 - e2 * math.sin(p1)**2)
    r1 = _A * (1 - e2) / (1 - e2 * math.sin(p1)**2)**1.5
    d = (x - _FE) / (n1 * _K0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (
        d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720)
    lon = _LON0 + (d - (1 + 2 * t1 + c1) * d**3 / 6
                   + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120) / math.cos(p1)
    return round(math.degrees(lat), 8), round(math.degrees(lon), 8)


def _in_range(lat, lon) -> bool:
    return (isinstance(lat, float) and isinstance(lon, float)
            and 31.2 <= lat <= 32.6 and 34.8 <= lon <= 35.7)


# ── the Settlements sheet ────────────────────────────────────────────────────

def series_key(settlement_id: int) -> str:
    """The last part of a settlement's indicator: Peace Now's DB_ID in four
    digits, so the keys sort (the ids reach 1397)."""
    return f"pn{int(settlement_id):04d}"


def indicator_of(settlement_id: int) -> str:
    return INDICATOR_PREFIX + series_key(settlement_id)


def _num(v):
    """A cell's number as the sheet states it: 1990.0 is 1990, 4.2 stays 4.2."""
    if isinstance(v, float) and v == v and v.is_integer():
        return int(v)
    return v


def period_of(label: str) -> dict | None:
    """What a population column measures, from its label: a year's figure or a
    month's. None for a label that is not a population column."""
    m = _YEAR_COL.match(label)
    if m:
        y = int(m.group(1))
        return {"period": str(y), "period_kind": "year_end", "year": y,
                "date": f"{y}-12-31"}
    m = _MONTH_COL.match(label)
    if m and m.group(1) in MONTHS:
        y, mo = int(m.group(2)), MONTHS[m.group(1)]
        return {"period": f"{y}-{mo:02d}", "period_kind": "month", "year": y,
                "date": f"{y}-{mo:02d}-01"}
    return None


def established_year(v) -> int | None:
    """The first year in the sheet's "Year established" cell: 1990, "January
    2002" -> 2002, "1984 (as a military ouptost; ...1997)" -> 1984. It only
    sorts a zero into one of the two reasons it is not loaded for."""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
        return int(v)
    m = re.search(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", str(v or ""))
    return int(m.group(1)) if m else None


def read_cell(v, year: int, established: int | None) -> tuple[str, object, str | None]:
    """(kind, value, the cell's text when it is not a plain number)."""
    text = None
    if isinstance(v, bool):
        return "unreadable", None, str(v)
    if isinstance(v, str):
        text = v
        s = v.strip()
        if _PLAIN.match(s):
            v, text = float(s.replace(",", "")), None      # a number typed as text
        else:
            m = _ESTIMATED.match(s)
            if m:
                return "estimated", int(m.group(1).replace(",", "")), text
            m = _APPROX.match(s)
            if m:
                return "approximate", int(m.group(1).replace(",", "")), text
            if _UNKNOWN.match(s):
                return "unknown_marker", None, text
            return "unreadable", None, text
    if not isinstance(v, (int, float)) or v != v or v < 0:
        return "unreadable", None, str(v)
    if v == 0:
        before = established is not None and year < established
        return ("zero_before_established" if before else "zero_no_figure"), 0, text
    return "figure", _num(float(v)), text


def parse_settlements(sheet: dict, fetched_at: str, sheet_url: str = VIEW.format(id=KNOWN_SHEET_ID)
                      ) -> tuple[list[dict], list[dict], dict]:
    """(settlements, records, counts) from the Settlements sheet."""
    filled = [(n, v) for n, v in sheet["rows"] if v]
    if not filled:
        raise SheetChanged(f"the {SHEET} sheet is empty")
    header_row, header = filled[0]
    labels = {i: " ".join(str(x).split()) for i, x in header.items()}
    by_label: dict[str, int] = {}
    for i, lab in labels.items():
        if lab in by_label:
            raise SheetChanged(f"two columns are headed {lab!r}")
        by_label[lab] = i
    for need in ("Name", "DB_ID"):
        if need not in by_label:
            raise SheetChanged(f"no {need!r} column in row {header_row}")
    periods: dict[int, dict] = {}
    not_taken: list[str] = []
    for i in sorted(labels):
        lab = labels[i]
        if lab in DESCRIPTIVE:
            continue
        p = period_of(lab)
        if p:
            periods[i] = {**p, "sheet_column": lab}
        elif lab.lower().startswith("population"):
            raise SheetChanged(f"a population column this parser cannot date: {lab!r}")
        else:
            not_taken.append(lab)
    if not periods:
        raise SheetChanged("no population column")
    if len({p["period"] for p in periods.values()}) != len(periods):
        raise SheetChanged("two population columns state the same period")

    src = {"name": SOURCE_NAME, "organization": "Peace Now", "url": PAGE,
           "sheet_url": sheet_url,
           "license": "no licence stated (© Peace Now)", "fetched_at": fetched_at}
    counts: Counter = Counter()
    dropped: dict[str, list] = {"total_row": [], "row_without_name": [], "row_without_id": []}
    settlements: list[dict] = []
    records: list[dict] = []
    seen: dict = {}
    pop_cols = sorted(periods)
    for n, v in filled[1:]:
        name = v.get(by_label["Name"])
        sid = v.get(by_label["DB_ID"])
        has_numbers = any(i in v for i in pop_cols)
        if not isinstance(name, str):
            if has_numbers or sid is not None:
                dropped["row_without_name"].append(n)
            continue                                   # a stray cell is not a row
        if _TOTAL_NAME.search(name):
            dropped["total_row"].append({"row": n, "name": name})
            continue
        if not (isinstance(sid, float) and sid.is_integer()):
            dropped["row_without_id"].append({"row": n, "name": name})
            continue
        sid = int(sid)
        if sid in seen:
            raise SheetChanged(f"DB_ID {sid} is on rows {seen[sid]} and {n}")
        seen[sid] = n

        desc = {}
        for lab, key in DESCRIPTIVE.items():
            cell = v.get(by_label[lab]) if lab in by_label else None
            if cell is not None:
                desc[key] = _num(cell)
        desc["settlement_id"] = sid
        lat, lon = desc.pop("lat", None), desc.pop("lon", None)
        x, y = desc.pop("itm_x", None), desc.pop("itm_y", None)
        loc: dict = {"name": name}
        if _in_range(lat, lon):
            loc.update(lat=lat, lon=lon)
        elif lat is not None or lon is not None:
            counts["degrees_out_of_range"] += 1
        if x is not None and y is not None:
            loc.update(itm_x=x, itm_y=y)
            if "lat" not in loc:
                la, lo = itm_to_latlon(float(x), float(y))
                if _in_range(la, lo):
                    loc.update(lat=la, lon=lo, coord_basis=(
                        "computed from the sheet's ITM grid point the way the "
                        "sheet computes its own degree columns (GRS80, no datum "
                        "shift); the sheet gives no degrees for this row"))
                    counts["degrees_from_grid"] += 1
        counts["settlements_with_a_point" if "lat" in loc else "settlements_without_a_point"] += 1

        est = established_year(desc.get("year_established"))
        kinds: Counter = Counter()
        for i in pop_cols:
            p = periods[i]
            if i not in v:
                counts["cell:blank"] += 1
                continue
            kind, value, text = read_cell(v[i], p["year"], est)
            counts[f"cell:{kind}"] += 1
            kinds[kind] += 1
            rec = {"stable_id": f"peacenow-settlement-pop:{sid}:{p['period']}",
                   "series_key": series_key(sid),
                   "date": p["date"], "period": p["period"],
                   "period_kind": p["period_kind"],
                   "sheet_column": p["sheet_column"], "cell_kind": kind,
                   "value": value, "unit": "persons"}
            if p["period_kind"] == "year_end":
                rec["year"] = p["year"]        # a month's figure is no year's
            if kind == "estimated":
                rec["value_note"] = "estimated"
            if text is not None:
                rec["cell_text"] = text
            rec.update(desc)
            rec["location"] = loc
            rec["sources"] = [src]
            records.append(rec)
        loadable = sum(kinds[k] for k in LOADABLE)
        counts["settlements"] += 1
        counts["settlements_with_a_figure" if loadable else "settlements_without_a_figure"] += 1
        settlements.append({**desc, "series_key": series_key(sid),
                            "location": loc, "sheet_row": n,
                            "figures": loadable, "cells": dict(kinds)})
    info = {"counts": dict(counts), "rows_dropped": dropped,
            "columns_taken": [labels[i] for i in sorted(labels)
                              if labels[i] in DESCRIPTIVE or i in periods],
            "columns_not_taken": not_taken,
            "population_columns": [periods[i]["sheet_column"] for i in pop_cols],
            "periods": [periods[i]["period"] for i in pop_cols],
            "merged_cells": len(sheet.get("merged") or [])}
    return settlements, records, info


def named_series(table: Path | None = None) -> dict[int, str] | None:
    """DB_ID -> the name the series was given under, from the reviewed table.
    None when the table is not there to read (it never stops a fetch)."""
    try:
        import yaml
        doc = yaml.safe_load((table or NAMES_TABLE).read_text(encoding="utf-8"))
        return {int(e["id"]): str(e["name"]) for e in doc["settlements"]}
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return None


def unnamed_and_renamed(settlements: list[dict], named: dict[int, str] | None
                        ) -> tuple[list[dict], list[dict]]:
    """Settlements with a figure that the table does not name, and those it
    names under a spelling the sheet no longer uses."""
    if named is None:
        return [], []
    with_figure = [s for s in settlements if s["figures"]]
    unnamed = [{"id": s["settlement_id"], "name": s["settlement_name"],
                "indicator": indicator_of(s["settlement_id"])}
               for s in with_figure if s["settlement_id"] not in named]
    renamed = [{"id": s["settlement_id"], "sheet": s["settlement_name"],
                "table": named[s["settlement_id"]]}
               for s in with_figure if s["settlement_id"] in named
               and named[s["settlement_id"]] != s["settlement_name"]]
    return unnamed, renamed


def column_sums(records: list[dict]) -> dict[str, int]:
    """period -> the sum of the cells the spec loads (figures and estimates)."""
    out: Counter = Counter()
    for r in records:
        if r["cell_kind"] in LOADABLE:
            out[r["period"]] += r["value"]
    return dict(sorted(out.items()))


def document(xlsx: bytes, name: str | None, door: str, sheet_id: str,
             link_text: str | None, said: list[str], fetched_at: str) -> dict:
    """The raw file, from the export's bytes."""
    wb = workbook(xlsx)
    if SHEET not in wb:
        raise SheetChanged(f"no sheet named {SHEET!r}; the workbook holds {list(wb)}")
    settlements, records, info = parse_settlements(
        wb[SHEET], fetched_at, VIEW.format(id=sheet_id))
    c = info["counts"]
    figures = sum(c.get(f"cell:{k}", 0) for k in LOADABLE)
    year_ends = [r["period"] for r in records
                 if r["period_kind"] == "year_end" and r["cell_kind"] in LOADABLE]
    through = max((r["date"][:7] for r in records if r["cell_kind"] in LOADABLE), default=None)
    vint = vintage_of(name)
    basis = (f"the month in the name Google serves the export under: \"{name}\" "
             "(Content-Disposition)" if vint else
             f"the export's name carries no month ({name!r}); the newest "
             "population column is used instead")
    if said:
        basis += "; the page says: " + " / ".join(said)
    basis += (f"; the population columns run from \"{info['population_columns'][0]}\" "
              f"to \"{info['population_columns'][-1]}\"")
    unnamed, renamed = unnamed_and_renamed(settlements, named_series())
    return {"metadata": {
        "fetched_at": fetched_at, "parser": PARSER,
        "source": "Peace Now — Settlement Watch, the list of settlements and outposts",
        "source_url": PAGE, "sheet_url": VIEW.format(id=sheet_id),
        "export_url": EXPORT.format(id=sheet_id), "sheet_id": sheet_id,
        "sheet_link": door, "sheet_link_text": link_text,
        "file_name": name,
        "vintage": vint or through, "vintage_basis": basis, "vintage_url": PAGE,
        "page_says": said,
        "sheet": SHEET,
        "settlements": c.get("settlements", 0),
        "settlements_with_a_figure": c.get("settlements_with_a_figure", 0),
        "settlements_with_a_point": c.get("settlements_with_a_point", 0),
        "figures": figures, "records": len(records),
        "series": c.get("settlements_with_a_figure", 0),
        "indicator_prefix": INDICATOR_PREFIX,
        "series_without_a_name": unnamed,
        "series_renamed": renamed,
        "cells": {k[5:]: v for k, v in sorted(c.items()) if k.startswith("cell:")},
        "first_period": min((r["period"] for r in records if r["cell_kind"] in LOADABLE), default=None),
        "last_year_end": max(year_ends, default=None),
        "data_through": through,
        "column_sums": column_sums(records),
        "rows_dropped": info["rows_dropped"],
        "columns_taken": info["columns_taken"],
        "columns_not_taken": info["columns_not_taken"],
        "population_columns": info["population_columns"],
        "merged_cells": info["merged_cells"],
        "sheets_not_taken": {n: describe(s) for n, s in wb.items() if n != SHEET},
        "coordinates": "the sheet's \"x (UTM)\" and \"y (UTM)\" columns are latitude "
                       "and longitude in degrees: its ITM grid point on GRS80, no "
                       "datum shift",
        "coverage": "West Bank settlements; no East Jerusalem settlement is listed",
        "license": "no licence stated; footer \"© Peace Now\" (no-license-found)",
        "attribution": "Population by settlement: Peace Now (Settlement Watch), "
                       "peacenow.org.il, list of settlements and outposts."},
        "settlements": settlements,
        "data": records}


def _fresh(path: Path, days: float = MAX_AGE_DAYS) -> bool:
    try:
        if time.time() - path.stat().st_mtime >= days * 86400:
            return False
        return json.loads(path.read_text(encoding="utf-8"))["metadata"]["parser"] == PARSER
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    if not dry and "--force" not in argv and _fresh(OUT):
        print(f"  {LABEL}: held copy is younger than {MAX_AGE_DAYS} days, not re-fetched")
        return 0
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        try:
            page = fl.get(PAGE, timeout=60).decode("utf-8", "replace")
            links, said = sheet_links(page), page_says(page)
            sheet_id, door = choose_sheet(links)
        except PageChanged:
            raise
        except Exception as e:                               # noqa: BLE001
            # the page did not answer: the known id is still a door, and the
            # line says it was the one used
            links, said = [], []
            sheet_id, door = KNOWN_SHEET_ID, (
                f"fallback: the page could not be read ({type(e).__name__}), "
                "the id known on 2026-10-13 was used")
        xlsx, name = download(sheet_id)
        link_text = next((t for i, t in links if i == sheet_id), None)
        doc = document(xlsx, name, door, sheet_id, link_text, said, fetched_at)
    except LoginWall as e:
        print(f"  STOP {LABEL}: {e}. Nothing is written and nothing is signed into.")
        if not dry:
            fl.event(LABEL, "error", error=f"LoginWall: {e}"[:200])
        return 1
    except Exception as e:                                   # noqa: BLE001
        print(f"  FAIL {LABEL}: {type(e).__name__}: {e}")
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:200])
        return 1
    meta = doc["metadata"]
    for n, floor, what in ((meta["settlements"], MIN_SETTLEMENTS, "settlements"),
                           (meta["figures"], MIN_FIGURES, "figures")):
        if n < floor:
            print(f"  REFUSED {LABEL}: {n} {what} below the floor of {floor}; "
                  "keeping the file already on disk")
            if not dry:
                fl.event(LABEL, "refused", rows=n, floor=floor, what=what)
            return 1
    print(f"  ok   {LABEL}  {meta['settlements']} settlements, {meta['figures']} "
          f"figures in {len(meta['population_columns'])} columns "
          f"({meta['first_period']} to {meta['data_through']}), {meta['records']} "
          f"cells read; vintage {meta['vintage']}; sheet found: {door.split(':')[0]}")
    for what, rows in (("has a figure and no name in", meta["series_without_a_name"]),
                       ("is spelt differently in the sheet than in", meta["series_renamed"])):
        for r in rows:
            print(f"         {r.get('name') or r.get('sheet')} (DB_ID {r['id']}) {what} "
                  f"db/reference/{NAMES_TABLE.name}")
    moved = sheet_id != KNOWN_SHEET_ID
    if moved:
        print(f"         the page now links another document ({sheet_id}), not the "
              f"one known on 2026-10-13 ({KNOWN_SHEET_ID}); it was read because the "
              "page is the door and it passed every check")
    if dry:
        print(f"         would write {OUT.name} and 1 bronze payload under "
              "peace_now  (dry run, nothing written)")
        fl.stage(fl.stage_dir(argv), OUT.name, doc)
        return 0
    from ingest import bronze
    meta["bronze"] = bronze.put("peace_now", xlsx, "xlsx",
                                url=EXPORT.format(id=sheet_id)).ref
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=meta["records"], figures=meta["figures"],
             settlements=meta["settlements"], series=meta["series"],
             data_through=meta["data_through"],
             vintage=meta["vintage"], sheet_link=door.split(":")[0],
             **({"unnamed": len(meta["series_without_a_name"])}
                if meta["series_without_a_name"] else {}),
             **({"renamed": len(meta["series_renamed"])}
                if meta["series_renamed"] else {}),
             **({"sheet_id": sheet_id} if moved else {}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
