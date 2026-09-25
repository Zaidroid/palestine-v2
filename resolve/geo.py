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

The resolver CAN learn, and by default does not. With `learn=True` a
successful resolution bumps `place_alias.hits`, and a phrase that resolved by
containment with confidence >= LEARN_MIN_CONF is written back as an
`origin='observed'` alias. It used to be the default, so every public probe of
/v2/insights and every crowd or palhub fallback wrote permanent aliases, and
the exact branch then served those guesses as method 'exact' at 0.89+ to every
later caller, the incident classifier included (F071, 2026-09-25). Now:

  * learning is opt-in, for a trusted caller that names itself by passing
    `learn=True` (no caller in serve/, crowd/ or ingest/ does today);
  * a fuzzy match is never written back — a guess is not a spelling;
  * an observed alias is served as method 'observed', at no more than the
    confidence it was stored with;
  * resolve_place never commits a transaction it does not own.
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
MIN_LEN = 2               # two letters resolve by EXACT alias only (تل, جت);
                          # containment and fuzzy keep their own floors
FUZZY_CONF_FLOOR = 0.55   # fuzzy is last-resort; below this, answer "unknown"
LEARN_MIN_CONF = 0.75     # a containment phrase is written back only at or above
                          # this (the alias covers >= 2/3 of the phrase), and
                          # only by a caller that passed learn=True


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
    # (place_id, admin2_pcode, name_ar) of every place that carries this exact
    # name when nothing in the context decided between them (a twin village).
    alternatives: tuple = ()


# The alias join FOLLOWS MERGES. place_merge collapses v1's sentence-shaped
# phantom keys ("صره_هسا_اجو_الجيش") into one canonical checkpoint and
# re-points existing rows — but an alias can still name the merged-away row,
# and resolving through it handed out the dead place_id. 650 palhub
# observations landed on four merged-away places exactly this way, written
# AFTER the merge had supposedly closed those rows.
_SELECT = """
    SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
           p.admin1_pcode, p.admin2_pcode, p.oslo_area, a.alias_norm, a.confidence,
           a.origin
    FROM place_alias a
    JOIN place p0 ON p0.place_id = a.place_id
    JOIN place p  ON p.place_id = COALESCE(p0.merged_into, p0.place_id)
"""


def _mk(row, method: str, confidence: float, ambiguous: int = 0,
        alternatives: tuple = ()) -> Resolution:
    (pid, ar, en, kind, a1, a2, oslo, alias, _ac, _origin) = row[:10]
    return Resolution(
        place_id=pid, name_ar=ar, name_en=en, kind=kind,
        precision=KIND_PRECISION.get(kind, "unknown"),
        confidence=round(confidence, 3), method=method, matched_alias=alias,
        admin1_pcode=a1, admin2_pcode=a2, oslo_area=oslo, ambiguous_with=ambiguous,
        alternatives=alternatives,
    )


def _as_served(row, method: str, conf: float) -> tuple[str, float]:
    """An observed alias is a spelling the resolver once GUESSED (or a feed
    stated): serve it as what it is, at no more than the confidence it was
    stored with. The exact branch used to hand it out as method 'exact' at
    0.89-0.96, so a containment guess made once became a certainty (F071)."""
    if row[9] == "observed":
        return "observed", min(conf, float(row[8] or 0))
    return method, conf


_ADMIN_PCODE: dict[str, str | None] = {}


_GOV_ROWS: list[tuple[str, str]] | None = None      # (normalised name, pcode)


def governorate_pcode(cur, name: str | None) -> str | None:
    """OCHA admin2 code of the governorate NAMED — read from the governorate
    rows' own names, never through an alias and never from the city.

    Two things made the alias route unusable: `resolve_place("رام الله")`
    answers with the CITY (a locality beats a polygon in `_prefer`), and the
    alias backfill deliberately MOVED the bare Arabic name from the governorate
    polygon to the city (origin `backfill_city`), so the governorate row keeps
    no bare-name key at all. Until migration 077 the city also carried v1's own
    code, so every caller that wanted "the governorate this text names" got a
    code nothing else used; the fuller-form village lookup was dead for that
    reason from the day it landed (found 2026-09-24). The 16 rows are read once.
    """
    global _GOV_ROWS
    if not name:
        return None
    if _GOV_ROWS is None:
        cur.execute("""
            SELECT name_ar, name_en, admin2_pcode FROM place
             WHERE kind::text = 'governorate' AND servable AND admin2_pcode IS NOT NULL""")
        rows = []
        for ar, en, pc in cur.fetchall():
            for nm in (ar, en):
                for key in (normalize(nm), fold_for_match(nm)):
                    if key:
                        rows.append((key, pc))
        _GOV_ROWS = rows
    probes = {k for k in (normalize(name), fold_for_match(name)) if k}
    for key, pc in _GOV_ROWS:
        if key in probes:
            return pc
    return None


def _twins(cur, keys: list[str], exclude: set[int]) -> list[tuple]:
    """Promoted twins of names whose alias belongs to a place elsewhere.

    `place_alias.alias_norm` is unique, so the second المغير (Ramallah's) can
    never hold the key the first one (Jenin's) already has. A row promoted as a
    twin carries its keys in `attrs.twin_keys` instead (see
    ops/promote_named_localities.py). Returns rows shaped like `_SELECT`'s,
    the alias column set to the probe key the twin carries, origin 'twin'.

    Read on EVERY exact hit, not only when a governorate hint is present: the
    hint-less callers (/v2/geo/resolve, /v2/insights, route_between, the news
    area) got Jenin's المغير at ~0.96 with ambiguous_with=0 and no sign that a
    second place of that name exists (F070). The `attrs ? 'twin_keys'`
    predicate matches migration 090's partial index.
    """
    if not keys:
        return []
    cur.execute("""
        SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
               p.admin1_pcode, p.admin2_pcode, p.oslo_area,
               ARRAY(SELECT jsonb_array_elements_text(p.attrs->'twin_keys'))
          FROM place p
         WHERE p.servable AND p.merged_into IS NULL
           AND p.attrs ? 'twin_keys' AND p.attrs->'twin_keys' ?| %s
         ORDER BY p.place_id""", (list(keys),))
    out = []
    for pid, ar, en, kind, a1, a2, oslo, carried in cur.fetchall():
        if pid in exclude:
            continue
        key = next((k for k in keys if k in (carried or [])), keys[0])
        out.append((pid, ar, en, kind, a1, a2, oslo, key, 0.9, "twin"))
    return out


def _homonyms(key: str, rows, twins) -> list[tuple]:
    """Every distinct place that carries `key` itself: its alias owner and the
    twins holding it in attrs. One place, one row."""
    seen: dict[int, tuple] = {}
    for r in (*rows, *twins):
        if r[7] == key and r[0] not in seen:
            seen[r[0]] = r
    return list(seen.values())


def _decide_homonyms(best, homonyms, want_a2, conf: float):
    """(confidence, ambiguous_with, alternatives) once twins are counted.

    Settled when the governorate hint names exactly one of the places that
    carry the name and the answer is that one. Otherwise each is as likely as
    the other, so the answer says so: confidence divided by their number (two
    twins put an exact 0.96 at 0.48, under the crowd's and palhub's 0.55 floor,
    so a report is declined rather than filed on the wrong village) and the
    alternatives named for the caller to show.
    """
    if len(homonyms) < 2:
        return conf, 0, ()
    in_hint = [h for h in homonyms if want_a2 and h[5] == want_a2]
    if len(in_hint) == 1 and in_hint[0][0] == best[0]:
        return conf, 0, ()
    alts = tuple((h[0], h[5], h[1]) for h in homonyms)
    return conf / len(homonyms), len(homonyms) - 1, alts


def _with_admin_pcode(cur, context: dict | None) -> dict | None:
    """Turn an `admin` governorate NAME in the context into `admin2_pcode`.

    The incident classifier has always passed `{"admin": governorate}` and
    `_prefer` has only ever read `admin2_pcode`, so the hint was ignored: a
    village name shared by two governorates resolved by size, not by the
    governorate the message named. Measured 2026-09-24 (validation of the
    public-release plan).
    """
    if not context or context.get("admin2_pcode") or not context.get("admin"):
        return context
    pcode = governorate_pcode(cur, context["admin"])
    return {**context, "admin2_pcode": pcode} if pcode else context


def _swap_ending(key: str) -> str | None:
    """The same name with its final ا/ه swapped: channels write عنزا, يرزا,
    بلعا where the gazetteer holds عنزه, يرزه, بلعه — and the other way round.
    An extra EXACT probe only; never a replacement, never a display form."""
    if not key or len(key) < 3:
        return None
    last = key.rsplit(" ", 1)[-1]
    if len(last) < 3:
        return None
    if key.endswith("ا"):
        return key[:-1] + "ه"
    if key.endswith("ه"):
        return key[:-1] + "ا"
    return None


def _literal_first(rows, faithful: list[str], context: dict | None):
    """Rows matched by the text's own spellings, unless the caller's stated
    kind/governorate is met only by a row a derived probe found (F523)."""
    lit = [r for r in rows if r[7] in faithful]
    if not lit or len(lit) == len(rows):
        return rows
    ctx = context or {}
    want_kind, want_a2 = ctx.get("prefer_kind"), ctx.get("admin2_pcode")
    if not (want_kind or want_a2):
        return lit

    def meets(r) -> bool:
        return ((not want_kind or r[3] == want_kind)
                and (not want_a2 or r[5] == want_a2))

    if not any(meets(r) for r in lit) and any(meets(r) for r in rows):
        return rows
    return lit


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
        kind, a2, ac = r[3], r[5], r[8]
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
                  learn: bool = False, fuzzy: bool = True,
                  contain: bool = True) -> Resolution | None:
    """Resolve a free-text place phrase. Returns None when nothing is confident.

    `fuzzy=False` stops before the fuzzy branch and `contain=False` before the
    contained-alias branch: a caller whose phrase is a guess (a token that
    merely sits before "جنوب نابلس", or after "أبو") must not be handed the
    nearest-looking alias for it.

    `learn=True` is for a trusted caller only (see the module docstring). Its
    writes join the caller's transaction when `conn` is given — the caller
    commits — and are committed here only on a connection opened here.
    """
    if not text or len(text.strip()) < MIN_LEN:
        return None

    own = conn is None
    if own:
        from resolve.db import connect
        cm = connect()
        conn = cm.__enter__()

    def learned() -> None:
        # Never commit a transaction the caller owns: palhub_roads' whole
        # batch was committed mid-loop, before its ingest_seen row existed,
        # and --dry-run wrote hits and aliases (F071).
        if own:
            conn.commit()

    try:
        with conn.cursor() as cur:
            context = _with_admin_pcode(cur, context)
            want_a2 = (context or {}).get("admin2_pcode")
            probe = fold_for_match(text)
            # Order matters: variants first (most faithful), then the
            # generic-stripped probe. A phrase that reduces to nothing but
            # directions ("south", "شمال") yields no probe and must not resolve.
            # Extra probe with fused prepositions removed: "متوفر سولار بطولكرم"
            # -> "طولكرم". Additive, never a replacement — "بيت لحم" must not
            # become "يت لحم".
            unprep = " ".join(strip_preposition(t) or t for t in probe.split()) if probe else ""
            faithful = [k for k in (*variants(text), probe) if k and len(k) >= 2]
            derived = [k for k in (unprep,) if k and len(k) >= 2]
            derived += [sw for sw in (_swap_ending(k) for k in (*faithful, *derived)) if sw]
            seen_k: set[str] = set()
            faithful = [k for k in faithful
                        if not is_generic_alias(k) and not (k in seen_k or seen_k.add(k))]
            derived = [k for k in derived
                       if not is_generic_alias(k) and not (k in seen_k or seen_k.add(k))]
            keys = faithful + derived
            if not keys:
                return None

            # ── 1. exact ──────────────────────────────────────────────────────
            cur.execute(_SELECT + " WHERE a.alias_norm = ANY(%s)", (keys,))
            rows = cur.fetchall()
            if rows:
                # A derived probe (preposition stripped, ending swapped) is an
                # extra way IN, not a competitor of the literal spelling: with
                # both in one ranking, a checkpoint owning the swapped "بيته"
                # beat the village the text named, "بيتا", on kind alone
                # (F523). It still answers when the text's own spellings
                # matched nothing — and when the caller SAID which kind or
                # governorate it wants and only the derived match is that: the
                # swap exists for "channels write عنزا where the gazetteer
                # holds عنزه", and a station that took the other spelling first
                # must not win the classifier's prefer_kind=locality call.
                rows = _literal_first(rows, faithful, context)
                twins = _twins(cur, keys, {r[0] for r in rows})
                ranked = _prefer(rows, context)
                if want_a2 and not any(r[5] == want_a2 for r in ranked):
                    in_hint = [t for t in twins if t[5] == want_a2]
                    if in_hint:
                        ranked = _prefer(in_hint, context)
                best = ranked[0]
                # A fold-only hit is slightly weaker than a normalize hit: folding
                # discards information, so the match is less specific.
                exact_on_norm = best[7] == normalize(text)
                conf = min(0.98, (0.92 if exact_on_norm else 0.85) + float(best[8] or 0) * 0.05)
                method, conf = _as_served(best, "exact", conf)
                conf, twin_amb, alts = _decide_homonyms(
                    best, _homonyms(best[7], rows, twins), want_a2, conf)
                if learn and best[9] != "twin":
                    _bump(cur, best[7])
                    learned()
                ambiguous = max(len({r[0] for r in ranked}) - 1, twin_amb)
                return _mk(best, method, conf, ambiguous, alts)

            # Two letters are a name only when an alias says so exactly.
            if len(normalize(text)) < 3 or not contain:
                return None

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
                # A generic key (written by an old learning path or a merge) can
                # be the only whole-word hit; with it filtered there is nothing
                # left to rank, and rows[0] raised IndexError on "اغلاق بمدخل"
                # (F524). Same answer as when no hit is a whole word.
                if not rows:
                    return None
                rows.sort(key=cscore, reverse=True)
                top = cscore(rows[0])
                close = [r for r in rows if top - cscore(r) < 0.05]
                ranked = _prefer(close, context)
                best = ranked[0]
                # The contained name may be a twin's as well: "اقتحام المغير" is
                # no less ambiguous than "المغير" (F070/F171). Same rule as the
                # exact branch, including the governorate hint.
                twins = _twins(cur, [best[7]], {r[0] for r in close})
                if want_a2 and best[5] != want_a2:
                    in_hint = [t for t in twins if t[5] == want_a2]
                    if in_hint:
                        best = _prefer(in_hint, context)[0]
                # Coverage now only shapes confidence; it never rejects.
                coverage = len(best[7]) / plen
                conf = min(0.85, 0.55 + coverage * 0.30)
                method, conf = _as_served(best, "contains", conf)
                conf, twin_amb, alts = _decide_homonyms(
                    best, _homonyms(best[7], close, twins), want_a2, conf)
                if learn and best[9] != "twin":
                    _bump(cur, best[7])
                    # Only a confident, unambiguous containment becomes a
                    # spelling; a low-coverage or twin guess would outlive the
                    # context that made it plausible.
                    if conf >= LEARN_MIN_CONF and not alts:
                        _observe(cur, folded, best[0], conf)
                    learned()
                ambiguous = max(len({r[0] for r in ranked}) - 1, twin_amb)
                return _mk(best, method, conf, ambiguous, alts)

            # ── 3. fuzzy ──────────────────────────────────────────────────────
            if not fuzzy:
                return None
            fz = folded or keys[0]
            # Own SELECT list — appending `, similarity(...)` to _SELECT would put
            # the function in the FROM clause (legal SQL, wrong column count).
            cur.execute("""
                SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
                       p.admin1_pcode, p.admin2_pcode, p.oslo_area,
                       a.alias_norm, a.confidence, a.origin,
                       similarity(a.alias_norm, %s) AS sim
                FROM place_alias a
                JOIN place p0 ON p0.place_id = a.place_id
                JOIN place p  ON p.place_id = COALESCE(p0.merged_into, p0.place_id)
                WHERE a.alias_norm %% %s
                  AND similarity(a.alias_norm, %s) >= %s
                ORDER BY sim DESC LIMIT 10""", (fz, fz, fz, FUZZY_MIN))
            rows = cur.fetchall()
            if not rows:
                return None
            top_sim = float(rows[0][10])
            close = [r for r in rows if top_sim - float(r[10]) < FUZZY_MARGIN]
            ranked = _prefer([r[:10] for r in close], context)
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
            method, conf = _as_served(best, "fuzzy", conf)
            if learn and distinct == 1:
                # The matched alias earned a hit; the typed phrase does NOT
                # become an alias. A fuzzy match is a guess, and written back it
                # would be served on the next call as a spelling (F071).
                _bump(cur, best[7])
                learned()
            return _mk(best, method, conf, distinct - 1)
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
    # A generic noun ("مدخل", "منطقه") must never become a key: once written,
    # it is the only whole-word hit for every phrase that contains the plain
    # word (F524). The loaders have always refused them; so does this path.
    if not alias_norm or len(alias_norm) < 4 or is_generic_alias(alias_norm):
        return
    cur.execute("""
        INSERT INTO place_alias (alias_norm, place_id, confidence, origin, hits)
        VALUES (%s,%s,%s,'observed',1) ON CONFLICT (alias_norm) DO NOTHING""",
                (alias_norm, place_id, min(confidence, 0.7)))


def resolve_many(texts: Iterable[str], context: dict | None = None) -> list[Resolution | None]:
    from resolve.db import connect
    with connect() as conn:
        return [resolve_place(t, context, conn=conn, learn=False) for t in texts]


# ── kind-aware resolution ────────────────────────────────────────────────────
# Lifted out of crowd/engine.py once the MCP tools hit the same bug it was
# written for. Two copies of "which place did they mean" would drift, and the
# failure is silent: a report or a question lands on a row that looks right and
# holds none of the data.

# Which KIND of place each field's observations live on.
#
# READ FROM state_kind_config.place_kind (migration 035), not hardcoded. It was
# a dict here and the same silent failure happened three times — crowd
# checkpoint reports landing on towns, MCP history returning empty, crowd
# crossing reports landing on Rafah the city instead of Rafah the crossing.
# Every time, a new state kind had been added without anyone remembering this
# list, and every time the report was accepted and stored somewhere no other
# source would ever meet it.
#
# Cached for the process: it is configuration that changes at migration time,
# and re-reading it per resolution would add a query to the hot path.
_PLACE_KIND_CACHE: dict | None = None


def _prefer_place_kinds(conn=None) -> dict:
    global _PLACE_KIND_CACHE
    if _PLACE_KIND_CACHE is not None:
        return _PLACE_KIND_CACHE
    sql = ("SELECT state_kind, place_kind FROM state_kind_config "
           "WHERE place_kind IS NOT NULL")
    try:
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        else:
            from resolve.db import connect
            with connect() as own, own.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        if not rows:
            # Nothing configured yet (a migration in flight, the column still
            # NULL). Memoising {} sent every kind-scoped call to the generic
            # resolver — the town, not the checkpoint — until the next restart,
            # while the comment below promised a retry (F525).
            return {}
        _PLACE_KIND_CACHE = dict(rows)
    except Exception:                                   # noqa: BLE001
        # A database hiccup must not turn every resolution into the generic
        # path silently; an empty cache is not memoised, so it retries.
        return {}
    return _PLACE_KIND_CACHE


class _Ambiguous(Exception):
    """The phrase names more than one place of the right kind."""
    def __init__(self, options):
        self.options = options
        super().__init__("ambiguous place")


@dataclass
class _Place:
    """A kind-scoped match. Mirrors the fields of `Resolution` that callers
    actually read, so the two are interchangeable at the call site — a partial
    stand-in would fail at whichever attribute the next caller happens to want,
    which is how this was found (geo_resolve reached for `.kind`)."""
    place_id: int
    name_ar: str | None
    name_en: str | None
    precision: str
    confidence: float
    method: str
    kind: str = "place"
    admin1_pcode: str | None = None
    admin2_pcode: str | None = None
    oslo_area: str | None = None
    matched_alias: str = ""
    ambiguous_with: int = 0


# Match a typed name against places of one kind, by the same folding the
# gazetteer uses. Deliberately NOT done by adding place_alias rows.
#
# 172 of 359 checkpoint places have no alias at all — they came from v1's
# registry, which addresses them by its own id and never needed names — and 81
# of those carry live data. So a crowd member typing a checkpoint name reaches
# the LOCALITY of the same name instead, lands on a different row from every
# channel report, and can never corroborate anything.
#
# The obvious fix, backfilling place_alias, would change resolution for
# everything else too: `_prefer` scores a checkpoint above a locality, so a news
# sentence mentioning the town الظاهرية would start geocoding to the checkpoint.
# That is a live regression in the incident pipeline to fix a crowd bug. This
# stays inside the crowd path, where the caller knows which kind it wants.
# Folding happens in Python, with the same helper the gazetteer and every
# parser use. Doing it in SQL would mean a second implementation of Arabic
# normalisation, and this project has already been bitten twice by two
# normalisers disagreeing (`ILIKE` not folding hamza; patterns not folded at
# import). Under 600 rows per kind, so scanning them costs nothing.
# merged_into IS NULL: a merged-away phantom ("صره هسا اجو الجيش") must not
# offer its sentence-shaped name to crowd matching — its canonical row is the
# one with the data.
NAME_SQL = ("SELECT place_id, name_ar, name_en FROM place "
            "WHERE kind = %s AND merged_into IS NULL AND servable")
# `AND servable` (T2 close): the Nakba gazetteer adds 2,000+ historic
# localities as servable=false reference rows. A live report naming طنطورة
# must not resolve to a village destroyed in 1948 — unservable rows are for
# historical joins, never live capture.


def resolve_for_state_kind(conn, place: str, state_kind: str):
    """Resolve a place phrase to the row this field's data actually lives on."""
    want = _prefer_place_kinds(conn).get(state_kind)
    if want:
        from resolve.arabic import fold_for_match, normalize
        target = fold_for_match(place)
        typed = place.strip().lower()
        with conn.cursor() as cur:
            cur.execute(NAME_SQL, (want,))
            rows = cur.fetchall()

        # Exact name first, folded name second. `fold_for_match` strips generic
        # words, so "بوابة حوارة" (Huwara Gate) and "حوارة" both fold to
        # حواره — meaning the fuller, more specific name a submitter types to
        # disambiguate would itself come back ambiguous, and the refusal would
        # offer them options they cannot express. Matching the exact name first
        # makes the answer to "which one?" typeable.
        exact = [(pid, ar, en) for pid, ar, en in rows
                 if (ar and normalize(ar) == normalize(place))
                 or (en and en.strip().lower() == typed)]
        if len(exact) == 1:
            pid, ar, en = exact[0]
            return _Place(pid, ar, en, "exact", 0.92, f"name:{want}", want)

        hits = [(pid, ar, en) for pid, ar, en in rows
                if (ar and fold_for_match(ar) == target)
                or (en and en.strip().lower() == typed)]
        if len(hits) == 1:
            pid, ar, en = hits[0]
            return _Place(pid, ar, en, "exact", 0.9, f"name:{want}", want)
        if len(hits) > 1:
            # Genuinely ambiguous: "حوارة" is both a checkpoint and the gate
            # beside it. Falling through to the general resolver here put the
            # report on the TOWN — a row no channel writes to, so it could
            # never corroborate and never be served. Silently filing a report
            # against the wrong place is worse than declining it, and the
            # submitter is the only one who knows which they meant.
            raise _Ambiguous([(pid, ar or en) for pid, ar, en in hits])

    # learn=False, stated: the crowd, palhub_roads and /v2/geo/resolve all
    # reach this line, and none of them is a trusted teacher (F071).
    return resolve_place(place, {"prefer_kind": want} if want else None,
                         conn=conn, learn=False)
