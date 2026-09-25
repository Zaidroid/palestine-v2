"""Gaza Ministry of Health daily reports -> databank observations.

    .venv/bin/python -m ingest.sources.moh_gaza [--dry-run]

Turns @MOHMediaGaza's daily statistical report into `observation` rows — the
tier-2 table — rather than `state_observation`. A death toll is a measurement,
not the state of a place: it does not decay and it is not about somewhere being
open or shut. Same decision as the tier-1 rollup in 031, for the same reason.

The place is the Gaza Strip region, because the Ministry reports Strip-wide
totals and attributing them to a governorate would be inventing a breakdown it
did not give.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from cascade.moh_gaza import INDICATORS, parse                # noqa: E402
from resolve.db import connect                                # noqa: E402

SOURCE_KEY = "tg_mohmediagaza"
DATASET_KEY = "gaza_moh_daily"


def _dataset(cur) -> tuple[int, int]:
    cur.execute("SELECT source_id FROM source WHERE key=%s", (SOURCE_KEY,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"source {SOURCE_KEY} missing — is it in the poller?")
    sid = row[0]
    cur.execute("""
        INSERT INTO dataset (key, name, source_id, cadence, active, attrs)
        VALUES (%s, 'Gaza MoH daily statistical report', %s, 'daily', true, %s)
        ON CONFLICT (key) DO NOTHING""",
        (DATASET_KEY, sid, json.dumps({
            "grain": "Gaza Strip x day",
            "tiers": "daily, since_ceasefire, cumulative — never conflated",
            "note": "Counts as published by the Ministry. Not corroborated; "
                    "this is what one authoritative source stated."})))
    cur.execute("SELECT dataset_id FROM dataset WHERE key=%s", (DATASET_KEY,))
    return cur.fetchone()[0], sid


def _gaza_place(cur) -> int | None:
    cur.execute("""SELECT place_id FROM place
                    WHERE kind='region' AND (name_en ILIKE '%%gaza%%' OR name_ar LIKE '%%غزة%%')
                    ORDER BY place_id LIMIT 1""")
    r = cur.fetchone()
    return r[0] if r else None


# A REVISION SUPERSEDES; IT DOES NOT OVERWRITE.
#
# This was `DO UPDATE SET value_num = EXCLUDED.value_num, reported_at = now()`
# with no condition, and the loop re-reads every bulletin every hour. So:
#   * a corrected bulletin later the same day replaced the first figure with
#     no trace (HANDOFF §1 rule 2: corrections supersede, nothing is
#     overwritten), and attrs.claim_id went on naming the FIRST bulletin
#     while value_num came from the second;
#   * after the second hourly run every row's reported_at was the run time,
#     so "when did the Ministry say this" was gone for the whole series.
# Now a conflicting row changes only when a LATER bulletin states a
# DIFFERENT number; the old value, its bulletin and its time are appended to
# attrs.superseded, and reported_at is the bulletin's own time. Re-reading
# the same bulletins writes nothing, which makes the hourly re-read safe.
UPSERT_SQL = """
    INSERT INTO observation
      (dataset_id, place_id, indicator, value_num, unit,
       occurred_at, occurred_precision, reported_at, attrs)
    VALUES (%(did)s, %(place)s, %(ind)s, %(value)s, 'count',
            %(reported)s::date, 'day', %(reported)s, %(attrs)s)
    ON CONFLICT (dataset_id, place_id, indicator, occurred_at)
      WHERE place_id IS NOT NULL AND v1_stable_id IS NULL
    DO UPDATE SET
      value_num   = EXCLUDED.value_num,
      reported_at = EXCLUDED.reported_at,
      attrs       = EXCLUDED.attrs || jsonb_build_object('superseded',
                      COALESCE(observation.attrs -> 'superseded', '[]'::jsonb)
                      || jsonb_build_array(jsonb_build_object(
                           'value_num',     observation.value_num,
                           'reported_at',   observation.reported_at,
                           'claim_id',      observation.attrs -> 'claim_id',
                           'superseded_at', now())))
    WHERE observation.value_num IS DISTINCT FROM EXCLUDED.value_num
      AND (observation.reported_at IS NULL
           OR EXCLUDED.reported_at > observation.reported_at)"""


def write_report(cur, dataset_id: int, place_id: int, claim_id: int, text: str,
                 reported_at, st: dict, dry_run: bool = False) -> None:
    """One bulletin's tiers -> observation rows (see UPSERT_SQL)."""
    rep = parse(text)
    if not rep.is_report or not rep.tiers:
        return
    st["reports"] += 1
    for tier, measures in rep.tiers.items():
        for measure, value in measures.items():
            ind = INDICATORS.get((tier, measure))
            if not ind:
                continue
            st["rows"] += 1
            if dry_run:
                continue
            cur.execute(UPSERT_SQL, {
                "did": dataset_id, "place": place_id, "ind": ind,
                "value": float(value), "reported": reported_at,
                "attrs": json.dumps({"tier": tier, "measure": measure,
                                     "claim_id": claim_id}, ensure_ascii=False)})
            st["written"] += cur.rowcount


def load(dry_run: bool = False) -> dict:
    st = {"claims": 0, "reports": 0, "rows": 0, "written": 0, "no_place": 0}
    with connect() as conn, conn.cursor() as cur:
        did, sid = _dataset(cur)
        place_id = _gaza_place(cur)
        if place_id is None:
            st["no_place"] = 1
            return st

        # Hamza-less "الاحصائي" is the same word (cascade/moh_gaza.IS_REPORT);
        # a LIKE on the hamzated spelling alone never even selected that day.
        cur.execute("""
            SELECT cl.claim_id, cl.raw_text, cl.reported_at
              FROM claim cl WHERE cl.source_id=%s AND cl.raw_text ~ %s
             ORDER BY cl.reported_at, cl.claim_id""", (sid, "التقرير\\s+ال[إا]حصائي"))
        for claim_id, text, reported_at in cur.fetchall():
            st["claims"] += 1
            write_report(cur, did, place_id, claim_id, text, reported_at, st, dry_run)
        if not dry_run:
            conn.commit()
    return st


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = load(a.dry_run)
    if s["no_place"]:
        print("  no Gaza region place found — cannot attribute the totals")
        return 1
    for k in ("claims", "reports", "rows", "written"):
        print(f"  {k:12}{s[k]:>8,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
