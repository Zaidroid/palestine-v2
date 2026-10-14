"""The market channel's price lists (ops/build_market_channel.py, 2026-10-14).

Each case is a post as the channel writes it, cut down; the rules are the ones
measured on its 2,542 posts."""
from __future__ import annotations

from pathlib import Path

import yaml

from ops import build_market_channel as mc

ROOT = Path(__file__).resolve().parent.parent


def post(pid: int, text: str, date: str = "2024-11-21T08:24:33+00:00") -> dict:
    return {"channel": "asarsook", "id": pid, "date": date, "text": text, "views": "1K"}


def by_measure(posts):
    recs, notes = mc.build(posts)
    return {(r["date"], r["measure"]): r for r in recs}, notes


def test_a_list_by_area_with_its_own_date_and_the_two_line_form():
    text = ("📊 الأسعار في جنوب قطاع غزة اليوم\n🗓️ 20 نوفمبر 2024\n\nكيس طحين 25 كيلو\n800 شيكل\n\n"
            "كيلو بطاطا 25 - 30 شيكل\n\nكيلو عدس حب 25 شيكل\n\nكيلو عدس مجروش 17 شيكل\n\nلتر سيرج 45 شيكل\n")
    got, notes = by_measure([post(5, text)])
    flour = got[("2024-11-20", "flour_25kg_sack_south")]       # the list's date, the day before the post
    assert (flour["value"], flour["unit"]) == (800, "ILS/25 KG")
    potato = got[("2024-11-20", "potato_south")]                # a range: its midpoint, the ends kept; not a 25 kg unit
    assert (potato["value"], potato["unit"], potato["range_printed"]) == (27.5, "ILS/KG", [25.0, 30.0])
    assert got[("2024-11-20", "lentils_whole_south")]["value"] == 25
    assert got[("2024-11-20", "lentils_split_south")]["value"] == 17
    assert got[("2024-11-20", "vegetable_oil_south")]["unit"] == "ILS/L"
    assert notes["days_from_the_list"] == 1


def test_many_items_on_one_line_ranges_and_the_units_that_are_not_held():
    text = ("📅 أسعار الخضروات والفواكه اليوم 🗓️\n\n السبت | 06/06/2026\n━━━━\n🥬 الخضروات\n"
            "🥔 بطاطا: 7 شيكل ➖ 6 شيكل 🧅 بصل: 7 شيكل 🫑 فلفل سلطان: 5 شيكل للوقية "
            "🧄 ثوم للخزين: 13 شيكل/كغم 🥔 بطاطا بلدية (الرطل) ➝ 11 شيكل 🍆 باذنجان: 8 شيكل ➖ 6 شيكل\n")
    got, notes = by_measure([post(2342, text, "2026-06-06T09:00:00+00:00")])
    d = "2026-06-06"
    assert (got[(d, "potato")]["value"], got[(d, "potato")]["range_printed"]) == (6.5, [6.0, 7.0])
    assert got[(d, "onion")]["value"] == 7
    assert got[(d, "eggplant")]["value"] == 7
    assert (d, "hot_pepper") not in got                         # by the uqiya
    assert (d, "potato_local") not in got                       # by the ratl
    assert notes["units_not_held"] == {"priced by the uqiya": 1, "priced by the ratl": 1}


def test_the_goods_that_look_alike():
    text = ("🐔أسعار اللحوم البيضاء في مدينة غزة\n 🗓️ السبت 15 فبراير 2025\n\n👈 دجاج كامل 24 شيكل\n\n"
            "👈 صدر دجاج  مقطع 28 شيكل\n\n👈 صدر دجاج كامل 33 شيكل\n\n👈 قلاية بندورة 16 شيكل\n\n"
            "👈 حمض الليمون 600 شيكل\n\n👈 بزر بطيخ محمص 120 شيكل\n")
    got, _ = by_measure([post(135, text, "2025-02-15T10:59:56+00:00")])
    d = "2025-02-15"
    assert got[(d, "whole_chicken_gaza_city")]["value"] == 24
    assert got[(d, "chicken_breast_cut_gaza_city")]["value"] == 28
    assert got[(d, "chicken_breast_whole_gaza_city")]["value"] == 33   # not a second whole chicken
    goods = {r["good"] for r in got.values()}
    assert not goods & {"tomato", "lemon", "watermelon"}        # a dish, citric acid, roasted seeds


def test_what_is_not_a_list():
    exchange = post(2814, "📊 أسعار صرف العملات مقابل الشيكل اليوم\n💵 الدولار: 3.055 شيكل 💶 اليورو: 3.429 شيكل "
                          "💰 الدينار الأردني: 4.308 شيكل 💷 الجنيه المصري: 0.0583 شيكل")
    advert = post(900, "🍗 متوفر اليوم\nدجاج كامل 20 شيكل\nجناح دجاج 12 شيكل\nصدر دجاج 30 شيكل\nللطلب 0599123456")
    gas = post(1875, "📢 تعميم هام: أسعار أسطوانات الغاز (8 كيلو) 📢\n\n"
                     "بناءً على ما أفادت به هيئة البترول، نود إعلامكم بأسعار أسطوانات الغاز سعة 8 كيلو كما يلي وبدون أي زيادة:\n"
                     "💰 السعر للموزع: 68 شيكل.\n🏠 السعر للمستهلك: 74 شيكل.\n"
                     "هامش الربح تم تحديده بستة شواكل فقط لكل أسطوانة ومن يخالف ذلك يعرض نفسه للمساءلة القانونية الصارمة\n"
                     "أي زيادة عن السعر المعلن ستعرض صاحبها للإجراءات القانونية الصارمة والتي تشمل التوقيف عن العمل\n"
                     "نرجو من الجميع الالتزام التام بالأسعار المحددة وعدم استغلال حاجة المواطنين في هذه الظروف الصعبة\n"
                     "والإبلاغ عن أي مخالفة 5 شيكل")
    essay = post(1545, "الناس في #غزة مستغربين\n⚠️ هو مين باعنا حبة البطاطا بـ 100 شيكل ؟\n"
                       "⚠️ مين باعنا كيلو السكر بـ 500 شيكل ؟\n⚠️ مين باعنا كيس الطحين بـ 1200 و 3000 شيكل ؟")
    got, notes = by_measure([exchange, advert, gas, essay])
    assert got == {}
    assert notes["not_read"] == {"exchange_rates": 1, "advert": 1, "commentary": 1}
    assert mc.good_of("السعر للموزع") is None                  # «موز» inside «للموزع» is not a banana


def test_paid_by_app_and_missing_are_series_of_their_own():
    text = ("📍 أسعار سوق النصيرات\n🗓️ اليوم الجمعة 29/8/2025\n━━━━\n"
            "• 🛢️ لتر السيرج: 25 شيكل (تطبيق)\n• 🍚 كيلو السكر: 15 شيكل (تطبيق)\n• 🧂 كيلو الملح: 3 شيكل\n"
            "• 🧅 كيلو البصل: ❌ مفقود\n")
    got, _ = by_measure([post(800, text, "2025-08-29T10:04:47+00:00")])
    d = "2025-08-29"
    assert got[(d, "vegetable_oil_central_by_app")]["paid_by_app"] is True
    assert got[(d, "sugar_central_by_app")]["value"] == 15
    assert got[(d, "salt_central")]["value"] == 3
    miss = got[(d, "onion_central_missing")]
    assert (miss["value"], miss["text"], miss["unit"]) == (None, "missing", None)


def test_two_lists_the_same_day_the_earliest_stands():
    a = post(10, "الأسعار شمال قطاع غزة\n🗓19 ديسمبر 2024\nبصل 35 شيكل\nليمون 40 شيكل\nموز 50 شيكل",
             "2024-12-19T08:00:00+00:00")
    b = post(11, "الأسعار شمال قطاع غزة\n🗓19 ديسمبر 2024\nبصل 30 شيكل\nليمون 40 شيكل\nموز 50 شيكل",
             "2024-12-19T15:00:00+00:00")
    got, notes = by_measure([a, b])
    onion = got[("2024-12-19", "onion_north")]
    assert onion["value"] == 35 and onion["post"].endswith("/10")
    assert onion["other_prices_same_day"] == [{"value": 30.0, "post": "https://t.me/asarsook/11"}]
    assert notes["same_day_different_price"] == 1


def test_a_date_far_from_the_post_is_not_believed():
    text = "الأسعار شمال قطاع غزة\n🗓19 ديسمبر 2024\nبصل 35 شيكل\nليمون 40 شيكل\nموز 50 شيكل"
    got, notes = by_measure([post(12, text, "2025-03-01T10:00:00+00:00")])
    assert ("2025-03-01", "onion_north") in got                 # the post's own day in Gaza
    assert notes["days_from_the_post"] == 1


def test_the_spec_names_every_series_it_holds_and_every_unit_converts():
    spec = yaml.safe_load((ROOT / "db" / "mappings" / "price_asarsook.yaml").read_text(encoding="utf-8"))
    rules = spec["registry"]["rules"]
    assert all(r["name_en"] and r["name_ar"] and r["serve_warning"] and r["serve_warning_ar"] for r in rules)
    names = {r["when"]["equals"] for r in rules}
    assert {"price_asarsook.tomato", "price_asarsook.flour_25kg_sack_south",
            "price_asarsook.chicken_breast_whole_gaza_city"} <= names
    units = yaml.safe_load((ROOT / "db" / "registry" / "units.yaml").read_text(encoding="utf-8"))
    aliases = {a for u in units["units"].values() for a in (u.get("aliases") or {})}
    assert {"ILS/KG", "ILS/L", "ILS/25 KG", "ILS/3 KG", "ILS/4 KG", "ILS/5 KG", "ILS/10 KG", "ILS/800 G",
            "ILS/PIECE", "ILS/30 PIECES"} <= aliases
