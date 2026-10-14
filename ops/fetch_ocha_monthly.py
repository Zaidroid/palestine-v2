"""OCHA oPt's record of Palestinians killed by Israelis, by month (2008 on):
by area, perpetrator, governorate, age and the victim's affiliation.

    .venv/bin/python -m ops.fetch_ocha_monthly              # nightly
    .venv/bin/python -m ops.fetch_ocha_monthly --dry-run

WHY (2026-10-14). The databank reads OCHA's casualty report as totals sliced
five ways (ops/fetch_ocha.py: year, region, governorate, age group, weapon), so
it cannot say how many were killed in a month, by whom, or where. The report's
own incident table answers that: one grouped query over vw_BS_Pal_Fatalities by
day, area, governorate, perpetrator, age and the victim's affiliation, summing
`Fat`, through the same public API the embed calls (ops/pbi_public.py). The
victims' names are in that table; they are never asked for.

WHAT THE REPORT IS. OCHA's verified record of Palestinians killed by Israelis
(every perpetrator in it is Israeli: military forces, non-military security
forces such as police, settlers, civilians), the West Bank including East
Jerusalem, Gaza, and Israel, from 1 January 2008. Gaza's dead from 7 October
2023 are NOT in it (OCHA records them only once verified); its Gaza rows end in
2023. Measured 2026-10-14: 7,500 killed; West Bank 506 in 2023, 499 in 2024,
240 in 2025.

WHAT IS WRITTEN. data/raw/ocha/fatalities_monthly.json: one record per series
and month from January 2008 to this month (a month with none recorded is 0; the
newest is partial). The sum of each split (area, perpetrator, age, affiliation)
is checked against the total every month; a split that does not add up is
refused. Ledgered as `ocha:fatalities_monthly`. Terms: the source row
ocha_casualties (OCHA's terms of use: non-commercial, no redistribution).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from ops import fetch_ocha as O
from ops import fetchlib as fl
from ops import pbi_public as pb

OUT = fl.ROOT / "data" / "raw" / "ocha" / "fatalities_monthly.json"
LABEL = "ocha:fatalities_monthly"
FLOOR_TOTAL = 7000
SOURCE = dict(O.CAS_SOURCE)

AREA = {"West Bank": "west_bank", "Gaza Strip": "gaza_strip", "Israel": "israel"}
DOER = {"Military forces": "israeli_forces", "Non-military security forces": "israeli_security",
        "Civilian-settler": "settlers"}                   # the rest: other_or_disputed
AGE = {"Children": "children", "Adults": "adults"}       # the rest: age_unknown
VICTIM = {"Civilian": "civilians", "Armed group": "armed_group_members"}   # the rest: affiliation_other
GOV = {"Bethlehem": "Bethlehem", "Deir Al-Balah": "Deir Al-Balah", "Gaza": "Gaza", "Gaza North": "North Gaza",
       "Hebron": "Hebron", "Jenin": "Jenin", "Jericho": "Jericho", "Jerusalem": "Jerusalem",
       "Khan Yunis": "Khan Younis", "Nablus": "Nablus", "Qalqiliya": "Qalqilya", "Rafah": "Rafah",
       "Ramallah": "Ramallah", "Salfit": "Salfit", "Tubas": "Tubas", "Tulkarm": "Tulkarm"}


def month_of(ms) -> str | None:
    if ms is None:
        return None
    d = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    return f"{d.year:04d}-{d.month:02d}-01"


def _months(first: str, last: str) -> list[str]:
    y, m, out = int(first[:4]), int(first[5:7]), []
    while (y, m) <= (int(last[:4]), int(last[5:7])):
        out.append(f"{y}-{m:02d}-01")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly(rows: list[list], today) -> tuple[list[dict], dict]:
    """Grouped rows [day ms, area, governorate, perpetrator, age, victim affiliation, killed] → records."""
    by: dict[str, Counter] = defaultdict(Counter)
    gov_unknown: Counter = Counter()
    for day, area, gov, doer, age, victim, n in rows:
        mo, n = month_of(day), int(n or 0)
        if mo is None or not n:
            continue
        c = by[mo]
        c["killed"] += n
        c[f"killed_{AREA.get(area, 'area_not_listed')}"] += n
        c[f"killed_by_{DOER.get(doer, 'other_or_disputed')}"] += n
        c[f"killed_{AGE.get(age, 'age_unknown')}"] += n
        c[f"killed_{VICTIM.get(victim, 'affiliation_other')}"] += n
        if gov in GOV:
            c[f"killed_gov:{GOV[gov]}"] += n
        else:
            gov_unknown[gov] += n
    for mo, c in by.items():                               # every split adds up to the month's total
        for prefix, keys in (("area", [f"killed_{v}" for v in list(AREA.values()) + ["area_not_listed"]]),
                             ("perpetrator", [f"killed_by_{v}" for v in list(DOER.values()) + ["other_or_disputed"]]),
                             ("age", [f"killed_{v}" for v in list(AGE.values()) + ["age_unknown"]]),
                             ("affiliation", [f"killed_{v}" for v in list(VICTIM.values()) + ["affiliation_other"]])):
            if sum(c[k] for k in keys) != c["killed"]:
                raise fl.FetchRefused(f"{LABEL}: {mo}: the {prefix} split does not add up to {c['killed']}")
    this_month = f"{today.year}-{today.month:02d}-01"
    months = _months(min(by), this_month) if by else []
    measures = (["killed"] + [f"killed_{v}" for v in AREA.values()]
                + [f"killed_by_{v}" for v in list(DOER.values()) + ["other_or_disputed"]]
                + ["killed_children", "killed_civilians", "killed_armed_group_members"])
    recs = []
    for mo in months:
        c = by.get(mo, Counter())
        partial = True if mo == this_month else None
        for m in measures:
            recs.append({"stable_id": f"ocha_monthly:{m}:{mo}", "measure": m, "value": c[m], "unit": "persons",
                         "date": mo, "partial_month": partial, "location": {"region": "Palestine"},
                         "sources": [SOURCE]})
        for gname in GOV.values():
            key = gname.lower().replace(" ", "_").replace("-", "_")
            recs.append({"stable_id": f"ocha_monthly:killed_{key}:{mo}", "measure": f"killed_gov_{key}",
                         "value": c[f"killed_gov:{gname}"], "unit": "persons", "date": mo, "partial_month": partial,
                         "location": {"governorate": gname, "region": "Palestine"}, "sources": [SOURCE]})
    notes = {"killed_total": sum(c["killed"] for c in by.values()), "months": len(months),
             "first_month": months[0] if months else None,
             "governorate_not_listed": dict(gov_unknown)}
    return recs, notes


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    today = datetime.now(timezone.utc).date()
    try:
        rep = pb.Report(O.CASUALTIES_EMBED)
        res = rep.query("fatalities_monthly", O.CAS_ENTITY, [
            pb.col("Date", "day"), pb.col("Area", "area"), pb.col("Govornorate", "governorate"),
            pb.col("Doer Aff.", "perpetrator"), pb.col("Child/Adult", "age"), pb.col("Victim Aff.", "victim"),
            pb.agg("Fat", 0, "killed")])
        recs, notes = monthly(res["rows"], today)
        if notes["killed_total"] < FLOOR_TOTAL:
            raise fl.FetchRefused(f"{LABEL}: {notes['killed_total']} killed in all, below the floor of {FLOOR_TOTAL}")
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
    meta = {"fetched_at": datetime.now(timezone.utc).isoformat(), "source": SOURCE["name"],
            "source_url": "https://www.ochaopt.org/data/casualties", "vintage": (rep.last_refresh or "")[:10],
            "vintage_basis": "the report model's last refresh", **notes}
    print(f"  ok   {LABEL}: {notes['killed_total']:,} killed, {notes['months']} months from {notes['first_month']}, "
          f"{len(recs):,} records; model refreshed {rep.last_refresh}")
    if dry:
        fl.stage(staged, OUT.name, {"metadata": meta, "data": recs})
        return 0
    from ingest import bronze
    for name, raw in rep.raw:
        bronze.put("ocha_casualties_monthly", raw, "json", url=f"{O.CASUALTIES_EMBED}#{name}")
    fl.write_atomic(OUT, {"metadata": meta, "data": recs})
    fl.event(LABEL, "ok", rows=len(recs), killed=notes["killed_total"], vintage=meta["vintage"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
