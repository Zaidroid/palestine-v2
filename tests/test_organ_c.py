"""Organ C — the Gaza MoH daily bulletin, and the properties that must hold.

    ./.venv/bin/python -m pytest tests/test_organ_c.py -q

Four subjects, and every one of them is a way this reader was WRONG before it
was right — the numbers in the docstrings are the ones the coverage pass
measured, not illustrations:

  the reader      both label orders, a window that is not always 24 hours, a
                  dot as a thousands separator, a small number spelled out, a
                  value on the line below its label, a header whose own digits
                  must not be read as a toll, and a date taken from the trailer
  the validators  the four refusals F-10 names, each in words a human can act on
  the anchor      the row the databank froze at reads 73,384 killed / 174,242
                  injured, the same two numbers a different pipeline last served
                  on 2026-08-08 — agreement between two independent readers
  the gold set    every row revalidates to the verdict it was filed with, and
                  its provenance is the declared `read` or `arithmetic`

The fixtures are real bulletin texts, shortened only where a section is not
about the property under test.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import organ_c  # noqa: E402

GOLD = ROOT / "tests" / "gold" / "moh_c.jsonl"

# 2026-09-22 — the newest bulletin in the archive, the day the series resumes.
NEWEST = """
🇵🇸 وزارة الصحة الفلسطينية – غزة 🇵🇸
🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة
⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية:
- 5 شهداء (4 شهداء جدد، 1 شهيد متأثر بإصابته).
- 25 إصابة
🔴*منذ وقف إطلاق النار (11 أكتوبر 2025 حتى اليوم):*
- إجمالي الشهداء: 1,399 شهيد
- إجمالي الإصابات: 4,863 إصابة
- إجمالي حالات الانتشال: 834 شهيد
🔴*الحصيلة التراكمية منذ بداية العدوان:*
- إجمالي الشهداء: 73,919 شهيد
- إجمالي الإصابات: 174,977 إصابة
وزارة الصحة
22 سبتمبر 2026
"""

# 2026-01-01 — `شهيد واحد` is one death and `و 1 إصابة` is one injury.
SPELLED_ONE = """
⭕ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ24 ساعة الماضية:
• 2 شهداء (منهم شهيد واحد جديد و 1 شهيد انتشال) و 1 إصابة.
🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 416
• إجمالي عدد الإصابات: 1,153
• إجمالي حالات الانتشال: 683
🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 71,271
• العدد التراكمي للإصابات: 171,233
وزارة الصحة
01 يناير 2026
"""

# 2026-03-04 — a bare `شهيد` with no digit before it is one death.
BARE_ONE = """
⭕ إجمالي ما وصل إلى مستشفيات قطاع غزة , خلال الـ 24 ساعة الماضية : شهيد, و 3 إصابات.
🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 633
• إجمالي عدد الإصابات: 1,703
• إجمالي حالات الانتشال: 753
🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 72,117
• العدد التراكمي للإصابات: 171,801
وزارة الصحة
4 مارس 2026
"""

# 2026-04-05 — `72.292`: a dot as the thousands separator, not a decimal point.
DOT_SEPARATOR = """
⭕ بلغ إجمالي من وصلوا إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية 4 شهداء (1 شهيد جديد,3شهيد انتشال) و 5 إصابات.
🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 716
• إجمالي عدد الإصابات: 1,968
• إجمالي حالات الانتشال: 759
🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 72.292
• العدد التراكمي للإصابات: 172,073
وزارة الصحة
5 ابريل 2026
"""

# 2026-02-14 — a 48-hour window, which is why window_hours is read at all.
WINDOW_48 = """
⭕ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 48 ساعة الماضية : 2 شهداء انتشال, و 15 إصابات.
🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 591
• إجمالي عدد الإصابات: 1,598
• إجمالي حالات الانتشال: 726
🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 72,051
• العدد التراكمي للإصابات: 171,706
وزارة الصحة
14 فبراير 2026
"""

# 2026-03-23 — a holiday window with no hours in it at all.
HOLIDAY_WINDOW = """
⭕ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال ايام عيد الفطر وحتى الساعة:
9 شهداء(منهم 1شهيد متأثر بإصابته) و 30 إصابة.
🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 687
• إجمالي عدد الإصابات: 1,845
• إجمالي حالات الانتشال: 756
🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 72,263
• العدد التراكمي للإصابات: 171,944
وزارة الصحة
23 مارس 2026
"""

# 2026-07-26 — the cumulative injured value sits on the line BELOW its label.
VALUE_ON_NEXT_LINE = """
⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية.
* عدد الشهداء 9 جديد
• عدد الإصابات: 36 إصابات.
🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 1,200
• إجمالي عدد الإصابات: 3,888
• إجمالي حالات الانتشال: 803
🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 73,326
• العدد التراكمي للإصابات:
173,997
وزارة الصحة
26 يوليو 2026
"""

# 2026-01-15 — `شهيدان` written as a word while the header says 24 hours, so the
# toll must be 2 and never the header's own 24.
DUAL_AND_HEADER = """
⭕ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ24 ساعة الماضية: شهيدان, و5 إصابات.
🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 451
• إجمالي عدد الإصابات: 1,251
• إجمالي حالات الانتشال: 710
🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 71,441
• العدد التراكمي للإصابات: 171,329
وزارة الصحة
15 يناير 2026
"""

# 2026-05-07 — the trailer has no space in it: `7مايو 2026`.
TRAILER_NO_SPACE = """
⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة , خلال الـ  24 ساعة الماضية.
عدد الشهداء: 9 شهداء (6 شهداء جديد, 3 شهداء متأثرين بجراحهم)
عدد الإصابات:  39 إصابة
🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 846
• إجمالي عدد الإصابات: 2,418
• إجمالي حالات الانتشال: 769
🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 72,628
• العدد التراكمي للإصابات: 172,520
وزارة الصحة
7مايو 2026
"""

REF = datetime(2026, 9, 23, 6, 0)


def test_the_newest_bulletin_reads_the_series_the_databank_lost():
    r = organ_c.read(NEWEST, datetime(2026, 9, 22, 8, 39))
    assert r["as_of_date"] == "2026-09-22"
    assert (r["cum_killed"], r["cum_injured"]) == (73919, 174977)
    assert (r["last_24h_killed"], r["last_24h_injured"]) == (5, 25)
    assert (r["since_ceasefire_killed"], r["since_ceasefire_injured"]) == (1399, 4863)
    assert r["recovered"] == 834


def test_a_window_that_is_not_24_hours_is_read_as_48():
    r = organ_c.read(WINDOW_48, datetime(2026, 2, 14, 9, 15))
    assert r["window_hours"] == 48
    assert (r["last_24h_killed"], r["last_24h_injured"]) == (2, 15)
    # The delta rule does not apply to a 48-hour window: it overlaps the previous
    # bulletin's window, so a rise smaller than its count is not a fault.
    prev = {"cum_killed": 72049, "cum_injured": 171700}
    assert organ_c.validate(r, previous=prev).ok


def test_a_holiday_window_with_no_hours_is_still_read():
    r = organ_c.read(HOLIDAY_WINDOW, datetime(2026, 3, 23, 11, 25))
    assert r["window_hours"] is None
    assert (r["last_24h_killed"], r["last_24h_injured"]) == (9, 30)


def test_a_dot_between_digit_groups_is_a_thousands_separator():
    r = organ_c.read(DOT_SEPARATOR, datetime(2026, 4, 5, 8, 24))
    assert r["cum_killed"] == 72292, "72.292 is seventy-two thousand, not seventy-two"
    assert r["cum_injured"] == 172073


def test_small_numbers_are_sometimes_spelled_out():
    one = organ_c.read(SPELLED_ONE, datetime(2026, 1, 1, 12, 1))
    assert (one["last_24h_killed"], one["last_24h_injured"]) == (2, 1)
    bare = organ_c.read(BARE_ONE, datetime(2026, 3, 4, 9, 15))
    assert (bare["last_24h_killed"], bare["last_24h_injured"]) == (1, 3)


def test_the_number_in_the_window_header_is_never_the_toll():
    r = organ_c.read(DUAL_AND_HEADER, datetime(2026, 1, 15, 9, 55))
    assert r["last_24h_killed"] == 2, "`شهيدان` is 2; the header's 24 is an hour count"
    assert r["last_24h_injured"] == 5


def test_a_value_may_sit_on_the_line_below_its_label():
    r = organ_c.read(VALUE_ON_NEXT_LINE, datetime(2026, 7, 26, 8, 39))
    assert r["cum_injured"] == 173997
    assert r["cum_killed"] == 73326


def test_the_date_comes_from_the_trailer_not_from_the_war_or_the_ceasefire_line():
    r = organ_c.read(TRAILER_NO_SPACE, datetime(2026, 5, 7, 9, 0))
    assert r["as_of_date"] == "2026-05-07"


def test_the_validator_refuses_a_corrupted_row():
    """F-10's DONE WHEN, in four shapes."""
    good = organ_c.read(NEWEST, datetime(2026, 9, 22, 8, 39))
    # The real previous bulletin: 2026-09-21 read 73,914 / 174,952 with a 24 h
    # line of 1 killed, and the 22nd moves killed to 73,919 with a line of 5.
    previous = {"cum_killed": 73914, "cum_injured": 174952}
    assert organ_c.validate(good, previous=previous, reported_at=REF.replace(day=22)).ok

    backwards = dict(good, cum_killed=previous["cum_killed"] - 100)
    v = organ_c.validate(backwards, previous=previous)
    assert not v.ok and [r.code for r in v.reasons] == ["not-monotonic"]
    assert "fell" in v.reasons[0].detail

    too_many = dict(good, cum_killed=previous["cum_killed"] + 1, last_24h_killed=9)
    v = organ_c.validate(too_many, previous=previous)
    assert not v.ok and "delta-inconsistent" in [r.code for r in v.reasons]

    misdated = dict(good, as_of_date="2026-07-22")
    v = organ_c.validate(misdated, previous=previous, reported_at=REF.replace(day=22))
    assert not v.ok and [r.code for r in v.reasons] == ["date-drift"]

    missing = {k: v for k, v in good.items() if k != "cum_injured"}
    v = organ_c.validate(missing, previous=previous)
    assert not v.ok and [r.code for r in v.reasons] == ["schema"]


def test_the_row_the_databank_froze_at_carries_the_same_numbers():
    """Agreement between two independent readers, twelve months apart.

    The databank's last served value for the Gaza series was 73,384 killed /
    174,242 injured on 2026-08-08 — written by the v1 pipeline that has since
    gone quiet. This reader, built from the archived texts and nothing else,
    reads the same two numbers out of that day's bulletin.
    """
    rows = {r["claim_id"]: r for r in (json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines())}
    row = rows[34668]
    assert row["reader"]["as_of_date"] == "2026-08-08"
    assert (row["reader"]["cum_killed"], row["reader"]["cum_injured"]) == (73384, 174242)


def test_every_gold_row_revalidates_to_the_verdict_it_was_filed_with():
    lines = GOLD.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 201, "the 2026 window, one row per bulletin"
    for line in lines:
        row = json.loads(line)
        reported_at = datetime.fromisoformat(row["reported_at"])
        verdict = organ_c.validate(row["reader"], previous=row["previous"], reported_at=reported_at)
        assert verdict.ok == row["verdict"]["ok"], f"{row['claim_id']} verdict drifted"
        assert [r.code for r in verdict.reasons] == [r["code"] for r in row["verdict"]["reasons"]], \
            f"{row['claim_id']} reasons drifted"


def test_gold_provenance_is_declared_and_honest():
    rows = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines()]
    methods = {r["label_method"] for r in rows}
    assert methods <= {"read", "arithmetic"}, methods
    read = [r for r in rows if r["label_method"] == "read"]
    assert len(read) == 20, "the sample read by hand is 20 rows, and the file says so"
    # A `read` row must be one that was actually read: the ids are pinned in the
    # builder, so a change there without a re-read fails here.
    from analyst.gold_moh import READ_VERIFIED
    assert {r["claim_id"] for r in read} == READ_VERIFIED


def test_the_reader_reports_absence_rather_than_guessing():
    """A bulletin with no cumulative block gives None, and the validator says so."""
    empty = """
⭕ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية: 3 شهداء, و 4 إصابات.
وزارة الصحة
4 سبتمبر 2026
"""
    r = organ_c.read(empty, datetime(2026, 9, 4, 9, 0))
    assert r["cum_killed"] is None and r["cum_injured"] is None
    v = organ_c.validate(r)
    assert not v.ok and {x.code for x in v.reasons} == {"schema"}
