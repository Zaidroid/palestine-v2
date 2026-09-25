"""What a classifier bump WOULD change on the real corpus — read-only.

    python ops/project_classifier.py            # every stored classification
    python ops/project_classifier.py --limit 5  # samples per change (default 5)

Bumping CLASSIFIER_VERSION makes the news timer re-read every claim and write
the new verdicts (and sweep superseded events) at its next tick, on the live
tree. This runs the working tree's cascade.news.read() over the same stored
texts and compares with the stored verdicts, in a READ ONLY session: nothing is
written. Run it from a separate worktree before the bump goes live, and read
the samples of every change — above all anything that stops being a closure or
starts being one.

This is a projection over the whole corpus, not a precision number; precision
comes only from a hand-scored round (learn/incident_precision.py).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cascade.news import read                                      # noqa: E402
from ingest.sources.news_incidents import CLASSIFIER, CLASSIFIER_VERSION  # noqa: E402
from resolve.db import connect                                     # noqa: E402


def _label(verdict, itype, reason) -> str:
    return itype if verdict == "incident" else f"{verdict}:{reason or '-'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5, help="sample claim ids per change")
    a = ap.parse_args()
    moves: Counter = Counter()
    samples: dict = defaultdict(list)
    stored_versions: Counter = Counter()
    n = 0
    unlocated = 0
    with connect() as conn:
        conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        with conn.cursor(name="project") as cur:          # server-side: the corpus is large
            cur.execute("""SELECT c.claim_id, c.raw_text, cc.classifier_version,
                                  cc.verdict, cc.incident_type, cc.reject_reason
                             FROM claim c JOIN claim_classification cc USING (claim_id)
                            WHERE cc.classifier = %s""", (CLASSIFIER,))
            for cid, text, ver, verdict, itype, reason in cur:
                n += 1
                stored_versions[ver] += 1
                r = read(text)
                old = _label(verdict, itype, reason)
                new = _label(r.verdict, r.incident_type, r.reject_reason)
                # read() is the RULE stage; the stored verdict is after the
                # LOCATION stage. A stored 'place did not resolve' against a
                # read() incident is the same rule reading, so it is not a
                # change of the rules (2026-09-25: 426 of 435 'changes' in the
                # 1.9.0 projection were this and hid the 9 real ones).
                if old == "unclear:place did not resolve" and r.verdict == "incident":
                    unlocated += 1
                    continue
                if old != new:
                    moves[(old, new)] += 1
                    if len(samples[(old, new)]) < a.limit:
                        samples[(old, new)].append(cid)
        conn.rollback()
    print(f"working tree = {CLASSIFIER_VERSION}; stored: "
          + ", ".join(f"{v} x{c}" for v, c in stored_versions.most_common()))
    print(f"{n} stored classifications; {sum(moves.values())} would change "
          f"({unlocated} unlocated incidents compared at the rule stage only)")
    for (old, new), c in moves.most_common():
        print(f"  {c:6d}  {old}  ->  {new}   e.g. claim {samples[(old, new)]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
