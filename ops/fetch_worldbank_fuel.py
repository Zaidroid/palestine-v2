"""The World Bank's Global Fuel Prices Database: the West Bank's official fuel
prices, monthly 2016-12 → 2025-04, as the Bank compiled them from Palestinian
news announcements (ODbL).

    .venv/bin/python -m ops.fetch_worldbank_fuel              # fetch if changed + load
    .venv/bin/python -m ops.fetch_worldbank_fuel --dry-run    # fetch, print, write nothing
    .venv/bin/python -m ops.fetch_worldbank_fuel --file X.xlsx --dry-run   # parse a local copy

WHY (2026-10-19). The archive cannot confirm the fuel caps before 2026 under
the two-outlet rule (migration 071): the old articles are single transcriptions
that rarely name the authority. The Bank did the same transcription for its
database — "Official Prices … collected from local news articles", the article
links in the workbook's comment boxes — one institution, monthly, December
2016 to April 2025. Cross-checked against WAFA's announcement for October 2020:
Bank 5.32 / 4.79 / 58 (petrol 95, diesel, 12 kg) = WAFA 5.32 / 4.79 / 58. So the
rows ride on the fuel.price.official.* indicators under their own dataset
(worldbank_gfpd_fuel, migration 129) with the Bank's licence on every row.

THE WORKBOOK. One sheet per fuel, a header row of month dates (Excel serials),
one row per economy; the West Bank rows are labelled "West Bank & Gaza (…)" —
the label says Gaza, the Bank's method sheet says West Bank, and Gaza has no
official consumer price, so the rows are loaded on the West Bank place. Read
with the standard library (zip + XML), as every xlsx reader in ops/ is; the
sheet is found by its NAME through workbook.xml, not by position. Downloaded
only when the server says it changed (ETag / Last-Modified), ~5.6 MB.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                       # noqa: E402

URL = "https://datacatalogfiles.worldbank.org/ddh-published/0066829/DR0095290/Global_Fuel_Prices_Database.xlsx"
PAGE = "https://datacatalog.worldbank.org/search/dataset/0066829/global-fuel-prices-database"
CACHE = fl.ROOT / "data" / "cache" / "worldbank_gfpd"
BOOK, META = CACHE / "Global_Fuel_Prices_Database.xlsx", CACHE / "meta.json"
OUT = fl.ROOT / "data" / "raw" / "worldbank_gfpd" / "west_bank_fuel.json"
DATASET, PLACE, READER = "worldbank_gfpd_fuel", 2, "fetch_worldbank_fuel@1"
LABEL = "worldbank:gfpd_fuel"
MIN_ROWS = 600                      # 7 products × ~100 months = 697 on 2026-10-19

SHEETS = ["Premium Gasoline RON95 or above", "Diesel", "LPG", "Kerosene"]
ROW_PREFIX = "West Bank & Gaza ("
PRODUCTS = {"Gasoline Unleaded 95": "gasoline_95", "Gasoline Unleaded 98": "gasoline_98",
            "Diesel": "diesel", "Kerosene": "kerosene",
            "LPG 12kg": "lpg_12kg", "LPG 48kg": "lpg_48kg", "LPG 5kg": "lpg_5kg"}
UNITS = {"liter": "ILS/L", "litre": "ILS/L", "cylinder": "ILS/cylinder"}
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_REF = re.compile(r"^([A-Z]+)(\d+)$")

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


# ── pure: the workbook ────────────────────────────────────────────────────────

def product_for_label(label: str) -> str | None:
    """'West Bank & Gaza (LPG 12kg)' → 'lpg_12kg'; anything else → None."""
    if not label.startswith(ROW_PREFIX) or not label.endswith(")"):
        return None
    return PRODUCTS.get(label[len(ROW_PREFIX):-1].strip())


def unit_for(printed: str) -> str | None:
    """'Sheker/Liter', 'Sheker/Cylinder' (sic) → the unit the fuel rows carry."""
    tail = printed.lower().rsplit("/", 1)[-1].strip()
    return UNITS.get(tail)


def serial_month(serial: float) -> str | None:
    """An Excel date serial (1900 system) → 'YYYY-MM'. The Bank's header is a
    month label, mostly the 1st; eight months of 2018-12 → 2019-07 are dated the
    3rd, so any day in the first week is the month, later days are not a label."""
    d = date(1899, 12, 30) + timedelta(days=int(serial))
    return f"{d.year:04d}-{d.month:02d}" if d.day <= 7 else None


def _col(ref: str) -> str:
    m = _REF.match(ref)
    return m.group(1) if m else ""


def sheets_by_name(z: zipfile.ZipFile) -> dict[str, str]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    out = {}
    for s in wb.find("m:sheets", _NS):
        t = target[s.get(f"{{{_NS['r']}}}id")]
        out[s.get("name")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
    return out


def parse_workbook(blob: bytes) -> list[dict]:
    """Every West Bank (product, month, value) in the four fuel sheets."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    names = sheets_by_name(z)
    out = []
    for sheet in SHEETS:
        if sheet not in names:
            raise ValueError(f"sheet {sheet!r} is no longer in the workbook: {sorted(names)[:8]}…")
        rows = list(ET.fromstring(z.read(names[sheet])).iter(f"{{{_NS['m']}}}row"))
        if not rows:
            continue

        def cells(row):
            for c in row.findall("m:c", _NS):
                v = c.find("m:v", _NS)
                if v is None or v.text is None:
                    continue
                yield _col(c.get("r", "")), (shared[int(v.text)] if c.get("t") == "s" else v.text)

        months = {}
        for col, val in cells(rows[0]):
            try:
                mo = serial_month(float(val))
            except ValueError:
                mo = None
            if mo:
                if mo in months.values():
                    raise ValueError(f"{sheet}: month {mo} appears twice in the header")
                months[col] = mo
        for row in rows[1:]:
            got = dict(cells(row))
            label = got.get("A", "")
            product = product_for_label(label)
            if product is None:
                continue
            unit = unit_for(got.get("B", ""))
            if unit is None:
                raise ValueError(f"{sheet}: unit not understood for {label!r}: {got.get('B')!r}")
            for col, mo in months.items():
                raw = got.get(col)
                if raw in (None, ""):
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    continue
                out.append({"product": product, "period": mo, "value": value, "unit": unit,
                            "sheet": sheet, "row_label": label})
    return out


# ── fetch, cached on the server's own change signals ──────────────────────────

def fetch_if_changed() -> tuple[bytes, dict]:
    meta = json.loads(META.read_text()) if META.exists() else {}
    headers = {"User-Agent": fl.UA}
    if BOOK.exists() and meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if BOOK.exists() and meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]
    req = urllib.request.Request(URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            blob = r.read()
            new = {"etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified"),
                   "fetched_at": datetime.now(timezone.utc).isoformat(), "bytes": len(blob)}
    except urllib.error.HTTPError as e:
        if e.code == 304 and BOOK.exists():
            return BOOK.read_bytes(), {**meta, "not_modified": True}
        raise
    return blob, new


def observations(rows: list[dict], reported: str) -> list[dict]:
    out = []
    for r in rows:
        occurred = datetime(int(r["period"][:4]), int(r["period"][5:7]), 1, tzinfo=timezone.utc)
        out.append({"place_id": PLACE, "indicator": f"fuel.price.official.{r['product']}",
                    "value": r["value"], "unit": r["unit"], "occurred": occurred, "reported": reported,
                    "raw_ref": URL,
                    "attrs": json.dumps({"compiler": "World Bank Global Fuel Prices Database",
                                         "method": "official prices collected from local news articles (the Bank's method sheet)",
                                         "sheet": r["sheet"], "row_label": r["row_label"],
                                         "authority": "Palestinian General Petroleum Corporation",
                                         "reader": READER, "page": PAGE}, ensure_ascii=False),
                    "identity": f"worldbank_gfpd|{r['product']}|{r['period']}",
                    "stable": f"{DATASET}:{r['product']}:{r['period']}"})
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--file", help="parse this local workbook instead of fetching")
    a = ap.parse_args(argv)
    try:
        if a.file:
            blob, meta = Path(a.file).read_bytes(), {"fetched_at": datetime.now(timezone.utc).isoformat(), "file": a.file}
        else:
            blob, meta = fetch_if_changed()
        rows = parse_workbook(blob)
        fl.check_floor(LABEL, len(rows), MIN_ROWS)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}")
        return 1
    except Exception as e:                                             # noqa: BLE001
        if not a.dry_run:
            fl.event(LABEL, "error", error=type(e).__name__)
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}")
        return 1
    months = sorted({r["period"] for r in rows})
    by = {}
    for r in rows:
        by.setdefault(r["product"], []).append(r["period"])
    print(f"  ok   {LABEL}  {len(rows)} rows, {months[0]} → {months[-1]}, "
          + ", ".join(f"{p} {len(v)}" for p, v in sorted(by.items())))
    if a.dry_run:
        for r in rows:
            if r["period"] in ("2020-10", months[-1]) and r["product"] in ("gasoline_95", "diesel", "lpg_12kg"):
                print(f"         {r['period']} {r['product']:12} {r['value']} {r['unit']}")
        print("         (dry run — nothing written)")
        return 0
    if not a.file:
        CACHE.mkdir(parents=True, exist_ok=True)
        if not meta.get("not_modified"):
            BOOK.write_bytes(blob)
            META.write_text(json.dumps(meta))
    reported = meta.get("last_modified") or meta.get("fetched_at")
    try:
        reported_at = datetime.strptime(reported, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        reported_at = meta.get("fetched_at")
    fl.write_atomic(OUT, {"fetched_at": meta.get("fetched_at"), "source": URL, "page": PAGE,
                          "licence": "ODbL-1.0", "rows": rows})
    fl.event(LABEL, "ok", rows=len(rows), data_through=months[-1])
    from resolve.db import connect                                     # noqa: E402
    with connect() as conn:
        row = conn.execute("SELECT dataset_id FROM dataset WHERE key = %s", (DATASET,)).fetchone()
        if not row:
            raise SystemExit(f"dataset {DATASET} missing: apply migration 129")
        obs = observations(rows, reported_at)
        for o in obs:
            conn.execute(UPSERT, {**o, "dataset_id": row[0]})
        conn.commit()
    print(f"  loaded {len(obs)} observations into {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
