"""DATABANK-03, -04 and -V09 (audit 2026-09-25), fixed 2026-09-26.

-03: demolition localities were filed under "West Bank" while carrying their
     governorate and a point; the spec's declared ladder now runs.
-04: an `indistinguishable` dataset lost every identical copy after the first
     on a fresh load (aid_access: 25,872 of 50,059 written, run "succeeded").
-V09: one identity twice in one run with different content sent None to the
     supersede list and two rows under one key to the insert (052 aborts).

The write-phase harness below records every statement the loader would send
to the database, so a test can count what reaches the write — the path no
test reached before (DATABANK-V16)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from ingest import databank
from ingest.databank import Row


# ── a run that reaches the write, recording it ───────────────────────────────

def _write_run(monkeypatch, tmp_path, emitted, identity, *, held=()):
    spec = {"category": "phantom", "status": "reviewed", "shape": "observation",
            "identity": identity, "place": {},
            "expect": {"min_records": 1, "max_observations": 100000},
            "datasets": [{"key": "d", "source": "s"}]}
    stored = [(databank.identity_key_for(
                   identity, r.dataset_key, indicator=r.indicator,
                   occurred_at=r.occurred_at, place_id=r.place_id,
                   value_num=r.value_num, attrs=r.attrs),
               1000 + i, r.value_num, r.value_text, r.unit, r.place_id, r.attrs)
              for i, r in enumerate(held)]
    log = {"inserts": [], "supersede": []}

    class Cur:
        rowcount = 1
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            self.sql = sql
            if "INSERT INTO observation" in sql:
                log["inserts"].append(params)
            elif sql.lstrip().startswith("UPDATE observation"):
                log["supersede"].extend(params[0])
        def fetchall(self):
            return stored if "identity_key" in self.sql else []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()
        def commit(self): pass

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
                        lambda conn, spec, category: {"d": 1})
    report = databank.run("phantom", dry_run=False)
    return report, log


def _lorry(i, value=1.0):
    # identical content, a different source record each time
    return Row("d", "aid.trucks", "2024-03-01", "day", f"lorry-{i}",
               value_num=value, unit="trucks", place_id=5)


IDENT = {"fields": ["indicator", "occurred_at", "place_id"]}


def test_DATABANK_04_every_indistinguishable_copy_reaches_the_write(
        monkeypatch, tmp_path):
    ident = {**IDENT, "collision_kind": "indistinguishable",
             "allow_collisions": 10}
    report, log = _write_run(monkeypatch, tmp_path,
                             [_lorry(i) for i in range(5)], ident)
    assert len(log["inserts"]) == 5
    assert report["written"] == 5
    assert report["notes"]["indistinguishable_copies_kept"] == 4
    # keyless, as before: 052 must not refuse the second lorry
    assert all(p["identity_key"] is None for p in log["inserts"])


def test_DATABANK_04_a_duplicate_fact_still_collapses_and_says_so(
        monkeypatch, tmp_path):
    ident = {**IDENT, "collision_kind": "duplicate_fact", "allow_collisions": 10}
    report, log = _write_run(monkeypatch, tmp_path,
                             [_lorry(i) for i in range(5)], ident)
    assert len(log["inserts"]) == 1
    assert report["notes"]["intra_run_duplicate_collapsed"] == 4
    assert "identity_already_held" not in report["notes"]


def test_DATABANK_04_a_held_row_is_still_skipped(monkeypatch, tmp_path):
    report, log = _write_run(monkeypatch, tmp_path, [_lorry(0)], IDENT,
                             held=[_lorry(99)])
    assert log["inserts"] == []
    assert report["notes"]["identity_already_held"] == 1


def test_DATABANK_V09_same_run_conflict_keeps_the_first_and_never_supersedes_none(
        monkeypatch, tmp_path):
    ident = {**IDENT, "allow_collisions": 1}
    report, log = _write_run(monkeypatch, tmp_path,
                             [_lorry(0, 1.0), _lorry(1, 2.0)], ident)
    assert [p["value_num"] for p in log["inserts"]] == [1.0]
    assert None not in log["supersede"]
    assert report["notes"]["intra_run_conflict_kept_first"] == 1


def test_a_real_correction_still_supersedes_the_held_row(monkeypatch, tmp_path):
    report, log = _write_run(monkeypatch, tmp_path, [_lorry(0, 7.0)], IDENT,
                             held=[_lorry(99, 6.0)])
    assert log["supersede"] == [1000]
    assert [p["value_num"] for p in log["inserts"]] == [7.0]


# ── DATABANK-03: the demolition ladder runs ──────────────────────────────────

class _Pip:
    """Point-in-polygon stand-in: west of 35.1 is Hebron, east is Bethlehem."""
    def resolve(self, lat, lon):
        if lat is None or lon is None:
            return None
        return 13 if lon < 35.1 else 12


PLACES = {"region": {"West Bank": 2, "Gaza Strip": 1},
          "governorate": {"Hebron": 13, "Bethlehem": 12, "Qalqilya": 7,
                          "Jerusalem": 11},
          "crossing": {}, "pcode": {}, "_pip": _Pip()}


def _dem(name, gov, lat=None, lon=None, dim="locality", region="West Bank"):
    return {"stable_id": f"ocha-dem:{name}", "demolition_dimension": dim,
            "date": None if dim == "locality" else "2024-12-31",
            "coverage_end": "2024-07-30",
            "location": {"name": name, "governorate": gov, "region": region,
                         "lat": lat, "lon": lon, "admin2_pcode": None},
            "metrics": {"demolished": 20, "displaced": 15, "affected": 0},
            "sources": [{"name": "UN OCHA oPt — Data on Demolitions"}]}


def _spec():
    spec = databank.load_spec("demolitions")
    return spec


def _transform(rec):
    counts = Counter()
    rows = databank.t_demolitions(rec, _spec(), PLACES, counts)
    return rows, counts


def test_DATABANK_03_a_locality_lands_on_its_governorate_not_the_west_bank():
    rows, counts = _transform(_dem("Tatrit", "Hebron", 31.35, 34.93))
    assert {r.place_id for r in rows} == {13}
    assert all(r.located for r in rows)
    assert rows[0].attrs["lat"] == 31.35 and rows[0].attrs["lon"] == 34.93
    assert counts["place_rung:governorate"] == 1
    assert counts["locality_resolution_miss"] == 0


def test_DATABANK_03_the_publishers_name_beats_the_point_at_a_border():
    # OCHA says Bethlehem; the point falls a few metres into Hebron
    rows, _ = _transform(_dem("Border village", "Bethlehem", 31.6, 35.05))
    assert {r.place_id for r in rows} == {12}


def test_DATABANK_03_a_spelling_variant_resolves():
    rows, _ = _transform(_dem("Azzun", "Qalqiliya", 32.17, 35.05))
    assert {r.place_id for r in rows} == {7}


def test_DATABANK_03_no_name_falls_to_the_point_then_to_region():
    rows, counts = _transform(_dem("Nameless", None, 31.7, 35.2))
    assert {r.place_id for r in rows} == {12}
    assert counts["place_rung:latlon"] == 1
    rows, counts = _transform(_dem("Nowhere", None))
    assert {r.place_id for r in rows} == {2}
    assert counts["locality_resolution_miss"] == 1


def test_DATABANK_03_annual_totals_stay_at_region():
    rows, _ = _transform(_dem("West Bank", None, dim="annual_total"))
    assert {r.place_id for r in rows} == {2}
    assert not any(r.located for r in rows)


def test_DATABANK_03_the_spec_declares_the_ladder_it_runs():
    place = _spec()["place"]
    assert place["strategy"] == "pcode"
    assert place["fallback"] == ["governorate", "latlon", "region"]
    assert place["min_located_pct"] >= 0.9


def test_DATABANK_V11_one_crashing_category_does_not_stop_the_night(monkeypatch):
    ran = []

    def fake_run(cat, dry_run=False):
        ran.append(cat)
        if cat == "b":
            raise ValueError("truncated raw file")
        return {"written": 1, "events_written": 0}

    monkeypatch.setattr(databank, "TRANSFORMERS", {"a": None, "b": None, "c": None})
    monkeypatch.setattr(databank, "run", fake_run)
    assert databank.run_all() == 1
    assert ran == ["a", "b", "c"]
