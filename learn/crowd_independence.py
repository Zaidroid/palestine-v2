"""P2.3 — submitters earn their own independence unit, or they do not.

    .venv/bin/python -m learn.crowd_independence            # report
    .venv/bin/python -m learn.crowd_independence --write    # promote/demote

Commitment 3 of the scope: self-improving, on a timer, with nobody deciding.
This runs nightly beside Loop A.

WHAT IT DECIDES
Every submitter starts in the shared group `crowd:unverified`, where any number
of accounts count as ONE observer. That is what makes a sock-puppet ring
harmless, and it is also, deliberately, what makes a genuine new reporter
harmless. Nobody's word counts on its own until it has been shown to be their
own word.

Separation is granted on exactly the evidence copy-collapse uses for channels,
pointed the other way. `learn/source_independence.py` asks "do these two agree
so often that they are one observer?" and merges them. This asks the same
question of a submitter against everyone already inside the crowd unit, and
SPLITS them out when the answer is no:

    enough co-observed history      MIN_CO_OBSERVATIONS
    agreement below the copy line   AGREEMENT_THRESHOLD
    a reputation that has been measured at all (Loop A, n >= MIN_SCORED)

An adversary can satisfy this only by running five accounts that genuinely
disagree with each other over hundreds of observations — which is to say, by
behaving like five different people. At that point the distinction stops being
meaningful, which is the property we want: the defence is not a detector that
can be fooled, it is a cost that scales with the thing being faked.

DEMOTION IS PART OF IT
An earned unit can be taken back. If two independent submitters drift into
lockstep — one person acquiring a second phone, or two friends copying each
other — they are merged back. A promotion that could never be reversed would be
a one-way ratchet an attacker only has to win once.

WHY IT IS NOT A REPUTATION SCORE
Loop A already measures whether a reporter is RIGHT. This measures whether they
are SEPARATE. They are different questions and a system that conflates them
gets both wrong: five accurate sock puppets would look like five trustworthy
observers, and one lone eccentric who is often wrong would still be genuinely
independent evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect                          # noqa: E402

OUT = ROOT / "ops" / "crowd_independence.ndjson"

# Two reporters agreeing at or above this rate are treated as one observer —
# the same line copy-collapse draws for channels, where nine road feeds agree
# 99.5-100% of the time and are one voice.
AGREEMENT_THRESHOLD = 0.98

# Below this many co-observations, an agreement rate is a coincidence. A
# submitter who has been right about three checkpoints alongside somebody else
# has not demonstrated anything about independence.
MIN_CO_OBSERVATIONS = 30

# And they must have been scored by Loop A at all. Independence without a
# measured reliability would let a submitter earn their own unit purely by
# reporting things nobody else reports — which is indistinguishable from
# inventing them.
MIN_SCORED = 20

# Two observations further apart than this are describing different moments,
# not agreeing or disagreeing about one.
WINDOW_SECONDS = 900

PAIRS_SQL = f"""
WITH crowd_obs AS (
  SELECT o.source_id, o.place_id, o.state_kind, o.direction, o.value, o.observed_at
    FROM state_observation o
    JOIN source s USING (source_id)
   WHERE s.kind = 'crowd' AND o.modality = 'assertion'
     AND o.observed_at > now() - interval '%(days)s days'
)
SELECT a.source_id AS a_id, b.source_id AS b_id,
       count(*) AS co_obs,
       count(*) FILTER (WHERE a.value = b.value) AS agree
  FROM crowd_obs a
  JOIN crowd_obs b
    ON  b.place_id   = a.place_id
    AND b.state_kind = a.state_kind
    AND b.direction  = a.direction
    AND b.source_id  > a.source_id
    AND abs(extract(epoch FROM (b.observed_at - a.observed_at))) <= {WINDOW_SECONDS}
 GROUP BY 1, 2
"""

SCORED_SQL = """
SELECT s.source_id, sub.handle, s.reliability_n, s.independence_group,
       sub.independent_since
  FROM submitter sub
  JOIN source s USING (source_id)
 WHERE sub.status = 'active'
"""


def analyse(days: int = 30) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCORED_SQL)
        subs = {r[0]: {"source_id": r[0], "handle": r[1], "n": r[2] or 0,
                       "group": r[3], "independent_since": r[4]}
                for r in cur.fetchall()}
        cur.execute(PAIRS_SQL % {"days": days})
        pairs = [{"a": a, "b": b, "co_obs": n, "agree": k,
                  "rate": k / n if n else None}
                 for a, b, n, k in cur.fetchall()]

    # A submitter is a copy of somebody if ANY partner with enough shared
    # history agrees with them above the line. One lockstep partner is enough:
    # independence is a claim about being nobody else's echo, and a single echo
    # falsifies it.
    copies: dict[int, dict] = {}
    measured: dict[int, int] = {}
    for p in pairs:
        for x, y in ((p["a"], p["b"]), (p["b"], p["a"])):
            measured[x] = measured.get(x, 0) + p["co_obs"]
            if p["co_obs"] >= MIN_CO_OBSERVATIONS and p["rate"] >= AGREEMENT_THRESHOLD:
                prev = copies.get(x)
                if not prev or p["rate"] > prev["rate"]:
                    copies[x] = {"partner": y, "rate": p["rate"],
                                 "co_obs": p["co_obs"]}

    promote, demote, waiting = [], [], []
    for sid, s in subs.items():
        earned = s["independent_since"] is not None
        co = measured.get(sid, 0)
        why = None
        if sid in copies:
            why = (f"agrees {copies[sid]['rate']:.3f} with source "
                   f"{copies[sid]['partner']} over {copies[sid]['co_obs']} "
                   f"co-observations — one voice, not two")
            if earned:
                demote.append({**s, "reason": why})
            else:
                waiting.append({**s, "reason": why})
        elif s["n"] < MIN_SCORED:
            why = f"Loop A has scored {s['n']} of {MIN_SCORED} needed reports"
            waiting.append({**s, "reason": why})
        elif co < MIN_CO_OBSERVATIONS:
            why = (f"{co} of {MIN_CO_OBSERVATIONS} co-observations with other "
                   f"submitters — not enough shared ground to show they differ")
            waiting.append({**s, "reason": why})
        elif not earned:
            promote.append({**s, "reason":
                            f"scored on {s['n']} reports, {co} co-observations, "
                            f"no partner above {AGREEMENT_THRESHOLD}"})

    return {"submitters": len(subs), "pairs": len(pairs),
            "promote": promote, "demote": demote, "waiting": waiting}


def apply_changes(result: dict) -> int:
    n = 0
    with connect() as conn, conn.cursor() as cur:
        for s in result["promote"]:
            cur.execute("""UPDATE source SET independence_group = %s,
                             independence_note = %s, independence_measured_at = now()
                            WHERE source_id = %s""",
                        (f"crowd:{s['handle']}",
                         f"Earned an independent unit: {s['reason']}",
                         s["source_id"]))
            cur.execute("""UPDATE submitter SET independent_since = now()
                            WHERE source_id = %s""", (s["source_id"],))
            n += 1
        for s in result["demote"]:
            cur.execute("""UPDATE source SET independence_group = 'crowd:unverified',
                             independence_note = %s, independence_measured_at = now()
                            WHERE source_id = %s""",
                        (f"Merged back into the shared unit: {s['reason']}",
                         s["source_id"]))
            cur.execute("""UPDATE submitter SET independent_since = NULL
                            WHERE source_id = %s""", (s["source_id"],))
            n += 1
        conn.commit()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--write", action="store_true", help="apply promotions/demotions")
    a = ap.parse_args()

    r = analyse(a.days)
    print(f"crowd independence · {r['submitters']} active submitter(s) · "
          f"{r['pairs']} co-observed pair(s)")
    for s in r["promote"]:
        print(f"  PROMOTE @{s['handle']}: {s['reason']}")
    for s in r["demote"]:
        print(f"  DEMOTE  @{s['handle']}: {s['reason']}")
    for s in r["waiting"]:
        print(f"  waiting @{s['handle']}: {s['reason']}")
    if not r["submitters"]:
        print("  no submitters yet — the engine is live and nobody has registered")

    if a.write:
        n = apply_changes(r)
        print(f"  applied {n} change(s)")
        OUT.parent.mkdir(exist_ok=True)
        with OUT.open("a") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                 "promoted": [s["handle"] for s in r["promote"]],
                                 "demoted": [s["handle"] for s in r["demote"]],
                                 "waiting": len(r["waiting"])},
                                ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
