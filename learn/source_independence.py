"""Measure which channels are actually independent, and collapse the copies.

    .venv/bin/python -m learn.source_independence --report
    .venv/bin/python -m learn.source_independence --apply

Corroboration is only meaningful between observers who could have disagreed.
Measured over co-observations of the same place, same direction, within ten
minutes:

    ahwalaltorq  ~ rsdrasd            672 pairs   100.0% agree
    areenablus   ~ rsdrasd            672 pairs   100.0%
    ahwalaltareq ~ areenablus         619 pairs   100.0%
    roaddconditions ~ rsdrasd         679 pairs    99.9%
    …
    a7walstreet  ~ roaddconditions   1195 pairs    81.1%

Perfect agreement across hundreds of independent chances is not seven sources
confirming each other — it is one source republished seven times. Counting them
separately would turn a single unverified report into "corroborated by seven
channels", which is worse than having no corroboration model at all, because it
looks like evidence.

a7walstreet, disagreeing about one time in five, is a real second observer, and
its agreement is worth something precisely because it could have differed.

So: agreement is measured, channels above the threshold are merged into one
independence unit by transitive closure, and confidence counts UNITS. Nothing
here is hand-assigned — rerunning on new data can split or merge groups as the
channels' behaviour changes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect

# A pair must be this similar, over at least this many chances to differ,
# before we treat them as one voice. 0.98 sits in the empty band between the
# copy cluster (99.2-100%) and the nearest genuine observer (96.9%), so the
# split is read off the data rather than imposed on it.
AGREEMENT_THRESHOLD = 0.98
MIN_CO_OBSERVATIONS = 100
WINDOW_SECONDS = 600

MEASURE_SQL = """
WITH o AS (
  SELECT so.place_id, so.state_kind, so.direction, so.source_id, so.value, so.observed_at
  FROM state_observation so
  JOIN source s ON s.source_id = so.source_id AND s.kind <> 'crowd'   -- never measured here (audit F004)
  WHERE so.state_kind = ANY(%(kinds)s) AND so.modality = 'assertion'
    AND so.observed_at > now() - INTERVAL '90 days'
),
pairs AS (
  SELECT a.source_id AS sa, b.source_id AS sb, a.state_kind,
         (a.value = b.value)::int AS agreed
  FROM o a
  JOIN o b
    ON  a.place_id   = b.place_id
    AND a.state_kind = b.state_kind
    AND a.direction  = b.direction
    AND a.source_id  < b.source_id
    AND b.observed_at BETWEEN a.observed_at - make_interval(secs => %(win)s)
                          AND a.observed_at + make_interval(secs => %(win)s)
)
INSERT INTO source_agreement
  (source_a, source_b, state_kind, co_observations, agreements,
   agreement_rate, window_seconds, computed_at)
SELECT sa, sb, state_kind, COUNT(*), SUM(agreed),
       SUM(agreed)::real / COUNT(*), %(win)s, now()
FROM pairs
GROUP BY 1,2,3
HAVING COUNT(*) >= %(min_co)s
ON CONFLICT (source_a, source_b, state_kind) DO UPDATE SET
  co_observations = EXCLUDED.co_observations,
  agreements      = EXCLUDED.agreements,
  agreement_rate  = EXCLUDED.agreement_rate,
  window_seconds  = EXCLUDED.window_seconds,
  computed_at     = now()
"""


class _Union:
    """Union-find, smallest member id as the representative so group names are
    stable across reruns."""

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            lo, hi = min(ra, rb), max(ra, rb)
            self.parent[hi] = lo


def measure(kinds: list[str]) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(MEASURE_SQL, {"kinds": kinds, "win": WINDOW_SECONDS,
                                  "min_co": MIN_CO_OBSERVATIONS})
        n = cur.rowcount
        conn.commit()
    return n


def cluster(apply_changes: bool) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT a.source_a, a.source_b, a.agreement_rate, a.co_observations,
                   sa.key, sb.key
            FROM source_agreement a
            JOIN source sa ON sa.source_id = a.source_a
            JOIN source sb ON sb.source_id = a.source_b
            ORDER BY a.agreement_rate DESC""")
        rows = cur.fetchall()

        # A CROWD SUBMITTER IS NEVER TOUCHED HERE (audit F004, critical): the
        # nightly collapse could write NULL or a copyset over crowd:unverified
        # and grant independence that was never earned. crowd_independence is
        # the sole writer of crowd groups.
        cur.execute("SELECT source_id FROM source WHERE kind = 'crowd'")
        crowd = {r[0] for r in cur.fetchall()}
        uf = _Union()
        merged: list[tuple[str, str, float, int]] = []
        for sa, sb, rate, n, ka, kb in rows:
            if sa in crowd or sb in crowd:
                continue
            uf.find(sa); uf.find(sb)
            if rate >= AGREEMENT_THRESHOLD and n >= MIN_CO_OBSERVATIONS:
                uf.union(sa, sb)
                merged.append((ka, kb, rate, n))

        groups: dict[int, list[int]] = {}
        for sid in uf.parent:
            groups.setdefault(uf.find(sid), []).append(sid)

        assignments: list[tuple[str | None, str | None, int]] = []
        for rep, members in groups.items():
            if len(members) < 2:
                # A lone source is independent by definition; clearing any old
                # group matters, because a channel can stop being a copy.
                for sid in members:
                    assignments.append((None, "independent: no peer above threshold", sid))
                continue
            cur.execute("SELECT key FROM source WHERE source_id=%s", (rep,))
            name = f"copyset:{cur.fetchone()[0]}"
            note = (f"{len(members)} channels agreeing >={AGREEMENT_THRESHOLD:.0%} "
                    f"over >={MIN_CO_OBSERVATIONS} co-observations")
            for sid in members:
                assignments.append((name, note, sid))

        assignments = [a for a in assignments if a[2] not in crowd]
        if apply_changes:
            cur.executemany("""UPDATE source SET independence_group=%s,
                                      independence_note=%s,
                                      independence_measured_at=now()
                               WHERE source_id=%s""", assignments)
            conn.commit()

        cur.execute("""SELECT COALESCE(independence_group,'(independent)'),
                              COUNT(*), string_agg(key, ', ' ORDER BY key)
                       FROM source WHERE key LIKE 'tg\\_%%'
                       GROUP BY 1 ORDER BY 2 DESC""")
        summary = cur.fetchall()
    return {"pairs": len(rows), "merged": merged, "groups": groups,
            "summary": summary, "applied": apply_changes}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write independence groups")
    ap.add_argument("--kinds", default="checkpoint_flow",
                    help="comma-separated state kinds to measure on")
    a = ap.parse_args()

    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]
    n = measure(kinds)
    print(f"measured {n} source pairs on {', '.join(kinds)} "
          f"(>={MIN_CO_OBSERVATIONS} co-observations, +/-{WINDOW_SECONDS}s)\n")

    r = cluster(a.apply)
    print(f"pairs above threshold ({AGREEMENT_THRESHOLD:.0%}): {len(r['merged'])}")
    for ka, kb, rate, cnt in r["merged"][:12]:
        print(f"   {ka:<26} ~ {kb:<26} {rate:6.1%}  n={cnt}")

    print("\nindependence units:")
    for grp, cnt, members in r["summary"]:
        print(f"   {grp:<28} {cnt:>2} — {members}")

    if not a.apply:
        print("\n(dry run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
