"""Satellite thermal anomalies (NASA FIRMS) — physical evidence for a claim.

    .venv/bin/python -m ingest.sources.fires --dry-run
    .venv/bin/python -m ingest.sources.fires

Needs FIRMS_MAP_KEY in .env (free, issued instantly at
https://firms.modaps.eosdis.nasa.gov/api/map_key/).

WHAT THIS IS FOR — AND WHAT IT IS NOT
A VIIRS thermal anomaly says "something at this coordinate was hot at this
time". That is all it says. Agricultural stubble burning is routine and
seasonal across the West Bank, so a fire detection is NOT evidence of arson and
this module never labels one as an attack.

Its value is CORROBORATION, and specifically corroboration of a kind nothing
else in this system can provide. Every other source is a human writing a
sentence: the Telegram channels, the RSS wires, even the checkpoint parser.
They can all be wrong the same way, and nine of the road channels demonstrably
are. A satellite is a different KIND of witness — it cannot repost, cannot
misread Arabic, and has no view about who lit the fire. When a report of
"مستوطنون يحرقون أراضٍ زراعية جنوب نابلس" lands within a few kilometres and a
few hours of an independent thermal detection, that agreement is worth more
than a second channel saying the same words.

So detections are stored as their own events and LINKED to matching incident
reports. The link raises confidence in the report; it never creates a report.

DIRECTION OF ERROR
Matching is deliberately tight (radius and time window below). A missed link
costs nothing — both records still stand alone. A false link would attach
physical evidence to the wrong claim, which is worse than having no evidence at
all, so the thresholds err toward missing.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx

from resolve.db import connect

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SOURCE_KEY = "nasa_firms"
USER_AGENT = "palestine-v2/2.0 (humanitarian data)"

# West Bank bounding box: west,south,east,north. Gaza is excluded on purpose —
# this system serves West Bank movement, and Gaza fire activity has entirely
# different causes that would pollute any corroboration signal.
BBOX = "34.85,31.30,35.60,32.60"
# Two polar-orbiting sensors, ~12h apart. Independent instruments, so a
# detection seen by both is stronger than one seen by either.
SENSORS = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT")
DAY_RANGE = 2

# Corroboration window. 3km is about the imprecision of a village centroid plus
# VIIRS's 375m pixel; 6h covers a report filed after the fact and the gap
# between satellite passes.
MATCH_RADIUS_KM = 3.0
MATCH_WINDOW_HOURS = 6

# THE PLACE MUST BE PRECISE ENOUGH TO MATCH AGAINST.
#
# "مستوطنون يحرقون أراضٍ زراعية جنوب نابلس" ("settlers burn farmland SOUTH OF
# Nablus") names no village, so the event sits on the Nablus centroid. A
# detection 7.5km away is entirely consistent with that report — and equally
# consistent with a dozen others, and with ordinary stubble burning. The time
# agreement was excellent (0.7h) and it is still not evidence, because the
# report never said where.
#
# Widening the radius to catch it would let any fire in the governorate
# corroborate any burning report in the governorate. So instead of a looser
# distance, the requirement is a tighter PLACE: only localities and finer.
# Same rule as refusing to quote a drive time to a station known only to its
# governorate — the imprecision does not disappear by being ignored.
PRECISE_PLACE_KINDS = ("locality", "checkpoint", "crossing", "road", "station")

# THE REPORT ITSELF MUST DESCRIBE A FIRE.
#
# Matching on event_type alone produced four false links on the first real run,
# all to ONE detection 4.3km from Al-Junaid, and all to incidents with no
# thermal signature whatsoever:
#     مستوطنون يعتدون على قبر الشهيد        desecrating a grave
#     المستوطنون يحطمون شواهد أضرحة          smashing gravestones
#     هجوم المستوطنين وسط إطلاق نار          an attack with gunfire
# Smashing a headstone does not get hot. `settler_attack` covers arson, stone
# throwing, tree uprooting and cemetery vandalism alike, so the type says
# nothing about whether anything burned — and stubble burning is routine here,
# so a nearby fire at a similar hour is the expected background, not evidence.
#
# The honest join is therefore: the satellite confirms a fire that a human
# SAID happened. Anything looser is coincidence wearing the costume of proof,
# and it inflated three events to 0.97 confidence before this was caught.
CORROBORATABLE = ("settler_attack", "demolition", "shooting", "raid")

BURNING_TERMS = re.compile(
    r"(حرق|احرق|أحرق|يحرق|تحرق|حريق|اضرم|أضرم|اشعل|أشعل|نيران|النار|"
    r"محترق|احتراق|إحراق|حرائق)")


def _key() -> str | None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("FIRMS_MAP_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("FIRMS_MAP_KEY")


def fetch(sensor: str, key: str) -> list[dict]:
    r = httpx.get(f"{API}/{key}/{sensor}/{BBOX}/{DAY_RANGE}",
                  timeout=60.0, headers={"User-Agent": USER_AGENT})
    if r.status_code != 200 or "Invalid MAP_KEY" in r.text[:60]:
        raise RuntimeError(f"{sensor}: HTTP {r.status_code} {r.text[:80]}")
    body = r.text.strip()
    if not body or body.lower().startswith("no fire"):
        return []
    return list(csv.DictReader(io.StringIO(body)))


def _observed(row: dict) -> datetime | None:
    """FIRMS gives acq_date (YYYY-MM-DD) and acq_time as HHMM, in UTC."""
    try:
        d = row["acq_date"].strip()
        t = row["acq_time"].strip().zfill(4)
        return datetime.strptime(f"{d} {t}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None


def _ensure_source(cur) -> int:
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                            attribution_text,authority_rank)
        VALUES (%s,'NASA FIRMS (VIIRS active fire)','satellite','CC0-1.0',true,
                'NASA FIRMS — VIIRS active fire data, NASA/LANCE',1)
        ON CONFLICT (key) DO NOTHING""", (SOURCE_KEY,))
    cur.execute("SELECT source_id FROM source WHERE key=%s", (SOURCE_KEY,))
    return cur.fetchone()[0]


LINK_SQL = f"""
-- One fire corroborates at most ONE report: `linked` is now actually SET, so a
-- single detection cannot be counted several times over. On the first run one
-- fire raised the confidence of four separate events, which is one piece of
-- evidence pretending to be four.
WITH pair AS (
  SELECT DISTINCT ON (f.event_id) f.event_id AS fire_id, e.event_id AS inc_id
  FROM event f
  JOIN event e
    ON e.event_type = ANY(%(kinds)s)
   AND e.event_id <> f.event_id
   AND e.attrs->>'corroborating_fire' IS NULL
   AND ST_DWithin(e.geom, f.geom, %(radius_m)s)
   AND f.occurred_at BETWEEN e.occurred_at - INTERVAL '{MATCH_WINDOW_HOURS} hours'
                         AND e.occurred_at + INTERVAL '{MATCH_WINDOW_HOURS} hours'
  -- The report has to describe burning. See BURNING_TERMS for why the event
  -- type alone is not enough.
   AND EXISTS (SELECT 1 FROM claim c
               WHERE c.event_id = e.event_id AND c.raw_text ~ %(burning)s)
   -- A governorate-centroid event is too coarse to corroborate against.
   AND EXISTS (SELECT 1 FROM place pl
               WHERE pl.place_id = e.place_id AND pl.kind::text = ANY(%(kinds_place)s))
  WHERE f.event_type = 'fire_detection'
    AND f.attrs->>'linked' IS NULL
  ORDER BY f.event_id, ST_Distance(e.geom, f.geom)
),
mark AS (
  UPDATE event f SET attrs = jsonb_set(f.attrs,'{{linked}}', to_jsonb(p.inc_id), true)
  FROM pair p WHERE f.event_id = p.fire_id RETURNING f.event_id
)
UPDATE event e
SET independent_sources = e.independent_sources + 1,
    confidence = LEAST(0.97, 1 - (1 - e.confidence) * 0.30),
    attrs = jsonb_set(e.attrs, '{{corroborating_fire}}', to_jsonb(p.fire_id), true)
FROM pair p
WHERE e.event_id = p.inc_id
RETURNING e.event_id, p.fire_id
"""


def load(dry_run: bool = False) -> dict:
    key = _key()
    stats: dict = {"key": bool(key), "detections": 0, "written": 0,
                   "linked": 0, "errors": [], "sensors": {}}
    if not key:
        stats["errors"].append(
            "FIRMS_MAP_KEY not set — get one free at "
            "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and add it to .env")
        return stats

    rows: list[tuple[str, dict]] = []
    for sensor in SENSORS:
        try:
            got = fetch(sensor, key)
        except Exception as exc:                           # noqa: BLE001
            stats["errors"].append(str(exc))
            continue
        stats["sensors"][sensor] = len(got)
        rows.extend((sensor, r) for r in got)
    stats["detections"] = len(rows)
    if not rows or dry_run:
        return stats

    with connect() as conn, conn.cursor() as cur:
        source_id = _ensure_source(cur)
        for sensor, r in rows:
            when = _observed(r)
            if not when:
                continue
            try:
                lat, lon = float(r["latitude"]), float(r["longitude"])
            except (KeyError, ValueError):
                continue
            ext = f"{sensor}:{r.get('acq_date')}:{r.get('acq_time')}:{lat:.5f}:{lon:.5f}"
            # Idempotent on re-run: the same pass is fetched repeatedly within
            # the 2-day window.
            cur.execute("""SELECT 1 FROM event
                           WHERE event_type='fire_detection' AND attrs->>'ext_id'=%s""",
                        (ext,))
            if cur.fetchone():
                continue
            cur.execute("""
                INSERT INTO event (event_type, geom, occurred_at, occurred_precision,
                                   status, confidence, claim_count, independent_sources, attrs)
                VALUES ('fire_detection',
                        ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                        %s,'exact','believed',%s,0,1,%s)""",
                (lon, lat, when,
                 # FIRMS' own confidence class, carried through rather than
                 # replaced by a number of our own invention.
                 {"h": 0.9, "n": 0.7, "l": 0.4}.get(
                     str(r.get("confidence", "n")).lower()[:1], 0.7),
                 json.dumps({"ext_id": ext, "sensor": sensor,
                             "firms_confidence": r.get("confidence"),
                             "frp_mw": r.get("frp"), "brightness_k": r.get("bright_ti4"),
                             "daynight": r.get("daynight"),
                             "classifier": "firms"}, ensure_ascii=False)))
            stats["written"] += 1

        cur.execute(LINK_SQL, {"kinds": list(CORROBORATABLE),
                               "radius_m": MATCH_RADIUS_KM * 1000,
                               "burning": BURNING_TERMS.pattern,
                               "kinds_place": list(PRECISE_PLACE_KINDS)})
        stats["linked"] = len(cur.fetchall())
        conn.commit()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = load(a.dry_run)
    if not s["key"]:
        print(s["errors"][0])
        return 1
    print(f"{s['detections']} thermal detections over the West Bank "
          f"({', '.join(f'{k}:{v}' for k, v in s['sensors'].items()) or 'none'})")
    print(f"  wrote {s['written']} new · linked {s['linked']} to existing incident reports")
    for e in s["errors"]:
        print(f"  ERROR {e}")
    if a.dry_run:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
