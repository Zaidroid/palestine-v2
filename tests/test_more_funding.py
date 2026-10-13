"""UN funding counted a parked contribution twice (fixed 2026-10-13).

UN OCHA's Financial Tracking Service "parks" a contribution on a parent flow
and files its allocations as child flows. The parent's `amountUSD` is what is
left on it; `fullParkedAmountUSD` is the whole. Until this date a parent with
nothing left was a row of `funding.<status>` carrying the whole parked amount,
beside the children that carry the same money: 520 parents, USD 1,926,516,664
on the answer of 2026-10-13.

The rule under test: a parked parent with nothing left on it (amountUSD zero
or below, a parked amount above zero, at least one child flow) is one row of
`funding.parked_parent` and of no status series; every other record is filed
and held exactly as before.

Everything here is offline. tests/fixtures/more_funding/ holds twelve real
flows as FTS returned them on 2026-10-13 and the rows the databank held for
them that morning. A flow built by hand from a real one says so where it is
made. No network, no database.
"""
from __future__ import annotations

import inspect
import json
from collections import Counter
from pathlib import Path

import pytest

from ingest import databank, engine
from ingest.databank import SpecRefused, content_of, identity_key_for, load_spec, slug
from ops import fetch_fts as ff
from ops import load_registry as lr

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "more_funding"
AT = "2026-10-13T08:02:05+00:00"
DS = "v1_funding_unfts"
STATUS = ("funding.paid", "funding.commitment", "funding.pledge")
PARENT = "funding.parked_parent"


def fx(name):
    return json.loads((FX / name).read_text())


class _NoPoint:
    def resolve(self, lat, lon):
        return None


FLOWS = fx("fts_flows.json")["flows"]
FLOW = {str(f["id"]): f for f in FLOWS}
HELD = fx("fts_held.json")["rows"]
PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2}, "governorate": {},
          "pcode": {}, "_pip": _NoPoint()}

# The fixture, by what FTS says of each flow:
NOTHING_LEFT = ("162034", "277446")          # amountUSD 0 beside a parked amount
OVER_ALLOCATED = ("323807", "292049")        # amountUSD below zero: the children got more
PARENTS = NOTHING_LEFT + OVER_ALLOCATED
PARTLY = "247980"                            # USD 1,523,504 left of USD 1,922,455
OTHERS = ("162035", "162036", "323808", "323809", "292109", "401972", "247980", "257274")


def _row(rec, spec):
    """Through what runs for funding: the spec engine."""
    assert databank.TRANSFORMERS["funding"] is databank.t_engine
    (row,) = databank.TRANSFORMERS["funding"](rec, spec, PLACES, Counter())
    return row


def _key(row, spec):
    return identity_key_for(spec["identity"], row.dataset_key, indicator=row.indicator,
                            occurred_at=row.occurred_at, place_id=row.place_id,
                            value_num=row.value_num, attrs=row.attrs)


def _content(row):
    return content_of(value_num=row.value_num, value_text=row.value_text, unit=row.unit,
                      place_id=row.place_id, attrs=row.attrs)


def _held_content(h):
    return content_of(value_num=h["value_num"], value_text=None, unit=h["unit"],
                      place_id=h["place_id"], attrs=h["attrs"])


def _built():
    recs, summary = ff.build({2026: FLOWS}, AT)
    return {r["funding"]["flow_id"]: r for r in recs}, summary


# ── which flow is a parked parent ────────────────────────────────────────────

def test_a_parent_with_nothing_left_or_less_is_a_parked_parent_and_nothing_else_is():
    for fid in NOTHING_LEFT:
        assert FLOW[fid]["amountUSD"] == 0 < FLOW[fid]["fullParkedAmountUSD"]
        assert ff.is_parked_parent(FLOW[fid]), fid
    for fid in OVER_ALLOCATED:
        assert FLOW[fid]["amountUSD"] < 0 < FLOW[fid]["fullParkedAmountUSD"]
        assert ff.is_parked_parent(FLOW[fid]), fid
    # money still on the parent: it is funding, under its status
    assert 0 < FLOW[PARTLY]["amountUSD"] < FLOW[PARTLY]["fullParkedAmountUSD"]
    assert not ff.is_parked_parent(FLOW[PARTLY])
    # a parked flow nobody has allocated yet (itself a child here): whole, under its status
    assert FLOW["323808"]["flowType"] == "Parked" and not FLOW["323808"]["childFlowIds"]
    assert FLOW["323808"]["amountUSD"] == FLOW["323808"]["fullParkedAmountUSD"]
    assert not ff.is_parked_parent(FLOW["323808"])
    assert FLOW["162035"]["flowType"] == "Standard" and not ff.is_parked_parent(FLOW["162035"])


def test_a_parent_fts_lists_no_child_for_stays_where_v1_put_it():
    """Built by hand from 162034 (measured 2026-10-13: none of the 520 lacks a
    child list). Nothing says where its money went, so it is not taken out of
    the status series on a guess."""
    flow = dict(FLOW["162034"], childFlowIds=None)
    assert not ff.is_parked_parent(flow)
    f = ff.flow_record(flow, AT)["funding"]
    assert (f["series"], f["amount_usd"], f["child_flow_count"]) == ("commitment", 1945525, None)


def test_an_over_allocated_flow_with_no_parked_amount_is_still_no_record():
    """Built by hand: a negative amountUSD with nothing parked is v1's
    `no_amount`, as before."""
    flow = dict(FLOW["323807"], fullParkedAmountUSD=None)
    assert not ff.is_parked_parent(flow)
    assert ff.flow_record(flow, AT) == "no_amount"


# ── the record ───────────────────────────────────────────────────────────────

def test_a_parked_parent_record_carries_the_whole_contribution_and_names_its_children():
    rec = ff.flow_record(FLOW["162034"], AT)
    f = rec["funding"]
    assert f["series"] == "parked_parent"
    assert f["status"] == "commitment"                      # FTS's own status, unchanged
    assert f["amount_usd"] == rec["metrics"]["value"] == 1945525
    assert (f["child_flow_count"], f["child_flow_ids"]) == (2, ["162035", "162036"])
    # what FTS said, both amounts, in the raw record
    assert rec["fts"]["amount_usd"] == 0 and rec["fts"]["full_parked_amount_usd"] == 1945525
    assert rec["fts"]["child_flow_ids"] == [162035, 162036]
    assert rec["stable_id"] == "fts-flow-162034"

    over = ff.flow_record(FLOW["323807"], AT)
    assert over["funding"]["series"] == "parked_parent"
    assert over["funding"]["amount_usd"] == 3570560         # the parked amount, not -71
    assert over["fts"]["amount_usd"] == -71 and over["fts"]["full_parked_amount_usd"] == 3570560


def test_every_other_record_says_its_status_and_both_amounts():
    for fid in OTHERS:
        rec = ff.flow_record(FLOW[fid], AT)
        f = rec["funding"]
        assert f["series"] == f["status"] == FLOW[fid]["status"], fid
        assert (f["child_flow_count"], f["child_flow_ids"], f["child_flows_fetched"]) == \
            (None, None, None), fid
        assert rec["fts"]["amount_usd"] == FLOW[fid]["amountUSD"]
        assert rec["fts"]["full_parked_amount_usd"] == FLOW[fid].get("fullParkedAmountUSD")


def test_a_long_child_list_is_counted_and_not_listed():
    """Built by hand from 162034: the longest real list on 2026-10-13 has 21."""
    f = ff.flow_record(dict(FLOW["162034"], childFlowIds=list(range(1, 31))), AT)["funding"]
    assert f["child_flow_count"] == 30 and len(f["child_flow_ids"]) == 30
    f = ff.flow_record(dict(FLOW["162034"], childFlowIds=list(range(1, 32))), AT)["funding"]
    assert f["child_flow_count"] == 31 and f["child_flow_ids"] is None
    assert ff.CHILD_IDS_KEPT == 30


def test_the_children_this_answer_carries_are_counted_on_the_parent():
    recs, summary = _built()
    got = {fid: (recs[fid]["funding"]["child_flows_fetched"], recs[fid]["funding"]["child_flow_count"])
           for fid in PARENTS}
    # 277446's two children are UNRWA allocations FTS files under Syria: not in a PSE answer
    assert got == {"162034": (2, 2), "277446": (0, 2), "323807": (2, 2), "292049": (2, 2)}
    assert summary["records"] == 12 and summary["skipped_no_amount"] == 0
    assert summary["parked_parents"] == 4
    assert summary["parked_parents_usd"] == 1945525 + 600234 + 3570560 + 224568
    assert summary["parked_parents_with_a_child_outside_the_answer"] == 1


def test_a_child_filed_under_a_later_usage_year_than_its_parent_is_still_counted():
    recs, _ = ff.build({2016: [FLOW["162034"]], 2017: [FLOW["162035"], FLOW["162036"]]}, AT)
    (parent,) = [r for r in recs if r["funding"]["flow_id"] == "162034"]
    assert parent["funding"]["child_flows_fetched"] == 2


# ── the row the loader builds ────────────────────────────────────────────────

def test_the_template_reads_the_series_and_v1s_file_falls_back_to_the_status():
    spec = load_spec("funding")
    tpl = spec["indicator"]["template"]
    assert tpl == "funding.{funding.series|funding.status}"
    assert engine.split_segments(tpl) == ["funding", "{funding.series|funding.status}"]
    assert engine.render(tpl, {"funding": {"series": "parked_parent", "status": "paid"}}, slug) == PARENT
    assert engine.render(tpl, {"funding": {"series": "paid", "status": "paid"}}, slug) == "funding.paid"
    # v1's record has no series; an empty one is no series either
    assert engine.render(tpl, {"funding": {"status": "Commitment"}}, slug) == "funding.commitment"
    assert engine.render(tpl, {"funding": {"series": "", "status": "pledge"}}, slug) == "funding.pledge"
    # neither filled: the segment is dropped, as a single path always was
    assert engine.render(tpl, {"funding": {}}, slug) == "funding"
    assert engine.render("x.{a}", {"a": None}, slug) == "x"


def test_the_frozen_fallback_still_files_every_record_under_its_status():
    """v1's file keeps only the amount v1 chose, so it cannot tell a parked
    parent. It is read only where the fetcher has never run."""
    spec = load_spec("funding")
    frozen = ROOT / spec["input"]["fallback"]["root"] / spec["input"]["fallback"]["glob"]
    recs = databank._records(json.loads(databank.read_payload(frozen)), spec)
    seen = Counter()
    for rec in recs:
        row = _row(rec, spec)
        seen[row.indicator] += 1
        assert not any(k.startswith("child_flow") for k in row.attrs)
    assert set(seen) == set(STATUS) and sum(seen.values()) == len(recs) > 9000


def test_a_parked_parent_is_one_row_of_its_own_indicator_with_what_it_always_said():
    spec = load_spec("funding")
    recs, _ = _built()
    for fid in NOTHING_LEFT:
        held, row = HELD[fid], _row(recs[fid], spec)
        assert held["indicator"] in STATUS and row.indicator == PARENT
        # the same date, place, unit and amount...
        assert (str(row.occurred_at)[:10], row.place_id, row.unit, float(row.value_num)) == \
            (held["occurred_at"], held["place_id"], held["unit"], held["value_num"])
        # ...and the same attrs, plus what identifies its children
        f = recs[fid]["funding"]
        assert row.attrs == {**held["attrs"], "child_flow_count": f["child_flow_count"],
                             "child_flow_ids": f["child_flow_ids"],
                             "child_flows_fetched": f["child_flows_fetched"]}
        assert row.attrs["status"] == held["attrs"]["status"]          # paid / commitment, kept
        # a new identity that differs in the indicator only, under the same flow number
        assert _key(row, spec) == held["identity_key"].replace(f"|{held['indicator']}|", f"|{PARENT}|")
        assert row.attrs[spec["identity"]["revises_by"]] == held["attrs"]["flow_id"] == fid
    assert _row(recs["277446"], spec).attrs["child_flows_fetched"] == 0     # a zero is said, not dropped


def test_an_over_allocated_parent_held_under_a_status_gets_a_new_identity_too():
    """292049 is held under `funding.commitment` at USD 229,779, from a night
    when FTS still showed money on it. FTS now shows USD -98,805 on it and its
    two children in the answer carry USD 323,373. v1's rule dropped the flow,
    so nothing would ever revise the held row."""
    spec = load_spec("funding")
    recs, _ = _built()
    held, row = HELD["292049"], _row(recs["292049"], spec)
    assert (held["indicator"], held["value_num"]) == ("funding.commitment", 229779.0)
    assert (row.indicator, row.value_num) == (PARENT, 224568)
    assert _key(row, spec) != held["identity_key"]
    assert row.attrs["flow_id"] == held["attrs"]["flow_id"]
    assert sum(FLOW[c]["amountUSD"] for c in ("292109", "401972")) == 323373
    assert "323807" not in HELD and _row(recs["323807"], spec).indicator == PARENT


def test_no_other_row_changes_its_identity_or_its_content():
    """9,809 of the 10,375 rows are already held (the dry run of 2026-10-13):
    a record that is not a parked parent must read back exactly as held, or
    the first night would rewrite the dataset."""
    spec = load_spec("funding")
    recs, _ = _built()
    for fid in OTHERS:
        held, row = HELD[fid], _row(recs[fid], spec)
        assert row.indicator == held["indicator"], fid
        assert _key(row, spec) == held["identity_key"], fid
        assert _content(row) == _held_content(held), fid


def test_the_unregistered_twin_says_what_the_engine_says():
    spec = load_spec("funding")
    assert spec["transform"] == "engine"
    recs, _ = _built()
    for fid, rec in recs.items():
        row = _row(rec, spec)
        (twin,) = databank.t_funding(rec, spec, PLACES, Counter())
        assert (twin.indicator, twin.occurred_at, twin.value_num, twin.unit, twin.place_id,
                twin.attrs, twin.v1_stable_id) == \
            (row.indicator, row.occurred_at, row.value_num, row.unit, row.place_id,
             row.attrs, row.v1_stable_id), fid


# ── the money ────────────────────────────────────────────────────────────────

def _sums(recs, spec):
    out = Counter()
    for rec in recs.values():
        row = _row(rec, spec)
        out[row.indicator] += row.value_num
    return out


def test_a_contribution_is_counted_once_in_the_status_series():
    spec = load_spec("funding")
    recs, _ = _built()
    sums = _sums(recs, spec)
    # 162034: USD 1,945,525 parked, allocated to 162035 (paid) and 162036 (commitment)
    family = [recs[f]["funding"] for f in ("162035", "162036")]
    assert sum(f["amount_usd"] for f in family) == FLOW["162034"]["fullParkedAmountUSD"] == 1945525
    assert sums["funding.paid"] == 1297017 + 1004240 + 2566391 + 224568 + 1523504 + 398951
    assert sums["funding.commitment"] == 648508 + 98805
    assert sums["funding.pledge"] == 0
    assert sums[PARENT] == 1945525 + 600234 + 3570560 + 224568
    # what v1's rule counted for the same twelve flows: the two parents with
    # nothing left a second time, under their own status
    before = Counter()
    for f in FLOWS:
        amount = f["amountUSD"] or f.get("fullParkedAmountUSD") or 0
        if amount > 0:
            before[f"funding.{f['status']}"] += amount
    assert before["funding.commitment"] - sums["funding.commitment"] == 1945525      # 162034
    assert before["funding.paid"] - sums["funding.paid"] == 600234                   # 277446


def test_a_partly_allocated_parent_keeps_what_is_left_on_it():
    recs, _ = _built()
    f = recs[PARTLY]["funding"]
    assert (f["series"], f["amount_usd"]) == ("paid", 1523504)
    assert recs[PARTLY]["fts"]["full_parked_amount_usd"] == 1922455
    # the remainder and its one child are the whole contribution, to the dollar
    assert FLOW[PARTLY]["childFlowIds"] == [257274]
    assert f["amount_usd"] + recs["257274"]["funding"]["amount_usd"] == 1922455


def test_a_chain_counts_only_what_is_left_at_each_level():
    """Built by hand from the 162034 family (measured 2026-10-13: no child of
    a parked parent is itself one). The child 162036 is made a parked parent
    with nothing left, allocated to a grandchild."""
    child = dict(FLOW["162036"], flowType="Parked", amountUSD=0,
                 fullParkedAmountUSD=648508, childFlowIds=[900001])
    grandchild = dict(FLOW["162035"], id="900001", amountUSD=648508, parentFlowId=162036)
    recs, summary = ff.build({2016: [FLOW["162034"], FLOW["162035"], child, grandchild]}, AT)
    series = {r["funding"]["flow_id"]: (r["funding"]["series"], r["funding"]["amount_usd"]) for r in recs}
    assert series == {"162034": ("parked_parent", 1945525), "162036": ("parked_parent", 648508),
                      "162035": ("paid", 1297017), "900001": ("paid", 648508)}
    in_status = sum(usd for s, usd in series.values() if s != "parked_parent")
    assert in_status == 1945525                 # the contribution, once
    # and the parents' own series is not a total: it holds both levels
    assert summary["parked_parents_usd"] == 1945525 + 648508


# ── the registry: a name and a warning, and never the prefix rule ────────────

def test_the_parked_parent_has_its_own_rule_a_warning_and_a_name_in_both_languages():
    spec = load_spec("funding")
    rules = spec["registry"]["rules"]
    assert rules[0]["when"] == {"equals": PARENT}           # before the prefix rule
    got, conflicts = lr.classify([(i, "USD", 1) for i in (*STATUS, PARENT)], rules)
    assert set(got) == {*STATUS, PARENT} and conflicts == []
    parent = got[PARENT]
    assert (parent["concept"], parent["measure_kind"], parent["canonical_unit"]) == \
        ("funding.humanitarian", "flow", "USD")
    assert "never add this series" in parent["serve_warning"]
    assert "child flows" in parent["serve_warning"]
    assert "ما بتنجمع" in parent["serve_warning_ar"]
    for status in STATUS:
        assert got[status]["serve_warning"] is None and got[status]["polarity"] == 1
    en, ar = lr.name_for(PARENT, parent, None, lr.load_names())
    assert "already counted in its child flows" in en
    assert ar and "أوتشا" in ar
    assert spec["registry"]["max_unclassified"] == 0


# ── the held rows close by themselves, and the first night needs a hand ──────

def _run(monkeypatch, tmp_path, allow_absent=None):
    """`databank.run("funding", dry_run=True)` on the fixture: the real spec,
    the real engine and the real file reader; a connection that answers the
    one question that matters, which rows are held."""
    recs, _ = ff.build({2026: FLOWS}, AT)
    raw = tmp_path / "raw" / "fts"
    raw.mkdir(parents=True)
    (raw / "flows.json").write_text(json.dumps({"metadata": {}, "data": recs}))
    real = load_spec("funding")
    spec = dict(real, input=dict(real["input"], root=str(raw)), expect={"min_records": 1})
    stored = [(h["identity_key"], 1000 + i, h["value_num"], None, h["unit"], h["place_id"],
               h["attrs"], DS, h["v1_stable_id"], h["occurred_at"])
              for i, h in enumerate(HELD.values())]

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None): self.sql = sql
        def fetchall(self): return stored if "o.identity_key" in self.sql else []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()

    monkeypatch.setattr(databank, "load_spec", lambda c: spec)
    monkeypatch.setattr(databank, "connect", lambda: Conn())
    monkeypatch.setattr(databank, "load_places", lambda conn: dict(PLACES))
    monkeypatch.setattr(databank, "PointResolver", lambda conn: _NoPoint())
    monkeypatch.setattr(databank.bronze, "put", lambda *a, **k: type("R", (), {"ref": "bronze:x"}))
    monkeypatch.setattr(databank, "RUNS", tmp_path / "runs.ndjson")
    return databank.run("funding", dry_run=True, allow_absent=allow_absent)


def test_the_held_status_rows_of_the_parents_close_through_revises_by(monkeypatch, tmp_path):
    out = _run(monkeypatch, tmp_path, allow_absent=3)
    assert out["records_read"] == out["observations_emitted"] == 12
    assert out["drops"] == {}
    assert out["notes"]["identity_already_held"] == 8            # the eight that are not parents
    assert "revisions" not in out["notes"]                       # none rewritten in place
    assert out["notes"][f"revised_upstream:{DS}"] == 3
    closing = out["revised_upstream"]
    assert closing["would_close"] == 3 and closing["closed"] == 0   # a dry run closes nothing
    assert sorted(closing["samples"]) == sorted(HELD[f]["identity_key"]
                                                for f in ("162034", "277446", "292049"))
    assert all(k.split("|")[1] in STATUS for k in closing["samples"])


def test_the_default_ceiling_refuses_the_first_night_and_one_run_may_lift_it(monkeypatch, tmp_path):
    """Three of eleven held rows is over the default ceiling (5% of the rows
    held, at least one), as 535 of 10,431 was over 521 on 2026-10-13. The lift
    is one run's, given by hand; the spec carries no ceiling and the nightly
    passes none."""
    with pytest.raises(SpecRefused, match=r"3 held rows revised under a new identity > "
                                          r"ceiling 1 of 11 .* nothing is closed"):
        _run(monkeypatch, tmp_path)
    with pytest.raises(SpecRefused, match=r"> ceiling 2 of 11"):
        _run(monkeypatch, tmp_path / "again", allow_absent=2)
    assert "max_absent" not in load_spec("funding")["identity"]
    assert "allow_absent" not in inspect.getsource(databank.run_all)
    assert inspect.getsource(databank.run).count("cap = max(cap, allow_absent)") == 2
