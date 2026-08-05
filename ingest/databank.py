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
from collections import Counter
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
    return spec


def iter_v1_files(category: str):
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
    attrs: dict = field(default_factory=dict)


@dataclass
class Drop:
    reason: str


def slug(s: str) -> str:
    """Global loader convention: lowercase, runs of non-alnum → '_'."""
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


# ── place maps (loaded once per run, keyed on names not ids) ────────────────

def load_places(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT place_id, kind, name_en, admin2_pcode
                       FROM place WHERE merged_into IS NULL
                         AND kind IN ('region', 'governorate')""")
        rows = cur.fetchall()
    by_name = {(k, n): pid for pid, k, n, _ in rows}
    by_pcode = {pc: pid for pid, k, n, pc in rows if k == "governorate" and pc}
    return {
        "region": {n: pid for (k, n), pid in by_name.items() if k == "region"},
        "governorate": {n: pid for (k, n), pid in by_name.items()
                        if k == "governorate"},
        "pcode": by_pcode,
    }


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


TRANSFORMERS = {
    "prisoners": t_prisoners,
    "casualties": t_casualties,
    "demolitions": t_demolitions,
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
            cur.execute("""
                INSERT INTO dataset (key, name, source_id, v1_category,
                                     cadence, active)
                VALUES (%s, %s, %s, %s, 'migration', true)
                ON CONFLICT (key) DO UPDATE SET v1_category = EXCLUDED.v1_category
                RETURNING dataset_id""",
                (ds["key"], f"v1 {category} — {ds['source']}",
                 row[0], category))
            out[ds["key"]] = cur.fetchone()[0]
    return out


INSERT_SQL = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num,
                         value_text, unit, occurred_at, occurred_precision,
                         reported_at, raw_ref, v1_stable_id, attrs)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value_num)s,
        %(value_text)s, %(unit)s, %(occurred_at)s, %(precision)s,
        %(reported_at)s, %(raw_ref)s, %(v1_stable_id)s, %(attrs)s)
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE v1_stable_id IS NOT NULL
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

    with connect() as conn:
        places = load_places(conn)
        for f in iter_v1_files(category):
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
                    seen_stable.add(r.v1_stable_id)
                    r.raw_ref = refs[f]
                    rows.append(r)

        # ── enforcement, before any write ────────────────────────────────────
        n = counts["records_read"]
        problems = []
        if n < spec["expect"]["min_records"]:
            problems.append(f"records_read {n} < expect.min_records "
                            f"{spec['expect']['min_records']}")
        for k in counts:
            if k.startswith(("unroutable:", "no_dataset_for_source:",
                             "governorate_unresolved:")):
                problems.append(f"{k} × {counts[k]}")
        declared = {d["reason"] for d in spec.get("drop", [])} | {"unroutable"}
        for reason in drops:
            if reason not in declared:
                problems.append(f"undeclared drop reason: {reason}")
        retained = [r for r in rows]
        decided = len(retained)             # every Row reached a decision
        located = sum(1 for r in retained if r.located)
        place_spec = spec.get("place", {})
        min_decided = place_spec.get("min_decided_pct", 1.0)
        emitted_basis = max(len(rows) + counts["deduped"], 1)
        if decided / emitted_basis < min_decided:
            problems.append(f"decided {decided}/{emitted_basis} < {min_decided}")
        min_located = place_spec.get("min_located_pct")
        if min_located and located / max(decided, 1) < min_located:
            problems.append(f"located {located}/{decided} < {min_located}")
        if problems:
            raise SpecRefused(f"{category}: run FAILED — " + "; ".join(problems))

        written = 0
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
                        "attrs": json.dumps(r.attrs, ensure_ascii=False),
                    })
                    written += cur.rowcount
            conn.commit()

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "category": category, "dry_run": dry_run,
        "records_read": counts["records_read"],
        "observations_emitted": len(rows),
        "written": written, "deduped": counts["deduped"],
        "drops": dict(drops),
        "located_pct": round(located / max(decided, 1), 3),
        "notes": {k: v for k, v in counts.items()
                  if k not in ("records_read", "deduped")},
    }
    with RUNS.open("a") as fh:
        fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    return report


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: python -m ingest.databank <category> [--dry-run]")
    out = run(args[0], dry_run="--dry-run" in sys.argv)
    print(json.dumps(out, indent=2, ensure_ascii=False))
