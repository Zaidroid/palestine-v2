"""F-05 — the fuel vertical serves from rendered cards now, and these hold the
two properties that make that safe: the promotion is asked for rather than
assumed, and the provenance travels on every row it writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.sources import palhub_fuel_image as loader      # noqa: E402


class _Cur:
    """Just enough cursor to see what a write would carry."""

    def __init__(self):
        self.params = None

    def execute(self, sql, params=None):
        self.params = params


def test_a_bare_run_is_still_quarantined():
    """The promotion has to be reversible BY NUMBER, not by memory: `--serve`
    is what writes an assertion, and the default stays the safe modality."""
    assert loader.MODALITY == "quarantined"
    assert loader.MODALITY_SERVING == "assertion"
    cur = _Cur()
    loader._write(cur, 1, "fuel_diesel", "available", "raw",
                  "2026-09-22T00:00:00Z", 2, {})
    assert cur.params[-2] == "quarantined", "the default is no longer safe"


def test_serve_writes_an_assertion_carrying_its_provenance():
    """A served reading must never be mistakable for a text bulletin's."""
    cur = _Cur()
    loader._write(cur, 1, "fuel_diesel", "available", "raw",
                  "2026-09-22T00:00:00Z", 2,
                  {"basis": "pill", "modality_basis": "image_ocr",
                   "warning": loader.SERVING_WARNING},
                  modality=loader.MODALITY_SERVING)
    assert cur.params[-2] == "assertion"
    assert "image_ocr" in cur.params[-1]
    assert "may be stale or wrong" in cur.params[-1]


def test_the_api_repeats_the_loader_warning_exactly():
    """`serve/` must not import an ingest module, so the warning sentence exists
    twice. This is the thing that keeps the two copies from drifting."""
    from serve import app as api
    assert api.IMAGE_OCR_WARNING == loader.SERVING_WARNING
    assert loader.SERVING_BASIS == "image_ocr"
