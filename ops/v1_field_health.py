"""Which v1 fields are actually there today, and which come and go.

Born 2026-08-08, from four separate hunts for the same bug. Each time the
symptom was different — demolition localities unnamed, historical villages
unresolvable, education and infrastructure silently at region grade, UNRWA
camps losing their coordinates — and each time the cause was one v1
enrichment step that had stopped running.

The vault (ops/vault_snapshots.py) holds 38 days of v1's own output, so the
question "is this field disappearing?" is answerable rather than arguable.
Measured across those 38 days, the answer is stranger than a regression:

    field           2026-06-25   2026-07-23   2026-08-07   today
    admin2_pcode         0          2,357          0          0     education
    admin2_pcode         0          3,261          0          0     infrastructure
    gazetteer_key        0          2,492          0          0     historical
    lat/lon            350            350        334        334     refugees

v1's geo enrichment ran for one window around 2026-07-23 — the window the
specs were written in — and is off on either side of it. So a spec citing
"admin2_pcode filled on 2,357/2,359" was true when written and false a
fortnight later, with nothing in between to say so.

The lesson is in the specs now: prefer the field that is always there. lat/lon
survived every snapshot; the derived codes did not, and v2's place ladder
therefore tries the coordinate rung before falling back. This script is how
you check that judgement is still right.

Run:  .venv/bin/python -m ops.v1_field_health
      .venv/bin/python -m ops.v1_field_health --json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resolve.db import v1_path  # noqa: E402

from ops import evidence                                     # noqa: E402

V1_UNIFIED = v1_path("public/data/unified")   # READ-ONLY

# The fields a spec's place ladder can stand on. Anything a transformer might
# reach for; ordered as the ladders try them.
GEO_FIELDS = ("lat", "lon", "admin2_pcode", "gazetteer_key", "governorate",
              "locality", "region")

# A field is FLAPPING if its FILL RATE was substantially higher and is now
# much lower. Rate, not count: health's raw count fell 40,769 → 12,712 and
# water's 74,243 → 25,049 while both stayed 100% filled — those categories
# lost RECORDS upstream, which is a different fact needing a different
# response, and a count-based test reports it as the same thing.
# 0.5 rather than 1.0 because a growing corpus moves numbers slightly every
# day and a tripwire that fires on noise gets muted.
LOSS = 0.5


def _fill(recs: list, field: str) -> int:
    return sum(1 for r in recs
               if (r.get("location") or {}).get(field) not in (None, "", [], {}))


def _records(snap) -> list:
    if snap is None:
        return []
    return snap if isinstance(snap, list) else (snap.get("data") or [])


def pick_days(days: list[str], n: int) -> list[str]:
    """Evenly spaced days, endpoints always included.

    The full 38-day sweep decompresses ~18 GB and takes tens of minutes, which
    means it gets run once and then never again. A 6-day sample runs in under
    a minute and still catches a field that was there and is not — which is
    the question. `--all-days` when the sample says something interesting.
    """
    if n >= len(days) or n < 2:
        return days
    step = (len(days) - 1) / (n - 1)
    return sorted({days[round(i * step)] for i in range(n)})


# ONE PAYLOAD AT A TIME, and never below this much free memory.
#
# This script took the host down twice on 2026-08-08 — 09:28 and, most likely,
# 07:54. main-server has 15 GB with ~7 GB available; martyrs_snapshot_2023's
# all-data.json is 142 MB of JSON, which parses to well over a gigabyte of
# Python objects, and the first version held TODAY's copy and a SNAPSHOT's
# copy simultaneously, per category, in a loop. The kernel logged "Under
# memory pressure, flushing caches" for ninety seconds and then the machine
# was gone — taking the nightly backup, a full pytest run and the audit itself
# with it, and leaving the fuel spool torn mid-write.
#
# So: count, then free, then load the next one. And refuse to start a load
# that the machine cannot afford, loudly, instead of discovering it by
# rebooting.
MIN_AVAILABLE_MB = 2048


def _available_mb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return 1 << 30                       # unknown: do not block


def _count(recs: list) -> tuple[dict[str, int], int]:
    """Fill counts and row count, so the caller can free the payload at once."""
    return {f: _fill(recs, f) for f in GEO_FIELDS}, len(recs)


def measure(n_days: int = 6, progress=None) -> dict:
    days = pick_days(evidence.snapshot_days(), n_days)
    out: dict[str, dict] = {}
    skipped: list[str] = []
    for cat_dir in sorted(p for p in V1_UNIFIED.iterdir() if p.is_dir()):
        cat = cat_dir.name
        live = cat_dir / "all-data.json"
        if not live.exists():
            continue
        if _available_mb() < MIN_AVAILABLE_MB:
            skipped.append(cat)
            continue
        if progress:
            progress(cat)
        now_n, n_today = _count(_records(json.loads(live.read_text())))
        if not n_today:
            continue
        now = {f: v / n_today for f, v in now_n.items()}

        series: dict[str, dict[str, float]] = {}
        for d in days:
            if _available_mb() < MIN_AVAILABLE_MB:
                skipped.append(f"{cat}@{d}")
                continue
            try:
                counts, n = _count(_records(evidence.open_snapshot(d, cat)))
            except Exception:
                continue
            if n:
                series[d] = {f: v / n for f, v in counts.items()}
                series[d]["_n"] = n

        peak = {f: max([s[f] for s in series.values()] + [now[f]])
                for f in GEO_FIELDS}
        lost = {f: {"peak_pct": round(peak[f], 4),
                    "now_pct": round(now[f], 4),
                    "now_n": now_n[f],
                    "peak_day": next((d for d, s in series.items()
                                      if s[f] == peak[f]), "today")}
                for f in GEO_FIELDS
                if peak[f] > 0 and now[f] < peak[f] * LOSS}
        # Record count is its own signal, reported beside the fields rather
        # than mixed into them.
        peak_n = max([s["_n"] for s in series.values()] + [n_today])
        out[cat] = {"records": n_today, "peak_records": peak_n,
                    "records_lost_pct": round(1 - n_today / peak_n, 4),
                    "now": now, "peak": peak,
                    "lost": lost, "days_compared": len(series)}
    # Law 4's posture applied to the instrument itself: what it did not look
    # at is stated, never silently absent. A short report that looks clean is
    # exactly the failure this whole file exists to prevent.
    if skipped:
        out["_skipped_for_memory"] = skipped
    return out


def main(argv: list[str]) -> int:
    n_days = 999 if "--all-days" in argv else 6
    result = measure(n_days, progress=lambda c: print(f"  reading {c} …",
                                                      flush=True))
    print()
    if "--json" in argv:
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    skipped = result.pop("_skipped_for_memory", [])
    flapping = 0
    for cat, r in sorted(result.items()):
        if not r["lost"]:
            continue
        flapping += 1
        print(f"\n{cat}  ({r['records']} records, {r['days_compared']} "
              "vaulted days compared)")
        for f, v in sorted(r["lost"].items()):
            print(f"   {f:<16} peak {v['peak_pct']:>7.1%} on {v['peak_day']}"
                  f"   →   now {v['now_pct']:>7.1%} ({v['now_n']})")
    shrunk = {c: r for c, r in result.items() if r["records_lost_pct"] > 0.1}
    if shrunk:
        print("\nRECORD COUNT, separately — these lost rows, not fields:")
        for c, r in sorted(shrunk.items()):
            print(f"   {c:<18} {r['peak_records']:>7} → {r['records']:<7}"
                  f"  ({r['records_lost_pct']:.0%} fewer)")
    if skipped:
        print(f"\nNOT MEASURED — too little free memory: {skipped}")
    print(f"\n{flapping} category(ies) have a geo field below half its "
          "vaulted peak fill RATE")
    print("A ladder that stands on a field like this is a ladder that will "
          "quietly drop a rung.\nWhich rung each category is actually "
          "standing on is in the run report: place_rung:*")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
