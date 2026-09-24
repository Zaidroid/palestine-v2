"""P0-C.1b — the place reader offers every name the text carries.

Measured 2026-09-24: of 1,260 governorate-only incidents, 881 carried a name
the single-pass reader never looked at (a village before "جنوب نابلس", a
dual "بلدتي X وY", a site word "منطقة X", a toponym prefix "بيت X"). These
tests pin the readers; the gazetteer's verdict on each candidate is tested
against the database in test_place_locate.py.
"""
import pytest

from cascade.news import _extract_place, _extract_places, read


def names(text):
    return [n for n, _how in _extract_places(text)[0]]


def hows(text):
    return dict(_extract_places(text)[0])


# ── the readers ───────────────────────────────────────────────────────────────
def test_every_settlement_word_is_read_not_just_the_first():
    cands, gov = _extract_places("قوات الاحتلال تقتحم بلدتي فحمة وكفر راعي قضاء جنين")
    assert [n for n, _ in cands][:2] == ["فحمه", "كفر راعي"]
    assert gov == "جنين"


def test_dual_form_names_two_places():
    h = hows("مستوطنون يشعلون النيران بين بلدتي جالود وقصرة جنوب نابلس")
    assert h["جالود"] == "dual"
    assert h["قصره"] == "conjunct"


def test_a_short_conjunct_still_splits():
    """"وأبو" is four letters; it is a conjunction all the same."""
    assert names("الطريق الواصل بين قريتي المغير وأبو فلاح شرق رام الله")[:2] == ["المغير", "ابو فلاح"]


def test_village_before_a_bearing_and_a_governorate():
    assert hows("الاحتلال يهدم منشأة زراعية في يرزا شرق طوباس")["يرزا"] == "bearing"
    assert "قصره" in names("قصرة جنوب نابلس تحت الإغلاق والحصار")


def test_bearing_reads_a_two_word_governorate():
    assert "ابو نجيم" in names("اصابة ناشطة خلال محاولة الوصول للخيمة الاستيطانية في ابو نجيم جنوب بيت لحم")
    assert "المسعوديه" in names("تعيش عائلات المسعودية شمال غربي نابلس في ظلام دامس")


def test_site_words_read_the_name_after_them():
    assert hows("قوات الاحتلال تقتحم منزلا بمنطقة الديرات بمسافر يطا جنوب الخليل")["الديرات"] == "cue"
    assert hows("مداهمة منزله في حي الطيرة برام الله")["الطيره"] == "cue"
    assert hows("تجريف أشجار الزيتون في سهل عرابة جنوب جنين")["عرابه"] == "cue"


def test_toponym_prefix_is_a_name_on_its_own():
    assert hows("الاحتلال يعتقل شابا في بيت أمر ويداهم منازل في تفوح")["بيت امر"] == "prefix"
    assert "خربه الفخيت" in names("الاحتلال يهدم مساكن في خربة الفخيت بمسافر يطا")


def test_between_without_a_settlement_word():
    got = names("قوات الاحتلال تبدأ بعمليات التجريف في الأراضي بين مركة وقباطية جنوب جنين")
    assert {"مركه", "قباطيه"} <= set(got[:2])


# ── what must NOT be read ─────────────────────────────────────────────────────
def test_a_region_word_ends_the_name():
    """"خلة الحمص بمسافر يطا" is the hamlet, and "مسافر يطا" on its own must
    not collapse to the town of Yatta."""
    assert names("مستوطنون يعتدون على خلة الحمص بمسافر يطا جنوب الخليل")[0] == "الحمص"
    assert "يطا" not in names("قوات الاحتلال تعتدي على شاب خلال عمليات هدم مساكنهم في مسافر يطا جنوب الخليل")


def test_a_governorate_name_is_not_a_prefix_or_bearing_candidate():
    """"برية زعترة جنوب بيت لحم": the desert east of the city, not the city."""
    assert "بيت لحم" not in names("عشرات المستوطنين اقتحموا برية زعترة جنوب بيت لحم وتمركزوا في واد المعلق")
    assert "رام الله" not in names("قوات الاحتلال تغلق بوابة طريق المهلل المؤدية لقرى غربي رام الله")


def test_a_city_named_with_a_settlement_word_is_still_a_candidate():
    assert names("اقتحام قوات الاحتلال لمدينة سلفيت") == ["سلفيت"]
    assert _extract_place("اقتحام قوات الاحتلال لمدينة سلفيت") == ("سلفيت", "سلفيت")


def test_a_street_named_after_a_city_is_not_the_city():
    assert "نابلس" not in names("محاصرة منزله قرب مسجد الفردوس بمنطقة شارع نابلس في طولكرم")


def test_live_fire_is_not_a_neighbourhood():
    assert names("إطلاق رصاص حي صوب الشبان في بيت امر") == ["بيت امر"]


def test_residence_is_not_site_for_the_prefix_reader_either():
    """"شابا من بيت أمر ويداهم منازل في تفوح": the arrest is in Tuffah."""
    assert "بيت امر" not in names("الاحتلال يعتقل شابا من بيت أمر ويداهم منازل في تفوح")


def test_administrative_words_end_a_name():
    assert "ترمسعيا" in names("قوات الاحتلال تغلق الطريق بين قريتي أبو فلاح وترمسعيا قضاء رام الله")
    assert not any("قضاء" in n for n in names("قوات الاحتلال تغلق الطريق بين قريتي أبو فلاح وترمسعيا قضاء رام الله"))


def test_reading_carries_every_candidate():
    r = read("مستوطنون يشعلون النيران بين بلدتي جالود وقصرة جنوب نابلس")
    assert r.verdict == "incident"
    assert r.place_text == "جالود"
    assert [n for n, _ in r.place_candidates][:2] == ["جالود", "قصره"]
