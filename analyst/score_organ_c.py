#!/usr/bin/env python3
"""F-11 — score the gateway's roles against the organ C gold set.

WHY THIS EXISTS
F-10 proved the bulletins are readable and committed the ground truth. The plan
(D3) says the Arabic organs are scored on BOTH gateway roles and the numbers
pick the model, and that the winner's heavy work runs in the night window
because the 35B evicts the resident model per swap. This is the measurement,
not the decision: it writes a table and an artifact, and picks nothing.

WHAT IT MEASURES
Per role, per field: how many rows the model answered, how many it answered
CORRECTLY against the gold reader, and — separately, because it is a different
failure — how often it produced a number where the bulletin states none. Row
level is reported too: how many bulletins it read completely right.

THE KEY IS NEVER PRINTED. The base URL and the key come from environment
variables named on the command line, so the caller can source v1's env file and
pass the name, not the value. A missing key is a refusal, not a retry.

BACKPRESSURE IS NORMAL (the project's own rule): the gateway has one resident
model and Honcho's dialectic turns hold it for 30-45 s, so a call can fail
without anything being wrong. Failures are counted, a run that cannot answer for
five rows in a row stops as `paused` and keeps its partial artifact, and the
caller resumes later. A call is never retried more than three times.

    usage:
      .venv/bin/python -m analyst.score_organ_c \\
          --gold tests/gold/moh_c.jsonl --csv /tmp/moh.csv \\
          --roles engine,engine-quality --limit 200 \\
          --base-url-env MINIMAX_BASE_URL --key-env MINIMAX_API_KEY \\
          --out ops/organ-c-scores.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import organ_c  # noqa: E402

PROMPT = """You are reading one daily statistical bulletin published by the \
Palestinian Ministry of Health in Gaza. Read it and return the numbers it states.

- as_of_date: the date printed at the END of the bulletin, as YYYY-MM-DD
- cum_killed, cum_injured: the CUMULATIVE totals since the start of the aggression
- last_24h_killed, last_24h_injured: the totals for the window the bulletin names
  (it is not always 24 hours; it may be 48, or a holiday period with no hours)
- since_ceasefire_killed, since_ceasefire_injured: the block "since the ceasefire"
- recovered: bodies recovered from under the rubble, if the bulletin states it

Rules: use null for any field the bulletin does not state. Never guess, never
carry a number over from another block. Digits only, no thousands separators.
Return a JSON object with exactly those nine keys and nothing else.

BULLETIN:
%s
"""

FIELDS = ("as_of_date", "cum_killed", "cum_injured", "last_24h_killed",
          "last_24h_injured", "since_ceasefire_killed", "since_ceasefire_injured",
          "recovered")


def call(base_url: str, key: str, role: str, text: str, timeout: int = 180) -> dict:
    """One call. Returns {'ok', 'json', 'raw', 'latency_ms', 'error', 'enforced'}."""
    body = {
        "model": role,
        "temperature": 0,
        "messages": [{"role": "user", "content": PROMPT % text}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "moh_bulletin", "schema": organ_c.SCHEMA, "strict": False}},
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "error": f"HTTP {exc.code}: {detail}", "enforced": True,
                "latency_ms": int((time.perf_counter() - t0) * 1000)}
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "enforced": True,
                "latency_ms": int((time.perf_counter() - t0) * 1000)}
    latency = int((time.perf_counter() - t0) * 1000)
    raw = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
    try:
        parsed = json.loads(raw)
    except Exception:                                            # noqa: BLE001
        return {"ok": False, "error": "reply was not JSON", "raw": raw, "enforced": True,
                "latency_ms": latency}
    return {"ok": True, "json": parsed, "raw": raw, "enforced": True, "latency_ms": latency}


def score_row(gold: dict, answer: dict) -> dict:
    """Field-level comparison. `invented` counts numbers where gold has none."""
    out = {}
    for field in FIELDS:
        truth = gold.get(field)
        got = answer.get(field)
        if truth is None:
            out[field] = "invented" if got not in (None, "") else "abstained"
        else:
            out[field] = "correct" if got == truth else "wrong"
    out["row"] = "correct" if all(v == "correct" for v in out.values() if v != "abstained") \
        and "wrong" not in out.values() and "invented" not in out.values() else "not-correct"
    return out


def summarise(results: list[dict]) -> dict:
    per_field: dict[str, dict[str, int]] = {f: {"correct": 0, "wrong": 0, "invented": 0,
                                                "abstained": 0} for f in FIELDS}
    answered = wrong_rows = 0
    for r in results:
        if not r.get("scored"):
            continue
        answered += 1
        for field, verdict in r["scored"].items():
            if field == "row":
                continue
            per_field[field][verdict] += 1
        if r["scored"]["row"] != "correct":
            wrong_rows += 1
    table = {}
    for field, counts in per_field.items():
        n = counts["correct"] + counts["wrong"] + counts["invented"]
        table[field] = {**counts, "compared": n,
                        "precision": round(counts["correct"] / n, 3) if n else None}
    return {"rows_scored": answered, "rows_wrong": wrong_rows,
            "rows_exact": answered - wrong_rows, "per_field": table}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--csv", required=True, help="the dump the gold set was built from")
    ap.add_argument("--roles", default="engine,engine-quality")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--base-url-env", default="MINIMAX_BASE_URL")
    ap.add_argument("--key-env", default="MINIMAX_API_KEY")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    base_url = os.environ.get(args.base_url_env)
    key = os.environ.get(args.key_env)
    if not base_url:
        print(f"refusing: ${args.base_url_env} is not set", file=sys.stderr)
        return 2
    if not key:
        print(f"refusing: ${args.key_env} is not set (and it is never printed)", file=sys.stderr)
        return 2

    gold_rows = [json.loads(l) for l in Path(args.gold).read_text(encoding="utf-8").splitlines()]
    gold_rows = [r for r in gold_rows if r["reader"]["cum_killed"] is not None][:args.limit]
    texts = {}
    with open(args.csv, encoding="utf-8") as fh:
        for cid, _ts, text in csv.reader(fh):
            texts[int(cid)] = text
    missing = [r["claim_id"] for r in gold_rows if r["claim_id"] not in texts]
    if missing:
        print(f"refusing: {len(missing)} gold rows have no text in {args.csv}", file=sys.stderr)
        return 2

    artifact = Path(args.out)
    state = {"started_at": datetime.now(timezone.utc).isoformat(), "base_url": base_url,
             "roles": args.roles.split(","), "rows": {}}
    for role in args.roles.split(","):
        results = []
        consecutive_failures = 0
        status = "complete"
        for row in gold_rows:
            text = texts[row["claim_id"]]
            last_error = None
            for attempt in range(3):
                res = call(base_url, key, role, text)
                if res["ok"]:
                    break
                last_error = res["error"]
                time.sleep(2 * (attempt + 1))
            if not res["ok"]:
                consecutive_failures += 1
                results.append({"claim_id": row["claim_id"], "error": last_error})
                if consecutive_failures >= 5:
                    status = "paused"
                    break
                continue
            consecutive_failures = 0
            results.append({"claim_id": row["claim_id"], "latency_ms": res["latency_ms"],
                            "answer": res["json"], "scored": score_row(row["reader"], res["json"])})
            # nothing is written to the databank and no state is mutated: this is a
            # measurement, and its artifact is written incrementally so a paused run
            # keeps everything it paid for. While a role is mid-run its status says
            # so — an artifact that says `complete` at row 40 is a lie, and a
            # resuming caller has to be able to tell the difference.
            state["rows"][role] = results
            state["status"] = {**state.get("status", {}), role: "running"}
            state["summary"] = {r: summarise(state["rows"][r]) for r in state["rows"]}
            artifact.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

        state["rows"][role] = results
        state["status"] = {**state.get("status", {}), role: status}
        state["summary"] = {r: summarise(state["rows"][r]) for r in state["rows"]}
        artifact.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

        s = state["summary"][role]
        print(f"\n== {role} · {s['rows_scored']} rows scored · "
              f"{s['rows_exact']} read completely right · status {status} ==")
        for field, v in s["per_field"].items():
            print(f"   {field:<26} correct {v['correct']:>3}  wrong {v['wrong']:>3}  "
                  f"invented {v['invented']:>3}  abstained {v['abstained']:>3}  "
                  f"precision {v['precision']}")
    print(f"\nartifact: {artifact}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
