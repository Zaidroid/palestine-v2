"""Gaza casualty cross-check — T4P's published series against the Ministry's own bulletin.

    .venv/bin/python -m ops.gaza_crosscheck              # last 45 days, write the report
    .venv/bin/python -m ops.gaza_crosscheck --since 2026-01-01

WHY. Since 2026-09-23 the databank serves the Gaza cumulative series from
Tech4Palestine (conflict_gaza.yaml, F-12). T4P transcribes the Gaza Ministry
of Health's daily bulletin. So does analyst/organ_c.py, directly from the
Ministry's Telegram channel, with the rules Zaid ratified ("B as written").
Two independent transcriptions of the same bulletin should say the same
two numbers. When they do not, one of them is wrong, and neither can tell
which from its own side.

Measured over 2026 before this existed: 188 of 199 days agree. Of the 11
that differ, T4P was right on 2026-06-07 (the bulletin's extra-digit
1,730,128) and the bulletin was right on 2026-01-28 (a Ministry downward
revision T4P never took). So a disagreement is a question for a human, not
an automatic correction, and this job only reports.

WHAT COUNTS. A day is compared when both sides have it: T4P transcribed it
from a bulletin ("mohtel", both totals — exactly the rows the databank
serves) and organ C accepted the bulletin under its validator. A day
only one side has is listed, not alarmed. Only disagreements INSIDE the
window the databank now serves from T4P (from 2026-08-09) raise an alarm;
older ones are history the report keeps.

READ-ONLY. Database reads and one JSON file (data/gaza-crosscheck.json). It
never writes a figure anywhere.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import organ_c  # noqa: E402
from resolve.db import connect  # noqa: E402

T4P_FILE = ROOT / "data" / "raw" / "tech4palestine" / "gaza_daily.json"
OUT = ROOT / "data" / "gaza-crosscheck.json"
SERVED_FROM = date(2026, 8, 9)          # conflict_gaza.yaml's cut-over
BULLETIN_MARK = "التقرير الإحصائي اليومي"
ALERT_UNIT = "crosscheck:gaza-casualties"


def ministry_series(since: date) -> tuple[dict[str, dict], dict[str, str]]:
    """organ C over the archived bulletins, oldest first, with the ratified
    validator. Returns accepted readings per date, and the refusal per date
    the validator would not accept."""
    # Read from a week before `since` so the first compared day has an
    # accepted previous reading to be judged against.
    start = since - timedelta(days=7)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT c.claim_id, c.reported_at, c.raw_text
              FROM claim c JOIN source s USING (source_id)
             WHERE s.key = 'tg_mohmediagaza' AND c.reported_at >= %s
               AND c.raw_text LIKE %s
             ORDER BY c.reported_at, c.claim_id""", (start, f"%{BULLETIN_MARK}%"))
        rows = cur.fetchall()
    accepted: dict[str, dict] = {}
    refused: dict[str, str] = {}
    last_accepted = last_reading = None
    for cid, when, text in rows:
        reading = organ_c.read(text, when)
        if (last_reading and reading["as_of_date"] == last_reading["as_of_date"]
                and reading["cum_killed"] == last_reading["cum_killed"]
                and reading["cum_injured"] == last_reading["cum_injured"]):
            continue                                   # a same-day repost
        previous = ({"cum_killed": last_accepted["cum_killed"],
                     "cum_injured": last_accepted["cum_injured"]} if last_accepted else None)
        verdict = organ_c.validate(reading, previous=previous, reported_at=when)
        day = reading["as_of_date"]
        if verdict.ok:
            accepted[day] = {**verdict.settled, "claim_id": cid}
            refused.pop(day, None)
            last_accepted = verdict.settled
        elif day not in accepted:
            refused[day] = "; ".join(r.code for r in verdict.reasons)
        last_reading = reading
    return accepted, refused


def t4p_series() -> dict[str, dict]:
    rows = json.loads(T4P_FILE.read_text(encoding="utf-8"))
    return {r["report_date"]: r for r in rows if r.get("report_date")}


def classify(ministry: dict[str, dict], refused: dict[str, str],
             t4p: dict[str, dict], since: str) -> dict:
    """Pure: pair the two series by day. Only T4P rows transcribed from a
    bulletin ("mohtel") are compared — the rows the databank serves."""
    t_ok = {d: r for d, r in t4p.items()
            if r.get("report_source") == "mohtel"
            and r.get("killed_cum") is not None and r.get("injured_cum") is not None}
    days = sorted(d for d in set(ministry) | set(t_ok) if d >= since)
    agree, disagree, t4p_only, ministry_only = [], [], [], []
    for d in days:
        m, t = ministry.get(d), t_ok.get(d)
        if m and t:
            row = {"date": d, "ministry": [m["cum_killed"], m["cum_injured"]],
                   "t4p": [t["killed_cum"], t["injured_cum"]], "claim_id": m["claim_id"]}
            (agree if row["ministry"] == row["t4p"] else disagree).append(row)
        elif t:
            t4p_only.append({"date": d, "t4p": [t["killed_cum"], t["injured_cum"]],
                             "bulletin": refused.get(d, "no bulletin dated this day")})
        elif m:
            ministry_only.append({"date": d, "ministry": [m["cum_killed"], m["cum_injured"]],
                                  "claim_id": m["claim_id"]})
    # The same two numbers one day apart are one bulletin filed under two
    # dates (its own text vs the day it was posted), not a disagreement.
    # Measured: 2 of 202 bulletins in 2026 carry a date other than their
    # posting day, one of them 2026-09-13.
    dated_differently = []
    for m in list(ministry_only):
        for t in list(t4p_only):
            gap = abs((date.fromisoformat(t["date"]) - date.fromisoformat(m["date"])).days)
            if gap == 1 and t["t4p"] == m["ministry"]:
                dated_differently.append({"bulletin_date": m["date"], "t4p_date": t["date"],
                                          "totals": m["ministry"], "claim_id": m["claim_id"]})
                ministry_only.remove(m)
                t4p_only.remove(t)
                break
    return {"agree": agree, "disagree": disagree, "t4p_only": t4p_only,
            "ministry_only": ministry_only, "dated_differently": dated_differently}


def compare(since: date) -> dict:
    ministry, refused = ministry_series(since)
    k = classify(ministry, refused, t4p_series(), since.isoformat())
    served = [r for r in k["disagree"] if r["date"] >= SERVED_FROM.isoformat()]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": since.isoformat(), "served_from": SERVED_FROM.isoformat(),
        "reader": organ_c.VERSION,
        "counts": {"compared": len(k["agree"]) + len(k["disagree"]), "agree": len(k["agree"]),
                   "disagree": len(k["disagree"]), "disagree_in_served_window": len(served),
                   "dated_differently": len(k["dated_differently"]),
                   "t4p_only": len(k["t4p_only"]), "ministry_only": len(k["ministry_only"])},
        **k,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", type=date.fromisoformat,
                    help="first day to compare (default: 45 days ago)")
    ap.add_argument("--no-alert", action="store_true", help="report only, never page")
    a = ap.parse_args()
    since = a.since or (datetime.now(timezone.utc).date() - timedelta(days=45))
    report = compare(since)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)

    c = report["counts"]
    print(f"gaza crosscheck since {report['since']}: {c['compared']} days compared, "
          f"{c['agree']} agree, {c['disagree']} disagree "
          f"({c['disagree_in_served_window']} in the served window) · "
          f"{c['dated_differently']} dated differently · "
          f"{c['t4p_only']} T4P-only · {c['ministry_only']} bulletin-only")
    for r in report["disagree"]:
        print(f"  {r['date']}  bulletin {r['ministry'][0]:,} / {r['ministry'][1]:,}"
              f"   T4P {r['t4p'][0]:,} / {r['t4p'][1]:,}   (claim {r['claim_id']})")
    for r in report["dated_differently"]:
        print(f"  dated differently: bulletin says {r['bulletin_date']}, T4P files it "
              f"{r['t4p_date']} — {r['totals'][0]:,} / {r['totals'][1]:,} (claim {r['claim_id']})")

    if not a.no_alert:
        # The watchdog's pattern: raise only if not already open, resolve only
        # if open. resolve() writes a record and sends a (silent) recovery,
        # so calling it on a green night with nothing open would put a
        # "recovered" on the phone every night for a fault that never was.
        from ops.alert import open_alerts, raise_alert, resolve
        is_open = any(r.get("unit") == ALERT_UNIT for r in open_alerts())
        served = [r for r in report["disagree"] if r["date"] >= report["served_from"]]
        if served and not is_open:
            days = ", ".join(r["date"] for r in served[:5])
            raise_alert(ALERT_UNIT,
                        f"T4P and the Ministry bulletin disagree on {len(served)} served "
                        f"day(s): {days}. Which is right is a human call; see "
                        f"data/gaza-crosscheck.json.")
        elif not served and is_open:
            resolve(ALERT_UNIT, "T4P and the Ministry bulletin agree on every served day")
    return 0


if __name__ == "__main__":
    sys.exit(main())
