"""Migrations 135 and 136 and ops/load_job_returns.py: the reviewed returns of jobs
03, 04 and 05 (2026-10-19) and 06 (2026-10-20). Pure tests run anywhere; the store tests skip
until the migration is applied and the loader has run."""
from __future__ import annotations

import json

import pytest

from ops import load_job_returns as L


def test_job03_keeps_pre_dashboard_months_and_maps_products(monkeypatch, tmp_path):
    d = tmp_path / "03"; d.mkdir()
    rows = [{"period": "2012-01", "region": "West Bank", "product": "gasoline_95", "value": 6.88, "unit": "ILS_per_litre", "source_file": "a.pdf", "table": "Table 8", "page": 9, "quote": "Jan 6.60 6.88 10.0 6.60 70.17", "confidence": "sure"},
            {"period": "2012-01", "region": "West Bank", "product": "coal", "value": 10.0, "unit": "ILS_per_kg", "source_file": "a.pdf", "table": "Table 8", "page": 9, "quote": "…", "confidence": "sure"},
            {"period": "2019-01", "region": "Jerusalem", "product": "diesel", "value": 6.0, "unit": "ILS_per_litre", "source_file": "b.pdf", "table": "Table 11", "page": 12, "quote": "…", "confidence": "sure"},
            {"period": "2014-12", "region": "Jerusalem", "product": "lpg_12kg", "value": 66.25, "unit": "ILS_per_cylinder", "source_file": "c.pdf", "table": "Table 9", "page": 10, "quote": "…", "confidence": "sure"}]
    (d / "pcbs_fuel_monthly.ndjson").write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(L, "JOBS", tmp_path)
    ds, obs = L.job03("2026-10-19T00:00:00+00:00")
    assert ds == "pcbs_fuel_monthly"
    got = {(o["indicator"], o["place_id"], o["occurred"].date().isoformat()): (o["value"], o["unit"]) for o in obs}
    assert got == {("fuel.price.average.gasoline_95", 2, "2012-01-01"): (6.88, "ILS/L"),
                   ("fuel.price.average.lpg_12kg_delivered", 11, "2014-12-01"): (66.25, "ILS/cylinder")}   # coal and 2019 left out
    assert obs[0]["stable"] == "pcbs_fuel_monthly:tables:gasoline_95:west-bank:2012-01"


def test_job04_loads_kept_and_fixed_rows_only(monkeypatch, tmp_path):
    d = tmp_path / "04"; d.mkdir()
    units = [{"doc_id": 1, "date": "2020-10-14", "source": "s", "url": "u", "stage": "approval", "units": 2166, "region": "West Bank", "verdict": "keep", "quote": "q", "doc_ids": [1]},
             {"doc_id": 2, "date": "2010-03-09", "source": "s", "url": "u", "stage": "approval", "units": 1600, "region": "East Jerusalem", "settlement_other": "رمات شلومو", "verdict": "fix", "quote": "q", "doc_ids": [2]},
             {"doc_id": 3, "date": "2015-01-01", "source": "s", "url": "u", "stage": "plan", "units": 300, "region": "West Bank", "verdict": "drop", "quote": "q", "doc_ids": [3]}]
    outs = [{"doc_id": 9, "date": "2023-07-01", "published": "2023-07-01", "source": "s", "url": "u", "place_id": 1234, "place_en": "al-Mughayyir", "governorate": "Ramallah", "verdict": "keep", "quote": "q", "doc_ids": [9]},
            {"doc_id": 10, "date": "2021-11-23", "published": "2021-11-23", "source": "s", "url": "u", "place_id": None, "governorate": "Jericho", "verdict": "fix", "quote": "q", "doc_ids": [10]},
            {"doc_id": 11, "date": "2021-11-24", "published": "2021-11-24", "source": "s", "url": "u", "place_id": None, "governorate": None, "verdict": "drop", "quote": "q", "doc_ids": [11]}]
    (d / "events-units.reviewed.ndjson").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in units))
    (d / "events-outposts.reviewed.ndjson").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in outs))
    monkeypatch.setattr(L, "JOBS", tmp_path)
    ds, obs = L.job04("2026-10-19T00:00:00+00:00")
    assert ds == "settlements_press_events"
    units_obs = [o for o in obs if o["indicator"] == "settlements.units_announced"]
    assert [(o["value"], o["place_id"]) for o in units_obs] == [(2166.0, 2), (1600.0, 11)]
    outs_obs = [o for o in obs if o["indicator"] == "settlements.outpost_reported"]
    assert [(o["value"], o["place_id"]) for o in outs_obs] == [(1.0, 1234), (1.0, 10)]          # the village, else the governorate


def test_job05_loads_statements_with_hours_on_their_area(monkeypatch, tmp_path):
    d = tmp_path / "05"; d.mkdir()
    rows = [{"doc_id": 5, "doc_ids": [5], "published_at": "2014-12-27", "as_of": "2014-12-27", "date_basis": "published", "publisher": "p", "url": "u", "quote": "6 وصل و12 قطع", "hours_on": 6, "hours_off": 12, "hours_per_day": 8.0, "kind": "rota", "area": "Gaza Strip", "authority_named": "GEDCO", "confidence": "sure"},
            {"doc_id": 6, "doc_ids": [6], "published_at": "2016-04-24", "as_of": "2016-04-24", "date_basis": "published", "publisher": "p", "url": "u", "quote": "6 وصل مقابل 8 قطع في غزة", "hours_on": 6, "hours_off": 8, "hours_per_day": 10.29, "kind": "rota", "area": "Gaza City", "authority_named": None, "confidence": "sure"},
            {"doc_id": 7, "doc_ids": [7], "published_at": "2015-01-04", "as_of": "2015-01-04", "date_basis": "published", "publisher": "p", "url": "u", "quote": "انقطاع", "hours_on": None, "hours_off": 12, "hours_per_day": None, "kind": "outage", "area": "Gaza Strip", "authority_named": None, "confidence": "sure"}]
    (d / "rota_statements.ndjson").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    monkeypatch.setattr(L, "JOBS", tmp_path)
    ds, obs = L.job05("2026-10-19T00:00:00+00:00")
    assert ds == "gaza_electricity_rota_press"
    assert [(o["value"], o["place_id"]) for o in obs] == [(8.0, 1), (10.29, 15)]                 # the outage has no hours and is not loaded



def _gz(path, rows):
    import gzip
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def test_job06_loads_only_the_reviewed_rows_and_places_them(monkeypatch, tmp_path):
    d = tmp_path / "06" / "reviewed"; d.mkdir(parents=True)
    _gz(d / "trees_uprooted.ndjson.gz", [
        {"doc_id": 1, "date": "2026-10-18T10:00:00+00:00", "publisher": "web:wafa", "url": "u1", "family": "trees_uprooted", "printed": "120", "quote": "مستعمرون يقطعون 120 شجرة زيتون في كيسان", "doc_ids": [1], "verdict": "keep"},
        {"doc_id": 2, "date": "2026-10-11T00:00:00+00:00", "publisher": "web:wafa", "url": "u2", "family": "trees_uprooted", "printed": "50", "quote": "اقتلاع أكثر من 50 شجرة زيتون في بلدة قصرة", "doc_ids": [2], "verdict": "keep"},
        {"doc_id": 2, "date": "2026-10-11T00:00:00+00:00", "publisher": "web:wafa", "url": "u2", "family": "trees_uprooted", "printed": "26.395", "quote": "بينها 26.395 شجرة زيتون", "doc_ids": [2], "verdict": "keep"},
        {"doc_id": 3, "date": "2026-07-06T00:00:00+00:00", "publisher": "web:wafa", "url": "u3", "family": "trees_uprooted", "printed": "26395", "quote": "45195 شجرة منها 26395 شجرة زيتون", "doc_ids": [3], "verdict": "keep"},
        {"doc_id": 9, "date": "2026-05-06T00:00:00+00:00", "publisher": "tg:khalelnews", "url": None, "family": "trees_uprooted", "printed": "40 ألف", "quote": "يبدأ باقتلاع نحو 40 ألف شجرة عنب", "doc_ids": [9], "verdict": "keep"}])
    _gz(d / "land_orders.ndjson.gz", [
        {"doc_id": 4, "date": "2026-09-10T00:00:00+00:00", "publisher": "tg:alqastalps", "url": "u4", "family": "land_orders", "printed": "160", "quote": "مصادرة 160 دونمًا من أراضي بلدة جيوس إضافة إلى 21 دونمًا من أراضي بلدة إماتين", "doc_ids": [4], "verdict": "keep"},
        {"doc_id": 5, "date": "2026-07-21T00:00:00+00:00", "publisher": "tg:alkofiyatv", "url": "u5", "family": "land_orders", "printed": "5.283", "quote": "وضع اليد على 5.283 دونمًا من أراضي بلدة جبع", "doc_ids": [5], "verdict": "keep"}])
    _gz(d / "aid_trucks.ndjson.gz", [
        {"doc_id": 6, "date": "2026-05-27T00:00:00+00:00", "publisher": "web:maannews", "url": "u6", "family": "aid_trucks", "printed": "973", "quote": "دخل إلى قطاع غزة 49 ألفا و973 شاحنة مساعدات فقط من أصل 135 ألفا و600", "doc_ids": [6], "verdict": "keep"},
        {"doc_id": 7, "date": "2025-10-26T00:00:00+00:00", "publisher": "tg:alqastalps", "url": "u7", "family": "aid_trucks", "printed": "1500", "quote": "7 آلاف شاحنة دخلت القطاع بينها 1500 شاحنة مساعدات", "doc_ids": [7], "verdict": "keep"},
        {"doc_id": 10, "date": "2025-10-13T00:00:00+00:00", "publisher": "web:safa", "url": "u10", "family": "aid_trucks", "printed": "173", "quote": "173 شاحنة مساعدات دخلت غزة الأحد", "doc_ids": [10], "verdict": "keep"}])
    _gz(d / "cooking_gas.ndjson.gz", [
        {"doc_id": 8, "date": "2026-06-30T00:00:00+00:00", "publisher": "web:safa", "url": "u8", "family": "cooking_gas", "printed": "5", "quote": "دخول حمولة شاحنتين من غاز الطهي من أصل 5 شاحنات", "doc_ids": [8], "verdict": "keep"}])
    review = tmp_path / "review.yaml"
    review.write_text(json.dumps({
        "trees_incidents": [{"doc": 1, "trees": 120, "place": "كيسان", "gov": "Bethlehem", "actor": "settlers", "kind": "olive"},
                            {"doc": 2, "idx": 1, "trees": 50, "qualifier": "more_than", "place": "قصرة", "gov": "Nablus", "actor": "settlers", "kind": "olive"},
                            {"doc": 2, "idx": 1, "trees": 1, "place": "نوجد", "gov": "Nablus", "actor": "army", "kind": "olive", "note": "unknown village: lands on the governorate"}][:2] + [
                            {"doc": 1, "trees": 7, "place": "نوجد", "gov": "Nablus", "actor": "army", "kind": "olive"}],
        "trees_tallies": [{"doc": 3, "authority": "CWRC half-year", "from": "2026-01-01", "to": "2026-06-30", "precision": "day",
                           "rows": [{"measure": "all", "place": "West Bank", "trees": 45195}, {"measure": "olive", "place": "West Bank", "trees": 26395}, {"measure": "all", "place": "Hebron", "trees": 16617}]}],
        "land_orders": [{"doc": 4, "dunums": 160, "place": "جيوس", "gov": "Qalqilya", "kind": "order"},
                        {"doc": 4, "n": 2, "dunums": 21, "place": "إماتين", "gov": "Qalqilya", "kind": "order"},
                        {"doc": 5, "dunums": 5.283, "place": "جبع", "gov": "Jerusalem", "kind": "order"}],
        "gaza_trucks": [{"doc": 6, "as_of": "2026-05-27", "entered": 49973, "agreed": 135600, "scope": "all"},
                        {"doc": 7, "as_of": "2025-10-26", "entered": 7000, "agreed": None, "scope": "all", "aid": 1500}],
        "gaza_aid_trucks_day": [{"doc": 10, "day": "2025-10-12", "aid": 173, "total": None}],
        "gaza_cooking_gas": [{"doc": 8, "trucks": 2}],
        "dropped": {"trees_uprooted": {"9": "unverified"}}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(L, "JOBS", tmp_path); monkeypatch.setattr(L, "REVIEW06", review)
    places = {("كيسان", "Bethlehem"): 989, ("قصرة", "Nablus"): 298, ("جيوس", "Qalqilya"): 89, ("إماتين", "Qalqilya"): 578, ("جبع", "Jerusalem"): 570}
    got = dict(L.job06("2026-10-20T00:00:00+00:00", places=places))
    ev = got["settlements_press_events"]
    trees = [(o["value"], o["place_id"], o["occurred"].date().isoformat()) for o in ev if o["indicator"] == "settlements.trees_uprooted_reported"]
    assert trees == [(120.0, 989, "2026-10-18"), (50.0, 298, "2026-10-11"), (7.0, 6, "2026-10-18")]   # the unknown village lands on the governorate
    assert json.loads(ev[1]["attrs"])["quote"].startswith("اقتلاع أكثر من 50")                      # idx picks the row, not the 26.395 one
    assert json.loads(ev[1]["attrs"])["qualifier"] == "more than"
    assert "40 ألف" not in json.dumps([o["attrs"] for o in ev])                                       # the dropped document is not loaded
    land = [(o["value"], o["place_id"], o["stable"]) for o in ev if o["indicator"] == "settlements.land_seizure_order_reported"]
    assert land == [(160.0, 89, "settlements_press_events:land:4:1"), (21.0, 578, "settlements_press_events:land:4:2"), (5.283, 570, "settlements_press_events:land:5:1")]
    tal = [(o["indicator"].split(".")[-1], o["value"], o["place_id"], o["precision"], o["occurred"].date().isoformat()) for o in got["settlements_press_tallies"]]
    assert tal == [("trees_damaged_stated", 45195.0, 2, "day", "2026-01-01"), ("trees_damaged_olive_stated", 26395.0, 2, "day", "2026-01-01"), ("trees_damaged_stated", 16617.0, 13, "day", "2026-01-01")]
    assert json.loads(got["settlements_press_tallies"][0]["attrs"])["period_to"] == "2026-06-30"
    sup = [(o["indicator"].split(".")[-1], o["value"], o["occurred"].date().isoformat()) for o in got["gaza_supply_press"]]
    assert sup == [("ceasefire_trucks_entered_cumulative", 49973.0, "2026-05-27"), ("ceasefire_trucks_agreed_cumulative", 135600.0, "2026-05-27"),
                   ("ceasefire_trucks_entered_cumulative", 7000.0, "2025-10-26"),                   # no agreed figure → no agreed row
                   ("aid_trucks_entered_day_stated", 173.0, "2025-10-12"), ("cooking_gas_trucks_entered", 2.0, "2026-06-30")]
    assert all(o["place_id"] == 1 for o in got["gaza_supply_press"])
    assert json.loads(got["gaza_supply_press"][2]["attrs"])["aid"] == 1500


def test_job06_refuses_a_document_missing_from_the_reviewed_file(monkeypatch, tmp_path):
    d = tmp_path / "06" / "reviewed"; d.mkdir(parents=True)
    _gz(d / "trees_uprooted.ndjson.gz", [{"doc_id": 1, "date": "2026-10-18T00:00:00+00:00", "publisher": "p", "url": None, "printed": "1", "quote": "q", "doc_ids": [1], "verdict": "keep"}])
    review = tmp_path / "review.yaml"
    review.write_text(json.dumps({"trees_incidents": [{"doc": 404, "trees": 1, "gov": "Nablus", "actor": "army", "kind": "olive"}]}), encoding="utf-8")
    monkeypatch.setattr(L, "JOBS", tmp_path); monkeypatch.setattr(L, "REVIEW06", review)
    with pytest.raises(SystemExit):
        L.job06("2026-10-20T00:00:00+00:00", places={})


def test_job06_review_file_matches_the_reviewed_rows():
    """The committed review names only documents DeepSeek's files hold, every tally place is a region
    or a governorate, and nothing listed as dropped is also loaded (needs data/raw/jobs/06)."""
    import yaml
    if not (L.JOBS / "06" / "reviewed" / "trees_uprooted.ndjson.gz").exists():
        pytest.skip("data/raw/jobs/06 is not on this machine")
    got = dict(L.job06("2026-10-20T00:00:00+00:00"))
    assert {k: len(v) for k, v in got.items()} == {"settlements_press_events": 63, "settlements_press_tallies": 39, "gaza_supply_press": 34}
    rv = yaml.safe_load(L.REVIEW06.read_text(encoding="utf-8"))
    loaded = {e["doc"] for k in ("trees_incidents", "land_orders", "gaza_trucks", "gaza_aid_trucks_day", "gaza_cooking_gas") for e in rv[k]} | {t["doc"] for t in rv["trees_tallies"]}
    # a key like 2364905#7 drops one row of a document whose other row is loaded; a bare key drops the document
    dropped = {int(k) for fam in rv["dropped"].values() if isinstance(fam, dict) for k in fam if "#" not in str(k)}
    assert not (loaded & dropped), loaded & dropped
    assert len(got["settlements_press_events"]) == len({o["stable"] for o in got["settlements_press_events"]})
    assert sum(1 for o in got["settlements_press_events"] if '"placed": "village"' in o["attrs"]) >= 45


@pytest.fixture
def db():
    try:
        from resolve.db import connect
        cm = connect(); c = cm.__enter__()
    except Exception as e:                                             # noqa: BLE001
        pytest.skip(f"no database here: {type(e).__name__}")
    try:
        c.execute("SET default_transaction_read_only = on"); yield c
    finally:
        cm.__exit__(None, None, None)


def test_returns_served(db):
    ds = db.execute("SELECT dataset_id FROM dataset WHERE key = 'settlements_press_events'").fetchone()
    if not ds:
        pytest.skip("migration 135 not applied")
    n = db.execute("SELECT count(*) FROM databank_serving WHERE dataset_key = 'settlements_press_events'").fetchone()[0]
    if not n:
        pytest.skip("not loaded yet")
    assert n >= 550
    fuel = db.execute("""SELECT min(occurred_at)::date::text, count(*) FROM databank_serving
                         WHERE dataset_key = 'pcbs_fuel_monthly' AND indicator = 'fuel.price.average.diesel' AND place_id = 2""").fetchone()
    assert fuel[0] == "2012-01-01" and fuel[1] >= 72 + 93                                        # the tables 2012, 2014–2018 (no 2013 table), then the dashboard
    jan12 = db.execute("""SELECT value_num FROM databank_serving WHERE dataset_key = 'pcbs_fuel_monthly'
                          AND indicator = 'fuel.price.average.gasoline_95' AND place_id = 2 AND occurred_at = '2012-01-01'""").fetchone()
    assert jan12 and float(jan12[0]) == 6.88
    rota = db.execute("SELECT count(*), min(occurred_at)::date::text FROM databank_serving WHERE dataset_key = 'gaza_electricity_rota_press'").fetchone()
    assert rota[0] >= 200 and rota[1] <= "2010-12-31"
