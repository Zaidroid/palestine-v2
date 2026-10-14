"""ILO's quarterly labour figures for Palestine (ILOSTAT, from PCBS's Labour
Force Survey): the unemployment rate and the labour force participation rate.

    .venv/bin/python -m ops.fetch_ilostat              # nightly
    .venv/bin/python -m ops.fetch_ilostat --dry-run

WHY (2026-10-14). PCBS publishes its quarterly labour survey as press releases
(PDF and DOCX, no tables); ILO processes the survey's micro data into quarterly
series from 2000. Measured on 2026-10-14: 2000Q1 to 2025Q4, by sex and age.

THE ROUTE. ILO's data API, keyless: rplumber.ilo.org/data/indicator/?id=<id>
&ref_area=PSE&format=.csv, and its note dictionaries /metadata/dic/?var=
note_source|note_indicator (its robots file is empty; ilostat.ilo.org itself
sits behind a challenge and is not used). Four GETs a night, three seconds
apart. Licence: ILOSTAT data are published under CC BY 4.0.

COVERAGE CHANGES IN 2023Q4. From the fourth quarter of 2023 every row carries
ILO's note S4:6333, "Geographical coverage: Excluding Gaza Strip": the survey
could not be run in Gaza. Those quarters are series of their own
(`..._excluding_gaza`), never joined to the quarters before, which cover the
West Bank and Gaza: unemployment's jump from 25.7% to 35.2% in 2024Q1 is the West
Bank's alone. A series break (obs_status B, "methodology revised") and a value
ILO flags unreliable (U) are kept on the row.

WHAT IS WRITTEN. data/raw/ilostat/quarterly.json: one record per indicator, sex
(total, men, women), age (15+, 15-24, 25+) and quarter, dated by the quarter's
first day (precision month; attrs.quarter, period_start, period_end).
Floor 1,500 records; never more than a tenth fewer than the file on disk.
Ledgered as `ilostat:quarterly`.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
from datetime import datetime, timezone

from ops import fetchlib as fl

API = "https://rplumber.ilo.org"
DATA = API + "/data/indicator/?id={id}&ref_area=PSE&format=.csv"
DIC = API + "/metadata/dic/?var={var}&lang=en&format=.csv"
PAGE = "https://ilostat.ilo.org/data/country-profiles/pse/"
OUT = fl.ROOT / "data" / "raw" / "ilostat" / "quarterly.json"
LABEL = "ilostat:quarterly"
PAUSE = 3.0
FLOOR = 1500
SHRINK = 0.10
SOURCE_NAME = "ILOSTAT (ILO), from PCBS's Labour Force Survey"

INDICATORS = {
    "UNE_DEAP_SEX_AGE_RT_Q": ("unemployment_rate", "unemployment rate", "معدل البطالة"),
    "EAP_DWAP_SEX_AGE_RT_Q": ("participation_rate", "labour force participation rate",
                              "نسبة المشاركة في القوى العاملة"),
}
SEX = {"SEX_T": ("total", "", ""), "SEX_M": ("men", "men", "الذكور"), "SEX_F": ("women", "women", "الإناث")}
AGE = {"AGE_YTHADULT_YGE15": ("15plus", "aged 15 and over", "15 سنة فأكثر"),
       "AGE_YTHADULT_Y15-24": ("15_24", "aged 15 to 24", "15 إلى 24 سنة"),
       "AGE_YTHADULT_YGE25": ("25plus", "aged 25 and over", "25 سنة فأكثر")}
EXCLUDING_GAZA = "S4:6333"
STATUS = {"B": "break in series", "U": "unreliable", "": None}


def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def quarter_dates(q: str) -> tuple[str, str] | None:
    """'2025Q4' → ('2025-10-01', '2025-12-31')."""
    if len(q) != 6 or q[4] != "Q" or q[5] not in "1234":
        return None
    y, n = int(q[:4]), int(q[5])
    ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    return f"{y}-{3 * n - 2:02d}-01", f"{y}-{ends[n]}"


def records(rows_by_id: dict[str, list[dict]], notes: dict[str, str]) -> tuple[list[dict], dict]:
    recs, skipped = [], 0
    src = {"name": SOURCE_NAME, "organization": "International Labour Organization", "url": PAGE}
    for iid, rows in rows_by_id.items():
        key = INDICATORS[iid][0]
        for r in rows:
            if r["sex"] not in SEX or r["classif1"] not in AGE:
                continue
            q = quarter_dates(r["time"])
            if q is None or r.get("obs_value") in ("", None):
                skipped += 1
                continue
            excl = EXCLUDING_GAZA in (r.get("note_source") or "")
            measure = f"{key}_{SEX[r['sex']][0]}_{AGE[r['classif1']][0]}" + ("_excluding_gaza" if excl else "")
            codes = [c for f in ("note_source", "note_indicator", "note_classif")
                     for c in (r.get(f) or "").split("_") if c]
            recs.append({"stable_id": f"ilostat:{measure}:{r['time']}", "measure": measure,
                         "value": float(r["obs_value"]), "unit": "percent", "date": q[0],
                         "quarter": r["time"], "period_start": q[0], "period_end": q[1],
                         "obs_status": STATUS.get(r.get("obs_status") or "", r.get("obs_status")),
                         "notes": [notes.get(c, c) for c in codes] or None,
                         "ilo_source": r.get("source"),
                         "location": {"region": "West Bank" if excl else "Palestine"},
                         "sources": [src]})
    recs.sort(key=lambda x: (x["measure"], x["date"]))
    return recs, {"skipped_no_value": skipped}


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    try:
        rows_by_id = {}
        for i, iid in enumerate(INDICATORS):
            if i:
                time.sleep(PAUSE)
            rows_by_id[iid] = _csv(fl.get(DATA.format(id=iid), timeout=180).decode("utf-8", "replace"))
        notes = {}
        for var in ("note_source", "note_indicator"):
            time.sleep(PAUSE)
            for r in _csv(fl.get(DIC.format(var=var), timeout=120).decode("utf-8", "replace")):
                notes[r.get(var)] = r.get(f"{var}.label")
        recs, extra = records(rows_by_id, notes)
        if len(recs) < FLOOR:
            raise fl.FetchRefused(f"{LABEL}: {len(recs)} records below the floor of {FLOOR}")
        if OUT.exists():
            held = len(json.loads(OUT.read_text()).get("data") or [])
            if held and len(recs) < held * (1 - SHRINK):
                raise fl.FetchRefused(f"{LABEL}: {len(recs)} records against {held} held, more than a tenth fewer")
    except fl.FetchRefused as e:
        print(f"  REFUSED {LABEL}: {e}", file=sys.stderr)
        if not dry:
            fl.event(LABEL, "refused", why=str(e)[:300])
        return 1
    except Exception as e:                                   # noqa: BLE001
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:300])
        return 1
    quarters = sorted({r["quarter"] for r in recs})
    meta = {"fetched_at": datetime.now(timezone.utc).isoformat(), "source": SOURCE_NAME, "source_url": PAGE,
            "license": "CC BY 4.0 (ILOSTAT)", "attribution": "Labour statistics: ILOSTAT (ILO), from the "
            "Palestinian Central Bureau of Statistics' Labour Force Survey.",
            "vintage": quarters[-1], "vintage_basis": "the newest quarter ILO gives",
            "first_quarter": quarters[0], "series": len({r["measure"] for r in recs}), **extra}
    print(f"  ok   {LABEL}: {len(recs)} records, {meta['series']} series, {quarters[0]} to {quarters[-1]}")
    if dry:
        print(f"         would write {OUT.relative_to(fl.ROOT)} (dry run)")
        fl.stage(staged, OUT.name, {"metadata": meta, "data": recs})
        return 0
    fl.write_atomic(OUT, {"metadata": meta, "data": recs})
    fl.event(LABEL, "ok", rows=len(recs), vintage=quarters[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
