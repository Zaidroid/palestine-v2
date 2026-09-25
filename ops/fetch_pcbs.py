"""Fetch PCBS's own figures — the v1 supply line `pcbs-indicators`, dead since
2026-08-26, taken over by v2 (P1-B.3, 2026-09-25).

WHAT THIS FEEDS. Dataset v1_economic_pcbs_direct (source `pcbs_direct`,
CC-BY-4.0): the Palestinian Central Bureau of Statistics' OWN numbers, split
West Bank / Gaza Strip / East Jerusalem / Palestine — not the World Bank
series the `pcbs` category carries under PCBS's name. Two of its three
indicators have a living source again; the third does not:

  economic.pcbs_population  the "Projected Population in the Palestine"
                            workbook linked from the PCBS home page
                            (2017 → 2026 by region; also by governorate,
                            which this fetch does not read yet)
  economic.pcbs_cpi         the CPI dashboard's yearly table (base 2018,
                            1996 → last full year, four regions)
  economic.pcbs_poverty_rate  NO machine-readable source found on the rebuilt
                            site (2026-09-25): the 2 rows held stay held and
                            are not refreshed. Said here so nobody mistakes
                            their age for a fetch failure.

Measured 2026-09-25 against what the databank holds: every held population
row (30) and every held CPI row (84, 2005–2025) is reproduced to the digit;
the CPI table adds 1996–2004 (36 rows the old page never showed).

WHY v1's STEP DIED. Two things at once. The page it rendered
(statisticsIndicatorsTables.aspx?table_id=585) no longer exists — PCBS moved
to a new site and the old URL redirects to the home page. And the headless
browser it needed left v1's image. Neither door is needed now: the workbook
is a plain file and the CPI dashboard (a Plotly Dash app) answers its own
callback over plain HTTP — the same POST the page makes when you pick
"yearly" and "all".

THE CERTIFICATE. www.pcbs.gov.ps serves its leaf certificate with the WRONG
intermediate (GlobalSign GCC R3 DV 2020, where the leaf is signed by GCC R46
DV 2025). Browsers repair that by fetching the right intermediate from the
certificate's AIA URL; Python and curl do not, and fail verification. The
right intermediate is pinned in ops/certs/ and ADDED to the system trust
store for these requests — verification stays on, it just has the missing
link. (Fingerprint and expiry in ops/certs/README.md; it expires 2029-06-23.)

A REBASE IS REFUSED, NOT ABSORBED. Every CPI level depends on its base year.
If the dashboard's base is no longer 2018 the fetch refuses: loading a
rebased index over the held one would "revise" 120 numbers that were never
wrong.

Run: .venv/bin/python -m ops.fetch_pcbs
     .venv/bin/python -m ops.fetch_pcbs --dry-run
"""
from __future__ import annotations

import io
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

BASE = "https://www.pcbs.gov.ps"
HOME = f"{BASE}/?lang=en"
POPULATION_FALLBACK = f"{BASE}/media/f4np1lnh/projected-population-in-the-palestine.xlsx"
DASH = f"{BASE}/CPIDashBoard"
INTERMEDIATE = fl.ROOT / "ops" / "certs" / "globalsign-gcc-r46-dv-tls-ca-2025.pem"
RAW = fl.ROOT / "data" / "raw" / "pcbs"
OUT = RAW / "indicators.json"

SOURCE = {"name": "Palestinian Central Bureau of Statistics (PCBS)",
          "url": BASE, "license": "verify-required"}
# PCBS's labels → the region vocabulary the loader's region rules know.
REGIONS = {"West Bank": "West Bank", "Gaza Strip": "Gaza Strip",
           "Palestine": "Palestine", "Jerusalem J1": "East Jerusalem"}
CPI_BASE_YEAR = 2018

# Floors, ~0.9 of 2026-09-25: population 10 years × 3 regions = 30;
# CPI 30 years × 4 regions = 120.
MIN_POPULATION, MIN_CPI = 27, 100


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=INTERMEDIATE.read_text())
    return ctx


def _get(url: str, data: bytes | None = None, timeout: int = 90) -> bytes:
    headers = {"User-Agent": fl.UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
        return r.read()


# ── population: the workbook ─────────────────────────────────────────────────

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def xlsx_rows(blob: bytes, sheet: str = "xl/worksheets/sheet1.xml") -> list[list[str]]:
    """The cells of one sheet as rows of strings — stdlib only (zip + XML);
    the venv carries no spreadsheet library and one sheet does not need one."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    out = []
    for r in ET.fromstring(z.read(sheet)).iter(f"{{{_NS['m']}}}row"):
        cells = {}
        for c in r.findall("m:c", _NS):
            ref = re.match(r"[A-Z]+", c.get("r", "")).group(0)
            col = 0
            for ch in ref:
                col = col * 26 + ord(ch) - 64
            v, t = c.find("m:v", _NS), c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
            elif v is None:
                continue
            else:
                val = shared[int(v.text)] if t == "s" else v.text
            cells[col - 1] = (val or "").strip()
        if cells:
            out.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return out


def parse_population(rows: list[list[str]]) -> list[dict]:
    """[year, region, persons] from the workbook's layout: a header row naming
    'Year', a second header row naming the regions, then one row per year.
    The region columns are FOUND by name, never assumed by position."""
    hdr = next((i for i, r in enumerate(rows) if "Year" in r), None)
    if hdr is None or hdr + 1 >= len(rows):
        raise ValueError("no 'Year' header in the population workbook")
    year_col = rows[hdr].index("Year")
    names = rows[hdr + 1]
    cols = {REGIONS[n]: i for i, n in enumerate(names) if n in REGIONS}
    if set(cols) != {"West Bank", "Gaza Strip", "Palestine"}:
        raise ValueError(f"population workbook regions changed: {names[:10]}")
    out = []
    for r in rows[hdr + 2:]:
        y = r[year_col] if year_col < len(r) else ""
        if not re.fullmatch(r"(19|20)\d\d", y):
            continue
        for region, i in cols.items():
            try:
                n = float(r[i])
            except (IndexError, ValueError):
                continue
            out.append({"year": int(y), "region": region, "value": n})
    return out


def population_url(home_html: str) -> str:
    m = re.search(r'href="(/media/[^"]*projected-population[^"]*\.xlsx)"', home_html)
    return BASE + m.group(1) if m else POPULATION_FALLBACK


# ── CPI: the dashboard's own callback ────────────────────────────────────────

def _find_props(node, ids: set, out: dict) -> dict:
    if isinstance(node, dict):
        p = node.get("props")
        if isinstance(p, dict) and p.get("id") in ids:
            out[p["id"]] = p
        for v in node.values():
            _find_props(v, ids, out)
    elif isinstance(node, list):
        for v in node:
            _find_props(v, ids, out)
    return out


def cpi_request(layout: dict, deps: list) -> dict:
    """The POST the dashboard makes for its yearly table — built from the
    app's OWN declared callback, so a renamed input fails loudly here."""
    dep = next((d for d in deps if "overall_table.data" in d.get("output", "")), None)
    if dep is None:
        raise ValueError("the CPI dashboard no longer declares overall_table")
    props = _find_props(layout, {"regions", "overall_base_year"}, {})
    regions = [o["value"] for o in (props.get("regions") or {}).get("options", [])]
    unknown = set(regions) - set(REGIONS)
    if not regions or unknown:
        raise ValueError(f"CPI dashboard regions changed: {regions}")
    bases = [o["value"] for o in (props.get("overall_base_year") or {}).get("options", [])]
    if CPI_BASE_YEAR not in bases:
        raise ValueError(f"base year {CPI_BASE_YEAR} no longer offered: {bases}")
    values = {"time_window": "all", "frequency": "yearly", "regions": regions,
              "date_range_month": None, "date_range_year": None,
              "overall_view": ["index"], "overall_base_year": CPI_BASE_YEAR,
              "lang_store": "en"}
    inputs = []
    for i in dep["inputs"]:
        if i["id"] not in values:
            raise ValueError(f"the CPI callback wants an input we do not know: {i['id']}")
        inputs.append({"id": i["id"], "property": i["property"], "value": values[i["id"]]})
    outputs = [{"id": o.split(".")[0], "property": o.split(".")[1]}
               for o in dep["output"].strip(".").split("...")]
    return {"output": dep["output"], "outputs": outputs, "inputs": inputs,
            "changedPropIds": ["time_window.value"], "state": []}


def parse_cpi(answer: dict) -> list[dict]:
    table = (answer.get("response") or {}).get("overall_table") or {}
    out = []
    for row in table.get("data") or []:
        if str(row.get("Frequency", "")).lower() != "yearly":
            continue
        base = row.get("Base Year")
        if base is not None and int(base) != CPI_BASE_YEAR:
            raise ValueError(f"CPI rebased: base {base}, expected {CPI_BASE_YEAR}")
        period, region = str(row.get("Period", "")), row.get("Region")
        value = row.get("CPI (Index)")
        if not re.fullmatch(r"(19|20)\d\d", period) or region not in REGIONS \
                or value is None:
            continue
        out.append({"year": int(period), "region": REGIONS[region],
                    "value": float(value)})
    return out


# ── records, in the shape t_economic reads ───────────────────────────────────

CODES = {"pcbs_population": ("Population", "persons"),
         "pcbs_cpi": ("Consumer Price Index", "index")}


def records(population: list[dict], cpi: list[dict], fetched_at: str) -> list[dict]:
    src = dict(SOURCE, fetched_at=fetched_at)
    out = []
    for code, rows in (("pcbs_population", population), ("pcbs_cpi", cpi)):
        name, unit = CODES[code]
        for r in rows:
            out.append({
                "stable_id": f"pcbs:{code}:{r['region'].lower().replace(' ', '-')}:{r['year']}",
                "indicator_code": code, "indicator_name": name,
                "date": f"{r['year']}-12-31",
                "location": {"name": r["region"], "region": r["region"]},
                "metrics": {"value": r["value"], "unit": unit},
                "sources": [src]})
    return out


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    fetched_at = datetime.now(timezone.utc).isoformat()
    ok, raws, got = True, [], {}
    # population
    try:
        home = _get(HOME).decode("utf-8", "replace")
        url = population_url(home)
        blob = _get(url)
        pop = parse_population(xlsx_rows(blob))
        if len(pop) < MIN_POPULATION:
            raise fl.FetchRefused(f"{len(pop)} population rows < {MIN_POPULATION}")
        raws.append(("population", blob, "xlsx", url))
        got["pcbs_population"] = pop
        yrs = sorted({r["year"] for r in pop})
        print(f"  ok   pcbs:population  {len(pop)} rows, {yrs[0]}–{yrs[-1]} ({url})")
        if not dry:
            fl.event("pcbs:population", "ok", rows=len(pop), data_through=str(yrs[-1]))
    except fl.FetchRefused as e:
        ok = False
        print(f"  REFUSED pcbs:population: {e}")
        if not dry:
            fl.event("pcbs:population", "refused", why=str(e)[:200])
    except (urllib.error.URLError, OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
        ok = False
        print(f"  FAIL pcbs:population: {type(e).__name__}: {str(e)[:200]}")
        if not dry:
            fl.event("pcbs:population", "error", error=type(e).__name__)
    # CPI
    try:
        layout = json.loads(_get(f"{DASH}/_dash-layout"))
        deps = json.loads(_get(f"{DASH}/_dash-dependencies"))
        body = json.dumps(cpi_request(layout, deps)).encode()
        blob = _get(f"{DASH}/_dash-update-component", data=body)
        cpi = parse_cpi(json.loads(blob))
        if len(cpi) < MIN_CPI:
            raise fl.FetchRefused(f"{len(cpi)} CPI rows < {MIN_CPI}")
        raws.append(("cpi", blob, "json", f"{DASH}/_dash-update-component"))
        got["pcbs_cpi"] = cpi
        yrs = sorted({r["year"] for r in cpi})
        print(f"  ok   pcbs:cpi         {len(cpi)} rows, {yrs[0]}–{yrs[-1]}, base {CPI_BASE_YEAR}")
        if not dry:
            fl.event("pcbs:cpi", "ok", rows=len(cpi), data_through=str(yrs[-1]))
    except fl.FetchRefused as e:
        ok = False
        print(f"  REFUSED pcbs:cpi: {e}")
        if not dry:
            fl.event("pcbs:cpi", "refused", why=str(e)[:200])
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        ok = False
        print(f"  FAIL pcbs:cpi: {type(e).__name__}: {str(e)[:200]}")
        if not dry:
            fl.event("pcbs:cpi", "error", error=type(e).__name__)

    if not got:
        return 1
    # A half-fetched night must not truncate the other half: an indicator
    # that failed tonight keeps yesterday's rows in the file.
    if len(got) < len(CODES) and OUT.exists():
        prev = json.loads(OUT.read_text())
        for code in CODES:
            if code not in got:
                got[code] = [{"year": int(r["date"][:4]), "region": r["location"]["region"],
                              "value": r["metrics"]["value"]}
                             for r in prev.get("data", []) if r.get("indicator_code") == code]
                print(f"         {code}: kept yesterday's {len(got[code])} rows")
    recs = records(got.get("pcbs_population", []), got.get("pcbs_cpi", []), fetched_at)
    doc = {"metadata": {
        "fetched_at": fetched_at, "source": SOURCE["name"], "source_url": BASE,
        "license": "CC-BY-4.0 (PCBS terms of use, read 2026-08-05)",
        "attribution": "Official statistics: Palestinian Central Bureau of "
                       "Statistics (pcbs.gov.ps).",
        "cpi_base_year": CPI_BASE_YEAR,
        "not_refreshed": {"pcbs_poverty_rate": "no machine-readable source on "
                          "the rebuilt PCBS site (2026-09-25)"}},
        "data": recs}
    if dry:
        print(f"         would write {OUT.relative_to(fl.ROOT)} ({len(recs)} records) "
              f"and {len(raws)} bronze payloads under pcbs_direct  (dry run, nothing written)")
        fl.stage(fl.stage_dir(argv), "indicators.json", doc)
        return 0 if ok else 1
    from ingest import bronze
    doc["metadata"]["bronze"] = [bronze.put("pcbs_direct", blob, ext, url=url).ref
                                 for _, blob, ext, url in raws]
    fl.write_atomic(OUT, doc)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
