"""Backtest: of the readings we would have SERVED, how many were right?

    .venv/bin/python -m learn.accuracy --days 7
    .venv/bin/python -m learn.accuracy --days 7 --write

Closes the last open item on Gate 1 ("measured precision proxy >=0.80 on the
7-day window"). Until this runs, every accuracy claim about this system is an
assertion rather than a measurement.

HOW IT WORKS
For each observation, reconstruct the belief that would have been served at the
instant just before it arrived, then check the two against each other. The
reconstruction replays the serving GATES at the historical timestamp —
measured persistence, the confidence floor, the staleness band and
max_assert_seconds — which is possible only because those functions all take
`at` explicitly instead of reading now(). A backtest that scored the CURRENT
contents of state_current would measure nothing: those rows are the answer.

WHAT THE NUMBER IS, EXACTLY (audit F235, 2026-09-25)
It is SINGLE-UNIT GATE PRECISION: the belief under test is the latest report
from ONE other independence unit, with a flat `base` of SINGLE_SOURCE_TRUST.
It is not the belief resolve/belief.py serves — that one is a per-unit noisy-OR
over every agreeing unit, weighted by each unit's measured trust_weight and
discounted for dissent, and this harness does not reconstruct it. Every line
this writes says so (`belief_model`). And because consecutive reports at one
place are scored against the same prior belief, pairs are not independent: the
interval (`ci95`) is a Wilson interval over DISTINCT beliefs (place, direction,
belief_at), not over pairs, which would be too narrow.

THE WINDOW IT JUDGES IS HELD OUT OF THE FIT IT REPLAYS (audit F234)
The decay curves (p0 / asymptote / half-life per value) are refitted nightly on
all history, the judged week included, and the gates are built on them. Replaying
tonight's fit over the week it was fitted on lets the fit absorb a change before
it is measured — the number cannot fall as far as reality did. So by default
the curves are refitted here on history strictly BEFORE the window
(learn.state_persistence with `until`), and those are replayed; `--in-sample`
replays the serving table instead, for comparison. The per-place cadence
(`place_state_cadence`, a median reporting gap that only sets the staleness band
and the fallback half-life) is still read as served, and the line says that too.

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
from datetime import datetime, timedelta, timezone
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learn import state_persistence  # noqa: E402
from resolve.db import connect  # noqa: E402

OUT = ROOT / "ops" / "accuracy.ndjson"

BELIEF_MODEL = ("single_unit_latest: the latest report from ONE other "
                "independence unit at a flat base trust — not belief.py's "
                "trust-weighted noisy-OR over every agreeing unit")

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
  AND o.observed_at > %(since)s
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
       (belief = truth) AS hit,
       place_id, direction, belief_at
FROM (
  SELECT pr.belief, pr.truth, pr.place_id, pr.direction, pr.belief_at,
         EXTRACT(EPOCH FROM (pr.t - pr.belief_at))          AS elapsed_s,
         COALESCE(c.half_life_seconds, k.half_life_seconds) AS hl,
         k.confidence_floor, k.max_assert_seconds,
         (%(base)s * CASE
            WHEN d.value IS NULL THEN
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
  {decay}
) x
"""

# Where the decay curves come from: the table serving reads (in-sample), or the
# curves refitted on history before the window (held out). Same columns either way.
DECAY_SERVING = """LEFT JOIN state_value_decay d   ON d.state_kind = %(kind)s
                                 AND d.value      = pr.belief"""
DECAY_HELD_OUT = """LEFT JOIN unnest(%(d_value)s::text[], %(d_p0)s::real[],
                   %(d_asym)s::real[], %(d_hl)s::int[])
       AS d(value, p0, asymptote, half_life_seconds) ON d.value = pr.belief"""


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


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def held_out_decay(cur, kind: str, until) -> dict[str, tuple[float, float, int]]:
    """value -> (p0, asymptote, half_life_s), fitted on history before `until`.

    The same fitter the nightly learn uses (learn.state_persistence), pointed
    at history that ends where the judged window begins, so the curves being
    replayed have never seen the reports they are judged against."""
    out = {}
    for r in state_persistence.fit_values(state_persistence.pairs(cur, kind, until)):
        if r["fitted"]:
            out[r["value"]] = (float(r["p0"]), float(r["asymptote"]), int(r["half_life"]))
    return out


def backtest(kind: str, days: int, cross_unit: bool,
             base: float = SINGLE_SOURCE_TRUST, held_out: bool = True) -> dict:
    with connect() as conn, conn.cursor() as cur:
        return _backtest(cur, kind, days, cross_unit, base, held_out)


def _backtest(cur, kind: str, days: int, cross_unit: bool,
              base: float = SINGLE_SOURCE_TRUST, held_out: bool = True,
              now: datetime | None = None) -> dict:
    since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    decay: dict = {}
    if held_out:
        decay = held_out_decay(cur, kind, since)
        fit_note = {"mode": "held_out", "fitted_before": since.isoformat(),
                    "values": sorted(decay)}
    else:
        fit_note = {"mode": "in_sample",
                    "note": "the serving state_value_decay, fitted on all history "
                            "including the judged window"}
    fit_note["cadence"] = "place_state_cadence as served (in-sample)"
    empty = {"state_kind": kind, "window_days": days, "pairs_examined": 0,
             "mode": "independent" if cross_unit else "self_consistency",
             "belief_model": BELIEF_MODEL, "decay_fit": fit_note,
             "would_have_asserted": 0, "correct": 0,
             "precision": None, "ci95": None, "distinct_beliefs_asserted": 0,
             "coverage": None, "calibration": {}, "by_value": {}, "by_age": {}}

    cur.execute(OBS_SQL, {"kind": kind, "since": since})
    pairs = _pair(cur.fetchall(), cross_unit)
    if not pairs:
        return empty
    cols = list(zip(*pairs))
    params = {
        "kind": kind, "base": base,
        "place_ids": list(cols[0]), "directions": list(cols[1]),
        "beliefs": list(cols[2]), "truths": list(cols[3]),
        "belief_ats": list(cols[4]), "ts": list(cols[5])}
    if held_out:
        vals = sorted(decay)
        params.update({"d_value": vals,
                       "d_p0": [decay[v][0] for v in vals],
                       "d_asym": [decay[v][1] for v in vals],
                       "d_hl": [decay[v][2] for v in vals]})
    cur.execute(GATES_SQL.format(decay=DECAY_HELD_OUT if held_out else DECAY_SERVING),
                params)
    rows = cur.fetchall()
    out = summarise(rows)
    return {"state_kind": kind,
            "mode": "independent" if cross_unit else "self_consistency",
            "belief_model": BELIEF_MODEL, "decay_fit": fit_note,
            "window_days": days, **out}


def summarise(rows: list[tuple]) -> dict:
    """GATES_SQL rows -> the reported numbers. Rows are
    (belief, truth, elapsed_s, conf, asserted, hit, place_id, direction, belief_at)."""
    served = [r for r in rows if r[4]]
    hits = sum(1 for r in served if r[5])
    # One vote per DISTINCT belief for the interval: every report that follows
    # one belief is scored against that same belief, so n pairs are far fewer
    # than n independent trials. A belief's share of hits is its vote.
    per_belief: dict[tuple, list[int]] = {}
    for r in served:
        agg = per_belief.setdefault((r[6], r[7], r[8]), [0, 0])
        agg[0] += 1
        agg[1] += int(r[5])
    n_eff = len(per_belief)
    k_eff = round(sum(h / n for n, h in per_belief.values()))
    out: dict = {
        "pairs_examined": len(rows),
        "would_have_asserted": len(served),
        "correct": hits,
        "precision": round(hits / len(served), 4) if served else None,
        "distinct_beliefs_asserted": n_eff,
        "ci95": _wilson(k_eff, n_eff),
        "coverage": round(len(served) / len(rows), 4) if rows else None,
    }

    # Calibration. The confidence model is only worth having if a stated 0.6
    # means roughly 60% — this is the check that would catch it being decorative.
    buckets: dict[str, list[int]] = {}
    for _, _, _, conf, asserted, hit, *_ in rows:
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
    for belief, _, _, _, asserted, hit, *_ in rows:
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
    for _, _, elapsed, _, asserted, hit, *_ in rows:
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
    ap.add_argument("--in-sample", action="store_true",
                    help="replay the serving decay table (fitted on the judged "
                         "window too) instead of a fit held out of it")
    a = ap.parse_args()

    # A retired kind (migration 070: fuel availability, 2026-09-23) has no
    # collector; backtesting it appended a null-precision line every night that
    # a reader had to know to ignore (audit F489). Asked of the config, so the
    # next retirement needs no edit here.
    targets = [("checkpoint_flow", True), ("fuel_diesel", False),
               ("fuel_gasoline", False)]
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT state_kind FROM state_kind_config WHERE retired_at IS NOT NULL")
        retired = {r[0] for r in cur.fetchall()}
    for kind in sorted(retired & {k for k, _ in targets}):
        print(f"  {kind}: retired in state_kind_config — not measured")
    targets = [(k, c) for k, c in targets if k not in retired]
    stamp = datetime.now(timezone.utc).isoformat()
    results = []

    for kind, cross in targets:
        r = backtest(kind, a.days, cross, a.base, held_out=not a.in_sample)
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
        ci = r.get("ci95")
        ci_txt = f" 95% CI {ci[0]:.3f}-{ci[1]:.3f} over {r['distinct_beliefs_asserted']} " \
                 f"distinct beliefs" if ci else ""
        print(f"  single-unit gate precision {r['precision']:.3f}{ci_txt}   [{verdict}]")
        print(f"  decay curves: {r['decay_fit']['mode']}"
              + (f" (fitted before {r['decay_fit']['fitted_before'][:16]})"
                 if r['decay_fit'].get('fitted_before') else ""))

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
