"""Loop A — learn how much each REPORTER is worth, from measured agreement.

    .venv/bin/python -m learn.reliability --days 30
    .venv/bin/python -m learn.reliability --days 30 --write

WHY THIS EXISTS
`source.reliability` has been NULL for all 42 sources since migration 003, which
says "NULL until measured — never seed by hand". It was never measured, so every
source is trusted at a flat 0.70: `a7walstreet`, which is first-reporter 74% of
the time and sole reporter 53%, counts for exactly as much as a channel that
only reposts other people's messages.

REPORTERS, NOT CHANNELS
Deliberately written over "reporters" rather than Telegram channels, because
[ZAID]'s scope for P2 is an engine that tracks crowd reports across every field
tier 1 covers, and this is the reputation model it runs on. A reporter is
anything that makes a claim — a channel, an API, a scraper, or a person with a
phone. Nothing below knows which it is dealing with, and nothing below is tuned
to checkpoints.

CONSENSUS IS PER INDEPENDENCE UNIT, ONE VOTE EACH
The single most repeated lesson in this project: nine of the road channels agree
99.5-100% of the time and are ONE observer. So the vote is taken across
independence units, never across messages. Without that, a copy-paste ring of
five would outvote a first-hand reporter five to one — which is precisely the
attack P2 has to survive, where the ring is one person with five phones.

WHY A SHORT WINDOW
Two observations are only comparable if the world cannot reasonably have changed
between them. Compared six hours apart, disagreement means the checkpoint
reopened, not that anybody was wrong. The window is derived from the state's own
MEASURED persistence (`state_kind_config.half_life_seconds`), so a fast-moving
kind is compared over minutes and a slow one over hours, and no constant here
has to be guessed.

REPUTATION IS EARNED, NEVER SEEDED
The posterior mean of Beta(1+hits, 1+misses) is stored in `reliability`, and the
number that should be USED is the lower bound of its interval, which
`trust()` returns. That is what makes a new reporter start low without any
special-casing: 1 correct report out of 1 has a posterior mean of 0.67 but a
lower bound of 0.21, while 90 out of 100 has a mean of 0.89 and a lower bound of
0.82. Evidence, not enthusiasm, moves it. A brand-new crowd submitter therefore
begins near zero and climbs only by being right about things other people
independently confirm — with no separate rule to enforce it.

WHAT THIS CANNOT MEASURE, AND SAYS SO
A kind with one independence unit has no second observer and is reported as
UNMEASURABLE rather than given a number. That covers fuel (palhub only), weather
(Open-Meteo only) and internet (IODA only). Scoring those against themselves
would report ~99% and mean nothing, which is the same error as counting copied
channels as corroboration.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect  # noqa: E402

OUT = ROOT / "ops" / "reliability.ndjson"

# Beta(1,1) — uniform. A weak, symmetric prior is the only honest starting point
# when the instruction is "never seed by hand": it encodes no opinion, and it is
# the interval width rather than the prior that keeps a new reporter cautious.
PRIOR_A = 1.0
PRIOR_B = 1.0

# Comparison window as a fraction of the kind's own half-life. A third means
# persistence across the window is ~0.79, so a disagreement is much more likely
# to be an error than a real change.
WINDOW_FRACTION = 3.0
MIN_WINDOW_S = 300
MAX_WINDOW_S = 7200

# A reporter needs this much evidence before it counts as "established" and can
# define the plateau that everyone else is normalised against. Below it the
# interval is too wide for the bound to mean much.
ESTABLISHED_N = 100


def wilson_lower(hits: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the score interval — the number to actually trust."""
    if n == 0:
        return 0.0
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half)


def trust(reliability: float | None, n: int | None) -> float | None:
    """What a caller should actually multiply by. None when unmeasured, so the
    caller decides its own fallback rather than silently getting 0.5."""
    if reliability is None or not n:
        return None
    hits = reliability * (n + PRIOR_A + PRIOR_B) - PRIOR_A
    return round(wilson_lower(max(0.0, hits), n), 4)


KINDS_SQL = """
SELECT o.state_kind,
       COALESCE(c.half_life_seconds, 3600) AS half_life,
       count(DISTINCT COALESCE(s.independence_group, 'src:' || s.source_id::text)) AS units
FROM state_observation o
JOIN source s USING (source_id)
LEFT JOIN state_kind_config c ON c.state_kind = o.state_kind
WHERE o.observed_at > now() - make_interval(days => %(days)s)
  AND o.modality = 'assertion'
GROUP BY 1, 2
ORDER BY 1
"""

# DISTINCT ON collapses the historical duplicate rows: palhub re-inserted the
# same observation up to 490 times before migration 023, and counting those as
# separate reports would have handed one feed 66x the weight of every other.
OBS_SQL = """
SELECT DISTINCT ON (o.place_id, o.direction, o.observed_at, o.source_id, o.value)
       o.place_id, o.direction, o.observed_at, o.value, o.source_id,
       COALESCE(s.independence_group, 'src:' || s.source_id::text) AS unit
FROM state_observation o
JOIN source s USING (source_id)
WHERE o.state_kind = %(kind)s
  AND o.modality = 'assertion'
  AND o.observed_at > now() - make_interval(days => %(days)s)
ORDER BY o.place_id, o.direction, o.observed_at, o.source_id, o.value
"""


def score_kind(cur, kind: str, days: int, window_s: int) -> dict:
    """Per-source hits and misses against independent consensus."""
    cur.execute(OBS_SQL, {"kind": kind, "days": days})
    rows = cur.fetchall()

    # (place, direction, time bucket) -> unit -> {value: [source_ids]}
    buckets: dict[tuple, dict[str, dict[str, list[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    # A 'both' report speaks for each travel direction — the serving view reads
    # it that way (079: inbound/outbound are the freshest of that direction OR
    # 'both'). Until 2026-09-26 the learner did not, so a reporter that files
    # directions separately (palhub: every bulletin row is دخول/خروج) had no
    # peer in its buckets: 21 comparisons in 30 days, a Wilson lower bound of
    # 0.245, trust_weight 0.274 — and at 03:21 that single write took the
    # known-fraction from 0.59 to 0.06, undoing an earn-out measured at ≥ 0.90.
    # A 'both' reading now WITNESSES the inbound and outbound buckets: it votes
    # there, but is scored only in its own 'both' bucket, so no reporter is
    # counted twice.
    witnesses: dict[tuple, dict[str, dict[str, list[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    for place_id, direction, observed_at, value, source_id, unit in rows:
        b = int(observed_at.timestamp()) // window_s
        buckets[(place_id, direction, b)][unit][value].append(source_id)
        if direction == "both":
            for d in ("inbound", "outbound"):
                witnesses[(place_id, d, b)][unit][value].append(source_id)

    return _score_buckets(buckets, kind, window_s, witnesses)


def _score_buckets(buckets, kind: str, window_s: int, witnesses=None) -> dict:
    """LEAVE-ONE-OUT (audit F110): each unit is scored against the majority of
    the OTHER units in its bucket. The old consensus included the unit's own
    vote, so a two-unit bucket could never record a miss and every unit was
    partly judging itself. With two units the other one is the consensus: a
    disagreement is a miss for both, an agreement a hit for both. A tie among
    the others scores nobody and is counted."""
    per_source: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # hits, misses
    # (source_value, consensus_value) counts per source, for chance correction.
    joint: dict[int, Counter] = defaultdict(Counter)
    compared = ties = singleton = 0

    for key, by_unit in buckets.items():
        # witnesses: units that spoke for this direction with a 'both' report
        # and are not already here — they vote, they are not scored
        wit = {u: v for u, v in ((witnesses or {}).get(key) or {}).items()
               if u not in by_unit}
        if len(by_unit) + len(wit) < 2:
            singleton += 1
            continue
        # ONE VOTE PER UNIT. A unit that reported two different values inside
        # the window is internally inconsistent and abstains rather than voting
        # twice — it cannot be evidence about anybody else.
        votes: Counter = Counter()
        unit_value: dict[str, str] = {}
        for unit, vals in by_unit.items():
            if len(vals) != 1:
                continue
            v = next(iter(vals))
            unit_value[unit] = v
            votes[v] += 1
        witness_value = {u: next(iter(vals)) for u, vals in wit.items() if len(vals) == 1}
        if not unit_value or len(unit_value) + len(witness_value) < 2:
            singleton += 1
            continue
        compared += 1
        scored_any = False
        everyone = {**witness_value, **unit_value}
        for unit, v in unit_value.items():
            others = Counter(v2 for u2, v2 in everyone.items() if u2 != unit)
            top = others.most_common()
            if len(top) > 1 and top[0][1] == top[1][1]:
                continue                      # the others tie: this unit is not scored
            consensus = top[0][0]
            scored_any = True
            hit = v == consensus
            for sid in by_unit[unit][v]:
                per_source[sid][0 if hit else 1] += 1
                joint[sid][(v, consensus)] += 1
        if not scored_any:
            ties += 1

    return {"state_kind": kind, "window_s": window_s,
            "buckets": len(buckets), "compared": compared, "ties": ties,
            "no_second_unit": singleton,
            "per_source": {sid: {"hits": h, "misses": m}
                           for sid, (h, m) in per_source.items()},
            "joint": {sid: dict(c) for sid, c in joint.items()}}


def kappa(joint: Counter) -> float | None:
    """Cohen's kappa between a reporter and the independent consensus.

    RAW AGREEMENT IS NOT SKILL. `open` is roughly 88% of all checkpoint
    readings, so a reporter that said "open" every single time and understood
    nothing would score ~0.88 raw. Kappa subtracts the agreement you would get
    by chance from the two marginal distributions and rescales, so 0 means "no
    better than guessing with the right frequencies" and 1 means perfect.

    This is the same correction the persistence work already applies when it
    calls `open`'s flat tail the base rate rather than knowledge.
    """
    n = sum(joint.values())
    if not n:
        return None
    obs = sum(c for (a, b), c in joint.items() if a == b) / n
    src: Counter = Counter()
    con: Counter = Counter()
    for (a, b), c in joint.items():
        src[a] += c
        con[b] += c
    exp = sum((src[v] / n) * (con[v] / n) for v in set(src) | set(con))
    if exp >= 1.0:
        # Only one value was ever seen — agreement is guaranteed and says
        # nothing at all. Undefined, not 1.0.
        return None
    return round((obs - exp) / (1 - exp), 4)


def run(days: int, write: bool) -> dict:
    measured_at = datetime.now(timezone.utc)
    totals: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    joint_all: dict[int, Counter] = defaultdict(Counter)
    per_kind: list[dict] = []
    unmeasurable: list[str] = []

    with connect() as conn, conn.cursor() as cur:
        cur.execute(KINDS_SQL, {"days": days})
        kinds = cur.fetchall()
        for kind, half_life, units in kinds:
            if units < 2:
                unmeasurable.append(kind)
                continue
            window = int(min(MAX_WINDOW_S,
                             max(MIN_WINDOW_S, (half_life or 3600) / WINDOW_FRACTION)))
            k = score_kind(cur, kind, days, window)
            per_kind.append(k)
            for sid, hm in k["per_source"].items():
                totals[sid][0] += hm["hits"]
                totals[sid][1] += hm["misses"]
            for sid, jj in k["joint"].items():
                for pair, c in jj.items():
                    joint_all[sid][pair] += c

        cur.execute("SELECT source_id, key, COALESCE(independence_group,'') FROM source")
        names = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        sources = []
        for sid, (hits, misses) in sorted(totals.items(),
                                          key=lambda kv: -(kv[1][0] + kv[1][1])):
            n = hits + misses
            mean = (hits + PRIOR_A) / (n + PRIOR_A + PRIOR_B)
            sources.append({
                "source_id": sid, "key": names.get(sid, ("?", ""))[0],
                "independence_group": names.get(sid, ("", ""))[1] or None,
                "hits": hits, "misses": misses, "n": n,
                "reliability": round(mean, 4),
                "trust": round(wilson_lower(hits, n), 4),
                "kappa": kappa(joint_all[sid]),
            })

        # The plateau is the trust an ESTABLISHED reporter reaches — measured,
        # not chosen. Everyone is normalised against it so that a well-evidenced
        # reporter scores 1.0 and keeps the globally calibrated base confidence,
        # while a new or contradicted one is discounted in proportion.
        established = [s["trust"] for s in sources if s["n"] >= ESTABLISHED_N]
        plateau = (sorted(established)[len(established) // 2]
                   if established else None)
        for s in sources:
            s["trust_weight"] = (round(min(1.0, s["trust"] / plateau), 4)
                                 if plateau else None)

        if write:
            for s in sources:
                cur.execute("""
                    UPDATE source SET reliability = %s, reliability_n = %s,
                                      reliability_trust = %s, trust_weight = %s,
                                      reliability_measured_at = %s
                    WHERE source_id = %s""",
                            (s["reliability"], s["n"], s["trust"],
                             s["trust_weight"] or None, measured_at, s["source_id"]))
            conn.commit()

    result = {
        "measured_at": measured_at.isoformat(), "window_days": days,
        "plateau_trust": plateau,
        "kinds_measured": [k["state_kind"] for k in per_kind],
        "kinds_unmeasurable": unmeasurable,
        "per_kind": [{k: v for k, v in d.items() if k not in ("per_source", "joint")}
                     for d in per_kind],
        "sources": sources,
        "written": write,
    }
    if write:
        with OUT.open("a") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--write", action="store_true",
                    help="persist to source.reliability / reliability_n")
    a = ap.parse_args()
    r = run(a.days, a.write)

    print(f"reporter reliability · {a.days}d · "
          f"measured {len(r['kinds_measured'])} kinds, "
          f"{len(r['kinds_unmeasurable'])} unmeasurable "
          f"({', '.join(r['kinds_unmeasurable']) or 'none'})\n")
    for k in r["per_kind"]:
        print(f"  {k['state_kind']:<24} window {k['window_s']:>5}s · "
              f"{k['compared']:>6} scored · {k['ties']:>4} ties · "
              f"{k['no_second_unit']:>6} with no second unit")
    print(f"\n  {'source':<24}{'group':<14}{'n':>7}{'miss':>6}"
          f"{'agree':>8}{'trust':>8}{'kappa':>8}{'weight':>8}")
    for s in r["sources"]:
        kp = f"{s['kappa']:.3f}" if s["kappa"] is not None else "n/a"
        wt = ("n/a" if s.get("trust_weight") is None
              else f"{s['trust_weight']:.3f}")
        print(f"  {s['key'][:23]:<24}{(s['independence_group'] or '-')[:13]:<14}"
              f"{s['n']:>7}{s['misses']:>6}{s['reliability']:>8.3f}"
              f"{s['trust']:>8.3f}{kp:>8}{wt:>8}")
    unscored = 42 - len(r["sources"])
    print(f"\n  {len(r['sources'])} reporters scored · "
          f"~{unscored} have no state observations to score against")
    if a.write:
        print("  written to source.reliability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
