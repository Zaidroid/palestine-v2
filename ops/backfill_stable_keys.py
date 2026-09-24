"""Give every existing classifier event its stable key (migration 076).

Computed exactly as ingest/sources/news_incidents.py computes it for a new
event — classifier | type | place_id | name_key (the named place, folded) |
earliest claim id — so the next --rebuild joins these rows instead of minting
new ones. Additive: only events lacking the key are touched.

Usage: python ops/backfill_stable_keys.py [--apply]     (default: dry run)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.sources.news_incidents import CLASSIFIER, _stable_key   # noqa: E402
from resolve.arabic import fold_for_match                            # noqa: E402
from resolve.db import connect                                       # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT e.event_id, e.event_type, e.place_id, e.attrs->>'place_text',
                   MIN(c.claim_id)
              FROM event e LEFT JOIN claim c ON c.event_id = e.event_id
             WHERE e.attrs->>'classifier' = %s AND NOT (e.attrs ? 'stable_key')
             GROUP BY 1, 2, 3, 4""", (CLASSIFIER,))
        rows = cur.fetchall()
        done = skipped = 0
        seen: set[str] = set()
        for event_id, etype, place_id, place_text, first_claim in rows:
            if first_claim is None:
                skipped += 1                       # an orphan; the sweep removes it
                continue
            name_key = fold_for_match(place_text) if place_text else ""
            key = _stable_key(etype, place_id, name_key or None, first_claim)
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            if a.apply:
                cur.execute("UPDATE event SET attrs = attrs || %s::jsonb WHERE event_id = %s",
                            (json.dumps({"stable_key": key, "name_key": name_key}), event_id))
            done += 1
        if a.apply:
            conn.commit()
    print(f"{'applied' if a.apply else 'dry run'}: {done} keyed, {skipped} skipped "
          f"(orphans or duplicate keys), of {len(rows)} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
