"""The health supply line: WHO GHO's own rows for Palestine, every dimension
kept (2026-10-12).

Offline: the fetcher's parsing and the transformer run on real answers of
ghoapi.azureedge.net saved under tests/fixtures/supply_who/ (trimmed, fetched
2026-10-12), the held side is the 18 rows the store held for one code that
day, and the loader runs against a fake store that records what it would
write. No network, no database.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from collections import Counter
from pathlib import Path

import pytest
import yaml

from ingest import databank
from ingest import spec as spec_mod
from ingest.databank import (Drop, content_of, gho_unit_from_name,
                             identity_key_for, load_spec, slug, t_health)
from ops import fetch_gho_health as gh
from ops import fetchlib as fl
from ops.load_registry import classify

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "supply_who"
SAMPLE = json.loads((FX / "gho_sample.json").read_text())
HELD_AIR_41 = json.loads((FX / "held_air_41.json").read_text())["rows"]
UNITS = json.loads((FX / "units_2026-10-12.json").read_text())["units"]
SPEC = load_spec("health")


def recs(*codes):
    """The fetcher's records for some of the sample's codes."""
    rows = {c: SAMPLE["rows_by_code"][c] for c in (codes or SAMPLE["rows_by_code"])}
    return gh.records(rows, SAMPLE["names"], SAMPLE["labels"])


def emit(*codes):
    out, drops = [], Counter()
    for rec in recs(*codes):
        res = t_health(rec, SPEC, {}, Counter())
        if isinstance(res, Drop):
            drops[res.reason] += 1
        else:
            out += res
    return out, drops


def key(row, ident=None):
    return identity_key_for(ident or SPEC["identity"], row.dataset_key,
                            indicator=row.indicator, occurred_at=row.occurred_at,
                            place_id=row.place_id, value_num=row.value_num,
                            attrs=row.attrs)


# ── the fetcher ──────────────────────────────────────────────────────────────

def test_the_codes_are_the_held_ones_and_no_more():
    # the store's 12,502 rows carry exactly the codes of the frozen corpus
    # (measured 2026-10-12: 184 = 184), and the corpus is in the repository
    corpus = json.loads(gzip.decompress((ROOT / "data/frozen/health.json.gz").read_bytes()))
    held = {r["indicator_code"] for r in corpus["data"] if r.get("indicator_code")}
    assert set(gh.CODES) == held and len(gh.CODES) == len(held) == 184
    assert list(gh.CODES) == sorted(gh.CODES)


def test_one_code_is_asked_for_palestine_and_the_answer_is_checked(monkeypatch):
    assert gh.data_url("GHED_GGHE-D_pc_US_SHA2011") == (
        "https://ghoapi.azureedge.net/api/GHED_GGHE-D_pc_US_SHA2011"
        "?$filter=SpatialDim%20eq%20%27PSE%27")
    rows = SAMPLE["rows_by_code"]["AIR_41"]
    pages = {gh.data_url("AIR_41"): {"value": rows[:10], "@odata.nextLink": "page2"},
             "page2": {"value": rows[10:]}}
    monkeypatch.setattr(gh, "_get", lambda url: pages[url])
    assert gh.fetch_code("AIR_41") == rows                  # paging is followed

    monkeypatch.setattr(gh, "_get", lambda url: {"value": rows})
    with pytest.raises(ValueError, match="holds a row for AIR_41/PSE"):
        gh.fetch_code("AIR_42")                             # another code's rows
    other_place = [{**rows[0], "SpatialDim": "ISR"}]
    monkeypatch.setattr(gh, "_get", lambda url: {"value": other_place})
    with pytest.raises(ValueError, match="AIR_41/ISR"):
        gh.fetch_code("AIR_41")
    monkeypatch.setattr(gh, "_get", lambda url: {"error": "throttled"})
    with pytest.raises(ValueError, match="not an OData answer"):
        gh.fetch_code("AIR_41")


def test_a_failed_request_is_tried_once_more_and_no_more(monkeypatch):
    monkeypatch.setattr(gh.time, "sleep", lambda s: None)
    calls = []

    def flaky(url, timeout=60):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("reset")
        return {"value": []}
    monkeypatch.setattr(gh, "get_json", flaky)
    assert gh._get("u") == {"value": []} and len(calls) == 2

    def dead(url, timeout=60):
        calls.append(url)
        raise OSError("down")
    calls.clear()
    monkeypatch.setattr(gh, "get_json", dead)
    with pytest.raises(OSError):
        gh._get("u")
    assert len(calls) == 2


def test_records_keep_whos_fields_and_add_a_name_labels_and_a_stable_id():
    raw = SAMPLE["rows_by_code"]["AIR_41"][0]
    rec = next(r for r in recs("AIR_41") if r["Id"] == raw["Id"])
    assert {k: rec[k] for k in raw} == raw                  # the publisher's fields, verbatim
    assert rec["indicator_name"] == "Ambient air pollution attributable deaths"
    assert (rec["Dim1Label"], rec["Dim2Label"], rec["Dim3Label"]) == ("Both sexes", "Total", None)
    assert rec["stable_id"] == "gho:AIR_41:2021:SEX=SEX_BTSX;GHECAUSE=GHECAUSE_GHE000000"
    everything = recs()
    assert len(everything) == 71
    assert len({r["stable_id"] for r in everything}) == 71
    # the same answer is the same file, whatever order it arrived in
    shuffled = {c: list(reversed(v)) for c, v in reversed(SAMPLE["rows_by_code"].items())}
    assert gh.records(shuffled, SAMPLE["names"], SAMPLE["labels"]) == everything


def test_the_file_states_its_vintage_and_which_codes_came_back_empty():
    payload = gh.build(SAMPLE["rows_by_code"], SAMPLE["names"], SAMPLE["labels"],
                       SAMPLE["titles"], "2026-10-12T20:00:00+00:00")
    meta = payload["metadata"]
    assert meta["rows"] == len(payload["data"]) == 71
    assert meta["codes_empty"] == ["NUTWASTINGNUM"]
    # the newest `Date` among the rows; here NUTRITION_WH_3's, 14 August 2026
    assert meta["vintage"].startswith("2026-08-14")
    assert "Date" in meta["vintage_basis"] and meta["vintage_url"].startswith("https://ghoapi")
    assert meta["dimension_titles"]["GHECAUSE"] == "GHE cause of death codes"
    assert all(r["Date"] for r in payload["data"])          # every record keeps its own


def test_a_short_answer_is_refused_and_a_withdrawal_needs_a_human(monkeypatch, tmp_path):
    monkeypatch.setattr(fl, "EVENTS", tmp_path / "events.ndjson")
    held = {"data": recs()}
    fewer = {"data": [r for r in held["data"] if r["IndicatorCode"] != "AIR_41"]}   # 53 of 71
    with pytest.raises(fl.FetchRefused, match="53 rows against 71 on disk"):
        gh.check_against_held(fewer, held, accept_shrink=False)
    line = json.loads((tmp_path / "events.ndjson").read_text().splitlines()[-1])
    assert line["outcome"] == "refused" and line["codes_gone"] == ["AIR_41"]
    gh.check_against_held(fewer, held, accept_shrink=True)   # a human looked
    gh.check_against_held(fewer, None, accept_shrink=False)  # nothing on disk to protect
    gh.check_against_held(held, held, accept_shrink=False)
    # many codes gone empty is a broken answer even when the row count holds
    monkeypatch.setattr(gh, "GONE_CODES", 1)
    monkeypatch.setattr(gh, "SHRINK", 0.0)
    two_gone = {"data": [r for r in held["data"]
                         if r["IndicatorCode"] not in ("SDGPM25", "WHS3_50")]}
    with pytest.raises(fl.FetchRefused, match="2 code"):
        gh.check_against_held(two_gone, held, accept_shrink=False)


def _wire(monkeypatch, tmp_path, fail_on=None):
    """main() against the sample: three codes, the API answered from the
    fixture, `fail_on` failing (after its retry) until removed from the set."""
    codes = ("AIR_41", "NUTWASTINGNUM", "WHS4_154")
    monkeypatch.setattr(gh, "CODES", codes)
    monkeypatch.setattr(gh, "OUT", tmp_path / "raw" / "health_pse.json")
    monkeypatch.setattr(gh, "PARTS", tmp_path / "raw" / "health_parts")
    monkeypatch.setattr(gh, "FLOOR_ROWS", 1)
    monkeypatch.setattr(gh, "FLOOR_CODES", 1)
    monkeypatch.setattr(gh, "ROOT", tmp_path)
    monkeypatch.setattr(fl, "EVENTS", tmp_path / "events.ndjson")
    asked, failing = [], set(fail_on or ())
    by_url = {gh.data_url(c): c for c in codes}

    def answer(url):
        asked.append(url)
        if url in by_url:
            if by_url[url] in failing:
                raise OSError("HTTP 503")
            return {"value": SAMPLE["rows_by_code"][by_url[url]]}
        if url.endswith("/Indicator"):
            return {"value": [{"IndicatorCode": c, "IndicatorName": n}
                              for c, n in SAMPLE["names"].items()]}
        if url.endswith("/Dimension"):
            return {"value": [{"Code": c, "Title": t} for c, t in SAMPLE["titles"].items()]}
        kind = url.split("/DIMENSION/")[1].split("/")[0]
        return {"value": [{"Code": c, "Title": t} for c, t in SAMPLE["labels"][kind].items()]}
    monkeypatch.setattr(gh, "_get", answer)
    events = lambda: [json.loads(l) for l in (tmp_path / "events.ndjson").read_text().splitlines()]
    return asked, failing, events, by_url


def test_a_run_stopped_halfway_writes_nothing_and_the_next_one_resumes(monkeypatch, tmp_path):
    asked, failing, events, by_url = _wire(monkeypatch, tmp_path, fail_on={"WHS4_154"})
    assert gh.main([]) == 1
    assert not gh.OUT.exists()                              # atomic: no half file
    assert sorted(p.stem for p in gh.PARTS.glob("*.json")) == ["AIR_41", "NUTWASTINGNUM"]
    assert events()[-1]["outcome"] == "error" and "503" in events()[-1]["error"]

    asked.clear()
    failing.clear()
    assert gh.main([]) == 0
    assert [by_url[u] for u in asked if u in by_url] == ["WHS4_154"]   # only what was missing
    out = json.loads(gh.OUT.read_text())
    assert out["metadata"]["rows"] == 22 and out["metadata"]["codes_empty"] == ["NUTWASTINGNUM"]
    assert events()[-1]["outcome"] == "ok" and events()[-1]["parts_reused"] == 2

    asked.clear()
    assert gh.main([]) == 0 and asked == []                 # younger than MAX_AGE_DAYS: not re-fetched
    assert len(events()) == 2                               # and no ledger line for a skip


def test_a_part_is_reused_only_while_it_is_young_and_whole(monkeypatch, tmp_path):
    monkeypatch.setattr(gh, "PARTS", tmp_path)
    fl.write_atomic(tmp_path / "AIR_41.json", {"code": "AIR_41", "rows": [{"Id": 1}]})
    now = time.time()
    assert gh.load_part("AIR_41", now) == [{"Id": 1}]
    assert gh.load_part("AIR_42", now) is None
    old = now - (gh.RESUME_HOURS + 1) * 3600
    os.utime(tmp_path / "AIR_41.json", (old, old))
    assert gh.load_part("AIR_41", now) is None
    (tmp_path / "CM_01.json").write_text('{"code": "CM_01", "ro')      # killed mid-write elsewhere
    assert gh.load_part("CM_01", now) is None


# ── the transformer: the dimension survives ──────────────────────────────────

def test_the_dimension_survives():
    # BEFORE, as the store held it: 18 rows under 3 names, six rows a name,
    # nothing in a row saying which cause of death it counts
    assert len(HELD_AIR_41) == 18
    assert Counter(h["indicator"] for h in HELD_AIR_41) == {
        "health.air_41.sex_btsx": 6, "health.air_41.sex_fmle": 6, "health.air_41.sex_mle": 6}
    assert all("GHECAUSE" not in json.dumps(h["attrs"]) for h in HELD_AIR_41)
    # AFTER: the same 18 values, each under its own name, each saying both
    rows, drops = emit("AIR_41")
    assert not drops and len(rows) == 18
    assert len({r.indicator for r in rows}) == 18
    assert sorted(r.value_num for r in rows) == sorted(h["value_num"] for h in HELD_AIR_41)
    lung = next(r for r in rows if r.value_num == 50.222)
    assert lung.indicator == "health.air_41.sex_btsx.ghecause_ghe000680"
    assert lung.attrs["dim"] == {"SEX": "SEX_BTSX", "GHECAUSE": "GHECAUSE_GHE000680"}
    assert lung.attrs["dim_label"] == {"SEX": "Both sexes",
                                       "GHECAUSE": "Trachea, bronchus, lung cancers"}
    assert lung.attrs["dim_key"] == "SEX=SEX_BTSX;GHECAUSE=GHECAUSE_GHE000680"
    assert (lung.occurred_at, lung.precision, lung.place_id) == ("2021-01-01", "year", None)
    assert lung.attrs["region"] == "Palestine"
    assert (lung.attrs["value_low"], lung.attrs["value_high"]) == (27.031, 82.055)
    assert all(set(r.attrs["dim"]) == {"SEX", "GHECAUSE"} for r in rows)


def test_two_sexes_are_two_identities():
    rows, _ = emit("NUTSTUNTINGNUM")
    assert [r.attrs["dim"]["SEX"] for r in rows] == ["SEX_BTSX", "SEX_FMLE", "SEX_MLE"]
    keys = [key(r) for r in rows]
    assert len(set(keys)) == 3
    assert keys[1] == ("v1_health_who|health.nutstuntingnum.sex_fmle|2022-01-01||SEX=SEX_FMLE")
    # the value is not what makes the row itself: a revised number is the SAME
    # row saying something else, which is what lets the loader supersede it
    female = rows[1]
    revised = t_health({**recs("NUTSTUNTINGNUM")[1], "NumericValue": 26.1}, SPEC, {}, Counter())[0]
    assert key(revised) == key(female) and revised.value_num != female.value_num
    assert "value_num" not in SPEC["identity"]["fields"]
    assert SPEC["identity"]["attrs"] == ["dim_key"]


def test_rows_that_differ_only_in_a_second_dimension_are_apart():
    # severe wasting among girls, 2020, by age group: 22 rows, the value 0.3
    # four times and 0.7 four times. v1's route kept the sex alone, so equal
    # values became ONE row and the rest sat under one name.
    rows, drops = emit("NUTRITION_WH_3")
    assert not drops and len(rows) == 22
    assert Counter(r.value_num for r in rows)[0.3] == 4
    assert len({r.indicator for r in rows}) == 22 and len({key(r) for r in rows}) == 22
    assert len({(r.indicator, r.occurred_at, r.place_id) for r in rows}) == 22
    total = next(r for r in rows if set(r.attrs["dim"]) == {"SEX"})
    assert total.indicator == "health.nutrition_wh_3.sex_fmle"
    one = next(r for r in rows if r.attrs["dim"].get("AGEGROUP") == "AGEGROUP_MONTHS54-59")
    assert one.indicator == "health.nutrition_wh_3.sex_fmle.agegroup_months54_59"
    # a bound of zero is a bound (v1 wrote `low || null` and lost it)
    assert (one.value_num, one.attrs["value_low"], one.attrs["value_high"]) == (0.0, 0.0, 0.0)


def test_three_dimensions_keep_whos_order_and_none_is_said_too():
    rows, _ = emit("CARE_SOURCE")
    three = next(r for r in rows if len(r.attrs["dim"]) == 3)
    assert three.attrs["dim_key"].split(";")[0].startswith("WEALTHQUINTILE=")
    assert three.indicator.startswith("health.care_source.wealthquintile_wq")
    assert three.indicator.endswith(".carepatient_carepatient_tot.caresector_caresector_pub")
    assert len(three.attrs["dim_label"]) == 3
    # an indicator WHO does not break down says so: an empty dim, never a missing one
    none, _ = emit("WHS4_154")
    assert {r.indicator for r in none} == {"health.whs4_154"}
    assert all(r.attrs["dim"] == {} and r.attrs["dim_key"] == "" for r in none)
    assert len({key(r) for r in none}) == 4
    # a survey period is filed under the year WHO files it under, and says its span
    last = max(none, key=lambda r: r.occurred_at)
    assert (last.occurred_at, last.attrs["period"], last.value_num) == ("2020-01-01", "2017-2020", 94.8)


def test_an_indicator_with_one_dimension_keeps_the_name_it_had():
    rows, _ = emit("WSH_WATER_BASIC")
    assert {r.indicator for r in rows} == {
        "health.wsh_water_basic.residenceareatype_totl",    # the name tests/test_api.py asks for
        "health.wsh_water_basic.residenceareatype_urb",
        "health.wsh_water_basic.residenceareatype_rur"}
    assert all(r.indicator.startswith("health.wsh") for r in rows)    # v_water's rule (051)


def test_the_stable_id_has_one_rendering():
    for rec in recs():
        assert rec["stable_id"] == gh.stable_id(rec) == databank.gho_stable_id(rec)
        assert gh.dim_key(rec) == databank.gho_dim_key(rec)
    rows, _ = emit()
    assert {r.v1_stable_id for r in rows} <= {r["stable_id"] for r in recs()}


# ── the transformer: what is counted out ─────────────────────────────────────

def test_a_row_without_a_number_is_counted_out_never_parsed():
    rows, drops = emit("TOBACCO_MPOWER_W2A_CIGARETTES", "WHS3_50")
    assert drops == {"no_numeric_value": 4}                 # three "No", one blank
    assert len(rows) == 3
    year_in_words = {**recs("TOBACCO_MPOWER_W2A_CIGARETTES")[0], "NumericValue": None, "Value": "2006"}
    assert t_health(year_in_words, SPEC, {}, Counter()).reason == "no_numeric_value"
    assert t_health({"IndicatorCode": "AIR_41"}, SPEC, {}, Counter()).reason == "missing_identity"
    declared = {d["reason"] for d in SPEC["drop"]}
    assert declared == {"no_numeric_value", "projection_after_publication", "missing_identity"}


def test_a_projection_is_judged_on_the_rows_own_date():
    rows, drops = emit("M_Est_smk_curr")
    assert drops == {"projection_after_publication": 3}     # the 2030 point, three sexes
    assert {r.occurred_at for r in rows} == {"2025-01-01"}  # written by WHO in January 2026
    rec = recs("M_Est_smk_curr")[0]
    assert t_health({**rec, "TimeDim": 2027, "Date": "2026-01-15T10:00:00+01:00"},
                    SPEC, {}, Counter()).reason == "projection_after_publication"
    assert isinstance(t_health({**rec, "TimeDim": 2026, "Date": "2026-01-15T10:00:00+01:00"},
                               SPEC, {}, Counter()), list)


def test_the_vintage_is_the_rows_own_date_and_is_not_what_the_row_says():
    rec = recs("AIR_41")[0]
    row = t_health(rec, SPEC, {}, Counter())[0]
    assert row.reported_at == rec["Date"] == "2026-06-15T14:12:00.073+02:00"
    again = t_health({**rec, "Date": "2027-02-01T09:00:00+01:00"}, SPEC, {}, Counter())[0]
    says = lambda r: content_of(value_num=r.value_num, value_text=r.value_text, unit=r.unit,
                                place_id=r.place_id, attrs=r.attrs)
    # WHO republishing an unchanged number is not a revision
    assert says(again) == says(row) and again.reported_at != row.reported_at


# ── the unit ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, unit", [
    ("Mortality rate attributed to unintentional poisoning (per 100 000 population)", "per_100000"),
    ("Ambient air pollution attributable DALYs  (per 100 000 population, age-standardized)", "per_100000"),
    ("Incidence of tuberculosis (per 100 000 population per year)", "per_100000"),
    ("Hospital beds (per 10 000 population)", "per_10000"),
    ("Neonatal mortality rate (per 1000 live births)", "per_1000"),
    ("Adolescent mortality rate (per 1 000 age specific cohort)", "per_1000"),
    ("Preterm birth rate (per 100 live births)", "per_100"),
    ("Current health expenditure (CHE) per capita in US$", "USD_per_capita"),
    ("Current health expenditure (CHE) as percentage of gross domestic product (GDP) (%)", "percent"),
    ("Population pushed below the $1.90 a day poverty line by household health expenditures (%)", "percent"),
    ("Stunting prevalence among children under 5 years of age (% height-for-age <-2 SD), survey-based estimates", "percent"),
    ("Probability (%) of dying between age 30 and exact age 70 from any of cardiovascular disease, cancer", "percent"),
    ("Distribution of road traffic deaths by type of road user (%)", "percent"),
    ("Life expectancy at birth (years)", "years"),
    ("UHC Service Coverage sub-index on infectious diseases", "index"),
    ("Number of under-five deaths", "persons"),
    ("Number of deaths among adolescents (10 to 19 years of age)", "persons"),
    ("Measles - number of reported cases", "cases"),
    ("Estimated number of MDR/RR-TB incident cases", "cases"),
    ("Number of children aged 6-59 months with anaemia (thousands)", "thousand_persons"),
    ("Low birth weight number (in thousands)", "thousand_persons"),
    ("Preterm birth (number)", "count"),
    ("Sugar-content of beverage (g/100ml)", "g_per_100ml"),
    ("Amount of water- and sanitation-related official development assistance that is part of a "
     "government-coordinated spending plan (constant 2024 US$ millions)", "USD_millions"),
    ("Mortality rate (per 100 000 population)", "per_100000"),          # no-break spaces
    # names that state nothing: no unit from the rule, whatever the words suggest
    ("Treatment success rate: new TB cases", None),           # a rate, not a count of cases
    ("Premature deaths due to noncommunicable diseases (NCD) as a proportion of all NCD deaths", None),
    ("Total NCD Deaths", None),
    ("Prevalence of diabetes, crude", None),
    ("Concentrations of fine particulate matter (PM2.5)", None),
    ("Beverage price", None),
    ("Stunting numbers among children under 5 years of age (millions), model-based estimates", None),
    ("", None), (None, None),
])
def test_the_unit_rule_reads_what_the_name_states(name, unit):
    assert gho_unit_from_name(name) == unit


def test_every_held_code_has_the_unit_decided_on_2026_10_12():
    table = SPEC["value"]["unit_by_code"]
    names = SAMPLE["names"]
    assert set(UNITS) == set(gh.CODES) == set(names)
    decided = {c: (table[c] if c in table else gho_unit_from_name(names[c])) for c in gh.CODES}
    assert decided == UNITS
    # the table speaks only where the name is silent, so no code is decided twice
    assert all(gho_unit_from_name(names[c]) is None for c in table)
    assert set(table) <= set(gh.CODES)
    no_unit = sorted(c for c, u in decided.items() if u is None)
    assert len(no_unit) == 18 and no_unit[0] == "TAXBEV_PRICE"
    assert all(c.startswith("TOBACCO_MPOWER_") for c in no_unit[1:])
    assert sum(1 for c in gh.CODES if c not in table) == 138    # names that state their unit


def test_the_unit_is_the_indicators_never_the_values():
    # v1 looked at each number: the store held AIR_41 under two units
    assert Counter(h["unit"] for h in HELD_AIR_41) == {"number": 10, "percentage": 8}
    rows, _ = emit("AIR_41")
    assert {r.unit for r in rows} == {"persons"}             # deaths, all 18
    assert {r.value_num for r in rows} >= {39.169, 1145.749}


def test_the_spec_table_decides_where_the_name_cannot_and_null_means_none():
    by = lambda code: {r.unit for r in emit(code)[0]}
    assert by("TB_c_new_tsr") == {"percent"}                 # WHO: "The proportion of cases ..."
    assert by("SDGPM25") == {"ug_per_m3"}                    # WHO: "Micrograms per cubic meter"
    assert by("NUTSTUNTINGNUM") == {"thousand_persons"}      # the API name says "(millions)"
    assert by("TOBACCO_MPOWER_W2A_CIGARETTES") == {None}     # decided: no unit
    assert by("WHS4_154") == by("WSH_WATER_BASIC") == by("CARE_SOURCE") == {"percent"}
    # a null in the table is a decision, and beats a name that later gains a "(%)"
    numbered = next(r for r in recs("TOBACCO_MPOWER_W2A_CIGARETTES") if r["NumericValue"] is not None)
    renamed = {**numbered, "indicator_name": "Tobacco warnings (%)"}
    assert t_health(renamed, SPEC, {}, Counter())[0].unit is None


# ── the spec and the registry ────────────────────────────────────────────────

def test_the_spec_is_valid_and_declares_how_a_row_is_itself():
    doc = yaml.safe_load((ROOT / "db/mappings/health.yaml").read_text())
    assert spec_mod.validate(doc, "health") == []
    assert SPEC["transform"] == "python:t_health"
    assert databank.TRANSFORMERS["health"] is t_health
    assert (SPEC["input"]["root"], SPEC["input"]["glob"]) == ("data/raw/gho", "health_pse.json")
    assert SPEC["input"]["root"] == str(gh.OUT.parent.relative_to(gh.ROOT))
    assert SPEC["identity"]["generation"] == "complete"
    # no fallback until the first run has closed the held rows: a fallback run
    # closes nothing, and would write the new rows beside them
    assert "fallback" not in SPEC["input"]
    assert [d["key"] for d in SPEC["datasets"]] == [
        "v1_health_who", "v1_health_gaza_moh", "v1_health_hdx"]


def test_the_old_transformer_is_kept_for_replay_only():
    assert databank.REPLAY_TRANSFORMERS["health"] is databank.t_health_v1
    v1 = {"indicator_code": "AIR_41", "date": "2021-01-01", "stable_id": "abc",
          "metrics": {"value": 50.222, "unit": "percentage"},
          "dimension": {"type": "SEX", "code": "SEX_BTSX", "name": "Both sexes"}}
    row = databank.t_health_v1(v1, SPEC, {}, Counter())[0]
    assert (row.indicator, row.unit, row.attrs["code"]) == (
        "health.air_41.sex_btsx", "percentage", "SEX_BTSX")


def test_every_unit_resolves_and_every_canonical_unit_exists():
    units = yaml.safe_load((ROOT / "db/registry/units.yaml").read_text())["units"]
    aliases = set(units) | {a for u in units.values() for a in (u.get("aliases") or {})}
    assert {u for u in UNITS.values() if u} <= aliases
    concepts = yaml.safe_load((ROOT / "db/registry/concepts.yaml").read_text())["concepts"]
    for rule in SPEC["registry"]["rules"]:
        assert rule["concept"] in concepts
        assert rule.get("canonical_unit") is None or rule["canonical_unit"] in units
    assert units["persons"]["aliases"]["thousand_persons"]["factor_num"] == 1000
    assert units["USD"]["aliases"]["USD_millions"]["factor_num"] == 1000000


def test_the_registry_gives_every_indicator_its_kind_of_number():
    rules = SPEC["registry"]["rules"]
    rows, _ = emit()
    pairs = [(i, u, n) for (i, u), n in Counter((r.indicator, r.unit) for r in rows).items()]
    got, conflicts = classify(pairs, rules)
    assert set(got) == {r.indicator for r in rows} and conflicts == []
    kind = lambda ind: (got[ind]["measure_kind"], got[ind]["canonical_unit"], got[ind]["concept"])
    assert kind("health.air_41.sex_btsx.ghecause_ghe000680") == ("flow", "persons", "health.outcome")
    assert kind("health.whs4_154") == ("ratio", "percent", "health.outcome")
    assert kind("health.wsh_water_basic.residenceareatype_totl") == ("ratio", "percent", "water.access")
    assert kind("health.nutstuntingnum.sex_fmle") == ("stock", "persons", "health.outcome")
    assert kind("health.sdgpm25.residenceareatype_rur") == ("rate", "ug_per_m3", "health.outcome")
    assert kind("health.whs3_50") == ("flow", "count", "health.outcome")
    tobacco = next(i for i in got if i.startswith("health.tobacco_mpower_w2a"))
    assert kind(tobacco) == ("unclassified", None, "health.outcome")

    # every one of the 184 codes: a kind for each that has a unit, and
    # `unclassified` exactly for the 18 that have none
    every = [(f"health.{slug(c)}", u, 1) for c, u in UNITS.items()]
    got, _ = classify(every, rules)
    assert len(got) == 184
    unclassified = {i for i, m in got.items() if m["measure_kind"] == "unclassified"}
    assert unclassified == {f"health.{slug(c)}" for c, u in UNITS.items() if u is None}
    assert Counter(m["measure_kind"] for m in got.values()) == {
        "ratio": 97, "rate": 25, "flow": 30, "unclassified": 18, "stock": 9, "index": 5}
    assert got["health.lbw_number"]["measure_kind"] == "flow"            # births in the year
    assert got["health.nutrition_anaemia_children_num"]["measure_kind"] == "stock"
    assert got["health.ghed_che_pc_us_sha2011"]["concept"] == "health.service"


def test_the_held_rows_keep_their_definitions_until_the_first_run():
    # the nightly registry reads the store: until the run, it still holds v1's units
    got, _ = classify([("health.air_41.sex_btsx", "number", 10),
                       ("health.mdg_0000000007.sex_btsx", "percentage", 50),
                       ("health.whosis_000001.sex_btsx", "years", 22),
                       ("health.nut_bf_ebf", "number", 4)], SPEC["registry"]["rules"])
    assert [got[i]["measure_kind"] for i in (
        "health.air_41.sex_btsx", "health.mdg_0000000007.sex_btsx",
        "health.whosis_000001.sex_btsx", "health.nut_bf_ebf")] == ["stock", "ratio", "stock", "stock"]


# ── the loader, against a store that records what it is sent ─────────────────

def _run(monkeypatch, tmp_path, emitted, stored, identity):
    """databank.run with the health identity. `stored` is what the dataset
    holds: (identity_key, observation_id, value_num, value_text, unit,
    place_id, attrs), the shape the loader reads back."""
    spec = {"category": "phantom", "status": "reviewed", "shape": "observation",
            "identity": identity, "place": {},
            "expect": {"min_records": 1, "max_observations": 100000},
            "datasets": [{"key": "v1_health_who", "source": "who"}]}
    log = {"inserts": [], "closed": []}

    class Cur:
        rowcount = 1
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            self.sql, self.rowcount = sql, 1
            if "INSERT INTO observation" in sql:
                log["inserts"].append(params)
            elif sql.lstrip().startswith("UPDATE observation"):
                log["closed"].extend(params[0])
                self.rowcount = len(params[0])
        def fetchall(self):
            return stored if "identity_key" in self.sql else []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()
        def commit(self): log["committed"] = True
        def rollback(self): log["rolled_back"] = True

    def transform_all(category, spec, places, counts, drops):
        for r in emitted:
            counts["records_read"] += 1
            yield Path("/phantom.json"), r

    monkeypatch.setattr(databank, "RUNS", tmp_path / "runs.ndjson")
    monkeypatch.setattr(databank, "load_spec", lambda c: spec)
    monkeypatch.setitem(databank.TRANSFORMERS, "phantom", lambda *a: [])
    monkeypatch.setattr(databank, "connect", lambda: Conn())
    monkeypatch.setattr(databank, "load_places", lambda conn: {})
    monkeypatch.setattr(databank, "PointResolver", lambda conn: None)
    monkeypatch.setattr(databank, "transform_all", transform_all)
    monkeypatch.setattr(databank, "read_payload", lambda f: b"")
    monkeypatch.setattr(databank.bronze, "put",
                        lambda *a, **k: type("R", (), {"ref": "bronze:x"}))
    monkeypatch.setattr(databank, "ensure_datasets",
                        lambda conn, spec, category: {"v1_health_who": 164})
    return databank.run("phantom", dry_run=False), log


def _held_v1():
    """The 18 AIR_41 rows as the store holds them, old identity and all."""
    return [(h["identity_key"], 271400 + i, h["value_num"], None, h["unit"], None, h["attrs"])
            for i, h in enumerate(HELD_AIR_41)]


def _held_gho(rows):
    """Rows of a GHO run, as the store would hold them afterwards."""
    return [(key(r), 900000 + i, r.value_num, r.value_text, r.unit, r.place_id,
             json.loads(json.dumps(r.attrs))) for i, r in enumerate(rows)]


def _ident(**over):
    ident = {k: v for k, v in SPEC["identity"].items() if k != "max_absent"}
    return {**ident, **over}


def test_the_first_run_closes_the_held_rows_and_writes_rows_that_name_their_dimensions(
        monkeypatch, tmp_path):
    rows, _ = emit("AIR_41")
    report, log = _run(monkeypatch, tmp_path, rows, _held_v1(), _ident(max_absent=18))
    # no held key can equal a new one: the old key ends in the value and its bounds
    assert not {k for k, *_ in _held_v1()} & {key(r) for r in rows}
    assert sorted(log["closed"]) == [271400 + i for i in range(18)]     # closed, never deleted
    assert len(log["inserts"]) == 18 and log.get("committed")
    assert report["notes"]["absent_upstream:v1_health_who"] == 18
    assert "identity_already_held" not in report["notes"] and "revisions" not in report["notes"]
    for p in log["inserts"]:
        attrs = json.loads(p["attrs"])
        assert p["identity_key"].endswith("|" + attrs["dim_key"]) and attrs["dim"]
        assert p["unit"] == "persons" and p["reported_at"].startswith("2026-06-15")
    # one current row per indicator and year: nothing is counted twice
    assert len({(p["indicator"], p["occurred_at"]) for p in log["inserts"]}) == 18


def test_without_its_ceiling_the_first_run_refuses_and_touches_nothing(monkeypatch, tmp_path):
    rows, _ = emit("AIR_41")
    with pytest.raises(databank.SpecRefused, match="a shrink, not a correction"):
        _run(monkeypatch, tmp_path, rows, _held_v1(), _ident())
    refusal = json.loads((tmp_path / "runs.ndjson").read_text().splitlines()[-1])
    assert refusal["status"] == "refused" and "18 held rows absent upstream" in refusal["reason"]


def test_the_second_run_writes_nothing(monkeypatch, tmp_path):
    rows, _ = emit("AIR_41", "NUTRITION_WH_3", "WHS4_154")
    report, log = _run(monkeypatch, tmp_path, rows, _held_gho(rows), _ident())
    assert log["inserts"] == [] and log["closed"] == []
    assert report["notes"]["identity_already_held"] == len(rows) == 44
    assert not any(k.startswith("absent_upstream") for k in report["notes"])


def test_a_revised_value_supersedes_that_row_alone(monkeypatch, tmp_path):
    held, _ = emit("NUTSTUNTINGNUM")
    fresh = [t_health({**rec, "NumericValue": 26.1} if rec["Dim1"] == "SEX_FMLE" else rec,
                      SPEC, {}, Counter())[0] for rec in recs("NUTSTUNTINGNUM")]
    report, log = _run(monkeypatch, tmp_path, fresh, _held_gho(held), _ident())
    assert report["notes"]["revisions"] == 1 and report["notes"]["identity_already_held"] == 2
    assert log["closed"] == [900001]                         # the girls' row, and only it
    assert [(p["indicator"], p["value_num"]) for p in log["inserts"]] == [
        ("health.nutstuntingnum.sex_fmle", 26.1)]


def test_who_republishing_the_same_numbers_rewrites_nothing(monkeypatch, tmp_path):
    held, _ = emit("AIR_41")
    later = [t_health({**rec, "Date": "2027-03-01T10:00:00+01:00"}, SPEC, {}, Counter())[0]
             for rec in recs("AIR_41")]
    report, log = _run(monkeypatch, tmp_path, later, _held_gho(held), _ident())
    assert log["inserts"] == [] and log["closed"] == []
    assert report["notes"]["identity_already_held"] == 18


def test_a_row_who_withdraws_is_closed_and_a_mass_withdrawal_is_refused(monkeypatch, tmp_path):
    held, _ = emit("NUTRITION_WH_3")                         # 22 rows held
    report, log = _run(monkeypatch, tmp_path, held[1:], _held_gho(held), _ident())
    assert log["closed"] == [900000] and log["inserts"] == []
    assert report["absent_upstream"]["closed"] == 1
    # the default ceiling is 5 % of the rows held: more than that is a shrink
    with pytest.raises(databank.SpecRefused, match="a shrink, not a correction"):
        _run(monkeypatch, tmp_path, held[5:], _held_gho(held), _ident())
