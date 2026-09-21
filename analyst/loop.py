"""The analyst's consumer loop. One worker, one tick per interval, forever.

    .venv/bin/python -m analyst.loop                # the service
    .venv/bin/python -m analyst.loop --once --json  # one tick, machine-readable
    .venv/bin/python -m analyst.loop --organ lang   # one organ only

WHAT A TICK IS
For each registered organ, in order: read its watermark, take the next BATCH
claims past it, ask the organ about each one, write a provenance row for every
claim it actually read, advance the watermark to the last claim of the batch,
commit. Then beat.

WHY THE WATERMARK ADVANCES OVER CLAIMS THE ORGAN DECLINED
See store.fetch_batch. The cursor tracks what has been LOOKED AT, not what has
been acted on. An organ that declines every claim in a batch has still read
them, and a cursor that only moved on action would sit forever one row short of
the next interesting claim, beating healthily the whole time.

WHY A MODEL ORGAN IS SKIPPED RATHER THAN RETRIED
The PC is a games machine that also thinks. When the game watcher stops
llama-swap, the port refuses, and that is the system working: ingestion never
waits for the analyst (§1), so the organ is skipped for this tick, the reason is
recorded in the heartbeat detail, and the next tick tries again. The watermark
does not move, so nothing is lost — the backlog simply grows until the PC is
free, which is exactly what it is supposed to mean.

WHY THE BEAT CARRIES NUMBERS AND NOT A WORD
The MiniMax path this component was designed against failed 29,686 times out of
29,687 and said "falling back to rules" every time, truthfully. Health here is
processed-per-minute, backlog depth, error rate, JSON-valid rate and the pause
reason, written into ops_heartbeat.detail on every cycle, where ops/watchdog.py
and /health already read every other collector's liveness. A failed tick calls
`fail()`, which leaves last_ok alone, so "running and failing" and "not running"
stay the two different problems they are.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import backpressure, store                         # noqa: E402
from analyst.organs import ORGANS, by_name                       # noqa: E402
from ops.heartbeat import beat, fail                             # noqa: E402

HEARTBEAT = "analyst"
INTERVAL = 60          # seconds between ticks; duplicated in ops/watchdog.py
GRACE = 900            # and there is a test that says so

_stop = False


def _sleep(seconds: int) -> None:
    """Sleep in one-second slices so a SIGTERM is answered in about a second.

    A plain sleep(60) makes `systemctl stop` wait up to a minute and, on a
    deploy that restarts several things at once, look like a hang. The loop
    holds no lock and no connection while it waits, so there is nothing to
    finish — only the flag to notice.
    """
    for _ in range(max(seconds, 0)):
        if _stop:
            return
        time.sleep(1)


def tick(organs: list, *, probe=backpressure.available) -> dict:
    """One pass over every organ. Returns what the heartbeat will carry."""
    started = time.perf_counter()
    report: dict = {"organs": {}, "processed": 0, "errors": 0, "skipped": 0}

    # Asked ONCE per tick, and only if some organ actually needs the PC. A
    # deterministic-only tick must not depend on a machine across the tailnet.
    pc_ok, pc_why = (True, "not asked — no registered organ needs the PC")
    if any(o.needs_model for o in organs):
        pc_ok, pc_why = probe()
    report["pc"] = {"available": pc_ok, "detail": pc_why}

    for organ in organs:
        entry: dict = {"read": 0, "errors": 0, "scanned": 0}
        report["organs"][organ.name] = entry

        if organ.needs_model and not pc_ok:
            entry["paused"] = pc_why
            report["skipped"] += 1
            continue

        with store.connect() as conn, conn.cursor() as cur:
            after = store.read_watermark(cur, organ.name)
            batch = store.fetch_batch(cur, after)
            entry["scanned"] = len(batch)
            if not batch:
                entry["idle"] = "caught up"
                conn.commit()
                continue

            for claim in batch:
                # One claim, one SAVEPOINT. A claim that blows up must not cost
                # the forty the organ already answered in this batch — and a
                # plain rollback() would do exactly that. The failure is
                # recorded as a ROW, outside the savepoint, so the error rate
                # is a SELECT rather than a line in a journal nobody aggregates.
                try:
                    with conn.transaction():
                        reading = organ.read(cur, claim)
                        if reading is not None:
                            store.record_run(
                                cur, claim_id=claim["claim_id"],
                                organ=organ.name, organ_version=organ.version,
                                outcome="ok", model=reading.model,
                                prompt_version=reading.prompt_version,
                                verdict=reading.verdict, votes=reading.votes,
                                agreed=reading.agreed,
                                json_valid=reading.json_valid,
                                latency_ms=reading.latency_ms,
                                raw=reading.raw)
                except Exception as exc:                        # noqa: BLE001
                    store.record_run(cur, claim_id=claim["claim_id"],
                                     organ=organ.name,
                                     organ_version=organ.version,
                                     outcome="error",
                                     error=f"{type(exc).__name__}: {exc}")
                    entry["errors"] += 1
                    report["errors"] += 1
                    continue
                if reading is not None:
                    entry["read"] += 1
                    report["processed"] += 1

            last = batch[-1]
            store.write_watermark(cur, organ.name, last["ingested_at"],
                                  last["claim_id"])
            conn.commit()

    elapsed = max(time.perf_counter() - started, 1e-6)
    report["seconds"] = round(elapsed, 3)
    report["per_minute"] = round(report["processed"] / elapsed * 60, 1)

    with store.connect() as conn, conn.cursor() as cur:
        report["backlog"] = store.backlog(cur)
        report["health"] = store.health(cur)
    return report


def _detail(report: dict) -> dict:
    """The heartbeat's payload: small, numeric, and enough to diagnose from."""
    lang = report.get("health", {}).get("lang", {})
    return {
        "processed": report["processed"],
        "errors": report["errors"],
        "per_minute": report["per_minute"],
        "backlog": {k: v["pending_claims"] for k, v in report.get("backlog", {}).items()},
        "organs_paused": report["skipped"],
        "pc": report["pc"]["detail"],
        # The rates the model organs will fill. Reported as None until an organ
        # produces the denominator — never as 1.0, which would read as a
        # perfect score for work nobody has done.
        "success_rate_1h": lang.get("success_rate_1h"),
        "json_valid_rate_1h": lang.get("json_valid_rate_1h"),
        "vote_agreement_1h": lang.get("vote_agreement_1h"),
    }


def run(once: bool = False, organs: list | None = None,
        as_json: bool = False, interval: int = INTERVAL) -> int:
    organs = ORGANS if organs is None else organs
    while not _stop:
        try:
            report = tick(organs)
        except Exception as exc:                                # noqa: BLE001
            fail(HEARTBEAT, f"{type(exc).__name__}: {exc}", interval, GRACE)
            print(f"tick failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if once:
                return 1
            _sleep(interval)
            continue

        detail = _detail(report)
        beat(HEARTBEAT, interval, GRACE, detail)
        if as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        else:
            per = ", ".join(f"{n}: {e['read']}/{e['scanned']}"
                            + (f" paused ({e['paused'][:40]})" if e.get("paused") else "")
                            for n, e in report["organs"].items())
            back = ", ".join(f"{k} {v['pending_claims']}"
                             for k, v in report.get("backlog", {}).items())
            print(f"tick {report['seconds']:.2f}s · {per} · errors {report['errors']}"
                  f" · backlog {back or '-'}")
        if once:
            return 0
        _sleep(interval)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="the analyst's consumer loop")
    ap.add_argument("--once", action="store_true", help="one tick, then exit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--organ", action="append", help="run only this organ (repeatable)")
    ap.add_argument("--interval", type=int, default=INTERVAL)
    a = ap.parse_args()

    def _sig(*_):
        global _stop
        _stop = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    organs = [by_name(n) for n in a.organ] if a.organ else None
    return run(a.once, organs, a.json, a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
