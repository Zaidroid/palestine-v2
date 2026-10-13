"""A projection is not a measurement (migration 115, indicator_def.projection;
serve/app.py _projections, the guards in serve/ and the registry loader). The
gap radar and the attribution file are held in tests/test_more_projections_radar.py.

Two declared facts, each doing one thing. `ask_by_name` (migration 114) keeps
a projection series out of its category's rows unless it is asked for by name:
the category route has ONE condition, and the projection's series declare the
flag like Peace Now's settlements do. `projection` decides everything that is
a projection's own: the refusals in compare, correlate and the scan, what the
spoken answers say, where the listing puts it, and which key its rows travel
under.

No database, no network and no running API: every query is answered by a
stand-in, so what is held here is what each guard ASKS the store and what it
does with the answer. The store has no `projection` column until 115.
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg
import pytest
import yaml

from ingest import spec as spec_mod
from ops import fetch_wpp, load_registry
from serve import app as A, correlate as C, licence as L, mcp_en as E, mcp_server as M

ROOT = Path(__file__).resolve().parent.parent
SPEC = yaml.safe_load((ROOT / "db" / "mappings" / "population_wpp_projection.yaml")
                      .read_text(encoding="utf-8"))
MIGRATION = ROOT / "db" / "migrations" / "115_a_projection_is_not_a_measurement.sql"
P_DEATHS = "population.wpp_projection.deaths"
P_BIRTHS = "population.wpp_projection.births"
E_DEATHS = "population.wpp.deaths"
PROJ = frozenset({P_DEATHS, P_BIRTHS})
ORDINARY = (E_DEATHS, "economic.sp_pop_totl", "settlements.settler_population", "prisoners.total")
WARN = {"en": "A PROJECTION, not a measurement: …", "ar": "هاد إسقاط مش قياس: …"}


class Store:
    """Answers serve/app.py's queries by what they ask for, and keeps them."""

    def __init__(self, rows=(), proj=PROJ, fail=None, by_name=None):
        self.rows, self.proj, self.fail, self.asked = list(rows), proj, fail, []
        # what migration 115 and the spec declare: a projection is asked for by name
        self.by_name = {i: "economic" for i in proj} if by_name is None else by_name

    def __call__(self, sql, params=()):
        self.asked.append((sql, params))
        if "FROM indicator_def WHERE projection" in sql:
            if self.fail:
                raise self.fail
            return [{"indicator": i} for i in sorted(self.proj)]
        if "FROM indicator_def i WHERE i.ask_by_name" in sql:
            return [{"indicator": i, "category": c} for i, c in sorted(self.by_name.items())]
        if "NOT y.ask_by_name" in sql:           # does the filter name an ordinary series?
            return [{"yes": 1}] if any(o.startswith(params[0][:-1]) for o in ORDINARY) else []
        if "FROM category WHERE active" in sql:
            return [{"key": k} for k in ("economic", "prisoners", "settlements")]
        if "to_regclass" in sql:
            return [{"ok": False}]
        if "serve_warning" in sql:
            return [{"indicator": i, "serve_warning": WARN["en"], "serve_warning_ar": WARN["ar"]}
                    for i in params[0] if i in self.proj]
        if "name_en" in sql and "ANY" in sql:
            return [{"indicator": i, "name_en": "Projection: " + i.rsplit(".", 1)[1].capitalize() + " per year",
                     "name_ar": "إسقاط: عدد الوفيات في السنة"} for i in params[0] if i in self.proj]
        return self.rows

    def main(self):
        """The one query that reads rows."""
        return next((s, p) for s, p in self.asked if "ORDER BY r.occurred_at DESC" in s)


@pytest.fixture
def store(monkeypatch):
    def make(**kw):
        s = Store(**kw)
        monkeypatch.setattr(A, "q", s)
        monkeypatch.setattr(A, "q_cached", s)
        return s
    return make


def _row(indicator, year, value, **attrs):
    return {"indicator": indicator, "occurred_at": f"{year}-01-01", "occurred_precision": "year",
            "value_num": value, "value_text": None, "unit": "persons", "place_en": None, "place_ar": None,
            "attrs": attrs, "source_key": "un_wpp", "dataset_key": "x", "license_spdx": "CC-BY-IGO-3.0",
            "redistribution": "attribution", "commercial_use": True, "attribution_text": "UN DESA"}


# ── the one declared fact ────────────────────────────────────────────────────

def test_the_registry_is_asked_once_and_in_one_place(store):
    s = store()
    assert A._projections() == PROJ
    assert [q for q, _ in s.asked] == ["SELECT indicator FROM indicator_def WHERE projection"]
    src = (ROOT / "serve" / "app.py").read_text(encoding="utf-8")
    assert src.count("FROM indicator_def WHERE projection") == 1
    # ...and it is not a second condition on the category's rows: `ask_by_name`
    # (114) is the one, and the route's SQL never reads the projection column
    assert src.count("NOT y.ask_by_name") == 1 and "y.projection" not in src
    # no name pattern anywhere in the serving code: the registry says it, not the key
    for f in ("app.py", "correlate.py", "mcp_server.py", "mcp_en.py", "licence.py", "when.py"):
        assert "wpp_projection" not in (ROOT / "serve" / f).read_text(encoding="utf-8"), f


def test_before_the_migration_there_are_none_and_any_other_failure_is_raised(store):
    store(fail=psycopg.errors.UndefinedColumn("column \"projection\" does not exist"))
    assert A._projections() == frozenset()
    store(fail=psycopg.OperationalError("connection refused"))
    with pytest.raises(psycopg.OperationalError):
        A._projections()                    # never "no projections" because the store did not answer


# ── the category route: one condition, `ask_by_name`, and the mark ───────────

BY_NAME_SQL = ("NOT EXISTS (SELECT 1 FROM indicator_def n"
               " WHERE n.indicator = r.indicator AND n.ask_by_name)")


def test_a_category_s_rows_leave_projections_out_and_say_they_are_held(store):
    s = store(rows=[_row("economic.sp_pop_totl", 2025, 5.5e6)])
    out = A.databank_category("economic", None, None, False, 10, None)
    sql, params = s.main()
    assert sql.count(BY_NAME_SQL) == 1 and "y.projection" not in sql
    # no filter: it matches every observed series, so the condition is there and no
    # projection row passes; it takes no parameter of its own
    assert params == ("economic", 10)
    assert sql.count("%s") == len(params)                     # every placeholder has its value, in order
    assert "projections" not in out and out["count"] == 1
    held = out["by_name_only"]
    assert (held["series"], held["indicator_prefix"], held["example"]) == \
        (2, "population.wpp_projection.", P_BIRTHS)
    assert held["example_en"].startswith("Projection: ") and held["example_ar"].startswith("إسقاط: ")
    assert held["note"].startswith("projections (a model's output, not measurements); each is served when asked")


def test_the_estimates_prefix_gets_the_estimates_alone(store):
    s = store(rows=[_row(E_DEATHS, 2023, 38937.0)])
    out = A.databank_category("economic", "population.wpp", None, False, 10, None)
    _sql, params = s.main()
    # `population.wpp` is also a prefix of the projection's name: the store is
    # asked whether a series that is NOT asked for by name matches it, and one does
    assert params == ("economic", "population.wpp%", 10) and BY_NAME_SQL in _sql
    assert "projections" not in out and out["by_name_only"]["series"] == 2


def test_a_named_projection_is_served_and_says_so(store):
    s = store(rows=[_row(P_DEATHS, 2100, 103216.0, projection=True),
                    _row(P_DEATHS, 2099, 102800.0, projection=True)])
    out = A.databank_category("economic", P_DEATHS, None, False, 10, None)
    _sql, params = s.main()
    assert params == ("economic", P_DEATHS + "%", 10)
    assert BY_NAME_SQL not in _sql, "it names only series asked for by name: they are what was asked for"
    assert out["projections"] == [P_DEATHS] and "by_name_only" not in out
    assert out["warnings"] == {P_DEATHS: WARN} and out["names"][P_DEATHS]["en"].startswith("Projection: ")


def test_the_condition_keeps_its_place_among_the_other_filters(store):
    s = store(rows=[])
    A.databank_category("economic", "economic.sp", "2026-01-01", False, 5, "Ramle")
    sql, params = s.main()
    assert params == ("economic", "economic.sp%", "Ramle", "Ramle", "2026-01-01", 5)
    assert sql.count("%s") == len(params) and BY_NAME_SQL in sql
    # a category that holds no series asked for by name runs the query it always ran
    s = store(rows=[])
    A.databank_category("prisoners", None, None, False, 5, None)
    sql, params = s.main()
    assert "ask_by_name" not in sql and params == ("prisoners", 5)


def test_a_family_held_one_per_entity_keeps_its_own_note_and_is_no_projection(store):
    """Peace Now's settlements are asked for by name and are measurements: the
    mark, the wording and the refusals of a projection are not theirs."""
    fam = "settlements.population_by_settlement."
    s = store(rows=[_row("settlements.settler_population", 2024, 511100.0)],
              by_name={fam + "pn0016": "settlements", fam + "pn0017": "settlements", P_DEATHS: "economic"})
    out = A.databank_category("settlements", None, None, False, 10, None)
    _sql, params = s.main()
    assert params == ("settlements", 10) and BY_NAME_SQL in _sql
    assert out["by_name_only"]["series"] == 2 and "projections" not in out
    assert out["by_name_only"]["note"].startswith("series held one per entity; each is served when asked")
    s = store(rows=[_row(fam + "pn0016", 2024, 20000.0)],
              by_name={fam + "pn0016": "settlements", P_DEATHS: "economic"})
    assert "projections" not in A.databank_category("settlements", fam + "pn0016", None, False, 10, None)


# ── the indicators listing ───────────────────────────────────────────────────

def test_the_listing_says_which_series_are_projections_and_lists_them_last(store):
    store(rows=[{"indicator": P_DEATHS, "rows_served": 77, "to_date": "2100-01-01"},
                {"indicator": E_DEATHS, "rows_served": 74, "to_date": "2023-01-01"},
                {"indicator": P_BIRTHS, "rows_served": 77, "to_date": "2100-01-01"},
                {"indicator": "economic.sp_pop_totl", "rows_served": 66, "to_date": "2025-01-01"}])
    out = A.databank_indicators(None, "deaths", None, 100, None)
    assert [(r["indicator"], r["projection"]) for r in out["indicators"]] == [
        (E_DEATHS, False), ("economic.sp_pop_totl", False), (P_DEATHS, True), (P_BIRTHS, True)]


# ── compare and correlate ────────────────────────────────────────────────────

def _series(indicator, projection, n=20, start=2000):
    from datetime import date
    return {"known": True, "indicator": indicator, "projection": projection,
            "concept_key": "population.count", "measure_kind": "flow", "polarity": None,
            "grain": "year", "place_grain": "region", "canonical_unit": "persons",
            "points": [{"at": date(start + i, 1, 1), "prec": "year", "value": float(100 + (i * 37) % 11),
                        "unit": "persons"} for i in range(n)],
            "n": n, "units": ["persons"], "unit_mixed": False, "sources": ["UN"],
            "source_names": {"UN"}, "attribution": ["UN DESA"], "redistribution": "attribution",
            "commercial_use": True}


def test_a_series_carries_the_registry_s_word(store):
    store(rows=[])
    assert A._series_at(P_DEATHS, None, None, None)["projection"] is True
    assert A._series_at(E_DEATHS, None, None, None)["projection"] is False


def test_compare_refuses_a_projection_beside_an_observed_series_and_reads_nothing(store, monkeypatch):
    store()
    monkeypatch.setattr(A, "_series", lambda *a, **k: pytest.fail("a refused pair must not be read"))
    out = A.databank_compare(f"{E_DEATHS},{P_DEATHS}", None, None, None, None)
    assert out["refused"] is True and out["series"] == [] and out["overlap"]["n"] == 0
    assert out["reasons"] == [C.projection_reason([P_DEATHS], [E_DEATHS])]
    assert "is a PROJECTION (a model's output, not a measurement)" in out["reasons"][0]
    assert out["warnings"] == {P_DEATHS: WARN}


def test_compare_serves_projections_together_and_one_projection_with_itself(store, monkeypatch):
    store()
    monkeypatch.setattr(A, "_series", lambda k, *a, **kw: _series(k, k in PROJ, start=2024))
    for asked in (f"{P_DEATHS},{P_BIRTHS}", f"{P_DEATHS},{P_DEATHS}"):
        out = A.databank_compare(asked, None, None, None, None)
        assert "refused" not in out and [s["projection"] for s in out["series"]] == [True, True]
        assert out["warnings"][P_DEATHS] == WARN                # said on the path that returns the rows
    out = A.databank_compare(f"{E_DEATHS},economic.sp_pop_totl", None, None, None, None)
    assert "refused" not in out and "warnings" not in out


def test_correlate_refuses_the_pair_with_a_reason_and_no_number(store, monkeypatch):
    store()
    monkeypatch.setattr(A, "_series", lambda k, *a, **kw: _series(k, k in PROJ))
    for a, b in ((E_DEATHS, P_DEATHS), (P_DEATHS, E_DEATHS)):
        out = A.databank_correlate(a, b, None, None, None, "spearman", 0, True, "diff", None, None)
        assert out["refused"] is True and "rho" not in out
        assert out["reasons"][0] == C.projection_reason([P_DEATHS], [E_DEATHS])
        assert out["warnings"] == {P_DEATHS: WARN}
    # allow_same_concept lifts one refusal only, and it is not this one (passed True above)
    assert C.check_comparable(_series(E_DEATHS, False), _series("economic.x", False)) != []   # same concept
    assert not any("PROJECTION" in r for r in C.check_comparable(_series(P_DEATHS, True), _series(P_BIRTHS, True)))


def test_the_refusal_is_said_in_arabic_and_counted_by_the_scan():
    reason = C.projection_reason([P_DEATHS], [E_DEATHS])
    ar = C.reason_ar(reason)
    assert P_DEATHS in ar and E_DEATHS in ar and "إسقاط" in ar and "مرصودة" in ar
    assert ar != "مرفوض — السبب مفصّل في `reasons`"
    assert A._skip_reason(reason) == "a projection against an observed series"
    assert C.skip_ar("a projection against an observed series") == "إسقاط مقابل سلسلة مرصودة"


def test_the_scan_never_takes_a_projection_as_a_candidate(store, monkeypatch):
    s = store(rows=[])
    monkeypatch.setattr(A, "_series", lambda k, *a, **kw: _series(k, k in PROJ))
    out = A.databank_correlate_scan(E_DEATHS, None, None, None, "spearman", 40, False)
    sql, params = next((q, p) for q, p in s.asked if "FROM indicator_def d" in q)
    assert "d.indicator <> ALL(%(proj)s)" in sql and params["proj"] == sorted(PROJ)
    assert out["refused"] is True                              # the stand-in offers no candidate at all
    # ...and a projection that is the SUBJECT meets only observed candidates, each refused
    monkeypatch.setattr(A, "q", lambda sql, params=(): (
        [{"indicator": "economic.sp_pop_totl", "concept_key": "x", "measure_kind": "stock",
          "place_grain": "region", "grain": "year", "canonical_unit": "persons", "n": 60}]
        if "FROM indicator_def d" in sql else []))
    out = A.databank_correlate_scan(P_DEATHS, None, None, None, "spearman", 40, False)
    assert out["tested"] == 0 and out["matches"] == []
    assert out["skipped"] == {"a projection against an observed series": 1}


# ── the spoken answers ───────────────────────────────────────────────────────

def _category_payload(projected: bool) -> dict:
    ind = P_DEATHS if projected else E_DEATHS
    items = [_row(ind, y, v, **({"projection": True} if projected else {}))
             for y, v in ((2100, 103216.0), (2099, 102800.0))] if projected else [_row(ind, 2023, 38937.0)]
    for it in items:
        it["attribution"] = it.pop("attribution_text")
    return {"category": "economic", "as_of": None, "district": None, "count": len(items), "items": items,
            "attribution": ["UN DESA"],
            "names": {ind: {"en": ("Projection: " if projected else "") + "Deaths per year",
                            "ar": ("إسقاط: " if projected else "") + "عدد الوفيات في السنة"}},
            **({"warnings": {ind: WARN}, "projections": [ind]} if projected else {})}


def _api(payload):
    def api(path, **params):
        if path == "/v2/databank/indicators":
            return {"indicators": []}
        return payload
    return api


def test_a_named_projection_is_never_spoken_as_the_latest_figure(monkeypatch):
    monkeypatch.setattr(M, "api", _api(_category_payload(True)))
    out = M.databank("economic", P_DEATHS)
    assert "آخر الأرقام" not in out["answer"] and "أحدث" not in out["answer"]
    assert "إسقاط مش قياس، وهاي أبعد سنة فيه: إسقاط: عدد الوفيات في السنة: 103,216 persons سنة 2100" in out["answer"]
    assert out["answer"].count("تنبيه: " + WARN["ar"]) == 1
    assert out["latest_by_indicator"] == []
    assert [r["occurred_at"] for r in out["projected_by_indicator"]] == ["2100-01-01"]
    en = E.databank(out)
    assert "latest" not in en and "newest" not in en
    assert "a projection, not a measurement; its farthest year: Projection: Deaths per year: 103,216 persons in 2100" in en
    assert en.count("Note: " + WARN["en"]) == 1 and "(farthest 2 rows shown.)" in en


def test_an_observed_series_is_spoken_as_before(monkeypatch):
    monkeypatch.setattr(M, "api", _api(_category_payload(False)))
    out = M.databank("economic", E_DEATHS)
    assert "economic — آخر الأرقام: عدد الوفيات في السنة: 38,937 persons سنة 2023" in out["answer"]
    assert "(أحدث 1 سجلات معروضة)" in out["answer"] and "projected_by_indicator" not in out
    assert [r["occurred_at"] for r in out["latest_by_indicator"]] == ["2023-01-01"]
    assert "economic — latest: Deaths per year: 38,937 persons in 2023" in E.databank(out)
    assert "(newest 1 rows shown.)" in E.databank(out)


def test_a_warning_one_family_shares_is_said_once(monkeypatch):
    payload = _category_payload(True)
    payload["items"].append({**payload["items"][0], "indicator": P_BIRTHS})
    payload["warnings"][P_BIRTHS] = WARN
    payload["projections"] = [P_BIRTHS, P_DEATHS]
    monkeypatch.setattr(M, "api", _api(payload))
    out = M.databank("economic", "population.wpp_projection")
    assert out["answer"].count("تنبيه:") == 1 and E.databank(out).count("Note:") == 1


def test_the_partner_filter_reads_the_new_key_too():
    row = {"indicator": P_DEATHS, "redistribution": "no-redistribution", "commercial_use": False,
           "source_key": "x"}
    out = L.apply("databank", {"answer": "…", "items": [dict(row)], "latest_by_indicator": [],
                               "projected_by_indicator": [dict(row)], "count": 1}, "partner")
    assert out["items"] == [] and out["projected_by_indicator"] == []


def test_compare_says_why_it_refused(monkeypatch):
    refused = {"refused": True, "series": [], "overlap": {"from": None, "to": None, "n": 0},
               "reasons": [C.projection_reason([P_DEATHS], [E_DEATHS])], "warnings": {P_DEATHS: WARN}}
    monkeypatch.setattr(M, "api", lambda path, **kw: refused)
    out = M.compare(f"{E_DEATHS},{P_DEATHS}")
    assert out["answer"].startswith("ما بحطهم جنب بعض: ") and "إسقاط (ناتج نموذج، مش قياس)" in out["answer"]
    assert out["answer"].endswith("تنبيه: " + WARN["ar"]) and out["refused"] is True
    en = E.compare(out)
    assert en.startswith("Refused: ") and "is a PROJECTION" in en and en.endswith("Note: " + WARN["en"])


def test_the_series_tool_says_a_projection_whole_and_never_as_recent_readings(monkeypatch):
    from datetime import date
    pts = [{"at": f"{y}-01-01", "prec": "year", "value": v, "unit": "persons"}
           for y, v in ((2024, 32257.0), (2025, 23414.0), (2026, 16412.0), (2100, 103216.0))]
    calls = []

    def api(path, **kw):
        calls.append(kw)
        shown = [p for p in pts if not kw.get("frm") or p["at"] >= kw["frm"]]
        return {"series": [{"indicator": P_DEATHS, "projection": True, "points": shown, "n": len(shown)}] * 2,
                "warnings": {P_DEATHS: WARN},
                "names": {P_DEATHS: {"en": "Projection: Deaths per year", "ar": "إسقاط: عدد الوفيات في السنة"}}}
    monkeypatch.setattr(M, "api", api)
    out = M.trend(P_DEATHS, days=90)
    assert calls[0]["frm"] == (date.today() - __import__("datetime").timedelta(days=90)).isoformat()
    assert "frm" not in calls[1]                               # the whole projection, not a window of it
    assert out["answer"] == ("إسقاط: عدد الوفيات في السنة: إسقاط مش قياس، 4 سنة من 32,257 سنة 2024 "
                             "لـ103,216 سنة 2100. تنبيه: " + WARN["ar"])
    for word in ("آخر", "قراءة", "يوم", "وسيط"):                # no "last N days", no "readings", no baseline
        assert word not in out["answer"].replace(WARN["ar"], ""), word
    assert out["projection"] is True and "direction" not in out and "last_age_days" not in out
    assert E.trend(out) == ("Projection: Deaths per year: a projection, not a measurement; 4 projected years, "
                            "from 32,257 in 2024 to 103,216 in 2100. Note: " + WARN["en"])


def test_an_observed_series_keeps_its_trend(monkeypatch):
    pts = [{"at": f"{2000 + i}-01-01", "prec": "year", "value": float(10 + i), "unit": "persons"} for i in range(12)]
    monkeypatch.setattr(M, "api", lambda path, **kw: {
        "series": [{"indicator": E_DEATHS, "projection": False, "points": pts, "n": 12}] * 2})
    out = M.trend(E_DEATHS, days=3650)
    assert out["direction"] == "higher" and "projection" not in out and "آخر 3 قراءة" in out["answer"]


def test_a_category_that_leaves_projections_out_says_so_in_both_languages(monkeypatch):
    """The by-name sentence (114) and the projection's wording live together:
    an observed page that holds projections by name says "latest" AND says
    they are held, with a name that begins with the word."""
    payload = _category_payload(False)
    payload["by_name_only"] = {"series": 51, "indicator_prefix": "population.wpp_projection.",
                               "example": P_BIRTHS, "example_en": "Projection: Births per year",
                               "example_ar": "إسقاط: عدد المواليد في السنة"}
    monkeypatch.setattr(M, "api", _api(payload))
    out = M.databank("economic")
    assert "آخر الأرقام" in out["answer"] and "projected_by_indicator" not in out
    assert "وفي كمان 51 سلسلة، كل وحدة لحالها وبتنطلب بالاسم (مثلاً: إسقاط: عدد المواليد في السنة)." in out["answer"]
    en = E.databank(out)
    assert "— latest: " in en
    assert "Also held, each served when asked for by name: 51 series (for example: Projection: Births per year)." in en


# ── the registry half: the spec says it, the loader writes it ────────────────

PAIRS = [(f"population.wpp_projection.{ind}", unit, 77)
         for ind, unit, _m, _u in fetch_wpp.INDICATORS.values()]


def test_every_rule_of_the_projection_spec_declares_both_facts_and_the_spec_is_on():
    assert spec_mod.validate(SPEC, "population_wpp_projection") == []
    assert SPEC.get("migrate", True) is True and "skip_reason" not in SPEC
    from ingest.databank import load_spec
    assert load_spec("population_wpp_projection")["datasets"][0]["key"] == "un_wpp_2024_projection"
    assert all(r.get("projection") is True and r.get("ask_by_name") is True for r in SPEC["registry"]["rules"])
    got, _ = load_registry.classify(PAIRS, SPEC["registry"]["rules"])
    assert len(got) == 51 and all(m["projection"] is True and m["ask_by_name"] is True for m in got.values())
    assert {"projection", "ask_by_name"} <= set(load_registry.FIELDS)
    for key in ("projection", "ask_by_name"):
        bad = {**SPEC, "registry": {**SPEC["registry"],
                                    "rules": [{**SPEC["registry"]["rules"][0], key: "yes"}]}}
        assert spec_mod.validate(bad, "population_wpp_projection") != [], key


def test_no_other_spec_declares_a_projection_or_reaches_these_series():
    """The registry loader writes both flags the way the rule says them, for
    every indicator a rule classifies. A rule of another spec that matched a
    projection series would un-say them."""
    for p in sorted((ROOT / "db" / "mappings").glob("*.yaml")):
        if p.stem == "population_wpp_projection":
            continue
        rules = ((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("registry") or {}).get("rules") or []
        assert not any(r.get("projection") for r in rules), p.stem
        reached = [ind for ind, unit, _n in PAIRS if any(load_registry.matches(r, ind, unit) for r in rules)]
        assert reached == [], (p.stem, reached[:3])
    datasets = yaml.safe_load((ROOT / "db" / "registry" / "datasets.yaml").read_text(encoding="utf-8")) or {}
    for name, reg in (datasets.get("datasets") or {}).items():
        assert not "population.wpp_projection.".startswith(reg["indicator_prefix"]), name


# ── migration 115: the 51 series declared before their first row ─────────────

ROW = re.compile(
    r"  \('((?:[^']|'')*)', '((?:[^']|'')*)', '((?:[^']|'')*)',\n"
    r"   '((?:[^']|'')*)',\n"
    r"   \(SELECT key FROM unit_def WHERE key = '(\w+)'\), '(\w+)', (NULL|-?1), '(\w+)', '(\w+)', "
    r"'generated', 'population_wpp_projection', (true|false), (true|false)\)")


def test_the_migration_adds_one_column_and_gives_up_rather_than_wait():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout = '5s';" in sql
    assert "ADD COLUMN IF NOT EXISTS projection boolean NOT NULL DEFAULT false;" in sql
    head = sql.split("SET LOCAL")[0]
    assert "-- Rollback" in head and "ALTER TABLE indicator_def DROP COLUMN projection;" in head
    body = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", body, re.M)      # db/migrate.sh runs it with psql -1
    assert "DELETE" not in body and "DROP" not in body
    assert "(indicator, concept_key, name_en, name_ar, canonical_unit,\n" in sql
    assert "projection, ask_by_name)\nVALUES" in sql
    assert "ON CONFLICT (indicator) DO UPDATE SET projection = true, ask_by_name = true;" in sql
    assert [p.name for p in sorted(MIGRATION.parent.glob("115_*.sql"))] == [MIGRATION.name]
    assert not (ROOT / "db" / "proposed" / "indicator_projection.sql").exists()


def test_the_migration_s_51_rows_are_what_the_registry_loader_would_write():
    """Generated from the spec and names.yaml on 2026-10-13, and held to them
    here. A migration is history once it has run: if a name or the warning is
    reworded later, the registry loader carries the new words to the store, and
    it is this comparison of words that is retired, never the migration."""
    sql = MIGRATION.read_text(encoding="utf-8")
    found = {m[0]: m for m in ROW.findall(sql)}
    got, _ = load_registry.classify(PAIRS, SPEC["registry"]["rules"])
    doc = load_registry.load_names()
    assert list(found) == [ind for ind, _u, _n in PAIRS]             # 51, in the fetcher's order
    assert sql.count("'population_wpp_projection', ") == 51
    unq = lambda v: v.replace("''", "'")                             # noqa: E731
    for ind, unit, _n in PAIRS:
        _i, concept, en, ar, unit_key, kind, polarity, grain, place_grain, projection, by_name = found[ind]
        m = got[ind]
        assert (concept, kind, grain, place_grain, unit_key) == \
            (m["concept"], m["measure_kind"], m["grain"], m["place_grain"], m["canonical_unit"]), ind
        assert unit_key == unit                                      # never converted
        assert (None if polarity == "NULL" else int(polarity)) == m["polarity"], ind
        assert (projection, by_name) == ("true", "true"), ind        # both facts, before the first row
        assert (unq(en), unq(ar)) == load_registry.name_for(ind, m, None, doc), ind
    rule = SPEC["registry"]["rules"][0]
    assert f"serve_warning = $w${rule['serve_warning']}$w$" in sql
    assert f"serve_warning_ar = $w${rule['serve_warning_ar']}$w$" in sql
    assert "<> 51 THEN" in sql and "RAISE EXCEPTION" in sql          # it checks itself as it runs
