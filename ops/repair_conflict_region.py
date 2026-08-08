"""Supersede four West Bank figures stored inside the Gaza cumulative series.

Found 2026-08-08 by building v_flow. `t_conflict` hardcoded the Gaza
indicator and the Gaza place row for every `daily_casualty_report`, and the
spec's drop rule removes only the ALL-ZERO West Bank ones — so four real West
Bank figures survived and landed in Gaza's series:

    2026-06-09  killed 1,086   injured 11,132
    2026-08-06  killed 1,108   injured 11,399

against a Gaza toll of 73,382. The series therefore read
73,381 → 1,108 → 73,382, and the first difference came out as 72,274 killed
in one day — the same arithmetic that produced conflict.yaml's famous
~35-million-dead artifact, in miniature and for the same reason. v_flow's
revision guard caught the fall; nothing caught the rise, because a rise in a
cumulative series is exactly what a cumulative series does.

These are NOT duplicates to be dropped. The West Bank cumulative series from
conflict_westbank runs 2023-10-07..2026-07-27 and covers neither date, so
deleting them loses two real observations.

SUPERSEDED, NEVER DELETED. The rows stay readable at their own as_of; the
loader then writes the corrected ones under the right indicator and place.
044's unique index is on (dataset_id, v1_stable_id, occurred_at) with no
validity predicate, which is why the old row must close before the new one
can land.

Run:  .venv/bin/python -m ops.repair_conflict_region          # measure
      .venv/bin/python -m ops.repair_conflict_region --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect                                   # noqa: E402

FIND = """
    SELECT o.observation_id, o.v1_stable_id, o.indicator,
           o.occurred_at::date, o.value_num
    FROM observation o JOIN dataset d USING (dataset_id)
    WHERE d.key = 'v1_conflict_tech4palestine'
      AND upper_inf(o.sys_period)
      AND o.indicator LIKE 'conflict.gaza_cumulative%'
      AND o.attrs->>'region' = 'West Bank'
    ORDER BY 4, 3
"""


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    with connect() as conn, conn.cursor() as cur:
        cur.execute(FIND)
        rows = cur.fetchall()
        for oid, sid, ind, day, val in rows:
            print(f"  {day}  {ind:<38} {val:>10.0f}  {sid}")
        if not rows:
            print("  none — already repaired")
            return 0
        if apply:
            cur.execute(
                "UPDATE observation "
                "SET sys_period = tstzrange(lower(sys_period), now()) "
                "WHERE observation_id = ANY(%s)",
                ([r[0] for r in rows],))
            print(f"\nsuperseded {cur.rowcount} row(s) — still readable at "
                  "their own as_of, no longer served as current")
            conn.commit()
        else:
            print(f"\n{len(rows)} row(s) would be superseded (--apply to do it)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
