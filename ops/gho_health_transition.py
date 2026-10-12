"""What the first GHO run does to the held health rows, row by row. Read-only.

    .venv/bin/python -m ops.gho_health_transition            # counts, as JSON
    .venv/bin/python -m ops.gho_health_transition AIR_41     # one code, every row

The loader's dry run can say only that 12,502 held rows carry an identity the
fetch never emits (their key is indicator, year, VALUE and bounds; the new one
is indicator, year and dimensions). It cannot say what becomes of each. This
does, by the only fields both sides have: WHO's code, the year, the FIRST
dimension (the one v1's route kept) and the value.

  same_value   the fetch holds a row of that code, year and first dimension
               with the same value: the held row is restated with every
               dimension named
  revised      the code, year and first dimension are still published, the
               value is not: `one_to_one` where the group holds one row on
               each side, `in_group` where it holds several and nothing says
               which new row replaces which old one
  gone         WHO no longer publishes that code, year and first dimension
               (or publishes fewer rows there than are held)
and, on the fetch's side, `arrived`: rows no held row accounts for.

Writes nothing: one SELECT on the store, and the transformer run on the
fetched file. Run it right before the first real run to see that night's
numbers.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.databank import load_spec, transform_all             # noqa: E402
from resolve.db import connect                                   # noqa: E402

DATASET = "v1_health_who"


def held_rows() -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT o.observation_id, o.indicator, o.occurred_at, o.value_num,
                   o.unit, o.attrs, o.identity_key
            FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
            WHERE d.key = %s AND upper_inf(o.sys_period)""", (DATASET,))
        return [{"id": i, "indicator": ind, "year": occ.year, "value": val,
                 "unit": unit, "attrs": attrs or {}, "key": key}
                for i, ind, occ, val, unit, attrs, key in cur.fetchall()]


def emitted_rows() -> tuple[list, Counter]:
    spec = load_spec("health")
    drops: Counter = Counter()
    rows = [r for _f, r in transform_all("health", spec, {}, Counter(), drops)]
    return rows, drops


def _first_dim(dim_key: str) -> str | None:
    return dim_key.split(";")[0].split("=", 1)[1] if dim_key else None


def classify(held: list[dict], emitted: list) -> dict:
    by_group = defaultdict(list)
    for r in emitted:
        by_group[(r.attrs["indicator_code"], int(r.occurred_at[:4]),
                  _first_dim(r.attrs["dim_key"]))].append(r)
    held_group = defaultdict(list)
    for h in held:
        # v1 wrote the kept dimension as attrs.code; a row with none has no key
        held_group[(h["attrs"].get("indicator_code"), h["year"],
                    h["attrs"].get("code"))].append(h)

    out = Counter()
    per_row = []                        # (held row, verdict, the fetch's row or None)
    taken: set[int] = set()
    for g, hs in held_group.items():
        pool = list(by_group.get(g, []))
        left = []
        for h in hs:
            hit = next((r for r in pool
                        if float(r.value_num) == float(h["value"])), None)
            if hit is None:
                left.append(h)
                continue
            pool.remove(hit)
            taken.add(id(hit))
            out["same_value"] += 1
            if not hit.attrs["dim_key"]:
                out["same_value:no_dimension"] += 1
            elif ";" in hit.attrs["dim_key"]:
                out["same_value:further_dimension_now_named"] += 1
            out[f"unit:{h['unit']}→{hit.unit}"] += 1
            per_row.append((h, "same_value", hit))
        for h in left:
            if not pool:
                out["gone"] += 1
                per_row.append((h, "gone", None))
            elif len(hs) == 1 and len(by_group[g]) == 1:
                hit = pool.pop()
                taken.add(id(hit))
                out["revised:one_to_one"] += 1
                per_row.append((h, "revised:one_to_one", hit))
            else:
                out["revised:in_group"] += 1
                per_row.append((h, "revised:in_group", None))
    # every fetched row of a group that holds a revised-in-group held row is
    # its group's answer; what is left over elsewhere arrived
    revised_groups = {(h["attrs"].get("indicator_code"), h["year"],
                       h["attrs"].get("code"))
                      for h, verdict, _ in per_row if verdict == "revised:in_group"}
    arrived = [r for g, rs in by_group.items() for r in rs
               if id(r) not in taken and g not in revised_groups]
    in_revised_groups = sum(1 for g in revised_groups for r in by_group[g]
                            if id(r) not in taken)
    # why a row arrived: the three things that can make a fetched row one no
    # held row accounts for
    held_values = {g: {float(h["value"]) for h in hs} for g, hs in held_group.items()}
    newest = defaultdict(int)
    for (c, y, _d), _hs in held_group.items():
        newest[c] = max(newest[c], y)
    why = {}
    for g, rs in by_group.items():
        for r in rs:
            if id(r) in taken or g in revised_groups:
                continue
            if float(r.value_num) in held_values.get(g, ()):
                reason = "same_value_as_a_sibling_v1_kept_once"
            elif g[1] > newest[g[0]]:
                reason = "a_year_newer_than_any_held_for_the_code"
            elif g not in held_group:
                reason = "a_year_or_first_dimension_not_held"
            else:
                reason = "another_row_beside_held_ones"
            why[id(r)] = reason
            out[f"arrived:{reason}"] += 1
    for r in arrived:
        r.attrs["_why"] = why[id(r)]
    out["fetch:rows"] = len(emitted)
    out["fetch:arrived"] = len(arrived)
    out["fetch:in_a_group_revised_as_a_whole"] = in_revised_groups
    out["held:rows"] = len(held)
    return {"counts": dict(sorted(out.items())), "per_row": per_row,
            "arrived": arrived}


def main(argv: list[str]) -> int:
    held = held_rows()
    emitted, drops = emitted_rows()
    res = classify(held, emitted)
    code = next((a for a in argv if not a.startswith("--")), None)
    if code:
        print(f"HELD ({DATASET}, current rows of {code}):")
        for h, verdict, hit in sorted(
                (x for x in res["per_row"] if x[0]["attrs"].get("indicator_code") == code),
                key=lambda x: (x[0]["year"], x[0]["indicator"], x[0]["value"])):
            print(f"  {h['year']}  {h['indicator']}  {h['value']}  unit={h['unit']}"
                  f"  → {verdict}" + (f": {hit.indicator}" if hit else ""))
        print(f"FETCHED ({code}, as t_health emits):")
        for r in sorted((r for r in emitted if r.attrs["indicator_code"] == code),
                        key=lambda r: (r.occurred_at, r.indicator)):
            print(f"  {r.occurred_at[:4]}  {r.indicator}  {r.value_num}  unit={r.unit}"
                  f"  {r.attrs['dim_label']}  updated {str(r.reported_at)[:10]}")
        return 0
    arrived = res["arrived"]
    samples = {}
    for r in sorted(arrived, key=lambda r: (r.occurred_at, r.indicator), reverse=True):
        samples.setdefault(r.attrs["_why"], [])
        if len(samples[r.attrs["_why"]]) < 3:
            samples[r.attrs["_why"]].append(
                f"{r.indicator}@{r.occurred_at[:4]} = {r.value_num} {r.unit}")
    print(json.dumps({
        "dataset": DATASET, "drops": dict(drops), **res["counts"],
        "arrived_by_code": dict(Counter(r.attrs["indicator_code"]
                                        for r in arrived).most_common(12)),
        "arrived_samples": samples,
        "indicator_names": {
            "held": len({h["indicator"] for h in held}),
            "fetched": len({r.indicator for r in emitted}),
            "kept": len({h["indicator"] for h in held} & {r.indicator for r in emitted}),
        },
    }, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
