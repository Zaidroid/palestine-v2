"""The posture every v2 fetcher shares: atomic, floored, ledgered.

Extracted at the third and fourth fetcher (OONI and IODA), not the first —
two copies of a habit is a coincidence, four is a rule that should live in one
place. `ops/fetch_gho_wash.py` established it and `ops/fetch_t4p.py` repeated
it; both now read from here.

The three properties, and why each one exists:

  ATOMIC     write to a temp file and rename. A fetcher killed halfway (this
             host rebooted five times in fourteen hours on 2026-08-07/08)
             must leave yesterday's complete file, never today's half of one.

  FLOORED    refuse a payload below a measured floor and keep what is already
             on disk. A truncated fetch that overwrites a good file is how a
             series silently loses its history, and NO downstream check can
             distinguish that from the source itself shrinking. The floor is
             the only place that distinction can be made, because it is the
             only place that still holds both.

  LEDGERED   one NDJSON line per attempt to ops/fetch-events.ndjson, in the
             {label, at, outcome} shape gap_radar already reads from v1's
             refresh-events. A fetcher that fails silently is worse than no
             fetcher: the loader keeps loading yesterday's file and every
             freshness check passes.

Deliberately NOT here: retry/backoff. Every fetcher so far runs nightly
against a source that will be there tomorrow, and a retry loop around a
publisher having a bad night is how one job holds a scheduler open for an
hour. Add it when a source needs it, and say which one did.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "ops" / "fetch-events.ndjson"
UA = "palestine-v2 databank (zsalem33@gmail.com)"


class FetchRefused(Exception):
    """The payload arrived and was not good enough to overwrite what we have."""


def get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(url: str, timeout: int = 120):
    return json.loads(get(url, timeout))


def event(label: str, outcome: str, **extra) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a") as fh:
        fh.write(json.dumps({"label": label,
                             "at": datetime.now(timezone.utc).isoformat(),
                             "outcome": outcome, **extra}) + "\n")


def write_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.replace(path)


def check_floor(label: str, n: int, floor: int) -> None:
    """Raise rather than return a flag, so a caller cannot forget to look."""
    if n < floor:
        event(label, "refused", rows=n, floor=floor)
        raise FetchRefused(
            f"{label}: {n} rows below the floor of {floor} — keeping the file "
            "already on disk. A short fetch that overwrites a good file is "
            "indistinguishable, one layer later, from the source shrinking.")


def stage_dir(argv: list[str]) -> Path | None:
    """`--dry-run --stage DIR`: a dry run that also materialises the raw file
    it WOULD write, under DIR — so the loader's own dry run can be pointed at
    tonight's answer without the raw tree, bronze or the ledger being touched.
    Added for P1-B.3's proofs; nothing in the nightly passes it."""
    if "--stage" not in argv:
        return None
    i = argv.index("--stage")
    if i + 1 >= len(argv):
        raise SystemExit("--stage needs a directory")
    return Path(argv[i + 1])


def stage(directory: Path | None, name: str, payload) -> None:
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload, ensure_ascii=False))
    print(f"         staged {directory / name}")


def stamp(path: Path, source: str, license_note: str, attribution: str,
          **extra) -> None:
    """Every raw tree says what it is and under what terms it was taken.

    A directory of JSON with no provenance is the thing this whole databank
    exists not to produce.
    """
    write_atomic(path, {"fetched_at": datetime.now(timezone.utc).isoformat(),
                        "source": source, "license": license_note,
                        "attribution": attribution, **extra})
