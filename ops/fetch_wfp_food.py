"""WFP's food prices for the State of Palestine, read from WFP's own file on HDX.

    .venv/bin/python -m ops.fetch_wfp_food                  # fetch and write
    .venv/bin/python -m ops.fetch_wfp_food --dry-run        # print, write nothing
    .venv/bin/python -m ops.fetch_wfp_food --dry-run --stage DIR

WHY (2026-10-12). `food` was one of the nine categories still reading v1's
unified tree: v1 downloaded this same CSV every night, rewrote it as 79
quarterly files, and the loader read those. The day v1 is switched off the
series stops. This is the direct line: HDX dataset
`wfp-food-prices-for-state-of-palestine`, resource "State of Palestine - Food
Prices" (CSV, one row per month, market and commodity, 2007-01 onward).

WHAT IT WRITES. data/raw/wfp_food/food_prices.json, in the record shape
`t_food` already reads (v1's unified field names: date, location.name /
.governorate / .lat / .lon, metrics.price / .price_usd / .unit, commodity,
commodity_category, price_type, sources[0].name = "WFP Food Prices"). The
transformer and the loader are untouched. Numbers are written the way v1's
JavaScript wrote them (2, never 2.0), because the databank compares a row's
attrs as text. Measured 2026-10-12: all 27,235 rows of the file match a held
row exactly, identity and content.

THE STABLE ID is the publisher's own key, not a hash of the record:
`wfp:<date>:m<market_id>:c<commodity_id>:<pricetype>`. The food spec matches
on its declared identity (indicator, month, place), so held rows keep the id
v1 gave them and only a new month's rows take this one.

THE FILE FLAPS, SO NOTHING HERE TREATS A MISSING ROW AS A WITHDRAWAL. WFP
replaces the file about once a week. The vault's 64 nightly copies of the
loader's food input (2026-08-07 to 2026-10-12) show ten replacements, five of
them short by 210 to 1,354 rows scattered over 92 to 185 different months;
after each of the first four, the next file restored every missing row. The
fifth is the file of 2026-10-12 (231 short). The smallest file seen held
25,814 rows, the largest 27,466. The databank keeps a point once it has been
published (the spec declares no `generation`), so a short week costs nothing;
the floor below sits under the smallest file ever seen and only refuses a
download that is plainly broken.

POSTURE (ops/fetchlib.py): atomic, floored, ledgered under `wfp:food_prices`.
The CSV as downloaded is archived in bronze before it is parsed.

LICENCE, as HDX states it (read 2026-10-12): "Creative Commons Attribution for
Intergovernmental Organisations (CC BY-IGO)", license_id cc-by-igo,
http://creativecommons.org/licenses/by/3.0/igo/legalcode. Publisher: WFP -
World Food Programme; dataset_source "FPMA, Palestinian Central Bureau of
Statistics(PCBS) via FAO: GIEWS, VAM".
"""
from __future__ import annotations

import csv
import io
import re
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import fetchlib as fl                                   # noqa: E402
from ops import hdx                                              # noqa: E402

SLUG = "wfp-food-prices-for-state-of-palestine"
PAGE = hdx.PAGE + SLUG
OUT = ROOT / "data" / "raw" / "wfp_food" / "food_prices.json"
LABEL = "wfp:food_prices"
RESOURCE = re.compile(r"food prices", re.I)         # v1's own test of the name
FLOOR = 24500                 # under the smallest file in 64 archived nights
                              #   (25,814 on 2026-08-17; 27,235 on 2026-10-12)
SOURCE = {"name": "WFP Food Prices",                 # routed by this exact name
          "organization": "World Food Programme",
          "url": PAGE, "license": "CC-BY-IGO"}
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    """The loader's own slug rule (ingest/databank.slug), for the indicator
    names written beside the data."""
    return _SLUG.sub("_", str(s).lower()).strip("_")


def parse_prices(raw: bytes) -> list[dict]:
    """WFP's CSV → the rows v1 kept: a real date, a commodity, a price that
    parses. An HXL tag row ('#date', '#adm1+name', ...) has no real date and
    falls out here."""
    rows = []
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        if not _DAY.match(r.get("date") or "") or not r.get("commodity"):
            continue
        price = hdx.jsnum(r.get("price"))
        if price is None:
            continue
        rows.append({**r, "price": price})
    return rows


def record(r: dict) -> dict:
    """One CSV row → one record in the shape t_food reads (v1's
    FoodPricesTransformer, field for field)."""
    admin1 = r.get("admin1") or None
    region = admin1 if admin1 in ("Gaza Strip", "West Bank") else "Palestine"
    market = r.get("market") or None
    pricetype = r.get("pricetype") or None
    return {
        "stable_id": (f"wfp:{r['date']}:m{r.get('market_id') or _slug(market or '')}"
                      f":c{r.get('commodity_id') or _slug(r['commodity'])}"
                      f":{_slug(pricetype or 'price')}"),
        "date": r["date"],
        "category": "food",
        "event_type": "food_price",
        "location": {
            "name": market or r.get("admin2") or admin1 or "Palestine",
            "region": region,
            "governorate": r.get("admin2") or None,
            "lat": hdx.jsnum(r.get("latitude")),
            "lon": hdx.jsnum(r.get("longitude")),
            "precision": "market" if market else "region",
        },
        "metrics": {
            "price": r["price"],
            "price_usd": hdx.jsnum(r.get("usdprice")),
            "unit": f"{r.get('currency') or 'ILS'}/{r.get('unit') or 'unit'}",
        },
        "commodity": r["commodity"],
        "commodity_category": r.get("category") or None,
        "price_type": pricetype,
        # the publisher's own keys, kept so a row can be traced back to its line
        "market_id": r.get("market_id") or None,
        "commodity_id": r.get("commodity_id") or None,
        "price_flag": r.get("priceflag") or None,
        "sources": [dict(SOURCE)],
    }


def summarise(recs: list[dict]) -> dict:
    months = sorted({r["date"][:7] for r in recs})
    markets: dict[str, list[str]] = {}
    for r in recs:
        markets.setdefault(r["location"]["name"], []).append(r["date"][:7])
    names: dict[str, dict] = {}
    for r in recs:
        key = f"food.price.{_slug(r['commodity'])}"
        n = names.setdefault(key, {"indicator": key, "indicator_name": r["commodity"],
                                   "indicator_name_ar": None,      # WFP gives none
                                   "category": r["commodity_category"], "units": []})
        unit = r["metrics"]["unit"]
        if unit not in n["units"]:
            n["units"].append(unit)
    return {
        "rows": len(recs),
        "months": len(months),
        "first_month": months[0] if months else None,
        "last_month": months[-1] if months else None,
        "markets": {m: {"rows": len(v), "first_month": min(v), "last_month": max(v)}
                    for m, v in sorted(markets.items())},
        "indicators": [names[k] for k in sorted(names)],
    }


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    try:
        pkg = hdx.package(SLUG)
        res = hdx.resource(pkg, name=RESOURCE)
        if res is None:
            hdx.refuse(LABEL, "HDX lists no resource named like 'Food Prices'", dry)
        raw = fl.get(res["url"], timeout=180)
        recs = [record(r) for r in parse_prices(raw)]
        if len(recs) < FLOOR:
            hdx.refuse(LABEL, f"{len(recs)} rows below the floor of {FLOOR}", dry,
                       rows=len(recs), floor=FLOOR)
        summary = summarise(recs)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:300])
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1

    stamp = hdx.stamp(pkg, res, kind="series")
    doc = {"metadata": {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "WFP Food Prices (via HDX)",
        "organization": "World Food Programme",
        "source_url": PAGE,
        "attribution": "Food prices: World Food Programme (WFP) via HDX, CC BY-IGO.",
        **stamp, **summary}, "data": recs}
    print(f"  ok   {LABEL}: {len(recs)} rows, {summary['months']} months "
          f"{summary['first_month']} to {summary['last_month']}, "
          f"{len(summary['markets'])} markets, {len(summary['indicators'])} commodities; "
          f"publisher's file last replaced {stamp['vintage']}")
    if dry:
        print(f"         would write {OUT.relative_to(ROOT)}")
        fl.stage(staged, OUT.name, doc)
        return 0
    from ingest import bronze
    doc["metadata"]["bronze"] = bronze.put("wfp_food_prices", raw, "csv", url=res["url"]).ref
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=len(recs), data_through=summary["last_month"],
             vintage=stamp["vintage"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
