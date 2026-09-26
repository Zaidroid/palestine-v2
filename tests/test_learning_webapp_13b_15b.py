"""Audit 2026-09-25, areas 13 (learning) and 15 (webapp)."""
from __future__ import annotations

import inspect
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from learn import reliability as R, source_independence as SI                # noqa: E402
from ops import mcp_accuracy_audit as AU                                     # noqa: E402
from serve import mcp_usage                                                  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


# ── LEARNING-01 ──────────────────────────────────────────────────────────────
def test_learning_01_copy_collapse_never_touches_a_crowd_source():
    assert "s.kind <> 'crowd'" in SI.MEASURE_SQL
    src = inspect.getsource(SI.cluster)
    assert "kind = 'crowd'" in src and "if sa in crowd or sb in crowd" in src
    assert "a[2] not in crowd" in src


# ── LEARNING-03 ──────────────────────────────────────────────────────────────
def _buckets(*units_values):
    b = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for i, uv in enumerate(units_values):
        for unit, (value, sid) in uv.items():
            b[("p", "both", i)][unit][value].append(sid)
    return b


def test_learning_03_leave_one_out_scores_each_unit_against_the_others():
    # two units disagree: a miss for BOTH (the old consensus included the
    # unit's own vote, so a two-unit bucket could never record a miss)
    out = R._score_buckets(_buckets({"u1": ("open", 1), "u2": ("closed", 2)}), "k", 900)
    assert out["per_source"][1] == {"hits": 0, "misses": 1}
    assert out["per_source"][2] == {"hits": 0, "misses": 1}
    # two units agree: a hit for both
    out = R._score_buckets(_buckets({"u1": ("open", 1), "u2": ("open", 2)}), "k", 900)
    assert out["per_source"][1]["hits"] == 1 and out["per_source"][2]["hits"] == 1
    # three units, one dissenter: the dissenter's OTHERS agree, so it misses;
    # each majority unit's others tie 1-1, so they are not scored (leave-one-out)
    out = R._score_buckets(_buckets({"u1": ("open", 1), "u2": ("open", 2), "u3": ("closed", 3)}), "k", 900)
    assert out["per_source"] == {3: {"hits": 0, "misses": 1}}
    # five units, one dissenter: the majority units see 3-1 among the others -> hits
    out = R._score_buckets(_buckets({"u1": ("open", 1), "u2": ("open", 2), "u3": ("open", 3),
                                     "u4": ("open", 4), "u5": ("closed", 5)}), "k", 900)
    assert out["per_source"][5] == {"hits": 0, "misses": 1}
    assert all(out["per_source"][i]["hits"] == 1 for i in (1, 2, 3, 4))
    # four units split 2/2: each unit is outvoted 2-1 by the OTHERS -> every
    # unit misses (leave-one-out has no self-vote to lean on)
    out = R._score_buckets(_buckets({"u1": ("open", 1), "u2": ("open", 2),
                                     "u3": ("closed", 3), "u4": ("closed", 4)}), "k", 900)
    assert all(out["per_source"][i] == {"hits": 0, "misses": 1} for i in (1, 2, 3, 4))
    # a genuine tie among the others: three units, the scored unit's two others disagree
    out = R._score_buckets(_buckets({"u1": ("open", 1), "u2": ("closed", 2), "u3": ("slow", 3)}), "k", 900)
    assert out["per_source"] == {} and out["ties"] == 1


# ── LEARNING-04 ──────────────────────────────────────────────────────────────
def test_learning_04_the_audit_drives_the_transport_and_exempts_the_ledger(monkeypatch):
    calls = []
    def fake_handle(msg, ip=None, tier="partner"):
        calls.append((msg["params"]["name"], msg["params"]["arguments"], tier))
        return {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": json.dumps({"answer": "x", "answer_en": "y"})}],
            "isError": False}}
    from serve import mcp_http
    monkeypatch.setattr(mcp_http, "_handle", fake_handle)
    monkeypatch.delenv("MCP_USAGE_EXEMPT", raising=False)
    out = AU.check("checkpoint_status", {"name": "حوارة"})
    assert out["answer_en"] == "y" and calls == [("checkpoint_status", {"name": "حوارة"}, "partner")]
    import os
    assert os.environ.get("MCP_USAGE_EXEMPT") == "1"
    # the ledger honours the exemption
    written = []
    monkeypatch.setattr(mcp_usage, "LEDGER", None, raising=False)
    monkeypatch.setattr(mcp_usage, "_append", lambda line: written.append(line), raising=False)
    mcp_usage.record("checkpoint_status", {}, 1, True, {}, None)
    assert written == []


# ── LEARNING-02 ──────────────────────────────────────────────────────────────
def test_learning_02_the_196_of_199_is_restated_as_agreement():
    plan = (ROOT / "docs" / "PLAN-2026-09-24-PUBLIC-RELEASE.md").read_text()
    assert "scored **196/199 exact**" not in plan and "agrees with the deterministic reader" in plan
    assert "audit 2026-09-25 F229" in (ROOT / "analyst" / "gold_moh.py").read_text()


# ── WEBAPP-01..04 ────────────────────────────────────────────────────────────
def test_webapp_01_02_pulse_carries_the_verdict_rows_age_and_consumes_named_events():
    h = (ROOT / "serve" / "webapp" / "pulse.html").read_text()
    assert "age_minutes: worst.age_minutes" in h and "${ageStr(d.age_minutes)}" in h
    assert 'es.addEventListener("state_change"' in h and "es.onmessage" not in h
    assert "d.decayed" in h and "d.to" in h and "ROWS.unshift" not in h
    assert "setInterval(load" in h and 'err:"' in h


def test_webapp_03_04_road_refreshes_and_says_when_a_fetch_fails():
    h = (ROOT / "serve" / "webapp" / "road.html").read_text()
    assert 'es.addEventListener("state_change"' in h and "setInterval(load" in h
    assert "if (!a.ok || !b.ok) throw" in h
    assert h.count('err:"') == 2 and "تعذّر تحميل البيانات" in h and "Could not load" in h


def test_a_both_report_witnesses_a_direction_report_without_being_scored_twice():
    """2026-09-26: palhub files inbound/outbound; the channels mostly file
    'both'. Bucketed by direction they never met — 21 comparisons in 30 days,
    trust_weight 0.274, and the known-fraction fell from 0.59 to 0.06 at the
    03:21 write. A 'both' reading now votes in the direction buckets as a
    witness and is scored only in its own bucket."""
    from collections import defaultdict
    buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    witnesses = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    buckets[(7, "inbound", 1)]["palhub"]["open"].append(10)
    buckets[(7, "both", 1)]["channels"]["open"].append(20)
    witnesses[(7, "inbound", 1)]["channels"]["open"].append(20)
    out = R._score_buckets(buckets, "k", 900, witnesses)
    assert out["per_source"][10] == {"hits": 1, "misses": 0}      # palhub scored
    assert 20 not in out["per_source"]                             # the witness is not
    # without witnesses palhub has no peer at all
    assert 10 not in R._score_buckets(buckets, "k", 900)["per_source"]
