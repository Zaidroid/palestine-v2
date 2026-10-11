"""A road-channel message, read into one reading per checkpoint it names.

    names   resolve.road_names.Lexicon.scan      WHICH places, and where in the line
    status  cascade.checkpoint_text.read         WHAT is said, per direction and axis

v1 did both at once and one way: the words before the first status word are
the name, the rest is the status, one reading per line. Measured on the roads
gold (tests/gold/roads.jsonl, 200 hand-read messages) that finds 0.72 of what
a person reads. What it cannot do, and this does:

  * a name anywhere in the line — "ازمه خانقه عالمربعه", "سكرو النبي صالح";
  * several names sharing one status — "عطاره وعين سينيا سالكات" is two
    readings, "النبي يونس حلحول وسعير مغلقات" three;
  * several names with a status each — "عناب سالك دير شرف مسكر";
  * a name that only says which way — "عين سينيا حاجز للخارج من رام الله" is
    about Ein Sinya, not Ramallah; "شرطه للي رايح على عين سينيا" is about the
    road there, not the checkpoint;
  * a part of a place the register does not hold — "بوابة سنجل المحول مغلقة"
    is not Sinjil's main gate, and is not read as it;
  * a status on the line below its name — "عناب سالك لداخل ⏎ مغلق للخارج",
    "بوابات النبي يونس وسعير ⏎ اليوم مغلقه";
  * an answer that names nothing — "حاجز للخارج", sent as a reply to "عطاره
    كيف؟", is about Atara. v1 filed 361 such replies under Avnei Hefetz, as
    open, because "حاجز" is a substring of that checkpoint's name.

Each name is replaced by `checkpoint_text.NAME` before the status is read, so
a name can neither be read as a status ("الفحص": the inspection) nor hide which
side of it the checkpoint noun stands on.

Pure: no database, no clock. ingest/sources/roads.py does the reading and the
writing around it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cascade.checkpoint_text import (DIRECTION_WORDS, EMOJI_FLOW, FLOW_WORDS, NAME,
                                     PRESENCE_WORDS, Fact, _lex, _noun_kind, read, tokens)
from resolve.arabic import normalize
from resolve.road_names import Lexicon, Span, fold_token


def _folded(*words: str) -> frozenset:
    return frozenset(fold_token(normalize(w)) for w in words)


# Between two names of one list: "عطاره و عين سينيا", "بوابات حلحول وسعير".
_LIST_WORDS = _folded("و", "او", "مع", "ثم", "حاجز", "حاجزي", "حواجز", "بوابه", "بوابات",
                      "مدخل", "مداخل", "دوار", "مفرق", "مفترق", "جسر", "معبر", "طريق",
                      "شارع", "كمان", "اشارات", "اشاره")

# A name behind one of these says where something is heading or coming from,
# never what the line is about: "للخارج من نابلس", "باتجاه اريحا", "بين حزما وجبع".
_HEADING = _folded("من", "باتجاه", "اتجاه", "بإتجاه", "نحو", "صوب", "جهه", "لغايه", "حتي",
                   "لحد", "لبعد", "الي", "بين", "غير")
# Near a place is not at it — "سكروا الدخلة الترابية جنب بوابة جماعين" — unless
# what stands there is a checkpoint: "حاجز بعد دير شرف".
_NEAR = _folded("جنب", "قرب", "مقابل", "قبال", "قبل", "بعد")
# At a place: the subject, if the line has none yet ("ازمه ع المربعه").
_AT = _folded("علي", "ع", "عل", "عند", "في")
# "شرطه للي رايح على عين سينيا": on the way there.
_MOTION = _folded("رايح", "رايحين", "طالع", "طالعين", "نازل", "نازلين", "جاي", "جايين",
                  "متجه", "متجهين", "المتجه", "مروح", "مروحين")

# After a name: a part of the place that is not the place the register holds.
# "بوابة حزما البلد" is the village gate, not the Hizma checkpoint; where the
# register does hold the part ("عطاره البلد"), the longer name has already won.
_PART = _folded("البلد", "القديمه", "القديم", "الجديده", "الجديد", "المحول", "الترابيه",
                "الترابي", "الشرقي", "الشرقيه", "الغربي", "الغربيه", "الشمالي", "الشماليه",
                "الجنوبي", "الجنوبيه", "الفوقا", "التحتا", "الفرعي", "الفرعيه")

# Directions for a detour. Its ✅ is "go this way", not "this checkpoint is open".
_ROUTE_VERBS = _folded("بتلف", "بلف", "بلفو", "لفيت", "لفينا", "لف", "لفو", "بتطلع", "اطلع", "بترجع", "ارجع", "بتنزل",
                       "انزل", "بتروح", "روح", "روحو", "بتفوت", "فوت", "بتمر", "بتكمل")

_DETOUR_VERBS = _ROUTE_VERBS - _folded("روح", "روحو", "بتروح")

# A reply or a channel's own subject is assumed only for a short message: a
# long one that names nothing is about something else.
INHERIT_MAX_WORDS = 12

# Words that may stand before a status without naming anything. A line whose
# status follows any OTHER word has a subject of its own — a place the register
# may not hold ("الطنيب شرطة من عشر دقايق") — and inherits nobody else's.
FILLERS = _folded(
    "في", "فيه", "اه", "ااه", "لا", "بس", "فش", "ولا", "يعني", "حاليا", "صحيح", "كلو", "كله",
    "عليه", "عليها", "مش", "لسا", "لسه", "هسا", "هسه", "هلا", "كان", "كانت", "هي", "هيه",
    "هاي", "هيو", "مع", "بدون", "ما", "راح", "راحو", "تم", "و", "انا", "شباب", "الي", "شكلو",
    "شكله", "اكيد", "بحكو", "بحكوا", "حكو", "بقولو", "انو", "من", "قبل", "بعد", "شوي",
    "ربع", "ساعه", "دقايق", "عشر", "شبه", "حطو", "رجع", "جميع", "كل", "اخر", "تحديث", "اشاره",
    "الان", "لحد", "لغايه", "ان", "شاء", "الله", "له", "طيب", "وفي", "كتير", "كثير", "جدا",
    "تماما", "فقط", "بدايه", "وضع", "وضعها", "وضعو", "الوضع", "الامور", "السير", "الطريق",
    "مرقت", "مريت", "مرقنا", "مرقو", "نعم", "ايوا", "ايوه", "والله", "يا", "اخوي", "اخي",
    "حبيبي", "غالي", "الحمدلله", "الحمد", "لله", "تواجد", "مع", "عم", "بلش", "بلشت", "صار",
    "صارت", "ضل", "ضلت", "لساتو", "لساتها", "بعدو", "بعدها", "زي", "مثل", "نفس", "شي", "اشي",
    "اليوم", "الاحد", "الاثنين", "الثلاثاء", "الاربعاء", "الخميس", "الجمعه", "السبت", "الصبح",
    "الليله", "مبارح", "طول", "يوم", "فك", "فكو", "شكلها", "شكلهم", "حطوا", "انسحب",
    "انسحبو", "رجعو", "بدء", "بدا",
    # Generic words the backfill counted as names 20 to 60 times each: "البلد
    # فاتح", "البوابة مغلقة", "الطالع سالك", "الشمالي فاتح".
    "البلد", "البوابه", "البوابات", "الحاجز", "الطالع", "النازل", "الشمالي", "الجنوبي",
    "الشرقي", "الغربي", "الارتباط", "حجز", "مافي", "المدخل", "الدوار", "الشارع", "الخط")

# A title names a region, not a subject: "أحوال الطرق أريحا والأغوار".
_TITLE = _folded("احوال", "أحوال", "تحديثات", "تحديث", "محافظات", "محافظه", "منطقه", "حاله")

# In a crossing's own channel most talk is bookings and dates. Only a message
# about the gate itself is read as about the crossing.
_CROSSING_WORDS = _folded("البوابه", "بوابه", "الجسر", "جسر", "المعبر", "معبر")
_BOOKING_WORDS = _folded("حجز", "الحجز", "تواريخ", "تاريخ", "المنصه", "منصه", "vip", "تذكره",
                         "تذاكر", "موعد", "مواعيد")


@dataclass
class RoadReading:
    place_id: int
    alias: str                       # the name as matched
    line: str                        # the raw line it was read from
    modality: str                    # assertion | question
    facts: list[Fact] = field(default_factory=list)
    rivals: tuple[int, ...] = ()     # other places the same name could be
    via: str = "name"                # name | below | reply | channel


def mask(text: str, spans: list[Span], offset: int = 0) -> str:
    """`text` with every name replaced by the NAME token."""
    out, at = [], 0
    for sp in sorted(spans, key=lambda s: s.start):
        a, b = sp.start - offset, sp.end - offset
        if a < at or b > len(text):
            continue
        out += [text[at:a], f" {NAME} "]
        at = b
    out.append(text[at:])
    return "".join(out)


def _own_subject(text: str) -> bool:
    """A line that names nothing the register holds, yet is about something:
    a word that is no filler stands before its first status word."""
    toks = tokens(normalize(text))
    for t in toks:
        if _lex(t, FLOW_WORDS) or _lex(t, PRESENCE_WORDS) or _noun_kind(t):
            return False
        if t == NAME or _lex(t, DIRECTION_WORDS) or t.isdigit():
            continue
        if fold_token(t) not in FILLERS:
            return True
    return False


def subjects_of(text: str, lex: Lexicon) -> dict[int, Span]:
    """The places a message is about (qualifiers and parts left out)."""
    out: dict[int, Span] = {}
    for line in text.split("\n"):
        spans = lex.scan(line)
        for sp, role in zip(spans, _roles(spans, lex.words(line))):
            if role == "subject":
                out.setdefault(sp.place_id, sp)
    return out


def parts_of(text: str, lex: Lexicon) -> list[tuple[str, str, str]]:
    """(key, as written, the line) for each part of a place the register does
    not hold as its own row: "حزما البلد", "سنجل المحول". Names waiting for a yes."""
    out = []
    for line in text.split("\n"):
        spans, words = lex.scan(line), lex.words(line)
        for sp, role in zip(spans, _roles(spans, words)):
            if role == "part":
                out.append((f"{sp.alias} {words[sp.w1][0]}",
                            line[sp.start:words[sp.w1][2]].strip(), line.strip()[:200]))
    return out


def _has_status(text: str) -> bool:
    return any(_lex(t, FLOW_WORDS) or _lex(t, PRESENCE_WORDS) or _noun_kind(t) == "indef"
               for t in tokens(normalize(text)))


def _unfused(word: str) -> str:
    return word[1:] if len(word) > 2 and word[0] == "و" else word


def _roles(spans: list[Span], words: list[tuple[str, int, int]]) -> list[str]:
    """subject | qualifier | part, for each name of a line."""
    roles: list[str] = []
    generic = _LIST_WORDS - {"و", "او", "مع", "ثم", "كمان"}
    for k, sp in enumerate(spans):
        # What stands before the name, past its own generic word: in "جنب بوابة
        # الفوار" the name is behind "جنب".
        b = sp.w0 - 1
        while b >= 0 and words[b][0] in generic:
            b -= 1
        before = _unfused(words[b][0]) if b >= 0 else ""
        before2 = _unfused(words[b - 1][0]) if b > 0 else ""
        after = words[sp.w1][0] if sp.w1 < len(words) else ""
        has_subject = "subject" in roles
        role = "subject"
        if after in _PART:
            role = "part"
        elif before in _HEADING or sp.fused == "ل":
            role = "qualifier"
        elif before in _NEAR:
            role = "subject" if _noun_kind(before2) else "qualifier"
        elif before in _AT or sp.fused in ("ب", "ع"):
            # "بلف ع صره" goes round by Sarra; "روح ع عطاره في ازمه" is about Atara.
            role = ("qualifier" if (has_subject or before2 in _MOTION
                                    or before2 in _DETOUR_VERBS) else "subject")
        elif k and roles[-1] == "qualifier" and all(
                _unfused(w) in _LIST_WORDS for w, _, _ in words[spans[k - 1].w1:sp.w0]):
            role = "qualifier"                 # "بين حزما وجبع": the second of the pair
        roles.append(role)
    return roles


def _groups(subjects: list[Span], words: list[tuple[str, int, int]]) -> list[list[Span]]:
    """Names with only list words between them are one list and share a status."""
    groups: list[list[Span]] = []
    for sp in subjects:
        if groups and all(_unfused(w) in _LIST_WORDS
                          for w, _, _ in words[groups[-1][-1].w1:sp.w0]):
            groups[-1].append(sp)
        else:
            groups.append([sp])
    return groups


def _segments(line: str, groups: list[list[Span]]) -> list[tuple[list[Span], int, int]]:
    """The stretch of the line each group's status is read from.

    The channels write the name first: a group owns the line from its own start
    to the next group's. Where nothing follows the last name and a status
    stands before the first ("سالك عطاره مسكر عين سينيا"), the status comes
    first and each group owns what precedes it instead.
    """
    if len(groups) == 1:
        return [(groups[0], 0, len(line))]
    first, last = groups[0][0], groups[-1][-1]
    if not _has_status(line[last.end:]) and _has_status(line[:first.start]):
        out, at = [], 0
        for g in groups:
            out.append((g, at, g[-1].end))
            at = g[-1].end
        return out
    out = []
    for k, g in enumerate(groups):
        a = 0 if k == 0 else g[0].start
        b = groups[k + 1][0].start if k + 1 < len(groups) else len(line)
        out.append((g, a, b))
    return out


def _read(text: str, route: bool):
    if route:
        for ch in EMOJI_FLOW:
            text = text.replace(ch, " ")
    return read(text)


def _line(line: str, lex: Lexicon) -> tuple[list[RoadReading], list[Span], bool]:
    """One line: its readings, the names it is about, and whether it named any."""
    spans = lex.scan(line)
    if not spans:
        return [], [], False
    words = lex.words(line)
    route = any(w in _ROUTE_VERBS for w, _, _ in words)
    roles = _roles(spans, words)
    subjects = [sp for sp, r in zip(spans, roles) if r == "subject"]
    if not subjects:
        return [], [], True
    if read(mask(line, spans)).modality == "question":
        seen: set[int] = set()
        return ([RoadReading(sp.place_id, sp.alias, line, "question", rivals=sp.rivals)
                 for sp in subjects if not (sp.place_id in seen or seen.add(sp.place_id))],
                [], True)
    out: list[RoadReading] = []
    pending: list[Span] = []           # groups whose own stretch said nothing yet
    last_group: list[Span] = []
    for group, a, b in _segments(line, _groups(subjects, words)):
        inside = [sp for sp in spans if a <= sp.start and sp.end <= b]
        r = _read(mask(line[a:b], inside, a), route)
        last_group = group
        if r.modality != "assertion":
            # "برقه ومفرق بزاريا حومش سالك": برقه shares what the rest is told.
            pending = pending + group if len(tokens(normalize(line[a:b]))) <= len(group) * 3 + 2 else []
            continue
        for sp in pending + group:
            out.append(RoadReading(sp.place_id, sp.alias, line, "assertion",
                                   list(r.facts), sp.rivals))
        pending = []
    return out, (pending + last_group if pending else last_group), True


def read_message(text: str | None, lex: Lexicon, parent: str | None = None,
                 home: int | None = None) -> list[RoadReading]:
    """Every reading in a message.

    `parent` is the text of the message this one replies to: a short reply that
    names no place is read as an answer about the one place its parent names.
    `home` is the place a channel is wholly about (a crossing's own channel): a
    short message there that names nothing is about it.
    """
    if not text or not text.strip():
        return []
    out: list[RoadReading] = []
    above: list[Span] = []             # who the line above was about
    above_told = False                 # …and whether it said anything of them
    named_any = False
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        note = line.startswith("📝")
        got, subjects, named = ([], [], False) if note else _line(line, lex)
        named_any = named_any or named
        if named and not note:
            out += got
            title = any(w in _TITLE for w, _, _ in lex.words(line))
            above, above_told = ([] if title else subjects), bool(got)
            continue
        # A line that names nothing: the rest of the line above, if it carries
        # a direction ("مغلق للخارج"), is a note under it (📝), or the line
        # above was names alone.
        if above and not _own_subject(line) and (note or not above_told or any(
                _lex(t, DIRECTION_WORDS) for t in tokens(normalize(line)))):
            r = read(f"{NAME} {mask(line, lex.scan(line))}")
            if r.modality == "assertion":
                if any(f.axis == "flow" and f.direction_explicit for f in r.facts):
                    # The note says which way; the line above said only "partly".
                    for prev in out:
                        if prev.place_id in {sp.place_id for sp in above}:
                            prev.facts = [f for f in prev.facts
                                          if not (f.axis == "flow" and f.direction == "both")]
                out += [RoadReading(sp.place_id, sp.alias, line, "assertion", list(r.facts),
                                    sp.rivals, via="below") for sp in above]
                above_told = True
                continue
        above = []
    if not out and not named_any:
        out = _inherit(text, parent, home, lex)
    return _dedupe(out)


def _inherit(text: str, parent: str | None, home: int | None, lex: Lexicon) -> list[RoadReading]:
    """A message that names nothing, read as about its parent's place or its
    channel's."""
    toks = tokens(normalize(text))
    if len(toks) > INHERIT_MAX_WORDS or _own_subject(text):
        return []
    subject, via = None, ""
    if parent:
        asked = subjects_of(parent, lex)
        if len(asked) == 1:
            sp = next(iter(asked.values()))
            subject, via = (sp.place_id, sp.alias, sp.rivals), "reply"
    if subject is None and home is not None:
        folded = {fold_token(t) for t in toks}
        if folded & _CROSSING_WORDS and not folded & _BOOKING_WORDS:
            subject, via = (home, "", ()), "channel"
    if subject is None:
        return []
    # Line by line, as the answer was typed: "مغلق ⏎ الداخل فاتح". What the
    # answer leaves undirected takes the direction that was asked about
    # ("كيف عناب للخارج" → the مغلق is the way out).
    asked_dir = {d for t in tokens(normalize(parent or "")) if (d := _lex(t, DIRECTION_WORDS))
                 and d != "both"} if via == "reply" else set()
    facts: list[Fact] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        r = read(f"{NAME} {line.strip()}")
        if r.modality == "question":
            return []
        for f in r.facts if r.modality == "assertion" else ():
            if len(asked_dir) == 1 and f.direction == "both" and not f.direction_explicit:
                f.direction = next(iter(asked_dir))
            facts.append(f)
    if not facts:
        return []
    return [RoadReading(subject[0], subject[1], text.strip(), "assertion", facts,
                        subject[2], via=via)]


def _dedupe(readings: list[RoadReading]) -> list[RoadReading]:
    """One reading per place and modality; of two facts that say the same thing
    about the same direction and axis, the more confident."""
    by: dict[tuple[int, str], RoadReading] = {}
    for r in readings:
        k = (r.place_id, r.modality)
        if k not in by:
            by[k] = RoadReading(r.place_id, r.alias, r.line, r.modality, [], r.rivals, r.via)
        best = {(f.direction, f.axis, f.value): f for f in by[k].facts}
        for f in r.facts:
            fk = (f.direction, f.axis, f.value)
            if fk not in best or f.confidence > best[fk].confidence:
                best[fk] = f
        by[k].facts = list(best.values())
    # An assertion about a place outranks a question about it in one message.
    asserted = {pid for (pid, m), r in by.items() if m == "assertion" and r.facts}
    return [r for (pid, m), r in by.items()
            if (m == "assertion" and r.facts) or (m == "question" and pid not in asserted)]
