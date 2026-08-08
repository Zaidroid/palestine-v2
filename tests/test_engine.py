"""The declarative engine: the grammar is closed, and the spec cannot lie.

These test the engine's own rules. That its OUTPUT matches the transformer it
replaced is a different question, answered by ops/spec_equivalence.py over
every record — and it earned its place immediately: it caught two engine bugs
on the first migration that no unit test here would have found, because both
were about agreeing with existing behaviour rather than being correct in
isolation.
"""
from __future__ import annotations

import pytest
import yaml

from ingest import engine
from ingest.spec import CONDITION_OPS, SPECS


def slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


REC = {"date": "2024-12-31", "event_type": "settler_population",
       "funding": {"status": "paid", "amount_usd": 12.5},
       "metrics": {"count": 3, "unit": "settlers"},
       "sources": [{"name": "Peace Now", "fetched_at": "2026-08-07T03:37:08.923Z"}]}


# ── the closed grammar ───────────────────────────────────────────────────────

def test_the_grammar_is_closed():
    with pytest.raises(engine.EngineRefused) as e:
        engine.check({"field": "date", "op": "regex", "value": ".*"}, REC)
    assert "closed on purpose" in str(e.value)


def test_the_validator_and_the_engine_agree_on_the_operator_list():
    """Two lists of operators that drift apart give a spec that validates and
    then refuses at row time — the worst of both gates."""
    assert set(CONDITION_OPS) == set(engine.OPS)


@pytest.mark.parametrize("cond,expected", [
    ({"op": "always"}, True),
    ({"field": "event_type", "op": "eq", "value": "settler_population"}, True),
    ({"field": "event_type", "op": "eq", "value": "other"}, False),
    ({"field": "date", "op": "endswith", "value": "-12-31"}, True),
    ({"field": "funding.status", "op": "in", "value": ["paid", "pledge"]}, True),
    ({"field": "missing", "op": "present"}, False),
    ({"field": "missing", "op": "absent"}, True),
    ({"field": "date", "op": "equals_fetch_day"}, False),
    ({"all": [{"field": "date", "op": "endswith", "value": "-12-31"},
              {"field": "event_type", "op": "eq",
               "value": "settler_population"}]}, True),
    ({"all": [{"field": "date", "op": "endswith", "value": "-12-31"},
              {"field": "event_type", "op": "eq", "value": "no"}]}, False),
    ({"any": [{"field": "event_type", "op": "eq", "value": "no"},
              {"op": "always"}]}, True),
])
def test_conditions(cond, expected):
    assert engine.check(cond, REC) is expected


def test_a_missing_field_is_false_not_an_error():
    """An absent field is data — the record does not say. Raising would make
    every optional field a landmine."""
    assert engine.check({"field": "nope.deeper", "op": "eq", "value": "x"},
                        REC) is False


# ── templates ────────────────────────────────────────────────────────────────

def test_a_dotted_path_inside_braces_is_one_segment():
    """`funding.{funding.status}` is two segments, not three. Splitting on
    every dot produced the literal string 'funding.{funding.status}' as the
    indicator on all 9,990 funding rows."""
    assert engine.split_segments("funding.{funding.status}") == \
        ["funding", "{funding.status}"]
    assert engine.render("funding.{funding.status}", REC, slug) == "funding.paid"


def test_a_null_brace_drops_its_segment():
    """casualties.{dimension}.{label} becomes casualties.annual_total when
    there is no label — never 'casualties.annual_total.None'."""
    rec = {"dim": "annual_total", "label": None}
    assert engine.render("casualties.{dim}.{label}", rec, slug) == \
        "casualties.annual_total"


def test_interpolated_values_are_slugged():
    rec = {"t": "Separation Barrier Segment"}
    assert engine.render("x.{t}", rec, slug) == "x.separation_barrier_segment"


# ── dates: the two named laws ────────────────────────────────────────────────

def test_law_1_reported_at_only_keeps_the_full_stamp():
    """occurred_at takes the DAY (the fact is 'sometime that day'); reported_at
    keeps the full timestamp, because when WE saw it is our own provenance and
    is known to the second. Truncating it silently dropped sub-second
    precision on 329 culture rows."""
    attrs = {}
    occurred, precision, reported = engine.resolve_date(
        {"from": "date", "precision": "day",
         "rules": [{"when": {"field": "date", "op": "always"},
                    "then": {"reported_at_only": True}}]},
        REC, attrs)
    assert precision == "unknown"
    assert occurred == "2026-08-07"
    assert reported == "2026-08-07T03:37:08.923Z"


def test_law_2_year_buckets_become_years():
    attrs = {}
    occurred, precision, _ = engine.resolve_date(
        {"from": "date", "precision": "day",
         "rules": [{"when": {"field": "date", "op": "endswith",
                             "value": "-12-31"},
                    "then": {"truncate_to": "year", "precision": "year"}}]},
        REC, attrs)
    assert (occurred, precision) == ("2024-01-01", "year")


def test_rules_are_ordered_and_first_match_wins():
    attrs = {}
    occurred, precision, _ = engine.resolve_date(
        {"from": "date", "precision": "day", "rules": [
            {"when": {"op": "always"}, "then": {"precision": "month"}},
            {"when": {"op": "always"}, "then": {"precision": "year"}}]},
        REC, attrs)
    assert precision == "month"


def test_prose_in_an_executable_slot_is_refused():
    """`then: "NO-OP — must not fire"` is documentation of a rule's ABSENCE.
    Sitting in `then:` made it look like a rule for three days."""
    with pytest.raises(engine.EngineRefused) as e:
        engine.resolve_date(
            {"from": "date", "rules": [
                {"when": {"op": "always"}, "then": "truncate to year start"}]},
            REC, {})
    assert "rationale" in str(e.value)


def test_a_rule_with_only_a_rationale_never_fires():
    """conflict documents that law 2 must NOT apply to it — every -12-31 there
    is a real December day. Documentation of an absence is not an instruction."""
    occurred, precision, _ = engine.resolve_date(
        {"from": "date", "precision": "day",
         "rules": [{"if": "date endswith -12-31",
                    "rationale": "NO-OP — this rule must not fire here"}]},
        REC, {})
    assert (occurred, precision) == ("2024-12-31", "day")


def test_a_rule_may_add_attrs_so_the_row_states_its_own_span():
    attrs = {}
    engine.resolve_date(
        {"from": "nothing", "rules": [
            {"when": {"field": "nothing", "op": "absent"},
             "then": {"literal": "2008-01-01", "precision": "unknown",
                      "attrs": {"coverage_start": "2008-01-01"}}}]},
        REC, attrs)
    assert attrs == {"coverage_start": "2008-01-01"}


def test_precision_must_be_a_known_grade():
    with pytest.raises(engine.EngineRefused):
        engine.resolve_date(
            {"from": "date", "precision": "see rules below"}, REC, {})


# ── the declaration ──────────────────────────────────────────────────────────

def test_every_spec_declares_which_mechanism_drives_it():
    for p in sorted(SPECS.glob("*.yaml")):
        spec = yaml.safe_load(p.read_text())
        assert spec.get("transform"), (
            f"{p.stem}: no `transform:` — a half-migrated format where nobody "
            "can tell which half they are reading is worse than none")


def test_the_declared_transform_is_the_one_that_runs():
    """The declaration is checked, not decorative. A spec saying `engine`
    while a hand-written transformer runs would make the reader confidently
    wrong instead of merely uninformed."""
    from ingest.databank import TRANSFORMERS, t_engine
    for p in sorted(SPECS.glob("*.yaml")):
        spec = yaml.safe_load(p.read_text())
        fn = TRANSFORMERS.get(p.stem)
        actual = ("none" if fn is None else "engine" if fn is t_engine
                  else f"python:{fn.__name__}")
        assert spec["transform"].split()[0] == actual, p.stem
