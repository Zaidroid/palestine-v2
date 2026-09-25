"""The analyst's consumer loop. One worker, one tick per interval, forever.

    .venv/bin/python -m analyst.loop                # the service
    .venv/bin/python -m analyst.loop --once --json  # one tick, machine-readable
    .venv/bin/python -m analyst.loop --organ lang   # one organ only
    .venv/bin/python -m analyst.loop --dry-run --organ moh --batches 80 --show -1
                                                    # read, write nothing

WHAT A TICK IS
For each registered organ, in order: read its watermark, take the next BATCH
claims past it (the organ's own `batch` if it names one, none younger than its
`settle_seconds`), ask the organ about each one, write a provenance row for
every claim it actually read, advance the watermark to the last claim of the
batch, commit. Then beat.

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
from datetime import datetime, timedelta, timezone
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


def _batch_size(organ) -> int:
    return int(getattr(organ, "batch", None) or store.BATCH)


def _fetch(cur, organ, after) -> list[dict]:
    """The organ's next batch. An organ with `settle_seconds` never sees a claim
    younger than that — see store.fetch_batch's `before`."""
    settle = int(getattr(organ, "settle_seconds", 0) or 0)
    if settle:
        before = datetime.now(timezone.utc) - timedelta(seconds=settle)
        return store.fetch_batch(cur, after, limit=_batch_size(organ), before=before)
    return store.fetch_batch(cur, after, limit=_batch_size(organ))


def _read_batch(conn, cur, organ, batch: list[dict], record, entry: dict,
                report: dict) -> None:
    """Ask the organ about every claim in the batch; `record` keeps each answer.

    `record` is store.record_run in the service and a collector under
    --dry-run, so the one path a claim takes — savepoint, reading, provenance,
    error row — is the same path in both.
    """
    for claim in batch:
        # One claim, one SAVEPOINT. A claim that blows up must not cost the
        # forty the organ already answered in this batch — and a plain
        # rollback() would do exactly that. The failure is recorded as a ROW,
        # outside the savepoint, so the error rate is a SELECT rather than a
        # line in a journal nobody aggregates.
        try:
            with conn.transaction():
                reading = organ.read(cur, claim)
                if reading is not None:
                    record(cur, claim_id=claim["claim_id"],
                           organ=organ.name, organ_version=organ.version,
                           outcome="ok", model=reading.model,
                           prompt_version=reading.prompt_version,
                           verdict=reading.verdict, votes=reading.votes,
                           agreed=reading.agreed,
                           json_valid=reading.json_valid,
                           latency_ms=reading.latency_ms,
                           raw=reading.raw)
        except Exception as exc:                                # noqa: BLE001
            record(cur, claim_id=claim["claim_id"], organ=organ.name,
                   organ_version=organ.version, outcome="error",
                   error=f"{type(exc).__name__}: {exc}")
            entry["errors"] += 1
            report["errors"] += 1
            continue
        if reading is not None:
            entry["read"] += 1
            report["processed"] += 1


def _summaries(cur, organs: list) -> dict:
    """Each organ's own one-line account, when it keeps one. A summary that
    fails is reported as its error, never as a failed tick."""
    out: dict = {}
    for organ in organs:
        fn = getattr(organ, "summary", None)
        if fn is None:
            continue
        try:
            out[organ.name] = fn(cur)
        except Exception as exc:                                # noqa: BLE001
            out[organ.name] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


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
            batch = _fetch(cur, organ, after)
            entry["scanned"] = len(batch)
            if not batch:
                entry["idle"] = "caught up"
                conn.commit()
                continue

            _read_batch(conn, cur, organ, batch, store.record_run, entry, report)

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
        report["summaries"] = _summaries(cur, organs)
    return report


def dry_run(organs: list, *, batches: int = 1, show: int | None = 20,
            probe=backpressure.available) -> dict:
    """Read as a tick would, from each organ's real watermark, and write NOTHING.

    No provenance row, no watermark, no heartbeat: every would-be `analyst_run`
    row is collected into the report instead. The connection is READ ONLY
    (store.connect_readonly), so a write that slipped through would fail on the
    database's word. Only `pure` organs run — organ A corrects `claim.lang`
    through the cursor and has no dry mode; it is listed as skipped, not run.
    `batches` walks that many batches forward on an in-memory cursor, so the
    whole corpus can be read in one invocation; `show` caps the rows kept per
    organ (None keeps all).
    """
    started = time.perf_counter()
    report: dict = {"dry_run": True, "organs": {}, "processed": 0, "errors": 0}
    pc_ok, pc_why = (True, "not asked — no organ in this run needs the PC")
    if any(o.needs_model and getattr(o, "pure", False) for o in organs):
        pc_ok, pc_why = probe()
    report["pc"] = {"available": pc_ok, "detail": pc_why}

    with store.connect_readonly() as conn, conn.cursor() as cur:
        for organ in organs:
            entry: dict = {"read": 0, "errors": 0, "scanned": 0, "verdicts": {},
                           "rows": []}
            report["organs"][organ.name] = entry
            if not getattr(organ, "pure", False):
                entry["skipped"] = ("writes outside provenance (not a pure "
                                    "organ); it has no dry mode")
                continue
            if organ.needs_model and not pc_ok:
                entry["paused"] = pc_why
                continue

            def collect(_cur, *, entry=entry, **row):
                if row.get("outcome") == "ok":
                    v = row.get("verdict")
                    entry["verdicts"][v] = entry["verdicts"].get(v, 0) + 1
                if show is None or len(entry["rows"]) < show:
                    entry["rows"].append(row)

            after = store.read_watermark(cur, organ.name)
            entry["watermark"] = [str(after[0]), after[1]] if after else None
            for _ in range(max(batches, 1)):
                batch = _fetch(cur, organ, after)
                if not batch:
                    entry["idle"] = "caught up"
                    break
                entry["scanned"] += len(batch)
                _read_batch(conn, cur, organ, batch, collect, entry, report)
                after = (batch[-1]["ingested_at"], batch[-1]["claim_id"])
            entry["cursor_would_be"] = [str(after[0]), after[1]] if after else None
        conn.rollback()
    report["seconds"] = round(time.perf_counter() - started, 3)
    return report


def _detail(report: dict) -> dict:
    """The heartbeat's payload: small, numeric, and enough to diagnose from."""
    lang = report.get("health", {}).get("lang", {})
    backlog = report.get("backlog", {})
    health = report.get("health", {})
    summaries = report.get("summaries", {})
    per_organ = {}
    for name in sorted(set(backlog) | set(health) | set(summaries)):
        h = health.get(name, {})
        per_organ[name] = {
            "backlog": (backlog.get(name) or {}).get("pending_claims"),
            "runs_1h": h.get("runs_1h"),
            "errors_1h": h.get("errors_1h"),
            "success_rate_1h": h.get("success_rate_1h"),
            **({"summary": summaries[name]} if name in summaries else {}),
        }
    return {
        "processed": report["processed"],
        "errors": report["errors"],
        "per_minute": report["per_minute"],
        "backlog": {k: v["pending_claims"] for k, v in backlog.items()},
        "organs_paused": report["skipped"],
        "pc": report["pc"]["detail"],
        # The rates the model organs will fill. Reported as None until an organ
        # produces the denominator — never as 1.0, which would read as a
        # perfect score for work nobody has done.
        "success_rate_1h": lang.get("success_rate_1h"),
        "json_valid_rate_1h": lang.get("json_valid_rate_1h"),
        "vote_agreement_1h": lang.get("vote_agreement_1h"),
        # Per organ: how far behind, how it did in the last hour, and its own
        # account (organ C: the newest bulletin's verdict against the series).
        "organs": per_organ,
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
    ap.add_argument("--dry-run", action="store_true",
                    help="read from the real watermarks and write NOTHING (no provenance, "
                         "no watermark, no heartbeat); pure organs only")
    ap.add_argument("--batches", type=int, default=1,
                    help="with --dry-run: how many batches to walk forward")
    ap.add_argument("--show", type=int, default=20,
                    help="with --dry-run: rows kept per organ (-1 keeps all)")
    a = ap.parse_args()

    organs = [by_name(n) for n in a.organ] if a.organ else None
    if a.dry_run:
        report = dry_run(ORGANS if organs is None else organs, batches=a.batches,
                         show=None if a.show < 0 else a.show)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    def _sig(*_):
        global _stop
        _stop = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    return run(a.once, organs, a.json, a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
