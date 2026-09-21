"""One-time corrective pass: give every existing claim its real language.

    .venv/bin/python -m analyst.backfill_lang --dry-run    # distribution first
    .venv/bin/python -m analyst.backfill_lang --apply
    .venv/bin/python -m analyst.backfill_lang --apply --limit 5000

WHY THIS IS ALLOWED TO WRITE TO AN IMMUTABLE TABLE
`claim` is immutable because it is the record of what a source SAID (005). Every
row's `lang` says `ar`, and no source ever said that: it was a literal in three
INSERT statements, including the one that writes English MoH bulletins and the
one that writes RSS. It is not testimony, it is a measurement of the text that
was never taken. So this takes it, and — the condition on which the exception
rests — stamps WHAT TOOK IT into the same row: `attrs.lang_detector`. A
corrected value with no provenance would be a second unfalsifiable constant.

WHY IN BATCHES WITH A CURSOR AND NOT ONE UPDATE
99,376 rows in one transaction on a hypertable holds locks across every chunk
for the duration, blocks the poller mid-flight, and either finishes or leaves
nothing. 2,000 rows a transaction, cursor on (ingested_at, claim_id), commits as
it goes; killed halfway it resumes from where it stopped, because the stamp IS
the progress marker — a row that carries `lang_detector` is never selected
again.

WHY --dry-run PRINTS THE DISTRIBUTION FIRST
The point of the exercise is a number that changes: 99,376 rows claiming Arabic,
against whatever is actually there. A run whose before and after are not
comparable proves nothing.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import store                                        # noqa: E402
from analyst.lang import detect, detector_id                      # noqa: E402

BATCH = 2000
ORGAN = "lang"

UPDATE = """
UPDATE claim c
   SET lang  = v.lang,
       attrs = c.attrs || jsonb_build_object('lang_detector', v.det)
  FROM (VALUES %s) AS v(claim_id, ingested_at, lang, det)
 WHERE c.claim_id = v.claim_id AND c.ingested_at = v.ingested_at
"""


def _rows(cur, after, limit):
    if after is None:
        cur.execute("""SELECT claim_id, ingested_at, raw_text, lang,
                              attrs->>'lang_detector'
                         FROM claim ORDER BY ingested_at, claim_id LIMIT %s""",
                    (limit,))
    else:
        cur.execute("""SELECT claim_id, ingested_at, raw_text, lang,
                              attrs->>'lang_detector'
                         FROM claim
                        WHERE (ingested_at, claim_id) > (%s, %s)
                        ORDER BY ingested_at, claim_id LIMIT %s""",
                    (after[0], after[1], limit))
    return cur.fetchall()


def distribution() -> dict[str, int]:
    with store.connect() as conn, conn.cursor() as cur:
        return store.lang_distribution(cur)


def run(apply: bool, limit: int | None = None, batch: int = BATCH,
        progress=print) -> dict:
    """Walk the corpus once. Returns what it did and what it would have done."""
    ident = detector_id()
    after, seen, changed, stamped = None, 0, 0, 0
    verdicts: Counter = Counter()
    unchanged_value = 0

    while True:
        with store.connect() as conn, conn.cursor() as cur:
            rows = _rows(cur, after, batch)
            if not rows:
                break
            pending = []
            for claim_id, ingested_at, raw_text, old_lang, det in rows:
                seen += 1
                if det:                       # already measured, by anyone
                    continue
                code, _ = detect(raw_text)
                verdicts[code] += 1
                if code == old_lang:
                    unchanged_value += 1
                else:
                    changed += 1
                pending.append((claim_id, ingested_at, code, ident))
            after = (rows[-1][1], rows[-1][0])

            if pending and apply:
                values = ",".join(["(%s::bigint,%s::timestamptz,%s::text,%s::text)"]
                                  * len(pending))
                flat = [x for row in pending for x in row]
                cur.execute(UPDATE % values, flat)
                stamped += cur.rowcount
                # The cursor is written inside the SAME transaction as the rows
                # it covers, so a kill between the two cannot leave the loop
                # starting from claims that were never stamped.
                store.write_watermark(cur, ORGAN, rows[-1][1], rows[-1][0],
                                      note=f"lang backfill {ident}")
                conn.commit()
            else:
                conn.rollback()
        progress(f"  {seen:>6} scanned · {changed:>6} corrected · "
                 f"{stamped:>6} written")
        if limit and seen >= limit:
            break

    return {"scanned": seen, "would_change": changed, "written": stamped,
            "already_right": unchanged_value, "verdicts": dict(verdicts),
            "detector": ident}


def main() -> int:
    ap = argparse.ArgumentParser(description="give every claim its real language")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="measure and report; write nothing")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="stop after N claims")
    ap.add_argument("--batch", type=int, default=BATCH)
    a = ap.parse_args()

    before = distribution()
    print("BEFORE  " + "  ".join(f"{k}={v}" for k, v in before.items()))

    res = run(a.apply, a.limit or None, a.batch)

    print(f"\ndetector        {res['detector']}")
    print(f"claims scanned  {res['scanned']}")
    print(f"never measured  {res['would_change'] + res['already_right']}")
    print(f"value corrected {res['would_change']}")
    print(f"rows written    {res['written']}")
    print("verdicts        " + "  ".join(f"{k}={v}" for k, v in
                                         sorted(res["verdicts"].items(),
                                                key=lambda kv: -kv[1])))
    after = distribution()
    print("AFTER   " + "  ".join(f"{k}={v}" for k, v in after.items()))
    if not a.apply:
        print("\n(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
