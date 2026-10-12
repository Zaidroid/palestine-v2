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
same canonical fields and the same victim roll-up.

THE ID (2026-10-12)
It no longer reproduces v1's incident_id. That id was meant to end in the
publisher's event number and missed it under three of its four spellings, so
it merged different incidents and split identical ones (the measurement is on
legacy_incident_id below). An incident is now identified by the publisher's
own event number within its category, and by its whole row where a file gives
no number. The events held under the old ids are moved to the new ones by
ops/rekey_insecurity_insight.py, which reads the id map written beside the
data; it runs once, before the first load from this file.

WHAT IS KEPT
Every row with a readable date, from every xlsx resource in the package, in
the package's own resource order; a row whose incident_id was already seen in
an earlier resource is dropped (one incident appears in the thematic file and
again in the yearly ones). Category comes from the file name. Everything the sheet says
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

from ops.fetchlib import (FetchRefused, check_floor, event, get, get_json,  # noqa: E402
                          stage, stage_dir, write_atomic)
from resolve.db import v1_path  # noqa: E402

PACKAGE_SLUG = "opt-violent-and-threatening-incidents-against-healthcare"
PACKAGE = f"https://data.humdata.org/api/3/action/package_show?id={PACKAGE_SLUG}"
PAGE = f"https://data.humdata.org/dataset/{PACKAGE_SLUG}"
OUT = ROOT / "data" / "raw" / "insecurity_insight" / "incidents.json"
# legacy id -> [new id, file rank], for ops/rekey_insecurity_insight.py
ID_MAP = OUT.with_name("id_map.json")
LABEL = "insecurity_insight:incidents"
FLOOR = 20000                 # 24,305 on 2026-10-12; the file only grows
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


def legacy_incident_id(category: str, row: dict, date_iso: str | None) -> str:
    """v1's id, kept only to find the events already held under it.

    It was meant to end in the publisher's event number and read the column
    "SiND Event ID". Seven of the files spell it "Sind Event ID", "SIND Event
    ID" or "Event ID", and the Protection file has no such column, so for those
    the id was built from date, coordinates, perpetrator, place type and 80
    characters of description: fields that are EMPTY on most Protection rows.
    Measured 2026-10-12 on the publisher's files: 9,627 incidents with their
    own content were dropped as repeats of another (6,189 of Protection's 7,400),
    while the same health-care incident, present in the thematic file and in
    the yearly SHCC files with a differently worded description, was kept under
    each (4,965 distinct health-care incidents held as 7,903)."""
    desc = row.get("Event Description")
    key = "|".join([category, date_iso or "", js_str(row.get("Latitude")), js_str(row.get("Longitude")),
                    js_str(row.get("Reported Perpetrator Name")), js_str(row.get("Location of Incident")),
                    (str(desc)[:80] if desc not in (None, "") else ""), js_str(row.get("SiND Event ID"))])
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


# The publisher's own event number, under every spelling its files use. One
# numbering runs through all the files (measured: wherever two files share a
# number, the dates agree on 99.6% of them), and no file repeats one.
ID_COLUMNS = ("SiND Event ID", "Sind Event ID", "SIND Event ID", "Event ID")


def publisher_id(row: dict) -> str | None:
    for k in ID_COLUMNS:
        v = row.get(k)
        if v not in (None, ""):
            return js_str(v)
    return None


def incident_id(category: str, row: dict, date_iso: str | None = None) -> str:
    """One id per incident per category: the publisher's event number where the
    file gives one, and otherwise everything the row says (no file repeats a
    whole row). The category stays in it because one incident is deliberately
    held under each theme it is filed in."""
    pid = publisher_id(row)
    if pid:
        key = f"{category}|sind|{pid}"
    else:
        key = category + "|row|" + json.dumps(
            {k: js_str(v) for k, v in sorted(row.items()) if k and v not in (None, "")},
            ensure_ascii=False, sort_keys=True)
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


_MONTH_ONLY = re.compile(r"^(\d{4})-(\d{2})$")


def date_of(v) -> tuple[str | None, str]:
    """(date, precision). The 2019 and 2020 SHCC files give a month ("2019-01");
    it was stored as the 15th and called a day."""
    if isinstance(v, str) and _MONTH_ONLY.match(v):
        return v + "-01", "month"
    return to_iso(v), "day"


def normalise(row: dict, category: str, source_url: str, source_dataset: str) -> dict | None:
    stated = pick(row, "Date", "Incident date", "incident date", "Event Date")
    date_iso, precision = date_of(stated)
    if not date_iso:
        return None
    lat, lon = num(pick(row, "Latitude", "latitude")), num(pick(row, "Longitude", "longitude"))
    return {
        "incident_id": incident_id(category, row, date_iso),
        # the id (and the mid-month date) the events held before 2026-10-12 carry
        "incident_id_legacy": legacy_incident_id(category, row, to_iso(stated)),
        "publisher_event_id": publisher_id(row),
        "date": date_iso,
        "date_precision": precision,
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


def from_hdx() -> tuple[list[dict], dict, dict]:
    pkg = get_json(PACKAGE, timeout=60).get("result", {})
    resources = [r for r in pkg.get("resources") or [] if "xlsx" in (r.get("format") or "").lower()]
    if not resources:
        raise FetchRefused(f"{LABEL}: the HDX package lists no xlsx resource")
    # One incident can sit in the thematic file and again in the yearly ones,
    # and the copies are not equally informative: the thematic health-care file
    # censors its coordinates while the SHCC files give them at 25 km. The copy
    # WITH coordinates is kept, and among equals the earliest file's (measured
    # 2026-10-12: "first file wins" kept 114 located incidents of 24,305).
    best: dict[str, tuple] = {}
    files = []
    # legacy id -> [the new id of the FIRST row that carried it, its file's
    # rank, whether that row has coordinates]: the row a held event was built
    # from (v1 kept the first).
    id_map: dict[str, list] = {}
    order = 0
    for rank, res in enumerate(resources):
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
            located = inc["latitude"] is not None and inc["longitude"] is not None
            id_map.setdefault(inc["incident_id_legacy"], [inc["incident_id"], rank, located])
            order += 1
            cand = (not located, rank, order, inc)
            held = best.get(inc["incident_id"])
            if held is None:
                kept += 1
            else:
                dup += 1
            if held is None or cand[:3] < held[:3]:
                best[inc["incident_id"]] = cand

        files.append({"file": name, "category": category, "rows": len(rows) - 1, "kept": kept, "duplicates": dup})
    incidents = [c[3] for c in sorted(best.values(), key=lambda c: c[2])]
    incidents.sort(key=lambda i: i["date"], reverse=True)
    stamp = {"source": "Insecurity Insight — State of Palestine incident data (HDX, direct)", "url": PAGE,
             "licence": {"license_id": pkg.get("license_id"), "license_title": pkg.get("license_title"),
                         "hdx_updated": pkg.get("last_modified") or pkg.get("metadata_modified"),
                         "caveats": pkg.get("caveats")},
             "files": files,
             "vintage": (pkg.get("last_modified") or "")[:10] or None,
             "vintage_basis": "HDX package last_modified",
             "vintage_url": PAGE,
             "id_rule": "publisher event number per category; whole row where the file has none"}
    return incidents, stamp, id_map


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
    # v1's own normalised file carries v1's ids. Since the events are held under
    # the publisher's numbers (2026-10-12) a night fed from it would write every
    # incident a second time, so it is no longer a fallback: a failed HDX read
    # leaves yesterday's file, like every other fetcher. `--from-v1 --stage DIR`
    # still reads it, into DIR only, for comparison.
    only_v1 = "--from-v1" in argv
    staged = stage_dir(argv)
    if only_v1 and staged is None:
        print(f"{LABEL}: --from-v1 writes v1's ids; pass --stage DIR to read it for comparison",
              file=sys.stderr)
        return 2
    try:
        id_map: dict = {}
        if only_v1:
            rows, stamp = from_v1()
        else:
            rows, stamp, id_map = from_hdx()
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
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(), **stamp, "data": rows}
    if staged is not None:
        stage(staged, OUT.name, payload)
        stage(staged, ID_MAP.name, id_map)
        print(f"{LABEL}: {len(rows)} incidents staged, nothing written to the raw tree")
        return 0
    write_atomic(OUT, payload)
    write_atomic(ID_MAP, id_map)
    event(LABEL, "ok", rows=len(rows), via="v1" if "read_from" in stamp else "hdx")
    print(f"{LABEL}: {len(rows)} incidents → {OUT.relative_to(ROOT)}"
          + (" (from v1's file)" if "read_from" in stamp else " (HDX, direct)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
