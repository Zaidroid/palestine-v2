"""P1-C: usage probes counted apart, local test calls exempt, the shared key
limited per minute, and the key files owner-only."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import mcp_http as H                                            # noqa: E402
from serve import mcp_usage as U                                           # noqa: E402


def test_path_probes_are_counted_apart_never_as_demand():
    assert U.is_probe({"args": {"category": "../../health"}})
    assert U.is_probe({"args": {"category": "a/b"}})
    assert not U.is_probe({"args": {"category": "prisoners"}})
    assert not U.is_probe({"args": {"place": "رام الله/البيرة"}})      # a place may carry a slash


def test_a_local_exempt_call_is_not_recorded(tmp_path, monkeypatch):
    f = tmp_path / "u.ndjson"
    monkeypatch.setattr(U, "LEDGER", f)
    monkeypatch.delenv("MCP_USAGE_EXEMPT", raising=False)
    U.record("about", {}, 5, True, {}, "127.0.0.1", exempt=True)
    assert not f.exists()
    U.record("about", {}, 5, True, {}, "127.0.0.1")
    assert f.exists()


def test_the_shared_key_is_limited_per_minute(monkeypatch):
    monkeypatch.setattr(H, "_MINUTE", {})
    rec = {"name": H.PUBLIC_KEY_NAME}
    assert not any(H._minute_exceeded(rec, 1, now=100.0 + i * 0.1) for i in range(60))
    assert H._minute_exceeded(rec, 1, now=106.0)
    assert not H._minute_exceeded(rec, 1, now=170.0)          # a minute later it opens
    assert not any(H._minute_exceeded({"name": "thaura"}, 1, now=100.0) for _ in range(500))


def test_the_key_files_are_owner_only():
    for p in (Path("/home/zaid/palestine-v2/.keys")).glob("*"):
        mode = stat.S_IMODE(os.stat(p).st_mode)
        assert mode & 0o077 == 0, f"{p.name} is readable beyond its owner ({oct(mode)})"
