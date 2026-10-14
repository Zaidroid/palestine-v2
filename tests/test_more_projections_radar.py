"""The night after the UN's projection is loaded (ops/gap_radar.py PROJECTION,
ops/gen_attribution.py span and opening).

Its rows are dated 2024 to 2101. Judged like any dataset, the gap radar read it
`fresh` at an age of -27,107 days and would have gone on doing so until 2104,
and counted 3,927 projected values as the `economic` category's coverage of
"Oct 2023 to today"; the attribution file would have opened "spanning 1922 to
2101". No database: both are asked with a stand-in cursor.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from ops import gap_radar, gen_attribution


# ── the gap radar: neither fresh until 2104 nor a false alarm ────────────────

class RadarStore:
    """The estimates and the projection, as ops/gap_radar.py asks for them."""

    def __init__(self):
        self.out, self.asked = None, []

    def execute(self, sql, params=()):
        self.asked.append((sql, params))
        if "FROM dataset d JOIN source s" in sql:
            self.out = [(1, "un_wpp_2024", "economic", "un_wpp", "CC-BY-IGO-3.0", True, {"vintage": "2024-07-11"}),
                        (2, "un_wpp_2024_projection", "economic", "un_wpp", "CC-BY-IGO-3.0", True,
                         {"vintage": "2024-07-11"})]
        elif "WITH shared" in sql:
            self.out = [(None, None)]
        elif "mode() WITHIN GROUP" in sql:
            self.out = ([(3774, date(1950, 1, 1), date(2023, 1, 1), 74, "year", date(2026, 10, 13))]
                        if params[0] == 1 else
                        [(3928, date(2024, 1, 1), date(2101, 1, 1), 78, "year", date(2026, 10, 14))])
        elif "percentile_cont" in sql:
            self.out = [(365.0, 366, date(1952, 1, 1))]
        else:
            self.out = [("economic", 1)] if "GROUP BY 1" in sql else [(0,)]

    def fetchall(self):
        return self.out

    def fetchone(self):
        return self.out[0]


def test_the_radar_gives_a_projection_no_age_and_never_calls_it_fresh():
    assert set(gap_radar.PROJECTION) == {"un_wpp_2024_projection"}
    assert "11 July 2027" in gap_radar.PROJECTION["un_wpp_2024_projection"]
    assert not set(gap_radar.PROJECTION) & (set(gap_radar.CLOSED_CORPUS) | set(gap_radar.DEAD_UPSTREAM)
                                            | set(gap_radar.ALLOWANCE_OVERRIDE_DAYS))
    today = date(2026, 10, 14)
    est, pro = gap_radar.measure_datasets(RadarStore(), today)
    assert (pro["dataset"], pro["status"]) == ("un_wpp_2024_projection", "projection")
    assert pro["age_days"] is None and pro["last_information_day"] is None       # not -27,107 days "old"
    assert pro["freshness_basis"].startswith("projection") and pro["largest_hole"] is None
    assert pro["projection_reason"] == gap_radar.PROJECTION["un_wpp_2024_projection"]
    assert pro["span"] == ["2024-01-01", "2101-01-01"] and pro["rows"] == 3928   # still listed, as what it is
    # the estimates beside it: fresh since 2026-10-14, under an allowance that waits for the revision the UN
    # announced for 11 July 2027 (under the learned rhythm they read "late", with nothing newer published)
    assert (est["dataset"], est["status"], est["age_days"], est["projection_reason"]) == \
        ("un_wpp_2024", "fresh", (today - date(2023, 1, 1)).days, None)
    # no gap line for either, and the projection never one of the fresh
    gaps = gap_radar.rank_gaps([est, pro], [], {"dead": []})
    assert [g["subject"] for g in gaps] == []
    supply = gap_radar.judge_supply_lines({}, {}, [est, pro],
                                          datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert supply["data"] == [] and not [x for x in supply["dead"] if "projection" in x["line"]]
    gap_radar.apply_supply([est, pro], supply)
    assert pro["status"] == "projection"


def test_a_projected_year_is_not_coverage_of_an_era():
    store = RadarStore()
    gap_radar.measure_eras(store)
    era = [(sql, params) for sql, params in store.asked if "FROM observation o JOIN dataset d" in sql]
    assert len(era) == len(gap_radar.ERAS)
    for sql, params in era:
        assert "AND d.key <> ALL(%s)" in sql and params[2] == ["un_wpp_2024_projection"]
        assert sql.count("%s") == len(params) == 3


def test_the_radar_s_headline_counts_it_apart():
    c = {"datasets": 43, "fresh": 30, "late": 2, "stalled": 0, "supply_dead": 0, "dead_upstream": 3,
         "closed_corpus": 4, "continued": 1, "awaiting_permission": 1, "projection": 1,
         "supply_lines": {k: 0 for k in ("dead", "v2_live", "v2_lines", "v2_failing", "v2_dead", "v1_live",
                                         "v1_steps", "v1_dead", "v1_failing", "v1_retired_pending",
                                         "v1_retired", "v1_benign", "stalled_data_lines")}}
    assert "1 awaiting permission · 1 projection" in gap_radar.headline(date(2026, 10, 14), c)[0]
    del c["projection"]                                      # a radar file written before this
    assert "· 0 projection" in gap_radar.headline(date(2026, 10, 14), c)[0]


# ── the attribution file: observations are counted and dated apart ───────────

class SpanStore:
    def __init__(self, column: bool, row: tuple):
        self.column, self.row, self.asked, self.out = column, row, [], None

    def execute(self, sql, params=()):
        self.asked.append(sql)
        self.out = (int(self.column),) if "information_schema.columns" in sql else self.row

    def fetchone(self):
        return self.out


def test_the_attribution_file_never_spans_to_a_projected_year():
    with_proj = (331593, date(1922, 1, 1), date(2026, 10, 13), 3928, 51, date(2024, 1, 1), date(2101, 1, 1))
    s = SpanStore(True, with_proj)
    assert gen_attribution.span(s) == with_proj
    assert "indicator IN (SELECT indicator FROM indicator_def WHERE projection) AS p FROM databank_serving" in s.asked[1]
    assert "max(occurred_at) FILTER (WHERE NOT p)" in s.asked[1]
    said = gen_attribution.opening(*with_proj)
    assert "serves **331,593 observations** spanning **1922-01-01 to 2026-10-13**" in said
    assert "2101-01-01" not in said and "**3,928 projected values** in 51 series for 2024 to 2101" in said
    assert "a model's output, not observations" in said and "not in the count or the span above" in said
    # before migration 115 the column is not there: nothing is a projection, and the sentence is the old one
    s = SpanStore(False, (336174, date(1922, 1, 1), date(2026, 10, 13), 0, 0, None, None))
    assert gen_attribution.span(s)[3:] == (0, 0, None, None) and "false AS p FROM databank_serving" in s.asked[1]
    plain = gen_attribution.opening(*gen_attribution.span(s))
    assert plain == ("The Palestine databank serves **336,174 observations** spanning **1922-01-01 to "
                     "2026-10-13** from the sources below. Every row carries its source and licence in the "
                     "API response; this file is the same information in one place.")
