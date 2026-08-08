"""Prove a v1 CUT changed nothing — keyed on what a row is, not on v1's hash.

ops/spec_equivalence.py proves a refactor changed nothing, and it works because
a refactor leaves `v1_stable_id` alone: it can sort both sides by that id and
compare row i to row i. A v1 cut cannot use it. The whole point of the cut is
to stop reading v1, and v1's `stable_id` is a CONTENT HASH computed inside
v1 — a v2-native fetcher cannot reproduce it and should not try, because that
hash re-deriving itself is the bug that re-inserted 19,451 observations on
2026-08-07. So every row's id legitimately changes, every row sorts to a new
position, and spec_equivalence reports 100% difference on a cut that in fact
moved nothing.

WHAT THIS COMPARES INSTEAD is the spec's own declared `identity:` — the natural
key that says what a row IS independent of anyone's hashing. Rows are matched
across the cut by identity, and then:

  same        every field a database column reads is identical
  provenance  only v1_stable_id / reported_at moved — expected, and the reason
              this tool exists rather than spec_equivalence
  CHANGED     a field that carries meaning moved. This is the finding.
  arrived     an identity the new input has and v1 did not
  departed    an identity v1 had and the new input does not

`arrived` and `departed` are not failures by themselves — a live upstream that
v1 stopped fetching SHOULD have arrivals, and that is exactly what the T4P cut
found. They are failures when they are not explained, so the report records
them and the operator states which they expected.

    .venv/bin/python -m ops.cut_equivalence martyrs_snapshot_2023 --before
    #   ... make the cut: repoint input:, write the v2-native transformer ...
    .venv/bin/python -m ops.cut_equivalence martyrs_snapshot_2023

TWO ARTIFACTS, following spec_equivalence's split:
  ops/cuts/<cat>-before.json.gz   every pre-cut tuple. GITIGNORED.
  ops/cuts/report.json            what each cut did, in counts and samples.
                                  COMMITTED — the record of the v1 cut, one
                                  entry per category, reviewable in the diff.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.databank import load_spec                              # noqa: E402
from ops.spec_equivalence import capture                           # noqa: E402

BASE = Path(__file__).resolve().parent / "cuts"
REPORT = BASE / "report.json"

# The two fields a cut is ALLOWED to move, and only these.
#   v1_stable_id  v1's content hash. A v2-native id is deterministic from the
#                 publisher's own key instead, which is strictly better: it
#                 does not re-derive itself when the content changes.
#   reported_at   v1's fetched_at becomes ours. Same meaning, different clock.
PROVENANCE = ("v1_stable_id", "reported_at")


def _identity(row: dict, ident: dict | None) -> str:
    """The spec's declared identity, computed from a captured tuple.

    Mirrors ingest.databank.identity_key_for, but reads the flat dict that
    spec_equivalence emits (where attrs is already a canonical JSON string)
    rather than a Row.
    """
    if row.get("event_type") is not None:
        # Events declare `event_identity:` and the loader keys them on what
        # happened, where, when, at what scale. Same shape here.
        return "|".join(["event", row["dataset_key"], row["event_type"],
                         str(row["occurred_at"])[:10], str(row.get("place_id")),
                         str(row.get("lat")), str(row.get("lon")),
                         str(row.get("metrics"))])
    if not ident:
        # No declared identity: fall back to everything that is not
        # provenance. Weaker, and the report says so.
        return "|".join(f"{k}={row[k]}" for k in sorted(row)
                        if k not in PROVENANCE)
    parts = [row["dataset_key"]]
    attrs = json.loads(row["attrs"]) if row.get("attrs") else {}
    for f in ident.get("fields", []):
        parts.append("" if row.get(f) is None else str(row[f]))
    for a in ident.get("attrs", []):
        parts.append("" if attrs.get(a) is None else str(attrs[a]))
    return "|".join(parts)


def _identities(cap: dict, spec: dict) -> dict[str, dict]:
    """Captured rows, keyed by identity. Collisions are counted, never merged —
    a cut is not the place to discover the identity is not injective, and Gate
    6 owns that question, so this only reports it."""
    by_ds = {}
    for ds in spec.get("datasets", []):
        by_ds[ds["key"]] = ((ds.get("overrides") or {}).get("identity")
                            or spec.get("identity"))
    out: dict[str, dict] = {}
    dupes = 0
    for r in cap["rows"]:
        k = _identity(r, by_ds.get(r["dataset_key"]))
        if k in out:
            dupes += 1
            k = f"{k}#{dupes}"
        out[k] = r
    cap["_identity_collisions"] = dupes
    return out


def diff(before: dict, after: dict, spec: dict, limit: int = 8) -> dict:
    a = _identities(before, spec)
    b = _identities(after, spec)
    same = prov = 0
    changed: list[str] = []
    for k in a.keys() & b.keys():
        moved = [f for f in a[k]
                 if f not in PROVENANCE and a[k][f] != b[k].get(f)]
        if moved:
            if len(changed) < limit:
                changed.append("; ".join(
                    f"{f}: {a[k][f]!r} → {b[k].get(f)!r}" for f in moved)
                    + f"   [{k[:70]}]")
        elif any(a[k][f] != b[k].get(f) for f in PROVENANCE):
            prov += 1
        else:
            same += 1
    n_changed = sum(1 for k in a.keys() & b.keys()
                    if any(a[k][f] != b[k].get(f)
                           for f in a[k] if f not in PROVENANCE))
    return {
        "records_read": [before["records_read"], after["records_read"]],
        "emitted": [before["emitted"], after["emitted"]],
        "matched": len(a.keys() & b.keys()),
        "same": same, "provenance_only": prov, "changed": n_changed,
        "arrived": len(b.keys() - a.keys()),
        "departed": len(a.keys() - b.keys()),
        "identity_collisions": [before.get("_identity_collisions", 0),
                                after.get("_identity_collisions", 0)],
        "changed_samples": changed,
        "arrived_samples": [k[:100] for k in
                            sorted(b.keys() - a.keys())[:limit]],
        "departed_samples": [k[:100] for k in
                             sorted(a.keys() - b.keys())[:limit]],
    }


def main(argv: list[str]) -> int:
    cats = [a for a in argv if not a.startswith("--")]
    if not cats:
        print(__doc__.strip().splitlines()[0])
        print("\n  usage: cut_equivalence <category> [--before] [--record]")
        return 2
    BASE.mkdir(exist_ok=True)
    before_mode = "--before" in argv
    record = "--record" in argv
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    bad = 0
    for cat in cats:
        cap = capture(cat)
        path = BASE / f"{cat}-before.json.gz"
        if before_mode:
            path.write_bytes(gzip.compress(json.dumps(
                cap, ensure_ascii=False, sort_keys=True).encode()))
            print(f"  before {cat}: {cap['emitted']} rows from "
                  f"{cap['records_read']} records → {path.name}")
            continue
        if not path.exists():
            print(f"  MISS {cat}: no before-state. Run --before BEFORE the "
                  "cut; there is nothing to compare against afterwards.")
            bad += 1
            continue
        d = diff(json.loads(gzip.decompress(path.read_bytes())), cap,
                 load_spec(cat))
        print(f"\n  {cat}")
        print(f"    records_read {d['records_read'][0]} → "
              f"{d['records_read'][1]}   emitted {d['emitted'][0]} → "
              f"{d['emitted'][1]}")
        print(f"    matched {d['matched']}  "
              f"(identical {d['same']}, provenance-only "
              f"{d['provenance_only']}, CHANGED {d['changed']})")
        print(f"    arrived {d['arrived']}   departed {d['departed']}")
        for s in d["changed_samples"]:
            print(f"      CHANGED  {s}")
        for s in d["arrived_samples"]:
            print(f"      arrived  {s}")
        for s in d["departed_samples"]:
            print(f"      departed {s}")
        if d["changed"]:
            bad += 1
        if record:
            report[cat] = {k: v for k, v in d.items()
                           if not k.endswith("_samples")}
            report[cat]["changed_samples"] = d["changed_samples"]
    if record:
        REPORT.write_text(json.dumps(report, indent=1, sort_keys=True))
        print(f"\n  recorded {len(report)} cut(s) → {REPORT}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
