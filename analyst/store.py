"""The analyst's bookkeeping: the cursor, the provenance row, the numbers.

Everything here is SQL against `analyst_watermark`, `analyst_run` and the two
views migration 068 defines. It is kept apart from the organs so that an organ
is only ever a function from a claim to a verdict, and apart from the loop so
that the loop is only ever a schedule.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect                                  # noqa: E402

# How many claims one organ reads per tick. 200 is ~0.7 s of organ A on this
# box and roughly four minutes of ingestion, so the loop sleeps far more than
# it works while staying inside one transaction's worth of lock time.
BATCH = 200

# `reported_at` is organ C's: a bulletin's own date is checked against when it
# was posted, and the series the ingest writes is keyed on that posting day.
CLAIM_COLUMNS = ("claim_id, ingested_at, source_id, raw_text, lang, attrs, claim_type, "
                 "reported_at")


def connect_readonly():
    """A connection on which every transaction is READ ONLY.

    For `analyst.loop --dry-run`: a dry run that reached an INSERT or an UPDATE
    by mistake must fail on the database's word, not on the care of whoever
    wrote the organ. The organs that write outside provenance (organ A's
    `claim.lang`) are not run dry at all; this is the second lock.
    """
    return connect(options="-c default_transaction_read_only=on")


def read_watermark(cur, organ: str) -> tuple | None:
    """(last_ingested_at, last_claim_id), or None if this organ never ran."""
    cur.execute("""SELECT last_ingested_at, last_claim_id
                     FROM analyst_watermark WHERE organ = %s""", (organ,))
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return row[0], row[1]


def write_watermark(cur, organ: str, ingested_at, claim_id: int,
                    note: str | None = None) -> None:
    """Advance the cursor. Never moves backwards.

    A rewind would re-read claims an organ has already answered and, for a
    model organ, re-pay for them. Deliberate rewinds are a human act: DELETE
    the row, or UPDATE it by hand, and the loop starts from the oldest claim.
    """
    cur.execute("""
        INSERT INTO analyst_watermark (organ, last_ingested_at, last_claim_id,
                                       updated_at, note)
        VALUES (%s, %s, %s, now(), %s)
        ON CONFLICT (organ) DO UPDATE SET
          last_ingested_at = EXCLUDED.last_ingested_at,
          last_claim_id    = EXCLUDED.last_claim_id,
          updated_at       = now(),
          note             = COALESCE(EXCLUDED.note, analyst_watermark.note)
        WHERE (EXCLUDED.last_ingested_at, EXCLUDED.last_claim_id)
              > (analyst_watermark.last_ingested_at, analyst_watermark.last_claim_id)
           OR analyst_watermark.last_ingested_at IS NULL""",
        (organ, ingested_at, claim_id, note))


def fetch_batch(cur, after: tuple | None, limit: int = BATCH,
                before=None) -> list[dict]:
    """The next `limit` claims past the cursor, oldest first.

    THE FILTER IS NOT IN THIS QUERY, ON PURPOSE. An organ that only wants some
    claims (organ A wants the ones nothing has stamped) decides per row in
    Python. If the filter lived here, a batch in which no row qualified would
    return nothing, the loop would have nothing to advance the cursor to, and
    the organ would re-scan the same stretch of corpus forever — busy, honest
    in its heartbeat, and permanently stuck one row before the interesting one.

    `before` is the one bound that IS here, because it is about time, not
    about the claim: an organ that judges a claim against what ANOTHER job
    derives from it (organ C against the hourly MoH ingest) must not read the
    claim before that job has had its turn. Claims ingested at or after
    `before` are not fetched, so the cursor stops short of them and they are
    read on a later tick — never skipped.
    """
    bound = "" if before is None else "AND ingested_at < %s"
    params: list = [] if before is None else [before]
    if after is None:
        cur.execute(f"""SELECT {CLAIM_COLUMNS} FROM claim
                         WHERE true {bound}
                         ORDER BY ingested_at, claim_id LIMIT %s""",
                    (*params, limit))
    else:
        cur.execute(f"""SELECT {CLAIM_COLUMNS} FROM claim
                         WHERE (ingested_at, claim_id) > (%s, %s) {bound}
                         ORDER BY ingested_at, claim_id LIMIT %s""",
                    (after[0], after[1], *params, limit))
    cols = [c.strip() for c in CLAIM_COLUMNS.split(",")]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def record_run(cur, *, claim_id: int, organ: str, organ_version: str,
               outcome: str, model: str | None = None,
               prompt_version: str | None = None, verdict: str | None = None,
               votes: list | None = None, agreed: bool | None = None,
               json_valid: bool | None = None, latency_ms: int | None = None,
               error: str | None = None, raw: dict | None = None) -> None:
    """One row per claim an organ actually read. See 068 for why."""
    cur.execute("""
        INSERT INTO analyst_run (claim_id, organ, organ_version, model,
                                 prompt_version, verdict, votes, agreed,
                                 json_valid, latency_ms, outcome, error, raw)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (claim_id, organ, organ_version, model, prompt_version, verdict,
         json.dumps(votes, ensure_ascii=False) if votes is not None else None,
         agreed, json_valid, latency_ms, outcome,
         error[:2000] if error else None,
         json.dumps(raw or {}, ensure_ascii=False)))


def health(cur) -> dict[str, dict]:
    """Per-organ health for the last hour, straight from the view."""
    cur.execute("""SELECT organ, runs_1h, ok_1h, errors_1h, skipped_1h,
                          success_rate_1h, json_valid_rate_1h, vote_agreement_1h,
                          latency_p50_ms, latency_p95_ms
                     FROM analyst_health""")
    out = {}
    for r in cur.fetchall():
        out[r[0]] = {
            "runs_1h": r[1], "ok_1h": r[2], "errors_1h": r[3],
            "skipped_1h": r[4],
            "success_rate_1h": float(r[5]) if r[5] is not None else None,
            "json_valid_rate_1h": float(r[6]) if r[6] is not None else None,
            "vote_agreement_1h": float(r[7]) if r[7] is not None else None,
            "latency_p50_ms": float(r[8]) if r[8] is not None else None,
            "latency_p95_ms": float(r[9]) if r[9] is not None else None,
        }
    return out


def backlog(cur) -> dict[str, dict]:
    """How far behind each organ is, in claims and in minutes."""
    cur.execute("""SELECT organ, pending_claims, lag_minutes
                     FROM analyst_backlog""")
    return {r[0]: {"pending_claims": int(r[1]),
                   "lag_minutes": float(r[2]) if r[2] is not None else None}
            for r in cur.fetchall()}


def lang_distribution(cur) -> dict[str, int]:
    """What `claim.lang` currently says, whatever wrote it."""
    cur.execute("""SELECT COALESCE(lang, '(null)'), count(*)
                     FROM claim GROUP BY 1 ORDER BY 2 DESC""")
    return {r[0]: int(r[1]) for r in cur.fetchall()}


def undetected_claims(cur) -> int:
    """Claims no language detector has ever stamped."""
    cur.execute("""SELECT count(*) FROM claim
                    WHERE attrs->>'lang_detector' IS NULL""")
    return int(cur.fetchone()[0])


__all__ = ["BATCH", "backlog", "connect", "connect_readonly", "fetch_batch", "health",
           "lang_distribution", "read_watermark", "record_run",
           "undetected_claims", "write_watermark"]
