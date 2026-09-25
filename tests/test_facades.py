"""The public tool surface: 16 names over the old 28 (P0-A, 2026-09-24).

A first-time caller — human or model — reads tools/list and has to choose. The
menu is the façade table in serve/mcp_facades.py; the old names stay callable
for one release so nothing a tester tried breaks, but they are not offered.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import mcp_facades as F                                # noqa: E402
from serve import mcp_http as m                                   # noqa: E402
from serve import mcp_server as s                                 # noqa: E402


def call(name, tier="partner", **args):
    return m._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": name, "arguments": args}}, None, tier)


def payload(reply):
    return json.loads(reply["result"]["content"][0]["text"])


# ── the menu ─────────────────────────────────────────────────────────────────

def test_the_menu_is_sixteen_names_in_reading_order():
    assert len(F.LISTED) == 16
    assert F.LISTED[0] == "about"                 # the first call a stranger makes
    assert F.LISTED == F.ORDER


def test_absorbed_names_are_off_the_menu_but_still_answer():
    listed = {t["name"] for t in m._tool_list()}
    assert not (F.ABSORBED & listed)
    assert all(n in s.TOOLS for n in F.ABSORBED)      # nothing was deleted
    # F271: the envelope never carries a top-level `error`; a failed tool is
    # `isError` with an `error` key inside the payload, so that is what this
    # gate must read.
    for old in ("coverage", "checkpoints_summary", "where_is"):
        reply = call(old, place="نابلس") if old == "where_is" else call(old)
        assert not reply["result"].get("isError"), payload(reply)
        assert "error" not in payload(reply), payload(reply)


def test_every_listed_parameter_is_described_and_every_default_declared():
    """The schema is the only thing a client sees; a parameter with no
    description or an undeclared default is a guess we make the caller take."""
    for t in m._tool_list():
        props = t["inputSchema"].get("properties", {})
        for name, spec in props.items():
            assert spec.get("description"), f"{t['name']}.{name} has no description"
            if "enum" in spec and name not in t["inputSchema"].get("required", []):
                # an optional enum either declares its default or says what
                # omitting it means ("omit for the whole list")
                assert "default" in spec or "omit" in spec["description"], \
                    f"{t['name']}.{name} enum has no default"


def test_one_name_for_a_place():
    """Six names for one idea was the audit's first complaint. Every façade
    that takes a place calls it `place`."""
    for n in F.LISTED:
        props = (F.FACADES[n]["schema"] if n in F.FACADES else s.TOOLS[n][2])["properties"]
        for bad in ("area", "origin_place", "name_ar"):
            assert bad not in props, (n, bad)
    assert "place" in F.FACADES["checkpoints"]["schema"]["properties"]
    assert "place" in F.FACADES["incidents"]["schema"]["properties"]
    assert "place" in F.FACADES["place"]["schema"]["properties"]


# ── routing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,args,target,expect", [
    ("licence", {}, "licence_tools", {}),
    ("licence", {"source": "wfp"}, "licenses", {"source": "wfp"}),
    ("licence", {"scope": "sources"}, "licenses", {}),
    ("checkpoints", {}, "checkpoints_summary", {}),
    ("checkpoints", {"place": "نابلس", "limit": 3}, "checkpoints_near",
     {"place": "نابلس", "limit": 3}),
    ("checkpoints", {"lat": 32.2, "lon": 35.2}, "checkpoints_near", {"lat": 32.2, "lon": 35.2}),
    ("incidents", {}, "incidents_summary", {"hours": 24}),
    ("incidents", {"hours": 6}, "incidents_summary", {"hours": 6}),
    ("incidents", {"place": "رام الله", "hours": 6}, "incidents_near",
     {"place": "رام الله", "hours": 6}),
    ("place", {"place": "حوارة"}, "place_profile", {"place": "حوارة"}),
    ("place", {"place": "حوارة", "view": "history", "days": 7}, "place_history",
     {"place": "حوارة", "days": 7}),
    ("place", {"place": "قلنديا", "view": "pattern"}, "place_pattern", {"place": "قلنديا"}),
    ("place", {"place": "Nablus", "view": "locate", "state_kind": "checkpoint_status"},
     "where_is", {"place": "Nablus", "state_kind": "checkpoint_status"}),
    # the kind is DECLARED on both routes (F047): news for the newest, all for a word search
    ("news", {}, "latest_news", {"kind": "news"}),
    ("news", {"place": "رام الله", "limit": 3}, "latest_news",
     {"area": "رام الله", "limit": 3, "kind": "news"}),
    ("crossings", {}, "crossings", {}),
    ("crossings", {"place": "غزة"}, "crossings", {"area": "غزة"}),
    ("news", {"text": "قلنديا", "hours": 24}, "search",
     {"text": "قلنديا", "hours": 24, "kind": "all"}),
    ("news", {"text": "قلنديا", "place": "رام الله", "kind": "roads"}, "search",
     {"text": "قلنديا", "area": "رام الله", "kind": "roads"}),
    ("series", {"indicators": "food.price.bread"}, "trend", {"indicator": "food.price.bread"}),
    ("series", {"indicators": "a, b", "place": "Ramallah"}, "compare",
     {"indicators": "a, b", "place": "Ramallah"}),
    ("correlate", {}, "correlate", {}),
    ("correlate", {"a": "x", "b": "y"}, "correlate", {"a": "x", "b": "y"}),
    ("correlate", {"indicator": "x", "candidates": 10}, "what_correlates_with",
     {"indicator": "x", "candidates": 10}),
    ("insights", {"place": "نابلس", "days": 7}, "insights", {"place": "نابلس", "days": 7}),
    ("insights", {"scope": "governorates", "days": 7}, "area_history", {"days": 7}),
    ("coverage", {}, "coverage", {}),                        # an alias routes to itself
])
def test_routes(name, args, target, expect):
    got_target, got_args = F.route(name, args)
    assert got_target == target
    assert got_args == expect


def test_a_facade_drops_arguments_its_target_does_not_take():
    """The defaults differ per target (60 days for a pattern, 24 hours for the
    summary); passing a foreign argument through would be a TypeError in the
    serving path."""
    target, args = F.route("place", {"place": "حوارة", "view": "pattern", "days": 7,
                                     "scope": "nonsense"})
    assert target == "place_pattern" and "scope" not in args
    target, args = F.route("insights", {"scope": "governorates", "place": "x", "radius_km": 3})
    assert target == "area_history" and args == {}


def test_a_bad_view_is_a_bad_argument_not_a_system_error():
    r = call("place", place="حوارة", view="nonsense")
    assert r["error"]["code"] == -32602 and "view" in r["error"]["message"]
    r = call("series")
    assert r["error"]["code"] == -32602


def test_the_host_only_tools_stay_unreachable_through_a_facade_or_by_name():
    assert call("system_health")["error"]["code"] == -32601


# ── what a façade reply carries ──────────────────────────────────────────────

def test_a_facade_reply_is_graded_by_the_answering_tool_and_labelled_by_name():
    p = payload(call("checkpoints"))
    assert p["licence"]["tool"] == "checkpoints"
    assert p["licence"]["via"] == "checkpoints_summary"
    assert p["licence"]["emits"] == "derived"
    assert p.get("answer") and p.get("answer_en")


def test_the_usage_ledger_records_the_public_name():
    """The ledger is the demand signal: what people ASKED, in the words the menu
    offered them. A façade call must be recorded under the façade's name."""
    from serve import mcp_usage
    call("incidents", hours=6)
    last = json.loads(Path(mcp_usage.LEDGER).read_text().splitlines()[-1])
    assert last["tool"] == "incidents" and last["args"] == {"hours": 6}


def test_about_is_a_reduction_with_the_detail_one_section_away():
    p = payload(call("about"))
    assert p["name"] == "Palestine Data — live + databank"
    assert set(p) >= {"live", "databank", "top_gaps", "stream", "answer", "answer_en"}
    assert p["live"]["messages"] and p["databank"]["rows"]
    assert p["databank"]["categories"] >= 19
    # the headline names the numbers a reader needs and the fields with no source
    assert "بيانات فلسطين" in p["answer"]
    # Fields are SPOKEN as words, never as column names (both testers,
    # 2026-09-25: "ما في ولا مصدر لـ: crossing_status، water").
    from serve.mcp_en import field_words
    for field in p["live"]["no_source"]:
        ar, en = field_words(field)
        assert ar in p["answer"] and en in p["answer_en"]
        assert field not in p["answer"] or field == en
    full = payload(call("about", section="fields"))
    assert "fields" in full and len(full["fields"]) > 10
    assert len(json.dumps(p, ensure_ascii=False)) < len(json.dumps(full, ensure_ascii=False))


def test_the_server_says_its_one_name():
    r = m._handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18"}}, None, "partner")
    assert r["result"]["serverInfo"]["name"] == "palestine-data"
    assert "Palestine Data" in r["result"]["serverInfo"]["title"]
    assert "Start with `about`" in r["result"]["instructions"]
