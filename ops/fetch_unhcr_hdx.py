"""UNHCR's six population tables for people originating from, or residing in, the
State of Palestine — read straight from UNHCR's HDX release (CC BY-IGO).

    .venv/bin/python -m ops.fetch_unhcr_hdx

WHY (2026-10-11, the fragments decision)
The databank held one UNHCR series: refugees + asylum seekers per country of
asylum, 2010 → 2025, 1,157 rows, through v1's flattened file. UNHCR publishes six
tables on HDX (package unhcr-population-data-for-pse, last modified 2026-08-20):
end-year stocks by category back to 1976, demographics by sex and age band per
asylum country and location, the same for people residing in Palestine, asylum
applications, asylum decisions, and solutions (resettlement, naturalisation,
returns). v1 fetched them all into public/data/displacement and nothing read
them. This fetcher takes them from the publisher; db/mappings/unhcr_population.yaml
loads them.

WHAT IS KEPT
Every row of every table, as written, with a `table` field naming which of the
six it came from. Floors per table catch a short download. Atomic, floored,
ledgered (ops/fetchlib.py); a failed table keeps yesterday's file for that
table only.

LICENCE, read on 2026-10-11 through HDX's CKAN API: "Creative Commons Attribution
for Intergovernmental Organisations (CC BY-IGO)", license_id cc-by-igo. The
source row `unhcr` (CC-BY-4.0, verified at unhcr.org 2026-08-08) already carries
attribution; this release's own grant is recorded in the file stamp.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import FetchRefused, check_floor, event, get, get_json, write_atomic  # noqa: E402

PACKAGE = "https://data.humdata.org/api/3/action/package_show?id=unhcr-population-data-for-pse"
PAGE = "https://data.humdata.org/dataset/unhcr-population-data-for-pse"
OUT = ROOT / "data" / "raw" / "unhcr"
LABEL = "unhcr:hdx"
# table name → (substring of the resource's download URL, floor)
TABLES = {
    "stocks": ("end_year_population_totals_originating", 1500),
    "demographics_originating": ("demographics_originating", 4000),
    "demographics_residing": ("demographics_residing", 5),
    "applications": ("asylum_applications_originating", 1200),
    "decisions": ("asylum_decisions_originating", 1100),
    "solutions": ("solutions_originating", 150),
}


def parse_csv(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    # an HXL tag row, if UNHCR ever adds one, is a row whose first value starts with '#'
    return [r for r in rows if not str(next(iter(r.values()), "")).startswith("#")]


def main(argv: list[str]) -> int:
    try:
        pkg = get_json(PACKAGE, timeout=60).get("result", {})
    except Exception as e:                                  # noqa: BLE001
        event(LABEL, "error", error=f"package_show: {e}"[:300])
        print(f"{LABEL}: package_show failed: {e}", file=sys.stderr)
        return 1
    resources = pkg.get("resources") or []
    stamp = {"fetched_at": datetime.now(timezone.utc).isoformat(),
             "source": "UNHCR — State of Palestine, data on forcibly displaced populations and stateless persons (HDX)",
             "url": PAGE, "license_id": pkg.get("license_id"), "license_title": pkg.get("license_title"),
             "hdx_modified": pkg.get("last_modified") or pkg.get("metadata_modified")}
    failed = 0
    for table, (needle, floor) in TABLES.items():
        label = f"{LABEL}:{table}"
        try:
            res = next((r for r in resources if needle in (r.get("url") or "")), None)
            if res is None:
                raise FetchRefused(f"{label}: no resource whose URL contains {needle!r}; yesterday's file stands")
            rows = parse_csv(get(res["url"], timeout=120))
            for r in rows:
                r["table"] = table
            check_floor(label, len(rows), floor)
        except FetchRefused as e:
            print(e, file=sys.stderr)
            failed += 1
            continue
        except Exception as e:                              # noqa: BLE001
            event(label, "error", error=str(e)[:300])
            print(f"{label}: {e}", file=sys.stderr)
            failed += 1
            continue
        write_atomic(OUT / f"{table}.json", {**stamp, "table": table, "resource": res.get("name"),
                                              "resource_url": res.get("url"), "data": rows})
        event(label, "ok", rows=len(rows))
        print(f"{label}: {len(rows)} rows → {(OUT / (table + '.json')).relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
