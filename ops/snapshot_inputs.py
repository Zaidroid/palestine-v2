"""Snapshot what the loader read today, in the shape the as_of proof expects.

THE PROBLEM THIS SOLVES
v1 archived a copy of every category every night, and that archive is the only
reason `ops/asof_harness.py` can prove `sys_period` tells the truth. Vaulting it
(ops/vault_snapshots.py) preserves 38 days of evidence — but preserves them
frozen. The day v1 is cut, the proof stops growing: every future correction,
supersedence and revision would be unverifiable, and the harness would keep
returning 0 while covering an ever-smaller share of the record.

So v2 archives its own loader inputs, nightly, in v1's exact shape:

    data/evidence/v2-inputs/<day>/<dataset>/stable-id-index.json   {"index": {id: pos}}
    (payload bytes content-addressed in bronze, referenced from the manifest)

`ops/evidence.py` resolves both trees, so `analyze()` and the harness keep
working across the cut without knowing it happened.

Deliberately independent of the loader's internals: it re-resolves each spec's
declared inputs rather than instrumenting `run()`. If the two ever disagree
about what "the input" is, the spec is the answer — and a bug in one cannot
silently corrupt the other's evidence.

Wired into ops/databank-sync.sh AFTER the loader. Non-fatal: a failed snapshot
must never fail the night's ingest, but it is reported and the radar sees it.

Run: .venv/bin/python -m ops.snapshot_inputs
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import bronze                                          # noqa: E402
from ingest.databank import (SPECS, SpecRefused, _records,         # noqa: E402
                             iter_v1_files, load_spec)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "evidence" / "v2-inputs"
MANIFEST = ROOT / "data" / "evidence" / "v2-manifest.json"


def snapshot(day: str | None = None) -> dict:
    day = day or datetime.now(timezone.utc).date().isoformat()
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"entries": {}}
    entries = dict(man.get("entries", {}))

    written = skipped = refused = 0
    for spec_file in sorted(SPECS.glob("*.yaml")):
        category = spec_file.stem
        try:
            spec = load_spec(category)
        except SpecRefused:
            refused += 1                    # skipped/draft specs archive nothing
            continue

        index: dict[str, int] = {}
        payloads: list[bytes] = []
        pos = 0
        for f in iter_v1_files(category, spec):
            payload = f.read_bytes()
            payloads.append(payload)
            for rec in _records(json.loads(payload)):
                if isinstance(rec, dict) and rec.get("stable_id"):
                    index[rec["stable_id"]] = pos
                pos += 1
        if not payloads:
            continue

        key = f"{day}/{category}"
        d = OUT / day / category
        d.mkdir(parents=True, exist_ok=True)
        # v1's exact shape, so ops/evidence.index_ids() needs no special case
        (d / "stable-id-index.json").write_text(
            json.dumps({"index": index, "records": pos}, ensure_ascii=False))

        refs = [str(bronze.put(f"v2input_{category}", p,
                               url=f"file://{spec_file}")) for p in payloads]
        entries[key] = {"data_refs": refs, "records": pos,
                        "indexed": len(index),
                        "source": "v2-loader-input"}
        written += 1

    out = {"snapshotted_at": datetime.now(timezone.utc).isoformat(),
           "days": sorted({k.split("/")[0] for k in entries}),
           "entries": entries}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, sort_keys=True))
    tmp.replace(MANIFEST)
    print(f"snapshot-inputs {day}: {written} datasets archived, "
          f"{refused} specs skipped (draft/migrate:false), "
          f"{len(out['days'])} days of v2 evidence held")
    return out


if __name__ == "__main__":
    snapshot()
