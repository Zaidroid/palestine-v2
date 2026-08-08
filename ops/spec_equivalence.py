"""Prove a refactor changed nothing — field by field, over every record.

Stage 3 replaces 21 hand-written transformers with a spec-driven engine. The
risk is not that it breaks loudly; it is that it emits 205,118 rows that are
subtly, invisibly different — one unit string, one precision, one place that
fell to a coarser rung. No test suite catches that. A byte-for-byte comparison
of every emitted tuple does.

    .venv/bin/python -m ops.spec_equivalence --save            # baseline all
    .venv/bin/python -m ops.spec_equivalence --save education  # baseline one
    .venv/bin/python -m ops.spec_equivalence                   # compare all

TWO ARTIFACTS, because they answer different questions:

  ops/equivalence/<cat>.json.gz   every tuple. 121 MB raw, ~9 MB gzipped, and
                                  GITIGNORED — it exists to make a diff
                                  readable while you work, not to be reviewed.
  ops/equivalence/manifest.json   counts, drops and a sha256 over the
                                  canonical row stream. COMMITTED. This is the
                                  reviewable claim: "these 21 categories emit
                                  exactly these rows". A refactor that changes
                                  one unit string in 205,118 rows changes this
                                  hash, and the diff of this file in a commit
                                  is one line per category.

Re-saving a baseline to turn a red run green is the one way to misuse this.
The diff prints first, and the manifest lands in the commit, so doing it by
accident is hard and doing it deliberately is on the record.

Two numbers are compared before any tuple: records_read and the emitted count.
If those move, the diff below them is noise.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.databank import (EventRow, SpecRefused, TRANSFORMERS,   # noqa: E402
                             load_places, load_spec, PointResolver,
                             transform_all)
from resolve.db import connect                                      # noqa: E402

BASE = Path(__file__).resolve().parent / "equivalence"

# Every field that reaches a database column. raw_ref is excluded: it is a
# bronze content hash, so it changes when v1's bytes change, which is not a
# transform difference. identity_key is excluded too — it is derived after
# the transform, and Gate 6 owns it.
OBS_FIELDS = ("dataset_key", "indicator", "occurred_at", "precision",
              "v1_stable_id", "value_num", "value_text", "unit", "place_id",
              "located", "reported_at", "attrs")
EVENT_FIELDS = ("dataset_key", "event_type", "occurred_at", "precision",
                "v1_stable_id", "place_id", "lat", "lon", "located",
                "confidence", "independent_sources", "metrics", "attrs")


def _tuple(r) -> dict:
    fields = EVENT_FIELDS if isinstance(r, EventRow) else OBS_FIELDS
    out = {}
    for f in fields:
        v = getattr(r, f)
        # attrs/metrics are dicts: canonicalise so key ORDER never reads as a
        # difference, and so a float that became an int does
        out[f] = json.dumps(v, sort_keys=True, ensure_ascii=False, default=str) \
            if isinstance(v, dict) else v
    return out


def capture(category: str) -> dict:
    spec = load_spec(category)
    counts, drops = Counter(), Counter()
    rows: list[dict] = []
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
            cur.execute("""SELECT ST_Y(geom::geometry), ST_X(geom::geometry),
                                  place_id
                           FROM place
                           WHERE geom IS NOT NULL AND merged_into IS NULL
                             AND ST_GeometryType(geom::geometry) = 'ST_Point'
                             AND (attrs->>'historic' = 'mandate-palestine'
                                  OR source_refs ? 'v1_canonical_key')""")
            places["_historic_geo"] = {(f"{a:.5f}", f"{b:.5f}"): pid
                                       for a, b, pid in cur.fetchall()}
        for _f, r in transform_all(category, spec, places, counts, drops):
            rows.append(_tuple(r))
    # Sorted by the row's own identity, never by emission order: a refactor
    # that changes the ORDER of otherwise-identical rows is not a difference,
    # and letting it read as one would bury the differences that matter.
    rows.sort(key=lambda d: (d.get("v1_stable_id") or "",
                             d.get("indicator") or d.get("event_type") or "",
                             str(d.get("occurred_at"))))
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, sort_keys=True, ensure_ascii=False,
                            default=str).encode())
    return {"category": category, "records_read": counts["records_read"],
            "emitted": len(rows), "drops": dict(drops),
            "sha256": h.hexdigest(), "rows": rows}


def digest(cap: dict) -> dict:
    return {k: cap[k] for k in ("records_read", "emitted", "drops", "sha256")}


def compare(old: dict, new: dict, limit: int = 10) -> list[str]:
    diffs = []
    for k in ("records_read", "emitted"):
        if old[k] != new[k]:
            diffs.append(f"{k}: {old[k]} → {new[k]}")
    if old.get("drops") != new.get("drops"):
        diffs.append(f"drops: {old.get('drops')} → {new.get('drops')}")
    if diffs:
        # Counts moved. Per-row diffs against a different-length list are
        # thousands of lines of noise reporting one cause.
        return diffs
    for i, (a, b) in enumerate(zip(old["rows"], new["rows"])):
        for f in a:
            if a[f] != b.get(f):
                diffs.append(f"row {i} ({a.get('v1_stable_id')}) .{f}: "
                             f"{a[f]!r} → {b.get(f)!r}")
                if len(diffs) >= limit:
                    return diffs + [f"… stopped at {limit}"]
    return diffs


MANIFEST = BASE / "manifest.json"


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def main(argv: list[str]) -> int:
    save = "--save" in argv
    wanted = [a for a in argv if not a.startswith("--")] or sorted(TRANSFORMERS)
    BASE.mkdir(exist_ok=True)
    manifest = _load_manifest()
    bad = 0
    for cat in wanted:
        try:
            cur = capture(cat)
        except SpecRefused as e:
            print(f"skip {cat:<24} {e}")
            continue
        path = BASE / f"{cat}.json.gz"
        if save:
            path.write_bytes(gzip.compress(json.dumps(
                cur, ensure_ascii=False, sort_keys=True).encode()))
            manifest[cat] = digest(cur)
            print(f"save {cat:<24} {cur['emitted']:>7} rows from "
                  f"{cur['records_read']} records  {cur['sha256'][:12]}")
            continue
        # The manifest is authoritative — it is the committed claim. The row
        # dump only explains a hash that already disagrees.
        old_digest = manifest.get(cat)
        if not old_digest:
            print(f"MISS {cat:<24} not in manifest — run --save {cat} first")
            bad += 1
            continue
        if old_digest["sha256"] == cur["sha256"]:
            print(f"ok   {cat:<24} {cur['emitted']:>7} rows  "
                  f"{cur['sha256'][:12]}")
            continue
        bad += 1
        if not path.exists():
            print(f"DIFF {cat:<24} hash moved "
                  f"{old_digest['sha256'][:12]} → {cur['sha256'][:12]}, and "
                  "the row dump is gone — re-save the baseline BEFORE the "
                  "change next time; without it there is nothing to diff")
            continue
        diffs = compare(json.loads(gzip.decompress(path.read_bytes())), cur)
        print(f"DIFF {cat:<24} {cur['emitted']:>7} rows  "
              f"{len(diffs)} difference(s)")
        for d in diffs:
            print(f"       {d}")
    if save:
        MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))
        print(f"\nmanifest: {len(manifest)} categories")
    else:
        print(f"\n{bad} category(ies) differ from baseline")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
