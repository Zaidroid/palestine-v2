"""Gaza's daily electricity supply, 1 January 2017 → 30 September 2023: OCHA's
table from GEDCO's figures (supply by line, demand, hours of supply a day).

    .venv/bin/python -m ops.fetch_ocha_gaza_electricity              # fetch once + load
    .venv/bin/python -m ops.fetch_ocha_gaza_electricity --dry-run
    .venv/bin/python -m ops.fetch_ocha_gaza_electricity --file X.csv --dry-run

WHY (2026-10-19). Zaid asked for GEDCO's own schedules. GEDCO only ever
published them as posts and images; OCHA received GEDCO's figures daily and
tabulated them on ochaopt.org/page/gaza-strip-electricity-supply, in a Tableau
embed whose download is now switched off. A copy of the full table (2,464
days, no gaps) survives in public course repositories; it reproduces OCHA's
published 2019 average (12 h) and its 2017 crisis lows, and runs above OCHA's
November 2019 indicator PDF for 2017–18 (7.3 against 5.7 / 6.6), which the
dataset's note carries. The grid has been down since 11 October 2023; the table
ends the day before the war. Dataset ocha_gaza_electricity_daily, migration
130; source ocha_electricity (OCHA's site terms: non-commercial, no
redistribution — served here, withheld from partners).

THE TRAP. The column OCHA titled "Power_Cuts_hours_day" is hours of SUPPLY:
May 2018 shows 117 MW against 522 MW demand and 4.8, which only reads as
supply. It is loaded as energy.gaza.supply_hours_per_day. A daily average
across the strip: a rota of 4 on / 12 off is 6 hours.

The file is fetched once into data/raw/ocha/gaza_electricity.csv (the table
is frozen); three known rows are checked before anything is loaded, so a
different file never loads silently.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                       # noqa: E402

COPY = "https://raw.githubusercontent.com/sondosaabed/Gaza-Electricity-Supply-AVLTree/main/Electricy/src/resources/Electricity.csv"
PAGE = "https://www.ochaopt.org/page/gaza-strip-electricity-supply"
RAW = fl.ROOT / "data" / "raw" / "ocha"
OUT = RAW / "gaza_electricity.csv"
DATASET, READER, LABEL = "ocha_gaza_electricity_daily", "fetch_ocha_gaza_electricity@1", "ocha:gaza_electricity"
GAZA = 1                                         # the Gaza Strip region place
MIN_ROWS = 2400                                  # 2,464 days
COLUMNS = {"Israeli_Lines_MWs": ("energy.gaza.supply_mw_israel_lines", "MW"),
           "Gaza_Power_Plant_MWs": ("energy.gaza.supply_mw_power_plant", "MW"),
           "Egyptian_Lines_MWs": ("energy.gaza.supply_mw_egypt_lines", "MW"),
           "Total_daily_Supply_available_in_MWs": ("energy.gaza.supply_mw", "MW"),
           "Overall_demand_in_MWs": ("energy.gaza.demand_mw", "MW"),
           "Power_Cuts_hours_day_400mg": ("energy.gaza.supply_hours_per_day", "hours_per_day")}
# Rows the table must reproduce (OCHA's crisis low, a 2019 day, the last day before the war)
KNOWN = {"2017-07-13": ("Total_daily_Supply_available_in_MWs", 70.0, "Power_Cuts_hours_day_400mg", 3.0),
         "2019-08-11": ("Total_daily_Supply_available_in_MWs", 185.0, "Power_Cuts_hours_day_400mg", 12.0),
         "2023-09-30": ("Total_daily_Supply_available_in_MWs", 190.0, "Power_Cuts_hours_day_400mg", 13.5)}

UPSERT = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num, unit,
                         occurred_at, occurred_precision, reported_at, raw_ref,
                         attrs, identity_key, v1_stable_id)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value)s, %(unit)s,
        %(occurred)s, 'day', %(reported)s, %(raw_ref)s, %(attrs)s::jsonb,
        %(identity)s, %(stable)s)
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE (v1_stable_id IS NOT NULL AND upper(sys_period) IS NULL)
DO UPDATE SET value_num = EXCLUDED.value_num,
              unit = EXCLUDED.unit,
              reported_at = EXCLUDED.reported_at,
              raw_ref = EXCLUDED.raw_ref,
              attrs = EXCLUDED.attrs
"""


def parse(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and not set(COLUMNS) <= set(rows[0]):
        raise ValueError(f"table columns changed: {list(rows[0])}")
    out = []
    for r in rows:
        d = (r.get("Date") or "").strip()
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        rec = {"date": d}
        for col in COLUMNS:
            v = (r.get(col) or "").strip()
            rec[col] = float(v) if v not in ("", None) else None
        rec["temp_c"] = float(r["Temp"]) if (r.get("Temp") or "").strip() else None
        out.append(rec)
    return out


def check_known(rows: list[dict]) -> None:
    by = {r["date"]: r for r in rows}
    for d, (c1, v1, c2, v2) in KNOWN.items():
        r = by.get(d)
        if not r or r[c1] != v1 or r[c2] != v2:
            raise ValueError(f"known row {d} not reproduced: got {r and (r[c1], r[c2])}, expected {(v1, v2)}")


def observations(rows: list[dict], reported: str, sha: str) -> list[dict]:
    out = []
    for r in rows:
        occurred = datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        for col, (indicator, unit) in COLUMNS.items():
            if r[col] is None:
                continue
            attrs = {"column_printed": col, "temp_c": r["temp_c"], "copy_sha256": sha, "reader": READER, "page": PAGE}
            if col == "Power_Cuts_hours_day_400mg":
                attrs["note"] = "OCHA's column is titled power cuts; it is hours of supply (May 2018 check)"
            out.append({"place_id": GAZA, "indicator": indicator, "value": r[col], "unit": unit, "occurred": occurred,
                        "reported": reported, "raw_ref": PAGE, "attrs": json.dumps(attrs, ensure_ascii=False),
                        "identity": f"ocha_gaza_electricity|{indicator}|{r['date']}",
                        "stable": f"{DATASET}:{indicator.rsplit('.', 1)[1]}:{r['date']}"})
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--file")
    a = ap.parse_args(argv)
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        if a.file:
            text = Path(a.file).read_text(encoding="utf-8-sig")
        elif OUT.exists():
            text = OUT.read_text(encoding="utf-8-sig")
        else:
            req = urllib.request.Request(COPY, headers={"User-Agent": fl.UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                text = r.read().decode("utf-8-sig")
        rows = parse(text)
        fl.check_floor(LABEL, len(rows), MIN_ROWS)
        check_known(rows)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}")
        return 1
    except Exception as e:                                             # noqa: BLE001
        if not a.dry_run:
            fl.event(LABEL, "error", error=type(e).__name__)
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}")
        return 1
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    hours = [r["Power_Cuts_hours_day_400mg"] for r in rows if r["Power_Cuts_hours_day_400mg"] is not None]
    print(f"  ok   {LABEL}  {len(rows)} days, {rows[0]['date']} → {rows[-1]['date']}, hours/day {min(hours)}–{max(hours)}, known rows reproduced")
    if a.dry_run:
        print("         (dry run — nothing written)")
        return 0
    if not a.file and not OUT.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        (RAW / "gaza_electricity.meta.json").write_text(json.dumps({"fetched_at": fetched_at, "copy": COPY, "page": PAGE, "sha256": sha}))
    fl.event(LABEL, "ok", rows=len(rows), data_through=rows[-1]["date"])
    from resolve.db import connect                                     # noqa: E402
    with connect() as conn:
        row = conn.execute("SELECT dataset_id FROM dataset WHERE key = %s", (DATASET,)).fetchone()
        if not row:
            raise SystemExit(f"dataset {DATASET} missing: apply migration 130")
        obs = observations(rows, fetched_at, sha)
        for o in obs:
            conn.execute(UPSERT, {**o, "dataset_id": row[0]})
        conn.commit()
    print(f"  loaded {len(obs)} observations into {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
