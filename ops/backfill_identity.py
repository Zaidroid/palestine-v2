"""Give every migrated row its declared identity_key, and report collisions.

Two jobs, in this order, because the second is the audit of the first:

  1. BACKFILL — compute each existing row's key with the SAME function the
     loader uses (ingest.databank.identity_key_for). Reading a row back and
     re-rendering its key in SQL is exactly the mistake 052 exists to remove:
     Python writes 106.0 where numeric::text writes 106, and the guard then
     fails open. One renderer, or none.

  2. REPORT — after the keys exist, count current rows that share one. Those
     are the rows migration 052's unique index will refuse, and each one is a
     real question: is it an upstream duplicate (declare it), a too-coarse
     identity (fix the spec), or a superseded generation still being served
     as current (supersede it — ops/repair_identity.py)?

Read-only unless --apply. Never deletes: this writes one column.

Run: .venv/bin/python -m ops.backfill_identity            # measure
     .venv/bin/python -m ops.backfill_identity --apply    # write the keys
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.databank import (SPECS, SpecRefused,                 # noqa: E402
                             identity_key_for, load_spec)
from resolve.db import connect                                   # noqa: E402


def identities_by_dataset() -> dict[str, dict]:
    """dataset_key → its declared identity, honouring per-dataset overrides."""
    out: dict[str, dict] = {}
    for p in sorted(SPECS.glob("*.yaml")):
        try:
            spec = load_spec(p.stem)
        except SpecRefused:
            continue
        for ds in spec.get("datasets", []):
            ident = ((ds.get("overrides") or {}).get("identity")
                     or spec.get("identity"))
            if ident:
                out[ds["key"]] = ident
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    idents = identities_by_dataset()
    report: dict[str, dict] = {}

    with connect() as conn, conn.cursor() as cur:
        for ds_key, ident in sorted(idents.items()):
            cur.execute("SELECT dataset_id FROM dataset WHERE key = %s",
                        (ds_key,))
            row = cur.fetchone()
            if not row:
                continue
            ds_id = row[0]
            cur.execute("""
                SELECT observation_id, indicator, occurred_at, place_id,
                       value_num, attrs
                FROM observation
                WHERE dataset_id = %s AND upper_inf(sys_period)""", (ds_id,))
            rows = cur.fetchall()
            # A dataset that DECLARES collisions cannot carry a stored key:
            # 052's index is unique and would refuse it, and appending an
            # ordinal to force distinctness would be inventing identity the
            # source does not have. Such datasets are protected by 044
            # (v1_stable_id) plus expect.max_observations, which is exactly
            # what their spec says. Measured, not assumed — see aid_access.
            # `indistinguishable` (aid_access): different things the source
            # records identically — no stored key is possible, 044 guards it.
            # `duplicate_fact` (IDMC, conflict): the same fact twice — the key
            # IS stored and the extra copy is superseded, because one fact
            # deserves one current row.
            declares_collisions = (
                ident.get("collision_kind") == "indistinguishable")
            keys: dict[str, int] = {}
            updates = []
            extras = []
            for obs_id, ind, occ, pid, val, attrs in rows:
                k = identity_key_for(ident, ds_key, indicator=ind,
                                     occurred_at=occ, place_id=pid,
                                     value_num=val, attrs=attrs)
                keys[k] = keys.get(k, 0) + 1
                if keys[k] == 1:
                    updates.append((k, obs_id))
                else:
                    extras.append(obs_id)   # the same fact, already current
            collisions = sum(c - 1 for c in keys.values() if c > 1)
            report[ds_key] = {"rows": len(rows), "distinct_keys": len(keys),
                              "collisions": collisions}
            if apply and updates and not declares_collisions:
                # One UPDATE joined against a COPY'd temp table. Row-by-row
                # executemany over ~197k rows took longer than a session and
                # committed nothing; this is seconds. The temp table is
                # dropped on commit, so a failed run leaves no residue.
                cur.execute("CREATE TEMP TABLE _ik (k TEXT, oid BIGINT) "
                            "ON COMMIT DROP")
                with cur.copy("COPY _ik (k, oid) FROM STDIN") as cp:
                    for k, oid in updates:
                        cp.write_row((k, oid))
                cur.execute("UPDATE observation o SET identity_key = _ik.k "
                            "FROM _ik WHERE o.observation_id = _ik.oid")
                cur.execute("DROP TABLE _ik")
                if extras:
                    # one fact, one current row — the copies are superseded,
                    # never deleted, so they stay readable at their own as_of
                    cur.execute(
                        "UPDATE observation "
                        "SET sys_period = tstzrange(lower(sys_period), now()) "
                        "WHERE observation_id = ANY(%s)", (extras,))
                    report[ds_key]["superseded_duplicates"] = len(extras)
            if declares_collisions:
                report[ds_key]["stored"] = False
            flag = ("  (declared collisions — no stored key, 044 + "
                    "max_observations guard it)" if declares_collisions
                    else "" if not collisions else f"  <-- {collisions} collide")
            print(f"  {ds_key:<44} {len(rows):>6} rows  "
                  f"{len(keys):>6} keys{flag}")
        if apply:
            conn.commit()

    total_coll = sum(r["collisions"] for r in report.values())
    print(f"\n{'WROTE' if apply else 'measured'} identity keys for "
          f"{len(report)} datasets; {total_coll} current rows share a key "
          f"with another and would be refused by 052's index")
    (Path(__file__).parent / "identity-backfill.json").write_text(
        json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
