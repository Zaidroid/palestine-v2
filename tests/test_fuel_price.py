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


# ── 2026-09-25 audit: fuel_price@5 ───────────────────────────────────────────

@pytest.mark.parametrize("comma", [",", "،"])
def test_a_decimal_comma_is_a_decimal_point(comma):
    """F174. The comma was a clause boundary before it was a decimal, so
    "8,15 شيكلا والسولار 8,39" left the clause "15 شيكلا والسولار 8" and
    diesel was recorded as a STATED 15.0 — inside its bounds."""
    a = fp.parse("أعلنت الهيئة العامة للبترول ... اعتبارا من 1 أيلول 2026: البنزين 95 "
                 f"بسعر 8{comma}15 شيكلا والسولار 8{comma}39 شيكلا.", date(2026, 8, 31))
    assert a.verdict == "prices"
    assert a.prices == {"gasoline_95": 8.15, "diesel": 8.39}


def test_a_thousands_comma_and_a_list_of_prices_are_not_decimals():
    assert fp.normalise("1,230 شيكل") == "1,230 شيكل"
    assert fp.normalise("8.15،9.21") == "8.15،9.21"
    assert fp.normalise("أسطوانة 2,5 كغم") == "أسطوانة 2.5 كغم"


def test_a_list_announced_for_the_midnight_between_two_days_governs_the_second():
    """F173. "منتصف ليلة 31 آب/1 أيلول" took the first day-month, so the list
    was dated 31 Aug — and an October list worded the same way on 30 Sep
    would be filed under September, leaving October `awaiting_list`."""
    a = fp.parse("أعلنت الهيئة العامة للبترول … اعتبارا من منتصف ليلة 31 آب/1 أيلول 2026: "
                 "بنزين 95: 8.15 شيكل.", date(2026, 8, 31))
    assert a.effective_from == date(2026, 9, 1)
    oct_ = fp.parse("أعلنت الهيئة العامة للبترول اعتبارا من منتصف ليلة 30 أيلول/1 تشرين الأول "
                    "2026: بنزين 95: 8.15 شيكل.", date(2026, 9, 30))
    assert oct_.effective_from == date(2026, 10, 1) and oct_.period_month == date(2026, 10, 1)


def test_a_date_range_keeps_its_start():
    """Only CONSECUTIVE days are a midnight boundary; a range is not one."""
    a = fp.parse("أعلنت الهيئة العامة للبترول اعتبارا من 1 أيلول - 30 أيلول 2026: "
                 "بنزين 95: 8.15 شيكل.", date(2026, 8, 31))
    assert a.effective_from == date(2026, 9, 1)


@pytest.mark.parametrize("text", [
    # "كان " matched inside مكان
    "أعلنت الهيئة العامة للبترول اعتبارا من 1 أيلول 2026: سعر لتر بنزين 95 في مكان البيع 8.15 شيكل",
    # a rise stated in agorot: the delta is stripped, the new price stands
    "أعلنت الهيئة العامة للبترول اعتبارا من 1 أيلول 2026: رفع سعر لتر بنزين 95 بمقدار 20 أغورة ليصبح 8.15 شيكل",
])
def test_a_word_inside_another_word_does_not_throw_the_list_away(text):
    """F175. The sentence filter matched short substrings anywhere."""
    a = fp.parse(text, date(2026, 8, 31))
    assert a.verdict == "prices" and a.prices == {"gasoline_95": 8.15}


def test_the_corporations_israeli_market_explanation_does_not_hide_its_prices():
    """F175. raya.ps's April list states all four litre prices in the sentence
    that explains they follow "سعر الأسواق الإسرائيلية"; it was skipped whole
    and only the cylinder was read."""
    a = _read("raya.ps/news/1214890")
    assert a.verdict == "prices"
    assert a.prices == {"gasoline_95": 7.9, "gasoline_98": 8.86, "diesel": 8.4,
                        "kerosene": 8.4, "lpg_12kg": 95.0}


def test_an_israeli_price_in_a_palestinian_sentence_is_still_refused():
    """The excuse covers only the dependence phrase. A sentence that STATES a
    price in Israel is still not an announcement of the West Bank's."""
    a = fp.parse("أعلنت الهيئة العامة للبترول اعتبارا من 1 أيلول 2026 أسعار المحروقات. "
                 "وفي إسرائيل، بنزين 95 بـ 7.75 شيكل.", date(2026, 8, 31))
    assert "gasoline_95" not in a.prices
    b = fp.parse("أعلنت الهيئة العامة للبترول اعتبارا من 1 أيلول 2026، وكانت أسعار "
                 "الأسواق الإسرائيلية أعلى، بنزين 95 بـ 7.75 شيكل.", date(2026, 8, 31))
    assert "gasoline_95" not in b.prices


def test_kanun_the_month_is_not_kana_the_verb():
    a = fp.parse("أعلنت الهيئة العامة للبترول اعتبارا من 1 كانون الثاني 2027: بنزين 95: 8.15 شيكل.",
                 date(2026, 12, 31))
    assert a.verdict == "prices" and a.effective_from == date(2027, 1, 1)
