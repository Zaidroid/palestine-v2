"""Re-read a scored precision round with the CURRENT classifier, without a DB.

    python ops/rescore_round.py 7

The hand labels in ops/incident-scored-roundN.ndjson were judged against the
verdicts in ops/incident-sample-roundN.ndjson (which carries raw_text). Running
cascade.news.read() over the same texts says what a newer classifier would have
SERVED from that sample and how many of the hand-judged rows it keeps:

  kept_right    served then and now, labelled correct
  kept_wrong    served then and now, labelled wrong   (still costs precision)
  dropped_wrong served then, not now, labelled wrong  (the fix working)
  dropped_right served then, not now, labelled right  (a new false negative)
  type_moved    served then and now with a DIFFERENT type — the old type_ok
                label no longer applies; these need a human re-judge and are
                counted OUT of the precision below

Precision here = kept_right / (kept_right + kept_wrong). It is a projection
from an old sample, not a new round: a real round draws a fresh sample.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cascade.news import read                                       # noqa: E402
from ingest.sources.news_incidents import CLASSIFIER_VERSION        # noqa: E402


def main(n: str) -> int:
    sample = {json.loads(x)["claim_id"]: json.loads(x)
              for x in (ROOT / "ops" / f"incident-sample-round{n}.ndjson").read_text().splitlines()
              if x.strip()}
    scored = [json.loads(x) for x in (ROOT / "ops" / f"incident-scored-round{n}.ndjson")
              .read_text().splitlines() if x.strip()]
    # A human re-judgement of rows whose type moved (ops/incident-rejudged-
    # roundN-<version>.ndjson: claim_id, type_now, is_incident, type_ok) turns
    # `type_moved` back into kept_right / kept_wrong for that version.
    rejudged: dict[int, dict] = {}
    rj = ROOT / "ops" / f"incident-rejudged-round{n}-{CLASSIFIER_VERSION}.ndjson"
    if rj.exists():
        rejudged = {json.loads(x)["claim_id"]: json.loads(x)
                    for x in rj.read_text().splitlines() if x.strip()}
    tally: Counter = Counter()
    by_type: dict[str, Counter] = {}
    reasons: Counter = Counter()
    for s in scored:
        src = sample.get(s["claim_id"])
        if not src or src.get("verdict") != "incident":
            continue
        right = bool(s.get("is_incident") and s.get("type_ok") and s.get("place_ok")
                     and s.get("west_bank"))
        r = read(src.get("raw_text"))
        t = src.get("incident_type") or "?"
        slot = by_type.setdefault(t, Counter())
        if r.verdict != "incident":
            key = "dropped_right" if right else "dropped_wrong"
            reasons[f"{r.verdict}:{r.reject_reason}"] += 1
        elif r.incident_type != t:
            j = rejudged.get(s["claim_id"])
            if j and j.get("type_now") == r.incident_type:
                ok = bool(j.get("is_incident") and j.get("type_ok")
                          and s.get("place_ok") and s.get("west_bank"))
                key = "kept_right" if ok else "kept_wrong"
                reasons[f"rejudged:{t}->{r.incident_type}:{'right' if ok else 'wrong'}"] += 1
            else:
                key = "type_moved"
                reasons[f"moved:{t}->{r.incident_type}"] += 1
        else:
            key = "kept_right" if right else "kept_wrong"
        tally[key] += 1
        slot[key] += 1
    kr, kw = tally["kept_right"], tally["kept_wrong"]
    out = {"round": n, "classifier_version": CLASSIFIER_VERSION,
           "served_then": sum(tally.values()), "tally": dict(tally),
           "projected_precision": round(kr / max(kr + kw, 1), 3),
           "per_type": {t: {"tally": dict(c),
                            "projected_precision": round(c["kept_right"] /
                                                         max(c["kept_right"] + c["kept_wrong"], 1), 3)}
                        for t, c in sorted(by_type.items())},
           "why_dropped_or_moved": dict(reasons.most_common()),
           "rejudged": len(rejudged),
           "note": "projection over the old sample; type_moved rows need a human re-judge"}
    path = ROOT / "ops" / f"incident-precision-round{n}-rescored-{CLASSIFIER_VERSION}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({k: out[k] for k in ("classifier_version", "served_then", "tally",
                                          "projected_precision")}, ensure_ascii=False))
    for t, v in out["per_type"].items():
        print(f"  {t:16s} {v['projected_precision']:.3f}  {v['tally']}")
    print("  why:", out["why_dropped_or_moved"])
    print("->", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "7"))
