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


def fisher_ci(r: float, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Fisher z interval. Reported because a rho without an interval invites
    the reader to treat 0.6 from 13 points as 0.6 from 1,300."""
    if n < 4 or abs(r) >= 1:
        return None
    zr = 0.5 * math.log((1 + r) / (1 - r))
    se = 1 / math.sqrt(n - 3)
    lo, hi = zr - z * se, zr + z * se
    return (math.tanh(lo), math.tanh(hi))


def check_comparable(a: dict, b: dict) -> list[str]:
    """Every reason these two series must not be correlated. Empty means go."""
    stop = []
    for s in (a, b):
        if s["measure_kind"] in (None, "unclassified"):
            stop.append(
                f"{s['indicator']}: nobody has established what KIND of number "
                "this is (measure_kind is unclassified), so it cannot be "
                "compared to anything. Classify it in the spec's registry "
                "block first.")
        if s["measure_kind"] == "cumulative":
            stop.append(
                f"{s['indicator']} is CUMULATIVE — a running total. "
                "Correlating running totals measures the passage of time, not "
                "a relationship: any two rising totals correlate at ~1.0. "
                "Difference it deliberately through v_flow and ask again.")
        if s["measure_kind"] == "status":
            stop.append(f"{s['indicator']} is categorical (status); a "
                        "correlation over category labels is meaningless.")
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
    reading; precision carried from it."""
    pts = [p for p in series["points"] if p.get("value") is not None]
    out = []
    for prev, cur in zip(pts, pts[1:]):
        out.append({**cur, "value": float(cur["value"]) - float(prev["value"])})
    return {**series, "points": out, "n": len(out), "detrended": "diff"}


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
    dates = [p["at"] for p in series["points"]]
    distinct = len(set(dates))
    return len(dates) - distinct, distinct


def caveats(a: dict, b: dict, pairs: list, lag: int) -> list[str]:
    """Never empty. A correlation served without caveats is a claim."""
    out = ["Correlation is not causation, and neither series was collected to "
           "answer this question."]
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
        out.append(
            f"a lag of {lag} period(s) was applied. A lag scan tries many "
            "shifts and reports the best, which finds a correlation in noise "
            "reliably; treat a lagged result as a hypothesis, not a finding.")
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
