"""Parse the Gaza Ministry of Health daily statistical report.

    from cascade.moh_gaza import parse
    rep = parse(message_text)

The Ministry posts one report a day in a stable shape:

    🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى...
    ⭕ ... خلال الـ 24 ساعة الماضية.
    * عدد الشهداء 7 شهداء
    * (6 شهداء جديد + 1 شهيد متأثر بإصابته)
    • عدد الإصابات: 23 إصابة.

    🔴 منذ وقف إطلاق النار (11 أكتوبر):
    • إجمالي عدد الشهداء: 1,230
    • إجمالي عدد الإصابات: 4،076
    • إجمالي حالات الانتشال: 804

    🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
    • العدد التراكمي للشهداء: 73,356
    • العدد التراكمي للإصابات: 174,185

THREE TIERS THAT MUST NOT BE CONFLATED
Daily, since-ceasefire, and since-October-2023 all use the words شهداء and
إصابات. A parser that matches on the words alone will read 73,356 as today's
figure — off by four orders of magnitude, in the direction that gets quoted.
So the tier is decided by the SECTION HEADER, and a number outside a recognised
section is not emitted at all.

WHY THESE ARE `observation` AND NOT `state_observation`
They are measurements, not the state of a place. `state_observation` answers
"what is true at this place now" and decays; a death toll does not decay and is
not about a place being open or shut. `observation` is the databank's table —
dataset, indicator, value, time — and a daily count is exactly its shape. Same
decision as the tier-1 rollup in migration 031, for the same reason: written
where tier 2 will look for it.

NUMBERS ARRIVE IN THREE WRITING SYSTEMS
Arabic-Indic digits (٧٣٣٥٦), Latin digits with a Latin thousands comma
(73,356), and Latin digits with an ARABIC thousands comma (4،076 — U+060C, not
U+002C). The third is the one that bites: it looks like a comma, is not one,
and `int("4،076".replace(",", ""))` raises while `float()` of a partial match
silently yields 4.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
# U+060C ARABIC COMMA and U+066C ARABIC THOUSANDS SEPARATOR both appear.
_SEPS = dict.fromkeys([0x002C, 0x060C, 0x066C, 0x2009, 0x00A0])
_BIDI = dict.fromkeys([0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C,
                       0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069])

# [إا]: February 2024 – January 2025 the Ministry wrote "الاحصائي" without the
# hamza, and 330 reports of that era were not reports to this regex (found
# 2026-10-11 when the archive was read for the first time).
IS_REPORT = re.compile(r"التقرير\s+ال[إا]حصائي\s+(?:اليوم|خلال)")   # "خلال الـ 48 ساعة": December 2025's heading

# Section headers decide the tier. Order matters: the most specific first, since
# the cumulative header also contains the word "العدوان".
SECTIONS = (
    # NOT "العدد التراكمي" — that phrase opens every cumulative DATA line
    # ("العدد التراكمي للشهداء: 73,356"), so using it as a header pattern made
    # each data line look like a section switch and the largest figures in the
    # report were silently never emitted.
    ("cumulative", re.compile(r"الإحصائي[ةه]\s+التراكمي[ةه]|الحصيل[ةه]\s+التراكمي[ةه]|منذ\s+بداي[ةه]\s+العدوان")),
    ("since_ceasefire", re.compile(r"منذ\s+وقف\s+إطلاق\s+النار")),
    # A tier of its own so its totals never land under the previous one; not
    # in INDICATORS, so never emitted (audit F176).
    ("since_resumption", re.compile(r"منذ\s+استئناف")),
    ("daily", re.compile(r"خلال\s+ال.?\s*24\s*ساع[ةه]|الساعات\s+ال.?\s*24")),
)

# A marker followed by a NUMBER or a dash is a data line, not a header: since
# 2026-08-10 the 24-hour block is written "▪️ 6 إصابات" / "- 5 شهداء", and the
# bullet made every such line look like a header (the daily series stopped on
# 08-09; found by organ C's control run, 2026-09-25).
# `(?![markers])` stops the regex backtracking INTO the marker run: ▪️ is two
# code points (U+25AA + U+FE0F), and giving back the variation selector let it
# pose as the header's first character.
_HEADER_SHAPE = re.compile(r"^\s*[🔴⭕🔻▪️◾️]+(?![🔴⭕🔻▪️◾️])\s*(?![\d\-–])\S")

# NUMBER-FIRST, the 24-hour block's shape since 2026-08-10 ("5 شهداء، بينهم
# شهيد متأثر بجراحه." / "- 18 إصابة"). Anchored at the start of the line (after
# a bullet or dash) and used ONLY in the daily tier, so a number inside a
# sentence, or a total in another tier, is never taken for the day's count.
DAILY_NUMBER_FIRST = (
    # …or right after "و" at a clause boundary: January–April 2026 wrote both
    # counts on one line ("• 2 شهداء (…) و 1 إصابة.").
    ("deaths",   re.compile(r"(?:^[\s\-–•*▪️◾️]*|\sو\s?)(\d+)\s+(?:شهداء|شهيد[اًا]?|شهيدًا)(?:\s|،|\.|\(|$)")),
    ("injuries", re.compile(r"(?:^[\s\-–•*▪️◾️]*|\sو\s?)(\d+)\s+(?:إصابات|إصابة|اصابات|اصابة|جرحى|جريح)(?:\s|،|\.|\(|$)")),
)

MEASURES = (
    ("deaths",     re.compile(r"(?:العدد\s+التراكمي\s+ل|إجمالي\s+عدد\s+ال|عدد\s+ال)?شهداء\s*:?\s*([\d]+)")),
    ("injuries",   re.compile(r"(?:العدد\s+التراكمي\s+ل|إجمالي\s+عدد\s+ال|عدد\s+ال)?إصابات\s*:?\s*([\d]+)")),
    ("recovered",  re.compile(r"(?:حالات|[إا]جمالي)\s+الانتشال\s*:?\s*([\d]+)")),   # "إجمالي الانتشال" Oct 2025 – Jan 2026
)


@dataclass
class MohReport:
    is_report: bool = False
    tiers: dict = field(default_factory=dict)   # tier -> {measure: int}
    rejected: list = field(default_factory=list)


# A PERIOD is also used as a thousands separator, and it is the dangerous one.
# The Ministry wrote "72.292" on 2026-04-05 and 06; commas were stripped and the
# period was not, so 72,292 parsed as 72 — wrong by a factor of a thousand, and
# in the direction that makes a catastrophe look like a quiet day. Only periods
# BETWEEN digits are removed, so sentence-ending full stops are untouched. Every
# figure in this report is an integer count, so a period between digits is never
# a decimal point.
_THOUSANDS_DOT = re.compile(r"(?<=\d)\.(?=\d)")


def _normalise(text: str) -> str:
    """Fold digits and strip separators and invisible marks."""
    s = (text or "").translate(_BIDI).translate(_AR_DIGITS).translate(_SEPS)
    return _THOUSANDS_DOT.sub("", s)


# ── The archive's shapes (2026-10-11) ────────────────────────────────────────
# Three eras of the same report, read from 837 bulletins February 2024 → today:
#   A  Feb 2024 – Jan 2025   "الاحتلال يرتكب 11 مجزرة … راح ضحيتها 103 شهيد و 145
#                            اصابة خلال ال 24 ساعة" + "ارتفاع حصيلة العدوان الى
#                            28576 شهيد و 68291 اصابة منذ السابع من اكتوبر"
#   B  Jan 2025 – Oct 2025   "وصل مستشفيات قطاع غزة 23 شهيد (منهم 14 شهيد انتشال
#                            و5 شهداء متأثرين بجراحهم و4 شهداء جدد) و 11 اصابة، خلال
#                            72 ساعة الماضية" + the resumption toll "منذ 18 مارس
#                            2025" + from July 2025 the aid-seeker and famine tolls
#   C  Oct 2025 →            sectioned (the shape the tier machinery below reads),
#                            with the 24 h line still written in prose until
#                            April 2026
# In A and B the header and the data share one line, so the tier machinery
# (header → continue) never saw a number. These extractors read a line on its
# own terms and never overwrite what the tier machinery already found.
_D = r"(?:شهداء|شهيد(?:ًا|اً|ا|ة)?)"
_I = r"(?:[إا]صاب(?:ات|ة|ه)|جرحى|جريح(?:ًا|اً|ا)?)"
_NUM_D = re.compile(r"(\d+)\s*" + _D + r"(?!\s*(?:[إا]نتشال|جرى|تم|متأثر|جدد|جديد|نتيج[ةه]|المساعدات|لقمة))")
_NUM_I = re.compile(r"(\d+)\s*" + _I)
_HOURS = re.compile(r"خلال[\s*]*\(?[\s*]*(?:ال[ـ]?)?[\s*]*\(?\s*(\d+)\s*ساع")  # "خلال 72 ساعة", "خلال الـ24 ساعة", "خلال الـ *(48 ساعة", "خلال *(الـ 24 ساعة"
_ARRIVED = re.compile(r"وصل(?:ت|وا)?\s+(?:منها\s+)?(?:[إا]لى\s+)?(?:لل|ال)?مستشفيات|وصول\s+(?:[إا]لى\s+)?المستشفيات")
# A block whose LENGTH the bulletin does not state (2026-10-12, the last three
# bulletins of the archive with no readable day line): "خلال ايام عيد الفطر
# وحتى الساعة:" (23 March 2026, the days of Eid) and "بلغ إجمالي ما وصل إلى
# مستشفيات قطاع غزة حتى هذه اللحظة." (4 June 2026, no window at all). Neither
# says 24 hours, so neither is a day: both are read as the `period` tier with
# no `hours` beside them, which is exactly what the bulletin says.
_UNSTATED_WINDOW = re.compile(r"خلال\s+[أا]يام|حتى\s+(?:هذه\s+اللحظ[ةه]|الساع[ةه])")
_COMMITTEE = re.compile(r"(?:[إا]ضاف[ةه])\s+(?:عدد\s+)?(\d+)\s*" + _D)      # "تم اضافة عدد 499 شهيد … اللجنة القضائية"
# Counts written as WORDS (March 2026: "شهيدان، أحدهما شهيد انتشال، وإصابتان.")
_WORDS = (("deaths", re.compile(r"شهيدان|شهيدين"), 2), ("deaths", re.compile(r"شهيد(?:ًا|اً|ا)?\s+واحد"), 1),
          ("injuries", re.compile(r"[إا]صابتان|[إا]صابتين"), 2), ("injuries", re.compile(r"[إا]صاب[ةه]\s+واحد[ةه]"), 1),
          ("recovered", re.compile(r"[أا]حدهما\s+شهيد\s+[إا]نتشال"), 1), ("recovered", re.compile(r"كلاهما\s+(?:شهيد\s+)?[إا]نتشال"), 2))
_COUNT_LINE = re.compile(r"عدد\s+ال(?:شهداء|[إا]صابات)|^[\s\-–•*▪️◾️⭕]*\d+\s*(?:شه|[إا]صاب)")
_MASSACRES = re.compile(r"(\d+)\s*(?:مجزرة|مجازر)")
_RECOVERED = re.compile(r"(\d+)\s*" + _D + r"\s*(?:[إا]نتشال|جرى\s+انتشالهم|تم\s+انتشالهم)")
_SUCCUMBED = re.compile(r"(\d+)\s*" + _D + r"\s*مت[أا]ثر")
# "جدد" from 28 October 2025; the eight bulletins of 16-27 October, the first
# after the ceasefire, write the same thing as "4 شهداء نتيجة استهداف مباشر من
# الاحتلال" beside the recovered and the died-of-wounds, and were read without
# their newly killed (found 2026-10-12 through gate G4.8).
_NEW = re.compile(r"(\d+)\s*" + _D + r"\s*(?:جدد|جديد|نتيج[ةه]\s+استهداف\s+مباشر)")
_CUM_LINE = re.compile(r"(?:ارتفاع|ارتفعت)\s+حصيل[ةه]\s+العدوان")
_RESUMPTION_LINE = re.compile(r"منذ\s+18\s+مارس\s+2025")
_AID_LINE = re.compile(r"شهداء\s+المساعدات|لقم[ةه]\s+العيش")
_FAMINE_LINE = re.compile(r"المجاع[ةه]")
_FAMINE_DAILY = re.compile(r"(\d+)\s*حال(?:ة|ات)\s+وفا[ةه]")
# the running total, written "إلى 188 شهيدًا" (Aug 2025) or "ليصبح العدد الإجمالي … 133 حالة وفاة" (Jul 2025)
_FAMINE_TOTAL = re.compile(r"(?:الإجمالي|[إا]جمالي|[إا]لى)\D{0,80}?(\d+)\s*(?:حال(?:ة|ات)\s+وفا[ةه]|" + _D + ")")
_CHILD = re.compile(r"(?:(\d+)\s*|\b)(?:طفل(?:ًا|اً|ا)?|[أا]طفال)")
_CUM_TOTAL = re.compile(r"(?:[إا]لى|الى)\s+(\d+)\s*" + _D)


def _child_count(line: str) -> int | None:
    m = _CHILD.search(line)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 1      # "من بينهم طفل" = one child


def _era_lines(lines: list[str], r: MohReport) -> None:
    def put(tier: str, measure: str, value):
        if value is not None:
            r.tiers.setdefault(tier, {}).setdefault(measure, int(value))

    def window_counts(tier: str, line: str) -> None:
        if _ARRIVED.search(line) or _COUNT_LINE.search(line) or "ضحيتها" in line:
            d = _NUM_D.search(line)
            put(tier, "deaths", d and d.group(1))
        i = _NUM_I.search(line)
        if i and ("وصل" in line or "إصاب" in line or "اصاب" in line or "ضحيتها" in line):
            put(tier, "injuries", i.group(1))
        m = _MASSACRES.search(line)
        put(tier, "massacres", m and m.group(1))
        for measure, pat in (("recovered", _RECOVERED), ("succumbed", _SUCCUMBED), ("new", _NEW)):
            m = pat.search(line)
            put(tier, measure, m and m.group(1))
        # "4 شهداء جدد" with no other death figure: the day's dead are all new
        if "deaths" not in r.tiers.get(tier, {}) and _NEW.search(line):
            put(tier, "deaths", _NEW.search(line).group(1))
        if not re.search(r"\d", line):
            for measure, pat, n in _WORDS:
                if pat.search(line):
                    put(tier, measure, n)

    # December 2025's shape puts the hours in the HEADING ("التقرير الإحصائي خلال
    # الـ 48 ساعة") or on a line of its own ("بلغ إجمالي ما وصل … خلال الـ 48 ساعة
    # الماضية.") and the counts on the lines below; the window is remembered
    # until a line that is plainly a total or the next section heading.
    window: str | None = None
    for line in lines:
        if not line.strip():
            continue
        # the totals and the special tolls first, so a window never eats them
        if _AID_LINE.search(line):
            cum = _CUM_TOTAL.search(line)
            if cum or "إجمالي" in line or "ليرتفع" in line:
                i = _NUM_I.search(line[cum.end():] if cum else line)
                put("aid_seekers", "deaths", cum and cum.group(1))
                put("aid_seekers", "injuries", i and i.group(1))
            elif _HOURS.search(line):
                d, i = _NUM_D.search(line), _NUM_I.search(line)
                put("aid_seekers_daily", "deaths", d and d.group(1))
                put("aid_seekers_daily", "injuries", i and i.group(1))
            continue
        if _FAMINE_LINE.search(line):
            cum = _FAMINE_TOTAL.search(line)
            head = line[:cum.start()] if cum else line      # the day's part, before the running total
            daily = _FAMINE_DAILY.search(head)
            if daily and _HOURS.search(head):
                put("famine_daily", "deaths", daily.group(1))
                put("famine_daily", "children", _child_count(head[daily.end():]))
            if cum:
                put("famine", "deaths", cum.group(1))
                put("famine", "children", _child_count(line[cum.end():]))
            continue
        if _CUM_LINE.search(line):
            d, i = _NUM_D.search(line), _NUM_I.search(line)
            put("cumulative", "deaths", d and d.group(1))
            put("cumulative", "injuries", i and i.group(1))
            window = None
            continue
        if _RESUMPTION_LINE.search(line):
            d, i = _NUM_D.search(line), _NUM_I.search(line)
            put("since_resumption", "deaths", d and d.group(1))
            put("since_resumption", "injuries", i and i.group(1))
            window = None
            continue
        # "اللجنة القضائية" until December 2025; "لجنة اعتماد الشهداء" since
        # (10 October 2026: 106 added). The definite article is not the rule.
        if "لجنة" in line and _COMMITTEE.search(line):
            put("daily" if r.tiers.get("daily") else "period" if r.tiers.get("period") else "daily",
                "committee", _COMMITTEE.search(line).group(1))
            continue
        h = _HOURS.search(line)
        if h and (_ARRIVED.search(line) or "ضحيتها" in line or "إجمالي ما وصل" in line
                  or IS_REPORT.search(line)):
            hours = int(h.group(1))
            tier = "daily" if hours == 24 else "period"
            rest = line[:h.start()] + line[h.end():]
            if tier == "period":
                put(tier, "hours", hours)
            if re.search(r"\d", rest) and not IS_REPORT.search(line):
                window_counts(tier, line)               # one-line shape (2024, 2025)
                window = None
            else:
                window = tier                           # heading; the counts follow
            continue
        if (not h and _ARRIVED.search(line) and "إجمالي ما وصل" in line
                and _UNSTATED_WINDOW.search(line) and not re.search(r"\d", line)):
            window = window or "period"                 # the counts follow; no hours are given
            continue
        if window:
            if (line.lstrip().startswith(("🔴", "⬅")) or ("منذ" in line and line.rstrip().endswith(":"))
                    or "حصيلة" in line or ("إجمالي" in line and "وصل" not in line)):
                window = None
                continue
            window_counts(window, line)
            continue


def parse(text: str) -> MohReport:
    r = MohReport()
    if not text or not IS_REPORT.search(_normalise(text)):
        return r
    r.is_report = True

    # A label can end in a colon with its number on the NEXT line
    # ("العدد التراكمي للإصابات:\n174,185"). Join those before matching, or
    # the biggest number in the report is dropped for looking like prose.
    lines: list[str] = []
    for raw in _normalise(text).splitlines():
        s = raw.strip()
        if lines and lines[-1].rstrip().endswith(":") and re.fullmatch(r"[\d]+", s):
            lines[-1] = lines[-1].rstrip() + " " + s
        # ...and a sentence can be cut after its number: "61 شهيد و 231" /
        # "اصابة خلال الـ 24 ساعة الماضية." (11 October 2024). The first half
        # had the dead and no window, the second the window and no count.
        elif lines and re.search(r"\d\s*$", lines[-1]) and re.match(_I + r"|" + _D, s):
            lines[-1] = lines[-1].rstrip() + " " + s
        else:
            lines.append(s)

    # The archive's one-line shapes are read FIRST (2026-10-11): on 2024-06-09
    # the tier machinery, reading the daily block line by line, took the
    # Nuseirat massacre's "274 شهيد و 698 اصابة" for the day's count while the
    # day's own line ("283 شهيد و 814 اصابة خلال ال 24 ساعة") had been skipped as
    # a header. setdefault below keeps whatever was read here.
    _era_lines(lines, r)

    current: str | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # A header line switches tier. Checked BEFORE measures, because the
        # header itself can contain a year ("7 أكتوبر 2023") that would
        # otherwise be scraped as a count.
        matched_header = False
        for tier, pat in SECTIONS:
            if pat.search(line):
                current, matched_header = tier, True
                break
        if matched_header:
            continue
        # A line SHAPED like a header that matched no tier (starts with the
        # section marker, or says "منذ …" and ends with ':') switches to no
        # tier at all: its totals were filed under the previous tier — the
        # 72,274-in-one-day class (audit F176).
        if _HEADER_SHAPE.match(line) or ("منذ" in line and line.rstrip().endswith(":")):
            current = None
            r.rejected.append(line)
            continue
        # A total written in prose inside the day's block (2025: "ارتفعت حصيلة
        # العدوان … و144,477 إصابة" right under the 24 h line) is its own tier,
        # read by _era_lines; left here it became the day's injuries (F176 again).
        if (_CUM_LINE.search(line) or _RESUMPTION_LINE.search(line)
                or _AID_LINE.search(line) or _FAMINE_LINE.search(line)):
            current = None
            continue
        if current is None:
            continue

        pats = list(MEASURES)
        if current == "daily":
            pats += list(DAILY_NUMBER_FIRST)
        for measure, pat in pats:
            m = pat.search(line)
            if not m:
                continue
            try:
                val = int(m.group(1))
            except ValueError:                          # noqa: PERF203
                r.rejected.append(line)
                continue
            # Never overwrite: the daily section states deaths twice, once as a
            # total and once broken into new/died-of-wounds. The first is the
            # total and the parenthetical breakdown must not replace it.
            r.tiers.setdefault(current, {}).setdefault(measure, val)
    _sanity(r)
    return r


# A figure the Ministry itself mistyped ("173,0128" on 2026-06-07, read as
# 1,730,128) or that the parser took from the wrong line is refused, not served:
# the cumulative injured have never exceeded 2.5 × the cumulative dead, and no
# bulletin has ever reported a thousand dead in a day.
def _sanity(r: MohReport) -> None:
    cum = r.tiers.get("cumulative", {})
    if cum.get("deaths") and cum.get("injuries") and cum["injuries"] > 5 * cum["deaths"]:
        r.rejected.append(f"cumulative injuries {cum['injuries']} > 5 x deaths {cum['deaths']}")
        del cum["injuries"]
    for tier in ("daily", "period"):
        t = r.tiers.get(tier, {})
        if t.get("deaths", 0) > 1000:
            r.rejected.append(f"{tier} deaths {t['deaths']} > 1000"); del t["deaths"]
        if t.get("injuries", 0) > 3000:
            r.rejected.append(f"{tier} injuries {t['injuries']} > 3000"); del t["injuries"]


# The indicator vocabulary, so the databank rows are queryable rather than
# free-text. Tier is part of the name because conflating them is the failure
# this parser exists to avoid.
INDICATORS = {
    ("daily", "deaths"):              "gaza.moh.deaths.daily",
    ("daily", "injuries"):            "gaza.moh.injuries.daily",
    ("since_ceasefire", "deaths"):    "gaza.moh.deaths.since_ceasefire",
    ("since_ceasefire", "injuries"):  "gaza.moh.injuries.since_ceasefire",
    ("since_ceasefire", "recovered"): "gaza.moh.recovered.since_ceasefire",
    ("cumulative", "deaths"):         "gaza.moh.deaths.cumulative",
    ("cumulative", "injuries"):       "gaza.moh.injuries.cumulative",
    # The archive's measures (2026-10-11), named so no tier is ever conflated:
    ("daily", "recovered"):           "gaza.moh.recovered.daily",
    ("daily", "succumbed"):           "gaza.moh.deaths_succumbed.daily",
    ("daily", "new"):                 "gaza.moh.deaths_new.daily",
    ("daily", "massacres"):           "gaza.moh.massacres.daily",
    # A 48/72/96-hour block is NEVER a day (test_a_48_hour_block_is_never_a_day):
    # it is its own tier, with the hours it covered beside it.
    ("period", "deaths"):             "gaza.moh.deaths.period",
    ("period", "injuries"):           "gaza.moh.injuries.period",
    ("period", "hours"):              "gaza.moh.period.hours",
    ("period", "recovered"):          "gaza.moh.recovered.period",
    ("period", "succumbed"):          "gaza.moh.deaths_succumbed.period",
    ("period", "new"):                "gaza.moh.deaths_new.period",
    ("period", "massacres"):          "gaza.moh.massacres.period",
    ("daily", "committee"):           "gaza.moh.deaths_committee.daily",
    ("period", "committee"):          "gaza.moh.deaths_committee.period",
    ("since_resumption", "deaths"):   "gaza.moh.deaths.since_resumption",
    ("since_resumption", "injuries"): "gaza.moh.injuries.since_resumption",
    ("aid_seekers_daily", "deaths"):  "gaza.moh.aid_seekers.deaths.daily",
    ("aid_seekers_daily", "injuries"): "gaza.moh.aid_seekers.injuries.daily",
    ("aid_seekers", "deaths"):        "gaza.moh.aid_seekers.deaths.cumulative",
    ("aid_seekers", "injuries"):      "gaza.moh.aid_seekers.injuries.cumulative",
    ("famine_daily", "deaths"):       "gaza.moh.famine.deaths.daily",
    ("famine_daily", "children"):     "gaza.moh.famine.deaths_children.daily",
    ("famine", "deaths"):             "gaza.moh.famine.deaths.cumulative",
    ("famine", "children"):           "gaza.moh.famine.deaths_children.cumulative",
}
