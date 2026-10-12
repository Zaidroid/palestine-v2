"""A re-read of the Ministry's bulletins writes each day's last word once.

2026-10-12: the re-read after a parser fix replayed same-day bulletins in order
and wrote 69 revisions over 34 figures, every one of which ended where it
began. Pure: no connection is opened."""
from datetime import datetime, timezone

from ingest.sources import moh_gaza as M


def at(day, hour):
    return datetime(2024, 6, day, hour, tzinfo=timezone.utc)


def test_the_last_bulletin_of_a_day_has_the_last_word():
    read = [(1, at(22, 11), ["deaths", "injuries"]), (2, at(22, 12), ["deaths"]),
            (3, at(23, 11), ["deaths"])]
    stands = M.last_word(read)
    assert stands[("deaths", at(22, 0).date())] == 2
    assert stands[("injuries", at(22, 0).date())] == 1, "the second post did not restate it"
    assert stands[("deaths", at(23, 0).date())] == 3


class Cur:
    """One held row; records the verb of every statement it is given."""
    def __init__(self, held):
        self.held, self.ran = held, []

    def execute(self, sql, params=None):
        self.ran.append(sql.split()[0].upper())

    def fetchone(self):
        return self.held


def test_a_dry_run_counts_against_what_is_held_and_writes_nothing():
    st, cur = {}, Cur((7, 19.0))
    args = (cur, 1, 1, "gaza.moh.deaths.daily")
    assert M._upsert_day(*args, 19.0, at(22, 11), "daily", "deaths", 5, st, dry_run=True) == 0
    assert M._upsert_day(*args, 101.0, at(22, 11), "daily", "deaths", 5, st, dry_run=True) == 1
    assert st == {"unchanged": 1, "revised": 1}
    assert set(cur.ran) == {"SELECT"}


def test_a_real_run_closes_the_old_row_before_it_writes_the_new_one():
    st, cur = {}, Cur((7, 19.0))
    assert M._upsert_day(cur, 1, 1, "gaza.moh.deaths.daily", 101.0, at(22, 11),
                         "daily", "deaths", 5, st) == 1
    assert cur.ran == ["SELECT", "UPDATE", "INSERT"] and st == {"revised": 1}


def test_no_two_tiers_share_one_series():
    """load() keys a bulletin's figures by series; two (tier, measure) pairs on
    one series would silently become one."""
    assert len(set(M.INDICATORS.values())) == len(M.INDICATORS)
