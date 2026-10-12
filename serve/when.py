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
    return str(v or "")[:10]


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
