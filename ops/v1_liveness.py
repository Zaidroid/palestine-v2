"""Which v1 categories still receive data, and which merely get rebuilt.

Stage 7 has to decide, per category, between FREEZE (vault the last good
file, read it locally, never touch v1 again) and RE-FETCH (write a v2 fetcher
against the upstream's own API). Getting that wrong in either direction is
expensive: freezing a live series stops the record, and re-fetching a dead
one is a fetcher nobody needs and a nightly job that fails forever.

THE OBVIOUS TESTS BOTH LIE.

  File mtimes say every category is fresh. v1 rewrites all of them nightly.
  That is the June-9 lesson: casualties sat frozen for 57 days behind a file
  whose mtime was always yesterday.

  Stable-id sets say every category churns 100%. v1's `stable_id` is a
  CONTENT HASH re-derived on every rebuild, so the entire id set is replaced
  whether or not a single fact changed. Measured across all 22 categories and
  38 vaulted days: total churn everywhere, signal nowhere.

WHAT ACTUALLY WORKS is to hash the publisher's content with v1's own
bookkeeping removed. Diffing one education record across 38 days shows
exactly five fields differing on 100% of records, and every one belongs to v1
rather than to the source:

    stable_id         v1's content hash, re-derived each rebuild
    sources           carries fetched_at
    date              the ingest stamp (law 1's masquerade)
    temporal_context  derived from that stamp
    location          v1's geo enrichment, which flaps on and off entirely
                      (see ops/v1_field_health.py)

Strip those and education is byte-identical across 38 days: 2,359 records,
same names, same coordinates, same statuses. It is frozen in fact and has
been republished daily anyway.

Run:  .venv/bin/python -m ops.v1_liveness
      .venv/bin/python -m ops.v1_liveness --json
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import evidence                                        # noqa: E402

V1_UNIFIED = Path("/opt/stacks/palestine/public/data/unified")  # READ-ONLY

# v1's own bookkeeping, not the publisher's data. Every one of these was
# measured to differ on 100% of records between any two rebuilds.
V1_VOLATILE = ("stable_id", "id", "sources", "date", "temporal_context",
               "location", "last_updated", "fetched_at")

MIN_AVAILABLE_MB = 2048


def _available_mb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return 1 << 30


def _records(snap):
    if snap is None:
        return []
    return snap if isinstance(snap, list) else (snap.get("data") or [])


def fingerprints(recs: list) -> collections.Counter:
    """A multiset of per-record content hashes, v1's churn removed.

    A multiset rather than a set: two records that are genuinely identical
    (v1 does emit those) must count twice, or a category would look like it
    shrank every time a duplicate appeared.
    """
    c: collections.Counter = collections.Counter()
    for r in recs:
        body = {k: v for k, v in r.items() if k not in V1_VOLATILE}
        c[hashlib.sha256(json.dumps(body, sort_keys=True,
                                    ensure_ascii=False).encode()
                         ).hexdigest()] += 1
    return c


def measure(n_days: int = 4) -> dict:
    days = evidence.snapshot_days()
    step = max(1, (len(days) - 1) // max(1, n_days - 1))
    sample = sorted({days[0], *days[::step], days[-1]})
    out: dict[str, dict] = {}
    for cat_dir in sorted(p for p in V1_UNIFIED.iterdir() if p.is_dir()):
        cat = cat_dir.name
        if not (cat_dir / "all-data.json").exists():
            continue
        if _available_mb() < MIN_AVAILABLE_MB:
            out.setdefault("_skipped", []).append(cat)
            continue
        series = []
        for d in sample:
            try:
                recs = _records(evidence.open_snapshot(d, cat))
            except Exception:
                continue
            if recs:
                series.append((d, fingerprints(recs)))
        if len(series) < 2:
            continue
        live = fingerprints(_records(
            json.loads((cat_dir / "all-data.json").read_text())))
        series.append(("today", live))

        (d0, f0), (dn, fn) = series[0], series[-1]
        added = sum((fn - f0).values())
        gone = sum((f0 - fn).values())
        # Frozen: the publisher's content has not moved once across the whole
        # window, however many times v1 rewrote the file.
        moved = any(a[1] != b[1] for a, b in zip(series, series[1:]))
        out[cat] = {
            "from": d0, "to": dn, "rows_then": sum(f0.values()),
            "rows_now": sum(fn.values()), "added": added, "gone": gone,
            "verdict": "FROZEN" if not moved else
                       ("GROWING" if added and not gone else "REVISED"),
        }
    return out


def main(argv: list[str]) -> int:
    r = measure()
    skipped = r.pop("_skipped", [])
    if "--json" in argv:
        print(json.dumps(r, indent=1, sort_keys=True))
        return 0
    print(f"  {'category':<24}{'then':>8}{'now':>8}{'added':>7}{'gone':>7}"
          "  verdict")
    for cat, d in sorted(r.items(), key=lambda kv: (kv[1]["verdict"], kv[0])):
        print(f"  {cat:<24}{d['rows_then']:>8}{d['rows_now']:>8}"
              f"{d['added']:>7}{d['gone']:>7}  {d['verdict']}")
    frozen = [c for c, d in r.items() if d["verdict"] == "FROZEN"]
    print(f"\n  {len(frozen)} category(ies) FROZEN — the publisher's content "
          "has not changed once across the vault, however often v1 rewrote "
          f"the file:\n    {', '.join(sorted(frozen)) or '(none)'}")
    print("\n  These are the Stage 7 freeze candidates: vault the last good "
          "file, point the spec's `input:` at it, and stop reading v1 for "
          "them entirely.")
    if skipped:
        print(f"\n  NOT MEASURED, too little free memory: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
