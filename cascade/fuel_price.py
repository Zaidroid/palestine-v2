"""Read the Palestinian fuel price announcement out of a news article.

    from cascade.fuel_price import parse
    a = parse(text, published=date(2026, 8, 31))
    a.verdict            # "prices" | a refusal code
    a.prices             # {"gasoline_95": 8.15, "diesel": 8.39, ...}
    a.effective_from     # date(2026, 9, 1)

WHAT IS BEING READ
The Palestinian General Petroleum Corporation (الهيئة العامة للبترول, Ministry
of Finance) sets the MAXIMUM consumer price of fuel and cooking gas for the West
Bank once a month, usually on the evening of the last day of the month before,
and sometimes revises it mid-month (2026-09-06: petrol 95 cut 8.15 -> 7.65 from
7 September). There is no machine-readable feed. The announcement reaches the
public as news: every outlet reposts the same list within the hour.

So this is a transcription reader, not an extractor of opinion. Everything it
refuses, it refuses because a real article in the corpus would otherwise have
produced a wrong price:

  * an Israeli price story that names "وزارة المالية" (Israel's) and a 95-octane
    price in shekels — 2026-09-03, reposted by two West Bank channels;
  * a rumour DENIAL that quotes the rumoured number ("ارتفاع سعر السولار إلى
    9.56 شيكل غير صحيح") — 2026-08-30;
  * a mid-month revision story that restates the OLD prices in a
    "وكانت ... في حينه" sentence — 2026-09-06;
  * "ليصبح X بدلاً من Y": Y is the old price, and it is a number followed by
    شيكل like any other.

Every product is read to a price only when its clause makes the pairing
unambiguous; an ambiguous clause is counted and skipped, never guessed. One
article is one transcription: nothing here is believed until two independent
outlets agree (see migration 071, fuel_price_believed).

Scope: the West Bank. The Corporation's list is for "المحافظات الشمالية"; Gaza
has no official consumer price this reader could honestly report.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

VERSION = "fuel_price@5"

LITRE_PRODUCTS = ("gasoline_95", "gasoline_98", "diesel", "kerosene")
LPG_SIZES = {"2.5": "lpg_2_5kg", "5": "lpg_5kg", "12": "lpg_12kg", "48": "lpg_48kg"}

NAMES = {
    "gasoline_95": ("بنزين 95", "Petrol 95"),
    "gasoline_98": ("بنزين 98", "Petrol 98"),
    "diesel": ("سولار", "Diesel"),
    "kerosene": ("كاز", "Kerosene"),
    "lpg_2_5kg": ("أسطوانة غاز 2.5 كغم", "Cooking gas cylinder 2.5 kg"),
    "lpg_5kg": ("أسطوانة غاز 5 كغم", "Cooking gas cylinder 5 kg"),
    "lpg_12kg": ("أسطوانة غاز 12 كغم", "Cooking gas cylinder 12 kg"),
    "lpg_48kg": ("أسطوانة غاز 48 كغم", "Cooking gas cylinder 48 kg"),
}
UNITS = {p: "ILS/L" for p in LITRE_PRODUCTS} | {p: "ILS/cylinder" for p in LPG_SIZES.values()}

# Plausibility, not truth: wide enough for a decade of real prices (2016 petrol
# 95 was ~5.9, 2026-08 ~8), narrow enough that a year, a cylinder size or a
# percentage read as a price is refused.
# A list with no stated start date is dated to the 1st of its month only when
# it was published between the 24th of the month before and the 3rd.
PERIOD_START_BEFORE, PERIOD_START_AFTER = 7, 2

BOUNDS = {
    "gasoline_95": (3, 15), "gasoline_98": (3, 16), "diesel": (3, 15),
    "kerosene": (3, 15), "lpg_2_5kg": (8, 40), "lpg_5kg": (15, 80),
    "lpg_12kg": (40, 180), "lpg_48kg": (150, 700),
}

# ── months ───────────────────────────────────────────────────────────────────
# Levantine and Gregorian names, both appear, often together ("أيلول/سبتمبر").
# Multi-word names first so "كانون الثاني" is not read as a bare "كانون".
_MONTHS = [
    ("كانون الثاني", 1), ("كانون الأول", 12), ("كانون الاول", 12),
    ("تشرين الأول", 10), ("تشرين الاول", 10), ("تشرين الثاني", 11),
    ("شباط", 2), ("آذار", 3), ("اذار", 3), ("أذار", 3), ("نيسان", 4),
    ("أيار", 5), ("ايار", 5), ("حزيران", 6), ("تموز", 7), ("آب", 8), ("اب", 8),
    ("أيلول", 9), ("ايلول", 9),
    ("يناير", 1), ("فبراير", 2), ("مارس", 3), ("أبريل", 4), ("ابريل", 4),
    ("إبريل", 4), ("مايو", 5), ("يونيو", 6), ("يونيه", 6), ("يوليو", 7),
    ("يوليه", 7), ("أغسطس", 8), ("اغسطس", 8), ("سبتمبر", 9), ("أكتوبر", 10),
    ("اكتوبر", 10), ("نوفمبر", 11), ("ديسمبر", 12),
]
_MONTH_ALT = "|".join(re.escape(n) for n, _ in sorted(_MONTHS, key=lambda m: -len(m[0])))
_MONTH_NUM = {n: m for n, m in _MONTHS}
_A = r"[\u0600-\u06FF]"                      # an Arabic letter, for word edges

# ── text normalisation ───────────────────────────────────────────────────────
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")
_TASHKEEL = re.compile(r"[\u064B-\u0652\u0640]")     # harakat + tatweel


# A DECIMAL COMMA IS A DECIMAL POINT. "البنزين 95 بسعر 8,15 شيكلا والسولار
# 8,39 شيكلا" (or with the Arabic comma, "8،15") was split at the comma as a
# clause boundary before _PRICE ever saw the number, and the tail
# "15 شيكلا والسولار 8" read as diesel = 15.0 — inside diesel's bounds, one
# product and one number, so recorded as a STATED reading. A comma between a
# 1-3 digit number with no decimal of its own and one or two digits that end
# the number is a decimal separator; "1,230" (three digits after) and
# "8.15،9.21" (a list of two prices) are left alone.
_DECIMAL_COMMA = re.compile(r"(?<![\d.,،])(\d{1,3})[,،](\d{1,2})(?![\d.,،])")


def normalise(text: str) -> str:
    t = _TASHKEEL.sub("", text.translate(_DIGITS))
    t = t.replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    t = _DECIMAL_COMMA.sub(r"\1.\2", t)
    return re.sub(r"[ \t]+", " ", t)


# ── gates ────────────────────────────────────────────────────────────────────
# The Palestinian authority, named. Israel's finance ministry is also
# "وزارة المالية", so the bare phrase is NOT enough — measured 2026-09-03.
ATTRIBUTION = re.compile(
    r"الهيئة العامة للبترول|هيئة البترول|وزارة المالية والتخطيط|المالية الفلسطينية")
# A sentence that talks about a price without announcing it.
#
# كان AND سابق ARE WORDS, NOT SUBSTRINGS. "كان " matched inside مكان, السكان
# and بالإمكان, and "سابق" inside مسابقة, so "سعر لتر بنزين 95 في مكان البيع
# 8.15 شيكل" threw the whole list away (HANDOFF §4: short Arabic substrings
# inside common words). They are anchored to word edges, prefixes allowed
# ("وكانت ... في حينه", "السعر السابق") because those are the measured forms.
_NOT_AN_ANNOUNCEMENT = re.compile(
    r"غير صحيح|لا صحة|شائع|إشاع|اشاع|مفبرك|يتم تداول|لم تصدر|أن تصدر|ان تصدر"
    rf"|(?<!{_A})[وف]?كان(?:ت|وا)?(?!{_A})|في حينه|(?<!{_A})(?:[وب]?ال|[وب])?سابق"
    r"|الأعلى منذ|الأدنى منذ|منذ \d+ ?عام"
    r"|إسرائيل|اسرائيل|الإسرائيلي|الاسرائيلي|أغورة|اغورة|الخدمة الذاتية")
# THE CORPORATION'S OWN EXPLANATION OF ITS PRICE IS NOT AN ISRAELI PRICE.
# raya.ps's April list (2026-03-31) carries all four litre prices in one
# sentence that begins "... واعتماد الأسعار على سعر الأسواق الإسرائيلية كونها
# المزوّد الرئيسي ..., فإن سعر لتر البنزين 95 ... سيباع بـ7.90 شيقلا" — and the
# sentence was skipped whole for "الإسرائيلية", so the reader kept only the
# cylinder. Only that dependence phrase is excused, and only for the Israel
# test; an Israeli price stated anywhere else in the sentence still skips it.
_PRICED_ON_ISRAELI_MARKET = re.compile(
    r"(?:اعتماد|ارتباط|مرتبط\S*|ترتبط|يرتبط|تعتمد|يعتمد)\s+(?:ال[أا]سعار\s+)?"
    r"(?:على|ب)\s*(?:سعر\s+|[أا]سعار\s+)?(?:ال)?(?:[أا]سواق|سوق)\s+(?:ال)?[إا]سرائيلي[ةه]?")
# "ليصبح 7.65 بدلاً من 8.15" — the second number is the OLD price. So is a
# change "بمقدار 20 أغورة" / "بقيمة شيكل": a delta is not a price.
_OLD_OR_DELTA = re.compile(
    r"(?:بدلا|بدل|عوضا عن|عوضاً عن|مقارنة ب\S*|بمقدار|بقيمة)\s*(?:من\s*)?"
    r"(?:\d+(?:[.,]\d+)?)\s*(?:شي[كق]ل\S*|شواكل|أغور\S*)?")

_PRICE = re.compile(r"(?<![\d.])(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:شي[كق]ل|شواكل|ش\.ج)")
_PRODUCTS = [
    ("gasoline_95", re.compile(r"بنزين\s*(?:ال)?(?:أوكتان|اوكتان|أوكتين)?\s*\(?\s*95(?!\d)")),
    ("gasoline_98", re.compile(r"بنزين\s*(?:ال)?(?:أوكتان|اوكتان|أوكتين)?\s*\(?\s*98(?!\d)")),
    ("diesel", re.compile(rf"(?<!{_A})(?:و|ل|ب)?(?:ال)?(?:سولار|ديزل)(?!{_A})")),
    ("kerosene", re.compile(rf"(?<!{_A})(?:و|ل|ب)?(?:ال)?كاز(?!{_A})")),
]
_KG = r"(?:كغم|كلغم|كغ|كيلو\s*غرام\S*|كيلوغرام\S*|كيلو)"
_LPG = re.compile(r"(?:أ|ا|إ)سطوان(?:ة|ات)[^\d،,\n]{0,25}?(\d+(?:\.\d+)?)\s*" + _KG)
# A bare size, read as a cylinder ONLY after a cylinder was named earlier in
# the same sentence (measured: khaberni 2026-08-01 lists four sizes after one
# "أسطوانة"). Without the earlier mention "12 كغم" could be anything.
_BARE_KG = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*" + _KG)


@dataclass
class Announcement:
    verdict: str                                   # "prices" or a refusal code
    prices: dict[str, float] = field(default_factory=dict)
    period_month: date | None = None               # the month the list governs
    effective_from: date | None = None
    effective_basis: str | None = None             # "explicit" | "period_start"
    detail: list[str] = field(default_factory=list)
    # product -> {"clause": the text read, "inferred": whether the pairing of
    # product and number was inferred rather than stated one-to-one}
    evidence: dict[str, dict] = field(default_factory=dict)
    version: str = VERSION


# ── dates ────────────────────────────────────────────────────────────────────

def _year_for(month: int, published: date | None, stated: str | None) -> int | None:
    if stated:
        return int(stated)
    if published is None:
        return None
    y = published.year
    if month < published.month - 6:        # a January list published in December
        y += 1
    elif month > published.month + 6:      # a December list published in January
        y -= 1
    return y


_PERIOD = re.compile(
    rf"(?:لشهر|خلال شهر|عن شهر|لشهر\s*/)\s*(?:(\d{{1,2}})\s*)?(?:({_MONTH_ALT}))?"
    rf"(?:\s*[/\\-]\s*(?:{_MONTH_ALT}))?\s*(?:(\d{{4}}))?")


def period_month(text: str, published: date | None) -> date | None:
    for m in _PERIOD.finditer(text):
        num, name, year = m.group(1), m.group(2), m.group(3)
        month = _MONTH_NUM.get(name) if name else (int(num) if num else None)
        if name and num and int(num) != _MONTH_NUM[name]:
            continue                        # "لشهر 9 أيار" — refuse to pick one
        if not month or not 1 <= month <= 12:
            continue
        y = _year_for(month, published, year)
        if y:
            return date(y, month, 1)
    return None


_EFFECTIVE_ANCHOR = re.compile(
    r"(?:اعتبارا|اعتبار|ابتداء|بدءا|بدء|بداية|يعمل بها|يُعمل بها|حيز النفاذ|حيز التنفيذ)"
    r"[^.\n]{0,25}?من\s+")
_DMY = re.compile(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})")
_D_MONTH = re.compile(
    rf"(?<![\d{_A[1:-1]}])(?:ال)?(\d{{1,2}}|أول|اول)\s*(?:من\s+)?(?:شهر\s+)?({_MONTH_ALT})"
    rf"(?:\s*[/\\-]\s*(?:{_MONTH_ALT}))?(?:\s*(?:لعام\s*)?(\d{{4}}))?")
_D_THIS_MONTH = re.compile(r"(?<!\d)(\d{1,2})\s*(?:من\s*)?(?:ال)?شهر\s*(?:ال)?(?:جاري|حالي)")
_EFFECTIVE_REACH = 50
# What may sit between the two days of a midnight boundary ("31 آب/1 أيلول",
# "31 آب - 1 أيلول", "31 آب و 1 أيلول"). Always matches, possibly empty.
_BOUNDARY = re.compile(r"\s*(?:[/\\-]|و)?\s*")


def _d_month_date(m: re.Match, published: date | None) -> date | None:
    day = 1 if m.group(1) in ("أول", "اول") else int(m.group(1))
    month = _MONTH_NUM[m.group(2)]
    y = _year_for(month, published, m.group(3))
    if not y:
        return None
    try:
        return date(y, month, day)
    except ValueError:
        return None


def effective_from(text: str, published: date | None) -> date | None:
    for anchor in _EFFECTIVE_ANCHOR.finditer(text):
        tail = text[anchor.end(): anchor.end() + _EFFECTIVE_REACH]
        m = _DMY.search(tail)
        if m:
            d, mo, y = map(int, m.groups())
            try:
                return date(y, mo, d)
            except ValueError:
                continue
        m = _D_MONTH.search(tail)
        if m:
            got = _d_month_date(m, published)
            # "منتصف ليلة 31 آب/1 أيلول" names the midnight BETWEEN two days,
            # and the list governs the second. Reading the first dated every
            # list announced that way a day early — and an October list
            # published on 30 Sep as "30 أيلول/1 تشرين الأول" would be filed
            # under September, leaving October `awaiting_list`. Only a pair
            # of CONSECUTIVE days is a midnight boundary; "1 أيلول - 30
            # أيلول" is a range and keeps its start.
            nxt = _D_MONTH.match(tail, m.end() + len(_BOUNDARY.match(tail, m.end()).group(0)))
            if got and nxt:
                later = _d_month_date(nxt, published)
                if later and later - got == timedelta(days=1):
                    got = later
            if got:
                return got
            continue
        m = _D_THIS_MONTH.search(tail)
        if m and published:
            try:
                return published.replace(day=int(m.group(1)))
            except ValueError:
                continue
    return None


# ── prices ───────────────────────────────────────────────────────────────────

def _sentences(text: str) -> list[str]:
    # A full stop is a sentence end only when it is not a decimal point.
    return [s for s in re.split(r"(?<!\d)\.(?!\d)|\.(?=\s)|[\n؟!]+", text) if s.strip()]


def _clauses(sentence: str) -> list[str]:
    return [c for c in re.split(r"[،,؛;*•]|\s-\s|:\s(?=\D)", sentence) if c.strip()]


def _lpg_size(raw: str) -> str | None:
    size = raw.rstrip("0").rstrip(".") if "." in raw else raw
    return LPG_SIZES.get(size)


_INFERRED_LAST: set[str] = set()      # products _products_in read from carried context


def _products_in(clause: str, cylinder_context: bool = False) -> list[tuple[int, str]]:
    _INFERRED_LAST.clear()
    found = []
    for name, rx in _PRODUCTS:
        for m in rx.finditer(clause):
            found.append((m.start(), name))
    lpg = [(m.start(), _lpg_size(m.group(1))) for m in _LPG.finditer(clause)]
    if not lpg and cylinder_context:
        lpg = [(m.start(), _lpg_size(m.group(1))) for m in _BARE_KG.finditer(clause)]
        found.extend((pos, name) for pos, name in lpg if name)
        _INFERRED_LAST.update(name for _, name in lpg if name)
    else:
        found.extend((pos, name) for pos, name in lpg if name)
    found.sort()
    out, seen = [], set()
    for pos, name in found:                 # "بنزين 95 أوكتان" is one mention
        if name not in seen:
            out.append((pos, name))
            seen.add(name)
    return out


def read_prices(text: str) -> tuple[dict[str, float], list[str], dict[str, dict]]:
    prices: dict[str, float] = {}
    notes: list[str] = []
    evidence: dict[str, dict] = {}
    for sentence in _sentences(text):
        # The old price and the delta come out FIRST: "بمقدار 20 أغورة ليصبح
        # 8.15 شيكل" is a rise announced in agorot, and with the delta still
        # in the sentence its "أغورة" made the negative filter throw away the
        # new price the sentence exists to state.
        sentence = _OLD_OR_DELTA.sub(" ", sentence)
        if _NOT_AN_ANNOUNCEMENT.search(_PRICED_ON_ISRAELI_MARKET.sub(" ", sentence)):
            if _PRICE.search(sentence):
                notes.append(f"sentence skipped (not an announcement): {sentence.strip()[:80]}")
            continue
        cylinder_context = False
        for clause in _clauses(sentence):
            products = _products_in(clause, cylinder_context)
            cylinder_context = cylinder_context or bool(_LPG.search(clause))
            values = [float(m.group(1).replace(",", ".")) for m in _PRICE.finditer(clause)]
            if not values or not products:
                continue
            if len(values) == 1:
                pairs = [(p, values[0]) for _, p in products]
            elif len(values) == len(products):
                pairs = [(p, v) for (_, p), v in zip(products, values)]
            else:
                notes.append(f"ambiguous clause, {len(products)} products / "
                             f"{len(values)} prices: {clause.strip()[:80]}")
                continue
            for product, value in pairs:
                lo, hi = BOUNDS[product]
                if not lo <= value <= hi:
                    notes.append(f"{product} {value} outside {lo}-{hi}")
                    continue
                if product in prices and prices[product] != value:
                    notes.append(f"{product} stated twice: {prices[product]} and {value}")
                    prices[product] = None       # type: ignore[assignment]
                    continue
                if prices.get(product, 0) is not None:
                    prices[product] = value
                    # One product, one number, the product named outright: the
                    # pairing is stated. Anything else — a shared number, a
                    # positional pairing, a cylinder size carried from an
                    # earlier clause — is the reader's inference, and an
                    # inference repeated over copies of one text is one reading.
                    evidence[product] = {
                        "clause": re.sub(r"\s+", " ", clause).strip(),
                        "inferred": (len(products) > 1 or len(values) > 1
                                     or product in _INFERRED_LAST),
                    }
    conflicted = [p for p, v in prices.items() if v is None]
    for p in conflicted:
        del prices[p]
        evidence.pop(p, None)
    return prices, notes, evidence


# ── the whole article ────────────────────────────────────────────────────────

_IMPLIED_OFFICIAL = re.compile(r"رسمي")
_IMPLIED_MIN_LITRE_PRODUCTS = 3


def parse(text: str, published: date | None = None) -> Announcement:
    t = normalise(text)
    named = bool(ATTRIBUTION.search(t))
    if not named and not _IMPLIED_OFFICIAL.search(t):
        return Announcement("no_attribution",
                            detail=["names neither the Petroleum Corporation nor the "
                                    "Palestinian finance ministry"])
    prices, notes, evidence = read_prices(t)
    if not prices:
        return Announcement("no_prices", detail=notes)
    period = period_month(t, published)
    if not named:
        litre = sum(1 for p in LITRE_PRODUCTS if p in prices)
        if litre < _IMPLIED_MIN_LITRE_PRODUCTS or period is None:
            return Announcement("no_attribution", detail=notes + [
                f"says 'official' without naming the authority, and reads only "
                f"{litre} litre products / period {period} — not the full-list shape"])
        notes = notes + ["attribution implied ('رسمي' + full list), not named"]
    eff = effective_from(t, published)
    basis = "explicit" if eff else None
    if eff is None and period is not None:
        if published is not None and not (
                period - timedelta(days=PERIOD_START_BEFORE) <= published
                <= period + timedelta(days=PERIOD_START_AFTER)):
            return Announcement("no_effective_date", prices=prices, period_month=period,
                                detail=notes + [f"no stated start date, and published "
                                                f"{published} is not at the start of "
                                                f"{period:%Y-%m}; a mid-month revision "
                                                f"must not be dated to the 1st"])
        eff, basis = period, "period_start"
    if eff is None:
        return Announcement("no_period", prices=prices, detail=notes)
    if period is None:
        period = eff.replace(day=1)
    if published is not None:
        # An announcement governs the month it is published for, give or take
        # the end-of-month publication. Anything further is a history piece.
        if not published - timedelta(days=45) <= eff <= published + timedelta(days=40):
            return Announcement("out_of_window", prices=prices, period_month=period,
                                effective_from=eff, effective_basis=basis,
                                detail=notes + [f"effective {eff} vs published {published}"])
    if abs((eff.year * 12 + eff.month) - (period.year * 12 + period.month)) > 1:
        return Announcement("period_mismatch", prices=prices, period_month=period,
                            effective_from=eff, effective_basis=basis,
                            detail=notes + [f"effective {eff} vs period {period}"])
    return Announcement("prices", prices=prices, period_month=period,
                        effective_from=eff, effective_basis=basis, detail=notes,
                        evidence=evidence)
