"""Load the arrests read by ops/extract_arrests.py into the databank.

    .venv/bin/python -m ops.load_arrests_press              # load data/raw/arrests/*.ndjson
    .venv/bin/python -m ops.load_arrests_press --dry-run

Dataset arrests_press (migration 131). Monthly: one row per (authority, scope,
month) for the total, and for children and women when stated; the place is the
West Bank or the governorate the statement is scoped to. Daily: the Club's
overnight count on the West Bank. Idempotent on (dataset, stable id, date); a
re-run after a new extraction updates the figure and its provenance.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "arrests"
DATASET, READER = "arrests_press", "extract_arrests@1"
GOV = {"Jenin": 3, "Tubas": 4, "Tulkarm": 5, "Nablus": 6, "Qalqilya": 7, "Salfit": 8, "Ramallah": 9,
       "Jericho": 10, "Jerusalem": 11, "Bethlehem": 12, "Hebron": 13, "West Bank": 2}

UPSERT = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num, unit,
                         occurred_at, occurred_precision, reported_at, raw_ref,
                         attrs, identity_key, v1_stable_id)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value)s, 'arrests',
        %(occurred)s, %(precision)s, %(reported)s, %(raw_ref)s, %(attrs)s::jsonb,
        %(identity)s, %(stable)s)
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE (v1_stable_id IS NOT NULL AND upper(sys_period) IS NULL)
DO UPDATE SET value_num = EXCLUDED.value_num,
              place_id = EXCLUDED.place_id,
              reported_at = EXCLUDED.reported_at,
              raw_ref = EXCLUDED.raw_ref,
              attrs = EXCLUDED.attrs
"""


def monthly_observations(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        auth = r.get("authority") or "unnamed"
        place = GOV.get(r.get("scope") or "West Bank", 2)
        occurred = datetime(int(r["period"][:4]), int(r["period"][5:7]), 1, tzinfo=timezone.utc)
        reported = datetime.fromisoformat(r["date"]).replace(tzinfo=timezone.utc).isoformat()
        base = {"authority": auth, "scope": r.get("scope") or "West Bank", "quote": r["quote"], "doc_ids": r["doc_ids"],
                "outlets": r.get("outlets"), "publisher": r.get("publisher"), "where": r.get("where"), "period_basis": r.get("basis"),
                "by_governorate": r.get("by_governorate"), "reader": READER}
        for measure, value in (("total", r["total"]), ("children", r.get("children")), ("women", r.get("women"))):
            if value is None:
                continue
            out.append({"place_id": place, "indicator": f"prisoners.arrests_reported.{measure}", "value": value, "occurred": occurred,
                        "precision": "month", "reported": reported, "raw_ref": r["url"],
                        "attrs": json.dumps(base, ensure_ascii=False),
                        "identity": f"arrests_press|{auth}|{place}|{r['period']}|{measure}",
                        "stable": f"{DATASET}:{measure}:{auth}:{place}:{r['period']}"})
    return out


def daily_observations(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        occurred = datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        out.append({"place_id": 2, "indicator": "prisoners.arrests_reported.overnight", "value": r["arrests_overnight"], "occurred": occurred,
                    "precision": "day", "reported": occurred.isoformat(), "raw_ref": None,
                    "attrs": json.dumps({"authority": "pps", "statements": r["statements"], "agree": r["agree"], "quote": r["quote"],
                                         "doc_ids": r["doc_ids"], "reader": READER}, ensure_ascii=False),
                    "identity": f"arrests_press|pps|2|{r['date']}|overnight", "stable": f"{DATASET}:overnight:{r['date']}"})
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args(argv)
    monthly = [json.loads(l) for l in (RAW / "monthly.ndjson").read_text().splitlines() if l.strip()]
    daily = [json.loads(l) for l in (RAW / "daily.ndjson").read_text().splitlines() if l.strip()]
    obs = monthly_observations(monthly) + daily_observations(daily)
    print(f"  {len(monthly)} monthly figures → {len(obs) - len(daily)} observations; {len(daily)} daily")
    if a.dry_run:
        print("  (dry run — nothing written)"); return 0
    from resolve.db import connect                                     # noqa: E402
    with connect() as conn:
        row = conn.execute("SELECT dataset_id FROM dataset WHERE key = %s", (DATASET,)).fetchone()
        if not row:
            raise SystemExit(f"dataset {DATASET} missing: apply migration 131")
        for o in obs:
            conn.execute(UPSERT, {**o, "dataset_id": row[0]})
        conn.commit()
    print(f"  loaded {len(obs)} observations into {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
