"""The organs, and the contract every one of them keeps.

An organ is four things and nothing else:

    name          what it is called in `analyst_run.organ` and its watermark
    version       bumped whenever its answer could change; runs stay comparable
    needs_model   True if it calls the PC — those are the ones the game watcher
                  pauses, and the only ones the backpressure probe gates
    read(cur, claim) -> Reading | None

`read` returns None for a claim this organ has nothing to say about, and the
loop writes no provenance row for it (068 says why). Everything else — the
cursor, the batching, the heartbeat, the pause — belongs to the loop, so an
organ is a function and can be tested as one.

P0 REGISTERS ONE ORGAN. B–G are written against this same interface: B and C
will return a Reading whose `writes` are `claim_classification` rows instead of
a `claim.lang` update, and will set `model`, `votes`, `agreed` and `json_valid`
from the §2.5 redundancy. The loop already carries all of those columns.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import lang as lang_mod                            # noqa: E402


@dataclass
class Reading:
    """One organ's answer about one claim, plus everything it will be judged by."""
    verdict: str
    model: str | None = None
    prompt_version: str | None = None
    votes: list | None = None
    agreed: bool | None = None
    json_valid: bool | None = None
    raw: dict = field(default_factory=dict)
    latency_ms: int | None = None


class LanguageOrgan:
    """Organ A — the language a claim is in, and the provenance of that answer.

    It reads a claim only when nothing has stamped `attrs.lang_detector` on it.
    Once the three insert sites detect at ingest (they do), that is the empty
    set on a healthy system, and this organ is the safety net: a new writer that
    forgets to detect, a run where the library was missing, a row written before
    this existed. The net is the point. The insert sites can be changed by
    someone who has never read this file, and the corpus stays true.

    IT IS A CORRECTIVE WRITE TO AN IMMUTABLE TABLE, AND THAT IS ARGUED
    `claim` is immutable because it records what a source SAID. A language code
    is not something the source said — it is a measurement of the text, made by
    us, with a library that has a version. So it is stamped like every other
    measurement in this repo: the value, and what produced it, in the same
    write. `attrs.lang_detector` is what makes the row honest, and it is also
    what stops this organ from touching the same row twice.
    """

    name = "lang"
    version = "a/1"
    needs_model = False

    def wants(self, claim: dict) -> bool:
        return not (claim.get("attrs") or {}).get("lang_detector")

    def read(self, cur, claim: dict) -> Reading | None:
        if not self.wants(claim):
            return None
        t0 = time.perf_counter()
        code, detector = lang_mod.detect(claim.get("raw_text"))
        cur.execute("""
            UPDATE claim
               SET lang  = %s,
                   attrs = attrs || jsonb_build_object('lang_detector', %s::text)
             WHERE claim_id = %s AND ingested_at = %s""",
            (code, detector, claim["claim_id"], claim["ingested_at"]))
        return Reading(
            verdict=code, model=detector,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            raw={"was": claim.get("lang"), "now": code},
        )


# The registry. P0 is organ A alone; adding an organ is adding it here, and the
# loop grows a watermark, a heartbeat number and a health row for it with no
# other change.
ORGANS: list = [LanguageOrgan()]


def by_name(name: str):
    for o in ORGANS:
        if o.name == name:
            return o
    raise KeyError(f"no analyst organ named {name!r}; have "
                   f"{[o.name for o in ORGANS]}")
