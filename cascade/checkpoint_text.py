"""Structured reading of a checkpoint report line.

v1 collapses every line to ONE status value on ONE axis. Measured against its
own 92,719 stored updates, that costs accuracy in four separate ways:

  1. QUESTIONS BECOME FACTS. 5,485 updates (5.9%) come from lines containing a
     question mark, and 4,566 of those were recorded as `open`. "بوابة دورا
     فاتحة؟" ("is the Dura gate open?") is stored as evidence that it IS open.
     The bias runs the wrong way: people ask about checkpoints they fear are
     closed, so the false evidence is concentrated exactly where being wrong
     costs the most.

  2. DIRECTION IS INVERTED ON TWO-FACT LINES. 527 updates mention both
     directions. "عنبتا تفتيش للخارج، سالك للداخل" ("Anabta: inspection
     outbound, flowing inbound") was stored as `inspection` + direction
     `inbound` — the outbound fact attached to the inbound direction, and the
     inbound fact discarded. Inverted is worse than missing.

  3. PRESENCE OVERWRITES FLOW. `idf` and `open` flip on the same place within
     10 minutes 1,889 times. They are not competing values — they are answers
     to different questions. "عين شبلي فتحت مع تفتيش" ("Ein Shibli opened,
     with inspection") became `inspection`, losing the fact that it is passable.
     A traveller asking "can I get through?" needs the flow axis; the presence
     axis is a separate, also-true fact.

  4. THE NOUN IS READ AS A STATUS. v1 maps `حاجز` — the ordinary word for
     "checkpoint" — to `idf`, so merely NAMING a checkpoint reports soldiers at
     it ("اودلا حاجز" -> idf). `سيارات` ("cars") likewise. Both are removed
     here; only genuinely deictic phrases ("نصب حاجز", "حاجز طيار") count.

So a line is read into a `Reading`: a modality, plus zero or more `Fact`s, each
scoped to a direction and carrying the two axes separately.

NOTHING IS DISCARDED. A question still becomes a stored observation — tagged
`question`, excluded from belief, retained as a demand signal (which places
people worry about is worth knowing). The no-data-loss rule applies to parse
failures too: an unreadable line is kept with modality `unparsed`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from resolve.arabic import normalize

# ── axes ─────────────────────────────────────────────────────────────────────
# FLOW is ordered and mutually exclusive: a road has one throughput state.
# Severity ranks it so the most restrictive report in a clause wins, and so a
# serving layer can answer "passable?" without knowing the vocabulary.
FLOW_SEVERITY = {"open": 0, "slow": 1, "congested": 2, "closed": 3}

# PRESENCE is a SET, not a scale. Soldiers and police can both be there, and
# either can coexist with any flow state.
PRESENCE_VALUES = ("idf", "police", "settlers", "inspection")

DIRECTIONS = ("inbound", "outbound", "both")

FLOW_WORDS: dict[str, str] = {
    # open
    "سالك": "open", "سالكه": "open", "سالكين": "open", "سالكه": "open",
    "مفتوح": "open", "مفتوحه": "open", "مفتوحين": "open",
    "فاتح": "open", "فاتحه": "open", "فتح": "open", "فتحت": "open",
    "فتحوا": "open", "فاتحين": "open", "انفتح": "open", "نظيف": "open",
    "ماشي": "open", "ماشيه": "open", "طبيعي": "open", "عادي": "open",
    # slow
    "بطيء": "slow", "بطئ": "slow", "بطيئ": "slow", "بطيه": "slow",
    "متقطع": "slow",
    # NOT "شوي". It is a temporal quantifier ("a while", "shortly"), not a
    # speed: "دير شرف فتح من شوي" is "Deir Sharaf opened A WHILE AGO" and
    # "شوي وبتسلك" is "it'll flow SHORTLY" — both read as `slow`, and the
    # backtest scored `slow` at 0 correct out of 16 because of it.
    # congested
    "زحمه": "congested", "ازمه": "congested", "مزحوم": "congested",
    "ضاغط": "congested", "ضغط": "congested", "مزدحم": "congested",
    "مزدحمه": "congested", "ازدحام": "congested", "اختناق": "congested",
    "وقفه": "congested", "واقف": "congested", "واقفه": "congested",
    "كثافه": "congested", "كثافة": "congested", "تكدس": "congested",
    # closed
    "مغلق": "closed", "مغلقه": "closed", "مغلقين": "closed",
    "مقفل": "closed", "مقفله": "closed", "مسكر": "closed", "مسكره": "closed",
    "موقوف": "closed", "مسدود": "closed", "مسدوده": "closed",
    "سكروا": "closed", "سكر": "closed", "اغلاق": "closed", "مغلقه": "closed",
}

PRESENCE_WORDS: dict[str, str] = {
    "جيش": "idf", "عسكر": "idf", "مداهمه": "idf", "دبابات": "idf",
    "جنود": "idf", "عسكري": "idf",
    "شرطه": "police", "دوريه": "police", "الشرطه": "police",
    "مستوطنين": "settlers", "مستوطنون": "settlers", "مستوطن": "settlers",
    "قطعان": "settlers",
    "تفتيش": "inspection", "يفتشو": "inspection", "بفتشو": "inspection",
    "تدقيق": "inspection", "هويات": "inspection",
}

# Multi-word forms. Checked before single tokens so "نصب حاجز" is read as a
# newly-erected obstacle while a bare "حاجز" stays what it is — a noun.
PHRASES: list[tuple[str, str, str]] = [
    # (phrase, axis, value)
    ("مش سالك", "flow", "closed"), ("مش فاتح", "flow", "closed"),
    ("غير سالك", "flow", "closed"), ("مو سالك", "flow", "closed"),
    ("مش ماشي", "flow", "closed"), ("ما بيمشي", "flow", "closed"),
    ("نصب حاجز", "presence", "idf"), ("عمل حاجز", "presence", "idf"),
    ("حاجز طيار", "presence", "idf"), ("حواجز طياره", "presence", "idf"),
    ("فيه جيش", "presence", "idf"), ("عليه جيش", "presence", "idf"),
    ("سيارات الجيش", "presence", "idf"), ("سياره جيش", "presence", "idf"),
    ("فيه شرطه", "presence", "police"), ("سياره شرطه", "presence", "police"),
    ("دوريه شرطه", "presence", "police"),
    ("تفتيش هويات", "presence", "inspection"), ("تفتيش دقيق", "presence", "inspection"),
    ("فيه ضغط", "flow", "congested"), ("فيه زحمه", "flow", "congested"),
    ("في ازمه", "flow", "congested"), ("كثافه سير", "flow", "congested"),
    ("حركه خفيفه", "flow", "open"), ("سير طبيعي", "flow", "open"),
    ("في حاجز", "presence", "idf"), ("فيه حاجز", "presence", "idf"),
]

# Withdrawal / removal. These CLEAR presence rather than assert it, and usually
# imply the obstacle is gone. v1 has no concept of this, so "انسحب الجيش عن صرة"
# ("the army withdrew from Sarra") was stored as a place NAME.
CLEARING_WORDS = frozenset([
    "انسحب", "انسحبوا", "انسحبت", "شالو", "شالوا", "شال", "رفعوا", "رفع",
    "ازالوا", "فكوا", "راح", "راحت", "راحوا", "غادر", "غادروا", "تركوا",
    "خلص", "خلصت", "انتهي", "انتهت", "فتحوه", "فتحوها",
])

# "لا" is deliberately ABSENT. In Palestinian Arabic an adjective is negated
# with "مش", not "لا"; before a status word "لا" is nearly always the discourse
# marker "no" answering someone — "لا مسكر" is "no, it's closed", which the
# negation rule inverted into "open".
NEGATORS = frozenset(["مش", "ما", "مو", "بدون", "بلا", "غير"])

# "ما زال" / "لا زالت" mean "STILL", not "not". Reading the particle as a
# negator turned "النبي الياس ما زال مغلق" ("Nabi Elias is still closed") into
# open — an inversion on exactly the message that most needed to be right.
CONTINUATIVES = frozenset(["زال", "زالت", "زالوا", "زالا", "يزال", "تزال"])

DIRECTION_WORDS: dict[str, str] = {
    "للداخل": "inbound", "الداخل": "inbound", "داخل": "inbound",
    "للدخول": "inbound", "دخول": "inbound", "جوا": "inbound", "لجوا": "inbound",
    "الداخلين": "inbound", "الوارد": "inbound",
    "للخارج": "outbound", "الخارج": "outbound", "خارج": "outbound",
    "للخروج": "outbound", "خروج": "outbound", "برا": "outbound", "لبرا": "outbound",
    "الخارجين": "outbound", "الصادر": "outbound",
    "بالاتجاهين": "both", "الاتجاهين": "both", "اتجاهين": "both",
    "الاتجاهات": "both", "الطرفين": "both",
}

# Emoji are used by several channels as generic ATTENTION markers, not status:
# "🔴عنبتا تفتيش للخارج، سالك للداخل" is red-dotted but reports a flowing lane.
# So emoji are consulted only when a clause carries no status word at all.
EMOJI_FLOW = {"✅": "open", "🟢": "open", "🟩": "open", "✔": "open", "☑": "open",
              "🟠": "congested", "🟧": "congested", "🟡": "slow", "🟨": "slow",
              "❌": "closed", "⛔": "closed", "🚫": "closed", "🛑": "closed"}

# Interrogatives that open a question even with no "؟" typed.
QUESTION_OPENERS = frozenset([
    "شو", "وش", "ايش", "كيف", "كيفك", "وين", "مين", "هل", "ليش", "متي",
    "شومع", "شومعليش", "امتي", "قديش", "بكم",
])
QUESTION_PHRASES = ("شو وضع", "شو اخبار", "شو الوضع", "حدا يعرف", "مين بيعرف",
                    "حدا بيعرف", "بدنا نعرف", "بدي اعرف", "في حدا", "شو صار")

_QMARK = re.compile(r"[؟?]")
# Clause boundaries. NOT ":" — "الداخل: سالك" must stay one clause, because the
# direction binds to the status across the colon.
#
# A STANDALONE waw is split on; a PREFIXED one ("وسالك") is not, because و opens
# many ordinary words (وادي, وزارة) and splitting inside them would separate a
# status from its direction. Prefixed waw is handled at lookup time instead.
_CLAUSE_SPLIT = re.compile(r"[،؛,\n\r]+|\s+[-–—]\s+|\s+و\s+")

# Article shapes, longest first — same set as resolve.arabic, applied here at
# LOOKUP time: "للمستوطنين" must find "مستوطنين" in the presence table.
_ARTICLE = re.compile(r"^(?:لل|[بلكفو]ال|ال)")


# Emoji and variation selectors survive normalize() (they are not punctuation),
# so "سالك✅️" arrives as ONE token and misses the lexicon entirely — the line
# then falls through to the emoji branch or to `unparsed`. Channels attach these
# constantly, so stripping them at tokenisation is worth more than any rule.
_NONWORD = re.compile(r"[^\w؀-ۿ]+", re.UNICODE)


def tokens(clause: str) -> list[str]:
    """Lexicon-ready tokens: emoji and stray symbols removed, empties dropped."""
    return [t for t in (_NONWORD.sub("", w) for w in clause.split()) if t]


def _lex(tok: str, table: dict[str, str]) -> str | None:
    """Look a token up, retrying without a fused article or conjunction.

    Written as a fallback chain rather than by pre-stripping every token: the
    bare form is authoritative where it exists, and stripping unconditionally
    would turn "لا" into "" and mangle names that merely start with these
    letters.
    """
    if tok in table:
        return table[tok]
    stripped = _ARTICLE.sub("", tok)
    if len(stripped) >= 3 and stripped in table:
        return table[stripped]
    if len(tok) >= 4 and tok[0] == "و" and tok[1:] in table:
        return table[tok[1:]]
    return None


@dataclass
class Fact:
    """One axis-value scoped to one direction."""
    direction: str                # inbound | outbound | both
    axis: str                     # flow | presence
    value: str                    # open/slow/congested/closed | idf/police/...
    direction_explicit: bool      # False when inferred rather than stated
    confidence: float
    clause: str


@dataclass
class Reading:
    modality: str                 # assertion | question | unparsed
    facts: list[Fact] = field(default_factory=list)
    cleared: bool = False         # a withdrawal/removal was reported
    note: str | None = None

    @property
    def is_evidence(self) -> bool:
        return self.modality == "assertion" and bool(self.facts)

    def flow_for(self, direction: str) -> Fact | None:
        """Most restrictive flow fact applying to `direction`."""
        cands = [f for f in self.facts if f.axis == "flow"
                 and (f.direction == direction or f.direction == "both")]
        if not cands:
            return None
        return max(cands, key=lambda f: FLOW_SEVERITY.get(f.value, 0))

    def presence_for(self, direction: str) -> list[str]:
        return sorted({f.value for f in self.facts if f.axis == "presence"
                       and (f.direction == direction or f.direction == "both")})

    def absence_for(self, direction: str) -> list[str]:
        """Who was reported NOT to be there. Its own axis, because "nobody said
        the army is here" and "somebody said the army is not here" are utterly
        different facts and only the second one is evidence."""
        return sorted({f.value for f in self.facts if f.axis == "absence"
                       and (f.direction == direction or f.direction == "both")})


def _presplit_waw(raw: str) -> str:
    """Insert a clause break before a waw-prefixed status word — but only where
    it genuinely separates two directional clauses.

    "حوارة سالك للداخل ومغلق للخارج"  -> two clauses (in=open, out=closed)
    "جبع ازمة وتفتيش للخارج"          -> ONE clause; the single للخارج governs both

    The discriminator is a direction word on BOTH sides of the waw. Splitting
    unconditionally would strand "ازمة" with no direction; never splitting
    would collapse the first example to a single most-restrictive value.
    """
    toks = raw.split()
    norms = [normalize(t) for t in toks]
    dir_pos = [i for i, n in enumerate(norms) if _lex(n, DIRECTION_WORDS)]
    if len(dir_pos) < 2:
        return raw
    out: list[str] = []
    for i, t in enumerate(toks):
        n = norms[i]
        if (i > 0 and len(n) >= 4 and n.startswith("و")
                and (_lex(n[1:], FLOW_WORDS) or _lex(n[1:], PRESENCE_WORDS))
                and any(p < i for p in dir_pos) and any(p > i for p in dir_pos)):
            out.append("،")
        out.append(t)
    return " ".join(out)


def _is_question(raw: str, toks: list[str]) -> bool:
    if _QMARK.search(raw):
        return True
    joined = " ".join(toks)
    if any(p in joined for p in QUESTION_PHRASES):
        return True
    if any(t in QUESTION_OPENERS for t in toks[:2]):
        return True
    # Disjunctive question: "بوابة بورين فاتحه ولا مسكره" — "…open OR closed?".
    # Two opposing flow words joined by "ولا" is a request for the status, not
    # a report of it, and often carries no question mark.
    if "ولا" in toks:
        vals = {v for v in (_lex(t, FLOW_WORDS) for t in toks) if v}
        if len(vals) >= 2:
            return True
    # An interrogative anywhere in a SHORT line: "عطارة للخارج كيف" is a
    # question with the particle last. In a long line the same word is usually
    # part of a relative clause ("...حسب ما كيف"), so the length bound matters.
    return len(toks) <= 6 and any(t in QUESTION_OPENERS for t in toks)


def _direction_positions(toks: list[str]) -> list[tuple[int, str]]:
    out = []
    for i, t in enumerate(toks):
        d = _lex(t, DIRECTION_WORDS)
        if d:
            out.append((i, d))
    return out


def _bind_direction(pos: int, dirs: list[tuple[int, str]]) -> tuple[str, bool]:
    """Attach a status at token `pos` to one of the directions in its clause.

    Nearest wins; a tie goes to the direction that FOLLOWS the status, because
    the postfix order ("سالك للداخل") is the common one in these channels. The
    prefix order ("الداخل: سالك") almost always carries a separator and has
    been split into its own clause before reaching here.
    """
    if not dirs:
        return "both", False
    if len({d for _, d in dirs}) == 1:
        return dirs[0][1], True
    if pos < 0:
        return "both", False
    best = min(dirs, key=lambda pd: (abs(pd[0] - pos), 0 if pd[0] > pos else 1))
    return best[1], True


def _negated(toks: list[str], i: int) -> bool:
    """Is toks[i] within the scope of a negator?

    A NEGATOR IS CONSUMED BY THE FIRST LEXICON WORD IT REACHES. Without that,
    "المربعة بدون جيش سالكة" ("Al-Murabba'a, without army, FLOWING") read the
    بدون two tokens back from سالكة and inverted the road to CLOSED — the most
    expensive error this parser can make, produced by a line that is actually
    good news twice over. The بدون belongs to جيش, which sits between them.
    """
    for j in range(max(0, i - 2), i):
        if toks[j] not in NEGATORS:
            continue
        # "ما زال مغلق" — the particle is continuative, not negating.
        if j + 1 < len(toks) and toks[j + 1] in CONTINUATIVES:
            continue
        # Already spoken for by something closer to it.
        if any(_lex(t, FLOW_WORDS) or _lex(t, PRESENCE_WORDS)
               for t in toks[j + 1:i]):
            continue
        return True
    return False


_FLIP = {"open": "closed", "closed": "open", "congested": "open", "slow": "open"}


def _scan_clause(clause: str, raw_clause: str) -> tuple[list[tuple[str, str, float, int]], bool]:
    """Return [(axis, value, confidence, token_pos)] found in a clause, and
    whether a clearing verb fired. `token_pos` is -1 where the finding has no
    single anchor token (emoji, clause-level inference)."""
    toks = tokens(clause)
    out: list[tuple[str, str, float, int]] = []
    consumed: set[int] = set()

    # Phrases first — they override the single tokens they contain.
    #
    # Matched on TOKEN boundaries, never as raw substrings. "حومش سالك"
    # ("Homesh is flowing") contains the characters of "مش سالك" ("not
    # flowing") straddling a word boundary; substring matching read that as
    # closed and inverted the meaning of a frequently-reported checkpoint.
    padded = " " + " ".join(toks) + " "
    for phrase, axis, value in PHRASES:
        if f" {phrase} " not in padded:
            continue
        pt = phrase.split()
        at = -1
        for i in range(len(toks) - len(pt) + 1):
            if toks[i:i + len(pt)] == pt:
                consumed.update(range(i, i + len(pt)))
                at = i if at < 0 else at
        out.append((axis, value, 0.92, at))

    cleared = any(t in CLEARING_WORDS or (t[:1] == "و" and t[1:] in CLEARING_WORDS)
                  for t in toks)

    for i, t in enumerate(toks):
        if i in consumed:
            continue
        flow = _lex(t, FLOW_WORDS)
        if flow:
            if _negated(toks, i):
                out.append(("flow", _FLIP.get(flow, flow), 0.80, i))
            else:
                out.append(("flow", flow, 0.90, i))
            continue
        pres = _lex(t, PRESENCE_WORDS)
        if pres:
            # "ما في جيش" / "بدون تفتيش" asserts ABSENCE, and absence is
            # RECORDED, not discarded.
            #
            # It used to be dropped on the floor, and P1.3 measured what that
            # cost: 1,752 of 6,188 presence mentions in the corpus are negated
            # — 28.31% — and they are the only statements of absence anybody
            # ever makes. Without them `present` was the ONLY value presence
            # could ever take, so the persistence fit returned 1.00 at every
            # lag (a value that cannot change cannot decay), the state was
            # `unknown` for 99.5% of places, and there was nothing a second
            # report could contradict.
            #
            # "المربعة بدون جيش سالكة" is not an absence of information. It is
            # somebody standing at the checkpoint telling you the army is not
            # there, which is exactly what a family planning a journey wants.
            if _negated(toks, i):
                out.append(("absence", pres, 0.86, i))
            elif cleared:
                # A withdrawal verb somewhere in the line is weaker evidence:
                # it may attach to a different entity than this one.
                out.append(("absence", pres, 0.78, i))
            else:
                out.append(("presence", pres, 0.88, i))

    # Predicative "حاجز": the bare noun is not a status (v1's biggest false
    # positive), but a line that ENDS on it — "عابود حاجز", "المربعه في حاجز" —
    # is reporting that an obstacle is there, not naming one.
    if not out and toks and toks[-1] in ("حاجز", "حواجز"):
        out.append(("presence", "idf", 0.70, len(toks) - 1))

    # Emoji only where the words said nothing.
    if not out:
        for ch, v in EMOJI_FLOW.items():
            if ch in raw_clause:
                out.append(("flow", v, 0.65, -1))
                break

    # A clearing verb with no other flow signal means the obstacle is gone.
    if cleared and not any(a == "flow" for a, _, _, _ in out):
        out.append(("flow", "open", 0.72, -1))
    return out, cleared


def read(text: str | None) -> Reading:
    """Parse one report line into a modality plus per-direction facts."""
    if not text or not text.strip():
        return Reading(modality="unparsed", note="empty")

    raw = text.strip()
    norm_all = normalize(raw)
    if not norm_all:
        return Reading(modality="unparsed", note="no text after normalisation")

    if _is_question(raw, tokens(norm_all)):
        return Reading(modality="question", note="interrogative — not evidence")

    facts: list[Fact] = []
    any_clear = False
    for raw_clause in _CLAUSE_SPLIT.split(_presplit_waw(raw)):
        if not raw_clause or not raw_clause.strip():
            continue
        clause = normalize(raw_clause)
        if not clause:
            continue
        dirs = _direction_positions(tokens(clause))
        found, cleared = _scan_clause(clause, raw_clause)
        any_clear = any_clear or cleared
        for axis, value, conf, pos in found:
            direction, explicit = _bind_direction(pos, dirs)
            facts.append(Fact(direction=direction, axis=axis, value=value,
                              direction_explicit=explicit, confidence=conf,
                              clause=raw_clause.strip()[:160]))

    if not facts:
        return Reading(modality="unparsed", cleared=any_clear,
                       note="no status vocabulary found")

    # Collapse duplicates, keeping the most confident instance of each
    # (direction, axis, value).
    best: dict[tuple[str, str, str], Fact] = {}
    for f in facts:
        k = (f.direction, f.axis, f.value)
        if k not in best or f.confidence > best[k].confidence:
            best[k] = f

    # One flow value per direction: the most restrictive wins. Two flow words in
    # one clause ("ازمه" + "سالك") mean the tighter constraint is the real one.
    #
    # presence AND absence both pass through: they are a SET, not a scale, and
    # "police here, army not here" is one coherent report of two facts.
    kept: list[Fact] = [f for f in best.values()
                        if f.axis in ("presence", "absence")]
    for d in DIRECTIONS:
        flows = [f for f in best.values() if f.axis == "flow" and f.direction == d]
        if flows:
            kept.append(max(flows, key=lambda f: FLOW_SEVERITY.get(f.value, 0)))

    return Reading(modality="assertion", facts=kept, cleared=any_clear)
