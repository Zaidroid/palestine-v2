"""Internet reachability for the West Bank, measured from outside.

    .venv/bin/python -m ingest.sources.connectivity
    .venv/bin/python -m ingest.sources.connectivity --dry-run

THE GAP THIS FILLS, AND WHY NO FEED COULD
Utilities was the one tier-1 gap that adding a source could not close. Discovery
found no live West Bank electricity or connectivity channel — the Jerusalem
power company's channel last posted in 2021 — and the reason is structural: when
the network goes down, the people who would report it are the people who just
lost their connection. A feed of outage reports has a hole exactly where the
outage is.

So this does not ask anyone. IODA (Georgia Tech) infers reachability from three
INDEPENDENT vantage points that keep working when the region does not:

  bgp           /24 prefixes still announced in the global routing table —
                the network saying it exists
  ping-slash24  /24s actually answering active probes — the network working
  merit-nt      background traffic arriving at a darknet telescope — hosts
                being alive without anyone asking them to be

They fail differently. Routing can stay up while the data plane is dead; probes
can be filtered while traffic continues. Requiring two of three to agree before
declaring an outage is the same copy-collapse discipline used on the Telegram
channels — with the advantage that these three genuinely cannot copy each other.

WEST BANK, NOT "PALESTINE"
IODA separates the two, and the difference is not subtle: West Bank bgp ~3020
and ping-slash24 ~1343, against Gaza ~143 and ~9. Reporting the country
aggregate would let a Gaza blackout appear as a West Bank one, which is the same
error as filing a Gaza raid under a West Bank governorate.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx

from resolve.db import connect

API = "https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw"
# IODA's region code for the West Bank. Gaza Strip is 1226 and is deliberately
# not read here.
WEST_BANK_REGION = "4581"
SOURCE_KEY = "ioda"
STATE_KIND = "internet"
USER_AGENT = "palestine-v2/2.0 (humanitarian data)"

# Fractions of the trailing baseline. An outage has to be severe AND corroborated
# before it is asserted — a false blackout alarm is its own kind of harm.
OUTAGE_RATIO = 0.50
DEGRADED_RATIO = 0.80
MIN_SIGNALS_AGREEING = 2
BASELINE_HOURS = 168      # 7 days, so the baseline spans weekday and weekend
RECENT_POINTS = 4         # ~2h at the 30-min step; one bad sample cannot trip it


def _ensure_source(cur) -> int:
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                            attribution_text,authority_rank)
        VALUES (%s,'IODA (Georgia Tech) internet outage detection','api',
                'CC-BY-NC-4.0',false,
                'Internet measurement by IODA, Georgia Tech',2)
        ON CONFLICT (key) DO NOTHING""", (SOURCE_KEY,))
    cur.execute("SELECT source_id FROM source WHERE key=%s", (SOURCE_KEY,))
    return cur.fetchone()[0]


def fetch_signals() -> dict[str, list[float]]:
    """Numeric series keyed by datasource.

    NOTE the absolute timestamps. IODA accepts a relative form (`from=-86400`)
    and answers 200 with an EMPTY series for it — a silent nothing rather than
    an error, which read as "no data for Palestine" until absolute epochs were
    tried.
    """
    now = int(time.time())
    r = httpx.get(f"{API}/region/{WEST_BANK_REGION}",
                  params={"from": now - BASELINE_HOURS * 3600, "until": now},
                  timeout=60.0, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    groups = r.json().get("data") or [[]]
    out: dict[str, list[float]] = {}
    for s in groups[0]:
        vals = [v for v in (s.get("values") or []) if isinstance(v, (int, float))]
        if len(vals) >= RECENT_POINTS * 2:
            out[s["datasource"]] = vals
    return out


def assess(signals: dict[str, list[float]]) -> tuple[str, dict]:
    """Compare recent level against each signal's own trailing baseline."""
    detail: dict[str, dict] = {}
    outage = degraded = 0
    for ds, vals in signals.items():
        recent = vals[-RECENT_POINTS:]
        baseline_pool = vals[:-RECENT_POINTS] or vals
        baseline = sorted(baseline_pool)[len(baseline_pool) // 2]
        cur_level = sum(recent) / len(recent)
        ratio = (cur_level / baseline) if baseline else 1.0
        detail[ds] = {"baseline": round(baseline, 1),
                      "recent": round(cur_level, 1),
                      "ratio": round(ratio, 3)}
        if ratio < OUTAGE_RATIO:
            outage += 1
        elif ratio < DEGRADED_RATIO:
            degraded += 1

    if outage >= MIN_SIGNALS_AGREEING:
        value = "outage"
    elif outage + degraded >= MIN_SIGNALS_AGREEING:
        value = "degraded"
    else:
        value = "normal"
    return value, detail


def load(dry_run: bool = False) -> dict:
    signals = fetch_signals()
    if not signals:
        return {"signals": 0, "value": None, "detail": {}, "written": 0}
    value, detail = assess(signals)
    stats = {"signals": len(signals), "value": value, "detail": detail, "written": 0}
    if dry_run:
        return stats

    with connect() as conn, conn.cursor() as cur:
        source_id = _ensure_source(cur)
        cur.execute("SELECT place_id FROM place WHERE kind='region' AND name_en='West Bank'")
        row = cur.fetchone()
        if not row:
            stats["error"] = "no West Bank region place"
            return stats
        place_id = row[0]

        cur.execute("""
            INSERT INTO state_observation
              (place_id,state_kind,value,raw_value,observed_at,source_id,confidence,
               direction,direction_explicit,modality,attrs)
            VALUES (%s,%s,%s,NULL,%s,%s,%s,'both',false,'assertion',%s)""",
            (place_id, STATE_KIND, value, datetime.now(timezone.utc), source_id,
             # Corroborated across independent measurement methods, so a
             # two-of-three verdict earns more than a single-source reading.
             0.90 if value != "normal" else 0.85,
             json.dumps({"signals": detail, "region": "West Bank",
                         "method": "IODA bgp/ping-slash24/merit-nt vs 7d baseline"},
                        ensure_ascii=False)))
        stats["written"] = 1

        # Scoped to this kind only — the fuel loader's unscoped rebuild is how
        # checkpoint belief was silently overwritten.
        cur.execute("""
            INSERT INTO state_current
              (place_id,state_kind,direction,value,observed_at,source_id,
               base_confidence,independent_sources,contradicted_by,updated_at)
            SELECT DISTINCT ON (place_id, state_kind)
                   place_id, state_kind, 'both', value, observed_at, source_id,
                   confidence, %s, 0, now()
            FROM state_observation WHERE state_kind = %s
            ORDER BY place_id, state_kind, observed_at DESC
            ON CONFLICT (place_id, state_kind, direction) DO UPDATE SET
              value=EXCLUDED.value, observed_at=EXCLUDED.observed_at,
              source_id=EXCLUDED.source_id, base_confidence=EXCLUDED.base_confidence,
              independent_sources=EXCLUDED.independent_sources, updated_at=now()
            WHERE EXCLUDED.observed_at >= state_current.observed_at""",
            (len(signals), STATE_KIND))
        conn.commit()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = load(a.dry_run)
    if not s["signals"]:
        print("no usable IODA signals returned")
        return 0
    print(f"West Bank internet: {s['value']}  ({s['signals']} independent signals)")
    for ds, d in s["detail"].items():
        flag = "" if d["ratio"] >= DEGRADED_RATIO else "  <-- below baseline"
        print(f"   {ds:<16} baseline {d['baseline']:>10} · now {d['recent']:>10} "
              f"· {d['ratio'] * 100:5.1f}%{flag}")
    if a.dry_run:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
