"""Weekly review: re-measure what is quarantined, notice when precision rots.

    .venv/bin/python -m ops.measure_review          # run and record
    .venv/bin/python -m ops.measure_review --dry    # print, write nothing

WHY THIS EXISTS
Quarantine was a one-way door: palhub roads failed at 46.7% and the fuel cards
failed on 34 one-sided false-availables, and NOTHING would ever look again — a
feed that fixed itself stayed condemned by a measurement of its past. The same
rot runs the other way: the incident classifier's precision was measured at a
version, the version moves on, and the old number keeps being believed. Both
are the same disease — a measurement treated as a property instead of a
reading — and the cure for both is a clock.

WHAT IT DOES, AND DOES NOT
Each week: re-measure the fuel-card agreement over the TRAILING window,
re-measure palhub roads against the live channels, and check how stale the
incident precision round is. Everything is appended to ops/measure-review.ndjson.
A quarantined feed crossing its promotion gate sends a NOTIFICATION for a human
to act on — nothing is auto-promoted. Believing a source is a decision, not a
threshold event; this module only makes sure the decision is offered when the
evidence has changed. A rotten precision round raises a real alarm, because
serving numbers measured on a classifier that no longer exists is quietly
lying.

GATES
  fuel images    >= 100 trailing station+fuel units, ZERO card-available/
                 text-unavailable disagreements, station rate >= 0.99. The
                 original failure was one-sided false reassurance; the gate is
                 therefore hardest exactly there (P2.4's asymmetry).
  palhub roads   >= 200 trailing pairs and agreement >= 0.90 against
                 independent channels. It failed at 46.7% on staleness; a
                 stale feed cannot pass this by accident.
  precision      a round is DUE when the classifier version has moved since
                 the last scored round, or 35 days have passed. The alarm
                 names the unmeasured types rather than a generic "overdue".
  gold contract  (P2-A.3, ops/gold_contract.py) every classifier and organ
                 version scored against the gold sets that exist — incident
                 rounds, the MoH gold, the roads hook — each score beside its
                 version, and each version servable / NOT SERVABLE /
                 unmeasured against its gate. Reported, never enforced: a
                 version below its gate is named in `not_servable` and in the
                 table this prints; what serves does not change here.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LEDGER = ROOT / "ops" / "measure-review.ndjson"

FUEL_TRAILING_DAYS = 14
FUEL_MIN_UNITS = 100
FUEL_MIN_STATION_RATE = 0.99

ROADS_TRAILING_DAYS = 14
ROADS_WINDOW_MINUTES = 90
ROADS_MIN_PAIRS = 200
ROADS_MIN_RATE = 0.90

ROUND_MAX_AGE_DAYS = 35

# Palhub's quarantined checkpoint rows against the nearest independent-channel
# assertion for the same place and direction. Same DISTINCT ON discipline as
# the fuel measurement: one row per palhub observation, or the rate measures
# sweep frequency instead of agreement.
ROADS_PAIR_SQL = """
WITH ph AS (
  SELECT o.place_id, o.direction, o.value, o.observed_at
    FROM state_observation o
    JOIN source s ON s.source_id = o.source_id
   WHERE s.key = 'tg_palhubapproad' AND o.state_kind = 'checkpoint_flow'
     AND o.observed_at > now() - make_interval(days => %s)
), live AS (
  SELECT o.place_id, o.direction, o.value, o.observed_at
    FROM state_observation o
    JOIN source s ON s.source_id = o.source_id
   WHERE s.key <> 'tg_palhubapproad' AND o.state_kind = 'checkpoint_flow'
     AND o.modality = 'assertion'
)
SELECT DISTINCT ON (p.place_id, p.direction, p.observed_at)
       p.value AS palhub_value, l.value AS live_value
  FROM ph p
  JOIN live l ON l.place_id = p.place_id
   AND (l.direction = p.direction OR l.direction = 'both' OR p.direction = 'both')
   AND l.observed_at BETWEEN p.observed_at - make_interval(mins => %s)
                         AND p.observed_at + make_interval(mins => %s)
 ORDER BY p.place_id, p.direction, p.observed_at,
          abs(EXTRACT(epoch FROM (p.observed_at - l.observed_at)))
"""


def review_fuel() -> dict:
    from learn.fuel_image_agreement import measure
    r = measure(days=FUEL_TRAILING_DAYS)
    units = r.get("station_fuels") or 0
    gate = (units >= FUEL_MIN_UNITS
            and (r.get("false_available") or 0) == 0
            and (r.get("station_rate") or 0) >= FUEL_MIN_STATION_RATE)
    return {"feed": "fuel_images", "trailing_days": FUEL_TRAILING_DAYS,
            "units": units, "station_rate": r.get("station_rate"),
            "false_available": r.get("false_available"),
            "false_unavailable": r.get("false_unavailable"),
            "gate_crossed": gate}


def review_palhub_roads() -> dict:
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(ROADS_PAIR_SQL,
                    (ROADS_TRAILING_DAYS, ROADS_WINDOW_MINUTES, ROADS_WINDOW_MINUTES))
        pairs = cur.fetchall()
    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b)
    rate = round(agree / n, 4) if n else None
    gate = n >= ROADS_MIN_PAIRS and rate is not None and rate >= ROADS_MIN_RATE
    return {"feed": "palhub_roads", "trailing_days": ROADS_TRAILING_DAYS,
            "pairs": n, "rate": rate, "gate_crossed": gate}


def review_precision_rounds() -> dict:
    from ingest.sources.news_incidents import CLASSIFIER_VERSION

    # ops/incident-rounds.ndjson is written by learn/incident_precision.score()
    # from this session on. Rounds scored before it existed have no version on
    # record, so the fallback is the scored files' mtimes — age-only, with the
    # version treated as unknown (and unknown counts as moved: a number whose
    # provenance cannot be established should not be quoted quietly).
    last_at, last_ver = None, None
    rounds = ROOT / "ops" / "incident-rounds.ndjson"
    if rounds.exists():
        for line in rounds.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("scored_at") and (last_at is None or rec["scored_at"] > last_at):
                last_at, last_ver = rec["scored_at"], rec.get("classifier_version")
    if last_at is None:
        mtimes = [f.stat().st_mtime for f in (ROOT / "ops").glob("incident-scored*.ndjson")]
        if mtimes:
            last_at = datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat()

    age_days = None
    if last_at:
        try:
            age_days = (datetime.now(timezone.utc)
                        - datetime.fromisoformat(last_at)).days
        except ValueError:
            age_days = None

    version_moved = last_ver != CLASSIFIER_VERSION
    due = version_moved or age_days is None or age_days > ROUND_MAX_AGE_DAYS
    return {"feed": "incident_precision", "classifier_version": CLASSIFIER_VERSION,
            "last_scored_version": last_ver, "last_scored_at": last_at,
            "age_days": age_days, "round_due": due,
            "reason": ("classifier version moved (or last round's version "
                       "unrecorded)" if version_moved
                       else "no scored round on file" if age_days is None
                       else f"last round {age_days}d old" if due else "")}


def review_gold_contract() -> dict:
    """P2-A.3: every version against its gold set, the verdict beside the number."""
    from ops.gold_contract import contract
    return {"feed": "gold_contract", **contract()}


REVIEWERS = (review_fuel, review_palhub_roads, review_precision_rounds,
             review_gold_contract)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only", choices=[fn.__name__.removeprefix("review_") for fn in REVIEWERS],
                    help="with --dry: run one reviewer and look, recording nothing")
    a = ap.parse_args()
    if a.only and not a.dry:
        # A partial week in the ledger would read as reviewers that vanished.
        ap.error("--only is for looking: use it with --dry")

    results = []
    # One failing reviewer must not silence the others — each is recorded,
    # errors included, because "the review broke" is itself worth an entry.
    for fn in REVIEWERS:
        if a.only and fn.__name__ != f"review_{a.only}":
            continue
        try:
            results.append(fn())
        except Exception as exc:                                # noqa: BLE001
            results.append({"feed": fn.__name__, "error": f"{type(exc).__name__}: {exc}"})

    record = {"ts": datetime.now(timezone.utc).isoformat(), "results": results}
    print(json.dumps(record, indent=2, ensure_ascii=False, default=str))
    gold = next((r for r in results if r.get("feed") == "gold_contract" and "entries" in r), None)
    if gold:
        # The same verdicts in the form a human reads in the journal: a version
        # below its gate is a line that says NOT SERVABLE, with its number.
        from ops.gold_contract import table
        print(table(gold))
    if a.dry:
        return 0

    with LEDGER.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    from ops.notify import send
    for r in results:
        if r.get("gate_crossed"):
            send(f"📊 {r['feed']} crossed its promotion gate over the trailing "
                 f"{r['trailing_days']}d — worth a human look. Details in "
                 f"ops/measure-review.ndjson. Nothing was auto-promoted.")
    rot = next((r for r in results if r.get("round_due")), None)
    if rot:
        from ops.alert import raise_alert
        raise_alert("measure-review",
                    f"incident precision round DUE: {rot['reason']} "
                    f"(classifier v{rot['classifier_version']}, last scored "
                    f"{rot['last_scored_at'] or 'never'}). Draw with: "
                    f".venv/bin/python -m learn.incident_precision --sample")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
