"""Measure the Ramallah -> Nablus corridor before changing the verdict.

The external pass says the route has NO checkpoint at all in its first 26 km and
concludes: "Either it takes a real bypass road, or the corridor it checks is too
narrow." Those are different defects with different fixes, so measure which one
it is rather than assume.

Also answers the second half of the ask — which towns and roads the route passes
through — from OUR OWN gazetteer, in travel order, so the answer can say where it
goes without a geocoder we don't have.
"""
import math
import sys

import httpx

from resolve.corridor import CORRIDOR_METRES, NEAR_MISS_METRES, VALHALLA, decode_polyline
from resolve.db import connect

M_PER_DEG_LAT = 111_320.0


def _local_xy(lat, lon, lat0):
    x = math.radians(lon) * 6_371_000.0 * math.cos(math.radians(lat0))
    y = math.radians(lat) * 6_371_000.0
    return x, y


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def nearest_on_line(pt, pts, cum, lat0):
    """(metres off the line, metres along it) for the closest point."""
    px, py = _local_xy(pt[0], pt[1], lat0)
    best = (float("inf"), 0.0)
    for i in range(len(pts) - 1):
        ax, ay = _local_xy(pts[i][0], pts[i][1], lat0)
        bx, by = _local_xy(pts[i + 1][0], pts[i + 1][1], lat0)
        d, t = _seg_dist(px, py, ax, ay, bx, by)
        if d < best[0]:
            best = (d, cum[i] + t * (cum[i + 1] - cum[i]))
    return best


def route():
    body = {"locations": [{"lat": 31.9038, "lon": 35.2034},   # Ramallah
                          {"lat": 32.2211, "lon": 35.2544}],  # Nablus
            "costing": "auto", "alternates": 1,
            "directions_options": {"units": "km"}}
    r = httpx.post(f"{VALHALLA}/route", json=body, timeout=30.0)
    r.raise_for_status()
    d = r.json()
    return [d["trip"]] + [a["trip"] for a in d.get("alternates", [])]


def main():
    trips = route()
    with connect() as conn:
        _measure(trips, conn)


def _measure(trips, conn):
    for ti, trip in enumerate(trips):
        leg = trip["legs"][0]
        # decode_polyline yields (lon, lat) — NOT (lat, lon). Consuming it as
        # (lat, lon) swaps the axes and every distance comes out enormous, which
        # reads as "no checkpoints anywhere near this route" and looks exactly
        # like a quiet corridor instead of a bug. Same trap the decoder's own
        # docstring warns about, one layer up.
        pts_ll = decode_polyline(leg["shape"])          # (lon, lat)
        pts = [(lat, lon) for lon, lat in pts_ll]       # (lat, lon) for the math
        wkt = "LINESTRING(" + ",".join(f"{lon} {lat}"
                                       for lon, lat in pts_ll) + ")"
        lat0 = pts[0][0]
        cum = [0.0]
        for i in range(1, len(pts)):
            ax, ay = _local_xy(pts[i - 1][0], pts[i - 1][1], lat0)
            bx, by = _local_xy(pts[i][0], pts[i][1], lat0)
            cum.append(cum[-1] + math.hypot(bx - ax, by - ay))
        total_km = cum[-1] / 1000.0
        summ = trip.get("summary", {})
        label = "PRIMARY" if ti == 0 else f"ALTERNATE {ti}"
        print(f"=== {label}: {total_km:.1f} km, "
              f"{summ.get('time', 0)/60:.0f} min, {len(pts)} points ===")

        with conn.cursor() as cur:
            cur.execute("""SELECT p.place_id, p.name_ar, p.name_en, p.kind,
                                  ST_Y(p.centroid::geometry),
                                  ST_X(p.centroid::geometry)
                             FROM place p
                            WHERE p.merged_into IS NULL
                              AND ST_DWithin(p.centroid,
                                  ST_GeogFromText(%s), 5000)
                           ORDER BY p.kind""", (wkt,))
            near = cur.fetchall()

        cps = [r for r in near if r[3] == "checkpoint"]
        towns = [r for r in near if r[3] != "checkpoint"]
        print(f"    tracked checkpoints within 5 km: {len(cps)} | "
              f"other places within 5 km: {len(towns)}")

        placed = []
        for pid, ar, en, kind, lat, lon in cps:
            off, along = nearest_on_line((lat, lon), pts, cum, lat0)
            placed.append((off, along, ar or en or f"#{pid}", pid))
        placed.sort(key=lambda t: t[1])

        for band, lo, hi in (("ON-ROUTE (corridor)", 0, CORRIDOR_METRES),
                             ("NEAR-MISS", CORRIDOR_METRES, NEAR_MISS_METRES),
                             ("FAR (invisible)", NEAR_MISS_METRES, 5000)):
            sel = [p for p in placed if lo < p[0] <= hi]
            print(f"  -- {band}: {len(sel)}")
            for off, along, name, pid in sel[:12]:
                print(f"     {along/1000:6.1f} km along | {off:6.0f} m off | {name}")

        # Where is the coverage thin? Longest run of route with no checkpoint
        # inside the corridor.
        on = [p for p in placed if p[0] <= CORRIDOR_METRES]
        marks = sorted([0.0] + [p[1] for p in on] + [cum[-1]])
        gaps = [(marks[i + 1] - marks[i], marks[i], marks[i + 1])
                for i in range(len(marks) - 1)]
        gaps.sort(reverse=True)
        print(f"  -- coverage: {len(on)} checkpoints inside "
              f"{CORRIDOR_METRES} m over {total_km:.1f} km")
        for g, a, b in gaps[:3]:
            print(f"     longest blind stretch: {g/1000:5.1f} km "
                  f"({a/1000:.1f} -> {b/1000:.1f} km along)")

        # What towns does it pass, in travel order? This is what the answer
        # should name.
        passed = []
        for pid, ar, en, kind, lat, lon in towns:
            off, along = nearest_on_line((lat, lon), pts, cum, lat0)
            if off <= 1500:
                passed.append((along, off, ar or en or f"#{pid}"))
        passed.sort()
        print(f"  -- passes {len(passed)} named places within 1.5 km, in order:")
        print("     " + " · ".join(f"{n} ({a/1000:.0f}km)"
                                   for a, o, n in passed[:26]))
        print()


if __name__ == "__main__":
    sys.exit(main())
