"""Fetch Tech4Palestine directly — the first live category to leave v1.

Stage 7's larger half. Seven finished corpora were frozen into this
repository (ops/freeze_corpus.py); the fourteen that still move need their
own fetchers, and T4P is the one to do first for three reasons:

  It is PUBLIC DOMAIN. Unlicense, verified at the publisher — "copy, modify,
  publish, use, compile, sell, or distribute … for any purpose". No
  permission to seek, no tier to worry about.

  It has a REAL API. Four endpoints, all reachable, all JSON, no key.

  It feeds THREE specs — conflict (Gaza daily), conflict_westbank (the West
  Bank cumulative series) and martyrs_snapshot_2023 (the named roster). One
  fetcher, ~77,000 rows, and the single largest v1 dependency after the
  freeze.

WHY IT WRITES QUARTER FILES. conflict_westbank already reads a RAW tree —
v1's `data/tech4palestine/westbank/2*.json` — because v1's unified transform
destroys the cumulative fields (that is what Phase 4 brick 1 recovered).
Measured 2026-08-08: v1's quarter files carry exactly T4P's own field names
(`report_date`, `killed_cum`, `flash_source`, …) and add three v1 fields the
transformer never reads. So writing T4P's live records into the same
quarter-file shape lets that spec change one line and leave v1 today, with
equivalence proving nothing moved.

ATOMIC, FLOORED, LEDGERED. Writes only on success and only above a row
floor — a bad API night must leave yesterday's file intact rather than
truncate the series, which is the failure the `expect.min_records` floors
exist to catch one layer later. Every attempt appends one line to
ops/fetch-events.ndjson, the ledger that replaces v1's refresh-events when
gap_radar stops reading v1.

Run: .venv/bin/python -m ops.fetch_t4p
     .venv/bin/python -m ops.fetch_t4p --dry-run
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "tech4palestine"
EVENTS = ROOT / "ops" / "fetch-events.ndjson"
UA = "palestine-v2 databank (zsalem33@gmail.com)"

BASE = "https://data.techforpalestine.org/api"

# name -> (url, minimum plausible rows). The floors are ~90% of what was
# measured on 2026-08-08; below one of them the API is having a bad day and
# yesterday's file is the better answer.
FEEDS = {
    "gaza_daily":  (f"{BASE}/v2/casualties_daily.min.json", 900),
    "westbank_daily": (f"{BASE}/v2/west_bank_daily.min.json", 900),
    "killed_in_gaza": (f"{BASE}/v2/killed-in-gaza.min.json", 65000),
    "summary": (f"{BASE}/v3/summary.min.json", 1),
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _event(label: str, outcome: str, **extra) -> None:
    """One NDJSON line per attempt, in the shape gap_radar already reads from
    v1's refresh-events — so the radar's streak logic is unchanged when it
    stops reading v1 at all."""
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a") as fh:
        fh.write(json.dumps({"label": label,
                             "at": datetime.now(timezone.utc).isoformat(),
                             "outcome": outcome, **extra}) + "\n")


def _write_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.replace(path)


def write_westbank_quarters(records: list, dry: bool) -> dict:
    """T4P's flat daily list becomes v1's quarter-file layout.

    Same shape v1 produced, so db/mappings/conflict_westbank.yaml changes one
    line. The three fields v1 added on top (`date`, `region`, `source`) are
    written too — the transformer does not read them, but a raw tree that
    differs from the one it replaced invites someone to wonder why.
    """
    by_q: dict[str, list] = defaultdict(list)
    for r in records:
        day = str(r.get("report_date") or "")[:10]
        if not day:
            continue
        q = f"{day[:4]}-Q{(int(day[5:7]) - 1) // 3 + 1}"
        by_q[q].append({**r, "date": day, "region": "West Bank",
                        "source": "Tech4Palestine"})
    if not dry:
        for q, rows in by_q.items():
            _write_atomic(RAW / "westbank" / f"{q}.json", rows)
    return {q: len(v) for q, v in sorted(by_q.items())}


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    failed = []
    got: dict[str, int] = {}
    for name, (url, floor) in FEEDS.items():
        try:
            payload = json.loads(_get(url))
        except (urllib.error.URLError, ValueError, TimeoutError) as e:
            print(f"  FAIL {name:<16} {type(e).__name__}: {e}")
            _event(f"t4p:{name}", "error", error=f"{type(e).__name__}")
            failed.append(name)
            continue
        n = len(payload) if isinstance(payload, list) else 1
        if n < floor:
            # The floor is the point. A truncated fetch that overwrites a
            # good file is how a series silently loses its history, and no
            # downstream check can tell that from the source shrinking.
            print(f"  REFUSED {name:<12} {n} rows < floor {floor} — keeping "
                  "yesterday's file")
            _event(f"t4p:{name}", "refused", rows=n, floor=floor)
            failed.append(name)
            continue
        got[name] = n
        if not dry:
            _write_atomic(RAW / f"{name}.json", payload)
        _event(f"t4p:{name}", "ok", rows=n)
        print(f"  ok   {name:<16} {n:>6} records")

    if "westbank_daily" in got:
        wb = json.loads(_get(FEEDS["westbank_daily"][0])) if dry else \
            json.loads((RAW / "westbank_daily.json").read_text())
        q = write_westbank_quarters(wb, dry)
        print(f"  ok   {'westbank/*.json':<16} {len(q)} quarter files, "
              f"{sum(q.values())} records")

    if not dry:
        _write_atomic(RAW / "_fetched.json", {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "Tech4Palestine (data.techforpalestine.org)",
            "license": "Unlicense — public domain, verified 2026-08-05",
            "attribution": "Data: Tech4Palestine "
                           "(data.techforpalestine.org), public domain "
                           "(Unlicense); credited by choice.",
            "feeds": got})
    print(f"\n  {len(got)}/{len(FEEDS)} feeds fetched"
          + (f", failed: {failed}" if failed else "")
          + ("  (dry run, nothing written)" if dry else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
