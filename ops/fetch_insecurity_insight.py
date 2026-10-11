"""Insecurity Insight's Palestine incident data, straight from HDX (CC BY-SA):
eighteen xlsx workbooks — attacks on health care (and the SHCC yearly files),
explosive weapons, aid workers, education, food and water systems, protection,
sexual violence — one row per incident with weapon, perpetrator and victims.

    .venv/bin/python -m ops.fetch_insecurity_insight            # HDX, then v1's file if HDX fails
    .venv/bin/python -m ops.fetch_insecurity_insight --from-v1  # v1's normalised file only

WHY (2026-10-11)
The fragments decision brought these incidents into the databank in the
morning (db/mappings/insecurity_insight.yaml) by reading the file v1's parser
writes nightly. This is the direct supply line, so the dataset no longer
depends on v1 staying alive. It reproduces v1's normalisation exactly — the
same canonical fields, the same victim roll-up, and the same incident_id (an
md5 over category, date, coordinates, perpetrator, location, description and
SiND id) — so every event the databank already holds keeps its stable id and
a re-fetch re-matches instead of re-loading.

WHAT IS KEPT
Every row with a readable date, from every xlsx resource in the package, in
the package's own resource order; a row whose incident_id was already seen in
an earlier resource is dropped (v1's rule: one incident can appear in two
sub-datasets). Category comes from the file name. Everything the sheet says
rides in `details`, as before. The HDX package's licence is stamped beside the
data. Floored at 15,000 rows; a short download leaves yesterday's file.

The xlsx is read with the standard library (zip + XML), as ops/fetch_unrwa_registered.py
reads UNRWA's, so no new dependency lands on the serving host.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import FetchRefused, check_floor, event, get, get_json, write_atomic  # noqa: E402
from resolve.db import v1_path  # noqa: E402

PACKAGE_SLUG = "opt-violent-and-threatening-incidents-against-healthcare"
PACKAGE = f"https://data.humdata.org/api/3/action/package_show?id={PACKAGE_SLUG}"
PAGE = f"https://data.humdata.org/dataset/{PACKAGE_SLUG}"
OUT = ROOT / "data" / "raw" / "insecurity_insight" / "incidents.json"
LABEL = "insecurity_insight:incidents"
FLOOR = 15000                 # 20,836 on 2026-10-11; the file only grows
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# v1's file-name → category table, first match wins (scripts/sources/insecurity-insight.js)
CATEGORY_BY_NAME = (
    (re.compile(r"aid[- ]?worker[- ]?kika", re.I), "aid_worker"),
    (re.compile(r"attacks[- ]?on[- ]?health[- ]?care", re.I), "healthcare"),
    (re.compile(r"shcc[- ]?health[- ]?care", re.I), "healthcare"),
    (re.compile(r"conflict[- ]?related[- ]?sexual[- ]?violence|crsv", re.I), "sexual_violence"),
    (re.compile(r"education[- ]?in[- ]?danger", re.I), "education"),
    (re.compile(r"explosive[- ]?weapons", re.I), "explosive_weapons"),
    (re.compile(r"protection[- ]?in[- ]?danger", re.I), "protection"),
    (re.compile(r"food[- ]?systems", re.I), "food_systems"),
    (re.compile(r"water[- ]?systems", re.I), "water_systems"),
    (re.compile(r"overview", re.I), "overview"),
)
VICTIM_FIELDS = {
    "killed": re.compile(r"(workers?[\s_]killed|health[\s_]worker[\s_]killed|fatalities|deaths|killed( in captivity)?$)", re.I),
    "injured": re.compile(r"(workers?[\s_]injured|health[\s_]worker[\s_]injured|injuries|wounded)", re.I),
    "kidnapped": re.compile(r"(workers?[\s_]kidnapped|health[\s_]worker[\s_]kidnapped|abducted)", re.I),
    "arrested": re.compile(r"(workers?[\s_]arrested|health[\s_]worker[\s_]arrested|detained)", re.I),
    "threatened": re.compile(r"(workers?[\s_]threatened|threats)", re.I),
    "assaulted": re.compile(r"(workers?[\s_]assaulted|health[\s_]worker[\s_]assaulted|assault(ed)?$)", re.I),
}
_EXCEL_EPOCH = date(1899, 12, 30)


def category_for(name: str) -> str:
    for rx, cat in CATEGORY_BY_NAME:
        if rx.search(name):
            return cat
    return "other"


def sheet_rows(xlsx: bytes) -> list[list]:
    """The first sheet, cell values typed as the xlsx types them: numbers as
    float, strings as str, empty as None — what v1's XLSX reader gave it."""
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    sheet = next(n for n in sorted(z.namelist()) if n.startswith("xl/worksheets/sheet"))
    root = ET.fromstring(z.read(sheet))
    out: list[list] = []
    for r in root.find("m:sheetData", NS):
        vals: list = []
        for c in r.findall("m:c", NS):
            col = re.match(r"[A-Z]+", c.get("r") or "")
            idx = 0
            if col:
                for ch in col.group(0):
                    idx = idx * 26 + (ord(ch) - 64)
                idx -= 1
            while len(vals) < idx:
                vals.append(None)                    # a skipped (empty) cell keeps its column
            t = c.get("t")
            v = c.find("m:v", NS)
            if t == "s" and v is not None:
                vals.append(shared[int(v.text)])
            elif t == "inlineStr":
                vals.append("".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t")))
            elif t == "str" and v is not None:
                vals.append(v.text)
            elif v is None or v.text is None or v.text == "":
                vals.append(None)
            elif t == "b":
                vals.append(v.text == "1")
            else:
                try:
                    vals.append(float(v.text))
                except ValueError:
                    vals.append(v.text)
        out.append(vals)
    return out


def js_str(v) -> str:
    """How v1's JavaScript stringified a cell inside the id key: a number
    prints as JS prints it (32, not 32.0; otherwise the shortest round-trip),
    an empty or zero value prints as '' (JS `|| ''`)."""
    if v is None or v == "" or v == 0 or v is False:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e21 else repr(v)
    return str(v)


def to_iso(v) -> str | None:
    if isinstance(v, float):
        if v < 10000 or v > 200000:
            return None
        return (_EXCEL_EPOCH + timedelta(days=int(v // 1))).isoformat() if v == v else None
    if isinstance(v, str):
        if v.startswith("#"):
            return None
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
        if m:
            return f"{m[1]}-{m[2]}-{m[3]}"
        m = re.match(r"^(\d{4})-(\d{2})$", v)
        if m:
            return f"{m[1]}-{m[2]}-15"
        m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", v)
        if m:
            return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    return None


_LEADING_NUMBER = re.compile(r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)")


def num(v):
    """JS parseFloat: the leading number of a cell, so '2 (one critical)' is 2
    — what v1 summed; 89 SHCC rows differed until this matched it."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _LEADING_NUMBER.match(str(v).replace(",", ""))
    return float(m.group(0)) if m else None


def pick(row: dict, *keys):
    for k in keys:
        v = row.get(k)
        if v is not None and v != "":
            return v
    return None


def rollup_victims(row: dict) -> dict:
    out = {}
    for bucket, rx in VICTIM_FIELDS.items():
        total, any_ = 0.0, False
        for k, v in row.items():
            if not k or not rx.search(k):
                continue
            n = num(v)
            if n is None:
                continue
            total += n
            any_ = True
        out[bucket] = (int(total) if total.is_integer() else total) if any_ else None
    return out


def incident_id(category: str, row: dict, date_iso: str | None) -> str:
    desc = row.get("Event Description")
    key = "|".join([category, date_iso or "", js_str(row.get("Latitude")), js_str(row.get("Longitude")),
                    js_str(row.get("Reported Perpetrator Name")), js_str(row.get("Location of Incident")),
                    (str(desc)[:80] if desc not in (None, "") else ""), js_str(row.get("SiND Event ID"))])
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def normalise(row: dict, category: str, source_url: str, source_dataset: str) -> dict | None:
    date_iso = to_iso(pick(row, "Date", "Incident date", "incident date", "Event Date"))
    if not date_iso:
        return None
    lat, lon = num(pick(row, "Latitude", "latitude")), num(pick(row, "Longitude", "longitude"))
    return {
        "incident_id": incident_id(category, row, date_iso),
        "date": date_iso,
        "category": category,
        "country_iso": pick(row, "Country ISO", "Country") or "PSE",
        "admin1": pick(row, "Admin 1", "admin 1", "Province"),
        "latitude": lat, "longitude": lon,
        "geo_precision": pick(row, "Geo Precision", "geo precision"),
        "location_type": pick(row, "Location of Incident", "Location"),
        "perpetrator_type": pick(row, "Reported Perpetrator", "Perpetrator", "Perpetrator "),
        "perpetrator_name": pick(row, "Reported Perpetrator Name", "Name of perpetrator", "Name of perpetrator "),
        "weapon": pick(row, "Weapon Carried/Used", "Weapons use", "Weapon"),
        "event_description": pick(row, "Event Description", "Description", "Incident description"),
        "organisation_affected": pick(row, "Organisation Affected", "Organization Affected", "Org affected"),
        "victims": rollup_victims(row),
        "source_dataset": source_dataset,
        "source_url": source_url,
        "details": {k: (int(v) if isinstance(v, float) and v.is_integer() and abs(v) < 1e15 else v)
                    for k, v in row.items() if k},
    }


def _sheetjs_headers(cells: list) -> list[str]:
    """Header names as SheetJS gave them to v1: a repeated name gets _1, _2 …
    The 2022 SHCC file has "Health Workers Injured" twice, and v1 summed both
    columns; reading them into one key kept only the last and 94 roll-ups
    differed."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for h in cells:
        name = str(h) if h is not None else ""
        if name in seen:
            seen[name] += 1
            out.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            out.append(name)
    return out


def from_hdx() -> tuple[list[dict], dict]:
    pkg = get_json(PACKAGE, timeout=60).get("result", {})
    resources = [r for r in pkg.get("resources") or [] if "xlsx" in (r.get("format") or "").lower()]
    if not resources:
        raise FetchRefused(f"{LABEL}: the HDX package lists no xlsx resource")
    seen: set[str] = set()
    incidents: list[dict] = []
    files = []
    for res in resources:
        name = res.get("name") or res["url"].rsplit("/", 1)[-1]
        category = category_for(name)
        rows = sheet_rows(get(res["url"], timeout=180))
        if not rows:
            files.append({"file": name, "rows": 0})
            continue
        header = _sheetjs_headers(rows[0])
        kept = dup = 0
        for vals in rows[1:]:
            row = dict(zip(header, vals + [None] * (len(header) - len(vals))))
            inc = normalise(row, category, res["url"], name)
            if inc is None:
                continue
            if inc["incident_id"] in seen:
                dup += 1
                continue
            seen.add(inc["incident_id"])
            incidents.append(inc)
            kept += 1
        files.append({"file": name, "category": category, "rows": len(rows) - 1, "kept": kept, "duplicates": dup})
    incidents.sort(key=lambda i: i["date"], reverse=True)
    stamp = {"source": "Insecurity Insight — State of Palestine incident data (HDX, direct)", "url": PAGE,
             "licence": {"license_id": pkg.get("license_id"), "license_title": pkg.get("license_title"),
                         "hdx_updated": pkg.get("last_modified") or pkg.get("metadata_modified"),
                         "caveats": pkg.get("caveats")},
             "files": files}
    return incidents, stamp


def from_v1() -> tuple[list[dict], dict]:
    src = Path(v1_path("public/data/insecurity-insight/incidents.json"))
    if not src.exists():
        raise FetchRefused(f"{LABEL}: v1's normalised file is absent at V1_ROOT")
    rows = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise FetchRefused(f"{LABEL}: v1's file is not a list")
    return rows, {"source": "Insecurity Insight — State of Palestine incident data (HDX)", "url": PAGE,
                  "read_from": "v1 public/data/insecurity-insight/incidents.json (fallback)"}


def main(argv: list[str]) -> int:
    only_v1 = "--from-v1" in argv
    try:
        try:
            rows, stamp = from_v1() if only_v1 else from_hdx()
        except Exception as e:                              # noqa: BLE001
            if only_v1:
                raise
            event(LABEL, "error", error=f"hdx: {str(e)[:200]}; falling back to v1's file")
            print(f"{LABEL}: HDX read failed ({str(e)[:120]}); reading v1's file instead", file=sys.stderr)
            rows, stamp = from_v1()
        bad = sum(1 for r in rows if not isinstance(r, dict)
                  or any(not r.get(k) for k in ("incident_id", "date", "category")))
        if bad:
            raise FetchRefused(f"{LABEL}: {bad} rows lack incident_id/date/category")
        check_floor(LABEL, len(rows), FLOOR)
    except FetchRefused as e:
        print(e, file=sys.stderr)
        return 1
    except Exception as e:                                  # noqa: BLE001
        event(LABEL, "error", error=str(e)[:300])
        print(f"{LABEL}: {e}", file=sys.stderr)
        return 1
    write_atomic(OUT, {"fetched_at": datetime.now(timezone.utc).isoformat(), **stamp, "data": rows})
    event(LABEL, "ok", rows=len(rows), via="v1" if "read_from" in stamp else "hdx")
    print(f"{LABEL}: {len(rows)} incidents → {OUT.relative_to(ROOT)}"
          + (" (from v1's file)" if "read_from" in stamp else " (HDX, direct)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
