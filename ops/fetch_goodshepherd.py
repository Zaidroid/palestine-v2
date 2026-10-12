"""Fetch the Good Shepherd Collective's daily demolition counts — the v1
supply line `goodshepherd`, as far as the databank reads it (land.demolition).

WHAT THE PUBLISHER GIVES. goodshepherdcollective.org/api/home_demolitions.json
is one JSON object: totals, and `chartData`, one entry per day that had an
incident, over a rolling window of about thirteen months (2025-09-08 to
2026-10-08 on 2026-10-12, 232 days). Each day carries `incidents`,
`structures`, `displacedPeople` and the displaced by men, women, children.
The page beside it says what the data is: "This data only represents
information from UN OCHA, which focuses on the West Bank and East Jerusalem"
and "The data reflects the reporting as of 10.08.2026". So this is OCHA's
demolition record at daily grain, republished; the databank also holds OCHA's
own register (v1_demolitions_ocha_demolitions) by locality and year.

WHAT IS LOADED. One `land.demolition` row a day, value = structures, in the
record shape `t_land` reads (v1's unified record). The window rolls: a day
that leaves it stays in the databank (the dataset's identity is the day, and
nothing here declares the window complete).

ONE NUMBER v1 GOT WRONG, corrected here. v1 computed
`item.structures || ... || 1`, so a day Good Shepherd reports with one
incident and 0 structures (people displaced, nothing demolished) was stored as
1 structure. Two such days are in the window (2026-01-04, 2026-07-26). This
fetcher writes the publisher's 0, and the loader supersedes the two held 1s.

WHAT v1 INVENTED AND THIS KEEPS, SO NOTHING ELSE IS REWRITTEN. Five attributes
on every row are defaults in v1's code and nothing the publisher says:
structure_type "residential", structures_demolished 1 (whatever the count),
reason "Administrative demolition", notification_given true, owner_type
"Private". The region "Palestine" is v1's too (the publisher says West Bank
and East Jerusalem). They are isolated in V1_DEFAULTS and named in the raw
file's metadata; removing them is a decision about 275 held rows, not a
fetcher's.

The publisher's other figures for the day (incidents, people displaced) are
kept in each raw record under `upstream`; the loader does not read them yet.

LICENCE: the site's "Liberation License" (goodshepherdcollective.org/license):
share and adapt for purposes aligned with Palestinian liberation, attribution,
non-commercial, revocable. Source row `goodshepherd`, no redistribution.

Posture (ops/fetchlib.py): atomic, floored, ledgered. One request a night.

Run: .venv/bin/python -m ops.fetch_goodshepherd
     .venv/bin/python -m ops.fetch_goodshepherd --dry-run
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

API = "https://goodshepherdcollective.org/api/home_demolitions.json"
PAGE = "https://goodshepherdcollective.org/data/home_demolitions"
LICENSE_URL = "https://goodshepherdcollective.org/license"
OUT = fl.ROOT / "data" / "raw" / "land" / "demolitions.json"
LABEL = "goodshepherd:demolitions"
SOURCE_NAME = "Good Shepherd Collective"     # exactly as land.yaml routes it

# 232 days measured 2026-10-12 in a window of about thirteen months. Below
# this the answer is not the chart we know.
MIN_DAYS = 150
# v1 kept nothing before this day (its BASELINE_DATE); neither does this.
BASELINE = "2023-10-07"

V1_DEFAULTS = {"structure_type": "residential", "structures_demolished": 1,
               "reason": "Administrative demolition",
               "notification_given": True, "owner_type": "Private"}

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UPSTREAM = ("incidents", "structures", "displacedPeople", "menDisplaced",
             "womenDisplaced", "childrenDisplaced")


def _count(v) -> int | None:
    """A whole, non-negative number, or None. 0 is a number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if v >= 0 and float(v).is_integer() else None


def days(payload: dict) -> list[dict]:
    """The chart's days, oldest first: a real date, a structure count, once."""
    out, seen = [], set()
    for item in (payload or {}).get("chartData") or []:
        day = str(item.get("date") or "")[:10]
        n = _count(item.get("structures"))
        if not _DAY.match(day) or day < BASELINE or n is None or day in seen:
            continue
        seen.add(day)
        out.append({"date": day, "structures": n,
                    **{k: item.get(k) for k in _UPSTREAM if k in item}})
    out.sort(key=lambda d: d["date"])
    return out


def publisher_stamp(payload: dict) -> str | None:
    """`mostRecentTimestamp` is 'MM.DD.YYYY HH:MM:SS'; returned as ISO."""
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4}) (\d{2}:\d{2}:\d{2})$",
                 str((payload or {}).get("mostRecentTimestamp") or ""))
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}T{m.group(4)}" if m else None


def day_records(day_rows: list[dict], fetched_at: str) -> list[dict]:
    """Days → records in the shape t_land reads for a demolition."""
    src = {"name": SOURCE_NAME, "organization": SOURCE_NAME, "url": PAGE,
           "license": "Liberation License (goodshepherdcollective.org/license)",
           "fetched_at": fetched_at}
    recs = []
    for d in day_rows:
        recs.append({
            "stable_id": f"gsc-demolitions:{d['date']}",
            "date": d["date"],
            "event_type": "demolition",
            # the page's title and the row of its table this number is
            "indicator_name": "Home Demolitions — Structures",
            "location": {"name": "Multiple locations", "region": "Palestine"},
            "metrics": {"count": d["structures"], "demolished": d["structures"],
                        "unit": "structures"},
            "land_type": "demolition",
            "land_name": "Multiple locations",
            "land_status": "Unknown",
            "demolition": {"demolition_date": d["date"], **V1_DEFAULTS},
            "upstream": {k: d[k] for k in _UPSTREAM if k in d},
            "sources": [src]})
    return recs


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    try:
        raw = fl.get(API, timeout=60)
        payload = json.loads(raw)
    except Exception as e:                                   # noqa: BLE001
        print(f"  FAIL {LABEL}: {type(e).__name__}: {e}")
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:200])
        return 1
    day_rows = days(payload)
    if len(day_rows) < MIN_DAYS:
        print(f"  REFUSED {LABEL}: {len(day_rows)} days below the floor of "
              f"{MIN_DAYS} — keeping the file already on disk")
        if not dry:
            fl.event(LABEL, "refused", rows=len(day_rows), floor=MIN_DAYS)
        return 1
    fetched_at = datetime.now(timezone.utc).isoformat()
    recs = day_records(day_rows, fetched_at)
    first, last = day_rows[0]["date"], day_rows[-1]["date"]
    newest = str(payload.get("newestDateofincident") or last)[:10]
    zeros = [d["date"] for d in day_rows if d["structures"] == 0]
    print(f"  ok   {LABEL}  {len(recs)} days {first} → {last}, "
          f"{sum(d['structures'] for d in day_rows):,} structures, "
          f"{len(zeros)} day(s) with none")
    doc = {"metadata": {
        "fetched_at": fetched_at,
        "source": "Good Shepherd Collective — Home Demolitions "
                  "(West Bank and East Jerusalem; UN OCHA's record, republished)",
        "source_url": PAGE, "read_url": API,
        "vintage": newest,
        "vintage_basis": "newestDateofincident in the publisher's answer; its "
                         "page says \"The data reflects the reporting as of\" "
                         "that day",
        "vintage_url": API,
        "publisher_built_at": publisher_stamp(payload),
        "window": {"first_day": first, "last_day": last, "days": len(recs)},
        "license": "Liberation License — attribution, non-commercial, "
                   "purpose-conditional, revocable",
        "license_url": LICENSE_URL,
        "attribution": "Demolition counts: Good Shepherd Collective "
                       "(goodshepherdcollective.org), from UN OCHA's data.",
        "days_with_no_structure": zeros,
        "v1_defaults_not_from_publisher": sorted(
            [f"demolition.{k}" for k in V1_DEFAULTS]
            + ["land_name", "land_status", "location.region"])},
        "data": recs}
    if dry:
        print(f"         would write {OUT.relative_to(fl.ROOT)} and 1 bronze "
              "payload under goodshepherd  (dry run, nothing written)")
        fl.stage(fl.stage_dir(argv), OUT.name, doc)
        return 0
    from ingest import bronze
    doc["metadata"]["bronze"] = bronze.put("goodshepherd", raw, "json",
                                           url=API).ref
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=len(recs), data_through=last)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
