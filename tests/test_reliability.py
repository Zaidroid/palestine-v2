"""Loop A — the properties the crowd engine will rest on.

    ./.venv/bin/python -m pytest tests/test_reliability.py -q

These are not tests of the current 15 Telegram channels. They are tests of the
behaviour P2 needs from this loop when the reporter is a person with a phone,
written now because that behaviour is easy to break by "improving" the formula
later and impossible to notice from the aggregate numbers.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from learn.reliability import PRIOR_A, PRIOR_B, kappa, trust, wilson_lower  # noqa: E402


def mean(hits: int, misses: int) -> float:
    return (hits + PRIOR_A) / (hits + misses + PRIOR_A + PRIOR_B)


# ── reputation is EARNED, never seeded ───────────────────────────────────────

def test_a_perfect_newcomer_is_not_trusted():
    """One correct report is not a track record. This is what stops a fresh
    account — or fifty fresh accounts — from arriving pre-trusted, with no rule
    anywhere that says "new submitters are suspicious"."""
    assert mean(1, 0) > 0.6           # the posterior mean flatters them
    assert wilson_lower(1, 1) < 0.25  # the bound, which is what we use, does not


def test_trust_rises_only_with_evidence():
    """Same 100% accuracy, more evidence — trust must increase monotonically."""
    bounds = [wilson_lower(n, n) for n in (1, 5, 20, 100, 1000)]
    assert bounds == sorted(bounds)
    assert bounds[0] < 0.25 and bounds[-1] > 0.99


def test_a_long_good_record_beats_a_short_perfect_one():
    """90/100 must outrank 1/1, or volume of noise beats demonstrated accuracy
    and the engine rewards spam."""
    assert wilson_lower(90, 100) > wilson_lower(1, 1)


def test_being_contradicted_costs_standing():
    assert wilson_lower(80, 100) < wilson_lower(95, 100)


def test_unmeasured_is_none_not_a_guess():
    """A source nobody has been able to score must not silently become 0.5.
    27 of 42 sources are in this state; they keep their prior behaviour because
    the caller coalesces NULL to 1.0, which is a decision the caller makes
    explicitly rather than one this function makes for it."""
    assert trust(None, None) is None
    assert trust(0.9, 0) is None


# ── raw agreement is not skill ───────────────────────────────────────────────

def test_always_saying_the_common_value_scores_zero_kappa():
    """`open` is ~88% of checkpoint readings. A reporter that says "open" every
    time and understands nothing agrees ~88% of the time, and a raw agreement
    score would call that excellent. Kappa must call it worthless."""
    j = Counter({("open", "open"): 88, ("open", "closed"): 12})
    assert kappa(j) == 0.0


def test_kappa_rewards_actually_tracking_the_state():
    j = Counter({("open", "open"): 88, ("closed", "closed"): 12})
    assert kappa(j) == 1.0


def test_kappa_is_undefined_when_only_one_value_was_ever_seen():
    """Agreement is then guaranteed and carries no information. Returning 1.0
    would mark a reporter that has only ever seen one value as perfect."""
    assert kappa(Counter({("open", "open"): 500})) is None
    assert kappa(Counter()) is None


def test_worse_than_chance_is_negative():
    """A reporter who is systematically out of step should go BELOW zero, not
    bottom out at zero — an inverted reporter is a different problem from an
    uninformative one, and P2 needs to be able to tell them apart."""
    j = Counter({("open", "closed"): 40, ("closed", "open"): 40,
                 ("open", "open"): 10, ("closed", "closed"): 10})
    assert kappa(j) < 0
