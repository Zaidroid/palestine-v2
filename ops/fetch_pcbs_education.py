"""PCBS's school statistics by year: schools, students and teachers by
supervising authority, for Palestine, the West Bank and the Gaza Strip from
1994/95, and by governorate from 2011/12.

    .venv/bin/python -m ops.fetch_pcbs_education              # fetch + load (nightly)
    .venv/bin/python -m ops.fetch_pcbs_education --dry-run
    .venv/bin/python -m ops.fetch_pcbs_education --dir DIR --dry-run   # the four workbooks already on disk

WHY (2026-10-19). The education area held one day: the HDX school register
of 2015. PCBS publishes the Ministry of Education's yearly counts (CC BY 4.0,
"Data: PCBS"): one bilingual workbook with ten sheets, 1994/95 → 2024/25, by
region and authority (government / UNRWA / private), and three workbooks by
governorate 2011/12 → 2024/25. This reads schools (sheet 1), students (sheet 4)
and teachers (sheet 8) by region, and the three governorate files, into
dataset pcbs_education_yearly (migration 134). Gaza stops at 2022/23 ("..",
PCBS: not available because of the war). Jerusalem excludes the Israeli
municipality's and Ma'arif schools (PCBS's own footnote).

THE WORKBOOKS. Years are labelled in Arabic order in the first column
("1995/1994") and in English order in the last ("1994/1995"); a school year is
loaded on 1 September of its first year with precision 'year' and the label in
attrs. "-" is nil (loaded as 0 where a column exists), ".." is not available
(no row). Schools: the three "Schools" columns (kindergartens are separate
columns and are not schools); the total is their sum, not the printed total,
which adds kindergartens. Teachers: the printed Total, Government, UNRWA,
Private. Governorate files: blocks headed كافة الجهات / حكومة / وكالة / خاصة, one
row per governorate; the region rows inside them are skipped (the long workbook
is the regions' series). Read with the standard library by sheet NAME.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                       # noqa: E402
from ops.fetch_pcbs import _get                                     # noqa: E402
from ops.fetch_worldbank_fuel import sheets_by_name, _NS            # noqa: E402

BASE = "https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/"
FILES = {"long": "Education1994_2024.xlsx", "schools": "Schools2011-2024.xlsx",
         "students": "Students2011-2024.xlsx", "teachers": "Teachers2011-2024.xlsx"}
RAW = fl.ROOT / "data" / "raw" / "pcbs" / "education"
DATASET, READER, LABEL = "pcbs_education_yearly", "fetch_pcbs_education@1", "pcbs:education"
MIN_ROWS = 2500                                   # ~3,000 observations on 2026-10-19
REGION = {"فلسطين": None, "الضفة الغربية": 2, "قطاع غزة": 1}
GOV = {"جنين": 3, "طوباس والاغوار الشمالية": 4, "طوباس": 4, "طولكرم": 5, "نابلس": 6, "قلقيلية": 7, "سلفيت": 8,
       "رام الله والبيرة": 9, "أريحا والأغوار": 10, "القدس": 11, "بيت لحم": 12, "الخليل": 13,
       "شمال غزة": 14, "غزة": 15, "دير البلح": 16, "خانيونس": 17, "خان يونس": 17, "رفح": 18}
SEX = {"كلا الجنسين": "both", "ذكور": "male", "إناث": "female", "اناث": "female"}
AUTH = {"كافة الجهات": "total", "حكومة": "government", "الوكالة": "unrwa", "وكالة": "unrwa", "خاصة": "private"}
UNIT = {"schools": "count", "students": "persons", "teachers": "persons"}
YEAR = re.compile(r"^(\d{4})/(\d{4})$")

UPSERT = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num, unit,
                         occurred_at, occurred_precision, reported_at, raw_ref,
                         attrs, identity_key, v1_stable_id)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value)s, %(unit)s,
        %(occurred)s, 'year', %(reported)s, %(raw_ref)s, %(attrs)s::jsonb,
        %(identity)s, %(stable)s)
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE (v1_stable_id IS NOT NULL AND upper(sys_period) IS NULL)
DO UPDATE SET value_num = EXCLUDED.value_num,
              unit = EXCLUDED.unit,
              reported_at = EXCLUDED.reported_at,
              raw_ref = EXCLUDED.raw_ref,
              attrs = EXCLUDED.attrs
"""


# ── pure: the workbooks ──────────────────────────────────────────────────────

def sheets(blob: bytes) -> dict[str, list[list]]:
    z = zipfile.ZipFile(io.BytesIO(blob))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t"))
                  for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS)]
    out = {}
    for name, path in sheets_by_name(z).items():
        rows = []
        for r in ET.fromstring(z.read(path)).iter(f"{{{_NS['m']}}}row"):
            vals = []
            for c in r.findall("m:c", _NS):
                v = c.find("m:v", _NS)
                vals.append(None if v is None else (shared[int(v.text)] if c.get("t") == "s" else v.text))
            rows.append(vals)
        out[name.strip()] = rows
    return out


def school_year(label) -> str | None:
    """'1995/1994' (Arabic order) or '1994/1995' → '1994/1995'."""
    m = YEAR.match(str(label or "").strip())
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    lo, hi = sorted((a, b))
    return f"{lo}/{hi}" if hi == lo + 1 else None


def _num(v):
    s = str(v or "").strip().replace(",", "")
    if s in ("", "..", "…"):
        return None
    if s == "-":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def long_sheet(rows: list[list], measure: str) -> list[dict]:
    """One region block after another; year rows between. Columns by measure."""
    if measure == "schools" or measure == "students":
        cols = {"government": 1, "unrwa": 3, "private": 5}        # the Schools columns; kindergartens sit between
    else:
        cols = {"total": 1, "government": 2, "unrwa": 3, "private": 4}
    out, region = [], None
    for r in rows:
        head = str(r[0] or "").strip() if r else ""
        if head in REGION:
            region = head
            continue
        y = school_year(head)
        if not y or region is None:
            continue
        vals = {a: _num(r[i]) if i < len(r) else None for a, i in cols.items()}
        if measure in ("schools", "students"):
            parts = [vals[a] for a in ("government", "unrwa", "private")]
            vals["total"] = sum(parts) if all(p is not None for p in parts) else None
        for auth, v in vals.items():
            if v is None:
                continue
            out.append({"measure": measure, "authority": auth, "place_id": REGION[region], "region": region,
                        "school_year": y, "value": v, "file": "long"})
    return out


def governorate_sheet(rows: list[list], measure: str) -> list[dict]:
    """Blocks headed by an authority; one row per governorate; years across."""
    years, out, auth, sex = None, [], None, "both"
    for r in rows:
        head = str(r[0] or "").strip() if r else ""
        cells1 = [str(v or "").strip() for v in r[:6]]
        if years is None and len(r) > 2 and school_year(r[1]):
            labels = [school_year(v) for v in r[1:]]
            # the students file repeats the years across the row: both sexes, then males, then females
            first_repeat = next((i for i, y in enumerate(labels) if y and y in labels[:i]), len(labels))
            years = labels[:first_repeat]
            continue
        if any(c in SEX for c in cells1):                           # the students file: both sexes, then males, then females
            sex = SEX[next(c for c in cells1 if c in SEX)]
            continue
        if head in AUTH:
            auth = AUTH[head]
            continue
        name = head.rstrip("*").strip()
        if years is None or auth is None or name not in GOV or sex != "both":
            continue
        for y, v in zip(years, r[1:]):
            val = _num(v)
            if y and val is not None:
                out.append({"measure": measure, "authority": auth, "place_id": GOV[name], "region": name,
                            "school_year": y, "value": val, "file": measure})
    return out


def parse_all(blobs: dict[str, bytes]) -> list[dict]:
    out = []
    long = sheets(blobs["long"])
    for sh, measure in (("1", "schools"), ("4", "students"), ("8", "teachers")):
        if sh not in long:
            raise ValueError(f"sheet {sh} missing from the long workbook: {list(long)}")
        out += long_sheet(long[sh], measure)
    for key, measure in (("schools", "schools"), ("students", "students"), ("teachers", "teachers")):
        book = sheets(blobs[key])
        out += governorate_sheet(next(iter(book.values())), measure)
    return out


def observations(rows: list[dict], reported: str) -> list[dict]:
    out = []
    for r in rows:
        y0 = int(r["school_year"][:4])
        slug = (str(r["place_id"]) if r["place_id"] else "palestine")
        out.append({"place_id": r["place_id"], "indicator": f"education.{r['measure']}.{r['authority']}", "value": r["value"],
                    "unit": UNIT[r["measure"]], "occurred": datetime(y0, 9, 1, tzinfo=timezone.utc), "reported": reported,
                    "raw_ref": BASE + FILES["long" if r["file"] == "long" else r["file"]],
                    "attrs": json.dumps({"school_year": r["school_year"], "region_printed": r["region"], "authority": r["authority"],
                                         "workbook": FILES["long" if r["file"] == "long" else r["file"]], "reader": READER}, ensure_ascii=False),
                    "identity": f"pcbs_education|{r['measure']}|{r['authority']}|{slug}|{r['school_year']}",
                    "stable": f"{DATASET}:{r['measure']}:{r['authority']}:{slug}:{y0}"})
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--dir")
    a = ap.parse_args(argv)
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        blobs = {}
        for key, name in FILES.items():
            blobs[key] = (Path(a.dir) / name).read_bytes() if a.dir else _get(BASE + name)
        rows = parse_all(blobs)
        fl.check_floor(LABEL, len(rows), MIN_ROWS)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}"); return 1
    except Exception as e:                                             # noqa: BLE001
        if not a.dry_run:
            fl.event(LABEL, "error", error=type(e).__name__)
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}"); return 1
    years = sorted({r["school_year"] for r in rows})
    by = {}
    for r in rows:
        by.setdefault((r["measure"], r["file"] == "long"), 0); by[(r["measure"], r["file"] == "long")] += 1
    print(f"  ok   {LABEL}  {len(rows)} rows, {years[0]} → {years[-1]}; " + ", ".join(f"{m}{' regions' if lg else ' governorates'} {n}" for (m, lg), n in sorted(by.items())))
    if a.dry_run:
        for r in rows:
            if r["school_year"] in ("1994/1995", "2022/2023", "2024/2025") and r["authority"] == "total" and r["region"] in ("فلسطين", "الخليل", "غزة"):
                print(f"         {r['school_year']} {r['region']:14} {r['measure']:9} {r['value']:>10.0f}")
        print("         (dry run — nothing written)"); return 0
    RAW.mkdir(parents=True, exist_ok=True)
    for key, name in FILES.items():
        (RAW / name).write_bytes(blobs[key])
    fl.write_atomic(RAW / "education.json", {"fetched_at": fetched_at, "rows": rows})
    fl.event(LABEL, "ok", rows=len(rows), data_through=years[-1])
    from resolve.db import connect                                     # noqa: E402
    with connect() as conn:
        row = conn.execute("SELECT dataset_id FROM dataset WHERE key = %s", (DATASET,)).fetchone()
        if not row:
            raise SystemExit(f"dataset {DATASET} missing: apply migration 134")
        obs = observations(rows, fetched_at)
        for o in obs:
            conn.execute(UPSERT, {**o, "dataset_id": row[0]})
        conn.commit()
    print(f"  loaded {len(obs)} observations into {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
