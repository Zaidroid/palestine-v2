"""One door to the as_of evidence base, wherever it currently lives.

`ops/replay_snapshots.py` and `ops/asof_harness.py` each hardcoded
/opt/stacks/palestine/.../snapshots. That path is v1's, and v1 is being cut.
This module is the seam: the harnesses' logic is untouched, only the byte
source moves.

Resolution order, deliberately in this direction:
  1. the VAULT (data/evidence) — ours, verified by sha256, in the backup set
  2. v1's live tree — while it still exists, so nothing regresses mid-migration

The vault first, not last: once a day is vaulted it is the authoritative copy,
because v1 prunes and rewrites its own archive and we have watched it re-hash
a whole corpus overnight.

Set PALESTINE_V1_ROOT=/nonexistent to run the unplug test — the harnesses must
stay green reading only the vault. That test is what proves the cut is
survivable before anything is cut.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from ingest import bronze

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "data" / "evidence" / "v1-snapshots"
MANIFEST = ROOT / "data" / "evidence" / "manifest.json"


def v1_snapshots() -> Path:
    root = os.environ.get("PALESTINE_V1_ROOT", "/opt/stacks/palestine")
    return Path(root) / "public" / "data" / "unified" / "snapshots"


@lru_cache(maxsize=1)
def _manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"entries": {}, "days": []}


def snapshot_days() -> list[str]:
    """Every archived day, from both sources — the vault can outlive v1's
    pruning, so the union is the honest answer."""
    days = set(_manifest().get("days", []))
    live = v1_snapshots()
    if live.exists():
        days |= {p.name for p in live.iterdir()
                 if p.is_dir() and len(p.name) == 10}
    return sorted(days)


def index_ids(day: str, category: str) -> dict[str, int]:
    """The stable-id index v1 wrote for that day, or {} if it never existed."""
    p = VAULT / day / category / "stable-id-index.json"
    if not p.exists():
        p = v1_snapshots() / day / category / "stable-id-index.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text()).get("index", {})


def snapshot_ref(day: str, category: str) -> str:
    """The provenance pointer for a day's records — the vault's bronze ref when
    we hold it, else a file:// URL naming where the bytes were read."""
    entry = _manifest().get("entries", {}).get(f"{day}/{category}", {})
    if entry.get("data_ref"):
        return entry["data_ref"]
    return f"file://{v1_snapshots() / day / category / 'all-data.json'}"


def open_snapshot(day: str, category: str) -> list:
    """The records v1 served that day, from bronze or the live tree.

    Returns [] when the day was never archived — the same shape the harnesses
    already handle, so "no evidence" stays distinguishable from "no records".
    """
    entry = _manifest().get("entries", {}).get(f"{day}/{category}", {})
    payload = None
    if entry.get("data_ref"):
        try:
            payload = bronze.get(entry["data_ref"])
        except FileNotFoundError:
            payload = None                     # fall through; --verify reports it
    if payload is None:
        f = v1_snapshots() / day / category / "all-data.json"
        if not f.exists():
            return []
        payload = f.read_bytes()
    d = json.loads(payload)
    if isinstance(d, list):
        return d
    for k in ("data", "records"):
        if isinstance(d.get(k), list):
            return d[k]
    return []
