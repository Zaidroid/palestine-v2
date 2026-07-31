"""P0.12 — pipeline run report.

v1's report has 8 tasks reading `{"status": "ok", "records": null}` — success and
no-op are indistinguishable. Here that state cannot be represented: FetchResult
rejects it at construction, and this reporter re-asserts the invariant before
writing, so a bug upstream of it still cannot produce a dishonest report.

Exit code is non-zero when any source failed, so cron/CI notices.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.framework import FetchResult, Status  # noqa: E402
from ingest import bronze                          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "ops" / "pipeline-report.json"


def build(results: Sequence[FetchResult]) -> dict:
    for r in results:
        # Defence in depth: even if a caller hand-builds a result, refuse to
        # write the v1 silent-null shape.
        if r.status is Status.OK and r.records is None:
            raise ValueError(f"{r.source_key}: ok with null records — refusing to write report")

    by = {s: [r for r in results if r.status is s] for s in Status}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            **{s.value: len(by[s]) for s in Status},
            "records_total": sum(r.records or 0 for r in results),
        },
        "sources": [r.to_dict() for r in results],
        "bronze": bronze.stats(),
    }


def write(results: Sequence[FetchResult], path: Path = REPORT) -> int:
    report = build(results)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    s = report["summary"]
    print(f"pipeline: {s['ok']} ok · {s['failed']} failed · {s['skipped']} skipped · "
          f"{s['unchanged']} unchanged · {s['records_total']} records")
    for r in results:
        if r.status is Status.FAILED:
            print(f"  FAILED  {r.source_key}: {r.reason}", file=sys.stderr)
        elif r.schema_drift:
            print(f"  DRIFT   {r.source_key}: {r.schema_drift}", file=sys.stderr)
    return 1 if s["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(write([]))
