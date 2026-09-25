"""P0-C.5 — news channels measured for copying (learn/news_independence.py)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learn import news_independence as N                                    # noqa: E402

T0 = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
TEXT = "قوات الاحتلال تقتحم بلدة بيتا جنوب نابلس وتداهم عدة منازل وتعتقل شابين"


def test_a_verbatim_repost_within_the_hour_is_a_copy():
    claims = [("tg_a", T0, TEXT), ("tg_b", T0 + timedelta(minutes=20), TEXT + " @tg_b")]
    r = N.copy_rates(claims)
    assert r[("tg_b", "tg_a")] == (1, 1)


def test_the_same_text_a_day_later_is_not():
    claims = [("tg_a", T0, TEXT), ("tg_b", T0 + timedelta(days=1), TEXT)]
    assert N.copy_rates(claims)[("tg_b", "tg_a")] == (0, 1)


def test_groups_need_both_the_rate_and_the_volume():
    heavy = {("tg_b", "tg_a"): (40, 60)}
    assert N.groups_from(heavy)[0] == {"tg_a": "newscopy:tg_a", "tg_b": "newscopy:tg_a"}
    assert N.groups_from({("tg_b", "tg_a"): (10, 12)})[0] == {}      # too few matches
    assert N.groups_from({("tg_b", "tg_a"): (40, 400)})[0] == {}     # 10 % is a real second reporter


def test_apply_never_touches_a_road_copyset_or_crowd():
    import inspect
    src = inspect.getsource(N.main)
    assert 'kind == "crowd"' in src and 'startswith("newscopy:")' in src
