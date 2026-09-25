"""P1-A — the palhub earn-out, measured by VALUE CLASS (PLAN §7 P1-A.1).

    .venv/bin/python -m ops.palhub_earnout --days 28 --window 90 [--out ops/palhub-earnout.json]

READ-ONLY. The weekly review prints one blended agreement rate (0.73–0.78 vs a
0.90 gate) and never said WHICH readings disagree. This pairs every quarantined
palhub reading with the nearest independent-channel assertion for the same
checkpoint and a compatible direction, then reports agreement per palhub value
(open / congested / closed), per checkpoint and per direction — beside the
channel-vs-channel CONTROL computed the same way, because two channels do not
agree 100 % either and the gate must be read against that.

A class that agrees with the control's own rate for that class is a class palhub
reads as well as a channel does. That is the promotion decision; it is made in
ingest/sources/palhub_roads.py (MODALITY per class), never here.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect                                     # noqa: E402

PAIR_SQL = """
WITH ph AS (
  SELECT o.place_id, o.direction, o.value, o.observed_at
    FROM state_observation o JOIN source s ON s.source_id = o.source_id
   WHERE s.key = 'tg_palhubapproad' AND o.state_kind = 'checkpoint_flow'
     AND o.observed_at > now() - make_interval(days => %(days)s)
), live AS (
  SELECT o.place_id, o.direction, o.value, o.observed_at, o.direction_explicit,
         COALESCE(s.independence_group, 'src:' || s.source_id::text) AS unit
    FROM state_observation o JOIN source s ON s.source_id = o.source_id
   WHERE s.key <> 'tg_palhubapproad' AND s.kind <> 'crowd'
     AND o.state_kind = 'checkpoint_flow' AND o.modality = 'assertion'
     AND o.observed_at > now() - make_interval(days => %(days)s + 1)
)
SELECT DISTINCT ON (p.place_id, p.direction, p.observed_at)
       p.place_id, p.direction, p.value, l.value, l.direction, l.direction_explicit, l.unit,
       abs(EXTRACT(epoch FROM (p.observed_at - l.observed_at))) AS gap_s
  FROM ph p
  JOIN live l ON l.place_id = p.place_id
   AND (l.direction = p.direction OR l.direction = 'both' OR p.direction = 'both')
   AND l.observed_at BETWEEN p.observed_at - make_interval(mins => %(win)s)
                         AND p.observed_at + make_interval(mins => %(win)s)
 ORDER BY p.place_id, p.direction, p.observed_at, gap_s
"""

# The control: one channel unit against another, same pairing, same window.
CONTROL_SQL = """
WITH live AS (
  SELECT o.place_id, o.direction, o.value, o.observed_at,
         COALESCE(s.independence_group, 'src:' || s.source_id::text) AS unit
    FROM state_observation o JOIN source s ON s.source_id = o.source_id
   WHERE s.key <> 'tg_palhubapproad' AND s.kind <> 'crowd'
     AND o.state_kind = 'checkpoint_flow' AND o.modality = 'assertion'
     AND o.observed_at > now() - make_interval(days => %(days)s)
)
SELECT DISTINCT ON (a.place_id, a.direction, a.observed_at, a.unit)
       a.value, b.value
  FROM live a
  JOIN live b ON b.place_id = a.place_id AND b.unit <> a.unit
   AND (b.direction = a.direction OR b.direction = 'both' OR a.direction = 'both')
   AND b.observed_at BETWEEN a.observed_at - make_interval(mins => %(win)s)
                         AND a.observed_at + make_interval(mins => %(win)s)
 ORDER BY a.place_id, a.direction, a.observed_at, a.unit,
          abs(EXTRACT(epoch FROM (a.observed_at - b.observed_at)))
"""

NAME_SQL = "SELECT place_id, COALESCE(name_ar, name_en) FROM place WHERE place_id = ANY(%s)"


def _rate(agree: int, n: int):
    return round(agree / n, 3) if n else None


def measure(days: int, win: int) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cur.execute(PAIR_SQL, {"days": days, "win": win})
        pairs = cur.fetchall()
        cur.execute(CONTROL_SQL, {"days": days, "win": win})
        control = cur.fetchall()
        places = sorted({p[0] for p in pairs})
        cur.execute(NAME_SQL, (places,))
        names = dict(cur.fetchall())
        conn.rollback()

    by_class: dict[str, list[int]] = defaultdict(lambda: [0, 0])          # value -> [agree, n]
    by_class_dir: dict[str, list[int]] = defaultdict(lambda: [0, 0])      # value|explicit-same-direction
    by_place: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    by_dir: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    confusion: Counter = Counter()
    for pid, pdir, pv, lv, ldir, lexp, unit, gap in pairs:
        ok = int(pv == lv)
        by_class[pv][0] += ok; by_class[pv][1] += 1
        by_place[pid][pv][0] += ok; by_place[pid][pv][1] += 1
        by_dir[pdir][0] += ok; by_dir[pdir][1] += 1
        confusion[(pv, lv)] += 1
        if lexp and ldir == pdir:
            by_class_dir[pv][0] += ok; by_class_dir[pv][1] += 1
    ctl: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for av, bv in control:
        ctl[av][0] += int(av == bv); ctl[av][1] += 1

    classes = {}
    for v in ("open", "congested", "closed", "slow"):
        a, n = by_class.get(v, [0, 0]); ca, cn = ctl.get(v, [0, 0]); da, dn = by_class_dir.get(v, [0, 0])
        if not n and not cn:
            continue
        classes[v] = {"pairs": n, "agreement": _rate(a, n),
                      "control_pairs": cn, "control_agreement": _rate(ca, cn),
                      "direction_explicit_pairs": dn, "direction_explicit_agreement": _rate(da, dn),
                      "gap_to_control": (round(_rate(a, n) - _rate(ca, cn), 3)
                                         if n and cn else None)}
    worst = []
    for pid, per in by_place.items():
        n = sum(x[1] for x in per.values()); a = sum(x[0] for x in per.values())
        if n >= 20:
            worst.append({"place_id": pid, "name": names.get(pid), "pairs": n, "agreement": _rate(a, n),
                          "by_class": {v: {"pairs": x[1], "agreement": _rate(x[0], x[1])} for v, x in per.items()}})
    worst.sort(key=lambda r: r["agreement"])
    overall_n = sum(x[1] for x in by_class.values()); overall_a = sum(x[0] for x in by_class.values())
    ctl_n = sum(x[1] for x in ctl.values()); ctl_a = sum(x[0] for x in ctl.values())
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(), "days": days, "window_minutes": win,
        "overall": {"pairs": overall_n, "agreement": _rate(overall_a, overall_n),
                    "control_pairs": ctl_n, "control_agreement": _rate(ctl_a, ctl_n)},
        "by_class": classes,
        "by_direction": {d: {"pairs": x[1], "agreement": _rate(x[0], x[1])} for d, x in by_dir.items()},
        "confusion": {f"palhub={pv} live={lv}": c for (pv, lv), c in confusion.most_common()},
        "checkpoints_measured": len(by_place),
        "worst_checkpoints": worst[:15],
        "best_checkpoints": sorted(worst, key=lambda r: -r["agreement"])[:5],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--window", type=int, default=90)
    ap.add_argument("--out", default=str(ROOT / "ops" / "palhub-earnout.json"))
    a = ap.parse_args()
    r = measure(a.days, a.window)
    Path(a.out).write_text(json.dumps(r, ensure_ascii=False, indent=1))
    o = r["overall"]
    print(f"palhub vs channels, {a.days} d, ±{a.window} min: {o['pairs']:,} pairs agree {o['agreement']} "
          f"| control (channel vs channel) {o['control_pairs']:,} pairs agree {o['control_agreement']}")
    print(f"{'class':<10}{'pairs':>8}{'agree':>8}{'ctl n':>8}{'ctl':>8}{'gap':>8}{'dir n':>8}{'dir':>8}")
    for v, c in r["by_class"].items():
        print(f"{v:<10}{c['pairs']:>8}{str(c['agreement']):>8}{c['control_pairs']:>8}{str(c['control_agreement']):>8}"
              f"{str(c['gap_to_control']):>8}{c['direction_explicit_pairs']:>8}{str(c['direction_explicit_agreement']):>8}")
    print("by direction:", r["by_direction"])
    print("confusion:", dict(list(r["confusion"].items())[:8]))
    print(f"checkpoints measured (≥20 pairs): {len(r['worst_checkpoints'])} of {r['checkpoints_measured']}")
    for w in r["worst_checkpoints"][:8]:
        print(f"  worst {w['agreement']:<6} {w['pairs']:>5} {w['name']}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
