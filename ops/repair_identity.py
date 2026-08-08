"""Close the generations that cannot carry a valid identity. Never delete.

WHY ANY ROW NEEDS REPAIRING
Three datasets hold current rows that predate the attribute their declared
identity is built from — the locality name for demolitions, the coordinates
for the HDX barrier register and the Mandate localities. Their keys therefore
collapse (demolitions 906 rows → 76 keys) and migration 052's unique index
would refuse them. Underneath that, demolitions is worse: 515 of its 536
current id-prefixes no longer exist upstream at all, while 513 live upstream
records have been locked out since the freeze. It is serving a superseded
generation as if it were current.

WHAT THIS DOES
Supersedence, not deletion, exactly as the no-data-loss rule requires: the
current generation's `sys_period` is closed at now(), so every row stays
queryable at the as_of dates when it WAS the truth, and stops being served as
present. The loader then writes a fresh generation carrying proper identity
keys — including, for demolitions, the 513 records that could not land.

WHICH DATASETS, AND WHY NOT A HARDCODED LIST
Chosen by measurement: any dataset whose current rows collide under its own
declared identity by more than its declared `allow_collisions`. A dataset that
keys cleanly is never touched, and a spec change that fixes a key removes its
dataset from this list automatically.

Run: .venv/bin/python -m ops.repair_identity           # measure
     .venv/bin/python -m ops.repair_identity --apply   # close the generations
     # then: .venv/bin/python -m ingest.databank --all
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.databank import (SPECS, SpecRefused,                 # noqa: E402
                             identity_key_for, load_spec)
from resolve.db import connect                                   # noqa: E402


def plan() -> dict[str, dict]:
    """dataset_key → {rows, keys, collisions, allowed, verdict}."""
    out: dict[str, dict] = {}
    with connect() as conn, conn.cursor() as cur:
        for p in sorted(SPECS.glob("*.yaml")):
            try:
                spec = load_spec(p.stem)
            except SpecRefused:
                continue
            for ds in spec.get("datasets", []):
                ident = ((ds.get("overrides") or {}).get("identity")
                         or spec.get("identity"))
                if not ident:
                    continue
                key = ds["key"]
                cur.execute("""
                    SELECT o.indicator, o.occurred_at, o.place_id,
                           o.value_num, o.attrs
                    FROM observation o JOIN dataset d
                      ON d.dataset_id = o.dataset_id
                    WHERE d.key = %s AND upper_inf(o.sys_period)""", (key,))
                rows = cur.fetchall()
                if not rows:
                    continue
                seen: dict[str, int] = {}
                for ind, occ, pid, val, attrs in rows:
                    k = identity_key_for(ident, key, indicator=ind,
                                         occurred_at=occ, place_id=pid,
                                         value_num=val, attrs=attrs)
                    seen[k] = seen.get(k, 0) + 1
                coll = sum(c - 1 for c in seen.values() if c > 1)
                allowed = ident.get("allow_collisions", 0)
                out[key] = {
                    "rows": len(rows), "keys": len(seen),
                    "collisions": coll, "allowed": allowed,
                    "verdict": ("supersede the current generation"
                                if coll > allowed else "clean"),
                }
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    p = plan()
    doomed = {k: v for k, v in p.items() if v["verdict"] != "clean"}

    for k, v in sorted(p.items()):
        if v["verdict"] == "clean":
            continue
        print(f"  {k:<44} {v['rows']:>6} rows → {v['keys']:>6} keys "
              f"({v['collisions']} collide, {v['allowed']} allowed)")
    if not doomed:
        print("every dataset keys cleanly — nothing to repair")
        return 0

    closed = 0
    if apply:
        with connect() as conn, conn.cursor() as cur:
            for key in doomed:
                cur.execute("""
                    UPDATE observation o
                       SET sys_period = tstzrange(lower(o.sys_period), now())
                      FROM dataset d
                     WHERE d.dataset_id = o.dataset_id AND d.key = %s
                       AND upper_inf(o.sys_period)""", (key,))
                doomed[key]["superseded"] = cur.rowcount
                closed += cur.rowcount
            conn.commit()

    report = {"ts": datetime.now(timezone.utc).isoformat(), "apply": apply,
              "datasets": p}
    (Path(__file__).parent / "repair-report.json").write_text(
        json.dumps(report, indent=1, sort_keys=True))
    print(f"\n{'SUPERSEDED' if apply else 'would supersede'} "
          f"{closed if apply else sum(v['rows'] for v in doomed.values())} "
          f"rows across {len(doomed)} datasets — no row deleted; each stays "
          "valid at the as_of dates it was true.\n"
          "Next: .venv/bin/python -m ingest.databank --all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
