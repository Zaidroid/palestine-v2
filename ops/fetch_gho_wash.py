"""Fetch WHO GHO WASH indicators for Palestine — the water category's own feed.

The water recovery (2026-08-06) measured GHO's entire WSH_* universe against
what v1's health fetch already delivers with identity: the six JMP access
codes are at exact row parity (75=75), WHO publishes NO WASH burden
estimates for PSE (WSH_1/3/10 empty), and exactly ONE code with PSE data was
missing — WSH_SANITATION_OD. This fetcher pulls the missing code(s) directly
from the GHO OData API so the water category feeds itself; the code list is
a parameter so a future PSE burden series is one edit away (the weekly
maintenance run may re-probe).

Atomic: writes only on success with a sane row floor; a failed API night
leaves yesterday's file (and the loader's expect floor) intact.

Run: .venv/bin/python -m ops.fetch_gho_wash
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CODES = ["WSH_SANITATION_OD"]
API = "https://ghoapi.azureedge.net/api/{code}?$filter=SpatialDim%20eq%20%27PSE%27"
OUT = Path(__file__).resolve().parent.parent / "data" / "gho" / "wash_pse.json"
MIN_ROWS = 50           # 75 at first fetch; below this the API is lying


def main() -> int:
    rows = []
    for code in CODES:
        with urllib.request.urlopen(API.format(code=code), timeout=60) as r:
            payload = json.load(r)
        got = payload.get("value") or []
        print(f"[GHO] {code}: {len(got)} rows")
        rows.extend(got)
    if len(rows) < MIN_ROWS:
        print(f"[GHO] only {len(rows)} rows (< {MIN_ROWS}) — refusing to "
              "overwrite existing file", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "metadata": {
            "source": "WHO Global Health Observatory OData API",
            "url": "https://ghoapi.azureedge.net/api/",
            "codes": CODES,
            "spatial": "PSE",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "data": rows,
    }, ensure_ascii=False, indent=1))
    tmp.replace(OUT)
    print(f"[GHO] wrote {OUT} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
