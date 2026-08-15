"""The MCP surface that strangers can reach.

    ./.venv/bin/python -m pytest tests/test_mcp_http.py -q

The stdio server is spoken to by processes already on this host. The HTTP one
is spoken to by anybody with the URL, and the difference is the whole subject of
this file: what is on the menu, what is not, and what a caller can talk the
server into doing with a string.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import mcp_http as m                                  # noqa: E402
from serve import mcp_server as s                                # noqa: E402
from serve import ratelimit as rl                                # noqa: E402


def call(name, **args):
    return m._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": name, "arguments": args}})


# ── what is on the menu ──────────────────────────────────────────────────────

def test_the_ops_tools_are_not_served_over_http():
    """They report the health of THIS MACHINE — failing units, feed faults, the
    maintenance ledger. Over stdio the caller is already on the host. Over the
    open internet it is infrastructure detail answering a question nobody
    outside asked."""
    listed = {t["name"] for t in m._tool_list()}
    assert "system_health" not in listed
    assert "ops_digest" not in listed
    assert listed == set(s.TOOLS) - m.PRIVATE


def test_a_hidden_tool_cannot_be_called_by_name_either():
    """Absent from tools/list is not the same as unreachable. A client that
    learned the name elsewhere must still be refused."""
    err = call("system_health")["error"]
    assert err["code"] == -32601


def test_there_is_no_write_path():
    """Read surface at parity, write surface human. An agent that can file
    reports is the sock-puppet problem at machine speed."""
    listed = " ".join(m.PUBLIC_TOOLS)
    assert "report" not in listed and "register" not in listed


# ── what a caller can do with a string ───────────────────────────────────────

def test_a_category_cannot_walk_out_of_the_databank():
    """`databank(category=...)` is the one caller string that becomes part of a
    URL PATH. Before this was checked, '../../health' reached a different
    endpoint entirely and only failed on the shape of what came back."""
    out = call("databank", category="../../health")
    body = out["result"]["content"][0]["text"]
    assert "error" in body and "category must be" in body


@pytest.mark.parametrize("bad", ["../crowd/pending", "prisoners?limit=999999",
                                 "a/b", "PRISONERS", "prisoners#x"])
def test_the_category_is_a_name_and_nothing_else(bad):
    assert "category must be" in call("databank", category=bad)["result"]["content"][0]["text"]


def test_no_category_still_lists_them():
    """The guard must not swallow the discovery call — an empty category is how
    a model finds out what the categories are."""
    assert "categories" in call("databank")["result"]["content"][0]["text"]


def test_the_fetcher_itself_refuses_a_path_it_never_meant_to_ask_for():
    """Belt and braces: the guard lives in api(), through which every tool
    reaches the API, so a future f-string cannot quietly reopen this."""
    for path in ("/v2/databank/../../health", "/etc/passwd", "/v2/x?y=1",
                 "http://elsewhere/v2"):
        with pytest.raises(ValueError):
            s.api(path)


def test_the_paths_the_tools_really_use_still_pass():
    """A guard that blocks the real traffic is an outage, not a control."""
    for path in ("/health", "/v2/coverage", "/v2/fuel/nearby",
                 "/v2/databank/prisoners", "/v2/geo/resolve",
                 "/v2/databank/licenses", "/v2/patterns/place"):
        assert s._SAFE_PATH.match(path) and ".." not in path


# ── what leaks in the reply ──────────────────────────────────────────────────

def test_an_error_does_not_hand_back_the_address_or_a_path():
    """httpx quotes the URL it was fetching and OSError quotes the file it
    touched. Neither helps the model recover, and both tell a stranger where to
    push next."""
    leaky = f"Client error '404' for url '{s.API}/v2/databank/x' at /home/zaid/palestine-v2/serve"
    clean = m._scrub(leaky)
    assert s.API not in clean and "/home/zaid" not in clean


def test_a_tool_that_raises_reports_as_a_tool_error_not_a_crash():
    out = call("databank", category="prisoners", limit="not-a-number")
    assert "result" in out and out["result"]["isError"] is True


# ── the cap that stands in front of all of it ────────────────────────────────

def test_mcp_is_rate_limited_as_a_read_despite_being_a_POST():
    """JSON-RPC arrives as POST, so the default classifier called it a write and
    handed the whole room 20 requests a minute between them."""
    assert rl.classify("/mcp", "POST") == "mcp"
    assert rl.LIMITS["mcp"][0] > rl.LIMITS["write"][0]


def test_the_crowd_write_endpoints_keep_their_own_stricter_class():
    assert rl.classify("/v2/crowd/register", "POST") == "register"
    assert rl.classify("/v2/crowd/report", "POST") == "write"
