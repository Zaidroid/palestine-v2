"""Is a weekly maintenance run owed? The skip condition for every catch-up.

    .venv/bin/python -m ops.maintain_due [--max-age-days 6]

Exit 0: OWED — the last digest in ops/digests.ndjson is older than the window,
or there is no readable digest at all. Exit 1: a digest landed inside the
window; skip. Those are ExecCondition='s codes, which is where this runs
(palestine-v2-maintain-retry.service): 1 skips the unit cleanly instead of
failing it, and 255 — which nothing here returns — would fail it.

WHY THE DIGEST AND NOT THE HEARTBEAT
The maintainer's product is the digest Fawwaz reads to Zaid. A session that
starts, beats, and dies before writing one has still lost the week, and the
digest ledger is the one record that only moves when the week was actually
done. It is also the record that has been silent since 2026-09-07 while two
Mondays failed on the Claude monthly spend limit.

WHY A BROKEN LEDGER IS OWED
Every unreadable case — no file, no parseable line, no parseable ts — answers
"owed". The cost of a spurious catch-up is one maintenance session in a week
that already had one; the cost of a spurious skip is the failure this exists
to end, a week lost with nothing saying so.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "ops" / "digests.ndjson"


def last_digest_ts(path: Path) -> datetime | None:
    """The `ts` of the last line that parses, in append order. A torn final
    line (a run killed mid-write) falls back to the one before it."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            ts = datetime.fromisoformat(json.loads(line)["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def is_owed(path: Path, now: datetime, max_age: timedelta) -> tuple[bool, str]:
    ts = last_digest_ts(path)
    if ts is None:
        return True, f"no readable digest in {path.name} — owed"
    age = now - ts
    days = age.total_seconds() / 86400
    verdict = "owed" if age > max_age else "not owed, skipping"
    return age > max_age, (f"last digest {ts.isoformat(timespec='seconds')}, "
                           f"{days:.1f} days old vs {max_age.total_seconds() / 86400:g}-day "
                           f"window — {verdict}")


def main() -> int:
    ap = argparse.ArgumentParser(description="is a weekly maintenance run owed?")
    ap.add_argument("--max-age-days", type=float, default=6)
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    a = ap.parse_args()
    owed, why = is_owed(a.ledger, datetime.now(timezone.utc),
                        timedelta(days=a.max_age_days))
    print(f"maintain_due: {why}")
    return 0 if owed else 1


if __name__ == "__main__":
    sys.exit(main())
