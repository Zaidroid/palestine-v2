"""P1-A.1 — the palhub earn-out by value class (Zaid's decision A, 2026-09-25)."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.sources import palhub_roads as PR                               # noqa: E402
from ops import measure_review as MR, palhub_earnout as PE, watchdog as W   # noqa: E402


def test_open_and_closed_are_asserted_congested_stays_quarantined():
    assert PR.modality_for("open") == "assertion" and PR.modality_for("closed") == "assertion"
    assert PR.modality_for("congested") == "quarantined" and PR.modality_for("slow") == "quarantined"
    assert PR.modality_for("anything-else") == "quarantined"
    assert "modality_for(rd.value)" in inspect.getsource(PR.load)


def test_the_measurements_read_every_palhub_row_whatever_its_modality():
    assert "modality = 'quarantined'" not in MR.ROADS_PAIR_SQL
    assert "modality = 'quarantined'" not in PE.PAIR_SQL


def test_g4_is_recorded_on_every_watchdog_run():
    assert W.EXPECTED_JOBS["coverage"] == (600, 900)
    src = inspect.getsource(W.coverage_check)
    assert "known_fraction" in src and "COVERAGE_LEDGER" in src and "0.60" in src
