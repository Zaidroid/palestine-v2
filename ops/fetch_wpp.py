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
not written. Fifty-one indicators (INDICATORS below): the twelve taken on
2026-09-26 and thirty-nine more on 2026-10-13, every one filled for all 74
years. Counts are converted from thousands to persons with the source unit
kept in attrs; every value keeps three decimals, as the first twelve do.

WHAT EACH COLUMN IS
The UN's own two documents, read 2026-10-13, and nothing else: the indicator
reference beside the file (NOTES_URL: one name and one unit per column, the
unit copied here word for word as `wpp_unit`) and the Glossary of Demographic
Terms (GLOSSARY_URL: one definition per indicator). The names in
db/registry/names.yaml follow them.

WHAT IS NOT TAKEN, of the 54 value columns the file fills for Palestine
(measured 2026-10-13 on the 74 estimate years; the formulas are the UN's):
  DoublingTime  blank for 1965-1969 ("computed only for fast growing
                populations with growth rates exceeding 0.5 per cent"), and
                elsewhere exactly 100 x ln(2) / PopGrowthRate, which is held.
  PopDensity    TPopulation1July / 6,020 km2 in every year (largest
                difference 0.0001): population_total on another scale.
  PopChange     "the difference between the population at the end of the
                period and that at the beginning of the period":
                TPopulation1Jan of the next year minus this year's, to the
                last digit. The 1 January population is taken; its first
                difference is not.
Four of the columns that ARE taken are also arithmetic of two others, to
rounding: NatChange = Births - Deaths, NatChangeRT = CBR - CDR, PopSexRatio =
100 x male / female, CNMR = 1000 x NetMigrations / TPopulation1July. They are
kept because each is an indicator people ask for by name and none is another
series on a new scale; the sex cuts (male + female = total) are kept for the
same reason. Dropping one is one line here, one rule and one name.

TERMS
"Figures and tables in this publication can be reproduced without prior
permission under a Creative Commons license (CC BY 3.0 IGO)" — WPP 2024
Summary of Results, copyright page (read 2026-09-26). The data portal's own
terms page renders client-side and could not be read; the source row
(migration 089) records exactly that. The Download Center that serves this
file says the same of the data (read 2026-10-13, .../wpp/downloads): "Copyright
© 2024 by United Nations, made available under a Creative Commons license CC
BY 3.0 IGO".

VINTAGE
The file says which edition it is and when the UN released it
(metadata.vintage, vintage_basis, vintage_url), so the dataset row does too:
the loader copies them (ingest/databank.py read_vintage).

POSTURE (ops/fetchlib.py): atomic write, a floor (95 % of 74 years × 51
indicators; fewer is a truncated file and yesterday's copy stands), one ledger line per
attempt. WPP changes every two years, so a held copy younger than 30 days is
not re-downloaded (16.5 MB) — unless it was written before the indicators
taken today, in which case it is read again whatever its age: a loader
handed the old twelve would be refused by the spec's floor.

THE NEXT EDITION (read 2026-10-13)
There is none yet, and 2023 stays the newest estimate until there is. "The
next revision, originally planned for 2026, has been postponed for public
release until 11 July 2027" — World Population Prospects 2024: Interim Update,
19 January 2026 (.../wpp/assets/Files/WPP2024_Release-Note-rev1.pdf). That
interim update changed Togo only (its indicator file holds 151 rows, all
LocID 768); the file at URL was last modified 2024-12-13 and still parses to
the 888 held records, value for value. No WPP2025 or WPP2026 file exists
beside it (404). Everything here is pinned to the edition: URL, LABEL,
LAST_ESTIMATE, the stable ids and t_population_wpp's `revision` and dataset
key. A new edition revises the whole series back to 1950, and the UN's FAQ
says only the most recent one stays online outside its archive folder, so
this URL may stop answering the day it lands. Either way those names are
repointed by hand; nothing here finds a new edition by itself.
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
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import FetchRefused, check_floor, event, write_atomic  # noqa: E402

URL = ("https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/"
       "CSV_FILES/WPP2024_Demographic_Indicators_Medium.csv.gz")
TERMS_URL = "https://population.un.org/wpp/assets/Files/WPP2024_Summary-of-Results.pdf"
NOTES_URL = ("https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/"
             "CSV_FILES/WPP2024_Demographic_Indicators_notes.csv")
GLOSSARY_URL = "https://population.un.org/wpp/glossary-demographic-terms"
# The edition, and the day the UN says it released it (its FAQ, read 2026-10-13).
VINTAGE = "2024-07-11"
VINTAGE_URL = "https://population.un.org/wpp/faqs"
VINTAGE_SAID = ("The 2024 revision is the most recent revision of World Population "
                "Prospects, the official United Nations population estimates and "
                "projections released on 11 July 2024 (World Population Day)")
OUT = ROOT / "data" / "raw" / "wpp" / "palestine.json"
LOC_ID = "275"                          # State of Palestine
FIRST, LAST_ESTIMATE = 1950, 2023
MAX_AGE_DAYS = 30
LABEL = "wpp-2024"
UA = "palestine-v2 databank (+https://live-api.zaidlab.xyz)"

# WPP column → (our indicator, unit written, multiplier from WPP's unit, WPP's unit)
# The first twelve are the rows held since 2026-09-26: a changed word in one of
# them rewrites 74 held rows, so they stay as they are.
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
    # ── taken 2026-10-13; `wpp_unit` is the Unit column of the UN's indicator
    #    reference (NOTES_URL), word for word ──
    # population
    "TPopulation1Jan": ("population_total_1jan", "persons", 1000, "thousands"),
    "TPopulationMale1July": ("population_male", "persons", 1000, "thousands"),
    "TPopulationFemale1July": ("population_female", "persons", 1000, "thousands"),
    "PopSexRatio": ("sex_ratio", "males_per_100_females", 1, "males per 100 females"),
    "NatChange": ("natural_change", "persons", 1000, "thousands"),
    "NatChangeRT": ("natural_change_rate", "per_1000", 1, "per 1,000 population"),
    # fertility
    "Births1519": ("births_women_15_19", "persons", 1000, "thousands"),
    "NRR": ("net_reproduction_rate", "daughters_per_woman", 1, "surviving daughters per woman"),
    "MAC": ("mean_age_childbearing", "years", 1, "years"),
    "SRB": ("sex_ratio_at_birth", "males_per_100_females", 1, "males per 100 female births"),
    # mortality
    "DeathsMale": ("deaths_male", "persons", 1000, "thousands"),
    "DeathsFemale": ("deaths_female", "persons", 1000, "thousands"),
    "LExMale": ("life_expectancy_male", "years", 1, "years"),
    "LExFemale": ("life_expectancy_female", "years", 1, "years"),
    "LE15": ("life_expectancy_at_15", "years", 1, "years"),
    "LE15Male": ("life_expectancy_at_15_male", "years", 1, "years"),
    "LE15Female": ("life_expectancy_at_15_female", "years", 1, "years"),
    "LE65": ("life_expectancy_at_65", "years", 1, "years"),
    "LE65Male": ("life_expectancy_at_65_male", "years", 1, "years"),
    "LE65Female": ("life_expectancy_at_65_female", "years", 1, "years"),
    "LE80": ("life_expectancy_at_80", "years", 1, "years"),
    "LE80Male": ("life_expectancy_at_80_male", "years", 1, "years"),
    "LE80Female": ("life_expectancy_at_80_female", "years", 1, "years"),
    "InfantDeaths": ("infant_deaths", "persons", 1000, "thousands"),
    "LBsurvivingAge1": ("births_surviving_to_age_1", "persons", 1000, "thousands"),
    "Under5Deaths": ("under5_deaths", "persons", 1000, "thousands"),
    "Q0040": ("mortality_before_40", "per_1000", 1,
              "deaths under age 40 per 1,000 live births"),
    "Q0040Male": ("mortality_before_40_male", "per_1000", 1,
                  "deaths under age 40 per 1,000 male live births"),
    "Q0040Female": ("mortality_before_40_female", "per_1000", 1,
                    "deaths under age 40 per 1,000 female live births"),
    "Q0060": ("mortality_before_60", "per_1000", 1,
              "deaths under age 60 per 1,000 live births"),
    "Q0060Male": ("mortality_before_60_male", "per_1000", 1,
                  "deaths under age 60 per 1,000 male live births"),
    "Q0060Female": ("mortality_before_60_female", "per_1000", 1,
                    "deaths under age 60 per 1,000 female live births"),
    "Q1550": ("mortality_15_to_50", "per_1000", 1,
              "deaths under age 50 per 1,000 alive at age 15"),
    "Q1550Male": ("mortality_15_to_50_male", "per_1000", 1,
                  "deaths under age 50 per 1,000 males alive at age 15"),
    "Q1550Female": ("mortality_15_to_50_female", "per_1000", 1,
                    "deaths under age 50 per 1,000 females alive at age 15"),
    "Q1560": ("mortality_15_to_60", "per_1000", 1,
              "deaths under age 60 per 1,000 alive at age 15"),
    "Q1560Male": ("mortality_15_to_60_male", "per_1000", 1,
                  "deaths under age 60 per 1,000 males alive at age 15"),
    "Q1560Female": ("mortality_15_to_60_female", "per_1000", 1,
                    "deaths under age 60 per 1,000 females alive at age 15"),
    # migration
    "CNMR": ("net_migration_rate", "per_1000", 1, "per 1,000 population"),
}
# Columns the file fills for Palestine and this does not take, with the reason
# in the module docstring. tests/test_more_editions.py holds the two lists
# against a file's header, so a column the UN adds is seen and decided.
NOT_TAKEN = ("DoublingTime", "PopDensity", "PopChange")
# 3,774 when every value is present (measured 2026-10-13); 95 % of it, so a
# blank cell does not refuse a good file but a truncated one is refused
FLOOR = int((LAST_ESTIMATE - FIRST + 1) * len(INDICATORS) * 0.95)     # 3585


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


def holds_every_indicator(path: Path) -> bool:
    """False for a held file written before the indicators taken today (or one
    that cannot be read): its age then says nothing, and it is fetched again."""
    try:
        held = {r.get("indicator")
                for r in json.loads(path.read_text(encoding="utf-8"))["data"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
    return {ind for ind, *_ in INDICATORS.values()} <= held


def last_modified_day(header: str | None) -> str | None:
    """The HTTP Last-Modified header as a day, or None when the server sent
    none that can be read."""
    try:
        return parsedate_to_datetime(header).date().isoformat()
    except (TypeError, ValueError):
        return None


def vintage(last_modified: str | None) -> dict:
    """What the raw file says about the publisher's vintage: the edition's
    release day as the UN states it, the sentence, and where it stands."""
    basis = (f"the day the UN released the edition this file belongs to, World "
             f"Population Prospects 2024. Its FAQ (read 2026-10-13): \"{VINTAGE_SAID}\". "
             f"The estimates end at {LAST_ESTIMATE}")
    if last_modified:
        basis += f"; the data file's HTTP Last-Modified is {last_modified}"
    return {"vintage": VINTAGE, "vintage_basis": basis, "vintage_url": VINTAGE_URL}


def main(argv: list[str]) -> int:
    if "--force" not in argv and _fresh(OUT) and holds_every_indicator(OUT):
        print(f"{LABEL}: held copy is younger than {MAX_AGE_DAYS} days — not re-fetched")
        return 0
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r:
            modified = last_modified_day(r.headers.get("Last-Modified"))
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
                       "metadata": {**vintage(modified),
                                    "indicators": len({r["indicator"] for r in recs}),
                                    "indicator_reference_url": NOTES_URL,
                                    "glossary_url": GLOSSARY_URL},
                       "data": recs})
    event(LABEL, "ok", rows=len(recs), indicators=len({r["indicator"] for r in recs}),
          data_through=str(LAST_ESTIMATE))
    print(f"{LABEL}: {len(recs)} rows ({FIRST}-{LAST_ESTIMATE}) → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
