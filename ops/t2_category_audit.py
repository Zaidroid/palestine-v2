"""T2.0 — measure every v1 databank category before writing a single mapping spec.

The mapping specs (db/mappings/*.yaml) are derived from what the records
actually contain, not from v1's README — every unmeasured v1 number this
project trusted turned out wrong. Reads /opt/stacks/palestine read-only.

Per category this measures the four things that decide a spec:
  - dates: how many records have one, how many are the fetch date wearing a
    record-date costume (the ingest-masquerade defeat), how many are Dec-31
    year buckets (the negative-freshness defeat), real min/max
  - geography: location.precision distribution, lat/lon / pcode /
    gazetteer_key fill — i.e. which place-resolution strategy can work
  - values: metrics fill rates and units, event_type vocabulary
  - provenance: per-record source×license pairs, stable id presence

Output: ops/t2-category-audit.json + a stdout table.
Run: .venv/bin/python -m ops.t2_category_audit
"""

from __future__ import annotations

import gc
import json
from collections import Counter
from pathlib import Path

V1_UNIFIED = Path("/opt/stacks/palestine/public/data/unified")
OUT = Path(__file__).resolve().parent / "t2-category-audit.json"

CATEGORIES = sorted(
    p.name for p in V1_UNIFIED.iterdir()
    if p.is_dir() and p.name != "snapshots"
    and ((p / "all-data.json").exists() or (p / "partitions").is_dir())
)


def _records(payload):
    if isinstance(payload, list):
        return payload
    for key in ("data", "records"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def _iter_files(d: Path):
    """A category is either one all-data.json or quarterly partitions/*.json."""
    if (d / "all-data.json").exists():
        yield d / "all-data.json"
        return
    for f in sorted((d / "partitions").glob("*.json")):
        if f.name != "index.json":
            yield f


def _fill(counter: Counter, n: int) -> dict:
    """Counter of key-path → non-empty count, as fractions of n."""
    return {k: round(v / n, 3) for k, v in sorted(counter.items(), key=lambda kv: -kv[1])}


def _top(counter: Counter, k: int = 8) -> dict:
    return dict(counter.most_common(k))


def audit_category(cat: str) -> dict:
    d = V1_UNIFIED / cat
    files = list(_iter_files(d))

    meta = {}
    if (d / "metadata.json").exists():
        meta = json.loads((d / "metadata.json").read_text())
    fetch_day = (meta.get("last_updated") or "")[:10]

    out: dict = {
        "partitioned": not (d / "all-data.json").exists(),
        "file_mb": round(sum(f.stat().st_size for f in files) / 1e6, 1),
        "has_stable_id_index": (d / "stable-id-index.json").exists(),
        "metadata_notice": meta.get("notice"),
    }

    fill: Counter = Counter()
    n = dates_present = ingest_masquerade = year_bucket = 0
    date_min = date_max = None
    precisions: Counter = Counter()
    regions: Counter = Counter()
    event_types: Counter = Counter()
    units: Counter = Counter()
    schema_versions: Counter = Counter()
    src_licenses: Counter = Counter()
    id_present = 0
    first_rec = last_rec = None

    def _all_records():
        for f in files:
            payload = json.loads(f.read_text())
            yield from _records(payload)
            del payload
            gc.collect()

    for r in _all_records():
        if not isinstance(r, dict):
            continue
        n += 1
        if first_rec is None:
            first_rec = r
        last_rec = r
        for k, v in r.items():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    if v2 not in (None, "", [], {}):
                        fill[f"{k}.{k2}"] += 1
            elif v not in (None, "", [], {}):
                fill[k] += 1

        if r.get("id"):
            id_present += 1
        schema_versions[str(r.get("schema_version"))] += 1
        event_types[str(r.get("event_type"))] += 1

        date = r.get("date")
        if date:
            dates_present += 1
            day = str(date)[:10]
            if day == fetch_day:
                ingest_masquerade += 1
            if day.endswith("-12-31"):
                year_bucket += 1
            date_min = day if date_min is None or day < date_min else date_min
            date_max = day if date_max is None or day > date_max else date_max

        loc = r.get("location") or {}
        if isinstance(loc, dict):
            precisions[str(loc.get("precision"))] += 1
            regions[str(loc.get("region"))] += 1

        metrics = r.get("metrics") or {}
        if isinstance(metrics, dict) and metrics.get("unit"):
            units[str(metrics["unit"])] += 1

        for s in r.get("sources") or []:
            if isinstance(s, dict):
                src_licenses[f"{s.get('name')} :: {s.get('license')}"] += 1

    out["records"] = n
    if not n:
        return out

    out.update({
        "id_present_pct": round(id_present / n, 3),
        "schema_versions": _top(schema_versions, 4),
        "dates": {
            "present_pct": round(dates_present / n, 3),
            "ingest_masquerade_pct": round(ingest_masquerade / n, 3),
            "year_bucket_pct": round(year_bucket / n, 3),
            "min": date_min,
            "max": date_max,
            "fetch_day": fetch_day,
        },
        "geo": {
            "precision": _top(precisions),
            "region": _top(regions, 6),
            "latlon_pct": round(fill.get("location.lat", 0) / n, 3),
            "gazetteer_key_pct": round(fill.get("location.gazetteer_key", 0) / n, 3),
            "admin2_pcode_pct": round(fill.get("location.admin2_pcode", 0) / n, 3),
            "name_pct": round(fill.get("location.name", 0) / n, 3),
        },
        "event_types": _top(event_types, 10),
        "units": _top(units, 6),
        "source_licenses": _top(src_licenses, 10),
        "field_fill": _fill(fill, n),
        "samples": [
            {k: v for k, v in rec.items() if k != "description"}
            for rec in (first_rec, last_rec) if rec is not None
        ],
    })
    return out


def main() -> None:
    report = {}
    for cat in CATEGORIES:
        report[cat] = audit_category(cat)
        r = report[cat]
        d = r.get("dates", {})
        g = r.get("geo", {})
        print(f"{cat:24s} n={r['records']:>6}  dates={d.get('present_pct', 0):>5.0%} "
              f"masq={d.get('ingest_masquerade_pct', 0):>4.0%} "
              f"ybkt={d.get('year_bucket_pct', 0):>4.0%}  "
              f"latlon={g.get('latlon_pct', 0):>4.0%} "
              f"pcode={g.get('admin2_pcode_pct', 0):>4.0%} "
              f"gaz={g.get('gazetteer_key_pct', 0):>4.0%}")
        gc.collect()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\nwrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB), "
          f"{sum(r['records'] for r in report.values())} records across {len(report)} categories")


if __name__ == "__main__":
    main()
