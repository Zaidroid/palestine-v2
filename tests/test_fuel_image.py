"""The fuel card parser, against real OCR output from real cards.

    .venv/bin/python -m pytest tests/test_fuel_image.py -q

Every string below is verbatim tesseract 5.3.4 `-l ara` output from cards
posted on 2026-08-02 — artefacts and all, including the logo glyphs that bleed
onto the title line, the truncation of "بيت لحم" to "ب", and Hebron's dry count
read as 0 against a card that says 30. A test written against tidied-up input
would prove nothing, because the mess IS the input.

Both segmentation modes appear because neither is sufficient alone, and the
pairs here are the evidence for that claim rather than an assertion about it.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade.fuel_image import parse_card  # noqa: E402

REGIONS = ["الخليل", "بيت لحم", "بيتونيا", "طوباس", "دورا", "يطا",
           "أريحا", "نابلس", "جنين"]

# ── Hebron. psm 6 lost the pills entirely; psm 4 lost the region. ────────────
HEBRON_6 = """أي حالة محطات الوقود الخليل
اللا آخر تحديث كردن 5نم
59 0 حطة السلام 2 ازمة متوسطة
0 محطة أخرى بلا وقود متوفر حالياً"""
HEBRON_4 = """أخالة محطات الرقوة الخليل
اقيم
آخر تحديث: 8/:7 ع
بنزين | سولار محطة السلام از سونط
30 محطة أخرى بلا وقود متوفز حانياً"""

# ── Bethlehem. psm 4 truncated the region to "ب" and lost one row's pills. ──
BETHLEHEM_6 = """ليا بر حالة محطات الوقود بيت لحم
لاط آخر تديث على تدم
بنزين | سولار محطة الجزيرة
بنزين ‎١‏ سولار محطة عبادين
9 محطة أخرى بلا وقود متوفر حالياً
نأهأة-اقبة/ممة.طناطاهم"""
BETHLEHEM_4 = """4 حالة محطات الوقود ب
آخر تعديث: #إهء. 8:84 م
د محطة الجزيرة
بنزين ‏ سولار محطة عبادين
9 محطة أخرى بلا وقود متوفر حالياً
طانطاقم"""

# ── Tubas. psm 4 dropped the all-dry sentence AND the region. ───────────────
TUBAS_6 = """ليا بر حالة محطات الوقود طوباس
لالط آخر تديث على 55م
لا توجد محطة متؤفر قيها وقود حالياً في هذه المدينة.
6 محطة أخرى بلا وقود متوفر حالياً"""
TUBAS_4 = """كاله سسطات الرفرة لوك
آخر تعديث: #إهء. 8:84 م
نود حالياً في هذه المدينة.
6 محطة أخرى بلا وقود متوفر حالياً"""

# ── Dura. Four substitutions in the all-dry sentence and it still must read. ─
DURA_6 = """ليا بر حالة محطات الوقود دورا
اللا آخر تحديث كردن 5نم
لااكزجد ضعطة متزفر فيها وقود:خاليآ في هذه للمدينة.
2 محطة أخرى بلا وقود متوفر اليا"""

BEITUNIA_6 = """ررك حالة محطات الوقود بيتونيا
اللا آخر تحديث كردن 5نم
بنزين ‎١‏ سولار محطة عطاري وعليان للمحروقات
2 محطة أخرى بلا وقود متوفر حالياً"""

HEBRON_STATIONS = ["محطة السلام", "محطة الأمل", "محطة الحرية"]
BETH_STATIONS = ["محطة الجزيرة", "محطة عبادين", "محطة النجمة"]


def test_not_a_card_is_refused() -> None:
    for junk in ("", "مرحبا", "🔗 التفاصيل والتحديث اللحظي"):
        assert parse_card(junk).is_card is False


def test_merging_recovers_what_each_pass_alone_loses() -> None:
    """The whole reason two modes run. Hebron proves both halves at once.

    psm 6 sees the crisis badge and the region but NOT the pills.
    psm 4 sees the pills and the true dry count but mangles the region.
    Ship either alone and a station with fuel is reported as having none.
    """
    only6 = parse_card(HEBRON_6, HEBRON_STATIONS, REGIONS)
    only4 = parse_card(HEBRON_4, HEBRON_STATIONS, REGIONS)
    assert only6.stations[0].fuels == {}, "psm 6 is expected to miss the pills"
    assert only4.region_matched is None, "psm 4 is expected to mangle the title"

    both = parse_card([HEBRON_6, HEBRON_4], HEBRON_STATIONS, REGIONS)
    assert both.region_matched == "الخليل"
    assert len(both.stations) == 1, "the same station must not become two"
    st = both.stations[0]
    assert st.name_matched == "محطة السلام"
    assert st.fuels == {"fuel_gasoline": "available", "fuel_diesel": "available"}
    assert st.crisis == "moderate"


def test_ocr_dropped_a_letter_and_the_match_still_lands() -> None:
    """Hebron's psm-6 row reads "حطة السلام" — the mim of محطة is gone.

    Read as free text that is a different station; matched against the region's
    own list it is obvious. This is what name-matching exists for.
    """
    st = parse_card(HEBRON_6, HEBRON_STATIONS, REGIONS).stations[0]
    assert st.name_matched == "محطة السلام"
    assert st.match_score >= 0.70


def test_truncated_region_is_rejected_rather_than_mismatched() -> None:
    """psm 4 read "ب" for بيت لحم. A one-letter region must match NOTHING."""
    c = parse_card(BETHLEHEM_4, BETH_STATIONS, REGIONS)
    assert c.region_matched is None
    # ...and the merge must then take the region from the pass that got it.
    both = parse_card([BETHLEHEM_6, BETHLEHEM_4], BETH_STATIONS, REGIONS)
    assert both.region_matched == "بيت لحم"


def test_two_stations_with_both_fuels() -> None:
    c = parse_card([BETHLEHEM_6, BETHLEHEM_4], BETH_STATIONS, REGIONS)
    assert len(c.stations) == 2
    assert {s.name_matched for s in c.stations} == {"محطة الجزيرة", "محطة عبادين"}
    for s in c.stations:
        assert s.fuels == {"fuel_gasoline": "available",
                           "fuel_diesel": "available"}
    assert c.others_dry == 9
    assert c.region_all_dry is False


def test_the_crisis_badge_is_kept_apart_from_availability() -> None:
    """`أزمة متوسطة` describes the QUEUE. The fuel is still there."""
    st = parse_card([HEBRON_6, HEBRON_4], HEBRON_STATIONS, REGIONS).stations[0]
    assert st.crisis == "moderate"
    assert st.fuels["fuel_diesel"] == "available"


def test_region_wide_negative_is_taken() -> None:
    """The one caution the card supports, and it covers every station."""
    c = parse_card([TUBAS_6, TUBAS_4], ["محطة كذا"], REGIONS)
    assert c.region_all_dry is True
    assert c.stations == []
    assert c.region_matched == "طوباس"


def test_dura_ocr_is_mangled_and_still_reads_as_all_dry() -> None:
    """"لااكزجد ضعطة متزفر فيها وقود:خاليآ" — same meaning, four substitutions.

    A regression here is silent and expensive: the region stops saying "nobody
    has fuel" and simply goes quiet, which reads as no-news instead of no-fuel.
    """
    assert parse_card(DURA_6, [], REGIONS).region_all_dry is True


def test_disagreeing_dry_counts_are_recorded_not_silently_picked() -> None:
    """Hebron: psm 6 read 0, psm 4 read 30, and the card says 30."""
    c = parse_card([HEBRON_6, HEBRON_4], HEBRON_STATIONS, REGIONS)
    assert c.others_dry == 30
    assert any("disagree" in n for n in c.notes)


def test_dry_count_never_becomes_a_station_verdict() -> None:
    """Bethlehem implies 11 stations where we hold 10.

    Named + dry does not reconcile against our own list and never will
    reliably, so subtracting to find the dry ones would put "no diesel" on a
    station that has it. The count is context and nothing else.
    """
    c = parse_card([BETHLEHEM_6, BETHLEHEM_4], BETH_STATIONS, REGIONS)
    assert c.others_dry == 9
    assert c.region_all_dry is False
    assert all(v == "available" for s in c.stations for v in s.fuels.values())


def test_unknown_station_is_reported_not_guessed() -> None:
    c = parse_card(BETHLEHEM_6, ["محطة شيء مختلف تماما"], REGIONS)
    assert c.unmatched
    assert all(s.name_matched is None for s in c.stations)


def test_without_a_candidate_list_nothing_is_matched() -> None:
    """A name not tied to a row in `place` is not evidence about anywhere."""
    c = parse_card(BEITUNIA_6, None, REGIONS)
    assert c.stations and c.stations[0].name_matched is None


def test_long_name_matches() -> None:
    c = parse_card(BEITUNIA_6, ["محطة عطاري وعليان للمحروقات", "محطة ثانية"],
                   REGIONS)
    assert c.stations[0].name_matched == "محطة عطاري وعليان للمحروقات"


def test_contradictory_card_is_discarded_whole() -> None:
    """Both halves cannot be true; picking one would be picking at random."""
    text = """حالة محطات الوقود نابلس
لا توجد محطة متوفر فيها وقود حالياً في هذه المدينة.
بنزين سولار محطة الاتحاد
3 محطة أخرى بلا وقود متوفر حالياً"""
    c = parse_card(text, ["محطة الاتحاد"], REGIONS)
    assert c.stations == []
    assert c.region_all_dry is False
    assert any("CONTRADICTION" in n for n in c.notes)


def test_a_missing_pill_is_silence_not_a_negative() -> None:
    """Diesel only. Gasoline is absent from the card, which is not 'unavailable'.

    The card names stations that HAVE fuel; it never states a station lacks one.
    Recording an absent pill as `unavailable` would manufacture a caution the
    source never made — and would make the union merge unsound, because a pass
    that simply failed to read a pill would start contradicting one that did.
    """
    text = """حالة محطات الوقود اريحا
سولار محطة الواحة
1 محطة أخرى بلا وقود متوفر حالياً"""
    st = parse_card(text, ["محطة الواحة"], REGIONS).stations[0]
    assert st.fuels == {"fuel_diesel": "available"}
    assert "fuel_gasoline" not in st.fuels


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_ocr_passes_runs_both_modes() -> None:
    from cascade.fuel_image import PSM_MODES, ocr_passes
    assert PSM_MODES == (6, 4)
    # A path that does not exist must return nothing rather than raise: one
    # unreadable card must never stop a sweep.
    assert ocr_passes("/nonexistent/card.jpg") == []
