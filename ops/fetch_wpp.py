"""The 1950s, from the UN: World Population Prospects 2024 for the State of Palestine (P1-B.4).

    .venv/bin/python -m ops.fetch_wpp            # fetch if the held copy is older than 30 days
    .venv/bin/python -m ops.fetch_wpp --force

WHY
The databank held 5 rows for the whole 1950s (PLAN §4 R4). The scout found one
source with annual numbers for 1950-1966: UN DESA's World Population Prospects.
They are MODELLED estimates (WPP reconstructs the past from censuses, surveys
and registration, revised every two years), and every row says so.

WHAT IS KEPT
The State of Palestine (LocID 275), the Medium variant, years 1950-2023 — the
ESTIMATES. WPP's file runs to 2100; the projections are not the past and are
not written. Twelve indicators (INDICATORS below), counts converted from
thousands to persons with the source unit kept in attrs.

TERMS
"Figures and tables in this publication can be reproduced without prior
permission under a Creative Commons license (CC BY 3.0 IGO)" — WPP 2024
Summary of Results, copyright page (read 2026-09-26). The data portal's own
terms page renders client-side and could not be read; the source row
(migration 089) records exactly that.

POSTURE (ops/fetchlib.py): atomic write, a floor (95 % of 74 years × 12
indicators; fewer is a truncated file and yesterday's copy stands), one ledger line per
attempt. WPP changes every two years, so a held copy younger than 30 days is
not re-downloaded (16.5 MB).
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import FetchRefused, check_floor, event, write_atomic  # noqa: E402

URL = ("https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/"
       "CSV_FILES/WPP2024_Demographic_Indicators_Medium.csv.gz")
TERMS_URL = "https://population.un.org/wpp/assets/Files/WPP2024_Summary-of-Results.pdf"
OUT = ROOT / "data" / "raw" / "wpp" / "palestine.json"
LOC_ID = "275"                          # State of Palestine
FIRST, LAST_ESTIMATE = 1950, 2023
MAX_AGE_DAYS = 30
LABEL = "wpp-2024"
UA = "palestine-v2 databank (+https://live-api.zaidlab.xyz)"

# WPP column → (our indicator, unit written, multiplier from WPP's unit, WPP's unit)
INDICATORS = {
    "TPopulation1July": ("population_total", "persons", 1000, "thousands"),
    "Births": ("births", "persons", 1000, "thousands"),
    "Deaths": ("deaths", "persons", 1000, "thousands"),
    "NetMigrations": ("net_migration", "persons", 1000, "thousands"),
    "CBR": ("crude_birth_rate", "per_1000", 1, "per 1,000 population"),
    "CDR": ("crude_death_rate", "per_1000", 1, "per 1,000 population"),
    "TFR": ("total_fertility_rate", "births_per_woman", 1, "live births per woman"),
    "LEx": ("life_expectancy", "years", 1, "years at birth"),
    "IMR": ("infant_mortality_rate", "per_1000", 1, "infant deaths per 1,000 live births"),
    "Q5": ("under5_mortality_rate", "per_1000", 1, "deaths under 5 per 1,000 live births"),
    "MedianAgePop": ("median_age", "years", 1, "years"),
    "PopGrowthRate": ("population_growth_rate", "percent", 1, "percent"),
}
# 888 when every value is present (measured 2026-09-26); 95 % of it, so one
# blank cell does not refuse a good file but a truncated one is refused
FLOOR = int((LAST_ESTIMATE - FIRST + 1) * len(INDICATORS) * 0.95)     # 843


def parse(text: str) -> list[dict]:
    """The Palestine rows of the CSV, estimates only, one record per (year,
    indicator)."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("LocID") != LOC_ID or row.get("Variant") != "Medium":
            continue
        try:
            year = int(float(row["Time"]))
        except (KeyError, ValueError):
            continue
        if not FIRST <= year <= LAST_ESTIMATE:
            continue                          # projections are not the past
        for col, (ind, unit, mult, src_unit) in INDICATORS.items():
            raw = (row.get(col) or "").strip()
            if not raw:
                continue
            value = float(raw) * mult
            out.append({"stable_id": f"{LABEL}:{year}:{ind}", "year": year,
                        "indicator": ind, "value": round(value, 3), "unit": unit,
                        "wpp_column": col, "wpp_unit": src_unit,
                        "location": row.get("Location")})
    return out


def _fresh(path: Path, days: int = MAX_AGE_DAYS) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < days * 86400


def main(argv: list[str]) -> int:
    if "--force" not in argv and _fresh(OUT):
        print(f"{LABEL}: held copy is younger than {MAX_AGE_DAYS} days — not re-fetched")
        return 0
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r:
            text = gzip.decompress(r.read()).decode("utf-8-sig")
        recs = parse(text)
        check_floor(LABEL, len(recs), FLOOR)
    except FetchRefused as e:
        print(e, file=sys.stderr)
        return 1
    except Exception as e:                                  # noqa: BLE001
        event(LABEL, "error", error=str(e)[:300])
        print(f"{LABEL}: {e}", file=sys.stderr)
        return 1
    write_atomic(OUT, {"fetched_at": datetime.now(timezone.utc).isoformat(),
                       "source": "UN DESA Population Division — World Population Prospects 2024",
                       "url": URL, "terms_url": TERMS_URL, "license": "CC-BY-IGO-3.0",
                       "note": "modelled estimates, Medium variant, 1950-2023; projections not kept",
                       "data": recs})
    event(LABEL, "ok", rows=len(recs))
    print(f"{LABEL}: {len(recs)} rows ({FIRST}-{LAST_ESTIMATE}) → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
