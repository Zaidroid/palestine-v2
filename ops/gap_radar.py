"""The gap radar — where the record thins, measured, ranked, every night.

Born from the June-9 lesson (2026-08-06): the flagship casualty series froze
for 57 days while every mtime looked fresh, because freshness was measured on
FILES instead of on the data's own dates. This instrument measures the four
ways the databank can quietly rot, and ranks what it finds:

  1. FRESHNESS — per dataset, age of the last *information* day (not the last
     padding row, not a file mtime) against the series' OWN learned rhythm:
     the median gap between its distinct observation days. A series that
     publishes weekly is not "stale" at 6 days; one that publishes daily is.
     Dead upstreams are declared with evidence, excused, and still listed.
  2. HOLES — inside each day-grained series, the largest silent gap relative
     to its rhythm (a 30-day hole in a daily series is a wound; a 300-day gap
     in an annual series is Tuesday).
  3. ERAS — the category × era coverage grid, 1922 → today: where the record
     of Palestine simply has no shelf.
  4. FETCH HEALTH — the supply lines: v1's per-step refresh outcomes (FAIL
     streaks from refresh-events.ndjson) and v2's own fetch artifacts (raw
     tree ages) — the layer where June-9 actually broke.

  5. SUPPLY LINES (P1-B.3, 2026-09-25) — every nightly fetch judged as a line
     that feeds named datasets. A line is DEAD when its last three attempts
     failed, when it has stopped attempting at all, or when a dataset it feeds
     has stalled (data older than twice its allowance, the allowance being
     three times its learned rhythm). A v1 step is dead the same way unless it
     is declared RETIRED with its successor named. A dead line FAILS the
     nightly job: this module exits 5 and ops/databank-sync.sh runs it through
     ops/with-heartbeat.sh and exits non-zero, so systemd's OnFailure alarm
     pages (ops/alert.py) — the path every other job uses.

     Why: on 2026-09-25 four v1 fetches had failed 31 nights in a row, eight
     more 29, and the headline read "27 fresh of 32" — because the datasets
     they fed were judged on a 730-day allowance and the failures were a
     severity-3 line nobody was paged for. A dataset whose line is dead is
     now `supply_dead`, never `fresh`.

Output: data/gap-radar.json (served at /v2/databank/radar, read by the
Monday maintenance run) + a human table on stdout.

Exit: 0 every line alive · 5 at least one dead supply line (the job fails) ·
      1 the radar itself broke (the job fails too — an unjudged night is not
      a green one).

Run: .venv/bin/python -m ops.gap_radar
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from resolve.db import connect
from resolve.db import v1_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gap-radar.json"
V1_EVENTS = v1_path("public/data/refresh-events.ndjson")
V2_EVENTS = ROOT / "ops" / "fetch-events.ndjson"   # ops/fetchlib.py's ledger
V1_T4P_RAW = v1_path("public/data/tech4palestine")

# ── declarations: the radar's reviewable knowledge, never guessed ────────────

# Upstreams that died, with evidence. Excused from STALLED, still reported.
DEAD_UPSTREAM = {
    "v1_aid_access_unrwa_aid_trucks":
        "UNRWA ceased publishing aid-truck data 2025-01-16 (operational ban).",
    "v1_infrastructure_tech4palestine":
        "T4P's infrastructure-damaged series ended 2025-10-05 — verified "
        "against their live API 2026-08-06; UNOSAT and the unified infra "
        "sources carry the category forward.",
}

# Closed corpora: history, not feeds. Age is meaningless; only HOLES and the
# era grid speak for them.
CLOSED_CORPUS = {
    "v1_historical_palopenmaps",
}

# Datasets whose series another dataset CONTINUES. Their age stops mattering
# on the day the successor takes over; the successor is judged instead, and
# if the successor stalls the radar reports that. Measured, not asserted:
# the successor's first day must follow the predecessor's last, checked below.
CONTINUED_BY = {
    # v1 stopped refreshing the Gaza series at 2026-08-08; conflict_gaza.yaml
    # reads the same publisher (T4P) from 2026-08-09 (F-12, 2026-09-23).
    "v1_conflict_tech4palestine": "t4p_gaza_daily",
}

# Rhythm overrides where the learned median would mislead (annual releases
# that arrive in one batch, registers whose dates are disclaimed).
ALLOWANCE_OVERRIDE_DAYS = {
    # Annual/year-labeled series: age is measured from the period LABEL
    # (2025 data is stamped 2025-01-01), so a healthy annual series reads
    # ~550d old the day before its next release. 730 = one missed release.
    "v1_conflict_ucdp": 730,
    "v1_health_who": 730,
    "v1_pcbs_pcbs": 730,
    "v1_settlements_peacenow": 730,
    "v1_casualties_ocha_casualties": 730,
    "who_gho_wash": 1200,             # JMP labels are biennial: 2024-label
                                      #   data ages ~1100d before the next
    "v1_martyrs_snapshot_2023_tech4palestine": 90,  # roster update cadence
    "v1_conflict_t4p_westbank": 30,   # OCHA flash updates: ~weekly-biweekly;
                                      #   learned 1d rhythm is the kept-run
                                      #   artifact, not the publish cadence
}

# Event-recording series: silence can mean "no events", not "feed died".
# They get a wide allowance and the note travels with the status.
EVENT_DRIVEN = {
    "v1_refugees_idmc": 90,           # displacement events
    "v1_infrastructure_unosat": 540,  # damage assessments after major events
    "v1_connectivity_ioda": 30,       # outage detections
}

# v1 refresh steps whose FAIL is an artifact, not a wound — excluded from
# the gap list, kept visible in fetch_health with the reason.
BENIGN_STEPS = {
    "docker-restart-api": "ExecStartPost restarts the container for real; "
                          "the in-container docker call always fails",
}

# Notes for failing v1 steps the project has already diagnosed. A step that is
# RETIRED (below) carries its successor instead.
STEP_NOTES = {
    "validate": "v1's own validation step (validate-data.js, 25 min a night)",
}

# ── supply lines (P1-B.3) ────────────────────────────────────────────────────
# Consecutive not-ok attempts that make a line dead. The same three the
# watchdog's fetch family uses (ops/watchdog.py FETCH_FAIL_STREAK), so the
# nightly job and the ten-minute watchdog never disagree about a line.
FAIL_STREAK = 3

# v2's own fetchers, by the labels they write to ops/fetch-events.ndjson, and
# the datasets each one feeds. `replaces` names the v1 step the line took
# over; `successor` is who carries the series if the line is ever declared
# dead (`declared_dead: "<evidence>"`), which excuses it from failing the job.
# ops/fetch_gho_wash.py writes no ledger line; the raw-artifact age below
# judges it.
SUPPLY_LINES = {
    "t4p": {"labels": ["t4p:gaza_daily", "t4p:westbank_daily",
                       "t4p:killed_in_gaza", "t4p:summary"],
            "feeds": ["t4p_gaza_daily", "v1_conflict_t4p_westbank",
                      "v1_martyrs_snapshot_2023_tech4palestine"],
            "fetcher": "ops/fetch_t4p.py", "every_days": 1},
    "ooni": {"labels": ["ooni:ps_daily"], "feeds": ["v1_connectivity_ooni"],
             "fetcher": "ops/fetch_ooni.py", "every_days": 1},
    "ioda": {"labels": ["ioda:outages"], "feeds": ["v1_connectivity_ioda"],
             "fetcher": "ops/fetch_ioda.py", "every_days": 1},
    "ocha-casualties": {"labels": ["ocha:casualties"],
                        "feeds": ["v1_casualties_ocha_casualties"],
                        "fetcher": "ops/fetch_ocha.py", "every_days": 1,
                        "replaces": "ocha-casualties"},
    "ocha-demolitions": {"labels": ["ocha:demolitions"],
                         "feeds": ["v1_demolitions_ocha_demolitions"],
                         "fetcher": "ops/fetch_ocha.py", "every_days": 1,
                         "replaces": "ocha-demolitions"},
    "pcbs-direct": {"labels": ["pcbs:population", "pcbs:cpi"],
                    "feeds": ["v1_economic_pcbs_direct"],
                    "fetcher": "ops/fetch_pcbs.py", "every_days": 1,
                    "replaces": "pcbs-indicators",
                    "note": "pcbs_poverty_rate has no source on PCBS's rebuilt "
                            "site; its 2 held rows are not refreshed"},
    "hamoked": {"labels": ["hamoked:detention"],
                "feeds": ["v1_prisoners_hamoked"],
                "fetcher": "ops/fetch_hamoked.py", "every_days": 1,
                "replaces": "hamoked-detention",
                "successor": "Addameer (v1_prisoners_addameer, via v1's "
                             "`prisoners` step): total and administrative "
                             "detention, 2022 onward"},
    "unrwa-registered": {"labels": ["unrwa:registered"],
                         "feeds": ["unrwa_registered_hdx"],
                         "fetcher": "ops/fetch_unrwa_registered.py", "every_days": 1,
                         "note": "UNRWA's quarterly HDX release; the file holds one "
                                 "quarter, the databank keeps every one it has seen"},
}

# v1 refresh steps that are RETIRED: a successor carries what they did, so
# their failure is not a dead supply line. They stay listed — with the
# successor, and as `retired_pending` while v1 keeps running them — until the
# line is removed from v1's refresh-data.sh (docs/HANDS-2026-09-24.md §9,
# Zaid's hand: v1 is live production and is never edited from here).
RETIRED_V1_STEPS = {
    "ocha-casualties": "v2 supply line ocha-casualties (ops/fetch_ocha.py)",
    "ocha-demolitions": "v2 supply line ocha-demolitions (ops/fetch_ocha.py)",
    "pcbs-indicators": "v2 supply line pcbs-direct (ops/fetch_pcbs.py)",
    "hamoked-detention": "v2 supply line hamoked (ops/fetch_hamoked.py)",
    "databank-martyrs": "v2 Tier 2 databank (martyrs_snapshot_2023, from T4P)",
    "databank-btselem": "v2 Tier 2 databank (v1's people-killed backfill; the "
                        "B'Tselem register is a letter, not a feed)",
    "databank-gaza": "v2 Tier 2 databank (conflict_gaza, from T4P)",
    "databank-prisoners": "v2 Tier 2 databank (prisoners + prisoners_hamoked)",
    "databank-ucdp-actions": "v2 Tier 2 databank (UCDP events, migration 083)",
    "databank-structures": "v2 Tier 2 databank (infrastructure)",
    "databank-incidents": "v2 Tier 2 databank (v1's Insecurity Insight backfill)",
    "learn-corrections": "v2's accuracy loop (ops/measure_review.py, learn/)",
    "validate": "v2's spec floors, identity invariant and this radar — the "
                "loader refuses what validate-data.js only reported",
    "docker-restart-api": "palestine-refresh.service's ExecStartPost (the "
                          "in-container docker call never worked)",
}

# Exit code for "found at least one dead supply line": the job must fail.
DEAD_EXIT = 5

# Datasets whose occurred_at is disclaimed (precision=unknown registers):
# freshness runs on ingest recency instead, and says so.
REGISTER_BASIS = "register (occurred_at disclaimed; age = last ingest)"

# Fill paths for gaps the project has already scoped. Everything else gets
# honest "unscoped".
FILL_PATHS = {
    "v1_casualties_ocha_casualties": "v2 fetch ops/fetch_ocha.py (supply line "
                                     "ocha-casualties) — read that line in "
                                     "supply_lines first.",
    "v1_demolitions_ocha_demolitions": "v2 fetch ops/fetch_ocha.py (supply "
                                       "line ocha-demolitions).",
    "v1_food_wfp": "WFP price data usually lands monthly; check the HDX "
                   "dataset revision if LATE persists.",
    "v1_aid_access_unrwa_aid_trucks": "dead; a successor series would need "
                                      "OCHA aid-tracking or COGAT data — "
                                      "unscoped.",
    "v1_economic_pcbs_direct": "v2 fetch ops/fetch_pcbs.py (supply line "
                               "pcbs-direct); poverty has no source.",
    "v1_prisoners_hamoked": "v2 fetch ops/fetch_hamoked.py (supply line "
                            "hamoked); successor if it dies: Addameer.",
    "v1_conflict_tech4palestine": "fix installed 2026-08-06, heals via the "
                                  "02:35→03:41 chain — if this is still "
                                  "stalled after 2026-08-07, the container "
                                  "copy was lost (recreate re-copies, see "
                                  "task #55).",
    "v1_connectivity_ooni": "v2 fetch ops/fetch_ooni.py (supply line ooni).",
}

ERAS = [
    ("1922–1947", "1922-01-01", "1947-12-31"),
    ("1948–1966", "1948-01-01", "1966-12-31"),
    ("1967–1999", "1967-01-01", "1999-12-31"),
    ("2000–2009", "2000-01-01", "2009-12-31"),
    ("2010 – Oct 2023", "2010-01-01", "2023-10-06"),
    ("Oct 2023 → today", "2023-10-07", "2100-01-01"),
]


def measure_datasets(cur, today: date) -> list[dict]:
    cur.execute("""
        SELECT d.dataset_id, d.key, d.v1_category, s.key, s.license_spdx,
               s.commercial_use
        FROM dataset d JOIN source s ON s.source_id = d.source_id
        WHERE d.v1_category IS NOT NULL ORDER BY d.key""")
    metas = cur.fetchall()
    out = []
    # A successor counts only if it really picks up where the predecessor
    # stopped: its first day is within 3 days after the predecessor's last,
    # and it holds current rows at all. Otherwise the predecessor is judged
    # as before, and a broken hand-over stays visible.
    continued_ok = set()
    for old_key, new_key in CONTINUED_BY.items():
        cur.execute("""
            SELECT (max(o.occurred_at) FILTER (WHERE d.key = %s))::date,
                   (min(o.occurred_at) FILTER (WHERE d.key = %s))::date
              FROM observation o JOIN dataset d USING (dataset_id)
             WHERE d.key IN (%s, %s) AND upper_inf(o.sys_period)""",
                    (old_key, new_key, old_key, new_key))
        last_old, first_new = cur.fetchone()
        if last_old and first_new and 0 < (first_new - last_old).days <= 3:
            continued_ok.add(new_key)
    for ds_id, key, cat, src, lic, comm in metas:
        cur.execute("""
            SELECT count(*), min(occurred_at)::date, max(occurred_at)::date,
                   count(DISTINCT occurred_at::date),
                   mode() WITHIN GROUP (ORDER BY occurred_precision::text),
                   max(coalesce(reported_at, ingested_at))::date
            FROM observation WHERE dataset_id = %s AND upper_inf(sys_period)""",
            (ds_id,))
        n, lo, hi, days, prec, last_touch = cur.fetchone()
        if not n:
            continue
        # the series' own rhythm + its largest internal hole
        cur.execute("""
            WITH d AS (SELECT DISTINCT occurred_at::date AS dt
                       FROM observation
                       WHERE dataset_id = %s AND upper_inf(sys_period)),
            g AS (SELECT dt, dt - lag(dt) OVER (ORDER BY dt) AS gap FROM d)
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY gap),
                   max(gap),
                   (SELECT dt FROM g WHERE gap = (SELECT max(gap) FROM g)
                    LIMIT 1)
            FROM g WHERE gap IS NOT NULL""", (ds_id,))
        med, maxgap, hole_end = cur.fetchone() or (None, None, None)

        basis, last_info = "data dates", hi
        if prec == "unknown":
            basis, last_info = REGISTER_BASIS, last_touch
        age = (today - last_info).days if last_info else None

        if key in ALLOWANCE_OVERRIDE_DAYS:
            allowance = ALLOWANCE_OVERRIDE_DAYS[key]
        elif key in EVENT_DRIVEN:
            allowance = EVENT_DRIVEN[key]
        elif med:
            allowance = max(int(3 * med), 7)
        else:
            allowance = 90
        if key in DEAD_UPSTREAM:
            status = "dead_upstream"
        elif key in CLOSED_CORPUS:
            status = "closed_corpus"
        elif key in CONTINUED_BY and CONTINUED_BY[key] in continued_ok:
            status = "continued"
        elif age is None:
            status = "unmeasured"
        elif age <= allowance:
            status = "fresh"
        elif age <= 2 * allowance:
            status = "late"
        else:
            status = "stalled"

        hole = None
        if med and maxgap and days and days > 30 and maxgap >= 6 * max(med, 1) \
                and maxgap >= 14 and status not in ("closed_corpus",):
            hole = {"days": int(maxgap),
                    "ended": str(hole_end),
                    "rhythm_days": float(med)}

        out.append({
            "dataset": key, "category": cat, "source": src,
            "license": lic, "commercial": comm,
            "rows": n, "span": [str(lo), str(hi)],
            "distinct_days": days, "precision": prec,
            "rhythm_median_days": float(med) if med else None,
            "freshness_basis": basis,
            "last_information_day": str(last_info) if last_info else None,
            "age_days": age, "allowance_days": allowance,
            "status": status,
            "event_driven": key in EVENT_DRIVEN,
            "dead_reason": DEAD_UPSTREAM.get(key),
            "largest_hole": hole,
        })
    return out


def measure_eras(cur) -> dict:
    grid: dict[str, dict[str, int]] = defaultdict(dict)
    for label, lo, hi in ERAS:
        cur.execute("""
            SELECT d.v1_category, count(*)
            FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
            WHERE d.v1_category IS NOT NULL AND upper_inf(o.sys_period)
              AND o.occurred_at >= %s AND o.occurred_at <= %s
            GROUP BY 1""", (lo, hi + " 23:59:59"))
        for cat, n in cur.fetchall():
            grid[cat][label] = n
        cur.execute("""
            SELECT count(*) FROM event
            WHERE attrs ? 'v1_stable_id' AND upper_inf(sys_period)
              AND occurred_at >= %s AND occurred_at <= %s""",
            (lo, hi + " 23:59:59"))
        n = cur.fetchone()[0]
        if n:
            grid["(events)"][label] = n
    return {cat: {label: vals.get(label, 0) for label, _, _ in ERAS}
            for cat, vals in sorted(grid.items())}


def measure_fetch_health(today: date) -> list[dict]:
    out = []
    # v1's per-step outcomes: current FAIL streak in consecutive runs
    if V1_EVENTS.exists():
        runs: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for line in V1_EVENTS.read_text().splitlines()[-4000:]:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            runs[e["label"]].append((e["at"], e["outcome"]))
        for label, hist in sorted(runs.items()):
            hist.sort()
            streak = 0
            for _, outcome in reversed(hist):
                if outcome == "FAIL":
                    streak += 1
                else:
                    break
            if streak:
                out.append({"line": f"v1 step {label}", "step": label,
                            "kind": "v1_refresh",
                            "fail_streak": streak, "last_at": hist[-1][0],
                            "benign": BENIGN_STEPS.get(label),
                            "retired_to": RETIRED_V1_STEPS.get(label),
                            "note": STEP_NOTES.get(label)})
    # v2-native fetch artifacts: file age at the RAW layer — the June-9 class
    for name, path, allowance in [
        # v2's own T4P fetch (ops/fetch_t4p.py). Until 2026-09-23 this line
        # watched v1's tree, which v2 stopped reading for T4P on 2026-08-08,
        # so it reported a 45-day-old file at severity 5 while the file v2
        # actually loads was refreshed every night.
        ("t4p raw casualties (v2-native fetch)",
         ROOT / "data" / "raw" / "tech4palestine" / "gaza_daily.json", 3),
        ("gho wash (v2-native fetch)", ROOT / "data" / "gho" / "wash_pse.json", 3),
        # The as_of evidence base. If this stops growing, the history layer
        # keeps answering and quietly stops being provable — the exact class
        # of silent failure this radar exists to catch.
        ("as_of evidence: v2 loader inputs",
         ROOT / "data" / "evidence" / "v2-manifest.json", 2),
        ("as_of evidence: vaulted v1 snapshots",
         ROOT / "data" / "evidence" / "manifest.json", 400),
    ]:
        try:
            if path.is_dir():
                mtime = max(p.stat().st_mtime for p in path.glob("*.json"))
            else:
                mtime = path.stat().st_mtime
            age = (today - date.fromtimestamp(mtime)).days
            out.append({"line": name, "kind": "raw_artifact",
                        "age_days": age, "allowance_days": allowance,
                        "status": "fresh" if age <= allowance else "stalled"})
        except (OSError, ValueError):
            out.append({"line": name, "kind": "raw_artifact",
                        "status": "missing"})
    return out


def _when(s: str) -> datetime:
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def read_events(path: Path, limit: int = 20000) -> dict[str, list[dict]]:
    """A fetch ledger (v2's ops/fetch-events.ndjson or v1's refresh-events)
    as label → attempts, oldest first. Both write {label, at, outcome}; v2
    says "ok", v1 says "OK" — anything else is a failed attempt."""
    if not path.exists():
        return {}
    by: dict[str, list[dict]] = defaultdict(list)
    for line in path.read_text(errors="replace").splitlines()[-limit:]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or not e.get("label") or not e.get("at"):
            continue
        out = str(e.get("outcome", ""))
        by[e["label"]].append({"at": e["at"], "outcome": out,
                               "ok": out.lower() == "ok"})
    for v in by.values():
        v.sort(key=lambda a: _when(a["at"]))
    return dict(by)


def judge_attempts(attempts: list[dict], now: datetime,
                   every_days: float = 1) -> dict:
    """One feed's verdict from its own attempts.

    dead     FAIL_STREAK consecutive failures, or no attempt at all for
             FAIL_STREAK × its cadence (the fetcher stopped being run — the
             June-9 class: nothing fails because nothing runs), or never
             attempted.
    failing  one or two failures at the tail — reported, not yet dead.
    live     the last attempt worked.
    """
    if not attempts:
        return {"status": "dead", "why": "never fetched — no attempt on record",
                "fail_streak": 0, "last_ok": None, "last_attempt": None,
                "attempts": 0}
    streak = 0
    for a in reversed(attempts):
        if a["ok"]:
            break
        streak += 1
    last = attempts[-1]
    silent = (now - _when(last["at"])).total_seconds() / 86400
    v = {"fail_streak": streak, "attempts": len(attempts),
         "last_attempt": last["at"], "last_outcome": last["outcome"],
         "last_ok": max((a["at"] for a in attempts if a["ok"]),
                        key=_when, default=None)}
    if streak >= FAIL_STREAK:
        return {**v, "status": "dead",
                "why": f"{streak} consecutive attempts failed "
                       f"(last: {last['outcome']}, {last['at'][:10]})"}
    if silent > FAIL_STREAK * every_days:
        return {**v, "status": "dead",
                "why": f"no attempt for {silent:.1f} days — the fetcher is "
                       "not being run"}
    if streak:
        return {**v, "status": "failing",
                "why": f"{streak} failed attempt(s), fewer than {FAIL_STREAK}"}
    return {**v, "status": "live", "why": None}


def judge_supply_lines(v2_events: dict, v1_events: dict,
                       datasets: list[dict], now: datetime) -> dict:
    """Every line that feeds the databank, judged — and which ones are dead.

    Returns {"v2": [...], "v1_steps": [...], "data": [...], "dead": [...]}:
    `dead` is the list the nightly job fails on. A v2 line is dead when any
    of its feeds is, or when a dataset it feeds has stalled; a v1 step is
    dead unless it is RETIRED (successor named) or BENIGN; a stalled dataset
    that no declared line feeds is a dead line of its own ("data").
    """
    status_of = {d["dataset"]: d["status"] for d in datasets}
    fed = set()
    v2 = []
    for name, decl in SUPPLY_LINES.items():
        every = decl.get("every_days", 1)
        feeds = [dict(label=lab, **judge_attempts(v2_events.get(lab, []), now,
                                                  every))
                 for lab in decl["labels"]]
        fed |= set(decl.get("feeds", []))
        stalled = [k for k in decl.get("feeds", [])
                   if status_of.get(k) == "stalled"]
        why = ([f"{f['label']}: {f['why']}" for f in feeds
                if f["status"] == "dead"]
               + [f"{k}: data stalled (older than twice its allowance)"
                  for k in stalled])
        if decl.get("declared_dead"):
            status = "declared_dead"
        elif why:
            status = "dead"
        elif any(f["status"] == "failing" for f in feeds):
            status = "failing"
        else:
            status = "live"
        v2.append({"line": name, "kind": "v2_fetch", "status": status,
                   "why": "; ".join(why) or None,
                   "fetcher": decl.get("fetcher"),
                   "feeds": decl.get("feeds", []),
                   "replaces_v1_step": decl.get("replaces"),
                   "successor": decl.get("successor"),
                   "declared_dead": decl.get("declared_dead"),
                   "note": decl.get("note"),
                   "labels": feeds})
    v1 = []
    for step, attempts in sorted(v1_events.items()):
        verdict = judge_attempts(attempts, now, 1)
        still_run = (now - _when(attempts[-1]["at"])).days < FAIL_STREAK
        if step in RETIRED_V1_STEPS:
            # Excused because a successor carries it — never because it works.
            status = "retired_pending" if still_run else "retired"
        elif step in BENIGN_STEPS and verdict["status"] != "live":
            status = "benign"
        else:
            status = verdict["status"]
        v1.append({"line": f"v1 step {step}", "step": step, "kind": "v1_step",
                   "status": status, "why": verdict["why"],
                   "fail_streak": verdict["fail_streak"],
                   "last_attempt": verdict["last_attempt"],
                   "last_ok": verdict["last_ok"],
                   "successor": RETIRED_V1_STEPS.get(step),
                   "benign": BENIGN_STEPS.get(step),
                   "note": STEP_NOTES.get(step)})
    data = [{"line": f"data {d['dataset']}", "kind": "data", "status": "dead",
             "why": f"stalled: last information {d['last_information_day']}, "
                    f"{d['age_days']}d old against a {d['allowance_days']}d "
                    "allowance — whatever feeds it has stopped delivering",
             "feeds": [d["dataset"]]}
            for d in datasets
            if d["status"] == "stalled" and d["dataset"] not in fed]
    dead = [x for x in v2 + v1 + data if x["status"] == "dead"]
    return {"v2": v2, "v1_steps": v1, "data": data, "dead": dead}


def apply_supply(datasets: list[dict], supply: dict) -> None:
    """A dataset fed by a dead line is `supply_dead`, never `fresh`: its age
    can look fine for months (a 730-day allowance) while nothing arrives."""
    line_of = {}
    for line in supply["v2"]:
        for k in line["feeds"]:
            line_of[k] = line
    for d in datasets:
        line = line_of.get(d["dataset"])
        if not line:
            continue
        d["supply_line"] = line["line"]
        if line["status"] == "dead" and d["status"] in ("fresh", "late"):
            d["status"] = "supply_dead"
            d["supply_why"] = line["why"]


def supply_counts(supply: dict) -> dict:
    def n(rows, st):
        return sum(1 for r in rows if r["status"] == st)
    v2, v1 = supply["v2"], supply["v1_steps"]
    return {"v2_lines": len(v2), "v2_live": n(v2, "live"),
            "v2_failing": n(v2, "failing"), "v2_dead": n(v2, "dead"),
            "v2_declared_dead": n(v2, "declared_dead"),
            "v1_steps": len(v1), "v1_live": n(v1, "live"),
            "v1_failing": n(v1, "failing"), "v1_dead": n(v1, "dead"),
            "v1_retired_pending": n(v1, "retired_pending"),
            "v1_retired": n(v1, "retired"), "v1_benign": n(v1, "benign"),
            "stalled_data_lines": len(supply["data"]),
            "dead": len(supply["dead"])}


def rank_gaps(datasets, fetch_health, supply: dict | None = None) -> list[dict]:
    gaps = []
    for d in datasets:
        if d["status"] == "stalled":
            gaps.append({
                "severity": 4, "kind": "freshness", "subject": d["dataset"],
                "measure": f"last information {d['last_information_day']} — "
                           f"{d['age_days']}d old against a "
                           f"{d['allowance_days']}d allowance "
                           f"(rhythm ≈ {d['rhythm_median_days']}d)",
                "fill_path": FILL_PATHS.get(d["dataset"], "unscoped — chase "
                             "the upstream before assuming it died"),
            })
        elif d["status"] == "late":
            note = (" (event-recording series — silence may mean no events)"
                    if d.get("event_driven") else "")
            gaps.append({
                "severity": 2, "kind": "freshness", "subject": d["dataset"],
                "measure": f"{d['age_days']}d old, allowance "
                           f"{d['allowance_days']}d — watch, don't panic"
                           + note,
                "fill_path": FILL_PATHS.get(d["dataset"], "recheck next run"),
            })
        elif d["status"] == "dead_upstream":
            gaps.append({
                "severity": 1, "kind": "dead_upstream",
                "subject": d["dataset"],
                "measure": d["dead_reason"],
                "fill_path": FILL_PATHS.get(d["dataset"], "successor source "
                             "unscoped"),
            })
        if d["largest_hole"]:
            h = d["largest_hole"]
            gaps.append({
                "severity": 2, "kind": "hole", "subject": d["dataset"],
                "measure": f"{h['days']}-day silent gap ending {h['ended']} "
                           f"in a series with a {h['rhythm_days']:.0f}d rhythm",
                "fill_path": "check bronze + upstream archive for that window",
            })
    # Dead supply lines: the gaps the nightly job FAILS on (P1-B.3). A v1
    # step's streak used to be a severity-3 line here that nobody was paged
    # for; it is judged in judge_supply_lines now, with retired steps excused
    # only by a named successor.
    for line in (supply or {}).get("dead", []):
        gaps.append({
            "severity": 5, "kind": "supply", "subject": line["line"],
            "measure": line["why"] or "dead",
            "fill_path": (f"run {line['fetcher']} by hand and read its error"
                          + (f"; successor if it cannot be revived: "
                             f"{line['successor']}" if line.get("successor")
                             else "")
                          if line.get("fetcher") else
                          "fix the step in v1, or declare it retired with its "
                          "successor in ops/gap_radar.py RETIRED_V1_STEPS"),
        })
    for f in fetch_health:
        if f.get("kind") == "v1_refresh":
            continue                      # judged as a supply line above
        if f.get("status") == "stalled":
            gaps.append({
                "severity": 5, "kind": "fetch", "subject": f["line"],
                "measure": f"raw artifact {f['age_days']}d old against "
                           f"{f['allowance_days']}d — the June-9 failure "
                           "class, at the layer where it actually breaks",
                "fill_path": "the fetcher behind this artifact stopped — "
                             "chase it TODAY",
            })
        elif f.get("status") == "missing":
            gaps.append({
                "severity": 4, "kind": "fetch", "subject": f["line"],
                "measure": "raw artifact missing entirely",
                "fill_path": "run the fetcher by hand and read its error",
            })
    return sorted(gaps, key=lambda g: -g["severity"])


def headline(today, c: dict) -> list[str]:
    """The two lines a human reads first. Every failure is COUNTED here — a
    retired v1 step that still fails inside v1 is said, not folded into
    'fresh' (the 2026-09-25 headline read '27 fresh of 32' over twelve
    supply lines that had failed for a month)."""
    s = c["supply_lines"]
    return [
        f"gap radar {today}: {c['datasets']} datasets — "
        f"{c['fresh']} fresh · {c['late']} late · {c['stalled']} stalled · "
        f"{c['supply_dead']} supply-dead · "
        f"{c['dead_upstream']} dead-upstream · {c['closed_corpus']} closed · "
        f"{c['continued']} continued",
        f"supply lines: {s['dead']} DEAD · v2 fetches {s['v2_live']}/"
        f"{s['v2_lines']} live ({s['v2_failing']} failing, {s['v2_dead']} dead)"
        f" · v1 steps {s['v1_live']}/{s['v1_steps']} live ({s['v1_dead']} dead,"
        f" {s['v1_failing']} failing, {s['v1_retired_pending']} retired but "
        f"still run and fail in v1 until HANDS §9, {s['v1_retired']} retired, "
        f"{s['v1_benign']} benign) · {s['stalled_data_lines']} stalled "
        "datasets with no declared line"]


def main() -> int:
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    with connect() as conn, conn.cursor() as cur:
        datasets = measure_datasets(cur, today)
        eras = measure_eras(cur)
    fetch_health = measure_fetch_health(today)
    supply = judge_supply_lines(read_events(V2_EVENTS),
                                read_events(V1_EVENTS, limit=4000),
                                datasets, now)
    apply_supply(datasets, supply)
    gaps = rank_gaps(datasets, fetch_health, supply)

    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "method": "freshness on the data's own dates vs each series' median "
                  "rhythm (3x allowance, declared exceptions); holes vs "
                  "rhythm; era grid; fetch-layer artifact ages; supply lines "
                  f"judged on their own attempts ({FAIL_STREAK} failures in a "
                  "row, or silence, or a stalled dataset = dead)",
        "counts": {
            "datasets": len(datasets),
            "fresh": sum(1 for d in datasets if d["status"] == "fresh"),
            "late": sum(1 for d in datasets if d["status"] == "late"),
            "stalled": sum(1 for d in datasets if d["status"] == "stalled"),
            "supply_dead": sum(1 for d in datasets
                               if d["status"] == "supply_dead"),
            "dead_upstream": sum(1 for d in datasets
                                 if d["status"] == "dead_upstream"),
            "closed_corpus": sum(1 for d in datasets
                                 if d["status"] == "closed_corpus"),
            "continued": sum(1 for d in datasets if d["status"] == "continued"),
            "open_gaps": len(gaps),
            "supply_lines": supply_counts(supply),
        },
        "datasets": datasets,
        "era_grid": eras,
        "fetch_health": fetch_health,
        "supply_lines": supply,
        "gaps": gaps,
    }
    # A dataset that stalled since the last radar is named (audit F275). It
    # is also a dead supply line, so it fails the job below.
    def _key(d):
        return d.get("dataset") or d.get("key") or d.get("name")
    prev_stalled: set = set()
    try:
        prev = json.loads(OUT.read_text())
        prev_stalled = {_key(d) for d in prev.get("datasets", []) if d.get("status") == "stalled"}
    except (OSError, ValueError):
        pass
    now_stalled = {_key(d) for d in datasets if d.get("status") == "stalled"}
    report["newly_stalled"] = sorted(x for x in (now_stalled - prev_stalled) if x)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    tmp.replace(OUT)

    for line in headline(today, report["counts"]):
        print(line)
    for g in gaps[:12]:
        print(f"  [{g['severity']}] {g['kind']:<12} {g['subject']:<44} "
              f"{g['measure'][:80]}")
    print(f"→ {OUT}")
    if report["newly_stalled"]:
        print("NEWLY STALLED:", ", ".join(report["newly_stalled"]))
    if supply["dead"]:
        print(f"DEAD SUPPLY LINES ({len(supply['dead'])}): "
              + "; ".join(f"{x['line']} — {x['why']}" for x in supply["dead"]),
              file=sys.stderr)
        return DEAD_EXIT
    return 0


if __name__ == "__main__":
    sys.exit(main())
