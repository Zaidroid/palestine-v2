"""P0.18 — place resolution.

    resolve_place(text, context) -> Resolution | None

One service, used by every fetcher and by the classifier. v1 resolved geography
ad-hoc inside each fetcher, which is why only 7.1% of its 244k records carry an
admin key. Everything here funnels through one code path so coverage is a
property of the system, not of whichever fetcher happened to try.

Strategy, in order — first hit wins:
  1. exact alias   (normalize / fold variants)     confidence 0.85–0.98
  2. containment   (a known alias inside a phrase) confidence 0.70–0.85
  3. fuzzy trigram (similarity >= threshold)       confidence 0.50–0.75

The resolver LEARNS: every successful resolution bumps `place_alias.hits`, and
a phrase that resolved by containment or fuzzy match is written back as an
`origin='observed'` alias, so the next occurrence is an exact hit. This is the
mechanism that makes coverage improve without anyone labelling anything.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.arabic import (fold, fold_for_match, is_generic_alias,
                            is_probably_arabic, normalize, strip_preposition,
                            variants)

# Precision by place kind — what resolving to this kind actually tells you.
KIND_PRECISION = {
    "checkpoint": "station", "station": "station", "crossing": "station",
    "facility": "station", "hospital": "station", "school": "station",
    "road": "street", "neighborhood": "street",
    "locality": "town", "village": "town", "town": "town", "city": "town",
    "camp": "town", "governorate": "admin2", "region": "admin1", "other": "unknown",
}

FUZZY_MIN = 0.55          # pg_trgm similarity floor
FUZZY_MARGIN = 0.08       # winner must beat runner-up by this much, else ambiguous
MIN_LEN = 3               # shorter strings match everything; not worth the noise
FUZZY_CONF_FLOOR = 0.55   # fuzzy is last-resort; below this, answer "unknown"


@dataclass(frozen=True)
class Resolution:
    place_id: int
    name_ar: str | None
    name_en: str | None
    kind: str
    precision: str
    confidence: float
    method: str                 # exact | contains | fuzzy
    matched_alias: str
    admin1_pcode: str | None = None
    admin2_pcode: str | None = None
    oslo_area: str | None = None
    ambiguous_with: int = 0     # runner-up count when the decision was close


_SELECT = """
    SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
           p.admin1_pcode, p.admin2_pcode, p.oslo_area, a.alias_norm, a.confidence
    FROM place_alias a JOIN place p ON p.place_id = a.place_id
"""


def _mk(row, method: str, confidence: float, ambiguous: int = 0) -> Resolution:
    (pid, ar, en, kind, a1, a2, oslo, alias, _ac) = row
    return Resolution(
        place_id=pid, name_ar=ar, name_en=en, kind=kind,
        precision=KIND_PRECISION.get(kind, "unknown"),
        confidence=round(confidence, 3), method=method, matched_alias=alias,
        admin1_pcode=a1, admin2_pcode=a2, oslo_area=oslo, ambiguous_with=ambiguous,
    )


def _prefer(rows, context: dict | None):
    """Tie-break among equally-good matches.

    Context beats size: a channel that usually reports from Nablus should
    resolve an ambiguous name to the Nablus one. Without context, prefer the
    more specific kind (a checkpoint over the governorate that contains it),
    because a specific mention is more informative and more often what was meant.
    """
    ctx = context or {}
    want_a2 = ctx.get("admin2_pcode")
    want_kind = ctx.get("prefer_kind")

    def score(r):
        _pid, _ar, _en, kind, a1, a2, _oslo, _alias, ac = r
        s = 0.0
        if want_kind and kind == want_kind:
            s += 3.0
        if want_a2 and a2 == want_a2:
            s += 2.0
        s += {"checkpoint": 1.0, "station": 1.0, "crossing": 1.0,
              "locality": 0.8, "road": 0.5,
              "governorate": 0.2, "region": 0.0}.get(kind, 0.4)
        s += float(ac or 0) / 10.0
        return s

    return sorted(rows, key=score, reverse=True)


def resolve_place(text: str | None, context: dict | None = None, *, conn=None,
                  learn: bool = True) -> Resolution | None:
    """Resolve a free-text place phrase. Returns None when nothing is confident."""
    if not text or len(text.strip()) < MIN_LEN:
        return None

    own = conn is None
    if own:
        from resolve.db import connect
        cm = connect()
        conn = cm.__enter__()
    try:
        with conn.cursor() as cur:
            probe = fold_for_match(text)
            # Order matters: variants first (most faithful), then the
            # generic-stripped probe. A phrase that reduces to nothing but
            # directions ("south", "شمال") yields no probe and must not resolve.
            # Extra probe with fused prepositions removed: "متوفر سولار بطولكرم"
            # -> "طولكرم". Additive, never a replacement — "بيت لحم" must not
            # become "يت لحم".
            unprep = " ".join(strip_preposition(t) or t for t in probe.split()) if probe else ""
            keys = [k for k in (*variants(text), probe, unprep) if k and len(k) >= 2]
            if not keys:
                return None
            seen_k: set[str] = set()
            keys = [k for k in keys
                    if not is_generic_alias(k) and not (k in seen_k or seen_k.add(k))]
            if not keys:
                return None

            # ── 1. exact ──────────────────────────────────────────────────────
            cur.execute(_SELECT + " WHERE a.alias_norm = ANY(%s)", (keys,))
            rows = cur.fetchall()
            if rows:
                ranked = _prefer(rows, context)
                best = ranked[0]
                # A fold-only hit is slightly weaker than a normalize hit: folding
                # discards information, so the match is less specific.
                exact_on_norm = best[7] == normalize(text)
                conf = min(0.98, (0.92 if exact_on_norm else 0.85) + float(best[8] or 0) * 0.05)
                if learn:
                    _bump(cur, best[7])
                    conn.commit()
                return _mk(best, "exact", conf, max(0, len(ranked) - 1))

            # ── 2. containment ────────────────────────────────────────────────
            # "الجيش يقتحم بلدة حوارة" — the alias sits inside a longer phrase.
            #
            # NOT longest-match. Many Palestinian place names are ordinary Arabic
            # nouns (الزيتون "the olive", الشهداء "the martyrs", النخيل "the palms"),
            # so the longest contained alias is regularly a common word used
            # literally. Measured on 549 real v1 phrases, longest-match sent
            # "قرب جنين واقتلاع أشجار الزيتون" to Az Zaytun, 134 km from Jenin.
            # Score on position and prominence as well as length: news phrases
            # lead with their location, so an early match is far more likely to
            # be the subject.
            folded = probe or fold(text)
            folded_unprep = unprep if unprep and unprep != folded else None
            cur.execute(_SELECT + """
                WHERE length(a.alias_norm) >= 4
                  AND position(a.alias_norm in %s) > 0
                ORDER BY length(a.alias_norm) DESC
                LIMIT 60""", (folded,))
            rows = cur.fetchall()
            if rows:
                plen = max(len(folded), 1)
                # Coverage was a hard reject at 0.25. That is right for terse
                # alert headlines and wrong for conversational fuel chatter:
                # "وين في سولار في نابلس" is 21 chars, so نابلس covers 0.24 and
                # was rejected even though it is unambiguously the location.
                # The real false-positive guard is a TOKEN-BOUNDARY match —
                # an alias must be a whole word, not a fragment inside one.
                rows = [r for r in rows
                        if _token_match(folded, r[7])
                        or (folded_unprep and _token_match(folded_unprep, r[7]))]
                if not rows:
                    return None
                KIND_W = {"governorate": 1.6, "region": 1.2, "city": 1.4,
                          "locality": 1.0, "checkpoint": 1.1, "crossing": 1.1,
                          "road": 0.7, "neighborhood": 0.6}

                def cscore(r):
                    alias, kind = r[7], r[3]
                    pos = folded.find(alias)
                    length_s = len(alias) / plen                 # how much it explains
                    pos_s = 1.0 - (pos / plen)                   # earlier is better
                    # Length dominates; position only breaks near-ties. Weighting
                    # position heavily made every "غرب مخيم X" resolve to whatever
                    # generic token appeared earliest.
                    return (length_s * 1.0 + pos_s * 0.35) * KIND_W.get(kind, 0.9)

                rows = [r for r in rows if not is_generic_alias(r[7])]
                rows.sort(key=cscore, reverse=True)
                top = cscore(rows[0])
                close = [r for r in rows if top - cscore(r) < 0.05]
                ranked = _prefer(close, context)
                best = ranked[0]
                # Coverage now only shapes confidence; it never rejects.
                coverage = len(best[7]) / plen
                conf = min(0.85, 0.55 + coverage * 0.30)
                if learn:
                    _bump(cur, best[7])
                    _observe(cur, folded, best[0], conf)
                    conn.commit()
                return _mk(best, "contains", conf, max(0, len({r[0] for r in ranked}) - 1))

            # ── 3. fuzzy ──────────────────────────────────────────────────────
            fz = folded or keys[0]
            # Own SELECT list — appending `, similarity(...)` to _SELECT would put
            # the function in the FROM clause (legal SQL, wrong column count).
            cur.execute("""
                SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
                       p.admin1_pcode, p.admin2_pcode, p.oslo_area,
                       a.alias_norm, a.confidence,
                       similarity(a.alias_norm, %s) AS sim
                FROM place_alias a JOIN place p ON p.place_id = a.place_id
                WHERE a.alias_norm %% %s
                  AND similarity(a.alias_norm, %s) >= %s
                ORDER BY sim DESC LIMIT 10""", (fz, fz, fz, FUZZY_MIN))
            rows = cur.fetchall()
            if not rows:
                return None
            top_sim = float(rows[0][9])
            close = [r for r in rows if top_sim - float(r[9]) < FUZZY_MARGIN]
            ranked = _prefer([r[:9] for r in close], context)
            best = ranked[0]
            # Ambiguity is a real answer: several distinct places matched equally
            # well, so report lower confidence rather than guessing confidently.
            distinct = len({r[0] for r in ranked})
            conf = min(0.75, top_sim * 0.8) / (1.0 + 0.35 * (distinct - 1))
            # Floor raised from 0.30: an OSM station in Palestine is literally
            # named "Baghdad Fuel", and at 0.30 the country "Baghdad" fuzzy-matched
            # it at 0.49 — a foreign-place leak. Fuzzy is the last resort and
            # contributes ~2 of 505 resolutions, so a strict floor costs almost
            # nothing and removes a whole class of false positive.
            if conf < FUZZY_CONF_FLOOR:
                return None
            if learn and distinct == 1:
                _bump(cur, best[7])
                _observe(cur, fz, best[0], conf)
                conn.commit()
            return _mk(best, "fuzzy", conf, distinct - 1)
    finally:
        if own:
            cm.__exit__(None, None, None)


def _token_match(haystack: str, alias: str) -> bool:
    """True if `alias` occurs in `haystack` on whole-token boundaries.

    Substring containment alone matches fragments inside unrelated words, which
    is how short aliases produce nonsense. Arabic has no casing and our
    normaliser already collapses punctuation to spaces, so a space/edge check
    is sufficient and much cheaper than a regex per candidate.
    """
    start = 0
    while True:
        i = haystack.find(alias, start)
        if i < 0:
            return False
        before_ok = i == 0 or haystack[i - 1] == " "
        j = i + len(alias)
        after_ok = j == len(haystack) or haystack[j] == " "
        if before_ok and after_ok:
            return True
        start = i + 1


def _bump(cur, alias_norm: str) -> None:
    cur.execute("UPDATE place_alias SET hits = hits + 1 WHERE alias_norm = %s", (alias_norm,))


def _observe(cur, alias_norm: str, place_id: int, confidence: float) -> None:
    """Write back a newly-seen spelling so the next occurrence resolves exactly.
    Only for keys long enough to be meaningful, and never overwriting an
    existing alias — a fuzzy guess must not displace a curated mapping."""
    if not alias_norm or len(alias_norm) < 4:
        return
    cur.execute("""
        INSERT INTO place_alias (alias_norm, place_id, confidence, origin, hits)
        VALUES (%s,%s,%s,'observed',1) ON CONFLICT (alias_norm) DO NOTHING""",
                (alias_norm, place_id, min(confidence, 0.7)))


def resolve_many(texts: Iterable[str], context: dict | None = None) -> list[Resolution | None]:
    from resolve.db import connect
    with connect() as conn:
        return [resolve_place(t, context, conn=conn) for t in texts]
