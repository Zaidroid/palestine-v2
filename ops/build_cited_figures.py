"""Check the hand-entered cited figures and write the loader's input.

db/reference/cited_figures.yaml is the file a person edits: one publisher's
statement per entry, with the document, the URL and the sentence. This step
refuses an entry that could not be stood behind (no publisher, no
verification tag, an id used twice, a value AND a range) and writes
data/reference/cited_figures.json in the record shape the loader's engine
reads (db/mappings/cited_figures.yaml). No network. Deterministic: the same
YAML gives the same bytes, so an unchanged night leaves the file alone.

  .venv/bin/python -m ops.build_cited_figures           # check and write
  .venv/bin/python -m ops.build_cited_figures --check   # check only
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "db" / "reference" / "cited_figures.yaml"
OUT = ROOT / "data" / "reference" / "cited_figures.json"

VERIFICATION = ("read", "via_wikipedia", "secondary")
QUALIFIER = {"about": "about", "at_least": "at least", "more_than": "more than", "up_to": "up to"}
PRECISION = ("day", "month", "year")
REQUIRED = ("id", "topic", "measure", "date", "precision", "unit", "region", "publisher",
            "document", "verification")
SOURCE_NAME = "Cited figures (hand-entered, each with its publisher)"


def _n(v) -> str:
    return f"{int(v):,}" if float(v).is_integer() else f"{v:,}"


def said(f: dict) -> str:
    """The figure as a reader should hear it: its qualifier and its range are
    part of the statement, not decoration."""
    if f.get("statement"):
        return str(f["statement"])
    if "low" in f:
        return f"{_n(f['low'])} to {_n(f['high'])}"
    q = QUALIFIER.get(f.get("qualifier") or "")
    return (q + " " if q else "") + _n(f["value"])


def check(figures: list[dict]) -> list[str]:
    problems, seen = [], set()
    for i, f in enumerate(figures):
        name = f.get("id") or f"entry {i + 1}"
        for k in REQUIRED:
            if f.get(k) in (None, ""):
                problems.append(f"{name}: `{k}` is missing")
        if f.get("id") in seen:
            problems.append(f"{name}: the id is used twice")
        seen.add(f.get("id"))
        if not re.fullmatch(r"[a-z0-9-]+", str(f.get("id") or "")):
            problems.append(f"{name}: an id is lower-case letters, digits and dashes")
        for k in ("topic", "measure"):
            if not re.fullmatch(r"[a-z0-9_]+", str(f.get(k) or "")):
                problems.append(f"{name}: `{k}` is lower-case letters, digits and underscores")
        kinds = sum((("value" in f), ("low" in f or "high" in f), bool(f.get("statement"))))
        if kinds != 1:
            problems.append(f"{name}: give `value`, or `low` and `high`, or a `statement` "
                            "(a dated event), not both and not neither")
        if f.get("statement") and f.get("unit") != "events":
            problems.append(f"{name}: a dated event is counted in `events`")
        if ("low" in f) != ("high" in f) or ("low" in f and f["low"] > f["high"]):
            problems.append(f"{name}: a range needs `low` and `high`, low first")
        if f.get("verification") not in VERIFICATION:
            problems.append(f"{name}: verification must be one of {VERIFICATION}")
        if f.get("precision") not in PRECISION:
            problems.append(f"{name}: precision must be one of {PRECISION}")
        if f.get("qualifier") and f["qualifier"] not in QUALIFIER:
            problems.append(f"{name}: qualifier must be one of {tuple(QUALIFIER)}")
        for k in ("date", "from", "to"):
            if f.get(k) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f[k])):
                problems.append(f"{name}: `{k}` must be YYYY-MM-DD")
        if ("from" in f) != ("to" in f):
            problems.append(f"{name}: a period needs both `from` and `to`")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f.get("read_on") or "")):
            problems.append(f"{name}: `read_on` (the day the source was read) is missing")
    return problems


def records(figures: list[dict]) -> list[dict]:
    out = []
    for f in figures:
        rec = {
            "stable_id": f"cited:{f['id']}",
            "cite_id": f["id"],
            "topic": f["topic"], "measure": f["measure"],
            "date": f["date"], "date_precision": f["precision"],
            # a dated event is one event; what happened is in `said`
            "value": 1 if f.get("statement") else f.get("value"),
            "said": said(f),
            "unit": f["unit"],
            "location": {"region": f["region"]},
            "publisher": f["publisher"], "document": f["document"],
            "verification": f["verification"], "read_on": f["read_on"],
            "sources": [{"name": SOURCE_NAME}],
        }
        for k_in, k_out in (("low", "value_low"), ("high", "value_high"), ("qualifier", "qualifier"),
                            ("url", "url"), ("quote", "quote"), ("caution", "caution"),
                            ("from", "coverage_start"), ("to", "coverage_end")):
            if f.get(k_in) not in (None, ""):
                rec[k_out] = f[k_in]
        out.append(rec)
    return out


def main(argv: list[str]) -> int:
    doc = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    defaults = doc.get("defaults") or {}
    figures = [{**defaults, **f} for f in doc.get("figures") or []]
    problems = check(figures)
    if problems:
        print("cited figures: refused\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    payload = {"metadata": {"source": SOURCE_NAME,
                            "what": "one publisher's statement per row; see db/reference/cited_figures.yaml"},
               "data": records(figures)}
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        print(f"cited figures: {len(figures)} entries, all well-formed")
        return 0
    if OUT.exists() and OUT.read_text(encoding="utf-8") == text:
        print(f"cited figures: {len(figures)} entries, unchanged")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(OUT)
    print(f"cited figures: {len(figures)} entries → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
