"""P1.8 — load palhubappfuel sweeps into v2 state tables.

Reads the tee spool, parses sweeps, resolves each station to the best available
place, and writes `state_observation` (+ `state_current`).

GEO PRECISION LADDER — never drop a station for want of coordinates, and never
pretend to precision we do not have:

    1. OSM station name match  -> precision 'station'  (real coordinates)
    2. "(locality)" suffix     -> precision 'town'     (locality centroid)
    3. region header           -> precision 'admin2'   (always present)

Measured on the first 200 stations: 17% match an OSM station, 48% a locality,
the rest fall back to region. Every station lands somewhere, and the precision
is recorded so the serving layer can rank a station-precise answer above a
region-precise one instead of treating them as equal.

Stations palhub knows and OSM does not are CREATED as places — palhub is the
authoritative list of which fuel stations exist; OSM merely has coordinates for
some of them.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cascade.palhub_fuel import parse_spool
from resolve.arabic import is_generic_alias, variants
from resolve.db import connect
from resolve.belief import refresh as belief_refresh
from resolve.geo import resolve_place

# The kinds this loader owns, named so the belief refresh can be scoped to them.
FUEL_KINDS = ("fuel_diesel", "fuel_gasoline", "cooking_gas")

SPOOL_DIR = Path("/opt/stacks/palestine/services/westbank-alerts/data/tee")
SOURCE_KEY = "telegram_fuel"

# palhub splits some governorates into towns (دورا, يطا, بيتونيا), so a region
# is resolved as a place rather than assumed to be an admin2.
_region_cache: dict[str, tuple | None] = {}


def _ensure_source(cur) -> int:
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,attribution_text,
                            authority_rank,independence_group)
        VALUES (%s,'Palhub - احوال الوقود (Telegram)','telegram','NONE',false,
                'Palhub fuel status channel',5,'palhub')
        ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name
        RETURNING source_id""", (SOURCE_KEY,))
    return cur.fetchone()[0]


def _resolve_station(cur, conn, name: str, locality: str | None, region: str):
    """Return (place_id, precision, how). Creates a place when palhub knows a
    station OSM does not."""
    # 1 — an actual station in the gazetteer
    r = resolve_place(name, {"prefer_kind": "station"}, conn=conn, learn=False)
    if r and r.kind == "station" and r.confidence >= 0.65:
        return r.place_id, "station", "osm_station"

    # 2 / 3 — anchor geometry on the locality, else the region
    anchor = None
    if locality:
        a = resolve_place(locality, conn=conn, learn=False)
        if a:
            anchor, precision, how = a, "town", "locality"
    if anchor is None:
        if region not in _region_cache:
            _region_cache[region] = resolve_place(region, conn=conn, learn=False)
        a = _region_cache[region]
        if a:
            anchor, precision, how = a, "admin2", "region"
    if anchor is None:
        return None, "unknown", "unresolved"

    # Create the station as a first-class place at the anchor's centroid.
    cur.execute("""
        SELECT place_id FROM place
        WHERE kind='station' AND source_refs->>'palhub_name' = %s""", (name,))
    row = cur.fetchone()
    if row:
        return row[0], precision, how

    cur.execute("""
        INSERT INTO place (kind,name_ar,admin1_pcode,admin2_pcode,geom,source_refs,confidence,attrs)
        SELECT 'station', %s, p.admin1_pcode, p.admin2_pcode,
               (p.centroid)::geometry, %s, %s, %s
        FROM place p WHERE p.place_id = %s
        RETURNING place_id""",
        (name,
         json.dumps({"palhub_name": name, "palhub_locality": locality,
                     "palhub_region": region, "source": "palhub",
                     "geo_anchor_place_id": anchor.place_id, "geo_basis": how}),
         0.8 if how == "locality" else 0.5,
         json.dumps({"geo_precision": precision}),
         anchor.place_id))
    pid = cur.fetchone()[0]

    for key in variants(name):
        if key and len(key) >= 2 and not is_generic_alias(key):
            cur.execute("""
                INSERT INTO place_alias (alias_norm, place_id, confidence, origin)
                VALUES (%s,%s,0.8,'observed') ON CONFLICT (alias_norm) DO NOTHING""",
                        (key, pid))
    return pid, precision, how


#. A torn line is tolerated; a torn SPOOL is not. 2026-08-08: the host lost
#  power mid-write and v1's spool gained one NUL-padded line — 1 of 40,014 —
#  which crashed json.loads and took the whole fuel vertical down for hours.
#  One unreadable line must not silence a live feed, and a spool that is
#  mostly unreadable must not be quietly half-ingested either.
MAX_MALFORMED_FRACTION = 0.01


def load(spool_files=None) -> dict:
    files = spool_files or sorted(SPOOL_DIR.glob("*.ndjson"))
    rows = []
    malformed: list[str] = []
    for f in files:
        # errors="replace": a torn write can also leave invalid UTF-8, and
        # failing to DECODE the file would lose every good line in it
        for i, line in enumerate(
                Path(f).read_text(encoding="utf-8",
                                  errors="replace").splitlines(), 1):
            if not line.strip() or not line.strip("\x00"):
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                malformed.append(f"{Path(f).name}:{i}")

    if malformed and len(malformed) > MAX_MALFORMED_FRACTION * max(
            len(rows) + len(malformed), 1):
        raise RuntimeError(
            f"palhub spool is {len(malformed)}/{len(rows) + len(malformed)} "
            f"unreadable — that is corruption, not a torn write. "
            f"First: {malformed[:3]}")

    sweeps = parse_spool(rows)
    stats = {"sweeps": len(sweeps), "readings": 0, "observations": 0,
             "stations_created": 0, "unresolved": 0,
             # counted by reason, never silently swallowed (law 4): a torn
             # line is survivable but it is still a fact about the feed
             "malformed_lines": len(malformed),
             "malformed_at": malformed[:5],
             "by_precision": {}, "by_how": {}}
    if not sweeps:
        return stats

    with connect() as conn, conn.cursor() as cur:
        source_id = _ensure_source(cur)
        cur.execute("SELECT COUNT(*) FROM place WHERE kind='station'")
        before = cur.fetchone()[0]

        # The spool is append-only and this reads all of it every run, so
        # without a cursor every sweep is re-inserted on every 5-minute tick.
        # It was: 774,374 fuel rows for 11,765 real observations, 98.48% exact
        # duplicates, one observation stored 490 times. See migration 023.
        cur.execute("SELECT external_id FROM ingest_seen WHERE source_id=%s",
                    (source_id,))
        seen: set[str] = {r[0] for r in cur.fetchall()}
        stats["skipped_seen"] = 0

        resolved: dict[tuple, tuple] = {}
        now_utc = datetime.now(timezone.utc)
        for sw in sweeps:
            # A sweep with no msg_id cannot be deduped, so it is still
            # processed — under-collecting is worse than a rare repeat.
            msg_id = getattr(sw, "msg_id", None)
            if msg_id is not None and str(msg_id) in seen:
                stats["skipped_seen"] += 1
                continue
            # observed_at comes from the TELEGRAM message date, which is UTC and
            # authoritative. The "آخر تحديث" stamp inside the message is
            # channel-LOCAL (UTC+3) with no offset; treating it as UTC put every
            # observation ~3h in the future, pinning confidence at 1.0 and
            # producing age_minutes = -177. Same class of bug as v1's negative
            # freshness. The local stamp is kept as provenance only.
            observed = None
            msg_date = getattr(sw, "msg_date", None)
            if msg_date:
                try:
                    observed = datetime.fromisoformat(msg_date.replace("Z", "+00:00"))
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                except ValueError:
                    observed = None
            if observed is None:
                observed = now_utc
            # Guard: an observation can never be in the future. If a source ever
            # claims one, clamp and keep the claim visible in attrs.
            future_skew_s = (observed - now_utc).total_seconds()
            if future_skew_s > 60:
                observed = now_utc
            else:
                future_skew_s = 0
            for rd in sw.readings:
                stats["readings"] += 1
                key = (rd.station_name, rd.locality, rd.region)
                if key not in resolved:
                    resolved[key] = _resolve_station(cur, conn, *key)
                place_id, precision, how = resolved[key]
                stats["by_precision"][precision] = stats["by_precision"].get(precision, 0) + 1
                stats["by_how"][how] = stats["by_how"].get(how, 0) + 1
                if place_id is None:
                    stats["unresolved"] += 1
                    continue

                cur.execute("""
                    INSERT INTO state_observation
                        (place_id,state_kind,value,raw_value,observed_at,source_id,confidence,attrs)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (place_id, rd.state_kind, rd.value, rd.raw_value, observed, source_id,
                     0.95,
                     json.dumps({"region": rd.region, "locality": rd.locality,
                                 "station_raw": rd.station_raw,
                                 "geo_precision": precision, "geo_basis": how,
                                 "msg_id": msg_id,
                                 "palhub_stamp_local": sw.updated_raw,
                                 "future_skew_clamped_s": future_skew_s or None})))
                stats["observations"] += 1

            # Marked only after every reading in the sweep is written, and
            # committed in the same transaction — a crash mid-sweep must leave
            # it unmarked so the next run finishes it rather than skipping it.
            if msg_id is not None:
                cur.execute("""INSERT INTO ingest_seen (source_id, external_id)
                               VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                            (source_id, str(msg_id)))
                seen.add(str(msg_id))

        # Belief for fuel is resolve/belief.py — the same model that serves
        # checkpoints, rather than a second one living here.
        #
        # SCOPED TO FUEL, as it always was: without the scope this would
        # recompute EVERY kind and a fuel ingest would overwrite checkpoint
        # belief. The two feeds share a table and must not write outside their
        # own rows.
        #
        # What used to be here was `SELECT DISTINCT ON (place_id, state_kind)`
        # with `independent_sources=1, contradicted_by=0` hardcoded and the
        # PARSE confidence used as the belief confidence — a flat 0.95 on every
        # fuel row in the database, asserted for a single unverified reading
        # while an identical checkpoint reading said 0.85 and meant it.
        #
        # It also had NO modality filter, which stopped being untidy and became
        # dangerous the moment crowd reporting arrived: one crowd report —
        # including one the engine had already refused and marked
        # `rate_limited` — would have overwritten belief at full confidence,
        # past corroboration, past earned trust and past the P2.4 gate, on the
        # vertical where crowd reports were already turning up.
        #
        # Fuel is still one independence unit, so its confidence becomes 0.85
        # rather than 0.95. That is a smaller number meaning more: 0.85 is
        # measured, 0.95 was a parser's confidence in its own regex wearing a
        # belief's clothing.
        belief_refresh(FUEL_KINDS, conn=conn)

        cur.execute("SELECT COUNT(*) FROM place WHERE kind='station'")
        stats["stations_created"] = cur.fetchone()[0] - before
        conn.commit()
    return stats


if __name__ == "__main__":
    s = load()
    print(f"sweeps            {s['sweeps']}")
    print(f"readings          {s['readings']}")
    print(f"observations      {s['observations']}")
    print(f"stations created  {s['stations_created']}")
    print(f"unresolved        {s['unresolved']}")
    print(f"by precision      {s['by_precision']}")
    print(f"by basis          {s['by_how']}")
