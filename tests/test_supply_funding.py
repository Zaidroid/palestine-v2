"""The `funding` and `refugees` supply lines, cut from v1 on 2026-10-12.

Everything here is offline. The parsers run on real answers saved under
tests/fixtures/supply_funding/ (captured 2026-10-12): ten FTS flows as the API
returned them, seven rows of IDMC's HDX file, OCHA's admin-2 polygons thinned
to a fixture, and the rows the databank held for those flows and events on
that day (written from v1's file). The claim under test is the cut's: a record
built by the v2 fetcher keeps the identity AND the content the store already
holds, so the first night after the cut writes nothing it should not.
No network, no database.
"""
from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path

import pytest

from ingest import databank
from ingest.databank import content_of, identity_key_for, load_spec
from ops import fetch_fts as ff
from ops import fetch_idmc as fi
from ops import fetchlib as fl

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "supply_funding"
AT = "2026-10-12T19:47:00+00:00"


def fx(name):
    return json.loads((FX / name).read_text())


class _NoPoint:
    """The loader's point-in-polygon needs the database; the pcode rung does not."""

    def resolve(self, lat, lon):
        return None


FLOWS = {int(y): v for y, v in fx("fts_flows.json")["flows_by_year"].items()}
FLOW = {str(f["id"]): f for fs in FLOWS.values() for f in fs}
FTS_HELD = fx("fts_held.json")["rows"]
IDMC_HELD = fx("idmc_held.json")
PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2},
          "governorate": {"Jerusalem": 11},
          "pcode": IDMC_HELD["pcode_place"], "_pip": _NoPoint()}


def _held_content(h):
    return content_of(value_num=h["value_num"], value_text=None, unit=h["unit"],
                      place_id=h["place_id"], attrs=h["attrs"])


def _row_content(r):
    return content_of(value_num=r.value_num, value_text=r.value_text, unit=r.unit,
                      place_id=r.place_id, attrs=r.attrs)


# ── FTS: one flow → the record t_funding reads ───────────────────────────────

def test_a_flow_becomes_the_record_v1_wrote():
    rec = ff.flow_record(FLOW["401966"], AT)
    assert rec["stable_id"] == "fts-flow-401966"
    assert rec["date"] == "2026-10-07"
    assert rec["location"] == {"name": "Occupied Palestinian Territory",
                               "governorate": None, "region": "Palestine",
                               "lat": None, "lon": None, "precision": "country"}
    f = rec["funding"]
    assert (f["amount_usd"], f["original_amount"], f["original_currency"]) == (2328060, 2300000, "EUR")
    assert (f["status"], f["flow_type"], f["contribution_type"]) == ("paid", "Standard", "financial")
    assert f["donor"] == {"name": "European Commission's Humanitarian Aid and Civil Protection Department",
                          "type": "Multilateral Organizations"}
    assert f["recipient"] == {"name": "Oxfam Novib Netherlands", "type": "NGOs"}
    assert f["usage_years"] == ["2022"] and f["cluster"] == "Food Security"
    assert f["keywords"] == [] and f["new_money"] is True
    assert f["ref_code"] == "ECHO/PSE/BUD/2022/91001" and f["flow_id"] == "401966"
    assert rec["sources"][0]["name"] == "UN OCHA Financial Tracking Service"
    # the publisher's own fields v1 threw away stay in the raw record
    assert rec["fts"]["version_id"] == FLOW["401966"]["versionId"]
    assert rec["fts"]["updated_at"] == FLOW["401966"]["updatedAt"]


def test_a_parked_flow_takes_its_parked_amount_and_an_empty_or_negative_one_is_no_record():
    assert FLOW["152896"]["amountUSD"] == 0
    assert ff.flow_record(FLOW["152896"], AT)["funding"]["amount_usd"] == 38000000
    assert ff.flow_record(FLOW["402264"], AT)["funding"]["amount_usd"] == 7330000
    # amountUSD -14,520 beside a parked 6.4 M: v1's `amountUSD || parked` took
    # the negative and its `> 0` filter dropped the flow. Kept as v1 had it.
    assert FLOW["390239"]["amountUSD"] < 0 < FLOW["390239"]["fullParkedAmountUSD"]
    assert ff.flow_record(FLOW["390239"], AT) == "no_amount"
    assert ff.flow_record(FLOW["234685"], AT) == "no_amount"


def test_whole_amounts_are_written_the_way_v1s_json_wrote_them():
    """2000000.0 beside a held 2000000 would read as a revision of the row."""
    assert ff.js_number(2000000.0) == 2000000 and isinstance(ff.js_number(2000000.0), int)
    assert ff.js_number(1397260.5) == 1397260.5
    assert ff.js_number(None) == 0 and ff.js_number("") == 0
    assert ff.js_number("125.0") == 125 and isinstance(ff.js_number("125.0"), int)


def test_the_region_is_v1s_rule_on_the_first_destination_and_the_rest_are_kept():
    rec = ff.flow_record(FLOW["160700"], AT)
    assert rec["location"]["name"] == "West Bank"
    assert rec["location"]["region"] == "West Bank"
    assert rec["fts"]["destination_locations"] == ["West Bank", "Gaza Strip",
                                                   "Occupied Palestinian Territory"]
    assert ff.classify_region("Occupied Palestinian Territory") == "Palestine"
    assert ff.classify_region("Gaza Strip") == "Gaza Strip"
    assert ff.classify_region("East Jerusalem") == "East Jerusalem"
    assert ff.classify_region("Lebanon") == "Palestine"      # v1's fall-through
    assert ff.classify_region(None) == "Palestine"


def test_a_missing_donor_or_recipient_reads_as_v1_named_it():
    assert ff.flow_record(FLOW["124783"], AT)["funding"]["donor"] == {
        "name": "Unknown donor", "type": None}
    assert ff.flow_record(FLOW["125236"], AT)["funding"]["recipient"] == {
        "name": "Unknown recipient", "type": None}


def test_a_flow_with_no_date_is_skipped_not_stamped_with_the_fetch_day():
    flow = dict(FLOW["401966"], date=None, createdAt=None,
                firstReportedDate=None, decisionDate=None)
    assert ff.flow_record(flow, AT) == "undated"
    # v1's order: date, then createdAt, then first reported, then decision
    flow = dict(FLOW["401966"], date=None, createdAt="2026-10-08T09:00:00.000Z")
    assert ff.flow_record(flow, AT)["date"] == "2026-10-08"
    flow = dict(FLOW["401966"], date="not a date", createdAt=None,
                firstReportedDate=None, decisionDate="2026-09-30T00:00:00Z")
    assert ff.flow_record(flow, AT)["date"] == "2026-09-30"


def test_a_flow_filed_under_two_usage_years_is_one_record():
    recs, summary = ff.build(FLOWS, AT)
    ids = [r["funding"]["flow_id"] for r in recs]
    assert ids.count("359611") == 1 and len(ids) == len(set(ids))
    assert summary["rows_returned"] == 10 and summary["flows"] == 9
    assert summary["records"] == 7 and summary["skipped_no_amount"] == 2
    assert summary["skipped_undated"] == 0
    assert summary["years"] == [2015, 2026]
    assert summary["data_through"] == "2026-10-10"
    # the vintage is the publisher's own newest change, not the fetch time
    assert summary["newest_flow_update"] == max(f["updatedAt"] for f in FLOW.values())
    assert {r["stable_id"] for r in recs} == {f"fts-flow-{i}" for i in ids}


def _pager(flows, per_page=2, count=None):
    """An FTS that answers `per_page` flows a page and links the next one."""
    calls = []

    def get(url):
        calls.append(url)
        page = int(url.split("page=")[1]) if "page=" in url else 1
        chunk = flows[(page - 1) * per_page: page * per_page]
        more = page * per_page < len(flows)
        return json.dumps({"status": "ok", "data": {"flows": chunk}, "meta": {
            "count": len(flows) if count is None else count,
            "nextLink": f"{ff.year_url(2026)}&page={page + 1}" if more else None}}).encode()
    return get, calls


def test_paging_follows_next_link_and_archives_every_page():
    get, calls = _pager(FLOWS[2026])
    kept = []
    got = ff.fetch_year(2026, get=get, archive=lambda url, body: kept.append(url))
    assert [str(f["id"]) for f in got] == ["359611", "402264", "390239"]
    assert calls[0] == ("https://api.hpc.tools/v1/public/fts/flow"
                        "?countryISO3=PSE&year=2026&limit=200")
    assert len(calls) == 2 and kept == calls


def test_a_year_that_comes_back_short_refuses_the_fetch():
    get, _ = _pager(FLOWS[2026], count=5)
    with pytest.raises(ff.ShortYear, match="returned 3 flows, FTS counts 5"):
        ff.fetch_year(2026, get=get)
    assert issubclass(ff.ShortYear, fl.FetchRefused)


# ── FTS: the identity and the content the store already holds ────────────────

UNCHANGED = ("124783", "125236", "152896", "160700", "401966", "402264")


def test_a_fetched_flow_keeps_the_identity_and_the_content_the_store_holds():
    spec = load_spec("funding")
    for fid in UNCHANGED:
        rec = ff.flow_record(FLOW[fid], AT)
        (row,) = databank.t_funding(rec, spec, PLACES, Counter())
        held = FTS_HELD[fid]
        key = identity_key_for(spec["identity"], row.dataset_key,
                               indicator=row.indicator, occurred_at=row.occurred_at,
                               place_id=row.place_id, value_num=row.value_num,
                               attrs=row.attrs)
        assert key == held["identity_key"], fid
        assert _row_content(row) == _held_content(held), fid
        assert row.v1_stable_id == f"fts-flow-{fid}"


def test_a_revised_flow_keeps_its_number_under_a_new_identity():
    """FTS moved flow 359611 from 2025-08-27 to 2026-10-07 on 2026-10-12, twelve
    hours after v1 fetched it. The date is in the identity, so the new reading
    is a new row; `revises_by: flow_id` is what closes the old one."""
    spec = load_spec("funding")
    assert spec["identity"]["revises_by"] == "flow_id"
    (row,) = databank.t_funding(ff.flow_record(FLOW["359611"], AT), spec, PLACES, Counter())
    held = FTS_HELD["359611"]
    key = identity_key_for(spec["identity"], row.dataset_key, indicator=row.indicator,
                           occurred_at=row.occurred_at, place_id=row.place_id,
                           value_num=row.value_num, attrs=row.attrs)
    assert held["identity_key"] == "v1_funding_unfts|funding.commitment|2025-08-27||359611"
    assert key == "v1_funding_unfts|funding.commitment|2026-10-07||359611"
    assert row.attrs["flow_id"] == held["attrs"]["flow_id"] == "359611"


def test_a_held_flow_fts_now_reports_negative_is_left_alone_not_closed():
    """390239 is held from an earlier night with a positive amount. Tonight it
    is no record, so its number is not emitted and nothing revises it."""
    assert "390239" in FTS_HELD
    recs, _ = ff.build(FLOWS, AT)
    assert "390239" not in {r["funding"]["flow_id"] for r in recs}


# ── FTS: the run ─────────────────────────────────────────────────────────────

def _offline(monkeypatch, tmp_path, floor):
    ledger = tmp_path / "fetch-events.ndjson"
    out = tmp_path / "raw" / "fts" / "flows.json"
    monkeypatch.setattr(fl, "EVENTS", ledger)
    monkeypatch.setattr(ff, "OUT", out)
    monkeypatch.setattr(ff, "FLOOR", floor)
    monkeypatch.setattr(ff, "fetch_year",
                        lambda year, get=None, archive=None: FLOWS.get(year, []))
    return ledger, out


def test_a_dry_run_writes_no_file_and_no_ledger_line(monkeypatch, tmp_path):
    ledger, out = _offline(monkeypatch, tmp_path, floor=5)
    stage = tmp_path / "stage"
    assert ff.main(["--dry-run", "--stage", str(stage)]) == 0
    assert not out.exists() and not ledger.exists()
    doc = json.loads((stage / "flows.json").read_text())
    meta = doc["metadata"]
    assert len(doc["data"]) == 7 == meta["records"]
    assert meta["vintage"] == max(f["updatedAt"] for f in FLOW.values())
    assert meta["vintage_basis"] and meta["vintage_url"].startswith("https://api.hpc.tools/")
    assert meta["license_url"] == "https://fts.unocha.org/content/terms-use"
    assert "usage years 2015" in meta["window"]


def test_a_fetch_below_the_floor_is_refused_and_yesterdays_file_stands(monkeypatch, tmp_path):
    ledger, out = _offline(monkeypatch, tmp_path, floor=9300)
    out.parent.mkdir(parents=True)
    out.write_text('{"data": ["yesterday"]}')
    monkeypatch.setattr("ingest.bronze.put", lambda *a, **k: None)
    assert ff.main([]) == 1
    assert json.loads(out.read_text()) == {"data": ["yesterday"]}
    assert json.loads(ledger.read_text())["outcome"] == "refused"
    # the same refusal as a rehearsal leaves no trace in the ledger
    ledger.unlink()
    assert ff.main(["--dry-run"]) == 1
    assert not ledger.exists()


# ── IDMC: one CSV row → the record t_refugees reads ──────────────────────────

ROWS = fi.parse_csv((FX / "idmc_events.csv").read_bytes())
ROW = {r["id"]: r for r in ROWS}
ADMIN2 = fi.admin2_features(fx("admin2_thinned.geojson"))


def test_an_event_becomes_the_record_v1_wrote():
    rec = fi.event_record(ROW["512433"], ADMIN2, AT)
    assert rec["stable_id"] == rec["id"] == "idmc-512433"
    assert rec["date"] == "2026-07-31"
    assert rec["location"] == {
        "name": "West Bank, Palestinian Territories", "governorate": None,
        "region": "West Bank", "lat": 31.94697, "lon": 35.273869,
        "precision": "region", "admin1": "West Bank", "admin2": "Ramallah",
        "admin2_pcode": "PS0130"}
    assert rec["metrics"] == {"displaced": 445, "affected": 445, "count": 445,
                              "value": 445, "unit": "persons"}
    assert rec["event_name"] == "Palestine: Unclear/Unknown - West Bank - 01/07/2026"
    assert rec["displacement_category"] == ""
    assert rec["sources"][0]["name"] == "IDMC"
    # IDMC's own words for how precise the point is stay in the raw record
    assert rec["idmc"]["locations_accuracy"] == "District/Zone/Department (ADM2)"


def test_a_point_in_no_governorate_gets_no_admin2():
    rec = fi.event_record(ROW["512435"], ADMIN2, AT)
    assert (rec["location"]["lat"], rec["location"]["lon"]) == (31.46242, 34.27496)
    assert "admin2" not in rec["location"] and "admin2_pcode" not in rec["location"]
    assert rec["location"]["region"] == "Gaza Strip"       # v1's bounding box


def test_point_in_polygon_is_v1s_rule_holes_out_first_polygon_wins():
    square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    feats = fi.admin2_features({"features": [
        {"properties": {"adm1_name": "A", "adm2_name": "outer", "adm2_pcode": "P1"},
         "geometry": {"type": "Polygon", "coordinates": [square, hole]}},
        {"properties": {"adm1_name": "A", "adm2_name": "island", "adm2_pcode": "P2"},
         "geometry": {"type": "MultiPolygon", "coordinates": [[hole]]}}]})
    assert fi.point_to_admin(feats, 1, 1)["admin2"] == "outer"
    assert fi.point_to_admin(feats, 5, 5) == {"admin1": "A", "admin2": "island",
                                              "admin2_pcode": "P2"}
    assert fi.point_to_admin(feats, 20, 20) is None
    assert fi.point_to_admin(feats, None, 5) is None


def test_rows_idmc_gave_no_id_or_no_date_are_not_events():
    assert fi.event_record(dict(ROW["512433"], id=""), ADMIN2, AT) is None
    assert fi.event_record(dict(ROW["512433"], displacement_date=""), ADMIN2, AT) is None
    recs, summary = fi.build(ROWS + [dict(ROW["512433"], id="")], ADMIN2, AT)
    assert summary["rows"] == 8 and summary["records"] == 7 == len(recs)
    assert summary["with_admin2"] == 6
    assert (summary["data_from"], summary["data_through"]) == ("2025-09-01", "2026-07-31")
    assert summary["newest_row_created_at"] == max(r["created_at"] for r in ROWS)


def test_an_hxl_tag_row_is_not_data():
    raw = (FX / "idmc_events.csv").read_bytes()
    head, rest = raw.split(b"\n", 1)
    tagged = head + b"\n" + b"#meta+id" + b"," * head.count(b",") + b"\n" + rest
    assert [r["id"] for r in fi.parse_csv(tagged)] == [r["id"] for r in ROWS]


def test_cells_are_read_the_way_v1_read_them():
    assert fi._int("445") == 445 and fi._int("12.9") == 12 and fi._int("") == 0
    assert fi._int("n/a") == 0
    assert fi._float("31.94697") == 31.94697 and fi._float("") is None
    assert fi.region_from_coords(31.5, 34.45) == "Gaza Strip"
    assert fi.region_from_coords(32.2, 35.25) == "West Bank"
    assert fi.region_from_coords(None, 35.0) == "Palestine"


def _idmc_key(spec, row):
    ident = next(d for d in spec["datasets"]
                 if d["key"] == "v1_refugees_idmc")["overrides"]["identity"]
    return identity_key_for(ident, row.dataset_key, indicator=row.indicator,
                            occurred_at=row.occurred_at, place_id=row.place_id,
                            value_num=row.value_num, attrs=row.attrs)


def test_a_fetched_event_keeps_the_identity_and_the_content_the_store_holds():
    spec = load_spec("refugees")
    held = {h["identity_key"]: h for h in IDMC_HELD["rows"]}
    assert len(held) == 6
    seen = Counter()
    for raw in ROWS:
        (row,) = databank.t_refugees(fi.event_record(raw, ADMIN2, AT), spec, PLACES, Counter())
        key = _idmc_key(spec, row)
        assert key in held, raw["id"]
        assert _row_content(row) == _held_content(held[key]), raw["id"]
        assert row.precision == held[key]["precision"], raw["id"]
        assert row.v1_stable_id == f"idmc-{raw['id']}"
        seen[key] += 1
    # IDMC publishes one Nur Shams displacement twice (ids 191547 and 192631):
    # two records, one identity — the collision the spec declares, still one.
    assert sorted(seen.values()) == [1, 1, 1, 1, 1, 2]
    twice = next(k for k, n in seen.items() if n == 2)
    assert "|2025-09-01|" in twice and "|106.0|" in twice


def test_a_year_end_event_is_a_year_not_a_december_day():
    spec = load_spec("refugees")
    (row,) = databank.t_refugees(fi.event_record(ROW["224901"], ADMIN2, AT), spec, PLACES, Counter())
    assert ROW["224901"]["displacement_date"] == "2025-12-31"
    assert (row.occurred_at, row.precision) == ("2025-01-01", "year")


# ── IDMC: the polygons and the run ───────────────────────────────────────────

def _hdx_admin(modified="2026-01-26T16:09:19.703104", fail=False):
    """A stand-in for HDX's cod-ab-pse package and its geojson zip."""
    import io
    import urllib.error
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pse_admin0.geojson", '{"features": []}')
        z.writestr("pse_admin2.geojson", (FX / "admin2_thinned.geojson").read_text())
    calls = []

    def get_json(url, timeout=0):
        calls.append("package")
        if fail:
            raise urllib.error.URLError("HDX is down")
        return {"result": {"license_title": "CC BY-IGO", "resources": [
            {"format": "XLSX", "url": "https://hdx.test/x.xlsx"},
            {"format": "GeoJSON", "url": "https://hdx.test/b.zip", "last_modified": modified}]}}

    def get(url, timeout=0):
        calls.append("zip")
        return buf.getvalue()
    return get, get_json, calls


def test_the_polygons_are_downloaded_once_and_again_only_when_hdx_changes_them(monkeypatch, tmp_path):
    monkeypatch.setattr(fi, "ADMIN_CACHE", tmp_path / "cod_ab" / "admin2.json")
    get, get_json, calls = _hdx_admin()
    feats, stamp = fi.admin_polygons(get, get_json)
    assert len(feats) == 16 and stamp["layer"] == "pse_admin2.geojson"
    assert calls == ["package", "zip"]
    assert fi.point_to_admin(feats, 31.94697, 35.273869)["admin2"] == "Ramallah"
    fi.admin_polygons(get, get_json)                       # same file on HDX
    assert calls == ["package", "zip", "package"]
    get, get_json, calls = _hdx_admin(modified="2027-02-01T00:00:00")
    fi.admin_polygons(get, get_json)                       # HDX replaced it
    assert calls == ["package", "zip"]
    assert json.loads(fi.ADMIN_CACHE.read_text())["stamp"]["hdx_modified"] == "2027-02-01T00:00:00"


def test_without_polygons_the_fetch_is_refused_and_with_a_cache_it_goes_on(monkeypatch, tmp_path):
    monkeypatch.setattr(fi, "ADMIN_CACHE", tmp_path / "cod_ab" / "admin2.json")
    get, get_json, _ = _hdx_admin(fail=True)
    with pytest.raises(fl.FetchRefused, match="no admin-2 polygons"):
        fi.admin_polygons(get, get_json)
    ok_get, ok_json, _ = _hdx_admin()
    fi.admin_polygons(ok_get, ok_json)
    feats, _stamp = fi.admin_polygons(get, get_json)       # HDX down, cache held
    assert len(feats) == 16
    # a dry run leaves the cache as it found it
    fi.ADMIN_CACHE.unlink()
    fi.admin_polygons(ok_get, ok_json, write_cache=False)
    assert not fi.ADMIN_CACHE.exists()


def _offline_idmc(monkeypatch, tmp_path):
    ledger = tmp_path / "fetch-events.ndjson"
    raw = tmp_path / "raw" / "refugees"
    monkeypatch.setattr(fl, "EVENTS", ledger)
    monkeypatch.setattr(fi, "OUT", raw / "idmc.json")
    monkeypatch.setattr(fi, "CARRIED", raw / "carried.json")
    monkeypatch.setattr(fl, "get_json", lambda url, timeout=0: {"result": {
        "license_id": "cc-by-igo",
        "license_title": "Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO)",
        "dataset_date": "[2025-01-01T00:00:00 TO 2026-07-31T23:59:59]",
        "resources": [{"format": "CSV", "name": "pse_idmc_idu_events.csv",
                       "url": "https://hdx.test/idmc.csv",
                       "last_modified": "2026-09-17T11:23:55.236911"}]}})
    monkeypatch.setattr(fl, "get", lambda url, timeout=0: (FX / "idmc_events.csv").read_bytes())
    monkeypatch.setattr(fi, "admin_polygons",
                        lambda write_cache=True: (ADMIN2, {"hdx_modified": "2026-01-26"}))
    return ledger, raw


def test_an_idmc_dry_run_writes_nothing_and_stages_both_files(monkeypatch, tmp_path):
    ledger, raw = _offline_idmc(monkeypatch, tmp_path)
    monkeypatch.setattr(fi, "FLOOR", 5)
    stage = tmp_path / "stage"
    assert fi.main(["--dry-run", "--stage", str(stage)]) == 0
    assert not raw.exists() and not ledger.exists()
    meta = json.loads((stage / "idmc.json").read_text())["metadata"]
    assert meta["vintage"] == "2026-09-17T11:23:55.236911"
    assert meta["vintage_basis"] == "HDX `last_modified` of the CSV resource"
    assert meta["vintage_url"] == "https://data.humdata.org/dataset/pse-idmc-idu-events"
    assert meta["license_id"] == "cc-by-igo" and meta["records"] == 7
    assert len(json.loads((stage / "carried.json").read_text())["data"]) == 1232


def test_a_real_run_writes_the_events_then_the_carried_records(monkeypatch, tmp_path):
    ledger, raw = _offline_idmc(monkeypatch, tmp_path)
    monkeypatch.setattr(fi, "FLOOR", 5)

    class _Ref:
        ref = "bronze://idmc_idu/test"
    monkeypatch.setattr("ingest.bronze.put", lambda *a, **k: _Ref())
    assert fi.main([]) == 0
    assert [r["id"] for r in json.loads((raw / "idmc.json").read_text())["data"]] == [
        f"idmc-{r['id']}" for r in ROWS]
    assert len(json.loads((raw / "carried.json").read_text())["data"]) == 1232
    line = json.loads(ledger.read_text())
    assert (line["label"], line["outcome"], line["rows"], line["carried"]) == (
        "idmc:events", "ok", 7, 1232)


def test_a_short_idmc_file_is_refused_and_nothing_is_carried_on_its_own(monkeypatch, tmp_path):
    """Seven events against the floor of 300. No idmc.json means no
    carried.json either: the loader must find neither and read the fallback."""
    ledger, raw = _offline_idmc(monkeypatch, tmp_path)
    assert fi.main([]) == 1
    assert not (raw / "idmc.json").exists() and not (raw / "carried.json").exists()
    assert json.loads(ledger.read_text())["outcome"] == "refused"


# ── the two datasets nobody fetches ──────────────────────────────────────────

def test_the_carried_records_are_the_frozen_non_idmc_records_unchanged():
    doc = fi.carried_doc()
    frozen = json.loads(gzip.decompress(fi.FROZEN.read_bytes()))["data"]
    want = [r for r in frozen if r["sources"][0]["name"] != "IDMC"]
    assert doc["data"] == want and len(want) == 1232
    names = Counter(r["sources"][0]["name"] for r in doc["data"])
    assert names == {"UNHCR Operational Data Portal": 1157, "UNRWA camp registry": 75}
    ds = doc["metadata"]["datasets"]
    assert ds["v1_refugees_unhcr"]["records"] == 1157
    assert ds["v1_refugees_unrwa"]["records"] == 75
    for d in ds.values():
        assert d["vintage"] and d["vintage_basis"] and d["vintage_url"].startswith("https://")
    # the camp rows say what they are: a Wikipedia table, not a UNRWA release
    assert "oldid=1356227162" in ds["v1_refugees_unrwa"]["vintage_url"]
    assert "Not a UNRWA release" in ds["v1_refugees_unrwa"]["attribution"]


def test_carried_is_written_once_and_again_only_when_the_frozen_corpus_changes(monkeypatch, tmp_path):
    carried = tmp_path / "raw" / "refugees" / "carried.json"
    monkeypatch.setattr(fi, "CARRIED", carried)
    assert fi.ensure_carried() == 1232
    first = carried.stat().st_mtime_ns
    assert fi.ensure_carried() == 1232
    assert carried.stat().st_mtime_ns == first
    doc = json.loads(carried.read_text())
    doc["metadata"]["frozen_sha256"] = "an older corpus"
    carried.write_text(json.dumps(doc))
    assert fi.ensure_carried() == 1232
    assert json.loads(carried.read_text())["metadata"]["frozen_sha256"] != "an older corpus"


# ── the specs ────────────────────────────────────────────────────────────────

def test_funding_reads_the_fetch_and_falls_back_to_the_frozen_copy():
    spec = load_spec("funding")
    assert spec["input"] == {"root": "data/raw/fts", "glob": "flows.json",
                             "fallback": {"root": "data/frozen", "glob": "funding.json.gz"}}
    assert spec.get("cadence") == "daily"
    assert ff.OUT == ROOT / "data" / "raw" / "fts" / "flows.json"
    assert spec["transform"] == "engine" or databank.TRANSFORMERS["funding"] is databank.t_funding


def test_refugees_reads_both_files_and_falls_back_to_the_frozen_copy():
    spec = load_spec("refugees")
    assert spec["input"] == {"root": "data/raw/refugees",
                             "glob": ["idmc.json", "carried.json"],
                             "fallback": {"root": "data/frozen", "glob": "refugees.json.gz"}}
    assert spec.get("cadence") == "daily"
    assert (fi.OUT, fi.CARRIED) == (ROOT / "data/raw/refugees/idmc.json",
                                    ROOT / "data/raw/refugees/carried.json")
    assert fi.FLOOR == next(d for d in spec["datasets"] if d["key"] == "v1_refugees_idmc"
                            )["overrides"]["expect"]["min_records"]


def test_neither_spec_reaches_for_v1(monkeypatch):
    monkeypatch.setattr(databank, "V1_UNIFIED", Path("/nonexistent/v1-is-gone"))
    for cat in ("funding", "refugees"):
        files = list(databank.iter_v1_files(cat, load_spec(cat)))
        assert files, cat
        assert all(ROOT in f.parents for f in files), cat


def test_a_machine_that_never_fetched_reads_the_fallback_whole(tmp_path):
    """The fallback fires only when NO input file exists. That is why the
    fetcher carries the unfetched datasets into data/raw/refugees itself
    rather than the spec naming the frozen corpus beside the fetch."""
    spec = load_spec("refugees")
    spec = dict(spec, input=dict(spec["input"], root=str(tmp_path / "raw")))
    assert databank.reads_fallback(spec)
    assert [f.name for f in databank.iter_v1_files("refugees", spec)] == ["refugees.json.gz"]
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "idmc.json").write_text('{"data": []}')
    (tmp_path / "raw" / "carried.json").write_text('{"data": []}')
    assert not databank.reads_fallback(spec)
    assert [f.name for f in databank.iter_v1_files("refugees", spec)] == ["idmc.json",
                                                                          "carried.json"]


def test_the_frozen_copies_hold_what_the_manifest_says():
    manifest = json.loads((ROOT / "data" / "frozen" / "manifest.json").read_text())
    funding = json.loads(gzip.decompress((ROOT / "data/frozen/funding.json.gz").read_bytes()))["data"]
    assert len(funding) == manifest["funding"]["records"] == 10341
    assert len({r["funding"]["flow_id"] for r in funding}) == 10341
    assert {r["sources"][0]["name"] for r in funding} == {"UN OCHA Financial Tracking Service"}
    refugees = json.loads(gzip.decompress((ROOT / "data/frozen/refugees.json.gz").read_bytes()))["data"]
    assert len(refugees) == manifest["refugees"]["records"] == 1571
    assert Counter(r["sources"][0]["name"] for r in refugees) == {
        "UNHCR Operational Data Portal": 1157, "IDMC": 339, "UNRWA camp registry": 75}
