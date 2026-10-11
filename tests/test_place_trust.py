"""Trust by place (learn/place_trust.py, migration 099): the board's word is
believed where it has earned it and held where it has not. Pure tests; the last
runs the real measurement read-only on main-server."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.sources import palhub_roads as PR                               # noqa: E402
from learn import place_trust as T                                          # noqa: E402

T0 = datetime(2026, 9, 1)
CONTROL = {"open": 0.84, "closed": 0.65, "congested": 0.45}


def _pairs(place, claim, said: list[str], per_hour: int = 2):
    """`said[i]` is what the channels said in hour i; the board repeats itself
    `per_hour` times in that hour, as it does."""
    out = []
    for i, s in enumerate(said):
        hour = T0 + timedelta(hours=7 * i)            # spread over days
        out += [(place, claim, s, hour)] * per_hour
    return out


def _verdict(place, claim, said):
    rows = T.verdicts(T.fold(_pairs(place, claim, said)), CONTROL)
    return next(r for r in rows if r["place_id"] == place and r["claim_class"] == claim)


def test_the_boards_two_congestions_are_two_claims():
    assert T.claim_class("congested", 1) == "congested_medium"
    assert T.claim_class("congested", "2") == "congested_severe"
    assert T.claim_class("open", 0) == "open" and T.claim_class("closed", 3) == "closed"
    assert T.claim_class("slow", None) is None


def test_repeats_inside_one_hour_are_one_trial():
    f = T.fold(_pairs(1, "open", ["open"] * 10, per_hour=4))
    assert f[(1, "open")]["cells"] == 10 and f[(1, "open")]["agree"] == 10


def test_a_closed_the_channels_call_open_is_held_at_that_place():
    # بيت ليد as measured: the board said closed, the channels said open 92 of 92.
    v = _verdict(1510, "closed", ["open"] * 42)
    assert v["verdict"] == "hold" and v["moved"] and "under the bar" in v["why"]


def test_a_closed_the_channels_confirm_stays_asserted():
    v = _verdict(1520, "closed", ["closed"] * 60)
    assert v["verdict"] == "assert" and not v["moved"]


def test_a_severe_congestion_is_asserted_where_it_was_earned():
    # قلنديا as measured: 0.69 over 242 hours.
    v = _verdict(1589, "congested_severe", ["congested"] * 167 + ["open"] * 75)
    assert v["verdict"] == "assert" and v["moved"] and "earned here" in v["why"]


def test_a_medium_congestion_the_channels_call_open_stays_held():
    v = _verdict(1492, "congested_medium", ["open"] * 130 + ["closed"] * 2)
    assert v["verdict"] == "hold" and not v["moved"]


def test_too_few_hours_or_days_never_move_a_claim():
    few = _verdict(7, "closed", ["open"] * (T.MIN_CELLS - 1))
    assert few["verdict"] == "assert" and not few["moved"] and "too few" in few["why"]
    # plenty of hours, all inside two days: one long episode decides nothing
    pairs = [(8, "closed", "open", T0 + timedelta(hours=h)) for h in range(40)]
    one = T.verdicts(T.fold(pairs), CONTROL)[0]
    assert one["days"] == 2 and not one["moved"]


def test_a_borderline_place_keeps_the_class_rule():
    # 0.60 over 50 hours against a bar of 0.69 for `open`: the upper bound is
    # above the bar, so we are not sure it is worse than a channel here.
    v = _verdict(9, "open", ["open"] * 30 + ["closed"] * 20)
    assert v["verdict"] == "assert" and not v["moved"]


def test_the_ingest_lets_a_measured_place_overrule_the_class_rule():
    trust = {(1510, "closed"): "hold", (1589, "congested_severe"): "assert"}
    assert PR.modality_for("closed", 3, 1510, trust) == "quarantined"
    assert PR.modality_for("closed", 3, 1520, trust) == "assertion"       # unmeasured: class rule
    assert PR.modality_for("congested", 2, 1589, trust) == "assertion"
    assert PR.modality_for("congested", 1, 1589, trust) == "quarantined"  # medium was not earned
    assert PR.modality_for("open", 0, 1589, {}) == "assertion"
    assert PR.modality_for("open") == "assertion"                         # no table yet (before 099)


def test_wilson_bounds_bracket_the_rate_and_tighten_with_evidence():
    lo, hi = T.wilson(30, 50)
    assert lo < 0.6 < hi
    lo2, hi2 = T.wilson(300, 500)
    assert lo < lo2 and hi2 < hi
    assert T.wilson(0, 0) == (0.0, 1.0)


def test_the_real_measurement_runs_read_only():
    from resolve.db import connect
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            rows, control = T.measure(cur, days=14)
            conn.rollback()
    except OSError:
        pytest.skip("no database here")
    assert {"open", "closed"} <= set(control)
    assert all(r["verdict"] in ("assert", "hold") for r in rows)
    assert all(r["moved"] == (r["verdict"] != T.CLASS_DEFAULT[r["claim_class"]]) for r in rows)
