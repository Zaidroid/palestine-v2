"""Tier 1 grows a memory: one immutable row per place, kind and day.

    .venv/bin/python -m ops.rollup                  # yesterday
    .venv/bin/python -m ops.rollup --days 90        # backfill
    .venv/bin/python -m ops.rollup --dry-run

Writes into `observation` — the DATABANK's table — rather than a private
tier-1 summary table. See db/migrations/031_tier1_history.sql for why: tier 2's
Phase 2 gate is a cross-tier query joined on place and time, and history written
this way satisfies it by construction instead of by a later migration.

WHAT A DAY BECOMES
Three indicators per (place, state_kind, day):

    <kind>.reports          how many assertions arrived
    <kind>.reports.<value>  how many carried each value
    <kind>.units            how many INDEPENDENCE units they came from

Counts, never shares of time. "Huwara was closed 40% of yesterday" would need
the decay curve replayed and would let sparse reporting read as measured time —
a checkpoint with three reports cannot speak for the other 23 hours. "15 of 37
reports said closed" is measurable and cannot be mistaken for coverage it does
not have. Counts are also additive, so a month is the sum of its days and no
aggregate ever has to be recomputed.

`units` is the honesty column. Nine road channels reposting each other are one
observer; 200 reports from one unit is a thinner day than 12 from four. Without
it a volume chart reads as a confidence chart.

COMPLETE DAYS ONLY
A day still running would be written and then rewritten, and `observation` is
an immutable record. Today is served live from `state_observation`. The boundary
is what makes "written once" true rather than aspirational — and the unique
index means a re-run after a backfill updates in place instead of silently
duplicating, which is the failure that put 762,609 copies in state_observation
before anyone noticed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect                          # noqa: E402

DATASET_KEY = "tier1_daily"

# One statement per day, so a backfill is a loop over days rather than one query
# holding a lock on the whole hypertable.
#
# `unit` mirrors resolve/belief.py exactly: a source with no independence group
# is its own unit. If the two ever disagree, a rollup would report a number of
# observers the confidence model does not recognise.
ROLLUP_SQL = """
WITH grp AS (
  SELECT source_id,
         COALESCE(independence_group, 'src:' || source_id::text) AS unit
    FROM source
),
day AS (
  -- DISTINCT, and it is load-bearing rather than tidiness.
  --
  -- 762,609 historical fuel rows are exact duplicates — the loader re-read its
  -- append-only spool every five minutes before migration 023 gave it a cursor
  -- — and they were deliberately RETAINED, because the rule is that nothing is
  -- deleted. Counting storage rows therefore reported 59,100 "no diesel"
  -- reports for Tulkarm in a month, roughly 66x the truth.
  --
  -- Retention and honest counting are not in conflict: keep every row, count
  -- every distinct thing that was actually SAID. The key matches the one
  -- tests/test_no_data_loss.sql uses to distinguish real growth from
  -- duplication, so the two agree about what an observation is.
  SELECT DISTINCT o.place_id, o.state_kind, o.value, o.source_id,
         o.observed_at, g.unit
    FROM state_observation o
    JOIN grp g USING (source_id)
   WHERE o.modality = 'assertion'
     AND o.place_id IS NOT NULL
     AND o.observed_at >= %(day)s::date
     AND o.observed_at <  %(day)s::date + interval '1 day'
),
totals AS (
  SELECT place_id, state_kind,
         state_kind || '.reports'      AS indicator,
         count(*)::float8              AS value_num
    FROM day GROUP BY 1, 2
  UNION ALL
  SELECT place_id, state_kind,
         state_kind || '.units',
         count(DISTINCT unit)::float8
    FROM day GROUP BY 1, 2
  UNION ALL
  SELECT place_id, state_kind,
         state_kind || '.reports.' || value,
         count(*)::float8
    FROM day GROUP BY 1, 2, value
)
INSERT INTO observation
  (dataset_id, place_id, indicator, value_num, unit, occurred_at,
   occurred_precision, reported_at, attrs)
SELECT %(dataset_id)s, t.place_id, t.indicator, t.value_num, 'count',
       %(day)s::date, 'day', now(),
       jsonb_build_object('state_kind', t.state_kind, 'grain', 'day')
  FROM totals t
ON CONFLICT (dataset_id, place_id, indicator, occurred_at)
  WHERE place_id IS NOT NULL
  DO UPDATE SET value_num = EXCLUDED.value_num, reported_at = now()
"""

# Days with observations but no rollup yet. Asked of the data rather than of a
# cursor, so a gap left by a failed run is picked up on the next one instead of
# being stepped over.
PENDING_SQL = """
SELECT d::date
  FROM generate_series(
         GREATEST(
           (SELECT min(observed_at)::date FROM state_observation),
           (CURRENT_DATE - %(days)s::int)),
         CURRENT_DATE - 1,
         interval '1 day') AS d
 WHERE EXISTS (SELECT 1 FROM state_observation o
                WHERE o.observed_at >= d AND o.observed_at < d + interval '1 day'
                  AND o.modality = 'assertion' LIMIT 1)
 ORDER BY d
"""


def dataset_id(cur) -> int:
    cur.execute("SELECT dataset_id FROM dataset WHERE key = %s", (DATASET_KEY,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"dataset {DATASET_KEY!r} missing — run db/migrate.sh")
    return row[0]


def run(days: int, dry_run: bool = False) -> dict:
    written, covered = 0, []
    with connect() as conn, conn.cursor() as cur:
        did = dataset_id(cur)
        cur.execute(PENDING_SQL, {"days": days})
        for (day,) in cur.fetchall():
            if dry_run:
                covered.append(str(day))
                continue
            cur.execute(ROLLUP_SQL, {"day": day, "dataset_id": did})
            written += cur.rowcount
            covered.append(str(day))
        if not dry_run:
            conn.commit()
    return {"days": len(covered), "rows": written, "covered": covered}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=2,
                    help="how far back to look for un-rolled days (default 2, "
                         "so a missed night is caught the next)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    r = run(a.days, a.dry_run)
    if not r["days"]:
        print("rollup: no complete days with observations in range")
        return 0
    print(f"rollup: {r['rows']:,} rows across {r['days']} day(s) "
          f"[{r['covered'][0]} .. {r['covered'][-1]}]"
          + (" (dry run)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
