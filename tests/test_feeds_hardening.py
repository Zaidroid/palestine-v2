"""External feeds — the audit findings of 2026-09-25, each pinned by the input
that broke it.

    ./.venv/bin/python -m pytest tests/test_feeds_hardening.py -q

Two kinds of test live here. The pure ones (parsers, pairing, scheduling) run
anywhere. The database ones exercise the real SQL — belief, the fuel-price
views, the MoH upsert — inside a transaction that is always rolled back, the
tests/test_crowd.py pattern; they skip, saying why, where no database answers.
Nothing here fetches from the internet: every page, feed and series is a
fixture or a hand-made input.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── the database fixture ─────────────────────────────────────────────────────

@pytest.fixture()
def db():
    """A transaction that is always rolled back. Never commits."""
    psycopg = pytest.importorskip("psycopg")
    from resolve.db import dsn
    try:
        conn = psycopg.connect(dsn(), connect_timeout=5)
    except (KeyError, psycopg.OperationalError) as exc:
        pytest.skip(f"no v2 database reachable here ({type(exc).__name__})")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _place(cur, name_ar: str, kind: str = "locality", lon: float = 35.25,
           lat: float = 32.2) -> int:
    cur.execute("""INSERT INTO place (kind, name_ar, name_en, geom)
                   VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                   RETURNING place_id""", (kind, name_ar, f"_t {name_ar}", lon, lat))
    return cur.fetchone()[0]


def _source(cur, key: str, kind: str = "telegram") -> int:
    cur.execute("""INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                                       attribution_text, authority_rank)
                   VALUES (%s, %s, %s, 'NONE', false, %s, 3)
                   ON CONFLICT (key) DO NOTHING""", (key, key, kind, key))
    cur.execute("SELECT source_id FROM source WHERE key = %s", (key,))
    return cur.fetchone()[0]


# ═════════════════════════════════════════════════════════════════════════════
# POWER (ingest/sources/power.py)
# ═════════════════════════════════════════════════════════════════════════════

from ingest.sources import power  # noqa: E402

LOCAL = power.LOCAL_TZ

_INDEX = """
<a class="m4" href="?page=details&newsID=5001&cat=6"><div>فصل تيار كهربائي في قرية تل
<p><i class="fa fa-calendar"></i>31/08/2026</p></div></a>
<a class="m4" href="?page=details&newsID=5002&cat=6"><div>فصل تيار كهربائي في سالم
<p><i class="fa fa-calendar"></i>31/08/2026</p></div></a>
"""


def _body(day: str, start: str = "8:30 صباحاً", end: str = "1:30 من ظهر") -> str:
    return (f"تاريخ النشر: 31/08/2026 - عدد القراءات: 12 تعتذر شركة توزيع كهرباء "
            f"الشمال عن فصل التيار الكهربائي وذلك في الفترة الواقعة مابين الساعة "
            f"{start} الى الساعة {end} يوم الثلاثاء الموافق {day}.")


# The scenario day. Belief (resolve/belief.py) reads a bounded window behind
# the DATABASE's clock and refuses stamps from its future, so the notices are
# dated two days ago rather than on a fixed calendar day: every tick below is
# in the real past and inside power's window.
DAY = (datetime.now(LOCAL) - timedelta(days=2)).date()


def _dmy(d: date) -> str:
    return f"{d.day}/{d.month}/{d.year}"


@pytest.fixture()
def nedco(db, monkeypatch):
    """NEDCO's two pages and two notice bodies, and a resolver that knows the
    two places — so `load` runs its real SQL against a rolled-back database."""
    with db.cursor() as cur:
        places = {"قرية تل": _place(cur, "قرية تل _t"), "سالم": _place(cur, "سالم _t")}
    bodies = {"5001": _body(_dmy(DAY + timedelta(days=1))),   # the day after DAY
              "5002": _body(_dmy(DAY))}                       # DAY, 08:30 → 13:30

    def fake_get(url: str) -> str:
        if "newsid=" in url:
            return bodies[url.rsplit("=", 1)[1]]
        return _INDEX if "cat=6" in url else ""

    def fake_resolve(text, conn=None, learn=True, **_):
        pid = places.get(text)
        return SimpleNamespace(place_id=pid, name_ar=text, name_en=None) if pid else None

    monkeypatch.setattr(power, "_get", fake_get)
    monkeypatch.setattr(power, "resolve_place", fake_resolve)
    return SimpleNamespace(conn=db, places=places, bodies=bodies)


def _current(conn, place_id):
    with conn.cursor() as cur:
        cur.execute("""SELECT value, observed_at FROM state_current
                        WHERE place_id = %s AND state_kind = 'power'""", (place_id,))
        return cur.fetchone()


def _at(days_after: int, hh: int, mm: int = 0) -> datetime:
    d = DAY + timedelta(days=days_after)
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=LOCAL).astimezone(timezone.utc)


def test_a_future_scheduled_cut_is_never_believed_as_an_active_one(nedco):
    """F038/F073. At 10:00 on DAY the سالم cut is live and the قرية تل
    notice is for the NEXT day. The private rebuild took the newest power row of
    any modality, so the 'scheduled' announcement became قرية تل's belief and
    /v2/services reported a live cut there — a day early, with window_start in
    the future in the same payload."""
    stats = power.load(conn=nedco.conn, now=_at(0, 10))
    assert stats["announced"] == 2 and stats["written"] == 1

    assert _current(nedco.conn, nedco.places["سالم"])[0] == "cut"
    tel = _current(nedco.conn, nedco.places["قرية تل"])
    assert tel is None or tel[0] != "cut", f"scheduled notice served as belief: {tel}"


def test_a_cut_ends_when_its_announced_window_ends(nedco):
    """F037. The last in-window assertion used to decay for ~22 h past the
    announced end (0.9 at a 12 h half-life above a 0.25 floor), so the place
    stayed under power_cuts_active until the next morning. The notice is the
    evidence the cut ends: at window_end the belief becomes `unknown`."""
    power.load(conn=nedco.conn, now=_at(0, 13, 25))       # last tick inside
    assert _current(nedco.conn, nedco.places["سالم"])[0] == "cut"

    stats = power.load(conn=nedco.conn, now=_at(0, 13, 40))   # first tick after
    assert stats["ended"] == 1
    value, observed = _current(nedco.conn, nedco.places["سالم"])
    assert value == "unknown"
    assert observed == _at(0, 13, 30), "the end is stamped at window_end, not the clock"

    # Once per notice: a later run writes nothing more.
    again = power.load(conn=nedco.conn, now=_at(0, 16))
    assert again["ended"] == 0 and again["written"] == 0


def test_a_window_nobody_asserted_is_not_closed(nedco):
    """A notice first seen after its window passed never asserted a cut, so
    there is nothing to end — writing `unknown` there would be noise."""
    stats = power.load(conn=nedco.conn, now=_at(1, 20))
    assert stats["written"] == 0 and stats["ended"] == 0
    assert _current(nedco.conn, nedco.places["سالم"]) is None


def test_noon_written_with_min_is_noon_not_midnight():
    """F184. 'الساعة 12:00 من ظهر' — the marker preceded by 'من', the notices'
    own form — left the marker empty, and the bare 12 became 00:00: a
    noon-to-three cut asserted from midnight."""
    window = power.parse_window(
        "من الساعة 12:00 من ظهر حتى الساعة 3:00 مساء يوم الثلاثاء الموافق 1/9/2026")
    assert window is not None
    start, end = (w.astimezone(LOCAL).strftime("%H:%M") for w in window)
    assert (start, end) == ("12:00", "15:00")


def test_the_marker_after_min_still_reads_every_shape_it_did():
    for body, expected in [
        ("الساعة 8:30 صباحاً الى الساعة 1:30 من ظهر يوم الثلاثاء الموافق 1/9/2026", ("08:30", "13:30")),
        ("من الساعة 12:30 ظهرا حتى الساعة 3:00 مساء الموافق 1/9/2026", ("12:30", "15:00")),
        ("من الساعة 9:00 من صباح يوم الموافق 1/9/2026 حتى الساعة 11:00", ("09:00", "11:00")),
    ]:
        w = power.parse_window(body)
        assert w is not None, body
        assert tuple(x.astimezone(LOCAL).strftime("%H:%M") for x in w) == expected, body


def test_a_two_digit_year_is_this_century_not_year_26():
    """F466 (the year half). 'الموافق 1/9/26' built a window in year 0026:
    counted as parsed, never active, the announced cut silently lost."""
    w = power.parse_window("من الساعة 9:00 صباحا وحتى الساعة 11:00 صباحا الموافق 1/9/26")
    assert w is not None
    assert w[0].astimezone(LOCAL).date() == date(2026, 9, 1)
    assert power.parse_window("من الساعة 9:00 صباحا وحتى الساعة 11:00 صباحا الموافق 1/9/0003") is None


# ═════════════════════════════════════════════════════════════════════════════
# FUEL PRICES (ingest/sources/fuel_prices.py)
# ═════════════════════════════════════════════════════════════════════════════

from cascade import fuel_price as fp            # noqa: E402
from ingest.sources import fuel_prices          # noqa: E402


class _Rows:
    """A cursor that answers one SELECT with the rows it was given."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_a, **_k):
        pass

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


def _list_text(today: date, price: float) -> str:
    return (f"أعلنت الهيئة العامة للبترول أسعار المحروقات، اعتبارا من "
            f"01/{today.month:02d}/{today.year}: بنزين 95: {price} شيكل.")


def test_an_outlets_rss_claim_and_its_web_page_are_one_unit():
    """F036. qudsn.co is read twice: its article (unit web:qudsn.co) and its
    RSS item, which rss_news stores as a claim under rss_qudsn (unit
    src:<id>). Two units from one newsroom satisfied the two-outlet rule."""
    now = datetime.now(timezone.utc)
    cur = _Rows([(1, _list_text(now.date(), 8.15), now, 77, "rss_qudsn", "src:77")])
    (claim,) = fuel_prices.claim_rows(cur)
    web_unit = f"web:{fuel_prices._domain('https://qudsn.co/post/1')}"
    assert claim["independence_unit"] == web_unit == "web:qudsn.co"
    assert claim["outlet"] == "rss_qudsn", "the transport is still recorded as the outlet"


def test_every_rss_feed_rss_news_reads_maps_to_its_publishers_web_unit():
    from ingest.sources import rss_news
    units = fuel_prices.newsroom_units()
    assert set(units) == {f["key"] for f in rss_news.FEEDS}
    feed_domains = {fuel_prices._domain(u) for u in fuel_prices.FEEDS}
    for key, unit in units.items():
        assert unit.startswith("web:") and unit[4:] in feed_domains, (key, unit)


def test_a_claim_from_any_other_channel_keeps_its_own_unit():
    now = datetime.now(timezone.utc)
    cur = _Rows([(2, _list_text(now.date(), 8.15), now, 9, "tg_somechannel", "grp:roads")])
    (claim,) = fuel_prices.claim_rows(cur)
    assert claim["independence_unit"] == "grp:roads"


def test_one_newsroom_is_not_believed_on_its_own_word(db):
    """F036 end to end, on the real 071-073 views: the qudsn.co article and
    the rss_qudsn claim carrying the same list are one vote, so the price is
    not believed. The price is one no real list has ever carried, so live
    rows on main-server cannot join the vote."""
    today = datetime.now(timezone.utc).date()
    eff = date(today.year, today.month, 1)
    text = _list_text(today, 13.37)
    with db.cursor() as cur:
        sid = _source(cur, "rss_qudsn", kind="rss")
        cur.execute("""INSERT INTO claim (source_id, raw_ref, raw_text, reported_at)
                       VALUES (%s, 'test://f036', %s, now()) RETURNING claim_id""", (sid, text))
        claim_id = cur.fetchone()[0]
        (claim,) = [r for r in fuel_prices.claim_rows(cur) if r["claim_id"] == claim_id]
        ann = fp.parse(text, today)
        web = fuel_prices._row(ann, outlet="qudsn.co", unit="web:qudsn.co", text=text,
                               url="https://qudsn.co/post/f036", published=None)
        for row in (claim, web):
            assert row["verdict"] == "prices"
            cur.execute(fuel_prices._INSERT, row)
        cur.execute("""SELECT units, named_units, distinct_texts FROM fuel_price_votes
                        WHERE effective_from = %s AND product = 'gasoline_95' AND price = 13.37""",
                    (eff,))
        assert cur.fetchone() == (1, 1, 1)
        cur.execute("""SELECT count(*) FROM fuel_price_believed
                        WHERE effective_from = %s AND product = 'gasoline_95' AND price = 13.37""",
                    (eff,))
        assert cur.fetchone()[0] == 0


def _due_at(first: datetime, now: datetime) -> bool:
    return fuel_prices._due(_Rows([(first, False)]), "https://raya.ps/x", now)


def test_an_empty_page_is_retried_every_two_hours_not_every_tick():
    """F180. An unchanged page hashes the same, inserts nothing, and
    max(fetched_at) never moved — so from hour two the retry fired on every
    15-minute tick. The schedule now keys on the first fetch: one retry in
    the first tick of each two-hour slot."""
    first = datetime(2026, 8, 31, 18, 0, 40, tzinfo=timezone.utc)
    ticks = [datetime(2026, 8, 31, 18, 15, tzinfo=timezone.utc) + timedelta(minutes=15 * k)
             for k in range(4 * 60)]            # 60 hours of ticks
    due = [t for t in ticks if _due_at(first, t)]
    assert len(due) == 23, len(due)             # one per slot from 2h to 48h
    gaps = {b - a for a, b in zip(due, due[1:])}
    assert gaps == {timedelta(hours=2)}
    assert due[0] - first < timedelta(hours=2, minutes=15)
    assert all(t - first < fuel_prices.RETRY_EMPTY_FOR for t in due)


def test_a_page_that_gave_a_list_is_never_refetched():
    first = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
    assert not fuel_prices._due(_Rows([(first, True)]), "u", first + timedelta(hours=2, minutes=5))
    assert fuel_prices._due(_Rows([(None, None)]), "u", first)


def test_the_table_unit_is_looked_for_once_per_page(monkeypatch):
    """F464. The whole-page search sat inside the per-row loop."""
    calls = []
    real = fuel_prices._SHEKEL_TABLE

    class Counting:
        def search(self, page):
            calls.append(1)
            return real.search(page)

    monkeypatch.setattr(fuel_prices, "_SHEKEL_TABLE", Counting())
    rows = "".join(f"<tr><td>صنف {i}</td><td>{i}.5</td></tr>" for i in range(40))
    fuel_prices.article_text(f"<table><tr><th>الصنف</th><th>السعر/ شيكل</th></tr>{rows}</table>")
    assert len(calls) == 1


# ═════════════════════════════════════════════════════════════════════════════
# GAZA MoH (cascade/moh_gaza.py, ingest/sources/moh_gaza.py)
# ═════════════════════════════════════════════════════════════════════════════

from cascade import moh_gaza                    # noqa: E402
from ingest.sources import moh_gaza as moh_ingest   # noqa: E402

_TITLE = "🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة\n"
_DAILY = "⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية:\n* عدد الشهداء 7 شهداء\n"
_CUMULATIVE = ("🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:\n"
               "• العدد التراكمي للشهداء: 73,356\n• العدد التراكمي للإصابات: 174,185\n")


@pytest.mark.parametrize("unknown", [
    # the 2025 form, the whole block on one line
    "🔴 منذ استئناف العدوان في 18 مارس 2025: إجمالي عدد الشهداء: 5,000 / "
    "إجمالي عدد الإصابات: 16,000\n",
    # the same block, one figure per line
    "🔴 منذ استئناف العدوان في 18 مارس 2025:\n• إجمالي عدد الشهداء: 5,000\n"
    "• إجمالي عدد الإصابات: 16,000\n",
    # a header with no section mark, ending at its colon
    "منذ استئناف العدوان في 18 مارس 2025:\n• إجمالي عدد الإصابات: 16,000\n",
])
def test_an_unknown_section_is_never_filed_under_the_tier_before_it(unknown):
    """F176. The tier switched only on the three known headers; any other
    header left `current` at the previous tier and setdefault accepted what
    that tier lacked — 16,000 injuries filed as ONE DAY's."""
    rep = moh_gaza.parse(_TITLE + _DAILY + unknown + _CUMULATIVE)
    assert rep.tiers["daily"] == {"deaths": 7}
    assert rep.tiers["cumulative"] == {"deaths": 73356, "injuries": 174185}
    assert all(v < 1000 for v in rep.tiers["daily"].values())
    assert any("unknown section" in x for x in rep.rejected)


def test_the_other_spelling_of_the_cumulative_header_is_a_cumulative_header():
    text = _TITLE + _DAILY + ("🔴*الحصيلة التراكمية للعدوان:*\n"
                              "- إجمالي عدد الشهداء: 73,919\n- إجمالي عدد الإصابات: 174,977\n")
    rep = moh_gaza.parse(text)
    assert rep.tiers["cumulative"] == {"deaths": 73919, "injuries": 174977}
    assert rep.tiers["daily"] == {"deaths": 7}


def test_a_report_typed_without_the_hamza_is_still_a_report():
    """F418. 'الاحصائي' / 'اطلاق' / 'اصابات' are the same words; with the hamza
    required the day was silently not a report."""
    text = ("🔴 التقرير الاحصائي اليومي\n"
            "⭕ خلال الـ 24 ساعة الماضية:\n* عدد الشهداء 7 شهداء\n• عدد الاصابات: 23 اصابة\n"
            "🔴 منذ وقف اطلاق النار (11 أكتوبر):\n• اجمالي عدد الشهداء: 1,230\n"
            "• اجمالي عدد الاصابات: 4,076\n")
    rep = moh_gaza.parse(text)
    assert rep.is_report
    assert rep.tiers == {"daily": {"deaths": 7, "injuries": 23},
                         "since_ceasefire": {"deaths": 1230, "injuries": 4076}}


def _moh_setup(cur):
    sid = _source(cur, "_t_moh_source")
    cur.execute("""INSERT INTO dataset (key, name, source_id) VALUES ('_t_gaza_moh', 't', %s)
                   RETURNING dataset_id""", (sid,))
    return cur.fetchone()[0], _place(cur, "غزة _t", kind="region", lon=34.4, lat=31.4)


def _moh_row(cur, did, place):
    cur.execute("""SELECT value_num, reported_at, attrs FROM observation
                    WHERE dataset_id = %s AND place_id = %s
                      AND indicator = 'gaza.moh.deaths.daily'""", (did, place))
    return cur.fetchone()


def test_a_revised_bulletin_supersedes_and_keeps_the_first_figure(db):
    """F182. DO UPDATE SET value_num=..., reported_at=now(): a same-day
    correction erased the first figure without trace, attrs.claim_id kept
    naming the first bulletin, and every hourly re-read reset reported_at to
    the run time for the whole series."""
    first = datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc)
    later = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
    v7 = _TITLE + _DAILY
    v9 = v7.replace("7 شهداء", "9 شهداء")
    with db.cursor() as cur:
        did, place = _moh_setup(cur)

        def run():
            st = {"reports": 0, "rows": 0, "written": 0}
            moh_ingest.write_report(cur, did, place, 101, v7, first, st)
            moh_ingest.write_report(cur, did, place, 102, v9, later, st)
            return st

        assert run()["written"] == 2               # inserted, then superseded
        value, reported, attrs = _moh_row(cur, did, place)
        assert value == 9 and reported == later and attrs["claim_id"] == 102
        (old,) = attrs["superseded"]
        assert old["value_num"] == 7 and old["claim_id"] == 101
        assert datetime.fromisoformat(old["reported_at"]) == first

        # The hourly re-read of both bulletins changes nothing at all.
        assert run()["written"] == 0
        assert _moh_row(cur, did, place) == (value, reported, attrs)


def test_an_earlier_bulletin_read_again_cannot_undo_a_later_one(db):
    with db.cursor() as cur:
        did, place = _moh_setup(cur)
        st = {"reports": 0, "rows": 0, "written": 0}
        later = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
        moh_ingest.write_report(cur, did, place, 102,
                                (_TITLE + _DAILY).replace("7 شهداء", "9 شهداء"), later, st)
        moh_ingest.write_report(cur, did, place, 101, _TITLE + _DAILY,
                                later - timedelta(hours=8), st)
        value, reported, attrs = _moh_row(cur, did, place)
        assert (value, reported, attrs["claim_id"]) == (9, later, 102)
        assert "superseded" not in attrs
