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


def load_dataset_rules() -> dict:
    """name -> {indicator_prefix, rules, max_unclassified} for the datasets no
    mapping spec describes."""
    f = REGISTRY / "datasets.yaml"
    if not f.exists():
        return {}
    doc = yaml.safe_load(f.read_text()) or {}
    out = {}
    for name, reg in (doc.get("datasets") or {}).items():
        if not (reg or {}).get("indicator_prefix"):
            raise SystemExit(f"db/registry/datasets.yaml: {name} declares no "
                             "indicator_prefix — it would speak for every indicator")
        out[name] = reg
    return out


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
          "canonical_unit", "name_en", "name_ar",
          "serve_warning", "serve_warning_ar", "ask_by_name")


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


def unclassified_by_reader(read: list[tuple]) -> dict[str, list[str]]:
    """What each reader (a spec, or an entry of datasets.yaml) leaves without a
    meaning: the indicators it sees that NO reader classified. `read` is
    [(name, pairs, got)]. Every reader is classified before any is judged, so
    the answer does not depend on the order they were read in."""
    anywhere: set[str] = set()
    for _name, _pairs, got in read:
        anywhere |= set(got)
    return {name: sorted({i for i, _u, _n in pairs} - anywhere)
            for name, pairs, _got in read}


# ── names ────────────────────────────────────────────────────────────────────
# Measured 2026-10-12: 8 of 2,105 indicator definitions had a name. An answer
# said "health.m_est_cig_curr_std.sex_fmle: 4.9" and the search matched only
# on the key. A name comes, in this order, from:
#   1. the spec rule that classifies the indicator (name_en / name_ar);
#   2. db/registry/names.yaml `names:` (written and reviewed by hand);
#   3. the PUBLISHER's own name, already carried on the rows as
#      attrs.indicator_name (WHO, the World Bank, the IMF: 1,160 indicators),
#      with the row's dimension label after it when the indicator is one cut
#      of a series ("… — Female"). Its Arabic is looked up by that English
#      name in names.yaml (`publisher_names`, `dimension_names`), so a new
#      indicator of a known series is named without anyone typing it.
# A definition marked `reviewed` is never renamed here.
NAMES = Path(__file__).resolve().parent.parent / "db" / "registry" / "names.yaml"


def _clean(s) -> str | None:
    s = " ".join(str(s or "").split())
    return s or None


def load_names() -> dict:
    doc = (yaml.safe_load(NAMES.read_text(encoding="utf-8")) if NAMES.exists() else None) or {}
    return {"names": doc.get("names") or {},
            "publisher_names": {_clean(k): v for k, v in (doc.get("publisher_names") or {}).items()},
            "dimension_names": {_clean(k): v for k, v in (doc.get("dimension_names") or {}).items()}}


def derive_name(carried: tuple | None, doc: dict) -> tuple[str | None, str | None]:
    """(name_en, name_ar) from what the rows carry. `carried` is
    (publisher's indicator name, distinct dimension labels on the rows, one of them)."""
    if not carried or not _clean(carried[0]):
        return None, None
    base, n_dims, dim = _clean(carried[0]), carried[1], _clean(carried[2])
    one_cut = n_dims == 1 and dim
    en = f"{base} — {dim}" if one_cut else base
    ar = doc["publisher_names"].get(base)
    if ar and one_cut:
        # a cut may name several dimensions ("Both sexes; 15-19 years")
        parts = [doc["dimension_names"].get(_clean(x)) for x in dim.split("; ")]
        ar = f"{ar} — {'؛ '.join(parts)}" if all(parts) else None   # half a name is not a name
    return en, ar


def name_for(indicator: str, rule_meta: dict | None, carried: tuple | None,
             doc: dict) -> tuple[str | None, str | None]:
    exact = doc["names"].get(indicator) or {}
    d_en, d_ar = derive_name(carried, doc)
    rule = rule_meta or {}
    return (_clean(rule.get("name_en")) or _clean(exact.get("en")) or d_en,
            _clean(rule.get("name_ar")) or _clean(exact.get("ar")) or d_ar)


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
        # ...and the EVENT-shaped indicators, which live in `event`, not in
        # `observation`. The census read only observations, so an event
        # indicator had a definition only if a migration typed one (083 did,
        # for UCDP and the 1948 localities). Insecurity Insight's eight
        # `attack.*` series, 20,174 served events loaded on 2026-10-11, had
        # none, and the first nightly-style run of this loader left them out
        # (2026-10-12: "8 served indicators with no definition").
        cur.execute("SELECT to_regclass('databank_event_rows') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("""SELECT COALESCE(v1_category, dataset_key), indicator,
                                  unit, count(*)
                           FROM databank_event_rows GROUP BY 1, 2, 3""")
            for cat, ind, unit, n in cur.fetchall():
                live.setdefault(cat, []).append((ind, unit, n))

        # indicator_def.ask_by_name (migration 114): absent, the flag is not written
        cur.execute("""SELECT count(*) FROM information_schema.columns
                        WHERE table_name = 'indicator_def' AND column_name = 'ask_by_name'""")
        has_by_name = bool(cur.fetchone()[0])
        by_name_written = 0
        total_unclassified = 0
        warned = 0
        declared_warnings = 0
        problems = []
        # An indicator classified by ANY spec is classified. Two specs can
        # share one serving category — conflict_westbank declares
        # `v1_category: conflict` — so per-spec accounting counts conflict's
        # ten indicators as unclassified against the spec that has no rules
        # for them, which is a report about the bookkeeping rather than the
        # data.
        #
        # ANY spec, whatever its place in the alphabet. The set used to fill
        # as the loop went, so it only excused a spec read AFTER the one that
        # held the rules: acled_hdx, btselem_fatalities and fao_diem, loaded
        # on 2026-10-11, sort before conflict, casualties and food, and the
        # loader refused all three for indicators their siblings classify.
        # Nobody ran it after those loads: on 2026-10-12, 717 of 2,047 served
        # indicators (105,908 rows) had no indicator_def row, and `series`,
        # `compare`, `correlate` and the indicator search answer "no series
        # named ..." for a row that does not exist. Every spec is classified
        # first; the accounting follows.
        classified_anywhere: set[str] = set()
        read: list[tuple] = []
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
            rules = (reg or {}).get("rules") or []
            got, conflicts = classify(pairs, rules)
            classified_anywhere |= set(got)
            read.append((p, reg, pairs, got, conflicts))
        # Datasets written by their own ingest module declare their rules in
        # db/registry/datasets.yaml (see its header: the Ministry's bulletins
        # had none and no question could reach them).
        for name, reg in sorted(load_dataset_rules().items()):
            pairs = [x for rows in live.values() for x in rows
                     if x[0].startswith(reg["indicator_prefix"])]
            if not pairs:
                continue
            got, conflicts = classify(pairs, reg.get("rules") or [])
            classified_anywhere |= set(got)
            read.append((Path(name), reg, pairs, got, conflicts))
        left = unclassified_by_reader([(p.stem, pairs, got)
                                       for p, _reg, pairs, got, _c in read])
        for p, reg, pairs, got, conflicts in read:
            inds = {i for i, _u, _n in pairs}
            declared_warnings += sum(1 for m in got.values() if m.get("serve_warning"))
            missing = left[p.stem]
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
                # A warning is the spec's statement about the SOURCE, so it is
                # written whatever the row's review status. A rule that
                # declares none leaves the column alone.
                if meta.get("serve_warning"):
                    cur.execute("""UPDATE indicator_def
                                      SET serve_warning = %s, serve_warning_ar = %s
                                    WHERE indicator = %s
                                      AND (serve_warning, serve_warning_ar)
                                          IS DISTINCT FROM (%s, %s)""",
                                (meta["serve_warning"], meta.get("serve_warning_ar"),
                                 ind, meta["serve_warning"],
                                 meta.get("serve_warning_ar")))
                    warned += cur.rowcount
                # Like the warning, the spec's statement about the SERIES, so it
                # is written whatever the row's review status, and it follows
                # the rule both ways: a rule that stops saying it clears it.
                if has_by_name:
                    want = meta.get("ask_by_name") is True
                    cur.execute("UPDATE indicator_def SET ask_by_name = %s "
                                "WHERE indicator = %s AND ask_by_name IS DISTINCT FROM %s",
                                (want, ind, want))
                    by_name_written += cur.rowcount
            # Unclassified indicators get a ROW too, marked as such. A
            # missing row and a row saying "nobody has classified this" look
            # identical to a query and are completely different facts.
            for ind in missing:
                cur.execute("""
                    INSERT INTO indicator_def (indicator, measure_kind,
                                               status, source_spec)
                    VALUES (%s,'unclassified','generated',%s)
                    ON CONFLICT (indicator) DO NOTHING""", (ind, p.stem))
        # ── names, for every definition whatever spec classified it ──
        doc = load_names()
        # The cut a row is: GHO's dimension labels ("Both sexes; Trachea,
        # bronchus, lung cancers") on rows fetched since 2026-10-12, or the one
        # label v1 kept beside a `type` before that. `attrs.name` alone is NOT
        # a cut: on IMF and World Bank rows it is the country, typed by v1.
        cur.execute("""
            SELECT indicator,
                   mode() WITHIN GROUP (ORDER BY attrs->>'indicator_name'),
                   count(DISTINCT COALESCE(lbl, '')), max(lbl)
              FROM (SELECT indicator, attrs,
                           CASE WHEN attrs ? 'dim_label'
                                THEN (SELECT string_agg(t.value, '; ' ORDER BY t.ord)
                                        FROM jsonb_each_text(attrs->'dim_label')
                                             WITH ORDINALITY AS t(key, value, ord))
                                WHEN attrs ? 'type' THEN attrs->>'name'
                           END AS lbl
                      FROM databank_serving
                     WHERE attrs ? 'indicator_name') x
             GROUP BY 1""")
        carried = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
        rule_meta: dict[str, dict] = {}
        for _p, _reg, _pairs, got, _c in read:
            rule_meta.update(got)
        named_en = named_ar = renamed = 0
        unnamed: list[str] = []
        for ind in sorted(classified_anywhere):
            en, ar = name_for(ind, rule_meta.get(ind), carried.get(ind), doc)
            named_en += bool(en)
            named_ar += bool(ar)
            if not en:
                unnamed.append(ind)
                continue
            if apply:
                # a name already there is replaced only by a name; an Arabic
                # name is never blanked because this run found none
                cur.execute("""UPDATE indicator_def
                                  SET name_en = %s, name_ar = COALESCE(%s, name_ar)
                                WHERE indicator = %s AND status <> 'reviewed'
                                  AND (name_en, name_ar)
                                      IS DISTINCT FROM (%s, COALESCE(%s, name_ar))""",
                            (en, ar, ind, en, ar))
                renamed += cur.rowcount
        report["names"] = {"named_en": named_en, "named_ar": named_ar,
                           "unnamed": len(unnamed), "unnamed_sample": unnamed[:12]}
        if apply:
            conn.commit()
        print(f"{len(classified_anywhere)} indicator(s) now carry a concept "
              "and a measure kind")
        print(f"{named_en} indicator(s) have an English name, {named_ar} an Arabic one"
              + (f" · {renamed} written or changed" if apply else "")
              + (f" · {len(unnamed)} still unnamed, e.g. {unnamed[:3]}" if unnamed else ""))
        print(f"{declared_warnings} indicator(s) have a serve warning declared"
              + (f" · {warned} written or changed" if apply else ""))
        n_by_name = sum(1 for m in rule_meta.values() if m.get("ask_by_name"))
        print(f"{n_by_name} indicator(s) are served when asked for by name"
              + (f" · {by_name_written} written or changed" if apply and has_by_name else "")
              + ("" if has_by_name else " · indicator_def.ask_by_name is absent (migration 114): not written"))

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
