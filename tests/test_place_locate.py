"""P0-C.1b — the gazetteer's verdict on what the reader offers (needs the DB)."""
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
