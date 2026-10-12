"""IDMC's displacement events inside the occupied Palestinian territory, read from
IDMC's own HDX release — and the two refugee datasets nobody fetches, carried
beside it so the `refugees` category keeps loading whole (2026-10-12).

    .venv/bin/python -m ops.fetch_idmc
    .venv/bin/python -m ops.fetch_idmc --dry-run [--stage DIR]

WHY
`refugees` is three datasets v1 merged into one file. IDMC (v1_refugees_idmc,
338 current rows) is the live one: v1's `scripts/sources/idmc.js` read the HDX
package `pse-idmc-idu-events` every night (the old slug, idmc-event-data-for-pse,
answers 404) and `populate-unified-data.js` merged the events into
unified/refugees/all-data.json. The day v1 stops, so does the dataset. This
reads the same CSV and writes the record `t_refugees` already reads.

WHAT v1 ADDED THAT IDMC DOES NOT PUBLISH, AND WHY IT IS KEPT
Each held row carries attrs.admin2, the governorate name v1's
`attach-locations.js` derived by testing the event's point against OCHA's
COD-AB admin-2 polygons. IDMC's CSV has no such column. Leaving it out would
read as 335 revisions (every row superseded to drop one attr), so this fetcher
makes the same test against the same polygons (HDX package cod-ab-pse, the
`pse_admin2` layer, v1's ray-casting rule) and writes location.admin1 /
admin2 / admin2_pcode. The polygons are cached in data/raw/cod_ab/admin2.json
and re-downloaded only when HDX says the file changed; with no cache and no
download the fetch is refused, because records without admin2 are worse than
yesterday's file.
Measured 2026-10-12 against v1's file of the same night: the same 339 event
ids, and on 339 of 339 the same date, name, figure, point, admin2 and pcode
(336 fall in a governorate, 3 in none). The one field that differs,
location.governorate (v1 filled it from its own gazetteer on 123 records), is
read by nothing in t_refugees.

WHAT IS WRITTEN (the spec's two input files)
  data/raw/refugees/idmc.json     IDMC's whole current list, one record a row
  data/raw/refugees/carried.json  the UNHCR (1,157) and UNRWA-camp (75) records
                                  copied unchanged from data/frozen/refugees.json.gz
The second file exists because the loader's fallback fires only when NO input
file is found: a spec that named the frozen corpus beside the fetch would read
1,232 records on a fresh clone and fail its floor. Both files are written, or
neither: carried.json is written only once idmc.json exists, so a machine that
has never fetched still reads the fallback whole.
Neither carried dataset is refreshed by anything. UNHCR's 1,157 rows are a
subset of what unhcr_population_hdx already holds (measured 2026-10-12: the
same refugees and asylum-seeker figures on 1,157 of 1,157 country-years). The
75 "UNRWA camp registry" rows are v1's 2026-06-10 scrape of a Wikipedia table.
Their vintage and honest credit are stamped in carried.json's metadata.

STABLE ID: `idmc-<id>`, IDMC's own figure id (what v1 used as `id`; v1's
stable_id was a hash of its whole record). Rows are matched on the spec's
identity, not on this id.

VINTAGE: the CSV resource's `last_modified` on HDX. The dataset's own date
range and the newest `created_at` in the rows are stamped beside it.

POSTURE (ops/fetchlib.py): atomic, floored (300, the spec's own floor),
ledgered. The CSV is archived in bronze before it is parsed.

LICENCE, read 2026-10-12: HDX states "Creative Commons Attribution for
Intergovernmental Organisations (CC BY-IGO)" for the package; IDMC's own terms
(internal-displacement.org/terms-of-use) allow reuse with acknowledgement "in
line with the Creative Commons – Attribution (BY) 3.0 IGO – license". The
source row `idmc` carries the grade and is not changed here.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sys
import urllib.error
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

CKAN = "https://data.humdata.org/api/3/action/package_show?id="
PACKAGE = "pse-idmc-idu-events"
PAGE = f"https://data.humdata.org/dataset/{PACKAGE}"
ADMIN_PACKAGE = "cod-ab-pse"
ADMIN_LAYER = "pse_admin2.geojson"

RAW = fl.ROOT / "data" / "raw" / "refugees"
OUT = RAW / "idmc.json"
CARRIED = RAW / "carried.json"
ADMIN_CACHE = fl.ROOT / "data" / "raw" / "cod_ab" / "admin2.json"
FROZEN = fl.ROOT / "data" / "frozen" / "refugees.json.gz"
LABEL = "idmc:events"
FLOOR = 300                       # db/mappings/refugees.yaml, IDMC's own floor
STABLE_PREFIX = "idmc-"

# sources[0] as v1 wrote it; the spec routes on `name`.
SOURCE = {"name": "IDMC",
          "organization": "Internal Displacement Monitoring Centre (via HDX)",
          "url": PAGE, "license": "CC-BY-IGO"}

# What the two carried datasets really are (read 2026-10-12; the report of that
# day has the evidence). Stamped into carried.json so the file says it itself.
CARRIED_NOTES = {
    "v1_refugees_unhcr": {
        "source_name": "UNHCR Operational Data Portal",
        "what": "refugees + asylum seekers originating from Palestine, per "
                "country of asylum and year, 2010 to 2025, from UNHCR's "
                "population API as v1 last fetched it",
        "vintage": "2025",
        "vintage_basis": "the newest year in the rows (end-year stocks); the "
                         "API states no update date. UNHCR's HDX release of "
                         "the same stocks was last modified 2026-08-20",
        "vintage_url": "https://api.unhcr.org/population/v1/population/"
                       "?yearFrom=2010&yearTo=2026&coo=GAZ&coa_all=true",
    },
    "v1_refugees_unrwa": {
        "source_name": "UNRWA camp registry",
        "what": "v1's scrape, on 2026-06-10, of three tables on Wikipedia's "
                "'Palestinian refugee camps' page (revision 1356227162 of "
                "2026-05-26): 64 camp rows and 11 rows from two summary tables",
        "vintage": "undated; about 2018 to 2020 for the 64 camp rows, 1990 "
                   "and 2018 for the 11 summary rows",
        "vintage_basis": "the camp table entered Wikipedia on 2020-07-08 "
                         "(revision 966661999), each row citing UNRWA's camp "
                         "profile page, which states no date. Archived "
                         "unrwa.org pages: Rafah read 104,000 on 2017-05-09, "
                         "120,526 on 2018-09-08 and 125,304 (the held value) "
                         "from 2019-06-16; Ein el-Hilweh's 59,660 is 'as of "
                         "June 2018'. Of the summary rows, 6 are the 1990 "
                         "column of the page's history table and 5 are the "
                         "Gaza Strip column of its 2018 table: v1 read the "
                         "sixth cell of every row. No row is a 2026 figure",
        "vintage_url": "https://en.wikipedia.org/w/index.php?"
                       "title=Palestinian_refugee_camps&oldid=1356227162",
        "attribution": "Camp populations as listed in Wikipedia's "
                       "'Palestinian refugee camps' table (revision of "
                       "26 May 2026, CC BY-SA 4.0), copied there in July 2020 "
                       "from UNRWA's camp profile pages: UNRWA's undated "
                       "counts of registered refugees from about 2018 to "
                       "2020, not current populations. Not a UNRWA release.",
    },
}


# ── v1's rules, ported (scripts/sources/idmc.js, populate-unified-data.js
#    processIDMC, utils/location-resolver.js pointToAdmin) ─────────────────────

def parse_csv(raw: bytes) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    # an HXL tag row, if IDMC ever adds one, starts its first cell with '#'
    return [r for r in rows if not str(next(iter(r.values()), "") or "").startswith("#")]


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _int(v) -> int:
    """parseInt(v, 10) or 0: the leading integer of the cell."""
    s = str(v or "").strip()
    digits = ""
    for i, ch in enumerate(s):
        if ch.isdigit() or (i == 0 and ch in "+-"):
            digits += ch
        else:
            break
    try:
        return int(digits)
    except ValueError:
        return 0


def region_from_coords(lat, lon) -> str:
    """v1's two bounding boxes (idmc.js regionFromCoords)."""
    if lat is None or lon is None:
        return "Palestine"
    if 31.20 <= lat <= 31.62 and 34.18 <= lon <= 34.60:
        return "Gaza Strip"
    if 31.30 <= lat <= 32.60 and 34.85 <= lon <= 35.65:
        return "West Bank"
    return "Palestine"


def admin2_features(geojson: dict) -> list[dict]:
    """The admin-2 layer → [{admin1, admin2, pcode, bbox, polys}] in file order."""
    out = []
    for f in geojson.get("features") or []:
        geom, p = f.get("geometry") or {}, f.get("properties") or {}
        polys = [geom["coordinates"]] if geom.get("type") == "Polygon" else geom.get("coordinates") or []
        xs = [pt[0] for poly in polys for pt in poly[0]]
        ys = [pt[1] for poly in polys for pt in poly[0]]
        if not xs:
            continue
        out.append({"admin1": p.get("adm1_name"), "admin2": p.get("adm2_name"),
                    "pcode": p.get("adm2_pcode"),
                    "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    "polys": [[[[pt[0], pt[1]] for pt in ring] for ring in poly]
                              for poly in polys]})
    return out


def _in_ring(ring, x: float, y: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_to_admin(features: list[dict], lat, lon) -> dict | None:
    """First admin-2 polygon holding the point (outer ring, minus holes)."""
    if lat is None or lon is None:
        return None
    for f in features:
        min_x, min_y, max_x, max_y = f["bbox"]
        if lon < min_x or lon > max_x or lat < min_y or lat > max_y:
            continue
        for poly in f["polys"]:
            if not _in_ring(poly[0], lon, lat):
                continue
            if any(_in_ring(hole, lon, lat) for hole in poly[1:]):
                continue
            return {"admin1": f["admin1"], "admin2": f["admin2"],
                    "admin2_pcode": f["pcode"]}
    return None


def event_record(row: dict, features: list[dict], fetched_at: str) -> dict | None:
    """One CSV row → the record t_refugees reads; None when IDMC gave it no id
    or no displacement date (v1's filter)."""
    if not row.get("id") or not row.get("displacement_date"):
        return None
    lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
    figure = _int(row.get("figure"))
    loc = {"name": row.get("locations_name") or "Palestine", "governorate": None,
           "region": region_from_coords(lat, lon), "lat": lat, "lon": lon,
           "precision": "point" if row.get("locations_accuracy") == "Point" else "region"}
    loc.update(point_to_admin(features, lat, lon) or {})
    return {
        "stable_id": f"{STABLE_PREFIX}{row['id']}",
        "id": f"idmc-{row['id']}",
        "date": str(row["displacement_date"])[:10],
        "category": "refugees",
        "event_type": "displacement_event",
        "location": loc,
        "metrics": {"displaced": figure, "affected": figure, "count": figure,
                    "value": figure, "unit": "persons"},
        "displacement_category": row.get("category"),
        "displacement_type": row.get("type"),
        "displacement_subtype": row.get("subtype"),
        "event_name": row.get("event_name"),
        "sources": [dict(SOURCE, url=row.get("source_url") or PAGE,
                         fetched_at=fetched_at)],
        # IDMC's own columns v1 dropped. Not read by the loader.
        "idmc": {k: row.get(k) for k in (
            "id", "event_id", "role", "displacement_type", "qualifier",
            "displacement_start_date", "displacement_end_date", "year",
            "event_start_date", "event_end_date", "sources",
            "locations_accuracy", "locations_type", "displacement_occurred",
            "created_at", "description")},
    }


def build(rows: list[dict], features: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    recs = [r for r in (event_record(row, features, fetched_at) for row in rows) if r]
    days = sorted(r["date"] for r in recs)
    return recs, {
        "rows": len(rows), "records": len(recs),
        "with_admin2": sum(1 for r in recs if r["location"].get("admin2")),
        "data_from": days[0] if days else None,
        "data_through": days[-1] if days else None,
        "newest_row_created_at": max((r["idmc"].get("created_at") or "" for r in recs),
                                     default="") or None,
        "people_displaced": sum(r["metrics"]["displaced"] for r in recs),
    }


# ── OCHA's admin-2 polygons, cached ──────────────────────────────────────────

def admin_polygons(get=fl.get, get_json=fl.get_json,
                   write_cache: bool = True) -> tuple[list[dict], dict]:
    """The cached polygons, refreshed when HDX's file changed. Raises
    FetchRefused when there is neither a cache nor a download. A dry run
    passes write_cache=False and leaves the cache as it found it."""
    cache = json.loads(ADMIN_CACHE.read_text()) if ADMIN_CACHE.exists() else None
    try:
        pkg = get_json(CKAN + ADMIN_PACKAGE, timeout=60)["result"]
        res = next(r for r in pkg.get("resources") or []
                   if "geojson" in (r.get("format") or "").lower())
        if cache and cache["stamp"].get("hdx_modified") == res.get("last_modified"):
            return cache["features"], cache["stamp"]
        z = zipfile.ZipFile(io.BytesIO(get(res["url"], timeout=180)))
        name = next(n for n in z.namelist() if n.lower().endswith(ADMIN_LAYER))
        features = admin2_features(json.loads(z.read(name)))
        if len(features) < 16:
            raise ValueError(f"{len(features)} admin-2 polygons, 16 expected")
        stamp = {"fetched_at": datetime.now(timezone.utc).isoformat(),
                 "source": "OCHA COD-AB, State of Palestine subnational "
                           "administrative boundaries (HDX)",
                 "url": f"https://data.humdata.org/dataset/{ADMIN_PACKAGE}",
                 "resource_url": res["url"], "layer": name,
                 "license": pkg.get("license_title"),
                 "hdx_modified": res.get("last_modified")}
        if write_cache:
            fl.write_atomic(ADMIN_CACHE, {"stamp": stamp, "features": features})
        return features, stamp
    except (urllib.error.URLError, OSError, ValueError, KeyError, StopIteration,
            zipfile.BadZipFile) as e:
        if cache:
            print(f"         admin-2 polygons: HDX did not answer ({type(e).__name__}); "
                  f"using the cache of {cache['stamp'].get('fetched_at', '?')[:10]}")
            return cache["features"], cache["stamp"]
        raise fl.FetchRefused(
            f"{LABEL}: no admin-2 polygons (no cache, and HDX: {type(e).__name__}: "
            f"{str(e)[:120]}) — events without admin2 would supersede every held row")


# ── the datasets nobody fetches ──────────────────────────────────────────────

def _rel(p: Path) -> str:
    return str(p.relative_to(fl.ROOT)) if p.is_relative_to(fl.ROOT) else str(p)


def carried_doc() -> dict | None:
    """The non-IDMC records of the frozen corpus, unchanged, with what they are."""
    if not FROZEN.exists():
        return None
    raw = gzip.decompress(FROZEN.read_bytes())
    recs = [r for r in json.loads(raw).get("data") or []
            if ((r.get("sources") or [{}])[0].get("name")) != SOURCE["name"]]
    by_name: dict[str, int] = {}
    for r in recs:
        n = (r.get("sources") or [{}])[0].get("name")
        by_name[n] = by_name.get(n, 0) + 1
    datasets = {k: dict(v, records=by_name.get(v["source_name"], 0))
                for k, v in CARRIED_NOTES.items()}
    return {"metadata": {
        "carried_from": _rel(FROZEN),
        "frozen_sha256": hashlib.sha256(raw).hexdigest(),
        "why": "no v2 fetcher reads these two datasets; they are copied "
               "unchanged so the refugees spec keeps emitting them and the "
               "loader closes nothing",
        "records": len(recs), "datasets": datasets}, "data": recs}


def ensure_carried() -> int | None:
    """Write carried.json when it is missing, or when the frozen corpus or
    what this file says about it changed. Only ever called once idmc.json
    exists. The file carries no timestamp, so an unchanged night rewrites
    nothing and bronze keeps one copy."""
    doc = carried_doc()
    if doc is None:
        return None
    if CARRIED.exists():
        try:
            if json.loads(CARRIED.read_text()).get("metadata") == doc["metadata"]:
                return doc["metadata"]["records"]
        except ValueError:
            pass
    fl.write_atomic(CARRIED, doc)
    return doc["metadata"]["records"]


# ── the run ──────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    try:
        pkg = fl.get_json(CKAN + PACKAGE, timeout=60)["result"]
        res = next(r for r in pkg.get("resources") or []
                   if (r.get("format") or "").upper() == "CSV")
        body = fl.get(res["url"], timeout=180)
        features, admin_stamp = admin_polygons(write_cache=not dry)
        fetched_at = datetime.now(timezone.utc).isoformat()
        recs, summary = build(parse_csv(body), features, fetched_at)
        if len(recs) < FLOOR:
            raise fl.FetchRefused(
                f"{LABEL}: {len(recs)} events below the floor of {FLOOR} — "
                "keeping the file already on disk")
    except fl.FetchRefused as e:
        if not dry:
            fl.event(LABEL, "refused", why=str(e)[:300])
        print(f"  REFUSED {e}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError, KeyError, StopIteration) as e:
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:300])
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1

    doc = {"metadata": {
        "fetched_at": fetched_at,
        "source": "IDMC Internal Displacement Updates (IDU), State of Palestine (HDX)",
        "organization": "Internal Displacement Monitoring Centre (IDMC)",
        "source_url": PAGE, "resource": res.get("name"), "resource_url": res.get("url"),
        "vintage": res.get("last_modified"),
        "vintage_basis": "HDX `last_modified` of the CSV resource",
        "vintage_url": PAGE,
        "hdx_dataset_date": pkg.get("dataset_date"),
        "license_id": pkg.get("license_id"), "license": pkg.get("license_title"),
        "license_url": "https://www.internal-displacement.org/terms-of-use/",
        "attribution": "Internal Displacement Monitoring Centre (IDMC), "
                       "Internal Displacement Updates, via HDX",
        "admin2_from": admin_stamp,
        **summary}, "data": recs}
    print(f"  ok   {LABEL:<12} {len(recs):>5} events, {summary['data_from']} to "
          f"{summary['data_through']}, HDX file of {str(res.get('last_modified'))[:10]}, "
          f"{summary['with_admin2']} placed in a governorate")
    if dry:
        print(f"         would write {_rel(OUT)} and keep {_rel(CARRIED)} "
              f"in step with {_rel(FROZEN)}")
        fl.stage(staged, OUT.name, doc)
        carried = carried_doc()
        if carried:
            fl.stage(staged, CARRIED.name, carried)
        return 0
    from ingest import bronze
    doc["metadata"]["bronze"] = bronze.put("idmc_idu", body, "csv", url=res["url"]).ref
    fl.write_atomic(OUT, doc)
    n = ensure_carried()
    fl.event(LABEL, "ok", rows=len(recs), data_through=summary["data_through"],
             vintage=res.get("last_modified"), carried=n)
    print(f"         carried {n} UNHCR and UNRWA-camp records beside it")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
