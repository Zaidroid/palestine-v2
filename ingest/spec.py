"""Format v2 — the key registry, and the validator that makes a spec TRUE.

TRAP-4 says the spec is the reviewable artifact: every decision is written
here first, reviewed as a document, and only then executed. That promise has
one failure mode, and on 2026-08-08 we measured it live:

    place.min_resolved_pct is declared in 20 of 24 specs and read by NOTHING.

Twenty documents assert a resolution floor. Twenty reviewers could read those
documents and conclude the loader would fail a run that resolved less. It
would not. And while that dead floor sat there looking like a guard, v1 quietly
dropped `location.admin2_pcode` from every education and infrastructure record
— 5,896 rows whose specs promise 0.999 and 0.92 pcode resolution and which now
measure 0.000. The floor that existed to catch exactly that had no teeth,
because nobody had ever asked the code whether it read the key.

So the format gets a registry. Every key path any spec may contain is listed
here with what the machine does about it:

    enforced      generic loader code reads it; changing the VALUE changes
                  behaviour without touching Python.
    implemented   real behaviour, hand-written in the category's transformer.
                  The engine migration (Stage 3) converts these to `enforced`
                  one construct at a time behind ops/spec_equivalence.py.
                  Type-checked here; obedience is proven by the equivalence
                  harness, not by this file.
    rationale     prose. Measured counts, notes, reasoning. No behaviour, and
                  the validator SAYS so rather than letting it look like a rule.
    data_map      the node's child keys are DATA (crosswalk entries, upstream
                  source names), not schema. Values are shape-checked; keys
                  are not.
    unimplemented declared by some spec and doing nothing at all. `load_spec`
                  REFUSES. A spec may not promise what no code delivers.

An unknown key is refused too, with a spelling suggestion — that is the other
half: a typo in a reviewed document currently reads as silence.

Run:  .venv/bin/python -m ingest.spec              # validate every spec
      .venv/bin/python -m ingest.spec --explain    # print the registry
"""
from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "db" / "mappings"

# The field names identity_key_for() can render. A spec naming anything else
# would KeyError deep inside a run, after the corpus is already half-read.
IDENTITY_FIELDS = ("indicator", "occurred_at", "occurred_at_exact",
                   "place_id", "value_num")

PRECISIONS = ("exact", "hour", "day", "month", "year", "unknown")

# Place strategies the loader knows. `fixed` and `none` are terminal; the rest
# are rungs a ladder may also use.
PLACE_RUNGS = ("pcode", "admin2_pcode", "latlon", "gazetteer_key", "name",
               "region", "crossing", "none")

COLLISION_KINDS = (
    # the same fact recorded twice — keep the key, supersede the copy
    "duplicate_fact",
    # different things the source records identically (aid_access's 50,059
    # UNRWA consignments have no per-consignment id anywhere) — no stored key
    # is possible; 044 + expect.max_observations guard it instead
    "indistinguishable",
)


class SpecRefused(RuntimeError):
    """The loader will not run this category. Lives here rather than in
    databank.py so SpecInvalid can be one — see below."""


class SpecInvalid(SpecRefused):
    """Raised with EVERY problem found, not just the first — a spec author
    fixing one key at a time through six round trips is how review dies.

    A SUBCLASS of SpecRefused, and that is not tidiness. run_all() catches
    SpecRefused to fail one category and carry on with the other twenty; a
    validation error that escaped that net would abort the whole nightly
    because one spec had a typo. Caught by two Stage-2 tests within an hour
    of the validator landing, which is what those tests are for."""


@dataclass(frozen=True)
class Key:
    cls: str
    note: str
    types: tuple = ()          # accepted python types; () = anything
    values: tuple = ()         # allowed literals; () = unconstrained
    check: Callable[[Any], str | None] | None = None
    child_check: Callable[[Any], str | None] | None = None   # data_map values
    # "value": the node's children are part of a structured VALUE this key's
    # own `check` validates as a whole (a condition tree), not schema paths
    # to be walked. Without this a {field, op, value} triple reads as three
    # unknown keys — which is the validator being right about the wrong thing.
    cls_children: str = "schema"


def _pct(v) -> str | None:
    if not isinstance(v, (int, float)) or not 0 <= v <= 1:
        return f"must be a fraction in [0, 1], got {v!r}"
    return None


def _crosswalk_value(v) -> str | None:
    if v is None:
        return None                     # an explicit "resolves to nothing"
    if not isinstance(v, dict) or "kind" not in v or "name_en" not in v:
        return ("must be null or {kind, name_en} — crosswalks key on gazetteer "
                f"name_en, never place_id, so a rebuild cannot repoint them; "
                f"got {v!r}")
    return None


CONDITION_OPS = ("always", "eq", "ne", "in", "endswith", "startswith",
                 "present", "absent", "equals_fetch_day")


def _condition(v, depth: int = 0) -> str | None:
    """The closed grammar, validated where a reviewer can see the error rather
    than at row 40,000 of a run. Kept in step with engine.OPS by a test."""
    if depth > 4:
        return "conditions nest at most 4 deep"
    if not isinstance(v, dict):
        return f"a condition must be a mapping, got {type(v).__name__}"
    for combinator in ("all", "any"):
        if combinator in v:
            if not isinstance(v[combinator], list) or not v[combinator]:
                return f"`{combinator}` must be a non-empty list"
            for sub in v[combinator]:
                err = _condition(sub, depth + 1)
                if err:
                    return err
            return None
    op = v.get("op", "always")
    if op not in CONDITION_OPS:
        return (f"unknown operator {op!r} — the grammar is "
                f"{list(CONDITION_OPS)}, and it is closed on purpose: a spec "
                "that can express arbitrary code is not a document a reviewer "
                "can check")
    if op == "always":
        return None
    if not v.get("field"):
        return f"op {op!r} needs a `field`"
    if op in ("eq", "ne", "in", "endswith", "startswith") and "value" not in v:
        return f"op {op!r} needs a `value`"
    if op == "in" and not isinstance(v.get("value"), list):
        return "op 'in' needs a list `value`"
    return None


def _identity_fields(v) -> str | None:
    # An EMPTY fields list is legal when attrs carry the identity alone
    # (education keys purely on attrs.school_id). That the identity as a whole
    # is non-empty is checked across keys, in _cross_checks, where both halves
    # are visible.
    if not isinstance(v, list):
        return f"must be a list, got {type(v).__name__}"
    bad = [f for f in v if f not in IDENTITY_FIELDS]
    if bad:
        return (f"unknown identity field(s) {bad} — identity_key_for() renders "
                f"only {list(IDENTITY_FIELDS)}. A name it cannot render raises "
                "mid-run, after half the corpus is read")
    return None


def _fallback(v) -> str | None:
    rungs = v if isinstance(v, list) else [v]
    bad = [r for r in rungs if r not in PLACE_RUNGS]
    if bad:
        return f"unknown place rung(s) {bad} — known: {list(PLACE_RUNGS)}"
    return None


# ── the registry ─────────────────────────────────────────────────────────────
# Paths use `[]` for a list element. Every path any spec contains must appear
# here; ops/spec_keys.py --audit is the reverse check.

R: dict[str, Key] = {}


def _k(path: str, cls: str, note: str, **kw) -> None:
    R[path] = Key(cls, note, **kw)


# -- identity of the document ------------------------------------------------
_k("category", "enforced", "v1 category directory name; the loader's key",
   types=(str,))
_k("shape", "enforced", "observation | event — which table rows land in",
   types=(str,), values=("observation", "event"))
_k("status", "enforced", "the ETL runs only on `reviewed`", types=(str,),
   values=("draft", "reviewed"))
_k("migrate", "enforced", "false = measured, specced, deliberately not loaded",
   types=(bool,))
_k("skip_reason", "enforced", "required whenever migrate is false", types=(str,))
_k("records_measured", "rationale",
   "the audit's record count at spec time; expect.min_records derives from it",
   types=(int,))
_k("notes", "rationale", "measured quirks a future editor needs", types=(str,))
_k("transform", "enforced",
   "which mechanism builds this category's rows: `engine` (the spec drives "
   "it) or `python:<name>` (a hand-written transformer). DECLARED, because a "
   "half-migrated format where nobody can tell which half they are reading "
   "is worse than an unmigrated one", types=(str,))
_k("attrs_literal", "data_map",
   "constants the spec ASSERTS about every row — a stock's reference point, "
   "a coverage caveat. These were hardcoded in the transformers, which is the "
   "wrong home for a sentence like 'West Bank, excludes East Jerusalem': it "
   "is a claim about the data, and it belongs where it can be reviewed",
   types=(dict,))
_k("rationale", "rationale",
   "prose that would otherwise sit in an executable slot. conflict's "
   "'NO-OP — must not fire' is documentation of a rule's ABSENCE, and putting "
   "it in `then:` made it look like a rule", types=(str, dict, list))
_k("v1_category", "enforced",
   "when the file name is not the serving category (conflict_westbank → "
   "conflict), which category's views its datasets join", types=(str,))

# -- input -------------------------------------------------------------------
_k("input", "enforced",
   "read somewhere other than v1's unified category: a v1 RAW tree, or a "
   "FROZEN corpus in this repository. A relative root resolves against the "
   "repo, so a frozen spec works on any machine", types=(dict,))
_k("cut_from_v1", "enforced",
   "the day this category stopped reading v1. ops/asof_harness.py claims the "
   "vault's evidence only for days before it, and replays those through "
   "ingest.databank.REPLAY_TRANSFORMERS[category] — the transformer that "
   "actually produced the stored rows", types=(str, date))
_k("cadence", "enforced",
   "`frozen` means the corpus is finished and read locally — measured by "
   "ops/v1_liveness.py, not assumed", types=(str,),
   values=("frozen", "daily", "weekly", "monthly", "annual", "irregular"))
_k("input.root", "enforced", "absolute path, strictly read-only", types=(str,))
_k("input.glob", "enforced",
   "one pattern or a list of them; index.json/recent.json always excluded. A "
   "list is how a spec names the publisher's own endpoints (T4P's roster and "
   "summary) instead of sweeping a directory and hoping",
   types=(str, list))
_k("input.object_as_record", "enforced",
   "a payload that is one JSON object IS one record (T4P /v3/summary.json). "
   "Off by default so a genuinely empty file still reads as empty",
   types=(bool,))

# -- routing -----------------------------------------------------------------
_k("source_routing", "enforced", "record.sources[0].name → dataset", types=(dict,))
_k("source_routing.by_name", "data_map",
   "upstream source name → source key, or null for 'route elsewhere'. An "
   "unroutable name FAILS the run (law 5)", types=(dict,))
_k("source_routing.default", "enforced",
   "the dataset for records carrying sources: []. Declared in 21 specs and "
   "read by nothing until 2026-08-08 — and its absence was not neutral: a "
   "record with no sources routed to None, which FAILS the run", types=(str,))
_k("source_routing.route_on", "rationale",
   "documents WHICH field routing reads; route() hardcodes sources[0].name",
   types=(str,))
_k("provenance_only", "enforced",
   "source names that appear at index ≥1 and must never pick a dataset",
   types=(list,))

# -- datasets ----------------------------------------------------------------
_k("datasets", "enforced", "every (category, source) pair, pre-declared",
   types=(list,))
_k("datasets[].key", "enforced", "the dataset row's key", types=(str,))
_k("datasets[].source", "enforced", "source.key it joins", types=(str,))
_k("datasets[].records_measured", "rationale", "per-dataset audit count",
   types=(int,))
_k("datasets[].overrides", "enforced", "per-dataset narrowing", types=(dict,))

# -- indicator / value / event -----------------------------------------------
_k("indicator", "implemented", "how observation.indicator is built", types=(dict,))
_k("indicator.template", "implemented",
   "fields in {braces}; a brace resolving to null drops its segment; "
   "interpolated values are slugged", types=(str,))
_k("indicator.overrides", "data_map",
   "per-event_type indicator behaviour inside one dataset", types=(dict,))
_k("indicators", "rationale",
   "the exhaustive list of indicators this spec produces — a contract a "
   "reviewer can check against the run, not a rule the loader reads",
   types=(list,))
_k("value", "implemented", "how the numeric/text value is taken", types=(dict,))
_k("value.num_from", "implemented", "dotted path; first non-null wins",
   types=(str, list, type(None)))
_k("value.num_from_overrides", "data_map", "per-event_type value path",
   types=(dict,))
_k("value.text_from", "implemented", "dotted path or null",
   types=(str, list, type(None)))
_k("value.unit_from", "implemented", "dotted path, or {literal: '...'}",
   types=(str, dict, type(None)))
_k("value.unit_from.literal", "implemented", "a fixed unit string", types=(str,))
_k("event_type", "implemented", "event shape only", types=(dict,))
_k("event_type.template", "implemented", "as indicator.template", types=(str,))
_k("metrics_from", "implemented",
   "which metrics.* fields become event.metrics", types=(list,))
_k("metrics_rules", "implemented",
   "event-shape metric renames (cumulative keys get a _cumulative suffix)",
   types=(list,))
_k("metrics_rules[].if", "implemented", "condition, prose-shaped", types=(str,))
_k("metrics_rules[].then", "implemented", "action, prose-shaped", types=(str,))

# -- time --------------------------------------------------------------------
_k("occurred_at", "implemented", "law 1 and law 2 live here", types=(dict,))
_k("occurred_at.from", "implemented",
   "source field for the event date; a list means 'first present wins' "
   "(connectivity: outage_start for IODA, date for OONI)",
   types=(str, list))
_k("occurred_at.precision", "implemented", "the default precision",
   types=(str,), values=PRECISIONS)
_k("occurred_at.rules", "implemented", "ordered; first match wins", types=(list,))
_k("occurred_at.rules[].if", "rationale",
   "the condition in prose, for the reviewer. `when:` is the executable form",
   types=(str,))
_k("occurred_at.rules[].then", "implemented",
   "the action. A STRING here is prose and drives nothing — it is how the "
   "hand-written transformers' rules are documented. A MAPPING is executed by "
   "the engine", types=(str, dict))
_k("occurred_at.rules[].when", "enforced",
   "the executable condition: {field, op, value} over a closed grammar of "
   "nine operators, or {all: [...]} / {any: [...]}. Never eval",
   types=(dict,), check=_condition, cls_children="value")
_k("occurred_at.rules[].rationale", "rationale",
   "why this rule exists, or why a rule that looks needed is absent",
   types=(str,))
_k("occurred_at.rules[].then.reported_at_only", "enforced",
   "LAW 1: the date is v1's fetch stamp, so occurred_at becomes reported_at "
   "and precision becomes unknown", types=(bool,))
_k("occurred_at.rules[].then.truncate_to", "enforced",
   "LAW 2: year | month | day", types=(str,), values=("year", "month", "day"))
_k("occurred_at.rules[].then.precision", "enforced", "", types=(str,),
   values=PRECISIONS)
_k("occurred_at.rules[].then.precision_from", "enforced",
   "take precision from a field the source provides", types=(str,))
_k("occurred_at.rules[].then.verbatim_from", "enforced",
   "take the date from a different field", types=(str,))
_k("occurred_at.rules[].then.literal", "enforced",
   "a fixed date — a series start, where the source gives none", types=(str,))
_k("occurred_at.rules[].then.attrs", "data_map",
   "attrs this rule adds (coverage_start / coverage_end on a series-start "
   "row, so the row states its own span)", types=(dict,))
_k("occurred_at.keep_reported_at", "enforced",
   "carry the fetch stamp into observation.reported_at even when law 1 does "
   "not fire", types=(bool,))
_k("drop[].when", "enforced",
   "the executable condition, same grammar as occurred_at rules",
   types=(dict,), check=_condition, cls_children="value")

# -- place -------------------------------------------------------------------
_k("place", "enforced", "the resolution ladder and its floors", types=(dict,))
_k("place.strategy", "enforced", "the first rung", types=(str,),
   values=PLACE_RUNGS)
_k("place.fallback", "enforced",
   "the rungs tried in order when the strategy misses. Implemented 2026-08-08 "
   "— until then education and infrastructure declared [latlon, region] and "
   "the loader went straight to region, so 5,881 rows sat at region grade "
   "with a point in hand", check=_fallback)
_k("place.fixed", "implemented", "every row is this one place", types=(str,))
_k("place.name_from", "implemented", "field holding the place name",
   types=(str,))
_k("place.crosswalk", "data_map",
   "source name → {kind, name_en} in the v2 gazetteer", types=(dict,),
   child_check=_crosswalk_value)
_k("place.forbid", "enforced",
   "fields that LOOK like geo and are fabricated (synthetic centroids, "
   "projected metres). Listing one here is a hard safety rule", types=(list,))
_k("place.latlon_exclude", "enforced",
   "event types whose lat/lon must never be read as degrees", types=(list,))
_k("place.min_decided_pct", "enforced",
   "fraction of retained records reaching an error-free place decision — a "
   "deliberate NULL counts. Default 1.0", types=(int, float), check=_pct)
_k("place.min_located_pct", "enforced",
   "fraction landing at point/locality/governorate grade. Optional, and only "
   "meaningful where the source carries real geo", types=(int, float),
   check=_pct)

# -- identity ----------------------------------------------------------------
_k("identity", "enforced", "what makes a row THIS row, across v1 re-hashings",
   types=(dict,))
_k("identity.fields", "enforced", "rendered by identity_key_for, in order",
   types=(list,), check=_identity_fields)
_k("identity.attrs", "enforced", "attrs keys appended to the key", types=(list,))
_k("identity.allow_collisions", "enforced",
   "a MEASURED count of rows sharing a key; the injectivity invariant fails "
   "the run above it", types=(int,))
_k("identity.collision_kind", "enforced",
   "duplicate_fact (keep the key, supersede the copy) vs indistinguishable "
   "(no stored key possible). Getting this backwards doubled IDMC",
   types=(str,), values=COLLISION_KINDS)

# -- fan out / shape overrides -----------------------------------------------
_k("fan_out", "implemented",
   "one record becomes several observations when the values live in "
   "per-period fields", types=(list,))
_k("fan_out[].when", "implemented", "condition", types=(str,))
_k("fan_out[].indicator", "implemented", "the emitted indicator", types=(str,))
_k("fan_out[].value", "implemented", "where this fan-out's value comes from",
   types=(dict,))
_k("fan_out[].value.num_from", "implemented", "dotted path", types=(str,))
_k("fan_out[].value.text_from", "implemented", "dotted path", types=(str,))
_k("fan_out[].value.unit", "implemented", "literal unit", types=(str,))
_k("fan_out[].occurred_at", "implemented", "per-fan-out date", types=(dict,))
_k("fan_out[].occurred_at.from", "implemented", "dotted path", types=(str,))
_k("fan_out[].occurred_at.literal", "implemented", "a fixed date",
   types=(str, int))
_k("fan_out[].occurred_at.precision", "implemented", "", types=(str,),
   values=PRECISIONS)
_k("fan_out[].attrs", "data_map", "attrs this fan-out adds", types=(dict,))
_k("shape_overrides", "implemented",
   "route a subset to the other table (conflict's cumulative series → "
   "observation; historical's timeline → event)", types=(list,))
_k("shape_overrides[].if", "implemented", "condition", types=(str,))
_k("shape_overrides[].shape", "implemented", "", types=(str,),
   values=("observation", "event"))
_k("shape_overrides[].indicator", "implemented",
   "how the re-shaped subset builds its indicator", types=(dict,))
_k("shape_overrides[].indicator.fan_out", "implemented",
   "conflict's cumulative series: one daily record becomes several "
   "observations", types=(list,))
_k("shape_overrides[].indicator.fan_out[].when", "implemented", "condition",
   types=(str,))
_k("shape_overrides[].indicator.fan_out[].indicator", "implemented", "",
   types=(str,))
_k("shape_overrides[].indicator.fan_out[].value", "implemented", "",
   types=(dict,))
_k("shape_overrides[].indicator.fan_out[].value.num_from", "implemented", "",
   types=(str,))
_k("shape_overrides[].indicator.fan_out[].value.unit", "implemented", "",
   types=(str,))

# -- misc --------------------------------------------------------------------
_k("stable_id", "implemented", "field for observation.v1_stable_id (044)",
   types=(str,))
_k("attrs_passthrough", "enforced",
   "dotted paths kept in attrs. `description` is never one (law 6)",
   types=(list,))
_k("drop", "enforced", "declared, measured, counted-by-reason removals",
   types=(list,))
_k("drop[].reason", "enforced",
   "must match the reason the transformer emits; an undeclared reason FAILS "
   "the run", types=(str,))
_k("drop[].if", "rationale", "the condition, for the reviewer", types=(str,))
_k("drop[].measured", "enforced",
   "the count at spec time. A drop without one is invalid (README law)",
   types=(int, str))
_k("registry", "enforced",
   "how this category's indicators map onto the concept/unit registry "
   "(059). Ordered rules, first match wins — 1,011 WHO GHO codes are "
   "classified by three of them, which is the only way 1,408 indicators get "
   "meaning without being typed by hand", types=(dict,))
_k("registry.max_unclassified", "enforced",
   "how many of this category's indicators may go unclassified. Above it, "
   "ops/load_registry.py refuses — law 4 applied to meaning", types=(int,))
_k("registry.rules", "enforced", "ordered; first match wins", types=(list,))
_k("registry.rules[].when", "enforced",
   "{prefix|regex|equals|not_prefix|unit}. `unit` matches the RAW unit "
   "string: health's 1,011 GHO codes cannot have their measure_kind read "
   "off their names, but their units say it exactly", types=(dict,),
   cls_children="value")
_k("registry.rules[].notes", "rationale", "", types=(str,))
_k("registry.rules[].concept", "enforced", "a key in the concept table",
   types=(str,))
_k("registry.rules[].measure_kind", "enforced",
   "stock | flow | cumulative | rate | index | ratio | status. The "
   "distinction that makes comparison possible", types=(str,),
   values=("stock", "flow", "cumulative", "rate", "index", "ratio",
           "status", "unclassified"))
_k("registry.rules[].polarity", "enforced",
   "+1 a rise is better, -1 a rise is worse, null neither", types=(int,),
   values=(-1, 1))
_k("registry.rules[].grain", "enforced", "the period one row covers",
   types=(str,))
_k("registry.rules[].place_grain", "enforced", "", types=(str,))
_k("registry.rules[].canonical_unit", "enforced", "a key in unit_def",
   types=(str,))
_k("registry.rules[].name_en", "rationale", "", types=(str,))
_k("registry.rules[].name_ar", "rationale", "", types=(str,))
_k("registry.rules[].note", "rationale", "why this rule", types=(str,))
_k("expect", "enforced", "the tripwires", types=(dict,))
_k("expect.min_records", "enforced",
   "a run seeing fewer FAILS; it does not succeed with less", types=(int,))
_k("expect.max_observations", "enforced",
   "the opposite tripwire: an identity too FINE reads a revision as a new "
   "fact. ~1.15 × measured", types=(int,))

# Per-dataset overrides mirror the top-level keys. Building them from the
# same table means a key can never be legal at one level and unknown at the
# other — which is how `datasets[].overrides.place.min_resolved_pct` survived
# in three specs after the top-level key was questioned.
_OVERRIDABLE = ("indicator", "value", "occurred_at", "place", "identity",
                "attrs_passthrough", "expect", "fan_out", "stable_id",
                "metrics_from", "event_type")
for _p, _key in list(R.items()):
    _head = _p.split(".")[0].split("[")[0]
    if _head in _OVERRIDABLE:
        R[f"datasets[].overrides.{_p}"] = _key


# ── validation ───────────────────────────────────────────────────────────────

@dataclass
class Problem:
    path: str
    message: str
    fatal: bool = True

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _suggest(path: str) -> str:
    near = difflib.get_close_matches(path, R, n=1, cutoff=0.75)
    return f" (did you mean {near[0]!r}?)" if near else ""


def _walk(node: Any, path: str, out: list[Problem]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            key = R.get(p)
            if key is None:
                out.append(Problem(p, f"unknown key{_suggest(p)} — every key a "
                                      "spec may contain is registered in "
                                      "ingest/spec.py, so a typo cannot read "
                                      "as silence"))
                continue
            _check_value(key, p, v, out)
            if key.cls_children == "value":
                continue
            if key.cls == "data_map":
                if isinstance(v, dict) and key.child_check:
                    for ck, cv in v.items():
                        err = key.child_check(cv)
                        if err:
                            out.append(Problem(f"{p}[{ck!r}]", err))
                continue                      # child keys are DATA, not schema
            _walk(v, p, out)
    elif isinstance(node, list):
        for item in node:
            _walk(item, path + "[]", out)


def _check_value(key: Key, path: str, v: Any, out: list[Problem]) -> None:
    if key.cls == "unimplemented":
        out.append(Problem(path, f"declared but NOT IMPLEMENTED — {key.note}. "
                                 "A spec may not promise what no code "
                                 "delivers: implement it or delete the key"))
        return
    if v is None:
        return                                # an explicit null is a decision
    if key.types and not isinstance(v, key.types):
        want = "/".join(t.__name__ for t in key.types)
        out.append(Problem(path, f"must be {want}, got "
                                 f"{type(v).__name__} ({v!r})"))
        return
    if key.values and v not in key.values:
        out.append(Problem(path, f"must be one of {list(key.values)}, "
                                 f"got {v!r}"))
    if key.check:
        err = key.check(v)
        if err:
            out.append(Problem(path, err))


def _cross_checks(spec: dict, category: str, out: list[Problem]) -> None:
    """Rules that span keys. These are the ones a reader of one line cannot
    see — and every one of them is here because it failed in production."""
    migrating = spec.get("migrate") is not False

    if spec.get("migrate") is False and not spec.get("skip_reason"):
        out.append(Problem("skip_reason",
                           "migrate: false without a reason is an unexplained "
                           "hole in the databank"))

    ds_keys = [d.get("key") for d in spec.get("datasets") or []]
    dupes = {k for k in ds_keys if ds_keys.count(k) > 1}
    if dupes:
        out.append(Problem("datasets[].key",
                           f"duplicate dataset key(s) {sorted(dupes)} — "
                           "identity is rendered per dataset key, so two "
                           "datasets sharing one would share an identity space"))

    # Law 5: routing is exhaustive. A source named in by_name with no dataset
    # is a record the run will fail on, discovered only when that name appears.
    sources = {d.get("source") for d in spec.get("datasets") or []}
    routed = {v for v in (spec.get("source_routing") or {})
              .get("by_name", {}).values() if v}
    # provenance_only names are DELIBERATELY dataset-less: conflict lists
    # Zochrot, Palestine Remembered, Atlas of Palestine and Wikidata so their
    # licences are asserted against the routed dataset without ever picking
    # one. Naming them in by_name is how the spec says "known, not primary".
    routed -= set(spec.get("provenance_only") or [])
    orphan = routed - sources
    if orphan:
        out.append(Problem("source_routing.by_name",
                           f"routes to {sorted(orphan)}, which no dataset "
                           "declares — a record with that name fails the run"))

    # Law 6: description is not data.
    for lst_path in ("attrs_passthrough",):
        for item in spec.get(lst_path) or []:
            if str(item).split(".")[-1] == "description":
                out.append(Problem(f"{lst_path}",
                                   "`description` is not data (law 6) — it "
                                   "stays in bronze and raw_ref points there"))

    # A floor above the measurement is a run that can only ever fail.
    rm, exp = spec.get("records_measured"), (spec.get("expect") or {})
    if isinstance(rm, int) and isinstance(exp.get("min_records"), int) \
            and exp["min_records"] > rm:
        out.append(Problem("expect.min_records",
                           f"{exp['min_records']} exceeds records_measured "
                           f"{rm} — this run can only fail"))
    # NOT checked: max_observations against min_records. They count different
    # things and comparing them is a plausible-sounding invariant that is
    # simply false — conflict reads 10,611 records and emits 2,074
    # observations, because 8,495 of them become events.

    # Every drop is measured (README law). Defensive drops declare 0.
    for i, d in enumerate(spec.get("drop") or []):
        if "measured" not in d:
            out.append(Problem(f"drop[{i}].reason={d.get('reason')!r}",
                               "no `measured:` — a drop the reviewer cannot "
                               "size is an invitation to lose data quietly. "
                               "Declare 0 for a defensive drop"))

    if not migrating:
        return

    # The Stage 2 laws, restated here so a spec fails validation rather than
    # failing halfway through a run.
    idents = [spec.get("identity")] + [
        (d.get("overrides") or {}).get("identity")
        for d in spec.get("datasets") or []]
    if not any(idents):
        out.append(Problem("identity",
                           "a migrating spec must declare what makes a row "
                           "THIS row, or v1 re-hashing its ids re-inserts the "
                           "whole corpus"))
    for ident in [i for i in idents if i]:
        # Either half may be empty; both may not. An identity naming nothing
        # maps every row to the dataset key alone — the 2026-08-07 freeze,
        # where 5,840 infrastructure rows collapsed onto 4 keys.
        if not ident.get("fields") and not ident.get("attrs"):
            out.append(Problem("identity",
                               "declares neither fields nor attrs — an empty "
                               "identity maps every row to one key, which "
                               "does not de-duplicate, it DELETES"))
        if ident.get("collision_kind") and not ident.get("allow_collisions"):
            out.append(Problem("identity.collision_kind",
                               "a collision kind without a measured "
                               "allow_collisions declares a problem without "
                               "sizing it"))
    if not exp.get("max_observations"):
        out.append(Problem("expect.max_observations",
                           "the tripwire that catches an identity too FINE. "
                           "The injectivity invariant structurally cannot see "
                           "that failure mode"))


def validate(spec: dict, category: str) -> list[Problem]:
    out: list[Problem] = []
    _walk(spec, "", out)
    _cross_checks(spec, category, out)
    return out


def validate_or_raise(spec: dict, category: str) -> None:
    problems = validate(spec, category)
    if problems:
        raise SpecInvalid(
            f"{category}: spec is not valid Format v2 — "
            f"{len(problems)} problem(s):\n  " +
            "\n  ".join(str(p) for p in problems))


# ── CLI ──────────────────────────────────────────────────────────────────────

def _explain() -> None:
    by_class: dict[str, list[str]] = {}
    for p, k in sorted(R.items()):
        if p.startswith("datasets[].overrides."):
            continue                          # mirrors, printed once
        by_class.setdefault(k.cls, []).append(p)
    for cls in ("enforced", "implemented", "data_map", "rationale",
                "unimplemented"):
        paths = by_class.get(cls, [])
        print(f"\n=== {cls}  ({len(paths)})")
        for p in paths:
            note = (R[p].note.splitlines() or [""])[0]
            print(f"  {p:<42} {note[:70]}")


def main(argv: list[str]) -> int:
    import yaml
    if "--explain" in argv:
        _explain()
        return 0
    bad = 0
    for f in sorted(SPECS.glob("*.yaml")):
        problems = validate(yaml.safe_load(f.read_text()), f.stem)
        fatal = [p for p in problems if p.fatal]
        mark = "ok  " if not fatal else "FAIL"
        print(f"{mark} {f.stem:<24} {len(fatal)} problem(s)")
        for p in fatal:
            print(f"       {p}")
        bad += bool(fatal)
    print(f"\n{bad} spec(s) invalid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
