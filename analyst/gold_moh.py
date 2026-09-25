#!/usr/bin/env python3
"""Build the organ C gold set — `tests/gold/moh_c.jsonl`.

WHY A BUILDER AND NOT A HAND-TYPED FILE
The gold set is what F-11 scores a model against, so every row has to be
reproducible from the archived text and carry its own provenance. Each row says
how it was established:

    label_method "read"        a human read this bulletin's text and confirmed
                              every field in it (the list is in READ_VERIFIED)
    label_method "arithmetic"  the deterministic reader produced it and the
                              arithmetic held: monotonic against the row before
                              it, the window's count consistent with the
                              cumulative rise, the date from the bulletin's own
                              trailer — and, for the boundary row, agreement with
                              a value produced by a DIFFERENT pipeline in August
                              (2026-08-08: 73,384, the number the databank froze at)

No row claims to be hand-labelled when it was not. A model scored against a
gold set with unlabelled provenance measures nothing.

    usage:  .venv/bin/python -m analyst.gold_moh --csv <path> --out <path>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import organ_c  # noqa: E402

GOLD_YEAR = "2026"

# The bulletins read in full, by claim id, one at a time, against the text.
# Anything not in this list is arithmetic-verified only, and says so.
READ_VERIFIED = {
    11560,   # 2026-01-01 the dual form (`شهيد واحد`) and a 24 h injured of 1
    11561,   # 2026-01-03 a 48-hour window
    11570,   # 2026-01-09 injured value on the line below its label
    11579,   # 2026-01-15 `شهيدان, و5 إصابات` — the whole 24 h block, spelled
    11609,   # 2026-01-27 injured 171,428, the row before the revision downward
    11611,   # 2026-01-28 injured 171,343 — the publisher's own revision downward
    11640,   # 2026-02-14 a 48-hour window whose 24 h line is `2 شهداء انتشال`
    11653,   # 2026-02-19 cumulative injured rises 2 against a 24 h line of 4
    11656,   # 2026-02-23 `شهيد واحد جديد, و 8 إصابات`
    11662,   # 2026-03-04 a bare `شهيد`: one death, written as a word
    11668,   # 2026-03-10 `شهيدان, أحدهما شهيد انتشال, وإصابتان`
    11678,   # 2026-03-17 cumulative killed does not move against a 24 h line of 2
    11681,   # 2026-03-23 no hours at all: `خلال ايام عيد الفطر وحتى الساعة`
    11715,   # 2026-04-05 `72.292` — a dot as the thousands separator
    11772,   # 2026-05-07 the trailer has no space: `7مايو 2026`
    11818,   # 2026-06-08 the row after the seven-digit injured total
    11894,   # 2026-07-26 cumulative injured on the line below its own label
    74176,   # 2026-09-01 the note block after the cumulative line
    102173,  # 2026-09-16 the boundary the series resumes from
    124147,  # 2026-09-22 the newest bulletin in the archive
}


def rows_from_csv(path: str, year: str):
    with open(path, encoding="utf-8") as fh:
        for cid, ts, text in csv.reader(fh):
            when = datetime.fromisoformat(ts)
            if when.isoformat().startswith(year):
                yield int(cid), when, text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="claim_id,reported_at,raw_text, one bulletin per row")
    ap.add_argument("--out", required=True)
    ap.add_argument("--year", default=GOLD_YEAR)
    args = ap.parse_args()

    out_rows = []
    last_accepted = None          # B1: every comparison is to the last ACCEPTED row
    last_reading = None
    last_claim = None
    verdict_counts: dict[str, int] = {}
    note_counts: dict[str, int] = {}
    for cid, when, text in rows_from_csv(args.csv, args.year):
        reading = organ_c.read(text, when)
        # The Ministry sometimes posts the same bulletin twice on one day (twice
        # in 2026: 17 Mar and 18 Jun). A repost is one fact, not two, and
        # comparing a bulletin with its own copy refused both halves of it.
        repost_of = None
        if (last_reading and reading["as_of_date"] == last_reading["as_of_date"]
                and reading["cum_killed"] == last_reading["cum_killed"]
                and reading["cum_injured"] == last_reading["cum_injured"]):
            repost_of = last_claim
        if repost_of:
            out_rows.append({
                "claim_id": cid, "reported_at": when.isoformat(),
                "label_method": "read" if cid in READ_VERIFIED else "arithmetic",
                "reader": reading, "repost_of": repost_of,
                "verdict": {"ok": None, "reasons": [], "notes": []}, "previous": None,
            })
            continue
        previous = ({"cum_killed": last_accepted["cum_killed"],
                     "cum_injured": last_accepted["cum_injured"]} if last_accepted else None)
        verdict = organ_c.validate(reading, previous=previous, reported_at=when)
        for reason in verdict.reasons:
            verdict_counts[reason.code] = verdict_counts.get(reason.code, 0) + 1
        for note in verdict.notes:
            note_counts[note.code] = note_counts.get(note.code, 0) + 1
        out_rows.append({
            "claim_id": cid,
            "reported_at": when.isoformat(),
            "label_method": "read" if cid in READ_VERIFIED else "arithmetic",
            "reader": reading,
            "settled": verdict.settled,
            "verdict": verdict.as_dict(),
            "previous": previous,
        })
        if verdict.ok:
            last_accepted = verdict.settled
        last_reading, last_claim = reading, cid

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    unique = [r for r in out_rows if not r.get("repost_of")]
    read_n = sum(1 for r in out_rows if r["label_method"] == "read")
    ok_n = sum(1 for r in unique if r["verdict"]["ok"])
    print(f"{out}: {len(out_rows)} rows · {len(out_rows) - len(unique)} reposts · "
          f"{len(unique)} unique days · {ok_n} served · {len(unique) - ok_n} refused "
          f"· {read_n} read by a human · {len(out_rows) - read_n} arithmetic-verified")
    print("refusal codes:", verdict_counts)
    print("notes (served):", note_counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
