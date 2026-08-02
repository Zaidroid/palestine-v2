"""P6 — Palhub's road bulletin parser.

    ./.venv/bin/python -m pytest tests/test_palhub_roads.py -q

This source is machine-generated, so the parser is STRICT: anything that does
not match the grammar is rejected rather than approximated. A lenient parser
here would turn a 100%-legible source into a second probabilistic one, and we
already have one of those measuring 0.823.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cascade.palhub_roads import is_bulletin, parse, parse_stamp   # noqa: E402

REAL = """🚧 أحوال الطرق والحواجز  نابلس
آخر تحديث: ٠٢‏/٠٨، ١١:١٣ ص

- الـ 17 - عصيرة: دخول 🟡 أزمة متوسطة | خروج 🟡 أزمة متوسطة
- الجلمة: دخول 🔴 مغلق | خروج 🟢 مفتوح
- بيت فوريك: دخول 🟠 أزمة خانقة | خروج 🟢 مفتوح

🔗 التفاصيل والتحديث اللحظي: https://palhub.app/road-status"""


def test_a_real_bulletin_parses_completely():
    b = parse(REAL)
    assert b.area == "نابلس"
    assert b.updated_local == "11:13"
    assert len(b.readings) == 6          # three checkpoints x two directions
    assert b.rejected == []


def test_direction_is_carried_per_side_not_collapsed():
    """Palhub states دخول and خروج separately and they genuinely differ. Taking
    one for both would publish a closed direction as open half the time."""
    b = parse(REAL)
    jalama = [r for r in b.readings if r.name == "الجلمة"]
    assert {r.direction: r.value for r in jalama} == {"inbound": "closed",
                                                      "outbound": "open"}


# ── the mapping decision, asserted so it cannot drift ────────────────────────

def test_both_azma_levels_map_to_congested():
    """Our `congested` already means ازمه/ازدحام/اختناق; `slow` means بطيء —
    moving slowly, a different claim. Mapping the milder azma to `slow` because
    it is milder would make palhub systematically CONTRADICT road channels
    describing the same reality, and corroboration would read agreement as
    conflict."""
    b = parse(REAL)
    by = {(r.name, r.direction): r for r in b.readings}
    mid = by[("الـ 17 - عصيرة", "inbound")]
    severe = by[("بيت فوريك", "inbound")]
    assert mid.value == "congested" and severe.value == "congested"
    # The gradation is not thrown away, it is just not on the belief axis.
    assert severe.severity > mid.severity
    assert mid.raw_status == "أزمة متوسطة"


def test_the_original_arabic_is_retained():
    for r in parse(REAL).readings:
        assert r.raw_status, "the source's own words must survive the mapping"


# ── invisible characters, the trap this hit ──────────────────────────────────

def test_the_timestamp_survives_an_embedded_right_to_left_mark():
    """U+200F sits between the day and the slash so mixed-direction text renders
    correctly. It is not whitespace, so `\\s*` does not match it — the stamp
    failed to parse on all 400 sampled messages while looking perfectly normal
    in every terminal and diff."""
    assert "‏" in "٠٢‏/٠٨، ١١:١٣ ص"
    assert parse_stamp("٠٢‏/٠٨، ١١:١٣ ص") == "11:13"


def test_arabic_indic_digits_and_the_meridiem():
    assert parse_stamp("٠٢/٠٨، ١١:١٣ ص") == "11:13"     # ص = AM
    assert parse_stamp("٠٢/٠٨، ٠١:٠٥ م") == "13:05"     # م = PM
    assert parse_stamp("٠٢/٠٨، ١٢:٣٠ ص") == "00:30"     # midnight, not noon
    assert parse_stamp("٠٢/٠٨، ١٢:٣٠ م") == "12:30"


# ── strictness ───────────────────────────────────────────────────────────────

def test_a_malformed_line_is_rejected_not_guessed():
    """Two real lines in 6,060 are malformed at source ("- ازدحام: زيف"). They
    are dropped and counted, because inventing a reading from a broken line is
    how an exact source becomes an approximate one."""
    b = parse(REAL + "\n- ازدحام: زيف")
    assert len(b.rejected) == 1
    assert len(b.readings) == 6


def test_an_emoji_disagreeing_with_its_words_is_rejected():
    """If Palhub ever changes one without the other, that is a format change and
    must surface, not be silently resolved in whichever direction we preferred."""
    b = parse("""🚧 أحوال الطرق والحواجز  نابلس
- كذا: دخول 🟢 مغلق | خروج 🟢 مفتوح""")
    assert len(b.rejected) == 1 and b.readings == []


def test_an_unknown_status_word_is_rejected():
    b = parse("""🚧 أحوال الطرق والحواجز  نابلس
- كذا: دخول 🟢 حالة جديدة | خروج 🟢 مفتوح""")
    assert len(b.rejected) == 1


def test_a_non_bulletin_yields_nothing_rather_than_partial_junk():
    for junk in ("", "🔗 التفاصيل والتحديث اللحظي", "مرحبا"):
        b = parse(junk)
        assert b.readings == [] and b.area is None
        assert not is_bulletin(junk)


def test_is_bulletin_recognises_the_real_thing():
    assert is_bulletin(REAL)
