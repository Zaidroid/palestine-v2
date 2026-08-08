"""Fetch OONI's daily censorship measurements for Palestine, from OONI.

v1's copy STOPPED ON 2026-06-09 and has been sixty days stale ever since —
gap_radar has been printing it as a severity-4 freshness alert against a 7-day
allowance. So this cut does not merely remove a dependency; it is the only way
the series continues at all.

WHAT THE NUMBER IS. OONI's aggregation endpoint returns, per day, how many web
measurements its probes took in Palestine and how many came back anomalous.
The observation is the RATIO — anomalies over measurements — which is what v1
carried as `anomaly_rate` and what the databank stores as the value. The two
counts ride along in attrs, because a 50% anomaly rate over four measurements
and over four thousand are not the same claim and the row has to be able to
say which it is.

  anomaly     the measurement did not look like a clean fetch. It is EVIDENCE
              OF INTERFERENCE, not proof of blocking; OONI's own confirmed
              count is separate and is carried separately.
  failure     the measurement itself failed (probe-side). NOT an anomaly, and
              deliberately not folded into the rate — v1 did not, and calling
              a broken probe a blocked site would inflate exactly the number
              people would quote.

LICENCE: CC-BY-NC-SA-4.0, read 2026-08-08 at the licence file that
ooni.org/about/data-policy names (see 067). Non-commercial and share-alike;
both are recorded on the source row and both bind the open release.

Run: .venv/bin/python -m ops.fetch_ooni
     .venv/bin/python -m ops.fetch_ooni --dry-run
     .venv/bin/python -m ops.fetch_ooni --since 2017-01-01   # full re-fetch
"""
from __future__ import annotations

import sys
import urllib.error
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

RAW = fl.ROOT / "data" / "raw" / "ooni"
OUT = RAW / "ps_daily.json"
API = "https://api.ooni.io/api/v1/aggregation"

# ONE TEST, NOT ALL OF THEM — and this is the whole correctness of the series.
# OONI runs many tests (web_connectivity, whatsapp, telegram, signal, ...) and
# the aggregation endpoint sums whichever ones you do not exclude. The first
# draft of this fetcher left it off and got 2,542 days against v1's 1,276,
# with 1,218 of the 1,275 overlapping days carrying DIFFERENT counts — higher
# every time, because it was counting messaging-app reachability tests as web
# censorship measurements. That is not more data, it is a different measure
# wearing the same indicator name, and it would have been invisible the moment
# it landed. With the filter on, the overlap matches v1 exactly.
#
# v1 never declared this; its own record descriptions say "N web
# measurements", which is the only trace it left.
TEST_NAME = "web_connectivity"

# OONI's Palestine record starts here — v1's earliest row is 2017-02-09 and
# the endpoint returns nothing before it.
FIRST_DAY = "2017-01-01"

# ~0.9 x v1's 1,276 measured days. A day with no measurements is simply absent
# from the response, so the count is days-with-data, not calendar days.
MIN_DAYS = 1140

# One request per year. The endpoint will answer a nine-year range in one go,
# but a single timeout would then lose everything; a year at a time means a
# bad night costs one chunk and the refusal below still sees the shortfall.
CHUNK_DAYS = 366


def fetch(since: str, until: str) -> list[dict]:
    out: list[dict] = []
    a = date.fromisoformat(since)
    end = date.fromisoformat(until)
    while a <= end:
        b = min(a + timedelta(days=CHUNK_DAYS), end)
        url = (f"{API}?probe_cc=PS&since={a}&until={b}"
               f"&axis_x=measurement_start_day&test_name={TEST_NAME}")
        out.extend(fl.get_json(url).get("result") or [])
        a = b + timedelta(days=1)
    return out


def _rate(anomalies: int, n: int) -> float:
    """anomalies / n to four places, exactly as v1's Node `toFixed(4)` did.

    Two subtleties, both measured against the 1,275 overlapping days rather
    than reasoned about:

    `round()` is wrong. It rounds half to EVEN, so 1/32 — exactly 0.03125 —
    gives 0.0312 where v1 gave 0.0313. Six days land on an exact half.

    And rounding the exact RATIONAL is also wrong, in the other direction.
    9/800 is 0.01125 on paper, so half-up gives 0.0113; v1 gave 0.0112,
    because 0.01125 is not representable in binary and the double it becomes
    sits just below the half. toFixed rounds the DOUBLE, not the fraction.

    So: do the float division first, hand the double to Decimal (which takes
    its exact binary value), and round half-up from there. 1/32 is exactly
    representable and rounds up; 9/800 is not and rounds down. Both match.
    """
    q = Decimal(anomalies / n).quantize(Decimal("0.0001"),
                                        rounding=ROUND_HALF_UP)
    return float(q)


def to_records(rows: list[dict]) -> list[dict]:
    """OONI's aggregation rows → the shape the spec reads.

    Written out rather than passed through, because the ratio is a DERIVED
    number and deriving it here — once, in the fetcher, next to the counts it
    came from — is what lets the spec say `value = anomaly_rate` and be
    checkable. v1 computed the same quotient and rounded to 4 decimals; the
    rounding is reproduced so the cut moves no values.
    """
    recs = []
    for r in rows:
        day = str(r.get("measurement_start_day") or "")[:10]
        n = r.get("measurement_count") or 0
        if not day or not n:
            continue                      # a day with no measurements is not
        anomalies = r.get("anomaly_count") or 0    # a day with a zero rate
        recs.append({
            "id": f"ooni-ps-{day}",
            "date": day,
            "measurement_count": n,
            "anomaly_count": anomalies,
            "confirmed_count": r.get("confirmed_count") or 0,
            "failure_count": r.get("failure_count") or 0,
            "anomaly_rate": _rate(anomalies, n),
        })
    recs.sort(key=lambda r: r["date"])
    return recs


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    since = FIRST_DAY
    if "--since" in argv:
        since = argv[argv.index("--since") + 1]
    until = str(date.today())
    try:
        recs = to_records(fetch(since, until))
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"  FAIL ooni {type(e).__name__}: {e}")
        fl.event("ooni:ps_daily", "error", error=type(e).__name__)
        return 1
    try:
        fl.check_floor("ooni:ps_daily", len(recs), MIN_DAYS)
    except fl.FetchRefused as e:
        print(f"  REFUSED {e}")
        return 1
    if not dry:
        fl.write_atomic(OUT, recs)
        fl.stamp(RAW / "_fetched.json",
                 "OONI (api.ooni.io), Open Observatory of Network Interference",
                 "CC-BY-NC-SA-4.0 — non-commercial, share-alike; verified "
                 "2026-08-08 at github.com/ooni/license/data",
                 "Censorship measurements: OONI (ooni.org), CC-BY-NC-SA-4.0.",
                 days=len(recs), first=recs[0]["date"], last=recs[-1]["date"])
    fl.event("ooni:ps_daily", "ok", rows=len(recs))
    print(f"  ok   ooni  {len(recs)} days  {recs[0]['date']} .. "
          f"{recs[-1]['date']}" + ("  (dry run)" if dry else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
