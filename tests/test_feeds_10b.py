"""Audit 2026-09-25, area 10 — FEEDS-01..07."""
from __future__ import annotations

import inspect
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade import fuel_price as fp, moh_gaza as mg                       # noqa: E402
from ingest.sources import connectivity, fuel_prices, moh_gaza, power, weather   # noqa: E402


def test_feeds_01_one_publisher_is_one_witness_whatever_the_transport():
    assert fuel_prices.publisher_unit("rss_palinfo", "src:9") == "web:palinfo.com"
    assert fuel_prices.publisher_unit("rss_qudsn", "src:8") == "web:qudsn.co"
    assert fuel_prices.publisher_unit("tg_jeninnews1", "src:31") == "src:31"
    assert "publisher_unit(key, unit)" in inspect.getsource(fuel_prices.claim_rows)


def test_feeds_02_an_announced_cut_ends_at_its_window_end():
    src = inspect.getsource(power.load)
    assert "'normal'" in src and "window[1] < now" in src and '"ended": True' in src


def test_feeds_03_04_private_rebuilds_read_assertions_only():
    for mod, fn in ((power, power.load), (weather, weather.load), (connectivity, connectivity.load)):
        src = inspect.getsource(fn)
        i = src.index("INSERT INTO state_current")
        assert "modality = 'assertion'" in src[i:], mod.__name__


def test_feeds_05_a_comma_decimal_is_one_price():
    assert fp._clauses(fp.normalise("البنزين 8,15 شيكل، والسولار 7,20")) == \
        ["البنزين 8.15 شيكل", " والسولار 7.20"]
    ann = fp.parse("أعلنت الهيئة العامة للبترول أسعار المحروقات لشهر أكتوبر: "
                   "بنزين 95: 8,15 شيكل، سولار: 7,20 شيكل، كاز: 6,10 شيكل.", date(2026, 10, 1))
    if ann.verdict == "prices":
        assert ann.prices.get("gasoline_95") == 8.15 and ann.prices.get("diesel") == 7.2


REPORT = """🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى
🔴 الحصيلة التراكمية منذ بداية العدوان:
إجمالي الشهداء: 73,928 شهيدًا
إجمالي الإصابات: 175,030 إصابة
🔴 حصيلة القسم الجديد غير المعروف:
إجمالي الشهداء: 72,274 شهيدًا
🔴 منذ وقف إطلاق النار (11 أكتوبر 2025 حتى اليوم):
إجمالي الشهداء: 1,408 شهداء
"""


def test_feeds_06_an_unknown_section_never_files_under_the_previous_tier():
    r = mg.parse(REPORT)
    assert r.tiers["cumulative"]["deaths"] == 73928
    assert r.tiers["since_ceasefire"]["deaths"] == 1408
    assert 72274 not in {v for t in r.tiers.values() for v in t.values()}
    assert any("غير المعروف" in x for x in r.rejected)
    assert "since_resumption" in dict(mg.SECTIONS)


def test_feeds_07_moh_rows_are_read_once_and_revisions_supersede():
    assert "cl.claim_id > %s" in inspect.getsource(moh_gaza.load)
    fn = inspect.getsource(moh_gaza._upsert_day)
    assert "tstzrange(lower(sys_period), now())" in fn          # a revision closes the old row
    assert "reported_at, reported_at" in fn and "DO UPDATE" not in fn   # the claim's time, never now()
