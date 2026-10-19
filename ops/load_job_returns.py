"""Load the reviewed returns of the DeepSeek harness's jobs 03, 04 and 05.

    .venv/bin/python -m ops.load_job_returns              # load all three
    .venv/bin/python -m ops.load_job_returns --dry-run
    .venv/bin/python -m ops.load_job_returns --only 03

One-off, reviewed files under data/raw/jobs/NN/ (docs/jobs/JOB-NN-RETURN.md
says how each was read and checked); not in the nightly. Idempotent on
(dataset, stable id, date).

  03  PCBS energy tables 2012 → 2018 → pcbs_fuel_monthly (the dashboard holds
      2019 →; the overlap 2019–2023 agreed on all 720 cells, so those years are
      not loaded twice). Coal has no indicator and is left out.
  04  settlement announcements (keep + fix) → settlements.units_announced;
      new outposts (keep + fix) → settlements.outpost_reported.
  05  rota statements with hours → energy.gaza.rota_hours_stated.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "data" / "raw" / "jobs"
GOV = {"Jenin": 3, "Tubas": 4, "Tulkarm": 5, "Nablus": 6, "Qalqilya": 7, "Qalqiliya": 7, "Salfit": 8, "Ramallah": 9,
       "Jericho": 10, "Jerusalem": 11, "Bethlehem": 12, "Hebron": 13}
FUEL_PRODUCT = {"diesel": ("diesel", "ILS/L"), "gasoline_95": ("gasoline_95", "ILS/L"), "kerosene": ("kerosene", "ILS/L"),
                "lpg_12kg": ("lpg_12kg_delivered", "ILS/cylinder")}
FUEL_REGION = {"West Bank": (2, "West Bank"), "Jerusalem": (11, "East Jerusalem"), "Gaza Strip": (1, "Gaza Strip")}
GAZA_AREA = {"Gaza Strip": 1, "North Gaza": 14, "Gaza City": 15, "Middle Area": 16, "Khan Younis": 17, "Rafah": 18}

UPSERT = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num, unit,
                         occurred_at, occurred_precision, reported_at, raw_ref,
                         attrs, identity_key, v1_stable_id)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value)s, %(unit)s,
        %(occurred)s, %(precision)s, %(reported)s, %(raw_ref)s, %(attrs)s::jsonb,
        %(identity)s, %(stable)s)
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE (v1_stable_id IS NOT NULL AND upper(sys_period) IS NULL)
DO UPDATE SET value_num = EXCLUDED.value_num,
              place_id = EXCLUDED.place_id,
              unit = EXCLUDED.unit,
              reported_at = EXCLUDED.reported_at,
              raw_ref = EXCLUDED.raw_ref,
              attrs = EXCLUDED.attrs
"""


def _rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _day(s: str) -> datetime:
    return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)


def job03(reported: str) -> tuple[str, list[dict]]:
    out = []
    for r in _rows(JOBS / "03" / "pcbs_fuel_monthly.ndjson"):
        if r["product"] not in FUEL_PRODUCT or r["period"] >= "2019-01" or r["region"] not in FUEL_REGION:
            continue
        product, unit = FUEL_PRODUCT[r["product"]]
        place_id, region = FUEL_REGION[r["region"]]
        slug = region.lower().replace(" ", "-")
        attrs = {"region": region, "region_printed": r["region"], "source_file": r["source_file"], "table": r["table"], "page": r["page"],
                 "quote": r["quote"], "unit_printed": r["unit"], "confidence": r.get("confidence"), "reader": "JOB-03 (PCBS Energy Tables)"}
        out.append({"place_id": place_id, "indicator": f"fuel.price.average.{product}", "value": float(r["value"]), "unit": unit,
                    "occurred": _day(r["period"] + "-01"), "precision": "month", "reported": reported,
                    "raw_ref": "https://www.pcbs.gov.ps/site/886/default.aspx", "attrs": json.dumps(attrs, ensure_ascii=False),
                    "identity": f"pcbs_fuel_monthly|{product}|{slug}|{r['period']}", "stable": f"pcbs_fuel_monthly:tables:{product}:{slug}:{r['period']}"})
    return "pcbs_fuel_monthly", out


def job04(reported: str) -> tuple[str, list[dict]]:
    out = []
    for r in _rows(JOBS / "04" / "events-units.reviewed.ndjson"):
        if r.get("verdict") not in ("keep", "fix") or not r.get("units"):
            continue
        place_id = 11 if (r.get("region") == "East Jerusalem") else 2
        attrs = {"stage": r.get("stage"), "settlement_en": r.get("settlement_en"), "settlement_other": r.get("settlement_other"),
                 "settlement_ar": r.get("settlement_ar"), "region": r.get("region"), "authority": r.get("authority"), "quote": r.get("quote"),
                 "doc_ids": r.get("doc_ids"), "outlets": r.get("outlets"), "where": r.get("where"), "verdict": r["verdict"],
                 "verdict_note": r.get("verdict_note"), "reader": "extract_settlement_events@1 + JOB-04 review"}
        out.append({"place_id": place_id, "indicator": "settlements.units_announced", "value": float(r["units"]), "unit": "housing_units",
                    "occurred": _day(r["date"]), "precision": "day", "reported": _day(r["date"]).isoformat(), "raw_ref": r.get("url"),
                    "attrs": json.dumps(attrs, ensure_ascii=False), "identity": f"settlements_press|units|{r['doc_id']}",
                    "stable": f"settlements_press_events:units:{r['doc_id']}"})
    for r in _rows(JOBS / "04" / "events-outposts.reviewed.ndjson"):
        if r.get("verdict") not in ("keep", "fix"):
            continue
        place_id = r.get("place_id") or GOV.get(r.get("governorate") or "") or 2
        attrs = {"place_raw": r.get("place_raw"), "place_en": r.get("place_en"), "governorate": r.get("governorate"), "outpost_name": r.get("outpost_name"),
                 "kind": r.get("kind"), "quote": r.get("quote"), "doc_ids": r.get("doc_ids"), "outlets": r.get("outlets"), "published": r.get("published"),
                 "verdict": r["verdict"], "verdict_note": r.get("verdict_note"), "reader": "extract_settlement_events@1 + JOB-04 review"}
        out.append({"place_id": place_id, "indicator": "settlements.outpost_reported", "value": 1.0, "unit": "events",
                    "occurred": _day(r["date"]), "precision": "day", "reported": _day(r.get("published") or r["date"]).isoformat(), "raw_ref": r.get("url"),
                    "attrs": json.dumps(attrs, ensure_ascii=False), "identity": f"settlements_press|outpost|{r['doc_id']}",
                    "stable": f"settlements_press_events:outpost:{r['doc_id']}"})
    return "settlements_press_events", out


def job05(reported: str) -> tuple[str, list[dict]]:
    out = []
    for r in _rows(JOBS / "05" / "rota_statements.ndjson"):
        if r.get("hours_per_day") is None:
            continue
        place_id = GAZA_AREA.get(r.get("area") or "Gaza Strip", 1)
        attrs = {"kind": r.get("kind"), "hours_on": r.get("hours_on"), "hours_off": r.get("hours_off"), "area": r.get("area"),
                 "authority_named": r.get("authority_named"), "quote": r.get("quote"), "doc_ids": r.get("doc_ids"), "publishers": r.get("publishers"),
                 "date_basis": r.get("date_basis"), "confidence": r.get("confidence"), "reader": "JOB-05 review"}
        out.append({"place_id": place_id, "indicator": "energy.gaza.rota_hours_stated", "value": float(r["hours_per_day"]), "unit": "hours_per_day",
                    "occurred": _day(r["as_of"]), "precision": "day", "reported": _day(r["published_at"]).isoformat(), "raw_ref": r.get("url"),
                    "attrs": json.dumps(attrs, ensure_ascii=False), "identity": f"gaza_rota_press|{r['doc_id']}",
                    "stable": f"gaza_electricity_rota_press:{r['doc_id']}"})
    return "gaza_electricity_rota_press", out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--only")
    a = ap.parse_args(argv)
    reported = datetime.now(timezone.utc).isoformat()
    jobs = {"03": job03, "04": job04, "05": job05}
    if a.only:
        jobs = {a.only: jobs[a.only]}
    batches = [(n, *fn(reported)) for n, fn in jobs.items()]
    for n, ds, obs in batches:
        print(f"  job {n}: {len(obs)} observations → {ds}")
    if a.dry_run:
        print("  (dry run — nothing written)"); return 0
    from resolve.db import connect                                     # noqa: E402
    with connect() as conn:
        for n, ds, obs in batches:
            row = conn.execute("SELECT dataset_id FROM dataset WHERE key = %s", (ds,)).fetchone()
            if not row:
                raise SystemExit(f"dataset {ds} missing: apply migration 135")
            for o in obs:
                conn.execute(UPSERT, {**o, "dataset_id": row[0]})
            print(f"  loaded job {n}: {len(obs)} into {ds}")
        conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
