"""The UN's population projection for 2024 to 2100, kept apart from its
estimates (ops/fetch_wpp.py parse_projection, t_population_wpp_projection,
db/mappings/population_wpp_projection.yaml, db/registry/names.yaml).

No database and no network. The fixture is the UN's own text, cut untouched on
2026-10-13 from WPP2024_Demographic_Indicators_Medium.csv.gz (World Population
Prospects 2024, CC BY 3.0 IGO):

  wpp2024_projection_sample.csv   the header and eight rows: the State of
      Palestine in 2023 (the last estimate), 2024, 2025, 2026, 2050, 2100 and
      2101 (projections; 2101 fills one column), and Jordan in 2030.

What is held here: the file is split at the last estimate year and nowhere
else; a projection record says what it is and neither transformer takes the
other's records; the estimates are written as before; identities do not
collide; every projection series is classified as its estimate is, carries the
one warning, and is named from its estimate by rule with the word first; the
spec's floors are the measured file's; and the spec is switched off until the
serving rule exists.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from ingest import databank, spec as spec_mod
from ops import fetch_wpp, fetchlib, load_registry

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "more_projections"
SAMPLE = (FX / "wpp2024_projection_sample.csv").read_text(encoding="utf-8")
SPEC = yaml.safe_load((ROOT / "db" / "mappings" / "population_wpp_projection.yaml")
                      .read_text(encoding="utf-8"))
ESTIMATES = yaml.safe_load((ROOT / "db" / "mappings" / "population_wpp.yaml")
                           .read_text(encoding="utf-8"))
INDICATORS = [v[0] for v in fetch_wpp.INDICATORS.values()]
EST = "population.wpp."
PRO = "population.wpp_projection."


def _palestine(year: int) -> dict:
    return next(r for r in csv.DictReader(io.StringIO(SAMPLE))
                if r["LocID"] == "275" and r["Time"] == str(year))


def _value(recs: list[dict], year: int, indicator: str) -> float:
    return next(r["value"] for r in recs if r["year"] == year and r["indicator"] == indicator)


# ── the split, at the last estimate year and nowhere else ────────────────────

def test_the_file_is_split_at_the_last_estimate_year():
    est, pro = fetch_wpp.parse(SAMPLE), fetch_wpp.parse_projection(SAMPLE)
    assert fetch_wpp.LAST_ESTIMATE == 2023
    assert {r["year"] for r in est} == {2023}
    assert {r["year"] for r in pro} == {2024, 2025, 2026, 2050, 2100, 2101}
    assert max(r["year"] for r in est) < min(r["year"] for r in pro)
    assert {r["location"] for r in est + pro} == {"State of Palestine"}     # Jordan's 2030 is in the sample
    # every row of the file lands in exactly one of the two
    assert len(est) == 51
    assert not {r["stable_id"] for r in est} & {r["stable_id"] for r in pro}


def test_every_column_is_projected_to_2100_and_one_to_2101():
    pro = fetch_wpp.parse_projection(SAMPLE)
    per_year = Counter(r["year"] for r in pro)
    assert per_year == {2024: 51, 2025: 51, 2026: 51, 2050: 51, 2100: 51, 2101: 1}
    for year in (2024, 2025, 2026, 2050, 2100):
        assert {r["indicator"] for r in pro if r["year"] == year} == set(INDICATORS)
    assert [r["indicator"] for r in pro if r["year"] == 2101] == ["population_total_1jan"]
    # the blank cells of 2101 are the UN's, not a parse that gave up
    row = _palestine(2101)
    assert row["TPopulation1Jan"] == "11485.718" and row["TPopulation1July"] == "" and row["Deaths"] == ""
    # the measured file: 77 years of 51 columns and that one cell
    assert fetch_wpp.PROJECTION_MEASURED == 77 * 51 + 1 == 3928
    assert fetch_wpp.FLOOR_PROJECTION == int(3928 * 0.95) == 3731


def test_another_variant_or_another_country_is_not_taken():
    header, pal_2024 = SAMPLE.splitlines()[0], SAMPLE.splitlines()[3]
    assert ",Medium,2024," in pal_2024
    text = "\n".join([header, pal_2024, pal_2024.replace(",Medium,2024,", ",High,2024,"),
                      pal_2024.replace(",2,Medium,2024,", ",2,Medium,soon,")])
    pro = fetch_wpp.parse_projection(text)
    assert len(pro) == 51 and {r["variant"] for r in pro} == {"Medium"}
    assert fetch_wpp.VARIANT == "Medium"


def test_the_estimates_are_written_exactly_as_before():
    pop = next(r for r in fetch_wpp.parse(SAMPLE) if r["indicator"] == "population_total")
    assert pop == {"stable_id": "wpp-2024:2023:population_total", "year": 2023,
                   "indicator": "population_total", "value": 5409202.0, "unit": "persons",
                   "wpp_column": "TPopulation1July", "wpp_unit": "thousands",
                   "location": "State of Palestine"}
    for r in fetch_wpp.parse(SAMPLE):
        assert set(r) == set(pop)                       # no projection key ever reaches an estimate


# ── what a projection record says about itself ───────────────────────────────

def test_a_projection_record_says_what_it_is():
    pro = fetch_wpp.parse_projection(SAMPLE)
    deaths = next(r for r in pro if r["stable_id"] == "wpp-2024-projection:2026:deaths")
    assert deaths == {"stable_id": "wpp-2024-projection:2026:deaths", "year": 2026,
                      "indicator": "deaths", "value": 16412.0, "unit": "persons",
                      "wpp_column": "Deaths", "wpp_unit": "thousands",
                      "location": "State of Palestine", "projection": True,
                      "variant": "Medium", "edition": 2024, "released": "2024-07-11"}
    assert _palestine(2026)["Variant"] == "Medium"       # the UN's own word, not ours
    assert fetch_wpp.VINTAGE == "2024-07-11" and fetch_wpp.EDITION == 2024
    for r in pro:
        assert (r["projection"], r["variant"], r["edition"], r["released"]) == \
            (True, "Medium", 2024, "2024-07-11")
        assert r["stable_id"] == f"wpp-2024-projection:{r['year']}:{r['indicator']}"
        assert r["value"] == round(r["value"], 3)
    # the unit word is the one the estimate rows carry for the same column
    by_col = {col: v[3] for col, v in fetch_wpp.INDICATORS.items()}
    assert all(r["wpp_unit"] == by_col[r["wpp_column"]] for r in pro)


def test_the_warning_s_figures_are_the_file_s():
    est, pro = fetch_wpp.parse(SAMPLE), fetch_wpp.parse_projection(SAMPLE)
    assert _palestine(2023)["Deaths"] == "38.937" and _palestine(2026)["Deaths"] == "16.412"
    assert _value(est, 2023, "deaths") == 38937.0 and _value(pro, 2026, "deaths") == 16412.0
    assert _palestine(2023)["LEx"] == "65.1703" and _palestine(2026)["LEx"] == "77.4228"
    assert round(_value(est, 2023, "life_expectancy"), 1) == 65.2
    assert round(_value(pro, 2026, "life_expectancy"), 1) == 77.4
    for rule in SPEC["registry"]["rules"]:
        en, ar = rule["serve_warning"], rule["serve_warning_ar"]
        for figure in ("38,937", "16,412", "65.2", "77.4", "2023", "2026"):
            assert figure in en and figure in ar, figure
        assert "11 July 2024" in en and "11 July 2027" in en
        assert "11 تموز 2024" in ar and "11 تموز 2027" in ar


# ── the transformers: each takes its own records and no others ───────────────

def test_a_projection_row_carries_its_attrs_and_its_own_dataset():
    recs = {r["stable_id"]: r for r in fetch_wpp.parse_projection(SAMPLE)}
    [row] = databank.t_population_wpp_projection(recs["wpp-2024-projection:2100:life_expectancy"],
                                                 {}, {}, Counter())
    assert row.dataset_key == "un_wpp_2024_projection"
    assert row.indicator == "population.wpp_projection.life_expectancy"
    assert (row.occurred_at, row.precision, row.place_id) == ("2100-01-01", "year", None)
    assert (row.value_num, row.unit) == (87.545, "years")
    assert row.v1_stable_id == "wpp-2024-projection:2100:life_expectancy"
    assert row.attrs == {"region": "Palestine", "projection": True, "variant": "Medium",
                         "edition": 2024, "released": "2024-07-11",
                         "wpp_column": "LEx", "wpp_unit": "years at birth"}
    assert "estimate" not in row.attrs                   # it is not one
    [last] = databank.t_population_wpp_projection(
        recs["wpp-2024-projection:2101:population_total_1jan"], {}, {}, Counter())
    assert (last.occurred_at, last.value_num, last.unit) == ("2101-01-01", 11485718.0, "persons")


def test_an_estimate_row_is_what_it_was():
    rec = next(r for r in fetch_wpp.parse(SAMPLE) if r["indicator"] == "deaths")
    [row] = databank.t_population_wpp(rec, {}, {}, Counter())
    assert (row.dataset_key, row.indicator, row.occurred_at) == \
        ("un_wpp_2024", "population.wpp.deaths", "2023-01-01")
    assert row.attrs == {"region": "Palestine", "estimate": "modelled (WPP 2024, Medium variant)",
                         "wpp_column": "Deaths", "wpp_unit": "thousands", "revision": "WPP2024"}


def test_neither_transformer_takes_the_other_s_records():
    est, pro = fetch_wpp.parse(SAMPLE)[0], fetch_wpp.parse_projection(SAMPLE)[0]
    assert databank.t_population_wpp(pro, {}, {}, Counter()) == \
        databank.Drop("projection_among_estimates")
    assert databank.t_population_wpp_projection(est, {}, {}, Counter()) == \
        databank.Drop("not_a_projection")
    # a projection record that has lost one of the things it must say
    for key in ("projection", "variant", "edition", "released"):
        assert databank.t_population_wpp_projection({**pro, key: None}, {}, {}, Counter()) == \
            databank.Drop("not_a_projection"), key
    assert databank.t_population_wpp_projection({**pro, "projection": "yes"}, {}, {}, Counter()) == \
        databank.Drop("not_a_projection")
    # neither reason is a declared drop, so one such record FAILS the run
    # (ingest/databank.py: "undeclared drop reason") instead of passing quietly
    for s in (SPEC, ESTIMATES):
        assert not s.get("drop")
    assert databank.TRANSFORMERS["population_wpp_projection"] is databank.t_population_wpp_projection
    assert databank.TRANSFORMERS["population_wpp"] is databank.t_population_wpp
    assert SPEC["transform"] == "python:t_population_wpp_projection"


# ── identity ─────────────────────────────────────────────────────────────────

def test_the_identity_is_injective_and_apart_from_the_estimates():
    assert SPEC["identity"] == {"fields": ["indicator", "occurred_at"]}
    rows = [r for rec in fetch_wpp.parse_projection(SAMPLE)
            for r in databank.t_population_wpp_projection(rec, {}, {}, Counter())]
    est = [r for rec in fetch_wpp.parse(SAMPLE)
           for r in databank.t_population_wpp(rec, {}, {}, Counter())]
    key = lambda r: databank.identity_key_for(                                  # noqa: E731
        SPEC["identity"], r.dataset_key, indicator=r.indicator, occurred_at=r.occurred_at,
        place_id=r.place_id, value_num=r.value_num, attrs=r.attrs)
    keys = [key(r) for r in rows]
    assert len(set(keys)) == len(rows) == 256                 # 5 years of 51 and the one cell of 2101
    assert len({r.v1_stable_id for r in rows}) == len(rows)
    # no key, id, indicator or dataset is shared with an estimate
    assert not set(keys) & {key(r) for r in est}
    assert not {r.v1_stable_id for r in rows} & {r.v1_stable_id for r in est}
    assert not {r.indicator for r in rows} & {r.indicator for r in est}
    assert {r.dataset_key for r in rows} == {"un_wpp_2024_projection"}
    assert {r.dataset_key for r in est} == {"un_wpp_2024"}
    assert all(k.startswith("un_wpp_2024_projection|population.wpp_projection.") for k in keys)


# ── the spec ─────────────────────────────────────────────────────────────────

def test_the_spec_validates_switched_on_or_off_and_is_off():
    assert spec_mod.validate(SPEC, "population_wpp_projection") == []
    on = {k: v for k, v in SPEC.items() if k not in ("migrate", "skip_reason")}
    assert spec_mod.validate(on, "population_wpp_projection") == []
    # switched off, with the reason on the switch: the loader refuses it by
    # name and the nightly run passes over it (ingest/databank.py run_all)
    assert SPEC["migrate"] is False and "serving rule" in SPEC["skip_reason"]
    with pytest.raises(spec_mod.SpecRefused, match="migrate=false"):
        databank.load_spec("population_wpp_projection")
    assert spec_mod.validate(ESTIMATES, "population_wpp") == []
    assert ESTIMATES.get("migrate", True) is True          # the estimates still load


def test_the_spec_s_floor_and_ceiling_are_the_measured_file_s():
    assert SPEC["records_measured"] == fetch_wpp.PROJECTION_MEASURED == 3928
    assert SPEC["expect"]["min_records"] == fetch_wpp.FLOOR_PROJECTION == 3731
    assert SPEC["expect"]["max_observations"] == int(1.15 * 3928) == 4517
    assert SPEC["datasets"] == [{"key": "un_wpp_2024_projection", "source": "un_wpp"}]
    assert ESTIMATES["datasets"] == [{"key": "un_wpp_2024", "source": "un_wpp"}]    # one source row, one licence
    assert SPEC["v1_category"] == ESTIMATES["v1_category"] == "economic"
    assert SPEC["indicator"]["template"] == "population.wpp_projection.{indicator}"
    assert (SPEC["occurred_at"]["precision"], SPEC["place"]["strategy"]) == ("year", "region")


def test_each_spec_reads_its_own_file_and_not_the_other_s(tmp_path):
    for name in ("palestine.json", fetch_wpp.PROJECTION_NAME):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    read = lambda s: [f.name for f in databank._input_files(                    # noqa: E731
        {"root": str(tmp_path), "glob": s["input"]["glob"]})]
    assert read(ESTIMATES) == ["palestine.json"]
    assert read(SPEC) == ["palestine_projection.json"] == [fetch_wpp.PROJECTION_NAME]
    assert SPEC["input"]["root"] == ESTIMATES["input"]["root"] == "data/raw/wpp"
    assert fetch_wpp.projection_out() == fetch_wpp.OUT.with_name("palestine_projection.json")


# ── the registry: classified as its estimate is, and one warning for all ─────

def _pairs(prefix: str, n: int) -> list[tuple[str, str, int]]:
    return [(f"{prefix}{ind}", unit, n) for ind, unit, _m, _u in fetch_wpp.INDICATORS.values()]


def test_every_projection_series_is_classified_exactly_as_its_estimate():
    rules, est_rules = SPEC["registry"]["rules"], ESTIMATES["registry"]["rules"]
    got, conflicts = load_registry.classify(_pairs(PRO, 77), rules)
    est, _ = load_registry.classify(_pairs(EST, 74), est_rules)
    assert len(got) == len(est) == 51 and conflicts == []
    meaning = ("concept", "measure_kind", "polarity", "grain", "place_grain", "canonical_unit")
    for ind in INDICATORS:
        assert {k: got[PRO + ind][k] for k in meaning} == {k: est[EST + ind][k] for k in meaning}, ind
    for ind, unit, _n in _pairs(PRO, 77):
        hits = [r for r in rules if load_registry.matches(r, ind, unit)]
        assert len(hits) == 1, (ind, [r["when"] for r in hits])
        assert got[ind]["canonical_unit"] == unit                # never converted
    assert SPEC["registry"]["max_unclassified"] == 0
    assert load_registry.unclassified_by_reader(
        [("population_wpp_projection", _pairs(PRO, 77), got)]) == {"population_wpp_projection": []}


def test_no_rule_of_one_family_reaches_the_other():
    """Both specs share the serving category `economic`, so each is handed
    the other's indicators (and the World Bank's) by ops/load_registry.py."""
    rules, est_rules = SPEC["registry"]["rules"], ESTIMATES["registry"]["rules"]
    for ind, unit, _n in _pairs(EST, 74):
        assert not any(load_registry.matches(r, ind, unit) for r in rules), ind
    for ind, unit, _n in _pairs(PRO, 77):
        assert not any(load_registry.matches(r, ind, unit) for r in est_rules), ind
    for other in ("economic.SP.POP.TOTL", "population.wpp_projection_high.deaths",
                  "population.wpp_projectionx.deaths", "wpp_projection.deaths"):
        assert not any(load_registry.matches(r, other, "persons") for r in rules), other
    # read together, the two specs leave nothing of either family unclassified
    both = _pairs(EST, 74) + _pairs(PRO, 77)
    got_e, _ = load_registry.classify(both, est_rules)
    got_p, _ = load_registry.classify(both, rules)
    assert set(got_e) == {EST + i for i in INDICATORS} and set(got_p) == {PRO + i for i in INDICATORS}
    assert load_registry.unclassified_by_reader(
        [("population_wpp", both, got_e), ("population_wpp_projection", both, got_p)]) == \
        {"population_wpp": [], "population_wpp_projection": []}


def test_all_of_them_carry_one_warning_in_both_languages():
    rules = SPEC["registry"]["rules"]
    assert len({r["serve_warning"] for r in rules}) == len({r["serve_warning_ar"] for r in rules}) == 1
    got, _ = load_registry.classify(_pairs(PRO, 77), rules)
    assert all(m["serve_warning"] and m["serve_warning_ar"] for m in got.values())
    en, ar = rules[0]["serve_warning"], rules[0]["serve_warning_ar"]
    assert en.startswith("A PROJECTION, not a measurement") and "medium-variant" in en
    assert ar.startswith("هاد إسقاط مش قياس") and "المتغير المتوسط" in ar
    assert "estimates end at 2023" in en and "population.wpp.*" in en and "population.wpp.*" in ar
    assert not re.search("[٠-٩۰-۹]", ar) and "\n" not in en and "\n" not in ar
    # the estimates carry none: a warning about a projection is not theirs
    assert not any(r.get("serve_warning") for r in ESTIMATES["registry"]["rules"])


# ── names: the estimate's name, by rule, with the word first ─────────────────

EN_ESTIMATE = " (UN World Population Prospects 2024 estimate)"
EN_PROJECTION = " (UN World Population Prospects 2024, medium variant)"
AR_ESTIMATE = " (تقديرات التوقعات السكانية في العالم 2024، الأمم المتحدة)"
AR_PROJECTION = " (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)"


def projection_name(estimate: dict) -> dict:
    """THE RULE. A projection is called what its estimate is called, with the
    word first and the bracket naming the edition and the variant instead of
    saying "estimate". A name that does not end in the estimate's bracket has
    no projection name: the rule does not guess."""
    en, ar = estimate["en"], estimate["ar"]
    if not en.endswith(EN_ESTIMATE) or not ar.endswith(AR_ESTIMATE):
        raise ValueError(f"not an estimate's name: {en!r}")
    return {"en": "Projection: " + en[:-len(EN_ESTIMATE)] + EN_PROJECTION,
            "ar": "إسقاط: " + ar[:-len(AR_ESTIMATE)] + AR_PROJECTION}


def test_the_rule_on_one_name_and_on_a_name_it_must_refuse():
    assert projection_name({"en": "Deaths per year (UN World Population Prospects 2024 estimate)",
                            "ar": "عدد الوفيات في السنة (تقديرات التوقعات السكانية في العالم 2024، الأمم المتحدة)"}) == {
        "en": "Projection: Deaths per year (UN World Population Prospects 2024, medium variant)",
        "ar": "إسقاط: عدد الوفيات في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)"}
    with pytest.raises(ValueError):
        projection_name({"en": "Deaths per year (World Bank)", "ar": "عدد الوفيات في السنة (البنك الدولي)"})


def test_every_projection_name_is_its_estimate_s_name_by_that_rule():
    names = load_registry.load_names()["names"]
    held = {k: v for k, v in names.items() if k.startswith(PRO)}
    assert set(held) == {PRO + i for i in INDICATORS} and len(held) == 51
    for ind in INDICATORS:
        assert held[PRO + ind] == projection_name(names[EST + ind]), ind
    seen_en, seen_ar = set(), set()
    for ind, n in held.items():
        assert n["en"].startswith("Projection: ") and n["ar"].startswith("إسقاط: "), ind
        assert "2024" in n["en"] and "2024" in n["ar"], ind                 # the edition
        assert "estimate" not in n["en"] and "تقديرات" not in n["ar"], ind  # it is not one
        assert "medium variant" in n["en"] and "المتغير المتوسط" in n["ar"], ind
        assert not re.search("[٠-٩۰-۹]", n["ar"]), ind
        seen_en.add(n["en"])
        seen_ar.add(n["ar"])
    assert len(seen_en) == len(seen_ar) == 51
    assert not (seen_en | seen_ar) & {v[k] for i in INDICATORS for k, v in
                                      (("en", names[EST + i]), ("ar", names[EST + i]))}


def test_the_loader_gives_each_series_that_name():
    doc = load_registry.load_names()
    got, _ = load_registry.classify(_pairs(PRO, 77), SPEC["registry"]["rules"])
    for ind, _unit, _n in _pairs(PRO, 77):
        en, ar = load_registry.name_for(ind, got[ind], None, doc)
        assert en == doc["names"][ind]["en"] and ar == doc["names"][ind]["ar"], ind
        assert en.startswith("Projection: ") and ar.startswith("إسقاط: ")


# ── the vintage each file carries, and the fetch that writes both ────────────

class _Answer:
    """What urlopen hands back: the sample, gzipped, with the UN's header."""
    headers = {"Last-Modified": "Fri, 13 Dec 2024 19:11:17 GMT"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return gzip.compress(SAMPLE.encode("utf-8"))


@pytest.fixture
def fetch(tmp_path, monkeypatch):
    """main() pointed at a temporary tree, the network answered by the sample
    (51 estimate records and 256 projection records)."""
    out = tmp_path / "wpp" / "palestine.json"
    out.parent.mkdir()
    calls, events = [], []
    monkeypatch.setattr(fetch_wpp, "OUT", out)
    monkeypatch.setattr(fetch_wpp, "ROOT", tmp_path)
    monkeypatch.setattr(fetch_wpp, "FLOOR", 40)
    monkeypatch.setattr(fetch_wpp, "FLOOR_PROJECTION", 200)
    monkeypatch.setattr(fetchlib, "EVENTS", tmp_path / "fetch-events.ndjson")
    monkeypatch.setattr(fetch_wpp, "event", lambda label, outcome, **kw: events.append((label, outcome, kw)))
    monkeypatch.setattr(fetch_wpp.urllib.request, "urlopen",
                        lambda req, timeout=0: calls.append(req.full_url) or _Answer())
    return out, calls, events


def test_one_fetch_writes_two_files_and_one_ledger_line(fetch):
    out, calls, events = fetch
    assert fetch_wpp.main([]) == 0
    assert calls == [fetch_wpp.URL]                                    # one download
    est = json.loads(out.read_text(encoding="utf-8"))
    pro = json.loads(out.with_name("palestine_projection.json").read_text(encoding="utf-8"))
    assert sorted(p.name for p in out.parent.iterdir()) == ["palestine.json", "palestine_projection.json"]
    assert len(est["data"]) == 51 and {r["year"] for r in est["data"]} == {2023}
    assert len(pro["data"]) == 256 and min(r["year"] for r in pro["data"]) == 2024
    assert not any("projection" in r for r in est["data"])
    assert all(r["projection"] is True for r in pro["data"])
    assert "projections are not here" in est["note"] and pro["note"].startswith("PROJECTION, Medium variant, 2024-2101")
    assert "not a measurement" in pro["note"]
    m = pro["metadata"]
    assert (m["projection"], m["variant"], m["edition"], m["first_year"], m["last_year"], m["indicators"]) == \
        (True, "Medium", 2024, 2024, 2101, 51)
    assert pro["license"] == est["license"] == "CC-BY-IGO-3.0" and pro["url"] == est["url"] == fetch_wpp.URL
    assert events == [("wpp-2024", "ok", {"rows": 51, "indicators": 51, "data_through": "2023",
                                          "projection_rows": 256, "projection_through": "2101"})]


def test_each_dataset_takes_its_vintage_from_its_own_file(fetch):
    out, _calls, _events = fetch
    assert fetch_wpp.main([]) == 0
    got = databank.read_vintage(SPEC, [out.with_name("palestine_projection.json")])
    assert set(got) == {"un_wpp_2024_projection"}
    assert got["un_wpp_2024_projection"]["vintage"] == "2024-07-11"
    assert got["un_wpp_2024_projection"]["vintage_url"] == "https://population.un.org/wpp/faqs"
    assert "The estimates end at 2023" in got["un_wpp_2024_projection"]["vintage_basis"]
    assert set(databank.read_vintage(ESTIMATES, [out])) == {"un_wpp_2024"}


def test_a_held_estimates_file_without_its_projection_is_fetched_again(fetch):
    out, calls, events = fetch
    assert fetch_wpp.main([]) == 0
    assert fetch_wpp.main([]) == 0                       # both files fresh and complete: left alone
    assert len(calls) == 1 and len(events) == 1
    out.with_name("palestine_projection.json").unlink()   # the tree as it stood before 2026-10-13
    assert fetch_wpp.main([]) == 0
    assert len(calls) == 2 and out.with_name("palestine_projection.json").exists()
    assert fetch_wpp.main(["--force"]) == 0              # and whenever it is asked
    assert len(calls) == 3


def test_a_short_projection_is_refused_and_both_held_files_stand(fetch, monkeypatch):
    out, _calls, events = fetch
    assert fetch_wpp.main([]) == 0
    pro = out.with_name("palestine_projection.json")
    before = (out.read_text(encoding="utf-8"), pro.read_text(encoding="utf-8"))
    monkeypatch.setattr(fetch_wpp, "FLOOR_PROJECTION", 3731)           # the real floor; the sample holds 256
    assert fetch_wpp.main(["--force"]) == 1
    assert (out.read_text(encoding="utf-8"), pro.read_text(encoding="utf-8")) == before
    assert events[1:] == [("wpp-2024", "refused", {"rows": 256, "floor": 3731, "part": "projection"})]
    # ...and a short ESTIMATES part is refused first, before the projection is looked at
    monkeypatch.setattr(fetch_wpp, "FLOOR", 3585)
    assert fetch_wpp.main(["--force"]) == 1
    assert (out.read_text(encoding="utf-8"), pro.read_text(encoding="utf-8")) == before
    ledger = [json.loads(x) for x in fetchlib.EVENTS.read_text().splitlines()]
    assert [(e["label"], e["outcome"], e["rows"], e["floor"]) for e in ledger] == \
        [("wpp-2024", "refused", 51, 3585)]
    assert len(events) == 2                               # no `ok` line for either refusal
