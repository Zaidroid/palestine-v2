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
  different time grains  a monthly series against an annual one pairs January
                         with the whole year
  mixed units            a series whose points are in different units ranks
                         litres against kilograms
  several rows per date  a series broken down by place, read without a
                         place_id, pairs whichever row came last
  a shared time trend    two series that both rise (or fall) over the window
                         correlate at ~±1 from the trend alone — the
                         cumulative artifact wearing a `stock` label

No numpy or scipy on this host, so Pearson and Spearman are implemented
directly. They are twelve lines each and the arithmetic is not the hard part
of this file.
"""
from __future__ import annotations

import math
from datetime import timedelta

MIN_N = 12
# Precisions whose dates cannot support a monthly or finer comparison. A
# 'year' row is a period, not a day, and a 'unknown' row is v1's fetch stamp.
UNUSABLE_PRECISION = ("unknown",)
# How strongly BOTH series must move with time before the pair is refused as a
# shared trend. Two independent drifting random walks of 36 points reach a
# Spearman of 0.95 with a 95 % interval of (0.91, 0.98) — "a very strong
# association" between two things that share nothing but a calendar.
TREND_LIMIT = 0.8
METHODS = ("spearman", "pearson")
DETRENDS = ("diff",)


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
        # The unit is read per POINT (the conversion the unit registry made),
        # and a series whose points came out in different units — milk priced
        # per litre and per kilogram under one indicator — is two series.
        if s.get("unit_mixed"):
            stop.append(
                f"{s['indicator']}: its points are in different units "
                f"({', '.join(s.get('units') or [])}); a coefficient over them "
                "would rank one unit's prices against another's. Compare the "
                "units apart through /v2/databank/compare.")
    # The scan always checked this; the pairwise call did not, and a monthly
    # price against an annual toll paired January with the whole year and
    # served the number with a caveat about period alignment.
    ga, gb = a.get("grain"), b.get("grain")
    if ga and gb and ga != gb:
        stop.append(
            f"time grains differ: {a['indicator']} is {ga} and {b['indicator']} "
            f"is {gb}. Pairing on dates would match one {ga} period against a "
            f"whole {gb} one; resampling to force an overlap would invent the "
            "points the coefficient rests on.")
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


def collapse_by_date(points: list[dict]) -> tuple[dict, list]:
    """One point per date, or the dates on which the rows disagree.

    `_series` returns every row of an indicator, and a breakdown series (WFP
    prices: one row per market per month, thirteen markets) carries several
    rows per date when no place_id is given. Keying a dict on the date kept
    whichever row the query plan returned last, so the served rho changed with
    physical row order (-0.511 against -0.439 on one reshuffle), and the scan
    paired every candidate row against one `a` value, reporting n=312 from 24
    months. Identical duplicates — two feeders filing the same figure — are one
    point; rows that DIFFER on a date are returned as conflicts for the caller
    to refuse on, never silently picked between.
    """
    by: dict = {}
    for p in points:
        by.setdefault(p["at"], []).append(p)
    out, conflicts = {}, []
    for at, ps in by.items():
        vals = {p["value"] for p in ps if p["value"] is not None}
        if len(vals) > 1:
            conflicts.append(at)
            continue
        usable = [p for p in ps if p["value"] is not None
                  and p["prec"] not in UNUSABLE_PRECISION]
        out[at] = (usable or [p for p in ps if p["value"] is not None] or ps)[0]
    return out, sorted(conflicts)


def several_rows_reason(indicator: str, conflicts: list, dates: int) -> str:
    return (f"{indicator}: {len(conflicts)} of {dates} dates carry several "
            "different values — the series is broken down by place (or fed by "
            "more than one publisher), and without a place_id the pairing would "
            "keep one row per date by accident of row order. Pass place_id to "
            "correlate one place's series.")


def pair_on_dates(a_by: dict, b_by: dict, lag_days: int = 0) -> list[tuple]:
    """(a, b, date, a_prec, b_prec) for every date both sides can support,
    oldest first. `lag_days` shifts b: pairs a at t with b at t + lag."""
    pairs = []
    for at, pa in a_by.items():
        shifted = at + timedelta(days=lag_days) if lag_days else at
        pb = b_by.get(shifted)
        if (pb and pa["value"] is not None and pb["value"] is not None
                and pa["prec"] not in UNUSABLE_PRECISION
                and pb["prec"] not in UNUSABLE_PRECISION):
            pairs.append((pa["value"], pb["value"], at, pa["prec"], pb["prec"]))
    pairs.sort(key=lambda p: p[2])
    return pairs


def differenced(pairs: list[tuple]) -> list[tuple]:
    """Change between consecutive overlapping dates, on both sides at once.

    What `detrend=diff` correlates: whether the two series move TOGETHER from
    one period to the next, which a shared drift cannot fake."""
    return [(x1 - x0, y1 - y0, d1, p1a, p1b)
            for (x0, y0, _d0, _p0a, _p0b), (x1, y1, d1, p1a, p1b)
            in zip(pairs, pairs[1:])]


def coefficient(method: str, xs: list[float], ys: list[float]) -> float | None:
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    return spearman(xs, ys) if method == "spearman" else pearson(xs, ys)


def shared_trend(pairs: list[tuple]) -> tuple[float, float] | None:
    """(trend of a, trend of b) — each side's Spearman against time — when BOTH
    exceed TREND_LIMIT in magnitude; None otherwise. Only `cumulative` used to
    be refused, but a `stock` price and any other level that rose over the same
    years correlate just as reliably, and for the same reason: time."""
    if len(pairs) < MIN_N:
        return None
    t = [p[2].toordinal() for p in pairs]
    ta = spearman([p[0] for p in pairs], t)
    tb = spearman([p[1] for p in pairs], t)
    if ta is None or tb is None:
        return None
    if abs(ta) >= TREND_LIMIT and abs(tb) >= TREND_LIMIT:
        return (ta, tb)
    return None


def trend_reason(a: str, b: str, trend: tuple[float, float]) -> str:
    return (f"both series move with time over the overlap ({a} {trend[0]:+.2f}, "
            f"{b} {trend[1]:+.2f} against the calendar). Two series that both "
            "rise or fall over the same years correlate at about ±1 from the "
            "shared trend alone — the cumulative artifact under another label. "
            "Ask again with detrend=diff to correlate their period-to-period "
            "changes instead.")


def fit(a_by: dict, b_by: dict, method: str = "spearman", max_lag: int = 0,
        detrend: str | None = None) -> dict:
    """The best coefficient over lags −max_lag..+max_lag (in days), or why none.

    Returns {"rho", "lag", "pairs", "raw_pairs"} on success, or {"reason"}.
    The reason names the REAL cause: "too few overlapping points" was reported
    even when forty points overlapped and one series simply did not vary, a
    self-contradicting refusal that sent the caller to widen the window.
    """
    if detrend is not None and detrend not in DETRENDS:
        raise ValueError(f"detrend must be one of {DETRENDS}")
    best, most, flat = None, 0, False
    for lag in range(-abs(max_lag), abs(max_lag) + 1):
        raw = pair_on_dates(a_by, b_by, lag)
        pairs = differenced(raw) if detrend == "diff" else raw
        most = max(most, len(pairs))
        if len(pairs) < MIN_N:
            continue
        rho = coefficient(method, [p[0] for p in pairs], [p[1] for p in pairs])
        if rho is None:
            flat = True
            continue
        if best is None or abs(rho) > abs(best["rho"]):
            best = {"rho": rho, "lag": lag, "pairs": pairs, "raw_pairs": raw}
    if best is not None:
        return best
    if flat:
        return {"reason": (f"{most} usable overlapping point(s), but one of the "
                           "series does not vary over them — a constant "
                           "correlates with nothing.")}
    return {"reason": (f"only {most} usable overlapping point(s)"
                       + (" after differencing" if detrend == "diff" else "")
                       + f"; {MIN_N} are required. Points are excluded when "
                       "either side carries 'unknown' precision — that date is "
                       "v1's fetch stamp, not an event date (law 1).")}


def expected_false_positives(tested: int) -> str:
    """What a scan's test count means, said without inventing a floor: the old
    wording printed 'roughly 1 of these' when zero tests had run."""
    if tested == 0:
        return ("No test was run: every candidate was refused or lacked "
                "overlapping dates, so there is nothing to rank.")
    return (f"{tested} test(s) were run. At the conventional 5% threshold about "
            f"{tested * 0.05:.1f} of them would look significant from noise "
            "alone, so treat every row as a hypothesis to check, never as a "
            "finding.")


def caveats(a: dict, b: dict, pairs: list, lag: int,
            detrend: str | None = None) -> list[str]:
    """Never empty. A correlation served without caveats is a claim."""
    out = ["Correlation is not causation, and neither series was collected to "
           "answer this question."]
    # Fisher's interval assumes independent draws; consecutive months of a
    # price or a toll are not, so the true interval is wider than printed.
    out.append("The 95% interval assumes independent points. Consecutive points "
               "of a time series usually depend on each other, so the real "
               "uncertainty is wider than the interval shown.")
    if detrend == "diff":
        out.append("Computed on CHANGES between consecutive overlapping dates "
                   "(detrend=diff), not on levels: it says whether the two move "
                   "together period to period.")
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
        # DAYS, said as days: the shift is `timedelta(days=lag)`, and calling it
        # "period(s)" let a caller believe months had been tried on a monthly
        # series whose dates a shift of a few days can never align.
        out.append(
            f"a lag of {lag} day(s) was applied (b shifted against a). A lag "
            "scan tries many shifts and reports the best, which finds a "
            "correlation in noise reliably; treat a lagged result as a "
            "hypothesis, not a finding.")
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
