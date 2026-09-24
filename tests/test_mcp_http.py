"""The MCP surface that strangers can reach.

    ./.venv/bin/python -m pytest tests/test_mcp_http.py -q

The stdio server is spoken to by processes already on this host. The HTTP one
is spoken to by anybody with the URL, and the difference is the whole subject of
this file: what is on the menu, what is not, and what a caller can talk the
server into doing with a string.
"""
from __future__ import annotations

import json
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
    # The menu is the 16 public names (serve/mcp_facades.py); the absorbed
    # old names are aliases that answer but are not offered.
    from serve.mcp_facades import LISTED
    assert listed == set(LISTED)


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
    for path in ("/health", "/v2/coverage", "/v2/fuel/prices",
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


# ── what the HTTP surface adds (usage, English, prompts, resources) ──────────

def test_usage_counts_a_successful_but_empty_answer_as_unmet():
    """The valuable column. A tool that answers "nobody reports this" worked
    perfectly and still failed the person asking, and only the second sense
    tells us what to go and acquire."""
    from serve import mcp_usage as u
    assert u.unmet({"answer": "…", "no_source": True}) is True
    assert u.unmet({"count": 0}) is True
    assert u.unmet({"found": False}) is True
    assert u.unmet({"count": 3, "items": [1, 2, 3]}) is False


def test_coverage_naming_its_blind_spots_is_not_a_failure():
    """`no_source` is a FLAG on crossings and a LIST on coverage. Counting the
    list as failure would park the one honest tool at the top of the roadmap
    forever."""
    from serve import mcp_usage as u
    assert u.unmet({"answer": "…", "no_source": ["water", "power"]}) is False


def test_the_usage_ledger_records_no_address():
    """It records people asking which checkpoints are closed. A log of who
    wanted to know that is not a neutral artifact."""
    from serve import mcp_usage as u
    a, b = u.caller("203.0.113.9"), u.caller("203.0.113.10")
    assert a != b and "203.0.113" not in a and len(a) == 12


def test_english_is_built_from_fields_not_translated():
    """The Arabic sentence exists to stop the caveat being rephrased. The
    English must therefore come from the same structured facts, so that a
    reading with no recent report cannot become 'the checkpoint is open'."""
    from serve.mcp_en import add_english
    stale = add_english("checkpoint_status",
                        {"name": "حوارة", "flow": "unknown",
                         "last_known_flow": "open", "age_minutes": 180})
    assert "no current reading" in stale["answer_en"]
    assert "3h ago" in stale["answer_en"]


def test_a_tool_without_a_renderer_gets_no_english_rather_than_bad_english():
    from serve.mcp_en import add_english
    assert "answer_en" not in add_english("stream_info", {"answer": "البث شغال."})


def test_every_public_tool_declares_an_output_schema():
    assert all("outputSchema" in t for t in m._tool_list())


def test_prompts_and_resources_are_listed_and_readable():
    ps = m._handle({"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})["result"]["prompts"]
    assert {p["name"] for p in ps} >= {"route_check", "whats_missing"}
    got = m._handle({"jsonrpc": "2.0", "id": 1, "method": "prompts/get",
                     "params": {"name": "route_check",
                                "arguments": {"origin": "رام الله",
                                              "destination": "نابلس"}}})
    assert "نابلس" in got["result"]["messages"][0]["content"]["text"]
    rs = m._handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})["result"]["resources"]
    assert {r["uri"] for r in rs} == set(m.READERS)


def test_an_unknown_resource_is_refused_not_guessed():
    assert m._handle({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                      "params": {"uri": "palestine://../etc/passwd"}})["error"]["code"] == -32602


def test_a_trend_over_a_breakdown_is_refused():
    """refugees.cross_border is 1,157 points over 16 dates — a breakdown split
    by asylum country. Averaging its last three against the median of the rest
    produced '18,338% higher', which is arithmetic without a subject."""
    out = call("trend", indicator="refugees.cross_border")
    body = json.loads(out["result"]["content"][0]["text"])
    assert body.get("refused") is True and "breakdown" in body["reason"]


def test_the_scan_reports_how_many_tests_it_ran():
    """A scan is a multiple-comparisons machine. Forty tests at the usual
    threshold yield two 'significant' results from noise alone, so the count
    has to travel with the matches."""
    out = call("what_correlates_with", indicator="refugees.cross_border",
               candidates=20)
    body = json.loads(out["result"]["content"][0]["text"])
    assert "tested" in body and ("multiple_comparisons" in body or body.get("refused"))
