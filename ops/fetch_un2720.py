"""The UN2720 Mechanism's daily aid figures for Gaza: trucks, pallets and tonnes
offloaded at the crossings, collected from them, and arrived at their
destination, one row per stage, day and measure.

    .venv/bin/python -m ops.fetch_un2720                  # fetch and write
    .venv/bin/python -m ops.fetch_un2720 --dry-run        # print, write nothing
    .venv/bin/python -m ops.fetch_un2720 --dry-run --stage DIR

WHY (2026-10-12)
The databank's only series on aid entering Gaza was UNRWA's truck log
(v1_aid_access_unrwa_aid_trucks), which ends on 2025-01-16 when UNRWA stopped
publishing. The UN2720 Mechanism (Security Council resolution 2720, run by
UNOPS) is what tracks UN-coordinated cargo now. Its public "Monitoring &
Tracking" dashboard starts on 2025-05-19, the day aid resumed after the
blockade. The two do not overlap and do not count the same thing; see
db/mappings/aid_un2720.yaml.

WHAT IT READS
The dashboard (https://tracking.un2720.org/, where app.un2720.org/tracking
redirects) is a page that draws its charts from four JSON addresses on the
same host. They answer a plain GET: no account, no key, no cookie, and
robots.txt there allows everything (read 2026-10-12). This fetcher asks what
the page asks, once a night:

    /                      the page itself: `floor`, `until`, `capped` (its window)
    /fetchSummaryStats     the four totals on the landing cards
    /fetchData/date        Offloaded: `barLabels` (days) + trucks, pallets, weight
    /fetchCollectedData    Collected: the same
    /fetchDeliveredData    Arrived:   `dailyLabels` + trucks, pallets, weight

with `start` = floor and `end` = until, exactly as the page's own date picker
does. It never asks past `until`: while `capped` is true the page says the days
after it are "pending final verification", and that is the publisher's call.

WHAT IT WRITES
data/raw/un2720/daily.json: {"metadata", "publisher", "data"}.
  data       one record per stage x day x measure, in the shape the declarative
             engine reads (stage, measure, date, value, unit, location.region).
             A day the publisher does not list is not written: no zero is
             invented.
  publisher  the four answers as received. They also hold the to-date splits
             by crossing, commodity, route and organisation, which no spec
             loads yet; kept so nothing the publisher said is thrown away.
  metadata   the vintage (`until`), the window, per-stage counts and sums.
A night on which the publisher changed nothing leaves the file's bytes alone
(only its modification time moves), so bronze does not grow.

THE CHECKS (any failure keeps yesterday's file; ops/fetchlib.py's posture)
  - each stage holds at least its floor of days (about 0.9 of 2026-10-12);
  - every label is a date, none repeats, the three arrays are the same length;
  - the days sum to the publisher's own total: trucks and pallets exactly,
    weight within a tenth of a percent (each day is rounded to 10 kg).
All three stages pass or nothing is written: the spec declares the file to be
the publisher's whole series, so a file missing a stage would read as that
stage withdrawn.

LICENCE: none is stated on un2720.org, info.un2720.org or the dashboard (read
2026-10-12; the footer is "(c) UN2720 Mechanism for Gaza"). The source row is
therefore proposed as `ask` (db/proposed/un2720.sql).
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

BASE = "https://tracking.un2720.org"
PAGE = BASE + "/"
OUT = fl.ROOT / "data" / "raw" / "un2720" / "daily.json"
LABEL = "un2720:daily"
PAUSE = 1.0                     # seconds between the five requests

# The name the spec routes on (db/mappings/aid_un2720.yaml, by_name).
SOURCE = {"name": "UN2720 Monitoring & Tracking Dashboard",
          "organization": "UN2720 Mechanism for Gaza (UNOPS)",
          "url": PAGE, "license": "not stated"}

# stage -> where the page reads it, and what the page calls it. `key` in
# `summary` is the name the landing cards' totals use for the same stage.
STAGES = {
    "offloaded": {"path": "/fetchData/date", "days": "barLabels",
                  "trucks": "barTrucks", "pallets": "barPallets",
                  "tonnes": "barWeights", "summary": "arrival",
                  "title": "Offloaded",
                  "caption": "In any of the crossings along Gaza's perimeter"},
    "collected": {"path": "/fetchCollectedData", "days": "barLabels",
                  "trucks": "barTrucks", "pallets": "barPallets",
                  "tonnes": "barWeights", "summary": "collected",
                  "title": "Collected",
                  "caption": "From any of the crossings along Gaza's perimeter"},
    "arrived": {"path": "/fetchDeliveredData", "days": "dailyLabels",
                "trucks": "dailyTrucks", "pallets": "dailyPallets",
                "tonnes": "dailyWeights", "summary": "delivered",
                "title": "Arrived",
                "caption": "To the intended destination in Gaza"},
}
# measure -> (unit as the unit registry spells it, the page's own label)
MEASURES = {"trucks": ("truck", "Trucks"), "pallets": ("pallet", "Pallets"),
            "tonnes": ("tonne", "Weight (t)")}

# Floors: about 0.9 of the days each stage held on 2026-10-12 (333, 417, 395).
FLOORS = {"offloaded": 300, "collected": 375, "arrived": 355}
WEIGHT_TOLERANCE = 0.001        # of the publisher's total; days are rounded


# ── reading what the publisher sent ──────────────────────────────────────────

def landing_props(page_html: str) -> dict:
    """The window the page declares for itself: floor, until, capped,
    intercepted. The page carries them as JSON in a `data-page` block (older
    builds of the same framework put it in an attribute)."""
    m = re.search(r'<script[^>]*data-page="[^"]*"[^>]*>(.*?)</script>',
                  page_html, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        m = re.search(r'<div[^>]*\bdata-page="([^"]*)"', page_html)
        raw = html_lib.unescape(m.group(1)) if m else None
    if raw is None:
        raise fl.FetchRefused("un2720: the page carries no data-page block")
    try:
        props = json.loads(raw)["props"]
        floor, until = str(props["floor"]), str(props["until"])
        date.fromisoformat(floor), date.fromisoformat(until)
    except (KeyError, TypeError, ValueError) as e:
        raise fl.FetchRefused(f"un2720: page window unreadable ({type(e).__name__}: {e})")
    if until < floor:
        raise fl.FetchRefused(f"un2720: window ends ({until}) before it starts ({floor})")
    return {"floor": floor, "until": until, "capped": bool(props.get("capped")),
            "intercepted": bool(props.get("intercepted"))}


def publisher_total(stage: str, payload: dict) -> dict:
    """The stage's own totals, as its report page shows them above the charts."""
    t = payload.get("totalSummary")
    if isinstance(t, dict):                    # Offloaded
        return {"trucks": t.get("trucks"), "pallets": t.get("pallets"),
                "tonnes": t.get("weight"), "requests": t.get("utns")}
    return {"trucks": payload.get("totalTrucks"),
            "pallets": payload.get("totalPallets"),
            "tonnes": payload.get("totalWeight"),
            "requests": payload.get("totalUtns")}


def daily_series(stage: str, payload: dict) -> list[dict]:
    """[{day, trucks, pallets, tonnes}] for one stage, in day order, exactly
    the numbers the page charts. Refuses a shape it cannot read whole."""
    s = STAGES[stage]
    try:
        days = [str(d) for d in payload[s["days"]]]
        cols = {m: list(payload[s[m]]) for m in MEASURES}
    except (KeyError, TypeError) as e:
        raise fl.FetchRefused(f"un2720:{stage}: field missing ({e})")
    if any(len(c) != len(days) for c in cols.values()):
        raise fl.FetchRefused(
            f"un2720:{stage}: {len(days)} days against "
            f"{ {m: len(c) for m, c in cols.items()} } values")
    if len(set(days)) != len(days):
        raise fl.FetchRefused(f"un2720:{stage}: a day is listed twice")
    out = []
    for i, d in enumerate(days):
        try:
            date.fromisoformat(d)
        except ValueError:
            raise fl.FetchRefused(f"un2720:{stage}: {d!r} is not a date")
        row = {"day": d}
        for m in MEASURES:
            v = cols[m][i]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                raise fl.FetchRefused(f"un2720:{stage}: {m} on {d} is {v!r}")
            row[m] = v
        out.append(row)
    return sorted(out, key=lambda r: r["day"])


def clip(series: list[dict], floor: str, until: str) -> tuple[list[dict], int]:
    """Keep the days inside the page's own window. Anything outside it is a
    day the publisher has not put on the page; it is counted, never written."""
    kept = [r for r in series if floor <= r["day"] <= until]
    return kept, len(series) - len(kept)


def summarise(series: list[dict]) -> dict:
    return {"days": len(series), "first_day": series[0]["day"],
            "last_day": series[-1]["day"],
            "trucks": sum(r["trucks"] for r in series),
            "pallets": sum(r["pallets"] for r in series),
            "tonnes": round(sum(r["tonnes"] for r in series), 3)}


def check_stage(stage: str, series: list[dict], total: dict, floor_days: int) -> None:
    """Floor and sums, on the answer as the publisher sent it. Raises
    FetchRefused (no ledger line here: main() owns the ledger)."""
    if len(series) < floor_days:
        raise fl.FetchRefused(
            f"un2720:{stage}: {len(series)} days below the floor of {floor_days}"
            " — keeping the file already on disk")
    sums = summarise(series)
    for m in ("trucks", "pallets"):
        if total.get(m) is None or sums[m] != total[m]:
            raise fl.FetchRefused(
                f"un2720:{stage}: the days sum to {sums[m]} {m}, the publisher's "
                f"total says {total.get(m)} — the series is not the whole of it")
    tw = total.get("tonnes")
    if tw is None or abs(sums["tonnes"] - tw) > max(1.0, WEIGHT_TOLERANCE * tw):
        raise fl.FetchRefused(
            f"un2720:{stage}: the days sum to {sums['tonnes']:.2f} t, the "
            f"publisher's total says {tw}")


def records(series_by_stage: dict[str, list[dict]]) -> list[dict]:
    """One record per stage x day x measure, in the engine's shape."""
    out = []
    for stage in STAGES:                        # fixed order: a stable file
        s = STAGES[stage]
        for row in series_by_stage[stage]:
            for measure, (unit, label) in MEASURES.items():
                out.append({
                    "stable_id": f"un2720-{stage}-{row['day']}-{measure}",
                    "date": row["day"], "stage": stage, "measure": measure,
                    "value": row[measure], "unit": unit,
                    "indicator_name": f"{s['title']} ({s['caption'][0].lower()}"
                                      f"{s['caption'][1:]}): {label}",
                    "location": {"region": "Gaza Strip"},
                    "sources": [SOURCE],
                })
    return out


def build(props: dict, summary: dict, answers: dict[str, dict]) -> dict:
    """The whole raw document from the five answers, or FetchRefused."""
    series, stages = {}, {}
    for stage in STAGES:
        full = daily_series(stage, answers[stage])
        total = publisher_total(stage, answers[stage])
        # sums are checked on what the publisher sent, before clipping: the
        # total belongs to the whole answer
        check_stage(stage, full, total, FLOORS[stage])
        series[stage], outside = clip(full, props["floor"], props["until"])
        if len(series[stage]) < FLOORS[stage]:
            raise fl.FetchRefused(
                f"un2720:{stage}: {len(series[stage])} days inside the page's "
                f"window, below the floor of {FLOORS[stage]}")
        stages[stage] = {**summarise(series[stage]), "publisher_total": total}
        if outside:
            stages[stage]["days_outside_window_not_written"] = outside
        card = (summary or {}).get(STAGES[stage]["summary"]) or {}
        stages[stage]["landing_card_agrees"] = (
            card.get("trucks") == total["trucks"]
            and card.get("pallets") == total["pallets"])
    recs = records(series)
    return {
        "metadata": {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": SOURCE["name"], "organization": SOURCE["organization"],
            "source_url": PAGE,
            "via": "the dashboard page and its own JSON addresses, plain GET, "
                   "no account or key: /, /fetchSummaryStats, "
                   + ", ".join(s["path"] for s in STAGES.values()),
            "license": "none stated on un2720.org, info.un2720.org or the "
                       "dashboard (read 2026-10-12); held as `ask`",
            "attribution": "UN2720 Mechanism for Gaza (UNOPS), Monitoring & "
                           "Tracking Dashboard, https://tracking.un2720.org/",
            "vintage": props["until"],
            "vintage_basis": "the last day the dashboard itself covers (its "
                             "`until`); while `capped` is true the page says "
                             "the data is 'accurate and verified up to' that "
                             "day and later days are pending verification",
            "vintage_url": PAGE,
            "floor": props["floor"], "until": props["until"],
            "capped": props["capped"],
            "intercepted_section_published": props["intercepted"],
            "records": len(recs), "stages": stages,
        },
        "publisher": {"window": props, "summary": summary, **answers},
        "data": recs,
    }


def same_content(a: dict, b: dict) -> bool:
    """True when two documents say the same thing: everything but the stamp."""
    def strip(d):
        return {**d, "metadata": {k: v for k, v in (d.get("metadata") or {}).items()
                                  if k != "fetched_at"}}
    return strip(a) == strip(b)


# ── the run ──────────────────────────────────────────────────────────────────

def fetch() -> tuple[dict, dict, dict[str, dict]]:
    props = landing_props(fl.get(PAGE, timeout=60).decode("utf-8", "replace"))
    time.sleep(PAUSE)
    summary = fl.get_json(BASE + "/fetchSummaryStats", timeout=60)
    answers = {}
    for stage, s in STAGES.items():
        time.sleep(PAUSE)
        answers[stage] = fl.get_json(
            f"{BASE}{s['path']}?start={props['floor']}&end={props['until']}",
            timeout=120)
        if not isinstance(answers[stage], dict):
            raise fl.FetchRefused(f"un2720:{stage}: the answer is not an object")
    return props, summary, answers


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    try:
        props, summary, answers = fetch()
        doc = build(props, summary, answers)
    except fl.FetchRefused as e:
        print(f"  REFUSED {LABEL}: {e}", file=sys.stderr)
        if not dry:
            fl.event(LABEL, "refused", why=str(e)[:300])
        return 1
    except Exception as e:                                  # noqa: BLE001
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:300])
        return 1

    meta = doc["metadata"]
    print(f"  ok   {LABEL}: {meta['records']} records, window "
          f"{meta['floor']} to {meta['until']}"
          + (" (capped by the publisher)" if meta["capped"] else ""))
    for stage, s in meta["stages"].items():
        print(f"         {stage:<10} {s['days']:>4} days {s['first_day']} to "
              f"{s['last_day']}: {s['trucks']} trucks, {s['pallets']} pallets, "
              f"{s['tonnes']} t")
    if dry:
        print(f"         would write {OUT.relative_to(fl.ROOT)}  (dry run, nothing written)")
        fl.stage(staged, OUT.name, doc)
        return 0

    changed = True
    if OUT.exists():
        try:
            changed = not same_content(json.loads(OUT.read_text()), doc)
        except (OSError, ValueError):
            changed = True                      # an unreadable file is replaced
    if changed:
        fl.write_atomic(OUT, doc)
    else:
        os.utime(OUT)                           # checked tonight, bytes untouched
    fl.event(LABEL, "ok", rows=meta["records"], vintage=meta["vintage"],
             changed=changed)
    print(f"         {'wrote' if changed else 'unchanged:'} {OUT.relative_to(fl.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
