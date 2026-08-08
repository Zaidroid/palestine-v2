"""The declarative engine — the spec stops describing the code and drives it.

TRAP-4's promise is that the spec is the reviewable artifact. A validator
(ingest/spec.py) makes that promise honest about which keys are REAL. This
file is the other half: it makes the keys DO the work, so reviewing
`indicator.template` reviews what indicators get built rather than a sentence
about what somebody meant to build.

Three rules govern every construct here:

  1. NO `eval`, ever. Conditions are a closed grammar of eight operators over
     named fields. A spec is a document a reviewer reads and a machine
     executes; the moment it can express arbitrary Python it is neither.
  2. Prose lives under `rationale:`, never in an executable slot. historical
     carried `precision: "see rules below"` in an enum field for three days,
     and conflict carried `then: "NO-OP — must not fire"` — a rule whose
     content is that it is not a rule.
  3. Which mechanism drives a category is DECLARED, in `transform:`. Half a
     migration is worse than none if nobody can tell which half they are
     reading. `engine` or `python:<name>`; the registry refuses anything else
     and the run report says which one ran.

Every migration is gated on ops/spec_equivalence.py: the engine must emit
tuples identical to the transformer it replaces, field by field, over every
record, before the transformer is deleted.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

# ── field access ─────────────────────────────────────────────────────────────


class EngineRefused(RuntimeError):
    """The spec asked for something the grammar cannot express. Raised at
    build time, not row time — a category either compiles or it does not."""


def get_path(rec: dict, path: str) -> Any:
    """Dotted path into a record. A missing segment is None, never a KeyError:
    an absent field is data (the record does not say), and the caller decides
    what that means."""
    cur: Any = rec
    for part in str(path).split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


# ── conditions: a closed grammar ─────────────────────────────────────────────

OPS = ("always", "eq", "ne", "in", "endswith", "startswith", "present",
       "absent", "equals_fetch_day")


def _fetch_at(rec: dict) -> str | None:
    """The full stamp v1 wrote the record at. This is what reaches
    observation.reported_at — the sub-second part is provenance, and
    truncating it to a day (as this function did for an hour on 2026-08-08,
    until spec_equivalence caught it on culture's 329 rows) throws away real
    precision about OUR pipeline while pretending to be about the source's."""
    src = (rec.get("sources") or [{}])
    return src[0].get("fetched_at") if isinstance(src[0], dict) else None


def _fetch_day(rec: dict) -> str | None:
    """The DAY v1 wrote the record. Law 1 turns on this: a `date` equal to it
    is an ingest stamp wearing an event date's clothes. Day-grained on
    purpose — the comparison is 'same day', not 'same instant'."""
    fetched = _fetch_at(rec)
    return str(fetched)[:10] if fetched else None


def check(cond: dict, rec: dict) -> bool:
    if not isinstance(cond, dict):
        raise EngineRefused(f"a condition must be a mapping, got {cond!r}")
    if "all" in cond:
        return all(check(c, rec) for c in cond["all"])
    if "any" in cond:
        return any(check(c, rec) for c in cond["any"])
    op = cond.get("op", "always")
    if op not in OPS:
        raise EngineRefused(
            f"unknown operator {op!r} — the grammar is {list(OPS)}, and it is "
            "closed on purpose: a spec that can express arbitrary code is not "
            "a document a reviewer can check")
    if op == "always":
        return True
    v = get_path(rec, cond["field"])
    if op == "present":
        return v not in (None, "", [], {})
    if op == "absent":
        return v in (None, "", [], {})
    if op == "equals_fetch_day":
        fd = _fetch_day(rec)
        return bool(fd) and str(v)[:10] == fd
    if v is None:
        return False
    if op == "eq":
        return str(v) == str(cond["value"])
    if op == "ne":
        return str(v) != str(cond["value"])
    if op == "in":
        return str(v) in [str(x) for x in cond["value"]]
    if op == "endswith":
        return str(v).endswith(str(cond["value"]))
    if op == "startswith":
        return str(v).startswith(str(cond["value"]))
    raise EngineRefused(f"operator {op!r} is in OPS but has no implementation")


# ── dates: laws 1 and 2, executed ────────────────────────────────────────────

TRUNCATE = ("year", "month", "day")
PRECISIONS = ("exact", "hour", "day", "month", "year", "unknown")


def _truncate(value: str, grain: str) -> str:
    d = str(value)[:10]
    if grain == "year":
        return f"{d[:4]}-01-01"
    if grain == "month":
        return f"{d[:7]}-01"
    return d


def resolve_date(spec_oa: dict, rec: dict, attrs: dict) -> tuple[str, str, str | None]:
    """Returns (occurred_at, precision, reported_at).

    `from` may be a list — 'first present wins' — because connectivity carries
    two sources with two date fields in one dataset.
    """
    src = spec_oa.get("from")
    fields = src if isinstance(src, list) else [src] if src else []
    raw = next((get_path(rec, f) for f in fields
                if get_path(rec, f) is not None), None)
    precision = spec_oa.get("precision", "day")
    reported = _fetch_at(rec)
    occurred = str(raw)[:10] if raw is not None else None

    for rule in spec_oa.get("rules") or []:
        # `rationale:` entries document a rule that must NOT fire (conflict's
        # year-bucket rule, which law 2 would otherwise apply to a category
        # where every -12-31 is a real December day). Documentation of an
        # absence is not an instruction.
        if "then" not in rule:
            continue
        if not check(rule.get("when") or {"op": "always"}, rec):
            continue
        then = rule["then"]
        if not isinstance(then, dict):
            raise EngineRefused(
                f"`then` must be a mapping, got prose: {then!r}. Prose belongs "
                "under `rationale:` — a sentence in an executable slot is how "
                "'NO-OP: must not fire' came to look like a rule")
        if then.get("reported_at_only"):
            # LAW 1. The date is v1's fetch stamp, not an event date. T7
            # already excludes unknown precision from freshness, so a
            # category cannot fake being fresh with its own ingest time.
            # occurred_at takes the DAY (the fact is 'sometime that day');
            # reported_at keeps the full stamp, because when WE saw it is
            # known to the second and that is our own provenance to keep.
            return (_fetch_day(rec) or occurred or ""), "unknown", reported
        if "verbatim_from" in then:
            occurred = str(get_path(rec, then["verbatim_from"]) or occurred)[:19]
        if "literal" in then:
            occurred = str(then["literal"])
        if "truncate_to" in then:
            grain = then["truncate_to"]
            if grain not in TRUNCATE:
                raise EngineRefused(f"truncate_to {grain!r} not in {TRUNCATE}")
            if occurred:
                occurred = _truncate(occurred, grain)      # LAW 2
        if "precision_from" in then:
            precision = get_path(rec, then["precision_from"]) or precision
        if "precision" in then:
            precision = then["precision"]
        for k, v in (then.get("attrs") or {}).items():
            attrs[k] = v
        break                          # ordered, first match wins

    if precision not in PRECISIONS:
        raise EngineRefused(f"precision {precision!r} not in {PRECISIONS}")
    return (occurred or reported or ""), precision, reported


# ── templates ────────────────────────────────────────────────────────────────

def split_segments(template: str) -> list[str]:
    """Split on the dots BETWEEN segments, never on the dots inside a brace.

    `funding.{funding.status}` is two segments, not three. Splitting naively
    produced the literal indicator 'funding.{funding.status}' on all 9,990
    funding rows — caught by ops/spec_equivalence.py before it reached a
    single database write, which is the entire argument for that harness.
    """
    segs, buf, depth = [], [], 0
    for ch in str(template):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "." and depth == 0:
            segs.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    segs.append("".join(buf))
    return segs


def render(template: str, rec: dict, slug) -> str:
    """`{braces}` are dotted paths. A brace resolving to null DROPS ITS
    SEGMENT rather than rendering 'None' — the global loader convention, and
    the reason `casualties.{dimension}.{label}` becomes
    `casualties.annual_total` when there is no label. Values are slugged."""
    out = []
    for seg in split_segments(template):
        if "{" not in seg:
            out.append(seg)
            continue
        rendered, dropped = [], False
        i = 0
        while i < len(seg):
            if seg[i] == "{":
                j = seg.index("}", i)
                v = get_path(rec, seg[i + 1:j])
                if v is None or v == "":
                    dropped = True          # a null drops the whole segment
                    break
                rendered.append(slug(v))
                i = j + 1
            else:
                j = seg.find("{", i)
                j = len(seg) if j == -1 else j
                rendered.append(seg[i:j])
                i = j
        if not dropped:
            out.append("".join(rendered))
    return ".".join(out)


def first_non_null(rec: dict, paths) -> Any:
    if paths is None:
        return None
    for p in (paths if isinstance(paths, list) else [paths]):
        v = get_path(rec, p)
        if v is not None:
            return v
    return None


def resolve_unit(spec_value: dict, rec: dict) -> Any:
    uf = spec_value.get("unit_from")
    if isinstance(uf, dict):
        return uf.get("literal")
    return get_path(rec, uf) if uf else None
