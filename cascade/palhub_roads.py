"""Parse Palhub's road bulletin — pre-structured, so parse it exactly.

    from cascade.palhub_roads import parse
    bulletin = parse(message_text)

`@palhubapproad` publishes one message per area, refreshed every ~2 minutes:

    🚧 أحوال الطرق والحواجز  نابلس
    آخر تحديث: ٠٢‏/٠٨، ١١:١٣ ص

    - الـ 17 - عصيرة: دخول 🟡 أزمة متوسطة | خروج 🟡 أزمة متوسطة
    - الجلمة: دخول 🔴 مغلق | خروج 🔴 مغلق

    🔗 التفاصيل والتحديث اللحظي: https://palhub.app/road-status

WHY THIS IS A DIFFERENT KIND OF PARSER
`cascade/checkpoint_text.py` reads free prose written by people in a hurry and
measures 0.823 precision, because inferring meaning from "الحاجز فاضي" is
genuinely hard. This is a machine-generated table. Somebody else already did
the extraction, and the honest thing is to read it EXACTLY rather than run
guesswork over a fact that is already explicit.

So: a strict grammar, and anything that does not match is REJECTED rather than
approximated. Measured over 400 messages, 6,058 of 6,060 lines matched — the
two that did not are malformed entries in the source ("- ازدحام: زيف"), and
they should be dropped, not guessed at. A lenient parser here would turn a
100%-legible source into a second probabilistic one.

THE STATUS MAPPING IS THE LOAD-BEARING DECISION
Palhub has four states; we have four values; they are NOT the same four.

    🟢 مفتوح          -> open
    🟡 أزمة متوسطة    -> congested
    🟠 أزمة خانقة     -> congested
    🔴 مغلق           -> closed

Both azma levels become `congested`, and that is deliberate. Our vocabulary
already places ازمه, ازدحام and اختناق in `congested`, while `slow` means بطيء
— moving slowly, a different claim from being jammed. Mapping أزمة متوسطة to
`slow` because it is the milder of two would make palhub systematically
CONTRADICT road channels describing the same reality, and the corroboration
model would read genuine agreement as conflict.

The distinction is not thrown away: the original Arabic and its severity ride
along in the parsed row, so a future severity axis can use them and nothing is
lost by mapping conservatively today.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADER = re.compile(r"^🚧\s*أحوال الطرق والحواجز\s+(?P<area>.+?)\s*$")
UPDATED = re.compile(r"^آخر تحديث:\s*(?P<stamp>.+?)\s*$")
ROW = re.compile(
    r"^-\s*(?P<name>.+?):\s*"
    r"دخول\s*(?P<in_emoji>\S+)\s*(?P<in_text>[^|]+?)\s*\|\s*"
    r"خروج\s*(?P<out_emoji>\S+)\s*(?P<out_text>.+?)\s*$"
)

# Keyed on the Arabic, with the emoji as a cross-check rather than the key: an
# emoji is one codepoint away from a different meaning and renders identically
# in a diff, whereas the words are unambiguous.
STATUS = {
    "مفتوح":        ("open",      0),
    "مغلق":         ("closed",    3),
    "أزمة متوسطة":  ("congested", 1),
    "ازمة متوسطة":  ("congested", 1),
    "أزمة خانقة":   ("congested", 2),
    "ازمة خانقة":   ("congested", 2),
}

EMOJI_HINT = {"🟢": "open", "🔴": "closed", "🟡": "congested", "🟠": "congested"}

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Bidi control marks, which are INVISIBLE and break naive matching.
#
# The date arrives as '٠٢‏/٠٨، ١١:١٣ ص' — a RIGHT-TO-LEFT MARK sits between
# the day and the slash so the mixed-direction text renders correctly. It is not
# whitespace, so `\s*` does not match it, and the timestamp silently failed to
# parse on all 400 sampled messages while the line looked perfectly normal in
# every terminal and diff.
#
# Same family as the orthography traps already in HANDOFF: the text is right and
# its representation is not what it appears to be. Strip the marks before
# matching anything.
_BIDI = dict.fromkeys(
    [0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
     0x2066, 0x2067, 0x2068, 0x2069])

_STAMP = re.compile(r"(\d{2})\s*/\s*(\d{2})[،,]?\s*(\d{1,2}):(\d{2})\s*([صم])")


@dataclass
class Reading:
    name: str
    direction: str          # inbound | outbound
    value: str              # open | congested | closed
    raw_status: str         # the original Arabic, kept
    severity: int           # 0..3, palhub's own gradation


@dataclass
class Bulletin:
    area: str | None = None
    updated_local: str | None = None       # HH:MM as palhub stated it
    readings: list[Reading] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def _status(emoji: str, text: str) -> tuple[str, int] | None:
    text = text.strip()
    hit = STATUS.get(text)
    if hit is None:
        return None
    # The emoji must agree with the words. If Palhub ever changes one without
    # the other, that is a format change and should surface as a rejection
    # rather than be silently resolved in whichever direction we happened to
    # prefer.
    if emoji in EMOJI_HINT and EMOJI_HINT[emoji] != hit[0]:
        return None
    return hit


def parse_stamp(stamp: str) -> str | None:
    """`٠٢‏/٠٨، ١١:١٣ ص` -> `11:13`. Returns local wall time, 24h.

    Palhub's own "last updated", which is what the reading is ABOUT — not when
    Telegram delivered it. Using the post time instead would make every
    re-post look like a fresh observation of a fact that has not moved.
    """
    m = _STAMP.search(stamp.translate(_BIDI).translate(_AR_DIGITS))
    if not m:
        return None
    _dd, _mm, hh, mi, mer = m.groups()
    h = int(hh) % 12
    if mer == "م":                      # م = PM, ص = AM
        h += 12
    return f"{h:02d}:{mi}"


def parse(text: str) -> Bulletin:
    """Strict. A line that does not match the grammar is rejected, not guessed."""
    b = Bulletin()
    for raw in (text or "").splitlines():
        line = raw.translate(_BIDI).strip()
        if not line:
            continue
        if b.area is None and (m := HEADER.match(line)):
            b.area = m.group("area").strip()
            continue
        if b.updated_local is None and (m := UPDATED.match(line)):
            b.updated_local = parse_stamp(m.group("stamp"))
            continue
        if not line.startswith("-"):
            continue                     # the trailing link line, blank lines
        m = ROW.match(line)
        if not m:
            b.rejected.append(line)
            continue
        d = m.groupdict()
        ins = _status(d["in_emoji"], d["in_text"])
        out = _status(d["out_emoji"], d["out_text"])
        if ins is None or out is None:
            b.rejected.append(line)
            continue
        name = d["name"].strip()
        b.readings.append(Reading(name, "inbound", ins[0], d["in_text"].strip(), ins[1]))
        b.readings.append(Reading(name, "outbound", out[0], d["out_text"].strip(), out[1]))
    return b


def is_bulletin(text: str) -> bool:
    return bool(text) and bool(HEADER.match(text.strip().splitlines()[0] if text.strip() else ""))
