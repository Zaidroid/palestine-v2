"""Insecurity Insight's Palestine incident data (HDX, CC-BY-SA) — the health care,
explosive weapons, aid worker, education, food system, water system, protection
and sexual-violence incident files, one row per incident with weapon, perpetrator
and victims. Fetched for the databank since 2026-10-11 (Zaid: "the databank is
for personal use, build these as part of it").

    .venv/bin/python -m ops.fetch_insecurity_insight

WHY
v1 has fetched and normalised these files nightly since June (scripts/sources/
insecurity-insight.js → public/data/insecurity-insight/incidents.json, 20,836
incidents 2002-04 → 2026-09 on 2026-10-11) and nothing in v2 ever read them: the
scout file listed the source as "adopted" in August and no spec was written. The
audit of 2026-10-11 found it among nine fragments held outside the databank.

WHAT THIS DOES
Reads v1's normalised file through V1_ROOT (resolve.db.v1_path — the path is
never spelled here), checks it, and writes data/raw/insecurity_insight/
incidents.json atomically with the HDX package's licence stamped beside it.
The direct HDX fetch (twelve xlsx resources with differing columns) is the next
step; until then v1's parser is the parser, and the floor below catches the day
it stops.

POSTURE (ops/fetchlib.py): atomic, floored, ledgered. A short or unreadable file
leaves yesterday's copy in place.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import FetchRefused, check_floor, event, get_json, write_atomic  # noqa: E402
from resolve.db import v1_path  # noqa: E402

PACKAGE = ("https://data.humdata.org/api/3/action/package_show"
           "?id=b36e1975-4428-4caa-9b00-e0d8793130d0")
PAGE = "https://data.humdata.org/dataset/b36e1975-4428-4caa-9b00-e0d8793130d0"
OUT = ROOT / "data" / "raw" / "insecurity_insight" / "incidents.json"
LABEL = "insecurity_insight:incidents"
FLOOR = 15000                 # 20,836 on 2026-10-11; the file only grows
REQUIRED = ("incident_id", "date", "category")


def main(argv: list[str]) -> int:
    src = v1_path("public/data/insecurity-insight/incidents.json")
    try:
        if not Path(src).exists():
            raise FetchRefused(f"{LABEL}: v1's normalised file is absent at V1_ROOT "
                               "— nothing to read; yesterday's copy stands")
        rows = json.loads(Path(src).read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise FetchRefused(f"{LABEL}: v1's file is not a list")
        bad = sum(1 for r in rows if not isinstance(r, dict)
                  or any(not r.get(k) for k in REQUIRED))
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
    licence = {}
    try:                                                    # non-fatal: a stamp, not the data
        pkg = get_json(PACKAGE, timeout=60).get("result", {})
        licence = {"license_id": pkg.get("license_id"),
                   "license_title": pkg.get("license_title"),
                   "hdx_updated": pkg.get("last_modified") or pkg.get("metadata_modified"),
                   "caveats": pkg.get("caveats")}
    except Exception as e:                                  # noqa: BLE001
        licence = {"error": str(e)[:200]}
    write_atomic(OUT, {"fetched_at": datetime.now(timezone.utc).isoformat(),
                       "source": "Insecurity Insight — State of Palestine incident data (HDX)",
                       "url": PAGE, "licence": licence,
                       "read_from": "v1 public/data/insecurity-insight/incidents.json",
                       "data": rows})
    event(LABEL, "ok", rows=len(rows))
    print(f"{LABEL}: {len(rows)} incidents → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
