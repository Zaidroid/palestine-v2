"""Gold sets as the contract (P2-A.3): every classifier and organ version,
scored against the gold sets that exist, with the verdict beside the number.

    .venv/bin/python -m ops.gold_contract           # the table (reads only)
    .venv/bin/python -m ops.gold_contract --json    # the record

Weekly, ops/measure_review.py runs it and appends the record to
ops/measure-review.ndjson beside everything else it re-measures.

THE CONTRACT
A version may serve only when a gold set says it may. For each subject this
lists every version there is a score for, each score with its basis, the gate,
and one verdict per version:

  servable       a MEASURED score passes the gate
  NOT SERVABLE   a score is below the gate — a measured round, or a projection
                 that already fails (a projection keeps only rows a human
                 judged; if those alone fail, a fresh round will not rescue it)
  unmeasured     nothing decides it yet: a projection that passes, a gold set
                 too small to decide, or no gold set at all

It REPORTS. Nothing here changes what serves: serve/quality.py still states
the last round beside every incident count, and a NOT SERVABLE line is a thing
for a human to act on, not a switch. The plan's "a version below gate cannot
serve" (P2-A.3) is enforced by whoever reads this line, until Zaid decides
the review should hold a door.

THE SUBJECTS
  incidents   gold = the hand-scored precision rounds (ops/incident-scored-
              roundN.ndjson + their samples). Measured rounds come from
              ops/incident-rounds.ndjson (per type from ops/incident-precision-
              roundN.json where one exists); the SERVING version is re-projected
              live over the two latest rounds (ops/rescore_round.project) and
              older versions keep the projections recorded for them. Gate: the
              one serving already states — serve/quality.py, 0.80 overall and
              every type with n >= 5 at 0.70 (G3).
  moh         gold = tests/gold/moh_c.jsonl. The deterministic reader
              (analyst/organ_c.py) is scored on the bulletins' texts: exact on
              the human-read rows, and reproducing its own gold. The model
              candidates of F-11 (ops/organ-c-scores*.json, stored answers,
              rescored here without a call) are AGREEMENT with that reader —
              audit F229: agreement, not a precision. Gate: exact on every
              human-read row with at least 100 of them (F229), and exact on
              every gold row, because these numbers are served verbatim.
  roads       tests/gold/roads.jsonl (P1-A.5, built 2026-09-26 by
              learn/roads_gold.py): v1's whitelist parser — the control organ D
              must beat — scored per reading (checkpoint, direction, value).
              No gold file = "no gold set", never a number.
  organ:<x>   every registered analyst organ with no gold set of its own.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OPS = ROOT / "ops"
MOH_GOLD = ROOT / "tests" / "gold" / "moh_c.jsonl"
ROADS_GOLD = ROOT / "tests" / "gold" / "roads.jsonl"

PROJECT_OVER = 2          # the serving incident version is projected over this many latest rounds
MOH_MIN_HUMAN_ROWS = 100  # audit F229: hand-read a >= 100-row slice before the reader feeds a served number

SERVABLE, NOT_SERVABLE, UNMEASURED = True, False, None


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _word(servable) -> str:
    return {True: "servable", False: "NOT SERVABLE", None: "unmeasured"}[servable]


# ── incidents ────────────────────────────────────────────────────────────────

def incident_gate() -> dict:
    from learn.incident_precision import MIN_N_TO_GATE
    from serve.quality import GATE_OVERALL, GATE_TYPE
    return {"overall": GATE_OVERALL, "per_type": GATE_TYPE, "min_n": MIN_N_TO_GATE,
            "source": "serve/quality.py (G3)"}


def judge_incidents(overall: float | None, per_type: dict[str, tuple[float, int]],
                    gate: dict) -> tuple[bool, str, dict | None]:
    """(passes, why, weakest type) for one score. A type below min_n is not
    judged — n=3 says nothing either way, and failing on it would be as
    dishonest as passing on it."""
    judged = {t: (p, n) for t, (p, n) in per_type.items() if n >= gate["min_n"]}
    weakest = None
    if judged:
        t, (p, n) = min(judged.items(), key=lambda kv: (kv[1][0], kv[0]))
        weakest = {"type": t, "score": p, "n": n}
    failing = sorted(t for t, (p, _) in judged.items() if p < gate["per_type"])
    why = []
    if overall is None or overall < gate["overall"]:
        why.append(f"overall {overall} < {gate['overall']}")
    if failing:
        why.append("below " + str(gate["per_type"]) + ": "
                   + ", ".join(f"{t} {judged[t][0]}" for t in failing))
    return not why, "; ".join(why), weakest


def _round_files(ops: Path) -> dict[str, dict]:
    """measured_at -> {round, per_type} from ops/incident-precision-roundN.json."""
    out: dict[str, dict] = {}
    for f in sorted(ops.glob("incident-precision-round*.json")):
        if "-rescored-" in f.name:
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        at = d.get("measured_at")
        if not at:
            continue
        rnd = str(d.get("round") or f.stem.replace("incident-precision-round", ""))
        out[at] = {"round": rnd, "file": _rel(f),
                   "per_type": {t: (v.get("precision"), v.get("n") or 0)
                                for t, v in (d.get("per_type") or {}).items()
                                if v.get("precision") is not None}}
    return out


def _measured(ops: Path, gate: dict) -> list[tuple[str, dict]]:
    rounds = ops / "incident-rounds.ndjson"
    if not rounds.exists():
        return []
    files = _round_files(ops)
    out = []
    for line in rounds.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        at = rec.get("scored_at")
        o = rec.get("overall") or {}
        f = files.get(at) or {}
        per_type = f.get("per_type") or {}
        passes, why, weakest = judge_incidents(o.get("precision"), per_type, gate)
        score = {"basis": "measured", "round": f.get("round"), "at": at,
                 "gold": f.get("file") or _rel(rounds), "n": o.get("n"),
                 "score": o.get("precision"), "weakest": weakest,
                 "passes_gate": passes, "why": why}
        if not per_type:
            score["note"] = "per-type precision not on record for this round"
        out.append((rec.get("classifier_version") or "unrecorded", score))
    return out


def _projection_score(p: dict, gate: dict, *, live: bool) -> dict:
    per_type = {}
    for t, v in (p.get("per_type") or {}).items():
        tally = v.get("tally") or {}
        n = int(tally.get("kept_right", 0)) + int(tally.get("kept_wrong", 0))
        per_type[t] = (v.get("projected_precision"), n)
    tally = p.get("tally") or {}
    n = int(tally.get("kept_right", 0)) + int(tally.get("kept_wrong", 0))
    passes, why, weakest = judge_incidents(p.get("projected_precision"), per_type, gate)
    return {"basis": "projection" if live else "projection (recorded)",
            "round": str(p.get("round")), "at": None,
            "gold": f"ops/incident-scored-round{p.get('round')}.ndjson",
            "n": n, "score": p.get("projected_precision"), "weakest": weakest,
            "passes_gate": passes, "why": why,
            "type_moved_unjudged": int(tally.get("type_moved", 0))}


def _projectable_rounds(ops: Path) -> list[str]:
    rounds = []
    for f in ops.glob("incident-scored-round*.ndjson"):
        n = f.stem.replace("incident-scored-round", "")
        if n.isdigit() and (ops / f"incident-sample-round{n}.ndjson").exists():
            rounds.append(n)
    return sorted(rounds, key=int, reverse=True)


def decide(scores: list[dict]) -> tuple[bool | None, str]:
    """One verdict per version from all its scores. The latest MEASURED score
    decides when there is one; otherwise a failing projection is already
    NOT SERVABLE, and a passing one is still only a projection."""
    measured = sorted((s for s in scores if s["basis"] == "measured"),
                      key=lambda s: s.get("at") or "")
    if measured:
        s = measured[-1]
        label = f"round {s['round']}" if s.get("round") else f"the round of {(s.get('at') or '')[:10]}"
        if s["passes_gate"]:
            return SERVABLE, f"{label} measured {s['score']} (n={s['n']}) — passes"
        return NOT_SERVABLE, f"{label} measured {s['score']} (n={s['n']}): {s['why']}"
    projections = [s for s in scores if s["basis"].startswith("projection")]
    failing = [s for s in projections if not s["passes_gate"]]
    if failing:
        s = failing[0]
        return NOT_SERVABLE, (f"projection over round {s['round']} is {s['score']} "
                              f"(n={s['n']}): {s['why']}")
    if projections:
        parts = ", ".join(
            f"r{s['round']} {s['score']}"
            + (f" (weakest {s['weakest']['type']} {s['weakest']['score']})" if s.get("weakest") else "")
            for s in projections)
        return UNMEASURED, (f"projections pass ({parts}); only a round drawn from "
                            f"this version can make it servable")
    return UNMEASURED, "no gold score for this version"


def incidents(ops: Path = OPS, serving: str | None = None,
              project: Callable[[str], dict] | None = None) -> list[dict]:
    gate = incident_gate()
    if serving is None:
        from ingest.sources.news_incidents import CLASSIFIER_VERSION as serving
    if project is None:
        from ops.rescore_round import project
    by_version: dict[str, list[dict]] = {}
    for version, score in _measured(ops, gate):
        by_version.setdefault(version, []).append(score)
    # Recorded projections for versions no longer serving; the serving one is
    # re-projected below, with today's code, over today's files.
    for f in sorted(ops.glob("incident-precision-round*-rescored-*.json")):
        try:
            p = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        v = p.get("classifier_version")
        if v and v != serving:
            by_version.setdefault(v, []).append(_projection_score(p, gate, live=False))
    for n in _projectable_rounds(ops)[:PROJECT_OVER]:
        by_version.setdefault(serving, []).append(
            _projection_score(project(n), gate, live=True))
    by_version.setdefault(serving, [])

    def order(v: str):
        return tuple(int(x) if x.isdigit() else -1 for x in v.split(".")) if v else ()

    out = []
    for version in sorted(by_version, key=order, reverse=True):
        scores = by_version[version]
        servable, verdict = decide(scores)
        out.append({"subject": "incidents", "version": version,
                    "serving": version == serving, "servable": servable,
                    "verdict": verdict, "gate": gate, "scores": scores})
    return out


# ── moh ──────────────────────────────────────────────────────────────────────

def moh_gate() -> dict:
    return {"human_exact": 1.0, "min_human_rows": MOH_MIN_HUMAN_ROWS, "all_rows_exact": 1.0,
            "source": "numbers served verbatim; audit F229"}


def load_moh_texts(ids: list[int]) -> dict[int, tuple[str, datetime]] | None:
    """The bulletins' texts from `claim`, read only. None where there is no
    database — the reader is then UNSCORED this week, and says so."""
    try:
        from resolve.db import connect
        with connect(options="-c default_transaction_read_only=on") as conn, conn.cursor() as cur:
            cur.execute("SELECT claim_id, raw_text, reported_at FROM claim "
                        "WHERE claim_id = ANY(%s)", (ids,))
            rows = {int(c): (t, r) for c, t, r in cur.fetchall()}
            conn.rollback()
        return rows
    except Exception:                                           # noqa: BLE001
        return None


def _moh_reader(gold: list[dict], texts: dict | None, gate: dict) -> dict:
    from analyst import organ_c
    entry = {"subject": "moh", "version": organ_c.VERSION, "what": "deterministic reader",
             "serving": False, "role": "control (analyst organ C, ops/gaza_crosscheck.py)",
             "gate": gate, "scores": []}
    if texts is None:
        entry.update(servable=UNMEASURED,
                     verdict="unscored this run: the bulletin texts live in the database")
        return entry
    same = compared = h_exact = h_n = 0
    drifted: list[int] = []
    for g in gold:
        got = texts.get(g["claim_id"])
        if got is None:
            continue
        reading = organ_c.read(got[0] or "", got[1])
        compared += 1
        ok = reading == g["reader"]
        same += ok
        if not ok:
            drifted.append(g["claim_id"])
        if g.get("label_method") == "read":
            h_n += 1
            h_exact += ok
    entry["scores"] = [
        {"basis": "human-read rows", "gold": _rel(MOH_GOLD), "n": h_n, "exact": h_exact,
         "score": round(h_exact / h_n, 3) if h_n else None},
        {"basis": "reproduces its gold", "gold": _rel(MOH_GOLD), "n": compared, "exact": same,
         "score": round(same / compared, 3) if compared else None,
         **({"drifted": drifted[:20]} if drifted else {})},
    ]
    missing = len(gold) - compared
    if compared == 0:
        entry.update(servable=UNMEASURED, verdict="no gold bulletin text found in this database")
    elif same < compared:
        entry.update(servable=NOT_SERVABLE,
                     verdict=(f"the reader no longer reproduces {compared - same} of its "
                              f"{compared} gold rows — the gold does not vouch for this "
                              f"version until they are re-verified"))
    elif h_exact < h_n:
        entry.update(servable=NOT_SERVABLE,
                     verdict=f"{h_n - h_exact} of {h_n} human-read rows wrong")
    elif h_n < gate["min_human_rows"]:
        entry.update(servable=UNMEASURED,
                     verdict=(f"exact on {h_exact}/{h_n} human-read rows and {same}/{compared} "
                              f"gold rows, but human-read on {h_n} of the "
                              f"{gate['min_human_rows']} rows audit F229 requires"))
    else:
        entry.update(servable=SERVABLE,
                     verdict=f"exact on {h_exact}/{h_n} human-read rows and every gold row")
    if missing:
        entry["verdict"] += f" ({missing} gold rows had no text here)"
    return entry


def _moh_models(gold: list[dict], gate: dict, ops: Path) -> list[dict]:
    from analyst.score_organ_c import score_row
    truth = {g["claim_id"]: (g.get("settled") or g["reader"]) for g in gold}
    human = {g["claim_id"] for g in gold if g.get("label_method") == "read"}
    out = []
    for f in sorted(ops.glob("organ-c-scores*.json")):
        if f.stem.endswith("-rescored"):
            continue            # the same stored answers, scored earlier: rescored here instead
        try:
            state = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for role, results in (state.get("rows") or {}).items():
            n = exact = h_n = h_exact = 0
            for r in results:
                cid = r.get("claim_id")
                if not r.get("answer") or cid not in truth:
                    continue
                ok = score_row(truth[cid], r["answer"])["row"] == "correct"
                n += 1
                exact += ok
                if cid in human:
                    h_n += 1
                    h_exact += ok
            status = (state.get("status") or {}).get(role)
            entry = {"subject": "moh", "version": role, "what": "model candidate (F-11)",
                     "run": f"{f.stem} {str(state.get('started_at') or '')[:10]}".strip(),
                     "run_status": status, "serving": False, "gate": gate,
                     "scores": [
                         {"basis": "agreement with the reader (F229: not a precision)",
                          "gold": _rel(MOH_GOLD), "n": n, "exact": exact,
                          "score": round(exact / n, 3) if n else None},
                         {"basis": "human-read rows", "gold": _rel(MOH_GOLD), "n": h_n,
                          "exact": h_exact, "score": round(h_exact / h_n, 3) if h_n else None}]}
            if n == 0:
                entry.update(servable=UNMEASURED, verdict="no stored answer to score")
            elif exact < n:
                entry.update(servable=NOT_SERVABLE,
                             verdict=(f"agrees with the reader on {exact} of {n} gold rows "
                                      f"({h_exact}/{h_n} human-read); a number served "
                                      f"verbatim must be exact on every row"))
            elif h_n < gate["min_human_rows"]:
                entry.update(servable=UNMEASURED,
                             verdict=(f"agrees on every scored row ({n}), human-read on "
                                      f"{h_n} of {gate['min_human_rows']}"))
            else:
                entry.update(servable=SERVABLE, verdict=f"exact on all {n} gold rows")
            out.append(entry)
    return out


def moh(gold_path: Path = MOH_GOLD, texts: dict | None = None, ops: Path = OPS,
        load_texts: Callable[[list[int]], dict | None] = load_moh_texts) -> list[dict]:
    gate = moh_gate()
    if not gold_path.exists():
        return [{"subject": "moh", "version": None, "serving": False, "servable": UNMEASURED,
                 "verdict": "no gold set", "gold": _rel(gold_path), "scores": []}]
    gold = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if texts is None:
        texts = load_texts([g["claim_id"] for g in gold])
    return [_moh_reader(gold, texts, gate), *_moh_models(gold, gate, ops)]


# ── roads, and every organ with no gold ──────────────────────────────────────

# The hook. A scorer takes the gold rows and returns a list of entries like the
# ones above; until one is written, a gold file that exists is still reported
# as unmeasured, and a missing one as "no gold set" — never as a number.
SCORERS: dict[str, Callable[[list[dict]], list[dict]] | None] = {"roads": None}


def _roads_scorer(rows: list[dict]) -> list[dict]:
    # P1-A.5 (2026-09-26): v1's whitelist parser, the control organ D must
    # beat, scored on the seat-read messages (learn/roads_gold.py).
    from learn.roads_gold import contract_scorer
    return contract_scorer(rows)


SCORERS["roads"] = _roads_scorer


def roads(path: Path = ROADS_GOLD) -> list[dict]:
    base = {"subject": "roads", "version": None, "serving": None, "gold": _rel(path),
            "servable": UNMEASURED, "scores": []}
    if not path.exists():
        return [{**base, "verdict": "no gold set"}]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    scorer = SCORERS.get("roads")
    if scorer is None:
        return [{**base, "verdict": f"gold set present ({len(rows)} rows); no scorer wired yet"}]
    return scorer(rows)


def organs_without_gold(covered: set[str]) -> list[dict]:
    from analyst.organs import ORGANS
    return [{"subject": f"organ:{o.name}", "version": o.version, "serving": None,
             "servable": UNMEASURED, "verdict": "no gold set", "scores": []}
            for o in ORGANS if o.name not in covered]


# ── the whole contract ───────────────────────────────────────────────────────

def contract(**kw) -> dict:
    """Every subject; one failing subject is recorded as its error, never
    allowed to silence the others."""
    entries: list[dict] = []
    for name, fn in (("incidents", lambda: incidents(**kw.get("incidents", {}))),
                     ("moh", lambda: moh(**kw.get("moh", {}))),
                     ("roads", lambda: roads(**kw.get("roads", {}))),
                     ("organs", lambda: organs_without_gold({"moh"}))):
        try:
            entries.extend(fn())
        except Exception as exc:                                # noqa: BLE001
            entries.append({"subject": name, "version": None, "servable": UNMEASURED,
                            "verdict": f"scoring failed: {type(exc).__name__}: {exc}",
                            "scores": []})
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
        "serving": [{k: e.get(k) for k in ("subject", "version", "servable", "verdict")}
                    for e in entries if e.get("serving")],
        "not_servable": [f"{e['subject']} {e['version']}: {e['verdict']}"
                         for e in entries if e.get("servable") is False],
    }


def table(record: dict) -> str:
    """The human form, for the journal: one line per version, verdict last."""
    lines = [f"GOLD CONTRACT · {record['measured_at'][:16]}Z"]
    for e in record["entries"]:
        tag = "serving" if e.get("serving") else (e.get("role", "").split(" ")[0] or "-")
        version = e.get("version") or "-"
        status = ("no gold set" if str(e.get("verdict", "")).startswith("no gold set")
                  else _word(e.get("servable")))
        run = f" [{e['run']}]" if e.get("run") else ""
        lines.append(f"  {e['subject']:<11} {version:<15} {tag:<8} {status:<13} "
                     f"{e.get('verdict')}{run}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="score every version against its gold set (reads only)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    record = contract()
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str) if a.json else table(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
