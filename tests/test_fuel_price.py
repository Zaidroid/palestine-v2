"""cascade/fuel_price.py — the official West Bank fuel price list, read from news.

Every case below is a real document from the corpus frozen at
tests/fixtures/fuel_price/corpus.json (articles as fetched 2026-09-23, and
the archived Telegram claims). The refusals matter as much as the readings:
each one is a document that WOULD have produced a wrong price.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from cascade import fuel_price as fp

CORPUS = json.loads((Path(__file__).parent / "fixtures/fuel_price/corpus.json")
                    .read_text(encoding="utf-8"))


def _read(key: str) -> fp.Announcement:
    doc = next(v for k, v in CORPUS.items() if key in k)
    pub = date.fromisoformat(doc["published"]) if doc["published"] else None
    return fp.parse(doc["text"], pub)


SEPT_1 = {"gasoline_95": 8.15, "gasoline_98": 9.21, "diesel": 8.39, "kerosene": 8.39,
          "lpg_2_5kg": 18.0, "lpg_5kg": 36.0, "lpg_12kg": 85.0, "lpg_48kg": 340.0}


def test_the_full_september_list_reads_completely():
    a = _read("shehabnews.com/post/163237")
    assert a.verdict == "prices"
    assert a.prices == SEPT_1
    assert a.effective_from == date(2026, 9, 1) and a.effective_basis == "explicit"


def test_the_mid_month_cut_is_dated_to_the_7th_not_the_1st():
    """fuel_price@1 dated this to 2026-09-01, beside the real 8.15 for that day."""
    a = _read("masarnews.co")
    assert a.verdict == "prices"
    assert a.prices["gasoline_95"] == 7.65
    assert a.effective_from == date(2026, 9, 7)


def test_a_cylinder_size_carried_from_an_earlier_clause_is_marked_inferred():
    """"أسطوانة 2.5 كغم 18 شيكلاً، و5 كغم 36" — only the first names a cylinder."""
    a = _read("maannews.net")
    assert a.prices["lpg_5kg"] == 36.0 and a.prices["lpg_48kg"] == 340.0
    assert a.evidence["lpg_5kg"]["inferred"] is True
    assert a.evidence["gasoline_95"]["inferred"] is False


def test_an_unattributed_official_repost_is_read_only_as_a_full_list():
    """"رسميا.. ارتفاع جديد على أسعار المحروقات لشهر أيلول" never names the
    Corporation. Accepted as `implied` because it is the full-list shape."""
    a = _read("claim:73202")
    assert a.verdict == "prices" and a.prices == SEPT_1
    assert any("implied" in d for d in a.detail)


@pytest.mark.parametrize("key,why", [
    ("claim:75620", "Israeli price story: names 'وزارة المالية' — Israel's"),
    ("claim:68326", "rumour denial quoting the rumoured 9.56"),
    ("claim:68101", "one unattributed number, and it was wrong (8.25)"),
    ("claim:363", "one Israeli station's price during a shortage"),
    ("claim:84084", "a delta ('بقيمة نصف شيكل'), not a price"),
])
def test_documents_that_would_have_produced_a_wrong_price_are_refused(key, why):
    assert _read(key).verdict != "prices", why


def test_the_old_price_in_a_revision_story_is_not_read():
    """"ليصبح 7.65 بدلاً من 8.15" — 8.15 is the old price."""
    a = fp.parse("أعلنت الهيئة العامة للبترول لشهر أيلول، اعتبارا من 7 أيلول 2026، "
                 "سعر لتر بنزين 95 ليصبح 7.65 شيكل بدلاً من 8.15 شيكل.", date(2026, 9, 6))
    assert a.prices == {"gasoline_95": 7.65}


def test_a_mid_month_list_with_no_start_date_is_not_dated_to_the_1st():
    a = fp.parse("الهيئة العامة للبترول: أسعار المحروقات لشهر أيلول. بنزين 95 بـ 7.65 شيكل.",
                 date(2026, 9, 6))
    assert a.verdict == "no_effective_date"


def test_a_number_outside_any_real_price_is_refused():
    a = fp.parse("الهيئة العامة للبترول، اعتبارا من 1 أيلول 2026: بنزين 95 بـ 2026 شيكل.",
                 date(2026, 8, 31))
    assert a.verdict == "no_prices"


def test_eastern_arabic_digits_read_as_western():
    a = fp.parse("الهيئة العامة للبترول، اعتبارا من ١ أيلول ٢٠٢٦: السولار ٨٫٣٩ شيكل.",
                 date(2026, 8, 31))
    assert a.prices == {"diesel": 8.39} and a.effective_from == date(2026, 9, 1)


def test_every_frozen_reading_is_within_bounds():
    for key, doc in CORPUS.items():
        pub = date.fromisoformat(doc["published"]) if doc["published"] else None
        for product, value in fp.parse(doc["text"], pub).prices.items():
            lo, hi = fp.BOUNDS[product]
            assert lo <= value <= hi, (key, product, value)


def test_a_price_table_is_read_only_when_the_table_names_its_unit():
    """al-ayyam publishes the list as a table headed "السعر/ شيكل". A table
    row becomes "product: price شيكل" only because the header states the unit."""
    from ingest.sources.fuel_prices import article_text
    page = (Path(__file__).parent / "fixtures/fuel_price/al-ayyam-2026-08-01.html").read_text(encoding="utf-8")
    a = fp.parse(article_text(page), date(2026, 8, 1))
    assert a.verdict == "prices"
    assert a.prices == {"gasoline_95": 7.99, "gasoline_98": 9.05, "diesel": 8.56, "kerosene": 8.56,
                        "lpg_5kg": 36.0, "lpg_12kg": 85.0, "lpg_48kg": 340.0}
    unitless = page.replace("السعر/ شيكل", "السعر")
    assert fp.parse(article_text(unitless), date(2026, 8, 1)).verdict != "prices"
