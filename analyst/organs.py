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

Three optional attributes, read by the loop with a default:

    pure          True if `read` writes nothing through the cursor — the
                  Reading the loop stores is the organ's only record. Only a
                  pure organ runs under `analyst.loop --dry-run`. Default False.
    batch         claims per tick for this organ (default store.BATCH). A
                  deterministic organ that declines almost every claim can
                  walk the corpus ten times faster than one that answers each.
    settle_seconds  claims younger than this are not fetched yet (default 0):
                  for an organ that judges a claim against what another job
                  derives from it, and must wait for that job's turn.

and one optional method, `summary(cur) -> dict`, whose answer rides in the
heartbeat detail under the organ's name.

TWO ORGANS ARE REGISTERED, BOTH DETERMINISTIC (P2-A.1): A (language) and C
(the Gaza MoH bulletin, held against the series the ingest writes). B and D–G
are written against this same interface and will set `model`, `votes`,
`agreed` and `json_valid` from the §2.5 redundancy; the loop already carries
all of those columns. No organ that needs the PC is registered: the plan
(Z-2) moves the model work onto bounded seat batches, and an organ with no
gold set behind it must not put a model's guesses into the record (§5).
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import lang as lang_mod                            # noqa: E402
from analyst import organ_c                                     # noqa: E402
from analyst.gold_moh import GOLD_YEAR                          # noqa: E402
from cascade.moh_gaza import INDICATORS                         # noqa: E402
from ingest.sources.moh_gaza import DATASET_KEY, SOURCE_KEY     # noqa: E402


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


# ── organ C in the loop ──────────────────────────────────────────────────────

# organ C's fields, and the indicator ingest/sources/moh_gaza.py files each one
# under. Built from the ingest's own vocabulary so the two can never drift into
# comparing different things under the same name.
SERIES_FIELDS: dict[str, str] = {
    "cum_killed":              INDICATORS[("cumulative", "deaths")],
    "cum_injured":             INDICATORS[("cumulative", "injuries")],
    "since_ceasefire_killed":  INDICATORS[("since_ceasefire", "deaths")],
    "since_ceasefire_injured": INDICATORS[("since_ceasefire", "injuries")],
    "recovered":               INDICATORS[("since_ceasefire", "recovered")],
    "last_24h_killed":         INDICATORS[("daily", "deaths")],
    "last_24h_injured":        INDICATORS[("daily", "injuries")],
}
# The window lines are a DAY only when the bulletin says 24 hours. A 48-hour or
# a holiday window is not a day's count, so the series must hold none from it.
WINDOW_FIELDS = ("last_24h_killed", "last_24h_injured")
BULLETIN_MARK = "التقرير الإحصائي"      # the ingest's own filter, after bidi cleaning

# The reader is measured on the bulletins of its gold set — posted in 2026, the
# post-ceasefire daily format — and on nothing older. MEASURED 2026-09-25 by a
# dry run over all 498 archived bulletins: on the 295 of 2025 it refuses 286 on
# schema and "accepts" exactly one, a misread (25 Jul 2025: cumulative killed
# 8,527, window killed 59,676 — the aid-seekers' and the war's totals in the
# wrong slots), which then became every later bulletin's "previous" and had all
# 203 of 2026 refused as implausible jumps. A reader outside its measured domain
# is not a control, so those bulletins are declined, not judged.
READER_FROM = date(int(GOLD_YEAR), 1, 1)

# The verdict vocabulary, worst first. One word per bulletin; the per-field
# states that decided it are in `raw.fields`.
REFUSED = "refused"              # organ C's validator will not stand behind it
NOT_IN_SERIES = "not-in-series"  # the series holds nothing for that day
DISAGREE = "disagree"            # a field both hold differs, or the series holds one C does not
SERIES_GAP = "series-gap"        # the bulletin states a number the series lacks
AGREE = "agree"
VERDICTS = (REFUSED, NOT_IN_SERIES, DISAGREE, SERIES_GAP, AGREE)


def compare(reading: dict, held: dict[str, float]) -> dict[str, dict]:
    """Field by field: what organ C read against what the series holds.

    `held` maps indicator -> value for the day. States: agree · differ (both
    hold a number, not the same) · missing (the bulletin states it, the series
    lacks it) · extra (the series holds a number organ C does not read — for a
    window field, one filed as a day's count from a bulletin whose window is
    not 24 hours). A field neither side holds is left out.
    """
    is_day = reading.get("window_hours") == 24
    out: dict[str, dict] = {}
    for field_name, indicator in SERIES_FIELDS.items():
        mine = reading.get(field_name)
        if field_name in WINDOW_FIELDS and not is_day:
            mine = None
        theirs = held.get(indicator)
        if mine is None and theirs is None:
            continue
        if mine is None:
            state = "extra"
        elif theirs is None:
            state = "missing"
        elif float(mine) == float(theirs):
            state = "agree"
        else:
            state = "differ"
        out[field_name] = {"state": state, "read": mine,
                           "held": None if theirs is None else float(theirs)}
    return out


def verdict_of(accepted: bool, held: dict, fields: dict[str, dict]) -> str:
    """One word, worst first: refused > not-in-series > disagree > gap > agree."""
    if not accepted:
        return REFUSED
    if not held:
        return NOT_IN_SERIES
    states = {f["state"] for f in fields.values()}
    if states & {"differ", "extra"}:
        return DISAGREE
    if "missing" in states:
        return SERIES_GAP
    return AGREE


class MoHBulletinOrgan:
    """Organ C in the loop — the Gaza MoH bulletin, read a second time and held
    against the series the ingest wrote from it. It writes provenance only.

    WHY IT DOES NOT WRITE THE SERIES
    `ingest/sources/moh_gaza.py` is the one writer of the `gaza_moh_daily`
    dataset: every hour it reads new bulletins with `cascade/moh_gaza.parse` and
    upserts all seven indicators, the two daily ones included, superseding a
    revised value rather than overwriting it (F182). Measured 2026-09-25: its
    cumulative, since-ceasefire and recovered rows run to the newest bulletin
    (2026-09-24); its DAILY rows stop at 2026-08-09, because the Ministry began
    writing the 24 h lines value-first (`▪️ 6 إصابات`, `36 إصابة.`, `- 5 شهداء`)
    and that parser reads only label-first lines (`عدد الشهداء 7`). A second
    writer for the same indicators would have two readers superseding each
    other's rows, and the analyst's contract (068) forbids it writing
    `observation` anyway. So the ingest writes; organ C — a reader with a gold
    set behind it and none of the ingest's code — reads every bulletin again
    and says, per bulletin, as a row in `analyst_run`, whether the series holds
    what the bulletin states. The break of 08-09 is exactly what this reports
    (`series-gap` on the two window fields), within a tick instead of seven
    weeks. Resuming the daily rows is a change to the WRITER, and it waits on
    the gold contract (ops/gold_contract.py: this reader is human-read on 20
    rows of the 100 audit F229 requires before it may feed a served number).

    WHAT IT COMPARES
    The current rows the ingest keyed on the bulletin's posting day
    (`occurred_at = reported_at::date`, exactly as `_upsert_day` keys them),
    field by field — see `compare` — once the ingest has had two cycles to
    write them (`settle_seconds`), and only for bulletins inside the reader's
    measured domain (`READER_FROM`). The cumulative, ceasefire and recovered
    fields are an INDEPENDENT check: two readers that share no code. The T4P
    cross-check (ops/gaza_crosscheck.py) stays the control on the cumulative
    totals, from a third transcription.

    MEASURED 2026-09-25 (dry run, read-only, all 113,172 claims in 51 s): 203
    bulletins of 2026 read, 0 errors — agree 103, series-gap 98, disagree 1,
    refused 1. The cumulative and since-ceasefire totals agree on 203 of 203;
    the window lines agree on every day the series holds one (66 killed, 69
    injured) and are missing on 91/93 (Jan–Apr, before the daily rows began,
    and every bulletin from 2026-08-10); `recovered` is missing on 8 days. The
    one disagreement is 2026-04-25, where the series holds 32 as that DAY's
    injuries from a 48-hour bulletin; the one refusal is 2026-06-07, the
    extra-digit 1,730,128 — which the series holds.

    WHICH READING IS "PREVIOUS"
    organ C's validator judges a bulletin against the last ACCEPTED one (B1):
    here, the accepted reading with the latest `as_of_date` before this
    bulletin's, from this organ's own `analyst_run` rows and from the readings
    this process has made (so a dry run, which records nothing, judges the same
    way). By date and not by processing order, so a claim that arrives late is
    judged against the day before it. A refused reading is never anyone's
    previous — which is how the 7 June 1,730,128 does not poison 8 June.
    """

    name = "moh"
    # The reader's version, plus this comparison's. Bump the suffix when what a
    # verdict means changes; the reader bumps its own.
    version = f"{organ_c.VERSION}+series/1"
    needs_model = False
    pure = True
    # ~113k claims at 200 a minute is nine hours for the first pass; the organ
    # declines all but ~200 of them on a source-id comparison, so a larger bite
    # costs a larger fetch and nothing else (measured: the whole corpus in 51 s).
    batch = 2000
    # The ingest writes the series hourly (ops/ingest-gaza.sh, cadence 3600 s).
    # Read a bulletin a minute after it lands and the series cannot hold it yet:
    # every newest bulletin would be `not-in-series`, and the cursor would pass
    # it for good. Two ingest cycles of patience; a bulletin still absent after
    # that is a real `not-in-series` — the ingest has fallen behind.
    settle_seconds = 2 * 3600

    def __init__(self) -> None:
        self._source_id: int | None = None
        self._dataset_id: int | None = None
        self._looked_up = False
        self._accepted: dict[str, dict] = {}

    # ── lookups ────────────────────────────────────────────────────────────
    def _ids(self, cur) -> None:
        if self._looked_up:
            return
        cur.execute("SELECT source_id FROM source WHERE key = %s", (SOURCE_KEY,))
        row = cur.fetchone()
        self._source_id = row[0] if row else None
        cur.execute("SELECT dataset_id FROM dataset WHERE key = %s", (DATASET_KEY,))
        row = cur.fetchone()
        self._dataset_id = row[0] if row else None
        self._looked_up = True

    def wants(self, claim: dict) -> bool:
        if self._source_id is None or claim.get("source_id") != self._source_id:
            return False
        posted = claim.get("reported_at")
        if posted is None or posted.date() < READER_FROM:
            return False
        return BULLETIN_MARK in organ_c.clean(claim.get("raw_text") or "")

    def _previous_read(self, as_of: str) -> tuple[str, dict] | None:
        """From the readings this process accepted."""
        days = [d for d in self._accepted if d < as_of]
        if not days:
            return None
        day = max(days)
        return day, self._accepted[day]

    def _previous_stored(self, cur, as_of: str) -> tuple[str, dict] | None:
        """From this organ's own provenance rows."""
        cur.execute("""
            SELECT raw->>'as_of_date',
                   (raw->'reading'->>'cum_killed')::bigint,
                   (raw->'reading'->>'cum_injured')::bigint
              FROM analyst_run
             WHERE organ = %s AND outcome = 'ok'
               AND (raw->>'accepted')::boolean
               AND raw->>'as_of_date' < %s
             ORDER BY raw->>'as_of_date' DESC, run_id DESC
             LIMIT 1""", (self.name, as_of))
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        return row[0], {"cum_killed": row[1], "cum_injured": row[2]}

    def previous(self, cur, as_of: str) -> dict | None:
        """The accepted reading with the latest as_of_date before `as_of`."""
        found = [p for p in (self._previous_read(as_of), self._previous_stored(cur, as_of)) if p]
        if not found:
            return None
        _, reading = max(found, key=lambda p: p[0])
        return {"cum_killed": reading.get("cum_killed"),
                "cum_injured": reading.get("cum_injured")}

    def series(self, cur, reported_at) -> tuple[dict[str, float], list[int]]:
        """What the series holds for the bulletin's posting day, and which
        claims wrote it. Keyed exactly as the ingest keys it."""
        if self._dataset_id is None or reported_at is None:
            return {}, []
        cur.execute("""
            SELECT indicator, value_num, attrs->>'claim_id'
              FROM observation
             WHERE dataset_id = %s AND occurred_at = %s::date
               AND upper_inf(sys_period) AND v1_stable_id IS NULL
             ORDER BY observation_id""", (self._dataset_id, reported_at))
        held: dict[str, float] = {}
        claims: set[int] = set()
        for indicator, value, claim_id in cur.fetchall():
            held.setdefault(indicator, float(value))
            if claim_id and str(claim_id).isdigit():
                claims.add(int(claim_id))
        return held, sorted(claims)

    # ── the reading ────────────────────────────────────────────────────────
    def read(self, cur, claim: dict) -> Reading | None:
        self._ids(cur)
        if not self.wants(claim):
            return None
        t0 = time.perf_counter()
        reported_at = claim.get("reported_at")
        reading = organ_c.read(claim.get("raw_text") or "", reported_at)
        as_of = reading["as_of_date"]
        judged = organ_c.validate(reading, previous=self.previous(cur, as_of),
                                  reported_at=reported_at)
        if judged.ok:
            self._accepted[as_of] = reading
        held, series_claims = self.series(cur, reported_at)
        fields = compare(reading, held)
        return Reading(
            verdict=verdict_of(judged.ok, held, fields),
            # What to blame: the deterministic reader and its version. votes,
            # agreed and json_valid stay None — nothing was voted on and no JSON
            # was asked for; `agreed` means the §2.5 vote, not agreement with
            # the series, which is the verdict.
            model=f"organ_c@{organ_c.VERSION}",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            raw={
                "as_of_date": as_of,
                "day": reported_at.date().isoformat() if reported_at else None,
                "window_hours": reading.get("window_hours"),
                "accepted": judged.ok,
                "reasons": [r.code for r in judged.reasons],
                "notes": [n.code for n in judged.notes],
                "fields": fields,
                "series_claims": series_claims,
                "reading": reading,
            },
        )

    def summary(self, cur) -> dict:
        """The newest bulletin's verdict and the last 30 days' tally — the
        number that says, on the heartbeat, whether the series is keeping up."""
        cur.execute("""
            SELECT DISTINCT ON (claim_id) claim_id, verdict, raw->>'as_of_date'
              FROM analyst_run
             WHERE organ = %s AND outcome = 'ok'
             ORDER BY claim_id, run_id DESC""", (self.name,))
        rows = [r for r in cur.fetchall() if r and r[2]]
        if not rows:
            return {"newest": None, "last_30d": {}}
        newest = max(rows, key=lambda r: (r[2], r[0]))
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        tally: dict[str, int] = {}
        for _, verdict, as_of in rows:
            if as_of >= cutoff:
                tally[verdict] = tally.get(verdict, 0) + 1
        return {"newest": {"claim_id": newest[0], "as_of_date": newest[2],
                           "verdict": newest[1]},
                "last_30d": tally}


# The registry. Adding an organ is adding it here, and the loop grows a
# watermark, a heartbeat number and a health row for it with no other change.
ORGANS: list = [LanguageOrgan(), MoHBulletinOrgan()]


def by_name(name: str):
    for o in ORGANS:
        if o.name == name:
            return o
    raise KeyError(f"no analyst organ named {name!r}; have "
                   f"{[o.name for o in ORGANS]}")
