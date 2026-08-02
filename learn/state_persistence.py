"""Fit how long each status value actually stays true, from the record itself.

    .venv/bin/python -m learn.state_persistence --report
    .venv/bin/python -m learn.state_persistence --apply

The question a decay model has to answer is "if the last report said X, how
likely is X still true now?" — and that has a measurable answer, because the
archive contains 69,616 consecutive report pairs per state kind. For each pair
we know the value, the elapsed time, and whether the value changed.

Measured on checkpoint flow:

    elapsed:      5m    10m   20m   30m    1h    2h    4h    8h   24h
    open        0.96  0.89  0.88  0.89  0.88  0.88  0.88  0.87  0.88
    closed      0.92  0.75  0.74  0.75  0.77  0.74  0.70  0.64  0.62
    congested   0.84  0.64  0.64  0.57  0.55  0.48  0.40  0.34  0.38

Three things that a single hand-set half-life cannot represent:

  * The curves differ by VALUE, not just by place. Congestion is more likely
    gone than not after two hours; a closure still holds ~0.70 at four.
  * They flatten rather than decaying to zero, because they decay toward the
    BASE RATE. `open` sits at 0.88 forever — most checkpoints are open most of
    the time, so an old "open" reading agrees with the next report without
    carrying any information.
  * The initial drop is steep and short. Most of the loss happens in the first
    ten minutes; after that the curve is nearly flat.

So each value gets p(t) = asymptote + (p0 - asymptote) * 0.5^(t/H), fitted by
weighted least squares over the bucketed curve. state_serving turns p(t) into
confidence by asking how far it still beats a coin flip — see migration 015 for
why that step is needed and why freshness has to gate separately.

SAMPLING BIAS, STATED PLAINLY. Reports are not a random sample of reality:
people file one BECAUSE something changed, which over-represents change and
makes these curves a lower bound on true persistence. That biases the system
toward saying "unknown" sooner, which is the direction an error should point.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect

# Bucket upper bounds, seconds. Dense early because that is where the curve moves.
BUCKETS = (300, 600, 1200, 1800, 3600, 7200, 14400, 28800, 86400)
MIN_PAIRS_PER_VALUE = 300
MIN_PAIRS_PER_BUCKET = 50
HALF_LIFE_GRID = tuple(60 * m for m in
                       (2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360, 480, 720))

PAIRS_SQL = """
WITH seq AS (
  SELECT place_id, direction, value, observed_at,
         LEAD(value)       OVER w AS next_value,
         LEAD(observed_at) OVER w AS next_at
  FROM state_observation
  WHERE state_kind = %s AND modality = 'assertion'
  WINDOW w AS (PARTITION BY place_id, direction ORDER BY observed_at)
)
SELECT value,
       EXTRACT(EPOCH FROM (next_at - observed_at))::int AS gap,
       (value = next_value)::int AS same
FROM seq
WHERE next_value IS NOT NULL AND next_at > observed_at
"""


def curve(rows: list[tuple[int, int]]) -> list[tuple[int, int, float]]:
    """[(bucket_upper, n, p_same)] over the fixed buckets."""
    out = []
    lo = 0
    for hi in BUCKETS:
        sel = [s for g, s in rows if lo <= g < hi]
        if sel:
            out.append((hi, len(sel), sum(sel) / len(sel)))
        lo = hi
    return out


def fit(pts: list[tuple[int, int, float]]) -> tuple[int, float, float] | None:
    """Grid-search (half_life, asymptote) minimising n-weighted squared error.

    A grid rather than a solver: the surface is smooth and low-dimensional, the
    grid is auditable, and it cannot wander into a degenerate fit the way an
    unconstrained optimiser can on a curve this flat.
    """
    usable = [(t, n, p) for t, n, p in pts if n >= MIN_PAIRS_PER_BUCKET]
    if len(usable) < 4:
        return None
    p0 = usable[0][2]
    best = None
    # Asymptote cannot exceed p0, and below 0.15 the curve is indistinguishable
    # from decay-to-zero, which the fallback already handles.
    ceiling = int(p0 * 100) - 2
    for a100 in range(15, max(16, ceiling), 2):
        asym = a100 / 100
        for H in HALF_LIFE_GRID:
            err = sum(n * (p - (asym + (p0 - asym) * 0.5 ** (t / H))) ** 2
                      for t, n, p in usable)
            if best is None or err < best[0]:
                best = (err, H, asym)
    if not best:
        return None
    return best[1], best[2], p0


def run(state_kind: str, apply_changes: bool) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(PAIRS_SQL, (state_kind,))
        by_value: dict[str, list[tuple[int, int]]] = {}
        for value, gap, same in cur.fetchall():
            by_value.setdefault(value, []).append((gap, same))

        results = []
        for value, rows in sorted(by_value.items(), key=lambda kv: -len(kv[1])):
            if len(rows) < MIN_PAIRS_PER_VALUE:
                results.append({"value": value, "n": len(rows), "fitted": False,
                                "reason": f"only {len(rows)} pairs"})
                continue
            pts = curve(rows)
            f = fit(pts)
            if not f:
                results.append({"value": value, "n": len(rows), "fitted": False,
                                "reason": "too few populated buckets"})
                continue
            H, asym, p0 = f
            results.append({"value": value, "n": len(rows), "fitted": True,
                            "half_life": H, "asymptote": asym, "p0": p0,
                            "curve": pts})
            if apply_changes:
                cur.execute("""
                    INSERT INTO state_value_decay
                      (state_kind,value,p0,asymptote,half_life_seconds,observations,computed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,now())
                    ON CONFLICT (state_kind,value) DO UPDATE SET
                      p0=EXCLUDED.p0, asymptote=EXCLUDED.asymptote,
                      half_life_seconds=EXCLUDED.half_life_seconds,
                      observations=EXCLUDED.observations, computed_at=now()""",
                    (state_kind, value, p0, asym, H, len(rows)))
        if apply_changes:
            conn.commit()
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write fitted curves")
    ap.add_argument("--kinds", default="checkpoint_flow",
                    help="comma-separated state kinds to fit")
    a = ap.parse_args()

    for kind in [k.strip() for k in a.kinds.split(",") if k.strip()]:
        print(f"\n=== {kind} ===")
        hdr = "  ".join(f"{t // 60:>4}m" if t < 86400 else " 24h" for t in BUCKETS)
        print(f"  {'value':<12}{'pairs':>7}   {hdr}")
        for r in run(kind, a.apply):
            if not r["fitted"]:
                print(f"  {r['value']:<12}{r['n']:>7}   not fitted — {r['reason']}")
                continue
            cells = {t: p for t, _, p in r["curve"]}
            row = "  ".join(f"{cells[t]:.2f}" if t in cells else "  - " for t in BUCKETS)
            print(f"  {r['value']:<12}{r['n']:>7}   {row}")
            print(f"  {'':<12}{'':>7}   -> half-life {r['half_life'] // 60} min, "
                  f"settles at {r['asymptote']:.2f} (from {r['p0']:.2f})")
    if not a.apply:
        print("\n(dry run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
