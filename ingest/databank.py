"""T2.3 — the databank migration loader.

Reads a reviewed mapping spec from db/mappings/<category>.yaml and executes
it: bronze the v1 files, transform every record through a per-category
transformer that implements the spec, resolve places, and write
`observation` rows idempotently (044's unique index on v1_stable_id).

The spec is the contract; the transformer is its implementation; the run
report is the proof. Refusals are structural:
  - no spec, spec not `status: reviewed`, or `migrate: false`  → refuse
  - a record whose source name is not in the spec's by_name    → run FAILS
  - fewer records than expect.min_records                      → run FAILS
  - resolution below the spec's floors                         → run FAILS
  - a drop reason not declared in the spec                     → run FAILS
Nothing is silently skipped: every record lands in exactly one bucket of the
run report (written, deduped, dropped-by-reason, failed).

Run:  .venv/bin/python -m ingest.databank <category> [--dry-run]
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ingest import bronze
from resolve.db import connect

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "db" / "mappings"
V1_UNIFIED = Path("/opt/stacks/palestine/public/data/unified")  # READ-ONLY
RUNS = ROOT / "ops" / "databank-runs.ndjson"


# ── spec loading ─────────────────────────────────────────────────────────────

class SpecRefused(RuntimeError):
    pass


def load_spec(category: str) -> dict:
    p = SPECS / f"{category}.yaml"
    if not p.exists():
        raise SpecRefused(f"no spec for {category!r}")
    spec = yaml.safe_load(p.read_text())
    if spec.get("status") != "reviewed":
        raise SpecRefused(f"{category}: status={spec.get('status')!r}, not reviewed")
    if spec.get("migrate") is False:
        raise SpecRefused(f"{category}: migrate=false ({spec.get('skip_reason')})")

    # A migrating spec MUST declare how a row is identified and how many rows
    # are too many. Both were optional until 2026-08-07, and the eleven specs
    # that declared neither are exactly the ones that doubled overnight when
    # v1 re-hashed its corpus. Optional guards protect the datasets that
    # happened to be remembered.
    if not (spec.get("identity") or any(
            (d.get("overrides") or {}).get("identity")
            for d in spec.get("datasets", []))):
        raise SpecRefused(
            f"{category}: no `identity:` — declare what makes a row THIS row "
            "(per dataset via datasets[].overrides.identity where one key "
            "cannot describe them all), or v1 re-hashing its ids silently "
            "re-inserts the whole corpus")
    if not (spec.get("expect") or {}).get("max_observations"):
        raise SpecRefused(
            f"{category}: no `expect.max_observations` — the tripwire that "
            "catches an identity too FINE (a revision read as a new fact). "
            "Set it at ~1.15x the measured emission.")
    return spec


def identity_key_for(ident: dict, dataset_key: str, *, indicator, occurred_at,
                     place_id, value_num, attrs) -> str:
    """The ONE renderer for a row's declared identity.

    Both the loader (on a Row it just built) and the backfill (on a row read
    back from the database) call this. That is the whole point: the first
    version of the guard compared a Python-rendered key against a SQL-rendered
    one, and 106.0 != 106 made it fail OPEN — re-inserting rows it already
    held, which is the doubling it existed to prevent (measured: 998 of 1,000
    connectivity rows). One function, one rendering, no second opinion.
    """
    parts = [dataset_key]
    for f in ident.get("fields", []):
        v = {"indicator": indicator,
             "occurred_at": str(occurred_at)[:10],
             "occurred_at_exact": str(occurred_at),
             "place_id": place_id,
             "value_num": value_num}[f]
        parts.append("" if v is None else str(v))
    for a in ident.get("attrs", []):
        v = (attrs or {}).get(a)
        parts.append("" if v is None else str(v))
    return "|".join(parts)


def iter_v1_files(category: str, spec: dict | None = None):
    # Format v2 `input:` — a spec may read a v1 RAW tree instead of the
    # unified category (first user: conflict_westbank, whose cumulative
    # fields v1's unified transform destroys). Still strictly read-only.
    if spec and spec.get("input"):
        root = Path(spec["input"]["root"])
        for f in sorted(root.glob(spec["input"]["glob"])):
            if f.name not in ("index.json", "recent.json"):
                yield f
        return
    d = V1_UNIFIED / category
    if (d / "all-data.json").exists():
        yield d / "all-data.json"
        return
    for f in sorted((d / "partitions").glob("*.json")):
        if f.name != "index.json":
            yield f


def _records(payload):
    if isinstance(payload, list):
        return payload
    for key in ("data", "records"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


# ── row model ────────────────────────────────────────────────────────────────

@dataclass
class Row:
    dataset_key: str
    indicator: str
    occurred_at: str            # ISO date/timestamp
    precision: str              # exact|hour|day|month|year|unknown
    v1_stable_id: str
    value_num: float | None = None
    value_text: str | None = None
    unit: str | None = None
    place_id: int | None = None
    located: bool = False       # point/locality/governorate-grade resolution
    reported_at: str | None = None
    raw_ref: str | None = None
    identity_key: str | None = None     # 052: the declared natural key
    attrs: dict = field(default_factory=dict)


@dataclass
class EventRow:
    dataset_key: str            # provenance only — event has no dataset FK
    event_type: str
    occurred_at: str
    precision: str
    v1_stable_id: str
    place_id: int | None = None
    lat: float | None = None
    lon: float | None = None
    located: bool = False
    confidence: float = 0.7
    independent_sources: int = 1
    metrics: dict = field(default_factory=dict)
    raw_ref: str | None = None
    attrs: dict = field(default_factory=dict)


@dataclass
class Drop:
    reason: str


class PointResolver:
    """lat/lon → governorate place_id by containment (T2.3 prerequisite —
    resolve/geo.py is text-only). Cached per run; rounding to ~11 m."""

    def __init__(self, conn):
        self.conn = conn
        self.cache: dict = {}

    def resolve(self, lat, lon) -> int | None:
        if lat is None or lon is None:
            return None
        key = (round(float(lat), 4), round(float(lon), 4))
        if key not in self.cache:
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT place_id FROM place
                       WHERE kind = 'governorate' AND merged_into IS NULL
                         AND ST_Contains(geom::geometry,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                       LIMIT 1""", (key[1], key[0]))
                row = cur.fetchone()
            self.cache[key] = row[0] if row else None
        return self.cache[key]


def slug(s: str) -> str:
    """Global loader convention: lowercase, runs of non-alnum → '_'."""
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


# ── place maps (loaded once per run, keyed on names not ids) ────────────────

def load_places(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT place_id, kind, name_en, admin2_pcode
                       FROM place WHERE merged_into IS NULL
                         AND kind IN ('region', 'governorate', 'crossing')""")
        rows = cur.fetchall()
    by_name = {(k, n): pid for pid, k, n, _ in rows}
    by_pcode = {pc: pid for pid, k, n, pc in rows if k == "governorate" and pc}
    return {
        "region": {n: pid for (k, n), pid in by_name.items() if k == "region"},
        "governorate": {n: pid for (k, n), pid in by_name.items()
                        if k == "governorate"},
        "crossing": {n: pid for (k, n), pid in by_name.items()
                     if k == "crossing"},
        "pcode": by_pcode,
    }


# ── mojibake repair (README loader convention) ──────────────────────────────
# v1 double-encoded Arabic: UTF-8 bytes read as cp1252. The round trip
# restores it exactly; anything that does not round-trip cleanly passes
# through unchanged and is NOT counted as repaired.

_ARABIC = re.compile(r"[؀-ۿ]")


def demojibake(s, counts: Counter):
    if not isinstance(s, str) or _ARABIC.search(s):
        return s
    try:
        fixed = s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    if _ARABIC.search(fixed):
        counts["mojibake_repaired"] += 1
        return fixed
    return s


def region_place(places: dict, region: str, attrs: dict) -> tuple[int | None, bool]:
    """README's region rules. Returns (place_id, located)."""
    if region == "Gaza Strip":
        return places["region"]["Gaza Strip"], False
    if region == "West Bank":
        return places["region"]["West Bank"], False
    if region == "East Jerusalem":
        attrs["region"] = "East Jerusalem"
        return places["governorate"]["Jerusalem"], True
    attrs["region"] = region        # 'Palestine' and friends → honest NULL
    return None, False


def route(rec: dict, spec: dict, counts: Counter) -> str | None:
    """sources[0].name → dataset key via the spec's by_name. None = unroutable."""
    sources = rec.get("sources") or []
    name = sources[0].get("name") if sources and isinstance(sources[0], dict) else None
    by_name = spec["source_routing"]["by_name"]
    if name not in by_name or by_name[name] is None:
        counts[f"unroutable:{name}"] += 1
        return None
    src_key = by_name[name]
    for ds in spec["datasets"]:
        if ds["source"] == src_key:
            return ds["key"]
    counts[f"no_dataset_for_source:{src_key}"] += 1
    return None


def passthrough(rec: dict, spec_list: list, base: dict | None = None) -> dict:
    """attrs_passthrough: dotted paths, absent/empty values omitted."""
    out = dict(base or {})
    for path in spec_list or []:
        cur = rec
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, "", [], {}):
            out[path.split(".")[-1]] = cur
    return out


# ── per-category transformers (each implements its reviewed spec) ────────────

def t_prisoners(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    metric = rec.get("prisoner_metric_type")
    day = str(rec.get("date"))[:10]
    # spec: 890/890 dates are the 1st of a month; month precision, month start.
    if not day or day[8:10] != "01":
        counts["date_not_month_start"] += 1
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    attrs["reference"] = "period-end stock"     # REVIEW.md decision 2
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    return [Row(dataset_key=ds, indicator=f"prisoners.{slug(metric)}",
                occurred_at=day, precision="month",
                v1_stable_id=rec["stable_id"],
                value_num=rec["metrics"]["count"], unit="persons",
                place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def t_casualties(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    dim = rec.get("casualty_dimension")
    label = rec.get("casualty_breakdown_label")
    indicator = f"casualties.{slug(dim)}" + (f".{slug(label)}" if label else "")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    date = rec.get("date")
    if dim == "annual_total" and date:
        year = str(date)[:4]
        occurred, precision = f"{year}-01-01", "year"            # law 2
        if year == "2026":
            attrs["partial_year"] = True                          # spec note
    else:
        occurred, precision = "2008-01-01", "unknown"             # series start
        attrs["coverage_start"] = "2008-01-01"
        attrs["coverage_end"] = "2026-08-05"
    loc = rec.get("location") or {}
    if dim == "governorate":
        gov = loc.get("governorate")
        # OCHA's spelling vs the gazetteer's: the one measured divergence.
        gov = {"Qalqiliya": "Qalqilya"}.get(gov, gov)
        pid = places["governorate"].get(gov)
        if pid is not None:
            place_id, located = pid, True
        elif gov in ("Israel", "Not listed"):
            attrs["breakdown_place"] = gov                        # honest NULL
            place_id, located = None, False
        else:
            counts[f"governorate_unresolved:{gov}"] += 1          # counted FAILURE
            place_id, located = None, False
    else:
        place_id, located = region_place(places, loc.get("region"), attrs)
    return [Row(dataset_key=ds, indicator=indicator,
                occurred_at=occurred, precision=precision,
                v1_stable_id=rec["stable_id"],
                value_num=rec["metrics"]["killed"], unit="fatalities",
                place_id=place_id, located=located, attrs=attrs)]


def t_demolitions(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    dim = rec.get("demolition_dimension")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    date = rec.get("date")
    if dim == "annual_total" and date:
        year = str(date)[:4]
        occurred, precision = f"{year}-01-01", "year"             # law 2
        attrs["coverage_area"] = "West Bank + East Jerusalem"     # spec note
        if year == "2026":
            attrs["partial_year"] = True
    else:
        occurred, precision = "2009-01-01", "unknown"             # series start
        attrs["coverage_start"] = "2009-01-01"
        attrs["coverage_end"] = "2026-08-05"
    loc = rec.get("location") or {}
    if (rec.get("demolition_dimension") or "") == "locality":
        # THE FIX-FIRST NOTE, discharged (2026-08-07). The locality name was
        # in the source all along (location.name, 511 distinct of 516) and
        # this transformer dropped it, leaving these rows with no identity
        # but a governorate — which is why 828 of them collided and why the
        # dataset was frozen holding a superseded generation. governorate
        # rides along because five names repeat across governorates.
        attrs["locality_name"] = loc.get("name")
        attrs["governorate"] = loc.get("governorate")
    pid = places["pcode"].get(loc.get("admin2_pcode"))
    if pid is not None:
        place_id, located = pid, True                             # rung 1-2
    else:
        place_id, located = region_place(places, loc.get("region"), attrs)
        if dim == "locality":
            counts["locality_resolution_miss"] += 1               # Al Malha
    m = rec.get("metrics") or {}
    sid = rec["stable_id"]
    rows = []
    # fan_out per the reviewed spec; suffixed stable ids per emitted row (044)
    if m.get("demolished") is not None:
        rows.append(Row(ds, f"demolitions.{slug(dim)}.structures", occurred,
                        precision, f"{sid}:structures",
                        value_num=m["demolished"], unit="structures",
                        place_id=place_id, located=located, attrs=attrs))
    if (m.get("displaced") or 0) > 0:
        rows.append(Row(ds, f"demolitions.{slug(dim)}.displaced", occurred,
                        precision, f"{sid}:displaced",
                        value_num=m["displaced"], unit="persons",
                        place_id=place_id, located=located, attrs=attrs))
    if (m.get("affected") or 0) > 0:
        rows.append(Row(ds, f"demolitions.{slug(dim)}.affected", occurred,
                        precision, f"{sid}:affected",
                        value_num=m["affected"], unit="persons",
                        place_id=place_id, located=located, attrs=attrs))
    return rows


def t_settlements(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    year = str(rec["date"])[:4]                                   # 100% -12-31
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    attrs["reference"] = "period-end stock"                       # REVIEW.md 2
    attrs["coverage"] = "West Bank, excludes East Jerusalem"      # spec caveat
    return [Row(ds, "settlements.settler_population", f"{year}-01-01", "year",
                rec["stable_id"], value_num=rec["metrics"]["count"],
                unit="settlers", place_id=places["region"]["West Bank"],
                attrs=attrs)]


def t_land(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    etype = rec.get("event_type")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    if etype == "demolition":
        # the one honest date in the category: demolition.demolition_date
        occurred = str((rec.get("demolition") or {}).get("demolition_date")
                       or rec["date"])[:10]
        precision = "day"
    else:
        occurred, precision = str(rec["date"])[:10], "unknown"    # law 1
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    m = rec.get("metrics") or {}
    return [Row(ds, f"land.{slug(etype)}", occurred, precision,
                rec["stable_id"], value_num=m.get("count"),
                value_text=rec.get("land_status"), unit=m.get("unit"),
                place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def t_culture(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    return [Row(ds, f"culture.heritage_site.{slug(rec['site_type'])}",
                str(rec["date"])[:10], "unknown",                 # law 1: 100%
                rec["stable_id"], value_num=rec["metrics"]["count"],
                value_text=rec.get("site_status"), unit="sites",
                place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def t_education(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = {k: demojibake(v, counts)
             for k, v in passthrough(rec, spec.get("attrs_passthrough")).items()}
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    loc = rec.get("location") or {}
    pid = places["pcode"].get(loc.get("admin2_pcode"))
    if pid is not None:
        place_id, located = pid, True
    else:
        place_id, located = region_place(places, "West Bank", attrs)
    return [Row(ds, "education.school_record", str(rec["date"])[:10],
                "unknown",                                        # law 1: 100%
                rec["stable_id"], value_num=1,
                value_text=rec.get("school_status"), unit="schools",
                place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def t_connectivity(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    m = rec.get("metrics") or {}
    if rec.get("outage_start"):                                   # IODA
        occurred, precision = str(rec["outage_start"]), "hour"
        value = m.get("duration_seconds")
    else:                                                         # OONI
        occurred, precision = str(rec["date"])[:10], "day"
        value = rec.get("anomaly_rate", m.get("value"))
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    return [Row(ds, f"connectivity.{slug(rec['event_type'])}", occurred,
                precision, rec["stable_id"], value_num=value,
                place_id=place_id, located=located, attrs=attrs)]


def t_funding(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    f = rec.get("funding") or {}
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    return [Row(ds, f"funding.{slug(f['status'])}", str(rec["date"])[:10],
                "day", rec["stable_id"], value_num=f.get("amount_usd"),
                unit="USD", place_id=place_id, located=located, attrs=attrs)]


def t_pcbs(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    year = str(rec["date"])[:4]                                   # 100% -01-01
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    return [Row(ds, f"pcbs.{slug(rec['indicator_code'])}", f"{year}-01-01",
                "year", rec["stable_id"], value_num=rec["metrics"]["value"],
                unit=rec["metrics"].get("unit"),
                place_id=place_id, located=located, attrs=attrs)]


def t_economic(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    key = (ds, rec.get("indicator_code"), str(rec.get("date"))[:10],
           (rec.get("location") or {}).get("region"))
    if key in t_economic.dup_keys:                                # REVIEW.md 4
        return Drop("contradictory_duplicate")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    year = str(rec["date"])[:4]              # -01-01 kept, -12-31 truncated:
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    unit = None if ds == "v1_economic_imf" else rec["metrics"].get("unit")
    return [Row(ds, f"economic.{slug(rec['indicator_code'])}", f"{year}-01-01",
                "year", rec["stable_id"], value_num=rec["metrics"]["value"],
                unit=unit, place_id=place_id, located=located, attrs=attrs)]


def _economic_prepass(records, spec, counts):
    seen, dups = set(), set()
    for rec in records:
        key = ("v1_economic_pcbs_direct" if "pcbs.gov.ps"
               in str((rec.get("sources") or [{}])[0].get("url")) else "",
               rec.get("indicator_code"), str(rec.get("date"))[:10],
               (rec.get("location") or {}).get("region"))
        if key[0]:
            if key in seen:
                dups.add(key)
            seen.add(key)
    t_economic.dup_keys = {k for k in dups}


t_economic.prepass = _economic_prepass
t_economic.dup_keys = set()


def t_health(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    if not rec.get("indicator_code"):
        # measured 2026-08-07: v1's rebuild began emitting 184 Gaza-MoH and
        # 26 HDX rows into health with no indicator_code. An observation is
        # (indicator, value, unit, time, place); these have no indicator, so
        # they are dropped and counted — never guessed into WHO's namespace.
        return Drop("no_indicator_identity")
    dim = (rec.get("dimension") or {}).get("code")
    indicator = f"health.{slug(rec['indicator_code'])}" + \
                (f".{slug(dim)}" if dim else "")                  # null-brace
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    year = str(rec["date"])[:4]                                   # 100% -01-01
    attrs["region"] = "Palestine"
    return [Row(ds, indicator, f"{year}-01-01", "year", rec["stable_id"],
                value_num=rec["metrics"]["value"],
                unit=rec["metrics"].get("unit"), attrs=attrs)]


_FOOD_GOV = {"Ramallah and Albireh": "Ramallah", "Kan Younis": "Khan Younis"}


def t_food(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    day = str(rec["date"])[:10]                                   # 100% the 15th
    occurred = day[:8] + "01"                                     # month start
    loc = rec.get("location") or {}
    market = loc.get("name")
    if market in ("West Bank", "Gaza Strip"):                     # REVIEW.md 8
        place_id, located = region_place(places, market, attrs)
        attrs["basket"] = "region-wide"
    else:
        gov = _FOOD_GOV.get(loc.get("governorate"), loc.get("governorate"))
        pid = places["governorate"].get(gov)
        if pid is None:
            counts[f"governorate_unresolved:{gov}"] += 1
            place_id, located = None, False
        else:
            place_id, located = pid, True
    return [Row(ds, f"food.price.{slug(rec['commodity'])}", occurred, "month",
                rec["stable_id"], value_num=rec["metrics"]["price"],
                unit=rec["metrics"].get("unit"),
                place_id=place_id, located=located, attrs=attrs)]


_UNIT_CANON = {"truck": "truck", "trucks": "truck", "ton": "tonne",
               "mt": "tonne", "pallets": "pallet", "piece": "piece",
               "each": "piece", "ctn": "box", "box": "box",
               "vehicles": "vehicle", "tents": "tent"}
_CROSSINGS = {"Kerem Shalom": "Kerem Shalom Crossing",
              "Rafah Crossing": "Rafah Crossing",
              "Erez": "Erez Crossing (Beit Hanoun)",
              "Kissufim": "Kissufim Crossing",
              # Verified 2026-08-05: OCHA SitUpdate #326 equates the names —
              # "the Zikim crossing (Erez West/As Siafa)". UNRWA's dashboard
              # calls the same northern corridor 'Western Erez'.
              "Western Erez": "Zikim Crossing"}
# Gate 96 stays on the region row deliberately: it is a military gate on the
# Netzarim corridor serving CENTRAL Gaza — not a border terminal, and not in
# any crossings dictionary. JLOTS (the dismantled pier) likewise.


def t_aid_access(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    day = str(rec["date"])[:10]
    if day > "2024-05-05":
        attrs["upstream_partial"] = True          # source disclaimer, derived
    raw_unit = (rec.get("metrics") or {}).get("unit")
    unit = _UNIT_CANON.get(str(raw_unit).lower(), raw_unit)
    if unit != raw_unit:
        attrs["unit_raw"] = raw_unit
    crossing = rec.get("crossing")
    name_en = _CROSSINGS.get(crossing)
    if name_en:
        place_id, located = places["crossing"][name_en], True
    else:                                          # Western Erez / Gate 96 / JLOTS
        place_id, located = places["region"]["Gaza Strip"], False
    return [Row(ds, f"aid_access.consignment.{slug(rec['cargo_category'])}",
                day, "day", rec["stable_id"],
                value_num=(rec.get("metrics") or {}).get("quantity"),
                unit=unit, place_id=place_id, located=located, attrs=attrs)]


def t_martyrs(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    if rec.get("event_type") == "cumulative_summary":
        return [Row(ds, "martyrs.cumulative_summary", str(rec["date"])[:10],
                    "day", rec["stable_id"],
                    value_num=rec["metrics"]["killed"], unit="persons",
                    attrs=attrs)]
    place_id, located = region_place(places,
                                     rec["location"]["region"], attrs)
    return [Row(ds, "martyrs.identified_killed", "2023-10-07", "unknown",
                rec["stable_id"], value_num=rec["metrics"]["killed"],
                value_text=rec.get("name"), unit="persons",
                place_id=place_id, located=located, attrs=attrs)]


def t_infrastructure(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    etype = rec.get("event_type")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    m = rec.get("metrics") or {}
    loc = rec.get("location") or {}
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    detail = rec.get("infrastructure_detail") or {}
    if etype == "infrastructure_damage":
        indicator = f"infrastructure.damage.{slug(detail.get('type'))}"
        value, occurred, precision = m.get("count"), str(rec["date"])[:10], "day"
    elif etype == "satellite_damage_assessment":
        indicator = "infrastructure.satellite_damage_assessment"
        value = m.get("structures_total_affected")
        occurred, precision = str(rec["date"])[:10], "day"
    else:                                       # locality_record / barrier_segment
        indicator = f"infrastructure.{slug(etype)}"
        value = m.get("count")
        occurred, precision = str(rec["date"])[:10], "unknown"    # law 1: 100%
        # The 603 HDX registers name every row "Unknown Locality" or
        # "Separation Barrier Segment": the source carries NO usable name, so
        # the only thing that makes a row THIS row is where it is. Measured
        # 603/603 distinct. Discarding it (as this transformer did until
        # 2026-08-07) left the dataset with no identity at all — and the
        # identity guard then froze it at 2 keys.
        if loc.get("lat") is not None and loc.get("lon") is not None:
            attrs["geo_key"] = f"{loc['lat']:.6f},{loc['lon']:.6f}"
    if etype != "barrier_segment":                                # latlon_exclude
        pid = places["pcode"].get(loc.get("admin2_pcode"))
    else:
        pid = None
    if pid is not None:
        place_id, located = pid, True
    else:
        region = loc.get("region") or ("West Bank" if etype in
                                       ("barrier_segment", "locality_record")
                                       else "Gaza Strip")
        place_id, located = region_place(places, region, attrs)
    return [Row(ds, indicator, occurred, precision, rec["stable_id"],
                value_num=value, value_text=detail.get("damage_level"),
                unit=m.get("unit"), place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def _ds_over(spec, ds_key, *path, default=None):
    """datasets[].overrides lookup: _ds_over(spec, key, 'attrs_passthrough')."""
    for ds in spec["datasets"]:
        if ds["key"] == ds_key:
            cur = ds.get("overrides", {})
            for p in path:
                cur = cur.get(p, {}) if isinstance(cur, dict) else {}
            return cur or default
    return default


def t_conflict(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    etype = slug(rec.get("event_type"))
    loc = rec.get("location") or {}
    m = rec.get("metrics") or {}
    sources = rec.get("sources") or []

    # declared, measured, counted drops (spec drop blocks)
    if etype == "daily_casualty_report" and loc.get("region") == "West Bank":
        return Drop("v1_placeholder_all_metrics_zero")
    if sources and sources[0].get("name") == "Good Shepherd":
        return Drop("v1_placeholder_no_payload")

    # strictest-license-wins assertion for multi-source rows (REVIEW.md 7),
    # skipping declared provenance-only credits — a citation is not a
    # licence conflict (spec `provenance_only`, added 2026-08-07)
    if len(sources) > 1:
        by_name = spec["source_routing"]["by_name"]
        prov_only = set(spec.get("provenance_only") or [])
        routed_commercial = places["_commercial"].get(by_name.get(
            sources[0].get("name")))
        for s in sources[1:]:
            key = by_name.get(s.get("name"))
            if key in prov_only:
                counts["provenance_credit"] += 1
                continue
            other = places["_commercial"].get(key)
            if routed_commercial is True and other is False:
                counts["license_order_violation"] += 1

    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    if len(sources) > 1:
        attrs["provenance"] = [
            {"name": s.get("name"), "url": s.get("url")} for s in sources[1:]]

    # shape override: the cumulative Gaza series is a time series
    if etype in ("daily_casualty_report", "summary"):
        attrs["cumulative"] = True
        gaza = places["region"]["Gaza Strip"]
        day = str(rec["date"])[:10]
        sid = rec["stable_id"]
        rows = [Row(ds, "conflict.gaza_cumulative_killed", day, "day",
                    f"{sid}:killed", value_num=m.get("killed"),
                    unit="persons", place_id=gaza, attrs=attrs)]
        if (m.get("injured") or 0) > 0:
            rows.append(Row(ds, "conflict.gaza_cumulative_injured", day, "day",
                            f"{sid}:injured", value_num=m.get("injured"),
                            unit="persons", place_id=gaza, attrs=attrs))
        return rows

    # events
    if rec.get("date_precision"):                      # POM villages, verbatim
        precision = rec["date_precision"]
    elif etype == "aggregate_fatality":                # B'Tselem period totals
        precision = "unknown"
    else:
        precision = "day"
    lat, lon = loc.get("lat"), loc.get("lon")
    pid = places["pcode"].get(loc.get("admin2_pcode"))
    located = False
    if pid is not None:
        located = True
    elif lat is not None:
        pid = places["_pip"].resolve(lat, lon)
        located = True                                  # point-grade geometry
    elif loc.get("gazetteer_key") in places["_v1key"]:
        pid = places["_v1key"][loc["gazetteer_key"]]
        located = True
    else:
        pid, located = region_place(places, loc.get("region"), attrs)
    metrics = {k: m.get(k) for k in ("killed", "injured", "displaced",
                                     "affected", "unit")
               if m.get(k) not in (None, 0)}
    q = (rec.get("quality") or {}).get("score") or 0.7
    return [EventRow(ds, f"conflict.{etype}", str(rec["date"])[:10],
                     precision, rec["stable_id"], place_id=pid,
                     lat=lat, lon=lon, located=located, confidence=q,
                     independent_sources=max(len(sources), 1),
                     metrics=metrics, attrs=attrs)]


_CENSUSES = (("population_1922", "1922"), ("population_1931", "1931"),
             ("population_1945", "1945"), ("population_2016", "2016"))


def t_historical(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    loc = rec.get("location") or {}
    m = rec.get("metrics") or {}

    if ds == "v1_historical_archives":                 # 27 timeline → events
        attrs = passthrough(rec, _ds_over(spec, ds, "attrs_passthrough",
                                          default=[]))
        attrs["summary"] = rec.get("description")      # sanctioned law-6 exemption
        attrs["source_citation"] = (rec.get("sources") or [{}])[0].get("name")
        day = str(rec["date"])[:10]
        etype = slug(rec.get("event_type"))
        if day.endswith("-12-31") and etype == "uprising":       # law 2
            occurred, precision = f"{day[:4]}-01-01", "year"
        else:
            occurred, precision = day, "day"
        pid, located = region_place(places, loc.get("region"), attrs)
        metrics = {k: m.get(k) for k in ("killed", "displaced")
                   if m.get(k) not in (None, 0)}
        return [EventRow(ds, f"historical.{etype}", occurred, precision,
                         rec["stable_id"], place_id=pid, located=located,
                         independent_sources=1, metrics=metrics, attrs=attrs)]

    # POM localities: fan out censuses + status (REVIEW.md / spec fan_out)
    attrs = passthrough(rec, _ds_over(spec, ds, "attrs_passthrough",
                                      default=[]))
    # Mandate Palestine reused names heavily: five villages called al-Tira,
    # and eight cases where a post-1948 Jewish locality took the name of the
    # Palestinian village beside it, inside the same 1945 district. Two
    # localities called En HaHoresh sit in Tulkarem. Where the name, district
    # and group all match, the coordinates are what remain — and they are the
    # honest answer, because these ARE different places.
    if loc.get("lat") is not None and loc.get("lon") is not None:
        attrs["geo_key"] = f"{loc['lat']:.5f},{loc['lon']:.5f}"
    # the historic locality itself first — most Mandate villages sit inside
    # 1948 Israel, where no modern governorate polygon contains them, so the
    # point-in-polygon test alone leaves 4,141 rows unplaced
    pid = places["_historic_geo"].get(
        (f"{loc['lat']:.5f}", f"{loc['lon']:.5f}")
    ) if loc.get("lat") is not None and loc.get("lon") is not None else None
    if pid is None:
        pid = places["_pip"].resolve(loc.get("lat"), loc.get("lon"))
    located = pid is not None
    sid = rec["stable_id"]
    rows = []
    for field_, year in _CENSUSES:
        v = m.get(field_)
        if v is not None and v > 0:
            rows.append(Row(ds, "historical.population", f"{year}-01-01",
                            "year", f"{sid}:c{year}", value_num=v,
                            unit="persons", place_id=pid, located=located,
                            attrs={**attrs, "census": year}))
    day = str(rec["date"])[:10]
    if day == "1945-04-01":                # Village Statistics reference date
        occurred, precision = "1945-01-01", "year"
    else:
        occurred, precision = day, "day"   # real 1948 depopulation dates
    rows.append(Row(ds, "historical.locality_status", occurred, precision,
                    f"{sid}:status", value_text=rec.get("locality_status"),
                    place_id=pid, located=located, attrs=attrs))
    return rows


_UNRWA_AGG = {"Jordan", "Lebanon", "Syria", "West Bank", "Gaza Strip",
              "Total registered refugees", "Registered refugees",
              "Other registered people", "Total registered people",
              "Refugees living within official camp borders",
              "% living within camp borders"}


def t_refugees(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    loc = rec.get("location") or {}
    m = rec.get("metrics") or {}
    attrs = passthrough(rec, _ds_over(spec, ds, "attrs_passthrough",
                                      default=[]))
    if ds == "v1_refugees_unhcr":
        year = str(rec["date"])[:4]                    # 100% -12-31, law 2
        return [Row(ds, "refugees.cross_border", f"{year}-01-01", "year",
                    rec["stable_id"], value_num=m.get("count"), unit="people",
                    attrs=attrs)]
    if ds == "v1_refugees_idmc":
        day = str(rec["date"])[:10]
        if day.endswith("-12-31"):                     # law 2, hits 2 of 334
            occurred, precision = f"{day[:4]}-01-01", "year"
        else:
            occurred, precision = day, "day"
        pid = places["_pip"].resolve(loc.get("lat"), loc.get("lon")) \
            or places["pcode"].get(loc.get("admin2_pcode"))
        return [Row(ds, "refugees.displacement_event", occurred, precision,
                    rec["stable_id"], value_num=m.get("displaced"),
                    unit="persons", place_id=pid, located=pid is not None,
                    attrs=attrs)]
    # UNRWA camp registry: build-stamp date → unknown (law 1 by analogy)
    name = loc.get("name")
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    if name in _UNRWA_AGG:                             # REVIEW.md 9
        attrs["aggregate_label"] = name
        unit = "percent" if str(name).startswith("%") else "people"
        return [Row(ds, "refugees.registered_total", str(rec["date"])[:10],
                    "unknown", rec["stable_id"], value_num=m.get("count"),
                    unit=unit, reported_at=fetched, attrs=attrs)]
    pid = places["_pip"].resolve(loc.get("lat"), loc.get("lon"))
    return [Row(ds, "refugees.camp_population", str(rec["date"])[:10],
                "unknown", rec["stable_id"], value_num=m.get("count"),
                unit="people", place_id=pid, located=pid is not None,
                reported_at=fetched, attrs=attrs)]


# ── conflict_westbank — T4P's RAW West Bank cumulative series ────────────────
# v1's unified transform maps only the daily killed/injured fields (always 0
# for WB — the very rows conflict.yaml drops) and destroys the cumulative
# fields, so this spec reads the RAW quarterlies the healed nightly fetch
# refreshes. Law 1 applied to T4P's padding: flash_source='fill' days repeat
# yesterday's numbers on a date nothing was observed — the prepass keeps only
# 'un' days (real OCHA flash updates, even when values held) and fill days
# where a value actually moved.

_WB_CUMS = [
    ("killed_cum", "conflict.westbank_cumulative_killed", "persons"),
    ("injured_cum", "conflict.westbank_cumulative_injured", "persons"),
    ("killed_children_cum",
     "conflict.westbank_cumulative_killed_children", "persons"),
    ("injured_children_cum",
     "conflict.westbank_cumulative_injured_children", "persons"),
    ("settler_attacks_cum",
     "conflict.westbank_cumulative_settler_attacks", "attacks"),
    ("displaced_households_cum",
     "conflict.westbank_cumulative_displaced_households", "households"),
    ("displaced_persons_cum",
     "conflict.westbank_cumulative_displaced_persons", "persons"),
    ("displaced_children_cum",
     "conflict.westbank_cumulative_displaced_children", "persons"),
]


def _wb_day(rec):
    return str(rec.get("report_date") or rec.get("date") or "")[:10]


def t_conflict_westbank(rec, spec, places, counts):
    ds = "v1_conflict_t4p_westbank"
    day = _wb_day(rec)
    if not day:
        return Drop("missing_date")
    if day not in t_conflict_westbank.keep:
        return Drop("fill_padding")
    wb = places["region"]["West Bank"]
    attrs = {"cumulative": True, "flash_source": rec.get("flash_source")}
    rows = []
    for field_name, indicator, unit in _WB_CUMS:
        v = rec.get(field_name)
        if v is None:
            continue
        rows.append(Row(ds, indicator, day, "day",
                        f"t4praw-wb-{day}:{field_name}", value_num=v,
                        unit=unit, place_id=wb, attrs=attrs))
    return rows or Drop("no_metrics")


def _wb_prepass(all_recs, spec, counts):
    """Chronological change-detection over the whole series before any
    per-record transform: the keep-set is every 'un' day plus every fill
    day whose value tuple moved; everything else is carried-forward
    padding, dropped and counted."""
    recs = sorted((r for r in all_recs if isinstance(r, dict) and _wb_day(r)),
                  key=_wb_day)
    keep, prev = set(), None
    for r in recs:
        tup = tuple(r.get(k) for k, _, _ in _WB_CUMS)
        if r.get("flash_source") == "un" or prev is None or tup != prev:
            keep.add(_wb_day(r))
        prev = tup
    t_conflict_westbank.keep = keep


t_conflict_westbank.prepass = _wb_prepass


# ── water_gho — WHO GHO WASH indicators, v2's own fetch ──────────────────────
# The one code with PSE data the databank lacked (WSH_SANITATION_OD; the
# whole diff is in water_gho.yaml). Conventions mirror v1_health_who exactly
# so the water domain reads as one system.

_GHO_DIM_NAMES = {
    "RESIDENCEAREATYPE_RUR": "Rural",
    "RESIDENCEAREATYPE_URB": "Urban",
    "RESIDENCEAREATYPE_TOTL": "Total",
}


def t_water_gho(rec, spec, places, counts):
    ds = "who_gho_wash"
    code, year = rec.get("IndicatorCode"), rec.get("TimeDim")
    if not code or not year:
        return Drop("missing_identity")
    value, basis = rec.get("NumericValue"), "numeric"
    if value is None:
        # measured: GHO publishes this series as integer-rounded display
        # strings (Value "0"/"1"/"2") with NumericValue null — disclosed
        try:
            value = float(rec.get("Value"))
            basis = "gho_display_value"
        except (TypeError, ValueError):
            return Drop("no_value")
    dim = rec.get("Dim1") or "TOTAL"
    attrs = {"code": dim, "name": _GHO_DIM_NAMES.get(dim, dim),
             "type": rec.get("Dim1Type") or "", "region": "Palestine",
             "indicator_code": code, "value_basis": basis}
    return [Row(ds, f"water.{slug(code)}.{slug(dim)}", f"{year}-01-01",
                "year", f"gho-{code}-{year}-{dim}", value_num=value,
                unit="percentage", place_id=None, attrs=attrs)]


TRANSFORMERS = {
    "conflict": t_conflict,
    "conflict_westbank": t_conflict_westbank,
    "water_gho": t_water_gho,
    "historical": t_historical,
    "refugees": t_refugees,
    "prisoners": t_prisoners,
    "casualties": t_casualties,
    "demolitions": t_demolitions,
    "settlements": t_settlements,
    "land": t_land,
    "culture": t_culture,
    "education": t_education,
    "connectivity": t_connectivity,
    "funding": t_funding,
    "pcbs": t_pcbs,
    "economic": t_economic,
    "health": t_health,
    "food": t_food,
    "aid_access": t_aid_access,
    "martyrs_snapshot_2023": t_martyrs,
    "infrastructure": t_infrastructure,
}


# ── the run ──────────────────────────────────────────────────────────────────

def ensure_datasets(conn, spec, category) -> dict:
    """Upsert the spec's pre-declared datasets; return key → dataset_id."""
    out = {}
    with conn.cursor() as cur:
        for ds in spec["datasets"]:
            cur.execute("SELECT source_id FROM source WHERE key = %s",
                        (ds["source"],))
            row = cur.fetchone()
            if row is None:
                raise SpecRefused(f"dataset {ds['key']}: source {ds['source']!r}"
                                  " not in `source` — run migrations first")
            # Format v2 `v1_category:` — a spec whose file name is not the
            # serving category (conflict_westbank → conflict) declares which
            # category views its datasets join.
            cat_label = spec.get("v1_category", category)
            cur.execute("""
                INSERT INTO dataset (key, name, source_id, v1_category,
                                     cadence, active)
                VALUES (%s, %s, %s, %s, 'migration', true)
                ON CONFLICT (key) DO UPDATE SET v1_category = EXCLUDED.v1_category
                RETURNING dataset_id""",
                (ds["key"], f"v1 {category} — {ds['source']}",
                 row[0], cat_label))
            out[ds["key"]] = cur.fetchone()[0]
    return out


INSERT_SQL = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num,
                         value_text, unit, occurred_at, occurred_precision,
                         reported_at, raw_ref, v1_stable_id, identity_key,
                         attrs)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value_num)s,
        %(value_text)s, %(unit)s, %(occurred_at)s, %(precision)s,
        %(reported_at)s, %(raw_ref)s, %(v1_stable_id)s, %(identity_key)s,
        %(attrs)s)
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE v1_stable_id IS NOT NULL
DO NOTHING
"""

EVENT_INSERT_SQL = """
INSERT INTO event (event_type, place_id, geom, occurred_at,
                   occurred_precision, status, confidence, claim_count,
                   independent_sources, contradicted_by, metrics, attrs)
VALUES (%(event_type)s, %(place_id)s,
        CASE WHEN %(lon)s::float8 IS NULL THEN NULL
             ELSE ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
        END,
        %(occurred_at)s, %(precision)s, 'believed', %(confidence)s, 0,
        %(independent_sources)s, 0, %(metrics)s, %(attrs)s)
ON CONFLICT ((attrs->>'v1_stable_id')) WHERE attrs ? 'v1_stable_id'
DO NOTHING
"""


def run(category: str, dry_run: bool = False) -> dict:
    spec = load_spec(category)
    if category not in TRANSFORMERS:
        raise SpecRefused(f"{category}: spec is reviewed but no transformer "
                          "implements it yet — implement, do not improvise")
    transformer = TRANSFORMERS[category]

    counts: Counter = Counter()
    drops: Counter = Counter()
    rows: list[Row] = []
    refs: dict[Path, str] = {}
    seen_stable: set[str] = set()

    # Format v2 `identity:` — cross-run natural-key idempotency for datasets
    # whose v1 stable_ids are unstable (2026-08-07: v1 re-hashed after the
    # T4P heal and every floor-less register re-inserted its whole
    # generation). 044's unique index cannot see this: new hash = new row.
    # Declared identity is what the row IS, independent of v1's hashing.
    identity_spec = spec.get("identity")
    known_identities: set[str] = set()

    # Events need the same protection as observations: 046's index keys on
    # v1_stable_id, so a re-hashed upstream re-inserts the whole history
    # (measured 2026-08-07: conflict re-added 8,282 events). An event's
    # natural identity is what happened, where, when, at what scale.
    known_events: set[str] = set()

    # Injectivity bookkeeping for the invariant below.
    emitted_identities: set[str] = set()
    identity_collisions: Counter = Counter()
    collision_samples: dict[str, list[str]] = defaultdict(list)

    def _event_identity(e) -> str:
        return "|".join([e.event_type, str(e.occurred_at)[:10],
                         str(e.place_id), str(e.lat), str(e.lon),
                         json.dumps(e.metrics, sort_keys=True)])

    # Identity is per DATASET, not per spec. That distinction is the whole
    # 2026-08-07 freeze: infrastructure.yaml holds a 730-day Gaza daily
    # series, a West Bank barrier register and a UNOSAT assessment series
    # under one identity that omitted occurred_at, so 5,840 rows collapsed to
    # 4 keys and the dataset could never write again — while the run
    # reported success. A spec may declare `identity:` once and override it
    # per dataset through the existing datasets[].overrides mechanism.
    identity_by_ds: dict[str, dict] = {}
    for _ds in spec.get("datasets", []):
        _id = ((_ds.get("overrides") or {}).get("identity")) or identity_spec
        if _id:
            identity_by_ds[_ds["key"]] = _id

    def _identity_of(r) -> str | None:
        if isinstance(r, EventRow):
            return None                 # handled by _event_identity below
        ident = identity_by_ds.get(r.dataset_key)
        if not ident:
            return None
        return identity_key_for(ident, r.dataset_key, indicator=r.indicator,
                                occurred_at=r.occurred_at,
                                place_id=r.place_id, value_num=r.value_num,
                                attrs=r.attrs)

    event_rows: list[EventRow] = []
    with connect() as conn:
        places = load_places(conn)
        places["_pip"] = PointResolver(conn)
        with conn.cursor() as cur:
            cur.execute("""SELECT source_refs->>'v1_canonical_key', place_id
                           FROM place WHERE source_refs ? 'v1_canonical_key'
                             AND merged_into IS NULL""")
            places["_v1key"] = dict(cur.fetchall())
            cur.execute("SELECT key, commercial_use FROM source")
            places["_commercial"] = dict(cur.fetchall())
            # Mandate-era localities, indexed by coordinate. v1 USED to carry
            # location.gazetteer_key and the Nakba gazetteer was re-pointed
            # against it by a one-off script; v1's rebuild has since dropped
            # that key from all 2,490 historical records (the same regression
            # that hit demolitions). Both sides came from Palestine Open Maps,
            # so the coordinates still agree — and resolving on them means a
            # reload lands correctly by itself instead of depending on a
            # follow-up script somebody has to remember.
            cur.execute("""SELECT ST_Y(geom::geometry), ST_X(geom::geometry),
                                  place_id
                           FROM place
                           WHERE geom IS NOT NULL AND merged_into IS NULL
                             AND ST_GeometryType(geom::geometry) = 'ST_Point'
                             AND (attrs->>'historic' = 'mandate-palestine'
                                  OR source_refs ? 'v1_canonical_key')""")
            # formatted in Python, exactly as the transformer formats the
            # record's own coordinates — one renderer, same lesson as
            # identity_key_for
            places["_historic_geo"] = {(f"{a:.5f}", f"{b:.5f}"): pid
                                       for a, b, pid in cur.fetchall()}
            # what each dataset already holds, read from the STORED key
            # (052). Recomputing it in SQL is what made the first guard fail
            # open — see identity_key_for's docstring.
            if identity_by_ds:
                cur.execute("""
                    SELECT DISTINCT o.identity_key
                    FROM observation o JOIN dataset d
                      ON d.dataset_id = o.dataset_id
                    WHERE d.key = ANY(%s) AND o.identity_key IS NOT NULL
                      AND upper_inf(o.sys_period)""",
                    (list(identity_by_ds),))
                known_identities = {r[0] for r in cur.fetchall()}
            if spec.get("shape") == "event" or spec.get("shape_overrides"):
                cur.execute(
                    "SELECT event_type, occurred_at::date::text, "
                    "       place_id::text, "
                    "       ST_Y(geom::geometry)::text, "
                    "       ST_X(geom::geometry)::text, metrics "
                    "FROM event "
                    "WHERE attrs->>'dataset_key' = ANY(%s) "
                    "  AND upper_inf(sys_period)",
                    ([ds["key"] for ds in spec["datasets"]],))
                for et, oc, pid, lat, lon, met in cur.fetchall():
                    known_events.add("|".join([
                        et, oc, "None" if pid is None else pid,
                        "None" if lat is None else lat,
                        "None" if lon is None else lon,
                        json.dumps(met, sort_keys=True)]))
        if hasattr(transformer, "prepass"):
            # cross-record state (e.g. economic's contradictory-duplicate
            # detection) needs the whole category before the first transform
            all_recs = []
            for f in iter_v1_files(category, spec):
                all_recs.extend(_records(json.loads(f.read_bytes())))
            transformer.prepass(all_recs, spec, counts)
        for f in iter_v1_files(category, spec):
            payload = f.read_bytes()
            refs[f] = bronze.put(f"v1_{category}", payload,
                                 url=f"file://{f}").ref
            for rec in _records(json.loads(payload)):
                if not isinstance(rec, dict):
                    counts["not_a_dict"] += 1
                    continue
                counts["records_read"] += 1
                result = transformer(rec, spec, places, counts)
                if isinstance(result, Drop):
                    drops[result.reason] += 1
                    continue
                for r in result:
                    if r.v1_stable_id in seen_stable:
                        counts["deduped"] += 1
                        continue
                    # resolution floors judge what the TRANSFORM produced, not
                    # what happened to be new this run — otherwise a healthy
                    # no-op sync fails on a handful of unresolved stragglers
                    counts["decided_total"] += 1
                    if r.located:
                        counts["located_total"] += 1
                    ident = _identity_of(r)
                    if ident is not None:
                        # THE INVARIANT: an identity that cannot tell two rows
                        # of THIS run apart cannot tell them apart across runs
                        # either — it silently freezes the dataset. Recorded
                        # per dataset here and enforced before any write.
                        if ident in emitted_identities:
                            identity_collisions[r.dataset_key] += 1
                            if len(collision_samples[r.dataset_key]) < 3:
                                collision_samples[r.dataset_key].append(ident)
                        emitted_identities.add(ident)
                        if ident in known_identities:
                            # already in the databank under an older v1 hash —
                            # the 2026-08-07 doubling, prevented at the source
                            counts["identity_already_held"] += 1
                            # a DRY RUN reports what the spec PRODUCES (the
                            # arithmetic under test); only a real run drops
                            # the already-held rows. emitted − already_held
                            # is what a write would insert.
                            if not dry_run:
                                continue
                        else:
                            known_identities.add(ident)
                    if isinstance(r, EventRow):
                        ek = _event_identity(r)
                        if ek in known_events:
                            counts["event_already_held"] += 1
                            if not dry_run:
                                continue
                        else:
                            known_events.add(ek)
                    if ident is not None and (
                            identity_by_ds.get(r.dataset_key, {})
                            .get("collision_kind") != "indistinguishable"):
                        # Only `indistinguishable` datasets go keyless — their
                        # duplicates are DIFFERENT things the source records
                        # identically (aid_access lorries), so collapsing them
                        # would delete real data. A `duplicate_fact` dataset
                        # keeps its key and lets 052 refuse the second copy,
                        # which is the dedup we want. Getting this backwards
                        # cost IDMC a silent doubling on 2026-08-07.
                        r.identity_key = ident
                    seen_stable.add(r.v1_stable_id)
                    r.raw_ref = refs[f]
                    (event_rows if isinstance(r, EventRow) else rows).append(r)

        # ── enforcement, before any write ────────────────────────────────────
        n = counts["records_read"]
        problems = []
        if n < spec["expect"]["min_records"]:
            problems.append(f"records_read {n} < expect.min_records "
                            f"{spec['expect']['min_records']}")
        max_obs = spec["expect"].get("max_observations")
        if max_obs and len(rows) > max_obs:
            # health's failure mode: a run that "succeeds with more" has
            # failed to dedupe and must say so
            problems.append(f"emitted {len(rows)} > expect.max_observations "
                            f"{max_obs}")
        # THE INJECTIVITY INVARIANT (added 2026-08-07 after the freeze).
        # An identity that maps two distinct rows to one key does not
        # de-duplicate — it DELETES. The failure is silent by construction:
        # the second row is skipped as "already held", the run reports
        # success, and the dataset can never grow again. infrastructure sat
        # at 5,840 rows / 4 keys for a day looking perfectly healthy.
        # A spec may declare `identity.allow_collisions: <measured N>`, and
        # only a measured number — the same posture `drop:` already requires.
        for ds_key, n_coll in identity_collisions.items():
            allowed = (identity_by_ds.get(ds_key, {}) or {}).get(
                "allow_collisions", 0)
            if n_coll > allowed:
                sample = "; ".join(collision_samples[ds_key])
                problems.append(
                    f"identity is not injective for {ds_key}: {n_coll} "
                    f"collisions (allowed {allowed}) — two different rows "
                    f"share one identity, so the second can never be "
                    f"written. Samples: {sample}")
        for k in counts:
            if k.startswith(("unroutable:", "no_dataset_for_source:",
                             "governorate_unresolved:",
                             "license_order_violation")):
                problems.append(f"{k} × {counts[k]}")
        declared = {d["reason"] for d in spec.get("drop", [])} | {"unroutable"}
        for reason in drops:
            if reason not in declared:
                problems.append(f"undeclared drop reason: {reason}")
        # `decided` is enforced by the explicit failure counters above — an
        # unroutable name or unresolved governorate already fails the run.
        # Deduped rows reached a decision; they are duplicates, not failures.
        decided = counts["decided_total"] or (len(rows) + len(event_rows))
        located = counts["located_total"] or (
            sum(1 for r in rows if r.located) +
            sum(1 for r in event_rows if r.located))
        place_spec = spec.get("place", {})
        min_located = place_spec.get("min_located_pct")
        if min_located and located / max(decided, 1) < min_located:
            problems.append(f"located {located}/{decided} < {min_located}")
        if problems:
            raise SpecRefused(f"{category}: run FAILED — " + "; ".join(problems))

        written = events_written = 0
        if not dry_run:
            dataset_ids = ensure_datasets(conn, spec, category)
            with conn.cursor() as cur:
                for r in rows:
                    cur.execute(INSERT_SQL, {
                        "dataset_id": dataset_ids[r.dataset_key],
                        "place_id": r.place_id, "indicator": r.indicator,
                        "value_num": r.value_num, "value_text": r.value_text,
                        "unit": r.unit, "occurred_at": r.occurred_at,
                        "precision": r.precision, "reported_at": r.reported_at,
                        "raw_ref": getattr(r, "raw_ref", None),
                        "v1_stable_id": r.v1_stable_id,
                        "identity_key": r.identity_key,
                        "attrs": json.dumps(r.attrs, ensure_ascii=False),
                    })
                    written += cur.rowcount
                for e in event_rows:
                    attrs = dict(e.attrs)
                    attrs["v1_stable_id"] = e.v1_stable_id
                    attrs["dataset_key"] = e.dataset_key
                    if e.raw_ref:
                        attrs["raw_ref"] = e.raw_ref
                    cur.execute(EVENT_INSERT_SQL, {
                        "event_type": e.event_type, "place_id": e.place_id,
                        "lat": e.lat, "lon": e.lon,
                        "occurred_at": e.occurred_at,
                        "precision": e.precision,
                        "confidence": e.confidence,
                        "independent_sources": e.independent_sources,
                        "metrics": json.dumps(e.metrics, ensure_ascii=False),
                        "attrs": json.dumps(attrs, ensure_ascii=False),
                    })
                    events_written += cur.rowcount
            conn.commit()

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "category": category, "dry_run": dry_run,
        "records_read": counts["records_read"],
        "observations_emitted": len(rows),
        "events_emitted": len(event_rows),
        "written": written, "events_written": events_written,
        "deduped": counts["deduped"],
        "drops": dict(drops),
        "located_pct": round(located / max(decided, 1), 3),
        "notes": {k: v for k, v in counts.items()
                  if k not in ("records_read", "deduped")},
    }
    with RUNS.open("a") as fh:
        fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    return report


def run_all(dry_run: bool = False) -> int:
    """The nightly sync: every migrating category, idempotently, after v1's
    ~02:51 refresh. New upstream records get new stable_ids and land; old
    rows never change (corrections supersede in T2.4, never overwrite).
    Returns the number of failed categories — the exit code."""
    failed = []
    grew = {}
    for cat in sorted(TRANSFORMERS):
        try:
            rep = run(cat, dry_run=dry_run)
            if rep["written"] or rep["events_written"]:
                grew[cat] = rep["written"] + rep["events_written"]
        except SpecRefused as e:
            if "migrate=false" in str(e):
                continue
            print(f"FAIL {cat}: {e}", file=sys.stderr)
            failed.append(cat)
    print(json.dumps({"grew": grew, "failed": failed}, ensure_ascii=False))
    return len(failed)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        sys.exit(run_all(dry_run="--dry-run" in sys.argv))
    if not args:
        sys.exit("usage: python -m ingest.databank <category>|--all [--dry-run]")
    out = run(args[0], dry_run="--dry-run" in sys.argv)
    print(json.dumps(out, indent=2, ensure_ascii=False))
