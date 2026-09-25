"""P2-C.1 — what happened near a checkpoint in the same hours, said as
co-occurrence; and a TypeError inside a tool is a system error, not the
caller's (2026-09-26)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import mcp_en as EN                                               # noqa: E402
from serve import mcp_server as S                                            # noqa: E402


def _payload(related):
    return {"found": True, "query": "زيف", "match": {"resolved_to": "زيف يطا", "score": 1.0},
            "name": "زيف يطا", "name_en": "Zif (Yatta Road)", "direction": "both", "flow": "closed",
            "passable": False, "last_known_flow": "closed", "age_minutes": 3, "staleness_band": "live",
            "present": [], "by_direction": {}, "related": related}


def test_a_nearby_incident_is_spoken_as_cooccurrence(monkeypatch):
    rel = [{"type": "shooting", "name": "مخيم الفوار", "name_en": "Al-Fawwar Camp",
            "metres": 600, "age_minutes": 120, "relation": "co-occurrence"}]
    monkeypatch.setattr(S, "api", lambda path, **kw: _payload(rel))
    out = S.checkpoint_status("زيف")
    assert "إطلاق نار بمخيم الفوار (قبل ساعتين، 0.6 كم)" in out["answer"]
    assert "مش بالضرورة السبب" in out["answer"]
    en = EN.checkpoint_status(out)
    assert "shooting in Al-Fawwar Camp (2h ago, 0.6 km)" in en and "not necessarily the cause" in en


def test_nothing_nearby_says_nothing(monkeypatch):
    monkeypatch.setattr(S, "api", lambda path, **kw: _payload([]))
    out = S.checkpoint_status("زيف")
    assert "قريب منه" not in out["answer"] and "Near it" not in EN.checkpoint_status(out)


def test_an_internal_type_error_is_not_blamed_on_the_caller(monkeypatch):
    from serve import mcp_http as H

    def broken(name, direction="both"):
        return None + 1                                    # our bug, a TypeError

    monkeypatch.setitem(H.PUBLIC_TOOLS, "checkpoint_status",
                        (broken,) + tuple(H.PUBLIC_TOOLS["checkpoint_status"][1:]))
    r = H._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "checkpoint_status", "arguments": {"name": "x"}}}, None, "partner")
    out = json.loads(r["result"]["content"][0]["text"])
    assert out["answer"] == "صار خطأ بالنظام." and "accepts" not in out
    r = H._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "checkpoint_status", "arguments": {"bogus": 1}}}, None, "partner")
    assert "accepts" in json.loads(r["result"]["content"][0]["text"])
