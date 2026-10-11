"""ACLED's public monthly aggregates for Palestine (HDX): events and fatalities
per governorate per month for political violence, civilian targeting and
demonstrations — HELD, NEVER SERVED.

    .venv/bin/python -m ops.fetch_acled_file

WHY (2026-10-11, the fragments decision)
v1 has fetched ACLED's three HDX workbooks nightly (scripts/sources/acled-pse.js →
public/data/conflict/acled-pse-*.json, 2,080 rows each: 16 governorates × 130
months) and nothing in v2 held them. These are not ACLED's raw events: they are
the "HRP" aggregates ACLED publishes on HDX by month and admin-2. The scout read
ACLED's EULA on 2026-08-07 ("no direct access to Licensed Content; reorganizing
or dashboarding is explicitly insufficient") and ruled that ACLED is never served
from the databank in any form. That ruling stands: db/mappings/acled_hdx.yaml
loads these rows under the `internal` grade (migration 096), which every serving
view excludes. They exist for Zaid's own analysis and for cross-checking the
news classifier's counts, and for nothing else.

WHAT THIS DOES
Reads v1's three normalised files through V1_ROOT (never spelled here), adds
`family`, floors each, writes data/raw/acled/<family>.json atomically.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import FetchRefused, check_floor, event, write_atomic  # noqa: E402
from resolve.db import v1_path  # noqa: E402

OUT = ROOT / "data" / "raw" / "acled"
LABEL = "acled:hdx_monthly"
FAMILIES = {"political_violence": "acled-pse-political-violence.json",
            "civilian_targeting": "acled-pse-civilian-targeting.json",
            "demonstrations": "acled-pse-demonstrations.json"}
FLOOR = 1500                 # 2,080 per family on 2026-10-11


def main(argv: list[str]) -> int:
    failed = 0
    for family, name in FAMILIES.items():
        label = f"{LABEL}:{family}"
        src = Path(v1_path(f"public/data/conflict/{name}"))
        try:
            if not src.exists():
                raise FetchRefused(f"{label}: v1's file is absent at V1_ROOT — yesterday's copy stands")
            d = json.loads(src.read_text(encoding="utf-8"))
            rows = d.get("rows") if isinstance(d, dict) else None
            if not isinstance(rows, list):
                raise FetchRefused(f"{label}: no `rows` list in v1's file")
            bad = sum(1 for r in rows if not isinstance(r, dict) or not r.get("date_period")
                      or not r.get("admin2_pcode"))
            if bad:
                raise FetchRefused(f"{label}: {bad} rows lack date_period/admin2_pcode")
            for r in rows:
                r["family"] = family
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
        write_atomic(OUT / f"{family}.json", {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "ACLED — HRP monthly aggregates for Palestine (HDX), via v1",
            "source_url": d.get("source_url"), "source_dataset": d.get("source_dataset"),
            "licence": "ACLED Terms of Use — HELD under the internal grade, never served (scout 2026-08-07; 096)",
            "family": family, "data": rows})
        event(label, "ok", rows=len(rows))
        print(f"{label}: {len(rows)} rows → {(OUT / (family + '.json')).relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
