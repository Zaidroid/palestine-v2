"""P2-C.3 — a checkpoint's own history as a databank series; P2-C trend fix."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import app as A                                                  # noqa: E402
from serve import mcp_server as S                                           # noqa: E402


def test_the_share_is_of_reports_and_a_quiet_day_is_zero(monkeypatch):
    from datetime import date
    rows = [{"at": date(2026, 9, 1), "indicator": "checkpoint_flow.reports", "value_num": 10},
            {"at": date(2026, 9, 1), "indicator": "checkpoint_flow.reports.closed", "value_num": 4},
            {"at": date(2026, 9, 2), "indicator": "checkpoint_flow.reports", "value_num": 5}]
    monkeypatch.setattr(A, "q", lambda sql, params=None: rows)
    share = A._movement_series("movement.checkpoint.closed_share", 1630, None, None)
    assert [p["value"] for p in share["points"]] == [0.4, 0.0]
    closed = A._movement_series("movement.checkpoint.closed_reports", 1630, None, None)
    assert [p["value"] for p in closed["points"]] == [4.0, 0.0]
    assert "not of time" in share["attribution"][0]


def test_a_zero_median_still_has_a_direction(monkeypatch):
    pts = [{"at": f"2026-09-{d:02d}", "value": 0.0} for d in range(1, 10)] + \
          [{"at": f"2026-09-{d:02d}", "value": 0.3} for d in range(10, 13)]
    monkeypatch.setattr(S, "api", lambda path, **kw: {"series": [{"points": pts}]} if "compare" in path
                        else {"found": True, "place_id": 1630})
    out = S.trend("movement.checkpoint.closed_share", days=30, place="حوارة")
    assert out["direction"] == "higher" and "أعلى" in out["answer"]


def test_huwara_history_answers_live(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("series", indicators="movement.checkpoint.closed_share",
                             place="Huwara", days=365))
    assert p.get("n", 0) >= 30 and p.get("direction") in ("higher", "lower", "flat")
