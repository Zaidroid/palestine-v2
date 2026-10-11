"""B'Tselem's fatalities database, 2000-10-02 → 2023-09-24, one row per person —
the frozen CSV v1 has carried since June, made readable to the loader.

    .venv/bin/python -m ops.fetch_btselem_file

WHY
11,124 people killed (10,092 Palestinians, 1,029 Israelis), each with the date,
place, district, region, age, gender, citizenship, residence, participation in
hostilities, TYPE OF INJURY, AMMUNITION, who killed them, and a note — the
granular record the databank never held: it served six B'Tselem aggregates. The
scout capped exposure at six rows on 2026-08-06 because B'Tselem's terms call
bulk use "expansive use requiring express written consent". On 2026-10-11 Zaid
decided the databank is for personal use and everything we hold goes in; the
source row stays `no-redistribution`, so the partner and bulk tiers never carry
these rows, and per-row public serving waits for B'Tselem's written answer
(db/scout/letters/btselem_bulk.md).

WHAT THIS DOES
Reads v1's CSV through V1_ROOT (never spelled here), writes
data/raw/btselem/fatalities.json: one JSON record per CSV row, verbatim fields,
plus `seq` = the row's position among rows sharing (name, date_of_event), so two
people the file cannot tell apart (13 such pairs) keep two rows. Idempotent: the
file is frozen upstream, so the output is the same every night; the floor catches
a truncated source.

PROVENANCE (v1 data/historical/README.md): B'Tselem via the public Kaggle
aggregation, mirrored from github.com/EliBrignac/…; validated by v1 against
B'Tselem's published period totals (Cast Lead 98.9%, Protective Edge 97.5%,
Second Intifada 84%). The live database continues past 2023 behind HTTP 429.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import FetchRefused, check_floor, event, write_atomic  # noqa: E402
from resolve.db import v1_path  # noqa: E402

OUT = ROOT / "data" / "raw" / "btselem" / "fatalities.json"
LABEL = "btselem:fatalities_file"
FLOOR = 11000                 # 11,124 rows, frozen
COLUMNS = ("name", "date_of_event", "age", "citizenship", "event_location",
           "event_location_district", "event_location_region", "date_of_death",
           "gender", "took_part_in_the_hostilities", "place_of_residence",
           "place_of_residence_district", "type_of_injury", "ammunition",
           "killed_by", "notes")


def main(argv: list[str]) -> int:
    src = Path(v1_path("data/historical/btselem-fatalities-2000-2023.csv"))
    try:
        if not src.exists():
            raise FetchRefused(f"{LABEL}: v1's CSV is absent at V1_ROOT — yesterday's copy stands")
        with src.open(encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise FetchRefused(f"{LABEL}: CSV lacks columns {missing}")
            rows = [{c: (r.get(c) or "").strip() for c in COLUMNS} for r in reader]
        seen: Counter = Counter()
        for r in rows:
            k = (r["name"], r["date_of_event"])
            r["seq"] = seen[k]
            seen[k] += 1
        bad = sum(1 for r in rows if not r["name"] or len(r["date_of_event"]) != 10)
        if bad:
            raise FetchRefused(f"{LABEL}: {bad} rows lack a name or a day-precision event date")
        check_floor(LABEL, len(rows), FLOOR)
    except FetchRefused as e:
        print(e, file=sys.stderr)
        return 1
    except Exception as e:                                  # noqa: BLE001
        event(LABEL, "error", error=str(e)[:300])
        print(f"{LABEL}: {e}", file=sys.stderr)
        return 1
    write_atomic(OUT, {"fetched_at": datetime.now(timezone.utc).isoformat(),
                       "source": "B'Tselem fatalities database (via the public Kaggle aggregation, frozen in v1)",
                       "url": "https://statistics.btselem.org/",
                       "licence": "LicenseRef-BTselem — bulk use needs written consent; held for personal use, "
                                  "no-redistribution (source row 7856)",
                       "data": rows})
    event(LABEL, "ok", rows=len(rows))
    print(f"{LABEL}: {len(rows)} people → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
