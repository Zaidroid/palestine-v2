"""Fetch IODA's internet-outage detections for Palestine, from IODA.

An internet outage in Gaza is not a technical footnote. It is the interval in
which nothing can be reported — and having it as a dated series beside
casualty and displacement records is what lets someone ask whether a silence
in the record was a silence in the events or a silence in the network.

FOUR ENTITIES, the exact set v1 carried, measured 2026-08-08 across its 998
rows:

    country/PS    245   → region 'Palestine'   (place_id NULL, honestly)
    region/1226   417   → 'Gaza Strip'         (place 1)
    region/4581   180   → 'West Bank'          (place 2)
    asn/12975     156   → 'Palestine'          (Paltel, the national carrier)

IODA also exposes region/4782, "Unknown Region in Palestinian Territories".
v1 never carried it and this does not either — not because its outages are
unreal, but because an outage in an unplaceable region is a row that can never
answer "where", and adding it now would be a change of coverage smuggled in
under a change of plumbing. Left as a decision, not a default.

FOUR DATASOURCES, and they are not redundant: bgp (routes withdrawn),
ping-slash24 (hosts stop answering), merit-nt (darknet traffic disappears),
gtr (Google's own traffic). Each sees a different layer, so the same outage
can appear up to four times — and that is a FEATURE of the record rather than
a duplicate to collapse: two datasources agreeing is corroboration. Identity
keys on all of (entity, start, datasource), which is what keeps them apart.

LICENCE: All Rights Reserved. IODA answers every request with a top-level
`copyright` field saying so, read 2026-08-08 (see 067). The rows stay
QUERYABLE with attribution — returning a credited fact is reporting, not
redistribution — and they are held out of the bulk export until IODA answers
db/scout/letters/ioda.md.

Run: .venv/bin/python -m ops.fetch_ioda
     .venv/bin/python -m ops.fetch_ioda --dry-run
"""
from __future__ import annotations

import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

RAW = fl.ROOT / "data" / "raw" / "ioda"
OUT = RAW / "outages.json"
API = "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events"

# (entityType, entityCode, the region string the spec resolves).
ENTITIES = [
    ("country", "PS", "Palestine"),
    ("region", "1226", "Gaza Strip"),
    ("region", "4581", "West Bank"),
    ("asn", "12975", "Palestine"),        # Paltel
]

# v1's earliest outage is 2022-03-02T07:50Z. Asking from 2022-01-01 covers it
# with room, and IODA simply returns nothing for the empty weeks.
FROM_EPOCH = 1640995200          # 2022-01-01T00:00:00Z

# ~0.9 x v1's 998. Below this, IODA is having a bad day and the file already
# on disk is the better answer.
MIN_ROWS = 900


def fetch(until: int) -> list[dict]:
    out: list[dict] = []
    for etype, code, region in ENTITIES:
        url = (f"{API}?entityType={etype}&entityCode={code}"
               f"&from={FROM_EPOCH}&until={until}")
        for e in (fl.get_json(url).get("data") or []):
            start = e.get("start")
            if start is None or not e.get("datasource"):
                continue
            out.append({
                # v1's own id shape, which was deterministic and derived from
                # the publisher's key — unlike its `stable_id`, which was a
                # content hash and re-minted itself whenever IODA revised a
                # score. This is the good half of v1's identity, kept.
                "id": f"ioda-{etype}-{code}-{start}-{e['datasource']}",
                "entity_type": etype,
                "entity_code": code,
                "region": region,
                "outage_start": datetime.fromtimestamp(
                    start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "date": datetime.fromtimestamp(
                    start, timezone.utc).strftime("%Y-%m-%d"),
                "duration_seconds": e.get("duration"),
                "outage_datasource": e["datasource"],
                "severity_score": e.get("score"),
                "method": e.get("method"),
            })
    out.sort(key=lambda r: (r["outage_start"], r["id"]))
    return out


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    until = int(datetime.now(timezone.utc).timestamp())
    try:
        recs = fetch(until)
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"  FAIL ioda {type(e).__name__}: {e}")
        fl.event("ioda:outages", "error", error=type(e).__name__)
        return 1
    try:
        fl.check_floor("ioda:outages", len(recs), MIN_ROWS)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}")
        return 1
    if not dry:
        fl.write_atomic(OUT, recs)
        fl.stamp(RAW / "_fetched.json",
                 "IODA (api.ioda.inetintel.cc.gatech.edu), Internet "
                 "Intelligence Lab, Georgia Tech",
                 "All Rights Reserved — the API states this on every "
                 "response; verified 2026-08-08. Queryable with attribution, "
                 "withheld from bulk export pending permission.",
                 "Internet outage detection: IODA, Georgia Tech Internet "
                 "Intelligence Lab. Copyright (c) 2021-2025 Georgia Tech "
                 "Research Corporation.",
                 rows=len(recs), entities=[e[0] + "/" + e[1]
                                           for e in ENTITIES])
    fl.event("ioda:outages", "ok", rows=len(recs))
    print(f"  ok   ioda  {len(recs)} outages  {recs[0]['date']} .. "
          f"{recs[-1]['date']}" + ("  (dry run)" if dry else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
