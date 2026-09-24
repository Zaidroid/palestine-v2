"""Project the place reader + resolver over the corpus WITHOUT writing.

    python ops/place_measure.py --scope gov_only            # the governorate-only events
    python ops/place_measure.py --scope named               # would today's named events move?
    python ops/place_measure.py --scope unlocated           # claims the reader found no place for
    python ops/place_measure.py --scope gov_only --sample 40 --out /tmp/x.ndjson

Reads the events (or claims) the current classifier produced, runs the CURRENT
`cascade.news.read` and `ingest.sources.news_incidents.locate` over their text
with `learn=False`, and reports what the next re-read would serve: how many
land on a named place, on the governorate, on nothing — by how the name was
read and how it resolved — plus the names that still resolve to nothing (the
list a gazetteer fix should start from) and a sample for a human to judge.

Nothing here writes: no alias is learnt, no event is touched.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cascade.news import read                                        # noqa: E402
from ingest.sources.news_incidents import CLASSIFIER, locate         # noqa: E402
from resolve.db import connect                                       # noqa: E402

SCOPES = {
    "gov_only": """
        SELECT e.event_id, e.place_id, e.attrs->>'place_precision', cc.claim_id, c.raw_text
          FROM event e
          JOIN claim_classification cc ON cc.event_id = e.event_id AND cc.classifier = %(clf)s
          JOIN claim c ON c.claim_id = cc.claim_id
         WHERE e.attrs->>'classifier' = %(clf)s AND e.status = 'believed'
           AND e.attrs->>'place_precision' IN ('governorate', 'village_ambiguous')
         ORDER BY e.event_id, cc.claim_id""",
    "named": """
        SELECT e.event_id, e.place_id, e.attrs->>'place_precision', cc.claim_id, c.raw_text
          FROM event e
          JOIN claim_classification cc ON cc.event_id = e.event_id AND cc.classifier = %(clf)s
          JOIN claim c ON c.claim_id = cc.claim_id
         WHERE e.attrs->>'classifier' = %(clf)s AND e.status = 'believed'
           AND COALESCE(e.attrs->>'place_precision', 'named') = 'named'
         ORDER BY e.event_id, cc.claim_id""",
    "unlocated": """
        SELECT NULL::bigint, NULL::int, NULL::text, cc.claim_id, c.raw_text
          FROM claim_classification cc JOIN claim c ON c.claim_id = cc.claim_id
         WHERE cc.classifier = %(clf)s AND cc.verdict = 'unclear'
           AND cc.reject_reason IN ('no resolvable West Bank place', 'place did not resolve')
         ORDER BY cc.claim_id""",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=SCOPES, default="gov_only")
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--out", help="ndjson of every projected row")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCOPES[a.scope], {"clf": CLASSIFIER})
        rows = cur.fetchall()
        units: dict = {}
        for event_id, place_id, prec, claim_id, text in rows:
            key = event_id if event_id is not None else f"c{claim_id}"
            u = units.setdefault(key, {"event_id": event_id, "old_place": place_id,
                                       "old_precision": prec, "claims": []})
            u["claims"].append((claim_id, text))

        outcome = Counter()
        how = Counter()
        method = Counter()
        rejected = Counter()
        moved = Counter()
        unresolved = Counter()
        names_to = Counter()
        projected = []
        for key, u in units.items():
            result = None
            for claim_id, text in u["claims"]:
                r = read(text)
                if r.verdict != "incident":
                    continue
                loc = locate(conn, r)
                result = (claim_id, text, r, loc)
                break
            if result is None:
                outcome["not_an_incident_now"] += 1
                continue
            claim_id, text, r, loc = result
            prec = loc.precision or "unresolved"
            outcome[prec] += 1
            for name, why in loc.rejected:
                rejected[why] += 1
            if prec == "named":
                how[loc.how] += 1
                method[loc.method] += 1
                names_to[(loc.named_place, loc.place_id)] += 1
                if a.scope == "named" and u["old_place"] != loc.place_id:
                    moved["moved"] += 1
            else:
                for name, _h in r.place_candidates[:2]:
                    unresolved[(name, r.governorate)] += 1
            projected.append({
                "key": str(key), "event_id": u["event_id"], "claim_id": claim_id,
                "old_place": u["old_place"], "old_precision": u["old_precision"],
                "type": r.incident_type, "governorate": r.governorate,
                "candidates": r.place_candidates, "precision": prec,
                "place_id": loc.place_id, "named_place": loc.named_place,
                "how": loc.how, "method": loc.method, "rejected": loc.rejected,
                "text": " ".join((text or "").split())[:220],
            })

        if a.scope == "named" or True:
            ids = sorted({p["place_id"] for p in projected if p["place_id"]})
            cur.execute("SELECT place_id, name_ar, name_en, kind::text FROM place WHERE place_id = ANY(%s)", (ids,))
            names = {pid: (ar or en or "?", kind) for pid, ar, en, kind in cur.fetchall()}
        for p in projected:
            p["place"] = names.get(p["place_id"], (None, None))[0]
            p["place_kind"] = names.get(p["place_id"], (None, None))[1]

    total = sum(outcome.values())
    print(f"scope={a.scope}  units={len(units)}  projected={total}")
    print("outcome :", dict(outcome.most_common()))
    print("named by:", dict(how.most_common()), "| method:", dict(method.most_common()))
    print("rejected:", dict(rejected.most_common()))
    if moved:
        print("moved   :", dict(moved))
    print("\nstill unresolved (name, governorate) — top 40:")
    for (name, gov), n in unresolved.most_common(40):
        print(f"  {n:4}  {name!r:30} {gov}")
    print("\nnamed placements — top 30 (name -> place):")
    for (name, pid), n in names_to.most_common(30):
        print(f"  {n:4}  {name!r:26} -> {pid} {names.get(pid, ('?',))[0]}")
    random.seed(a.seed)
    named_rows = [p for p in projected if p["precision"] == "named"]
    print(f"\nsample of {min(a.sample, len(named_rows))} named placements to judge:")
    for p in random.sample(named_rows, min(a.sample, len(named_rows))):
        print(f"- [{p['key']} {p['type']} {p['governorate']}] {p['named_place']!r} ({p['how']}/{p['method']}) -> "
              f"{p['place']} ({p['place_kind']})\n    {p['text'][:170]}")
    if a.out:
        with open(a.out, "w") as f:
            for p in projected:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(f"\nwrote {len(projected)} rows to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
