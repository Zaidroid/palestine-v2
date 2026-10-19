"""PCBS's CPI dashboard, monthly: the Consumer Price Index by region (1996 →)
and the average consumer price of six fuel items by region (2019 →).

    .venv/bin/python -m ops.fetch_pcbs_monthly              # fetch + load (nightly)
    .venv/bin/python -m ops.fetch_pcbs_monthly --dry-run    # fetch, print, write nothing
    .venv/bin/python -m ops.fetch_pcbs_monthly --offline    # load the raw files already on disk

WHY (2026-10-19). Zaid asked for an official source for the fuel price history
and for CPI by region. Both sit behind the same Plotly Dash callback that
ops/fetch_pcbs.py already uses for the yearly CPI: the "Overall CPI" tab with
frequency=monthly answers 1996-01 → the latest month for Palestine, the West
Bank, the Gaza Strip and Jerusalem J1 (index, base 2018 = 100, and PCBS's own
month-on-month change); the "Commodity Prices" tab answers the monthly average
price of each surveyed item, among them petrol 95/98, diesel, kerosene, heating
diesel and the 12 kg cylinder delivered to the home, from 2019-01.

WHAT THE FUEL NUMBER IS. A survey average, not the announced maximum. For the
liquid fuels the two coincide in a month the cap holds (Dec 2014: diesel 6.18
both sides; Sep 2026: diesel 8.39 both sides) because the cap is the price at
every station, and the average blends two caps when one changes mid-month
(Sep 2026 petrol 95: 8.15 then 7.65 from the 7th, average 7.78); the cylinder
is priced delivered, 2–3 ILS above the cap. So the fuel rows go under
their own concept, fuel.price.average (migration 129), never mixed into
fuel.price.official.*.

The posture is fetchlib's: a floor below which nothing is written, a ledger
line per attempt, and loads idempotent on (dataset, stable id, month). The raw
answers are kept under data/raw/pcbs/ so --offline can reload them without the
network (the idempotency test uses that).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                       # noqa: E402
from ops.fetch_pcbs import (_find_props, _get, cpi_request, DASH,   # noqa: E402
                            CPI_BASE_YEAR)

RAW = fl.ROOT / "data" / "raw" / "pcbs"
OUT_CPI = RAW / "cpi_monthly.json"
OUT_FUEL = RAW / "fuel_monthly.json"
DASHBOARD = "https://pcbs.gov.ps/cpiDashboard/en"
READER = "fetch_pcbs_monthly@1"

DS_CPI, DS_FUEL = "pcbs_cpi_monthly", "pcbs_fuel_monthly"
# The dashboard's region labels → (place_id, the region word the loader's rules know)
PLACES = {"West Bank": (2, "West Bank"), "Gaza Strip": (1, "Gaza Strip"),
          "Jerusalem J1": (11, "East Jerusalem"), "Palestine": (None, "Palestine")}
# PCBS item code → (indicator suffix, unit as the fuel rows already carry it)
FUEL_ITEMS = {"072200102": ("gasoline_95", "ILS/L"), "072200103": ("gasoline_98", "ILS/L"),
              "072200104": ("diesel", "ILS/L"), "045300201": ("kerosene", "ILS/L"),
              "045300101": ("heating_diesel", "ILS/L"),
              "045200101": ("lpg_12kg_delivered", "ILS/cylinder")}
# Floors, ~0.9 of 2026-10-19: CPI 369 months × 4 regions = 1,476; fuel 93 months × 6 items × 4 regions = 2,232.
MIN_CPI_ROWS, MIN_FUEL_ROWS = 1300, 1800
PERIOD = re.compile(r"^(19|20)\d\d-(0[1-9]|1[0-2])$")

UPSERT = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num, unit,
                         occurred_at, occurred_precision, reported_at, raw_ref,
                         attrs, identity_key, v1_stable_id)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value)s, %(unit)s,
        %(occurred)s, 'month', %(reported)s, %(raw_ref)s, %(attrs)s::jsonb,
        %(identity)s, %(stable)s)
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE (v1_stable_id IS NOT NULL AND upper(sys_period) IS NULL)
DO UPDATE SET value_num = EXCLUDED.value_num,
              unit = EXCLUDED.unit,
              reported_at = EXCLUDED.reported_at,
              raw_ref = EXCLUDED.raw_ref,
              attrs = EXCLUDED.attrs
"""


# ── the two callbacks ─────────────────────────────────────────────────────────

def overall_monthly_request(layout: dict, deps: list) -> dict:
    """The yearly request fetch_pcbs builds, with frequency=monthly."""
    req = cpi_request(layout, deps)
    for i in req["inputs"]:
        if i["id"] == "frequency":
            i["value"] = "monthly"
    req["changedPropIds"] = ["frequency.value"]
    return req


def parse_overall(answer: dict) -> list[dict]:
    table = (answer.get("response") or {}).get("overall_table") or {}
    out = []
    for row in table.get("data") or []:
        if str(row.get("Frequency", "")).lower() != "monthly":
            continue
        base = row.get("Base Year")
        if base is not None and int(base) != CPI_BASE_YEAR:
            raise ValueError(f"CPI rebased: base {base}, expected {CPI_BASE_YEAR}")
        period, region = str(row.get("Period", "")), row.get("Region")
        value = row.get("CPI (Index)")
        if not PERIOD.match(period) or region not in PLACES or value is None:
            continue
        change = row.get("Percent Change (%)")
        out.append({"period": period, "region": region, "index": float(value),
                    "change": None if change is None else float(change)})
    return out


def fuel_request(layout: dict, deps: list) -> dict:
    """The POST the Commodity Prices tab makes, built from the app's own
    declared callback so a renamed input fails loudly here."""
    dep = next((d for d in deps if "commodity_table.data" in d.get("output", "")), None)
    if dep is None:
        raise ValueError("the CPI dashboard no longer declares commodity_table")
    props = _find_props(layout, {"regions", "commodity_view"}, {})
    regions = [o["value"] for o in (props.get("regions") or {}).get("options", [])]
    unknown = set(regions) - set(PLACES)
    if not regions or unknown:
        raise ValueError(f"CPI dashboard regions changed: {regions}")
    values = {"time_window": "all", "frequency": "monthly", "regions": regions,
              "date_range_month": [None, None], "date_range_year": [None, None],
              "commodity_category": None, "commodity_item": None,
              "commodity_search_items": sorted(FUEL_ITEMS),
              "commodity_view": ["index", "pct_change"], "lang_store": "en"}
    inputs = []
    for i in dep["inputs"]:
        if i["id"] not in values:
            raise ValueError(f"the commodity callback wants an input we do not know: {i['id']}")
        inputs.append({"id": i["id"], "property": i["property"], "value": values[i["id"]]})
    outputs = [{"id": o.split(".")[0], "property": o.split(".")[1]}
               for o in dep["output"].strip(".").split("...")]
    return {"output": dep["output"], "outputs": outputs, "inputs": inputs,
            "changedPropIds": ["commodity_search_items.value"], "state": []}


def parse_fuel(answer: dict) -> list[dict]:
    table = (answer.get("response") or {}).get("commodity_table") or {}
    out = []
    for row in table.get("data") or []:
        if str(row.get("Frequency", "")).lower() != "monthly":
            continue
        period, region, code = str(row.get("Period", "")), row.get("Region"), str(row.get("Item Code", ""))
        value = row.get("Average Price")
        if not PERIOD.match(period) or region not in PLACES or code not in FUEL_ITEMS or value is None:
            continue
        change = row.get("Percent Change (%)")
        out.append({"period": period, "region": region, "item_code": code,
                    "item": row.get("Item"), "unit_printed": row.get("Unit"),
                    "price": float(value), "change": None if change is None else float(change)})
    return out


# ── the load ──────────────────────────────────────────────────────────────────

def _occurred(period: str) -> datetime:
    return datetime(int(period[:4]), int(period[5:7]), 1, tzinfo=timezone.utc)


def cpi_observations(rows: list[dict], reported: str) -> list[dict]:
    out = []
    for r in rows:
        place_id, region = PLACES[r["region"]]
        slug = region.lower().replace(" ", "-")
        base_attrs = {"region": region, "region_printed": r["region"], "base_year": CPI_BASE_YEAR,
                      "reader": READER, "dashboard": DASHBOARD}
        out.append({"place_id": place_id, "indicator": "economic.pcbs_cpi_monthly",
                    "value": r["index"], "unit": "index", "occurred": _occurred(r["period"]),
                    "reported": reported, "raw_ref": f"{DASH}/_dash-update-component",
                    "attrs": json.dumps(base_attrs, ensure_ascii=False),
                    "identity": f"pcbs_cpi_monthly|{slug}|{r['period']}|index",
                    "stable": f"{DS_CPI}:index:{slug}:{r['period']}"})
        if r["change"] is not None:
            out.append({"place_id": place_id, "indicator": "economic.pcbs_cpi_monthly_change",
                        "value": r["change"], "unit": "percent", "occurred": _occurred(r["period"]),
                        "reported": reported, "raw_ref": f"{DASH}/_dash-update-component",
                        "attrs": json.dumps(base_attrs, ensure_ascii=False),
                        "identity": f"pcbs_cpi_monthly|{slug}|{r['period']}|change",
                        "stable": f"{DS_CPI}:change:{slug}:{r['period']}"})
    return out


def fuel_observations(rows: list[dict], reported: str) -> list[dict]:
    out = []
    for r in rows:
        place_id, region = PLACES[r["region"]]
        slug = region.lower().replace(" ", "-")
        product, unit = FUEL_ITEMS[r["item_code"]]
        attrs = {"region": region, "region_printed": r["region"], "item_code": r["item_code"],
                 "item_printed": r["item"], "unit_printed": r["unit_printed"],
                 "change_pct_mom": r["change"], "reader": READER, "dashboard": DASHBOARD}
        out.append({"place_id": place_id, "indicator": f"fuel.price.average.{product}",
                    "value": r["price"], "unit": unit, "occurred": _occurred(r["period"]),
                    "reported": reported, "raw_ref": f"{DASH}/_dash-update-component",
                    "attrs": json.dumps(attrs, ensure_ascii=False),
                    "identity": f"pcbs_fuel_monthly|{product}|{slug}|{r['period']}",
                    "stable": f"{DS_FUEL}:{product}:{slug}:{r['period']}"})
    return out


def load(conn, dataset_key: str, observations: list[dict]) -> int:
    row = conn.execute("SELECT dataset_id FROM dataset WHERE key = %s", (dataset_key,)).fetchone()
    if not row:
        raise SystemExit(f"dataset {dataset_key} missing: apply migration 129")
    for o in observations:
        conn.execute(UPSERT, {**o, "dataset_id": row[0]})
    return len(observations)


# ── the run ───────────────────────────────────────────────────────────────────

def fetch(dry: bool) -> tuple[list[dict], list[dict], str]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    layout = json.loads(_get(f"{DASH}/_dash-layout"))
    deps = json.loads(_get(f"{DASH}/_dash-dependencies"))
    cpi = parse_overall(json.loads(_get(f"{DASH}/_dash-update-component",
                                        data=json.dumps(overall_monthly_request(layout, deps)).encode())))
    fl.check_floor("pcbs:cpi_monthly", len(cpi), MIN_CPI_ROWS)
    fuel = parse_fuel(json.loads(_get(f"{DASH}/_dash-update-component",
                                      data=json.dumps(fuel_request(layout, deps)).encode())))
    fl.check_floor("pcbs:fuel_monthly", len(fuel), MIN_FUEL_ROWS)
    if not dry:
        fl.write_atomic(OUT_CPI, {"fetched_at": fetched_at, "source": DASHBOARD, "base_year": CPI_BASE_YEAR, "rows": cpi})
        fl.write_atomic(OUT_FUEL, {"fetched_at": fetched_at, "source": DASHBOARD, "items": FUEL_ITEMS, "rows": fuel})
        fl.event("pcbs:cpi_monthly", "ok", rows=len(cpi), data_through=max(r["period"] for r in cpi))
        fl.event("pcbs:fuel_monthly", "ok", rows=len(fuel), data_through=max(r["period"] for r in fuel))
    return cpi, fuel, fetched_at


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fetch and print; write nothing")
    ap.add_argument("--offline", action="store_true", help="load data/raw/pcbs/*_monthly.json, no network")
    a = ap.parse_args(argv)
    try:
        if a.offline:
            cdoc, fdoc = json.loads(OUT_CPI.read_text()), json.loads(OUT_FUEL.read_text())
            cpi, fuel, fetched_at = cdoc["rows"], fdoc["rows"], cdoc["fetched_at"]
        else:
            cpi, fuel, fetched_at = fetch(a.dry_run)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}")
        return 1
    except Exception as e:                                             # noqa: BLE001
        if not a.dry_run and not a.offline:
            fl.event("pcbs:cpi_monthly", "error", error=type(e).__name__)
        print(f"  FAIL pcbs:monthly: {type(e).__name__}: {str(e)[:200]}")
        return 1
    months = sorted({r["period"] for r in cpi})
    print(f"  ok   pcbs:cpi_monthly   {len(cpi)} rows, {months[0]} → {months[-1]}, base {CPI_BASE_YEAR}")
    fm = sorted({r["period"] for r in fuel})
    print(f"  ok   pcbs:fuel_monthly  {len(fuel)} rows, {fm[0]} → {fm[-1]}, {len({r['item_code'] for r in fuel})} items")
    if a.dry_run:
        for r in [x for x in cpi if x["period"] == months[-1]]:
            print(f"         cpi {r['period']} {r['region']:13} index {r['index']:>8}  change {r['change']}")
        for r in [x for x in fuel if x["period"] == fm[-1] and x["region"] == "West Bank"]:
            print(f"         fuel {r['period']} West Bank {FUEL_ITEMS[r['item_code']][0]:20} {r['price']}")
        print("         (dry run — nothing written)")
        return 0
    from resolve.db import connect                                     # noqa: E402
    with connect() as conn:
        n1 = load(conn, DS_CPI, cpi_observations(cpi, fetched_at))
        n2 = load(conn, DS_FUEL, fuel_observations(fuel, fetched_at))
        conn.commit()
    print(f"  loaded {n1} observations into {DS_CPI}, {n2} into {DS_FUEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
