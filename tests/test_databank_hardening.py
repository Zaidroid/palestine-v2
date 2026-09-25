"""The databank loader's guard, driven all the way to the write.

tests/test_databank.py's `_floor_run` stops at the first write on purpose —
it proves the floors. Everything AFTER the floors (what is superseded, what
is inserted, under which key, what the run report says) was on a path no test
reached, and the 2026-09-25 audit found four defects living there: a fresh
load that silently halved aid_access, a duplicate pair that aborted a whole
category, a tripwire that could not fire on a real run, and events that
collapsed into each other. These tests drive `databank.run` through a REAL
(non-dry) run against a fake cursor that records every UPDATE and INSERT, so
the assertion is about what would have reached the database.

A few tests at the bottom need a database (the local throwaway one, or
main-server's); each runs inside a transaction that is rolled back.
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import databank                                       # noqa: E402
from ingest.databank import (Drop, EventRow, Row, SpecRefused,    # noqa: E402
                             identity_key_for, load_spec)


# ── the harness ──────────────────────────────────────────────────────────────

class FakeDB:
    """What the loader reads before it writes, and a record of the writes."""

    def __init__(self, held=(), held_events=(), refuse=()):
        self.held = list(held)                # identity SELECT rows (7-tuple)
        self.held_events = list(held_events)  # event SELECT rows (7-tuple)
        self.refuse = set(refuse)             # stable ids 044 would refuse
        self.inserts: list[dict] = []
        self.event_inserts: list[dict] = []
        self.superseded: list = []
        self.committed = False


class _Cur:
    def __init__(self, db: FakeDB):
        self.db, self._all, self.rowcount = db, [], 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        head = sql.lstrip()
        self._all, self.rowcount = [], 0
        if "o.identity_key" in sql:
            self._all = list(self.db.held)
        elif head.startswith("SELECT event_type"):
            self._all = list(self.db.held_events)
        elif head.startswith("UPDATE observation"):
            self.db.superseded.extend(params[0])
            self.rowcount = len(params[0])
        elif "INSERT INTO observation" in sql:
            self.db.inserts.append(params)
            self.rowcount = 0 if params["v1_stable_id"] in self.db.refuse else 1
        elif "INSERT INTO event" in sql:
            self.db.event_inserts.append(params)
            self.rowcount = 1

    def fetchall(self):
        return self._all

    def fetchone(self):
        return self._all[0] if self._all else None


class _Conn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cur(self.db)

    def commit(self):
        self.db.committed = True


class _AnyId(dict):
    """A place map where every name resolves — the frozen-corpus tests are
    about the guard, not about the gazetteer."""

    def __missing__(self, key):
        return 900


def _places():
    return {"region": {"Gaza Strip": 1, "West Bank": 2},
            "governorate": {"Jerusalem": 11, "Qalqilya": 7, "Hebron": 13},
            "crossing": _AnyId(), "pcode": {}}


class _PIP:
    """lat/lon → one governorate for any coordinate; counts its calls."""

    def __init__(self, answer=500):
        self.answer, self.calls = answer, 0

    def resolve(self, lat, lon):
        self.calls += 1
        return None if lat is None or lon is None else self.answer


def _drive(monkeypatch, tmp_path, category, *, spec=None, emitted=None,
           db=None, pip=None, dry_run=False):
    """Run `databank.run(category)` against FakeDB. `spec`/`emitted` replace
    the real spec and transform; leave them None to run the real ones."""
    db = db or FakeDB()
    if spec is not None:
        monkeypatch.setattr(databank, "load_spec", lambda c: spec)
        monkeypatch.setitem(databank.TRANSFORMERS, category, lambda *a: [])
    if emitted is not None:
        def transform_all(cat, sp, places, counts, drops):
            for r in emitted:
                counts["records_read"] += 1
                yield Path("/phantom.json"), r
        monkeypatch.setattr(databank, "transform_all", transform_all)
        monkeypatch.setattr(databank, "read_payload", lambda f: b"")
    monkeypatch.setattr(databank, "connect", lambda: _Conn(db))
    monkeypatch.setattr(databank, "load_places", lambda conn: _places())
    monkeypatch.setattr(databank, "PointResolver",
                        lambda conn: pip or _PIP())
    monkeypatch.setattr(databank.bronze, "put",
                        lambda *a, **k: type("R", (), {"ref": "bronze:x"}))
    monkeypatch.setattr(databank, "RUNS", tmp_path / "runs.ndjson")

    def ensure(conn, sp, cat):
        return {d["key"]: i for i, d in enumerate(sp["datasets"], 1)}
    monkeypatch.setattr(databank, "ensure_datasets", ensure)
    report = databank.run(category, dry_run=dry_run)
    return report, db


def _spec(ident, *, max_obs=1000, ds="d1"):
    return {"category": "phantom", "status": "reviewed",
            "shape": "observation", "identity": ident, "place": {},
            "expect": {"min_records": 1, "max_observations": max_obs},
            "datasets": [{"key": ds, "source": "s"}]}


def _held(ident, rows):
    """FakeDB identity rows for `rows`, keyed by the one renderer."""
    return [(identity_key_for(ident, r.dataset_key, indicator=r.indicator,
                              occurred_at=r.occurred_at, place_id=r.place_id,
                              value_num=r.value_num, attrs=r.attrs),
             1000 + i, r.value_num, r.value_text, r.unit, r.place_id, r.attrs)
            for i, r in enumerate(rows)]


# ── F029: a fresh load keeps every indistinguishable row ─────────────────────

def test_a_fresh_load_writes_every_identical_lorry(monkeypatch, tmp_path):
    """aid_access declares `collision_kind: indistinguishable` — 24,550 rows
    that look identical and are different lorries. The guard seeded its
    'already held' map from the run's OWN rows, so on an empty databank the
    second lorry of each pair was skipped: measured on the frozen corpus,
    ~25.7k of 50,059 written and a clean report."""
    ident = {"fields": ["indicator", "occurred_at", "place_id", "value_num"],
             "attrs": ["donor"], "allow_collisions": 4,
             "collision_kind": "indistinguishable"}
    lorries = [Row("d1", "aid_access.consignment.food", "2024-01-02", "day",
                   f"sid{i}", value_num=1, unit="truck", place_id=5,
                   attrs={"donor": "WFP"}) for i in range(5)]
    report, db = _drive(monkeypatch, tmp_path, "phantom",
                        spec=_spec(ident), emitted=lorries)
    assert len(db.inserts) == 5, "identical lorries were collapsed"
    assert all(p["identity_key"] is None for p in db.inserts)  # keyless
    assert report["written"] == 5


def test_the_frozen_aid_access_corpus_loads_whole(monkeypatch, tmp_path):
    """The same property on the real corpus a fresh clone loads."""
    report, db = _drive(monkeypatch, tmp_path, "aid_access")
    assert report["records_read"] == 50059
    assert len(db.inserts) == 50059, (
        f"{50059 - len(db.inserts)} consignments never reached the write")


# ── F139: two copies of one fact in one run ──────────────────────────────────

def test_a_duplicate_fact_is_one_row_and_never_a_none_supersede(
        monkeypatch, tmp_path):
    """IDMC publishes Nur Shams 2025-09-01 twice. If the two copies differ in
    an attr outside the identity, the second took the CORRECTION branch with
    oid None: None went to the supersede list and both copies were inserted
    under one key, which 052's unique index refuses — aborting the category
    and every category after it that night."""
    ident = {"fields": ["indicator", "occurred_at", "place_id", "value_num"],
             "attrs": ["event_name"], "allow_collisions": 1,
             "collision_kind": "duplicate_fact"}
    a = Row("d1", "refugees.displacement_event", "2025-09-01", "day", "s1",
            value_num=106, unit="persons", place_id=8,
            attrs={"event_name": "Nur Shams", "admin2": "Tulkarm"})
    b = Row("d1", "refugees.displacement_event", "2025-09-01", "day", "s2",
            value_num=106, unit="persons", place_id=8,
            attrs={"event_name": "Nur Shams", "admin2": "Tulkarem"})
    report, db = _drive(monkeypatch, tmp_path, "phantom",
                        spec=_spec(ident), emitted=[a, b])
    assert None not in db.superseded
    assert [p["v1_stable_id"] for p in db.inserts] == ["s1"]
    keys = [p["identity_key"] for p in db.inserts]
    assert len(keys) == len(set(keys)), "two inserts share one identity_key"
    assert report["notes"]["intra_run_duplicate_dropped"] == 1


# ── F027: a revised value supersedes, though the value is in the identity ───

_IDMC = {"fields": ["indicator", "occurred_at", "place_id", "value_num"],
         "attrs": ["event_name"], "allow_collisions": 1,
         "collision_kind": "duplicate_fact"}


def _idmc(sid, day, value, place=8, name="Nur Shams"):
    return Row("d1", "refugees.displacement_event", day, "day", sid,
               value_num=value, unit="persons", place_id=place,
               attrs={"event_name": name})


def test_a_revised_displacement_supersedes_the_old_reading(monkeypatch,
                                                           tmp_path):
    """IDMC revises Nur Shams 2025-09-01 from 106 to 120. value_num is in the
    identity, so the revision is a NEW key: before 2026-09-25 it was written
    beside the old row and both stayed current — 226 displaced for one
    event. The stored keys are not touched; the held 106 row is superseded
    because a row sharing everything but the value is new tonight."""
    others = [_idmc(f"o{i}", f"2025-10-{i + 1:02d}", 50 + i, name="Jenin")
              for i in range(4)]
    old = _idmc("s-old", "2025-09-01", 106)
    db = FakeDB(held=_held(_IDMC, others + [old]))
    tonight = others + [_idmc("s-new", "2025-09-01", 120),
                        _idmc("s-new-dup", "2025-09-01", 120)]  # IDMC's copy
    report, db = _drive(monkeypatch, tmp_path, "phantom", spec=_spec(_IDMC),
                        emitted=tonight, db=db)
    old_oid = 1000 + 4
    assert db.superseded == [old_oid], "the 106 reading is still current"
    assert [p["v1_stable_id"] for p in db.inserts] == ["s-new"]
    assert report["notes"]["value_revisions"] == 1


def test_a_second_figure_at_one_place_is_not_a_revision(monkeypatch,
                                                        tmp_path):
    """The reason value_num is in the identity at all: two figures of one
    event, one day, one governorate. A new one arriving beside a held one
    that is still published closes nothing."""
    held = [_idmc("a", "2025-09-01", 500), _idmc("b", "2025-09-02", 7)]
    db = FakeDB(held=_held(_IDMC, held))
    tonight = held + [_idmc("c", "2025-09-01", 300)]
    report, db = _drive(monkeypatch, tmp_path, "phantom", spec=_spec(_IDMC),
                        emitted=tonight, db=db)
    assert db.superseded == []
    assert [p["v1_stable_id"] for p in db.inserts] == ["c"]


def test_an_incremental_slice_never_closes_what_it_did_not_resend(
        monkeypatch, tmp_path):
    """"Not re-emitted" only means "revised away" when the input is a whole
    generation. A slice that brings back almost nothing it held proves
    nothing about the rows it left out, so nothing is closed — and the
    unconfirmed pairing is counted, not hidden."""
    held = [_idmc(f"h{i}", "2025-09-01", 100 + i) for i in range(6)]
    db = FakeDB(held=_held(_IDMC, held))
    tonight = [_idmc("n", "2025-09-01", 42)]
    report, db = _drive(monkeypatch, tmp_path, "phantom", spec=_spec(_IDMC),
                        emitted=tonight, db=db)
    assert db.superseded == []
    assert report["notes"]["value_revision_unconfirmed"] == 6


def test_a_one_row_dataset_is_revised_one_for_one(monkeypatch, tmp_path):
    """The other half of the completeness rule: when a group loses one
    reading and gains one, that is a revision whatever the dataset's size —
    a one-row dataset brings back 0 % of what it held on the night its only
    figure is revised."""
    db = FakeDB(held=_held(_IDMC, [_idmc("old", "2025-09-01", 106)]))
    report, db = _drive(monkeypatch, tmp_path, "phantom", spec=_spec(_IDMC),
                        emitted=[_idmc("new", "2025-09-01", 120)], db=db)
    assert db.superseded == [1000]
    assert report["notes"]["value_revisions"] == 1


# ── F444: our re-resolution is not the publisher's revision ─────────────────

def test_a_place_re_resolution_supersedes_but_is_not_a_revision(
        monkeypatch, tmp_path):
    ident = {"fields": ["indicator", "occurred_at"], "attrs": ["name"]}
    held = Row("d1", "demolitions.locality.structures", "2009-01-01",
               "unknown", "sid:structures", value_num=416, unit="structures",
               place_id=2, attrs={"name": "Jabal al Mukabbir"})
    now = Row("d1", "demolitions.locality.structures", "2009-01-01",
              "unknown", "sid:structures", value_num=416, unit="structures",
              place_id=11, located=True, attrs={"name": "Jabal al Mukabbir"})
    report, db = _drive(monkeypatch, tmp_path, "phantom", spec=_spec(ident),
                        emitted=[now], db=FakeDB(held=_held(ident, [held])))
    assert db.superseded == [1000]
    assert report["notes"]["place_resolution_changes"] == 1
    assert "revisions" not in report["notes"]
    assert "revisions" not in report          # no publisher correction logged


# ── F140: the tripwire judges the whole emission on a real run ──────────────

def test_max_observations_can_fire_on_a_real_nightly(monkeypatch, tmp_path):
    """Already-held rows were skipped BEFORE the tripwire counted, so on any
    night after the first the count was a handful and the guard could not
    fire. A dry run always judged the full emission; now the real run does."""
    ident = {"fields": ["indicator", "occurred_at"]}
    rows = [Row("d1", "x.y", f"2026-01-{i + 1:02d}", "day", f"s{i}",
                value_num=i) for i in range(8)]
    db = FakeDB(held=_held(ident, rows))
    with pytest.raises(SpecRefused, match=r"emitted 8 > expect.max_obs"):
        _drive(monkeypatch, tmp_path, "phantom",
               spec=_spec(ident, max_obs=5), emitted=rows, db=db)


# ── F136: a row refused by 044 lands in a bucket ─────────────────────────────

def test_a_row_refused_by_the_stable_id_index_is_counted(monkeypatch,
                                                         tmp_path):
    ident = {"fields": ["indicator", "occurred_at"]}
    rows = [Row("d1", "x.y", f"2026-01-{i + 1:02d}", "day", f"s{i}",
                value_num=i) for i in range(3)]
    report, db = _drive(monkeypatch, tmp_path, "phantom", spec=_spec(ident),
                        emitted=rows, db=FakeDB(refuse={"s1"}))
    assert report["written"] == 2
    assert report["refused_by_stable_id"] == 1


# ── F141: one category's crash is one category's failure ────────────────────

def test_one_crashing_category_does_not_skip_the_rest(monkeypatch, capsys):
    ran = []

    def fake_run(cat, dry_run=False):
        ran.append(cat)
        if cat == "b":
            raise json.JSONDecodeError("truncated", "", 0)
        return {"written": 1, "events_written": 0}

    monkeypatch.setattr(databank, "TRANSFORMERS", {"a": 1, "b": 1, "c": 1})
    monkeypatch.setattr(databank, "run", fake_run)
    assert databank.run_all() == 1
    assert ran == ["a", "b", "c"], "categories after the crash never ran"
    err = capsys.readouterr().err
    assert "FAIL b: JSONDecodeError" in err


# ── F028: a demolition locality resolves by its coordinate ──────────────────

def test_a_demolition_locality_with_a_coordinate_is_located():
    spec = load_spec("demolitions")
    pip = _PIP(answer=13)
    counts = Counter()
    rec = {"stable_id": "sidd", "demolition_dimension": "locality",
           "date": None,
           "location": {"region": "West Bank", "admin2_pcode": None,
                        "lat": 31.53, "lon": 35.09, "name": "Masafer Yatta",
                        "governorate": "Hebron"},
           "metrics": {"demolished": 40, "displaced": 12, "affected": 0},
           "sources": [{"name": "UN OCHA oPt — Data on Demolitions"}]}
    rows = databank.t_demolitions(rec, spec, {**_places(), "_pip": pip},
                                  counts)
    assert all(r.place_id == 13 and r.located for r in rows)
    assert "locality_resolution_miss" not in counts
    assert counts["place_rung:latlon"] == 1


def test_the_frozen_demolitions_corpus_is_located_and_floored(monkeypatch,
                                                              tmp_path):
    """Measured on data/frozen/demolitions.json.gz: lat/lon on 515 of 516
    locality records, admin2_pcode on 0. Before the rung, 158/904 rows were
    located and the run was green; now every coordinate is used, the one
    genuine miss (Al Malha) is the only one counted, and the spec's floor
    fails a run that falls back to 0.175."""
    pip = _PIP(answer=13)
    report, _db = _drive(monkeypatch, tmp_path, "demolitions", pip=pip,
                         dry_run=True)
    assert report["notes"]["locality_resolution_miss"] == 1
    assert pip.calls == 515
    assert report["located_pct"] >= 0.9
    # and the floor has teeth: the same corpus with no coordinate rung fails
    with pytest.raises(SpecRefused, match="located"):
        _drive(monkeypatch, tmp_path, "demolitions", pip=_PIP(answer=None),
               dry_run=True)


# ── F137: an event's identity includes who and between whom ─────────────────

def _journalist(sid, name):
    return {"stable_id": sid, "event_type": "killing of journalist",
            "date": "2023-10-07", "location": {"region": "Gaza Strip"},
            "metrics": {"killed": 1, "unit": "persons"},
            "actors": [name], "sources": [{"name": "Tech4Palestine"}]}


def _conflict_places():
    return {**_places(), "_pip": _PIP(), "_v1key": {}, "_commercial": {}}


def _journalist_run(monkeypatch, tmp_path, names, held=()):
    spec = load_spec("conflict")
    evs = [databank.t_conflict(_journalist(f"j{i}", n), spec,
                               _conflict_places(), Counter())[0]
           for i, n in enumerate(names)]
    # the real spec with the harness's stand-ins: its transform is replaced
    # by the rows above, and a few region-precise rows cannot meet a located
    # floor set for 7,638 UCDP points
    spec_ev = {**spec, "transform": None, "place": {},
               "expect": {"min_records": 1, "max_observations": 10}}
    report, db = _drive(monkeypatch, tmp_path, "conflict", spec=spec_ev,
                        emitted=evs, db=FakeDB(held_events=held))
    written = sorted(json.loads(p["attrs"])["actors"][0]
                     for p in db.event_inserts)
    return report, written, evs


def test_two_journalists_killed_on_one_day_are_two_events(monkeypatch,
                                                          tmp_path):
    """All 262 T4P journalist records are dated 2023-10-07, region-precise,
    killed 1. Keyed on type|day|place|point|metrics they are ONE event, and
    the guard's memory of this run's own rows collapsed them: a fresh load
    kept one journalist per region. Their names are in `actors`."""
    _r, written, _e = _journalist_run(monkeypatch, tmp_path,
                                      ["Ahmad", "Salma", "Rushdi"])
    assert written == ["Ahmad", "Rushdi", "Salma"], written


def test_a_newly_published_journalist_is_not_already_held(monkeypatch,
                                                          tmp_path):
    """The held side renders the stored event's own attrs through the same
    function, so a held name is still recognised — and a new name is not
    mistaken for it."""
    spec = load_spec("conflict")
    e1 = databank.t_conflict(_journalist("j0", "Ahmad"), spec,
                             _conflict_places(), Counter())[0]
    held = [(e1.event_type, "2023-10-07", "1", None, None, e1.metrics,
             {**e1.attrs, "dataset_key": e1.dataset_key,
              "v1_stable_id": "old-hash"})]
    report, written, _e = _journalist_run(
        monkeypatch, tmp_path, ["Ahmad", "Salma", "Rushdi"], held=held)
    assert written == ["Rushdi", "Salma"], written
    assert report["notes"]["event_already_held"] == 1


def test_a_citation_is_not_an_independent_source():
    """A Nakba village carries Palestine Open Maps plus four provenance-only
    citations. That is one witness, not five."""
    spec = load_spec("conflict")
    rec = {"stable_id": "v1", "event_type": "village depopulation",
           "date": "1948-05-12", "date_precision": "day",
           "location": {"region": "Palestine", "lat": 32.5, "lon": 34.95,
                        "gazetteer_key": "ayn_hawd_1948"},
           "metrics": {"displaced": 650},
           "sources": [{"name": "Palestine Open Maps locality registry"},
                       {"name": "Zochrot village page"},
                       {"name": "Atlas of Palestine"},
                       {"name": "Palestine Remembered village page"},
                       {"name": "Wikidata crosswalk"}]}
    (ev,) = databank.t_conflict(rec, spec, _conflict_places(), Counter())
    assert ev.independent_sources == 1


# ── F135: a Media Office bulletin is not an arithmetic fill ─────────────────

def test_each_report_source_gets_its_own_drop_reason():
    spec = load_spec("conflict_gaza")
    places = {"region": {"Gaza Strip": 1}}

    def reason(src):
        out = databank.t_conflict_gaza(
            {"report_date": "2026-09-01", "report_source": src,
             "killed_cum": 73000, "injured_cum": 170000},
            spec, places, Counter())
        return out.reason if isinstance(out, Drop) else "kept"

    assert reason("mohtel") == "kept"
    assert reason("missing") == "t4p_inferred"
    assert reason("gmotel") == "not_a_ministry_bulletin"
    assert reason("brand_new") == "unknown_report_source:brand_new"
    declared = {d["reason"] for d in spec["drop"]}
    assert "not_a_ministry_bulletin" in declared
    assert not any(r.startswith("unknown_report_source") for r in declared), \
        "an unknown report_source must stay undeclared, so it fails the run"


# ── F132: a per-locality total is not a day's flow ──────────────────────────

def test_demolition_locality_totals_are_registered_cumulative():
    from ops.load_registry import classify
    rules = load_spec("demolitions")["registry"]["rules"]
    pairs = [(i, u, 1) for i, u in [
        ("demolitions.locality.structures", "structures"),
        ("demolitions.locality.displaced", "persons"),
        ("demolitions.annual_total.structures", "structures"),
        ("demolitions.annual_total.displaced", "persons"),
        ("demolitions.annual_total.affected", "persons")]]
    got, _ = classify(pairs, rules)
    for ind in ("demolitions.locality.structures",
                "demolitions.locality.displaced"):
        assert (got[ind]["measure_kind"], got[ind]["grain"]) == (
            "cumulative", "period"), ind
    for ind in ("demolitions.annual_total.structures",
                "demolitions.annual_total.displaced",
                "demolitions.annual_total.affected"):
        assert (got[ind]["measure_kind"], got[ind]["grain"]) == (
            "flow", "year"), ind
    assert got["demolitions.annual_total.affected"]["canonical_unit"] == \
        "persons"


# ── database-backed (rolled back) ────────────────────────────────────────────

def _db_or_skip():
    psycopg = pytest.importorskip("psycopg")
    from resolve.db import dsn
    try:
        return psycopg.connect(dsn(), connect_timeout=3)
    except Exception as e:                                # noqa: BLE001
        pytest.skip(f"no database: {e}")


@pytest.fixture()
def pg():
    conn = _db_or_skip()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_a_spec_cannot_quietly_repoint_a_dataset(pg):
    """F447: ensure_datasets upserted v1_category only, so moving a dataset
    to another publisher in its spec 'succeeded' while every row kept the
    old publisher's licence and name. It refuses now; the move is a
    migration."""
    with pg.cursor() as cur:
        cur.execute("SELECT key FROM source ORDER BY key LIMIT 2")
        (a,), (b,) = cur.fetchall()
    spec = {"datasets": [{"key": "_t_repoint", "source": a}]}
    databank.ensure_datasets(pg, spec, "phantom")
    with pytest.raises(SpecRefused, match="re-pointing a dataset"):
        databank.ensure_datasets(
            pg, {"datasets": [{"key": "_t_repoint", "source": b}]}, "phantom")
