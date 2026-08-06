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

Output: data/gap-radar.json (served at /v2/databank/radar, read by the
Monday maintenance run) + a human table on stdout.

Run: .venv/bin/python -m ops.gap_radar
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from resolve.db import connect

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gap-radar.json"
V1_EVENTS = Path("/opt/stacks/palestine/public/data/refresh-events.ndjson")
V1_T4P_RAW = Path("/opt/stacks/palestine/public/data/tech4palestine")

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

# Notes for failing v1 steps the project has already diagnosed.
STEP_NOTES = {
    "ocha-casualties": "no HDX mirror exists (measured 2026-08-06) — fix "
                       "v1's scraper or accept annual staleness",
    "ocha-demolitions": "same: scraper down, no open mirror anywhere",
    "pcbs-indicators": "PCBS direct (CC-BY, verified) is the re-source path",
    "hamoked-detention": "site fetch failing; prisoners still flow via "
                         "Addameer",
    "validate": "v1's own validation step — v1 maintenance backlog",
    "learn-corrections": "v1 internal; superseded by v2's accuracy loop",
    "databank-martyrs": "v1's internal databank backfills — superseded by "
                        "v2 Tier 2; fix or retire in v1",
    "databank-btselem": "superseded by v2 Tier 2; fix or retire in v1",
    "databank-gaza": "superseded by v2 Tier 2; fix or retire in v1",
    "databank-incidents": "superseded by v2 Tier 2; fix or retire in v1",
    "databank-prisoners": "superseded by v2 Tier 2; fix or retire in v1",
    "databank-structures": "superseded by v2 Tier 2; fix or retire in v1",
    "databank-ucdp-actions": "superseded by v2 Tier 2; fix or retire in v1",
}

# Datasets whose occurred_at is disclaimed (precision=unknown registers):
# freshness runs on ingest recency instead, and says so.
REGISTER_BASIS = "register (occurred_at disclaimed; age = last ingest)"

# Fill paths for gaps the project has already scoped. Everything else gets
# honest "unscoped".
FILL_PATHS = {
    "v1_casualties_ocha_casualties": "v1's ocha-casualties scraper FAILs nightly; no HDX "
                          "mirror exists (measured 2026-08-06). Fix the "
                          "scraper in v1 or accept annual staleness.",
    "v1_demolitions_ocha_demolitions": "same as casualties: scraper down, no open mirror "
                           "anywhere (Peace Now unlicensed, B'Tselem "
                           "consent-gated).",
    "v1_food_wfp": "WFP price data usually lands monthly; check the HDX "
                   "dataset revision if LATE persists.",
    "v1_aid_access_unrwa_aid_trucks": "dead; a successor series would need "
                                      "OCHA aid-tracking or COGAT data — "
                                      "unscoped.",
    "v1_economic_pcbs": "pcbs-indicators fetch FAILs nightly in v1; PCBS "
                        "direct (CC-BY, verified) is the re-source path.",
    "v1_conflict_tech4palestine": "fix installed 2026-08-06, heals via the "
                                  "02:35→03:41 chain — if this is still "
                                  "stalled after 2026-08-07, the container "
                                  "copy was lost (recreate re-copies, see "
                                  "task #55).",
    "v1_connectivity_ooni": "scripts/sources/ooni-censorship.js EXISTS in v1 "
                            "but was never added to refresh-data.sh — the "
                            "same never-ported class as tech4palestine, "
                            "frozen since the same June rebuild. One "
                            "run-line in v1 fixes it (Zaid's call: prod).",
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
                            "note": STEP_NOTES.get(label)})
    # v2-native fetch artifacts: file age at the RAW layer — the June-9 class
    for name, path, allowance in [
        ("t4p raw casualties (v1 tree, fed by the healed fetch)",
         V1_T4P_RAW / "casualties", 3),
        ("gho wash (v2-native fetch)", ROOT / "data" / "gho" / "wash_pse.json", 3),
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


def rank_gaps(datasets, fetch_health) -> list[dict]:
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
    for f in fetch_health:
        if f.get("benign"):
            continue
        if f.get("fail_streak", 0) >= 3:
            gaps.append({
                "severity": 3, "kind": "fetch", "subject": f["line"],
                "measure": f"{f['fail_streak']} consecutive FAILs "
                           f"(last {f['last_at'][:10]})",
                "fill_path": f.get("note") or "v1 maintenance backlog — the "
                             "step is failing inside v1's nightly",
            })
        elif f.get("status") == "stalled":
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


def main() -> int:
    today = datetime.now(timezone.utc).date()
    with connect() as conn, conn.cursor() as cur:
        datasets = measure_datasets(cur, today)
        eras = measure_eras(cur)
    fetch_health = measure_fetch_health(today)
    gaps = rank_gaps(datasets, fetch_health)

    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "method": "freshness on the data's own dates vs each series' median "
                  "rhythm (3x allowance, declared exceptions); holes vs "
                  "rhythm; era grid; fetch-layer artifact ages",
        "counts": {
            "datasets": len(datasets),
            "fresh": sum(1 for d in datasets if d["status"] == "fresh"),
            "late": sum(1 for d in datasets if d["status"] == "late"),
            "stalled": sum(1 for d in datasets if d["status"] == "stalled"),
            "dead_upstream": sum(1 for d in datasets
                                 if d["status"] == "dead_upstream"),
            "closed_corpus": sum(1 for d in datasets
                                 if d["status"] == "closed_corpus"),
            "open_gaps": len(gaps),
        },
        "datasets": datasets,
        "era_grid": eras,
        "fetch_health": fetch_health,
        "gaps": gaps,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    tmp.replace(OUT)

    c = report["counts"]
    print(f"gap radar {today}: {c['datasets']} datasets — "
          f"{c['fresh']} fresh · {c['late']} late · {c['stalled']} stalled · "
          f"{c['dead_upstream']} dead-upstream · {c['closed_corpus']} closed")
    for g in gaps[:12]:
        print(f"  [{g['severity']}] {g['kind']:<12} {g['subject']:<44} "
              f"{g['measure'][:80]}")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
