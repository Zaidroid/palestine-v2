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
    # Dialect for "jammed", absent until a recall sample turned it up in lines
    # v1 had read and we had not: "المشاة زاطم", "يعني مازمة عالحمرا".
    "زاطم": "congested", "زاطمه": "congested", "مزطوم": "congested",
    "زطمه": "congested", "مازمه": "congested",
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
    # مستوطين — the ن dropped — is how it is actually typed mid-incident.
    "مستوطنين": "settlers", "مستوطنون": "settlers", "مستوطن": "settlers",
    "مستوطين": "settlers", "قطعان": "settlers",
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
    # محسوم — the Hebrew loanword (מחסום) these channels use constantly and
    # this parser did not know at all. It is a NOUN meaning "checkpoint", so
    # the same rule applies as to حاجز: only the forms that say one was PUT
    # THERE are read as presence. A bare "اللبن الشرقي محسوم" is left alone,
    # because it is genuinely ambiguous between "there is a checkpoint here"
    # and "the road is blocked", and v1 resolves that ambiguity by asserting
    # `closed` — which is a caution invented from a noun.
    ("حطو محسوم", "presence", "idf"), ("حطوا محسوم", "presence", "idf"),
    ("نصب محسوم", "presence", "idf"), ("في محسوم", "presence", "idf"),
    ("فيه محسوم", "presence", "idf"), ("محسوم طيار", "presence", "idf"),
    ("حطو حاجز", "presence", "idf"), ("حطوا حاجز", "presence", "idf"),
    ("فيه جيش", "presence", "idf"), ("عليه جيش", "presence", "idf"),
    ("سيارات الجيش", "presence", "idf"), ("سياره جيش", "presence", "idf"),
    ("فيه شرطه", "presence", "police"), ("سياره شرطه", "presence", "police"),
    ("دوريه شرطه", "presence", "police"),
    ("تفتيش هويات", "presence", "inspection"), ("تفتيش دقيق", "presence", "inspection"),
    ("فيه ضغط", "flow", "congested"), ("فيه زحمه", "flow", "congested"),
    ("في ازمه", "flow", "congested"), ("كثافه سير", "flow", "congested"),
    ("حركه خفيفه", "flow", "open"), ("سير طبيعي", "flow", "open"),
    ("في حاجز", "presence", "idf"), ("فيه حاجز", "presence", "idf"),
    # "الجيش تحت جسر اودلا ومنعو المرور في الاتجاهين" — passage FORBIDDEN is a
    # closure, and none of these words is a flow adjective, so the line
    # recorded soldiers and lost the fact that nobody can get through.
    ("منع المرور", "flow", "closed"), ("منعو المرور", "flow", "closed"),
    ("منعوا المرور", "flow", "closed"), ("ممنوع المرور", "flow", "closed"),
    ("المرور ممنوع", "flow", "closed"),
    # The waw-prefixed forms are separate entries because "ومنعو المرور" is one
    # token and the phrase matcher compares whole tokens.
    ("ومنع المرور", "flow", "closed"), ("ومنعو المرور", "flow", "closed"),
    ("ومنعوا المرور", "flow", "closed"),
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
    # Single fused ل, no article: "جبع شرطة لداخل الرام". _ARTICLE strips لل
    # but not a bare ل, so these missed the table and the report served as
    # direction=both — overcovering the direction nobody reported on.
    "لداخل": "inbound", "لخارج": "outbound",
    "للخارج": "outbound", "الخارج": "outbound", "خارج": "outbound",
    "للخروج": "outbound", "خروج": "outbound", "برا": "outbound", "لبرا": "outbound",
    "الخارجين": "outbound", "الصادر": "outbound",
    "بالاتجاهين": "both", "الاتجاهين": "both", "اتجاهين": "both",
    "الاتجاهات": "both", "الطرفين": "both",
    # "عين شبلي بطيء عالجهتين" — both sides. ع is not in the article class, so
    # the fused forms need their own entries.
    "الجهتين": "both", "بالجهتين": "both", "عالجهتين": "both",
    "للجهتين": "both", "عالاتجاهين": "both",
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
                    "حدا بيعرف", "بدنا نعرف", "بدي اعرف", "في حدا", "شو صار",
                    # A DISPUTE about the status is a request for it, not a
                    # report of it: "الي بحكي انو عورتا سالك يعطينا دليل" —
                    # "whoever says Awarta is open, give us proof" — was
                    # asserting the jam and the inspection it went on to doubt.
                    "يعطينا دليل", "اعطونا دليل", "مين متاكد", "مش متاكد",
                    "حدا متاكد")

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

# Three or more of the same letter in a row is emphasis, never spelling.
# Two is left alone: real Arabic doubles letters (شدة is written out in these
# channels as an actual repeat often enough that collapsing pairs would damage
# genuine words).
_ELONGATED = re.compile(r"(.)\1{2,}")


def tokens(clause: str) -> list[str]:
    """Lexicon-ready tokens: emoji and stray symbols SPLIT ON, empties dropped.

    Split, not stripped: "سولار❌بنزين❌" is one whitespace-token, and deleting
    the emoji fused it into سولاربنزين — a word that matches nothing, so the
    fuel guard below never saw the fuel nouns and the ❌ served a crossing as
    closed. An emoji between two words separates them exactly as a space does.
    """
    out: list[str] = []
    for w in clause.split():
        out.extend(p for p in _NONWORD.split(w) if p)
    return out


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
    # Elongation for emphasis: "محسوووم", "سالكككك", "مسكررر". normalize()
    # strips tatweel but not a genuinely repeated letter, so these missed the
    # lexicon entirely and the line fell through to `unparsed`. Collapsed only
    # as a LAST resort, after the literal forms have had their chance, so a
    # real word with a legitimate doubling is never rewritten out from under a
    # direct hit.
    collapsed = _ELONGATED.sub(r"\1", tok)
    if collapsed != tok and len(collapsed) >= 3:
        if collapsed in table:
            return table[collapsed]
        stripped = _ARTICLE.sub("", collapsed)
        if len(stripped) >= 3 and stripped in table:
            return table[stripped]
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


def _collapse_enumerated_both(dirs: list[tuple[int, str]],
                              status_pos: list[int]) -> list[tuple[int, str]]:
    """"للي داخل والخارج" — two ADJACENT, opposite direction words are one
    statement of "both", not two competing anchors. Left as a pair, the status
    bound to whichever was nearer and the other half of the closure was lost —
    "جسر اودلا مسكر للي داخل والخارج" served closed-inbound and unknown-outbound.

    Only when the pair is one-sided, though. In "سالكه للداخل وخارج ازمه" the
    two direction words are also adjacent and opposite, but statuses stand on
    BOTH sides — each direction anchors its own status, and collapsing them
    would average two different lanes into one value. An enumerated pair has
    all its statuses on one side; a pair of anchors is surrounded.
    """
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(dirs):
        if (i + 1 < len(dirs)
                and dirs[i + 1][0] - dirs[i][0] == 1
                and {dirs[i][1], dirs[i + 1][1]} == {"inbound", "outbound"}
                and not (any(p < dirs[i][0] for p in status_pos)
                         and any(p > dirs[i + 1][0] for p in status_pos))):
            out.append((dirs[i][0], "both"))
            i += 2
        else:
            out.append(dirs[i])
            i += 1
    return out


def _assign_directions(found: list[tuple[str, str, float, int]],
                       dirs: list[tuple[int, str]]) -> list[tuple[str, bool]]:
    """Attach each status in a clause to a direction, clause-wide.

    The old rule bound each status independently — nearest direction, tie to
    the FOLLOWING one, on the theory that the postfix order ("سالك للداخل") is
    the common one and the prefix order always carries a separator. It does
    not: "بيت ايل الداخل سالك الخارج تفتيش" is the bare topic-comment order,
    and the tie sent سالك to الخارج — serving OPEN for the direction the text
    says is under inspection, v1's inversion class recreated in v2. Worse, in
    "العبيدية للداخل سالك للخارج ازمة" the misbound `open` then lost the
    severity collapse against `congested` and the inbound fact vanished.

    Two passes fix both orders without preferring either: statuses with a
    UNIQUE nearest direction bind first and claim it; a tied status then takes
    the tied candidate no other status claimed. "سالك للداخل تفتيش للخارج" and
    "الداخل سالك الخارج تفتيش" now both come out right, because in each the
    unambiguous status pins its direction and the ambiguous one takes what
    remains.
    """
    dirs = _collapse_enumerated_both(dirs, [p for (_, _, _, p) in found if p >= 0])
    n = len(found)
    if not dirs:
        return [("both", False)] * n
    if len({d for _, d in dirs}) == 1:
        return [(dirs[0][1], True)] * n

    result: list[tuple[str, bool] | None] = [None] * n
    claimed: set[int] = set()
    ties: list[tuple[int, list[int]]] = []          # (fact idx, tied dir idxs)

    for fi, (_axis, _value, _conf, pos) in enumerate(found):
        if pos < 0:
            result[fi] = ("both", False)
            continue
        ranked = sorted(range(len(dirs)), key=lambda di: abs(dirs[di][0] - pos))
        best = ranked[0]
        tied = [di for di in ranked
                if abs(dirs[di][0] - pos) == abs(dirs[best][0] - pos)]
        if len(tied) == 1:
            result[fi] = (dirs[best][1], True)
            claimed.add(best)
        else:
            ties.append((fi, tied))

    for fi, tied in ties:
        free = [di for di in tied if di not in claimed]
        if len(free) == 1:
            pick = free[0]
        else:
            # Still ambiguous: keep the old postfix preference as the last
            # resort — among the tied, the direction that follows the status.
            pos = found[fi][3]
            pick = min(tied, key=lambda di: 0 if dirs[di][0] > pos else 1)
        result[fi] = (dirs[pick][1], True)
        claimed.add(pick)

    return [r if r is not None else ("both", False) for r in result]


def _negated(toks: list[str], i: int) -> bool:
    """Is toks[i] within the scope of a negator?

    A NEGATOR IS CONSUMED BY THE FIRST LEXICON WORD IT REACHES. Without that,
    "المربعة بدون جيش سالكة" ("Al-Murabba'a, without army, FLOWING") read the
    بدون two tokens back from سالكة and inverted the road to CLOSED — the most
    expensive error this parser can make, produced by a line that is actually
    good news twice over. The بدون belongs to جيش, which sits between them.
    """
    for j in range(max(0, i - 2), i):
        # "لا" stays out of NEGATORS ("لا مسكر" is "no, it's closed") — but
        # لا/ولا DIRECTLY before an existential في/فيه is the one shape where
        # it negates: "ولا في مستوطنين" is "and there are NO settlers", and it
        # was being read as settlers PRESENT — a caution invented from its own
        # reassurance, the exact inversion P2.4 exists to prevent.
        la_fi = (toks[j] in ("لا", "ولا") and j + 1 < len(toks)
                 and toks[j + 1] in ("في", "فيه"))
        if toks[j] not in NEGATORS and not la_fi:
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

# A clause about one of these is about FUEL, whatever its emoji say.
_FUEL_NOUNS = frozenset(["سولار", "بنزين", "وقود", "غاز", "كاز", "ديزل",
                         "محطه", "محطات", "محروقات"])


def _cleared_nearby(toks: list[str], i: int) -> bool:
    """A clearing verb within two tokens of toks[i], either side."""
    lo, hi = max(0, i - 2), min(len(toks), i + 3)
    return any(toks[j] in CLEARING_WORDS
               or (toks[j][:1] == "و" and toks[j][1:] in CLEARING_WORDS)
               for j in range(lo, hi) if j != i)


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
        # PHRASES MUST RESPECT NEGATION, exactly as single tokens do.
        #
        # They did not, and "ما فيه جيش على الحاجز" — somebody standing there
        # saying the army is NOT present — was read as `presence: idf`. The
        # phrase "فيه جيش" matched inside its own negation. Two costs, and the
        # second is the larger: a caution is manufactured from good news, AND
        # the absence is thrown away, when absence is the only statement of
        # "they have gone" anybody ever makes (P1.3 measured 28.31% of presence
        # mentions as negated).
        #
        # Found by adding "في محسوم" to this table: "يعني ما في محسوم ع جبع"
        # turned up in the recall sample reading as soldiers present. The
        # existing "فيه جيش" and "فيه شرطه" had the same hole all along.
        if at >= 0 and _negated(toks, at):
            # Mirror the single-token path: a negated presence is an ABSENCE
            # sighting; a negated flow reading flips.
            if axis == "presence":
                out.append(("absence", value, 0.86, at))
            else:
                out.append(("flow", _FLIP.get(value, value), 0.80, at))
            continue
        out.append((axis, value, 0.92, at))

    cleared = any(t in CLEARING_WORDS or (t[:1] == "و" and t[1:] in CLEARING_WORDS)
                  for t in toks)

    for i, t in enumerate(toks):
        if i in consumed:
            continue
        flow = _lex(t, FLOW_WORDS)
        if flow:
            # "الجيش واقف على المدخل" — the ARMY is standing there, not the
            # traffic. واقف is a flow word only when its subject is the road;
            # with a presence noun immediately before it, the presence reading
            # (recorded separately from that noun) is the whole content, and
            # the flow reading manufactured a jam out of a soldier standing
            # still.
            if (flow == "congested" and t in ("واقف", "واقفه", "وقفه", "موقوف")
                    and i > 0 and _lex(toks[i - 1], PRESENCE_WORDS)):
                continue
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
            elif cleared and _cleared_nearby(toks, i):
                # A withdrawal verb NEXT TO this noun: "راح الجيش" and
                # "الجيش انسحب" both clear the army. A clearing verb elsewhere
                # in the line does not — "راح الجيش اجو المستوطين بكسرو
                # بالسيارات" is the army leaving AND the settlers arriving,
                # and the line-wide flag marked the arriving settlers absent,
                # a false all-clear about the party actively smashing cars.
                out.append(("absence", pres, 0.78, i))
            else:
                out.append(("presence", pres, 0.88, i))

    # Predicative "حاجز": the bare noun is not a status (v1's biggest false
    # positive), but a line that ENDS on it — "عابود حاجز", "المربعه في حاجز" —
    # is reporting that an obstacle is there, not naming one.
    if not out and toks and toks[-1] in ("حاجز", "حواجز"):
        out.append(("presence", "idf", 0.70, len(toks) - 1))

    # Emoji only where the words said nothing — and never on a FUEL line.
    # "الجلمة :سولار❌بنزين❌" is a fuel-availability report at the Jalama
    # crossing: none of its words is checkpoint vocabulary, so the ❌ fell
    # through to here and served the CROSSING as closed. The ❌ is about
    # diesel. A clause naming a fuel product keeps its words and loses only
    # the emoji inference.
    if not out and not any(t in _FUEL_NOUNS for t in toks):
        for ch, v in EMOJI_FLOW.items():
            if ch in raw_clause:
                out.append(("flow", v, 0.65, -1))
                break

    # A clearing verb with no other flow signal means the obstacle is gone —
    # unless somebody ELSE is asserted present in the same line. "راح الجيش
    # اجو المستوطين بكسرو بالسيارات" clears the army and reports settlers
    # smashing cars; inferring `open` from the departure would be a
    # reassurance manufactured over an active attack. Same asymmetry as P2.4:
    # a caution stands on its own, a reassurance must not be inferred past one.
    if (cleared and not any(a == "flow" for a, _, _, _ in out)
            and not any(a == "presence" for a, _, _, _ in out)):
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
        bound = _assign_directions(found, dirs)
        for (axis, value, conf, pos), (direction, explicit) in zip(found, bound):
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
