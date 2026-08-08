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


def test_non_commercial_is_never_sellable(conn):
    """CC-BY-NC-SA is both NC and SA, and the NC half binds on the SELLING
    question. `commercial_use` is where that lives."""
    with conn.cursor() as cur:
        cur.execute("""SELECT key, license_spdx, commercial_use FROM source
                       WHERE license_spdx LIKE '%-NC-%'
                          OR license_spdx LIKE '%-NC'""")
        rows = cur.fetchall()
        assert rows, "no NC sources — the fixture this guards is gone"
        for key, spdx, commercial in rows:
            assert commercial is False, f"{key} ({spdx}) is marked sellable"


def test_non_commercial_is_still_redistributable(conn):
    """053 got this backwards and 064 fixed it. CC-BY-NC does not forbid
    redistribution — it forbids COMMERCIAL redistribution, and expressly
    permits the non-commercial kind with attribution, which is exactly what
    this databank is. The bug mislabelled 13,577 perfectly servable rows
    (WHO 12,577, IODA 1,000) as forbidden.

    Two columns, two questions, and one must not answer the other:
        commercial_use = false   may we SELL it?         no
        redistribution           may we SHARE it at all? yes, with credit"""
    with conn.cursor() as cur:
        cur.execute("""SELECT key, redistribution FROM source
                       WHERE license_spdx LIKE 'CC-BY-NC%'""")
        for key, grade in cur.fetchall():
            assert grade == "attribution", f"{key} → {grade}"


def test_un_tou_is_genuinely_not_redistributable(conn):
    """The distinction a family-wide rule cannot see. OCHA's terms do not
    merely say non-commercial — they say "without any right to resell or
    redistribute", in those words. Only reading the terms catches that, which
    is the argument for terms_evidence being a column rather than a comment."""
    with conn.cursor() as cur:
        cur.execute("""SELECT key, redistribution, terms_evidence FROM source
                       WHERE license_spdx = 'UN-ToU-NC'""")
        rows = cur.fetchall()
        assert rows
        for key, grade, evidence in rows:
            assert grade == "no-redistribution", f"{key} → {grade}"
            assert "redistribute" in (evidence or ""), \
                f"{key}: the operative sentence is not on the row"


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
        # The size claim is checked WHERE IT IS MADE, not required everywhere.
        # Most letters ask a publisher for data we do not have and describe
        # what they would be joining; the IMF letter asks about the tier of
        # data we already hold and makes a different claim, checked below.
        # Demanding the boilerplate would push a sentence into a letter where
        # it does not belong, which is how boilerplate stops being read.
        # A FLOOR, not an exact count. These letters quoted an exact figure
        # until 2026-08-08, when Stage 7 put categories on live upstreams and
        # the databank started growing most nights — so the number was wrong
        # by morning and the test failed daily, which trains people to ignore
        # it. "More than 205,000" stays true as the databank grows and is
        # still a checkable claim: it must be a real floor, and it must not
        # have drifted so far below the truth that it undersells by a tenth.
        m = re.search(r"alongside more than ([\d,]+) observations "
                      r"from (\d+) other", text)
        if m:
            claimed = int(m.group(1).replace(",", ""))
            assert claimed <= n, \
                f"{p.name} claims more than {claimed:,}; the databank " \
                f"serves {n:,} — an overclaim to a publisher"
            assert n < claimed * 1.10, \
                f"{p.name} claims more than {claimed:,} but the databank " \
                f"serves {n:,}; round the letter up"
            assert int(m.group(2)) == nsrc, f"{p.name}: source count is stale"


def test_the_imf_letter_states_the_right_number_of_rows(conn):
    """It tells the IMF how much of their data we hold. If that number drifts
    the letter becomes a misstatement to a publisher, which is worse than a
    stale figure in an internal document."""
    import re
    from pathlib import Path
    p = (Path(__file__).resolve().parent.parent
         / "db" / "scout" / "letters" / "imf.md")
    # \s+ rather than a space: the letter is hard-wrapped, and a regex that
    # assumes one line fails on a document that reads perfectly.
    m = re.search(r"We hold ([\d,]+)\s+World Economic Outlook observations",
                  p.read_text())
    assert m, "the IMF letter no longer states how much we hold"
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM databank_serving "
                    "WHERE source_key = 'imf'")
        assert int(m.group(1).replace(",", "")) == cur.fetchone()[0]


def test_imf_is_redistributable_but_not_sellable(conn):
    """Read at the publisher 2026-08-08 (063). The IMF's special Data terms
    permit publishing and distributing WEO figures with attribution, and send
    commercial reuse to copyright@imf.org. Both halves must hold: the rows
    stay served, and they stay out of every commercial tier."""
    with conn.cursor() as cur:
        cur.execute("""SELECT redistribution, commercial_use, attribution_text,
                              terms_verified_at IS NOT NULL
                       FROM source WHERE key = 'imf'""")
        grade, commercial, attr, verified = cur.fetchone()
        assert grade == "attribution" and commercial is False and verified
        assert "World Economic Outlook" in attr, \
            "the IMF specifies the attribution format; it must be used"
        cur.execute("""SELECT
            (SELECT count(*) FROM databank_serving WHERE source_key='imf'),
            (SELECT count(*) FROM v_tier_commercial_permissive
             WHERE source_key='imf'),
            (SELECT count(*) FROM v_tier_open WHERE source_key='imf')""")
        served, sellable, open_tier = cur.fetchone()
        assert served > 0 and sellable == 0 and open_tier == served


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


def test_bulk_is_narrower_than_query_and_never_wider(conn):
    """066's distinction. A query returning credited facts is reporting; a
    file is a database, and a licence governs the second. If bulk ever equals
    serving, either every source became redistributable or the filter died."""
    with conn.cursor() as cur:
        cur.execute("""SELECT (SELECT count(*) FROM databank_serving),
                              (SELECT count(*) FROM databank_bulk)""")
        served, bulk = cur.fetchone()
        assert 0 < bulk < served


def test_nothing_ungranted_can_reach_a_bulk_export(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM databank_bulk
                       WHERE redistribution NOT IN
                             ('open', 'attribution', 'share-alike')""")
        assert cur.fetchone()[0] == 0


def test_what_bulk_withholds_is_enumerated_not_absent(conn):
    """An export that is quietly short reads as 'this is everything'. Every
    withheld row must appear in v_withheld with a reason."""
    with conn.cursor() as cur:
        cur.execute("""SELECT (SELECT count(*) FROM databank_serving)
                            - (SELECT count(*) FROM databank_bulk),
                              (SELECT COALESCE(sum(rows_held), 0)
                               FROM v_withheld)""")
        missing, enumerated = cur.fetchone()
        assert missing == enumerated
        cur.execute("SELECT count(*) FROM v_withheld WHERE reason IS NULL")
        assert cur.fetchone()[0] == 0


def test_the_release_builder_refuses_an_incompatible_aggregate():
    """Three incompatible copylefts live in this databank — ODbL-1.0,
    CC-BY-SA and WHO's CC-BY-NC-SA-3.0-IGO — so no single relicensed
    aggregate can hold them. The builder must say so rather than produce one.
    Going open source TRIGGERS share-alike; it does not avoid it."""
    import subprocess
    import sys as _s
    r = subprocess.run([_s.executable, "-m", "ops.export_open_data",
                        "--license", "CC-BY-4.0"],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "share-alike" in (r.stdout + r.stderr)


def test_the_readme_does_not_overstate_the_databank(conn):
    """A README with numbers in it goes stale silently, and this one is the
    first thing anyone reads.

    Until 2026-08-08 these were checked as EXACT figures, on the premise that
    databank counts move only when a human ships a migration. Stage 7 ended
    that premise: several categories now read live upstreams, so the counts
    move most nights and an exact README was guaranteed to be wrong by
    morning — failing this test daily, which is how a test stops being read.

    So every figure is a FLOOR, written `205,000+`, and two things are
    checked: it must be true (never claim more than the database holds), and
    it must not undersell by more than a tenth (a floor so old it is
    misleading in the other direction). The Tier-1 counters stay rounded for
    the original reason — they grow every few minutes."""
    import re
    from pathlib import Path
    r = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    with conn.cursor() as cur:
        for sql, label, pattern in [
            ("SELECT count(*) FROM observation WHERE upper_inf(sys_period)",
             "current observations", r"([\d,]+)\+ observations"),
            ("SELECT count(*) FROM source", "sources",
             r"(\d+) sources"),
            ("SELECT count(*) FROM databank_serving", "queryable",
             r"queryable through the API, credited \| ([\d,]+)\+"),
            ("SELECT count(*) FROM databank_bulk", "exportable",
             r"exportable as a file \| ([\d,]+)\+"),
            ("SELECT COALESCE(sum(rows_held),0) FROM v_withheld", "withheld",
             r"not exportable[^|]*\| ([\d,]+)\+"),
            ("SELECT count(*) FROM databank_bulk WHERE share_alike",
             "share-alike", r"share-alike obligation \| ([\d,]+)\+"),
            ("SELECT count(*) FROM databank_internal "
             "WHERE indicator='martyrs.identified_killed'", "memorial",
             r"([\d,]+)\+ identified people"),
        ]:
            cur.execute(sql)
            actual = cur.fetchone()[0]
            m = re.search(pattern, r)
            assert m, f"README no longer states its {label} figure"
            claimed = int(m.group(1).replace(",", ""))
            assert claimed <= actual, \
                f"README claims {claimed:,} {label}, the database has " \
                f"{actual:,} — an overclaim"
            assert actual < claimed * 1.10 or actual - claimed < 100, \
                f"README's {label} floor ({claimed:,}) is far below the " \
                f"real {actual:,}; raise it"
    # and the live counters must NOT be quoted exactly
    assert not re.search(r"1,0\d\d,\d\d\d state observations", r), \
        "a live-growing counter is quoted exactly; round it"
