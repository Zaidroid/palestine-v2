"""Migration 135 and ops/load_job_returns.py: the reviewed returns of jobs
03, 04 and 05 (2026-10-19). Pure tests run anywhere; the store tests skip
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
