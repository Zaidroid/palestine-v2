"""Audit 2026-09-25, area 08 — GAZETTEER-01 02 03 04."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve import geo, load_gazetteer, place_merge          # noqa: E402


@pytest.fixture(scope="module")
def conn():
    try:
        from resolve.db import connect
    except Exception as e:                                       # noqa: BLE001
        pytest.skip(str(e))
    with connect() as c:
        yield c


def test_gazetteer_01_a_twin_is_named_without_a_hint_and_chosen_with_one(conn):
    bare = geo.resolve_place("المغير", conn=conn)
    assert bare and bare.ambiguous_with >= 1, bare
    codes = {bare.admin2_pcode} | {a[2] for a in bare.alternatives}
    assert {"PS0130", "PS0101"} <= codes, codes
    assert bare.confidence < 0.8                        # divided, as the fuzzy branch does
    ram = geo.resolve_place("المغير", {"admin": "رام الله"}, conn=conn)
    jen = geo.resolve_place("المغير", {"admin": "جنين"}, conn=conn)
    assert ram.admin2_pcode == "PS0130" and ram.ambiguous_with == 0
    assert jen.admin2_pcode == "PS0101" and jen.ambiguous_with == 0
    assert ram.place_id != jen.place_id
    one = geo.resolve_place("نابلس", conn=conn)
    assert one and one.ambiguous_with == 0 and one.alternatives == []


def test_gazetteer_02_learning_is_opt_in_and_never_commits_a_borrowed_transaction():
    assert inspect.signature(geo.resolve_place).parameters["learn"].default is False
    src = inspect.getsource(geo.resolve_place)
    # every commit sits under `if own:` — the caller's transaction is the caller's
    for i in [m.start() for m in __import__("re").finditer(r"conn\.commit\(\)", src)]:
        assert "if own:" in src[max(0, i - 80):i], src[max(0, i - 80):i]
    # every serving and ingestion caller says learn=False explicitly
    import subprocess
    out = subprocess.run(["grep", "-rn", "resolve_place(", "serve", "ingest", "crowd", "ops"],
                         capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent).stdout
    calls = [l for l in out.splitlines() if "def resolve_place" not in l and "learn=True" in l]
    assert calls == [], calls


def test_gazetteer_03_the_loader_refuses_a_populated_database(conn, monkeypatch):
    src = inspect.getsource(load_gazetteer)
    assert "cur.execute(\"TRUNCATE" not in src and "TRUNCATE place" not in src
    with conn.cursor() as cur:
        reason = load_gazetteer.refuse_if_populated(cur)
    assert reason and "refusing" in reason
    assert load_gazetteer.GOV_AR["PS0130"].startswith("رام الله")      # the 077 scheme
    assert "PS0107" not in load_gazetteer.GOV_AR


def test_gazetteer_04_place_merge_never_steals_an_alias():
    src = inspect.getsource(place_merge)
    assert "DO UPDATE SET place_id=EXCLUDED.place_id" not in src
    assert "ON CONFLICT (alias_norm) DO NOTHING" in src and "aliases_owned_elsewhere" in src
