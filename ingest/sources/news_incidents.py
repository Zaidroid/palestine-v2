"""Turn news claims into located, corroborated incidents.

    .venv/bin/python -m ingest.sources.news_incidents --dry-run
    .venv/bin/python -m ingest.sources.news_incidents

Reads claims the agent2 poller has stored as `unclassified`, classifies them
with cascade.news, resolves the place against the gazetteer, and groups
near-duplicate reports into `event` rows — the belief layer, which has been
empty since it was built.

THE GAZETTEER IS THE VALIDATOR
Text extraction produces a candidate name; whether that name is a real place is
decided by looking it up, not by more regex. Two junk extractions survived every
pattern fix — "يمنع الطالب" ("prevents the student", pulled out of a sentence
about ALL villages) and "جنيد والقري المحيطه" ("Junaid and the surrounding
villages") — and both disappear the moment resolution is required, along with
whatever else the next parser bug invents. Chasing them individually would have
been an endless series of special cases.

DEDUPLICATION IS THE POINT
Eight channels covering eight governorates report the same raid within minutes.
Stored as eight events that is eight raids; grouped by (type, place, window) it
is one raid corroborated by several channels — and the count is meaningful only
after copy-collapse, so `independent_sources` counts independence GROUPS, the
same rule as checkpoints.

WHY INCIDENTS ARE NOT STATE
A raid happened; it does not decay into "no raid". Events carry occurred_at and
recede into history rather than expiring. Closures are different — "the road is
closed" is a claim about now — so those additionally write a `road_closure`
observation and decay like any other reading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dataclasses import dataclass, field

from cascade.news import NewsReading, read
from resolve.db import connect
from resolve.arabic import fold_for_match
from resolve.geo import governorate_pcode, resolve_place

# Reports of the same kind, at the same place, inside this window are one event.
DEDUP_WINDOW = timedelta(minutes=90)
STATE_KIND_CLOSURE = "road_closure"

# Bump when the lexicon or the rules change, so two runs over the same corpus
# are distinguishable and a shift in yield can be blamed on the right thing.
CLASSIFIER = "news"
# 1.1 — P1.1 measurement. Hand-scoring 163 classifications put the classifier at
# 0.732 overall, with demolition 0.353 and closure 0.500 under the 0.60 floor.
# Fixes: settler actions no longer recorded as army raids (tense-prefix bug in
# the settler stem), nominal casualty reports read as deaths, casualty outranks
# the action that caused it, and road-status bulletins / demolition notices /
# release follow-ups / period statistics stop being served as incidents.
# 1.2 — two further defects, both found by the HELD-OUT round rather than the
# tuning round, which is the argument for keeping the rounds disjoint:
#   * "رأي" normalises to "راي", a substring of "اسراييلي" (Israeli). 142 claims
#     were rejected as commentary for containing the word "Israeli".
#   * the verbal noun استشهاد does not contain the stem استشهد, so a man who
#     died of his wounds was filed as an injury.
# Held-out precision 0.864 [0.77-0.92] on n=81 measured against 1.1; the only
# sampled item either fix changed was the one death, taking it to 0.877.
# 1.3 — P1.1 round 3 measured the five never-measured types and `closure` came
# back at 0.167, one correct in six. FOUR of the six failures were a single
# unanchored stem: `سكر` inside `عسكري` (military) and `السكري` (diabetes).
#   "حاجز عورتا العسكري", "قرار عسكري", "نقطة عسكرية", and a health-ministry
#   note on labour induction, all served as road closures.
# The same shape as 1.2's "راي" inside "اسراييلي" — in Arabic a short stem is
# almost always inside a longer real word — so the third occurrence became a
# rule rather than another patch: short stems carry \b.
# Also: the status-bulletin reject required a bare `محطات` and the fuel channel
# writes `المحطات`, so "جميع محطات المدينة مغلقة" was served as a closure in
# Qalqilya. The article is optional now.
# Measured over the whole corpus: closure 420 -> 25, every other type within +4.
# 1.4 — a fresh held-out draw on the 1.3 output found three MORE ways for a
# correct verb to describe the wrong thing, so `closure` stopped being a
# wordlist and became a rule: a closing verb AND something a person could be
# stopped by, inside one clause.
#   * `سكر` anchored still matches صادق سكر, a man's SURNAME, and سُكّر, sugar.
#     The bare stem is gone; a news wire writes أغلق, not سكر.
#   * "اغلق المحافظ الهاتف" — the governor HUNG UP THE PHONE. No wordlist fixes
#     that one; only requiring a road, gate, checkpoint or area does.
#   * `ال?` in the status-bulletin reject means "alef then optional lam", not
#     "optional article", so "احوال طرق اريحا ومحيطها" never matched and a
#     bulletin listing eight OPEN checkpoints was served as a closure.
# 10/10 on every hand-checked case from rounds 3 and 4; corpus-wide closure
# 420 -> 18 with every other type within +4.
#
# NOT MEASURED YET. Round 4's closures were spent diagnosing these three, which
# makes them tuning data — the same reason round 1 was never reused. `closure`
# has no held-out precision at 1.4 and must not be quoted one until round 5.
#
# 1.5 (#37) — geography, not vocabulary:
#   * governorates are matched token-wise: نابلس no longer matches inside
#     النابلسي, which filed a 118-death Gaza massacre under Nablus.
#   * the Gaza reject knows the LANDMARKS Gaza coverage actually uses (شارع
#     الرشيد, مجمع الشفاء, دوار النابلسي...), not just town names.
#   * "الشاب فلان من قرية X" is a residence, not the incident site.
#   * حاجز/مفرق/دوار/معبر are place words — an arrest at مفرق فصايل now sites
#     at the junction instead of the arrested man's home village.
# Incident-type patterns are untouched, so round-2/3 measurements still
# describe them; the closure caveat above is unchanged.
#
# 1.6 — round 5 (n=163, disjoint, at 1.5) measured 0.748 overall and the
# failure was almost one class: month-end STATISTICS bulletins, which took
# `death` to 0/7 because the statistical reject knew no month names. Also:
# regional-roundup and court-news rejects; aftermath extended (خارج السجن,
# قبل اشهر, تركيب مشاهد); four missing settler stems (شعال the maṣdar, ضرم,
# دشن, ستول); army beatings as injury; censorship dots (مسـ.ـتوطن) stripped
# in normalize(). Round 5's 163 claims are tuning data now — 1.6 has NO
# held-out precision until round 6. Closure at 1.5 measured 0.875 (was
# 0.167 in round 3); the rewrite held on disjoint data.
CLASSIFIER_VERSION = "1.8.0"

# Confidence for an event, by how many INDEPENDENT groups reported it. Noisy-OR
# on the same 0.70 single-source trust used for checkpoint state, so the two
# layers are comparable.
SINGLE_SOURCE_TRUST = 0.70
MAX_CONFIDENCE = 0.97


def cluster_by_window(members: list[tuple], window: timedelta) -> list[list[tuple]]:
    """Group one (type, place)'s reports into events.

    CHAINS ON THE NEIGHBOUR, NOT ON THE FIRST MEMBER OF THE CLUSTER. The original
    compared every report against `cluster[0][1]`, so a cluster's boundary
    depended on when its EARLIEST report happened to arrive: a steady stream at
    T, T+60m, T+120m split into two events at a 90-minute window, while the same
    stream starting an hour later stayed whole. Deduplication whose result turns
    on arrival luck is not a rule.

    The trade-off is deliberate and worth stating: chaining can merge a long
    stream into one event, so two genuinely separate incidents 3 hours apart with
    a trickle of reports between them become one. For an incident feed that is
    the right error to make — the alternative understates corroboration on
    exactly the events that are most reported, which is the wrong way to be
    wrong.
    """
    out: list[list[tuple]] = []
    cur: list[tuple] = []
    prev_ts = None
    for m in sorted(members, key=lambda x: x[1]):
        if cur and prev_ts is not None and m[1] - prev_ts > window:
            out.append(cur)
            cur = []
        cur.append(m)
        prev_ts = m[1]
    if cur:
        out.append(cur)
    return out


def _stable_key(itype: str, place_id: int, name_key: str | None, first_claim_id: int) -> str:
    raw = f"{CLASSIFIER}|{itype}|{place_id}|{name_key or ''}|{first_claim_id}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _fuller_form(conn, name: str, governorate: str) -> tuple:
    """(resolution-like, candidate ids) for a short name inside a longer alias.

    Whole-word containment only (`بيت عور` inside `بيت عور التحتا`, never a
    fragment), restricted to the governorate the message named, stations and
    governorate rows excluded, four characters or more. Exactly one distinct
    place is an answer; two or more are recorded so the event can say it is
    ambiguous instead of pinning the wrong twin.

    The governorate's code comes from the GOVERNORATE row. Resolving the name
    gives the city, and until migration 077 the city carried a code no village
    shared — this lookup matched nothing from the day it landed (2026-09-24).
    """
    from types import SimpleNamespace
    key = fold_for_match(name)
    if not key or len(key) < 4:
        return None, []
    with conn.cursor() as cur:
        pcode = governorate_pcode(cur, governorate)
        if not pcode:
            return None, []
        keys = [key]
        if key.endswith("ا"):
            keys.append(key[:-1] + "ه")
        elif key.endswith("ه"):
            keys.append(key[:-1] + "ا")
        pats: list[str] = []
        for k in keys:
            pats += [k + " %", "% " + k, "% " + k + " %"]
        cur.execute("""
            SELECT DISTINCT p.place_id, p.name_ar
              FROM place_alias a
              JOIN place p0 ON p0.place_id = a.place_id
              JOIN place p  ON p.place_id = COALESCE(p0.merged_into, p0.place_id)
             WHERE p.servable AND p.admin2_pcode = %s
               AND p.kind::text NOT IN ('station', 'governorate', 'region')
               AND a.alias_norm LIKE ANY(%s)
             LIMIT 6""", (pcode, pats))
        rows = cur.fetchall()
    ids = sorted({r[0] for r in rows})
    if len(ids) == 1:
        return SimpleNamespace(place_id=ids[0], name_ar=rows[0][1], method="fuller",
                               kind="locality", admin2_pcode=pcode), ids
    return None, ids


# How a candidate may be resolved, by how it was read. A settlement-word
# capture is the text's own statement of a place and may use every branch;
# a token that merely sits before "جنوب نابلس" or after "أبو" must match an
# alias exactly or as a whole contained word — never a fuzzy neighbour.
FUZZY_HOW = frozenset(["place_word", "station_word", "dual"])
CONTAIN_HOW = frozenset(["place_word", "station_word", "dual", "bearing"])
FULLER_HOW = frozenset(["place_word", "dual", "bearing", "cue"])


@dataclass
class Located:
    place_id: int | None
    precision: str | None            # named | village_ambiguous | governorate
    named_place: str | None          # the candidate that answered, else the first
    candidates: list[int] = field(default_factory=list)   # ambiguous twins
    how: str | None = None
    method: str | None = None
    rejected: list[tuple[str, str]] = field(default_factory=list)


NEAR_GOVERNORATE_M = 3000


def _near_governorate(conn, place_id: int, pcode: str) -> bool:
    """A place on the wrong side of a governorate line, by a little.

    The channels name the governorate a village belongs to administratively;
    the polygons put بيت فجار's centroid in Hebron and قلنديا's in Jerusalem,
    and بدّو sits on the Ramallah line. Within 3 km of the stated governorate
    the text and the map agree closely enough to keep the village.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ST_DWithin(p.centroid::geography, g.geom::geography, %s)
              FROM place p, place g
             WHERE p.place_id = %s AND g.kind::text = 'governorate' AND g.servable
               AND g.admin2_pcode = %s""", (NEAR_GOVERNORATE_M, place_id, pcode))
        row = cur.fetchone()
    return bool(row and row[0])


def locate(conn, r: NewsReading, stats: Counter | None = None) -> Located:
    """The place an incident reading names, or the governorate, honestly.

    Every candidate the reader offered is tried in order of trust. A
    resolution is refused when it lands OUTSIDE the governorate the message
    named: the gazetteer holds one المغير (Jenin's) and the channels write about
    Ramallah's, and 223 Ramallah events were pinned 50 km away on 2026-09-24
    for want of this check. A refused twin falls through to the fuller-form
    lookup inside the stated governorate, and then to the governorate itself
    with `place_precision = governorate` — never to the wrong village.
    """
    stats = stats if stats is not None else Counter()
    with conn.cursor() as cur:
        gov_code = governorate_pcode(cur, r.governorate) if r.governorate else None
    twins: list[int] = []
    rejected: list[tuple[str, str]] = []
    gov_norm = fold_for_match(r.governorate) if r.governorate else None
    for idx, (name, how) in enumerate(r.place_candidates):
        if gov_norm and fold_for_match(name) == gov_norm:
            # The governorate's own name. "اقتحام مدينة نابلس" names the city
            # and that is the place; but "قرية برقا شرق مدينة رام الله", once
            # برقا fails to resolve, must not fall through to a NAMED pin on
            # Ramallah's centre — the village was named, the city was not.
            if how != "place_word" or idx > 0:
                continue
        # A village and a checkpoint often share a name (حوارة, الجلزون,
        # عطارة). An incident happens in the village unless the text said
        # حاجز/معبر/مفرق, in which case the checkpoint row is the place.
        ctx = {"admin": r.governorate,
               "prefer_kind": "checkpoint" if how == "station_word" else "locality"}
        res = resolve_place(name, ctx, conn=conn, learn=False,
                            fuzzy=how in FUZZY_HOW, contain=how in CONTAIN_HOW)
        if res and res.kind == "station":
            # A fuel station is where fuel is sold, not where a raid happens.
            rejected.append((name, "station"))
            res = None
        if (res and gov_code and res.admin2_pcode and res.admin2_pcode != gov_code
                and res.kind not in ("governorate", "region")
                and not _near_governorate(conn, res.place_id, gov_code)):
            rejected.append((name, "outside stated governorate"))
            stats["rejected_outside_governorate"] += 1
            res = None
        if not res and r.governorate and how in FULLER_HOW:
            res, cands = _fuller_form(conn, name, r.governorate)
            if cands and not res and not twins:
                twins = cands
        if res and res.kind in ("governorate", "region"):
            # "مدينة جنين" resolves to the governorate polygon because Jenin
            # city has no Arabic row of its own: that is a governorate pin,
            # and must be served as one.
            return Located(res.place_id, "governorate", name, [], how,
                           getattr(res, "method", "exact"), rejected)
        if res:
            stats[f"located_named_{how}"] += 1
            return Located(res.place_id, "named", name, [], how,
                           getattr(res, "method", "fuller"), rejected)
    first = r.place_candidates[0][0] if r.place_candidates else None
    if r.governorate:
        res = resolve_place(r.governorate, conn=conn, learn=False)
        if res:
            return Located(res.place_id, "village_ambiguous" if twins else "governorate",
                           first, twins, None, None, rejected)
    return Located(None, None, first, twins, None, None, rejected)


def _confidence(groups: int) -> float:
    return round(min(MAX_CONFIDENCE, 1 - (1 - SINGLE_SOURCE_TRUST) ** max(groups, 1)), 4)


# Drop only what THIS classifier produced, so a re-run after a rule change
# replaces its own output and leaves every other layer untouched. The claims
# themselves are never deleted — only our reading of them. Ordered so nothing
# is orphaned: observations, then the claim back-references, then the events
# they pointed at, then the ledger that names them.
# Events carry their producing classifier in attrs, so they can be identified
# without the ledger — which has to be deleted BEFORE them (claim_classification
# has a foreign key onto event) and would otherwise take the only record of
# which events were ours with it.
REBUILD_STEPS = [
    ("DELETE FROM state_observation "
     "WHERE state_kind = %(closure)s AND attrs ? 'from_event'"),
    ("UPDATE claim SET event_id = NULL WHERE event_id IN "
     "(SELECT event_id FROM event WHERE attrs->>'classifier' = %(clf)s)"),
    ("DELETE FROM state_current WHERE state_kind = %(closure)s"),
    ("DELETE FROM claim_classification WHERE classifier = %(clf)s"),
    # NOT deleted: reset. Re-clustering then joins each event by its stable
    # key and the id survives the rebuild; whatever the new clustering no
    # longer produces is left with claim_count 0 and no claim pointing at it,
    # and the orphan sweep at the end of classify() removes it.
    ("UPDATE event SET claim_count = 0, independent_sources = 0, "
     "attrs = attrs - 'channels' WHERE attrs->>'classifier' = %(clf)s "
     "AND status = 'believed'"),
]

REFRESH_CLOSURE_SQL = """
-- Scoped to road_closure. A rebuild that touched every kind is exactly how the
-- fuel loader silently overwrote checkpoint belief; feeds sharing this table
-- write only their own rows.
INSERT INTO state_current
  (place_id, state_kind, direction, value, observed_at, source_id,
   base_confidence, independent_sources, contradicted_by, updated_at)
SELECT DISTINCT ON (place_id, state_kind)
       place_id, state_kind, 'both', value, observed_at, source_id,
       confidence, 1, 0, now()
FROM state_observation
WHERE state_kind = %(closure)s
ORDER BY place_id, state_kind, observed_at DESC
ON CONFLICT (place_id, state_kind, direction) DO UPDATE SET
  value=EXCLUDED.value, observed_at=EXCLUDED.observed_at,
  source_id=EXCLUDED.source_id, base_confidence=EXCLUDED.base_confidence,
  updated_at=now()
WHERE EXCLUDED.observed_at >= state_current.observed_at
"""


LOCK_KEY = 7870_0001          # pg advisory lock: one classifier run at a time


def classify(limit: int | None, dry_run: bool, rebuild: bool = False) -> dict:
    stats = Counter()
    with connect() as conn, conn.cursor() as cur:
        # ONE RUN AT A TIME. A version bump re-reads the whole corpus, which
        # outlives the five-minute timer; a second run reading the same claims
        # would mint the same events and fail on the stable-key index, or
        # double-count what the first is about to write. The lock is held by
        # this session and released with it.
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        if not cur.fetchone()[0]:
            stats["locked"] = 1
            stats["read"] = 0
            return stats
        if rebuild and not dry_run:
            for step in REBUILD_STEPS:
                cur.execute(step, {"clf": CLASSIFIER, "closure": STATE_KIND_CLOSURE})
            stats["rebuilt"] = 1
        # Incremental on claim_classification, NOT on claim.claim_type.
        #
        # The obvious filter — claim_type = 'unclassified' — is wrong precisely
        # BECAUSE this cascade respects claim immutability and never stamps the
        # verdict back onto the claim. Every claim therefore stays
        # 'unclassified' forever, so that filter re-processed the entire corpus
        # on every run and created a fresh duplicate event each time. One timer
        # firing turned 151 events into 216.
        sql = """
            SELECT c.claim_id, c.raw_text, c.reported_at, c.source_id,
                   COALESCE(s.independence_group, 'src:' || s.source_id::text) AS unit
            FROM claim c
            JOIN source s USING (source_id)
            WHERE c.raw_text IS NOT NULL
              -- NEWS SOURCES ONLY (migration 037). Adding the palhub fuel
              -- channel to the poller fed 11,730 machine-generated station
              -- bulletins into this classifier and produced 390 "incidents" —
              -- more than the busiest real news channel in the system. The
              -- classifier read what it was given correctly; it was given fuel
              -- data, in which مغلقة means a petrol station is shut.
              AND s.feeds_incidents
              AND NOT EXISTS (
                    SELECT 1 FROM claim_classification cc
                    WHERE cc.claim_id = c.claim_id
                      AND cc.classifier = %(clf)s
                      AND cc.classifier_version = %(ver)s)
            ORDER BY c.reported_at
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql, {"clf": CLASSIFIER, "ver": CLASSIFIER_VERSION})
        claims = cur.fetchall()
        stats["read"] = len(claims)

        # (incident_type, place_id) -> [(claim_id, reported_at, unit, source_id)]
        groups: dict[tuple[str, int], list[tuple]] = {}
        unresolved = Counter()
        # Every verdict is recorded, rejections included — see migration 017.
        verdicts: list[tuple] = []

        for claim_id, text, reported_at, source_id, unit in claims:
            r = read(text)
            stats[f"verdict_{r.verdict}"] += 1
            if r.verdict != "incident":
                verdicts.append((claim_id, r.verdict, None, r.reject_reason,
                                 None, r.place_text, r.governorate, 0.0))
                continue

            # The gazetteer decides whether the extracted string is a place.
            #
            # THE NAMED PLACE IS THE PLACE, AND A GOVERNORATE IS NOT A SUBSTITUTE
            # FOR IT. The fallback used to silently replace an unresolvable
            # village with its governorate, which is how "land being bulldozed in
            # المزرعة الغربية" was served as *a demolition in Ramallah, pinned to
            # the city centre*. The village was named in the message — the text
            # is where the place lives — and the fallback threw that name away.
            #
            # So the fallback still LOCATES the incident loosely (admin2 is the
            # honest precision for "somewhere in this governorate") but never
            # pretends the governorate IS the place: the resolved place, the
            # named place as written, and which of the two answered all travel
            # with the event. `locate` holds the whole chain — every candidate
            # the reader offered, the governorate check, the fuller form.
            loc = locate(conn, r, stats)
            res = loc
            named_place = loc.named_place
            candidates = loc.candidates
            place_precision = loc.precision
            if loc.place_id is None:
                stats["unresolved_place"] += 1
                unresolved[(r.place_text or r.governorate or "?")[:28]] += 1
                verdicts.append((claim_id, "unclear", r.incident_type,
                                 "place did not resolve", None,
                                 r.place_text, r.governorate, 0.0))
                continue

            stats["located"] += 1
            if place_precision == "governorate":
                stats["located_gov_fallback"] = \
                    stats.get("located_gov_fallback", 0) + 1
            verdicts.append((claim_id, "incident", r.incident_type, None,
                             res.place_id, named_place, r.governorate, r.confidence))
            # Group on the place the report actually named when we have it: two
            # channels naming المزرعة الغربية are reporting the same village even
            # if the gazetteer made them land on different rows, and a name is
            # what a channel writes. Falls back to the resolved id so nothing
            # stops grouping.
            name_key = fold_for_match(named_place) if named_place else None
            groups.setdefault((r.incident_type, res.place_id, name_key), []).append(
                (claim_id, reported_at, unit, source_id, r, place_precision, candidates))

        # Split each group into time-windowed clusters; each cluster is an event.
        events = []
        for (itype, place_id, name_key), members in groups.items():
            for cluster in cluster_by_window(members, DEDUP_WINDOW):
                events.append((itype, place_id, name_key, cluster))

        stats["events"] = len(events)
        stats["claims_grouped"] = sum(len(c) for *_, c in events)
        stats["corroborated"] = sum(
            1 for *_, c in events if len({m[2] for m in c}) > 1)

        if dry_run:
            stats["unresolved_sample"] = unresolved.most_common(8)
            return stats

        event_by_claim: dict[int, int] = {}
        for itype, place_id, name_key, cluster in events:
            units = {m[2] for m in cluster}
            occurred = cluster[0][1]
            conf = _confidence(len(units))
            reading = cluster[0][4]
            # A STABLE IDENTITY. Event ids used to be re-minted on every
            # --rebuild (79,779-84,453 on 2026-09-24 alone), so nothing outside
            # could reference an event. The key is the grouping key plus the
            # EARLIEST claim, which never changes; an hour bucket would flip
            # when a report lands either side of the boundary.
            stable_key = _stable_key(itype, place_id, name_key, min(m[0] for m in cluster))

            # JOIN THE EVENT THAT ALREADY EXISTS, rather than minting a new one.
            # This loop used to be reached with only the claims THIS RUN picked
            # up, and it never looked at what previous runs had already written —
            # so five channels reporting one raid over 95 minutes became five
            # events, each with claim_count=1 and confidence 0.7, when the truth
            # was one event backed by four independent channels. Measured on
            # حبلة 2026-09-23: five events (65803/65806/65819/65820/65821), all
            # on place 610, all `raid`, 20:48→22:23 — split by ingest cycle, not
            # by time or place. A window that only sees one batch is not a window.
            #
            # The window is applied to the SERVER's clock (occurred_at of the
            # existing event) so a late-arriving report joins the event it
            # belongs to, and only events this classifier produced are eligible.
            cur.execute("""
                SELECT event_id, claim_count, independent_sources, occurred_at,
                       attrs->'channels' AS channels
                  FROM event
                 WHERE attrs->>'stable_key' = %s
                 LIMIT 1""", (stable_key,))
            prior = cur.fetchone()
            if not prior:
                # Keyed on the NAMED place too: 43 governorate-level events were
                # merging reports about different villages (validation,
                # 2026-09-24), because the window only knew type + resolved row.
                cur.execute("""
                    SELECT event_id, claim_count, independent_sources, occurred_at,
                           attrs->'channels' AS channels
                      FROM event
                     WHERE event_type = %s AND place_id = %s
                       AND status = 'believed'
                       AND attrs->>'classifier' = %s
                       AND COALESCE(attrs->>'name_key', '') = %s
                       AND ABS(EXTRACT(EPOCH FROM (occurred_at - %s::timestamptz)))
                           <= %s
                     ORDER BY occurred_at
                     LIMIT 1""",
                    (itype, place_id, CLASSIFIER, name_key or "", occurred,
                     DEDUP_WINDOW.total_seconds()))
                prior = cur.fetchone()

            if prior:
                event_id, prev_n, _prev_srcs, _prev_at, prev_ch = prior
                merged_units = set(prev_ch or []) | units
                # The event KEEPS its earliest report time: that is when the
                # incident was first reported, and moving it forward would let a
                # late report make an old incident look new.
                cur.execute("""
                    UPDATE event
                       SET claim_count = %s, independent_sources = %s,
                           confidence = %s,
                           attrs = attrs || %s::jsonb
                     WHERE event_id = %s""",
                    (prev_n + len(cluster), len(merged_units),
                     _confidence(len(merged_units)),
                     json.dumps({"channels": sorted(merged_units),
                                 "merged_reports": (prev_n + len(cluster)),
                                 "stable_key": stable_key,
                                 "name_key": name_key or ""},
                                ensure_ascii=False),
                     event_id))
                stats["events_joined"] = stats.get("events_joined", 0) + 1
            else:
                cur.execute("""
                    INSERT INTO event (event_type, place_id, geom, occurred_at,
                                       occurred_precision, status, confidence,
                                       claim_count, independent_sources, attrs)
                    -- 'hour', not 'exact': occurred_at is the time the channel
                    -- POSTED, and the incident happened some unknown amount before
                    -- that. Claiming second precision for a report time would be
                    -- the same overreach as quoting a drive time to a station
                    -- located only to its governorate.
                    SELECT %s, %s, p.centroid, %s, 'hour', 'believed', %s, %s, %s, %s
                    FROM place p WHERE p.place_id = %s
                    RETURNING event_id""",
                    (itype, place_id, occurred, conf, len(cluster), len(units),
                     json.dumps({"classifier": CLASSIFIER,
                                 "classifier_version": CLASSIFIER_VERSION,
                                 "channels": sorted({m[2] for m in cluster}),
                                 "place_text": reading.place_text,
                                 "governorate": reading.governorate,
                                 "matched": reading.matched,
                                 # Which of the two located this event. `named`
                                 # means the place in the message resolved;
                                 # `governorate` means it did NOT and only the
                                 # governorate matched, so the pin is admin2 and
                                 # the village in `place_text` is what the
                                 # channel named. Without this the two are
                                 # indistinguishable and a village incident
                                 # reads as if it happened in the city.
                                 "place_precision": (cluster[0][5] or "named"),
                                 "place_candidates": cluster[0][6] or [],
                                 "name_key": name_key or "",
                                 "stable_key": stable_key},
                                ensure_ascii=False),
                     place_id))
                row = cur.fetchone()
                if not row:
                    continue
                event_id = row[0]
            # event_id is the ONE field 005 sanctions updating on a claim; the
            # verdict itself goes to claim_classification, not onto the claim.
            cur.executemany("UPDATE claim SET event_id=%s WHERE claim_id=%s",
                            [(event_id, m[0]) for m in cluster])
            for m in cluster:
                event_by_claim[m[0]] = event_id
            stats["claims_linked"] += len(cluster)

            # A closure is also a movement STATE and must decay like one.
            if itype in ("closure", "siege"):
                cur.execute("""
                    INSERT INTO state_observation
                      (place_id, state_kind, value, raw_value, observed_at,
                       source_id, confidence, direction, direction_explicit,
                       modality, attrs)
                    VALUES (%s,%s,'closed',%s,%s,%s,%s,'both',false,'assertion',%s)""",
                    (place_id, STATE_KIND_CLOSURE, reading.matched, occurred,
                     cluster[0][3], conf,
                     json.dumps({"from_event": event_id, "incident_type": itype},
                                ensure_ascii=False)))
                stats["closure_states"] += 1

        # Record every verdict, hits and rejections alike. Re-runnable: a newer
        # classifier version overwrites its own row and leaves the claim alone.
        cur.executemany("""
            INSERT INTO claim_classification
              (claim_id, classifier, classifier_version, verdict, incident_type,
               reject_reason, place_id, place_text, governorate, confidence,
               event_id, classified_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
            ON CONFLICT (claim_id, classifier) DO UPDATE SET
              classifier_version = EXCLUDED.classifier_version,
              verdict            = EXCLUDED.verdict,
              incident_type      = EXCLUDED.incident_type,
              reject_reason      = EXCLUDED.reject_reason,
              place_id           = EXCLUDED.place_id,
              place_text         = EXCLUDED.place_text,
              governorate        = EXCLUDED.governorate,
              confidence         = EXCLUDED.confidence,
              event_id           = EXCLUDED.event_id,
              classified_at      = now()""",
            [(cid, CLASSIFIER, CLASSIFIER_VERSION, verdict, itype, reason,
              pid, ptext, gov, conf, event_by_claim.get(cid))
             for (cid, verdict, itype, reason, pid, ptext, gov, conf) in verdicts])
        stats["classifications"] = len(verdicts)

        # ── a version bump must not leave the previous generation behind ─────
        # These three sweeps exist because every one of them has already
        # happened. Bumping CLASSIFIER_VERSION re-reads claims that carry old
        # classifications; the upsert moves their pointers to freshly-clustered
        # events and nothing cleaned up what they used to point at. Five bumps
        # run WITHOUT --rebuild left 982 believed-but-unreferenced events, and
        # /v2/incidents was serving nearly every incident twice (#37 audit).
        # Deleting a stale conclusion is not data loss — the claims stay (037).
        #
        # (1) A claim whose new verdict is not `incident` keeps its old event
        # link forever otherwise — 77 fuel-bulletin "closures" survived 037
        # exactly this way, anchored by claim.event_id alone.
        demoted = [cid for (cid, verdict, *_rest) in verdicts if verdict != "incident"]
        if demoted:
            cur.execute("UPDATE claim SET event_id = NULL "
                        "WHERE claim_id = ANY(%s) AND event_id IS NOT NULL",
                        (demoted,))
            stats["claims_unlinked"] = cur.rowcount
        # (2) An event of ours that neither a claim nor a classification
        # references is a conclusion nothing stands behind.
        cur.execute("""
            DELETE FROM event e
             WHERE e.attrs->>'classifier' = %(clf)s
               AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.event_id = e.event_id)
               AND NOT EXISTS (SELECT 1 FROM claim_classification cc
                               WHERE cc.event_id = e.event_id)""",
            {"clf": CLASSIFIER})
        stats["stale_events_swept"] = cur.rowcount
        # (3) Closure observations derived from a now-deleted event follow it.
        if stats["stale_events_swept"]:
            cur.execute("""
                DELETE FROM state_observation so
                 WHERE so.state_kind = %(closure)s AND so.attrs ? 'from_event'
                   AND NOT EXISTS (SELECT 1 FROM event e
                                   WHERE e.event_id = (so.attrs->>'from_event')::bigint)""",
                {"closure": STATE_KIND_CLOSURE})
            stats["stale_closure_obs_swept"] = cur.rowcount

        # (4) Counts are derived, not accumulated. Joining an event adds the
        # cluster to its claim_count, and a re-read of the same claims (every
        # version bump) added them again — measured 2026-09-24. The claims
        # that point at an event are the count.
        cur.execute("""
            UPDATE event e
               SET claim_count = c.n
              FROM (SELECT event_id, count(*) AS n FROM claim
                     WHERE event_id IS NOT NULL GROUP BY event_id) c
             WHERE e.event_id = c.event_id AND e.attrs->>'classifier' = %(clf)s
               AND e.claim_count <> c.n""", {"clf": CLASSIFIER})
        stats["claim_counts_corrected"] = cur.rowcount

        if stats["closure_states"] or stats.get("stale_closure_obs_swept"):
            # The refresh only ever advances observed_at, so if a sweep removed
            # the newest observation behind a state_current row, the row must
            # go before the refresh can rebuild it from what remains.
            if stats.get("stale_closure_obs_swept"):
                cur.execute("DELETE FROM state_current WHERE state_kind = %s",
                            (STATE_KIND_CLOSURE,))
            cur.execute(REFRESH_CLOSURE_SQL, {"closure": STATE_KIND_CLOSURE})
            stats["closure_current"] = cur.rowcount
        conn.commit()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--rebuild", action="store_true",
                    help="discard this classifier's previous output and redo it "
                         "(use after any rule change)")
    a = ap.parse_args()

    s = classify(a.limit, a.dry_run, a.rebuild)
    if s.get("locked"):
        print("another classifier run holds the lock; nothing done")
        return 0
    print(f"read {s['read']} unclassified claims")
    print(f"  incident {s['verdict_incident']} · rejected {s['verdict_rejected']} "
          f"· unclear {s['verdict_unclear']}")
    print(f"  located {s['located']} · dropped {s['unresolved_place']} "
          f"whose place would not resolve")
    print(f"  -> {s['events']} distinct events from {s['claims_grouped']} reports "
          f"({s['corroborated']} corroborated by >1 independent group)")
    if a.dry_run:
        if s.get("unresolved_sample"):
            print("  unresolved samples:",
                  ", ".join(f"{k}({n})" for k, n in s["unresolved_sample"]))
        print("\n(dry run — nothing written)")
    else:
        print(f"  linked {s['claims_linked']} claims · "
              f"{s['closure_states']} closure states written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
