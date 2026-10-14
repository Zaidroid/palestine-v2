"""supply-scrapes (2026-10-12) — land, settlements, prisoners and culture off
v1's unified tree.

Everything here is offline. The parsers run on real answers cut down and
saved under tests/fixtures/supply_scrapes/ (read 2026-10-12 from
goodshepherdcollective.org, data.humdata.org, peacenow.org.il and
addameer.ps). The identity and content strings asserted below are the ones
the production store held that day for the same rows: a fetcher that stops
reproducing them would write every row a second time, or rewrite it.
No network, no database.
"""
from __future__ import annotations

import functools
import gzip
import json
import urllib.error
from collections import Counter
from pathlib import Path

import pytest

from ingest import databank
from ingest.databank import load_spec
from ops import fetch_addameer as ad
from ops import fetch_goodshepherd as gs
from ops import fetch_hdx_land as hl
from ops import fetch_peacenow as pn
from ops import fetchlib as fl

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "supply_scrapes"
PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2},
          "governorate": {"Jerusalem": 11}, "pcode": {}}
AT = "2026-10-12T19:50:00+00:00"


@functools.lru_cache(maxsize=None)
def _identity_spec(category: str, dataset_key: str) -> dict:
    spec = load_spec(category)
    return next(((d.get("overrides") or {}).get("identity")
                 for d in spec["datasets"] if d["key"] == dataset_key),
                None) or spec["identity"]


def identity(category: str, row) -> str:
    """The stored identity_key of a row, by the loader's own renderer."""
    ident = _identity_spec(category, row.dataset_key)
    return databank.identity_key_for(
        ident, row.dataset_key, indicator=row.indicator,
        occurred_at=row.occurred_at, place_id=row.place_id,
        value_num=row.value_num, attrs=row.attrs)


def says(row) -> tuple:
    return (row.value_num, row.value_text, row.unit, row.place_id, row.attrs)


# ── Good Shepherd: demolitions per day ───────────────────────────────────────

def gsc_payload() -> dict:
    return json.loads((FX / "gsc_home_demolitions.json").read_text())


def test_gsc_days_are_the_publishers_days_and_a_zero_stays_a_zero():
    days = gs.days(gsc_payload())
    assert [d["date"] for d in days] == ["2025-09-08", "2025-09-09", "2026-01-04",
                                         "2026-07-26", "2026-10-07", "2026-10-08"]
    by = {d["date"]: d for d in days}
    assert by["2025-09-08"]["structures"] == 31 and by["2025-09-08"]["incidents"] == 5
    # one incident, people displaced, nothing demolished: v1 stored 1 (`0 || 1`)
    assert by["2026-01-04"]["structures"] == 0 and by["2026-01-04"]["displacedPeople"] == 8
    assert by["2026-07-26"]["structures"] == 0
    assert gs.publisher_stamp(gsc_payload()) == "2026-10-12T06:01:31"
    assert gs.publisher_stamp({"mostRecentTimestamp": "soon"}) is None


def test_gsc_refuses_what_is_not_a_day_with_a_count():
    payload = {"chartData": [
        {"date": "2026-10-08", "structures": 1},
        {"date": "2026-10-08", "structures": 9},          # the same day again
        {"date": "08.10.2026", "structures": 1},          # not a date
        {"date": "2026-10-07", "structures": "3"},        # not a number
        {"date": "2026-10-06", "structures": -1},
        {"date": "2026-10-05", "structures": 2.5},
        {"date": "2026-10-04", "structures": True},
        {"date": "2023-10-06", "structures": 4},          # before v1's baseline
        {"structures": 4}]}
    assert gs.days(payload) == [{"date": "2026-10-08", "structures": 1}]
    assert gs.days({}) == [] and gs.days({"chartData": None}) == []


def test_gsc_records_land_on_the_held_rows():
    recs = gs.day_records(gs.days(gsc_payload()), AT)
    spec = load_spec("land")
    rows = {r["date"]: databank.t_land(r, spec, PLACES, Counter())[0] for r in recs}
    row = rows["2025-09-08"]
    assert (row.dataset_key, row.indicator, row.occurred_at, row.precision) == \
        ("v1_land_goodshepherd", "land.demolition", "2025-09-08", "day")
    assert identity("land", row) == "v1_land_goodshepherd|land.demolition|2025-09-08"
    # v1's five constants (residential, one structure, administrative, notice
    # given, private) and its region "Palestine" are no longer carried: the
    # publisher says West Bank and East Jerusalem and gives a count
    assert says(row) == (31, None, "structures", PLACES["region"]["West Bank"], {
        "land_name": "Multiple locations", "land_type": "demolition",
        "coverage_area": "West Bank and East Jerusalem"})
    assert row.reported_at == AT and row.v1_stable_id == "gsc-demolitions:2025-09-08"
    # the correction: the same identity, the publisher's number
    assert identity("land", rows["2026-01-04"]) == \
        "v1_land_goodshepherd|land.demolition|2026-01-04"
    assert rows["2026-01-04"].value_num == 0 and rows["2026-07-26"].value_num == 0
    # what the publisher said beside the count is kept in the raw record, not loaded
    assert recs[0]["upstream"]["displacedPeople"] == 14
    assert "displacedPeople" not in row.attrs


# ── HDX: the barrier and the settlement footprints ───────────────────────────

def test_the_attribute_table_reads_as_v1s_library_read_it():
    rows = hl.dbf_of((FX / "hdx_barrier_sample.zip").read_bytes())
    assert len(rows) == 7
    assert rows[0] == {"OBJECTID": 1, "Status": "Constructed", "Type": "Concrete",
                       "IS_COUNTED": 1, "Shape_Leng": 1911.588555}
    assert rows[5]["OBJECTID"] == 276 and rows[5]["Type"] is None   # an empty cell
    with pytest.raises(ValueError, match="one .dbf"):
        import io
        import zipfile
        buf = io.BytesIO()
        zipfile.ZipFile(buf, "w").close()
        hl.dbf_of(buf.getvalue())


def test_barrier_segments_keep_the_names_and_content_the_store_holds():
    recs = hl.barrier_records(hl.dbf_of((FX / "hdx_barrier_sample.zip").read_bytes()), AT)
    assert [r["land_name"] for r in recs] == [
        "Concrete - 1", "Fence - 2", "Fence - 13", "NA - 15", "Concrete - 234",
        "Unknown - 276", "Fence - 293"]
    assert [r["land_status"] for r in recs] == [
        "Constructed", "Constructed", "Under Construction", "Projected",
        "Under Construction", "Constructed", "Projected"]
    spec = load_spec("land")
    [row] = databank.t_land(recs[0], spec, PLACES, Counter())
    assert (row.dataset_key, row.indicator, row.precision) == \
        ("v1_land_ocha", "land.checkpoint", "unknown")
    assert identity("land", row) == "v1_land_ocha|land.checkpoint|Concrete - 1|Barrier"
    # the status is the file's own; "permits required" was v1's constant
    assert says(row) == (1, "Constructed", "sites", 2, {
        "land_name": "Concrete - 1", "land_type": "checkpoint",
        "land_status": "Constructed", "checkpoint_type": "Barrier"})
    [na] = databank.t_land(recs[3], spec, PLACES, Counter())
    assert identity("land", na) == "v1_land_ocha|land.checkpoint|NA - 15|Barrier"
    # what the file says is kept beside v1's naming
    assert recs[3]["upstream"] == {"objectid": 15, "status": "Projected", "type": "NA",
                                   "is_counted": 1, "length_m": 3105.05364166}
    # v1's three keyword rules, should the file ever use the words
    assert hl._checkpoint_status(None) == "Active"
    assert hl._checkpoint_status("Partially closed") == "Partial"
    assert hl._checkpoint_type("Road Gate") == "Gate"


def test_settlement_footprints_collapse_only_the_indistinguishable_twins():
    rows = hl.dbf_of((FX / "hdx_settlements_sample.zip").read_bytes())
    assert len(rows) == 8
    recs, collapsed = hl.settlement_records(rows, AT)
    assert collapsed == [197, 198]           # unnamed, same dunums as 189 and 190
    assert [(r["land_name"], r["settlement"].get("area_dunums")) for r in recs] == [
        ("Ariel", 2566), ("Beitar Illit", 2094), ("Bqa'ot", 193),
        ("Unknown", 1005), ("Unknown", 2), ("Unknown", 10)]
    spec = load_spec("land")
    [row] = databank.t_land(recs[0], spec, PLACES, Counter())
    assert identity("land", row) == "v1_land_peace_now|land.settlement|Ariel|2566"
    # the file has a name and an area; "Authorized" and "Settlement" were v1's constants
    assert says(row) == (1, None, "sites", 2, {
        "land_name": "Ariel", "land_type": "settlement", "area_dunums": 2566})
    [unknown] = databank.t_land(recs[3], spec, PLACES, Counter())
    assert identity("land", unknown) == "v1_land_peace_now|land.settlement|Unknown|1005"
    assert hl._js_round(2.5) == 3 and hl._js_round(0.5) == 1 and hl._js_round(2.4) == 2


def test_the_publishers_own_dates_and_licence_are_read_from_hdx():
    pkg = json.loads((FX / "hdx_pkg_barrier.json").read_text())["result"]
    pub = hl.publisher_record(pkg, hl.FEEDS["barrier"]["resource"])
    assert pub["license_id"] == "cc-by" and pub["dataset_source"] == "OCHA oPt"
    assert pub["resource_last_modified"].startswith("2019-07-16")
    v = hl.vintage_of(pub, hl.FEEDS["barrier"]["page"])
    assert v["vintage"] == "2018-01-01" and "2019-07-16" in v["vintage_basis"]
    pkg = json.loads((FX / "hdx_pkg_settlements.json").read_text())["result"]
    pub = hl.publisher_record(pkg, hl.FEEDS["settlements"]["resource"])
    assert pub["license_id"] == "cc-by-igo"
    assert pub["caveats"] == "Settlements data provided by Peace Now"
    assert hl.vintage_of(pub, "p")["vintage"] == "2018-12-31"
    with pytest.raises(ValueError, match="no longer in"):
        hl.publisher_record(pkg, "another-resource-id")


def test_an_unchanged_register_is_not_downloaded_again(tmp_path, monkeypatch):
    out = tmp_path / "barrier.json"
    monkeypatch.setitem(hl.FEEDS["barrier"], "out", out)
    monkeypatch.setattr(hl.fl, "ROOT", tmp_path)
    events, calls = [], []
    monkeypatch.setattr(hl.fl, "event", lambda label, outcome, **kw: events.append((label, outcome, kw)))
    from ingest import bronze
    monkeypatch.setattr(bronze, "put", lambda *a, **k: type("R", (), {"ref": "bronze://test"})())
    pkg = (FX / "hdx_pkg_barrier.json").read_bytes()
    archive = (FX / "hdx_barrier_sample.zip").read_bytes()

    def get(url, timeout=120):
        calls.append(url)
        return pkg if "package_show" in url else archive
    monkeypatch.setitem(hl.FEEDS["barrier"], "floor", 5)
    assert hl.fetch_one("barrier", False, [], get=get, sleep=lambda s: None) == 0
    doc = json.loads(out.read_text())
    assert len(doc["data"]) == 7 and doc["metadata"]["vintage"] == "2018-01-01"
    assert doc["metadata"]["license"].startswith("cc-by")
    assert "checkpoint.permits_required" in doc["metadata"]["v1_defaults_not_from_publisher"]
    assert len(calls) == 2 and events[-1][1] == "ok"
    before = out.read_bytes()
    assert hl.fetch_one("barrier", False, [], get=get, sleep=lambda s: None) == 0
    assert len(calls) == 3                       # the metadata only
    assert out.read_bytes() == before and events[-1][2]["unchanged"] is True
    # a short answer keeps the file on disk
    out.write_text(json.dumps({"metadata": {"publisher": {"resource_last_modified": "old"}},
                               "data": ["kept"]}))
    monkeypatch.setitem(hl.FEEDS["barrier"], "floor", 235)
    assert hl.fetch_one("barrier", False, [], get=get, sleep=lambda s: None) == 1
    assert json.loads(out.read_text())["data"] == ["kept"] and events[-1][1] == "refused"


# ── Peace Now: settler population by year ────────────────────────────────────

def pn_page() -> str:
    return (FX / "peacenow_population.html").read_text(encoding="utf-8")


def test_the_population_chart_parses_to_51_years():
    pts = pn.parse_population(pn_page())
    assert len(pts) == 51 and pts[0] == (1967, 0) and pts[1] == (1972, 1500)
    assert pts[-3:] == [(2022, 478600), (2023, 503732), (2024, 511100)]
    # the CBS census and year-end figures the labels were checked against
    by = dict(pts)
    assert (by[1983], by[1995], by[2008], by[2021]) == (23700, 134300, 281100, 465400)


def test_the_page_contradicts_itself_and_the_raw_file_says_so():
    """511,100 sits under "2024" on the chart and beside "end of 2023" under
    the pies. The chart's year is what is loaded; the captions are kept."""
    caps = pn.captions(pn_page())
    assert "Source: Israeli CBS, end of 2023" in caps
    assert "Source: Israeli and Palestinian CBS, end of 2023" in caps
    assert "Source: Israeli CBS" in caps
    assert '["", 511100]' in pn_page()                       # the pie's figure


def test_a_changed_page_is_refused_not_guessed():
    page = pn_page()
    with pytest.raises(pn.PageChanged, match="no year axis"):
        pn.parse_population(page.replace('categories: ["1967"', 'categories: ["1968"'))
    series = "data: [" + ",".join(str(n) for _, n in pn.parse_population(page)) + "]"
    with pytest.raises(pn.PageChanged, match="expected exactly one"):
        pn.parse_population(page + "<script>" + series + "</script>")
    with pytest.raises(pn.PageChanged, match="expected exactly one"):
        pn.parse_population('categories: ["1967","1972"]')


def test_settler_years_land_on_the_held_rows():
    recs = pn.year_records(pn.parse_population(pn_page()), AT)
    assert recs[-1]["date"] == "2024-12-31" and recs[-1]["stable_id"] == "peacenow-settlers:2024"
    spec = load_spec("settlements")
    [row] = databank.t_engine(recs[-1], spec, PLACES, Counter())
    assert (row.dataset_key, row.occurred_at, row.precision) == \
        ("v1_settlements_peace_now", "2024-01-01", "year")
    assert identity("settlements", row) == \
        "v1_settlements_peace_now|settlements.settler_population|2024-01-01"
    assert says(row) == (511100, None, "settlers", 2, {
        "year": 2024, "coverage": "West Bank, excludes East Jerusalem",
        "reference": "period-end stock", "event_type": "settler_population"})
    [first] = databank.t_engine(recs[0], spec, PLACES, Counter())
    assert first.value_num == 0 and first.occurred_at == "1967-01-01"   # a true 0


# ── Addameer: monthly prisoner statistics ────────────────────────────────────

def ad_page() -> str:
    return (FX / "addameer_statistics.html").read_text(encoding="utf-8")


def test_addameer_charts_and_block_give_their_series():
    recs, notes = ad.month_records(ad_page(), "direct", AT)
    v = {(r["date"], r["prisoner_metric_type"]): r["metrics"]["count"] for r in recs}
    assert len(recs) == 48 and len({r["date"] for r in recs}) == 14
    # three chart series by month; the block's other figures for its own month (since 2026-10-14)
    assert Counter(m for _, m in v) == {"total": 14, "administrative": 14, "jerusalem": 12,
                                        "child": 1, "female": 1, "from_1948": 1, "gaza": 1,
                                        "life_sentence": 1, "legislative_council": 1, "pre_oslo": 1,
                                        "unlawful_combatants": 1}
    assert v[("2026-10-01", "jerusalem")] == 400 and v[("2026-10-01", "gaza")] == 40
    assert v[("2026-10-01", "life_sentence")] == 118 and v[("2026-10-01", "unlawful_combatants")] == 1419
    assert v[("2026-10-01", "total")] == 9300
    assert v[("2026-10-01", "administrative")] == 3101
    assert v[("2026-10-01", "child")] == 350 and v[("2026-10-01", "female")] == 91
    assert v[("2025-05-01", "total")] == 10100 and v[("2025-10-01", "administrative")] == 3544
    assert notes["block_date"] == "2026-10-05"
    assert notes["statistics_block"]["Gaza Strip Detainees (Unlawful Combatant)"] == 1419
    # the East Jerusalem chart was read and not loaded until 2026-10-14; now every chart series is one
    assert notes["series_not_loaded"] == {}
    assert "block_total_differs_from_chart" not in notes
    assert recs[0]["date"] == "2026-10-01"            # newest first
    names = {r["prisoner_metric_type"]: r["indicator_name"] for r in recs}
    assert names == {"total": "Total Number of Political Prisoners",
                     "administrative": "Administrative Detainees",
                     "child": "Child prisoners", "female": "Female prisoners",
                     "jerusalem": "East Jerusalem prisoners",       # the chart's name: the chart's month wins
                     "from_1948": "1948 Territories prisoners", "gaza": "Gaza prisoners",
                     "life_sentence": "Prisoners serving life sentences",
                     "legislative_council": "Palestinian Legislative Council members",
                     "pre_oslo": "Prisoners before Oslo",
                     "unlawful_combatants": "Gaza Strip Detainees (Unlawful Combatant)"}


def test_child_and_female_are_filed_under_the_blocks_own_month():
    """v1 filed them under the month it ran in: a run on 1 October, before
    Addameer posted October's block, put September's figures under October."""
    september = ad_page().replace('datetime="2026-10-05T12:00:00Z"',
                                  'datetime="2026-09-28T12:00:00Z"')
    recs, notes = ad.month_records(september, "direct", "2026-10-01T02:57:00+00:00")
    v = {(r["date"], r["prisoner_metric_type"]): r["metrics"]["count"] for r in recs}
    assert v[("2026-09-01", "child")] == 350 and ("2026-10-01", "child") not in v
    # a block that disagrees with the chart for its month is said, not hidden
    assert notes["block_total_differs_from_chart"] == {
        "month": "2026-09-01", "block": 9300, "chart": 9350}
    undated = ad_page().replace("field-date-of-statistics", "field-date")
    recs, notes = ad.month_records(undated, "direct", AT)
    assert {r["prisoner_metric_type"] for r in recs} == {"total", "administrative", "jerusalem"}
    assert len(recs) == 40 and "no_block_date" in notes     # the charts alone: nothing from an undated block


def test_addameer_records_land_on_the_held_rows():
    recs, _ = ad.month_records(ad_page(), "direct", AT)
    spec = load_spec("prisoners")
    by = {(r["date"], r["prisoner_metric_type"]): r for r in recs}
    [row] = databank.t_prisoners(by[("2026-10-01", "total")], spec, PLACES, Counter())
    assert (row.dataset_key, row.occurred_at, row.precision) == \
        ("v1_prisoners_addameer", "2026-10-01", "month")
    assert identity("prisoners", row) == "v1_prisoners_addameer|prisoners.total|2026-10-01"
    assert says(row) == (9300, None, "persons", None, {
        "name": "West Bank & Gaza", "region": "Palestine",
        "reference": "period-end stock", "prisoner_metric_type": "total"})
    [child] = databank.t_prisoners(by[("2026-10-01", "child")], spec, PLACES, Counter())
    assert identity("prisoners", child) == "v1_prisoners_addameer|prisoners.child|2026-10-01"
    assert child.v1_stable_id == "addameer:2026-10-01:child"


def test_addameer_has_two_doors_and_a_refusal_is_not_walked_around():
    page = ad_page().encode("utf-8")
    cdx = json.dumps([["timestamp", "statuscode", "digest"],
                      ["20260901101010", "200", "A"], ["20260920111111", "200", "B"],
                      ["20260925000000", "301", "C"]]).encode()
    assert ad.latest_capture(json.loads(cdx)) == "20260920111111"

    def direct(url, ua, timeout=60):
        assert url == ad.PAGE and ua == fl.UA
        return page
    assert ad.fetch(get=direct)[1] == "direct"

    def expired_certificate(url, ua, timeout=60):
        if url == ad.PAGE:
            raise urllib.error.URLError("certificate has expired")
        if url == ad.CDX:
            return cdx
        assert url == ad.WAYBACK.format(ts="20260920111111")
        return page
    html, via, raw, url = ad.fetch(get=expired_certificate)
    assert via == "wayback:20260920111111" and raw == page

    asked = []

    def refused(url, ua, timeout=60):
        asked.append(url)
        raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
    with pytest.raises(OSError, match="direct: HTTP 403"):
        ad.fetch(get=refused)
    assert asked == [ad.PAGE]                 # the archive was not asked

    def no_charts_anywhere(url, ua, timeout=60):
        return cdx if url == ad.CDX else b"<html>maintenance</html>"
    with pytest.raises(OSError, match="200 without charts; wayback"):
        ad.fetch(get=no_charts_anywhere)


# ── every raw file says how old the publisher's data is ─────────────────────

def test_each_fetcher_stages_a_raw_file_with_the_publishers_vintage(tmp_path, monkeypatch):
    """`--dry-run --stage DIR` end to end, offline: the raw file each fetcher
    would write, with the vintage block the brief asks of every one. A dry
    run writes no ledger line and no bronze payload."""
    def no_ledger(*a, **k):
        raise AssertionError("a dry run wrote to the ledger")
    monkeypatch.setattr(fl, "event", no_ledger)
    stage = ["--dry-run", "--stage", str(tmp_path)]

    monkeypatch.setattr(gs, "MIN_DAYS", 5)
    monkeypatch.setattr(fl, "get", lambda url, timeout=120:
                        (FX / "gsc_home_demolitions.json").read_bytes())
    assert gs.main(stage) == 0
    doc = json.loads((tmp_path / "demolitions.json").read_text())
    assert doc["metadata"]["vintage"] == "2026-10-08"
    assert doc["metadata"]["publisher_built_at"] == "2026-10-12T06:01:31"
    assert doc["metadata"]["days_with_no_structure"] == ["2026-01-04", "2026-07-26"]
    assert "demolition.notification_given" in doc["metadata"]["v1_defaults_not_from_publisher"]
    monkeypatch.setattr(gs, "MIN_DAYS", 150)
    assert gs.main(["--dry-run"]) == 1                    # six days: refused

    monkeypatch.setattr(fl, "get", lambda url, timeout=120: pn_page().encode("utf-8"))
    assert pn.main(stage) == 0
    doc = json.loads((tmp_path / "settlers.json").read_text())
    assert doc["metadata"]["vintage"] == "2024" and len(doc["data"]) == 51
    assert "Source: Israeli CBS, end of 2023" in doc["metadata"]["page_captions"]
    monkeypatch.setattr(fl, "get", lambda url, timeout=120: b"<html>moved</html>")
    assert pn.main(["--dry-run"]) == 1                    # no chart: an error, not a guess

    page = ad_page()
    monkeypatch.setattr(ad, "fetch", lambda: (page, "direct", page.encode(), ad.PAGE))
    assert ad.main(stage) == 0
    doc = json.loads((tmp_path / "statistics.json").read_text())
    assert doc["metadata"]["vintage"] == "2026-10-05" and doc["metadata"]["via"] == "direct"
    assert doc["metadata"]["data_through"] == "2026-10" and len(doc["data"]) == 48

    for name in ("demolitions.json", "settlers.json", "statistics.json"):
        meta = json.loads((tmp_path / name).read_text())["metadata"]
        assert meta["vintage"] and meta["vintage_basis"] and meta["vintage_url"], name
        assert meta["license"], name


# ── the specs, and what a machine without v1 reads ───────────────────────────

FETCHED = {"land": ("data/raw/land", ["barrier.json", "settlements.json", "demolitions.json"]),
           "settlements": ("data/raw/peacenow", "settlers.json"),
           "prisoners": ("data/raw/addameer", ["statistics.json", "history.json"])}


def test_the_three_fetched_specs_read_v2s_fetch_and_fall_back_to_the_frozen_corpus():
    for cat, (root, glob) in FETCHED.items():
        spec = load_spec(cat)
        assert spec["input"]["root"] == root and spec["input"]["glob"] == glob, cat
        assert spec["input"]["fallback"] == {"root": "data/frozen",
                                             "glob": f"{cat}.json.gz"}, cat
    assert load_spec("land")["cadence"] == "daily"
    assert load_spec("settlements")["cadence"] == "annual"
    assert load_spec("prisoners")["cadence"] == "monthly"


def test_culture_is_a_frozen_corpus_with_its_wikidata_items_beside_it():
    spec = load_spec("culture")
    assert spec["input"] == {"root": "data/frozen", "glob": "culture.json.gz"}
    assert spec["cadence"] == "frozen"
    corpus = json.loads(gzip.decompress((ROOT / "data/frozen/culture.json.gz").read_bytes()))
    side = json.loads(gzip.decompress(
        (ROOT / "data/frozen/culture_wikidata_items.json.gz").read_bytes()))
    assert len(corpus["data"]) == len(side["data"]) == 335
    assert {r["site_name"] for r in corpus["data"]} == {s["name"] for s in side["data"]}
    assert all(s["wikidata_id"].startswith("Q") for s in side["data"])
    assert "query.wikidata.org" in side["metadata"]["endpoint"]
    assert "LIMIT 500" in side["metadata"]["query"]
    # the constant nobody observed, on every row including Gaza's
    assert {r["site_status"] for r in corpus["data"]} == {"Intact"}
    rows = [databank.t_engine(r, spec, PLACES, Counter())[0] for r in corpus["data"]]
    assert {r.dataset_key for r in rows} == {"v1_culture_heritage_composite"}
    assert len({identity("culture", r) for r in rows}) == 335
    held = "v1_culture_heritage_composite|culture.heritage_site.religious|Al-Yaqoubi Mosque"
    [row] = [r for r in rows if identity("culture", r) == held]
    # ...and it is no longer loaded: the corpus keeps v1's record, the row
    # says only where the site is and what kind it is
    assert says(row) == (1, None, "sites", 11, {
        "region": "East Jerusalem", "site_name": "Al-Yaqoubi Mosque",
        "site_type": "Religious"})


def test_no_spec_of_the_family_reaches_for_v1(monkeypatch):
    """The unplug test without a database: whatever a run would read is in
    this repository, fetched or frozen."""
    monkeypatch.setattr(databank, "V1_UNIFIED", Path("/nonexistent/v1-is-gone"))
    for cat in ("land", "settlements", "prisoners", "culture"):
        files = list(databank.iter_v1_files(cat, load_spec(cat)))
        assert files, f"{cat} would read nothing"
        for f in files:
            assert ROOT in f.resolve().parents and f.exists(), f


def test_the_frozen_fallbacks_transform_to_the_family_datasets():
    """A fresh clone loads these. Counts are v1's unified files of 2026-10-12."""
    def recs(cat):
        return json.loads(gzip.decompress(
            (ROOT / f"data/frozen/{cat}.json.gz").read_bytes()))["data"]
    spec = load_spec("land")
    rows = [databank.t_land(r, spec, PLACES, Counter())[0] for r in recs("land")]
    assert Counter(r.dataset_key for r in rows) == {
        "v1_land_ocha": 261, "v1_land_goodshepherd": 232, "v1_land_peace_now": 199}
    assert len({identity("land", r) for r in rows}) == 692
    spec = load_spec("settlements")
    rows = [databank.t_engine(r, spec, PLACES, Counter())[0] for r in recs("settlements")]
    assert len({identity("settlements", r) for r in rows}) == 51
    spec = load_spec("prisoners")
    out = [databank.t_prisoners(r, spec, PLACES, Counter()) for r in recs("prisoners")]
    moved = [o for o in out if isinstance(o, databank.Drop)]
    assert len(moved) == 864 and {d.reason for d in moved} == {"moved"}
    assert len(out) - len(moved) == 30
    assert spec["expect"]["min_records"] <= 30 <= spec["expect"]["max_observations"]


# ── Addameer's monthly pages: the back months (2026-10-13) ───────────────────

def ad_month(day: str, total: int, admin: int, child: int, female: int, extra: str = "") -> str:
    """One monthly page, cut to the markup the block reader reads (the real
    pages carry the same fields; statistics/2015/06 gives exactly these figures)."""
    field = '<span class="views-label views-label-x">{}</span> <div class="field-content">{:,}</div>'
    rows = [("Total Number of Political Prisoners", total), ("Administrative Detainees", admin),
            ("Child prisoners", child), ("Female prisoners", female), ("Gaza prisoners", 360)]
    return ('<div class="views-field views-field-field-date-of-statistics"><time datetime="' + day
            + 'T12:00:00Z">x</time></div>' + "".join(field.format(k, v) for k, v in rows) + extra)


def test_the_monthly_pages_give_each_month_its_own_dated_figures():
    pages = {"2015-06": ad_month("2015-06-01", 5850, 480, 162, 26),
             "2022-11": ad_month("2022-11-21", 4760, 820, 160, 33),
             "2016-06": "<html>a month with no block</html>"}
    recs, notes = ad.history_records(pages, set(), AT)
    v = {(r["date"], r["prisoner_metric_type"]): r["metrics"]["count"] for r in recs}
    assert v[("2015-06-01", "child")] == 162 and v[("2015-06-01", "female")] == 26
    assert v[("2022-11-01", "total")] == 4760 and v[("2022-11-01", "administrative")] == 820
    assert len(recs) == 10 and notes["no_block"] == ["2016-06"] and notes["months"] == 2
    assert v[("2015-06-01", "gaza")] == 360                                  # the block's other figures too (2026-10-14)
    one = next(r for r in recs if r["date"] == "2022-11-01" and r["prisoner_metric_type"] == "total")
    assert one["stable_id"] == "addameer:2022-11-01:total"                 # the identity the held row has
    assert one["sources"][0]["url"].endswith("/statistics/2022/11") and one["sources"][0]["block_date"] == "2022-11-21"
    assert notes["newest_block"] == "2022-11-21" and "vintage" not in notes


def test_a_month_the_nightly_file_carries_is_not_sent_twice():
    pages = {"2026-10": ad_month("2026-10-05", 9300, 3101, 350, 91)}
    skip = {("2026-10-01", m) for m in ("total", "administrative", "child", "female", "gaza")}
    assert ad.history_records(pages, skip, AT)[0] == []
    part = ad.history_records(pages, {("2026-10-01", "total"), ("2026-10-01", "administrative")}, AT)[0]
    assert sorted(r["prisoner_metric_type"] for r in part) == ["child", "female", "gaza"]


def test_the_history_file_does_not_speak_for_the_datasets_vintage():
    src = (ROOT / "ops" / "fetch_addameer.py").read_text()
    body = src[src.index("def history("):src.index("def main(")]
    assert '"vintage":' not in body and "newest_block" in src
    spec = load_spec("prisoners")
    assert spec["input"]["glob"] == ["statistics.json", "history.json"]
    assert spec["expect"]["max_observations"] >= 680


def test_the_twenty_year_lines_and_the_arrest_count_stay_on_the_page():
    """Read, not loaded: two readings of 'twenty years' that cannot be told
    apart over the run, a count of arrests (not persons) on nine pages, and
    deaths in custody on two."""
    for label in ("Prisoners serving more than 20 years", "Prisoners serving more than 25 years",
                  "Prisoners serving a sentence above 20 years", "Number of arrests since October 7, 2023",
                  "Number of martyred prisoners since 1967 (including those who died after October 7, 2023)"):
        assert ad.classify(label) is None, label
    assert ad.classify("Gaza Strip Detainees (Unlawful Combatant)") == "unlawful_combatants"
    assert ad.classify("East Jerusalem prisoners") == ad.classify("Jerusalemite prisoners") == "jerusalem"
