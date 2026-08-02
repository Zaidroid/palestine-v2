"""Backtest: of the readings we would have SERVED, how many were right?

    .venv/bin/python -m learn.accuracy --days 7
    .venv/bin/python -m learn.accuracy --days 7 --write

Closes the last open item on Gate 1 ("measured precision proxy >=0.80 on the
7-day window"). Until this runs, every accuracy claim about this system is an
assertion rather than a measurement.

HOW IT WORKS
For each observation, reconstruct the belief that would have been served at the
instant just before it arrived, then check the two against each other. The
reconstruction replays the real serving logic at the historical timestamp —
measured persistence, the confidence floor, the staleness band and
max_assert_seconds — which is possible only because those functions all take
`at` explicitly instead of reading now(). A backtest that scored the CURRENT
contents of state_current would measure nothing: those rows are the answer.

Only readings the system would actually have ASSERTED are counted. That is what
precision means here — of the things we were willing to say out loud, how many
held up. Readings served as `unknown` are excluded from the numerator and the
denominator alike, and reported separately as coverage, because declining to
answer is not a wrong answer.

VERIFICATION MUST BE INDEPENDENT
The verifying observation is required to come from a different independence
group than the belief. Without that constraint this measures whether a channel
agrees with its own copies — nine of these channels agree 99.5-100% of the time
— and would report ~99% precision while proving nothing. Checkpoints have
19,678 cross-unit pairs over seven days, which is enough.

Fuel cannot be measured this way at all: palhub is the only source, so there is
no second observer. It is scored in `self_consistency` mode — does the next
sweep agree with the last — and labelled as such in the output. That is a real
signal about feed stability and it is NOT precision; conflating them would be
the same error as counting copied channels as corroboration.

WHY THIS IS A PROXY, AND WHICH WAY IT ERRS
The next report is not ground truth. It is another observation, with its own
parse errors, and it is event-triggered — people file a report BECAUSE
something changed. Both effects push measured agreement DOWN, so the number
here is a lower bound on true precision. An error in the optimistic direction
would be the dangerous one; this is not that.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect

OUT = ROOT / "ops" / "accuracy.ndjson"

# Trust in a single independent group — the belief under test is always the
# latest report from ONE unit, so this matches what state_current would hold.
#
# IMPORTED, not restated. This backtest exists to replay what the serving path
# actually does; a second copy of the constant would let the two drift and the
# measurement would quietly start describing a system that is not running. The
# same reasoning is why the gates themselves live in SQL rather than here.
from ingest.sources.checkpoints import SINGLE_SOURCE_TRUST  # noqa: E402

OBS_SQL = """
SELECT o.place_id, o.direction, o.value, o.observed_at,
       COALESCE(s.independence_group, 'src:' || s.source_id::text) AS unit
FROM state_observation o
JOIN source s USING (source_id)
WHERE o.state_kind = %(kind)s
  AND o.modality = 'assertion'
  AND o.observed_at > now() - make_interval(days => %(days)s)
ORDER BY o.place_id, o.direction, o.observed_at
"""

# The gates are evaluated in SQL, against the same functions state_serving uses,
# so this cannot drift from what is actually served. Only the PAIRING is done in
# Python: "latest prior observation from a different independence group" needs a
# running last-seen-per-unit map, which as a correlated subquery made Postgres
# rescan the window per row and did not finish in ten minutes.
GATES_SQL = """
SELECT belief, truth, elapsed_s, conf,
       (conf >= confidence_floor
        AND elapsed_s < hl * 8
        AND (max_assert_seconds IS NULL OR elapsed_s <= max_assert_seconds)) AS asserted,
       (belief = truth) AS hit
FROM (
  SELECT pr.belief, pr.truth,
         EXTRACT(EPOCH FROM (pr.t - pr.belief_at))          AS elapsed_s,
         COALESCE(c.half_life_seconds, k.half_life_seconds) AS hl,
         k.confidence_floor, k.max_assert_seconds,
         (%(base)s * CASE
            WHEN d.state_kind IS NULL THEN
              state_confidence(1.0::real, pr.belief_at,
                               COALESCE(c.half_life_seconds, k.half_life_seconds), pr.t)
            WHEN d.p0 <= 0.5 THEN
              value_persistence(d.p0, d.asymptote, d.half_life_seconds, pr.belief_at, pr.t)
            ELSE GREATEST(0::real, LEAST(1::real,
                   (value_persistence(d.p0, d.asymptote, d.half_life_seconds,
                                      pr.belief_at, pr.t) - 0.5) / (d.p0 - 0.5)))
          END)::real AS conf
  FROM unnest(%(place_ids)s::bigint[], %(directions)s::text[], %(beliefs)s::text[],
              %(truths)s::text[], %(belief_ats)s::timestamptz[], %(ts)s::timestamptz[])
       AS pr(place_id, direction, belief, truth, belief_at, t)
  JOIN state_kind_config k        ON k.state_kind = %(kind)s
  LEFT JOIN place_state_cadence c ON c.place_id   = pr.place_id
                                 AND c.state_kind = %(kind)s
                                 AND c.direction  = pr.direction
  LEFT JOIN state_value_decay d   ON d.state_kind = %(kind)s
                                 AND d.value      = pr.belief
) x
"""


def _pair(obs: list[tuple], cross_unit: bool) -> list[tuple]:
    """(place_id, direction, belief, truth, belief_at, t) for each observation
    that has a prior belief to test.

    One forward pass per (place, direction), carrying the last observation seen
    from each independence unit. The belief under test is the most recent one
    from a DIFFERENT unit — checking a channel against its own copies would
    report ~99% and prove nothing.
    """
    out: list[tuple] = []
    key = None
    last: dict[str, tuple] = {}
    for place_id, direction, value, observed_at, unit in obs:
        k = (place_id, direction)
        if k != key:
            key, last = k, {}
        cands = [(u, v) for u, v in last.items() if not cross_unit or u != unit]
        if cands:
            _, (bval, bat) = max(cands, key=lambda uv: uv[1][1])
            out.append((place_id, direction, bval, value, bat, observed_at))
        last[unit] = (value, observed_at)
    return out


def backtest(kind: str, days: int, cross_unit: bool,
             base: float = SINGLE_SOURCE_TRUST) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(OBS_SQL, {"kind": kind, "days": days})
        pairs = _pair(cur.fetchall(), cross_unit)
        if not pairs:
            return {"state_kind": kind, "window_days": days, "pairs_examined": 0,
                    "mode": "independent" if cross_unit else "self_consistency",
                    "would_have_asserted": 0, "correct": 0,
                    "precision": None, "coverage": None,
                    "calibration": {}, "by_value": {}, "by_age": {}}
        cols = list(zip(*pairs))
        cur.execute(GATES_SQL, {
            "kind": kind, "base": base,
            "place_ids": list(cols[0]), "directions": list(cols[1]),
            "beliefs": list(cols[2]), "truths": list(cols[3]),
            "belief_ats": list(cols[4]), "ts": list(cols[5])})
        rows = cur.fetchall()

    served = [r for r in rows if r[4]]
    hits = sum(1 for r in served if r[5])
    out: dict = {
        "state_kind": kind,
        "mode": "independent" if cross_unit else "self_consistency",
        "window_days": days,
        "pairs_examined": len(rows),
        "would_have_asserted": len(served),
        "correct": hits,
        "precision": round(hits / len(served), 4) if served else None,
        "coverage": round(len(served) / len(rows), 4) if rows else None,
    }

    # Calibration. The confidence model is only worth having if a stated 0.6
    # means roughly 60% — this is the check that would catch it being decorative.
    buckets: dict[str, list[int]] = {}
    for _, _, _, conf, asserted, hit in rows:
        if not asserted:
            continue
        b = f"{int(float(conf) * 10) / 10:.1f}"
        agg = buckets.setdefault(b, [0, 0])
        agg[0] += 1
        agg[1] += int(hit)
    out["calibration"] = {b: {"n": n, "actual": round(h / n, 3)}
                          for b, (n, h) in sorted(buckets.items())}

    # Precision by value: a high average can hide one value being badly wrong,
    # and `closed` being wrong is the expensive direction.
    per_value: dict[str, list[int]] = {}
    for belief, _, _, _, asserted, hit in rows:
        if not asserted:
            continue
        agg = per_value.setdefault(belief, [0, 0])
        agg[0] += 1
        agg[1] += int(hit)
    out["by_value"] = {v: {"n": n, "precision": round(h / n, 3)}
                       for v, (n, h) in sorted(per_value.items(), key=lambda kv: -kv[1][0])}

    # Does precision actually decay with age the way the model assumes?
    bands = [(0, 900, "<15m"), (900, 3600, "15-60m"), (3600, 10800, "1-3h"),
             (10800, 21600, "3-6h"), (21600, 10 ** 9, ">6h")]
    per_age: dict[str, list[int]] = {}
    for _, _, elapsed, _, asserted, hit in rows:
        if not asserted:
            continue
        for lo, hi, lbl in bands:
            if lo <= float(elapsed) < hi:
                agg = per_age.setdefault(lbl, [0, 0])
                agg[0] += 1
                agg[1] += int(hit)
                break
    out["by_age"] = {lbl: {"n": n, "precision": round(h / n, 3)}
                     for lbl, (n, h) in per_age.items()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--write", action="store_true",
                    help=f"append the result to {OUT.relative_to(ROOT)}")
    ap.add_argument("--base", type=float, default=SINGLE_SOURCE_TRUST,
                    help="single-unit trust to replay the gates with. Loop A "
                         "(learn/reliability.py) measures what this should be; "
                         "sweeping it shows what raising it costs in precision.")
    a = ap.parse_args()

    targets = [("checkpoint_flow", True), ("fuel_diesel", False),
               ("fuel_gasoline", False)]
    stamp = datetime.now(timezone.utc).isoformat()
    results = []

    for kind, cross in targets:
        r = backtest(kind, a.days, cross, a.base)
        r["measured_at"] = stamp
        results.append(r)

        label = ("independent cross-source"
                 if r["mode"] == "independent" else "SELF-consistency (single source)")
        print(f"\n=== {kind} — {label}, {a.days}d ===")
        if not r["pairs_examined"]:
            print("  no verification pairs in the window")
            continue
        print(f"  pairs examined      {r['pairs_examined']}")
        print(f"  would have asserted {r['would_have_asserted']}  "
              f"({r['coverage']:.0%} of pairs — the rest served as unknown)")
        if r["precision"] is None:
            print("  nothing asserted; no precision to report")
            continue
        verdict = "PASS" if r["precision"] >= 0.80 else "BELOW 0.80"
        print(f"  precision           {r['precision']:.3f}   [{verdict}]")

        if r["by_value"]:
            print("  by value:")
            for v, d in r["by_value"].items():
                print(f"     {v:<12}{d['n']:>7}  {d['precision']:.3f}")
        if r["by_age"]:
            print("  by age of the reading:")
            for lbl in ("<15m", "15-60m", "1-3h", "3-6h", ">6h"):
                if lbl in r["by_age"]:
                    d = r["by_age"][lbl]
                    print(f"     {lbl:<12}{d['n']:>7}  {d['precision']:.3f}")
        if r["calibration"]:
            print("  calibration (stated confidence vs actual):")
            for b, d in r["calibration"].items():
                gap = d["actual"] - float(b)
                flag = "" if abs(gap) <= 0.10 else "   <-- miscalibrated"
                print(f"     said {b}  actual {d['actual']:.3f}  n={d['n']:<7}{flag}")

    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\nappended {len(results)} record(s) to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
