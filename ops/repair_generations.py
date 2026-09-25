"""Repair the Aug-7 generation doubling — measured, per-identity, dry-run first.

What happened (task #60): v1's nightly rebuild re-hashed stable ids after the
healed T4P fetch changed the raw tree, and every dataset WITHOUT a
max_observations tripwire silently re-inserted its rows under the new ids
(education 3 generations, culture 3, historical 2, ...). The floors caught it
where they existed (health, conflict); the public surface double-serves where
they did not.

The repair: for each affected dataset, DELETE current rows from newer
generations whose IDENTITY already exists in an older current row. Identity
is per-dataset (the same keys the as_of harness used): register datasets
match on their identity attr ONLY (their occurred_at is a re-stamped
masquerade date that differs per generation); series match on
indicator+date+place+value. Rows with genuinely new identity (the 12,635
newly identified martyrs, new IDMC events) are KEPT. Deletion, not
supersedence: these are erroneous duplicates, not revised truth — bronze
keeps every byte regardless.

Run: .venv/bin/python -m ops.repair_generations           (dry run, counts)
     .venv/bin/python -m ops.repair_generations --apply   (delete + report)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from resolve.db import connect

# dataset key → SQL expression (over alias `o`) computing the row's identity.
# Register datasets: identity attr only — their occurred_at is a re-stamped
# fetch-day masquerade that DIFFERS per generation by design (law 1).
IDENTITY = {
    "v1_education_hdx":
        "o.attrs->>'school_id'",
    "v1_culture_heritage_composite":
        "o.indicator || '|' || (o.attrs->>'site_name')",
    "v1_infrastructure_hdx":
        "o.indicator || '|' || coalesce(o.attrs->>'locality_name','') || '|' "
        "|| coalesce(o.attrs->>'event_type','')",
    "v1_land_ocha":
        "o.indicator || '|' || coalesce(o.attrs->>'land_name','') || '|' "
        "|| coalesce(o.attrs->>'checkpoint_type','')",
    "v1_land_peace_now":
        "o.indicator || '|' || coalesce(o.attrs->>'land_name','')",
    "v1_historical_palopenmaps":
        "o.indicator || '|' || o.occurred_at::date::text || '|' "
        "|| coalesce(o.attrs->>'name','')",
    # demolitions: the Aug-7 generation is a DEGRADED re-add of a frozen
    # upstream (fetcher dead since June, static file unchanged): place fell
    # from governorate-grade to region, attr shape drifted (coverage_area →
    # coverage_start/end). Nothing genuinely new can be in it — the whole
    # generation goes, by ingest date rather than identity.
    "v1_demolitions_ocha_demolitions": "GENERATION:2026-08-07",
    "v1_refugees_idmc":
        "o.indicator || '|' || o.occurred_at::date::text || '|' "
        "|| coalesce(o.place_id::text,'') || '|' "
        "|| coalesce(o.value_num::text,'') || '|' "
        "|| coalesce(o.attrs->>'event_name','')",
    "v1_refugees_unrwa":
        "o.indicator || '|' || o.occurred_at::date::text || '|' "
        "|| coalesce(o.attrs->>'aggregate_label','')",
    "v1_martyrs_snapshot_2023_tech4palestine":
        "coalesce(o.attrs->>'t4p_id', "
        "         o.indicator || '|' || o.occurred_at::date::text)",
}


def generation_sql(cutoff: str) -> str:
    """The ONE day of the bad generation, closed on both ends: `>= cutoff`
    would have deleted every current row ingested since (audit F345)."""
    return f"""
                SELECT o.observation_id FROM observation o
                WHERE o.dataset_id = %s AND upper_inf(o.sys_period)
                  AND o.ingested_at::date BETWEEN '{cutoff}' AND '{cutoff}'"""


def main() -> int:
    apply = "--apply" in sys.argv
    report = {"ts": datetime.now(timezone.utc).isoformat(), "apply": apply,
              "datasets": {}}
    with connect() as conn, conn.cursor() as cur:
        for key, ident in IDENTITY.items():
            cur.execute("SELECT dataset_id FROM dataset WHERE key = %s", (key,))
            row = cur.fetchone()
            if not row:
                continue
            ds = row[0]
            cur.execute("""SELECT EXISTS (SELECT 1 FROM observation
                                          WHERE dataset_id = %s AND identity_key IS NOT NULL)""", (ds,))
            if cur.fetchone()[0]:
                # Post-052 the dataset has identities; this one-off repair
                # would delete the repaired generation itself (audit F345).
                print(f"  {key}: carries identity_key — this repair does not apply, skipped")
                continue
            if ident.startswith("GENERATION:"):
                cutoff = ident.split(":", 1)[1]
                dup_sql = generation_sql(cutoff)
            else:
                # duplicates = current rows for which an OLDER current row
                # with the same identity exists in the same dataset
                dup_sql = f"""
                SELECT o.observation_id
                FROM observation o
                WHERE o.dataset_id = %s AND upper_inf(o.sys_period)
                  AND EXISTS (
                    SELECT 1 FROM observation k
                    WHERE k.dataset_id = o.dataset_id
                      AND upper_inf(k.sys_period)
                      AND k.ingested_at < o.ingested_at
                      AND ({ident}) = ({ident.replace('o.', 'k.')})
                  )"""
            cur.execute(f"SELECT count(*) FROM ({dup_sql}) x", (ds,))
            dupes = cur.fetchone()[0]
            cur.execute("""SELECT count(*) FROM observation o
                           WHERE o.dataset_id=%s AND upper_inf(o.sys_period)""",
                        (ds,))
            before = cur.fetchone()[0]
            deleted = 0
            if apply and dupes:
                cur.execute(f"DELETE FROM observation o WHERE "
                            f"o.observation_id IN ({dup_sql})", (ds,))
                deleted = cur.rowcount
            report["datasets"][key] = {
                "current_before": before, "identity_duplicates": dupes,
                "deleted": deleted, "current_after": before - deleted,
            }
            print(f"  {key:<46} current={before:>6} dupes={dupes:>6} "
                  f"{'DELETED' if apply else 'would delete'}={dupes:>6} "
                  f"→ {before - (deleted if apply else dupes):>6}")
        if apply:
            conn.commit()
    print(json.dumps({"apply": apply,
                      "total_dupes": sum(d["identity_duplicates"]
                                         for d in report["datasets"].values())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
