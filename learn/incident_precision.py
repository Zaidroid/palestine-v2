"""P1.1 — measure what the incident classifier is actually right about.

    .venv/bin/python -m learn.incident_precision --sample     # draw the sample
    .venv/bin/python -m learn.incident_precision --score      # after scoring
    .venv/bin/python -m learn.incident_precision --show       # last result

WHY THIS IS NOT OPTIONAL
The incident vertical shipped with a yield number (~22% of news claims classify)
and no accuracy number at all. Yield is a RATE: it says how often the classifier
fires, not how often it is right. Checkpoints were backtested to 0.816 and fuel
was measured; incidents were not, and everything downstream — the API, the MCP
tools, eventually a chatbot family members will believe — presents them with the
same confidence as the measured verticals.

WHY IT CANNOT REUSE THE CHECKPOINT BACKTEST
That harness works because a checkpoint has a later, independent observation to
be checked against: the road is still there in an hour and somebody else reports
it. An incident is an EVENT. Nobody re-reports that a particular raid happened
at 03:00, so there is no future ground truth to pair against. The only available
truth is the text itself, read by a human.

STRATIFIED, NOT RANDOM
A uniform sample of 120 would be ~76 raids and would tell us almost nothing
about `death` (2 rows) or `shooting` (4). The aggregate would then hide the weak
types exactly as it hid `slow` scoring 0/16 in the checkpoint parser. So every
type is sampled up to a cap, and precision is reported PER TYPE with an interval
wide enough to be honest about the small ones.

REJECTS ARE SAMPLED TOO
Precision alone is the metric you can game by classifying almost nothing. 679
claims were rejected and 497 called unclear; if the rejects are full of real
incidents then the vertical is quietly blind rather than accurate. Scoring a
sample of them gives the miss rate that precision on its own cannot show.

FOUR SEPARATE JUDGEMENTS
Recorded independently because they fail independently, and a single
right/wrong verdict would blur them:

    is_incident  does the text report a real-world incident at all
    type_ok      is the assigned incident_type the right one
    place_ok     does the resolved place match what the text names
    west_bank    is it actually in the West Bank (not Gaza, not abroad)

`is_incident` is the gate: if the text is not an incident the other three are
not applicable rather than false, and are left null.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect  # noqa: E402

SAMPLE_FILE = ROOT / "ops" / "incident-sample.ndjson"
SCORED_FILE = ROOT / "ops" / "incident-scored.ndjson"
RESULT_FILE = ROOT / "ops" / "incident-precision.json"


ROUND: str | None = None


def use_round(r: str | None) -> None:
    """Round files live side by side (`incident-sample-round8.ndjson`…) so a
    round is never clobbered by the next; `already_scored` reads them all."""
    global SAMPLE_FILE, SCORED_FILE, RESULT_FILE, ROUND
    ROUND = r
    if r:
        SAMPLE_FILE = ROOT / "ops" / f"incident-sample-round{r}.ndjson"
        SCORED_FILE = ROOT / "ops" / f"incident-scored-round{r}.ndjson"
        RESULT_FILE = ROOT / "ops" / f"incident-precision-round{r}.json"


# ADVERSARIAL STRATA (round 8, plan P0-C.3: "200 claims incl. 50 adversarial").
# Served incidents whose text carries a marker the classifier is known to
# stumble on. They are scored separately: a stress measure of the rules, not
# an estimate of the population's precision — mixing them into the core sample
# would bias it downward. Regexes run in Postgres (ARE), on the raw text.
ADVERSARIAL_STRATA = {
    "funeral":  r"تشييع|جنازة|جنازه|نعي|ينعي|تنعي|عزاء|وداع|ذكرى|ذكري|تزف|يزف|الشهيد المجاهد|القائد الشهيد",
    "notice":   r"إخطار|اخطار|يخطر|تخطر|أوامر|اوامر",
    "origin":   r"(شاب|شابا|مواطن|مواطنا|أسير|اسير|طفل|فتى|الشهيد)\s+\S+(\s+\S+){0,3}\s+من\s+(بلدة|قرية|مخيم|مدينة)",
    "opinion":  r"؟|\?|مقال|رأي|تحليل|قراءة في|لماذا|كيف",
    "long":     None,                       # length(raw_text) > 700: features, roundups
    "past":     r"عام 20[0-2][0-9]|العام الماضي|قبل عام|قبل أشهر|قبل اشهر|في مثل هذا اليوم|منذ عام",
    "bulletin": r"سولار|بنزين|كازية|كازيه|محروقات|الطابور",
}
ADVERSARIAL_SHARE = {"funeral": 12, "notice": 10, "origin": 10, "opinion": 6,
                     "long": 5, "past": 4, "bulletin": 3}                    # = 50

PER_TYPE_CAP = 20      # every type up to 20; the small ones are taken whole
REJECT_SAMPLE = 40     # enough to put a bound on the miss rate

# ONE GATE, READ FROM THE MODULE THAT SERVES IT (audit F210/F236, 2026-09-25).
# This file said 0.60 per type (docs/TIER1_COMPLETION_PLAN.md) while
# serve/quality.py and PLAN-2026-09-24 §6 G3 say 0.70, so round 8 reported no
# type below floor with death and siege at 0.60 — and `--score` exited 0, the
# ledger recorded gate_pass, while every served payload said the gate was 0.70.
# Whichever file a session read first decided whether the classifier shipped.
from serve.quality import GATE_OVERALL, GATE_TYPE as GATE_PER_TYPE  # noqa: E402
# Below this a "precision" is not a measurement. One sampled `closure` that
# happened to be wrong reads as 0.000 with a 95% interval of 0.00-0.79, which
# says nothing at all — failing the gate on it would be as dishonest as passing
# a type on 1/1. Such types are reported as UNMEASURED, which is a real state
# and the one that should drive the next round of sampling.
MIN_N_TO_GATE = 5

_WS = re.compile(r"\s+")
_DECOR = re.compile(r"[🔹🩵•┈▪◾]+")


def _clean(t: str) -> str:
    return _WS.sub(" ", _DECOR.sub(" ", t or "")).strip()


# ── sampling ────────────────────────────────────────────────────────────────

# ONE TEXT, ONE ROW (audit F238, 2026-09-25). The channels repost each other;
# `already_scored` keeps kin of PREVIOUS rounds out, but nothing collapsed the
# copies inside one draw — round 8 carried 5 copies of one text in the 12-row
# funeral stratum, so that stratum's 0.333 rested on ~8 texts, and every
# interval was narrower than the evidence. A copy is the same whitespace-
# normalised opening (150 chars, how the audit measured it); one representative
# per copy group is drawn, the stratum is filled from the next DISTINCT texts,
# and `copies_in_pool` says how many rows each representative stands for.
_COPY_KEY = "md5(left(regexp_replace(coalesce(c.raw_text, ''), '\\s+', ' ', 'g'), 150))"

# THE POPULATION BESIDE THE SAMPLE (audit F237). Every type is capped at the
# same n, so the pooled precision is a mean over strata of equal weight, not
# the precision of the mix the stream serves (raids dominate it). The pool's
# per-type count is recorded on every row so score() can weight by it.
SAMPLE_SQL = """
WITH pool AS (
  SELECT cc.claim_id, cc.verdict, cc.incident_type, cc.reject_reason,
         cc.place_text, cc.governorate, cc.confidence, cc.classifier_version,
         p.name_en AS resolved_place, p.name_ar AS resolved_place_ar,
         e.attrs->>'place_precision' AS place_precision,
         c.raw_text, s.key AS source_key, """ + _COPY_KEY + """ AS copy_key
  FROM claim_classification cc
  JOIN claim c USING (claim_id)
  LEFT JOIN place p ON p.place_id = cc.place_id
  LEFT JOIN event e ON e.event_id = cc.event_id
  LEFT JOIN source s ON s.source_id = c.source_id
  WHERE cc.classifier = 'news' AND cc.verdict = 'incident'
    AND NOT (cc.claim_id = ANY(%(exclude)s))
),
counted AS (
  SELECT pool.*,
         count(*) OVER (PARTITION BY verdict, incident_type) AS type_population,
         count(*) OVER (PARTITION BY verdict, incident_type, copy_key) AS copies_in_pool,
         row_number() OVER (PARTITION BY verdict, incident_type, copy_key
                            ORDER BY md5(claim_id::text)) AS copy_rn
  FROM pool
),
ranked AS (
  SELECT counted.*,
         row_number() OVER (PARTITION BY verdict, incident_type
                            ORDER BY md5(claim_id::text)) AS rn
  FROM counted WHERE copy_rn = 1
)
SELECT claim_id, verdict, incident_type, reject_reason, place_text, governorate,
       confidence, classifier_version, resolved_place, resolved_place_ar,
       place_precision, raw_text, source_key, type_population, copies_in_pool,
       copy_key
FROM ranked WHERE rn <= %(cap)s
"""

ADVERSARIAL_SQL = """
SELECT * FROM (
  SELECT DISTINCT ON (copy_key) * FROM (
    SELECT cc.claim_id, cc.verdict, cc.incident_type, cc.reject_reason,
           cc.place_text, cc.governorate, cc.confidence, cc.classifier_version,
           p.name_en AS resolved_place, p.name_ar AS resolved_place_ar,
           e.attrs->>'place_precision' AS place_precision,
           c.raw_text, s.key AS source_key, """ + _COPY_KEY + """ AS copy_key
    FROM claim_classification cc
    JOIN claim c USING (claim_id)
    LEFT JOIN place p ON p.place_id = cc.place_id
    LEFT JOIN event e ON e.event_id = cc.event_id
    LEFT JOIN source s ON s.source_id = c.source_id
    WHERE cc.classifier = 'news' AND cc.verdict = 'incident'
      AND NOT (cc.claim_id = ANY(%(exclude)s))
      AND {where}
  ) x
  WHERE NOT (copy_key = ANY(%(taken_keys)s))
  ORDER BY copy_key, md5(claim_id::text)
) d
ORDER BY md5(claim_id::text)
LIMIT %(limit)s
"""

REJECT_SQL = """
SELECT * FROM (
  SELECT DISTINCT ON (copy_key) * FROM (
    SELECT cc.claim_id, cc.verdict, cc.incident_type, cc.reject_reason,
           cc.place_text, cc.governorate, cc.confidence, cc.classifier_version,
           p.name_en AS resolved_place, c.raw_text, s.key AS source_key,
           """ + _COPY_KEY + """ AS copy_key
    FROM claim_classification cc
    JOIN claim c USING (claim_id)
    LEFT JOIN place p ON p.place_id = cc.place_id
    LEFT JOIN source s ON s.source_id = c.source_id
    WHERE cc.classifier = 'news' AND cc.verdict <> 'incident'
      -- 'too short' and 'gaza' are mechanical and not worth human time; the
      -- interesting rejects are the ones a rule decided against on meaning.
      -- NOTE this makes the miss rate a CONSERVATIVE (high) estimate: the
      -- mechanical rejects it skips are the ones most likely to be correct.
      AND coalesce(cc.reject_reason,'') NOT IN ('too short','gaza')
      AND NOT (cc.claim_id = ANY(%(exclude)s))
  ) x
  WHERE NOT (copy_key = ANY(%(taken_keys)s))
  ORDER BY copy_key, md5(claim_id::text)
) d
ORDER BY md5(claim_id::text)
LIMIT %(limit)s
"""


def already_scored() -> set[int]:
    """Claim ids used in any previous round.

    ROUND 1 WAS SPENT, NOT REUSED. Its 163 claims found 43 defects and those
    defects were then fixed by editing the classifier's patterns — which makes
    those exact claims a tuning set. Re-scoring them would measure how well the
    rules were fitted to the examples they were written from, and would come
    back near 1.0 while telling us nothing. Every later round must be disjoint.
    """
    seen: set[int] = set()
    for f in (ROOT / "ops").glob("incident-scored*.ndjson"):
        for line in f.read_text().splitlines():
            if line.strip():
                seen.add(json.loads(line)["claim_id"])
    return seen


def draw_sample(per_type_cap: int = PER_TYPE_CAP, adversarial: int = 0,
                rejects: int = REJECT_SAMPLE) -> int:
    exclude = sorted(already_scored())
    with connect() as conn, conn.cursor() as cur:
        rows = _draw(cur, exclude, per_type_cap, adversarial, rejects)
    _write_sample(rows)
    return len(rows)


def _draw(cur, exclude: list[int], per_type_cap: int = PER_TYPE_CAP,
          adversarial: int = 0, rejects: int = REJECT_SAMPLE) -> list[dict]:
    """The draw itself, on a caller's cursor (a test runs it in a transaction
    it rolls back). Reads only."""
    rows: list[dict] = []
    # KIN OF TUNING DATA ARE TUNING DATA (round 6). The channels repost
    # each other, so the unscored pool holds COPIES of scored claims under
    # fresh ids — identical content_hash — and same-story paraphrases that
    # clustered into the same event. v1.6's rules were tuned on round 5's
    # claims; scoring a copy of one measures how well the fix fits its own
    # example, wearing a new claim_id as a disguise. Excluding by id alone
    # left 466 such kin in the pool.
    if exclude:
        cur.execute("""
            SELECT DISTINCT c.claim_id FROM claim c
            WHERE c.content_hash IN (SELECT content_hash FROM claim
                                     WHERE claim_id = ANY(%(ids)s))
               OR (c.event_id IS NOT NULL AND c.event_id IN
                   (SELECT event_id FROM claim
                    WHERE claim_id = ANY(%(ids)s) AND event_id IS NOT NULL))""",
            {"ids": exclude})
        exclude = sorted({*exclude, *(r[0] for r in cur.fetchall())})
    cur.execute(SAMPLE_SQL, {"exclude": exclude, "cap": per_type_cap})
    cols = [d[0] for d in cur.description]
    core = [dict(zip(cols, r), stratum="core") for r in cur.fetchall()]
    rows += core
    # A text drawn once is not drawn again in another stratum either.
    taken_keys = {r["copy_key"] for r in core}
    if adversarial:
        # Each stratum gets its share of the adversarial budget, scaled;
        # a stratum that cannot fill its share leaves the rest unfilled
        # (a trap that fires rarely is a small trap).
        taken = set(exclude) | {r["claim_id"] for r in core}
        total_share = sum(ADVERSARIAL_SHARE.values())
        for name, share in ADVERSARIAL_SHARE.items():
            n = max(1, round(adversarial * share / total_share))
            rx = ADVERSARIAL_STRATA[name]
            where = "length(c.raw_text) > 700" if rx is None else "c.raw_text ~ %(rx)s"
            cur.execute(ADVERSARIAL_SQL.format(where=where),
                        {"exclude": sorted(taken), "limit": n, "rx": rx,
                         "taken_keys": sorted(taken_keys)})
            cols = [d[0] for d in cur.description]
            got = [dict(zip(cols, r), stratum=f"adv:{name}") for r in cur.fetchall()]
            taken |= {r["claim_id"] for r in got}
            taken_keys |= {r["copy_key"] for r in got}
            rows += got
    if rejects:
        cur.execute(REJECT_SQL, {"exclude": sorted({*exclude, *(r["claim_id"] for r in rows)}),
                                 "limit": rejects, "taken_keys": sorted(taken_keys)})
        cols = [d[0] for d in cur.description]
        rows += [dict(zip(cols, r), stratum="reject") for r in cur.fetchall()]
    return rows


def _write_sample(rows: list[dict]) -> None:
    # THE WHOLE TEXT (audit F211, 2026-09-25). This used to keep the first 400
    # characters, while the classifier reads all of it: a reject cue after
    # character 400 fired in production and not in the projection, and the
    # human judged a 700-char feature ("adv:long", defined as > 700) on its
    # first 400. ops/rescore_round.py reads this same field, so it now replays
    # the text the classifier actually saw.
    with SAMPLE_FILE.open("w") as fh:
        for r in rows:
            r["raw_text"] = _clean(r["raw_text"])
            r["confidence"] = float(r["confidence"]) if r["confidence"] else None
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


# ── scoring ─────────────────────────────────────────────────────────────────

def _wilson(k: int, n: int) -> tuple[float, float]:
    """95% Wilson interval. Used because the small types have n=2 and n=4, and
    a bare ratio there ("1.00 precision!") would be worse than no number."""
    if n == 0:
        return (0.0, 1.0)
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def score(promote: bool | None = None, allow_mixed: bool = False) -> dict:
    """Score the round. `promote`: write the serving file and the rounds ledger
    too — by default only when this is the newest round on disk (see below)."""
    if not SCORED_FILE.exists():
        raise SystemExit(f"no scores at {SCORED_FILE} — score the sample first")
    scored = [json.loads(x) for x in SCORED_FILE.read_text().splitlines() if x.strip()]
    sample = {json.loads(x)["claim_id"]: json.loads(x)
              for x in SAMPLE_FILE.read_text().splitlines() if x.strip()}

    by_type: dict[str, list[dict]] = defaultdict(list)
    rejects: list[dict] = []
    adversarial: dict[str, list[dict]] = defaultdict(list)
    for s in scored:
        src = sample.get(s["claim_id"])
        if not src:
            continue
        stratum = src.get("stratum") or ("core" if src["verdict"] == "incident" else "reject")
        if stratum.startswith("adv:"):
            adversarial[stratum[4:]].append(s)
        elif src["verdict"] == "incident":
            by_type[src["incident_type"]].append(s)
        else:
            rejects.append(s)

    def rate(items, key):
        vals = [i[key] for i in items if i.get(key) is not None]
        return (sum(1 for v in vals if v), len(vals))

    per_type = {}
    for t, items in sorted(by_type.items()):
        inc_k, inc_n = rate(items, "is_incident")
        # type/place/west_bank are only meaningful where it IS an incident
        real = [i for i in items if i.get("is_incident")]
        typ_k, typ_n = rate(real, "type_ok")
        plc_k, plc_n = rate(real, "place_ok")
        wb_k, wb_n = rate(real, "west_bank")
        # "correct" = a served row that is right in every respect that applies
        good = sum(1 for i in items if i.get("is_incident") and i.get("type_ok")
                   and i.get("place_ok") and i.get("west_bank"))
        lo, hi = _wilson(good, len(items))
        per_type[t] = {
            "n": len(items), "precision": round(good / len(items), 3),
            "ci95": [round(lo, 3), round(hi, 3)],
            "is_incident": f"{inc_k}/{inc_n}", "type_ok": f"{typ_k}/{typ_n}",
            "place_ok": f"{plc_k}/{plc_n}", "west_bank": f"{wb_k}/{wb_n}",
        }

    all_items = [i for v in by_type.values() for i in v]
    good_all = sum(1 for i in all_items if i.get("is_incident") and i.get("type_ok")
                   and i.get("place_ok") and i.get("west_bank"))
    lo, hi = _wilson(good_all, len(all_items))

    missed = sum(1 for r in rejects if r.get("is_incident"))

    def block(items):
        good = sum(1 for i in items if i.get("is_incident") and i.get("type_ok")
                   and i.get("place_ok") and i.get("west_bank"))
        l, h = _wilson(good, len(items))
        return {"n": len(items), "precision": round(good / max(len(items), 1), 3),
                "ci95": [round(l, 3), round(h, 3)],
                "not_incident": sum(1 for i in items if not i.get("is_incident")),
                "wrong_type": sum(1 for i in items if i.get("is_incident") and not i.get("type_ok")),
                "wrong_place": sum(1 for i in items if i.get("is_incident") and not i.get("place_ok"))}

    adv_items = [i for v in adversarial.values() for i in v]

    # THE VERSION MEASURED IS THE VERSION THAT PRODUCED THE ROWS (audit
    # F212/F239, 2026-09-25). It was stamped from the code imported at SCORING
    # time: round 8 was scored at 19:00 and 1.8.1 landed at 19:12 — a human
    # twelve minutes slower and round 8 would have said "measured 1.8.1",
    # serve/quality.py would have dropped its "1.8.1 is unmeasured" note, and
    # measure_review would never have called the next round due. Every served
    # row in the sample carries the version that classified it; that is the
    # version this round measured. More than one is refused, not averaged.
    versions: dict[str, int] = {}
    for srow in scored:
        src = sample.get(srow["claim_id"])
        if src and src.get("verdict") == "incident":
            v = src.get("classifier_version")
            versions[v or "unrecorded"] = versions.get(v or "unrecorded", 0) + 1
    if len(versions) > 1 and not allow_mixed:
        raise SystemExit(f"refusing: the scored rows were classified by more than one "
                         f"version {versions} — a single precision cannot belong to all "
                         f"of them (pass --allow-mixed to score it as 'mixed')")
    measured = (next(iter(versions)) if len(versions) == 1 else
                "mixed" if versions else None)
    if measured == "unrecorded":
        measured = None
    try:
        from ingest.sources.news_incidents import CLASSIFIER_VERSION as _code
    except Exception:                                           # noqa: BLE001
        _code = None

    result = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "round": ROUND,
        "classifier_version": measured,
        "classifier_versions_in_sample": versions,
        "scoring_process_version": _code,
        "overall": {"n": len(all_items),
                    "precision": round(good_all / max(len(all_items), 1), 3),
                    "ci95": [round(lo, 3), round(hi, 3)],
                    # audit F237: what the pooled number IS.
                    "basis": ("stratum mean: every type capped at the same number "
                              "of rows and pooled, so each type weighs about the same "
                              "whatever its share of the stream"),
                    "served_weighted": _served_weighted(by_type, sample)},
        "per_type": per_type,
        "rejects": {"n": len(rejects), "were_really_incidents": missed,
                    "miss_rate": round(missed / max(len(rejects), 1), 3)},
    }
    if adv_items:
        result["adversarial"] = {"all": block(adv_items),
                                 "by_stratum": {k: block(v) for k, v in sorted(adversarial.items())}}
        result["all_served"] = block(all_items + adv_items)
    failing = [t for t, v in per_type.items()
               if v["n"] >= MIN_N_TO_GATE and v["precision"] < GATE_PER_TYPE]
    unmeasured = [t for t, v in per_type.items() if v["n"] < MIN_N_TO_GATE]
    result["gate"] = {
        "overall_required": GATE_OVERALL,
        "per_type_required": GATE_PER_TYPE,
        "min_n_to_gate": MIN_N_TO_GATE,
        "overall_pass": result["overall"]["precision"] >= GATE_OVERALL,
        "types_below_floor": failing,
        "types_unmeasured": unmeasured,
        "pass": result["overall"]["precision"] >= GATE_OVERALL and not failing,
    }
    RESULT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    # ONLY THE NEWEST ROUND REACHES SERVING (audit F240/F247). The serving file
    # and the rounds ledger were written for whatever round was scored, so
    # `--score --round 7` — to regenerate its JSON after a scorer edit — put
    # round 7's 0.717 in every incident answer while round 8 existed, and its
    # fresh `scored_at` told measure_review a round had just been scored.
    serving = ROOT / "ops" / "incident-precision.json"
    if promote is None:
        promote = _is_newest_round(ROUND, serving)
    result["promoted_to_serving"] = bool(promote)
    if not promote:
        print(f"round {ROUND} is not the newest round on disk: wrote {RESULT_FILE.name} "
              f"only; serving ({serving.name}) and the rounds ledger were not touched "
              f"(pass --promote to override)")
        return result
    if RESULT_FILE != serving:
        serving.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    # Append the round to a machine-readable history. RESULT_FILE holds only
    # the LATEST round, and the scored files hold claim verdicts with no
    # timestamp or classifier version — so "when was precision last measured,
    # and of WHICH classifier" was answerable only by a human reconstructing
    # it from file names. The weekly review (ops/measure_review.py) reads this
    # ledger to raise the round-is-due alarm.
    with (ROOT / "ops" / "incident-rounds.ndjson").open("a") as fh:
        fh.write(json.dumps({
            "scored_at": result["measured_at"],
            "round": ROUND,
            "classifier_version": measured,
            "overall": {k: result["overall"][k] for k in ("n", "precision", "ci95")},
            "gate_pass": result["gate"]["pass"],
            "types_unmeasured": result["gate"]["types_unmeasured"],
        }, ensure_ascii=False) + "\n")
    return result


def _round_no(r) -> int | None:
    try:
        return int(r)
    except (TypeError, ValueError):
        return None


def _is_newest_round(r: str | None, serving: Path) -> bool:
    """True when round `r` is at least as new as every round on disk and as the
    round the serving file already holds. An unnumbered round (the legacy
    files) writes the serving file itself, as it always did."""
    n = _round_no(r)
    if n is None:
        return True
    on_disk = [int(m.group(1)) for f in (ROOT / "ops").glob("incident-s*-round*.ndjson")
               if (m := re.search(r"-round(\d+)\.ndjson$", f.name))]
    try:
        served = _round_no(json.loads(serving.read_text()).get("round"))
    except Exception:                                           # noqa: BLE001
        served = None
    return all(n >= x for x in on_disk + ([served] if served is not None else []))


def _served_weighted(by_type: dict[str, list[dict]], sample: dict) -> dict | None:
    """Per-type precision weighted by each type's share of the pool the sample
    was drawn from (`type_population`, recorded by the draw since audit F237),
    with a normal-approximation interval (delta method over the strata). None
    for rounds drawn before the population was recorded — never a guess."""
    pops, stats = {}, {}
    for t, items in by_type.items():
        p_ = {sample[i["claim_id"]].get("type_population") for i in items
              if i["claim_id"] in sample}
        if len(p_) != 1 or None in p_:
            return None
        pops[t] = int(next(iter(p_)))
        good = sum(1 for i in items if i.get("is_incident") and i.get("type_ok")
                   and i.get("place_ok") and i.get("west_bank"))
        stats[t] = (good, len(items))
    total = sum(pops.values())
    if not total:
        return None
    est = var = 0.0
    for t, (good, n) in stats.items():
        w, p_ = pops[t] / total, good / n
        est += w * p_
        var += w * w * p_ * (1 - p_) / n
    half = 1.96 * sqrt(var)
    return {"precision": round(est, 3),
            "ci95": [round(max(0.0, est - half), 3), round(min(1.0, est + half), 3)],
            "population": pops,
            "basis": "per-type precision weighted by each type's share of the pool drawn from"}


def show(r: dict) -> None:
    o = r["overall"]
    print(f"incident classifier precision  {o['precision']:.3f} "
          f"[{o['ci95'][0]:.2f}–{o['ci95'][1]:.2f}]  n={o['n']}"
          f"  (classifier {r.get('classifier_version')}; stratum mean)")
    sw = o.get("served_weighted")
    if sw:
        print(f"  weighted by the served mix     {sw['precision']:.3f} "
              f"[{sw['ci95'][0]:.2f}–{sw['ci95'][1]:.2f}]")
    print()
    print(f"  {'type':<16}{'n':>4}{'prec':>7}  {'95% CI':<14}"
          f"{'incident':>10}{'type':>8}{'place':>8}{'WB':>8}")
    for t, v in sorted(r["per_type"].items(), key=lambda x: x[1]["precision"]):
        flag = ("  <-- n too small to mean anything" if v["n"] < MIN_N_TO_GATE
                else "  <-- BELOW FLOOR" if v["precision"] < GATE_PER_TYPE else "")
        print(f"  {t:<16}{v['n']:>4}{v['precision']:>7.3f}  "
              f"{v['ci95'][0]:.2f}-{v['ci95'][1]:.2f}      "
              f"{v['is_incident']:>10}{v['type_ok']:>8}"
              f"{v['place_ok']:>8}{v['west_bank']:>8}{flag}")
    rj = r["rejects"]
    print(f"\n  rejects sampled {rj['n']}: {rj['were_really_incidents']} were real "
          f"incidents (miss rate {rj['miss_rate']:.1%})")
    if r.get("adversarial"):
        a = r["adversarial"]["all"]
        print(f"\n  adversarial {a['n']}: precision {a['precision']:.3f} "
              f"[{a['ci95'][0]:.2f}–{a['ci95'][1]:.2f}]  not_incident {a['not_incident']} "
              f"wrong_type {a['wrong_type']} wrong_place {a['wrong_place']}")
        for k, v in r["adversarial"]["by_stratum"].items():
            print(f"    {k:<10}{v['n']:>4}{v['precision']:>7.3f}  not_incident {v['not_incident']} "
                  f"wrong_type {v['wrong_type']} wrong_place {v['wrong_place']}")
        s_ = r["all_served"]
        print(f"  all served rows {s_['n']}: precision {s_['precision']:.3f} "
              f"[{s_['ci95'][0]:.2f}–{s_['ci95'][1]:.2f}]")
    g = r["gate"]
    print(f"\n  GATE {'PASS' if g['pass'] else 'FAIL'} "
          f"(need >={g['overall_required']} overall, "
          f">={g['per_type_required']} per type)")
    if g["types_below_floor"]:
        print(f"  below floor: {', '.join(g['types_below_floor'])}")
    if g.get("types_unmeasured"):
        print(f"  UNMEASURED (n < {g['min_n_to_gate']}): "
              f"{', '.join(g['types_unmeasured'])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--round", help="round number: files become incident-*-roundN.*")
    ap.add_argument("--per-type-cap", type=int, default=PER_TYPE_CAP)
    ap.add_argument("--adversarial", type=int, default=0,
                    help="served incidents drawn from the trap strata, scored apart")
    ap.add_argument("--rejects", type=int, default=REJECT_SAMPLE)
    ap.add_argument("--promote", action="store_true",
                    help="with --score: write the serving file and the rounds ledger "
                         "even when this is not the newest round on disk")
    ap.add_argument("--allow-mixed", action="store_true",
                    help="with --score: score a sample classified by more than one "
                         "version, stamped 'mixed'")
    a = ap.parse_args()
    use_round(a.round)
    if a.sample:
        n = draw_sample(a.per_type_cap, a.adversarial, a.rejects)
        print(f"{n} claims written to {SAMPLE_FILE}")
        print(f"score them into {SCORED_FILE} as one JSON object per line:")
        print('  {"claim_id":123,"is_incident":true,"type_ok":true,'
              '"place_ok":true,"west_bank":true,"note":"optional"}')
        return 0
    if a.show:
        show(json.loads(RESULT_FILE.read_text()))
        return 0
    if a.score:
        r = score(promote=True if a.promote else None, allow_mixed=a.allow_mixed)
        show(r)
        return 0 if r["gate"]["pass"] else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
