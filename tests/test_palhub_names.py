"""P1-A.1b — a palhub reading lives on a checkpoint row, never on a town.

The loader's fallback used to be the general resolver, which put "بوابة دير
دبوان" on Dayr Dibwan the village; once the earn-out made palhub's readings
assertions, checkpoint_serving listed towns as checkpoints. Migration 081
declares palhub's wording on the rows it means and creates the gates v1's list
never had; the loader accepts only checkpoint / crossing / road rows.

These tests need the database (main-server). The ones that need 081 applied
skip cleanly before it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.sources import palhub_roads as PR                               # noqa: E402
from resolve.db import connect                                             # noqa: E402

MIGRATION = "081_palhub_names_land_on_checkpoints.sql"


def _applied(cur) -> bool:
    cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (MIGRATION,))
    return cur.fetchone() is not None


def _latest_bulletins(cur, n=12):
    """One cycle: palhub posts one bulletin per governorate, twelve in all."""
    cur.execute("""SELECT c.raw_text FROM claim c JOIN source s USING (source_id)
                    WHERE s.key = %s ORDER BY c.reported_at DESC LIMIT %s""",
                (PR.SOURCE_KEY, n * 3))
    out = []
    for (text,) in cur.fetchall():
        if PR.is_bulletin(text or ""):
            out.append(PR.parse(text))
        if len(out) >= n:
            break
    return out


def _resolve_all(conn, cur):
    areas = PR._area_map(cur)
    declared = PR._declared_names(cur)
    cache: dict = {}
    seen: dict[str, object] = {}
    for b in _latest_bulletins(cur):
        admin2 = areas.get(b.area or "") if (b.area not in PR.NO_AREA) else None
        for rd in b.readings:
            if rd.name in seen:
                continue
            seen[rd.name] = PR._resolve(conn, rd.name, admin2, cache, declared)
    return seen


def test_a_palhub_reading_never_lands_off_a_checkpoint_row():
    """Whatever the resolver answers, the row is a checkpoint, a crossing or
    a junction — or there is no row. A town is never an answer (035 class)."""
    with connect() as conn, conn.cursor() as cur:
        resolved = _resolve_all(conn, cur)
        assert resolved, "no palhub bulletin in claim — nothing to test"
        ids = sorted({r.place_id for r in resolved.values() if r is not None})
        cur.execute("SELECT place_id, kind, name_ar FROM place WHERE place_id = ANY(%s)", (ids,))
        kinds = {pid: (kind, ar) for pid, kind, ar in cur.fetchall()}
    off = {name: kinds[r.place_id] for name, r in resolved.items()
           if r is not None and kinds[r.place_id][0] not in PR.ACCEPTED_KINDS}
    assert off == {}, f"palhub names resolved to a non-checkpoint row: {off}"


def test_declared_names_sit_on_servable_accepted_rows_once():
    with connect() as conn, conn.cursor() as cur:
        if not _applied(cur):
            pytest.skip(f"{MIGRATION} not applied")
        cur.execute("""SELECT n, p.place_id, p.kind, p.servable, p.merged_into
                         FROM place p, jsonb_array_elements_text(p.attrs->'palhub_names') n
                        WHERE p.attrs ? 'palhub_names'""")
        rows = cur.fetchall()
    assert len(rows) >= 60
    bad = [r for r in rows if r[2] not in PR.ACCEPTED_KINDS or not r[3] or r[4] is not None]
    assert bad == [], bad
    names = [r[0] for r in rows]
    assert len(names) == len(set(names)), "a palhub name declared on two rows"


def test_most_of_the_bulletin_resolves_after_081():
    """113 of ~190 names reached a checkpoint row before 081; 17 stay
    unresolved on purpose (no row, no anchor). Anything worse is a regression
    in the mapping or the bulletin's wording drifted — either way, look."""
    with connect() as conn, conn.cursor() as cur:
        if not _applied(cur):
            pytest.skip(f"{MIGRATION} not applied")
        resolved = _resolve_all(conn, cur)
    unresolved = sorted(n for n, r in resolved.items() if r is None)
    assert len(resolved) >= 150
    assert len(unresolved) <= 22, unresolved


def test_no_palhub_flow_written_to_a_town_since_081():
    with connect() as conn, conn.cursor() as cur:
        if not _applied(cur):
            pytest.skip(f"{MIGRATION} not applied")
        cur.execute("""SELECT count(*) FROM state_observation o
                         JOIN source s ON s.source_id = o.source_id
                         JOIN place p ON p.place_id = o.place_id
                        WHERE s.key = %s AND o.state_kind = 'checkpoint_flow'
                          AND p.kind <> ALL(%s)
                          AND o.observed_at > (SELECT applied_at FROM schema_migrations
                                                WHERE version = %s)
                          AND NOT (o.attrs ? 'moved_from')""",
                    (PR.SOURCE_KEY, list(PR.ACCEPTED_KINDS), MIGRATION))
        n = cur.fetchone()[0]
    assert n == 0, f"{n} palhub readings landed on a non-checkpoint row after 081"


def test_declared_wording_beats_the_resolver():
    """The declaration is exact wording, normalised, and wins over any fuzzy
    answer — that is the whole point of declaring it."""
    with connect() as conn, conn.cursor() as cur:
        if not _applied(cur):
            pytest.skip(f"{MIGRATION} not applied")
        declared = PR._declared_names(cur)
        cur.execute("""SELECT n, p.place_id FROM place p,
                       jsonb_array_elements_text(p.attrs->'palhub_names') n
                        WHERE p.attrs->>'palhub_names_by' = '081' LIMIT 5""")
        sample = cur.fetchall()
        for name, pid in sample:
            r = PR._resolve(conn, name, None, None, declared)
            assert r is not None and r.place_id == pid, (name, pid, r)
