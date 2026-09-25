"""The accuracy audit pages on a critical and closes when it is fixed.

The instrument itself is proven by running it (ops/mcp-accuracy.json carries the
verdict, and the watchdog shows the heartbeat). What needs proving here is the
paging DECISION, because getting it wrong has two costs that both matter: an
unfixed critical that pages every night gets muted, and a fixed one that never
closes leaves a red on the phone that nothing will clear.
"""
import json

import pytest

from ops import mcp_accuracy_audit as audit


@pytest.fixture
def pager(monkeypatch):
    calls = {"raised": [], "resolved": [], "open": []}

    def fake_open():
        return calls["open"]

    monkeypatch.setattr("ops.alert.open_alerts", fake_open, raising=False)
    monkeypatch.setattr("ops.alert.raise_alert",
                        lambda unit, msg: calls["raised"].append((unit, msg)), raising=False)
    monkeypatch.setattr("ops.alert.resolve",
                        lambda unit, msg: calls["resolved"].append((unit, msg)), raising=False)
    return calls


CRITICAL = [{"severity": "critical", "tool": "trend", "claim": "no date on the claim",
             "expected": "the last reading's date", "got": "flat"}]


def test_a_critical_raises_once_and_stays_open(pager):
    audit.page(CRITICAL)
    assert len(pager["raised"]) == 1
    unit, msg = pager["raised"][0]
    assert unit == audit.ALERT_UNIT
    assert "trend" in msg and "no date on the claim" in msg

    # it is already open: a second night with the same fault must not page again
    pager["open"] = [{"unit": audit.ALERT_UNIT}]
    audit.page(CRITICAL)
    assert len(pager["raised"]) == 1


def test_a_clean_run_closes_an_open_alert(pager):
    pager["open"] = [{"unit": audit.ALERT_UNIT}]
    audit.page([])
    assert len(pager["resolved"]) == 1
    assert pager["resolved"][0][0] == audit.ALERT_UNIT


def test_a_clean_run_with_nothing_open_does_not_send_a_recovery(pager):
    """The Gaza cross-check's lesson: resolve() on a green night with nothing
    open puts a 'recovered' on the phone every night for a fault that never was.
    """
    audit.page([])
    assert pager["resolved"] == []


def test_the_verdict_file_carries_counts_the_watchdog_and_a_human_can_read():
    """Asserted on what the writer BUILDS (audit.verdict), not on
    ops/mcp-accuracy.json: that file is gitignored, so the old form of this
    test failed on every checkout but main-server and, where the file did
    exist, only restated whatever last night wrote (audit F492/F583)."""
    findings = CRITICAL + [{"severity": "minor", "tool": "t", "claim": "c",
                            "expected": 1, "got": 2, "evidence": ""}]
    d = json.loads(json.dumps(audit.verdict(findings), default=str))
    assert d["counts"] == {"critical": 1, "major": 0, "minor": 1}
    assert isinstance(d["findings"], list) and len(d["findings"]) == 2
    for f in d["findings"]:
        assert {"severity", "tool", "claim", "expected", "got"} <= set(f)
    assert d["at"]


def test_the_live_verdict_file_has_the_same_shape_where_it_exists():
    path = audit.ROOT / "ops" / "mcp-accuracy.json"
    if not path.exists():
        pytest.skip("ops/mcp-accuracy.json is written nightly on main-server "
                    "and is gitignored; the builder is tested above")
    d = json.loads(path.read_text())
    assert set(d["counts"]) == {"critical", "major", "minor"}
    assert isinstance(d["findings"], list)
    for f in d["findings"]:
        assert {"severity", "tool", "claim", "expected", "got"} <= set(f)


# ── the instrument calls tools the way a client does (audit F243) ────────────

def _fake_tool(payload):
    return (lambda **kw: dict(payload, _args=kw), "fake", {"type": "object",
                                                         "properties": {}})


def test_the_audit_sees_the_english_a_client_receives(monkeypatch):
    """answer_en is attached by the transports, never by the tool function.
    Called in-process, every English check in the audit ran on '' and could
    not fire — so an English sentence contradicting its payload was invisible
    to the one instrument that pages on it."""
    monkeypatch.setitem(audit.TOOLS, "connectivity_now",
                        _fake_tool({"status": "normal", "answer": "النت طبيعي"}))
    d = audit.check("connectivity_now", {})
    assert d["answer_en"], "the audit read a payload with no English in it"
    assert "normally" in d["answer_en"]


def test_an_english_contradiction_can_now_be_found(monkeypatch):
    """The check at the heart of F243, end to end on a stub surface: a payload
    that says `degraded` while its English says `normal` must be a critical."""
    monkeypatch.setattr(audit, "FINDINGS", [])

    def down(**kw):
        raise RuntimeError("not under test")
    for name in list(audit.TOOLS):
        monkeypatch.setitem(audit.TOOLS, name, (down, "", {}))
    monkeypatch.setitem(audit.TOOLS, "connectivity_now",
                        _fake_tool({"status": "degraded", "answer": "النت ضعيف"}))
    monkeypatch.setattr(audit, "add_english",
                        lambda tool, out: dict(out, answer_en="Internet is normal.")
                        if tool == "connectivity_now" else out)
    audit.audit_answer_vs_payload()
    hits = [f for f in audit.FINDINGS if f["tool"] == "connectivity_now"
            and f["claim"].startswith("answer contradicts")]
    assert hits and hits[0]["severity"] == "critical"


def test_a_facade_name_is_routed_before_it_is_called(monkeypatch):
    """The public names are façades (serve/mcp_facades.py). An audit that can
    only call internal names never exercises the routing a client goes
    through."""
    seen = []
    monkeypatch.setattr(audit, "route",
                        lambda name, args: seen.append(name) or ("coverage", {}))
    monkeypatch.setitem(audit.TOOLS, "coverage", _fake_tool({"answer": "x"}))
    assert audit.check("checkpoints", {"place": "Nablus"})["answer"] == "x"
    assert seen == ["checkpoints"]


def test_an_empty_reply_to_a_nonsense_place_is_a_finding(monkeypatch):
    """audit_edges exists to catch a refusal with no words. The old test fired
    only when the reply carried `found`, `count` or `answer`, so a bare `{}` —
    the reply it exists to catch — passed (audit F488)."""
    monkeypatch.setattr(audit, "FINDINGS", [])
    for name in list(audit.TOOLS):
        monkeypatch.setitem(audit.TOOLS, name, _fake_tool({}))
    audit.audit_edges()
    silent = {f["tool"] for f in audit.FINDINGS if f["claim"] == "refusal without words"}
    assert {"where_is", "checkpoint_status", "insights"} <= silent


def test_every_renderer_probe_names_a_tool_that_exists(monkeypatch):
    """`fuels` was probed nightly and skipped silently: a line in the probe
    list that claimed coverage nobody had (audit F489)."""
    probes = getattr(audit, "RENDER_PROBES", None)
    assert probes, "the renderer probes are a list a test can read"
    assert [t for t in probes if audit.route(t, probes[t])[0] not in audit.TOOLS] == []
    monkeypatch.setattr(audit, "FINDINGS", [])
    for name in list(audit.TOOLS):
        monkeypatch.setitem(audit.TOOLS, name, _fake_tool({"answer": "ok"}))
    audit.audit_renderer_artifacts()
    assert not [f for f in audit.FINDINGS if f["claim"].startswith("probe names no tool")]
