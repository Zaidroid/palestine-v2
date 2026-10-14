"""IPC's acute food insecurity analyses for the Gaza Strip: the people and the
share of the population in each phase, by area, current and projected.

    .venv/bin/python -m ops.fetch_ipc              # nightly
    .venv/bin/python -m ops.fetch_ipc --dry-run

WHY (2026-10-14). The famine classification itself: how many people in each of
the five IPC phases (1 minimal, 2 stressed, 3 crisis, 4 emergency, 5
catastrophe/famine), and phase 3 or worse, for each analysis since December
2023, with the projection each analysis made. Zaid: "we need this data for our
own research and data collections and relations" (on HDX's robots file).

THE ROUTE. HDX's dataset `state-of-palestine-acute-food-insecurity-country-data`
(contributed by IPC; "Public Domain / No restrictions (CC0)"): its record
through the CKAN API (ops/hdx.py), then the area and national long CSVs, ten
seconds between requests (the Crawl-Delay of HDX's robots file, whose
Disallow lines cover /api/ and .csv: read anyway at Zaid's word). IPC's own API
needs a key and ipcinfo.org sits behind a challenge: neither is used.

AREAS. IPC's areas change from one analysis to the next, and the file names
them inconsistently. Single governorates (North Gaza, Gaza, Deir al-Balah, Khan
Younis, Rafah) are placed at their governorate; combined areas are areas of
their own: the northern governorates (North Gaza and Gaza), the middle and south
(Deir al-Balah and Khan Younis), and in December 2023 the south's residents and
the displaced in the south apart. The May 2024 analysis names its areas "North
Gaza" and "Deir Al-Balah", but their populations are the combined areas'
(300,000, the February figure for "North Gaza & Gaza governorates"; 1,751,457)
and are read as such. The West Bank rows analyse nobody (population 0) and are
left out. The national file is the Gaza Strip's.

WHAT IS WRITTEN. data/raw/ipc/phases.json: for each analysis, validity period
(current, first projection), area and phase, the people (persons) and the share
(percent); dated by the period's first day (period_end beside it). Ledgered as
`ipc:phases`.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
from datetime import datetime, timezone

from ops import fetchlib as fl
from ops import hdx

SLUG = "state-of-palestine-acute-food-insecurity-country-data"
PAGE = hdx.PAGE + SLUG
FILES = ("ipc_pse_area_long.csv", "ipc_pse_national_long.csv")
OUT = fl.ROOT / "data" / "raw" / "ipc" / "phases.json"
LABEL = "ipc:phases"
PAUSE = 10.0                       # HDX's Crawl-Delay
FLOOR = 400
SOURCE_NAME = "Integrated Food Security Phase Classification (IPC), via HDX"

# area as printed (lower case) → (key, English, Arabic, governorate or None)
AREAS = {
    "north gaza": ("north_gaza", "North Gaza", "شمال غزة", "North Gaza"),
    "gaza": ("gaza", "Gaza governorate", "محافظة غزة", "Gaza"),
    "deir al-balah": ("deir_al_balah", "Deir al-Balah", "دير البلح", "Deir Al-Balah"),
    "khan younis": ("khan_younis", "Khan Younis", "خان يونس", "Khan Younis"),
    "rafah": ("rafah", "Rafah", "رفح", "Rafah"),
    "rafah governorate": ("rafah", "Rafah", "رفح", "Rafah"),
    "northern governorates": ("north_and_gaza", "the northern governorates (North Gaza and Gaza)",
                              "المحافظات الشمالية (شمال غزة وغزة)", None),
    "north gaza & gaza governorates": ("north_and_gaza", "the northern governorates (North Gaza and Gaza)",
                                       "المحافظات الشمالية (شمال غزة وغزة)", None),
    "deir al-balah & khan younis governorates": ("middle_and_khan_younis", "Deir al-Balah and Khan Younis",
                                                 "دير البلح وخان يونس", None),
    "deir al balah & khan younis governorates": ("middle_and_khan_younis", "Deir al-Balah and Khan Younis",
                                                 "دير البلح وخان يونس", None),
    "southern governorates": ("south_residents", "the southern governorates (their residents)",
                              "المحافظات الجنوبية (سكانها المقيمون)", None),
    "southern governorate idps": ("south_displaced", "the southern governorates (the displaced there)",
                                  "المحافظات الجنوبية (النازحون إليها)", None),
}
# The May 2024 analysis printed combined areas under single names (their populations say so).
MAY_2024 = {"north gaza": "north gaza & gaza governorates", "deir al-balah": "deir al-balah & khan younis governorates"}
NATIONAL = ("gaza_strip", "the Gaza Strip", "قطاع غزة", None)
PHASES = {"all": "analysed", "1": "phase1", "2": "phase2", "3": "phase3", "4": "phase4", "5": "phase5",
          "3+": "phase3plus"}


def _area(printed: str, analysis: str):
    k = " ".join(printed.strip().lower().replace("deir al balah", "deir al-balah").split())
    if analysis == "May 2024" and k in MAY_2024:
        k = MAY_2024[k]
    return AREAS.get(k)


def records(area_rows: list[dict], national_rows: list[dict]) -> tuple[list[dict], dict]:
    recs, notes = [], {"west_bank_rows_left_out": 0, "areas_not_known": []}
    src = {"name": SOURCE_NAME, "organization": "IPC", "url": PAGE}
    unknown = set()
    for rows, national in ((area_rows, False), (national_rows, True)):
        for r in rows:
            printed = r.get("Area") or "Gaza Strip"
            if not national and printed.strip().lower() == "west bank":
                notes["west_bank_rows_left_out"] += 1
                continue
            area = NATIONAL if national else _area(printed, r["Date of analysis"])
            if area is None:
                unknown.add(printed)
                continue
            phase = PHASES.get((r.get("Phase") or "").strip())
            if phase is None or r.get("From") in (None, ""):
                continue
            proj = (r.get("Validity period") or "").strip() == "first projection"
            suffix = f"_{area[0]}" + ("_projected" if proj else "")
            base = {"date": r["From"], "period_end": r.get("To"), "analysis": r["Date of analysis"],
                    "validity": r.get("Validity period"), "area": area[0], "area_printed": printed,
                    "location": ({"governorate": area[3], "region": "Gaza Strip"} if area[3]
                                 else {"region": "Gaza Strip"}),
                    "sources": [src]}
            if r.get("Number") not in (None, ""):
                m = f"population_{phase}{suffix}"
                recs.append({**base, "stable_id": f"ipc:{m}:{r['From']}", "measure": m,
                             "value": float(r["Number"]), "unit": "persons"})
            if phase != "analysed" and r.get("Percentage") not in (None, ""):
                m = f"share_{phase}{suffix}"
                recs.append({**base, "stable_id": f"ipc:{m}:{r['From']}", "measure": m,
                             "value": round(float(r["Percentage"]) * 100, 2), "unit": "percent"})
    notes["areas_not_known"] = sorted(unknown)
    recs.sort(key=lambda x: (x["measure"], x["date"]))
    return recs, notes


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    try:
        pkg = hdx.package(SLUG)
        texts = {}
        for name in FILES:
            res = next((r for r in pkg.get("resources") or [] if r.get("name") == name), None)
            if res is None:
                raise fl.FetchRefused(f"{LABEL}: HDX no longer lists {name}")
            time.sleep(PAUSE)
            texts[name] = fl.get(res["url"], timeout=120).decode("utf-8-sig", "replace")
        area_rows = list(csv.DictReader(io.StringIO(texts[FILES[0]])))
        national_rows = list(csv.DictReader(io.StringIO(texts[FILES[1]])))
        recs, notes = records(area_rows, national_rows)
        if notes["areas_not_known"]:
            raise fl.FetchRefused(f"{LABEL}: areas not known: {notes['areas_not_known']}; a person names them")
        if len(recs) < FLOOR:
            raise fl.FetchRefused(f"{LABEL}: {len(recs)} records below the floor of {FLOOR}")
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
    analyses = sorted({r["analysis"] for r in recs}, key=lambda a: datetime.strptime(a, "%b %Y"))
    meta = {"fetched_at": datetime.now(timezone.utc).isoformat(), "source": SOURCE_NAME, "source_url": PAGE,
            "license": pkg.get("license_title"), "attribution": "Acute food insecurity: IPC (Integrated Food Security Phase "
            "Classification), via HDX.",
            **hdx.stamp(pkg, None, kind="series"), "analyses": analyses, **notes}
    print(f"  ok   {LABEL}: {len(recs)} records, {len({r['measure'] for r in recs})} series, analyses "
          f"{analyses[0]} to {analyses[-1]}; West Bank rows left out {notes['west_bank_rows_left_out']}")
    if dry:
        fl.stage(staged, OUT.name, {"metadata": meta, "data": recs})
        return 0
    fl.write_atomic(OUT, {"metadata": meta, "data": recs})
    fl.event(LABEL, "ok", rows=len(recs), vintage=meta.get("vintage"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
