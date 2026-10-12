"""The infrastructure category's four inputs, from where each one lives now.

    .venv/bin/python -m ops.fetch_hdx_infrastructure              # all four
    .venv/bin/python -m ops.fetch_hdx_infrastructure barrier      # one feed
    .venv/bin/python -m ops.fetch_hdx_infrastructure --dry-run [--stage DIR]

WHY (2026-10-12). `infrastructure` read one corpus frozen from v1 on
2026-08-08. It holds four different things from three publishers, and only
one of them is finished. This module writes each to its own file under
data/raw/infrastructure/, in the record shape `t_infrastructure` already
reads, so the transformer and the loader are untouched:

  tech4palestine.json     2,920 records, COPIED from the frozen corpus as they
                          are. Tech for Palestine's infrastructure-damaged
                          series ended on 2025-10-05 (their API still serves
                          730 days, 2023-10-07 to 2025-10-05, read 2026-10-12).
                          Nothing is fetched; the file exists so the category
                          has one input directory.
  barrier.json            HDX `west-bank-barrier` (OCHA oPt, CC BY): the
                          Barrier as of January 2018, 261 line segments.
  village_boundaries.json HDX `state-of-palestine-village-boundary-in-the-
                          west-bank` (OCHA oPt; source the Palestinian
                          Authority's Ministry of Planning; CC BY): 342 village
                          boundaries drawn under the British Mandate.
  unosat.json             UNOSAT's Gaza damage assessments (CC BY-SA), one
                          record per assessment, read from the description of
                          each UNOSAT dataset on HDX with v1's own rules.

A REGISTER RECORD'S `date` IS A PLACEHOLDER. A barrier segment and a village
boundary have no date; the 603 held rows carry 2026-08-07 (a day v1
downloaded the files) with precision `unknown`, and the transformer copies
`date` into occurred_at. Every register record written here carries that same
HELD_DAY, so a corrected or added row never splits a register across two
dates. The publisher's own date is `metadata.vintage` in each file.

IDENTITY, REPRODUCED. The two registers are matched on where a thing is
(`attrs.geo_key`, built by the transformer from location.lat / .lon), so this
module computes that point the way v1 did: the middle vertex of a barrier
line, the plain mean of the vertices of a village polygon's first ring. The
shapefile reader (ops/shp.py) sorts rings the way v1's did. UNOSAT rows are
matched on the assessment date.

WHAT IS KEPT AS v1 WROTE IT, THOUGH THE FILE SAYS MORE. A held row's content
is its value, unit and attrs, so each of these is reproduced rather than
quietly revised, and the publisher's own value rides beside it in the record:
  * every village is `locality_name: "Unknown Locality"`; the file names all
    342 (`village_name`);
  * every barrier segment counts 1 with unit "km"; the file gives each
    segment's length (`shape_length_m`, 711.9 km in all);
  * a village counts 1 with unit "persons"; the file holds no population;
  * 3 segments with no type in the file are typed "Wall".
  * the Barrier's coordinates are metres (WGS 84 / UTM zone 36N, the file's
    own .prj), in fields named lat / lon; the spec's `latlon_exclude` keeps
    them from being read as degrees.

POSTURE (ops/fetchlib.py): atomic, floored, ledgered — `hdx:barrier`,
`hdx:village_boundaries`, `unosat:gaza_damage`. Each downloaded zip is
archived in bronze before it is parsed. A feed that fails keeps its own file
from yesterday; the others are still written.
"""
from __future__ import annotations

import gzip
import hashlib
import json
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

RAW = ROOT / "data" / "raw" / "infrastructure"
FROZEN = ROOT / "data" / "frozen" / "infrastructure.json.gz"

BARRIER_SLUG = "west-bank-barrier"
VILLAGE_SLUG = "state-of-palestine-village-boundary-in-the-west-bank"
# v1 asked HDX for "unosat gaza damage assessment" and took the first 100 of
# some 1,450 results by relevance; on 2026-10-12 one of the 24 datasets it
# needs sat at rank 50. This asks for the same datasets by publisher and name
# (the same 24 that day, measured), so none can slide off the end of a ranking.
UNOSAT_QUERY = "q=name:unosat-gaza*&fq=organization:unosat"
UNOSAT_ORG = "https://data.humdata.org/organization/unosat"

# Floors: 0.9 of what the publisher's file has held since it was uploaded
# (261 segments since 2019-07-16, 342 boundaries since 2019-07-24), and of the
# 14 assessments UNOSAT had on HDX on 2026-10-12. T4P's is exact: the series
# is finished, 730 days x 4 kinds of building.
FLOORS = {"barrier": 235, "village_boundaries": 308, "unosat": 12}
T4P_RECORDS = 2920
HELD_DAY = "2026-08-07"       # the placeholder every held register row carries
                              #   (precision `unknown`); see the docstring

HDX_SOURCE = {"name": "HDX",                 # routed by this exact name
              "organization": "OCHA occupied Palestinian territory (oPt)",
              "license": "cc-by"}
UNOSAT_SOURCE = {"name": "UNOSAT Gaza damage assessments",      # routed by name
                 "organization": "UNITAR/UNOSAT", "license": "CC-BY-SA"}

MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}


# ── Tech for Palestine: the frozen series, carried over ──────────────────────

def t4p_from_frozen(frozen: Path = FROZEN) -> dict:
    raw = gzip.decompress(frozen.read_bytes())
    recs = [r for r in json.loads(raw)["data"]
            if ((r.get("sources") or [{}])[0].get("name")) == "TechForPalestine"]
    days = sorted({str(r.get("date"))[:10] for r in recs})
    return {"metadata": {
        "source": "TechForPalestine — infrastructure-damaged (Government Media Office, Gaza)",
        "copied_from": "data/frozen/infrastructure.json.gz",
        "frozen_sha256_uncompressed": hashlib.sha256(raw).hexdigest(),
        "rows": len(recs), "days": len(days),
        "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
        "vintage": days[-1] if days else None,
        "vintage_basis": ("the last day of the series; Tech for Palestine stopped publishing "
                          "it there (their API served the same 730 days on 2026-10-12)"),
        "vintage_url": "https://data.techforpalestine.org/api/v3/infrastructure-damaged.json",
        "note": "not fetched: these are the frozen corpus's own records, unchanged",
    }, "data": recs}


# ── the two West Bank registers ──────────────────────────────────────────────

def _line_point(geometry: dict | None) -> tuple[float | None, float | None]:
    """v1's 'centroid' of a barrier segment: the middle vertex of a single
    line. A segment drawn as several lines has none (one of the 261)."""
    if not geometry or geometry.get("type") != "LineString" or not geometry["coordinates"]:
        return None, None
    c = geometry["coordinates"]
    mid = c[len(c) // 2]
    return mid[1], mid[0]


def _ring_mean(geometry: dict | None) -> tuple[float | None, float | None]:
    """v1's 'centroid' of a village: the plain mean of the first ring's
    vertices, summed in file order (the closing vertex counts twice)."""
    ring = shp.first_ring(geometry)
    if not ring:
        return None, None
    lat = lon = 0
    for p in ring:
        lat += p[1]
        lon += p[0]
    return lat / len(ring), lon / len(ring)


def _geo_key(lat, lon) -> str | None:
    """The transformer's own rendering (ingest/databank.t_infrastructure)."""
    return None if lat is None or lon is None else f"{lat:.6f},{lon:.6f}"


def barrier_record(feature: dict, index: int, fetched_at: str, page: str,
                   when: str = HELD_DAY) -> dict:
    p = feature.get("properties") or {}
    lat, lon = _line_point(feature.get("geometry"))
    oid = p.get("OBJECTID")
    return {
        "stable_id": f"hdx-barrier:{oid}" if oid is not None else f"hdx-barrier:row{index}",
        "date": when,
        "category": "infrastructure",
        "event_type": "barrier_segment",
        "location": {
            "name": p.get("Name") or p.get("name") or "Separation Barrier Segment",
            "governorate": None, "region": "West Bank",
            # METRES, not degrees: northing in `lat`, easting in `lon`, as v1
            # stored them and as the row's identity is built from them
            "lat": lat, "lon": lon,
            "precision": "exact" if lat is not None else "region",
            "admin2_pcode": None,
            "coordinate_system": "WGS 84 / UTM zone 36N, metres (EPSG:32636)",
        },
        "metrics": {"count": 1, "unit": "km"},              # v1's; see the docstring
        "barrier_type": p.get("Type") or p.get("TYPE") or p.get("barrier_type") or "Wall",
        "barrier_status": p.get("Status") or p.get("STATUS") or "Constructed",
        # the publisher's own values
        "segment_id": oid,
        "barrier_type_published": p.get("Type"),
        "shape_length_m": p.get("Shape_Leng"),
        "sources": [dict(HDX_SOURCE, url=page, fetched_at=fetched_at)],
    }


def village_record(feature: dict, index: int, fetched_at: str, page: str,
                   when: str = HELD_DAY) -> dict:
    p = feature.get("properties") or {}
    lat, lon = _ring_mean(feature.get("geometry"))
    name = p.get("Name") or p.get("name") or p.get("LOCALITY") or "Unknown Locality"
    return {
        "stable_id": f"hdx-village:{_geo_key(lat, lon) or f'row{index}'}",
        "date": when,
        "category": "infrastructure",
        "event_type": "locality_record",
        "location": {
            "name": p.get("VNAME") or name,
            "governorate": None, "region": "West Bank",
            "lat": lat, "lon": lon,
            "precision": "exact" if lat is not None else "region",
            "admin2_pcode": None,
        },
        "metrics": {"count": 1, "unit": "persons"},         # v1's; see the docstring
        "locality_name": name,                              # v1's; the file's is below
        "locality_type": p.get("Type") or p.get("TYPE") or p.get("locality_type") or "Village",
        # the publisher's own values
        "village_name": p.get("VNAME"),
        "shape_area": p.get("Shape_Area"),
        "shape_length": p.get("Shape_Leng"),
        "sources": [dict(HDX_SOURCE, url=page, fetched_at=fetched_at)],
    }


# What the village dataset's own description adds about its date (HDX notes,
# read 2026-10-12: "These historical boundaries were created during British
# Mandate in Palestine.").
VILLAGE_SAYS = "the dataset describes the boundaries as drawn under the British Mandate"


def register_doc(pkg: dict, res: dict, parsed: dict, recs: list[dict],
                 fetched_at: str, attribution: str, says: str | None = None) -> dict:
    return {"metadata": {
        "fetched_at": fetched_at,
        "source": f"{pkg.get('title')} (HDX)",
        "organization": HDX_SOURCE["organization"],
        "source_url": hdx.PAGE + str(pkg.get("name")),
        "attribution": attribution,
        **hdx.stamp(pkg, res, kind="register", checked_at=fetched_at, says=says),
        "hdx_notes": (pkg.get("notes") or "")[:500] or None,
        "shapefile": parsed["name"], "text_encoding": parsed["encoding"],
        "projection": parsed["prj"],
        "table_last_written": parsed["table"]["last_update"],
        "table_fields": parsed["table"]["fields"],
        "record_date_is": (f"a placeholder, {HELD_DAY} on every record (the day the held "
                           "rows carry, precision unknown); the register's date is `vintage`"),
        "rows": len(recs),
        "rows_with_point": sum(1 for r in recs if r["location"]["lat"] is not None),
    }, "data": recs}


def check_points(label: str, recs: list[dict], allow_without: int, dry: bool = True) -> None:
    """The registers' identity is a point. Two rows on one point, or more rows
    without one than the file has ever had, and the identity does not hold."""
    keys = [_geo_key(r["location"]["lat"], r["location"]["lon"]) for r in recs]
    without = sum(1 for k in keys if k is None)
    have = [k for k in keys if k is not None]
    doubled = len(have) - len(set(have))
    if doubled or without > allow_without:
        hdx.refuse(label, f"{doubled} rows share a point and {without} have none "
                          f"(at most {allow_without} expected)", dry,
                   doubled=doubled, without_point=without)


def fetch_register(label: str, slug: str, make, attribution: str, fetched_at: str,
                   dry: bool, says: str | None = None):
    pkg = hdx.package(slug)
    res = hdx.resource(pkg, fmt="SHP") or hdx.resource(pkg, name=re.compile(r"\.zip$", re.I))
    if res is None:
        hdx.refuse(label, f"HDX lists no shapefile resource on {slug}", dry)
    raw = fl.get(res["url"], timeout=180)
    parsed = shp.read_zip(raw)
    page = hdx.PAGE + slug
    recs = [make(f, i, fetched_at, page) for i, f in enumerate(parsed["features"])]
    return (register_doc(pkg, res, parsed, recs, fetched_at, attribution, says),
            raw, res["url"])


# ── UNOSAT: one record per assessment, parsed from the dataset's own text ────

_DATE = re.compile(
    r"(?:images? collected on(?: the)?|as of)\s+(\d{1,2})(?:\s*(?:and|-|–|‑)\s*\d{1,2})?"
    r"\s+([A-Za-z]+),?\s+(\d{4})", re.I)
_TOTALS = {
    "destroyed": re.compile(r"([\d,]+)\s+destroyed structures", re.I),
    "severely_damaged": re.compile(r"([\d,]+)\s+severely damaged structures", re.I),
    "moderately_damaged": re.compile(r"([\d,]+)\s+moderately damaged structures", re.I),
    "possibly_damaged": re.compile(r"([\d,]+)\s+possibly damaged structures", re.I),
    "total_affected": re.compile(r"total of\s+([\d,]+)", re.I),
    "housing_units_damaged": re.compile(r"([\d,]+)\s+housing units have been damaged", re.I),
    "percent_structures_damaged": re.compile(r"approximately\s+(\d+)%\s+of all structures", re.I),
}


def _int(s: str) -> int | None:
    digits = s.replace(",", "")
    return int(digits) if digits.isdigit() else None


def assessment_date(text: str) -> str | None:
    """The first imagery date in the description: "images collected on 3 and 6
    September 2024", "image collected on 15 October 2023", "as of 22-23
    September 2025" → the first day named."""
    m = _DATE.search(text or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2).lower()]}-{int(m.group(1)):02d}"


def damage_totals(text: str) -> dict | None:
    found = {k: rx.search(text or "") for k, rx in _TOTALS.items()}
    if not found["destroyed"] and not found["total_affected"]:
        return None                 # a road or cropland dataset, or a partial one
    return {k: (_int(m.group(1)) if m else None) for k, m in found.items()}


def unosat_assessments(packages: list[dict]) -> list[dict]:
    """HDX search results → one assessment per (scope, date), v1's rules: the
    dataset's name starts 'unosat-gaza' and says 'damage'; its description
    gives totals and an imagery date; of two datasets for one assessment the
    larger total stands."""
    by_key: dict[str, dict] = {}
    for pkg in packages:
        name = pkg.get("name") or ""
        if not name.startswith("unosat-gaza") or "damage" not in name.lower():
            continue
        notes = pkg.get("notes") or ""
        totals = damage_totals(notes)
        when = assessment_date(notes)
        if not totals or not when:
            continue
        scope = "governorate" if "governorate" in name.lower() else "strip"
        gdb = next((r for r in pkg.get("resources") or []
                    if "geodatabase" in (r.get("format") or "").lower()), None)
        a = {"date": when, "scope": scope, "dataset": name, "title": pkg.get("title"),
             **totals, "geodatabase_url": (gdb or {}).get("url") or None,
             "source_url": hdx.PAGE + name,
             "dataset_date": pkg.get("dataset_date"),
             "hdx_last_modified": pkg.get("last_modified"),
             "hdx_created": pkg.get("metadata_created"),
             "license_id": pkg.get("license_id"), "license_title": pkg.get("license_title")}
        key = f"{scope}|{when}"
        if key not in by_key or (a["total_affected"] or 0) > (by_key[key]["total_affected"] or 0):
            by_key[key] = a
    return sorted(by_key.values(), key=lambda a: a["date"])


def unosat_record(a: dict) -> dict:
    return {
        "stable_id": f"unosat-cda:{a['scope']}:{a['date']}",
        "id": f"unosat-cda-{a['scope']}-{a['date']}",
        "date": a["date"],
        "category": "infrastructure",
        "event_type": "satellite_damage_assessment",
        "location": {"name": "Gaza Strip" if a["scope"] == "strip" else "Gaza Governorate",
                     "governorate": None, "region": "Gaza Strip", "lat": None, "lon": None,
                     "precision": "region", "admin2_pcode": None},
        "metrics": {
            "structures_destroyed": a["destroyed"],
            "structures_severely_damaged": a["severely_damaged"],
            "structures_moderately_damaged": a["moderately_damaged"],
            "structures_possibly_damaged": a["possibly_damaged"],
            "structures_total_affected": a["total_affected"],
            "housing_units_damaged": a["housing_units_damaged"],
            "percent_structures_damaged": a["percent_structures_damaged"],
            "unit": "structures",
        },
        "assessment_scope": a["scope"],
        "geodatabase_url": a["geodatabase_url"],
        "title": a["title"],
        "hdx_dataset": a["dataset"],
        "dataset_date": a["dataset_date"],
        "hdx_last_modified": a["hdx_last_modified"],
        "sources": [dict(UNOSAT_SOURCE, url=a["source_url"])],
    }


def unosat_doc(assessments: list[dict], fetched_at: str) -> dict:
    last = assessments[-1]
    return {"metadata": {
        "fetched_at": fetched_at,
        "source": "UNOSAT Gaza Strip damage assessments (via HDX)",
        "organization": "United Nations Satellite Centre (UNOSAT), UNITAR",
        "source_url": UNOSAT_ORG,
        "attribution": "Satellite damage assessments: UNOSAT (UNITAR) via HDX, CC BY-SA.",
        "vintage": last["date"],
        "vintage_basis": ("the imagery date of the newest UNOSAT Gaza damage assessment on HDX "
                          f"({last['dataset']}; dataset_date {last['dataset_date']}, added to "
                          f"HDX {hdx.day(last['hdx_created'])})"),
        "vintage_url": last["source_url"],
        "vintage_checked_at": fetched_at,
        "license_id": last["license_id"], "license_title": last["license_title"],
        "rows": len(assessments),
        "first_assessment": assessments[0]["date"], "last_assessment": last["date"],
        "by_scope": {s: sum(1 for a in assessments if a["scope"] == s)
                     for s in ("strip", "governorate")},
        "method": ("each record is one UNOSAT dataset on HDX whose name starts 'unosat-gaza' "
                   "and says 'damage'; its totals and imagery date are read from the "
                   "dataset's description"),
    }, "data": [unosat_record(a) for a in assessments]}


# ── the run ──────────────────────────────────────────────────────────────────

def _floor(label: str, n: int, feed: str, dry: bool) -> None:
    if n < FLOORS[feed]:
        hdx.refuse(label, f"{n} rows below the floor of {FLOORS[feed]}", dry,
                   rows=n, floor=FLOORS[feed])


def _same_data(path: Path, doc: dict) -> bool:
    try:
        return json.loads(path.read_text()) == doc
    except (OSError, ValueError):
        return False


def run_feed(feed: str, dry: bool, staged: Path | None) -> bool:
    out = RAW / f"{feed}.json"
    fetched_at = datetime.now(timezone.utc).isoformat()
    archive = None
    if feed == "tech4palestine":
        # no network and no ledger line: a copy of a file this repository holds
        try:
            doc = t4p_from_frozen()
        except (OSError, ValueError, KeyError) as e:
            print(f"  FAIL infrastructure:{feed}: {type(e).__name__}: {str(e)[:200]}",
                  file=sys.stderr)
            return False
        n = len(doc["data"])
        if n != T4P_RECORDS:
            print(f"  REFUSED infrastructure:{feed}: the frozen corpus holds {n} Tech for "
                  f"Palestine records, not {T4P_RECORDS}", file=sys.stderr)
            return False
        print(f"  ok   {feed:<19} {n:>5} records carried over from the frozen corpus, "
              f"{doc['metadata']['first_day']} to {doc['metadata']['last_day']}")
        if dry:
            fl.stage(staged, out.name, doc)
        elif not _same_data(out, doc):
            fl.write_atomic(out, doc)
        return True

    label = {"barrier": "hdx:barrier", "village_boundaries": "hdx:village_boundaries",
             "unosat": "unosat:gaza_damage"}[feed]
    try:
        if feed == "barrier":
            doc, raw, url = fetch_register(
                label, BARRIER_SLUG, barrier_record,
                "West Bank Barrier, January 2018: OCHA oPt via HDX, CC BY.", fetched_at, dry)
            _floor(label, len(doc["data"]), feed, dry)
            check_points(label, doc["data"], 1, dry)       # one segment has no point
            archive = ("hdx_barrier", raw, url)
        elif feed == "village_boundaries":
            doc, raw, url = fetch_register(
                label, VILLAGE_SLUG, village_record,
                ("Village boundaries in the West Bank: Palestinian Authority, Ministry of "
                 "Planning, contributed by OCHA oPt to HDX, CC BY."), fetched_at, dry,
                says=VILLAGE_SAYS)
            _floor(label, len(doc["data"]), feed, dry)
            check_points(label, doc["data"], 0, dry)
            archive = ("hdx_village_boundaries", raw, url)
        else:
            assessments = unosat_assessments(hdx.search(UNOSAT_QUERY, rows=200))
            _floor(label, len(assessments), feed, dry)
            doc = unosat_doc(assessments, fetched_at)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}", file=sys.stderr)
        return False
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        if not dry:
            fl.event(label, "error", error=f"{type(e).__name__}: {e}"[:300])
        print(f"  FAIL {label}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return False

    m = doc["metadata"]
    print(f"  ok   {feed:<19} {len(doc['data']):>5} records; publisher's date {m['vintage']}"
          + (f" (file last replaced {hdx.day(m.get('resource_last_modified'))}, table last "
             f"written {m.get('table_last_written')})" if feed != "unosat" else
             f" ({m['by_scope']['strip']} Strip-wide, {m['by_scope']['governorate']} of "
             "Gaza governorate alone)"))
    if dry:
        print(f"         would write {out.relative_to(ROOT)}")
        fl.stage(staged, out.name, doc)
        return True
    if archive:
        from ingest import bronze
        m["bronze"] = bronze.put(archive[0], archive[1], "zip", url=archive[2]).ref
    fl.write_atomic(out, doc)
    fl.event(label, "ok", rows=len(doc["data"]), vintage=m["vintage"])
    return True


FEEDS = ("tech4palestine", "barrier", "village_boundaries", "unosat")


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    feeds = [a for a in argv if not a.startswith("--")
             and (staged is None or a != str(staged))] or list(FEEDS)
    unknown = [f for f in feeds if f not in FEEDS]
    if unknown:
        raise SystemExit(f"unknown feed {unknown[0]!r} ({' | '.join(FEEDS)})")
    ok = [run_feed(f, dry, staged) for f in feeds]
    print(f"\n  {sum(ok)}/{len(ok)} infrastructure feeds written"
          + ("  (dry run, nothing written)" if dry else ""))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
