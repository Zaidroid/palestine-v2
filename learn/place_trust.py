"""Trust by place — where a wide source has earned its word, and where it has not.

    .venv/bin/python -m learn.place_trust                 # measure, print, write nothing
    .venv/bin/python -m learn.place_trust --write         # and record it (table source_place_trust, 099)
    .venv/bin/python -m learn.place_trust --show          # what is recorded

WHY IT EXISTS
PalHub's board is the widest source the live map has and the least trusted.
Its earn-out (ops/palhub_earnout.py, Zaid's decision A, 2026-09-25) was taken
by VALUE CLASS over the whole West Bank: `open` and `closed` are asserted,
`congested` is quarantined. A class is the wrong unit. Measured on 2026-10-11
over 42 days and 102,844 pairs:

    the board's `open`    agrees with the channels 0.88 overall, and 0.12 at
                          جماعين (the channels say closed 37 times in 42)
    the board's `closed`  agrees 0.72 overall, and 0.00 at بيت ليد (open 91 of 91)
    "أزمة خانقة" (severe) agrees 0.49 overall, and 0.72 at قلنديا, 0.70 at العيزرية
    "أزمة متوسطة" (medium) agrees 0.12: it is what the channels call open

The board restates a status its own users last set, however long ago, under a
fresh timestamp; at a checkpoint its users pass every hour it is right, and at
one they do not it repeats yesterday. So the same word is believed at one
place and held at another, by measurement, per place and per claim.

THE COUNT
One pair = one board reading and the nearest independent channel assertion for
the same checkpoint in a compatible direction within WINDOW_MIN minutes (half
the kind's measured persistence, the reliability loop's own rule for "the same
moment"). The board restates a place two to four times an hour, so pairs are
not independent trials: they are folded into (place, claim, hour) cells, a cell
agreeing when most of its pairs do, and the interval is taken over cells.

THE VERDICT
The bar for a claim is the channels' own agreement with each other on that
value, measured the same way, less BAND — the tolerance Zaid's decision A
accepted when it promoted `closed` 0.13 under its control.

  * a claim the class rule ASSERTS (open, closed) is HELD at a place when the
    upper bound of its agreement there is under the bar: we are sure it is
    worse than a channel here;
  * a claim the class rule HOLDS (the two congestions) is ASSERTED at a place
    when the lower bound of its agreement there reaches the bar: it has earned
    it here;
  * anything else keeps the class rule. A place the channels never report on
    has no pairs, so the board is judged there by its class alone, as before.

Bounds are Wilson 95 %, and a verdict also needs MIN_CELLS cells over MIN_DAYS
days, so one long episode cannot decide a place. Nothing here changes a stored
row: ingest/sources/palhub_roads.py reads the verdicts when it writes the next
reading.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOURCE_KEY = "tg_palhubapproad"
STATE_KIND = "checkpoint_flow"
DAYS = 42
WINDOW_MIN = 45
BAND = 0.15
MIN_CELLS = 24
MIN_DAYS = 5
Z = 1.96

# What the class rule does with a claim nobody has measured at a place.
CLASS_DEFAULT = {"open": "assert", "closed": "assert",
                 "congested_medium": "hold", "congested_severe": "hold"}
# The channels' value a claim is compared with.
MEANS = {"open": "open", "closed": "closed",
         "congested_medium": "congested", "congested_severe": "congested"}

PAIR_SQL = """
WITH ph AS (
  SELECT o.place_id, o.direction, o.value, o.observed_at,
         o.attrs->>'palhub_severity' AS severity
    FROM state_observation o JOIN source s ON s.source_id = o.source_id
   WHERE s.key = %(key)s AND o.state_kind = %(kind)s
     AND o.observed_at > now() - make_interval(days => %(days)s)
), live AS (
  SELECT o.place_id, o.direction, o.value, o.observed_at
    FROM state_observation o JOIN source s ON s.source_id = o.source_id
   WHERE s.key <> %(key)s AND s.kind <> 'crowd'
     AND o.state_kind = %(kind)s AND o.modality = 'assertion'
     AND o.observed_at > now() - make_interval(days => %(days)s + 1)
)
SELECT DISTINCT ON (p.place_id, p.direction, p.observed_at)
       p.place_id, p.value, p.severity, l.value, date_trunc('hour', p.observed_at)
  FROM ph p
  JOIN live l ON l.place_id = p.place_id
   AND (l.direction = p.direction OR l.direction = 'both' OR p.direction = 'both')
   AND l.observed_at BETWEEN p.observed_at - make_interval(mins => %(win)s)
                         AND p.observed_at + make_interval(mins => %(win)s)
 ORDER BY p.place_id, p.direction, p.observed_at,
          abs(EXTRACT(epoch FROM (p.observed_at - l.observed_at)))
"""

# The control: one channel unit against another, paired and folded the same way.
CONTROL_SQL = """
WITH live AS (
  SELECT o.place_id, o.direction, o.value, o.observed_at,
         COALESCE(s.independence_group, 'src:' || s.source_id::text) AS unit
    FROM state_observation o JOIN source s ON s.source_id = o.source_id
   WHERE s.key <> %(key)s AND s.kind <> 'crowd'
     AND o.state_kind = %(kind)s AND o.modality = 'assertion'
     AND o.observed_at > now() - make_interval(days => %(days)s)
)
SELECT DISTINCT ON (a.place_id, a.direction, a.observed_at, a.unit)
       a.place_id, a.value, b.value, date_trunc('hour', a.observed_at)
  FROM live a
  JOIN live b ON b.place_id = a.place_id AND b.unit <> a.unit
   AND (b.direction = a.direction OR b.direction = 'both' OR a.direction = 'both')
   AND b.observed_at BETWEEN a.observed_at - make_interval(mins => %(win)s)
                         AND a.observed_at + make_interval(mins => %(win)s)
 ORDER BY a.place_id, a.direction, a.observed_at, a.unit,
          abs(EXTRACT(epoch FROM (a.observed_at - b.observed_at)))
"""


def claim_class(value: str, severity) -> str | None:
    """The board's own word, as a claim: its two congestions are two claims."""
    if value in ("open", "closed"):
        return value
    if value == "congested":
        return "congested_severe" if str(severity) == "2" else "congested_medium"
    return None


def wilson(k: int, n: int) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + Z * Z / n
    mid = (p + Z * Z / (2 * n)) / d
    half = Z * sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(0.0, mid - half), min(1.0, mid + half)


def fold(pairs) -> dict:
    """(place, claim) → {cells, agree, days, heard}; a cell is one hour and
    agrees when most of its pairs do (a tie does not)."""
    cells: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    heard: dict[tuple, Counter] = defaultdict(Counter)
    for place_id, claim, said, hour in pairs:
        c = cells[(place_id, claim, hour)]
        c[0] += int(said == MEANS[claim])
        c[1] += 1
        heard[(place_id, claim)][said] += 1
    out: dict[tuple, dict] = {}
    for (place_id, claim, hour), (a, n) in cells.items():
        r = out.setdefault((place_id, claim), {"cells": 0, "agree": 0, "days": set()})
        r["cells"] += 1
        r["agree"] += int(a * 2 > n)
        r["days"].add(str(hour)[:10])
    for k, r in out.items():
        r["days"] = len(r["days"])
        r["heard"] = dict(heard[k])
    return out


def control_rates(control_pairs) -> dict[str, float]:
    """The channels' agreement with each other by value, over hour cells."""
    cells: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for place_id, a, b, hour in control_pairs:
        c = cells[(place_id, a, hour)]
        c[0] += int(a == b)
        c[1] += 1
    by: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (_p, value, _h), (a, n) in cells.items():
        by[value][0] += int(a * 2 > n)
        by[value][1] += 1
    return {v: a / n for v, (a, n) in by.items() if n}


def verdicts(folded: dict, control: dict[str, float]) -> list[dict]:
    """One row per (place, claim) that has pairs (pure)."""
    out = []
    for (place_id, claim), r in sorted(folded.items()):
        ctl = control.get(MEANS[claim])
        if ctl is None:
            continue
        bar = round(ctl - BAND, 3)
        lo, hi = wilson(r["agree"], r["cells"])
        default = CLASS_DEFAULT[claim]
        enough = r["cells"] >= MIN_CELLS and r["days"] >= MIN_DAYS
        verdict, why = default, "class rule"
        if not enough:
            why = f"class rule: {r['cells']} cells over {r['days']} days is too few to judge"
        elif default == "assert" and hi < bar:
            verdict, why = "hold", f"measured under the bar here (upper bound {hi:.2f} < {bar:.2f})"
        elif default == "hold" and lo >= bar:
            verdict, why = "assert", f"earned here (lower bound {lo:.2f} ≥ {bar:.2f})"
        out.append({"place_id": place_id, "claim_class": claim, "cells": r["cells"],
                    "days": r["days"], "agreement": round(r["agree"] / r["cells"], 3),
                    "lower": round(lo, 3), "upper": round(hi, 3), "bar": bar,
                    "heard": r["heard"], "verdict": verdict,
                    "moved": verdict != default, "why": why})
    return out


def measure(cur, days: int = DAYS, win: int = WINDOW_MIN) -> tuple[list[dict], dict]:
    args = {"key": SOURCE_KEY, "kind": STATE_KIND, "days": days, "win": win}
    cur.execute(PAIR_SQL, args)
    pairs = [(p, claim_class(v, sev), said, hour) for p, v, sev, said, hour in cur.fetchall()]
    pairs = [x for x in pairs if x[1]]
    cur.execute(CONTROL_SQL, args)
    control = control_rates(cur.fetchall())
    return verdicts(fold(pairs), control), control


def load(cur) -> dict[tuple[int, str], str]:
    """(place_id, claim_class) → verdict for the claims a measurement moved off
    the class rule. Empty where migration 099 has not run."""
    cur.execute("SELECT to_regclass('source_place_trust') IS NOT NULL")
    if not cur.fetchone()[0]:
        return {}
    cur.execute("""SELECT t.place_id, t.claim_class, t.verdict
                     FROM source_place_trust t JOIN source s USING (source_id)
                    WHERE s.key = %s AND t.moved""", (SOURCE_KEY,))
    return {(p, c): v for p, c, v in cur.fetchall()}


WRITE_SQL = """
INSERT INTO source_place_trust
  (source_id, place_id, claim_class, cells, days, agreement, lower_bound, upper_bound,
   bar, heard, verdict, moved, why, window_days, window_minutes, measured_at)
SELECT s.source_id, %(place_id)s, %(claim_class)s, %(cells)s, %(days)s, %(agreement)s,
       %(lower)s, %(upper)s, %(bar)s, %(heard)s, %(verdict)s, %(moved)s, %(why)s,
       %(window_days)s, %(window_minutes)s, now()
  FROM source s WHERE s.key = %(key)s
ON CONFLICT (source_id, place_id, claim_class) DO UPDATE SET
  cells = EXCLUDED.cells, days = EXCLUDED.days, agreement = EXCLUDED.agreement,
  lower_bound = EXCLUDED.lower_bound, upper_bound = EXCLUDED.upper_bound,
  bar = EXCLUDED.bar, heard = EXCLUDED.heard, verdict = EXCLUDED.verdict,
  moved = EXCLUDED.moved, why = EXCLUDED.why, window_days = EXCLUDED.window_days,
  window_minutes = EXCLUDED.window_minutes, measured_at = now()
"""


def write(cur, rows: list[dict], days: int, win: int) -> int:
    """Record the measurement. A (place, claim) measured before and not in this
    run keeps its row but returns to the class rule: an old verdict must not
    outlive the evidence for it."""
    seen: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        seen[r["claim_class"]].append(r["place_id"])
    for claim, default in CLASS_DEFAULT.items():
        cur.execute("""UPDATE source_place_trust t SET moved = false, verdict = %s,
                              why = 'class rule: no pairs in the last measurement'
                         FROM source s
                        WHERE s.source_id = t.source_id AND s.key = %s AND t.claim_class = %s
                          AND t.moved AND NOT (t.place_id = ANY(%s))""",
                    (default, SOURCE_KEY, claim, seen.get(claim, [])))
    for r in rows:
        cur.execute(WRITE_SQL, {**r, "heard": json.dumps(r["heard"], ensure_ascii=False),
                                "key": SOURCE_KEY, "window_days": days, "window_minutes": win})
    return len(rows)


def _print(rows: list[dict], control: dict, names: dict) -> None:
    print("the channels' own agreement by value (the control): "
          + ", ".join(f"{v} {r:.3f}" for v, r in sorted(control.items())))
    by = Counter((r["claim_class"], r["verdict"], r["moved"]) for r in rows)
    for claim in CLASS_DEFAULT:
        n = sum(c for (cl, _, _), c in by.items() if cl == claim)
        moved = sum(c for (cl, _, m), c in by.items() if cl == claim and m)
        print(f"  {claim:<18} {n:>4} places measured, {moved:>3} moved off the class rule "
              f"({CLASS_DEFAULT[claim]})")
    for r in sorted((r for r in rows if r["moved"]), key=lambda r: (r["claim_class"], r["agreement"])):
        print(f"  {r['claim_class']:<18} {r['verdict']:<6} {names.get(r['place_id'], r['place_id'])} "
              f"({r['place_id']}): {r['agreement']:.2f} over {r['cells']} hours, {r['days']} days; "
              f"channels said {r['heard']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--window", type=int, default=WINDOW_MIN)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args(argv)
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        if a.show:
            cur.execute("SELECT to_regclass('source_place_trust') IS NOT NULL")
            if not cur.fetchone()[0]:
                print("source_place_trust does not exist yet (migration 099)")
                return 0
            cur.execute("""SELECT t.claim_class, t.verdict, p.name_ar, t.place_id, t.agreement,
                                  t.cells, t.days, t.measured_at::date
                             FROM source_place_trust t JOIN place p USING (place_id)
                            WHERE t.moved ORDER BY 1, 5""")
            for r in cur.fetchall():
                print(*r, sep=" | ")
            return 0
        rows, control = measure(cur, a.days, a.window)
        cur.execute("SELECT place_id, COALESCE(name_ar, name_en) FROM place WHERE place_id = ANY(%s)",
                    ([r["place_id"] for r in rows],))
        _print(rows, control, dict(cur.fetchall()))
        if a.write:
            cur.execute("SELECT to_regclass('source_place_trust') IS NOT NULL")
            if not cur.fetchone()[0]:
                print("not written: source_place_trust does not exist yet (migration 099)")
                conn.rollback()
                return 0
            n = write(cur, rows, a.days, a.window)
            conn.commit()
            print(f"recorded {n} (place, claim) rows")
        else:
            conn.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
