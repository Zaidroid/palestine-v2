"""Checkpoint state — v1's parsed updates, re-read and re-attributed for v2.

    .venv/bin/python -m ingest.sources.checkpoints              # incremental
    .venv/bin/python -m ingest.sources.checkpoints --full       # from scratch
    .venv/bin/python -m ingest.sources.checkpoints --state-only # refresh belief
    .venv/bin/python -m ingest.sources.checkpoints --cadence    # cadence only

v1 keeps parsing new checkpoint reports every few seconds and its place matcher
is the part of v1 that genuinely works, so v2 consumes its output rather than
reimplementing 2,564 lines of hand-tuned Arabic. What v2 does NOT reuse is
v1's reading of the status text: `raw_line` is re-parsed here by
cascade.checkpoint_text, which separates questions from reports, binds status
to direction per clause, and keeps flow and presence on separate axes. See that
module for the measurements behind each of those.

WHAT GETS WRITTEN, AND WHY TWICE
  checkpoint_status   one row per v1 update, carrying V1'S verdict, for every
                      update including questions and unreadable lines. This is
                      the complete archival record — nothing v1 saw is dropped,
                      and keeping v1's own value is what makes the two readings
                      comparable later.
  checkpoint_flow     the re-parsed throughput, assertions only.
  checkpoint_idf / _police / _settlers / _inspection
                      presence, assertions only, one kind each so a patrol
                      sighting decays on its own clock instead of erasing the
                      answer to "can I get through?".

ATTRIBUTION IS PER CHANNEL
Every observation used to be credited to one synthetic source, which made
`independent_sources` a constant 1 and corroboration inert. Each report is now
attributed to the channel that filed it, and confidence comes from how many
INDEPENDENT channel groups agree — see learn/source_independence.py, because
seven of these channels are copies of each other and agree 99.5–100% of the
time.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cascade.checkpoint_text import FLOW_SEVERITY, read
from resolve.belief import refresh as belief_refresh
from resolve.db import connect

V1_DB = "/opt/stacks/palestine/services/westbank-alerts/data/checkpoints.db"
LEGACY_KIND = "checkpoint_status"
FLOW_KIND = "checkpoint_flow"
PRESENCE_KIND = {"idf": "checkpoint_idf", "police": "checkpoint_police",
                 "settlers": "checkpoint_settlers", "inspection": "checkpoint_inspection"}
ALL_KINDS = (FLOW_KIND, *PRESENCE_KIND.values())

# Half-life = this multiple of a place's own median reporting gap. 1.5 keeps a
# place confident across one missed report and decays quickly after two.
HALF_LIFE_FACTOR = 1.5
HALF_LIFE_MIN = 900       # 15 min — never decay faster than this
HALF_LIFE_MAX = 43200     # 12 h  — never keep a reading alive longer than this

# Corroboration window, single-unit trust and the confidence ceiling now live
# in resolve/belief.py, which is the ONE implementation of "what do we believe".
# They are re-exported here because this module was their home and
# learn/accuracy.py imports SINGLE_SOURCE_TRUST from it deliberately, so that
# the backtest can never describe a system that is not running. Re-exporting
# keeps that import working while leaving exactly one definition.
from resolve.belief import (CORROBORATION_WINDOW, MAX_CONFIDENCE,  # noqa: E402,F401
                            SINGLE_SOURCE_TRUST)


def _ro():
    return sqlite3.connect(f"file:{V1_DB}?mode=ro", uri=True)


def _channel_sources(cur) -> dict[str, int]:
    """channel name -> source_id, creating any channel not yet registered."""
    cur.execute("SELECT key, source_id FROM source WHERE key LIKE 'tg\\_%'")
    known = {k[3:]: sid for k, sid in cur.fetchall()}
    return known


def _ensure_channel(cur, channel: str, cache: dict[str, int]) -> int:
    ch = channel.lower()
    if ch in cache:
        return cache[ch]
    cur.execute("""
        INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                            attribution_text,authority_rank)
        VALUES (%s,%s,'telegram','NONE',false,%s,4)
        ON CONFLICT (key) DO NOTHING""",
        (f"tg_{ch}", f"Telegram @{channel}", f"Telegram channel @{channel}"))
    cur.execute("SELECT source_id FROM source WHERE key=%s", (f"tg_{ch}",))
    cache[ch] = cur.fetchone()[0]
    return cache[ch]


def _place_map(cur) -> dict[str, int]:
    """v1 canonical_key -> CANONICAL place_id (following any merge)."""
    cur.execute("""
        SELECT source_refs->>'v1_canonical_key' AS k,
               COALESCE(merged_into, place_id)  AS pid
        FROM place
        WHERE source_refs ? 'v1_canonical_key'
          AND kind IN ('checkpoint','crossing','road')""")
    return {k: pid for k, pid in cur.fetchall() if k}


# THE CURSOR IS THIS IMPORTER'S OWN NEWEST ROW (audit F007). It was
# MAX(observed_at) over every checkpoint_status row, and the crowd writes that
# kind with now(): one crowd report moved the cursor past v1 rows not yet
# imported, and they were skipped forever. Scoped to the canonical_key marker
# only this importer writes (the same scope --full deletes by).
CURSOR_SQL = """SELECT MAX(observed_at) FROM state_observation
                 WHERE state_kind = %s AND attrs ? 'canonical_key'"""

# v1 does not insert in message-date order across channels — a catch-up after
# an outage writes messages dated hours earlier than rows already imported —
# so a strict `timestamp > cursor` lost them. v1 is re-read OVERLAP behind the
# cursor and a row already imported is recognised by its v1 identity and
# skipped. 12 h covers the 8-hour outage the ledger records; a longer one is
# what `--full` is for.
OVERLAP = timedelta(hours=12)
SEEN_SQL = """SELECT attrs->>'channel', attrs->>'msg_id', attrs->>'canonical_key',
                     attrs->>'v1_direction', attrs->>'raw_line', observed_at
                FROM state_observation
               WHERE state_kind = %s AND attrs ? 'canonical_key' AND observed_at >= %s"""


def _legacy_attrs(channel, msg_id, key, raw_line, v1status, v1dir) -> dict:
    return {"channel": channel, "msg_id": msg_id, "canonical_key": key,
            "raw_line": (raw_line or "")[:300], "v1_status": v1status,
            "v1_direction": v1dir or None}


def _v1_identity(channel, msg_id, key, v1dir, raw_line, observed) -> tuple:
    """One v1 row, as the archival row stores it (see SEEN_SQL)."""
    return (channel, None if msg_id is None else str(msg_id), key,
            v1dir or None, (raw_line or "")[:300], observed)


def import_updates(full: bool = False) -> dict:
    stats = {"read": 0, "legacy": 0, "flow": 0, "presence": 0, "absence": 0,
             "questions": 0, "unparsed": 0, "skipped_no_place": 0, "already_imported": 0,
             "unmatched_keys": set()}
    rows: list[tuple] = []

    with connect() as conn, conn.cursor() as cur:
        # Serialize against belief refreshes and other imports. Without this,
        # a --full rebuild raced the 5-minute timer: the timer's refresh read
        # a pre-rebuild snapshot, queued behind the rebuild's locks, and wrote
        # old-parse beliefs AFTER the clean refresh — which the observed_at
        # guard then defended against correction. See resolve/belief.py.
        from resolve.belief import BELIEF_LOCK_SQL
        cur.execute(BELIEF_LOCK_SQL)
        places = _place_map(cur)
        cache = _channel_sources(cur)

        if full:
            # Rebuild from v1, which is the source of truth and is untouched by
            # this. Not data loss: every row is reconstructed below, with
            # correct attribution and modality that the old import lacked.
            #
            # Scoped to THIS importer's rows — the ones carrying its
            # canonical_key marker. The palhub roads cascade writes 26k
            # quarantined observations into the same state kinds, and an
            # unscoped delete would have taken them out with nothing here to
            # rebuild them: deleting by kind alone assumes one writer per
            # kind, and that stopped being true at P6.
            cur.execute("DELETE FROM state_current WHERE state_kind = ANY(%s)",
                        (list((LEGACY_KIND, *ALL_KINDS)),))
            cur.execute("""DELETE FROM state_observation
                           WHERE state_kind = ANY(%s) AND attrs ? 'canonical_key'""",
                        (list((LEGACY_KIND, *ALL_KINDS)),))
            since = None
        else:
            cur.execute(CURSOR_SQL, (LEGACY_KIND,))
            since = cur.fetchone()[0]
        seen: set[tuple] = set()
        if since:
            since = since - OVERLAP
            cur.execute(SEEN_SQL, (LEGACY_KIND, since))
            seen = {tuple(r) for r in cur.fetchall()}

        db = _ro()
        sql = ("SELECT canonical_key,status,status_raw,direction,source_channel,"
               "source_msg_id,timestamp,raw_line FROM checkpoint_updates")
        params: tuple = ()
        if since:
            sql += " WHERE timestamp > ?"
            params = (since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),)
        sql += " ORDER BY timestamp"

        for (key, v1status, status_raw, v1dir, channel, msg_id, ts, raw_line) in db.execute(sql, params):
            stats["read"] += 1
            pid = places.get(key)
            if not pid:
                stats["unmatched_keys"].add(key)
                stats["skipped_no_place"] += 1
                continue
            try:
                observed = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if _v1_identity(channel, msg_id, key, v1dir, raw_line, observed) in seen:
                stats["already_imported"] += 1
                continue

            source_id = _ensure_channel(cur, channel or "unknown", cache)
            r = read(raw_line)
            attrs = _legacy_attrs(channel, msg_id, key, raw_line, v1status, v1dir)

            # 1. Archival row — v1's own verdict, every update, no exceptions.
            rows.append((pid, LEGACY_KIND, v1status, status_raw, observed, source_id,
                         0.85, (v1dir or "").strip() or "both", bool((v1dir or "").strip()),
                         r.modality, json.dumps(attrs, ensure_ascii=False)))
            stats["legacy"] += 1
            if r.modality == "question":
                stats["questions"] += 1
                continue
            if r.modality == "unparsed":
                stats["unparsed"] += 1
                continue

            # 2. Re-parsed facts, one row per (direction, axis, value).
            for f in r.facts:
                kind = FLOW_KIND if f.axis == "flow" else PRESENCE_KIND.get(f.value)
                if not kind:
                    continue
                # `absence` shares the presence state_kind and carries the
                # opposite value, so "no army here" can contradict "army here"
                # through the ordinary corroboration path instead of needing a
                # rule of its own.
                value = (f.value if f.axis == "flow"
                         else "absent" if f.axis == "absence" else "present")
                fa = dict(attrs, clause=f.clause, axis=f.axis)
                rows.append((pid, kind, value, raw_line and raw_line[:200], observed,
                             source_id, f.confidence, f.direction, f.direction_explicit,
                             "assertion", json.dumps(fa, ensure_ascii=False)))
                stats["flow" if f.axis == "flow"
                      else "absence" if f.axis == "absence" else "presence"] += 1

            if len(rows) >= 5000:
                _flush(cur, rows)
        db.close()
        _flush(cur, rows)
        conn.commit()

    stats["unmatched_keys"] = sorted(stats["unmatched_keys"])[:10]
    return stats


def _flush(cur, rows: list[tuple]) -> None:
    if not rows:
        return
    cur.executemany("""
        INSERT INTO state_observation
          (place_id,state_kind,value,raw_value,observed_at,source_id,confidence,
           direction,direction_explicit,modality,attrs)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
    rows.clear()


# ── belief ───────────────────────────────────────────────────────────────────

def refresh_state() -> dict:
    """Recompute checkpoint belief. The model itself is resolve/belief.py —
    shared with fuel and the crowd path so the three cannot drift apart, and so
    the P2.4 gate covers checkpoints, where a false "open" costs the most."""
    with connect() as conn, conn.cursor() as cur:
        n = belief_refresh(ALL_KINDS, conn=conn)
        conn.commit()
        cur.execute("""SELECT state_kind, COUNT(*), ROUND(AVG(independent_sources),2),
                              COUNT(*) FILTER (WHERE contradicted_by > 0)
                       FROM state_current WHERE state_kind = ANY(%s)
                       GROUP BY 1 ORDER BY 1""", (list(ALL_KINDS),))
        by_kind = cur.fetchall()
    return {"rows": n, "by_kind": by_kind}


def compute_cadence() -> dict:
    """Derive each (place, kind, direction)'s half-life from its own rhythm."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            WITH gaps AS (
              SELECT place_id, state_kind, direction,
                     EXTRACT(EPOCH FROM (observed_at -
                        LAG(observed_at) OVER (PARTITION BY place_id, state_kind, direction
                                               ORDER BY observed_at))) AS gap
              FROM state_observation
              WHERE state_kind = ANY(%s) AND modality = 'assertion'
            ), agg AS (
              SELECT place_id, state_kind, direction,
                     percentile_cont(0.5) WITHIN GROUP (ORDER BY gap) AS median_gap,
                     COUNT(*) AS n
              FROM gaps WHERE gap IS NOT NULL AND gap > 0
              GROUP BY 1,2,3 HAVING COUNT(*) >= 5   -- too few gaps to trust a median
            )
            INSERT INTO place_state_cadence
                (place_id,state_kind,direction,median_gap_seconds,observations,
                 half_life_seconds,computed_at)
            SELECT place_id, state_kind, direction, GREATEST(median_gap,1)::int, n,
                   LEAST(GREATEST((median_gap * %s)::int, %s), %s), now()
            FROM agg
            ON CONFLICT (place_id,state_kind,direction) DO UPDATE SET
                median_gap_seconds=EXCLUDED.median_gap_seconds,
                observations=EXCLUDED.observations,
                half_life_seconds=EXCLUDED.half_life_seconds,
                computed_at=now()""",
            (list(ALL_KINDS), HALF_LIFE_FACTOR, HALF_LIFE_MIN, HALF_LIFE_MAX))
        conn.commit()
        cur.execute("""SELECT COUNT(*), ROUND(AVG(half_life_seconds)/60.0),
                              ROUND(MIN(half_life_seconds)/60.0),
                              ROUND(MAX(half_life_seconds)/60.0)
                       FROM place_state_cadence WHERE state_kind = ANY(%s)""",
                    (list(ALL_KINDS),))
        n, avg, lo, hi = cur.fetchone()
    return {"measured": n, "avg_min": avg, "min_min": lo, "max_min": hi}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="rebuild all history from v1")
    ap.add_argument("--cadence", action="store_true", help="recompute cadence only")
    ap.add_argument("--state-only", action="store_true", help="refresh belief only")
    a = ap.parse_args()

    if not (a.cadence or a.state_only):
        s = import_updates(a.full)
        print(f"read {s['read']} v1 updates · archived {s['legacy']} · "
              f"flow {s['flow']} · presence {s['presence']}")
        print(f"  excluded from belief: {s['questions']} questions, "
              f"{s['unparsed']} unreadable (both retained)")
        if s["skipped_no_place"]:
            print(f"  skipped {s['skipped_no_place']} with no matching place "
                  f"(e.g. {', '.join(s['unmatched_keys'][:5])})")
    if not a.cadence:
        r = refresh_state()
        print(f"belief refreshed: {r['rows']} rows")
        for kind, n, avg_src, contra in r["by_kind"]:
            print(f"  {kind:<22} {n:>5} states · avg {avg_src} independent sources · "
                  f"{contra} contradicted")
    c = compute_cadence()
    print(f"cadence: {c['measured']} series measured · half-life avg {c['avg_min']}min "
          f"(range {c['min_min']}–{c['max_min']}min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
