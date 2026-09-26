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

def _write_run(monkeypatch, tmp_path, emitted, identity, *, held=(), refuse=(),
               ceiling=100000):
    spec = {"category": "phantom", "status": "reviewed", "shape": "observation",
            "identity": identity, "place": {},
            "expect": {"min_records": 1, "max_observations": ceiling},
            "datasets": [{"key": "d", "source": "s"}]}
    stored = [(databank.identity_key_for(
                   identity, r.dataset_key, indicator=r.indicator,
                   occurred_at=r.occurred_at, place_id=r.place_id,
                   value_num=r.value_num, attrs=r.attrs),
               1000 + i, r.value_num, r.value_text, r.unit, r.place_id, r.attrs)
              for i, r in enumerate(held)]
    log = {"inserts": [], "supersede": [], "updates": []}

    class Cur:
        rowcount = 1
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            self.sql = sql
            self.rowcount = 1
            if "INSERT INTO observation" in sql:
                log["inserts"].append(params)
                if params["v1_stable_id"] in refuse:
                    self.rowcount = 0                 # the stable-id index said no
            elif sql.lstrip().startswith("UPDATE observation"):
                log["supersede"].extend(params[0])
                log["updates"].append(list(params[0]))
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


# ── DATABANK-V08 / -02: what a complete source stopped saying closes ─────────

import pytest
import yaml
from ingest import spec as spec_mod
from ingest.spec import SpecRefused as _Refused


def _camp(name, value, place=14):
    return Row("d", "refugees.camp_population", "2026-06-10", "day",
               f"camp-{name}-{place}", value_num=value, unit="persons",
               place_id=place, attrs={"name": name})


CAMP_ID = {"fields": ["indicator", "occurred_at", "place_id", "value_num"],
           "attrs": ["name"]}


def test_DATABANK_V08_a_row_the_complete_source_no_longer_sends_closes(
        monkeypatch, tmp_path):
    held = [_camp("Jabalia", 113990), _camp("Jabalia", 113990, place=None),
            _camp("Rafah", 125304)]
    emitted = [_camp("Jabalia", 113990), _camp("Rafah", 125304)]
    report, log = _write_run(monkeypatch, tmp_path, emitted,
                             {**CAMP_ID, "generation": "complete",
                              "max_absent": 5}, held=held)
    assert log["inserts"] == []                  # both still held
    assert log["updates"] == [[1001]]            # the NULL-place Jabalia
    assert report["absent_upstream"]["closed"] == 1
    assert report["absent_upstream"]["ids"] == [1001]


def test_DATABANK_02_a_revised_value_closes_the_old_reading(monkeypatch, tmp_path):
    held = [_camp("Nur Shams", 106)]
    emitted = [_camp("Nur Shams", 120)]
    report, log = _write_run(monkeypatch, tmp_path, emitted,
                             {**CAMP_ID, "generation": "complete"}, held=held)
    assert [p["value_num"] for p in log["inserts"]] == [120]
    assert log["updates"] == [[1000]]            # 106 closed, not counted twice


def test_DATABANK_V08_a_window_source_keeps_what_fell_out(monkeypatch, tmp_path):
    held = [_camp("Jabalia", 113990), _camp("Rafah", 125304)]
    report, log = _write_run(monkeypatch, tmp_path, [_camp("Rafah", 125304)],
                             CAMP_ID, held=held)
    assert log["updates"] == []
    assert "absent_upstream" not in report


def test_DATABANK_V08_a_shrink_fails_the_run_and_closes_nothing(
        monkeypatch, tmp_path):
    held = [_camp(f"c{i}", i + 1) for i in range(40)]
    with pytest.raises(_Refused, match="a shrink, not a correction"):
        _write_run(monkeypatch, tmp_path, held[:10],
                   {**CAMP_ID, "generation": "complete"}, held=held)


def test_DATABANK_02_the_validator_refuses_an_undeclared_value_in_the_key():
    spec = yaml.safe_load(open("db/mappings/refugees.yaml"))
    spec["identity"].pop("generation")
    problems = spec_mod.validate(spec, "refugees")
    assert any(p.path == "identity.fields" and "value_num" in p.message
               for p in problems)
    for cat in ("refugees", "health", "conflict", "aid_access"):
        assert spec_mod.validate(
            yaml.safe_load(open(f"db/mappings/{cat}.yaml")), cat) == []


# ── DATABANK-05: events are matched by count, never collapsed in-run ─────────

import json as _json
from ingest.databank import EventRow


def _event_run(monkeypatch, tmp_path, emitted, held=()):
    """held: (EventRow, stable id as stored) pairs already in `event`."""
    spec = {"category": "phantom", "status": "reviewed", "shape": "event",
            "place": {}, "expect": {"min_records": 1, "max_observations": 100000},
            "datasets": [{"key": "d", "source": "s"}]}
    key_rows = [(e.event_type, str(e.occurred_at)[:10],
                 None if e.place_id is None else str(e.place_id),
                 None if e.lat is None else str(e.lat),
                 None if e.lon is None else str(e.lon), e.metrics)
                for e, _ in held]
    id_rows = [(sid,) for _, sid in held]
    log = {"events": []}

    class Cur:
        rowcount = 1
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            self.sql = sql
            if "INSERT INTO event" in sql:
                log["events"].append(_json.loads(params["attrs"])["v1_stable_id"])
        def fetchall(self):
            if "FROM event" in self.sql and "SELECT attrs->>'v1_stable_id'" in self.sql:
                return id_rows
            if "FROM event" in self.sql:
                return key_rows
            return []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()
        def commit(self): pass

    def transform_all(category, spec, places, counts, drops):
        for e in emitted:
            counts["records_read"] += 1
            yield Path("/phantom.json"), e

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
    return databank.run("phantom", dry_run=False), log


def _death(sid, dyad):
    # UCDP, 1993-12-13, Rafah camp: one death per dyad, identical otherwise
    return EventRow("d", "conflict.state_based", "1993-12-13", "day", sid,
                    place_id=21, lat=31.29, lon=34.25,
                    metrics={"killed": 1}, attrs={"dyad_name": dyad})


PFLP, PIJ = _death("u-pflp", "Israel - PFLP"), _death("u-pij", "Israel - PIJ")


def test_DATABANK_05_a_fresh_load_keeps_both_dyads(monkeypatch, tmp_path):
    report, log = _event_run(monkeypatch, tmp_path, [PFLP, PIJ])
    assert sorted(log["events"]) == ["u-pflp", "u-pij"]
    assert report["notes"]["event_new"] == 2


def test_DATABANK_05_a_rehash_still_skips_everything(monkeypatch, tmp_path):
    # the same two events held under v1's OLD hashes
    held = [(PFLP, "old-1"), (PIJ, "old-2")]
    report, log = _event_run(monkeypatch, tmp_path, [PFLP, PIJ], held)
    assert log["events"] == []
    assert report["notes"]["event_already_held"] == 2


def test_DATABANK_05_a_held_twin_does_not_swallow_its_new_sibling_in_any_order(
        monkeypatch, tmp_path):
    held = [(PFLP, "u-pflp")]                      # only PFLP is held, by id
    for order in ([PFLP, PIJ], [PIJ, PFLP]):
        report, log = _event_run(monkeypatch, tmp_path, order, held)
        assert log["events"] == ["u-pij"], order
        assert report["notes"]["event_new"] == 1


# ── DATABANK-V02: a locality total is not an event flow ──────────────────────

def test_DATABANK_V02_locality_totals_are_cumulative_and_annual_rows_are_yearly_flows():
    from ops.load_registry import classify
    rules = databank.load_spec("demolitions")["registry"]["rules"]
    pairs = [("demolitions.locality.structures", "structures", 526),
             ("demolitions.locality.displaced", "persons", 400),
             ("demolitions.annual_total.structures", "structures", 18),
             ("demolitions.annual_total.displaced", "persons", 18),
             ("demolitions.annual_total.affected", "persons", 18)]
    got, missing = classify(pairs, rules)
    assert not missing
    for ind in ("demolitions.locality.structures", "demolitions.locality.displaced"):
        assert (got[ind]["measure_kind"], got[ind]["grain"]) == ("cumulative", "period")
    for ind in ("demolitions.annual_total.structures", "demolitions.annual_total.displaced",
                "demolitions.annual_total.affected"):
        assert (got[ind]["measure_kind"], got[ind]["grain"], got[ind]["place_grain"]) == \
            ("flow", "year", "region")
    assert got["demolitions.annual_total.displaced"]["canonical_unit"] == "persons"


# ── DATABANK-V06: a Media Office bulletin is published, not inferred ─────────

def _gaza(source):
    return {"report_date": "2026-09-20", "killed_cum": 65000, "injured_cum": 166000,
            "report_source": source}


def test_DATABANK_V06_media_office_bulletins_serve_and_arithmetic_does_not():
    places = {"region": {"Gaza Strip": 1}}
    rows = databank.t_conflict_gaza(_gaza("gmotel"), {}, places, Counter())
    assert isinstance(rows, list) and rows[0].attrs["report_source"] == "gmotel"
    assert databank.t_conflict_gaza(_gaza("missing"), {}, places, Counter()).reason == "t4p_inferred"
    new = databank.t_conflict_gaza(_gaza("pressconf"), {}, places, Counter())
    assert new.reason == "unknown_report_source"
    declared = {d["reason"] for d in databank.load_spec("conflict_gaza")["drop"]}
    assert "unknown_report_source" not in declared          # so the run fails


# ── DATABANK-V07: what the stable-id index refuses is counted, and for a keyed
#    dataset it fails the run ──────────────────────────────────────────────────

def test_DATABANK_V07_a_keyed_row_refused_by_the_stable_id_index_fails_the_run(
        monkeypatch, tmp_path):
    with pytest.raises(_Refused, match="refused by the stable-id index"):
        _write_run(monkeypatch, tmp_path, [_lorry(0, 5.0)], IDENT, refuse={"lorry-0"})


def test_DATABANK_V07_a_keyless_refetch_is_counted_not_failed(monkeypatch, tmp_path):
    ident = {**IDENT, "collision_kind": "indistinguishable", "allow_collisions": 10}
    report, log = _write_run(monkeypatch, tmp_path, [_lorry(0), _lorry(1)], ident,
                             refuse={"lorry-0", "lorry-1"})
    assert report["written"] == 0 and log.get("committed")
    assert report["notes"]["refused_by_stable_id:d"] == 2


def test_DATABANK_V10_the_ceiling_judges_the_full_emission_on_a_real_run(monkeypatch, tmp_path):
    rows = [_lorry(i, float(i)) for i in range(5)]
    ident = {"fields": ["indicator", "occurred_at", "place_id", "value_num"]}
    # four of five already held: one would be written, yet the spec emitted five
    with pytest.raises(_Refused, match="emitted 5 > expect.max_observations 3"):
        _write_run(monkeypatch, tmp_path, rows, ident, held=rows[:4], ceiling=3)


def test_DATABANK_V12_the_identity_backfill_keeps_the_first_seen_copy():
    src = open("ops/backfill_identity.py").read()
    select = src[src.index("SELECT observation_id, indicator"):]
    select = select[:select.index('(ds_id,)')]
    assert "ORDER BY lower(sys_period), observation_id" in select


# ── DATABANK-V18: concepts say what the series hold ───────────────────────────

def test_DATABANK_V18_settler_attacks_and_connectivity_access_have_their_own_concepts():
    from ops.load_registry import classify
    conflict = databank.load_spec("conflict")["registry"]["rules"]
    got, _ = classify([("conflict.westbank_cumulative_settler_attacks", "events", 10)], conflict)
    assert got["conflict.westbank_cumulative_settler_attacks"]["concept"] == "violence.settler"
    economic = databank.load_spec("economic")["registry"]["rules"]
    got, _ = classify([("economic.it_net_user_zs", "percent", 20)], economic)
    assert got["economic.it_net_user_zs"]["concept"] == "connectivity.access"
    concepts = yaml.safe_load(open("db/registry/concepts.yaml"))["concepts"]
    assert "NO SERIES YET" not in concepts["energy.supply"]["definition"]
    assert concepts["violence.settler"]["parent"] == "violence"
