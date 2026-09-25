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
    d = json.loads((audit.ROOT / "ops" / "mcp-accuracy.json").read_text())
    assert set(d["counts"]) == {"critical", "major", "minor"}
    assert isinstance(d["findings"], list)
    for f in d["findings"]:
        assert {"severity", "tool", "claim", "expected", "got"} <= set(f)


# ── P1-C.5 (2026-09-25): the checks the black-box audit did by hand ─────────
def test_the_nightly_audit_runs_the_new_families():
    import inspect
    from ops import mcp_accuracy_audit as M
    src = inspect.getsource(M.main)
    for fn in ("audit_english_inputs", "audit_parity", "audit_cross_tool",
               "audit_payload_size", "audit_description_drift"):
        assert fn in src
    assert '"fuels"' not in inspect.getsource(M.audit_renderer_artifacts)


def test_parity_numbers_survive_an_arabic_conjunction():
    from ops.mcp_accuracy_audit import _numbers
    assert _numbers("و101 حاجز، و13 خط إمداد") == {"101", "13"}
    assert _numbers("101 have no recent reading; 13 supply lines") == {"101", "13"}
    assert _numbers("route B2 and v1.9") == set()
