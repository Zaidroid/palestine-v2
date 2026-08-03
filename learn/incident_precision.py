"""P1.1 — measure what the incident classifier is actually right about.

    .venv/bin/python -m learn.incident_precision --sample     # draw the sample
    .venv/bin/python -m learn.incident_precision --score      # after scoring
    .venv/bin/python -m learn.incident_precision --show       # last result

WHY THIS IS NOT OPTIONAL
The incident vertical shipped with a yield number (~22% of news claims classify)
and no accuracy number at all. Yield is a RATE: it says how often the classifier
fires, not how often it is right. Checkpoints were backtested to 0.816 and fuel
was measured; incidents were not, and everything downstream — the API, the MCP
tools, eventually a chatbot family members will believe — presents them with the
same confidence as the measured verticals.

WHY IT CANNOT REUSE THE CHECKPOINT BACKTEST
That harness works because a checkpoint has a later, independent observation to
be checked against: the road is still there in an hour and somebody else reports
it. An incident is an EVENT. Nobody re-reports that a particular raid happened
at 03:00, so there is no future ground truth to pair against. The only available
truth is the text itself, read by a human.

STRATIFIED, NOT RANDOM
A uniform sample of 120 would be ~76 raids and would tell us almost nothing
about `death` (2 rows) or `shooting` (4). The aggregate would then hide the weak
types exactly as it hid `slow` scoring 0/16 in the checkpoint parser. So every
type is sampled up to a cap, and precision is reported PER TYPE with an interval
wide enough to be honest about the small ones.

REJECTS ARE SAMPLED TOO
Precision alone is the metric you can game by classifying almost nothing. 679
claims were rejected and 497 called unclear; if the rejects are full of real
incidents then the vertical is quietly blind rather than accurate. Scoring a
sample of them gives the miss rate that precision on its own cannot show.

FOUR SEPARATE JUDGEMENTS
Recorded independently because they fail independently, and a single
right/wrong verdict would blur them:

    is_incident  does the text report a real-world incident at all
    type_ok      is the assigned incident_type the right one
    place_ok     does the resolved place match what the text names
    west_bank    is it actually in the West Bank (not Gaza, not abroad)

`is_incident` is the gate: if the text is not an incident the other three are
not applicable rather than false, and are left null.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect  # noqa: E402

SAMPLE_FILE = ROOT / "ops" / "incident-sample.ndjson"
SCORED_FILE = ROOT / "ops" / "incident-scored.ndjson"
RESULT_FILE = ROOT / "ops" / "incident-precision.json"

PER_TYPE_CAP = 20      # every type up to 20; the small ones are taken whole
REJECT_SAMPLE = 40     # enough to put a bound on the miss rate

# Gate from docs/TIER1_COMPLETION_PLAN.md.
GATE_OVERALL = 0.80
GATE_PER_TYPE = 0.60
# Below this a "precision" is not a measurement. One sampled `closure` that
# happened to be wrong reads as 0.000 with a 95% interval of 0.00-0.79, which
# says nothing at all — failing the gate on it would be as dishonest as passing
# a type on 1/1. Such types are reported as UNMEASURED, which is a real state
# and the one that should drive the next round of sampling.
MIN_N_TO_GATE = 5

_WS = re.compile(r"\s+")
_DECOR = re.compile(r"[🔹🩵•┈▪◾]+")


def _clean(t: str) -> str:
    return _WS.sub(" ", _DECOR.sub(" ", t or "")).strip()


# ── sampling ────────────────────────────────────────────────────────────────

SAMPLE_SQL = """
WITH ranked AS (
  SELECT cc.claim_id, cc.verdict, cc.incident_type, cc.reject_reason,
         cc.place_text, cc.governorate, cc.confidence,
         p.name_en AS resolved_place, c.raw_text, s.key AS source_key,
         row_number() OVER (PARTITION BY cc.verdict, cc.incident_type
                            ORDER BY md5(cc.claim_id::text)) AS rn
  FROM claim_classification cc
  JOIN claim c USING (claim_id)
  LEFT JOIN place p ON p.place_id = cc.place_id
  LEFT JOIN source s ON s.source_id = c.source_id
  WHERE cc.verdict = 'incident'
    AND NOT (cc.claim_id = ANY(%(exclude)s))
)
SELECT claim_id, verdict, incident_type, reject_reason, place_text, governorate,
       confidence, resolved_place, raw_text, source_key
FROM ranked WHERE rn <= %(cap)s
"""

REJECT_SQL = """
SELECT cc.claim_id, cc.verdict, cc.incident_type, cc.reject_reason,
       cc.place_text, cc.governorate, cc.confidence,
       p.name_en AS resolved_place, c.raw_text, s.key AS source_key
FROM claim_classification cc
JOIN claim c USING (claim_id)
LEFT JOIN place p ON p.place_id = cc.place_id
LEFT JOIN source s ON s.source_id = c.source_id
WHERE cc.verdict <> 'incident'
  -- 'too short' and 'gaza' are mechanical and not worth human time; the
  -- interesting rejects are the ones a rule decided against on meaning.
  -- NOTE this makes the miss rate a CONSERVATIVE (high) estimate: the
  -- mechanical rejects it skips are the ones most likely to be correct.
  AND coalesce(cc.reject_reason,'') NOT IN ('too short','gaza')
  AND NOT (cc.claim_id = ANY(%(exclude)s))
ORDER BY md5(cc.claim_id::text)
LIMIT %(limit)s
"""


def already_scored() -> set[int]:
    """Claim ids used in any previous round.

    ROUND 1 WAS SPENT, NOT REUSED. Its 163 claims found 43 defects and those
    defects were then fixed by editing the classifier's patterns — which makes
    those exact claims a tuning set. Re-scoring them would measure how well the
    rules were fitted to the examples they were written from, and would come
    back near 1.0 while telling us nothing. Every later round must be disjoint.
    """
    seen: set[int] = set()
    for f in (ROOT / "ops").glob("incident-scored*.ndjson"):
        for line in f.read_text().splitlines():
            if line.strip():
                seen.add(json.loads(line)["claim_id"])
    return seen


def draw_sample() -> int:
    exclude = sorted(already_scored())
    rows = []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SAMPLE_SQL, {"exclude": exclude, "cap": PER_TYPE_CAP})
        cols = [d[0] for d in cur.description]
        rows += [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute(REJECT_SQL, {"exclude": exclude, "limit": REJECT_SAMPLE})
        cols = [d[0] for d in cur.description]
        rows += [dict(zip(cols, r)) for r in cur.fetchall()]

    with SAMPLE_FILE.open("w") as fh:
        for r in rows:
            r["raw_text"] = _clean(r["raw_text"])[:400]
            r["confidence"] = float(r["confidence"]) if r["confidence"] else None
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


# ── scoring ─────────────────────────────────────────────────────────────────

def _wilson(k: int, n: int) -> tuple[float, float]:
    """95% Wilson interval. Used because the small types have n=2 and n=4, and
    a bare ratio there ("1.00 precision!") would be worse than no number."""
    if n == 0:
        return (0.0, 1.0)
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def score() -> dict:
    if not SCORED_FILE.exists():
        raise SystemExit(f"no scores at {SCORED_FILE} — score the sample first")
    scored = [json.loads(x) for x in SCORED_FILE.read_text().splitlines() if x.strip()]
    sample = {json.loads(x)["claim_id"]: json.loads(x)
              for x in SAMPLE_FILE.read_text().splitlines() if x.strip()}

    by_type: dict[str, list[dict]] = defaultdict(list)
    rejects: list[dict] = []
    for s in scored:
        src = sample.get(s["claim_id"])
        if not src:
            continue
        if src["verdict"] == "incident":
            by_type[src["incident_type"]].append(s)
        else:
            rejects.append(s)

    def rate(items, key):
        vals = [i[key] for i in items if i.get(key) is not None]
        return (sum(1 for v in vals if v), len(vals))

    per_type = {}
    for t, items in sorted(by_type.items()):
        inc_k, inc_n = rate(items, "is_incident")
        # type/place/west_bank are only meaningful where it IS an incident
        real = [i for i in items if i.get("is_incident")]
        typ_k, typ_n = rate(real, "type_ok")
        plc_k, plc_n = rate(real, "place_ok")
        wb_k, wb_n = rate(real, "west_bank")
        # "correct" = a served row that is right in every respect that applies
        good = sum(1 for i in items if i.get("is_incident") and i.get("type_ok")
                   and i.get("place_ok") and i.get("west_bank"))
        lo, hi = _wilson(good, len(items))
        per_type[t] = {
            "n": len(items), "precision": round(good / len(items), 3),
            "ci95": [round(lo, 3), round(hi, 3)],
            "is_incident": f"{inc_k}/{inc_n}", "type_ok": f"{typ_k}/{typ_n}",
            "place_ok": f"{plc_k}/{plc_n}", "west_bank": f"{wb_k}/{wb_n}",
        }

    all_items = [i for v in by_type.values() for i in v]
    good_all = sum(1 for i in all_items if i.get("is_incident") and i.get("type_ok")
                   and i.get("place_ok") and i.get("west_bank"))
    lo, hi = _wilson(good_all, len(all_items))

    missed = sum(1 for r in rejects if r.get("is_incident"))
    result = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "overall": {"n": len(all_items),
                    "precision": round(good_all / max(len(all_items), 1), 3),
                    "ci95": [round(lo, 3), round(hi, 3)]},
        "per_type": per_type,
        "rejects": {"n": len(rejects), "were_really_incidents": missed,
                    "miss_rate": round(missed / max(len(rejects), 1), 3)},
    }
    failing = [t for t, v in per_type.items()
               if v["n"] >= MIN_N_TO_GATE and v["precision"] < GATE_PER_TYPE]
    unmeasured = [t for t, v in per_type.items() if v["n"] < MIN_N_TO_GATE]
    result["gate"] = {
        "overall_required": GATE_OVERALL,
        "per_type_required": GATE_PER_TYPE,
        "min_n_to_gate": MIN_N_TO_GATE,
        "overall_pass": result["overall"]["precision"] >= GATE_OVERALL,
        "types_below_floor": failing,
        "types_unmeasured": unmeasured,
        "pass": result["overall"]["precision"] >= GATE_OVERALL and not failing,
    }
    RESULT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    # Append the round to a machine-readable history. RESULT_FILE holds only
    # the LATEST round, and the scored files hold claim verdicts with no
    # timestamp or classifier version — so "when was precision last measured,
    # and of WHICH classifier" was answerable only by a human reconstructing
    # it from file names. The weekly review (ops/measure_review.py) reads this
    # ledger to raise the round-is-due alarm.
    try:
        from ingest.sources.news_incidents import CLASSIFIER_VERSION
    except Exception:                                           # noqa: BLE001
        CLASSIFIER_VERSION = None
    with (ROOT / "ops" / "incident-rounds.ndjson").open("a") as fh:
        fh.write(json.dumps({
            "scored_at": result["measured_at"],
            "classifier_version": CLASSIFIER_VERSION,
            "overall": result["overall"], "gate_pass": result["gate"]["pass"],
            "types_unmeasured": result["gate"]["types_unmeasured"],
        }, ensure_ascii=False) + "\n")
    return result


def show(r: dict) -> None:
    o = r["overall"]
    print(f"incident classifier precision  {o['precision']:.3f} "
          f"[{o['ci95'][0]:.2f}–{o['ci95'][1]:.2f}]  n={o['n']}\n")
    print(f"  {'type':<16}{'n':>4}{'prec':>7}  {'95% CI':<14}"
          f"{'incident':>10}{'type':>8}{'place':>8}{'WB':>8}")
    for t, v in sorted(r["per_type"].items(), key=lambda x: x[1]["precision"]):
        flag = ("  <-- n too small to mean anything" if v["n"] < MIN_N_TO_GATE
                else "  <-- BELOW FLOOR" if v["precision"] < GATE_PER_TYPE else "")
        print(f"  {t:<16}{v['n']:>4}{v['precision']:>7.3f}  "
              f"{v['ci95'][0]:.2f}-{v['ci95'][1]:.2f}      "
              f"{v['is_incident']:>10}{v['type_ok']:>8}"
              f"{v['place_ok']:>8}{v['west_bank']:>8}{flag}")
    rj = r["rejects"]
    print(f"\n  rejects sampled {rj['n']}: {rj['were_really_incidents']} were real "
          f"incidents (miss rate {rj['miss_rate']:.1%})")
    g = r["gate"]
    print(f"\n  GATE {'PASS' if g['pass'] else 'FAIL'} "
          f"(need >={g['overall_required']} overall, "
          f">={g['per_type_required']} per type)")
    if g["types_below_floor"]:
        print(f"  below floor: {', '.join(g['types_below_floor'])}")
    if g.get("types_unmeasured"):
        print(f"  UNMEASURED (n < {g['min_n_to_gate']}): "
              f"{', '.join(g['types_unmeasured'])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.sample:
        n = draw_sample()
        print(f"{n} claims written to {SAMPLE_FILE}")
        print(f"score them into {SCORED_FILE} as one JSON object per line:")
        print('  {"claim_id":123,"is_incident":true,"type_ok":true,'
              '"place_ok":true,"west_bank":true,"note":"optional"}')
        return 0
    if a.show:
        show(json.loads(RESULT_FILE.read_text()))
        return 0
    if a.score:
        r = score()
        show(r)
        return 0 if r["gate"]["pass"] else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
