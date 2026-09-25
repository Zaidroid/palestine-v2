"""Give the held conflict events back the names their importer dropped (P1-B.1).

The databank holds 1,163 village depopulation events (Palestine Open Maps, the
1948 Nakba record), 7,712 UCDP conflict events and 262 journalist killings
(Tech4Palestine). When v1's importer could not match a location to a place row
it kept the event and dropped the name: 574 of the villages have no place and
no name, so a list of "the depopulated villages of Ramla district" could not be
said at all. The raw rows are in bronze (attrs.raw_ref) and carry the name,
the 1945 district in the description, and for journalists the person's name.

ADDITIVE ONLY: new keys are merged UNDER the existing attrs (`new || attrs`, so
an existing key always wins), each row is marked `enriched_by`, and the event
versioning trigger keeps the prior row in event_history.

    .venv/bin/python -m ops.backfill_conflict_names            # dry run
    .venv/bin/python -m ops.backfill_conflict_names --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                                                   # noqa: E402
from resolve.db import connect                                              # noqa: E402

DATASETS = ("v1_conflict_palopenmaps", "v1_conflict_ucdp", "v1_conflict_tech4palestine")
MARK = "P1-B.1 2026-09-25: names from attrs.raw_ref"
DISTRICT = re.compile(r"\(([^()]*?) district\)")
JOURNALIST = re.compile(r"Journalist killed:\s*(.+?)\.\s")


def enrich(raw: dict, dataset_key: str) -> dict:
    """The keys this raw row can add. Pure, so it is tested without a DB."""
    loc = raw.get("location") or {}
    desc = raw.get("description") or ""
    out: dict = {}
    if dataset_key == "v1_conflict_tech4palestine":
        m = JOURNALIST.search(desc + " ")
        if m:
            out["name"] = m.group(1).strip()
        # The source carries no date for these: every row reads 2023-10-07,
        # the first day of the war. Served with precision 'unknown' (083).
        out["date_is_placeholder"] = True
    else:
        if loc.get("name"):
            out["name"] = loc["name"]
        m = DISTRICT.search(desc)
        if m and dataset_key == "v1_conflict_palopenmaps":
            out["district_1945"] = m.group(1).strip()
        if loc.get("lat") is not None and loc.get("lon") is not None:
            out["raw_lat"], out["raw_lon"] = loc["lat"], loc["lon"]
    if out:
        out["enriched_by"] = MARK
    return out


def plan(cur) -> tuple[list[tuple[int, dict]], Counter]:
    cur.execute("""SELECT event_id, attrs->>'dataset_key', attrs->>'raw_ref', attrs->>'v1_stable_id', attrs
                     FROM event WHERE attrs->>'dataset_key' = ANY(%s)""", (list(DATASETS),))
    events = cur.fetchall()
    by_ref: dict[str, dict] = {}
    todo, stats = [], Counter()
    for eid, ds, ref, sid, attrs in events:
        if ref not in by_ref:
            rows = next(v for v in json.loads(bronze.get(ref)).values() if isinstance(v, list))
            by_ref[ref] = {r.get("stable_id"): r for r in rows}
        raw = by_ref[ref].get(sid)
        if raw is None:
            stats[f"{ds}:no_raw_row"] += 1
            continue
        new = {k: v for k, v in enrich(raw, ds).items() if k not in (attrs or {})}
        if set(new) <= {"enriched_by"}:
            stats[f"{ds}:nothing_to_add"] += 1
            continue
        todo.append((eid, new))
        stats[f"{ds}:enrich"] += 1
        for k in new:
            stats[f"{ds}:+{k}"] += 1
    return todo, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    with connect() as conn, conn.cursor() as cur:
        todo, stats = plan(cur)
        for k, v in sorted(stats.items()):
            print(f"  {k:<48} {v:>6}")
        if not a.apply:
            print(f"dry run: {len(todo)} events would be enriched (--apply to write)")
            return 0
        for eid, new in todo:
            cur.execute("UPDATE event SET attrs = %s::jsonb || attrs WHERE event_id = %s",
                        (json.dumps(new, ensure_ascii=False), eid))
        conn.commit()
        print(f"enriched {len(todo)} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
