"""The Ministry's daily report has had three shapes since February 2024; until
2026-10-11 the parser read only the third, and the 2024 bulletins (written
"الاحصائي", no hamza) were not even reports to it. One bulletin per era, as
posted, with the figures a reader takes from it."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cascade.moh_gaza import INDICATORS, parse                              # noqa: E402

ERA_A = """🇵🇸وزارة الصحة بغزة||

التقرير الاحصائي اليومي لعدد الشهداء والجرحى جراء العدوان الاسرائيلي المستمر لليوم ال 131 على قطاع غزة

▪️ الاحتلال الاسرائيلي يرتكب 11 مجزرة ضد العائلات في قطاع غزة راح ضحيتها 103 شهيد و 145  اصابة خلال ال 24 ساعة الماضية

▪️ لازال عدد من الضحايا تحت الركام وفي الطرقات يمنع الاحتلال وصول طواقم الاسعاف والدفاع المدني الوصول اليهم

▪️ارتفاع حصيلة العدوان الاسرائيلي الى 28576 شهيد و 68291 اصابة منذ السابع من اكتوبر الماضي

        وزارة الصحة الفلسطينية
               قطاع غزة
            14 فبراير 2024"""

ERA_B_72H = """*🇵🇸وزارة الصحة الفلسطينية-غزة🇵🇸*

*🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جراء العدوان الإسرائيلي على قطاع غزة .*

▪️وصل مستشفيات قطاع غزة 23 شهيد *( منهم 14 شهيد انتشال و5 شهداء متأثرين بجراحهم و4 شهداء جدد )* و 11 اصابة،  *خلال 72 ساعة الماضية.*

▪ارتفاع حصيلة العدوان الاسرائيلي الى 47,306 شهيد و 111,483 اصابة منذ السابع من اكتوبر للعام 2023م.
   26 يناير 2025"""

ERA_B_AID = """🇵🇸 وزارة الصحة الفلسطينية – غزة 🇵🇸

🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جراء العدوان الإسرائيلي على قطاع غزة

⭕وصل إلى مستشفيات قطاع غزة 87 شهيدًا (منهم 8 شهيدًا جرى انتشالهم) و 644 إصابة خلال الـ24 ساعة الماضية.

⭕ارتفعت حصيلة العدوان الإسرائيلي إلى 61,020 شهيدًا 150,671 إصابة منذ السابع من أكتوبر للعام 2023م.
⭕بلغت حصيلة الشهداء والإصابات منذ 18 مارس 2025 حتى اليوم 9,519 شهيدًا و 38,630 إصابة.

🔴 ضمن شهداء لقمة العيش:
بلغ عدد ما وصل إلى المستشفيات خلال الـ24 ساعة الماضية من شهداء المساعدات 52 شهيدًا و 352 إصابة،
ليرتفع إجمالي شهداء لقمة العيش ممن وصلوا المستشفيات إلى 1,568 شهيدًا وأكثر من 11,230 إصابة.
⭕سجّلت مستشفيات قطاع غزة خلال الـ24 ساعة الماضية 8 حالات وفاة جديدة نتيجة المجاعة وسوء التغذية، من بينهم طفل و7 بالغين.

⬅️ وبذلك، يرتفع العدد الإجمالي لضحايا المجاعة وسوء التغذية إلى 188 شهيدًا، من بينهم 94 طفلًا.
5 أغسطس 2025"""

ERA_C_PROSE = """🇵🇸 وزارة الصحة الفلسطينية – غزة 🇵🇸

🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جراء العدوان الإسرائيلي على قطاع غزة

⭕ وصل إلى مستشفيات قطاع غزة 3 شهداء(منهم 1 شهيد جديد، 2 شهيد إنتشال)  و 2 اصابات خلال الـ 24 ساعة الماضية.

🔴 منذ وقف إطلاق النار (11 أكتوبر 2025):
 • إجمالي الشهداء: 241
 • إجمالي الإصابات: 609
 • إجمالي الانتشال: 513

⭕ ارتفعت حصيلة العدوان الإسرائيلي إلى 68,875 شهيدًا 170,679 إصابة منذ السابع من أكتوبر للعام 2023م.
05 نوفمبر 2025"""


def test_era_a_without_hamza_is_a_report_with_a_day_and_a_toll():
    r = parse(ERA_A)
    assert r.is_report
    assert r.tiers["daily"] == {"deaths": 103, "injuries": 145, "massacres": 11}
    assert r.tiers["cumulative"] == {"deaths": 28576, "injuries": 68291}


def test_era_b_72_hour_block_is_a_period_not_a_day():
    r = parse(ERA_B_72H)
    assert "daily" not in r.tiers
    assert r.tiers["period"] == {"deaths": 23, "injuries": 11, "hours": 72,
                                 "recovered": 14, "succumbed": 5, "new": 4}
    assert r.tiers["cumulative"] == {"deaths": 47306, "injuries": 111483}


def test_era_b_resumption_aid_seekers_and_famine():
    r = parse(ERA_B_AID)
    assert r.tiers["daily"]["deaths"] == 87 and r.tiers["daily"]["injuries"] == 644
    assert r.tiers["daily"]["recovered"] == 8
    assert r.tiers["cumulative"] == {"deaths": 61020, "injuries": 150671}
    assert r.tiers["since_resumption"] == {"deaths": 9519, "injuries": 38630}
    assert r.tiers["aid_seekers_daily"] == {"deaths": 52, "injuries": 352}
    assert r.tiers["aid_seekers"] == {"deaths": 1568, "injuries": 11230}
    assert r.tiers["famine_daily"] == {"deaths": 8, "children": 1}
    assert r.tiers["famine"] == {"deaths": 188, "children": 94}


def test_era_c_prose_line_keeps_the_sectioned_tiers():
    r = parse(ERA_C_PROSE)
    assert r.tiers["daily"]["deaths"] == 3 and r.tiers["daily"]["injuries"] == 2
    assert r.tiers["daily"]["new"] == 1 and r.tiers["daily"]["recovered"] == 2
    assert r.tiers["since_ceasefire"] == {"deaths": 241, "injuries": 609, "recovered": 513}
    assert r.tiers["cumulative"] == {"deaths": 68875, "injuries": 170679}


def test_every_emitted_measure_has_an_indicator():
    for text in (ERA_A, ERA_B_72H, ERA_B_AID, ERA_C_PROSE):
        for tier, measures in parse(text).tiers.items():
            for measure in measures:
                assert (tier, measure) in INDICATORS, (tier, measure)


def test_the_first_bulletins_after_the_ceasefire_name_the_newly_killed_as_direct_targeting():
    """16-27 October 2025: "4 شهداء نتيجة استهداف مباشر من الاحتلال" beside the
    recovered and the died-of-wounds. From 28 October the same figure is written
    "شهداء جدد". Eight bulletins were read without their newly killed (74 people)."""
    r = parse("🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جراء العدوان الإسرائيلي على قطاع غزة\n\n"
              "⭕ وصل إلى مستشفيات قطاع غزة 29 شهيدًا (منهم 22 شهيد انتشال، و3 شهداء متأثرين بإصابتهم، "
              "و4 شهداء نتيجة استهداف مباشر من الاحتلال)، و10 إصابات خلال الـ24 ساعة الماضية.\n\n"
              "⭕ ارتفعت حصيلة العدوان الإسرائيلي إلى 67,967 شهيدًا و170,179 إصابة منذ السابع من أكتوبر للعام 2023م.\n\n"
              "🔴 منذ وقف إطلاق النار (11 أكتوبر 2025):\n • إجمالي الشهداء: 23\n • إجمالي الإصابات: 122\n"
              " • إجمالي الانتشال: 381\n")
    day = r.tiers["daily"]
    assert (day["deaths"], day["recovered"], day["succumbed"], day["new"]) == (29, 22, 3, 4)
    # the Ministry's since-ceasefire total leaves the recovered out: 23 < 29, and that is right
    assert r.tiers["since_ceasefire"]["deaths"] == 23 and r.tiers["since_ceasefire"]["recovered"] == 381


# ── the last three bulletins of the archive with no readable day line (2026-10-12) ──

def test_a_day_line_cut_after_its_number_is_read_whole():
    """11 October 2024: the sentence breaks between "231" and "اصابة خلال الـ 24
    ساعة", so the first half had no window and the second no count."""
    r = parse("🇵🇸وزارة الصحة بغزة||\n\nالتقرير الاحصائي اليومي لعدد الشهداء والجرحى جراء العدوان "
              "الاسرائيلي المستمر لليوم ال 371  على قطاع غزة.\n\n"
              "▪️ الاحتلال الاسرائيلي يرتكب 4  مجازر ضد العائلات في قطاع غزة  وصل منها للمستشفيات 61 شهيد و 231\n"
              " اصابة خلال الـ 24 ساعة الماضية.\n \n"
              "▪ارتفاع حصيلة العدوان الاسرائيلي الى 42,126  شهيد و 98,117  اصابة منذ السابع من اكتوبر الماضي.\n")
    assert r.tiers["daily"] == {"deaths": 61, "injuries": 231, "massacres": 4}
    assert r.tiers["cumulative"] == {"deaths": 42126, "injuries": 98117}


def test_the_days_of_eid_are_a_block_of_unstated_length_never_a_day():
    """23 March 2026: "خلال ايام عيد الفطر وحتى الساعة". No hours are given, so
    none are stored; the figures are a period's, not a day's."""
    r = parse("🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة\n\n"
              "⭕ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال ايام عيد الفطر وحتى الساعة:\n"
              "9 شهداء(منهم 1شهيد متأثر بإصابته) و 30 إصابة.\n\n"
              "🔴 منذ وقف إطلاق النار (11 أكتوبر):\n• إجمالي عدد الشهداء: 687\n• إجمالي عدد الإصابات: 1,845\n"
              "• إجمالي حالات الانتشال: 756\n\n"
              "🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:\n"
              "• العدد التراكمي للشهداء: 72,263\n• العدد التراكمي للإصابات: 171,944\n")
    assert "daily" not in r.tiers
    assert r.tiers["period"] == {"deaths": 9, "injuries": 30, "succumbed": 1}
    assert r.tiers["since_ceasefire"] == {"deaths": 687, "injuries": 1845, "recovered": 756}
    assert r.tiers["cumulative"] == {"deaths": 72263, "injuries": 171944}


def test_a_bulletin_that_names_no_window_is_not_given_one():
    """4 June 2026: "بلغ إجمالي ما وصل … حتى هذه اللحظة." with the counts below
    and no "24 ساعة" anywhere. Read as a period with no hours, not as a day."""
    r = parse("🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة\n\n"
              "⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة حتى هذه اللحظة.\n\n"
              "• عدد الشهداء: 11 شهداء جدد . \n• ⁠عدد الإصابات: 32 إصابة. \n\n\n"
              "⭕ لا يزال عدد من الضحايا تحت الركام وفي الطرقات، في ظل عجز طواقم الإسعاف والدفاع المدني "
              "عن الوصول إليهم حتى هذه اللحظة.\n\n"
              "🔴 منذ وقف إطلاق النار (11 أكتوبر):\n• إجمالي عدد الشهداء: 947\n• إجمالي عدد الإصابات: 2,935\n"
              "• إجمالي حالات الانتشال: 781\n\n"
              "🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:\n"
              "• العدد التراكمي للشهداء:72,956\n• العدد التراكمي للإصابات: 173,043\n")
    assert "daily" not in r.tiers and "hours" not in r.tiers["period"]
    assert r.tiers["period"] == {"new": 11, "deaths": 11, "injuries": 32}
    assert r.tiers["since_ceasefire"]["deaths"] == 947 and r.tiers["cumulative"]["deaths"] == 72956


def test_the_committees_additions_are_read_under_its_new_name_too():
    """Until December 2025 the bulletins said "اللجنة القضائية"; since then
    "لجنة اعتماد الشهداء". Seventeen bulletins (2,412 people) were read without
    their committee figure because the rule asked for the definite article."""
    r = parse("🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة\n\n"
              "⭕ وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية: 2 شهداء و 5 إصابات.\n\n"
              "⭕ تم اضافة عدد 92 شهيد للإحصائية التراكمية للشهداء، ممن تم اكتمال بياناتهم واعتمادهم من "
              "لجنة اعتماد الشهداء من تاريخ 02/01/2026 الى 16/01/2026\n\n"
              "🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:\n"
              "• العدد التراكمي للشهداء: 71,548\n• العدد التراكمي للإصابات: 171,353\n")
    assert r.tiers["daily"]["committee"] == 92
    assert r.tiers["daily"]["deaths"] == 2 and r.tiers["cumulative"]["deaths"] == 71548
