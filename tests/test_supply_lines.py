"""P1-B.3 — the four v1 supply lines v2 took over, and the radar that fails
the night when a line dies.

Everything here is offline: the parsers run on real answers saved under
tests/fixtures/supply_lines/ (captured 2026-09-25 from OCHA's Power BI API,
hamoked.org, the Wayback CDX API and pcbs.gov.ps), and the radar's failure
path runs on fake ledgers and fake datasets. No network, no database.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingest import databank
from ingest.databank import Drop, load_spec
from ops import fetch_hamoked as hm
from ops import fetch_ocha as oc
from ops import fetch_pcbs as pc
from ops import fetchlib as fl
from ops import gap_radar as gr
from ops import pbi_public as pb

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "supply_lines"
PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2},
          "governorate": {"Jerusalem": 11, "Qalqilya": 7, "Hebron": 13,
                          "Jenin": 3},
          "pcode": {}}
NOW = datetime(2026, 9, 26, 4, 0, tzinfo=timezone.utc)


def fx(name):
    return json.loads((FX / name).read_text())


def rows_of(name, ncols=7):
    return pb.parse_querydata(fx(name), [f"c{i}" for i in range(ncols)])["rows"]


# ── the Power BI envelope ────────────────────────────────────────────────────

def test_resource_key_and_cluster_come_from_the_embed_itself():
    assert pb.resource_key(oc.CASUALTIES_EMBED) == "60eca1ef-5852-4807-9bc3-4fdb8915c71c"
    assert pb.resource_key(oc.DEMOLITIONS_EMBED) == "aae77805-0842-43a2-9d2e-aa21d43557e6"
    html = "var resolvedClusterUri = 'https://wabi-north-europe-j-primary-redirect.analysis.windows.net/';"
    assert pb.cluster_from_embed_html(html) == \
        "https://wabi-north-europe-j-primary-api.analysis.windows.net"
    assert pb.cluster_from_embed_html("<html></html>") is None


def test_plain_rows_decode_to_the_published_annual_series():
    rows = rows_of("pbi_casualties_year.json", 3)
    assert len(rows) == 19 and rows[0][:2] == [2008, 877] and rows[-1][0] == 2026
    assert sum(r[1] for r in rows) == 7494          # the report's own total


def test_value_dictionaries_and_repeat_bits_are_undone():
    # a real slice of the demolitions map: names/coordinates are dictionary
    # indices (ValueDicts D0–D3) and the governorate column is a repeat bit
    rows = rows_of("pbi_demolitions_locality_slice.json")
    assert rows[0] == ["31.351063", "34.92792", "Tatrit", "Hebron", 20, 15, 1722297600000]
    assert rows[1][2:4] == ["Arab al Fureijat", "Hebron"]     # R=8 → Hebron repeated
    assert all(isinstance(r[2], str) for r in rows[:6])


def test_a_null_bit_is_a_null_and_an_ungrouped_aggregate_is_keyed_by_name():
    ds = {"PH": [{"DM0": [
        {"S": [{"N": "G0", "T": 1}, {"N": "M0", "T": 4}], "C": ["a", 1]},
        {"C": ["b"], "Ø": 2},                       # M0 null
        {"C": [5], "R": 1}]}], "IC": True}           # G0 repeated
    assert pb.decode_dsr(ds) == [["a", 1], ["b", None], ["b", 5]]
    assert rows_of("pbi_casualties_maxdate.json", 1) == [[1789862400000]]
    assert oc._day(1789862400000) == "2026-09-20"


def test_a_truncated_or_refused_answer_is_refused_not_read_short():
    d = fx("pbi_casualties_year.json")
    d["results"][0]["result"]["data"]["dsr"]["DS"][0]["IC"] = False
    with pytest.raises(pb.PbiError, match="incomplete"):
        pb.parse_querydata(d, ["a", "b", "c"])
    bad = {"results": [{"result": {"data": {"dsr": {"DataShapes": [
        {"odata.error": {"code": "InvalidOrMalformedSemanticQueryDefinition"}}]}}}}]}
    with pytest.raises(pb.PbiError, match="data shape"):
        pb.parse_querydata(bad, ["a"])


# ── OCHA casualties + demolitions ────────────────────────────────────────────

def _cas_slices():
    return {"annual_total": rows_of("pbi_casualties_year.json", 3),
            "region": rows_of("pbi_casualties_region.json", 3),
            "governorate": [["Jenin", 486, 1789862400000], ["Qalqiliya", 51, 1700000000000],
                            ["Gaza", 6957, 1695081600000]],
            "demographic": [["Men", 7494, 1789862400000]],
            "weapon": rows_of("pbi_casualties_weapon.json", 3)}


def test_casualty_records_keep_the_frozen_shape_and_state_their_own_span():
    recs, summary = oc.casualty_records(_cas_slices(), "2026-09-26T03:45:00+00:00")
    assert summary["data_through"] == "2026-09-20"
    assert summary["slice_totals"] == {k: 7494 for k in oc.CAS_SLICES}
    oc.check_casualty_slices(summary["slice_totals"])          # agrees: no raise
    by = {r["stable_id"]: r for r in recs}
    assert len(by) == len(recs), "stable ids must be unique"
    y26 = by["ocha-cas:annual_total:2026"]
    assert y26["partial_year"] is True and y26["date"] == "2026-12-31"
    assert by["ocha-cas:annual_total:2025"]["partial_year"] is False
    wb = by["ocha-cas:region:west-bank"]
    assert wb["location"]["region"] == "West Bank" and wb["coverage_end"] == "2026-09-20"
    assert by["ocha-cas:region:not-listed"]["location"]["region"] == "Palestine"
    assert by["ocha-cas:weapon:airstrikes-including-drones"][
        "casualty_breakdown_label"] == "Airstrikes (including drones)"   # trimmed
    # and the reviewed spec's transformer reads them unchanged
    spec = load_spec("casualties")
    [row] = databank.t_casualties(y26, spec, PLACES, Counter())
    assert (row.indicator, row.occurred_at, row.precision, row.value_num) == \
        ("casualties.annual_total", "2026-01-01", "year", 90)
    assert row.attrs["partial_year"] is True
    [row] = databank.t_casualties(by["ocha-cas:governorate:qalqiliya"], spec, PLACES, Counter())
    assert row.place_id == 7 and row.attrs["coverage_end"] == "2023-11-14"
    assert row.occurred_at == "2008-01-01" and row.precision == "unknown"


def test_slices_that_disagree_refuse_the_fetch():
    with pytest.raises(fl.FetchRefused, match="disagree"):
        oc.check_casualty_slices({"annual_total": 7494, "region": 7494,
                                  "governorate": 6000, "demographic": 7494,
                                  "weapon": 7494})


def test_demolition_records_follow_v1s_region_rule_and_survive_a_missing_point():
    loc = [["31.754483", "35.246059", "Jabal al Mukabbir", "Jerusalem", 416, 1080, 1780000000000],
           ["Na", "Na", "Al Malha", "Bethlehem", 11, 0, 1600000000000],
           ["32.1", "35.3", "Khirbet Tana", "Nablus", 400, 685, 1790121600000]]
    ann = [[2025, 1660, 2113, 69661, 1767052800000], [2026, 1311, 1734, 31594, 1790121600000]]
    recs, summary = oc.demolition_records(loc, ann, "2026-09-26T03:45:00+00:00")
    assert summary["data_through"] == "2026-09-23"
    assert (summary["localities"], summary["years"]) == (3, 2)
    by = {r["stable_id"]: r for r in recs}
    jm = by["ocha-dem:locality:jabal-al-mukabbir:jerusalem"]
    assert jm["location"]["region"] == "East Jerusalem"
    assert by["ocha-dem:locality:al-malha:bethlehem"]["location"]["lat"] is None
    assert by["ocha-dem:annual_total:2026"]["partial_year"] is True
    spec = load_spec("demolitions")
    rows = databank.t_demolitions(jm, spec, PLACES, Counter())
    assert [r.indicator for r in rows] == ["demolitions.locality.structures",
                                           "demolitions.locality.displaced"]
    assert rows[0].place_id == 11 and rows[0].attrs["region"] == "East Jerusalem"
    assert rows[0].attrs["locality_name"] == "Jabal al Mukabbir"
    assert rows[0].attrs["coverage_end"] == oc._day(1780000000000)
    rows = databank.t_demolitions(by["ocha-dem:annual_total:2025"], spec, PLACES, Counter())
    assert {r.indicator: r.value_num for r in rows} == {
        "demolitions.annual_total.structures": 1660,
        "demolitions.annual_total.displaced": 2113,
        "demolitions.annual_total.affected": 69661}
    assert "partial_year" not in rows[0].attrs


def test_a_frozen_record_still_transforms_exactly_as_it_was_stored():
    """The fallback corpus carries no span; the transformers keep the frozen
    day for it, so a fresh clone's reload reproduces the held rows (measured:
    49/49 and 904/904 already held)."""
    rec = {"stable_id": "x", "casualty_dimension": "region",
           "casualty_breakdown_label": "West Bank", "date": None,
           "location": {"region": "West Bank"}, "metrics": {"killed": 2105},
           "sources": [{"name": "UN OCHA oPt — Data on Casualties"}]}
    [row] = databank.t_casualties(rec, load_spec("casualties"), PLACES, Counter())
    assert row.attrs["coverage_end"] == databank.FROZEN_COVERAGE_END == "2026-08-05"
    rec = dict(rec, casualty_dimension="annual_total", casualty_breakdown_label=None,
               date="2026-12-31")
    [row] = databank.t_casualties(rec, load_spec("casualties"), PLACES, Counter())
    assert row.attrs["partial_year"] is True


# ── HaMoked ──────────────────────────────────────────────────────────────────

def test_pillars_parse_and_a_malformed_month_is_skipped():
    months = hm.parse_pillars((FX / "hamoked_pillars.html").read_text())
    assert len(months) == 4                          # the month=13 pillar is out
    first = months[0]
    assert (first["year"], first["month"], first["sentenced"], first["remand"],
            first["administrative"]) == (2008, 5, 5689, 2588, 803)


def test_the_total_is_the_sum_of_all_four_figures_or_nothing():
    months = [{"year": 2026, "month": 6, "sentenced": 1335, "remand": 3386,
               "administrative": 3324, "unlawful_combatants": 1316},
              {"year": 2026, "month": 7, "sentenced": 1421, "remand": 3314,
               "administrative": 3244, "unlawful_combatants": None}]
    recs = hm.month_records(months, "direct", "t")
    tot = {r["date"]: r["metrics"]["count"] for r in recs
           if r["prisoner_metric_type"] == "total"}
    assert tot == {"2026-06-01": 9361}              # = the held June row, exactly
    assert sum(1 for r in recs if r["date"] == "2026-07-01") == 3
    spec = load_spec("prisoners_hamoked")
    [row] = databank.t_prisoners(recs[0], spec, PLACES, Counter())
    assert row.dataset_key == "v1_prisoners_hamoked"   # the held series, continued
    assert row.attrs == {"prisoner_metric_type": "sentenced", "name": "Palestine",
                         "region": "Palestine", "reference": "period-end stock"}


def test_the_second_door_is_the_newest_archived_capture():
    assert hm.latest_capture(fx("wayback_cdx.json")) == "20260824000411"
    assert hm.latest_capture([["timestamp", "statuscode"]]) is None
    page = (FX / "hamoked_pillars.html").read_bytes()

    def blocked_then_archived(url, ua, timeout=60):
        if url == hm.PAGE:
            import urllib.error
            raise urllib.error.HTTPError(url, 403, "blocked", None, None)
        if url == hm.CDX:
            return json.dumps(fx("wayback_cdx.json")).encode()
        assert url == hm.WAYBACK.format(ts="20260824000411")
        return page
    html, via, raw, url = hm.fetch(get=blocked_then_archived)
    assert via == "wayback:20260824000411" and raw == page

    def everything_down(url, ua, timeout=60):
        raise OSError("down")
    with pytest.raises(OSError, match="direct: OSError; wayback"):
        hm.fetch(get=everything_down)


# ── PCBS ─────────────────────────────────────────────────────────────────────

def test_the_population_workbook_parses_by_header_name():
    pop = pc.parse_population(pc.xlsx_rows((FX / "pcbs_population.xlsx").read_bytes()))
    assert len(pop) == 30 and {r["region"] for r in pop} == {"West Bank", "Gaza Strip", "Palestine"}
    v = {(r["year"], r["region"]): r["value"] for r in pop}
    assert v[(2017, "West Bank")] == 2856691 and v[(2026, "Palestine")] == 5876648
    assert pc.population_url('<a href="/media/ab12/projected-population-in-the-palestine.xlsx">') \
        == "https://www.pcbs.gov.ps/media/ab12/projected-population-in-the-palestine.xlsx"
    assert pc.population_url("<html/>") == pc.POPULATION_FALLBACK


def test_the_cpi_request_is_built_from_the_apps_own_callback():
    req = pc.cpi_request(fx("pcbs_dash_layout.json"), fx("pcbs_dash_dependencies.json"))
    vals = {i["id"]: i["value"] for i in req["inputs"]}
    assert vals["frequency"] == "yearly" and vals["time_window"] == "all"
    assert vals["overall_base_year"] == 2018
    assert set(vals["regions"]) == set(pc.REGIONS)
    deps = fx("pcbs_dash_dependencies.json")
    deps[0]["inputs"].append({"id": "a_new_knob", "property": "value"})
    with pytest.raises(ValueError, match="a_new_knob"):
        pc.cpi_request(fx("pcbs_dash_layout.json"), deps)


def test_cpi_rows_map_jerusalem_j1_to_east_jerusalem_and_a_rebase_is_refused():
    cpi = pc.parse_cpi(fx("pcbs_cpi_answer.json"))
    v = {(r["year"], r["region"]): r["value"] for r in cpi}
    assert v[(2024, "West Bank")] == 113.96 and v[(2024, "East Jerusalem")] == 117.78
    assert v[(1996, "Palestine")] == 49.58
    rebased = fx("pcbs_cpi_answer.json")
    rebased["response"]["overall_table"]["data"][0]["Base Year"] = 2010
    with pytest.raises(ValueError, match="rebased"):
        pc.parse_cpi(rebased)
    recs = pc.records([], cpi, "t")
    spec = load_spec("economic_pcbs")
    databank._economic_prepass(recs, spec, Counter())
    ej = next(r for r in recs if r["location"]["region"] == "East Jerusalem"
              and r["date"].startswith("2024"))
    [row] = databank.t_economic(ej, spec, PLACES, Counter())
    assert (row.dataset_key, row.indicator, row.place_id, row.value_num, row.unit) == \
        ("v1_economic_pcbs_direct", "economic.pcbs_cpi", 11, 117.78, "index")
    assert row.attrs == {"indicator_code": "pcbs_cpi", "indicator_name": "Consumer Price Index",
                         "region": "East Jerusalem", "name": "East Jerusalem"}


def test_pcbs_verification_stays_on_with_the_missing_intermediate_added():
    """PCBS serves the wrong intermediate; the right one is ADDED to the
    trust store — verification is never switched off."""
    import ssl
    ctx = pc.ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    subjects = [dict(x[0] for x in c["subject"]).get("commonName")
                for c in ctx.get_ca_certs()]
    assert "GlobalSign GCC R46 DV TLS CA 2025" in subjects


# ── the specs: moved sources and the frozen fallback ─────────────────────────

def test_a_moved_source_is_a_counted_drop_not_an_unroutable_failure():
    spec = load_spec("prisoners")
    rec = {"stable_id": "s", "prisoner_metric_type": "total", "date": "2026-06-01",
           "location": {"region": "Palestine"}, "metrics": {"count": 1},
           "sources": [{"name": "HaMoked"}]}
    assert databank.t_prisoners(rec, spec, PLACES, Counter()) == Drop("moved")
    spec = load_spec("economic")
    rec = {"stable_id": "s", "indicator_code": "pcbs_cpi", "date": "2024-12-31",
           "location": {"region": "West Bank"}, "metrics": {"value": 1},
           "sources": [{"name": "Palestinian Central Bureau of Statistics (PCBS)",
                        "url": "https://www.pcbs.gov.ps"}]}
    assert databank.t_economic(rec, spec, PLACES, Counter()) == Drop("moved")


def test_moving_a_source_into_nowhere_is_refused_by_the_format():
    from ingest.spec import validate
    import yaml
    spec = yaml.safe_load((ROOT / "db" / "mappings" / "prisoners.yaml").read_text())
    spec["source_routing"]["moved"] = {"HaMoked": "no_such_spec"}
    assert any("no spec" in p.message for p in validate(spec, "prisoners"))
    spec = yaml.safe_load((ROOT / "db" / "mappings" / "prisoners.yaml").read_text())
    spec["drop"] = []
    assert any("moved" in p.message and "sized" in p.message
               for p in validate(spec, "prisoners"))


def test_the_fallback_is_read_only_when_the_fetch_never_happened(tmp_path):
    (tmp_path / "frozen").mkdir()
    (tmp_path / "frozen" / "c.json.gz").write_bytes(b"")
    spec = {"input": {"root": str(tmp_path / "raw"), "glob": "c.json",
                      "fallback": {"root": str(tmp_path / "frozen"), "glob": "c.json.gz"}}}
    assert databank.reads_fallback(spec)
    assert [f.name for f in databank.iter_v1_files("c", spec)] == ["c.json.gz"]
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "c.json").write_text("[]")
    assert not databank.reads_fallback(spec)
    assert [f.name for f in databank.iter_v1_files("c", spec)] == ["c.json"]


def test_every_new_spec_names_its_fetcher_and_its_dataset():
    for cat, root, ds in (("prisoners_hamoked", "data/raw/hamoked", "v1_prisoners_hamoked"),
                          ("economic_pcbs", "data/raw/pcbs", "v1_economic_pcbs_direct")):
        spec = load_spec(cat)
        assert spec["input"]["root"] == root and [d["key"] for d in spec["datasets"]] == [ds]
    for line in gr.SUPPLY_LINES.values():
        assert (ROOT / line["fetcher"]).exists(), line["fetcher"]


# ── the radar: a dead line fails the night ───────────────────────────────────

def ev(label, outcome, days_ago):
    return {"label": label, "outcome": outcome,
            "at": (NOW - timedelta(days=days_ago)).isoformat()}


def _ledger(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def test_three_failures_in_a_row_or_silence_or_never_is_dead():
    j = gr.judge_attempts
    ok = lambda d: {"at": (NOW - timedelta(days=d)).isoformat(), "outcome": "ok", "ok": True}  # noqa: E731
    bad = lambda d: {"at": (NOW - timedelta(days=d)).isoformat(), "outcome": "error", "ok": False}  # noqa: E731
    assert j([ok(3), bad(2), bad(1), bad(0)], NOW)["status"] == "dead"
    assert j([ok(3), bad(1), bad(0)], NOW)["status"] == "failing"
    assert j([bad(3), ok(1), bad(0)], NOW)["status"] == "failing"
    assert j([ok(5), ok(4)], NOW)["status"] == "dead"            # stopped running
    assert "not being run" in j([ok(5)], NOW)["why"]
    assert j([], NOW)["status"] == "dead"
    assert j([ok(0)], NOW)["status"] == "live"


def _datasets(**status):
    return [{"dataset": k, "status": v, "last_information_day": "2026-01-01",
             "age_days": 268, "allowance_days": 30} for k, v in status.items()]


def test_supply_lines_are_judged_and_retired_steps_are_excused_only_by_a_successor(
        monkeypatch):
    monkeypatch.setitem(gr.BENIGN_STEPS, "a-known-artifact", "fails by design")
    v2 = {lab: [{"at": NOW.isoformat(), "outcome": "ok", "ok": True}]
          for line in gr.SUPPLY_LINES.values() for lab in line["labels"]}
    v2["ocha:demolitions"] = [{"at": (NOW - timedelta(days=d)).isoformat(),
                               "outcome": "error", "ok": False} for d in (2, 1, 0)]
    fail = [{"at": (NOW - timedelta(days=d)).isoformat(), "outcome": "FAIL", "ok": False}
            for d in (2, 1, 0)]
    v1 = {"ocha-casualties": fail, "validate": fail, "docker-restart-api": fail,
          "a-known-artifact": fail, "some-new-step": fail,
          "gaza-daily": [{"at": NOW.isoformat(), "outcome": "OK", "ok": True}]}
    ds = _datasets(v1_demolitions_ocha_demolitions="fresh", v1_food_wfp="stalled",
                   v1_prisoners_hamoked="fresh")
    s = gr.judge_supply_lines(v2, v1, ds, NOW)
    status = {x["line"]: x["status"] for x in s["v2"] + s["v1_steps"] + s["data"]}
    assert status["ocha-demolitions"] == "dead" and status["hamoked"] == "live"
    assert status["v1 step ocha-casualties"] == "retired_pending"      # successor named
    assert status["v1 step validate"] == "retired_pending"
    assert status["v1 step docker-restart-api"] == "retired_pending"
    assert status["v1 step a-known-artifact"] == "benign"
    assert status["v1 step some-new-step"] == "dead"                  # nobody excused it
    assert status["data v1_food_wfp"] == "dead"                       # stalled, no line
    assert {x["line"] for x in s["dead"]} == {"ocha-demolitions", "v1 step some-new-step",
                                              "data v1_food_wfp"}
    gr.apply_supply(ds, s)
    by = {d["dataset"]: d for d in ds}
    assert by["v1_demolitions_ocha_demolitions"]["status"] == "supply_dead"
    assert by["v1_prisoners_hamoked"]["status"] == "fresh"
    c = gr.supply_counts(s)
    assert (c["dead"], c["v2_dead"], c["v1_retired_pending"], c["v1_benign"]) == (3, 1, 3, 1)


def test_a_stalled_dataset_kills_the_line_that_feeds_it():
    v2 = {lab: [{"at": NOW.isoformat(), "outcome": "ok", "ok": True}]
          for line in gr.SUPPLY_LINES.values() for lab in line["labels"]}
    s = gr.judge_supply_lines(v2, {}, _datasets(v1_prisoners_hamoked="stalled"), NOW)
    hamoked = next(x for x in s["v2"] if x["line"] == "hamoked")
    assert hamoked["status"] == "dead" and "stalled" in hamoked["why"]
    assert not s["data"]                      # counted once, on its own line


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self


def _run_radar(monkeypatch, tmp_path, v2_events, v1_events, datasets):
    monkeypatch.setattr(gr, "connect", lambda: _Conn())
    monkeypatch.setattr(gr, "measure_datasets", lambda cur, today: datasets)
    monkeypatch.setattr(gr, "measure_eras", lambda cur: {})
    monkeypatch.setattr(gr, "measure_fetch_health", lambda today: [])
    monkeypatch.setattr(gr, "V2_EVENTS", _ledger(tmp_path / "v2.ndjson", v2_events))
    monkeypatch.setattr(gr, "V1_EVENTS", _ledger(tmp_path / "v1.ndjson", v1_events))
    monkeypatch.setattr(gr, "OUT", tmp_path / "gap-radar.json")
    rc = gr.main()
    return rc, json.loads((tmp_path / "gap-radar.json").read_text())


def _all_ok_today():
    now = datetime.now(timezone.utc)
    return [{"label": lab, "outcome": "ok", "at": now.isoformat()}
            for line in gr.SUPPLY_LINES.values() for lab in line["labels"]]


def test_the_radar_exits_5_on_a_dead_line_and_counts_it_in_the_headline(
        monkeypatch, tmp_path, capsys):
    now = datetime.now(timezone.utc)
    v2 = [e for e in _all_ok_today() if e["label"] != "hamoked:detention"] + [
        {"label": "hamoked:detention", "outcome": "error",
         "at": (now - timedelta(days=d)).isoformat()} for d in (2, 1, 0)]
    v1 = [{"label": "hamoked-detention", "outcome": "FAIL",
           "at": (now - timedelta(days=d)).isoformat()} for d in (2, 1, 0)]
    ds = [dict(d, rows=1, span=["", ""], distinct_days=1, precision="month",
               rhythm_median_days=31.0, freshness_basis="data dates",
               event_driven=False, dead_reason=None, largest_hole=None)
          for d in _datasets(v1_prisoners_hamoked="fresh", v1_food_wfp="fresh")]
    rc, report = _run_radar(monkeypatch, tmp_path, v2, v1, ds)
    assert rc == gr.DEAD_EXIT == 5
    c = report["counts"]
    assert (c["fresh"], c["supply_dead"], c["supply_lines"]["dead"]) == (1, 1, 1)
    assert report["gaps"][0]["kind"] == "supply" and report["gaps"][0]["severity"] == 5
    assert "Addameer" in report["gaps"][0]["fill_path"]            # the named successor
    out = capsys.readouterr()
    assert "1 supply-dead" in out.out and "1 DEAD" in out.out
    assert "DEAD SUPPLY LINES (1): hamoked" in out.err


def test_the_radar_exits_0_when_every_line_lives_and_still_names_retired_steps(
        monkeypatch, tmp_path, capsys):
    now = datetime.now(timezone.utc)
    v1 = [{"label": "databank-gaza", "outcome": "FAIL",
           "at": (now - timedelta(days=d)).isoformat()} for d in (2, 1, 0)]
    rc, report = _run_radar(monkeypatch, tmp_path, _all_ok_today(), v1, [])
    assert rc == 0
    assert report["counts"]["supply_lines"]["v1_retired_pending"] == 1
    step = report["supply_lines"]["v1_steps"][0]
    assert step["status"] == "retired_pending" and "Tier 2" in step["successor"]
    assert "1 retired but still run and fail in v1" in capsys.readouterr().out


def test_the_data_gaps_answer_says_the_dead_lines_in_both_languages(monkeypatch):
    """The MCP tool reads the radar's counts; a dead line is said, not folded
    into 'fresh' — in Arabic and in English, the same numbers."""
    from serve import mcp_en, mcp_server as s
    radar = {"counts": {"datasets": 32, "fresh": 24, "late": 0, "stalled": 0,
                        "supply_dead": 4, "dead_upstream": 2,
                        "supply_lines": {"dead": 4, "v2_live": 3, "v2_lines": 7}},
             "gaps": [], "measured_at": "t"}

    def fake_api(path, *a, **k):
        if path.endswith("radar"):
            return radar
        raise RuntimeError("no scout")
    monkeypatch.setattr(s, "api", fake_api)
    ar = s.data_gaps()["answer"]
    assert "24 حديثة" in ar and "4 خط إمدادها ميت" in ar and "خطوط الإمداد: 4 ميتة" in ar
    en = mcp_en.data_gaps(radar)
    assert "24 fresh" in en and "4 whose supply line is dead" in en and "4 dead" in en
    old = {"counts": {"datasets": 32, "fresh": 27, "late": 1, "stalled": 0,
                      "dead_upstream": 2}}
    assert mcp_en.data_gaps(old).endswith("has died.")      # an old radar still reads


# ── the nightly job wires it all ─────────────────────────────────────────────

def test_the_nightly_runs_the_four_fetchers_and_fails_on_a_dead_line():
    sh = (ROOT / "ops" / "databank-sync.sh").read_text()
    for mod in ("ops.fetch_ocha", "ops.fetch_pcbs", "ops.fetch_hamoked"):
        assert f"step .venv/bin/python -m {mod}" in sh
    assert sh.index("ops.fetch_hamoked") < sh.index("ingest.databank --all")
    assert "with-heartbeat.sh supply-lines 86400 21600 -- \\\n  .venv/bin/python -m ops.gap_radar" in sh
    assert "final=$rc" in sh and "[ \"$final\" -eq 0 ] && final=$radar" in sh
    assert sh.rstrip().endswith("exit $final")
    assert "ops.alert --resolve palestine-v2-databank.service" in sh
    from ops.watchdog import EXPECTED_JOBS
    assert EXPECTED_JOBS["supply-lines"] == (86400, 21600)
    wrap = (ROOT / "ops" / "with-heartbeat.sh").read_text()
    assert 'if [ "${HEARTBEAT_RESOLVE:-1}" != 0 ]; then' in wrap


def test_a_dry_run_leaves_no_ledger_line(monkeypatch, tmp_path):
    """A rehearsal must not count as an attempt in the radar's streak."""
    ledger = tmp_path / "fetch-events.ndjson"
    monkeypatch.setattr(fl, "EVENTS", ledger)
    with pytest.raises(fl.FetchRefused):
        oc.floor("ocha:casualties", 3, 44, "records", dry=True)
    assert not ledger.exists()
    with pytest.raises(fl.FetchRefused):
        oc.floor("ocha:casualties", 3, 44, "records", dry=False)
    assert json.loads(ledger.read_text())["outcome"] == "refused"
