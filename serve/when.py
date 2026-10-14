"""How an answer says WHEN a databank row is about.

Until 2026-10-12 every answer printed `occurred_at`: "5,304 persons in
2008-01-01" for OCHA's count of people killed in Gaza between 2008 and 2023,
and "1 schools in 2026-08-05" for a school register whose only date is the day
v1 downloaded it. The store had been honest about both all along (their
precision is `unknown`, and the period sits in `attrs`); the sentence was not.

Three kinds of row, three kinds of sentence:

  a period total   attrs carries coverage_start / coverage_end: the value is
                   one total for that period, and the sentence names both ends
  a register row   precision `unknown`, no period: the row has no date of its
                   own. If the dataset records the publisher's vintage the
                   sentence gives it (and the start of what it covers, for a
                   list like the names of the dead); if not, it says the
                   source gives none
  a dated row      year, month or day, said at that precision and no finer
"""
from __future__ import annotations


def _day(v) -> str:
    """A date cut to its day; anything else (a vintage like "about 2018 to
    2020") as it is written."""
    s = str(v or "")
    return s[:10] if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-" else s


def period_of(it: dict) -> tuple[str, str] | None:
    a = it.get("attrs") or {}
    if a.get("coverage_start"):
        return _day(a["coverage_start"]), _day(a.get("coverage_end"))
    return None


def when_en(it: dict) -> str:
    p = period_of(it)
    if p:
        return (f"between {p[0]} and {p[1]} (one total for the period)" if p[1]
                else f"since {p[0]} (one total)")
    prec = it.get("occurred_precision")
    at = _day(it.get("occurred_at"))
    if prec == "unknown":
        v, start = it.get("dataset_vintage"), it.get("dataset_coverage_start")
        if v and start:
            return f"between {_day(start)} and {_day(v)} (the source gives no day)"
        return (f"in the publisher's register of {_day(v)}" if v
                else "with no date given by the source")
    if prec == "year":
        return f"in {at[:4]}"
    if prec == "month":
        return f"in {at[:7]}"
    return f"on {at}" if at else "undated"


def when_ar(it: dict) -> str:
    p = period_of(it)
    if p:
        return (f"من {p[0]} لغاية {p[1]} (مجموع الفترة كلها)" if p[1]
                else f"من {p[0]} (مجموع واحد)")
    prec = it.get("occurred_precision")
    at = _day(it.get("occurred_at"))
    if prec == "unknown":
        v, start = it.get("dataset_vintage"), it.get("dataset_coverage_start")
        if v and start:
            return f"بين {_day(start)} و{_day(v)} (والمصدر ما بيعطي اليوم)"
        return (f"حسب سجلّ الناشر بتاريخ {_day(v)}" if v
                else "والمصدر ما بيعطي تاريخ")
    if prec == "year":
        return f"سنة {at[:4]}"
    if prec == "month":
        return f"شهر {at[:7]}"
    return f"يوم {at}" if at else "بدون تاريخ"


# ── a figure that is one publisher's statement ───────────────────────────────
# The cited figures (db/reference/cited_figures.yaml) hold several publishers'
# statements under one indicator and one date: 711,000, 750,000 and 957,000
# refugees. "The latest value" of such a series is whichever row sorted first.
# An answer names every publisher beside its figure, and says when a figure
# was seen on Wikipedia only.

_Q_AR = {"about": "حوالي", "at_least": "على الأقل", "more_than": "أكثر من", "up_to": "لغاية"}
_Q_EN = {"about": "about", "at_least": "at least", "more_than": "more than", "up_to": "up to"}


def _num(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{int(f):,}" if f.is_integer() else f"{f:,}"


def is_cited(it: dict) -> bool:
    return bool((it.get("attrs") or {}).get("publisher"))


def statements(items: list[dict], it: dict) -> list[dict]:
    """Every publisher's row for the indicator and date of `it`."""
    return [x for x in items
            if x.get("indicator") == it.get("indicator")
            and x.get("occurred_at") == it.get("occurred_at") and is_cited(x)]


def _figure(it: dict, words: dict, rng: str) -> str:
    a = it.get("attrs") or {}
    if a.get("value_low") is not None and a.get("value_high") is not None:
        return rng.format(_num(a["value_low"]), _num(a["value_high"]))
    q = words.get(a.get("qualifier") or "")
    return (q + " " if q else "") + _num(it.get("value_num"))


def cited_en(rows: list[dict]) -> str:
    return "; ".join(
        f"{_figure(r, _Q_EN, '{} to {}')} per {r['attrs']['publisher']}"
        + (" (seen on Wikipedia only)" if r["attrs"].get("verification") == "via_wikipedia" else "")
        for r in rows)


def cited_ar(rows: list[dict]) -> str:
    return "؛ ".join(
        f"{_figure(r, _Q_AR, 'من {} لـ {}')} حسب {r['attrs']['publisher']}"
        + (" (منقول عن ويكيبيديا بس)" if r["attrs"].get("verification") == "via_wikipedia" else "")
        for r in rows)


# ── what a series is called ──────────────────────────────────────────────────

def label_en(d: dict, indicator: str) -> str:
    """The series' English name where the registry has one, its key otherwise."""
    return ((d.get("names") or {}).get(indicator) or {}).get("en") or indicator


# The word a unit takes after a number in an Arabic answer (2026-10-14). Until then
# the answer printed the unit's English code: "26,000 arrests", "9,265 persons".
# Arabic counts above ten take the singular, so the counted form is the
# singular («26,000 حالة اعتقال», «9,265 شخص»); `count` adds no word.
COUNTED_AR = {
    "count": "", "persons": "شخص", "arrests": "حالة اعتقال", "events": "حادثة", "structures": "مبنى",
    "tonne": "طن", "years": "سنة", "vehicles": "مركبة", "facilities": "منشأة", "sites": "موقع",
    "localities": "تجمّع", "households": "أسرة", "packages": "طرد", "km": "كم", "USD": "دولار",
    "ILS": "شيكل", "percent": "٪", "index": "(مؤشر)",
}
# The printed word first: a pallet is not «طرد» because the registry counts it in
# packages, nor a truck «مركبة», nor a school «منشأة».
PRINTED_AR = {
    "pallet": "منصّة", "truck": "شاحنة", "vehicle": "مركبة", "attacks": "هجوم", "schools": "مدرسة",
    "piece": "قطعة", "box": "صندوق", "tent": "خيمة", "buildings": "مبنى", "fatalities": "شخص",
    "settlers": "مستوطن", "people": "شخص", "cases": "", "number": "", "units": "",
    "Percent of GDP": "٪ من الناتج المحلي", "Percent of World": "٪ من العالم",
    "Annual percent change": "٪ تغيّر سنوي", "Index": "(مؤشر)",
}
_PACK_AR = {"KG": "كغم", "G": "غرام", "L": "لتر", "PIECES": "قطعة"}


def unit_word_ar(raw: str | None, unit_key: str | None = None, factor: tuple | None = None,
                 name_ar: str | None = None) -> str | None:
    """The Arabic for a row's unit as printed (`raw`), from the units registry
    (`unit_key`, the alias's factor, the unit's `name_ar`); None when there is
    nothing better than the raw string. A pack size is said as it was priced
    («شيكل لكل 25 كغم»), never as the unit it converts to."""
    import re
    if not raw:
        return None
    m = re.fullmatch(r"ILS/(\d+(?:\.\d+)?) ?(KG|G|L|PIECES)", raw.strip())
    if m:
        return f"شيكل لكل {m.group(1)} {_PACK_AR[m.group(2)]}"
    if raw == "thousand_persons":
        return "ألف شخص"
    if raw in PRINTED_AR:
        return PRINTED_AR[raw]
    one = factor is None or (factor[0] == factor[1])
    if one and unit_key in COUNTED_AR:
        return COUNTED_AR[unit_key]
    if one and name_ar:
        return name_ar
    return None


def label_ar(d: dict, indicator: str) -> str:
    """Arabic first, then English, then the key: a name in the other language
    still says more than `health.m_est_cig_curr_std.sex_fmle`."""
    n = (d.get("names") or {}).get(indicator) or {}
    return n.get("ar") or n.get("en") or indicator


def short_source(parts, sep: str = "; ", cap: int = 120) -> str:
    """The source line of a spoken answer: at most `cap` characters and never
    cut inside a word. A longer attribution stops at the end of its last whole
    sentence or clause; "…(tracking.un2720.org). No li." was read aloud on
    2026-10-12."""
    text = sep.join(p for p in (parts or []) if p)
    if len(text) <= cap:
        return text.rstrip(". ")
    head = text[:cap + 1]
    cut = max(head.rfind(". "), head.rfind("; "), head.rfind("؛ "))
    if cut < 20:
        cut = head.rfind(" ")
    return (head[:cut] if cut > 0 else text[:cap]).rstrip(".;؛,، ")

