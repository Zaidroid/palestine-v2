"""P1-B.6 — the databank cache is keyed on the databank, not on dry runs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import serve.app as A                                                        # noqa: E402


def _write(p: Path, recs):
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))


def test_a_dry_run_does_not_invalidate_and_a_real_write_does(tmp_path, monkeypatch):
    f = tmp_path / "runs.ndjson"
    monkeypatch.setattr(A, "DATABANK_RUNS", f)
    monkeypatch.setattr(A, "_RUNS_SEEN", {"stat": None, "stamp": ""})
    _write(f, [{"ts": "2026-09-25T02:00:00", "dry_run": False, "written": 12}])
    first = A._runs_stamp()
    assert first == "2026-09-25T02:00:00"
    _write(f, [{"ts": "2026-09-25T02:00:00", "dry_run": False, "written": 12},
               {"ts": "2026-09-25T21:17:58", "dry_run": True, "written": 0},
               {"ts": "2026-09-25T21:18:03", "dry_run": False, "written": 0}])
    assert A._runs_stamp() == first          # a dry run and an empty real run change nothing
    _write(f, [{"ts": "2026-09-26T02:00:00", "dry_run": False, "written": 0, "events_written": 3}])
    assert A._runs_stamp() == "2026-09-26T02:00:00"


def test_the_ttl_is_a_bound_not_the_invalidator():
    assert A.CACHE_TTL_SECONDS >= 3600 and A.WATERMARK_SECONDS <= 600
