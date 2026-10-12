"""The IMF's annual series for the West Bank and Gaza, read from the IMF
DataMapper API: the smaller half of the `economic` category, taken off v1.

    .venv/bin/python -m ops.fetch_imf                      # tonight's run
    .venv/bin/python -m ops.fetch_imf --all                # read the 18 series whatever the list says
    .venv/bin/python -m ops.fetch_imf --dry-run            # print, write nothing
    .venv/bin/python -m ops.fetch_imf --dry-run --stage D  # ... and stage the file under D

WHY (2026-10-12)
`economic` read v1's unified tree (v1's `scripts/sources/imf.js` → its
`EconomicTransformer`). The day v1 is switched off, 474 IMF rows stop. This
reads the same API v1 read (imf.org/external/datamapper/api/v1, country WBG,
no key) and writes the record shape `t_economic` already transforms.

THE LIST IS THE HELD LIST. v1 probed every DataMapper indicator (132 on
2026-10-12) and kept the 18 that answer for WBG. CODES below is those 18. A
code the IMF starts answering for WBG is not fetched until it has a registry
rule in db/mappings/economic.yaml and Zaid's word; `metadata.not_fetched`
only counts how many other indicators the IMF lists.

THE UNIT, WHICH v1 THREW AWAY. The IMF states a unit for every indicator
("Billions of U.S. dollars", "Percent of GDP", "Annual percent change").
v1's transformer derived a unit from the label instead and stamped the
literal `number` on all 474 rows, so the loader nulled it. Here
`metrics.unit` is the IMF's own string, verbatim, and `t_economic` carries it.

NAMES. `records[].indicator_name` is the IMF's label exactly as the API
gives it (v1 did the same, so held rows match, trailing newline and all);
`metadata.indicators[code]` holds the same label with its whitespace
collapsed, the unit, the description, and the release it belongs to. The IMF
publishes no Arabic label: `indicator_name_ar` is absent, never translated.

VINTAGE. Each indicator names its release in `source` ("World Economic
Outlook (April 2026)") and carries `last-modified`. The 18 held codes sit in
three datasets: WEO (15), the Global Debt Database (1) and a 2016 gender
dataset (2). metadata.vintage is the WEO's, because the WEO is what moves
twice a year; each indicator's own is in metadata.indicators.

ONE SMALL REQUEST A NIGHT, EIGHTEEN LARGE ONES WHEN THE IMF HAS MOVED. The
API ignores the economy in the path: `/NGDPDPC/WBG` answers with all 229
economies (176 kB; measured 2026-10-12, and `?periods=` changes nothing), and
v1 downloaded that for all 132 indicators every night. The IMF's terms say it
"prohibits bulk download of information by automated technology without
explicit permission". So the indicator list is read every night (one request,
it carries each code's `last-modified`), and the 18 series are asked for only
when the list's label, unit or `last-modified` for a held code differs from
the file on disk, when that file's read was incomplete, or when it is more
than FULL_EVERY_DAYS old. Only WBG's values are kept; nothing else an answer
holds is written anywhere.

A YEAR AFTER THIS ONE IS A PROJECTION, NOT AN OBSERVATION. The WEO publishes
five years ahead for most economies and, on 2026-10-12, none for WBG (the last
year answered is 2025). If it starts to, those years are counted in
`metadata.projection_years_not_kept` and not written as records: a forecast
loaded as an observation is a claim nobody made.

POSTURE (ops/fetchlib.py): atomic, floored, ledgered, under the label
`imf:datamapper` (an unchanged night says `unchanged: true`). A code that
fails or stops answering is named in metadata and the ledger and makes the
run exit 1; the rest are still written (the spec declares no
`generation: complete`, so nothing in the store closes) and the next night
reads all 18 again.

LICENCE: the IMF's Copyright and Usage terms,
https://www.imf.org/en/about/copyright-and-terms (read 2026-10-12): data may
be used and redistributed with attribution; "For any potential commercial
reuse of IMF Data, email copyright@imf.org to request permission." Recorded
on the source row `imf` (commercial use false); this fetcher changes no
licence grade.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402
from ops.fetch_worldbank import get_json, unified_record        # noqa: E402

API = "https://www.imf.org/external/datamapper/api/v1"
COUNTRY = "WBG"                       # the IMF's code for West Bank and Gaza
OUT = fl.ROOT / "data" / "raw" / "imf" / "indicators.json"
LABEL = "imf:datamapper"
TERMS_URL = "https://www.imf.org/en/about/copyright-and-terms"
PROFILE_URL = "https://www.imf.org/external/datamapper/profile/WBG"

# 474 records over 18 codes measured 2026-10-12; the floor is 0.9 of it.
FLOOR_RECORDS = 426
MAX_MISSING = 2
PAUSE = 0.5
# However quiet the IMF's list, the 18 series are read again this often.
FULL_EVERY_DAYS = 30

# The 18 codes held under v1_economic_imf (extracted from v1's unified file
# on 2026-10-12; tests/test_supply_econ.py holds the list to the frozen corpus).
CODES = (
    "BCA", "BCA_NGDPD", "CG_DEBT_GDP", "GDI_TC", "GGXCNL_NGDP", "GGXWDG_NGDP",
    "GRB_dummy", "LP", "LUR", "NGDPD", "NGDPDPC", "NGDP_RPCH", "PCPIEPCH",
    "PCPIPCH", "PPPEX", "PPPGDP", "PPPPC", "PPPSH",
)


def series_of(answer, code: str) -> dict[int, float]:
    """One /<code>/WBG answer → {year: value}; a null value is not a point."""
    values = ((answer or {}).get("values") or {}).get(code) or {}
    series = values.get(COUNTRY) or {}
    out = {}
    for year, value in series.items():
        if value is None or not str(year).isdigit():
            continue
        out[int(year)] = value
    return out


def clean(text) -> str | None:
    """The label for the registry: the IMF's words, whitespace collapsed
    ('GDP per capita, current prices\\n' is the API's, not a second name)."""
    if not isinstance(text, str):
        return None
    return re.sub(r"\s+", " ", text).strip() or None


def records_for(code: str, meta: dict, series: dict[int, float],
                this_year: int) -> tuple[list[dict], list[int]]:
    """→ (records, the years after this one that were NOT kept)."""
    # No `license` on the record: v1 wrote "CC-BY-4.0" here, which the IMF's
    # terms do not say. The licence is the source row's (`imf`), and the terms
    # page is in this file's metadata.
    source = {"name": "IMF", "organization": "International Monetary Fund",
              "url": f"{API}/{code}/{COUNTRY}"}
    # v1's fallbacks, kept so a held row reads back identical: the label as
    # the API writes it (or the code), and 'Palestine' as the place name.
    label = meta.get("label") or code
    unit = clean(meta.get("unit"))      # the IMF's words; no held row has one to match
    later = sorted(y for y in series if y > this_year)
    recs = [unified_record(stable_id=f"imf:{COUNTRY}:{code}:{year}", year=year,
                           value=series[year], unit=unit, code=code, label=label,
                           place_name="Palestine", source=source)
            for year in sorted(series) if year <= this_year]
    return recs, later


def previous() -> dict | None:
    """The document already on disk, or None."""
    try:
        doc = json.loads(OUT.read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("data"), list) else None


def stamps(listing: dict) -> dict[str, list]:
    """What the IMF's indicator list says about each held code tonight: its
    label, its unit and the day the IMF last wrote it."""
    return {c: [(listing.get(c) or {}).get("label"), (listing.get(c) or {}).get("unit"),
                (listing.get(c) or {}).get("last-modified")] for c in CODES}


def unchanged(prev: dict | None, listing: dict, now: datetime) -> bool:
    """True when the file on disk is a complete read of exactly what the IMF's
    list describes tonight (same label, unit and last-modified on all 18
    codes), taken less than FULL_EVERY_DAYS ago. Then no series is asked for:
    the list is one small request, the series are 18 large ones (see the
    module docstring: the API answers with every economy)."""
    meta = (prev or {}).get("metadata") or {}
    if not prev or meta.get("stamps") != stamps(listing):
        return False
    if meta.get("codes_failed") or meta.get("codes_silent"):
        return False
    try:
        read = datetime.fromisoformat(meta["fetched_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return (now - read).total_seconds() < FULL_EVERY_DAYS * 86400


def build(listing: dict, now: datetime | None = None) -> tuple[dict, dict]:
    now = now or datetime.now(timezone.utc)
    recs: list[dict] = []
    indicators: dict[str, dict] = {}
    failed: dict[str, str] = {}
    silent: list[str] = []
    projections: dict[str, list[int]] = {}
    for code in CODES:
        meta = listing.get(code) or {}
        if not meta:
            failed[code] = "no longer in the IMF's indicator list"
            continue
        time.sleep(PAUSE)
        try:
            series = series_of(get_json(f"{API}/{code}/{COUNTRY}"), code)
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError,
                AttributeError) as e:
            failed[code] = f"{type(e).__name__}: {str(e)[:160]}"
            continue
        mine, later = records_for(code, meta, series, now.year)
        if later:
            projections[code] = later
        if not mine:
            silent.append(code)
            continue
        recs += mine
        years = [int(r["date"][:4]) for r in mine]
        indicators[code] = {
            "indicator_name": clean(meta.get("label")),
            "unit": clean(meta.get("unit")),
            "description": clean(meta.get("description")),
            "dataset": meta.get("dataset"),
            "release": clean(meta.get("source")),
            "last_modified": meta.get("last-modified"),
            "points": len(mine), "first_year": min(years), "last_year": max(years),
        }
    weo = [v for v in indicators.values() if v.get("dataset") == "WEO"]
    releases = sorted({v["release"] for v in weo if v.get("release")})
    modified = sorted(v["last_modified"] for v in weo if v.get("last_modified"))
    summary = {"records": len(recs), "codes_held": len(CODES),
               "codes_answered": len(indicators), "codes_failed": failed,
               "codes_silent": silent,
               "vintage": modified[-1][:10] if modified else None,
               "release": "; ".join(releases) or None}
    doc = {"metadata": {
        "fetched_at": now.isoformat(),
        "source": "IMF DataMapper",
        "organization": "International Monetary Fund",
        "source_url": PROFILE_URL,
        "api": f"{API}/<code>/{COUNTRY}",
        "country_code": COUNTRY,
        "license": "IMF Copyright and Usage, special terms for statistical data (see license_url)",
        "license_url": TERMS_URL,
        "attribution": "Source: International Monetary Fund, "
                       + (summary["release"] or "IMF DataMapper") + f", {PROFILE_URL}",
        "vintage": summary["vintage"],
        "vintage_release": summary["release"],
        "vintage_basis": ("`source` and `last-modified` on the World Economic Outlook "
                          "indicators in the IMF DataMapper indicator list: the release the "
                          "series belong to and the day the IMF last wrote them. Codes from "
                          "other IMF datasets carry their own in metadata.indicators[code]"),
        "vintage_url": f"{API}/indicators",
        "releases_seen": sorted({v["release"] for v in indicators.values() if v.get("release")}),
        "records": summary["records"],
        "codes_held": len(CODES), "codes_answered": len(indicators),
        "codes_failed": failed, "codes_silent": silent,
        "projection_years_not_kept": projections,
        "not_fetched": {"indicators_the_imf_lists": len(listing),
                        "outside_the_held_list": len(set(listing) - set(CODES))},
        "stamps": stamps(listing),
        "indicators": indicators},
        "data": recs}
    return doc, summary


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    now = datetime.now(timezone.utc)
    try:
        listing = (get_json(f"{API}/indicators") or {}).get("indicators") or {}
        if not listing:
            raise ValueError("the indicator list is empty")
    except (urllib.error.URLError, OSError, ValueError, AttributeError) as e:
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {str(e)[:200]}")
        print(f"{LABEL}: the indicator list did not load: {e}", file=sys.stderr)
        return 1
    prev = previous()
    if "--all" not in argv and unchanged(prev, listing, now):
        meta = prev["metadata"]
        print(f"{LABEL}: unchanged. The IMF's list still describes the {meta.get('vintage_release')} "
              f"series read on {meta['fetched_at'][:10]}; {len(prev['data'])} records stand, "
              "no series re-read")
        if not dry:
            fl.event(LABEL, "ok", rows=len(prev["data"]), vintage=meta.get("vintage"),
                     release=meta.get("vintage_release"), unchanged=True)
        return 0

    doc, s = build(listing, now)
    missing = {**s["codes_failed"], **{c: "answered with no value in any year"
                                       for c in s["codes_silent"]}}
    print(f"{LABEL}: {s['records']} records over {s['codes_answered']} of "
          f"{s['codes_held']} codes, {s['release']} (last modified {s['vintage']})")
    for code, why in sorted(missing.items()):
        print(f"  MISSING {code}: {why}", file=sys.stderr)
    for code, years in sorted(doc["metadata"]["projection_years_not_kept"].items()):
        print(f"  {code}: {len(years)} year(s) after {now.year} not kept (projections)")
    refusal = None
    if len(missing) > MAX_MISSING:
        refusal = f"{len(missing)} codes missing (more than {MAX_MISSING})"
    elif s["records"] < FLOOR_RECORDS:
        refusal = f"{s['records']} records below the floor of {FLOOR_RECORDS}"
    if refusal:
        if not dry:
            fl.event(LABEL, "refused", rows=s["records"], floor=FLOOR_RECORDS,
                     missing=sorted(missing), why=refusal)
        print(f"  REFUSED {LABEL}: {refusal}; the file already on disk stands", file=sys.stderr)
        return 1
    if dry:
        print(f"  would write {OUT.relative_to(fl.ROOT)}")
        fl.stage(staged, "imf_indicators.json", doc)
        return 1 if missing else 0
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=s["records"], codes=s["codes_answered"],
             vintage=s["vintage"], release=s["release"], missing=sorted(missing))
    print(f"  wrote {OUT.relative_to(fl.ROOT)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
