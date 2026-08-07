"""The as_of evidence base must outlive v1, and must say so honestly.

WHY THIS FILE EXISTS
`ops/asof_harness.py` is the only proof that `observation.sys_period` tells the
truth, and until 2026-08-07 it read that proof from v1's snapshot tree — a
stack v2 is cutting, whose nightly rebuild has already re-hashed a whole corpus
and dropped 516 gazetteer keys without warning. The vault (ops/vault_snapshots)
copies the evidence; ops/evidence.py is the seam that lets the harnesses read
it; ops/snapshot_inputs.py keeps it GROWING after the cut.

The failure this guards is quiet: nothing breaks when the evidence stops
growing. Queries keep answering, the harness keeps returning 0, and the share
of history it actually covers shrinks every night until it means nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "evidence" / "manifest.json"
V2_MANIFEST = ROOT / "data" / "evidence" / "v2-manifest.json"

needs_vault = pytest.mark.skipif(
    not MANIFEST.exists(), reason="vault not built on this machine")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


@needs_vault
def test_vault_covers_the_whole_archive(manifest) -> None:
    """35 days existed when Tier 2 started (2026-06-25 onward). The vault is
    where days go to be KEPT — its count may exceed v1's (v1 prunes; we do
    not) but it must never be short."""
    days = manifest["days"]
    assert len(days) >= 35, f"vault holds only {len(days)} days"
    assert days[0] == "2026-06-25"


@needs_vault
def test_every_vault_entry_carries_its_evidence(manifest) -> None:
    """A manifest entry with no sha256 cannot be verified, which makes it a
    claim rather than a proof."""
    thin = [k for k, e in manifest["entries"].items()
            if not (e.get("index_sha256") or e.get("data_sha256"))]
    assert not thin, f"entries with no checksum: {thin[:5]}"


@needs_vault
def test_vault_verifies_end_to_end() -> None:
    """The real test: read every byte back out of bronze and re-check its
    hash. Slow by nature and worth it — this is the assertion that turns the
    vault from a copy into a proof."""
    from ops import vault_snapshots
    assert vault_snapshots.verify() == 0


@needs_vault
def test_evidence_resolves_without_v1(monkeypatch, manifest) -> None:
    """THE UNPLUG TEST, in miniature: with v1's path pointed at nothing, the
    accessors must still return the archived day. This is what proves the cut
    is survivable — asserted before anything is cut."""
    from ops import evidence

    monkeypatch.setenv("PALESTINE_V1_ROOT", "/nonexistent-v1")
    day, category = sorted(manifest["entries"])[0].split("/", 1)

    assert day in evidence.snapshot_days()
    idx = evidence.index_ids(day, category)
    recs = evidence.open_snapshot(day, category)
    assert idx or recs, f"{day}/{category} resolved to nothing without v1"
    if recs:
        assert isinstance(recs, list) and isinstance(recs[0], dict)
    assert evidence.snapshot_ref(day, category).startswith("bronze://")


def test_v2_archives_its_own_inputs() -> None:
    """After the cut, v2's own loader inputs ARE the evidence base. If this
    file stops appearing, the proof stops growing — silently."""
    if not V2_MANIFEST.exists():
        pytest.skip("snapshot_inputs has not run on this machine")
    man = json.loads(V2_MANIFEST.read_text())
    assert man["days"], "v2 evidence manifest holds no days"
    entries = man["entries"]
    assert len(entries) >= 15, f"only {len(entries)} datasets archived"
    # the index must be usable, not merely present
    for key, e in list(entries.items())[:3]:
        day, cat = key.split("/", 1)
        p = ROOT / "data" / "evidence" / "v2-inputs" / day / cat / "stable-id-index.json"
        assert p.exists(), f"{key} has a manifest entry but no index file"
        idx = json.loads(p.read_text())
        assert "index" in idx and idx["records"] >= len(idx["index"])
