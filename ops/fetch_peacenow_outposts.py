"""Peace Now's list of settler outposts: one row per outpost at its
establishment month, and the monthly count per governorate.

    .venv/bin/python -m ops.fetch_peacenow_outposts              # fetch + load (nightly)
    .venv/bin/python -m ops.fetch_peacenow_outposts --dry-run    # fetch, print, write nothing
    .venv/bin/python -m ops.fetch_peacenow_outposts --file X.csv --dry-run

WHY (2026-10-19). Zaid asked for outposts by month. The archive pass
(ops/extract_settlement_events.py) finds about half of what Peace Now lists;
the list is public (a Google Sheet behind Settlement Watch's population page),
has 422 outposts with the establishment year and, from 2023, the month, the
district, the nearest settlement and coordinates. So the list is the series and
the archive is its detail. Dataset peacenow_outposts, migration 130; the source
row peace_now (no licence found, no redistribution) grades every row: served
here, withheld from partners.

THE SHEET. 'Established' is a Hebrew month abbreviation and a two-digit year
(ינו-26 = January 2026); 'Established Year' is always present; 5 rows have a
year and no month and become yearly rows. 'DB_ID' is NOT unique (342 of 422):
identity is (DB_ID, name). 'District' is the governorate as Peace Now names
it; 'Yatta' is the south of Hebron governorate; 32 rows carry none and count
on the West Bank only. 'x (UTM)' is the latitude and 'y(UTM)' the longitude
despite the labels (32.06, 35.33 is the West Bank).

A LIST OF WHAT STANDS. An evicted or legalised outpost leaves the list, so
the early years undercount what was established then; the note rides on the
indicator's warning. The sheet is re-read nightly and the loads are idempotent
on (dataset, stable id, month); an outpost that leaves the list keeps its row
here with the last sheet date it was seen in attrs (nothing is deleted).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                       # noqa: E402

URL = "https://docs.google.com/spreadsheets/d/1Hs_JdYPEs4oXs09zG3Hd4tWBpYo0ImkJ6WuXAEgMi0U/export?format=csv"
PAGE = "https://peacenow.org.il/en/settlements-watch/settlements-data/population"
RAW = fl.ROOT / "data" / "raw" / "peacenow"
OUT = RAW / "outposts.csv"
DATASET, READER, LABEL = "peacenow_outposts", "fetch_peacenow_outposts@1", "peacenow:outposts"
MIN_ROWS = 350                                   # 422 on 2026-10-19
HEB = {"ינו": 1, "פבר": 2, "מרץ": 3, "אפר": 4, "מאי": 5, "יונ": 6, "יול": 7, "אוג": 8, "ספט": 9, "אוק": 10, "נוב": 11, "דצמ": 12}
# Peace Now's district → the gazetteer's governorate place_id (place kind 'governorate')
GOV = {"Jenin": 3, "Tubas": 4, "Tulkarm": 5, "Nablus": 6, "Qalqiliya": 7, "Qalqilya": 7, "Salfit": 8, "Ramallah": 9,
       "Jericho": 10, "Jerusalem": 11, "Bethlehem": 12, "Hebron": 13, "Yatta": 13}
WEST_BANK = 2

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
              unit = EXCLUDED.unit,
              reported_at = EXCLUDED.reported_at,
              raw_ref = EXCLUDED.raw_ref,
              attrs = EXCLUDED.attrs
"""


def established(cell: str, year: str) -> tuple[str, str, str | None] | None:
    """('2026-01', 'month', None) from 'ינו-26'; ('1997', 'year', 'יונ-05') when the
    month cell names another year than the year column (a few old rows do: the
    year column is Peace Now's reviewed field, the month cell is kept as a note);
    ('2026', 'year', None) from the year alone."""
    cell = (cell or "").strip()
    year = str(year or "").strip()
    if "-" in cell:
        mon, yy = cell.split("-", 1)
        if mon in HEB and yy.strip().isdigit():
            y = int(yy.strip()); y += 2000 if y < 50 else 1900
            if year.isdigit() and str(y) != year:
                return f"{int(year):04d}", "year", cell
            return f"{y:04d}-{HEB[mon]:02d}", "month", None
    if year.isdigit():
        return f"{int(year):04d}", "year", None
    return None


def parse(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    need = {"Name", "DB_ID", "Settlement Type", "Established Year", "Established", "District"}
    if rows and not need <= set(rows[0]):
        raise ValueError(f"sheet columns changed: {list(rows[0])[:8]}")
    out = []
    for r in rows:
        when = established(r.get("Established"), r.get("Established Year"))
        if not when or not r.get("Name"):
            continue
        kind = (r.get("Settlement Type") or "").strip().lower()
        out.append({"name": r["Name"].strip(), "name_he": (r.get("Name Hebrew") or "").strip(), "db_id": (r.get("DB_ID") or "").strip(),
                    "kind": "farm" if "farm" in kind else "outpost", "type_printed": r.get("Settlement Type"),
                    "period": when[0], "precision": when[1], "month_cell_disagrees": when[2],
                    "district": (r.get("District") or "").strip() or None,
                    "nearest": (r.get("Nearest Settlemet") or r.get("Nearest Settlement") or "").strip() or None,
                    "lat": _f(r.get("x (UTM)")), "lon": _f(r.get("y(UTM)")), "municipality": (r.get("Municipality") or "").strip() or None})
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _occurred(period: str) -> datetime:
    y, m = (int(period[:4]), int(period[5:7])) if len(period) == 7 else (int(period), 1)
    return datetime(y, m, 1, tzinfo=timezone.utc)


def observations(rows: list[dict], reported: str, sheet_date: str) -> list[dict]:
    out, counts = [], Counter()
    for r in rows:
        gov = GOV.get(r["district"] or "")
        place = gov if gov else WEST_BANK
        slug = (r["db_id"] or "x") + ":" + "".join(ch for ch in r["name"].lower() if ch.isalnum())[:40]
        attrs = {"name": r["name"], "name_he": r["name_he"], "db_id": r["db_id"], "kind": r["kind"], "type_printed": r["type_printed"],
                 "district_printed": r["district"], "nearest_settlement": r["nearest"], "lat": r["lat"], "lon": r["lon"],
                 "municipality": r["municipality"], "precision": r["precision"], "month_cell_disagrees": r["month_cell_disagrees"],
                 "seen_in_sheet": sheet_date, "reader": READER, "page": PAGE}
        out.append({"place_id": place, "indicator": "settlements.outpost", "value": 1, "unit": "events",
                    "occurred": _occurred(r["period"]), "precision": r["precision"], "reported": reported, "raw_ref": URL,
                    "attrs": json.dumps(attrs, ensure_ascii=False), "identity": f"peacenow_outpost|{slug}",
                    "stable": f"{DATASET}:outpost:{slug}"})
        counts[(place, r["period"], r["precision"])] += 1
    for (place, period, precision), n in sorted(counts.items()):
        out.append({"place_id": place, "indicator": "settlements.outposts_established", "value": n, "unit": "events",
                    "occurred": _occurred(period), "precision": precision, "reported": reported, "raw_ref": URL,
                    "attrs": json.dumps({"seen_in_sheet": sheet_date, "reader": READER, "page": PAGE,
                                         "note": "outposts standing today, by establishment " + precision}, ensure_ascii=False),
                    "identity": f"peacenow_outposts|{place}|{period}", "stable": f"{DATASET}:count:{place}:{period}"})
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
        else:
            req = urllib.request.Request(URL, headers={"User-Agent": fl.UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                text = r.read().decode("utf-8-sig")
        rows = parse(text)
        fl.check_floor(LABEL, len(rows), MIN_ROWS)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}")
        return 1
    except Exception as e:                                             # noqa: BLE001
        if not a.dry_run:
            fl.event(LABEL, "error", error=type(e).__name__)
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}")
        return 1
    years = Counter(r["period"][:4] for r in rows)
    months = sum(1 for r in rows if r["precision"] == "month")
    print(f"  ok   {LABEL}  {len(rows)} outposts, {min(years)} → {max(years)}, {months} with a month, "
          f"{sum(1 for r in rows if not r['district'])} without a district, "
          f"{sum(1 for r in rows if r['month_cell_disagrees'])} month cells kept as notes")
    if a.dry_run:
        print("         by year:", dict(sorted(years.items()))); print("         (dry run — nothing written)")
        return 0
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    fl.event(LABEL, "ok", rows=len(rows), data_through=max(r["period"] for r in rows))
    from resolve.db import connect                                     # noqa: E402
    with connect() as conn:
        row = conn.execute("SELECT dataset_id FROM dataset WHERE key = %s", (DATASET,)).fetchone()
        if not row:
            raise SystemExit(f"dataset {DATASET} missing: apply migration 130")
        obs = observations(rows, fetched_at, fetched_at[:10])
        for o in obs:
            conn.execute(UPSERT, {**o, "dataset_id": row[0]})
        conn.commit()
    print(f"  loaded {len(obs)} observations into {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
