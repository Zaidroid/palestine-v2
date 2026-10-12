"""The West Bank school register, read from the publisher's shapefile on HDX.

    .venv/bin/python -m ops.fetch_hdx_schools                 # fetch and write
    .venv/bin/python -m ops.fetch_hdx_schools --dry-run       # print, write nothing
    .venv/bin/python -m ops.fetch_hdx_schools --dry-run --stage DIR

WHY (2026-10-12). `education` read a corpus frozen from v1 on 2026-08-08:
2,359 schools, every one dated by the day v1 downloaded the file. What the
register lacked was the publisher's own date. This is the direct line to the
file v1 read: HDX dataset `state-of-palestine-west-bank-schools`, resource
schools_WB.zip (a zipped shapefile, one point per school).

WHO PUBLISHES IT, AND WHEN IT IS FROM (HDX, read 2026-10-12). Contributed by
OCHA occupied Palestinian territory (oPt); source "Palestinian Authority -
Ministry of Education and UNICEF"; `dataset_date` 1 June 2015; the file was
last replaced on HDX on 10 June 2021 and its table was last written that same
day. Licence: "Creative Commons Attribution International (CC BY)",
license_id cc-by, http://www.opendefinition.org/licenses/cc-by.

WHAT IT WRITES. data/raw/hdx_schools/schools.json, in the record shape
`t_education` already reads (v1's WestBankSchoolsTransformer, field for
field), so the transformer and the loader are untouched. The four vintage
values sit in `metadata` (ops/hdx.stamp).

THE RECORD'S `date` IS A PLACEHOLDER, AND THE SAME ONE FOR EVERY ROW. A school
has no date; the 2,359 held rows carry 2026-08-05 (a day v1 downloaded the
file) with precision `unknown`, and the transformer copies `date` straight
into occurred_at. A corrected or added row written with any other day would
split one register across two dates (and the gap radar would read the gap
between them as the register's rhythm). So every record carries HELD_DAY, the
date is disclaimed as before, and the publisher's own date lives where a
reader can use it: `metadata.vintage` here, dataset.attrs once
db/proposed/hdx.sql is run.

IDENTITY. The spec matches a row on the publisher's school number
(`attrs.school_id`, the file's `schid`), and so does the stable id written
here: `hdx-school:<schid>`. Held rows keep the id v1 gave them.

WHAT MOVES, AND WHY (measured 2026-10-12 against the 2,359 held rows). The
shapefile's text is UTF-8 and says so in its .cpg file; v1 decoded it as
Windows-1252. The loader repairs that on the way in, except where the Arabic
holds the letter ف: its second UTF-8 byte, 0x81, has no Windows-1252
character, so the name could never be put back. This fetcher reads the text
as the publisher wrote it, and the rows whose stored name is still mojibake
are corrected (the loader supersedes them; nothing is deleted).

TWO OF v1's FIELDS ARE NOT THE PUBLISHER'S. The file has no column for a
school's type or status. v1 wrote "Unknown" and "Active" on every row, and
both are in the stored attrs (and "Active" is the stored value_text). They
are reproduced here so that no held row is revised for it; dropping them is a
decision about 2,359 rows, not a side effect of changing the supply line.

POSTURE (ops/fetchlib.py): atomic, floored, ledgered under `hdx:schools`. The
zip as downloaded is archived in bronze before it is parsed.
"""
from __future__ import annotations

import re
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import fetchlib as fl                                   # noqa: E402
from ops import hdx                                              # noqa: E402
from ops import shp                                              # noqa: E402

SLUG = "state-of-palestine-west-bank-schools"
PAGE = hdx.PAGE + SLUG
OUT = ROOT / "data" / "raw" / "hdx_schools" / "schools.json"
LABEL = "hdx:schools"
FLOOR = 2123                  # 0.9 x 2,359 schools (the file since 2021-06-10)
HELD_DAY = "2026-08-05"       # the placeholder every held row carries (precision
                              #   `unknown`); see the docstring
SOURCE = {"name": "HDX",      # routed by this exact name (education.yaml)
          "organization": "OCHA occupied Palestinian territory (oPt)",
          "url": PAGE, "license": "cc-by"}


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def record(feature: dict, index: int, fetched_at: str, when: str = HELD_DAY) -> dict:
    """One shapefile feature → one record in the shape t_education reads."""
    p = feature.get("properties") or {}
    g = feature.get("geometry") or {}
    name = (p.get("English_Sc") or p.get("Name") or p.get("name") or p.get("SCHOOL_NAM")
            or p.get("Arabic_sch") or "Unknown School")
    if g.get("type") == "Point":
        lon, lat = g["coordinates"][0], g["coordinates"][1]
    else:                               # no point: the table's own x_dd / y_dd
        lat = p.get("y_dd") if _finite(p.get("y_dd")) else None
        lon = p.get("x_dd") if _finite(p.get("x_dd")) else None
    schid = p.get("schid") or None
    return {
        "stable_id": f"hdx-school:{schid}" if schid is not None else f"hdx-school:row{index}",
        "date": when,
        "category": "education",
        "event_type": "school_record",
        "location": {
            "name": name,
            "governorate": p.get("districtna") or None,     # Arabic, as published
            "locality": p.get("locname") or None,           # Arabic, as published
            "region": "West Bank",
            "lat": lat, "lon": lon,
            "precision": "exact" if lat is not None and lon is not None else "region",
            "admin2_pcode": None,
        },
        "metrics": {"count": 1, "unit": "schools"},
        "school_name": name,
        "school_name_ar": p.get("Arabic_sch") or None,
        "school_id": schid,
        "school_type": "Unknown",       # v1's literal; the file has no such column
        "education_level": None,
        "school_status": "Active",      # v1's literal; the file has no such column
        # the publisher's own keys for the locality and the district
        "locality_code": p.get("locid") or None,
        "district_code": p.get("did"),
        "sources": [dict(SOURCE, fetched_at=fetched_at)],
    }


def records(parsed: dict, fetched_at: str) -> list[dict]:
    return [record(f, i, fetched_at) for i, f in enumerate(parsed["features"])]


def check(recs: list[dict], dry: bool = True) -> None:
    """The identity is the school number: every row must have one, and no two
    rows may share one. A file that breaks that is refused here, with the
    numbers, rather than by the loader's invariant one step later."""
    ids = [r["school_id"] for r in recs]
    missing = sum(1 for i in ids if i is None)
    doubled = len(ids) - missing - len({i for i in ids if i is not None})
    if missing or doubled:
        hdx.refuse(LABEL, f"{missing} schools without a school number and {doubled} "
                          "sharing one: the register's identity does not hold", dry,
                   missing=missing, doubled=doubled)


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        pkg = hdx.package(SLUG)
        res = hdx.resource(pkg, fmt="SHP") or hdx.resource(pkg, name=re.compile(r"\.zip$", re.I))
        if res is None:
            hdx.refuse(LABEL, f"HDX lists no shapefile resource on {SLUG}", dry)
        raw = fl.get(res["url"], timeout=180)
        parsed = shp.read_zip(raw)
        stamp = hdx.stamp(pkg, res, kind="register", checked_at=fetched_at)
        recs = records(parsed, fetched_at)
        if len(recs) < FLOOR:
            hdx.refuse(LABEL, f"{len(recs)} schools below the floor of {FLOOR}", dry,
                       rows=len(recs), floor=FLOOR)
        check(recs, dry)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:300])
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1

    doc = {"metadata": {
        "fetched_at": fetched_at,
        "source": "State of Palestine - West Bank schools (HDX)",
        "organization": SOURCE["organization"],
        "source_url": PAGE,
        "attribution": ("West Bank schools: Palestinian Authority Ministry of Education and "
                        "UNICEF, contributed by OCHA oPt to HDX, CC BY."),
        **stamp,
        "hdx_notes": (pkg.get("notes") or "")[:500] or None,
        "shapefile": parsed["name"], "text_encoding": parsed["encoding"],
        "projection": parsed["prj"],
        "table_last_written": parsed["table"]["last_update"],
        "table_fields": parsed["table"]["fields"],
        "record_date_is": (f"a placeholder, {HELD_DAY} on every record (the day the held "
                           "rows carry, precision unknown); the register's date is `vintage`"),
        "rows": len(recs),
        "rows_with_arabic_name": sum(1 for r in recs if r["school_name_ar"]),
        "rows_with_point": sum(1 for r in recs if r["location"]["lat"] is not None),
    }, "data": recs}
    print(f"  ok   {LABEL}: {len(recs)} schools; register as of {stamp['vintage']} "
          f"(file last replaced {hdx.day(stamp['resource_last_modified'])}, "
          f"table last written {parsed['table']['last_update']})")
    if dry:
        print(f"         would write {OUT.relative_to(ROOT)}")
        fl.stage(staged, OUT.name, doc)
        return 0
    from ingest import bronze
    doc["metadata"]["bronze"] = bronze.put("hdx_schools", raw, "zip", url=res["url"]).ref
    if not hdx.says_the_same(OUT, doc):
        fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=len(recs), vintage=stamp["vintage"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
