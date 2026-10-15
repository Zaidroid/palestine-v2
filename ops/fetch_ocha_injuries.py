"""OCHA oPt's record of Palestinians injured by Israelis, by month (2008 on):
by area, perpetrator, governorate and age.

    .venv/bin/python -m ops.fetch_ocha_injuries              # nightly
    .venv/bin/python -m ops.fetch_ocha_injuries --dry-run

WHY (2026-10-15). The databank held OCHA's deaths by month (ops/fetch_ocha_monthly.py) but not its injuries,
which are about twenty times as many and carry most of the West Bank's daily violence: 167,092 Palestinians
injured from January 2008 to 15 October 2026 (measured that day), 2,364 of them in the West Bank in 2026 so
far. The casualty page (ochaopt.org/data/casualties) has a second public report, "Palestinian injuries", over
its own table vw_BS_Pal_Injuries; one grouped query by day, area, governorate, perpetrator and age summing
`Inj`, through the same public API the embed calls (ops/pbi_public.py). The table's names columns, if any, are
never asked for.

WHAT IT IS. OCHA's verified record of Palestinians injured by Israelis (military forces, non-military
security forces such as police, settlers, civilians), the West Bank including East Jerusalem, Gaza, and
Israel (incidents related to the West Bank). Like the deaths, Gaza's injured since 7 October 2023 are NOT in it:
its Gaza rows end in 2023 (378 that year, measured). `SA` joins two fields, child (Yes, No, Unknown) and sex:
a child is "Yes…".

WHAT IS WRITTEN. data/raw/ocha/injuries_monthly.json: one record per series and month from January 2008 to
this month (a month with none recorded is 0; the newest is partial). Each split (area, perpetrator, age) is
checked against the month's total; a split that does not add up is refused. Ledgered as
`ocha:injuries_monthly`. Terms: the source row ocha_casualties (OCHA's terms of use: non-commercial, no
redistribution), as the deaths.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from ops import fetch_ocha as O
from ops import fetch_ocha_monthly as M
from ops import fetchlib as fl
from ops import pbi_public as pb

OUT = fl.ROOT / "data" / "raw" / "ocha" / "injuries_monthly.json"
LABEL = "ocha:injuries_monthly"
INJURIES_EMBED = (
    "https://app.powerbi.com/view?r=eyJrIjoiZDY1ZjI2YWItMWQ0Yy00YzMzLWE1ZTAtOGE0YWZlMTJjZTFjIiwidCI6IjBmOWUzNWRi"
    "LTU0NGYtNGY2MC1iZGNjLTVlYTQxNmU2ZGM3MCIsImMiOjh9")
ENTITY = "vw_BS_Pal_Injuries"
FLOOR_TOTAL = 150000                                     # 167,092 measured 2026-10-15
SOURCE = dict(O.CAS_SOURCE)
AREA = {"West Bank": "west_bank", "Gaza Strip": "gaza_strip", "Israel (West Bank Related)": "israel"}


def age_of(sa) -> str:
    """`SA` is the child flag and the sex run together ("YesMale", "NoFemale", "Unknownunknown")."""
    s = str(sa or "")
    return "children" if s.startswith("Yes") else "adults" if s.startswith("No") else "age_unknown"


def monthly(rows: list[list], today) -> tuple[list[dict], dict]:
    """Grouped rows [day ms, area, governorate, perpetrator, SA, injured] → records."""
    by: dict[str, Counter] = defaultdict(Counter)
    gov_unknown: Counter = Counter()
    for day, area, gov, doer, sa, n in rows:
        mo, n = M.month_of(day), int(n or 0)
        if mo is None or not n:
            continue
        c = by[mo]
        c["injured"] += n
        c[f"injured_{AREA.get(area, 'area_not_listed')}"] += n
        c[f"injured_by_{M.DOER.get(doer, 'other_or_disputed')}"] += n
        c[f"injured_{age_of(sa)}"] += n
        if gov in M.GOV:
            c[f"injured_gov:{M.GOV[gov]}"] += n
        else:
            gov_unknown[gov] += n
    for mo, c in by.items():                               # every split adds up to the month's total
        for prefix, keys in (("area", [f"injured_{v}" for v in list(AREA.values()) + ["area_not_listed"]]),
                             ("perpetrator", [f"injured_by_{v}" for v in list(M.DOER.values()) + ["other_or_disputed"]]),
                             ("age", ["injured_children", "injured_adults", "injured_age_unknown"])):
            if sum(c[k] for k in keys) != c["injured"]:
                raise fl.FetchRefused(f"{LABEL}: {mo}: the {prefix} split does not add up to {c['injured']}")
    this_month = f"{today.year}-{today.month:02d}-01"
    months = M._months(min(by), this_month) if by else []
    measures = (["injured"] + [f"injured_{v}" for v in AREA.values()]
                + [f"injured_by_{v}" for v in list(M.DOER.values()) + ["other_or_disputed"]]
                + ["injured_children"])
    recs = []
    for mo in months:
        c = by.get(mo, Counter())
        partial = True if mo == this_month else None
        for m in measures:
            recs.append({"stable_id": f"ocha_injuries:{m}:{mo}", "measure": m, "value": c[m], "unit": "persons",
                         "date": mo, "partial_month": partial, "location": {"region": "Palestine"},
                         "sources": [SOURCE]})
        for gname in M.GOV.values():
            key = gname.lower().replace(" ", "_").replace("-", "_")
            recs.append({"stable_id": f"ocha_injuries:injured_{key}:{mo}", "measure": f"injured_gov_{key}",
                         "value": c[f"injured_gov:{gname}"], "unit": "persons", "date": mo, "partial_month": partial,
                         "location": {"governorate": gname, "region": "Palestine"}, "sources": [SOURCE]})
    notes = {"injured_total": sum(c["injured"] for c in by.values()), "months": len(months),
             "first_month": months[0] if months else None,
             "governorate_not_listed": dict(gov_unknown)}
    return recs, notes


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    today = datetime.now(timezone.utc).date()
    try:
        rep = pb.Report(INJURIES_EMBED)
        res = rep.query("injuries_monthly", ENTITY, [
            pb.col("Date:", "day"), pb.col("Region_Id", "area"), pb.col("Govornorate", "governorate"),
            pb.col("Doer Aff.", "perpetrator"), pb.col("SA", "age_sex"), pb.agg("Inj", 0, "injured")])
        if len(res["rows"]) >= 30000:
            raise fl.FetchRefused(f"{LABEL}: {len(res['rows'])} grouped rows reached the query's window; split it")
        recs, notes = monthly(res["rows"], today)
        if notes["injured_total"] < FLOOR_TOTAL:
            raise fl.FetchRefused(f"{LABEL}: {notes['injured_total']} injured in all, below the floor of {FLOOR_TOTAL}")
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
    print(f"  ok   {LABEL}: {notes['injured_total']:,} injured, {notes['months']} months from {notes['first_month']}, "
          f"{len(recs):,} records; model refreshed {rep.last_refresh}")
    if dry:
        fl.stage(staged, OUT.name, {"metadata": meta, "data": recs})
        return 0
    from ingest import bronze
    for name, raw in rep.raw:
        bronze.put("ocha_casualties_injuries", raw, "json", url=f"{INJURIES_EMBED}#{name}")
    fl.write_atomic(OUT, {"metadata": meta, "data": recs})
    fl.event(LABEL, "ok", rows=len(recs), injured=notes["injured_total"], vintage=meta["vintage"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
