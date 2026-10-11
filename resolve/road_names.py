"""The road register's names, found in a line — v2's own matcher.

Until 2026-10-11 the only thing that could say WHICH checkpoint a road message
was about was v1's whitelist parser, inside the PoC: it takes the words before
the first status word as the name and looks that string up whole. A name it
does not hold spelled exactly that way is lost with its reading ("عين سينا",
"فرش الهوا", "برقا": 113 spellings one edit from a registered name, 6,699
mentions), a name in the middle of a sentence is never tried, and a line that
names two checkpoints gives one reading. v2's alias table held 11,030 aliases
and 104 had ever been hit, because nothing asked it.

This asks it. `load()` reads every name the register holds for a road place
(`place.name_ar`, `name_en`, v1's key, `place_alias`), follows merges, and
`Lexicon.scan()` finds the longest of them at every position of a line,
wherever it stands. The register is v2's: a spelling is added with one row in
`place_alias`, and the next run reads it.

WHAT IS FOLDED, AND WHY NO MORE
A name and a line meet on a key: `resolve.arabic.normalize`, then per word the
article off ("المربعه" = "مربعه", "عالمربعه" too) and a letter typed twice or
more collapsed ("صررره"). One conjunction or preposition fused to the first
word is tried off ("وعطاره", "لعطاره", "ععطاره"). Nothing fuzzier: one edit
also pairs جيب with جيت and بيت عوا with بيت عور, so a spelling becomes a name
only by being written into the table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from resolve.arabic import normalize

ROAD_KINDS = ("checkpoint", "crossing", "road")
MAX_WORDS = 6

# A word, in the RAW text: letters, digits, and the marks normalize() removes
# (harakat, tatweel), so offsets index the string the message was written in.
_MARKS = "".join(map(chr, [*range(0x0610, 0x061B), *range(0x064B, 0x0660), 0x0670,
                           *range(0x06D6, 0x06EE)]))
_WORD = re.compile(r"(?:[^\W_]|[" + _MARKS + "])+", re.UNICODE)
_ARTICLE = re.compile(r"^(?:لل|[بلكفوع]ال|ال)")
_REPEAT = re.compile(r"(.)\1+")

# Fused to the first word of a name: و (and), ب (at), ل (to), ع (on), ف (so).
_FUSED = "وبلعف"

# "حاجز عناب" is عناب: the generic word is dropped to make a second key. Only
# these — "مدخل X" and "بوابة X" are often a different place from X itself, and
# the register holds both.
_GENERIC = frozenset(["حاجز", "معبر", "محسوم", "checkpoint"])


def fold_token(tok: str) -> str:
    s = _ARTICLE.sub("", tok)
    s = s if len(s) >= 2 else tok
    return _REPEAT.sub(r"\1", s)


def key_of(surface: str) -> tuple[str, ...]:
    """The matching key of a name: its folded words."""
    return tuple(fold_token(t) for w in normalize(surface).split()
                 for t in _WORD.findall(w))


@dataclass(frozen=True)
class Span:
    """One name found in a line."""
    start: int                     # raw character offsets, [start, end)
    end: int
    w0: int                        # word indexes, [w0, w1)
    w1: int
    place_id: int
    alias: str                     # the key that matched, words joined by a space
    fused: str = ""                # the letter peeled off its first word, if any
    rivals: tuple[int, ...] = ()   # other places the same key names


@dataclass
class Lexicon:
    names: dict[tuple[str, ...], tuple[int, ...]] = field(default_factory=dict)
    # A weak name is also an ordinary word ("جيت": I came; "الفحص": the
    # inspection). It is taken only where it opens the line or follows a
    # generic place word.
    weak: frozenset = frozenset()

    def words(self, text: str) -> list[tuple[str, int, int]]:
        """(folded word, start, end) over the raw text."""
        out = []
        for m in _WORD.finditer(text):
            n = normalize(m.group()).replace(" ", "")
            if n:
                out.append((fold_token(n), m.start(), m.end()))
        return out

    def scan(self, text: str) -> list[Span]:
        """Every registered name in `text`, longest first at each position."""
        ws = self.words(text)
        folded = [w for w, _, _ in ws]
        spans: list[Span] = []
        i = 0
        while i < len(ws):
            hit = None
            for n in range(min(MAX_WORDS, len(ws) - i), 0, -1):
                k = tuple(folded[i:i + n])
                ids, fused = self.names.get(k), ""
                if not ids and len(folded[i]) >= 4 and folded[i][0] in _FUSED:
                    # "وعطاره": the conjunction off, and the article it hid.
                    bare = fold_token(folded[i][1:])
                    if len(bare) >= 3:
                        ids, fused = self.names.get((bare,) + k[1:]), folded[i][0]
                        k = (bare,) + k[1:]
                if not ids:
                    continue
                if n == 1 and k[0] in self.weak and not self._anchored(folded, i, fused):
                    continue
                hit = Span(ws[i][1], ws[i + n - 1][2], i, i + n, ids[0], " ".join(k),
                           fused, tuple(ids[1:]))
                break
            if hit:
                if hit.place_id:               # 0: a town's name, read past
                    spans.append(hit)
                i = hit.w1
            else:
                i += 1
        return spans

    @staticmethod
    def _anchored(folded: list[str], i: int, fused: str) -> bool:
        if fused:
            return False
        if folded[i].isdigit():
            # "17 دقيقة على عناب" opens a line too; "١٧ مريت عنه ما في حاجز" does.
            if i == 0:
                return i + 1 < len(folded) and folded[i + 1] not in _UNITS \
                    and not folded[i + 1].isdigit()
            return folded[i - 1] in _ANCHORS
        if i == 0:
            # "جيت من طريق عناب": the verb, with where from. "جيت سالك": the place.
            return not (len(folded) > 1 and folded[1] in _AFTER_A_VERB)
        return folded[i - 1] in _ANCHORS


_UNITS = frozenset(fold_token(w) for w in (
    "دقيقه", "دقايق", "دقيقتين", "ساعه", "ساعات", "سياره", "سيارات", "شيكل", "شيقل", "كم",
    "متر", "كيلو", "الف", "باص", "باصات", "جنود", "جندي", "شباب", "سنه", "يوم", "ايام",
    "مساء", "صباحا", "ظهرا", "عصرا", "فجرا", "الصبح", "العصر", "بالليل", "راكب"))

_AFTER_A_VERB = frozenset(fold_token(w) for w in (
    "من", "ع", "علي", "عل", "عن", "الي", "ل", "مع", "في", "قبل", "بعد", "عند"))

_ANCHORS = frozenset(fold_token(w) for w in (
    "حاجز", "بوابه", "بوابات", "مدخل", "مداخل", "معبر", "دوار", "مفرق", "جسر",
    "طريق", "شارع", "نفق", "محسوم", "مفترق", "اشارات", "اشاره", "علي", "ع", "عند"))


def build(entries: list[tuple[str, int]], prior: dict[int, int] | None = None,
          weak: frozenset | set = frozenset()) -> Lexicon:
    """A lexicon from (surface name, place_id) pairs.

    Two places under one key: the one with more readings behind it is taken and
    the other is kept as a rival, so a reading can say it was a choice.
    """
    prior = prior or {}
    by_key: dict[tuple[str, ...], set[int]] = {}
    derived: dict[tuple[str, ...], set[int]] = {}
    for surface, pid in entries:
        k = key_of(surface)
        if not k or len(k) > MAX_WORDS or (len(k) == 1 and len(k[0]) < 2):
            continue
        by_key.setdefault(k, set()).add(pid)
        if len(k) > 1 and k[0] in _GENERIC:
            derived.setdefault(k[1:], set()).add(pid)
    for k, ids in derived.items():           # a derived key never overrides a written one
        if k not in by_key and not (len(k) == 1 and len(k[0]) < 3):
            by_key[k] = ids
    names = {k: tuple(sorted(ids, key=lambda p: (-prior.get(p, 0), p)))
             for k, ids in by_key.items()}
    return Lexicon(names=names, weak=frozenset(fold_token(normalize(w)) for w in weak))


# Names that are also ordinary words in these channels. Measured 2026-10-11 on
# 73 days of road messages: each was found mid-sentence more often as the word
# than as the place.
WEAK_NAMES = frozenset([
    "جيت",          # "I came": "جيت من طريق بزاريا"
    "الفحص",        # "the inspection"
    "البلد",        # "the town"
    "الجسر", "النفق", "الدوار", "المعبر", "المفرق", "الحاجز", "البوابه",
    "المدخل", "الطريق", "الشارع",
    "سير",          # "كثافة سير": traffic. Also a village east of Qalqilya.
    "الهيئة",       # folds to "هيه", which is also "it is": "هيه سالكه"
])


def assemble(places: list[tuple], aliases: list[tuple], road_aliases: list[tuple],
             prior: dict[int, int], towns: list[str] = ()) -> Lexicon:
    """The lexicon from the register's rows (pure; `load` reads them).

    places        (place_id, merged_into, servable, name_ar, name_en, v1 key, board names)
    aliases       (alias, place_id)                 place_alias, the general gazetteer
    road_aliases  (alias, place_id, kind)           road_alias, the road register's own
    towns         names of localities, cities and governorates
    A merged row's names are names of the row it merged into; a row hidden
    without a merge (a sentence v1 stored as a place) gives none.

    A town's name that CONTAINS a road name and is not one itself is read past:
    "رام الله" is not الرام, "عين يبرود" is not the Yabrud gate. Without this
    the word "رام" was Ar-Ram 3,402 times in 90,000 messages.
    """
    canon = {pid: (merged or pid) for pid, merged, *_ in places}
    live = {pid for pid, merged, servable, *_ in places if not merged and servable}
    own: list[tuple[str, int]] = []        # what a live row is called
    other: list[tuple[str, int]] = []      # everything that points at one
    weak = set(WEAK_NAMES)
    for pid, merged, _servable, ar, en, v1key, board in places:
        if canon[pid] in live:
            (other if merged else own).extend(
                (s, canon[pid]) for s in (ar, en, (v1key or "").replace("_", " "),
                                          *(board or ())) if s)
    other += [(a, canon[pid]) for a, pid in aliases if canon.get(pid) in live]
    for a, pid, kind in road_aliases:
        if canon.get(pid) in live:
            own.append((a, canon[pid]))
            if kind == "weak":
                weak.add(a)
    # v1 stored whole lines as names and aliases ("صره بحري", "يبرود سلواد انسحب
    # الجيش", "احوال طرق اريحا"). Kept as a name, the status word is swallowed
    # by the match and the line says nothing.
    other = [e for e in other if not _is_a_sentence(e[0])]
    entries = [(s, pid) for s, pid in own + other if set(key_of(s)) - _NOT_A_NAME]
    lex = build(entries, {canon.get(p, p): n for p, n in prior.items()}, weak)
    for town in towns:
        k = key_of(town)
        if 2 <= len(k) <= MAX_WORDS and k not in lex.names and any(
                k[a:b] in lex.names for a in range(len(k)) for b in range(a + 1, len(k) + 1)
                if b - a < len(k)):
            lex.names[k] = (0,)
    return lex


_TITLE_WORDS = frozenset(fold_token(w) for w in ("احوال", "طرق", "تحديث", "تحديثات"))


def _is_a_sentence(alias: str) -> bool:
    """A stored "name" that carries a status, a direction, a negator or a time
    word is a line somebody wrote, not what a place is called. "ديرشرف بدون"
    held as a name read "ديرشرف بدون جيش" as the army PRESENT."""
    from cascade.checkpoint_text import (CLEARING_WORDS, DIRECTION_WORDS, EXIST_NEG,
                                         FLOW_WORDS, NEGATORS, PRESENCE_WORDS,
                                         QUESTION_OPENERS, _NOW, _lex)
    stop = NEGATORS | EXIST_NEG | _NOW | QUESTION_OPENERS | CLEARING_WORDS | {
        "في", "فيه", "مع", "بس", "لسا", "كان", "صار", "اخر", "جميع", "كل"}
    toks = normalize(alias).split()
    return any(_lex(t, FLOW_WORDS) or _lex(t, PRESENCE_WORDS) or _lex(t, DIRECTION_WORDS)
               or t in stop or fold_token(t) in _TITLE_WORDS for t in toks)


# A row named only this ("Checkpoint", "Check Point": OCHA's unnamed points) has
# no name a message could mean.
_NOT_A_NAME = frozenset(["checkpoint", "check", "point"])


def load(cur) -> Lexicon:
    """The register as it stands in the database."""
    cur.execute("""
        SELECT place_id, merged_into, servable, name_ar, name_en,
               source_refs->>'v1_canonical_key',
               ARRAY(SELECT jsonb_array_elements_text(
                       CASE WHEN jsonb_typeof(attrs->'palhub_names') = 'array'
                            THEN attrs->'palhub_names' ELSE '[]'::jsonb END))
          FROM place WHERE kind::text = ANY(%s)""", (list(ROAD_KINDS),))
    places = cur.fetchall()
    cur.execute("""
        SELECT a.alias_norm, a.place_id FROM place_alias a JOIN place p USING (place_id)
         WHERE p.kind::text = ANY(%s) AND a.confidence > 0""", (list(ROAD_KINDS),))
    aliases = cur.fetchall()
    cur.execute("SELECT to_regclass('road_alias') IS NOT NULL")
    road_aliases = []
    if cur.fetchone()[0]:
        cur.execute("SELECT alias, place_id, kind FROM road_alias")
        road_aliases = cur.fetchall()
    cur.execute("""
        SELECT place_id, count(*) FROM state_observation
         WHERE state_kind = 'checkpoint_flow' AND modality = 'assertion'
           AND observed_at > now() - interval '90 days' GROUP BY 1""")
    prior = dict(cur.fetchall())
    cur.execute("""SELECT name_ar FROM place
                    WHERE kind::text IN ('locality', 'governorate', 'district_mandate')
                      AND name_ar IS NOT NULL""")
    return assemble(places, aliases, road_aliases, prior, [r[0] for r in cur.fetchall()])
