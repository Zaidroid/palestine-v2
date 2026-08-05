"""T2.4 — the as_of harness (P2.7): prove sys_period against the archive.

For sampled dates × categories, the ids the database says were valid at a
date must match the ids v1's archived snapshot actually served that day —
counted exactly, verified from index files, with value spot-checks pulled
from the snapshot records themselves. A category is only claimed from its
replay base_lower onward; before that, v1's id instability makes per-day
reconstruction unprovable and the harness says so instead of guessing.

Run: .venv/bin/python -m ops.asof_harness
Exit non-zero on any mismatch. Report: ops/asof-report.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from ingest.databank import TRANSFORMERS, load_places, load_spec, PointResolver
from ops.replay_snapshots import index_ids, snapshot_days, _recs
from resolve.db import connect

SNAPS = Path("/opt/stacks/palestine/public/data/unified/snapshots")
OUT = Path(__file__).resolve().parent / "asof-report.json"

# Six categories with exact expectations (no rescue populations, no
# declared-drop arithmetic beyond what is stated here).
CATEGORIES = ["prisoners", "casualties", "aid_access", "demolitions",
              "martyrs_snapshot_2023", "education"]
SAMPLE_DATES = ["2026-06-28", "2026-07-05", "2026-07-15",
                "2026-07-25", "2026-08-02"]
SPOT_CHECKS = 5           # per (category, newest sampled date)


def db_ids_at(conn, category: str, at: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT split_part(o.v1_stable_id, ':', 1)
            FROM observation o
            JOIN dataset d ON d.dataset_id = o.dataset_id
            WHERE d.v1_category = %s AND o.v1_stable_id IS NOT NULL
              AND o.sys_period @> %s::date::timestamptz""", (category, at))
        return {r[0] for r in cur.fetchall()}


def main() -> int:
    report = {"checks": [], "spot_checks": [], "failures": []}
    replay = json.loads((Path(__file__).parent / "replay-report.json")
                        .read_text())["categories"]
    days = set(snapshot_days())

    with connect() as conn:
        places = load_places(conn)
        places["_pip"] = PointResolver(conn)
        with conn.cursor() as cur:
            cur.execute("""SELECT source_refs->>'v1_canonical_key', place_id
                           FROM place WHERE source_refs ? 'v1_canonical_key'
                             AND merged_into IS NULL""")
            places["_v1key"] = dict(cur.fetchall())
            cur.execute("SELECT key, commercial_use FROM source")
            places["_commercial"] = dict(cur.fetchall())

        from collections import Counter as _C
        for category in CATEGORIES:
            base = replay[category]["base_lower"]
            gens = replay[category]["generations"]
            gen_start = gens[-1]           # ids in the DB are this generation's
            churning = len(gens) > 3       # daily re-hashers: content-only
            spec = load_spec(category)
            transformer = TRANSFORMERS[category]
            rng = random.Random(47)

            for at in SAMPLE_DATES:
                if at not in days:
                    continue
                claimed = at >= base
                snap = set(index_ids(at, category))
                if not snap:
                    continue
                if not claimed:
                    report["checks"].append(
                        {"category": category, "at": at,
                         "claimed": False, "snapshot": len(snap)})
                    continue
                got = db_ids_at(conn, category, at)

                # COUNT: exact for these six categories on every claimed day
                count_ok = len(got) == len(snap)

                # IDS: only provable inside the DB's own hash generation —
                # v1 re-hashes the corpus on schema changes (2026-07-21) and
                # some categories daily; across that boundary identical
                # records carry different ids by construction.
                same_gen = (not churning) and at >= gen_start
                ids_ok = (got == snap) if same_gen else None

                # VALUES: transform a sample of what v1 actually served that
                # day and require each row's content to exist at that as_of.
                f = SNAPS / at / category / "all-data.json"
                recs = _recs(json.loads(f.read_bytes())) if f.exists() else []
                value_fail = 0
                for rec in rng.sample(recs, min(SPOT_CHECKS, len(recs))):
                    result = transformer(rec, spec, places, _C())
                    if not isinstance(result, list) or not result:
                        continue
                    r = result[0]
                    # precision=unknown means the timestamp is NOT a claim
                    # (masquerade registers) — match those on their real
                    # identity attr instead of a fetch-day stamp.
                    if r.precision == "unknown":
                        ident_key = next((k for k in ("school_id", "t4p_id",
                                                      "site_name")
                                          if k in r.attrs), None)
                        sql = """
                            SELECT 1 FROM observation o
                            JOIN dataset d ON d.dataset_id = o.dataset_id
                            WHERE d.v1_category = %s AND o.indicator = %s
                              AND o.value_num IS NOT DISTINCT FROM %s
                              AND o.value_text IS NOT DISTINCT FROM %s
                              AND (%s::text IS NULL
                                   OR o.attrs->>%s = %s::text)
                              AND o.sys_period @> %s::date::timestamptz
                            LIMIT 1"""
                        params = (category, r.indicator, r.value_num,
                                  r.value_text, ident_key, ident_key,
                                  str(r.attrs.get(ident_key)), at)
                    else:
                        sql = """
                            SELECT 1 FROM observation o
                            JOIN dataset d ON d.dataset_id = o.dataset_id
                            WHERE d.v1_category = %s AND o.indicator = %s
                              AND o.occurred_at = %s::timestamptz
                              AND o.value_num IS NOT DISTINCT FROM %s
                              AND o.value_text IS NOT DISTINCT FROM %s
                              AND o.sys_period @> %s::date::timestamptz
                            LIMIT 1"""
                        params = (category, r.indicator, r.occurred_at,
                                  r.value_num, r.value_text, at)
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        if cur.fetchone() is None:
                            value_fail += 1
                            report["failures"].append(
                                f"value {category}@{at} {r.indicator} "
                                f"{r.occurred_at}: ({r.value_num}, "
                                f"{r.value_text!r}) not served at as_of")
                report["spot_checks"].append(
                    {"category": category, "at": at,
                     "sampled": min(SPOT_CHECKS, len(recs)),
                     "value_fail": value_fail})

                ok = count_ok and ids_ok is not False and value_fail == 0
                report["checks"].append(
                    {"category": category, "at": at, "claimed": True,
                     "snapshot": len(snap), "db": len(got),
                     "count_ok": count_ok, "ids_ok": ids_ok, "ok": ok})
                if not count_ok:
                    report["failures"].append(
                        f"count {category}@{at}: snapshot {len(snap)} "
                        f"vs db {len(got)}")
                if ids_ok is False:
                    report["failures"].append(
                        f"ids {category}@{at}: same-generation id sets differ")

    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    n_ok = sum(1 for c in report["checks"] if c.get("ok"))
    n_claimed = sum(1 for c in report["checks"] if c.get("claimed"))
    sampled = sum(s["sampled"] for s in report["spot_checks"])
    v_fail = sum(s["value_fail"] for s in report["spot_checks"])
    print(f"as_of: {n_ok}/{n_claimed} claimed date-checks pass "
          f"(count + same-generation ids), "
          f"{sampled - v_fail}/{sampled} value spot-checks pass")
    for fail in report["failures"]:
        print("FAIL:", fail)
    return len(report["failures"])


if __name__ == "__main__":
    sys.exit(main())
