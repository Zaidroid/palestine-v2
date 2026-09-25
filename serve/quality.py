"""What the incident classifier is measured to get right — read, never asserted.

`ops/incident-precision.json` is the latest hand-scored round (written by
learn/incident_precision.py); the number in it belongs to the classifier
version it names, which is not always the one serving. Every incident answer
carries the measured precision beside its counts, deaths first, because a
count of "3 deaths" from a reader that is right 60 % of the time is not the
same fact as one from a reader that is right 93 % of the time (plan P0-C.3,
round 8 measured 2026-09-24: death 0.60, arrest 0.93).
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "ops" / "incident-precision.json"
GATE_OVERALL = 0.80
GATE_TYPE = 0.70


def _serving_version() -> str | None:
    try:
        from ingest.sources.news_incidents import CLASSIFIER_VERSION
        return CLASSIFIER_VERSION
    except Exception:                                           # noqa: BLE001
        return None


@functools.lru_cache(maxsize=4)
def _load(mtime: float) -> dict | None:
    try:
        r = json.loads(FILE.read_text())
    except Exception:                                           # noqa: BLE001
        return None
    o = r.get("overall") or {}
    measured = r.get("classifier_version")
    serving = _serving_version()
    per_type = {k: {"precision": v.get("precision"), "ci95": v.get("ci95"), "n": v.get("n")}
                for k, v in (r.get("per_type") or {}).items()}
    out = {
        "round": r.get("round"),
        "measured_at": r.get("measured_at"),
        "measured_version": measured,
        "serving_version": serving,
        "overall": {"precision": o.get("precision"), "ci95": o.get("ci95"), "n": o.get("n")},
        "gate": {"overall": GATE_OVERALL, "per_type": GATE_TYPE,
                 "state": ("below gate" if (o.get("precision") or 0) < GATE_OVERALL else "passing")},
        "per_type": per_type,
        "basis": f"hand-scored sample, ops/incident-precision.json (round {r.get('round')})",
    }
    if measured and serving and measured != serving:
        out["note"] = (f"measured on classifier {measured}; {serving} is serving and is "
                       f"unmeasured until the next round")
    return out


def incident_precision() -> dict | None:
    try:
        mtime = FILE.stat().st_mtime
    except OSError:
        return None
    return _load(mtime)


def annotate_by_type(by_type: dict) -> dict:
    """Each served type gains what the last round measured for it, or says it
    is unmeasured. Returns a new dict; the input is left alone."""
    q = incident_precision()
    out = {}
    for t, v in (by_type or {}).items():
        row = dict(v) if isinstance(v, dict) else {"n": v}
        m = (q or {}).get("per_type", {}).get(t)
        if m and m.get("precision") is not None:
            row["precision"] = {"value": m["precision"], "ci95": m.get("ci95"),
                                "n": m.get("n"), "round": q["round"]}
        else:
            row["precision"] = {"value": None, "note": "unmeasured"}
        out[t] = row
    return out


def weak_types(by_type: dict, below: float = GATE_OVERALL) -> list[dict]:
    """Served types whose measured precision is under `below`, weakest first,
    deaths first among equals — the ones an answer must say out loud."""
    q = incident_precision()
    if not q:
        return []
    rows = []
    for t in (by_type or {}):
        m = q["per_type"].get(t)
        if m and m.get("precision") is not None and m["precision"] < below:
            rows.append({"type": t, "precision": m["precision"], "n": m.get("n")})
    rows.sort(key=lambda r: (r["precision"], 0 if r["type"] == "death" else 1, r["type"]))
    return rows


def summary(by_type: dict | None = None) -> dict | None:
    q = incident_precision()
    if not q:
        return None
    return {"round": q["round"], "measured_version": q["measured_version"],
            "serving_version": q["serving_version"], "overall": q["overall"],
            "gate": q["gate"], "weak": weak_types(by_type or {}),
            "basis": q["basis"], **({"note": q["note"]} if q.get("note") else {})}
