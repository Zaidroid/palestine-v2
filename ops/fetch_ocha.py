"""Fetch OCHA oPt's casualty and demolition registers — two v1 supply lines
that had been dead for a month when v2 took them over (P1-B.3, 2026-09-25).

WHAT DIED, AND WHY NOTHING SAID SO. v1's nightly refresh ran
`scripts/sources/ocha-casualties.js` and `ocha-demolitions.js`, which drove a
headless Chromium through the Power BI embeds on ochaopt.org. When v1's image
lost the `playwright` package both steps began failing in 0 s (rc 1) — 31
nights by 2026-09-25 — and nothing paged, because v1's refresh always exits 0
and v2 had frozen both corpora from v1's last good file (data/frozen/). The
databank kept serving the June numbers as if they were current.

WHAT THIS READS INSTEAD. The same reports, through the public API the embed
itself calls (ops/pbi_public.py) — no browser. Measured 2026-09-25 against the
frozen corpora: every one of the 516 demolition localities and all 49
casualty rows are present with the same labels; the numbers moved (2026 year
to date: 56 → 90 fatalities, 678 → 1,311 structures) because OCHA kept
recording while we were not reading.

WHAT IT WRITES. data/raw/ocha/{casualties,demolitions}.json in the record
shape db/mappings/{casualties,demolitions}.yaml already transform (the v1
unified field names t_casualties / t_demolitions read), so the specs change
their `input:` and nothing else about a row changes. Every raw answer the
service gave is archived in bronze first (ingest/bronze.py). Per the
fetchlib posture: ATOMIC (temp + rename), FLOORED (a short answer keeps
yesterday's file), LEDGERED (one line per feed per attempt in
ops/fetch-events.ndjson — the gap radar's supply-line judgment reads it).

ONE CHECK THE FLOORS CANNOT MAKE. The casualty report publishes ONE total
sliced five ways (year, region, governorate, demographic, weapon); every slice
must sum to the same number. If they do not, the query no longer reads what
the report shows and the fetch is refused — a wrong slice is worse than a
stale one, because it looks like news.

coverage_end IS PER ROW. The cross-sections (casualties by region, demolitions
by locality) are 2008/2009-to-date totals. Each row carries the date of the
latest record inside it, not the fetch day: a row changes only when OCHA adds
a record to it, so a quiet night rewrites nothing (the frozen rows carried the
fetch day, 2026-08-05, which would have superseded ~900 rows every night).

LICENCE: OCHA's terms of use (UN-ToU-NC, commercial_use false, read
2026-08-05) — recorded on the source rows ocha_casualties / ocha_demolitions.

Run: .venv/bin/python -m ops.fetch_ocha                 # both feeds
     .venv/bin/python -m ops.fetch_ocha --dry-run       # print, write nothing
     .venv/bin/python -m ops.fetch_ocha casualties      # one feed
"""
from __future__ import annotations

import re
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402
from ops import pbi_public as pb                                # noqa: E402

RAW = fl.ROOT / "data" / "raw" / "ocha"

CASUALTIES_EMBED = (
    "https://app.powerbi.com/view?r=eyJrIjoiNjBlY2ExZWYtNTg1Mi00ODA3LTliYzMtNG"
    "ZkYjg5MTVjNzFjIiwidCI6IjBmOWUzNWRiLTU0NGYtNGY2MC1iZGNjLTVlYTQxNmU2ZGM3MC"
    "IsImMiOjh9")
DEMOLITIONS_EMBED = (
    "https://app.powerbi.com/view?r=eyJrIjoiYWFlNzc4MDUtMDg0Mi00M2EyLTlkMmUtYW"
    "EyMWQ0MzU1N2U2IiwidCI6IjBmOWUzNWRiLTU0NGYtNGY2MC1iZGNjLTVlYTQxNmU2ZGM3MC"
    "IsImMiOjh9")

# Source names EXACTLY as the specs route them (db/mappings/*.yaml by_name).
CAS_SOURCE = {"name": "UN OCHA oPt — Data on Casualties",
              "organization": "UN OCHA (B'Tselem data)",
              "url": "https://www.ochaopt.org/data/casualties",
              "license": "verify-required"}
DEM_SOURCE = {"name": "UN OCHA oPt — Data on Demolitions",
              "organization": "UN OCHA oPt",
              "url": "https://www.ochaopt.org/data/demolition",
              "license": "verify-required"}

# Floors: ~0.9 of what was measured 2026-09-25 (casualties 19 years + 30
# breakdown rows = 49; demolitions 526 localities + 18 years). Below them the
# service is having a bad night and yesterday's file is the better answer.
CAS_FLOOR_YEARS, CAS_FLOOR_ROWS = 18, 44
DEM_FLOOR_LOCALITIES, DEM_FLOOR_YEARS = 470, 17

# The five slices of the ONE casualty total. Column names are the model's own
# (typos included: 'Govornorate'); each is a plain column of the view, so the
# query does not depend on how the report happens to group its charts.
CAS_ENTITY = "vw_BS_Pal_Fatalities"
CAS_SLICES = {
    "annual_total": "Year",
    "region": "Area",
    "governorate": "Govornorate (groups)",
    "demographic": "SA (groups)",
    "weapon": "Weapon_name (groups)",
}
DEM_ENTITY = "_vw_Incidents"


def _day(ms) -> str | None:
    """Power BI serialises a date as epoch milliseconds."""
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).date().isoformat()


def _coord(v) -> float | None:
    """OCHA writes 'Na' where a locality has no point (Al Malha, measured)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


# ── casualties ───────────────────────────────────────────────────────────────

def casualty_records(slices: dict[str, list[list]], fetched_at: str) -> tuple[list[dict], dict]:
    """Query rows → records in the shape t_casualties reads.

    `slices[dim]` is a list of [label, fatalities, last_date_ms]. Returns the
    records and a summary (per-slice totals, the data's last day)."""
    totals = {dim: sum(int(r[1] or 0) for r in rows) for dim, rows in slices.items()}
    last_all = max((r[2] for rows in slices.values() for r in rows
                    if r[2] is not None), default=None)
    through = _day(last_all)
    recs: list[dict] = []
    src = dict(CAS_SOURCE, fetched_at=fetched_at)
    for year, fat, last in sorted(slices.get("annual_total", []),
                                  key=lambda r: int(r[0])):
        y = int(year)
        rec = {"stable_id": f"ocha-cas:annual_total:{y}",
               "casualty_dimension": "annual_total",
               "casualty_breakdown_label": None,
               "date": f"{y}-12-31",
               "location": {"name": "Palestine", "region": "Palestine",
                            "governorate": None},
               "metrics": {"killed": int(fat or 0), "unit": "fatalities"},
               "sources": [src],
               "partial_year": bool(through and int(through[:4]) == y)}
        recs.append(rec)
    for dim in ("region", "governorate", "demographic", "weapon"):
        for label, fat, last in slices.get(dim, []):
            label = str(label).strip() if label is not None else "Not listed"
            loc = {"name": "Palestine", "region": "Palestine", "governorate": None}
            if dim == "region":
                # v1's convention, kept so a row reads back identical: the
                # region slice carries its own label as the region, except
                # 'Not listed', which is Palestine-wide.
                loc["region"] = label if label != "Not listed" else "Palestine"
                loc["name"] = loc["region"]
            elif dim == "governorate":
                loc["governorate"] = label
            recs.append({
                "stable_id": f"ocha-cas:{dim}:{_slug(label)}",
                "casualty_dimension": dim,
                "casualty_breakdown_label": label,
                "date": None,
                "coverage_end": _day(last),
                "location": loc,
                "metrics": {"killed": int(fat or 0), "unit": "fatalities"},
                "sources": [src]})
    return recs, {"slice_totals": totals, "data_through": through}


def check_casualty_slices(totals: dict[str, int], tolerance: float = 0.005) -> None:
    """Every slice of the one total must sum to the annual series' total."""
    base = totals.get("annual_total") or 0
    if not base:
        raise fl.FetchRefused("casualties: the annual series is empty")
    off = {d: t for d, t in totals.items()
           if abs(t - base) > tolerance * base}
    if off:
        raise fl.FetchRefused(
            f"casualties: the slices disagree with the annual total {base}: "
            f"{off} — the query no longer reads what the report shows")


def fetch_casualties(report=None) -> tuple[list[dict], dict, list]:
    rep = report or pb.Report(CASUALTIES_EMBED)
    slices = {}
    for dim, column in CAS_SLICES.items():
        res = rep.query(f"casualties_{dim}", CAS_ENTITY,
                        [pb.col(column, "label"), pb.agg("Fat", 0, "fatalities"),
                         pb.agg("Date", 4, "last")])
        slices[dim] = [r for r in res["rows"] if r[0] is not None or dim != "annual_total"]
    fetched_at = datetime.now(timezone.utc).isoformat()
    recs, summary = casualty_records(slices, fetched_at)
    summary["model_last_refresh"] = rep.last_refresh
    return recs, summary, rep.raw


# ── demolitions ──────────────────────────────────────────────────────────────

def demolition_records(localities: list[list], annual: list[list],
                       fetched_at: str) -> tuple[list[dict], dict]:
    """localities: [lat, lon, name, governorate, structures, displaced, last_ms]
    annual:     [year, structures, displaced, affected, last_ms]"""
    src = dict(DEM_SOURCE, fetched_at=fetched_at)
    last_all = max([r[6] for r in localities if r[6] is not None]
                   + [r[4] for r in annual if r[4] is not None], default=None)
    through = _day(last_all)
    recs: list[dict] = []
    for lat, lon, name, gov, dem, disp, last in localities:
        if name is None:
            continue
        name, gov = str(name).strip(), (str(gov).strip() if gov else None)
        # v1's convention, measured on the frozen corpus (85 of 85): a
        # Jerusalem-governorate locality is East Jerusalem, every other one
        # is West Bank. The loader turns 'East Jerusalem' into the Jerusalem
        # governorate row with the label kept in attrs.
        region = "East Jerusalem" if gov == "Jerusalem" else "West Bank"
        recs.append({
            "stable_id": f"ocha-dem:locality:{_slug(name)}:{_slug(gov or '')}",
            "demolition_dimension": "locality",
            "date": None,
            "coverage_end": _day(last),
            "location": {"name": name, "governorate": gov, "region": region,
                         "lat": _coord(lat), "lon": _coord(lon),
                         "admin2_pcode": None, "gazetteer_key": None},
            "metrics": {"demolished": int(dem) if dem is not None else None,
                        "displaced": int(disp or 0), "affected": 0,
                        "unit": "structures"},
            "sources": [src]})
    for year, dem, disp, aff, _last in sorted(annual, key=lambda r: int(r[0])):
        y = int(year)
        recs.append({
            "stable_id": f"ocha-dem:annual_total:{y}",
            "demolition_dimension": "annual_total",
            "date": f"{y}-12-31",
            "location": {"name": "West Bank & East Jerusalem",
                         "region": "West Bank", "governorate": None},
            "metrics": {"demolished": int(dem) if dem is not None else None,
                        "displaced": int(disp or 0), "affected": int(aff or 0),
                        "unit": "structures"},
            "sources": [src],
            "partial_year": bool(through and int(through[:4]) == y)})
    loc_rows = [r for r in recs if r["demolition_dimension"] == "locality"]
    return recs, {
        "data_through": through,
        "localities": len(loc_rows),
        "years": len(recs) - len(loc_rows),
        "locality_structures": sum(r["metrics"]["demolished"] or 0 for r in loc_rows),
        "annual_structures": sum(r["metrics"]["demolished"] or 0 for r in recs
                                 if r["demolition_dimension"] == "annual_total"),
    }


def fetch_demolitions(report=None) -> tuple[list[dict], dict, list]:
    rep = report or pb.Report(DEMOLITIONS_EMBED)
    # The report's map: every locality, all incident types (its own visual
    # carries no filter). v1 read exactly this visual.
    loc = rep.query("demolitions_locality", DEM_ENTITY, [
        pb.col("y"), pb.col("x"), pb.col("Residentialarea"), pb.col("Governorate"),
        pb.agg(" Demolished structures", 0, "structures"),
        pb.agg("Displaced people", 0, "displaced"),
        pb.agg("Date of incident", 4, "last")])
    # The report's year chart: demolitions only — the chart excludes
    # 'Eviction' incidents, and so does the series we serve.
    ann = rep.query("demolitions_annual", DEM_ENTITY, [
        pb.col("Year"), pb.agg(" Demolished structures", 0, "structures"),
        pb.agg("Displaced people", 0, "displaced"),
        pb.agg("Affected people", 0, "affected"),
        pb.agg("Date of incident", 4, "last")],
        [pb.not_in("IncidentType", ["'Eviction'"])])
    fetched_at = datetime.now(timezone.utc).isoformat()
    recs, summary = demolition_records(
        loc["rows"], [r for r in ann["rows"] if r[0] is not None], fetched_at)
    summary["model_last_refresh"] = rep.last_refresh
    return recs, summary, rep.raw


# ── the run ──────────────────────────────────────────────────────────────────

def _archive(bronze_key: str, raw: list, url: str) -> list[str]:
    from ingest import bronze
    return [bronze.put(bronze_key, body, "json", url=f"{url}#{name}").ref
            for name, body in raw]


def floor(label: str, n: int, minimum: int, what: str, dry: bool) -> None:
    """fetchlib's FLOORED rule, except a dry run leaves no ledger line — a
    rehearsal must not count as an attempt in the radar's streak."""
    if n < minimum:
        if not dry:
            fl.event(label, "refused", rows=n, floor=minimum, what=what)
        raise fl.FetchRefused(f"{label}: {n} {what} below the floor of {minimum} "
                              "— keeping the file already on disk")


def run_feed(name: str, dry: bool, staged: Path | None = None) -> bool:
    label = f"ocha:{name}"
    out = RAW / f"{name}.json"
    try:
        if name == "casualties":
            recs, summary, raw = fetch_casualties()
            try:
                check_casualty_slices(summary["slice_totals"])
            except fl.FetchRefused:
                if not dry:
                    fl.event(label, "refused", why="slices disagree",
                             totals=summary["slice_totals"])
                raise
            years = sum(1 for r in recs if r["casualty_dimension"] == "annual_total")
            floor(label, years, CAS_FLOOR_YEARS, "years", dry)
            floor(label, len(recs), CAS_FLOOR_ROWS, "records", dry)
            source, url = CAS_SOURCE, CAS_SOURCE["url"]
        elif name == "demolitions":
            recs, summary, raw = fetch_demolitions()
            floor(label, summary["localities"], DEM_FLOOR_LOCALITIES, "localities", dry)
            floor(label, summary["years"], DEM_FLOOR_YEARS, "years", dry)
            source, url = DEM_SOURCE, DEM_SOURCE["url"]
        else:
            raise SystemExit(f"unknown feed {name!r} (casualties | demolitions)")
    except fl.FetchRefused as e:
        print(f"  REFUSED {label}: {e}")
        return False
    except (urllib.error.URLError, OSError, ValueError, KeyError,
            pb.PbiError) as e:
        print(f"  FAIL {label}: {type(e).__name__}: {str(e)[:200]}")
        if not dry:
            fl.event(label, "error", error=type(e).__name__)
        return False

    doc = {"metadata": {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source["name"], "organization": source["organization"],
        "source_url": url,
        "via": "Power BI publish-to-web public API (ops/pbi_public.py)",
        "license": "UN OCHA terms of use (UN-ToU-NC), verify-required",
        "attribution": (f"{source['name']} — UN OCHA oPt"
                        + (", sourced from B'Tselem." if name == "casualties" else ".")),
        **summary}, "data": recs}
    print(f"  ok   {label:<18} {len(recs):>4} records, data through "
          f"{summary.get('data_through')} (model refreshed {summary.get('model_last_refresh')})")
    for k, v in summary.items():
        if k not in ("data_through", "model_last_refresh"):
            print(f"         {k}: {v}")
    if dry:
        print(f"         would write {out.relative_to(fl.ROOT)} and "
              f"{len(raw)} bronze payloads under ocha_{name}")
        fl.stage(staged, f"{name}.json", doc)
        return True
    refs = _archive(f"ocha_{name}", raw, url)
    doc["metadata"]["bronze"] = refs
    fl.write_atomic(out, doc)
    fl.event(label, "ok", rows=len(recs), data_through=summary.get("data_through"))
    return True


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    feeds = [a for a in argv if not a.startswith("--") and
             (staged is None or a != str(staged))] or ["casualties", "demolitions"]
    ok = [run_feed(f, dry, staged) for f in feeds]
    print(f"\n  {sum(ok)}/{len(ok)} OCHA feeds fetched"
          + ("  (dry run, nothing written)" if dry else ""))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
