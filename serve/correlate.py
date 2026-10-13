"""Correlation, with the refusals that make it honest.

Zaid asked for "co-relations" — the ability to put electricity against
casualties against displacement and see whether they move together. That is a
reasonable thing to want and a dangerous thing to serve, because a
correlation coefficient looks like a fact and is usually an artifact.

So the refusals came first, and they are HARD — they return an explanation
instead of a number, never a number with a warning attached:

  n < 12                 too few overlapping points to mean anything
  precision unknown/year on a monthly question — the dates are not what the
                         caller thinks they are (laws 1 and 2, at the
                         serving layer)
  mixed place grains     a governorate series against a national one is a
                         comparison of two different things
  an underived cumulative — differencing must be deliberate (v_flow), never
                         implicit
  measure_kind unclassified — nobody established what kind of number it is
  identical concepts     correlating a series with itself, or with its own
                         subtotal, is arithmetic dressed as a finding
  mixed time grains      a daily series and a yearly one meet only on dates
                         they share by accident (2026-10-12; the scan had
                         this rule, the pairwise call did not)
  mixed units            one label holding prices per kg and per litre, or
                         counts and percentages, has no single line

No numpy or scipy on this host, so Pearson and Spearman are implemented
directly. They are twelve lines each and the arithmetic is not the hard part
of this file.
"""
from __future__ import annotations

import math

MIN_N = 12
# Precisions whose dates cannot support a monthly or finer comparison. A
# 'year' row is a period, not a day, and a 'unknown' row is v1's fetch stamp.
UNUSABLE_PRECISION = ("unknown",)


def rank(xs: list[float]) -> list[float]:
    """Average ranks, so ties do not bias Spearman. Ties are common here —
    a checkpoint status series is mostly the same number."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None                 # a constant series correlates with nothing
    return num / (dx * dy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return pearson(rank(xs), rank(ys))


def z_for_shifts(shifts: int) -> float:
    """The two-sided 95% z, widened for the number of shifts a lag search
    tried (Bonferroni). Trying 15 shifts and keeping the best one is 15 tests;
    an interval computed as if it were one is too narrow by construction."""
    from statistics import NormalDist
    return NormalDist().inv_cdf(1 - 0.025 / max(1, int(shifts)))


def fisher_ci(r: float, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Fisher z interval. Reported because a rho without an interval invites
    the reader to treat 0.6 from 13 points as 0.6 from 1,300."""
    if n < 4 or abs(r) >= 1:
        return None
    zr = 0.5 * math.log((1 + r) / (1 - r))
    se = 1 / math.sqrt(n - 3)
    lo, hi = zr - z * se, zr + z * se
    return (math.tanh(lo), math.tanh(hi))


GRAIN_WORD = {"day": "daily", "month": "monthly", "year": "yearly",
              "event": "a list of events", "register": "a register",
              "period": "period totals", "snapshot": "one snapshot",
              "census": "a census"}


def projection_reason(projected: list[str], observed: list[str]) -> str:
    """Why a projection is never put beside an observed series."""
    return (f"{', '.join(projected)} is a PROJECTION (a model's output, not a "
            f"measurement) and {', '.join(observed)} is observed. Side by side "
            "they would read as one record of what happened; a projection is "
            "compared only with other projections.")


def check_comparable(a: dict, b: dict, detrend: str = "none") -> list[str]:
    """Every reason these two series must not be correlated. Empty means go.

    `detrend="diff"` is the caller saying "correlate the changes". Until
    2026-10-12 this ran before the differencing and never heard about it, so
    the cumulative refusal's own advice ("pass detrend=diff") could not work:
    the second call was refused with the same sentence. A running total that is
    about to be differenced is not correlated as a running total."""
    stop = []
    if bool(a.get("projection")) != bool(b.get("projection")):
        p, o = (a, b) if a.get("projection") else (b, a)
        stop.append(projection_reason([p["indicator"]], [o["indicator"]]))
    for s in (a, b):
        if s["measure_kind"] in (None, "unclassified"):
            stop.append(
                f"{s['indicator']}: nobody has established what KIND of number "
                "this is (measure_kind is unclassified), so it cannot be "
                "compared to anything. Classify it in the spec's registry "
                "block first.")
        if s["measure_kind"] == "cumulative" and detrend != "diff":
            stop.append(
                f"{s['indicator']} is CUMULATIVE — a running total. "
                "Correlating running totals measures the passage of time, not "
                "a relationship: any two rising totals correlate at ~1.0. "
                "Pass detrend=diff to correlate the changes instead.")
        if s.get("unit_mixed"):
            stop.append(
                f"{s['indicator']} holds more than one unit "
                f"({', '.join(s.get('units') or [])}): one line drawn through "
                "them mixes different things. Read it with `databank` and pick "
                "one unit's rows.")
        if s["measure_kind"] == "status":
            stop.append(f"{s['indicator']} is categorical (status); a "
                        "correlation over category labels is meaningless.")
    ga, gb = a.get("grain"), b.get("grain")
    if ga and gb and ga != gb:
        stop.append(
            f"time grains differ: {a['indicator']} is {GRAIN_WORD.get(ga, ga)} "
            f"({ga}) and {b['indicator']} is {GRAIN_WORD.get(gb, gb)} ({gb}). "
            "They meet only on dates they happen to share, and filling one in "
            "to match the other would invent the points being compared.")
    if a["place_grain"] != b["place_grain"]:
        stop.append(
            f"place grains differ: {a['indicator']} is {a['place_grain']}-grade "
            f"and {b['indicator']} is {b['place_grain']}-grade. A governorate "
            "series against a national one compares two different things and "
            "the number would look fine.")
    if a["concept_key"] and a["concept_key"] == b["concept_key"] and \
            a["indicator"] != b["indicator"]:
        stop.append(
            f"both series are {a['concept_key']}. Two measures of one concept "
            "are often the same quantity counted twice — a subtotal against "
            "its total correlates at ~1.0 and means nothing. Say so "
            "explicitly with allow_same_concept=true if that is really the "
            "question.")
    return stop


# Two series that both climb (or both fall) over the window correlate at
# ~0.9 whatever they are: prices, population, an index — the coefficient
# measures time, exactly the artefact the cumulative rule refuses (audit
# 2026-09-25 F251). Spearman of value against its own order is the monotony
# test; both sides at or above this and the pair is refused unless the caller
# asks for the DIFFERENCED series (detrend=diff), which correlates the changes.
MONOTONE_RHO = 0.8


def trend_rho(xs: list[float]) -> float | None:
    """How monotone a series is: Spearman of its values against their order."""
    if len(xs) < MIN_N:
        return None
    return spearman(xs, [float(i) for i in range(len(xs))])


def check_shape(xs: list[float], ys: list[float]) -> list[str]:
    """Refusal reasons when BOTH series are (near-)monotone over the window."""
    ta, tb = trend_rho(xs), trend_rho(ys)
    if ta is None or tb is None:
        return []
    if abs(ta) >= MONOTONE_RHO and abs(tb) >= MONOTONE_RHO:
        return [f"both series {'rise' if ta > 0 else 'fall'} with time over the "
                f"window (monotony {ta:.2f} and {tb:.2f}); the coefficient would "
                "measure time, not a relationship. Pass detrend=diff to correlate "
                "the changes between consecutive readings instead."]
    return []


def differenced(series: dict) -> dict:
    """The series of changes between consecutive readings, dated at the later
    reading; precision carried from it.

    A running total that FALLS was corrected by its publisher: nobody was
    un-killed. That step is left out (the rule v_flow keeps), counted in
    `revisions_left_out`, and said in the caveats."""
    pts = [p for p in series["points"] if p.get("value") is not None]
    out, revisions = [], 0
    cumulative = series.get("measure_kind") == "cumulative"
    for prev, cur in zip(pts, pts[1:]):
        step = float(cur["value"]) - float(prev["value"])
        if cumulative and step < 0:
            revisions += 1
            continue
        out.append({**cur, "value": step})
    return {**series, "points": out, "n": len(out), "detrended": "diff",
            "revisions_left_out": revisions}


def collapse_dates(series: dict) -> tuple[dict, str | None]:
    """One value per date. A breakdown series (13 markets per month) used to
    be collapsed by 'last row wins', so rho depended on physical row order
    (audit F043). Now the MEDIAN of the rows on a date stands for the date —
    an explicit, order-independent rule — and the note says it was applied.
    Pass place_id to correlate one market instead."""
    dups, distinct = duplicate_dates(series)
    if not dups:
        return series, None
    by_date: dict = {}
    for p in series["points"]:
        if p.get("value") is None:
            continue
        by_date.setdefault(p["at"], []).append(p)
    pts = []
    for at in sorted(by_date):
        rows = by_date[at]
        vals = sorted(float(r["value"]) for r in rows)
        mid = len(vals) // 2
        med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        pts.append({**rows[0], "value": med, "rows_on_date": len(rows)})
    note = (f"{series.get('indicator')}: {dups} of {distinct} dates carried several rows "
            f"(a breakdown by place, sex, age or category); the MEDIAN per date was "
            f"correlated. Pass place_id to correlate one series of it.")
    return {**series, "points": pts, "n": len(pts), "aggregated": "median per date"}, note


def duplicate_dates(series: dict) -> tuple[int, int]:
    """(dates carrying more than one row, distinct dates) — a breakdown series
    (by place, sex, age, category) has several rows per date and no single
    value to correlate (audit F043)."""
    # The DATES that carry more than one row. This returned rows minus
    # distinct dates, so the note read "941 of 235 dates carried several rows"
    # (Claude web's test, 2026-09-25) — a count of extra rows, not of dates.
    from collections import Counter
    per_date = Counter(p["at"] for p in series["points"])
    return sum(1 for n in per_date.values() if n > 1), len(per_date)


def caveats(a: dict, b: dict, pairs: list, lag: int, shifts: int = 1) -> list[str]:
    """Never empty. A correlation served without caveats is a claim."""
    out = ["Correlation is not causation, and neither series was collected to "
           "answer this question."]
    for s in (a, b):
        if s.get("detrended") == "diff" and s.get("measure_kind") == "cumulative":
            out.append(
                f"{s['indicator']} is a running total; what was correlated is the "
                "change between consecutive readings, whatever the gap between them"
                + (f" ({s['revisions_left_out']} downward correction(s) by the "
                   "publisher left out)." if s.get("revisions_left_out") else "."))
        if s.get("other_sources"):
            out.append(
                f"{s['indicator']} is published by more than one source; only "
                f"{s.get('source_used')}'s series was used "
                f"(not pooled: {', '.join(sorted(s['other_sources']))}).")
    n = len(pairs)
    if n < 30:
        out.append(f"n = {n}. Below about 30 overlapping points a coefficient "
                   "moves a lot on one outlier; read the interval, not the "
                   "point estimate.")
    prec = {p[3] for p in pairs} | {p[4] for p in pairs}
    coarse = prec & {"year", "month"}
    if coarse:
        out.append(
            f"some points carry {sorted(coarse)} precision — they are PERIODS, "
            "not days, and were aligned to the start of the period they "
            "label.")
    if lag:
        first, second = (a, b) if lag > 0 else (b, a)
        out.append(
            f"a lag of {lag} day(s) was applied. A lag scan tries many "
            "shifts and reports the best, which finds a correlation in noise "
            "reliably; treat a lagged result as a hypothesis, not a finding.")
        out.append(
            f"{first['indicator']} moving before {second['indicator']} is an "
            "order in time, not a cause: a third thing can move both, and the "
            "earlier series can simply be reported sooner.")
    if shifts > 1:
        out.append(
            f"{shifts} shifts were tried and the strongest kept; the interval "
            "is widened for that many tries.")
    if a["source_names"] != b["source_names"]:
        out.append(
            f"different publishers ({', '.join(sorted(a['source_names']))} vs "
            f"{', '.join(sorted(b['source_names']))}) with different "
            "definitions, collection methods and coverage.")
    return out


def describe(rho: float | None, a: dict, b: dict) -> str:
    if rho is None:
        return "no coefficient — one of the series does not vary."
    mag = abs(rho)
    word = ("almost no" if mag < 0.2 else "a weak" if mag < 0.4 else
            "a moderate" if mag < 0.6 else "a strong" if mag < 0.8 else
            "a very strong")
    direction = "same" if rho > 0 else "opposite"
    s = f"{word} {direction}-direction association (rho = {rho:+.2f})"
    pa, pb = a.get("polarity"), b.get("polarity")
    if pa and pb and mag >= 0.4:
        both_bad = (pa == -1 and pb == -1)
        if both_bad:
            s += (", and both series are ones where a rise is a harm"
                  if rho > 0 else
                  ", between two series where a rise is a harm — so they move "
                  "against each other")
    return s


# ── the refusals, in Arabic ─────────────────────────────────────────────────
# The Arabic answer used to splice these English sentences in mid-flight
# ("لا يمكن حساب الارتباط: both series are detention…", Fawwaz's test,
# 2026-09-25). Every reason this module and the correlate routes produce has a
# fixed shape, so each is rendered from its parts; anything unrecognised is
# pointed at rather than pasted.
import re as _re

GRAIN_AR = {"region": "المنطقة كلها", "governorate": "المحافظة", "locality": "البلدة",
            "point": "النقطة"}
TIME_AR = {"month": "شهري", "year": "سنوي", "day": "يومي", "snapshot": "لقطة وحدة",
           "event": "أحداث", "register": "سجل", "census": "تعداد", "period": "فترات"}

SKIP_AR = {"cumulative — a running total": "مجموع تراكمي",
           "a projection against an observed series": "إسقاط مقابل سلسلة مرصودة",
           "more than one unit under one label": "أكثر من وحدة تحت اسم واحد",
           "categorical status": "تصنيف مش رقم",
           "different place grain": "مستوى مكان مختلف",
           "same concept as the subject": "نفس مفهوم السلسلة",
           "kind unclassified": "نوع الرقم غير مصنّف",
           "not comparable": "غير قابلة للمقارنة",
           "both series move with time (monotone; would measure time)":
               "السلسلتين بيتحركوا مع الوقت بس",
           "too few overlapping dates": "تواريخ مشتركة قليلة",
           "no variance in one series": "وحدة منهم ثابتة"}


def skip_ar(label: str) -> str:
    m = _re.fullmatch(r"different time grain \((\w+) vs (\w+)\)", label)
    if m:
        return f"دقة زمنية مختلفة ({TIME_AR.get(m[1], m[1])} مقابل {TIME_AR.get(m[2], m[2])})"
    return SKIP_AR.get(label, "غير قابلة للمقارنة")


def reason_ar(reason: str) -> str:
    """One refusal reason, in Arabic, with the same facts."""
    r = reason.strip()
    m = _re.match(r"no series named '(.+?)'", r)
    if m:
        return f"ما في سلسلة اسمها {m[1]} — دوّر على الاسم الصح بـ search"
    m = _re.match(r"(\S+) exists but has no points(.*)", r)
    if m:
        where = " بهالمكان" if "place" in m[2] else ""
        when = " بالفترة المطلوبة" if "window" in m[2] else ""
        return f"{m[1]} موجودة بس ما فيها نقاط{where}{when}"
    m = _re.match(r"(.+?) is a PROJECTION .*? and (.+?) is observed", r)
    if m:
        return (f"{m[1]} إسقاط (ناتج نموذج، مش قياس) و{m[2]} سلسلة مرصودة — جنب بعض "
                "بينقرأوا كأنهم سجل واحد للي صار، والإسقاط بينقارن بس مع إسقاط")
    m = _re.match(r"(\S+): nobody has established what KIND", r)
    if m:
        return f"{m[1]}: نوع الرقم غير مصنّف، فما بتنقارن بشي"
    m = _re.match(r"(\S+) is CUMULATIVE", r)
    if m:
        return (f"{m[1]} مجموع تراكمي — أي مجموعين تراكميين بيرتبطوا تقريباً 1.0 "
                "لأنهم بيكبروا مع الوقت، مش لأنهم مرتبطين")
    m = _re.match(r"(\S+) is categorical", r)
    if m:
        return f"{m[1]} تصنيف مش رقم، والارتباط على تصنيفات ما إله معنى"
    m = _re.match(r"place grains differ: (\S+) is (\w+)-grade and (\S+) is (\w+)-grade", r)
    if m:
        return (f"مستوى المكان مختلف: {m[1]} على مستوى {GRAIN_AR.get(m[2], m[2])} و{m[3]} "
                f"على مستوى {GRAIN_AR.get(m[4], m[4])} — الرقم رح يطلع شكله منطقي وهو بيقارن شيئين مختلفين")
    m = _re.match(r"time grains differ: (\S+) is .*?\((\w+)\) and (\S+) is .*?\((\w+)\)", r)
    if m:
        return (f"الدقة الزمنية مختلفة: {m[1]} {TIME_AR.get(m[2], m[2])} و{m[3]} "
                f"{TIME_AR.get(m[4], m[4])} — ما بيلتقوا إلا بتواريخ صدفة، وتعبئة وحدة "
                "لتطابق الثانية بتخترع النقاط اللي بنقارنها")
    m = _re.match(r"(\S+) holds more than one unit \((.+?)\)", r)
    if m:
        return (f"{m[1]} فيها أكثر من وحدة ({m[2]}) — خط واحد عليها بيخلط أشياء مختلفة. "
                "اقرأها بـ databank واختار صفوف وحدة وحدة")
    m = _re.match(r"both series are (.+?)\. Two measures", r)
    if m:
        return (f"السلسلتين من نفس المفهوم ({m[1]}) — غالباً نفس الكمية معدودة مرتين، "
                "وارتباطهم تقريباً 1.0 ما بيعني شي. إذا هاد فعلاً سؤالك مرّر allow_same_concept=true")
    m = _re.match(r"both series (rise|fall) with time", r)
    if m:
        way = "بيطلعوا" if m[1] == "rise" else "بينزلوا"
        return (f"السلسلتين {way} مع الوقت، فالمعامل رح يقيس الوقت مش العلاقة — "
                "مرّر detrend=diff لتقارن التغيّرات")
    m = _re.match(r"nothing else held is comparable to (\S+): .*?place grain \((\w+)\)", r)
    if m:
        return (f"ما في سلسلة ثانية على مستوى {GRAIN_AR.get(m[2], m[2])} "
                f"وفيها نقاط كفاية لنقارنها مع {m[1]}")
    return "مرفوض — السبب مفصّل في `reasons`"
