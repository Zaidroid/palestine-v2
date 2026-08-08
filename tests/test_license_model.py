"""Stage 4: a licence is more than one boolean, and the model must hold.

Gate 5 asserts these properties in SQL, without the app. These test the
things SQL cannot: that the grading is derivable rather than typed, that the
generators agree with the database, and that the constraints refuse the
specific mistakes they were written for.
"""
from __future__ import annotations

import pytest

from resolve.db import connect

SHARE_ALIKE_SPDX = ("ODbL-1.0", "CC-BY-SA", "CC-BY-SA-3.0-IGO",
                    "CC-BY-NC-SA-3.0-IGO")


@pytest.fixture(scope="module")
def conn():
    with connect() as c:
        yield c


def test_every_source_has_a_redistribution_grade(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT key FROM source WHERE redistribution IS NULL")
        assert cur.fetchall() == []


def test_share_alike_matches_the_licence_string(conn):
    """The flag is DERIVED from the SPDX identifier, not typed per source.
    A hand-set flag is one that drifts the first time somebody adds a source
    in a hurry."""
    with conn.cursor() as cur:
        cur.execute("SELECT key, license_spdx, share_alike FROM source")
        for key, spdx, sa in cur.fetchall():
            expect = (spdx or "").startswith("ODbL") or "-SA" in (spdx or "")
            assert sa == expect, f"{key}: {spdx} share_alike={sa}"


def test_non_commercial_always_wins_over_share_alike(conn):
    """CC-BY-NC-SA is both. The -NC half is the binding one, and a naive
    grader that checks -SA first would call WHO's data share-alike-
    redistributable when it may not be redistributed at all."""
    with conn.cursor() as cur:
        cur.execute("""SELECT key, license_spdx, redistribution FROM source
                       WHERE license_spdx LIKE '%-NC-%'
                          OR license_spdx LIKE '%-NC'""")
        rows = cur.fetchall()
        assert rows, "no NC sources — the fixture this guards is gone"
        for key, spdx, grade in rows:
            assert grade == "no-redistribution", f"{key} ({spdx}) → {grade}"


def test_the_permissive_tier_never_carries_a_copyleft_obligation(conn):
    """The measured hole Stage 4 closed: 6,562 rows were being offered as
    unencumbered while requiring a derived database to be ODbL or CC-BY-SA."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM v_tier_commercial_permissive "
                    "WHERE share_alike")
        assert cur.fetchone()[0] == 0


def test_databank_commercial_is_the_permissive_tier(conn):
    """The alias must stay an alias. G5.5-G5.8 and every consumer read this
    name; if it ever diverges from the tier it is supposed to be, the old
    gates go on passing while testing something else."""
    with conn.cursor() as cur:
        cur.execute("SELECT (SELECT count(*) FROM databank_commercial), "
                    "(SELECT count(*) FROM v_tier_commercial_permissive)")
        a, b = cur.fetchone()
        assert a == b


def test_the_tiers_partition_the_commercial_rows(conn):
    """Permissive + share-alike must equal all commercial rows: a row that
    falls into neither is a row nobody can find, and one that falls into both
    is one whose obligation is optional."""
    with conn.cursor() as cur:
        cur.execute("""SELECT
            (SELECT count(*) FROM databank_serving WHERE commercial_use),
            (SELECT count(*) FROM v_tier_commercial_permissive),
            (SELECT count(*) FROM v_tier_commercial_sharealike)""")
        total, perm, sa = cur.fetchone()
        assert perm + sa == total
        assert sa > 0, "the share-alike tier is empty — did a grade drift?"


def test_a_dataset_override_cannot_be_asserted_without_evidence(conn):
    """054's constraint. An override that widens the source's grant without
    a URL, a date and the operative sentence is exactly how a portal-level
    'varies' becomes CC0 for one dataset because somebody was in a hurry."""
    with conn.cursor() as cur:
        cur.execute("SELECT dataset_id FROM dataset LIMIT 1")
        ds = cur.fetchone()[0]
        with pytest.raises(Exception):
            cur.execute("UPDATE dataset SET license_spdx = 'CC0-1.0' "
                        "WHERE dataset_id = %s", (ds,))
        conn.rollback()


def test_a_grant_nobody_can_quote_is_not_storable(conn):
    """057's constraint — the whole point of the permission ledger."""
    with conn.cursor() as cur:
        with pytest.raises(Exception):
            cur.execute("INSERT INTO source_permission (source_key, status) "
                        "VALUES ('_t', 'granted')")
        conn.rollback()


def test_an_expired_grant_is_no_grant(conn):
    """G5.12 treats expiry as absence. Asserted here against a temporary row
    so the gate's logic is exercised even when no grant exists yet."""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO source_permission
            (source_key, status, scope, asked_at, answered_at, expires_at,
             grant_text)
            VALUES ('_expired', 'granted', 's', '2025-01-01', '2025-01-02',
                    '2025-06-01', 'yes')""")
        cur.execute("""SELECT count(*) FROM source_permission
                       WHERE source_key = '_expired' AND status = 'granted'
                         AND (expires_at IS NULL OR expires_at >= current_date)""")
        assert cur.fetchone()[0] == 0
        conn.rollback()


def test_every_pending_permission_points_at_a_real_draft(conn):
    """The ledger names a letter path per source. A ledger pointing at files
    that do not exist is the same class of claim-without-substance the
    licence model exists to remove."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    with conn.cursor() as cur:
        cur.execute("SELECT source_key, letter_path FROM source_permission "
                    "WHERE letter_path IS NOT NULL")
        for key, path in cur.fetchall():
            assert (root / path).exists(), f"{key}: {path} does not exist"


def test_letters_do_not_overclaim(conn):
    """A letter that says we already hold something we do not, or promises
    something the platform does not do, is worse than no letter. The two
    concrete claims every draft makes are checked against the database."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(DISTINCT source_key) "
                    "FROM databank_serving")
        n, nsrc = cur.fetchone()
    for p in sorted((root / "db" / "scout" / "letters").glob("*.md")):
        text = p.read_text()
        assert "not sent" in text, f"{p.name}: missing the not-sent marker"
        m = re.search(r"alongside ([\d,]+) observations from (\d+) other",
                      text)
        assert m, f"{p.name}: the claim about our own size is missing"
        assert int(m.group(1).replace(",", "")) == n, \
            f"{p.name} claims {m.group(1)} rows, the databank serves {n:,}"
        assert int(m.group(2)) == nsrc, f"{p.name}: source count is stale"


def test_generated_views_match_the_category_registry(conn):
    """056 + ops/gen_category_views.py. Compared by row set, not text."""
    with conn.cursor() as cur:
        cur.execute("SELECT key, domain_rule FROM category WHERE active")
        for key, rule in cur.fetchall():
            cur.execute(f"SELECT (SELECT count(*) FROM v_{key}), "
                        f"(SELECT count(*) FROM databank_serving WHERE {rule})")
            got, want = cur.fetchone()
            assert got == want, f"v_{key}: {got} rows, rule selects {want}"


def test_a_domain_rule_may_not_name_an_unknown_column():
    from ops.gen_category_views import validate_rule
    assert validate_rule("v1_category = 'water'") is None
    assert validate_rule("v1_category = 'x' OR indicator LIKE 'y%'") is None
    assert "unknown identifier" in (validate_rule("secret_column = 1") or "")
    assert validate_rule("v1_category = 'x'; DROP TABLE source") is not None
    assert validate_rule("v1_category = 'x' -- comment") is not None
