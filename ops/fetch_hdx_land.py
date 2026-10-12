"""Fetch the two land registers v1 read from HDX: OCHA oPt's West Bank
Separation Barrier and the Peace Now settlement footprints.

WHAT THESE TWO DATASETS REALLY ARE (measured 2026-10-12 against v1's own
intermediate files and the publisher's records).

  v1_land_ocha, 261 rows of `land.checkpoint`. v1's fetch-land-data.js does
  not name a dataset: it searches HDX for "west bank closure" inside OCHA
  oPt's organisation and takes the first hit that carries a shapefile. That
  hit is "West Bank Separation Barrier" (HDX `west-bank-barrier`, one file,
  Barrier_Jan2018), so the 261 "checkpoints" are the 261 line segments of
  the barrier: 181 constructed, 28 under construction, 52 projected. v1 named
  each `<Type> - <OBJECTID>` ("Concrete - 1", "Fence - 2"), typed every one
  "Barrier", and stamped `permits_required: true` on all of them, which is a
  default in v1's code and nothing the file says. The same 261 segments are
  held a second time as `infrastructure.barrier_segment`.

  v1_land_peace_now, 199 rows of `land.settlement`. HDX
  `state-of-palestine-settlements`, published by OCHA oPt, "Settlements data
  provided by Peace Now": 201 built-up-area polygons with a name and an area
  and nothing else. `Authorized` (land_status, legal_status) and `Settlement`
  (settlement_type) are v1 defaults: the file has no status and no type.
  Two unnamed polygons round to the same dunum as another unnamed polygon and
  collapse onto it (199 distinct name + area), as they did in v1.

This fetcher pins both datasets by id (a search result can change overnight)
and writes the record shape `t_land` already reads, v1's defaults included,
so every held row is matched on its identity and nothing is rewritten. The
defaults are isolated below (V1_DEFAULTS_*) and listed in the raw file's
metadata, so a reader of the raw file cannot take them for the publisher's
words. What the publisher's file does say is kept beside them under
`upstream` (status, type, segment length in metres, the polygon's area).

VINTAGE. Both are old registers: the barrier is "West Bank Separation
Barrier, January 2018" (HDX dataset_date 2018-01-01, file last modified
2019-07-16); the settlement footprints are dated 2018-12-30/31 (file last
modified 2021-06-03). Each raw file's metadata carries the publisher's dates.

GENTLE. HDX's robots.txt asks for ten seconds between requests; this waits
that long. A night on which the publisher's `last_modified` equals the one
already on disk downloads nothing and rewrites nothing (two metadata requests
in all). The same robots.txt lists `Disallow: /api/` for crawlers; the
metadata here is read through HDX's documented CKAN API (`package_show`), as
this project's other HDX fetchers read it (fetch_unhcr_hdx, fetch_fao_diem,
fetch_unrwa_registered, fetch_insecurity_insight). Said in the 2026-10-12
hand-over so the choice is Zaid's for all five at once.

LICENCE as HDX states it: barrier `cc-by`, settlements `cc-by-igo`. The store
routes the settlement rows to the source `peace_now` (no licence found); this
fetcher changes no grade.

Posture (ops/fetchlib.py): atomic, floored, ledgered.

Run: .venv/bin/python -m ops.fetch_hdx_land              # both
     .venv/bin/python -m ops.fetch_hdx_land --dry-run    # print, write nothing
     .venv/bin/python -m ops.fetch_hdx_land barrier      # one feed
"""
from __future__ import annotations

import io
import json
import math
import struct
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

RAW = fl.ROOT / "data" / "raw" / "land"
API = "https://data.humdata.org/api/3/action/package_show?id="
CRAWL_DELAY = 10            # seconds; data.humdata.org/robots.txt "Crawl-Delay: 10"

FEEDS = {
    "barrier": {
        "package": "west-bank-barrier",
        "resource": "95470fef-0d9d-4967-bbd6-cf247b80d578",
        "page": "https://data.humdata.org/dataset/west-bank-barrier",
        "out": RAW / "barrier.json", "label": "hdx:west_bank_barrier",
        "floor": 235,                      # 0.9 x 261 segments (2026-10-12)
        "bronze": "ocha",
    },
    "settlements": {
        "package": "state-of-palestine-settlements",
        "resource": "05d6421b-e796-4940-ae9e-a55858e96664",
        "page": "https://data.humdata.org/dataset/state-of-palestine-settlements",
        "out": RAW / "settlements.json", "label": "hdx:peacenow_settlements",
        "floor": 179,                      # 0.9 x 199 distinct name + area
        "bronze": "peace_now",
    },
}

# Source names EXACTLY as db/mappings/land.yaml routes them.
BARRIER_SOURCE = {"name": "OCHA oPt", "organization": "UN OCHA oPt",
                  "url": FEEDS["barrier"]["page"]}
SETTLEMENT_SOURCE = {"name": "Peace Now",
                     "organization": "Peace Now (Settlement Watch), "
                                     "published by UN OCHA oPt on HDX",
                     "url": FEEDS["settlements"]["page"]}

# What v1's code wrote on every row and the publisher's file does not say.
# Kept so the held rows are matched and not rewritten; never the publisher's.
V1_DEFAULTS_BARRIER = {"permits_required": True}
V1_DEFAULTS_SETTLEMENT = {"land_status": "Authorized",
                          "legal_status": "Authorized",
                          "settlement_type": "Settlement"}


# ── the attribute table of a shapefile, with the standard library ────────────

def read_dbf(b: bytes) -> list[dict]:
    """Rows of a dBASE table as dicts. Text is trimmed and an empty cell is
    None; N and F cells are numbers (an N with no decimals is an int). This is
    how the library v1 used read the same file, so names come out the same."""
    n, header_len, record_len = struct.unpack("<IHH", b[4:12])
    fields, off = [], 32
    while b[off] != 0x0D:
        name = b[off:off + 11].split(b"\0")[0].decode("ascii")
        fields.append((name, chr(b[off + 11]), b[off + 16], b[off + 17]))
        off += 32
    rows, pos = [], header_len
    for _ in range(n):
        raw = b[pos:pos + record_len]
        pos += record_len
        if len(raw) < record_len or raw[:1] == b"*":      # short or deleted
            continue
        row, p = {}, 1
        for name, kind, length, decimals in fields:
            cell = raw[p:p + length].decode("utf-8", "replace").strip()
            p += length
            if not cell:
                row[name] = None
            elif kind in "NF":
                try:
                    row[name] = int(cell) if kind == "N" and not decimals \
                        else float(cell)
                except ValueError:
                    row[name] = None
            else:
                row[name] = cell
        rows.append(row)
    return rows


def dbf_of(zip_bytes: bytes) -> list[dict]:
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = [n for n in z.namelist() if n.lower().endswith(".dbf")]
    if len(names) != 1:
        raise ValueError(f"expected one .dbf in the archive, found {names}")
    return read_dbf(z.read(names[0]))


# ── the two transforms v1 applied, reproduced ────────────────────────────────

def _checkpoint_status(status: str | None) -> str:
    """v1: a missing status reads 'Active'; three keywords are normalised;
    anything else (Constructed, Under Construction, Projected) stays as is."""
    s = status or "Active"
    low = s.lower()
    if "active" in low or "operational" in low:
        return "Active"
    if "partial" in low:
        return "Partial"
    if "closed" in low or "inactive" in low:
        return "Closed"
    return s


def _checkpoint_type(obstacle: str) -> str:
    low = obstacle.lower()
    if "checkpoint" in low:
        return "Checkpoint"
    if "gate" in low:
        return "Gate"
    if "roadblock" in low:
        return "Roadblock"
    return "Barrier"


def barrier_records(rows: list[dict], fetched_at: str) -> list[dict]:
    """One record per barrier segment, in the shape t_land reads for
    `event_type: checkpoint` (v1's name for them)."""
    src = {**BARRIER_SOURCE, "license": "cc-by (as stated on HDX)",
           "fetched_at": fetched_at}
    out = []
    for r in rows:
        oid = r.get("OBJECTID")
        if oid is None:
            continue
        kind = r.get("Type") or "Unknown"
        status = _checkpoint_status(r.get("Status"))
        out.append({
            "stable_id": f"hdx-west-bank-barrier:{oid}",
            "date": fetched_at[:10],             # a register: t_land disclaims it
            "event_type": "checkpoint",
            "location": {"name": "West Bank", "region": "West Bank"},
            "metrics": {"count": 1, "unit": "sites"},
            "land_type": "checkpoint",
            "land_name": f"{kind} - {oid}",
            "land_status": status,
            "checkpoint": {"checkpoint_type": _checkpoint_type(kind),
                           "operational_status": status,
                           **V1_DEFAULTS_BARRIER},
            "upstream": {"objectid": oid, "status": r.get("Status"),
                         "type": r.get("Type"),
                         "is_counted": r.get("IS_COUNTED"),
                         "length_m": r.get("Shape_Leng")},
            "sources": [src]})
    return out


def _js_round(x: float) -> int:
    """JavaScript's Math.round (half goes up), which is how v1 made dunums."""
    return math.floor(x + 0.5)


def settlement_records(rows: list[dict], fetched_at: str) -> tuple[list[dict], list]:
    """One record per distinct (name, dunums). Returns (records, collapsed
    OBJECTIDs): an unnamed polygon whose area rounds to the same dunum as an
    earlier unnamed polygon cannot be told apart by the dataset's identity
    and is left out, as v1 left it out."""
    src = {**SETTLEMENT_SOURCE, "license": "cc-by-igo (as stated on HDX)",
           "fetched_at": fetched_at}
    out, seen, collapsed = [], set(), []
    for r in rows:
        name = r.get("Name") or "Unknown"
        area = r.get("Shape_Area")
        dunums = _js_round(area / 1000) if area else None    # 1 dunum = 1,000 m2
        key = (name, dunums)
        if key in seen:
            collapsed.append(r.get("OBJECTID"))
            continue
        seen.add(key)
        settlement = {"settlement_type": V1_DEFAULTS_SETTLEMENT["settlement_type"],
                      "legal_status": V1_DEFAULTS_SETTLEMENT["legal_status"]}
        if dunums:
            settlement["area_dunums"] = dunums
        out.append({
            "stable_id": f"hdx-peacenow-settlements:{r.get('OBJECTID')}",
            "date": fetched_at[:10],
            "event_type": "settlement",
            "location": {"name": "West Bank", "region": "West Bank"},
            "metrics": {"count": 1, "unit": "sites"},
            "land_type": "settlement",
            "land_name": name,
            "land_status": V1_DEFAULTS_SETTLEMENT["land_status"],
            "settlement": settlement,
            "upstream": {"objectid": r.get("OBJECTID"), "name": r.get("Name"),
                         "gis_id": r.get("GIS_ID"), "area_m2": area},
            "sources": [src]})
    return out, collapsed


# ── fetch ────────────────────────────────────────────────────────────────────

def publisher_record(pkg: dict, resource_id: str) -> dict:
    """What HDX says about the dataset and the one file read from it."""
    res = next((r for r in pkg.get("resources") or []
                if r.get("id") == resource_id), None)
    if res is None:
        raise ValueError(f"resource {resource_id} is no longer in "
                         f"{pkg.get('name')}: the dataset was rebuilt, look "
                         "before reading another file")
    return {"package": pkg.get("name"), "title": pkg.get("title"),
            "dataset_date": pkg.get("dataset_date"),
            "dataset_source": pkg.get("dataset_source"),
            "license_id": pkg.get("license_id"),
            "license_title": pkg.get("license_title"),
            "methodology": pkg.get("methodology_other") or pkg.get("methodology"),
            "caveats": pkg.get("caveats"), "notes": pkg.get("notes"),
            "resource_name": res.get("name"), "resource_url": res.get("url"),
            "resource_last_modified": res.get("last_modified")}


def vintage_of(pub: dict, page: str) -> dict:
    """HDX dataset_date is '[2018-01-01T00:00:00 TO 2018-01-01T23:59:59]'."""
    span = (pub.get("dataset_date") or "").strip("[]").split(" TO ")
    days = [s[:10] for s in span if s]
    return {"vintage": days[-1] if days else None,
            "vintage_basis": "HDX dataset_date (the period the publisher says "
                             "the data covers); the file itself was last "
                             f"modified {str(pub.get('resource_last_modified'))[:10]}",
            "vintage_url": page}


def _held_last_modified(path: Path) -> str | None:
    try:
        return json.loads(path.read_text())["metadata"]["publisher"][
            "resource_last_modified"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fetch_one(name: str, dry: bool, argv: list[str], get=fl.get,
              sleep=time.sleep) -> int:
    feed = FEEDS[name]
    label = feed["label"]
    try:
        pkg = json.loads(get(API + feed["package"]))["result"]
        pub = publisher_record(pkg, feed["resource"])
        if not dry and pub["resource_last_modified"] and \
                pub["resource_last_modified"] == _held_last_modified(feed["out"]):
            print(f"  ok   {label}  unchanged since "
                  f"{pub['resource_last_modified'][:10]}, nothing downloaded")
            fl.event(label, "ok", unchanged=True,
                     last_modified=pub["resource_last_modified"])
            return 0
        sleep(CRAWL_DELAY)
        raw = get(pub["resource_url"])
        rows = dbf_of(raw)
    except Exception as e:                                   # noqa: BLE001
        print(f"  FAIL {label}: {type(e).__name__}: {e}")
        if not dry:
            fl.event(label, "error", error=f"{type(e).__name__}: {e}"[:200])
        return 1
    fetched_at = datetime.now(timezone.utc).isoformat()
    extra = {}
    if name == "barrier":
        recs = barrier_records(rows, fetched_at)
        extra["v1_defaults_not_from_publisher"] = sorted(
            ["checkpoint.permits_required", "land_type=checkpoint",
             "metrics.count=1"])
    else:
        recs, collapsed = settlement_records(rows, fetched_at)
        extra["polygons_upstream"] = len(rows)
        extra["collapsed_same_name_and_area"] = collapsed
        extra["v1_defaults_not_from_publisher"] = sorted(
            ["land_status", "settlement.legal_status",
             "settlement.settlement_type", "metrics.count=1"])
    if len(recs) < feed["floor"]:
        print(f"  REFUSED {label}: {len(recs)} records below the floor of "
              f"{feed['floor']} — keeping the file already on disk")
        if not dry:
            fl.event(label, "refused", rows=len(recs), floor=feed["floor"])
        return 1
    doc = {"metadata": {
        "fetched_at": fetched_at,
        "source": f"{pub['title']} (HDX, {pub['dataset_source']})",
        "source_url": feed["page"],
        **vintage_of(pub, feed["page"]),
        "license": f"{pub['license_id']}: {pub['license_title']}",
        "publisher": pub, "records": len(recs), **extra},
        "data": recs}
    print(f"  ok   {label}  {len(recs)} records from {len(rows)} features, "
          f"vintage {doc['metadata']['vintage']}, file of "
          f"{str(pub['resource_last_modified'])[:10]}, {pub['license_id']}")
    if dry:
        print(f"         would write {feed['out'].relative_to(fl.ROOT)}  "
              "(dry run, nothing written)")
        fl.stage(fl.stage_dir(argv), feed["out"].name, doc)
        return 0
    from ingest import bronze
    doc["metadata"]["bronze"] = bronze.put(
        feed["bronze"], raw, "zip", url=pub["resource_url"]).ref
    fl.write_atomic(feed["out"], doc)
    fl.event(label, "ok", rows=len(recs),
             last_modified=pub["resource_last_modified"])
    return 0


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    names = [a for a in argv if a in FEEDS] or list(FEEDS)
    rc = 0
    for i, name in enumerate(names):
        if i:
            time.sleep(CRAWL_DELAY)
        rc |= fetch_one(name, dry, argv)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
