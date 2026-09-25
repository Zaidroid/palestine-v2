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

IS_REPORT = re.compile(r"التقرير\s+الإحصائي\s+اليوم")

# Section headers decide the tier. Order matters: the most specific first, since
# the cumulative header also contains the word "العدوان".
SECTIONS = (
    # NOT "العدد التراكمي" — that phrase opens every cumulative DATA line
    # ("العدد التراكمي للشهداء: 73,356"), so using it as a header pattern made
    # each data line look like a section switch and the largest figures in the
    # report were silently never emitted.
    ("cumulative", re.compile(r"الإحصائي[ةه]\s+التراكمي[ةه]|منذ\s+بداي[ةه]\s+العدوان")),
    ("since_ceasefire", re.compile(r"منذ\s+وقف\s+إطلاق\s+النار")),
    ("daily", re.compile(r"خلال\s+ال.?\s*24\s*ساع[ةه]|الساعات\s+ال.?\s*24")),
)

MEASURES = (
    ("deaths",     re.compile(r"(?:العدد\s+التراكمي\s+ل|إجمالي\s+عدد\s+ال|عدد\s+ال)?شهداء\s*:?\s*([\d]+)")),
    ("injuries",   re.compile(r"(?:العدد\s+التراكمي\s+ل|إجمالي\s+عدد\s+ال|عدد\s+ال)?إصابات\s*:?\s*([\d]+)")),
    ("recovered",  re.compile(r"حالات\s+الانتشال\s*:?\s*([\d]+)")),
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
        else:
            lines.append(s)

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
        if current is None:
            continue

        for measure, pat in MEASURES:
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
    return r


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
}
