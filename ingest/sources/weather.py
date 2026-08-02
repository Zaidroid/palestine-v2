"""Weather per governorate, from Open-Meteo — free, no key, no account.

    .venv/bin/python -m ingest.sources.weather
    .venv/bin/python -m ingest.sources.weather --dry-run

WHY NOT THE TELEGRAM WEATHER CHANNELS
That was the plan until the corpus was measured: 978 claims across ten channels
contained ZERO weather advisories, and the live weather channels discovery found
post prose ("أجواء جافة وصافية وارتفاع ملموس على درجات الحرارة") that would need
a parser of its own to produce a number. Open-Meteo returns the same facts as
structured data for any coordinate, so there is nothing to parse, no Telegram
rate-limit exposure, and every governorate gets a value instead of only the ones
a channel mentioned.

WHAT IT IS FOR
Not a weather service — people have those. It is here because weather changes
what the rest of the system's answers MEAN. Forty-two degrees turns a checkpoint
queue from tedious into dangerous; 30mm of rain closes unpaved approaches that
no checkpoint report will mention. The advisory sits beside the movement data so
a bot can say "open, but it is 43 degrees" instead of just "open".

THE READING AND THE JUDGEMENT ARE STORED SEPARATELY
`value` is the advisory band; `attrs` keeps the raw temperature, precipitation
and wind that produced it. Thresholds are opinion (migration 019) and will be
revised — keeping the numbers means a revision can be applied to history rather
than only to new readings.
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

API = "https://api.open-meteo.com/v1/forecast"
SOURCE_KEY = "open_meteo"
STATE_KIND = "weather"
USER_AGENT = "palestine-v2/2.0 (humanitarian data)"

# First band that matches wins, so a 43C day with rain reads as extreme_heat.
#
# A STORM REQUIRES RAIN. The first version fired on gusts alone at 60km/h and
# labelled two dry 34-39C summer days as storms — West Bank hill country
# routinely gusts 35-68km/h on a clear afternoon, so that band caught ordinary
# weather. Worse, it OUTRANKED heat: Tubas at 38.8C with 0mm of rain was
# reported as `storm`, losing the heat-wave warning, which is the fact someone
# queueing at a checkpoint actually needs. Dry wind now has its own band below
# the temperature bands, and never displaces them.
def advisory(tmax: float | None, tmin: float | None,
             precip: float | None, gust: float | None) -> str:
    t_hi, t_lo = tmax if tmax is not None else -99, tmin if tmin is not None else 99
    mm, kmh = precip or 0.0, gust or 0.0
    if t_hi >= 42:
        return "extreme_heat"
    if t_lo <= 0:
        return "frost"
    if mm >= 30 or (mm >= 5 and kmh >= 70):
        return "storm"
    if t_hi >= 38:
        return "heat_wave"
    if t_lo <= 4:
        return "cold"
    if mm >= 10:
        return "rain"
    if kmh >= 70:
        return "high_wind"
    return "normal"


def _ensure_source(cur) -> int:
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                            attribution_text,authority_rank)
        VALUES (%s,'Open-Meteo','api','CC-BY-4.0',true,
                'Weather data by Open-Meteo.com (CC BY 4.0)',2)
        ON CONFLICT (key) DO NOTHING""", (SOURCE_KEY,))
    cur.execute("SELECT source_id FROM source WHERE key=%s", (SOURCE_KEY,))
    return cur.fetchone()[0]


def _targets(cur) -> list[tuple]:
    """West Bank governorates. Gaza is excluded — this system serves West Bank
    movement, and a Gaza advisory here would imply coverage we do not provide."""
    cur.execute("""
        SELECT place_id, name_en, name_ar,
               ST_Y(centroid::geometry), ST_X(centroid::geometry)
        FROM place
        WHERE kind = 'governorate' AND centroid IS NOT NULL
          AND name_en NOT IN ('Gaza','North Gaza','Deir Al-Balah','Khan Younis','Rafah')
        ORDER BY name_en""")
    return cur.fetchall()


def fetch_all(targets: list[tuple]) -> dict[int, dict]:
    """One batched request. Open-Meteo accepts comma-separated coordinates, so
    eleven governorates cost one call rather than eleven."""
    if not targets:
        return {}
    lats = ",".join(f"{t[3]:.4f}" for t in targets)
    lons = ",".join(f"{t[4]:.4f}" for t in targets)
    params = {
        "latitude": lats, "longitude": lons,
        "current": "temperature_2m,wind_speed_10m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max",
        "timezone": "Asia/Hebron", "forecast_days": 2,
    }

    # Retry 5xx, because a free public API returns them and self-heals.
    #
    # Open-Meteo 503'd at 17:30 and again at 18:00 on 2026-08-01 and was fine
    # either side. Before P3.1 that was invisible; afterwards each one raised an
    # alarm. An alerting channel that fires for something which fixes itself in
    # five minutes is one people learn to skim, which costs more than the
    # outages it reports. A transient failure absorbed here is not a failure
    # hidden — if it is still 5xx after three tries it raises, alarms, and
    # means something.
    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(2 ** attempt)          # 2s, 4s
        try:
            r = httpx.get(API, timeout=30.0,
                          headers={"User-Agent": USER_AGENT}, params=params)
            r.raise_for_status()
            break
        except httpx.HTTPStatusError as exc:
            # 4xx is our fault — a bad request will not fix itself, and retrying
            # it just hammers somebody's free API.
            if exc.response.status_code < 500:
                raise
            last = exc
            print(f"  open-meteo {exc.response.status_code}, retry {attempt + 1}/3")
        except httpx.RequestError as exc:
            last = exc
            print(f"  open-meteo unreachable ({exc}), retry {attempt + 1}/3")
    else:
        raise last
    payload = r.json()
    # A single coordinate returns an object; several return a list. Normalising
    # here keeps the caller from having to know which case it is in.
    blocks = payload if isinstance(payload, list) else [payload]
    return {targets[i][0]: b for i, b in enumerate(blocks) if i < len(targets)}


def load(dry_run: bool = False) -> dict:
    stats = {"governorates": 0, "written": 0, "advisories": {}}
    with connect() as conn, conn.cursor() as cur:
        source_id = _ensure_source(cur)
        targets = _targets(cur)
        stats["governorates"] = len(targets)
        blocks = fetch_all(targets)
        observed = datetime.now(timezone.utc)
        rows = []

        for place_id, name_en, name_ar, lat, lon in targets:
            b = blocks.get(place_id)
            if not b:
                continue
            daily = b.get("daily") or {}
            cur_block = b.get("current") or {}

            def day(key, idx=0):
                vals = daily.get(key) or []
                return vals[idx] if len(vals) > idx else None

            tmax, tmin = day("temperature_2m_max"), day("temperature_2m_min")
            precip, gust = day("precipitation_sum"), day("wind_gusts_10m_max")
            value = advisory(tmax, tmin, precip, gust)
            stats["advisories"][value] = stats["advisories"].get(value, 0) + 1

            rows.append((place_id, STATE_KIND, value, None, observed, source_id, 0.95,
                         "both", False, "assertion",
                         json.dumps({
                             "governorate": name_en,
                             "temp_now_c": cur_block.get("temperature_2m"),
                             "wind_now_kmh": cur_block.get("wind_speed_10m"),
                             "today": {"max_c": tmax, "min_c": tmin,
                                       "precip_mm": precip, "gust_kmh": gust},
                             "tomorrow": {"max_c": day("temperature_2m_max", 1),
                                          "min_c": day("temperature_2m_min", 1),
                                          "precip_mm": day("precipitation_sum", 1),
                                          "gust_kmh": day("wind_gusts_10m_max", 1),
                                          "advisory": advisory(
                                              day("temperature_2m_max", 1),
                                              day("temperature_2m_min", 1),
                                              day("precipitation_sum", 1),
                                              day("wind_gusts_10m_max", 1))},
                         }, ensure_ascii=False)))

        if dry_run or not rows:
            return stats

        cur.executemany("""
            INSERT INTO state_observation
              (place_id,state_kind,value,raw_value,observed_at,source_id,confidence,
               direction,direction_explicit,modality,attrs)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
        stats["written"] = len(rows)

        # Scoped to weather only — the fuel loader's habit of rebuilding every
        # kind is how checkpoint belief got silently overwritten.
        cur.execute("""
            INSERT INTO state_current
              (place_id,state_kind,direction,value,observed_at,source_id,
               base_confidence,independent_sources,contradicted_by,updated_at)
            SELECT DISTINCT ON (place_id, state_kind)
                   place_id, state_kind, 'both', value, observed_at, source_id,
                   confidence, 1, 0, now()
            FROM state_observation WHERE state_kind = %s
            ORDER BY place_id, state_kind, observed_at DESC
            ON CONFLICT (place_id, state_kind, direction) DO UPDATE SET
              value=EXCLUDED.value, observed_at=EXCLUDED.observed_at,
              source_id=EXCLUDED.source_id, base_confidence=EXCLUDED.base_confidence,
              updated_at=now()
            WHERE EXCLUDED.observed_at >= state_current.observed_at""", (STATE_KIND,))
        conn.commit()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = load(a.dry_run)
    print(f"{s['governorates']} governorates · wrote {s['written']} observations")
    if s["advisories"]:
        print("  " + " · ".join(f"{k}:{v}" for k, v in
                                sorted(s["advisories"].items(), key=lambda kv: -kv[1])))
    if a.dry_run:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
