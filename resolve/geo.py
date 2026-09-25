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
from dataclasses import dataclass, field
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
    # The other places that carry this name (place_id, name, admin2_pcode),
    # so a caller can name them instead of hiding them (audit F067).
    alternatives: list = field(default_factory=list)


# The alias join FOLLOWS MERGES. place_merge collapses v1's sentence-shaped
# phantom keys ("صره_هسا_اجو_الجيش") into one canonical checkpoint and
# re-points existing rows — but an alias can still name the merged-away row,
# and resolving through it handed out the dead place_id. 650 palhub
# observations landed on four merged-away places exactly this way, written
# AFTER the merge had supposedly closed those rows.
_SELECT = """
    SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
           p.admin1_pcode, p.admin2_pcode, p.oslo_area, a.alias_norm, a.confidence
    FROM place_alias a
    JOIN place p0 ON p0.place_id = a.place_id
    JOIN place p  ON p.place_id = COALESCE(p0.merged_into, p0.place_id)
"""


def _mk(row, method: str, confidence: float, ambiguous: int = 0,
        alternatives: list | None = None) -> Resolution:
    (pid, ar, en, kind, a1, a2, oslo, alias, _ac) = row
    return Resolution(
        place_id=pid, name_ar=ar, name_en=en, kind=kind,
        precision=KIND_PRECISION.get(kind, "unknown"),
        confidence=round(confidence, 3), method=method, matched_alias=alias,
        admin1_pcode=a1, admin2_pcode=a2, oslo_area=oslo, ambiguous_with=ambiguous,
        alternatives=list(alternatives or []),
    )


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


def _twins_all(cur, keys: list[str]) -> list:
    """Every promoted twin of these keys, wherever it sits (audit F067). The
    alias table can hold one owner per key; the other places of the same name
    carry it in attrs.twin_keys, and every caller — not only one with a
    governorate hint — must see that they exist."""
    cur.execute("""
        SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
               p.admin1_pcode, p.admin2_pcode, p.oslo_area, %s, 0.9
          FROM place p
         WHERE p.servable AND p.merged_into IS NULL
           AND p.attrs->'twin_keys' ?| %s
         ORDER BY p.place_id""", (keys[0], keys))
    return cur.fetchall()


def _twin_in(cur, keys: list[str], admin2: str):
    """A promoted twin of a name whose alias belongs to a place elsewhere.

    `place_alias.alias_norm` is unique, so the second المغير (Ramallah's) can
    never hold the key the first one (Jenin's) already has. A row promoted as a
    twin carries its keys in `attrs.twin_keys` instead, and is reachable only
    through the governorate hint — which is exactly when the alias's owner is
    the wrong answer. Returns a row shaped like `_SELECT`'s, or None.
    """
    cur.execute("""
        SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
               p.admin1_pcode, p.admin2_pcode, p.oslo_area, %s, 0.9
          FROM place p
         WHERE p.servable AND p.merged_into IS NULL AND p.admin2_pcode = %s
           AND p.attrs->'twin_keys' ?| %s
         ORDER BY p.place_id LIMIT 1""", (keys[0], admin2, keys))
    return cur.fetchone()


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
                  learn: bool = False, fuzzy: bool = True,
                  contain: bool = True) -> Resolution | None:
    """Resolve a free-text place phrase. Returns None when nothing is confident.

    `learn` is OFF by default (audit F068): a public caller's guess used to be
    inserted as an alias and served as 'exact' to every later caller,
    including the classifier. Learning is opt-in for ingestion, and a caller
    who passes its own connection owns the transaction — nothing here commits
    it.

    `fuzzy=False` stops before the fuzzy branch and `contain=False` before the
    contained-alias branch: a caller whose phrase is a guess (a token that
    merely sits before "جنوب نابلس", or after "أبو") must not be handed the
    nearest-looking alias for it.
    """
    if not text or len(text.strip()) < MIN_LEN:
        return None

    own = conn is None
    if own:
        from resolve.db import connect
        cm = connect()
        conn = cm.__enter__()
    try:
        with conn.cursor() as cur:
            context = _with_admin_pcode(cur, context)
            probe = fold_for_match(text)
            # Order matters: variants first (most faithful), then the
            # generic-stripped probe. A phrase that reduces to nothing but
            # directions ("south", "شمال") yields no probe and must not resolve.
            # Extra probe with fused prepositions removed: "متوفر سولار بطولكرم"
            # -> "طولكرم". Additive, never a replacement — "بيت لحم" must not
            # become "يت لحم".
            unprep = " ".join(strip_preposition(t) or t for t in probe.split()) if probe else ""
            keys = [k for k in (*variants(text), probe, unprep) if k and len(k) >= 2]
            keys += [sw for sw in (_swap_ending(k) for k in list(keys)) if sw]
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
                # The twins ALWAYS join the ranking (F067): with a governorate
                # hint _prefer picks the one in that governorate; without one
                # the answer says how many places carry the name and names
                # them, and its confidence is divided as the fuzzy branch's is.
                # المغير answered Jenin's village at 0.92 with ambiguous_with=0
                # while 232 of 241 events belonged to Ramallah's.
                have = {r[0] for r in rows}
                rows = rows + [t for t in _twins_all(cur, keys) if t[0] not in have]
                ranked = _prefer(rows, context)
                want_a2 = (context or {}).get("admin2_pcode")
                best = ranked[0]
                others: dict[int, tuple] = {}
                for r in ranked:
                    if r[0] != best[0] and r[0] not in others:
                        others[r[0]] = (r[0], r[1] or r[2], r[5])
                settled = bool(want_a2) and best[5] == want_a2
                ambiguous = 0 if settled else len(others)
                # A fold-only hit is slightly weaker than a normalize hit: folding
                # discards information, so the match is less specific.
                exact_on_norm = best[7] == normalize(text)
                conf = min(0.98, (0.92 if exact_on_norm else 0.85) + float(best[8] or 0) * 0.05)
                if ambiguous:
                    conf = conf / (1.0 + 0.35 * ambiguous)
                if learn:
                    _bump(cur, best[7])
                    if own:
                        conn.commit()
                return _mk(best, "exact", conf, ambiguous, list(others.values()))

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
                    if own:
                        conn.commit()
                return _mk(best, "contains", conf, max(0, len({r[0] for r in ranked}) - 1))

            # ── 3. fuzzy ──────────────────────────────────────────────────────
            if not fuzzy:
                return None
            fz = folded or keys[0]
            # Own SELECT list — appending `, similarity(...)` to _SELECT would put
            # the function in the FROM clause (legal SQL, wrong column count).
            cur.execute("""
                SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
                       p.admin1_pcode, p.admin2_pcode, p.oslo_area,
                       a.alias_norm, a.confidence,
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
                if own:
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


def resolve_for_state_kind(conn, place: str, state_kind: str, *, learn: bool = False):
    """Resolve a place phrase to the row this field's data actually lives on.

    Never learns by default: its callers are an anonymous crowd report, the
    public /v2/geo/resolve and a feed loader, and the fallthrough below used to
    write whatever phrase they carried into place_alias (audit F076).
    """
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

    return resolve_place(place, {"prefer_kind": want} if want else None,
                         conn=conn, learn=learn)
