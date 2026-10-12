"""P1-A.3 — every source judged against its own rhythm.

A dead channel used to hide behind the others feeding the same kind of data:
tg_areenablus stopped on 2026-08-24 and nothing said so for a month. The
classification is pure and tested here without a database; the last test runs
the real query on main-server.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import watchdog as W                                               # noqa: E402

H = 3600.0


def _row(key, n, age_h, p95_h=None, mean_h=None, kind="telegram", observed=True, last_claim=None):
    return {"key": key, "kind": kind, "arrivals": n, "age_seconds": age_h * H if age_h is not None else None,
            "p95": p95_h * H if p95_h else None, "mean_gap": mean_h * H if mean_h else None,
            "observed": observed, "last_claim": last_claim}


def _one(row, polled=frozenset()):
    return W.classify_sources([row], set(polled))[0]


def test_a_busy_channel_quiet_past_its_own_p95_is_silent():
    v = _one(_row("tg_x", 500, age_h=30, p95_h=2))        # floor is a day, so 30 h > 24 h
    assert v["status"] == "silent" and v["fault"] and "p95" in v["detail"]


def test_a_busy_channel_is_never_judged_under_a_day():
    v = _one(_row("tg_x", 500, age_h=20, p95_h=0.5))
    assert v["status"] == "ok"


def test_a_sparse_channel_gets_three_mean_gaps():
    v = _one(_row("tg_sparse", 10, age_h=100, mean_h=40))  # 3 x 40 h = 120 h
    assert v["status"] == "ok"
    v = _one(_row("tg_sparse", 10, age_h=130, mean_h=40))
    assert v["status"] == "silent" and "sparse" in v["detail"]


def test_areenablus_as_measured_on_2026_09_25_is_silent():
    v = _one(_row("tg_areenablus", 17, age_h=776, p95_h=143.5, mean_h=40.7))
    assert v["status"] == "silent" and v["fault"]


def test_nothing_in_the_window_is_dormant_not_an_alarm():
    v = _one(_row("tg_palmoh", 0, age_h=None, observed=False, last_claim="2026-07-24"))
    assert v["status"] == "dormant" and not v["fault"]
    assert "does not read it" in v["detail"]


def test_a_registry_feed_that_never_delivered_is_no_collector():
    v = _one(_row("bbc", 0, age_h=None, kind="rss", observed=False))
    assert v["status"] == "no_collector" and not v["fault"]


def test_a_v2_channel_taken_off_the_poller_is_dormant():
    v = _one(_row("tg_gedcogaza", 1, age_h=1397, observed=False, last_claim="2026-07-28"))
    assert v["status"] == "dormant" and not v["fault"]
    v = _one(_row("tg_gedcogaza", 1, age_h=1397, observed=False), polled={"gedcogaza"})
    assert v["status"] == "silent"                   # on the poller list, it IS silent


def test_the_summary_names_the_silent_and_the_dormant():
    vs = W.classify_sources([_row("tg_a", 500, 1, p95_h=1), _row("tg_b", 17, 776, mean_h=40),
                             _row("tg_c", 0, None, observed=False)], set())
    s = W.summarise_sources(vs)
    assert "1 of 2 watched" in s["detail"] and "SILENT: tg_b" in s["detail"]
    assert "dormant (retire or re-poll): tg_c" in s["detail"]
    assert s["fault"] is False                        # the per-source row carries the fault


def test_the_sources_job_is_expected_and_on_the_health_page():
    assert "sources" in W.EXPECTED_JOBS
    import inspect
    assert "recorded_source_checks" in inspect.getsource(W.all_checks)


def test_the_real_query_runs_and_every_verdict_is_known():
    rows = W.source_checks(record=False)
    assert rows[-1]["name"] == "sources"
    assert all(r["status"] in ("silent", "narrowed", "ok") for r in rows)


# ── reach: a source that still speaks, about fewer places ────────────────────

def _reach(key, today, base):
    return [{"key": key, "back": 0, "reach": today}] + \
           [{"key": key, "back": i + 1, "reach": v} for i, v in enumerate(base)]


def test_palhub_as_measured_on_2026_10_04_has_narrowed():
    # 164 places x 24 h as text until 3 October; 98 after the board's robot put
    # 14 fuel cards ahead of its road bulletins and only 6 of 12 still fitted
    # its message allowance. The channel posted more messages, not fewer.
    base = [3936, 3790, 3782, 3810, 3936, 3700, 3782] * 4
    v = W.classify_reach(_reach("tg_palhubapproad", 2352, base))[0]
    assert v["status"] == "narrowed" and v["fault"]
    assert "fewer places" in v["detail"] and "2,352" in v["detail"]


def test_a_crowd_channels_quiet_friday_is_not_a_narrowing():
    # tg_road_jehad as measured: median 693, robust spread 362.
    base = [693, 1100, 320, 980, 410, 700, 1210, 250, 690, 880, 300, 760, 1050, 420] * 2
    v = W.classify_reach(_reach("tg_road_jehad", 380, base))[0]
    assert v["status"] == "ok" and not v["fault"]


def test_a_small_source_is_left_to_the_silence_rule():
    assert W.classify_reach(_reach("tg_small", 0, [40] * 28)) == []


def test_a_regular_source_on_an_ordinary_day_is_ok():
    v = W.classify_reach(_reach("tg_board", 3700, [3782] * 28))[0]
    assert v["status"] == "ok"


def test_a_source_missing_days_in_its_month_counts_them_as_zero():
    rows = [{"key": "tg_new", "back": 0, "reach": 50}] + \
           [{"key": "tg_new", "back": i, "reach": 4000} for i in range(1, 6)]
    assert W.classify_reach(rows) == []          # five days of history: median is 0
