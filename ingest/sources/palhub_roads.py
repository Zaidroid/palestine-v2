"""Palhub's road bulletin as a checkpoint source.

    .venv/bin/python -m ingest.sources.palhub_roads
    .venv/bin/python -m ingest.sources.palhub_roads --dry-run

`@palhubapproad` publishes a machine-generated table every ~2 minutes: 12 areas,
184 named checkpoints, inbound and outbound stated separately, four states. The
poller writes those messages to `claim` like any other channel; this turns them
into `checkpoint_flow` observations.

WHY checkpoint_flow AND NOT checkpoint_status
`checkpoint_status` is the LEGACY lane — one row per v1 update, carrying v1's
own verdict. `checkpoint_flow` is v2's re-parsed throughput axis, and it is
where independent observers corroborate each other. Palhub is a new independent
observer, not v1, so it belongs in the lane where its agreement can count.

THE REFRESH PROBLEM, AND WHY IT IS NOT JUST DEDUP
Palhub restates every checkpoint every two minutes whether or not anything
changed. Written naively that is 184 checkpoints x 2 directions x 30 per hour =
265,000 observations a day, which is the fuel duplication all over again — and
that one took a backup-sizing exercise to notice.

But dropping unchanged repeats entirely is also wrong. "Still open at 13:00" is
a real observation: the serving gates decay confidence with age, so a source
that stops restating a true fact makes the system correctly forget something
palhub still knows.

So a reading is written when the VALUE CHANGES, or when the last write for that
checkpoint and direction is older than REFRESH_SECONDS. Thirty minutes is a
third of checkpoint_flow's 90-minute half-life — the same window fraction Loop A
uses to decide whether two observations are describing the same moment — so
belief stays fresh while the write volume stays near 18k/day instead of 265k.

PLACE RESOLUTION USES THE AREA
"بيت عور" exists in more than one governorate. Palhub states the area in the
header, so it is passed as context and the resolver prefers a checkpoint inside
it. Without that, a name shared across governorates lands wherever the gazetteer
happens to sort first — which is the failure that had crowd checkpoint reports
landing on towns.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from cascade.palhub_roads import is_bulletin, parse       # noqa: E402
from resolve.belief import refresh as belief_refresh      # noqa: E402
from resolve.db import connect                            # noqa: E402
from resolve.geo import _Ambiguous, resolve_for_state_kind, resolve_place  # noqa: E402

SOURCE_KEY = "tg_palhubapproad"
STATE_KIND = "checkpoint_flow"

# A third of checkpoint_flow's 90-minute half-life. See the module docstring.
REFRESH_SECONDS = 1800

# Palhub's own confidence in a machine-generated table is not something we can
# ask it for, so the observation carries the parser's confidence instead: this
# is an exact read of an explicit statement, not an inference from prose. The
# reporter's RELIABILITY is a separate question, measured by Loop A, and is
# applied when belief is computed.
PARSE_CONFIDENCE = 0.95

# QUARANTINED UNTIL IT EARNS ITS WAY OUT (migration 033).
#
# This source parses beautifully — 6,058 of 6,060 lines, exactly — and lifted
# checkpoint_flow coverage from 23% to 64% in one pass. Then the control was
# measured:
#
#     channel vs channel, 5-minute window   1,868 / 1,930  = 96.8%
#     palhub  vs channel, 5-minute window      21 /    45  = 46.7%
#
# The road channels agree with each other 96.8% of the time; palhub agrees with
# them less than half. It is describing something other than what they describe,
# or the name mapping is wrong in a way sampling did not reveal. Either way it
# must not move a value that tells a family whether a road is passable.
#
# So it KEEPS COLLECTING and stays out of belief. `resolve/belief.py` counts
# modality='assertion' and nothing else, so this is structural rather than a
# rule someone has to remember. Flip to 'assertion' only when a measurement
# says it has earned it — and measure against the channel-vs-channel baseline,
# never against perfection: 46.7% read alone looks like a source with a
# different congestion threshold, and only the 96.8% control shows what it is.
MODALITY = "quarantined"

# "أخرى" is Palhub's catch-all bucket and names no governorate; those rows
# resolve on the checkpoint name alone.
NO_AREA = {"أخرى"}


def _ensure_source(cur) -> int:
    cur.execute("""
        INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                            attribution_text, authority_rank, active)
        VALUES (%s, 'Palhub - احوال الطرق (Telegram)', 'telegram', 'NONE', false,
                'Palhub road status', 4, true)
        ON CONFLICT (key) DO NOTHING""", (SOURCE_KEY,))
    cur.execute("SELECT source_id FROM source WHERE key = %s", (SOURCE_KEY,))
    return cur.fetchone()[0]


def _area_map(cur) -> dict[str, str]:
    """Palhub's area names -> admin2_pcode, resolved once against the gazetteer."""
    out: dict[str, str] = {}
    cur.execute("SELECT name_ar, name_en, admin2_pcode FROM place "
                "WHERE kind = 'governorate' AND admin2_pcode IS NOT NULL")
    govs = cur.fetchall()
    from resolve.arabic import fold_for_match
    folded = {fold_for_match(ar): pc for ar, _en, pc in govs if ar}
    for area in ("نابلس", "رام الله و البيرة", "الخليل", "جنين", "طولكرم",
                 "قلقيلية", "سلفيت", "أريحا", "بيت لحم", "طوباس",
                 "ضواحي القدس"):
        key = fold_for_match(area)
        if key in folded:
            out[area] = folded[key]
            continue
        # "رام الله و البيرة" and "ضواحي القدس" are Palhub's phrasing, not
        # OCHA's. Fall back to the general resolver rather than hand-coding a
        # mapping that would silently rot if either side renamed anything.
        r = resolve_place(area, {"prefer_kind": "governorate"}, learn=False)
        if r and getattr(r, "admin2_pcode", None):
            out[area] = r.admin2_pcode
    return out


def _resolve(conn, name, admin2, cache=None):
    """Checkpoint place for a palhub name, preferring one inside the area.

    Cached per (name, area). Palhub restates the same 184 names every two
    minutes, so a three-day backfill asks the same question ~54,000 times.
    Uncached, each answer rescans all 359 checkpoint places and the backfill
    never finishes — there are only a couple of hundred distinct questions.
    """
    if cache is not None:
        ck = (name, admin2)
        if ck not in cache:
            cache[ck] = _resolve_uncached(conn, name, admin2)
        return cache[ck]
    return _resolve_uncached(conn, name, admin2)


def _resolve_uncached(conn, name: str, admin2: str | None):
    try:
        r = resolve_for_state_kind(conn, name, STATE_KIND)
        if r and getattr(r, "confidence", 0) >= 0.55:
            return r
    except _Ambiguous:
        pass                       # the area context below may settle it
    ctx = {"prefer_kind": "checkpoint"}
    if admin2:
        ctx["admin2_pcode"] = admin2
    r = resolve_place(name, ctx, conn=conn, learn=False)
    return r if r and r.confidence >= 0.55 else None


LAST_SQL = """
SELECT place_id, direction, value, observed_at
  FROM (SELECT DISTINCT ON (place_id, direction)
               place_id, direction, value, observed_at
          FROM state_observation
         WHERE state_kind = %s AND source_id = %s
         ORDER BY place_id, direction, observed_at DESC) t
"""


def load(limit: int = 2000, dry_run: bool = False) -> dict:
    stats = {"claims": 0, "bulletins": 0, "readings": 0, "written": 0,
             "unchanged_skipped": 0, "unresolved": 0, "rejected_lines": 0}
    unresolved: dict[str, int] = {}
    place_cache: dict = {}

    with connect() as conn, conn.cursor() as cur:
        source_id = _ensure_source(cur)
        areas = _area_map(cur)

        # What this source has already said, so an unchanged restatement can be
        # skipped without another query per checkpoint.
        cur.execute(LAST_SQL, (STATE_KIND, source_id))
        last = {(p, d): (v, t) for p, d, v, t in cur.fetchall()}

        cur.execute("SELECT external_id FROM ingest_seen WHERE source_id = %s",
                    (source_id,))
        seen = {r[0] for r in cur.fetchall()}

        cur.execute("""
            SELECT c.claim_id, c.raw_text, c.reported_at
              FROM claim c JOIN source s USING (source_id)
             WHERE s.key = %s
             ORDER BY c.reported_at
             LIMIT %s""", (SOURCE_KEY, limit))
        claims = cur.fetchall()

        for claim_id, text, reported_at in claims:
            if str(claim_id) in seen:
                continue
            stats["claims"] += 1
            if not is_bulletin(text or ""):
                if not dry_run:
                    cur.execute("""INSERT INTO ingest_seen (source_id, external_id)
                                   VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                                (source_id, str(claim_id)))
                continue

            b = parse(text)
            stats["bulletins"] += 1
            stats["rejected_lines"] += len(b.rejected)
            admin2 = areas.get(b.area or "") if (b.area not in NO_AREA) else None

            # Palhub's stated "last updated" matches the Telegram post time
            # exactly (08:13 UTC <-> 11:13 Asia/Hebron), so the message time IS
            # the observation time. The stated stamp rides along in attrs as a
            # cross-check, rather than being reconstructed into a datetime — a
            # reconstruction that would need care around midnight to buy
            # nothing.
            observed_at = reported_at

            for rd in b.readings:
                stats["readings"] += 1
                place = _resolve(conn, rd.name, admin2, place_cache)
                if place is None:
                    stats["unresolved"] += 1
                    unresolved[rd.name] = unresolved.get(rd.name, 0) + 1
                    continue

                key = (place.place_id, rd.direction)
                prev = last.get(key)
                if prev and prev[0] == rd.value and prev[1] is not None:
                    if (observed_at - prev[1]) < timedelta(seconds=REFRESH_SECONDS):
                        stats["unchanged_skipped"] += 1
                        continue

                if not dry_run:
                    cur.execute("""
                        INSERT INTO state_observation
                          (place_id, state_kind, value, raw_value, observed_at,
                           source_id, claim_id, confidence, direction,
                           direction_explicit, modality, attrs)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s)""",
                        (place.place_id, STATE_KIND, rd.value, rd.raw_status,
                         observed_at, source_id, claim_id, PARSE_CONFIDENCE,
                         rd.direction, MODALITY,
                         json.dumps({"palhub_area": b.area,
                                     "palhub_name": rd.name,
                                     "palhub_severity": rd.severity,
                                     "palhub_updated_local": b.updated_local},
                                    ensure_ascii=False)))
                last[key] = (rd.value, observed_at)
                stats["written"] += 1

            if not dry_run:
                cur.execute("""INSERT INTO ingest_seen (source_id, external_id)
                               VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                            (source_id, str(claim_id)))

        if not dry_run:
            belief_refresh([STATE_KIND], conn=conn)
            conn.commit()

    stats["unresolved_names"] = sorted(unresolved.items(),
                                       key=lambda kv: -kv[1])[:15]
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = load(a.limit, a.dry_run)
    for k in ("claims", "bulletins", "readings", "written",
              "unchanged_skipped", "unresolved", "rejected_lines"):
        print(f"  {k:20}{s[k]:>8,}")
    if s["unresolved_names"]:
        print("  unresolved names:",
              ", ".join(f"{n}({c})" for n, c in s["unresolved_names"][:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
