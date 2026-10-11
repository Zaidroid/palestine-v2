"""FAO's Data in Emergencies Monitoring (DIEM) household surveys for Palestine —
governorate-level aggregates per survey round, four thematic files (food
security, income shocks and needs, crop production, livestock production).

    .venv/bin/python -m ops.fetch_fao_diem

WHY (2026-10-11, the fragments decision)
v1 fetched the four HDX CSVs nightly into public/data/indicators (31 Palestine
rows each: 11 West Bank governorates and the Gaza governorates across survey
rounds since 2024) and nothing read them; the scout file listed FAO DIEM as a
candidate in August. These are the only household-survey figures on food
insecurity, income shocks, crop and livestock loss by governorate that the
databank can hold; db/mappings/fao_diem.yaml fans each row's indicators out.

WHAT IS KEPT
Only rows whose adm0_iso3 is PSE (the files are global, ~2,700 rows each), every
column as written, with a `theme` field. Floors per file. Atomic, floored,
ledgered (ops/fetchlib.py).

LICENCE, read on 2026-10-11 through HDX's CKAN API: HDX lists the package licence
as "Other" (hdx-other). FAO's own DIEM terms were not read; the source row
(migration 094) is therefore `ask`, commercial_use = false, and the rows are
withheld from the partner and bulk tiers until the terms are read.
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

PACKAGE = "https://data.humdata.org/api/3/action/package_show?id=e9942071-bf80-4216-9175-044720b82e6f"
PAGE = "https://data.humdata.org/dataset/e9942071-bf80-4216-9175-044720b82e6f"
OUT = ROOT / "data" / "raw" / "fao_diem"
LABEL = "fao_diem"
THEMES = {                      # theme → substring of the resource URL
    "food_security": "food_security",
    "income_shocks": "income__shocks",     # HDX spells the file with a double underscore
    "crop_production": "crop_production",
    "livestock_production": "livestock_production",
}
FLOOR = 20                      # 31 Palestine rows per theme on 2026-10-11


def main(argv: list[str]) -> int:
    try:
        pkg = get_json(PACKAGE, timeout=60).get("result", {})
    except Exception as e:                                  # noqa: BLE001
        event(LABEL, "error", error=f"package_show: {e}"[:300])
        print(f"{LABEL}: package_show failed: {e}", file=sys.stderr)
        return 1
    resources = pkg.get("resources") or []
    stamp = {"fetched_at": datetime.now(timezone.utc).isoformat(),
             "source": "FAO Data in Emergencies Monitoring System (DIEM), household surveys, aggregated (HDX)",
             "url": PAGE, "license_id": pkg.get("license_id"), "license_title": pkg.get("license_title"),
             "hdx_modified": pkg.get("last_modified") or pkg.get("metadata_modified")}
    failed = 0
    for theme, needle in THEMES.items():
        label = f"{LABEL}:{theme}"
        try:
            res = next((r for r in resources if needle in (r.get("url") or "")), None)
            if res is None:
                raise FetchRefused(f"{label}: no resource whose URL contains {needle!r}; yesterday's file stands")
            text = get(res["url"], timeout=180).decode("utf-8-sig")
            rows = [r for r in csv.DictReader(io.StringIO(text)) if r.get("adm0_iso3") == "PSE"]
            for r in rows:
                r["theme"] = theme
            check_floor(label, len(rows), FLOOR)
        except FetchRefused as e:
            print(e, file=sys.stderr)
            failed += 1
            continue
        except Exception as e:                              # noqa: BLE001
            event(label, "error", error=str(e)[:300])
            print(f"{label}: {e}", file=sys.stderr)
            failed += 1
            continue
        write_atomic(OUT / f"{theme}.json", {**stamp, "theme": theme, "resource": res.get("name"),
                                              "resource_url": res.get("url"), "data": rows})
        event(label, "ok", rows=len(rows))
        print(f"{label}: {len(rows)} Palestine rows → {(OUT / (theme + '.json')).relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
