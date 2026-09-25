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
    """The refusals that survive the 2026-09-23 ratification ("B as written")."""
    good = organ_c.read(NEWEST, datetime(2026, 9, 22, 8, 39))
    # The real previous bulletin: 2026-09-21 read 73,914 / 174,952 with a 24 h
    # line of 1 killed, and the 22nd moves killed to 73,919 with a line of 5.
    previous = {"cum_killed": 73914, "cum_injured": 174952}
    v = organ_c.validate(good, previous=previous, reported_at=REF.replace(day=22))
    assert v.ok and v.reasons == []

    # a fall far beyond the 0.5 % revision band
    backwards = dict(good, cum_killed=previous["cum_killed"] - 1000)
    v = organ_c.validate(backwards, previous=previous)
    assert not v.ok and [r.code for r in v.reasons] == ["not-monotonic"]
    assert "fell" in v.reasons[0].detail

    # the 7 June shape: an extra digit is a 900 % rise, refused as a typo
    typo = dict(good, cum_injured=previous["cum_injured"] * 10)
    v = organ_c.validate(typo, previous=previous)
    assert not v.ok and [r.code for r in v.reasons] == ["implausible-jump"]

    misdated = dict(good, as_of_date="2026-07-22")
    v = organ_c.validate(misdated, previous=previous, reported_at=REF.replace(day=22))
    assert not v.ok and [r.code for r in v.reasons] == ["date-drift"]

    missing = {k: v for k, v in good.items() if k != "cum_injured"}
    v = organ_c.validate(missing, previous=previous)
    assert not v.ok and [r.code for r in v.reasons] == ["schema"]


def test_a_small_stated_revision_is_served_and_marked():
    """B1 — 28 Jan revised cumulative injured 171,428 -> 171,343 (0.05 %), and
    the series continued from the new number; the old rule refused it."""
    row = {"as_of_date": "2026-01-28", "window_hours": 24,
           "cum_killed": 71667, "cum_injured": 171343,
           "last_24h_killed": 5, "last_24h_injured": 6}
    v = organ_c.validate(row, previous={"cum_killed": 71662, "cum_injured": 171428})
    assert v.ok
    assert [n.code for n in v.notes] == ["revised-down"]
    assert "-85" in v.notes[0].detail


def test_a_window_line_larger_than_the_rise_is_a_note_not_a_refusal():
    """B2 — the window counts hospital arrivals, the cumulative counts registered
    deaths. The divergence is recorded, and the row is served."""
    row = {"as_of_date": "2026-01-04", "window_hours": 24,
           "cum_killed": 71386, "cum_injured": 171264,
           "last_24h_killed": 3, "last_24h_injured": 13}
    v = organ_c.validate(row, previous={"cum_killed": 71384, "cum_injured": 171251})
    assert v.ok
    assert [n.code for n in v.notes] == ["delta-divergence"]


def test_an_omitted_line_is_zero_only_when_the_cumulative_proves_it():
    """B3 — a bulletin that lists injuries only. If cumulative killed did not
    move, the day's deaths are 0 and the row says how it knows. If it did
    move, the missing line is a real gap and the row is refused."""
    base = {"as_of_date": "2026-02-24", "window_hours": 24,
            "cum_killed": 72073, "cum_injured": 171756,
            "last_24h_killed": None, "last_24h_injured": 7}
    proven = organ_c.validate(base, previous={"cum_killed": 72073, "cum_injured": 171749})
    assert proven.ok
    assert proven.settled["last_24h_killed"] == 0
    assert [n.code for n in proven.notes] == ["zero-by-cumulative"]
    assert base["last_24h_killed"] is None, "the reader's output is never rewritten"

    moved = organ_c.validate(base, previous={"cum_killed": 72070, "cum_injured": 171749})
    assert not moved.ok
    assert [r.code for r in moved.reasons] == ["window-missing"]


def test_levantine_month_names_date_the_bulletin():
    """`02 تموز 2026` was dated 2023-10-07 by c/1 — the war's start date."""
    assert organ_c.parse_date("وزارة الصحة\n02 تموز 2026", None).isoformat() == "2026-07-02"
    assert organ_c.parse_date("وزارة الصحة\n1 تشرين الثاني 2025", None).isoformat() == "2025-11-01"
    assert organ_c.parse_date("وزارة الصحة\n9 شباط 2026", None).isoformat() == "2026-02-09"


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
        if row.get("repost_of"):
            continue
        reported_at = datetime.fromisoformat(row["reported_at"])
        verdict = organ_c.validate(row["reader"], previous=row["previous"], reported_at=reported_at)
        assert verdict.ok == row["verdict"]["ok"], f"{row['claim_id']} verdict drifted"
        assert [r.code for r in verdict.reasons] == [r["code"] for r in row["verdict"]["reasons"]], \
            f"{row['claim_id']} reasons drifted"
        assert [n.code for n in verdict.notes] == [n["code"] for n in row["verdict"]["notes"]], \
            f"{row['claim_id']} notes drifted"


def test_the_ratified_rules_serve_198_of_199_days_and_refuse_only_the_typo():
    """The number Zaid ratified against (2026-09-23): 2 same-day reposts are
    one fact each, and of the 199 unique days only 7 June — 1,730,128 injured,
    an extra digit — is refused. If this moves, a rule moved."""
    rows = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines()]
    reposts = [r for r in rows if r.get("repost_of")]
    unique = [r for r in rows if not r.get("repost_of")]
    refused = [r for r in unique if not r["verdict"]["ok"]]
    assert len(reposts) == 2 and len(unique) == 199
    assert [(r["reader"]["as_of_date"], r["verdict"]["reasons"][0]["code"]) for r in refused] \
        == [("2026-06-07", "implausible-jump")]


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


# ── what the scorer's number is (audit F230) ─────────────────────────────────

def test_the_score_says_it_is_agreement_with_the_reader_and_splits_the_human_rows():
    """The gold truth is organ_c.read()'s own output on every row; a human read
    only the `read` rows. 196/199 was quoted as the PARSER's score when it was
    a model agreeing with the parser. The summary must say what it measures and
    keep the human-read slice apart, or the next plan will quote it again."""
    from analyst.score_organ_c import summarise
    right = {f: "correct" for f in ("as_of_date", "cum_killed")} | {"row": "correct"}
    wrong = {"as_of_date": "correct", "cum_killed": "wrong", "row": "not-correct"}
    results = ([{"claim_id": i, "scored": right, "label_method": "arithmetic"} for i in range(8)]
               + [{"claim_id": 100, "scored": right, "label_method": "read"},
                  {"claim_id": 101, "scored": wrong, "label_method": "read"}])
    s = summarise(results)
    assert s["rows_exact"] == 9
    assert s["by_label_method"]["read"] == {"rows_scored": 2, "rows_exact": 1}
    assert s["by_label_method"]["arithmetic"] == {"rows_scored": 8, "rows_exact": 8}
    assert "agreement with the deterministic reader" in s["measures"]


# ── the band is per day, a sentence may end in a number, a note is not a day ─

def test_a_gap_of_eight_days_is_judged_against_eight_days_of_rise():
    """Audit F232. `previous` is the last ACCEPTED reading, so after a refused
    day or a silent week the rise in hand is several days' worth. Against one
    day's 1 % the honest bulletin was refused, `previous` never moved, and the
    series froze. 100 deaths a day for 8 days: 73,119 -> 73,919."""
    good = organ_c.read(NEWEST, datetime(2026, 9, 22, 8, 39))
    previous = {"cum_killed": 73119, "cum_injured": 173177, "as_of_date": "2026-09-14"}
    v = organ_c.validate(good, previous=previous, reported_at=REF.replace(day=22))
    assert v.ok, [r.code for r in v.reasons]

    # The typo the rule exists for is still a typo after a gap.
    typo = dict(good, cum_injured=previous["cum_injured"] * 10)
    v = organ_c.validate(typo, previous=previous)
    assert not v.ok and [r.code for r in v.reasons] == ["implausible-jump"]

    # And with no date on `previous` the ratified one-day rule is unchanged.
    undated = {k: v for k, v in previous.items() if k != "as_of_date"}
    v = organ_c.validate(good, previous=undated)
    assert [r.code for r in v.reasons] == ["implausible-jump", "implausible-jump"]


def test_a_total_that_ends_its_sentence_with_a_full_stop_is_read():
    """Audit F483: `73,919.` read as None — the day refused for a value it
    states."""
    text = (NEWEST.replace("إجمالي الشهداء: 73,919 شهيد", "إجمالي الشهداء: 73,919.")
                  .replace("إجمالي الإصابات: 174,977 إصابة", "إجمالي الإصابات: 174,977."))
    assert "73,919." in text and "174,977." in text
    r = organ_c.read(text, datetime(2026, 9, 22, 8, 39))
    assert (r["cum_killed"], r["cum_injured"]) == (73919, 174977)
    assert organ_c._to_int("73,919.") == 73919
    assert organ_c._to_int("72.292.") == 72292
    assert organ_c._to_int("1.5") is None


def test_a_cumulative_note_never_fills_a_daily_field():
    """Audit F484: a Ministry footnote about the war's total child deaths,
    after the cumulative block, landed in `children` beside the day's toll."""
    text = NEWEST.replace("وزارة الصحة\n22 سبتمبر 2026",
                          "منهم 18,500 من الأطفال\nوزارة الصحة\n22 سبتمبر 2026")
    assert "18,500" in text
    r = organ_c.read(text, datetime(2026, 9, 22, 8, 39))
    assert r["children"] is None
    assert r["cum_killed"] == 73919
