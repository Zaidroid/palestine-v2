"""T2.4 — replay v1's retained snapshot days into observation.sys_period.

THE FINDING THAT SHAPED THIS FILE: v1's stable_id is a content hash over the
whole record, so it is not a durable identity. Measured on 2026-08-05:
  - on 2026-07-21 v1 added four empty location fields to every record's
    schema and EVERY stable_id in the corpus flipped (prisoners day-pair
    overlap: 0 of 890) with zero value changes;
  - masquerade categories (culture, education, land's registers,
    infrastructure's HDX rows) embed the fetch day in hashed content, so
    their ids churn DAILY — 82,565 phantom "vanished" education records.
A naive per-id replay would have inserted ~340k superseded rows of pure
hash noise. Instead:

  GENERATIONS. Days are segmented where consecutive index overlap < 50%.
  Inside the latest generation ids are stable and per-id history is exact:
    - a live id first seen mid-generation keeps that day as its validity
      lower bound (a genuine addition — e.g. prisoners' new monthly rows);
    - an id that vanished mid-generation (absent from the latest day and
      from the live table) is a genuine upstream deletion/correction and is
      resurrected with a CLOSED range [first, last+1) — supersedence.
  ACROSS the flip, per-id matching is impossible, so the pre-flip window
  extends a row's lower bound to the oldest snapshot day ONLY when the
  category's daily counts are constant and equal across the flip — proof
  from index sizes alone that nothing was added or removed. Otherwise the
  bound stays at the generation start and the report says why.

  CHURNING categories get no per-id operations at all: their records are
  registers re-stamped daily; identity lives in v2's output key. Their rows
  take the count-stability bound.

The snapshot tree is READ-ONLY production and is never altered. Scope:
observations only. The as_of harness (ops/asof_harness.py) is the proof.

Run: .venv/bin/python -m ops.replay_snapshots [--dry-run]
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from ingest import bronze
from ingest.databank import (Drop, EventRow, INSERT_SQL, PointResolver,
                             TRANSFORMERS, SpecRefused, ensure_datasets,
                             load_places, load_spec)
from resolve.db import connect

SNAPS = Path("/opt/stacks/palestine/public/data/unified/snapshots")
OUT = Path(__file__).resolve().parent / "replay-report.json"


def snapshot_days() -> list[str]:
    return sorted(p.name for p in SNAPS.iterdir()
                  if p.is_dir() and len(p.name) == 10)


def index_ids(day: str, category: str) -> dict[str, int]:
    p = SNAPS / day / category / "stable-id-index.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text()).get("index", {})


def _day_after(d: str) -> str:
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def analyze(category: str, days: list[str]) -> dict | None:
    """Presence, generations, churn — from index files alone."""
    per_day = {d: index_ids(d, category) for d in days}
    per_day = {d: ids for d, ids in per_day.items() if ids}
    if not per_day:
        return None
    dayseq = sorted(per_day)
    gens: list[list[str]] = [[dayseq[0]]]
    for prev, cur in zip(dayseq, dayseq[1:]):
        a, b = set(per_day[prev]), set(per_day[cur])
        if len(a & b) < 0.5 * min(len(a), len(b)):
            gens.append([cur])
        else:
            gens[-1].append(cur)
    latest_gen = gens[-1]
    first: dict[str, str] = {}
    last: dict[str, tuple[str, int]] = {}
    for d in latest_gen:
        for sid, pos in per_day[d].items():
            first.setdefault(sid, d)
            last[sid] = (d, pos)
    n_days = len(latest_gen)
    single = sum(1 for sid in first if first[sid] == last[sid][0])
    churning = n_days > 3 and single > 0.5 * len(first)
    counts = [len(per_day[d]) for d in dayseq]
    stable_counts = len(set(counts)) == 1
    return {
        "dayseq": dayseq, "gens": [g[0] for g in gens],
        "latest_gen": latest_gen, "first": first, "last": last,
        "latest_ids": set(per_day[dayseq[-1]]),
        "churning": churning, "stable_counts": stable_counts,
    }


def replay(dry_run: bool = False) -> dict:
    days = snapshot_days()
    window_start = days[0]
    report: dict = {"window": [days[0], days[-1]], "categories": {}}

    with connect() as conn:
        places = load_places(conn)
        places["_pip"] = PointResolver(conn)
        with conn.cursor() as cur:
            cur.execute("""SELECT source_refs->>'v1_canonical_key', place_id
                           FROM place WHERE source_refs ? 'v1_canonical_key'
                             AND merged_into IS NULL""")
            places["_v1key"] = dict(cur.fetchall())
            cur.execute("SELECT key, commercial_use FROM source")
            places["_commercial"] = dict(cur.fetchall())

        for category, transformer in sorted(TRANSFORMERS.items()):
            try:
                spec = load_spec(category)
            except SpecRefused:
                continue
            a = analyze(category, days)
            if a is None:
                continue
            counts: Counter = Counter()
            gen_start = a["latest_gen"][0]
            # The pre-flip extension: only when index sizes prove nothing
            # was added or removed anywhere in the window.
            base_lower = window_start if a["stable_counts"] else gen_start

            with conn.cursor() as cur:
                cur.execute("""SELECT DISTINCT split_part(o.v1_stable_id, ':', 1)
                               FROM observation o
                               JOIN dataset d ON d.dataset_id = o.dataset_id
                               WHERE d.v1_category = %s
                                 AND o.v1_stable_id IS NOT NULL""", (category,))
                live_ids = {r[0] for r in cur.fetchall()}

            updated = inserted = 0
            if a["churning"]:
                # registers re-hashed daily: uniform bound, no per-id ops
                if not dry_run:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE observation o
                               SET sys_period = tstzrange(%s::date,
                                                          upper(o.sys_period))
                              FROM dataset d
                             WHERE d.dataset_id = o.dataset_id
                               AND d.v1_category = %s
                               AND o.v1_stable_id IS NOT NULL
                               AND lower(o.sys_period) > %s::date""",
                            (base_lower, category, base_lower))
                        updated = cur.rowcount
            else:
                # exact per-id bounds inside the latest generation
                by_lower = defaultdict(list)
                for sid in live_ids & set(a["first"]):
                    lower = a["first"][sid]
                    if lower == gen_start:
                        lower = base_lower
                    by_lower[lower].append(sid)
                if not dry_run:
                    with conn.cursor() as cur:
                        for lower, sids in by_lower.items():
                            cur.execute("""
                                UPDATE observation
                                   SET sys_period = tstzrange(%s::date,
                                                              upper(sys_period))
                                 WHERE split_part(v1_stable_id, ':', 1) = ANY(%s)
                                   AND lower(sys_period) > %s::date""",
                                (lower, sids, lower))
                            updated += cur.rowcount

                # genuine vanishings within the latest generation
                vanished = {sid: (a["first"][sid], *a["last"][sid])
                            for sid in a["first"]
                            if sid not in a["latest_ids"]
                            and sid not in live_ids}
                by_last = defaultdict(list)
                for sid, (frst, lst, pos) in vanished.items():
                    by_last[lst].append((sid, frst, pos))
                if not dry_run and by_last:
                    dataset_ids = ensure_datasets(conn, spec, category)
                for lst, entries in sorted(by_last.items()):
                    f = SNAPS / lst / category / "all-data.json"
                    if not f.exists():
                        counts["missing_snapshot_file"] += len(entries)
                        continue
                    payload = f.read_bytes()
                    ref = bronze.put(f"v1_{category}", payload,
                                     url=f"file://{f}").ref
                    data = json.loads(payload)
                    recs = _recs(data)
                    for sid, frst, pos in entries:
                        if not (0 <= pos < len(recs)) or \
                                recs[pos].get("stable_id") != sid:
                            counts["index_position_mismatch"] += 1
                            continue
                        result = transformer(recs[pos], spec, places, counts)
                        if isinstance(result, Drop):
                            counts[f"vanished_dropped:{result.reason}"] += 1
                            continue
                        lower = base_lower if frst == gen_start else frst
                        for r in result:
                            if isinstance(r, EventRow):
                                counts["vanished_event_skipped"] += 1
                                continue
                            if dry_run:
                                inserted += 1
                                continue
                            with conn.cursor() as cur:
                                cur.execute(INSERT_SQL, {
                                    "dataset_id": dataset_ids[r.dataset_key],
                                    "place_id": r.place_id,
                                    "indicator": r.indicator,
                                    "value_num": r.value_num,
                                    "value_text": r.value_text,
                                    "unit": r.unit,
                                    "occurred_at": r.occurred_at,
                                    "precision": r.precision,
                                    "reported_at": r.reported_at,
                                    "raw_ref": ref,
                                    "v1_stable_id": r.v1_stable_id,
                                    "attrs": json.dumps(r.attrs,
                                                        ensure_ascii=False)})
                                if cur.rowcount:
                                    cur.execute("""
                                        UPDATE observation
                                           SET sys_period = tstzrange(
                                                %s::date, %s::date)
                                         WHERE v1_stable_id = %s
                                           AND dataset_id = %s""",
                                        (lower, _day_after(lst),
                                         r.v1_stable_id,
                                         dataset_ids[r.dataset_key]))
                                    inserted += cur.rowcount
            if not dry_run:
                conn.commit()

            report["categories"][category] = {
                "generations": a["gens"], "churning": a["churning"],
                "stable_counts": a["stable_counts"],
                "base_lower": base_lower,
                "rows_bounded": updated,
                "superseded_rows_inserted": inserted,
                "notes": dict(counts),
            }
            print(f"{category:22s} gens={len(a['gens'])} "
                  f"churn={'Y' if a['churning'] else 'n'} "
                  f"lower={base_lower} bounded={updated:>6} "
                  f"superseded={inserted:>4} {dict(counts) if counts else ''}")

    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return report


def _recs(payload):
    if isinstance(payload, list):
        return payload
    for key in ("data", "records"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


if __name__ == "__main__":
    replay(dry_run="--dry-run" in sys.argv)
