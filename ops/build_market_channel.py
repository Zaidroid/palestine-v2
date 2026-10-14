"""Gaza's market prices as a Telegram channel posts them: «أسعار السوق - غزة» (@asarsook).

    .venv/bin/python -m ops.build_market_channel            # writes data/raw/market_channel/prices.json
    .venv/bin/python -m ops.build_market_channel --dry-run  # says what it would write
    .venv/bin/python -m ops.build_market_channel --posts DIR  # the channel's posts from another folder

WHY. The channel (5,000 subscribers, November 2024 onward) posts the day's
prices in Gaza's markets: lists for the north, Gaza City, the middle area or
the south, the Ministry of Agriculture's marketing directorate's own lists,
the price of chicken and fish, and which goods are missing. The Chamber of
Commerce gives a week's average for 31 goods; this gives the day, the market,
more goods (chicken by the cut, fish, eggs) and the price paid by app beside
the price in cash. Read from the posts the public channel reader holds
(data/raw/tg_public/asarsook/, ops/fetch_telegram_public.py); no network here.

WHAT IS READ (measured 2026-10-14 over 2,542 posts, 263 with three prices or
more):
  - a line that names a good on the list below and prints a price in shekels
    («بندورة: 12 شيكل», «كيس طحين 25 كيلو» then «800 شيكل» on the next line);
  - the unit: the one the line prints (كيلو, لتر, كيس 25 كيلو, «3 كيلو», the
    egg, the tray), else the kilo for produce, meat and fish, which these lists
    sell by the kilo (several say so: «الاسعار المرفقة بالكيلو», «وحدة القياس:
    شيكل / كيلو جرام»); the row's basis says which;
  - the area: a list's heading or a section's heading names it (north, Gaza
    City, the middle area, the south) and the market where printed; a list
    that names none is the Strip's;
  - the day: the date the list prints, when it is within three days before the
    post or the day after; else the post's own day in Gaza;
  - «(تطبيق)» after a price: paid by app (a bank transfer), a series of its
    own beside the price in cash, which runs lower;
  - «مفقود» / «غير متوفر» / ❌: the good was missing from the market that day,
    a mark of its own.
NOT READ, and counted in the file's metadata: posts of exchange rates (the
official rate, not a Gaza one), shop adverts (a phone number, «للطلب»,
«توصيل»), the one wholesale-and-consumer table, a good priced by the
«وقية» or the «رطل» (their weights differ by town) or by a sack or a pack of no
stated size, and every line whose good is not on the list (each name with its
count, so the list can grow).
Two posts the same day for the same good and area: the earliest stands; a
different price from a later post sits beside it (other_prices_same_day).
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import fetchlib as fl                                  # noqa: E402

CHANNEL = "asarsook"
POSTS = ROOT / "data" / "raw" / "tg_public" / CHANNEL
OUT = ROOT / "data" / "raw" / "market_channel" / "prices.json"
LABEL = "market_channel:prices"
SOURCE_NAME = "أسعار السوق - غزة (Telegram channel @asarsook)"
GAZA = ZoneInfo("Asia/Gaza")
MIN_RECORDS = 1500

DIGITS = str.maketrans({**{a: b for a, b in zip("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")},
                       **{chr(c): None for c in range(0x064B, 0x0653)}, "\u0670": None})   # no diacritics
# a price, or a range («25 - 30 شيكل», «20–30₪»): the range's midpoint, its ends kept
PRICE = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?\s*(?:شيكل|شيقل|شواكل|شيكلًا|شيكلا|₪)")
NUM_ONLY = re.compile(r"^\D{0,3}(\d+(?:[.,]\d+)?)\s*(?:شيكل|شيقل|شواكل|₪)\D{0,6}$")
MISSING = re.compile(r"مفقود|غير متوفر|غير متواجد|لا يوجد|❌")
APP = re.compile(r"تطبيق")
NOISE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍‏‎•▪️◾◽■□●○◆◇★☆✅✔️➖➕➡️⬅️🔹🔸|*#_]+")

# The area a heading or a section names. Order matters: "شمال" before "غزة".
AREAS = [
    ("north", re.compile(r"شمال(?:ي)?\s*(?:قطاع\s*)?غزة|الشمال|جباليا|بيت لاهيا|بيت حانون")),
    ("south", re.compile(r"جنوب(?:ي)?\s*(?:قطاع\s*)?غزة|الجنوب|خان ?يونس|رفح|المواصي")),
    ("central", re.compile(r"وسط\s*(?:قطاع\s*)?غزة|الوسطى|المنطقة الوسطى|دير البلح|النصيرات|الزوايدة|البريج|المغازي")),
    ("gaza_city", re.compile(r"مدينة غزة|غزة المدينة|سوق الشيخ رضوان|الرمال|الشجاعية|الزيتون|سوق فراس")),
]
MARKET = re.compile(r"(سوق\s+[؀-ۿ]+(?:\s+[؀-ۿ]+)?)")
AREA_EN = {"north": "the north of the Gaza Strip", "south": "the south of the Gaza Strip",
           "central": "the middle area of the Gaza Strip", "gaza_city": "Gaza City", None: "the Gaza Strip"}
AREA_AR = {"north": "شمال قطاع غزة", "south": "جنوب قطاع غزة", "central": "المنطقة الوسطى من قطاع غزة",
           "gaza_city": "مدينة غزة", None: "قطاع غزة"}

AD = re.compile(r"للطلب|للتواصل|توصيل|واتس|اتصل|(?<!\d)05\d{8}(?!\d)|(?<!\d)\+?970\d{8,9}(?!\d)")
EXCHANGE = re.compile(r"صرف|الدولار|الدينار|اليورو|الجنيه")
WHOLESALE_TABLE = re.compile(r"المستهلك")

# goods: (key, English name, Arabic name, pattern on the item's words, kind). kind "kilo" takes the
# kilo when the line prints no unit; "litre", "egg" and "sack25" take only what they say.
GOODS = [
    ("flour_25kg_sack", "flour", "طحين", r"طحين|دقيق", "sack25"),
    ("sugar", "sugar", "سكر", r"سكر", "kilo"),
    ("rice_egyptian", "Egyptian rice", "أرز مصري", r"(?:رز|أرز|ارز)\s*مصري", "kilo"),
    ("rice_long_grain", "long-grain rice", "أرز طويل الحبة", r"(?:رز|أرز|ارز)\s*(?:طويل|بسمتي|امريكي|أمريكي)", "kilo"),
    ("rice", "rice", "أرز", r"(?:^| )(?:رز|أرز|ارز)$", "kilo"),
    ("vegetable_oil", "vegetable oil", "زيت نباتي (سيرج)", r"سيرج|زيت\s*(?:نباتي|ذرة|عباد|دوار)", "litre"),
    ("olive_oil", "olive oil", "زيت زيتون", r"زيت\s*(?:ال)?زيتون", "litre"),
    ("lentils_split", "split lentils", "عدس مجروش", r"عدس\s*(?:مجروش|احمر|أحمر|مقشر)", "kilo"),
    ("lentils_whole", "whole lentils", "عدس حب", r"عدس\s*(?:حب|بني|اسود|أسود|كامل)", "kilo"),
    ("lentils", "lentils", "عدس", r"عدس", "kilo"),
    ("bulgur", "bulgur", "برغل", r"برغل", "kilo"),
    ("semolina", "semolina", "سميد", r"سميد", "kilo"),
    ("pasta", "pasta", "معكرونة", r"معكرون|مكرون", "kilo"),
    ("salt", "salt", "ملح", r"(?:^| )ملح$", "kilo"),
    ("tomato", "tomato", "بندورة", r"بندورة|طماطم", "kilo"),
    ("cucumber", "cucumber", "خيار", r"خيار", "kilo"),
    ("onion", "onion", "بصل", r"(?:^| )بصل(?!\s*(?:أخضر|اخضر))", "kilo"),
    ("sweet_potato", "sweet potato", "بطاطا حلوة", r"بطاطا\s*حلو", "kilo"),
    ("potato_local", "local potato", "بطاطا بلدية", r"بطاط(?:ا|س)?\s*بلدي", "kilo"),
    ("potato", "potato", "بطاطا", r"(?:^| )بطاط(?:ا|س)?(?!\s*حلو)", "kilo"),
    ("eggplant", "eggplant", "باذنجان", r"باذنجان|بتنجان|بادنجان", "kilo"),
    ("zucchini", "zucchini", "كوسا", r"كوسا|كوسة", "kilo"),
    ("sweet_pepper", "sweet pepper", "فلفل حلو", r"فلفل\s*حلو|فليفلة|فلفل\s*ملون|فلفل\s*رومي", "kilo"),
    ("carrot", "carrot", "جزر", r"جزر", "kilo"),
    ("lemon", "lemon", "ليمون", r"ليمون", "kilo"),
    ("red_cabbage", "red cabbage", "ملفوف أحمر", r"ملفوف\s*(?:أحمر|احمر)", "kilo"),
    ("cabbage", "cabbage", "ملفوف", r"ملفوف", "kilo"),
    ("cauliflower", "cauliflower", "زهرة", r"^زهرة|قرنبيط", "kilo"),
    ("pumpkin", "pumpkin", "قرع", r"قرع", "kilo"),
    ("molokhia", "molokhia", "ملوخية", r"ملوخي", "kilo"),
    ("apple", "apple", "تفاح", r"تفاح", "kilo"),
    ("banana", "banana", "موز", r"(?:^| )موز(?:$| )", "kilo"),
    ("orange", "orange", "برتقال", r"برتقال", "kilo"),
    ("clementine", "clementine", "كلمنتينا", r"كلمنتين|يوسف", "kilo"),
    ("pear", "pear", "إجاص", r"إجاص|اجاص|إنجاص|انجاص", "kilo"),
    ("grapes", "grapes", "عنب", r"عنب", "kilo"),
    ("watermelon", "watermelon", "بطيخ", r"بطيخ", "kilo"),
    ("melon", "melon", "شمام", r"شمام", "kilo"),
    ("avocado", "avocado", "أفوكادو", r"أفوكادو|افوكادو|أبو ?كادو|ابو ?كادو", "kilo"),
    ("mango", "mango", "مانجا", r"مانجا|مانجو", "kilo"),
    ("guava", "guava", "جوافة", r"جواف", "kilo"),
    ("strawberry", "strawberry", "فراولة", r"فراول", "kilo"),
    ("persimmon", "persimmon", "فرسمون", r"فرسمون|كاكا", "kilo"),
    ("pomegranate", "pomegranate", "رمان", r"رمان", "kilo"),
    ("turkey_breast", "turkey breast", "صدر حبش", r"صدر\s*حبش", "kilo"),
    ("chicken_breast_whole", "whole chicken breast", "صدر دجاج كامل", r"صدر\s*(?:دجاج\s*)?كامل", "kilo"),
    ("chicken_breast_cut", "cut chicken breast", "صدر دجاج مقطع", r"صدر\s*(?:دجاج\s*)?(?:مقطع|قطع|شيش|دفتر)", "kilo"),
    ("chicken_breast", "chicken breast", "صدر دجاج", r"صدر\s*دجاج|^صدر$", "kilo"),
    ("whole_chicken", "whole chicken", "دجاج كامل", r"(?<!صدر )دجاج\s*كامل|^دجاج(?:\s*(?:إسرائيلي|اسرائيلي|برازيلي|طازج|مجمد|مصري))?(?:\s*نخب)?$", "kilo"),
    ("chicken_wings", "chicken wings", "جناح دجاج", r"جناح\s*دجاج|^جناح$", "kilo"),
    ("chicken_drumsticks", "chicken drumsticks", "دبوس دجاج", r"دبوس\s*دجاج|^دبوس$", "kilo"),
    ("chicken_thighs", "chicken thighs", "فخذ دجاج", r"فخ[دذ]\s*دجاج|^فخ[دذ]", "kilo"),
    ("chicken_liver", "chicken liver", "كبدة دجاج", r"كبد[ةه]\s*دجاج", "kilo"),
    ("turkey_wings", "turkey wings", "جناح حبش", r"جناح\s*حبش", "kilo"),
    ("turkey_drumsticks", "turkey drumsticks", "دبوس حبش", r"دبوس\s*حبش", "kilo"),
    ("veal", "veal", "لحمة عجل", r"لحم[ةه]?\s*عجل|لحم[ةه]?\s*موزة|كتف\s*وموزة", "kilo"),
    ("minced_meat", "minced meat", "لحمة مفرومة", r"مفروم", "kilo"),
    ("calf_liver", "calf liver", "كبدة عجل", r"كبد[ةه]\s*عجل", "kilo"),
    ("frozen_fish_pollock", "frozen fish (bakala)", "سمك بكلا", r"بك[لا]ا|بكالا", "kilo"),
    ("fish_fillet", "fish fillet", "سمك فيليه", r"فيليه|فيلية", "kilo"),
    ("sardines", "sardines", "سردين", r"سردين", "kilo"),
    ("shrimp", "shrimp", "جمبري", r"جمبري|قريدس", "kilo"),
    ("eggs", "eggs", "بيض", r"بيض", "egg"),
    ("kiwi", "kiwi", "كيوي", r"كيوي", "kilo"),
    ("garlic", "garlic", "ثوم", r"(?:^| )(?:ثوم|تومة)$", "kilo"),
    ("turkey_liver", "turkey liver", "كبدة حبش", r"كبد[ةه]\s*حبش", "kilo"),
    ("chicken_backs", "chicken backs", "ظهر دجاج", r"[ضظ]هر\s*دجاج", "kilo"),
    ("hot_pepper", "hot pepper", "فلفل حار", r"فلفل\s*(?:سلطان|حار|اخضر|أخضر|بلدي)", "kilo"),
    ("okra", "okra", "بامية", r"بامي", "kilo"),
]
# Prepared or canned: never the fresh good («قلاية بندورة», «صلصة», «ذرة معلبة»).
NOT_FRESH = re.compile(r"قلاي|صلص|معلب|علب[ةه]|عصير|مربى|سلط[ةه]|شيبس|مجفف|مخلل|معجون|نقانق|لانشون|حمض|بزر|ورق")
_GOODS = [(k, en, ar, re.compile(p), kind) for k, en, ar, p, kind in GOODS]
GOOD_EN = {k: en for k, en, _, _, _ in GOODS}
GOOD_AR = {k: ar for k, _, ar, _, _ in GOODS}

UNIT_SACK = re.compile(r"(?:كيس|شوال)[^\d]{0,12}(\d+)\s*(?:كيلو|كغم|كجم|كغ|كلغ)")
UNIT_KILOS = re.compile(r"(?:^|\s)(\d+(?:\.\d+)?)\s*(?:كيلو|كغم|كجم|كغ)")
UNIT_GRAMS = re.compile(r"(\d+)\s*(?:غرام|جرام|غم|جم)")
UNIT_UQIYA = re.compile(r"وقي[ةه]|أوقي[ةه]")
UNIT_RATL = re.compile(r"رطل")                 # the ratl: several kilos, its weight differs by town
UNIT_PACK = re.compile(r"شوال|كيس|علب[ةه]|باكيت|بكيت|كرتون[ةه](?!\s*بيض)|ربط[ةه]|حب[ةه]|راس|رأس|قرص|شبر[ةه]")
EGG_TRAY = re.compile(r"كرتون[ةه]|طبق|صحن")
EGG_ONE = re.compile(r"(?:ال)?بيض[ةه](?!\s*\d)|حب[ةه]\s*(?:ال)?بيض")

ARABIC_MONTHS = {
    "يناير": 1, "كانون الثاني": 1, "فبراير": 2, "شباط": 2, "مارس": 3, "آذار": 3, "اذار": 3, "أبريل": 4, "ابريل": 4,
    "نيسان": 4, "مايو": 5, "أيار": 5, "ايار": 5, "يونيو": 6, "يونيه": 6, "حزيران": 6, "يوليو": 7, "يوليه": 7,
    "تموز": 7, "أغسطس": 8, "اغسطس": 8, "آب": 8, "اب": 8, "سبتمبر": 9, "أيلول": 9, "ايلول": 9, "أكتوبر": 10,
    "اكتوبر": 10, "تشرين الأول": 10, "تشرين الاول": 10, "نوفمبر": 11, "تشرين الثاني": 11, "ديسمبر": 12,
    "كانون الأول": 12, "كانون الاول": 12}
_MONTH_NAMES = "|".join(sorted(ARABIC_MONTHS, key=len, reverse=True))
DATE_WORDS = re.compile(rf"(\d{{1,2}})\s*(?:من\s*)?({_MONTH_NAMES})\s*(\d{{4}})?")
DATE_NUM = re.compile(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4}|\d{2})(?!\d)")
DATE_ISO = re.compile(r"(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?!\d)")


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", NOISE.sub(" ", line.translate(DIGITS))).strip(" :-–—،,.")


def area_of(text: str) -> str | None:
    for code, pat in AREAS:
        if pat.search(text):
            return code
    return None


def stated_date(head: str, posted: dt.date) -> dt.date | None:
    """The date a list prints in its first lines, if it is within three days
    before the post or the day after."""
    head = head.translate(DIGITS)
    cands = []
    for m in DATE_ISO.finditer(head):
        cands.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in DATE_NUM.finditer(head):
        y = int(m.group(3))
        cands.append((y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1))))
    for m in DATE_WORDS.finditer(head):
        cands.append((int(m.group(3)) if m.group(3) else posted.year, ARABIC_MONTHS[m.group(2)], int(m.group(1))))
    for y, mo, d in cands:
        try:
            day = dt.date(y, mo, d)
        except ValueError:
            continue
        if posted - dt.timedelta(days=3) <= day <= posted + dt.timedelta(days=1):
            return day
    return None


LEAD = re.compile(r"^(?:\d+(?:\.\d+)?\s*)?(?:كيلو|كغم|كجم|لتر|ليتر|كيس|شوال|علب[ةه]|وقي[ةه]|راس|رأس|حب[ةه]|ربط[ةه]|سعر)\s+")


def match_words(name: str) -> str:
    """The item's words as the goods list reads them: no leading measure («كيلو
    البطاطا»), no article on any word («البصل» → «بصل»)."""
    w = name
    for _ in range(2):
        w = LEAD.sub("", w)
    return " ".join(x[2:] if x.startswith("ال") and len(x) > 4 else x for x in w.split())


def good_of(name: str):
    """The item's words → (key, kind), or None."""
    w = match_words(name)
    if NOT_FRESH.search(w):
        return None
    for key, _en, _ar, pat, kind in _GOODS:
        if pat.search(w):
            return key, kind
    return None


PER_KILO_AFTER = re.compile(r"^\s*(?:/\s*(?:كغم|كجم|كغ|كيلو|ك(?![\u0600-\u06FF]))|(?:لل|ال|بال)كيلو|للكغم|لكل كيلو)")


def unit_of(name: str, line: str, kind: str, default_kilo: bool, after: str = "") -> tuple[str | None, str]:
    """The unit an item is priced in, from the item's own words (`line` is the
    piece of the line that carries this price) and what follows the price, and
    the basis for it; None when it is not one the databank can hold (the uqiya,
    a pack of no stated size)."""
    if kind != "egg" and PER_KILO_AFTER.match(after):
        return "ILS/KG", "per kilo, as printed after the price"
    words = line if name in line else f"{name}\n{line}"
    if kind == "egg":
        if EGG_TRAY.search(words):
            return "ILS/30 PIECES", "a tray of eggs (30 in Gaza's trays)"
        if EGG_ONE.search(words):
            return "ILS/PIECE", "one egg, as printed"
        return None, "eggs with no count printed"
    if kind == "sack25":
        m = UNIT_SACK.search(words)
        if m and m.group(1) == "25":
            return "ILS/25 KG", "a 25 kg sack, as printed"
        if re.search(r"كيلو|كغم|كجم", words) and not m:
            k = UNIT_KILOS.search(words)
            if k:
                return f"ILS/{_n(k.group(1))} KG" if _n(k.group(1)) != "1" else "ILS/KG", "the kilos printed"
            return "ILS/KG", "a kilo, as printed"
        return None, "flour in a sack of no stated size"
    if UNIT_UQIYA.search(words) or UNIT_UQIYA.search(after[:10]):
        return None, "priced by the uqiya"
    if UNIT_RATL.search(words) or UNIT_RATL.search(after[:10]):
        return None, "priced by the ratl"
    if kind == "litre":
        if re.search(r"لتر|ليتر", words):
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:لتر|ليتر)", words)
            n = _n(m.group(1)) if m else "1"
            return ("ILS/L" if n == "1" else f"ILS/{n} L"), "the litres printed"
        return None, "oil with no measure printed"
    m = UNIT_SACK.search(words)
    if m:
        return f"ILS/{m.group(1)} KG", "a sack of the kilos printed"
    m = UNIT_KILOS.search(" " + words.replace("\n", " \n "))
    if m and 0 < float(m.group(1)) <= 50 and not re.search(r"\d\s*[-–—]\s*$", words[:m.end()]):
        n = _n(m.group(1))
        return ("ILS/KG" if n == "1" else f"ILS/{n} KG"), "the kilos printed"
    if re.search(r"كيلو|كغم|كجم|بالكيلو", words):
        return "ILS/KG", "a kilo, as printed"
    m = UNIT_GRAMS.search(words)
    if m:
        return f"ILS/{m.group(1)} G", "the grams printed"
    if UNIT_PACK.search(words):
        return None, "a pack, head or piece of no stated weight"
    if default_kilo:
        return "ILS/KG", "no unit printed; these lists sell produce, meat and fish by the kilo"
    return None, "no unit printed"


def _n(s: str) -> str:
    v = float(s.replace(",", "."))
    return str(int(v)) if v == int(v) else str(v)


def _value(s: str) -> float:
    return float(s.replace(",", "."))


def read_posts(root: Path = POSTS) -> list[dict]:
    by_id: dict[int, dict] = {}
    for f in sorted(root.glob("posts-*.ndjson.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                p = json.loads(line)
                by_id[int(p["id"])] = p
    return [by_id[k] for k in sorted(by_id)]


def kind_of(text: str) -> str | None:
    """Why a post is not read as a price list, or None when it is."""
    t = text.translate(DIGITS)
    if len(EXCHANGE.findall(t)) >= 2:
        return "exchange_rates"
    if AD.search(t):
        return "advert"
    if WHOLESALE_TABLE.search(t) and re.search(r"الخان|الجملة", t):
        return "wholesale_and_consumer_table"
    if len(PRICE.findall(t)) < 3:
        return "fewer_than_three_prices"
    lines = [l for l in t.splitlines() if l.strip()]
    sentences = sum(1 for l in lines if len(l.split()) >= 12 and len(PRICE.findall(l)) <= 1)
    priced = sum(1 for l in lines if PRICE.search(l))
    if sentences >= 3 and sentences * 2 >= priced:
        return "commentary"                            # an essay that quotes prices, not a list
    return None


def post_lines(post: dict):
    """Each priced (or missing) item of a list: (area, market, item words, the
    piece of the line before its price, value or None, missing, by_app, the
    words after the price)."""
    text = (post.get("text") or "").translate(DIGITS)
    lines = [l for l in text.splitlines()]
    head = " ".join(lines[:4])
    area = area_of(head)
    m = MARKET.search(head)
    market = m.group(1) if m else None
    default_kilo = True
    prev_name = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        price = PRICE.search(line)
        missing = bool(MISSING.search(line))
        if not price and not missing:
            # a heading: it may name the section's area; a bare item name waits for its price
            a = area_of(line)
            if a and len(_clean(line)) < 60:
                area = a
                mm = MARKET.search(line)
                market = mm.group(1) if mm else market
            prev_name = _clean(line)
            continue
        n_prices = len(PRICE.findall(line)) if price else 0
        if price and ("؟" in line or "?" in line or (n_prices == 1 and len(line.split()) >= 12)):
            # a question, or a sentence with a price in it: commentary, not a list item
            prev_name = ""
            continue
        if price:
            # several prices on one line («🍅 بندورة: 12 شيكل 🥒 خيار: 10 شيكل»): split at each price;
            # a price with no name right after another closes a range («بطاطا: 7 شيكل ➖ 6 شيكل»)
            items: list[list] = []
            start = 0
            for pm in PRICE.finditer(line):
                before = line[start:pm.start()]
                start = pm.end()
                tail = line[pm.end():pm.end() + 16]
                lo = _value(pm.group(1))
                hi = _value(pm.group(2)) if pm.group(2) else None
                name = _clean(re.sub(r"\(.*?\)", " ", before))
                has_name = bool(re.search(r"[\u0600-\u06FF]{2}", name))
                if not has_name and items and not re.sub(r"[\s➖\-–—/و]", "", before):
                    prev = items[-1]                     # the range's other end
                    ends = sorted(x for x in (prev[8] or (prev[4], None)) + (lo, hi) if x is not None)
                    prev[8] = (ends[0], ends[-1]) if ends[-1] > ends[0] else None
                    prev[4] = (ends[0] + ends[-1]) / 2
                    continue
                if not has_name or NUM_ONLY.match(line):
                    name = prev_name                      # the two-line form: the name on the line before
                rng = (lo, hi) if hi is not None and hi > lo else None
                value = (lo + hi) / 2 if rng else lo
                items.append([area, market, name, before if name != prev_name else f"{prev_name} {before}",
                              value, bool(MISSING.search(before)),
                              bool(APP.search(tail) or APP.search(before[-12:])), tail, rng])
            for it in items:
                yield tuple(it)
        else:
            name = _clean(re.sub(r"\(.*?\)", " ", MISSING.split(line)[0]))
            yield (area, market, name, line, None, True, False, "", None)
        prev_name = ""


def build(posts: list[dict]) -> tuple[list[dict], dict]:
    notes: dict = {"posts": len(posts), "not_read": Counter(), "names_not_held": Counter(),
                   "units_not_held": Counter(), "lists_read": 0, "days_from_the_list": 0,
                   "days_from_the_post": 0}
    best: dict[tuple, dict] = {}
    others: dict[tuple, list] = defaultdict(list)
    for post in posts:
        text = post.get("text") or ""
        why = kind_of(text)
        if why:
            if why != "fewer_than_three_prices":
                notes["not_read"][why] += 1
            continue
        posted_at = dt.datetime.fromisoformat(post["date"]).astimezone(GAZA)
        day = stated_date(" ".join(text.splitlines()[:5]), posted_at.date())
        notes["days_from_the_list" if day else "days_from_the_post"] += 1
        day = day or posted_at.date()
        notes["lists_read"] += 1
        url = f"https://t.me/{CHANNEL}/{post['id']}"
        for area, market, name, line, value, missing, by_app, after, rng in post_lines(post):
            g = good_of(name)
            if not g:
                if name:
                    notes["names_not_held"][name[:40]] += 1
                continue
            key, kind = g
            measure = key + (f"_{area}" if area else "")
            if missing and value is None:
                measure += "_missing"
                unit, basis = None, "the list marks the good missing"
            else:
                unit, basis = unit_of(name, line, kind, default_kilo=True, after=after)
                if unit is None:
                    notes["units_not_held"][basis] += 1
                    continue
                if by_app:
                    measure += "_by_app"
                if missing:                                  # «قهوة ❌ 90 شيكل (مفقودة)»: a price printed for a missing good
                    notes["units_not_held"]["a price printed beside «missing»"] += 1
                    continue
            k = (day.isoformat(), measure)
            rec = {"stable_id": f"asarsook:{day.isoformat()}:{measure}", "measure": measure, "good": key,
                   "value": value, "text": "missing" if value is None else None, "unit": unit,
                   "date": day.isoformat(), "area": area, "market_printed": market,
                   "name_printed": name, "line_printed": _clean(line)[:120], "basis": basis,
                   "paid_by_app": by_app or None, "post": url, "posted_at": post["date"],
                   "range_printed": list(rng) if rng else None,
                   "location": {"region": "Gaza Strip"},
                   "sources": [{"name": SOURCE_NAME, "url": url}]}
            if k in best:
                if best[k]["value"] != value:
                    others[k].append({"value": value, "post": url})
                continue
            best[k] = rec
    recs = []
    for k, r in best.items():
        if others.get(k):
            r["other_prices_same_day"] = others[k]
        recs.append(r)
    recs.sort(key=lambda r: (r["date"], r["measure"]))
    notes["not_read"] = dict(notes["not_read"])
    notes["names_not_held"] = dict(notes["names_not_held"].most_common(150))
    notes["units_not_held"] = dict(notes["units_not_held"])
    notes["same_day_different_price"] = sum(1 for v in others.values() if v)
    return recs, notes


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    posts = read_posts(Path(argv[argv.index("--posts") + 1]) if "--posts" in argv else POSTS)
    recs, notes = build(posts)
    if len(recs) < MIN_RECORDS:
        print(f"  REFUSED {LABEL}: {len(recs)} prices below the floor of {MIN_RECORDS}; the file on disk stays")
        if not dry:
            fl.event(LABEL, "refused", rows=len(recs), floor=MIN_RECORDS)
        return 1
    days = sorted({r["date"] for r in recs})
    measures = Counter(r["measure"] for r in recs)
    print(f"{len(recs)} prices · {len(measures)} series · {notes['lists_read']} lists · {days[0]} → {days[-1]} · "
          f"missing marks {sum(1 for r in recs if r['value'] is None)} · by app "
          f"{sum(1 for r in recs if r.get('paid_by_app'))} · not read {notes['not_read']}")
    doc = {"metadata": {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": SOURCE_NAME, "source_url": f"https://t.me/s/{CHANNEL}",
        "license": "no licence stated (a public Telegram channel); held for the house",
        "attribution": "Gaza market prices: the Telegram channel «أسعار السوق - غزة» (@asarsook).",
        "goods": {k: {"en": GOOD_EN[k], "ar": GOOD_AR[k]} for k in GOOD_EN},
        "first_day": days[0], "last_day": days[-1], **notes},
        "data": recs}
    if dry:
        print(f"         would write {OUT.relative_to(ROOT)} (dry run, nothing written)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=len(recs), series=len(measures), first=days[0], last=days[-1])
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
