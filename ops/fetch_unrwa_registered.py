"""Registered Palestine refugees, by UNRWA field, sex and age — UNRWA's own HDX release (P1-B.4).

    .venv/bin/python -m ops.fetch_unrwa_registered

WHY
The refugees category held UNRWA camp populations and a flattened v1 table whose
rows no longer say which field they count (its "West Bank" row reads 414,298;
UNRWA's own 2025 Q4 release says 938,589). UNRWA publishes the registered
population per field every quarter on HDX ("UNRWA Palestine Refugees",
cc-by-igo): Jordan, Lebanon, Syria, the West Bank, Gaza, "Unknown", and the
total, each by sex and seven age groups.

WHAT IS KEPT
Every row of the latest quarter's sheet, as written. The sheet holds ONE quarter;
earlier quarters stay in the databank because the identity carries the date.

POSTURE (ops/fetchlib.py): atomic, floored (6 fields), ledgered. The workbook is
read with the standard library (an .xlsx is zipped XML) — no new dependency on
the serving host.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import FetchRefused, check_floor, event, write_atomic  # noqa: E402

PACKAGE = "https://data.humdata.org/api/3/action/package_show?id=unrwa-palestine-refugees"
PAGE = "https://data.humdata.org/dataset/unrwa-palestine-refugees"
OUT = ROOT / "data" / "raw" / "unrwa_registered" / "latest.json"
LABEL = "unrwa:registered"
UA = "palestine-v2 databank (+https://live-api.zaidlab.xyz)"
FLOOR = 6                    # Jordan, Lebanon, Syria, West Bank, Gaza, Total
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sheet_rows(xlsx: bytes) -> list[list[str]]:
    """The first sheet's rows as strings, shared strings resolved."""
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    out = []
    for r in root.find("m:sheetData", NS):
        vals = []
        for c in r.findall("m:c", NS):
            v = c.find("m:v", NS)
            vals.append("" if v is None else
                        (shared[int(v.text)] if c.get("t") == "s" else v.text))
        out.append(vals)
    return out


def records(rows: list[list[str]]) -> list[dict]:
    header, body = rows[0], rows[1:]
    out = []
    for vals in body:
        rec = dict(zip(header, vals))
        if not rec.get("UNRWA_Field") or not rec.get("Grand Total"):
            continue
        try:
            counts = {k: int(float(v)) for k, v in rec.items()
                      if k not in ("Year", "Quarter", "Country_ISOalpha3", "Country",
                                   "UNRWA_Field") and v not in ("", None)}
        except ValueError:
            continue
        out.append({"year": int(rec["Year"]), "quarter": rec["Quarter"],
                    "field": rec["UNRWA_Field"], "country": rec.get("Country"),
                    "iso3": rec.get("Country_ISOalpha3"), "counts": counts})
    return out


def main(argv: list[str]) -> int:
    try:
        pkg = json.loads(_get(PACKAGE))["result"]
        res = next(r for r in pkg["resources"]
                   if (r.get("format") or "").lower() in ("xlsx", "xls"))
        recs = records(sheet_rows(_get(res["url"])))
        check_floor(LABEL, len(recs), FLOOR)
    except FetchRefused as e:
        print(e, file=sys.stderr)
        return 1
    except Exception as e:                                  # noqa: BLE001
        event(LABEL, "error", error=str(e)[:300])
        print(f"{LABEL}: {e}", file=sys.stderr)
        return 1
    write_atomic(OUT, {"fetched_at": datetime.now(timezone.utc).isoformat(),
                       "source": "UNRWA — Palestine Refugees (HDX)", "url": PAGE,
                       "resource": res.get("name"), "license": pkg.get("license_id"),
                       "data": recs})
    event(LABEL, "ok", rows=len(recs), resource=res.get("name"))
    print(f"{LABEL}: {len(recs)} field rows ({res.get('name')}) → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
