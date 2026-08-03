"""Does the fuel CARD say the same thing the fuel TEXT said?

    .venv/bin/python -m learn.fuel_image_agreement

WHY THIS DECIDES WHETHER THE IMAGE FEED IS EVER BELIEVED
@palhubappfuel switched from text bulletins to rendered cards on 2026-08-01,
taking 196 stations dark. `cascade/fuel_image.py` can read the cards, and
`ingest/sources/palhub_fuel_image.py` writes what it reads — as `quarantined`,
collected and never believed. This is the measurement that says whether that
should change.

MEASURED AGAINST THE TEXT FEED, NOT AGAINST PERFECTION
The lesson from P6.1 is that a raw agreement rate is uninterpretable on its
own. Palhub's ROAD bulletin agreed with the road channels 46.7% of the time,
which read like a source with a different congestion threshold — until the
control showed the channels agreeing with EACH OTHER 96.8%. The control is what
turned an ambiguous number into a verdict.

The control here is different in kind, and weaker, and that has to be said
plainly: there is only ONE witness to fuel. No second source reports station
availability at all, so there is no channel-vs-channel baseline to compute. What
this measures is narrower — whether reading the channel's PICTURES agrees with
reading the same channel's WORDS. It cannot tell us the channel is right. It can
only tell us the OCR is not inventing anything, which is a necessary condition
and not a sufficient one.

TWO FAILURE MODES, KEPT APART
  disagreement   card and text give different values for the same station.
                 Points at the parser: a misread pill, a name matched to the
                 wrong row.
  staleness      card and text agree, but the card is repeating something hours
                 old. Points at the SOURCE, and is exactly what disqualified the
                 road bulletin. Only visible where the same station is covered
                 repeatedly, so it is reported separately and never averaged in.

WINDOW
Fuel availability moves in hours, not minutes — a station that has diesel at
19:00 almost certainly had it at 18:00. So the pairing window is generous (90
minutes by default) and the window itself is reported, because a wide window
flatters agreement and hiding that would be the same dishonesty this file
exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect  # noqa: E402

WINDOW_MINUTES = 90
RESULT_FILE = ROOT / "ops" / "fuel-image-agreement.json"

# Below this a rate is not a measurement. The road bulletin's 46.7% rested on 45
# pairs and was still enough to disqualify it; a handful is not.
MIN_PAIRS = 20

# ONE ROW PER IMAGE OBSERVATION, paired with its NEAREST text observation.
#
# The first version of this query joined every image row to every text row
# inside the window and reported 45,966 "pairs" from 172 stations — a cartesian
# product, roughly 267 copies of each real comparison. Both feeds sweep
# repeatedly, so a 90-minute window catches three image sweeps against three
# text sweeps and calls it nine independent agreements. Every rate computed
# that way is an artefact of sweep frequency, and a single disagreeing station
# appears as a thousand failures.
#
# DISTINCT ON keeps the closest text reading in time and discards the rest.
PAIR_SQL = """
WITH img AS (
  SELECT place_id, state_kind, value, observed_at
    FROM state_observation
   WHERE attrs->>'via' = 'image' AND modality = 'quarantined'
), txt AS (
  SELECT place_id, state_kind, value, observed_at
    FROM state_observation
   WHERE state_kind LIKE 'fuel%%' AND modality = 'assertion'
     AND COALESCE(attrs->>'via','') <> 'image'
)
SELECT DISTINCT ON (i.place_id, i.state_kind, i.observed_at)
       i.place_id, p.name_ar, i.state_kind,
       i.value AS img_value, t.value AS txt_value,
       i.observed_at AS img_at, t.observed_at AS txt_at,
       EXTRACT(epoch FROM (i.observed_at - t.observed_at))/60 AS gap_minutes
  FROM img i
  JOIN txt t ON t.place_id = i.place_id AND t.state_kind = i.state_kind
   AND t.observed_at BETWEEN i.observed_at - make_interval(mins => %s)
                         AND i.observed_at + make_interval(mins => %s)
  JOIN place p ON p.place_id = i.place_id
 ORDER BY i.place_id, i.state_kind, i.observed_at,
          abs(EXTRACT(epoch FROM (i.observed_at - t.observed_at)))
"""


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    z, ph = 1.96, k / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    m = z * sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


def measure(window: int = WINDOW_MINUTES) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(PAIR_SQL, (window, window))
        pairs = cur.fetchall()

        # Coverage context: a high agreement rate over three stations says
        # nothing about the other 193.
        cur.execute("""SELECT count(DISTINCT place_id) FROM state_observation
                        WHERE attrs->>'via' = 'image'""")
        img_places = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM place WHERE kind = 'station'
                        AND source_refs ? 'palhub_region'""")
        total_stations = cur.fetchone()[0]

    agree = sum(1 for r in pairs if r[3] == r[4])
    n = len(pairs)
    lo, hi = _wilson(agree, n)

    # PER (STATION, FUEL), because sweep-level pairs are not independent.
    # Both feeds resweep every half hour, so a station covered for a day
    # contributes ~48 pairs that are all the same comparison restated. A rate
    # over those measures how often the sources sweep, not how often they
    # agree. This collapses each station-fuel to one verdict: did the card ever
    # contradict the text about it?
    units: dict[tuple, bool] = {}
    for r in pairs:
        key = (r[0], r[2])
        units[key] = units.get(key, True) and (r[3] == r[4])
    u_total = len(units)
    u_agree = sum(1 for ok in units.values() if ok)
    u_lo, u_hi = _wilson(u_agree, u_total)

    # Distinct stations behind the false all-clears — the number that matters
    # operationally, since one bad station restated 400 times is one bad
    # station.
    false_ok_places = {r[1] for r in pairs
                       if r[3] == "available" and r[4] == "unavailable"}

    # Disagreements broken out by direction, because they are not symmetric.
    # The card saying `available` where the text said `unavailable` is the
    # dangerous one: it is a false all-clear, the value P2.4 guards hardest.
    false_ok = sum(1 for r in pairs
                   if r[3] == "available" and r[4] == "unavailable")
    false_dry = sum(1 for r in pairs
                    if r[3] == "unavailable" and r[4] == "available")

    result = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "window_minutes": window,
        "pairs": n,
        "agree": agree,
        "rate": round(agree / n, 3) if n else None,
        "ci95": [round(lo, 3), round(hi, 3)] if n else None,
        "station_fuels": u_total,
        "station_fuels_clean": u_agree,
        "station_rate": round(u_agree / u_total, 3) if u_total else None,
        "station_ci95": [round(u_lo, 3), round(u_hi, 3)] if u_total else None,
        "false_available": false_ok,
        "false_available_stations": sorted(false_ok_places),
        "false_unavailable": false_dry,
        "stations_with_image_data": img_places,
        "stations_total": total_stations,
        "verdict": None,
        "examples": list({
            (r[1], r[2], r[3], r[4]): {
                "place": r[1], "kind": r[2], "card": r[3], "text": r[4],
                "gap_minutes": round(float(r[7]), 1)}
            for r in pairs if r[3] != r[4]
        }.values())[:15],
    }

    if n < MIN_PAIRS:
        result["verdict"] = (
            f"UNMEASURED — only {n} comparable pairs. The text feed all but "
            f"stopped when the cards started, so the overlap is thin by nature. "
            f"Stays quarantined: an unmeasured source is not a trusted one.")
    elif false_ok > 0:
        result["verdict"] = (
            f"FAIL — {false_ok} pair(s) where the card said `available` and the "
            f"text said `unavailable`, across "
            f"{len(result['false_available_stations'])} station(s): "
            f"{', '.join(result['false_available_stations'][:5])}. A false "
            f"all-clear sends somebody to a dry station on a tank they could "
            f"not spare. Stays quarantined.")
    elif result["rate"] and result["rate"] >= 0.95:
        result["verdict"] = (
            f"PASS on agreement ({agree}/{n}). NOT a promotion on its own: this "
            f"shows the OCR is faithful to the channel, not that the channel is "
            f"right. Staleness is the open question and there is no second "
            f"source to settle it.")
    else:
        result["verdict"] = (
            f"FAIL — {agree}/{n} agree. Stays quarantined.")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=WINDOW_MINUTES)
    a = ap.parse_args()
    r = measure(a.window)
    RESULT_FILE.write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str))

    print(f"fuel card vs fuel text — ±{r['window_minutes']}min window\n")
    print(f"  pairs                {r['pairs']}")
    if r["rate"] is not None:
        print(f"  agree                {r['agree']}/{r['pairs']} = {r['rate']:.3f}"
              f"  [{r['ci95'][0]:.2f}-{r['ci95'][1]:.2f}]")
    if r.get("station_rate") is not None:
        print(f"  per station+fuel     {r['station_fuels_clean']}/{r['station_fuels']}"
              f" = {r['station_rate']:.3f}  [{r['station_ci95'][0]:.2f}-{r['station_ci95'][1]:.2f}]"
              f"   <- the honest one")
    print(f"  card said available, text said unavailable   {r['false_available']}"
          f" ({len(r.get('false_available_stations', []))} distinct station(s))")
    print(f"  card said unavailable, text said available   {r['false_unavailable']}")
    print(f"  stations with card data   {r['stations_with_image_data']}"
          f"/{r['stations_total']}")
    if r["examples"]:
        print("\n  disagreements:")
        for e in r["examples"]:
            print(f"    {e['place'][:28]:30} {e['kind'][5:]:9} "
                  f"card={e['card']:12} text={e['text']:12} {e['gap_minutes']:+.0f}min")
    print(f"\n  {r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
