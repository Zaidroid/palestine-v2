"""Load the reviewed registry, and GENERATE indicator_def from the specs.

1,408 indicator strings cannot be typed by hand, and a hand-typed table would
be stale the day a source is added. So the split is:

  REVIEWED DOCUMENTS (db/registry/*.yaml) — concepts and units. Small, argued
  over, changed deliberately. ~35 concepts and ~20 units cover everything.

  GENERATED ROWS — indicator_def, produced by applying each spec's `registry:`
  rules to the indicators that spec actually emits. A rule is a prefix or a
  regex plus the meaning that follows from it, which is how 1,011 WHO GHO
  codes are classified by three lines rather than 1,011.

An indicator no rule matches lands `unclassified` and is COUNTED — law 4
applied to meaning rather than to records. A spec may declare
`registry.max_unclassified`; above it, this refuses.

Run:  .venv/bin/python -m ops.load_registry            # measure
      .venv/bin/python -m ops.load_registry --apply    # write
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.databank import SPECS, SpecRefused, load_spec         # noqa: E402
from resolve.db import connect                                    # noqa: E402

REGISTRY = Path(__file__).resolve().parent.parent / "db" / "registry"


# ── the reviewed documents ───────────────────────────────────────────────────

def load_concepts(cur, apply: bool) -> int:
    doc = yaml.safe_load((REGISTRY / "concepts.yaml").read_text())["concepts"]
    # Parents before children, or the self-reference fails.
    ordered = sorted(doc.items(), key=lambda kv: (kv[1].get("parent") is not None,
                                                  kv[0]))
    if apply:
        for key, c in ordered:
            cur.execute("""
                INSERT INTO concept (key, parent, name_en, name_ar, definition,
                                     notes)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (key) DO UPDATE SET
                    parent=EXCLUDED.parent, name_en=EXCLUDED.name_en,
                    name_ar=EXCLUDED.name_ar, definition=EXCLUDED.definition,
                    notes=EXCLUDED.notes""",
                (key, c.get("parent"), c["name_en"], c.get("name_ar"),
                 c["definition"], c.get("notes")))
    return len(ordered)


def load_units(cur, apply: bool) -> tuple[int, int]:
    doc = yaml.safe_load((REGISTRY / "units.yaml").read_text())["units"]
    n_alias = 0
    if apply:
        for key, u in doc.items():
            cur.execute("""
                INSERT INTO unit_def (key, name_en, name_ar, dimension, notes)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (key) DO UPDATE SET
                    name_en=EXCLUDED.name_en, name_ar=EXCLUDED.name_ar,
                    dimension=EXCLUDED.dimension, notes=EXCLUDED.notes""",
                (key, u["name_en"], u.get("name_ar"), u["dimension"],
                 u.get("notes")))
        # Aliases in a second pass: an alias may point at a unit defined
        # further down the file (`buildings` -> `structures`), and a
        # single-pass loader would fail on a document that reads perfectly.
        for key, u in doc.items():
            for raw, a in (u.get("aliases") or {}).items():
                a = a or {}
                cur.execute("""
                    INSERT INTO unit_alias (raw, unit_key, factor_num,
                                            factor_den, note)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (raw) DO UPDATE SET
                        unit_key=EXCLUDED.unit_key,
                        factor_num=EXCLUDED.factor_num,
                        factor_den=EXCLUDED.factor_den, note=EXCLUDED.note""",
                    (raw, a.get("unit", key), a.get("factor_num", 1),
                     a.get("factor_den", 1), a.get("note")))
                n_alias += 1
            # A unit is always an alias of itself, so a source writing the
            # canonical name resolves without a redundant YAML entry.
            if key not in (u.get("aliases") or {}):
                cur.execute("""INSERT INTO unit_alias (raw, unit_key)
                               VALUES (%s,%s) ON CONFLICT (raw) DO NOTHING""",
                            (key, key))
    return len(doc), n_alias


# ── the generated rows ───────────────────────────────────────────────────────

def matches(rule: dict, indicator: str, unit: str | None) -> bool:
    w = rule.get("when") or {}
    if "prefix" in w and not indicator.startswith(w["prefix"]):
        return False
    if "regex" in w and not re.search(w["regex"], indicator):
        return False
    if "equals" in w and indicator != w["equals"]:
        return False
    if "not_prefix" in w and indicator.startswith(w["not_prefix"]):
        return False
    # `unit` matches the RAW unit string the source wrote. It is here because
    # health's 1,011 WHO GHO codes cannot have their measure_kind read off
    # their names — SP.POP.65UP.TO.ZS tells you nothing — but their units can:
    # a percentage is a ratio, a per_1000 is a rate, a plain number is a
    # stock. That is a declared mapping, not an inference about the code.
    if "unit" in w:
        want = w["unit"] if isinstance(w["unit"], list) else [w["unit"]]
        if unit not in want:
            return False
    return bool(w)


FIELDS = ("concept", "measure_kind", "polarity", "grain", "place_grain",
          "canonical_unit", "name_en", "name_ar")


def classify(pairs: list[tuple[str, str | None, int]],
             rules: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """Ordered, first match wins — the same grammar posture as occurred_at.

    `pairs` is (indicator, unit, rows). An indicator may appear with several
    units — aid_access counts consignments in pallets, tonnes AND lorries
    under one name — and indicator_def holds one row per indicator. The
    variant carrying the MOST rows decides, and the disagreement is recorded
    on the row rather than resolved silently.
    """
    best: dict[str, tuple[int, dict]] = {}
    conflict: dict[str, set] = {}
    for ind, unit, n in pairs:
        for rule in rules:
            if matches(rule, ind, unit):
                meta = {f: rule.get(f) for f in FIELDS}
                if ind in best and best[ind][1]["measure_kind"] != \
                        meta["measure_kind"]:
                    conflict.setdefault(ind, set()).add(
                        best[ind][1]["measure_kind"])
                    conflict[ind].add(meta["measure_kind"])
                if ind not in best or n > best[ind][0]:
                    best[ind] = (n, meta)
                break
    out = {i: m for i, (_n, m) in best.items()}
    for ind, kinds in conflict.items():
        out[ind]["notes"] = (
            "this indicator appears under more than one unit with different "
            f"measure kinds ({sorted(kinds)}); the variant with the most rows "
            "decides and this note is the record that it was not unanimous")
    return out, sorted(conflict)


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    report: dict = {"specs": {}, "unclassified": []}
    with connect() as conn, conn.cursor() as cur:
        n_c = load_concepts(cur, apply)
        n_u, n_a = load_units(cur, apply)
        print(f"concepts {n_c} · units {n_u} · unit aliases {n_a}"
              f"{'' if apply else '  (dry run)'}")

        # Which indicators each category actually emits, measured rather than
        # predicted — a spec's `indicators:` list is a contract, not a census.
        cur.execute("""SELECT COALESCE(d.v1_category, d.key), o.indicator,
                              o.unit, count(*)
                       FROM observation o JOIN dataset d
                         ON d.dataset_id = o.dataset_id
                       WHERE upper_inf(o.sys_period)
                       GROUP BY 1, 2, 3""")
        live: dict[str, list] = {}
        for cat, ind, unit, n in cur.fetchall():
            live.setdefault(cat, []).append((ind, unit, n))

        total_unclassified = 0
        problems = []
        # An indicator classified by ANY spec is classified. Two specs can
        # share one serving category — conflict_westbank declares
        # `v1_category: conflict` — so per-spec accounting counts conflict's
        # ten indicators as unclassified against the spec that has no rules
        # for them, which is a report about the bookkeeping rather than the
        # data.
        classified_anywhere: set[str] = set()
        for p in sorted(SPECS.glob("*.yaml")):
            try:
                spec = load_spec(p.stem)
            except SpecRefused:
                continue
            reg = spec.get("registry")
            cat = spec.get("v1_category", spec["category"])
            pairs = live.get(cat, [])
            if not pairs:
                continue
            inds = {i for i, _u, _n in pairs}
            rules = (reg or {}).get("rules") or []
            got, conflicts = classify(pairs, rules)
            classified_anywhere |= set(got)
            missing = sorted(inds - set(got) - classified_anywhere)
            rows_missing = sum(n for i, _u, n in pairs if i in set(missing))
            report["specs"][p.stem] = {
                "indicators": len(inds), "classified": len(got),
                "unclassified": len(missing),
                "rows_unclassified": rows_missing,
                "unit_conflicts": conflicts}
            total_unclassified += len(missing)
            report["unclassified"] += sorted(missing)[:5]
            cap = (reg or {}).get("max_unclassified")
            if cap is not None and len(missing) > cap:
                problems.append(
                    f"{p.stem}: {len(missing)} unclassified indicators "
                    f"(max_unclassified {cap}) — e.g. {sorted(missing)[:3]}")
            print(f"  {p.stem:<24} {len(got):>5}/{len(inds):<5} classified"
                  + (f"   {len(missing)} left" if missing else ""))
            if not apply:
                continue
            for ind, meta in got.items():
                cur.execute("""
                    INSERT INTO indicator_def
                        (indicator, concept_key, name_en, name_ar,
                         canonical_unit, measure_kind, polarity, grain,
                         place_grain, status, source_spec, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'generated',%s,now())
                    ON CONFLICT (indicator) DO UPDATE SET
                        concept_key=EXCLUDED.concept_key,
                        canonical_unit=EXCLUDED.canonical_unit,
                        measure_kind=EXCLUDED.measure_kind,
                        polarity=EXCLUDED.polarity, grain=EXCLUDED.grain,
                        place_grain=EXCLUDED.place_grain,
                        source_spec=EXCLUDED.source_spec, updated_at=now()
                    WHERE indicator_def.status <> 'reviewed'""",
                    (ind, meta["concept"], meta["name_en"], meta["name_ar"],
                     meta["canonical_unit"],
                     meta["measure_kind"] or "unclassified",
                     meta["polarity"], meta["grain"], meta["place_grain"],
                     p.stem))
                if meta.get("notes"):
                    cur.execute("UPDATE indicator_def SET notes = %s "
                                "WHERE indicator = %s AND status <> 'reviewed'",
                                (meta["notes"], ind))
            # Unclassified indicators get a ROW too, marked as such. A
            # missing row and a row saying "nobody has classified this" look
            # identical to a query and are completely different facts.
            for ind in missing:
                cur.execute("""
                    INSERT INTO indicator_def (indicator, measure_kind,
                                               status, source_spec)
                    VALUES (%s,'unclassified','generated',%s)
                    ON CONFLICT (indicator) DO NOTHING""", (ind, p.stem))
        if apply:
            conn.commit()
        print(f"{len(classified_anywhere)} indicator(s) now carry a concept "
              "and a measure kind")

        cur.execute("""SELECT count(*) FROM databank_serving ds
                       LEFT JOIN unit_alias ua ON ua.raw = ds.unit
                       WHERE ds.unit IS NOT NULL AND ua.raw IS NULL""")
        unmapped_unit_rows = cur.fetchone()[0]

    print(f"\n{total_unclassified} indicator(s) unclassified across all specs")
    print(f"{unmapped_unit_rows} served row(s) carry a unit with no alias "
          "— value_canonical is NULL for those, never guessed")
    (Path(__file__).parent / "registry-load.json").write_text(
        json.dumps(report, indent=1, sort_keys=True))
    for pr in problems:
        print(f"REFUSED  {pr}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
