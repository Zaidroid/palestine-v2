"""Freeze a dead v1 corpus into this repository, and stop reading v1 for it.

The first half of the Stage 7 cut, and the safe half: seven categories whose
CONTENT has not changed once across 38 vaulted days, however many times v1
rewrote the file. ops/v1_liveness.py measures which, by hashing the
publisher's fields with v1's own churn removed (its re-derived stable_id, its
ingest stamp, its flapping geo enrichment).

Freezing means: copy the last good file into `data/frozen/`, point the spec's
`input:` at it, and never touch v1 for that category again. The corpus is
finished, so there is nothing to lose and one whole class of failure to shed
— the id re-hash, the geo flap and the silent 57-day stall all become
impossible for these categories rather than merely guarded.

IT ALSO MAKES THE REPOSITORY RUNNABLE. 92 MB of aid_access is 2.5 MB
gzipped, and all seven together are 3 MB — small enough to commit, which
means someone who clones this can load 61,977 real observations without
access to a server they will never have. That is the difference between
open-source code and an open-source project.

Every frozen file records what it is: the day it was taken, its sha256, its
row count, and the liveness evidence that justified freezing it. A frozen
corpus that nobody can audit is just a stale copy.

Run:  .venv/bin/python -m ops.freeze_corpus                 # show the plan
      .venv/bin/python -m ops.freeze_corpus --apply
      .venv/bin/python -m ops.freeze_corpus --verify        # re-check hashes
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resolve.db import v1_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "data" / "frozen"
MANIFEST = FROZEN / "manifest.json"
V1_UNIFIED = v1_path("public/data/unified")   # READ-ONLY

# Measured FROZEN by ops/v1_liveness.py on 2026-08-08 across the vault's 38
# days: content identical at both ends and at every sample in between. Listed
# explicitly rather than computed at run time, because freezing a category is
# a decision — if the measurement changes, a human should see the diff.
FREEZE = {
    "aid_access":     "UNRWA Gaza aid-truck consignments. Upstream stopped; "
                      "un2720 is the live successor (see verdicts.yaml).",
    "casualties":     "OCHA oPt casualty aggregates. Static since 2026-01.",
    "demolitions":    "OCHA oPt demolition register. Static.",
    "education":      "West Bank school register (OCHA oPt via HDX). A "
                      "register, not a series — 2,359 rows, unchanged.",
    "historical":     "Palestine Open Maps Mandate-era gazetteer and the "
                      "1922-1947 record. Closed by definition.",
    "infrastructure": "Barrier segments, locality records and UNOSAT damage "
                      "assessments. Static.",
    "westbank":       "migrate:false (duplicates education), frozen for "
                      "completeness so no category still reads v1 by accident.",
}


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    verify = "--verify" in argv
    FROZEN.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}

    if verify:
        bad = 0
        for cat, m in sorted(manifest.items()):
            p = FROZEN / m["file"]
            if not p.exists():
                print(f"  MISSING {cat}: {m['file']}")
                bad += 1
                continue
            raw = gzip.decompress(p.read_bytes())
            ok = _digest(raw) == m["sha256_uncompressed"]
            n = len(json.loads(raw).get("data") or [])
            ok_n = n == m["records"]
            print(f"  {'ok  ' if ok and ok_n else 'BAD '} {cat:<16} "
                  f"{n:>7} records  {m['sha256_uncompressed'][:12]}")
            bad += not (ok and ok_n)
        print(f"\n{bad} problem(s)")
        return 1 if bad else 0

    total_gz = 0
    for cat, why in sorted(FREEZE.items()):
        src = V1_UNIFIED / cat / "all-data.json"
        if not src.exists():
            print(f"  SKIP {cat}: no all-data.json in v1")
            continue
        raw = src.read_bytes()
        payload = json.loads(raw)
        n = len(payload.get("data") or [])
        gz = gzip.compress(raw, 9)
        total_gz += len(gz)
        prev = manifest.get(cat)
        changed = prev and prev["sha256_uncompressed"] != _digest(raw)
        note = ("  <-- CONTENT CHANGED since the last freeze; a frozen "
                "corpus that moves is not frozen, look before applying"
                if changed else "")
        print(f"  {cat:<16} {n:>7} records  {len(gz)/1048576:>5.1f} MB gz{note}")
        if apply:
            (FROZEN / f"{cat}.json.gz").write_bytes(gz)
            manifest[cat] = {
                "file": f"{cat}.json.gz",
                "records": n,
                "sha256_uncompressed": _digest(raw),
                "bytes_uncompressed": len(raw),
                "bytes_gzipped": len(gz),
                "frozen_at": f"{datetime.now(timezone.utc):%Y-%m-%d}",
                "v1_path": str(src),
                "why": why,
                "evidence": "ops/v1_liveness.py, 2026-08-08: content "
                            "identical across all 38 vaulted days with v1's "
                            "own churn fields removed (stable_id, sources, "
                            "date, temporal_context, location).",
            }
    if apply:
        MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))
        print(f"\n  wrote {len(manifest)} frozen corpora, "
              f"{total_gz/1048576:.1f} MB total — small enough to commit, "
              "which is what makes a fresh clone able to load them")
    else:
        print(f"\n  {total_gz/1048576:.1f} MB total (--apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
