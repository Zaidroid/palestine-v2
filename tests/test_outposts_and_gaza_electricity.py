"""Migration 130: Peace Now's outposts by month and OCHA's daily Gaza
electricity table (2026-10-19). Pure tests run anywhere; the store tests
skip until the migration is applied and the loaders have run."""
from __future__ import annotations

import pytest

from ops import fetch_ocha_gaza_electricity as E
from ops import fetch_peacenow_outposts as P


# ── pure: the sheet ──────────────────────────────────────────────────────────

def test_established_reads_hebrew_month_and_two_digit_year():
    assert P.established("ינו-26", "2026") == ("2026-01", "month", None)
    assert P.established("יונ-96", "1996") == ("1996-06", "month", None)
    assert P.established("", "2019") == ("2019", "year", None)
    assert P.established("יונ-05", "1997") == ("1997", "year", "יונ-05")   # the year column wins, the cell is kept
    assert P.established("", "") is None


def test_parse_keeps_named_rows_and_maps_types():
    text = ("Name,Name Hebrew,DB_ID,Settlement Type,Established Year,Established,x (ITM),y (ITM),x (UTM),y(UTM),Nearest Settlemet,District,Municipality\n"
            "Har Ebal,הר עיבל,900,Farm Outpost,2026,ינו-26,1,2,32.25,35.27,Elon Moreh,Nablus,Shomron\n"
            "Hanekuda,הנקודה,255,Outpost,1996,יונ-96,1,2,32.17,35.32,Itamar,Nablus,Shomron\n"
            ",,1,Outpost,2020,,,,,,,,\n")
    rows = P.parse(text)
    assert [(r["name"], r["kind"], r["period"], r["precision"], r["district"]) for r in rows] == [
        ("Har Ebal", "farm", "2026-01", "month", "Nablus"), ("Hanekuda", "outpost", "1996-06", "month", "Nablus")]
    assert rows[0]["lat"] == 32.25 and rows[0]["lon"] == 35.27


def test_observations_one_row_per_outpost_and_a_count_per_governorate_month():
    rows = P.parse("Name,Name Hebrew,DB_ID,Settlement Type,Established Year,Established,x (ITM),y (ITM),x (UTM),y(UTM),Nearest Settlemet,District,Municipality\n"
                   "A,,1,Outpost,2025,מאי-25,,,,,,Yatta,\nB,,2,Farm Outpost,2025,מאי-25,,,,,,Hebron,\nC,,3,Outpost,2025,מאי-25,,,,,,,\n")
    obs = P.observations(rows, "2026-10-19T00:00:00+00:00", "2026-10-19")
    per = [o for o in obs if o["indicator"] == "settlements.outpost"]
    counts = {(o["place_id"], o["occurred"].date().isoformat()): o["value"] for o in obs if o["indicator"] == "settlements.outposts_established"}
    assert len(per) == 3 and all(o["value"] == 1 for o in per)
    assert counts == {(13, "2025-05-01"): 2, (2, "2025-05-01"): 1}      # Yatta and Hebron → Hebron governorate; no district → West Bank
    assert per[0]["precision"] == "month" and per[0]["stable"].startswith("peacenow_outposts:outpost:1:")


# ── pure: the OCHA table ─────────────────────────────────────────────────────

HEADER = "Date,Israeli_Lines_MWs,Gaza_Power_Plant_MWs,Egyptian_Lines_MWs,Total_daily_Supply_available_in_MWs,Overall_demand_in_MWs,Power_Cuts_hours_day_400mg,Temp\n"


def test_parse_reads_days_and_check_known_guards_the_copy():
    rows = E.parse(HEADER + "2017-07-13,70,0,0,70,450,3,34\n2019-08-11,120,65,0,185,385,12,31\n2023-09-30,120,70,0,190,439.56,13.5,32\nnot a date,1,1,1,1,1,1,1\n")
    assert [r["date"] for r in rows] == ["2017-07-13", "2019-08-11", "2023-09-30"]
    E.check_known(rows)
    rows[0]["Power_Cuts_hours_day_400mg"] = 21.0
    with pytest.raises(ValueError):
        E.check_known(rows)


def test_hours_column_is_loaded_as_supply_hours_on_the_gaza_place():
    rows = E.parse(HEADER + "2018-05-10,117,0,0,117,522,4.8,28\n")
    obs = E.observations(rows, "2026-10-19T00:00:00+00:00", "abc")
    got = {o["indicator"]: (o["value"], o["unit"], o["place_id"]) for o in obs}
    assert got["energy.gaza.supply_hours_per_day"] == (4.8, "hours_per_day", 1)
    assert got["energy.gaza.supply_mw"] == (117.0, "MW", 1)
    assert got["energy.gaza.demand_mw"] == (522.0, "MW", 1)
    assert len(obs) == 6


# ── the store (main-server only; skips until migration 130 is applied) ───────

@pytest.fixture
def db():
    try:
        from resolve.db import connect
        cm = connect()
        c = cm.__enter__()
    except Exception as e:                                             # noqa: BLE001
        pytest.skip(f"no database here: {type(e).__name__}")
    try:
        c.execute("SET default_transaction_read_only = on")
        yield c
    finally:
        cm.__exit__(None, None, None)


def _loaded(c, key):
    ds = c.execute("SELECT dataset_id FROM dataset WHERE key = %s", (key,)).fetchone()
    if not ds:
        pytest.skip(f"{key}: migration 130 not applied")
    n = c.execute("SELECT count(*) FROM observation WHERE dataset_id = %s AND upper_inf(sys_period)", (ds[0],)).fetchone()[0]
    if not n:
        pytest.skip(f"{key}: not loaded yet")
    return ds[0], n


def test_outposts_2024_count_matches_peace_now_headline(db):
    _loaded(db, "peacenow_outposts")
    n = db.execute("""SELECT sum(value_num) FROM databank_serving WHERE dataset_key = 'peacenow_outposts'
                      AND indicator = 'settlements.outposts_established' AND occurred_at >= '2024-01-01' AND occurred_at < '2025-01-01'""").fetchone()[0]
    assert n >= 59                                                   # "at least 59" in Peace Now's 2024 summary; the list says 59
    per = db.execute("SELECT count(*) FROM databank_serving WHERE dataset_key = 'peacenow_outposts' AND indicator = 'settlements.outpost'").fetchone()[0]
    assert per >= 350
    lic = db.execute("SELECT DISTINCT redistribution FROM databank_serving WHERE dataset_key = 'peacenow_outposts'").fetchall()
    assert lic == [("no-redistribution",)]


def test_gaza_electricity_served_with_the_crisis_low_and_the_last_day(db):
    _loaded(db, "ocha_gaza_electricity_daily")
    rows = db.execute("""SELECT occurred_at::date::text, indicator, value_num FROM databank_serving
                         WHERE dataset_key = 'ocha_gaza_electricity_daily' AND occurred_at IN ('2017-07-13', '2023-09-30')
                         AND indicator IN ('energy.gaza.supply_hours_per_day', 'energy.gaza.supply_mw')""").fetchall()
    got = {(r[0], r[1]): float(r[2]) for r in rows}
    assert got[("2017-07-13", "energy.gaza.supply_hours_per_day")] == 3.0
    assert got[("2023-09-30", "energy.gaza.supply_hours_per_day")] == 13.5
    assert got[("2023-09-30", "energy.gaza.supply_mw")] == 190.0
    last = db.execute("SELECT max(occurred_at)::date::text FROM databank_serving WHERE dataset_key = 'ocha_gaza_electricity_daily'").fetchone()[0]
    assert last == "2023-09-30"
    days = db.execute("SELECT count(DISTINCT occurred_at) FROM databank_serving WHERE dataset_key = 'ocha_gaza_electricity_daily'").fetchone()[0]
    assert days == 2464


def test_reload_is_idempotent(db):
    _, before = _loaded(db, "ocha_gaza_electricity_daily")
    if not E.OUT.exists():
        pytest.skip("the raw table is not on disk yet")
    assert E.main([]) == 0
    after = db.execute("SELECT count(*) FROM observation o JOIN dataset d USING (dataset_id) WHERE d.key = 'ocha_gaza_electricity_daily' AND upper_inf(o.sys_period)").fetchone()[0]
    assert after == before
