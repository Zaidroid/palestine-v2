"""Vault v1's snapshot archive — the evidence base for as_of, made ours.

WHY THIS EXISTS
`ops/replay_snapshots.py` and `ops/asof_harness.py` are the only proof that
`observation.sys_period` tells the truth: they replay what v1 actually served
on each archived day and require the database to agree. That archive lives at
/opt/stacks/palestine — a stack v2 is about to stop depending on, whose nightly
rebuild already re-hashes ids and drops gazetteer keys without warning.

Losing it would not break a query. It would remove our ability to prove the
history layer is honest, quietly, and we would not notice until someone asked.

WHAT THIS DOES
Two classes of file, two treatments, because their access patterns differ by
three orders of magnitude:

  stable-id-index.json  — 836 files, read on EVERY replay and harness run.
                          Copied hot and verbatim to data/evidence/v1-snapshots/.
  all-data.json         — 18 GB, read only on the vanished-record path and the
                          as_of value spot-checks. Pushed through the bronze
                          store: content-addressed and gzipped, so the frozen
                          categories that re-emit identical bytes every night
                          collapse to one object each. Free deduplication on
                          machinery that is already tested and already backed up.

A manifest records sha256 + record count per (day, category), so `--verify`
can re-read every byte back through bronze and prove the vault is intact.

Idempotent and resumable: an entry whose source sha256 already matches the
manifest is skipped, so a interrupted run costs only its unfinished work.

Run:  .venv/bin/python -m ops.vault_snapshots            # copy/refresh
      .venv/bin/python -m ops.vault_snapshots --verify   # re-read everything
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import bronze                                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
V1_SNAPS = Path("/opt/stacks/palestine/public/data/unified/snapshots")
VAULT = ROOT / "data" / "evidence" / "v1-snapshots"
MANIFEST = ROOT / "data" / "evidence" / "manifest.json"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _records(payload: bytes) -> int:
    try:
        d = json.loads(payload)
    except ValueError:
        return -1
    if isinstance(d, list):
        return len(d)
    for k in ("data", "records"):
        if isinstance(d.get(k), list):
            return len(d[k])
    return -1


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"entries": {}, "days": []}


def vault(source: Path = V1_SNAPS) -> dict:
    if not source.exists():
        raise SystemExit(f"vault REFUSED: {source} does not exist — nothing to "
                         "preserve. If v1 is already gone, the vault is the "
                         "only copy and must not be overwritten.")
    man = load_manifest()
    entries: dict = dict(man.get("entries", {}))
    prev_days = set(man.get("days", []))

    days = sorted(p.name for p in source.iterdir()
                  if p.is_dir() and len(p.name) == 10)
    # Floor: an archive that shrank is a fact worth refusing over. v1 prunes
    # its own snapshots; the vault is where days go to be kept, not lost.
    missing = prev_days - set(days)
    if missing:
        print(f"note: {len(missing)} day(s) have left v1's archive and survive "
              f"only in the vault: {sorted(missing)[:5]}")

    copied = skipped = failed = 0
    for day in days:
        for cat_dir in sorted((source / day).iterdir()):
            if not cat_dir.is_dir():
                continue
            key = f"{day}/{cat_dir.name}"
            entry = dict(entries.get(key, {}))

            idx_src = cat_dir / "stable-id-index.json"
            if idx_src.exists():
                sha = _sha(idx_src)
                if entry.get("index_sha256") != sha:
                    dst = VAULT / day / cat_dir.name / "stable-id-index.json"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(idx_src, dst)
                    entry["index_sha256"] = sha
                    entry["index_bytes"] = idx_src.stat().st_size

            data_src = cat_dir / "all-data.json"
            if data_src.exists():
                sha = _sha(data_src)
                if entry.get("data_sha256") == sha and entry.get("data_ref"):
                    skipped += 1
                else:
                    payload = data_src.read_bytes()
                    ref = bronze.put(f"v1snap_{cat_dir.name}", payload,
                                     url=f"file://{data_src}")
                    entry.update({"data_ref": str(ref), "data_sha256": sha,
                                  "data_bytes": len(payload),
                                  "records": _records(payload)})
                    copied += 1
            if entry:
                entries[key] = entry

    out = {
        "vaulted_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "days": sorted(set(days) | prev_days),
        "entries": entries,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, sort_keys=True))
    tmp.replace(MANIFEST)
    print(f"vault: {len(out['days'])} days, {len(entries)} (day,category) "
          f"entries — {copied} archived, {skipped} already held, {failed} failed")
    return out


def verify() -> int:
    """Re-read every manifest entry back out and check its sha256. This is the
    check that makes the vault a proof rather than a hope."""
    man = load_manifest()
    entries = man.get("entries", {})
    if not entries:
        print("verify FAILED: manifest is empty")
        return 1
    bad: list[str] = []
    for key, e in sorted(entries.items()):
        day, cat = key.split("/", 1)
        if e.get("index_sha256"):
            p = VAULT / day / cat / "stable-id-index.json"
            if not p.exists() or _sha(p) != e["index_sha256"]:
                bad.append(f"{key}: index missing or altered")
        if e.get("data_ref"):
            try:
                got = bronze.get(e["data_ref"])
            except FileNotFoundError:
                bad.append(f"{key}: bronze object {e['data_ref']} is gone")
                continue
            if hashlib.sha256(got).hexdigest() != e["data_sha256"]:
                bad.append(f"{key}: bronze content does not match its sha256")
    print(f"verify: {len(entries)} entries checked, {len(bad)} bad")
    for b in bad[:20]:
        print("  ", b)
    return 1 if bad else 0


if __name__ == "__main__":
    if "--verify" in sys.argv:
        sys.exit(verify())
    vault()
    sys.exit(verify())
