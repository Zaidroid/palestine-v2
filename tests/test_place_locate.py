"""P0-C.1b — the gazetteer's verdict on what the reader offers (needs the DB)."""
import json

import pytest

from cascade.news import read
from ingest.sources.news_incidents import locate
from resolve.db import connect
from resolve.geo import governorate_pcode, resolve_place


@pytest.fixture(scope="module")
def conn():
    with connect() as c:
        yield c


def test_governorate_code_comes_from_the_governorate_row(conn):
    with conn.cursor() as cur:
        assert governorate_pcode(cur, "رام الله") == "PS0130"
        assert governorate_pcode(cur, "الخليل") == "PS0150"
        assert governorate_pcode(cur, "Nablus") == "PS0115"
        assert governorate_pcode(cur, "البيره") is None


def test_two_letters_resolve_by_exact_alias_only(conn):
    r = resolve_place("تل", {"admin": "نابلس"}, conn=conn, learn=False)
    assert r and r.name_ar == "تل" and r.method == "exact"
    assert resolve_place("تن", conn=conn, learn=False) is None


def test_fuzzy_can_be_switched_off(conn):
    assert resolve_place("عنزا", conn=conn, learn=False, fuzzy=False) is not None   # exact via the ending swap
    r = resolve_place("قصرهه", {"admin": "نابلس"}, conn=conn, learn=False)
    r2 = resolve_place("قصرهه", {"admin": "نابلس"}, conn=conn, learn=False, fuzzy=False)
    assert r2 is None or r2.method != "fuzzy"
    assert r is None or r.method in ("fuzzy", "exact", "contains")


def test_a_twin_in_the_stated_governorate_wins(conn):
    """Ramallah's المغير, not Jenin's, when the text says رام الله."""
    ram = resolve_place("المغير", {"admin": "رام الله"}, conn=conn, learn=False)
    jen = resolve_place("المغير", {"admin": "جنين"}, conn=conn, learn=False)
    assert ram and jen and ram.place_id != jen.place_id
    assert ram.admin2_pcode == "PS0130" and jen.admin2_pcode == "PS0101"


def test_locate_refuses_the_twin_elsewhere_and_falls_to_the_governorate(conn):
    r = read("مستوطنون يعتدون على المواطنين في بلدة الطيبة شرق رام الله")
    loc = locate(conn, r)
    assert loc.precision == "named" and loc.named_place == "الطيبه"
    with conn.cursor() as cur:
        cur.execute("SELECT admin2_pcode FROM place WHERE place_id = %s", (loc.place_id,))
        assert cur.fetchone()[0] == "PS0130"


def test_locate_reads_the_short_name_inside_the_fuller_alias(conn):
    r = read("قوات الاحتلال تقتحم قرية أبو فلاح شمال شرق رام الله")
    loc = locate(conn, r)
    assert loc.precision == "named" and loc.method in ("exact", "fuller")


def test_locate_keeps_a_border_village(conn):
    """بيت فجار sits on the Bethlehem/Hebron line; the text says Bethlehem."""
    r = read("قوات الاحتلال تقتحم بلدة بيت فجار جنوب بيت لحم")
    loc = locate(conn, r)
    assert loc.precision == "named"


def test_locate_never_pins_a_village_report_on_the_city(conn):
    r = read("قوات الاحتلال تقتحم قرية زززز الغربية شرق مدينة رام الله")
    loc = locate(conn, r)
    assert loc.precision == "governorate"


def test_locate_prefers_the_camp_over_the_checkpoint(conn):
    r = read("قوات الاحتلال تقتحم مخيم العروب شمال الخليل")
    loc = locate(conn, r)
    with conn.cursor() as cur:
        cur.execute("SELECT kind::text FROM place WHERE place_id = %s", (loc.place_id,))
        assert cur.fetchone()[0] == "locality"
    r2 = read("قوات الاحتلال تغلق حاجز العروب شمال الخليل")
    loc2 = locate(conn, r2)
    with conn.cursor() as cur:
        cur.execute("SELECT kind::text FROM place WHERE place_id = %s", (loc2.place_id,))
        assert cur.fetchone()[0] == "checkpoint"


# ── the resolver's own contract, on synthetic rows ───────────────────────────
# These need only the schema: every row is inserted inside a transaction that
# is rolled back (the tests/test_crowd.py pattern), with made-up names no real
# gazetteer holds, so they run on an empty database and on main-server alike.
import psycopg                                                     # noqa: E402

from resolve.db import dsn                                         # noqa: E402

NAMES = {  # synthetic, normalised keys
    "owner": "مغيرتجربه", "exact": "زقتجربه", "fuzzy_alias": "سنجلتجربهكوم",
    "fuzzy_probe": "سنجلتجربهكون", "literal": "بيتتجربا", "swapped": "بيتتجربه",
}


@pytest.fixture()
def db():
    """A transaction that is always rolled back. Never commits."""
    c = psycopg.connect(dsn())
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def _place(cur, kind="locality", name_ar="تجربه", admin2=None, attrs=None,
           servable=True, lon=35.2, lat=32.0, name_en=None) -> int:
    cur.execute("""INSERT INTO place (kind, name_ar, name_en, admin2_pcode, servable, attrs, geom)
                   VALUES (%s, %s, %s, %s, %s, %s::jsonb,
                           ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                   RETURNING place_id""",
                (kind, name_ar, name_en, admin2, servable,
                 json.dumps(attrs or {}, ensure_ascii=False), lon, lat))
    return cur.fetchone()[0]


def _alias(cur, key, pid, origin="pcbs", conf=0.85) -> None:
    cur.execute("""INSERT INTO place_alias (alias_norm, place_id, confidence, origin)
                   VALUES (%s, %s, %s, %s)""", (key, pid, conf, origin))


def _hits(cur, key):
    cur.execute("SELECT hits FROM place_alias WHERE alias_norm = %s", (key,))
    row = cur.fetchone()
    return row[0] if row else None


def _alias_count(cur):
    cur.execute("SELECT count(*) FROM place_alias")
    return cur.fetchone()[0]


def test_the_resolver_does_not_learn_by_default(db):
    """F071: /v2/insights and the kind-scoped fallback called resolve_place with
    no `learn=`, and the default wrote. A public probe must leave no trace."""
    with db.cursor() as cur:
        pid = _place(cur)
        _alias(cur, NAMES["exact"], pid)
        n = _alias_count(cur)
    r = resolve_place(NAMES["exact"], conn=db)
    assert r and r.place_id == pid
    r2 = resolve_place(f"اقتحام {NAMES['exact']}", conn=db)        # containment
    assert r2 and r2.place_id == pid and r2.method == "contains"
    with db.cursor() as cur:
        assert _hits(cur, NAMES["exact"]) == 0
        assert _alias_count(cur) == n


def test_learning_never_commits_the_callers_transaction(db):
    """F071(c): the learning branches called conn.commit() on a connection the
    CALLER owns — palhub_roads' batch was committed mid-loop, before its
    ingest_seen row existed. The owner of the transaction commits."""
    with db.cursor() as cur:
        pid = _place(cur)
        _alias(cur, NAMES["exact"], pid)
    assert resolve_place(NAMES["exact"], conn=db, learn=True)
    assert db.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS


def test_explicit_learning_works_and_never_promotes_a_fuzzy_guess(db):
    with db.cursor() as cur:
        pid = _place(cur)
        _alias(cur, NAMES["exact"], pid)
        _alias(cur, NAMES["fuzzy_alias"], pid)
        n = _alias_count(cur)
    assert resolve_place(NAMES["exact"], conn=db, learn=True).method == "exact"
    with db.cursor() as cur:
        assert _hits(cur, NAMES["exact"]) == 1                     # the True path still works
    fz = resolve_place(NAMES["fuzzy_probe"], conn=db, learn=True)
    assert fz and fz.method == "fuzzy"
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM place_alias WHERE alias_norm = %s", (NAMES["fuzzy_probe"],))
        assert cur.fetchone() is None, "a fuzzy guess became an alias"
        assert _alias_count(cur) == n


def test_a_learned_alias_is_not_served_as_an_exact_hit(db):
    """F071: an origin='observed' row was re-served as method 'exact' at 0.89+
    — a containment guess made once became a certainty for every caller."""
    with db.cursor() as cur:
        pid = _place(cur)
        _alias(cur, NAMES["exact"], pid, origin="observed", conf=0.62)
    r = resolve_place(NAMES["exact"], conn=db)
    assert r and r.place_id == pid
    assert r.method == "observed" and r.confidence <= 0.62


def test_a_twin_without_a_governorate_hint_says_ambiguous(db):
    """F070: the second المغير holds its key in attrs.twin_keys; a caller with no
    governorate got the alias owner at ~0.96 with ambiguous_with=0."""
    key = NAMES["owner"]
    with db.cursor() as cur:
        jenin = _place(cur, admin2="PS0101", name_ar=key)
        _alias(cur, key, jenin)
        ramallah = _place(cur, admin2="PS0130", name_ar=key, attrs={"twin_keys": [key]})
    r = resolve_place(key, conn=db)
    assert r and r.ambiguous_with >= 1
    assert {a[0] for a in r.alternatives} == {jenin, ramallah}
    assert r.confidence < 0.55              # below the crowd and palhub floors
    ram = resolve_place(key, {"admin2_pcode": "PS0130"}, conn=db)
    jen = resolve_place(key, {"admin2_pcode": "PS0101"}, conn=db)
    assert ram.place_id == ramallah and ram.ambiguous_with == 0 and ram.confidence >= 0.85
    assert jen.place_id == jenin and jen.ambiguous_with == 0 and jen.confidence >= 0.85
    # A phrase that contains the twin name is no less ambiguous (F171).
    c = resolve_place(f"اقتحام {key}", conn=db)
    assert c and c.method == "contains" and c.ambiguous_with >= 1
    c2 = resolve_place(f"اقتحام {key}", {"admin2_pcode": "PS0130"}, conn=db)
    assert c2 and c2.place_id == ramallah and c2.ambiguous_with == 0


def test_the_literal_spelling_beats_a_derived_probe(db):
    """F523: the ending-swapped key is an extra way in, never a competitor: a
    checkpoint owning 'بيته' must not win the text 'بيتا' from the village."""
    with db.cursor() as cur:
        village = _place(cur, name_ar=NAMES["literal"])
        _alias(cur, NAMES["literal"], village)
        gate = _place(cur, kind="checkpoint", name_ar=NAMES["swapped"])
        _alias(cur, NAMES["swapped"], gate, origin="checkpoint_db", conf=0.9)
    r = resolve_place(NAMES["literal"], conn=db)
    assert r and r.place_id == village


def test_the_swapped_spelling_still_serves_a_stated_kind(db):
    """The other half of F523: the swap probe exists because channels write
    عنزا where the gazetteer holds عنزه. A station that took the literal
    spelling first must not win a caller that asked for a locality."""
    with db.cursor() as cur:
        village = _place(cur, name_ar=NAMES["swapped"])
        _alias(cur, NAMES["swapped"], village)
        station = _place(cur, kind="station", name_ar=NAMES["literal"])
        _alias(cur, NAMES["literal"], station, origin="osm", conf=0.8)
    r = resolve_place(NAMES["literal"], {"prefer_kind": "locality"}, conn=db)
    assert r and r.place_id == village
    r2 = resolve_place(NAMES["literal"], conn=db)          # no stated kind: the literal
    assert r2 and r2.place_id == station


def test_a_generic_alias_makes_containment_decline_not_crash(db):
    """F524: a generic key ('مدخل') reached by the preposition-stripped probe
    passed the token filter, was dropped by the generic filter, and rows[0]
    raised IndexError."""
    with db.cursor() as cur:
        pid = _place(cur, kind="checkpoint", name_ar="مدخل")
        _alias(cur, "مدخل", pid, origin="observed", conf=0.6)
    assert resolve_place("اغلاق بمدخل", conn=db) is None


def test_containment_still_reads_whole_words_only(db):
    """The word-boundary contract the containment branch keeps: a whole word
    (or one behind a fused preposition) is a hit, a fragment inside a word is
    not — and is not handed to fuzzy either."""
    with db.cursor() as cur:
        pid = _place(cur)
        _alias(cur, NAMES["exact"], pid)
    assert resolve_place(f"اقتحام {NAMES['exact']} فجرا", conn=db).place_id == pid
    assert resolve_place(f"اقتحام ب{NAMES['exact']} فجرا", conn=db).place_id == pid   # fused ب
    assert resolve_place(f"اقتحام{NAMES['exact']}", conn=db, fuzzy=False) is None


def test_a_merge_never_takes_a_key_another_place_owns(db):
    """F316: place_merge indexed a fragment's names with ON CONFLICT DO UPDATE,
    so a checkpoint fragment named like the town moved the TOWN's key onto the
    entrance checkpoint. First writer wins, as in every other loader."""
    from resolve.place_merge import keep_spellings
    with db.cursor() as cur:
        town = _place(cur, name_ar="قلقتجربه")
        _alias(cur, "قلقتجربه", town)
        gate = _place(cur, kind="checkpoint", name_ar="مدخل قلقتجربه")
        frag = _place(cur, kind="checkpoint", name_ar="قلقتجربه")
        stats = {"aliases": 0}
        keep_spellings(cur, {"place_id": frag, "name_ar": "قلقتجربه", "name_en": None,
                             "v1key": "qalq_tajriba"}, gate, stats)
        cur.execute("SELECT place_id FROM place_alias WHERE alias_norm = %s", ("قلقتجربه",))
        assert cur.fetchone()[0] == town
        assert stats["keys_left_with_owner"] == [("قلقتجربه", town)]
        cur.execute("SELECT place_id FROM place_alias WHERE alias_norm = %s", ("qalq tajriba",))
        assert cur.fetchone()[0] == gate                      # a free spelling is still kept


def test_a_merge_keeps_where_each_observation_came_from(db):
    """F540: the observations of a merged fragment were repointed with no
    record of the fragment, so a wrong merge could not be undone."""
    from resolve.place_merge import move_evidence
    with db.cursor() as cur:
        canon = _place(cur, kind="checkpoint", name_ar="كونتجربه")
        frag = _place(cur, kind="checkpoint", name_ar="كونتجربه2")
        cur.execute("""INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                                           attribution_text,authority_rank)
                       VALUES ('_t_merge','t','telegram','NONE',false,'t',5)
                       RETURNING source_id""")
        sid = cur.fetchone()[0]
        cur.execute("""INSERT INTO state_observation (place_id,state_kind,value,observed_at,source_id)
                       VALUES (%s,'checkpoint_status','open',now(),%s)""", (frag, sid))
        assert move_evidence(cur, frag, canon) == 1
        cur.execute("SELECT place_id, attrs FROM state_observation WHERE source_id = %s", (sid,))
        pid, attrs = cur.fetchone()
        assert pid == canon and attrs["place_id_before_merge"] == frag


def test_the_gazetteer_loader_refuses_a_loaded_database(db):
    """F072: load_gazetteer answered a populated gazetteer with TRUNCATE place,
    place_alias RESTART IDENTITY CASCADE — every table referencing place with
    it. It now refuses, with the reason; it never truncates."""
    from resolve.load_gazetteer import refuse_reason
    with db.cursor() as cur:
        cur.execute("""INSERT INTO place (kind, name_en, geom, source_refs)
                       VALUES ('locality', 'T_loaded', ST_SetSRID(ST_MakePoint(35.2, 32.0), 4326),
                               '{"source": "v1_known_locations"}')""")
        assert refuse_reason(cur) is not None


def test_the_modern_closure_holds_only_servable_places(db):
    """F313: the pcode edge had no servable guard, and since 077 a reference
    row inside a polygon carries its code — so a Mandate village gained a
    modern parent beside its 1945 one (G4.11). And the closure only ever
    appended, so an edge from a pre-077 code outlived the re-code."""
    from ops.build_place_closure import rebuild
    with db.cursor() as cur:
        gov = _place(cur, kind="governorate", name_ar="محافظهتجربه", admin2="PS9901",
                     lon=34.1, lat=31.1)
        other = _place(cur, kind="governorate", name_ar="محافظهتجربه2", admin2="PS9902",
                       lon=34.2, lat=31.2)
        _place(cur, kind="district_mandate", name_ar=None, name_en="T_sub_1945",
               servable=False, lon=34.3, lat=31.3)
        ref = _place(cur, name_ar="قريهتجربه", admin2="PS9901", servable=False,
                     attrs={"historic": "mandate-palestine", "subdistrict_1945": "T_sub_1945"},
                     lon=34.4, lat=31.4)
        live = _place(cur, name_ar="بلدهتجربه", admin2="PS9901", lon=34.5, lat=31.5)
        # An edge left from the old code of `live`, before a re-code.
        cur.execute("""INSERT INTO place_closure VALUES (%s, %s, 1, 'modern', 'pcode')""",
                    (other, live))
        rebuild(cur)
        cur.execute("SELECT relation FROM place_closure WHERE descendant_id = %s", (ref,))
        assert [r[0] for r in cur.fetchall()] == ["mandate"]
        cur.execute("""SELECT ancestor_id FROM place_closure
                        WHERE descendant_id = %s AND relation = 'modern' AND depth = 1""", (live,))
        assert [r[0] for r in cur.fetchall()] == [gov]
