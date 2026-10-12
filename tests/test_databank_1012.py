"""The databank's counting defects of the 2026-10-11 audit, items 1, 2 and 4:
a warning declared in the spec and said by every answer that serves the
number; the Gaza damage series held once and called what it is; a complete
generation declared for part of a dataset, so the names roster closes what the
list takes back without closing its own daily summary."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.databank import Row                                              # noqa: E402
from ingest.spec import SpecRefused                                          # noqa: E402

_g = importlib.util.spec_from_file_location(
    "_guard_0926", Path(__file__).with_name("test_databank_guard_0926.py"))
guard = importlib.util.module_from_spec(_g)
_g.loader.exec_module(guard)


def _spec(name: str) -> dict:
    return yaml.safe_load((ROOT / "db" / "mappings" / f"{name}.yaml").read_text())


# ── item 4: a complete generation for part of a dataset ──────────────────────

ROSTER_ID = {"fields": ["indicator", "occurred_at"], "attrs": ["t4p_id"],
             "generation": "complete",
             "generation_indicators": ["martyrs.identified_killed"],
             "max_absent": 5}


def _person(i):
    return Row("d", "martyrs.identified_killed", "2023-10-07", "unknown",
               f"p-{i}", value_num=1, unit="persons", attrs={"t4p_id": str(i)})


def _summary(day, total):
    return Row("d", "martyrs.cumulative_summary", day, "day", f"s-{day}",
               value_num=total, unit="persons", attrs={})


def test_a_name_the_list_took_back_closes_and_the_summary_of_earlier_days_stays(
        monkeypatch, tmp_path):
    held = [_person(1), _person(2), _person(3),
            _summary("2026-10-10", 75494), _summary("2026-10-12", 75506)]
    emitted = [_person(1), _person(3), _summary("2026-10-12", 75506)]
    report, log = guard._write_run(monkeypatch, tmp_path, emitted, ROSTER_ID, held=held)
    assert log["inserts"] == []
    assert log["updates"] == [[1001]]                 # person 2, and nothing else
    assert report["absent_upstream"]["closed"] == 1


def test_without_the_scope_the_same_run_would_close_the_summary_too(monkeypatch, tmp_path):
    held = [_person(1), _person(2), _summary("2026-10-10", 75494),
            _summary("2026-10-12", 75506)]
    emitted = [_person(1), _summary("2026-10-12", 75506)]
    whole = {k: v for k, v in ROSTER_ID.items() if k != "generation_indicators"}
    report, log = guard._write_run(monkeypatch, tmp_path, emitted, whole, held=held)
    assert sorted(log["updates"][0]) == [1001, 1002]  # the defect the scope prevents


def test_a_short_fetch_of_the_roster_closes_nothing(monkeypatch, tmp_path):
    held = [_person(i) for i in range(40)] + [_summary("2026-10-12", 75506)]
    with pytest.raises(SpecRefused, match="a shrink, not a correction"):
        guard._write_run(monkeypatch, tmp_path,
                         held[:10] + [_summary("2026-10-12", 75506)], ROSTER_ID, held=held)


def test_the_roster_spec_declares_it_with_a_measured_ceiling():
    ident = _spec("martyrs_snapshot_2023")["identity"]
    assert ident["generation"] == "complete"
    assert ident["generation_indicators"] == ["martyrs.identified_killed"]
    assert ident["max_absent"] == 300                 # 242 measured on 2026-10-12


def test_the_validator_refuses_a_scope_it_cannot_read_off_the_key():
    from ingest import spec as S
    base = _spec("martyrs_snapshot_2023")
    bad = {**base, "identity": {"fields": ["occurred_at"], "attrs": ["t4p_id"],
                                "generation": "complete",
                                "generation_indicators": ["martyrs.identified_killed"]}}
    problems = [p for p in S.validate(bad, "martyrs_snapshot_2023") if "generation_indicators" in str(p)]
    assert problems
    bad = {**base, "identity": {"fields": ["indicator", "occurred_at"], "attrs": ["t4p_id"],
                                "generation_indicators": ["martyrs.identified_killed"]}}
    assert [p for p in S.validate(bad, "martyrs_snapshot_2023") if "generation_indicators" in str(p)]


# ── item 2: the Gaza damage series ───────────────────────────────────────────

def test_the_damage_series_are_running_totals_of_the_strip():
    from ops.load_registry import classify
    rules = _spec("infrastructure")["registry"]["rules"]
    got, _ = classify([("infrastructure.damage.residential", "units", 730),
                       ("infrastructure.barrier_segment", "km", 261)], rules)
    d = got["infrastructure.damage.residential"]
    assert (d["measure_kind"], d["place_grain"]) == ("cumulative", "region")
    assert got["infrastructure.barrier_segment"]["measure_kind"] == "stock"


def test_two_damage_totals_are_refused_as_a_pair():
    from serve.correlate import check_comparable
    s = {"indicator": "infrastructure.damage.residential", "measure_kind": "cumulative",
         "place_grain": "region", "concept_key": "infrastructure.damage"}
    t = {"indicator": "conflict.gaza_cumulative_killed", "measure_kind": "cumulative",
         "place_grain": "region", "concept_key": "mortality.conflict"}
    assert check_comparable(s, t)                      # a reason, no coefficient


# ── item 1: the warning is the spec's, and every answer says it ──────────────

def test_every_casualties_indicator_is_given_a_warning_by_the_spec():
    from ops.load_registry import classify
    rules = _spec("casualties")["registry"]["rules"]
    inds = ["casualties.annual_total", "casualties.region.gaza_strip",
            "casualties.governorate.jenin", "casualties.demographic.girls",
            "casualties.weapon.live_ammunition"]
    got, _ = classify([(i, "fatalities", 1) for i in inds], rules)
    for i in inds:
        en, ar = got[i]["serve_warning"], got[i]["serve_warning_ar"]
        assert "EXCLUDES the Gaza war dead" in en and "7 October 2023" in en, i
        assert "ما بيشمل شهداء حرب غزة" in ar, i
        assert "Tselem" not in en and "بتسيلم" not in ar, i   # OCHA's own count
    assert "newest year is partial" in got["casualties.annual_total"]["serve_warning"]
    assert "not a year's figure" in got["casualties.region.gaza_strip"]["serve_warning"]


W = {"casualties.annual_total": {"en": "It EXCLUDES the Gaza war dead.",
                                 "ar": "ما بيشمل شهداء حرب غزة."}}


def test_the_english_answers_say_the_warning_once():
    from serve import mcp_en as E
    cmp_ = {"series": [{"indicator": "casualties.annual_total", "n": 19,
                        "canonical_unit": "persons"}] * 2,
            "overlap": {"n": 19, "from": "2008-01-01", "to": "2026-01-01"}, "warnings": W}
    assert E.compare(cmp_).count("Note: It EXCLUDES the Gaza war dead.") == 1
    cor = {"plain_english": "They move together", "n": 12, "ci95": [0.1, 0.9], "warnings": W}
    assert E.correlate(cor).endswith("Note: It EXCLUDES the Gaza war dead.")
    tr = {"indicator": "casualties.annual_total", "recent_mean": 280.0,
          "baseline_median": 150.0, "change_pct": 87, "direction": "higher", "warnings": W}
    assert "Note: It EXCLUDES the Gaza war dead." in E.trend(tr)
    assert "Note:" not in E.compare({k: v for k, v in cmp_.items() if k != "warnings"})


def test_the_arabic_answers_say_the_warning(monkeypatch):
    from serve import mcp_server as M
    pts = [{"at": f"{2008 + i}-01-01", "value": float(100 + 10 * i), "prec": "year"}
           for i in range(19)]
    payload = {"series": [{"indicator": "casualties.annual_total", "n": 19, "points": pts,
                           "canonical_unit": "persons", "place_used": None}] * 2,
               "overlap": {"n": 19, "from": "2008-01-01", "to": "2026-01-01"}, "warnings": W}

    def api(path, **kw):
        if path == "/v2/databank/compare":
            return {**payload, "series": [dict(s) for s in payload["series"]]}
        if path == "/v2/databank/correlate":
            return {"refused": False, "rho": 0.5, "n": 12, "ci95": [0.1, 0.8], "warnings": W}
        raise AssertionError(path)

    monkeypatch.setattr(M, "api", api)
    assert "تنبيه: ما بيشمل شهداء حرب غزة." in M.compare(
        "casualties.annual_total,casualties.annual_total")["answer"]
    t = M.trend("casualties.annual_total", days=3650)
    assert "تنبيه: ما بيشمل شهداء حرب غزة." in t["answer"] and t["warnings"] == W
    c = M.correlate(a="casualties.annual_total", b="conflict.gaza_killed_daily")
    assert c["answer"].endswith("تنبيه: ما بيشمل شهداء حرب غزة.")


def test_the_scan_says_the_warning_of_the_series_it_lists(monkeypatch):
    from serve import mcp_en as E, mcp_server as M
    d = {"refused": False, "tested": 12, "skipped": {}, "warnings": W,
         "matches": [{"indicator": "casualties.annual_total", "rho": 0.61, "n": 14}],
         "multiple_comparisons": "12 tests were run."}
    assert E.what_correlates_with(d).endswith("Note: It EXCLUDES the Gaza war dead.")
    monkeypatch.setattr(M, "api", lambda path, **kw: d)
    assert M.what_correlates_with("economic.ny_gdp_mktp_cd")["answer"].endswith(
        "تنبيه: ما بيشمل شهداء حرب غزة.")
    src = (ROOT / "serve" / "app.py").read_text()
    scan = src.split("def databank_correlate_scan(")[1].split("\ndef _skip_reason(")[0]
    assert "_serve_warnings(" in scan


def test_the_routes_carry_the_warning_of_what_they_serve():
    """compare and correlate attach `warnings`; read from the route's source so
    the test needs no database."""
    src = (ROOT / "serve" / "app.py").read_text()
    compare = src.split("def databank_compare(")[1].split("\n@app.get(")[0]
    correlate = src.split("def databank_correlate(")[1].split("\ndef _correlate(")[0]
    assert "_serve_warnings(" in compare and 'out["warnings"]' in compare
    assert "_serve_warnings(" in correlate and 'out["warnings"]' in correlate


# ── the registry: every held indicator has a definition ──────────────────────

def test_the_registrys_accounting_does_not_depend_on_the_alphabet():
    """acled_hdx sorts before conflict and holds no rules for conflict's
    indicators; it was refused for them until every reader was classified
    before any was judged."""
    from ops.load_registry import classify, unclassified_by_reader
    pairs = [("conflict.gaza_cumulative_killed", "persons", 800),
             ("attack.health", "incidents", 500)]
    rules_a = [{"when": {"prefix": "attack."}, "concept": "violence", "measure_kind": "flow"}]
    rules_c = [{"when": {"regex": "cumulative_"}, "concept": "mortality.conflict",
                "measure_kind": "cumulative"}]
    for order in (("acled_hdx", rules_a), ("conflict", rules_c)), \
                 (("conflict", rules_c), ("acled_hdx", rules_a)):
        read = [(name, pairs, classify(pairs, rules)[0]) for name, rules in order]
        assert unclassified_by_reader(read) == {"acled_hdx": [], "conflict": []}
    lonely = [("zzz", pairs, classify(pairs, rules_a)[0])]
    assert unclassified_by_reader(lonely) == {"zzz": ["conflict.gaza_cumulative_killed"]}


MOH = ["gaza.moh.aid_seekers.deaths.cumulative", "gaza.moh.aid_seekers.deaths.daily",
       "gaza.moh.aid_seekers.injuries.cumulative", "gaza.moh.aid_seekers.injuries.daily",
       "gaza.moh.deaths.cumulative", "gaza.moh.deaths.daily", "gaza.moh.deaths.period",
       "gaza.moh.deaths.since_ceasefire", "gaza.moh.deaths.since_resumption",
       "gaza.moh.deaths_committee.daily", "gaza.moh.deaths_committee.period",
       "gaza.moh.deaths_new.daily", "gaza.moh.deaths_new.period",
       "gaza.moh.deaths_succumbed.daily", "gaza.moh.deaths_succumbed.period",
       "gaza.moh.famine.deaths.cumulative", "gaza.moh.famine.deaths.daily",
       "gaza.moh.famine.deaths_children.cumulative", "gaza.moh.famine.deaths_children.daily",
       "gaza.moh.injuries.cumulative", "gaza.moh.injuries.daily", "gaza.moh.injuries.period",
       "gaza.moh.injuries.since_ceasefire", "gaza.moh.injuries.since_resumption",
       "gaza.moh.massacres.daily", "gaza.moh.massacres.period", "gaza.moh.period.hours",
       "gaza.moh.recovered.daily", "gaza.moh.recovered.period",
       "gaza.moh.recovered.since_ceasefire"]


def test_the_ministrys_thirty_series_each_get_a_definition():
    from ops.load_registry import classify, load_dataset_rules
    reg = load_dataset_rules()["gaza_moh_daily"]
    assert all(i.startswith(reg["indicator_prefix"]) for i in MOH)
    got, _ = classify([(i, "count", 10) for i in MOH], reg["rules"])
    assert sorted(got) == sorted(MOH)                  # none left without a meaning
    kind = {i: (m["concept"], m["measure_kind"]) for i, m in got.items()}
    assert kind["gaza.moh.deaths_new.daily"] == ("mortality.conflict", "flow")
    assert kind["gaza.moh.deaths.since_ceasefire"] == ("mortality.conflict", "cumulative")
    assert kind["gaza.moh.recovered.since_ceasefire"] == ("mortality.conflict", "cumulative")
    assert kind["gaza.moh.injuries.cumulative"] == ("injury.conflict", "cumulative")
    assert kind["gaza.moh.aid_seekers.injuries.daily"] == ("injury.conflict", "flow")
    assert kind["gaza.moh.massacres.daily"] == ("violence", "flow")
    assert kind["gaza.moh.period.hours"][1] == "status"   # context, never summed
    # the three tiers the Ministry keeps apart are never one kind
    assert {k for i, (_c, k) in kind.items() if i.endswith((".cumulative", "since_ceasefire",
                                                           "since_resumption"))} == {"cumulative"}


def test_the_series_086_left_under_their_old_names_are_classified():
    from ops.load_registry import classify
    got, _ = classify([("pcbs.sl_emp_totl_sp_zs", "percentage", 32),
                       ("pcbs.sp_pop_dpnd_ol", "percentage", 36)],
                      _spec("economic")["registry"]["rules"])
    assert got["pcbs.sl_emp_totl_sp_zs"]["concept"] == "economy.labour"
    assert got["pcbs.sp_pop_dpnd_ol"]["concept"] == "population.structure"
    got, _ = classify([("economic.pcbs_cpi", "index", 120), ("economic.pcbs_population", "persons", 30),
                       ("economic.pcbs_poverty_rate", "percent", 2)],
                      _spec("economic_pcbs")["registry"]["rules"])
    assert {i: m["measure_kind"] for i, m in got.items()} == {
        "economic.pcbs_cpi": "index", "economic.pcbs_population": "stock",
        "economic.pcbs_poverty_rate": "ratio"}


def test_no_served_unit_is_left_without_a_name():
    units = yaml.safe_load((ROOT / "db" / "registry" / "units.yaml").read_text())["units"]
    aliases = units["count"]["aliases"]
    assert aliases["incidents"]["unit"] == "events" and "cases" in aliases


def test_the_nightly_defines_what_it_loaded_and_fails_if_it_cannot():
    sh = (ROOT / "ops" / "databank-sync.sh").read_text()
    assert sh.index("ingest.databank --all") < sh.index("ops.load_registry --apply") \
        < sh.index("ops.gap_radar")
    assert '[ "$rc" -eq 0 ] && rc=$reg' in sh        # a refusal fails the night


def test_the_ministry_dataset_is_born_with_its_category():
    src = (ROOT / "ingest" / "sources" / "moh_gaza.py").read_text()
    assert "'conflict', 'daily'" in src
    mig = (ROOT / "db" / "migrations" / "103_moh_bulletins_answerable.sql").read_text()
    assert "SET v1_category = 'conflict'" in mig and "gaza_moh_daily" in mig
