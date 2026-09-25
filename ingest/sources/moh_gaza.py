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


def _upsert_day(cur, did, place_id, ind, value, reported_at, tier, measure, claim_id, st) -> int:
    """One row per (indicator, day). The same value again is nothing; a
    DIFFERENT value SUPERSEDES the current row (its sys_period is closed, the
    new row says which claim revised what) — never an in-place overwrite, and
    reported_at is the claim's, never now() (audit F182)."""
    cur.execute("""SELECT observation_id, value_num FROM observation
                    WHERE dataset_id = %s AND place_id = %s AND indicator = %s
                      AND occurred_at = %s::date AND upper_inf(sys_period)
                      AND v1_stable_id IS NULL""",
                (did, place_id, ind, reported_at))
    cur_row = cur.fetchone()
    attrs = {"tier": tier, "measure": measure, "claim_id": claim_id}
    if cur_row and float(cur_row[1]) == float(value):
        st["unchanged"] = st.get("unchanged", 0) + 1
        return 0
    if cur_row:
        cur.execute("""UPDATE observation
                          SET sys_period = tstzrange(lower(sys_period), now())
                        WHERE observation_id = %s""", (cur_row[0],))
        attrs["supersedes"] = cur_row[0]
        attrs["previous_value"] = float(cur_row[1])
        st["revised"] = st.get("revised", 0) + 1
    cur.execute("""
        INSERT INTO observation
          (dataset_id, place_id, indicator, value_num, unit,
           occurred_at, occurred_precision, reported_at, attrs)
        VALUES (%s,%s,%s,%s,'count',%s::date,'day',%s,%s)""",
        (did, place_id, ind, value, reported_at, reported_at,
         json.dumps(attrs, ensure_ascii=False)))
    return 1


# One writer at a time: the hourly timer and a hand re-read must never both
# find a day missing and insert it twice (2026-09-25).
LOCK_KEY = 0x6D6F6867   # 'mohg'


def load(dry_run: bool = False, reread_since: str | None = None) -> dict:
    """`reread_since` (YYYY-MM-DD) re-reads every bulletin from that day,
    ignoring the read-once cursor — the way a parser fix reaches claims the
    cursor has already passed (the number-first daily lines, 2026-08-10 on).
    Safe to repeat: the same value is nothing, a different one supersedes."""
    st = {"claims": 0, "reports": 0, "rows": 0, "no_place": 0}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_KEY,))
        if not cur.fetchone()[0]:
            st["locked"] = 1
            return st
        did, sid = _dataset(cur)
        place_id = _gaza_place(cur)
        if place_id is None:
            st["no_place"] = 1
            return st

        # READ ONCE (audit F182): every hourly run re-read every claim and DO
        # UPDATEd each day's row with reported_at=now(), so a revision
        # overwrote the value it corrected and every row looked fresh. The
        # cursor is the newest claim already recorded in this dataset's rows.
        cur.execute("""SELECT COALESCE(max((attrs->>'claim_id')::bigint), 0)
                         FROM observation WHERE dataset_id = %s AND attrs ? 'claim_id'""", (did,))
        since = cur.fetchone()[0]
        if reread_since:
            cur.execute("""
                SELECT cl.claim_id, cl.raw_text, cl.reported_at
                  FROM claim cl WHERE cl.source_id=%s AND cl.raw_text LIKE %s
                   AND cl.reported_at >= %s::date
                 ORDER BY cl.reported_at, cl.claim_id""", (sid, "%التقرير الإحصائي%", reread_since))
        else:
            cur.execute("""
                SELECT cl.claim_id, cl.raw_text, cl.reported_at
                  FROM claim cl WHERE cl.source_id=%s AND cl.raw_text LIKE %s
                   AND cl.claim_id > %s
                 ORDER BY cl.reported_at, cl.claim_id""", (sid, "%التقرير الإحصائي%", since))
        for claim_id, text, reported_at in cur.fetchall():
            st["claims"] += 1
            rep = parse(text)
            if not rep.is_report or not rep.tiers:
                continue
            st["reports"] += 1
            for tier, measures in rep.tiers.items():
                for measure, value in measures.items():
                    ind = INDICATORS.get((tier, measure))
                    if not ind:
                        continue
                    if dry_run:
                        st["rows"] += 1
                        continue
                    st["rows"] += _upsert_day(cur, did, place_id, ind, float(value),
                                              reported_at, tier, measure, claim_id, st)
        if not dry_run:
            conn.commit()
    return st


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reread-since", metavar="YYYY-MM-DD",
                    help="re-read every bulletin from that day (after a parser fix)")
    a = ap.parse_args()
    s = load(a.dry_run, a.reread_since)
    if s.get("locked"):
        print("  another Gaza ingest holds the lock — nothing done")
        return 0
    if s["no_place"]:
        print("  no Gaza region place found — cannot attribute the totals")
        return 1
    for k in ("claims", "reports", "rows", "unchanged", "revised"):
        print(f"  {k:12}{s.get(k, 0):>8,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
