"""Audit 2026-09-25, area 06 — the REST tasks left open after the cloud's pass
(REST-01 02 05/06 10 11 12 15/16 17 18 19 20). Offline where the code allows;
the rest read the real database through the TestClient."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from serve import app as A                      # noqa: E402
from serve import correlate as C                # noqa: E402

client = TestClient(A.app)


# ── REST-01 / REST-18: the checkpoint resolver ───────────────────────────────

def _rows():
    return [{"place_id": 1, "name_ar": "زعترة", "name_en": "Za'tara (Tapuach)", "obs": 3,
             "aliases": ["زعتره"]},
            {"place_id": 2, "name_ar": "عطارة", "name_en": "Atara", "obs": 1, "aliases": []},
            {"place_id": 3, "name_ar": "حاجز حوارة", "name_en": "Huwara", "obs": 3, "aliases": []}]


def test_rest_01_a_lookalike_is_named_not_served(monkeypatch):
    monkeypatch.setattr(A, "q", lambda *a, **k: _rows())
    exact = A._resolve_checkpoint("زعترة")
    assert exact["place_id"] == 1 and exact["score"] <= 1.0 and not exact["uncertain"]
    contained = A._resolve_checkpoint("حوارة")            # whole-token containment
    assert contained["place_id"] == 3 and not contained["uncertain"]
    # the audit's case: the Latin lookalike used to land on Atara's row
    zatara = A._resolve_checkpoint("Zatara")
    assert zatara["place_id"] == 1 and not zatara["uncertain"], zatara
    # a close misspelling of one name is served (its doubt is spoken by the renderer)
    hawara = A._resolve_checkpoint("Hawara")
    assert hawara["place_id"] == 3 and not hawara["uncertain"], hawara
    # far from every name: named, not served
    far = A._resolve_checkpoint("Qalqilyah")
    assert far is None or far["uncertain"], far
    # two rows nearly as close: a lookalike, not a spelling
    monkeypatch.setattr(A, "q", lambda *a, **k: [
        {"place_id": 7, "name_ar": None, "name_en": "Betin", "obs": 1, "aliases": []},
        {"place_id": 8, "name_ar": None, "name_en": "Bitin", "obs": 1, "aliases": []}])
    amb = A._resolve_checkpoint("Beitin")          # equally close to two names
    assert amb is None or amb["uncertain"], amb
    # the audit's other case, on a registry shaped like ours: Hawara sits at the
    # same edit distance from Huwara and Awarta; the kept initial decides
    monkeypatch.setattr(A, "q", lambda *a, **k: [
        {"place_id": 3, "name_ar": "حوارة", "name_en": "Huwara", "obs": 3, "aliases": []},
        {"place_id": 4, "name_ar": "بوابات حواره", "name_en": "Huwara", "obs": 1, "aliases": []},
        {"place_id": 5, "name_ar": "عورتا", "name_en": "Awarta", "obs": 3, "aliases": []}])
    h = A._resolve_checkpoint("Hawara")
    assert h["place_id"] == 3 and not h["uncertain"], h


def test_rest_01_the_route_serves_nearest_without_a_reading(monkeypatch):
    monkeypatch.setattr(A, "_resolve_checkpoint",
                        lambda name: {"place_id": 2, "name": "عطارة", "score": 0.61, "uncertain": True})
    d = client.get("/v2/checkpoints/status", params={"name": "Zatara"}).json()
    assert d["found"] is False and d["nearest"]["name"] == "عطارة" and "flow" not in d


def test_rest_18_the_resolver_does_not_scan_the_observation_hypertable():
    src = inspect.getsource(A._resolve_checkpoint)
    assert "state_observation" not in src and "state_current" in src


# ── REST-02: a one-direction closure reaches the summary ─────────────────────

def test_rest_02_closed_now_names_the_direction_and_misses_no_directional_closure():
    d = client.get("/v2/checkpoints/summary").json()
    for row in d["closed_now"]:
        assert "reported_for" in row and "differs_by_direction" in row
    # invariant on the real view (079): a place with a closed inbound or
    # outbound row has a closed default row, so it is in closed_now's set
    missing = A.q("""SELECT DISTINCT d.place_id FROM checkpoint_serving d
                      WHERE d.direction IN ('inbound','outbound') AND d.flow = 'closed'
                        AND NOT EXISTS (SELECT 1 FROM checkpoint_serving b
                                        WHERE b.place_id = d.place_id AND b.direction = 'both'
                                          AND b.flow = 'closed')""")
    assert missing == [], missing


# ── REST-05/06: insights never counts a governorate fallback under the city ──

def test_rest_05_06_insights_separates_governorate_only_events():
    assert "place_precision" in A.INSIGHTS_INC_SQL
    d = client.get("/v2/insights", params={"place": "رام الله", "days": 30, "learn": "false"}).json()
    inc = d["incidents"]
    assert "located_to_governorate_only" in inc and inc["located_to_governorate_only"] >= 0
    assert all(r["events"] > 0 for r in inc["by_type"])


# ── REST-10: exports carry precision and drop satellite pixels ───────────────

def test_rest_10_incident_exports_carry_place_precision():
    head = client.get("/v2/export/incidents.csv", params={"days": 7}).text.splitlines()[0]
    assert "place_precision" in head and "named_place" in head
    gj = client.get("/v2/export/incidents.geojson", params={"days": 7}).json()
    for f in gj["features"][:50]:
        assert "place_precision" in f["properties"]
        assert f["properties"]["event_type"] != "fire_detection"


# ── REST-11: the unit the value is in ────────────────────────────────────────

def test_rest_11_series_unit_is_the_resolved_unit_not_the_declared_one():
    src = inspect.getsource(A._series_at)   # _series widens the place, _series_at reads
    assert "v.resolved_unit" in src and "COALESCE(v.canonical_unit" not in src
    d = client.get("/v2/databank/compare",
                   params={"indicators": "food.price.water_drinking,food.price.bread"}).json()
    ser = {s["indicator"]: s for s in d.get("series", [])}
    if "food.price.water_drinking" not in ser or not ser["food.price.water_drinking"]["points"]:
        pytest.skip("no drinking-water series in this database")
    w = ser["food.price.water_drinking"]
    assert "units" in w and "ILS_per_kg" not in w["units"], w["units"]


# ── REST-12 / REST-20: breakdowns and monotone pairs are refused ─────────────

def _fake_series(points):
    return {"known": True, "points": points, "n": len(points), "measure_kind": "stock",
            "place_grain": "national", "concept_key": None, "grain": "month",
            "polarity": None, "canonical_unit": None, "sources": [], "source_names": set(),
            "attribution": [], "units": [], "unit_mixed": False}


def _pts(values, dup_first=False):
    from datetime import date, timedelta
    out = [{"at": date(2025, 1, 1) + timedelta(days=30 * i), "prec": "month", "value": v}
           for i, v in enumerate(values)]
    if dup_first:
        out.append({**out[0], "value": values[0] + 1})
    return out


def test_rest_12_a_breakdown_series_is_collapsed_by_rule_not_by_row_order(monkeypatch):
    """F043: with 'last row wins' the coefficient depended on physical row
    order. The median per date is order-independent, and the caveat says it."""
    base = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7]
    other = [2, 7, 1, 8, 2, 8, 1, 8, 2, 8, 4, 5, 9, 0]
    pts = _pts(base)
    extra = [{**pts[i], "value": pts[i]["value"] + 40} for i in range(0, 14, 2)]   # a second market
    forward = _fake_series(pts + extra)
    backward = _fake_series(list(reversed(pts + extra)))
    results = []
    for order in (forward, backward):
        table = {"a": order, "b": _fake_series(_pts(other))}
        monkeypatch.setattr(A, "_series", lambda ind, *a, **k: table[ind])
        results.append(client.get("/v2/databank/correlate", params={"a": "a", "b": "b"}).json())
    assert results[0].get("rho") is not None and results[0]["rho"] == results[1]["rho"]
    assert any("MEDIAN per date" in c for c in results[0]["caveats"])
    col, note = C.collapse_dates(forward)
    assert col["n"] == 14 and "7 of 14 dates" in note


def test_rest_20_two_rising_series_are_refused_unless_differenced(monkeypatch):
    # 14 points: differencing drops one and MIN_N is 12
    rising = [10, 11, 13, 14, 16, 18, 19, 21, 23, 25, 26, 28, 29, 31]
    other = [100, 101, 103, 106, 107, 110, 112, 113, 117, 118, 120, 123, 124, 127]
    table = {"a": _fake_series(_pts(rising)), "b": _fake_series(_pts(other))}
    monkeypatch.setattr(A, "_series", lambda ind, *a, **k: table[ind])
    d = client.get("/v2/databank/correlate", params={"a": "a", "b": "b"}).json()
    assert d["refused"] and "measure time" in d["reasons"][0] and d["hint"] == "detrend=diff"
    d2 = client.get("/v2/databank/correlate", params={"a": "a", "b": "b", "detrend": "diff"}).json()
    assert d2["detrend"] == "diff" and ("rho" in d2 or d2.get("refused"))
    assert C.check_shape([1, 2, 3, 4, 5, 6, 7], [7, 3, 5, 1, 6, 2, 4]) == []


# ── REST-15/16: pooled connections when the package exists, safe fallback ────

def test_rest_15_16_q_borrows_from_the_shared_connection_helper():
    from resolve import db
    src = inspect.getsource(A.q)
    assert "connection()" in src and "psycopg.connect(dsn()" not in src
    with db.connection() as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    st = db.pool_status()
    assert "pooled" in st


# ── REST-17: /health judges every watchdog family ────────────────────────────

def test_rest_17_health_reports_every_family_and_no_retired_feed_age():
    d = client.get("/health").json()
    assert "feed_age_minutes" not in d and "fuel_states" not in d
    assert d["status"] in ("ok", "degraded", "maintenance")
    fams = d["families"]
    assert {"job", "feed"} <= set(fams) and len(fams) >= 4, fams
    assert "maintenance" in d and "db" in d
    from ops.watchdog import all_checks
    a1, a2 = all_checks(), all_checks()
    assert a1 is a2                                    # cached between polls


# ── REST-19: per-row provenance at dataset grain ─────────────────────────────

def test_rest_19_category_rows_carry_source_dataset_and_licence():
    d = client.get("/v2/databank/education", params={"limit": 5}).json()
    if not d["items"]:
        pytest.skip("no education rows")
    it = d["items"][0]
    for k in ("source_key", "dataset_key", "license_spdx", "redistribution", "attribution"):
        assert k in it, k
    assert it["license_spdx"], "dataset-grain licence must resolve (054)"
