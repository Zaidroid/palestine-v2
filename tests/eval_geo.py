"""P0.19 — gazetteer gate check.

Two metrics, because self-grading is weak evidence:

  A. OBJECTIVE — for every distinct geo_source_phrase in v1's alerts.db that v1
     itself geocoded, compare v2's resolved centroid against v1's coordinates.
     Agreement within a kind-appropriate radius = correct. No human judgement.

  B. NEGATIVE — phrases naming places outside Palestine (Lebanon, Iran, Yemen…)
     MUST NOT resolve to a Palestinian place. Precision matters as much as
     recall: a fuzzy matcher that resolves everything is worse than useless.

v1's alerts.db is opened read-only + immutable.
"""
from __future__ import annotations

import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect
from resolve.db import v1_path  # noqa: E402
from resolve.geo import resolve_place

V1_ALERTS = str(v1_path("services/westbank-alerts/data/alerts.db"))

# Radius within which v2's answer counts as agreeing with v1's.
TOLERANCE_KM = {"station": 8.0, "street": 8.0, "town": 12.0,
                "admin2": 30.0, "admin1": 90.0, "unknown": 30.0}

# Should never resolve to a Palestinian place.
FOREIGN = {"lebanon", "iran", "yemen", "syria", "iraq", "jordan", "egypt",
           "beirut", "tehran", "sanaa", "damascus", "baghdad", "israel",
           "لبنان", "ايران", "اليمن", "سوريا", "العراق", "مصر", "بيروت", "طهران"}


def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main() -> int:
    db = sqlite3.connect(f"file:{V1_ALERTS}?mode=ro&immutable=1", uri=True)
    rows = db.execute("""
        SELECT geo_source_phrase, AVG(latitude), AVG(longitude), COUNT(*)
        FROM alerts
        WHERE geo_source_phrase IS NOT NULL AND length(geo_source_phrase) > 2
        GROUP BY geo_source_phrase""").fetchall()
    db.close()

    graded = ungradeable = 0
    correct = 0
    resolved_total = 0
    by_method: Counter = Counter()
    misses: list[tuple] = []
    far: list[tuple] = []
    foreign_leaks: list[tuple] = []

    with connect() as conn, conn.cursor() as cur:
        for phrase, v1lat, v1lon, n in rows:
            res = resolve_place(phrase, conn=conn, learn=False)
            if res:
                resolved_total += 1
                by_method[res.method] += 1

            # ---- B. negatives -------------------------------------------------
            if phrase.strip().lower() in FOREIGN:
                if res:
                    foreign_leaks.append((phrase, res.name_en or res.name_ar, res.method,
                                          res.confidence))
                continue

            # ---- A. objective agreement ---------------------------------------
            if v1lat is None or v1lon is None:
                ungradeable += 1
                continue
            graded += 1
            if not res:
                misses.append((phrase, n))
                continue
            cur.execute("SELECT ST_Y(centroid::geometry), ST_X(centroid::geometry) "
                        "FROM place WHERE place_id=%s", (res.place_id,))
            lat2, lon2 = cur.fetchone()
            d = haversine(v1lat, v1lon, lat2, lon2)
            if d <= TOLERANCE_KM.get(res.precision, 30.0):
                correct += 1
            else:
                far.append((phrase, res.name_en or res.name_ar, res.method, round(d, 1), n))

    total = len(rows)
    print(f"phrases (distinct):      {total}")
    print(f"resolved by v2:          {resolved_total}  ({resolved_total/total:.1%})")
    print(f"  by method:             {dict(by_method)}")
    print(f"gradeable (v1 has geo):  {graded}   [ungradeable: {ungradeable}]")
    print()
    acc = correct / graded if graded else 0.0
    print(f"AGREEMENT WITH v1 GEO:   {correct}/{graded} = {acc:.1%}   (gate: >=80%)")
    print(f"  unresolved:            {len(misses)}")
    print(f"  resolved but far:      {len(far)}")
    print()
    print(f"FOREIGN LEAKS:           {len(foreign_leaks)}  (gate: 0)")
    for p, got, m, c in foreign_leaks[:10]:
        print(f"    {p!r} -> {got!r} via {m} conf={c}")

    if far:
        print("\nworst distance errors:")
        for p, got, m, d, n in sorted(far, key=lambda x: -x[3])[:10]:
            print(f"    {d:>7.1f}km  {p!r} -> {got!r} ({m}, n={n})")
    if misses:
        print("\nsample unresolved:")
        for p, n in sorted(misses, key=lambda x: -x[1])[:10]:
            print(f"    n={n:<4} {p!r}")

    gate = acc >= 0.80 and not foreign_leaks
    print(f"\nGATE 0 (gazetteer): {'PASS' if gate else 'FAIL'}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
