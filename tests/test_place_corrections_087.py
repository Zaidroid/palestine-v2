"""087 — Karmelo (Taybeh, Ramallah), al-Fahs (Hebron), al-Banana (Jericho) sit in
the governorate their messages place them in. Skips until 087 is applied."""
import pytest

from resolve.db import connect

EXPECTED = {1759: "Ramallah", 1499: "Hebron", 1531: "Jericho"}


def _rows():
    with connect() as c, c.cursor() as cur:
        cur.execute("""
            SELECT p.place_id, p.attrs ? 'moved_by_087',
                   (SELECT g.name_en FROM place g
                     WHERE g.kind = 'governorate' AND g.merged_into IS NULL
                       AND ST_Contains(g.geom::geometry, p.centroid::geometry) LIMIT 1),
                   p.attrs->>'geom_before_087'
              FROM place p WHERE p.place_id = ANY(%s)""", (list(EXPECTED),))
        return cur.fetchall()


def test_087_three_checkpoints_sit_in_their_governorate():
    rows = _rows()
    if not rows or not all(moved for _, moved, _, _ in rows):
        pytest.skip("087 not applied yet")
    for pid, _, gov, before in rows:
        assert gov == EXPECTED[pid], (pid, gov)
        assert before and before.startswith("POINT(")       # rollback value kept
