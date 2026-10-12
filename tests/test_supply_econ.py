"""The `economic` category's two supply lines, taken off v1 on 2026-10-12:
the World Bank (ops/fetch_worldbank.py) and the IMF (ops/fetch_imf.py).

Everything here is offline. The parsers run on real answers saved under
tests/fixtures/supply_econ/ (captured 2026-10-12 from api.worldbank.org and
the IMF DataMapper API; the IMF answers are cut from 229 economies to three),
and the equivalence runs on the corpus the store's rows came from,
data/frozen/economic.json.gz (v1's unified file of 2026-10-12). No network,
no database.
"""
from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingest import databank
from ingest.databank import content_of, identity_key_for, load_spec, slug
from ops import fetch_imf as fi
from ops import fetch_worldbank as fw
from ops import fetchlib as fl
from ops.load_registry import classify

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "supply_econ"
PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2},
          "governorate": {"Jerusalem": 11}, "pcode": {}}
URBAN = "SP.URB.TOTL.IN.ZS"


def fx(name):
    return json.loads((FX / name).read_text())


@pytest.fixture(scope="module")
def frozen():
    recs = json.loads(gzip.decompress(
        (ROOT / "data" / "frozen" / "economic.json.gz").read_bytes()))["data"]
    by = defaultdict(list)
    for r in recs:
        by[r["sources"][0]["name"]].append(r)
    return by


@pytest.fixture(scope="module")
def spec():
    return load_spec("economic")


def said(row, spec):
    """(identity key, content) exactly as the loader computes them."""
    ident = identity_key_for(spec["identity"], row.dataset_key, indicator=row.indicator,
                             occurred_at=row.occurred_at, place_id=row.place_id,
                             value_num=row.value_num, attrs=row.attrs)
    return ident, content_of(value_num=row.value_num, value_text=row.value_text,
                             unit=row.unit, place_id=row.place_id, attrs=row.attrs)


# the two held series that are not in World Development Indicators (database 2)
OTHER_DATABASES = {"SE.TER.GRAD.FE.SI.ZS": "14", "SH.STA.OWAD.ZS": "16"}
PROBES = ["SP.POP.TOTL", "SE.TER.GRAD.FE.SI.ZS", "SH.STA.OWAD.ZS"]
VINTAGES = {"SP.POP.TOTL": "2026-10-08", "SE.TER.GRAD.FE.SI.ZS": "2026-07-22",
            "SH.STA.OWAD.ZS": "2026-07-01"}


def wb_rows(recs):
    """Held records of one code → the rows the World Bank API would answer."""
    return [{"indicator": {"id": r["indicator_code"], "value": "the Bank's own name"},
             "country": {"id": "PS", "value": "West Bank and Gaza"},
             "countryiso3code": "PSE", "date": r["date"][:4],
             "value": r["metrics"]["value"], "unit": "", "obs_status": "", "decimal": 0}
            for r in recs]


# ── the spec ─────────────────────────────────────────────────────────────────

def test_the_spec_reads_the_two_fetches_and_keeps_the_frozen_corpus_behind(spec):
    assert spec["transform"] == "python:t_economic"
    assert spec["input"]["root"] == "data/raw"
    assert spec["input"]["glob"] == ["worldbank/indicators.json", "imf/indicators.json"]
    assert spec["input"]["fallback"] == {"root": "data/frozen", "glob": "economic.json.gz"}
    for out in (fw.OUT, fi.OUT):
        assert str(out.relative_to(ROOT / "data" / "raw")) in spec["input"]["glob"]
    assert spec["identity"] == {"fields": ["indicator", "occurred_at", "place_id"]}
    assert [d["key"] for d in spec["datasets"]] == ["v1_economic_worldbank", "v1_economic_imf"]
    manifest = json.loads((ROOT / "data" / "frozen" / "manifest.json").read_text())["economic"]
    assert manifest["file"] == "economic.json.gz" and manifest["records"] == 4157


def test_the_radar_judges_both_lines_on_the_labels_the_fetchers_write(spec):
    """A line the radar does not know cannot fail the night: if the nightly
    never ran these fetchers the loader would read the frozen fallback in
    silence. Registered, a fetcher that is not run is `dead: never fetched`."""
    from ops import gap_radar as gr
    wb, imf = gr.SUPPLY_LINES["worldbank"], gr.SUPPLY_LINES["imf"]
    assert wb["labels"] == [fw.LABEL] and imf["labels"] == [fi.LABEL]
    assert wb["feeds"] + imf["feeds"] == [d["key"] for d in spec["datasets"]]
    assert (ROOT / wb["fetcher"]).exists() and (ROOT / imf["fetcher"]).exists()
    # the v1 steps they replace are excused only because a successor carries them
    assert {wb["replaces"], imf["replaces"]} <= set(gr.RETIRED_V1_STEPS)


def test_the_held_lists_are_exactly_what_the_frozen_corpus_holds(frozen):
    """No indicator is added and none is dropped by the move: the fetchers ask
    for the codes the store holds, under the label and unit it holds them."""
    wb, imf = frozen["World Bank"], frozen["IMF"]
    assert (len(wb), len(imf)) == (3541, 474)
    held = defaultdict(set)
    for r in wb:
        held[r["indicator_code"]].add((r["indicator_name"], r["metrics"]["unit"]))
    assert all(len(v) == 1 for v in held.values())
    assert {c: next(iter(v)) for c, v in held.items()} == fw.SERIES
    assert len(fw.SERIES) == 125
    assert {r["indicator_code"] for r in imf} == set(fi.CODES) and len(fi.CODES) == 18
    assert fw.PROBE_CODE in fw.SERIES


# ── the World Bank's answers ─────────────────────────────────────────────────

def test_a_world_bank_answer_becomes_the_records_t_economic_reads(spec):
    head, rows = fw.parse_answer(fx(f"wb_data_{URBAN}.json"))
    assert head["lastupdated"] == "2026-10-08" and head["pages"] == 1 and len(rows) == 66
    recs = fw.records_for(URBAN, rows)
    assert len(recs) == 66 and [r["date"] for r in recs] == sorted(r["date"] for r in recs)
    first = recs[0]
    assert first == {
        "stable_id": "wb:PSE:SP.URB.TOTL.IN.ZS:1960", "date": "1960-01-01",
        "category": "economic", "event_type": "indicator_measurement",
        "location": {"name": "West Bank and Gaza", "region": "Palestine", "precision": "region"},
        "metrics": {"value": 44.1830150432117, "unit": "percentage"},
        "indicator_code": URBAN,
        # the label held rows carry, NOT the name in tonight's answer
        "indicator_name": "Urban population (% of total)",
        "sources": [{"name": "World Bank", "organization": "World Bank",
                     "url": "https://api.worldbank.org/v2/country/PSE/indicator/SP.URB.TOTL.IN.ZS",
                     "license": "CC-BY-4.0"}]}
    assert fw.name_in_answer(rows) == "Urban population (% of total population)"
    databank._economic_prepass(recs, spec, Counter())
    [row] = databank.t_economic(first, spec, PLACES, Counter())
    assert (row.dataset_key, row.indicator, row.occurred_at, row.precision, row.unit,
            row.place_id, row.v1_stable_id) == \
        ("v1_economic_worldbank", "economic.sp_urb_totl_in_zs", "1960-01-01", "year",
         "percentage", None, "wb:PSE:SP.URB.TOTL.IN.ZS:1960")
    assert row.attrs == {"indicator_code": URBAN, "indicator_name": "Urban population (% of total)",
                         "region": "Palestine", "name": "West Bank and Gaza"}
    assert said(row, spec)[0] == "v1_economic_worldbank|economic.sp_urb_totl_in_zs|1960-01-01|"


def test_a_year_with_no_value_is_not_a_point_and_a_quarter_is_not_a_year():
    rows = [{"date": "2024", "value": None}, {"date": "2023", "value": 0},
            {"date": "2022Q1", "value": 5}, {"date": "2021", "value": 1.5}, {"date": None, "value": 2}]
    assert fw.points(rows) == [(2021, 1.5), (2023, 0)]
    # the API's answer for a series with nothing in the range: a header and null
    assert fw.parse_answer([{"page": 0, "pages": 0, "total": 0, "lastupdated": None}, None]) == \
        ({"page": 0, "pages": 0, "total": 0, "lastupdated": None}, [])


def test_an_archived_code_is_gone_not_empty():
    with pytest.raises(fw.Gone, match="deleted or archived"):
        fw.parse_answer(fx("wb_gone_EN.ATM.CO2E.PC.json"))
    with pytest.raises(ValueError):
        fw.parse_answer({"not": "a list"})


def test_the_banks_own_names_are_kept_in_both_languages():
    en, ar = fx(f"wb_name_en_{URBAN}.json"), fx(f"wb_name_ar_{URBAN}.json")
    names = fw.parse_names(en, ar)
    assert names["indicator_name"] == "Urban population (% of total population)"
    assert names["indicator_name_ar"] == "سكان المناطق الحضرية (% من إجمالي عدد السكان)"
    assert names["unit"] is None                       # the Bank states none: "" in the answer
    assert names["source_note"].startswith("Urban population refers to people living in urban areas")
    assert (names["database"], names["database_id"]) == ("World Development Indicators", "2")
    # where the Bank has no translation the Arabic endpoint answers in English
    assert fw.parse_names(en, en)["indicator_name_ar"] is None


def test_every_held_world_bank_row_is_reproduced_with_its_identity_and_content(frozen, spec):
    """The proof the move rests on, without a network: give the fetcher the
    values the store holds and every row it builds is the row the store holds
    (same identity key, same value, unit, place and attrs), so the loader
    counts it `identity_already_held` and writes nothing."""
    by_code = defaultdict(list)
    for r in frozen["World Bank"]:
        by_code[r["indicator_code"]].append(r)
    databank._economic_prepass(frozen["World Bank"], spec, Counter())
    held, built = {}, {}
    for code, recs in by_code.items():
        for r in recs:
            [row] = databank.t_economic(r, spec, PLACES, Counter())
            k, c = said(row, spec)
            held[k] = c
        for r in fw.records_for(code, wb_rows(recs)):
            [row] = databank.t_economic(r, spec, PLACES, Counter())
            k, c = said(row, spec)
            assert k not in built, f"identity not injective: {k}"
            built[k] = c
    assert len(held) == len(built) == 3541
    assert built == held


# ── the IMF's answers ────────────────────────────────────────────────────────

def test_the_imf_answers_with_every_economy_and_only_wbg_is_kept():
    answer = fx("imf_NGDPDPC_WBG.json")
    assert set(answer["values"]["NGDPDPC"]) == {"SDN", "USA", "WBG"}
    series = fi.series_of(answer, "NGDPDPC")
    assert (min(series), max(series), len(series)) == (1994, 2024, 31)
    assert series[2024] == 2853.301
    assert fi.series_of({"values": {}}, "NGDPDPC") == {} == fi.series_of({}, "NGDPDPC")


def test_an_imf_record_carries_the_imfs_unit_and_its_label_as_written(spec):
    listing = fx("imf_indicators_cut.json")["indicators"]
    meta = listing["NGDPDPC"]
    recs, later = fi.records_for("NGDPDPC", meta, fi.series_of(fx("imf_NGDPDPC_WBG.json"), "NGDPDPC"), 2026)
    assert len(recs) == 31 and later == []
    assert recs[-1] == {
        "stable_id": "imf:WBG:NGDPDPC:2024", "date": "2024-01-01", "category": "economic",
        "event_type": "indicator_measurement",
        "location": {"name": "Palestine", "region": "Palestine", "precision": "region"},
        "metrics": {"value": 2853.301, "unit": "U.S. dollars per capita"},
        "indicator_code": "NGDPDPC",
        "indicator_name": "GDP per capita, current prices\n",      # as the API writes it
        # no licence claim on the record: v1's "CC-BY-4.0" is not the IMF's terms
        "sources": [{"name": "IMF", "organization": "International Monetary Fund",
                     "url": "https://www.imf.org/external/datamapper/api/v1/NGDPDPC/WBG"}]}
    assert fi.clean(meta["label"]) == "GDP per capita, current prices"   # for the registry
    [row] = databank.t_economic(recs[-1], spec, PLACES, Counter())
    assert (row.dataset_key, row.indicator, row.unit, row.value_num) == \
        ("v1_economic_imf", "economic.ngdpdpc", "U.S. dollars per capita", 2853.301)


def test_a_year_after_this_one_is_a_projection_and_is_not_kept():
    listing = fx("imf_indicators_cut.json")["indicators"]
    series = fi.series_of(fx("imf_LP_WBG.json"), "LP")
    assert max(series) == 2025
    recs, later = fi.records_for("LP", listing["LP"], series, 2026)
    assert len(recs) == 33 and later == []
    recs, later = fi.records_for("LP", listing["LP"], series, 2023)
    assert [r["date"][:4] for r in recs][-1] == "2023" and later == [2024, 2025]


def test_v1s_placeholder_unit_stays_null_and_a_real_unit_is_carried(frozen, spec):
    held = frozen["IMF"][0]
    assert held["metrics"]["unit"] == "number"
    [row] = databank.t_economic(held, spec, PLACES, Counter())
    assert row.unit is None
    fresh = json.loads(json.dumps(held))
    fresh["metrics"]["unit"] = "Percent of GDP"
    [row] = databank.t_economic(fresh, spec, PLACES, Counter())
    assert row.unit == "Percent of GDP"
    # 'number' is a real unit token on 27 World Bank series and stays one
    wb = next(r for r in frozen["World Bank"] if r["metrics"]["unit"] == "number")
    [row] = databank.t_economic(wb, spec, PLACES, Counter())
    assert row.unit == "number"


def test_every_held_imf_row_keeps_its_identity_and_changes_in_its_unit_only(frozen, spec):
    """474 held rows, 474 revisions, and the unit is the whole of each one."""
    listing = fx("imf_indicators_cut.json")["indicators"]
    by_code = defaultdict(list)
    for r in frozen["IMF"]:
        by_code[r["indicator_code"]].append(r)
    held, built = {}, {}
    for code, recs in by_code.items():
        for r in recs:
            [row] = databank.t_economic(r, spec, PLACES, Counter())
            k, c = said(row, spec)
            held[k] = json.loads(c)
        series = {int(r["date"][:4]): r["metrics"]["value"] for r in recs}
        mine, later = fi.records_for(code, listing[code], series, 2026)
        assert later == []
        for r in mine:
            [row] = databank.t_economic(r, spec, PLACES, Counter())
            k, c = said(row, spec)
            built[k] = json.loads(c)
    assert len(held) == len(built) == 474 and set(held) == set(built)
    units = Counter()
    for k, h in held.items():
        b = built[k]
        assert h["u"] is None and b["u"] == listing[b["a"]["indicator_code"]]["unit"]
        assert {**b, "u": None} == h, k
        units[b["u"]] += 1
    assert sum(units.values()) == 474 and len(units) == 11
    assert units["Percent of GDP"] == 96 and units["Billions of U.S. dollars"] == 62


def test_the_registry_still_gives_every_imf_series_a_rule_under_its_new_unit(spec):
    """A unit the rules have never seen must not leave an indicator without a
    rule: that fails the night (registry.max_unclassified: 0)."""
    listing = fx("imf_indicators_cut.json")["indicators"]
    pairs = [(f"economic.{slug(c)}", listing[c]["unit"], 10) for c in fi.CODES]
    got, _conflicts = classify(pairs, spec["registry"]["rules"])
    assert set(got) == {p[0] for p in pairs}
    assert all(m["concept"] for m in got.values())


# ── a night's run, with the network replaced by the held values ──────────────

@pytest.fixture()
def offline(monkeypatch, tmp_path, frozen):
    """Both fetchers pointed at a temp tree, the APIs answering with exactly
    what the store holds."""
    monkeypatch.setattr(fl, "EVENTS", tmp_path / "fetch-events.ndjson")
    monkeypatch.setattr(fw, "OUT", tmp_path / "raw" / "worldbank" / "indicators.json")
    monkeypatch.setattr(fi, "OUT", tmp_path / "raw" / "imf" / "indicators.json")
    monkeypatch.setattr(fl, "ROOT", tmp_path)
    monkeypatch.setattr(fw.time, "sleep", lambda s: None)
    wb = defaultdict(list)
    for r in frozen["World Bank"]:
        wb[r["indicator_code"]].append(r)
    imf = defaultdict(dict)
    for r in frozen["IMF"]:
        imf[r["indicator_code"]][r["date"][:4]] = r["metrics"]["value"]
    # three World Bank databases, as measured on 2026-10-12
    state = {"vintage": {"2": "2026-10-08", "14": "2026-07-22", "16": "2026-07-01"},
             "broken": set(), "gone": set(), "asked": [],
             "listing": fx("imf_indicators_cut.json")["indicators"]}

    def fetch_series(code, last_year):
        state["asked"].append(code)
        if code in state["broken"]:
            raise TimeoutError("The read operation timed out")
        if code in state["gone"]:
            raise fw.Gone("The indicator was not found. It may have been deleted or archived.")
        db = OTHER_DATABASES.get(code, "2")
        return ({"page": 1, "pages": 1, "sourceid": db, "lastupdated": state["vintage"][db]},
                wb_rows(wb[code]))

    def fetch_names(code):
        return {"indicator_name": "the Bank's own name", "indicator_name_ar": "اسم المؤشر",
                "unit": None, "source_note": "a note", "source_organization": "an office",
                "database": "World Development Indicators", "database_id": "2"}

    def imf_get_json(url, *a, **k):
        if url.endswith("/indicators"):
            return {"indicators": state["listing"]}
        code = url.split("/")[-2]
        state["asked"].append(code)
        return {"values": {code: {"USA": {"2031": 1.0}, "WBG": imf[code]}}}

    monkeypatch.setattr(fw, "fetch_series", fetch_series)
    monkeypatch.setattr(fw, "fetch_names", fetch_names)
    monkeypatch.setattr(fi, "get_json", imf_get_json)
    return state


def ledger():
    return [json.loads(line) for line in fl.EVENTS.read_text().splitlines()]


def test_a_world_bank_night_writes_once_and_then_stands_until_the_vintage_moves(offline):
    assert fw.main([]) == 0
    doc = json.loads(fw.OUT.read_text())
    meta = doc["metadata"]
    assert len(doc["data"]) == 3541 and meta["series_answered"] == 125
    assert meta["vintage"] == "2026-10-08"
    assert meta["vintages_seen"] == ["2026-07-01", "2026-07-22", "2026-10-08"]
    assert {db: (d["lastupdated"], d["series"]) for db, d in meta["databases"].items()} == \
        {"2": ("2026-10-08", 123), "14": ("2026-07-22", 1), "16": ("2026-07-01", 1)}
    assert "lastupdated" in meta["vintage_basis"] and meta["vintage_url"].startswith("https://api.worldbank.org/")
    one = meta["indicators"]["SP.POP.TOTL"]
    assert (one["indicator_name"], one["indicator_name_ar"], one["held_label"], one["held_unit"]) == \
        ("the Bank's own name", "اسم المؤشر", "Population, total", "number")
    assert one["lastupdated"] == "2026-10-08" and one["last_year"] == 2025
    assert ledger()[-1]["outcome"] == "ok" and ledger()[-1]["rows"] == 3541
    assert len(offline["asked"]) == 125                 # the probe's answer is not asked twice

    written = fw.OUT.read_bytes()
    offline["asked"].clear()
    assert fw.main([]) == 0                            # the next night, the same vintages
    assert offline["asked"] == PROBES                  # one series per database, no more
    assert fw.OUT.read_bytes() == written
    assert ledger()[-1] == {**ledger()[-1], "outcome": "ok", "rows": 3541, "unchanged": True}

    offline["vintage"]["2"] = "2026-12-17"             # the Bank updates WDI
    offline["asked"].clear()
    assert fw.main([]) == 0
    assert len(offline["asked"]) == 125
    assert json.loads(fw.OUT.read_text())["metadata"]["vintage"] == "2026-12-17"

    offline["vintage"]["14"] = "2027-01-20"            # ... or only the small database moves
    offline["asked"].clear()
    assert fw.main([]) == 0
    assert len(offline["asked"]) == 125
    one = json.loads(fw.OUT.read_text())["metadata"]["indicators"]["SE.TER.GRAD.FE.SI.ZS"]
    assert (one["sourceid"], one["lastupdated"]) == ("14", "2027-01-20")


def test_a_missing_series_is_named_and_fails_the_step_but_the_rest_is_written(offline):
    offline["gone"] = {"EG.FEC.RNEW.ZS"}
    assert fw.main([]) == 1
    doc = json.loads(fw.OUT.read_text())
    assert doc["metadata"]["series_gone"] == {
        "EG.FEC.RNEW.ZS": "The indicator was not found. It may have been deleted or archived."}
    assert doc["metadata"]["series_answered"] == 124 and len(doc["data"]) < 3541
    assert ledger()[-1]["outcome"] == "ok" and ledger()[-1]["missing"] == ["EG.FEC.RNEW.ZS"]
    # ... and a read that missed a series is read again the next night
    assert not fw.unchanged(doc, VINTAGES, datetime.now(timezone.utc))


def test_a_bad_night_keeps_the_file_on_disk(offline):
    assert fw.main([]) == 0
    good = fw.OUT.read_bytes()
    offline["vintage"]["2"] = "2026-12-17"
    offline["broken"] = set(list(fw.SERIES)[5:5 + fw.MAX_MISSING + 1])
    offline["asked"].clear()
    assert fw.main([]) == 1
    assert fw.OUT.read_bytes() == good
    assert ledger()[-1]["outcome"] == "refused"
    assert len(offline["asked"]) < 125                 # it stopped asking
    offline["broken"] = {fw.PROBE_CODE}                # the API is not there at all
    assert fw.main([]) == 1
    assert ledger()[-1]["outcome"] == "error" and fw.OUT.read_bytes() == good


def test_a_dry_run_writes_nothing_and_leaves_no_ledger_line(offline, tmp_path):
    assert fw.main(["--dry-run", "--stage", str(tmp_path / "stage")]) == 0
    assert fi.main(["--dry-run", "--stage", str(tmp_path / "stage")]) == 0
    assert not fw.OUT.exists() and not fi.OUT.exists() and not fl.EVENTS.exists()
    assert sorted(p.name for p in (tmp_path / "stage").iterdir()) == \
        ["imf_indicators.json", "worldbank_indicators.json"]


def test_an_imf_night_reads_the_series_only_when_the_imfs_list_has_moved(offline):
    assert fi.main([]) == 0
    doc = json.loads(fi.OUT.read_text())
    meta = doc["metadata"]
    assert len(doc["data"]) == 474 and meta["codes_answered"] == 18
    assert meta["vintage"] == "2026-04-08"
    assert meta["vintage_release"] == "World Economic Outlook (April 2026)"
    assert meta["indicators"]["CG_DEBT_GDP"]["release"] == "Global Debt Database (Sep 2025)"
    assert meta["indicators"]["BCA"]["indicator_name"] == "Current account balance U.S. dollars"
    assert "indicator_name_ar" not in meta["indicators"]["BCA"]      # the IMF publishes none
    assert meta["not_fetched"] == {"indicators_the_imf_lists": 19, "outside_the_held_list": 1}
    assert meta["projection_years_not_kept"] == {}
    assert Counter(r["metrics"]["unit"] for r in doc["data"])["Annual percent change"] == 88
    assert len(offline["asked"]) == 18 and ledger()[-1]["rows"] == 474

    written = fi.OUT.read_bytes()
    offline["asked"].clear()
    assert fi.main([]) == 0                            # the next night, the same list
    assert offline["asked"] == [] and fi.OUT.read_bytes() == written
    assert ledger()[-1]["unchanged"] is True

    moved = json.loads(json.dumps(offline["listing"]))
    moved["NGDPD"]["last-modified"] = "2026-10-14 09:00:00"         # the October WEO
    moved["NGDPD"]["source"] = "World Economic Outlook (October 2026)"
    offline["listing"] = moved
    assert fi.main([]) == 0
    assert len(offline["asked"]) == 18
    assert "October 2026" in json.loads(fi.OUT.read_text())["metadata"]["vintage_release"]


def test_an_old_read_is_read_again_however_quiet_the_publisher(offline):
    assert fw.main([]) == 0 and fi.main([]) == 0
    wb, imf = json.loads(fw.OUT.read_text()), json.loads(fi.OUT.read_text())
    now = datetime.now(timezone.utc)
    assert fw.probe_codes(None) == ["SP.POP.TOTL"] and fw.probe_codes(wb) == PROBES
    assert fw.unchanged(wb, VINTAGES, now) and fi.unchanged(imf, offline["listing"], now)
    assert not fw.unchanged(wb, VINTAGES, now + timedelta(days=fw.FULL_EVERY_DAYS + 1))
    assert not fi.unchanged(imf, offline["listing"], now + timedelta(days=fi.FULL_EVERY_DAYS + 1))
    assert not fw.unchanged(None, VINTAGES, now) and not fw.unchanged(wb, {}, now)
    # a probe that did not cover every database decides nothing
    assert not fw.unchanged(wb, {"SP.POP.TOTL": "2026-10-08"}, now)
    assert not fw.unchanged(wb, {**VINTAGES, "SH.STA.OWAD.ZS": "2026-11-02"}, now)
    # a read taken while the API still served one series from before an update
    # is mixed, and is read again
    mixed = json.loads(json.dumps(wb))
    mixed["metadata"]["indicators"]["NY.GDP.MKTP.CD"]["lastupdated"] = "2026-07-01"
    assert not fw.unchanged(mixed, VINTAGES, now)
    assert not fi.unchanged(None, offline["listing"], now)


def test_an_imf_code_that_stops_answering_is_named_and_the_rest_is_written(offline):
    listing = dict(offline["listing"])
    del listing["GRB_dummy"]
    offline["listing"] = listing
    assert fi.main([]) == 1
    meta = json.loads(fi.OUT.read_text())["metadata"]
    assert meta["codes_failed"] == {"GRB_dummy": "no longer in the IMF's indicator list"}
    assert meta["records"] == 472 and ledger()[-1]["missing"] == ["GRB_dummy"]
