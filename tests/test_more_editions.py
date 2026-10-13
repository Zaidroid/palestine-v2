"""The 39 World Population Prospects indicators taken on 2026-10-13
(ops/fetch_wpp.py, db/mappings/population_wpp.yaml, db/registry/).

No database and no network. The two fixtures are the UN's own text, cut from
the files of World Population Prospects 2024 (CC BY 3.0 IGO) on 2026-10-13:

  wpp2024_indicators_sample.csv    the header of
      WPP2024_Demographic_Indicators_Medium.csv.gz and six of its rows,
      untouched: the State of Palestine in 1950, 1965, 2022, 2023 (estimates)
      and 2024 (a projection), and Jordan in 2023.
  wpp2024_indicator_reference.csv  WPP2024_Demographic_Indicators_notes.csv
      whole: the UN's name and unit for every column.

What is held here: the 888 rows loaded on 2026-09-26 are produced exactly as
before; every new indicator is the UN's column under the UN's unit; the three
columns left out are left out for the reason the fetcher states; every one of
the 51 indicators meets one registry rule, a unit the registry knows and a
name in both languages; the raw file carries the edition's vintage; and a held
copy written before these indicators is read again whatever its age.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from ingest import databank, spec as spec_mod
from ops import fetch_wpp, fetchlib, load_registry

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "more_editions"
SAMPLE = (FX / "wpp2024_indicators_sample.csv").read_text(encoding="utf-8")
SPEC = yaml.safe_load((ROOT / "db" / "mappings" / "population_wpp.yaml").read_text(encoding="utf-8"))
UNITS = yaml.safe_load((ROOT / "db" / "registry" / "units.yaml").read_text(encoding="utf-8"))["units"]
CONCEPTS = yaml.safe_load((ROOT / "db" / "registry" / "concepts.yaml").read_text(encoding="utf-8"))["concepts"]

# The twelve as they stood on 2026-09-26, typed out a second time on purpose:
# the stored rows carry `wpp_column` and `wpp_unit` in attrs, so one changed
# word in the fetcher would supersede 74 held rows and call it a revision.
HELD_TWELVE = {
    "TPopulation1July": ("population_total", "persons", 1000, "thousands"),
    "Births": ("births", "persons", 1000, "thousands"),
    "Deaths": ("deaths", "persons", 1000, "thousands"),
    "NetMigrations": ("net_migration", "persons", 1000, "thousands"),
    "CBR": ("crude_birth_rate", "per_1000", 1, "per 1,000 population"),
    "CDR": ("crude_death_rate", "per_1000", 1, "per 1,000 population"),
    "TFR": ("total_fertility_rate", "births_per_woman", 1, "live births per woman"),
    "LEx": ("life_expectancy", "years", 1, "years at birth"),
    "IMR": ("infant_mortality_rate", "per_1000", 1, "infant deaths per 1,000 live births"),
    "Q5": ("under5_mortality_rate", "per_1000", 1, "deaths under 5 per 1,000 live births"),
    "MedianAgePop": ("median_age", "years", 1, "years"),
    "PopGrowthRate": ("population_growth_rate", "percent", 1, "percent"),
}
# ...and how indicator_def classifies them (read from the store, 2026-10-13):
# indicator -> (concept, measure_kind, polarity, canonical_unit)
HELD_MEANING = {
    "population_total": ("population.count", "stock", None, "persons"),
    "births": ("population.count", "flow", None, "persons"),
    "deaths": ("population.count", "flow", None, "persons"),
    "net_migration": ("population.count", "flow", None, "persons"),
    "crude_birth_rate": ("population.structure", "rate", None, "per_1000"),
    "crude_death_rate": ("mortality.general", "rate", -1, "per_1000"),
    "total_fertility_rate": ("population.structure", "rate", None, "births_per_woman"),
    "life_expectancy": ("mortality.general", "index", 1, "years"),
    "infant_mortality_rate": ("mortality.general", "rate", -1, "per_1000"),
    "under5_mortality_rate": ("mortality.general", "rate", -1, "per_1000"),
    "median_age": ("population.structure", "index", None, "years"),
    "population_growth_rate": ("population.structure", "ratio", None, "percent"),
}
NEW = {col: v for col, v in fetch_wpp.INDICATORS.items() if col not in HELD_TWELVE}
META_COLUMNS = {"SortOrder", "LocID", "Notes", "ISO3_code", "ISO2_code", "SDMX_code",
                "LocTypeID", "LocTypeName", "ParentID", "Location", "VarID", "Variant", "Time"}


def _reference() -> dict[str, dict]:
    text = (FX / "wpp2024_indicator_reference.csv").read_text(encoding="utf-8-sig")
    return {r["Indicator"]: r for r in csv.DictReader(io.StringIO(text))}


def _palestine(year: int) -> dict:
    return next(r for r in csv.DictReader(io.StringIO(SAMPLE))
                if r["LocID"] == "275" and r["Time"] == str(year))


def _value(recs: list[dict], year: int, indicator: str) -> float:
    return next(r["value"] for r in recs if r["year"] == year and r["indicator"] == indicator)


# ── the held rows are not disturbed ──────────────────────────────────────────

def test_the_first_twelve_indicators_are_word_for_word_what_the_held_rows_carry():
    assert list(fetch_wpp.INDICATORS)[:12] == list(HELD_TWELVE)
    assert {c: fetch_wpp.INDICATORS[c] for c in HELD_TWELVE} == HELD_TWELVE
    assert len(fetch_wpp.INDICATORS) == 51 and len(NEW) == 39


def test_a_held_record_is_produced_exactly_as_before():
    recs = fetch_wpp.parse(SAMPLE)
    pop = next(r for r in recs if r["stable_id"] == "wpp-2024:2023:population_total")
    assert pop == {"stable_id": "wpp-2024:2023:population_total", "year": 2023,
                   "indicator": "population_total", "value": 5409202.0, "unit": "persons",
                   "wpp_column": "TPopulation1July", "wpp_unit": "thousands",
                   "location": "State of Palestine"}
    le = next(r for r in recs if r["stable_id"] == "wpp-2024:2023:life_expectancy")
    assert (le["value"], le["unit"], le["wpp_unit"]) == (65.17, "years", "years at birth")


def test_a_new_row_has_the_same_shape_as_a_held_one():
    recs = {r["stable_id"]: r for r in fetch_wpp.parse(SAMPLE)}
    [old] = databank.t_population_wpp(recs["wpp-2024:2023:population_total"], {}, {}, Counter())
    [new] = databank.t_population_wpp(recs["wpp-2024:2023:population_male"], {}, {}, Counter())
    assert new.dataset_key == old.dataset_key == "un_wpp_2024"
    assert new.indicator == "population.wpp.population_male"
    assert (new.occurred_at, new.precision, new.place_id) == ("2023-01-01", "year", None)
    assert (new.value_num, new.unit) == (2688310.0, "persons")
    assert set(new.attrs) == set(old.attrs)
    assert new.attrs["wpp_column"] == "TPopulationMale1July" and new.attrs["revision"] == "WPP2024"
    assert new.attrs["estimate"].startswith("modelled")


# ── what is taken ────────────────────────────────────────────────────────────

def test_parse_takes_51_indicators_for_the_estimate_years_of_palestine_only():
    recs = fetch_wpp.parse(SAMPLE)
    assert {r["year"] for r in recs} == {1950, 1965, 2022, 2023}       # 2024 is a projection
    assert {r["location"] for r in recs} == {"State of Palestine"}     # Jordan's row is in the sample
    per_year = Counter(r["year"] for r in recs)
    assert set(per_year.values()) == {51}
    assert len({r["stable_id"] for r in recs}) == len(recs) == 204
    assert {r["indicator"] for r in recs} == {v[0] for v in fetch_wpp.INDICATORS.values()}


def test_new_values_are_the_file_s_numbers_with_thousands_made_persons():
    recs = fetch_wpp.parse(SAMPLE)
    row = _palestine(2023)
    assert row["TPopulationMale1July"] == "2688.31" and row["TPopulationFemale1July"] == "2720.892"
    assert _value(recs, 2023, "population_male") == 2688310.0
    assert _value(recs, 2023, "population_female") == 2720892.0
    assert _value(recs, 2023, "population_male") + _value(recs, 2023, "population_female") \
        == _value(recs, 2023, "population_total")
    assert _value(recs, 2023, "population_total_1jan") == 5367977.0
    assert _value(recs, 2023, "infant_deaths") == 2076.0
    assert _value(recs, 2023, "under5_deaths") == 3821.0
    assert _value(recs, 1950, "life_expectancy_female") == 48.441
    assert _value(recs, 2023, "mean_age_childbearing") == float(row["MAC"]) == 28.551
    # three decimals, as the first twelve are kept: the file's fourth is dropped
    assert row["PopSexRatio"] == "98.8025" and _value(recs, 2023, "sex_ratio") == 98.802
    assert row["Q1560Male"] == "365.4788" and _value(recs, 2023, "mortality_15_to_60_male") == 365.479
    for r in recs:
        assert r["value"] == round(r["value"], 3)


def test_each_new_unit_is_the_un_reference_s_unit_word_for_word():
    ref = _reference()
    for col, (ind, unit, mult, wpp_unit) in NEW.items():
        assert col in ref, col
        assert wpp_unit == ref[col]["Unit"], (col, wpp_unit, ref[col]["Unit"])
        # thousands become persons and nothing else is converted
        assert (mult == 1000) == (ref[col]["Unit"] == "thousands") == (unit == "persons"), col
        assert mult in (1, 1000)
    # the sex cuts follow the both-sexes key
    by_ind = {v[0] for v in fetch_wpp.INDICATORS.values()}
    for ind in by_ind:
        m = re.fullmatch(r"(.+)_(male|female)", ind)
        if m and not ind.startswith(("population_", "deaths_")):
            assert m.group(1) in by_ind, ind
    assert {"population_male", "population_female", "deaths_male", "deaths_female"} <= by_ind


def test_every_column_the_file_fills_is_either_taken_or_named_as_not_taken():
    """A column the UN adds to the file fails here until someone decides."""
    header = next(csv.reader([SAMPLE.splitlines()[0]]))
    value_columns = [c for c in header if c not in META_COLUMNS]
    assert len(value_columns) == 54
    assert set(value_columns) == set(fetch_wpp.INDICATORS) | set(fetch_wpp.NOT_TAKEN)
    assert not set(fetch_wpp.INDICATORS) & set(fetch_wpp.NOT_TAKEN)
    assert fetch_wpp.NOT_TAKEN == ("DoublingTime", "PopDensity", "PopChange")


# ── what is left out, and the reason given for it ────────────────────────────

def test_the_three_columns_left_out_are_what_the_fetcher_says_they_are():
    y50, y65, y22, y23, y24 = (_palestine(y) for y in (1950, 1965, 2022, 2023, 2024))
    f = lambda row, col: float(row[col])                              # noqa: E731
    # DoublingTime: blank in a year of slow growth, else 100·ln2 / growth rate
    assert y65["DoublingTime"] == "" and f(y65, "PopGrowthRate") < 0.5
    for row in (y50, y22, y23):
        assert f(row, "DoublingTime") == pytest.approx(
            100 * math.log(2) / f(row, "PopGrowthRate"), abs=0.05)
    # PopDensity: the mid-year population over one constant area
    for row in (y50, y65, y22, y23):
        assert f(row, "PopDensity") == pytest.approx(f(row, "TPopulation1July") * 1000 / 6020, abs=0.001)
    # PopChange: next 1 January minus this one
    assert f(y22, "PopChange") == pytest.approx(f(y23, "TPopulation1Jan") - f(y22, "TPopulation1Jan"), abs=0.0011)
    assert f(y23, "PopChange") == pytest.approx(f(y24, "TPopulation1Jan") - f(y23, "TPopulation1Jan"), abs=0.0011)


def test_four_taken_columns_are_arithmetic_of_two_others_as_the_fetcher_admits():
    for year in (1950, 1965, 2022, 2023):
        row = _palestine(year)
        f = lambda col: float(row[col])                               # noqa: E731
        assert f("NatChange") == pytest.approx(f("Births") - f("Deaths"), abs=0.0011)
        assert f("NatChangeRT") == pytest.approx(f("CBR") - f("CDR"), abs=0.0011)
        assert f("PopSexRatio") == pytest.approx(
            100 * f("TPopulationMale1July") / f("TPopulationFemale1July"), abs=0.001)
        assert f("CNMR") == pytest.approx(1000 * f("NetMigrations") / f("TPopulation1July"), abs=0.001)
        # ...and one that looks like it is not: the UN's survivors to age 1 are a
        # cohort measure, more than 100 children away from births minus infant deaths
        assert f("LBsurvivingAge1") - (f("Births") - f("InfantDeaths")) > 0.1


# ── the registry: a meaning, a unit and a name for every one ─────────────────

def _pairs() -> list[tuple[str, str, int]]:
    return [(f"population.wpp.{ind}", unit, 74) for ind, unit, _m, _u in fetch_wpp.INDICATORS.values()]


def test_every_indicator_meets_exactly_one_registry_rule():
    rules = SPEC["registry"]["rules"]
    for ind, unit, _n in _pairs():
        hits = [r for r in rules if load_registry.matches(r, ind, unit)]
        assert len(hits) == 1, (ind, [r["when"] for r in hits])
    got, conflicts = load_registry.classify(_pairs(), rules)
    assert len(got) == 51 and conflicts == []
    assert load_registry.unclassified_by_reader([("population_wpp", _pairs(), got)]) == {"population_wpp": []}
    assert SPEC["registry"]["max_unclassified"] == 0
    # no rule reaches outside this dataset: the spec shares `economic` with the
    # World Bank, the IMF and PCBS, and is handed their indicators too
    for other in ("economic.SP.POP.TOTL", "economic.pcbs_population", "population_total",
                  "population.wpp_other.sex_ratio"):
        assert not any(load_registry.matches(r, other, "persons") for r in rules), other


def test_the_first_twelve_keep_their_meaning_and_every_meaning_is_registered():
    got, _ = load_registry.classify(_pairs(), SPEC["registry"]["rules"])
    for ind, want in HELD_MEANING.items():
        m = got[f"population.wpp.{ind}"]
        assert (m["concept"], m["measure_kind"], m["polarity"], m["canonical_unit"]) == want, ind
    for ind, m in got.items():
        assert m["concept"] in CONCEPTS, ind
        assert m["canonical_unit"] in UNITS, ind
        assert m["measure_kind"] in ("stock", "flow", "rate", "index", "ratio"), ind
        assert (m["grain"], m["place_grain"]) == ("year", "region"), ind
        assert m["polarity"] in (None, -1, 1), ind


def test_a_cut_is_classified_as_its_series_and_a_risk_of_dying_reads_worse_when_it_rises():
    got, _ = load_registry.classify(_pairs(), SPEC["registry"]["rules"])
    key = lambda m: (m["concept"], m["measure_kind"], m["polarity"], m["canonical_unit"])   # noqa: E731
    g = lambda ind: key(got[f"population.wpp.{ind}"])                                       # noqa: E731
    assert g("population_male") == g("population_female") == g("population_total_1jan") == g("population_total")
    assert g("deaths_male") == g("deaths_female") == g("infant_deaths") == g("under5_deaths") == g("deaths")
    assert g("natural_change") == g("births_women_15_19") == g("births_surviving_to_age_1") == g("births")
    for ind in [v[0] for v in fetch_wpp.INDICATORS.values() if v[0].startswith("life_expectancy_")]:
        assert g(ind) == g("life_expectancy") == ("mortality.general", "index", 1, "years")
    for ind in [v[0] for v in fetch_wpp.INDICATORS.values() if v[0].startswith("mortality_")]:
        assert g(ind) == g("infant_mortality_rate") == ("mortality.general", "rate", -1, "per_1000")
    assert g("natural_change_rate") == g("net_migration_rate") == g("crude_birth_rate")
    assert g("net_reproduction_rate") == ("population.structure", "rate", None, "daughters_per_woman")
    assert g("mean_age_childbearing") == g("median_age")
    assert g("sex_ratio") == g("sex_ratio_at_birth") == \
        ("population.structure", "ratio", None, "males_per_100_females")


def test_every_row_unit_is_one_the_registry_knows_and_is_never_converted():
    """A row whose unit has no alias is served with value_canonical NULL and
    counted by ops/load_registry.py; none of these may add to that count."""
    known = set(UNITS)
    for u in UNITS.values():
        known |= set((u or {}).get("aliases") or {})
    got, _ = load_registry.classify(_pairs(), SPEC["registry"]["rules"])
    for ind, unit, _n in _pairs():
        assert unit in known, (ind, unit)
        assert got[ind]["canonical_unit"] == unit, ind      # persons stay persons, years stay years
    for key in ("males_per_100_females", "daughters_per_woman"):
        assert UNITS[key]["name_en"] and UNITS[key]["name_ar"] and UNITS[key]["dimension"] in ("ratio", "rate")
    # a sex ratio is not a percentage: nothing may alias it to one
    assert "males_per_100_females" not in (UNITS["percent"].get("aliases") or {})


def test_every_indicator_has_an_english_and_an_arabic_name():
    doc = load_registry.load_names()
    got, _ = load_registry.classify(_pairs(), SPEC["registry"]["rules"])
    seen_en, seen_ar = set(), set()
    for ind, _unit, _n in _pairs():
        en, ar = load_registry.name_for(ind, got[ind], None, doc)
        assert en and ar, ind
        assert en.endswith("(UN World Population Prospects 2024 estimate)"), ind
        assert ar.endswith("(تقديرات التوقعات السكانية في العالم 2024، الأمم المتحدة)"), ind
        assert not re.search("[٠-٩۰-۹]", ar), ind
        assert re.search("[؀-ۿ]", ar) and en != ind
        seen_en.add(en)
        seen_ar.add(ar)
    assert len(seen_en) == len(seen_ar) == 51          # no two indicators share a name


def test_the_names_say_which_sex_and_which_age():
    names = load_registry.load_names()["names"]
    for ind, *_ in fetch_wpp.INDICATORS.values():
        n = names[f"population.wpp.{ind}"]
        if ind.endswith("_male"):
            assert "Male" in n["en"] and "ذكور" in n["ar"], ind
        if ind.endswith("_female"):
            assert "Female" in n["en"] and "إناث" in n["ar"], ind
        for age in re.findall(r"(?<![a-z])(\d{2})(?!\d)", ind):
            assert age in n["en"] and age in n["ar"], (ind, age)


# ── the spec's tripwires ─────────────────────────────────────────────────────

def test_the_spec_s_floor_and_ceiling_are_the_measured_file_s():
    years = fetch_wpp.LAST_ESTIMATE - fetch_wpp.FIRST + 1
    assert years == 74 and (fetch_wpp.FIRST, fetch_wpp.LAST_ESTIMATE) == (1950, 2023)
    assert SPEC["records_measured"] == years * len(fetch_wpp.INDICATORS) == 3774
    assert SPEC["expect"]["min_records"] == fetch_wpp.FLOOR == 3585
    assert SPEC["expect"]["max_observations"] == int(1.15 * 3774) == 4340
    assert spec_mod.validate(SPEC, "population_wpp") == []
    assert SPEC["identity"]["fields"] == ["indicator", "occurred_at"]


# ── the vintage the raw file carries ─────────────────────────────────────────

def test_the_vintage_is_the_edition_s_release_day_in_the_un_s_words():
    v = fetch_wpp.vintage("2024-12-13")
    assert set(v) == {"vintage", "vintage_basis", "vintage_url"}
    assert v["vintage"] == "2024-07-11" and v["vintage_url"] == "https://population.un.org/wpp/faqs"
    assert "released on 11 July 2024 (World Population Day)" in v["vintage_basis"]
    assert "The estimates end at 2023" in v["vintage_basis"]
    assert "HTTP Last-Modified is 2024-12-13" in v["vintage_basis"]
    assert "Last-Modified" not in fetch_wpp.vintage(None)["vintage_basis"]
    assert fetch_wpp.last_modified_day("Fri, 13 Dec 2024 19:11:17 GMT") == "2024-12-13"
    assert fetch_wpp.last_modified_day(None) is None and fetch_wpp.last_modified_day("soon") is None


def test_the_loader_reads_that_vintage_for_the_dataset(tmp_path):
    f = tmp_path / "palestine.json"
    f.write_text(json.dumps({"source": "x", "metadata": fetch_wpp.vintage("2024-12-13"),
                             "data": fetch_wpp.parse(SAMPLE)}), encoding="utf-8")
    got = databank.read_vintage(SPEC, [f])
    assert set(got) == {"un_wpp_2024"}
    assert got["un_wpp_2024"]["vintage"] == "2024-07-11"
    assert got["un_wpp_2024"]["vintage_url"] == "https://population.un.org/wpp/faqs"
    # the file as it was before 2026-10-13 said nothing, and the dataset row was {}
    f.write_text(json.dumps({"source": "x", "data": []}), encoding="utf-8")
    assert databank.read_vintage(SPEC, [f]) == {}


# ── a held copy from before these indicators ─────────────────────────────────

def _held(path: Path, indicators) -> None:
    path.write_text(json.dumps({"data": [{"indicator": i, "year": 1950} for i in indicators]}),
                    encoding="utf-8")


def test_a_held_copy_without_today_s_indicators_does_not_count_as_complete(tmp_path):
    f = tmp_path / "palestine.json"
    assert fetch_wpp.holds_every_indicator(f) is False                      # no file
    _held(f, [v[0] for v in HELD_TWELVE.values()])
    assert fetch_wpp.holds_every_indicator(f) is False                      # the file of 2026-09-26
    _held(f, [v[0] for v in fetch_wpp.INDICATORS.values()])
    assert fetch_wpp.holds_every_indicator(f) is True
    f.write_text("{not json", encoding="utf-8")
    assert fetch_wpp.holds_every_indicator(f) is False
    f.write_text(json.dumps(["a", "list"]), encoding="utf-8")
    assert fetch_wpp.holds_every_indicator(f) is False


class _Answer:
    """What urlopen hands back: the sample, gzipped, with the UN's header."""
    headers = {"Last-Modified": "Fri, 13 Dec 2024 19:11:17 GMT"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return gzip.compress(SAMPLE.encode("utf-8"))


def test_a_fresh_but_older_copy_is_fetched_again_and_a_complete_one_is_not(tmp_path, monkeypatch):
    out = tmp_path / "wpp" / "palestine.json"
    out.parent.mkdir()
    _held(out, [v[0] for v in HELD_TWELVE.values()])           # minutes old, twelve indicators
    calls, events = [], []
    monkeypatch.setattr(fetch_wpp, "OUT", out)
    monkeypatch.setattr(fetch_wpp, "ROOT", tmp_path)
    monkeypatch.setattr(fetch_wpp, "FLOOR", 150)               # the sample holds four years, not 74
    monkeypatch.setattr(fetch_wpp, "event", lambda label, outcome, **kw: events.append((label, outcome, kw)))
    monkeypatch.setattr(fetch_wpp.urllib.request, "urlopen",
                        lambda req, timeout=0: calls.append(req.full_url) or _Answer())

    assert fetch_wpp.main([]) == 0
    assert calls == [fetch_wpp.URL]                            # fresh by age, fetched all the same
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(doc["data"]) == 204 and doc["metadata"]["indicators"] == 51
    assert doc["metadata"]["vintage"] == "2024-07-11"
    assert "2024-12-13" in doc["metadata"]["vintage_basis"]
    assert doc["license"] == "CC-BY-IGO-3.0" and doc["url"] == fetch_wpp.URL
    assert events == [("wpp-2024", "ok", {"rows": 204, "indicators": 51, "data_through": "2023"})]

    assert fetch_wpp.main([]) == 0                             # now complete and fresh: left alone
    assert len(calls) == 1 and len(events) == 1
    assert fetch_wpp.main(["--force"]) == 0                    # unless asked
    assert len(calls) == 2


def test_a_short_file_is_refused_and_the_held_copy_stands(tmp_path, monkeypatch):
    out = tmp_path / "wpp" / "palestine.json"
    out.parent.mkdir()
    _held(out, [v[0] for v in HELD_TWELVE.values()])
    before = out.read_text(encoding="utf-8")
    events = []
    monkeypatch.setattr(fetch_wpp, "OUT", out)
    monkeypatch.setattr(fetch_wpp, "ROOT", tmp_path)
    # check_floor writes its own ledger line through fetchlib: keep it off the real ledger
    monkeypatch.setattr(fetchlib, "EVENTS", tmp_path / "fetch-events.ndjson")
    monkeypatch.setattr(fetch_wpp, "event", lambda label, outcome, **kw: events.append((label, outcome, kw)))
    monkeypatch.setattr(fetch_wpp.urllib.request, "urlopen", lambda req, timeout=0: _Answer())
    assert fetch_wpp.FLOOR == 3585                             # four years of 51 is 204: far below
    assert fetch_wpp.main(["--force"]) == 1
    assert out.read_text(encoding="utf-8") == before
    refused = [json.loads(x) for x in (tmp_path / "fetch-events.ndjson").read_text().splitlines()]
    assert [(e["label"], e["outcome"], e["rows"], e["floor"]) for e in refused] == \
        [("wpp-2024", "refused", 204, 3585)]
    assert events == []                                        # no `ok` line for a refused file
