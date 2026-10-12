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
