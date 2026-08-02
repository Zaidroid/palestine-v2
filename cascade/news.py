"""Read a West Bank news message into a localized incident, or reject it.

The agent2 poller collects ~500 messages/day from eight governorate news
channels and every one of them sat as `claim_type='unclassified'` — the second
Telegram account was producing nothing. This is what makes that feed useful.

WHAT THE FEED ACTUALLY CONTAINS
Read 22 messages at random and roughly five are a localized, actionable West
Bank incident:

    قوات الاحتلال تقتحم بلدة بيت امر شمال الخليل
    مستوطنون يعربدون على الشارع الواصل بين بلدتي الزبابدة وقباطية، جنوب جنين
    جيش الاحتلال أطلق النار تجاه مركبة قرب بلدة بيتا جنوب نابلس

The rest is commentary ("هل بات الانتظار قدر الفلسطيني"), international politics
(Iran, Jordan, a US senator), Gaza, memorial posts, and prisoner-affairs
statements. A keyword count puts "incident vocabulary" at 33%, but that
overcounts badly: rhetoric about settlers matches the same words as a settler
attack.

SO THE DEFAULT IS REJECT
Three conditions must all hold: a concrete action from a tight verb list, a
resolvable West Bank place, and no rejection marker. Anything else is left
unclassified — the claim is retained either way, so a miss costs nothing and a
false positive costs a great deal. A bot that announces an op-ed as a raid is
worse than a bot that says nothing, because a family plans around it.

GAZA IS REJECTED ON PURPOSE
Several of these channels carry Gaza coverage. It is real news and it is not
West Bank movement data; mixing it in would inflate incident counts for
governorates it did not happen in. Gaza place names are an explicit reject.

INCIDENTS ARE EVENTS, NOT STATE
A raid happened at a time and place — it does not decay into "no raid", it
simply recedes into history. So incidents populate `event` (ARCHITECTURE §3.2),
which has been empty until now. Closures are the exception: "the road is
closed" IS a state, and those additionally feed `road_closure` observations so
they decay like any other reading.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from resolve.arabic import normalize

# Patterns are matched against normalize()d text, so they must be written in the
# same orthography. They are not: "إغلاق", "خامنئي" and "قطاع غزة" can never
# match once the text has become "اغلاق", "خامنيي" and "قطاع غزه". Spelling both
# variants by hand caught some of these and silently missed others.
#
# normalize() cannot be applied to a pattern directly — it strips punctuation,
# which would eat |, (, ), [, ], * and ?. So only the LETTER folds are applied
# here, leaving regex syntax intact.
_PAT_FOLDS = (("آ", "ا"), ("أ", "ا"), ("إ", "ا"), ("ٱ", "ا"),
              ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي"))


def _norm_pat(pattern: str) -> str:
    for src, dst in _PAT_FOLDS:
        pattern = pattern.replace(src, dst)
    return pattern

# ── what happened ────────────────────────────────────────────────────────────
# Ordered: the first match wins, so the more specific/severe pattern is listed
# above the general one it would otherwise be swallowed by.
# ORDER IS PRIORITY — the first pattern that matches wins, and most real reports
# match several. P1.1 measured what the old order cost:
#
#   * `demolition` sat above `settler_attack` and `raid`, so any stray "هدم"
#     took the message. "Continues for the 551st day of the raid ... and
#     demolitions continue" was filed as a demolition.
#   * `raid` sat above `injury`, so "Red Crescent: youth shot in the abdomen
#     during the raid on Beit Ummar" was filed as a raid, losing the casualty.
#
# The order below is: how badly it hurt someone, then who did it, then what the
# action was. A human outcome outranks the label for the action that caused it,
# and the ACTOR outranks the action so a settler attack is never recorded as an
# army raid.
#
# This is a workaround, not a fix. These events genuinely have two axes —
# action and outcome — and one label cannot carry both, which is the same
# axis-collapse that made an army sighting erase whether a road was passable.
# The real answer is to record both; see docs/TIER1_COMPLETION_PLAN.md.
INCIDENT_PATTERNS: list[tuple[str, str]] = [
    # A VERB of killing, never the bare noun "شهيد". The noun is overwhelmingly
    # referential in this corpus — "the grave of martyr Muhammad al-Junaidi",
    # "the father of the two martyrs" — and matching it filed a settler attack
    # on a cemetery as a death.
    #
    # The CASUALTY-REPORT shape is nominal and has no verb at all, and leaving
    # it out was measured to cost real deaths: "شهيد ومصابان ... برصاص
    # الاحتلال" from the Health Ministry was rejected outright, and "شهيد و١٣
    # اصابة خلال اقتحام" was filed as a raid. A bare "شهيد" is still not enough;
    # what is required is the count-and-casualty frame around it.
    # "استشه" not "استشهد": the verbal noun استشهاد is ا-س-ت-ش-ه-ا-د and does
    # NOT contain the perfective stem — the same trap as اقتحام/اقتحم, found
    # again in the held-out round. "استشهاد الشاب ... متأثراً بجروح" was filed
    # as an INJURY, which is the worst direction for this error to run.
    ("death",          r"(استشه\w*|ارتقى|ارتقي|قتلت قوات|قتل الاحتلال|اعدمت|أعدمت|"
                       r"يرتقي شهيد|ارتقاء|"
                       r"(شهيد|شهداء|شهيدا)\s*و\s*[\d٠-٩]*\s*(اصاب|مصاب|جريح|إصاب)|"
                       r"حصيله الشهداء|حصيلة الشهداء|"
                       r"[\d٠-٩]+\s*(شهداء|شهيدا))"),
    # Tear gas and stun grenades fired at people are a use-of-force incident.
    # Their absence rejected "occupation forces fire gas and stun grenades at a
    # WEDDING in Beit Ummar" for having "no incident verb".
    ("shooting",       r"(اطلق النار|أطلق النار|اطلاق نار|إطلاق نار|رصاص حي|استهدف بالرصاص|"
                       r"[يت]طلق\w*\s+(النار|الرصاص)|قنابل الغاز|قنابل الصوت|الغاز المسيل)"),
    # Arabic inflects the verb with a ي/ت/ن prefix — "يعتدون", "يهاجمون",
    # "يحطمون" — so the perfective stems alone matched almost nothing. Match on
    # the consonantal stem, gated by a settler noun nearby.
    #
    # THREE MEASURED FAILURES FIXED HERE (P1.1):
    #  * the raid stem was written "اقتحم", which is the same tense-prefix bug
    #    this file already documents for `raid`: "يقتحمون" contains "قتح", not
    #    "اقتحم". Settlers storming a village fell through to `raid`, so the
    #    ACTOR was recorded as the army.
    #  * the settler noun had to come FIRST, so "اقتحام المستوطنين" and "هجوم
    #    لعصابات المستوطنين" — verb/noun before the actor — never matched.
    #  * seizure verbs were absent entirely: "يسيطرون على آبار المياه" and
    #    "تقوم بالاستيلاء على عين القصعة" were rejected as having no verb.
    ("settler_attack", r"(?:(مستوطن\w*|قطعان)(?:\s+\S+){0,5}?\s+\S*"
                       r"(عتد|هاجم|هجوم|عربد|حرق|شعل|رشق|قتلع|خرب|حطم|دهس|قتح|"
                       r"سيطر|ستيلا|ستولا)"
                       r"|(عتد|هاجم|هجوم|عربد|عربده|قتح|رشق|قتلع)\w*"
                       r"(?:\s+\S+){0,3}?\s*\S*(مستوطن|قطعان))"),
    ("injury",         r"(اصاب\w*|إصاب\w*|جرح\w*|اصيب|أصيب|اختناق)"),
    # Arabic marks person/tense with a PREFIX, so "تقتحم" / "يقتحم" share no
    # leading letters with "اقتحم". Matching only the perfective missed the
    # commonest headline form in this corpus — "قوات الاحتلال تقتحم بلدة بيت
    # امر" — so every verb here is written as prefix + consonantal stem.
    # Stem "قتح", not "قتحم": the verbal noun "اقتحام" is ا-ق-ت-ح-ا-م and does
    # not contain the fuller stem, so requiring it dropped every headline that
    # names the raid rather than conjugating it.
    ("raid",           r"([اتين]?قتح\w*|[تي]?داهم\w*|مداهم\w*|توغل\w*)"),
    # "اخطار هدم" REMOVED: a demolition notice is not a demolition. It was
    # serving "owners handed demolition notices" as a completed demolition.
    # Notices are rejected below as `notice not act`.
    #
    # "بنية هدم" ("with the intent to demolish") is excluded for the same
    # reason one step further back — it is a CONDITIONAL threat, not even an
    # order. It filed a report of a detainee being tortured in Jericho prison
    # as a demolition, on the strength of "threatened to demolish his house if
    # he does not surrender". Excluding it lets the arrests in the same message
    # take the classification, which is what actually happened.
    ("demolition",     r"((?<!بنيه )هدم\w*|جرافات|تجريف|يجرف|تجرف)"),
    # NOT "معتقل" — like "شهيد", the participle names a person ("the detained
    # child Muhammad") rather than reporting an arrest.
    ("arrest",         r"([اتين]عتقل\w*|اعتقالات?)"),
    ("siege",          r"(حصار|طوق|محاصرة|[يت]حاصر)"),
    ("closure",        r"([اتين]?غلق\w*|اغلاق|إغلاق|سكر\w*|منع الحركة|قطع الطريق)"),
]

# Any of these and the message is not a report of a discrete local event.
REJECT_PATTERNS: list[tuple[str, str]] = [
    # Gaza — real news, wrong geography for a West Bank movement tracker.
    ("gaza", r"(غزة|غزه|قطاع غزة|رفح|خان يونس|خانيونس|البريج|النصيرات|"
             r"دير البلح|بيت لاهيا|بيت حانون|جباليا|الشجاعية|المواصي)"),
    # A road/fuel STATUS bulletin is checkpoint or fuel data, not an incident.
    # Measured: three of twenty sampled `closure` incidents were these, and one
    # of them was reporting that the roads were OPEN. They duplicate the
    # checkpoint pipeline and misrepresent routine status as an event.
    ("status bulletin", r"(احوال\s+(الطرق|بعض الطرق|طرق|حواجز|الحواجز|محطات|"
                        r"محطات الوقود)|احوال\s+\S+\s+ومحيطها)"),
    # A demolition ORDER is not a demolition. Kept out of the incident stream
    # rather than served as one — the act may never follow.
    ("notice not act", r"(اخطار\w*\s+(هدم|بالهدم)|اوامر\s+هدم|انذار\w*\s+بالهدم)"),
    # Follow-ups about an earlier event: a release days later, a family
    # inspecting old damage. Measured as four of seventeen sampled
    # `demolition` incidents — all one story about a woman freed after 8 days,
    # filed as a fresh demolition because the sentence mentions هدم.
    ("aftermath", r"(الافراج عن|افرجت?\s+\S*\s*عن|بعد\s+[\d٠-٩]+\s+(ايام|يوما|شهر))"),
    # Period statistics and retrospectives are summaries, not events.
    ("statistical", r"(خلال النصف الاول|خلال العام|خلال الاسبوع الماضي|"
                    r"احصائيه|إحصائية|حصيله\s+\S+\s+خلال|منذ\s+بدايه\s+العام)"),
    # International / national politics.
    #
    # "الجامعة الأمريكية" is a West Bank university, and matching "امريك" inside
    # it rejected a real raid on student housing sheltering people displaced
    # from Jenin camp as foreign news.
    ("international", r"(ايران|إيران|العراق|الاردن|الأردن|"
                      r"(?<!الجامعه )(?<!الجامعه ال)امريك|"
                      r"(?<!الجامعه )(?<!الجامعه ال)أمريك|واشنطن|ترامب|"
                      r"خامنئي|نتنياهو|الكنيست|البيت الابيض|مجلس الامن|الامم المتحدة|"
                      r"سوريا|لبنان|حزب الله|اليمن|الحوثي)"),
    # Commentary, memorials, media promos — not events.
    #
    # SHORT TERMS ARE ANCHORED TO TOKEN BOUNDARIES, and the reason is the worst
    # single defect P1.1 found. "رأي" (opinion) normalises to "راي", which is a
    # SUBSTRING of "اسراييلي" — the normalised form of إسرائيلي, "Israeli", one
    # of the commonest words in this corpus. 142 claims were being rejected as
    # commentary for containing the word "Israeli". It also matched inside
    # "حرايق" (fires), which is how a settler arson report with casualties came
    # to be filed as an opinion piece.
    #
    # Same family as "حومش سالك" containing "مش سالك" and "حي" matching inside
    # "الرصاص الحي": in Arabic a short string is almost always inside a longer
    # real word. "رحيل" (passing) sits inside "ترحيل" (DEPORTATION) — which is
    # an incident this system exists to record.
    ("commentary", r"(بقلم|\bراي\b|تحليل|\bمقال\b|\bالذكري\b|\bذكري\b|\bرحيل\b|"
                   r"حكاية شهيد|تابعونا|اشترك|قناتنا|هل بات|كيف يحاول|"
                   r"في مثل هذا اليوم)"),
    # Institutional statements rather than a located happening.
    ("statement", r"(نادي الاسير|نادي الأسير|تصريح|بيان صحفي|وزارة الصحة تعلن|"
                  r"تنعى|تدين|تستنكر|طالب\w* ب|دعا\w* الى|ناشد)"),
]

# ── where ────────────────────────────────────────────────────────────────────
# The dominant shape in this corpus: a settlement word, the name, then a bearing
# and the governorate — "بلدة علار شمال طولكرم".
#
# Extraction is TOKEN-based, not regex-greedy. Three separate failures came from
# doing it with a pattern:
#   * "حي" (neighbourhood) matched inside "الرصاص الحي" ("LIVE ammunition") and
#     captured the following word as a place. It is dropped entirely — a
#     two-letter place word cannot be told from a substring, the same reason
#     "حاجز" was dropped from the checkpoint status lexicon.
#   * "بمدينة بيت لحم" truncated to "بيت", because a non-greedy capture stops at
#     the first space and half these names are two words.
#   * "قرية المغير، شمال رام الله" captured "المغير شمال" — normalize() has
#     already turned the comma into a space, so punctuation cannot terminate it.
# خربة / خلة are the commonest prefixes for the small rural localities where
# settler incidents concentrate — Khirbet Qawawis, Khallet al-Hummus. Leaving
# them out sent "settlers seizing water wells in خلة الحمص south of Yatta" to
# "no resolvable West Bank place", i.e. the classifier read the event correctly
# and then dropped it for want of a noun.
PLACE_WORDS = frozenset(["بلده", "بلدة", "قريه", "قرية", "مخيم", "مدينه", "مدينة",
                         "بلدات", "قري", "قرى", "ضاحيه", "ضاحية",
                         "خربه", "خربة", "خله", "خلة", "تجمع"])
BEARING_WORDS = frozenset(["شمال", "جنوب", "شرق", "غرب", "شمالي", "جنوبي",
                           "شرقي", "غربي", "وسط", "شمالا", "جنوبا"])
GOVERNORATES = ["نابلس", "الخليل", "جنين", "طولكرم", "رام الله", "بيت لحم",
                "قلقيلية", "قلقيليه", "سلفيت", "اريحا", "أريحا", "طوباس",
                "القدس", "البيرة", "البيره"]
_GOV_RE = _norm_pat("|".join(GOVERNORATES))
_GOV_TOKENS = frozenset(normalize(g) for g in GOVERNORATES) | {"رام", "الله"}

# A name stops here. Without this the capture runs on into the next clause.
_STOP_TOKENS = (BEARING_WORDS | _GOV_TOKENS | PLACE_WORDS | frozenset([
    "قرب", "في", "من", "الي", "الى", "على", "عن", "مع", "بحماية", "خلال",
    "بعد", "قبل", "و", "او", "التي", "الذي", "حيث", "كما", "المحتله",
    "المحتلة", "بالضفه", "الضفه", "الغربيه", "اليوم", "امس", "صباح", "مساء",
    "قوات", "الاحتلال", "جيش", "المستوطنين", "مستوطنين",
]))

_WS = re.compile(r"\s+")



def _stops(tok: str) -> bool:
    """Whether a token ends a place name, allowing for a fused article.

    "قرية جنيد والقرى المحيطة" — normalize() gives "والقري", the waw strips to
    "القري", and only after the article comes off is it recognisable as the
    place word "قري". Without both strips the name ran on into the next clause.
    """
    if tok in _STOP_TOKENS or _is_place_word(tok):
        return True
    bare = tok[2:] if tok.startswith("ال") and len(tok) > 4 else tok
    return bare in _STOP_TOKENS or _is_place_word(bare)

def _is_place_word(tok: str) -> bool:
    """Settlement word, with or without a fused preposition.

    Arabic writes the preposition onto the noun — "لبلدة إذنا" ("to the town of
    Idhna"), "بمدينة بيت لحم" ("in the city of Bethlehem"), "لمدينة سلفيت".
    Matching only the bare form missed every one of those, which is most of the
    corpus: the place word almost always follows a verb of motion.
    """
    if tok in PLACE_WORDS:
        return True
    return len(tok) > 3 and tok[0] in "بلكفو" and tok[1:] in PLACE_WORDS


@dataclass
class NewsReading:
    verdict: str                       # incident | rejected | unclear
    incident_type: str | None = None
    place_text: str | None = None
    governorate: str | None = None
    reject_reason: str | None = None
    confidence: float = 0.0
    matched: str | None = None
    is_closure: bool = False           # also a movement STATE, not just an event
    evidence: list[str] = field(default_factory=list)


_INCIDENT_RE = [(lbl, re.compile(_norm_pat(p))) for lbl, p in INCIDENT_PATTERNS]
_REJECT_RE = [(lbl, re.compile(_norm_pat(p))) for lbl, p in REJECT_PATTERNS]


def _first_match(text: str, patterns) -> tuple[str, str] | None:
    for label, rx in patterns:
        m = rx.search(text)
        if m:
            return label, m.group(0)[:60]
    return None


def _extract_place(text: str) -> tuple[str | None, str | None]:
    """(place name, governorate) — the governorate only when actually stated.

    Scans for a settlement word and takes the 1-3 tokens after it, stopping at
    a bearing, a governorate, a preposition or a verb. Multi-word names such as
    "بيت لحم" and "دير شرف" survive; "قرية المغير شمال رام الله" yields
    ("المغير", "رام الله") rather than "المغير شمال".
    """
    toks = normalize(text).split()
    name: str | None = None
    for i, t in enumerate(toks):
        if not _is_place_word(t):
            continue
        # A governorate is a stop-word in the trailing position ("بلدة علار
        # شمال طولكرم" must not capture طولكرم) but it is the NAME when it
        # follows the place word directly — "لمدينة سلفيت" is the city of
        # Salfit. Two tokens, so "مدينة رام الله" survives intact.
        head = toks[i + 1:i + 3]
        if head and head[0] in _GOV_TOKENS:
            two = " ".join(head)
            if two in _GOV_TOKENS or normalize("رام الله") == two:
                name = two
                break
            name = head[0]
            break

        parts: list[str] = []
        for nxt in toks[i + 1:i + 4]:
            # A fused waw ends the name: "قرية جنيد والقرى المحيطة" must give
            # "جنيد", not "جنيد والقري المحيطه".
            if (nxt in _STOP_TOKENS or _is_place_word(nxt) or len(nxt) < 2
                    or nxt.isdigit()
                    or (nxt.startswith("و") and _stops(nxt[1:]))):
                break
            parts.append(nxt)
        if parts:
            name = " ".join(parts)
            break

    # Governorate, wherever it appears. Recorded separately from the name so a
    # village keeps its admin2 context for disambiguation — several West Bank
    # villages share a name across governorates.
    m = re.search(_GOV_RE, text)
    gov = m.group(0) if m else None
    return name, gov


def read(text: str | None) -> NewsReading:
    """Classify one news message. Rejecting is the expected outcome."""
    if not text or len(text.strip()) < 25:
        return NewsReading(verdict="rejected", reject_reason="too short")

    norm = normalize(text)

    rej = _first_match(norm, _REJECT_RE)
    if rej:
        return NewsReading(verdict="rejected", reject_reason=rej[0], matched=rej[1])

    inc = _first_match(norm, _INCIDENT_RE)
    if not inc:
        return NewsReading(verdict="unclear", reject_reason="no incident verb")

    place_text, gov = _extract_place(norm)
    if not place_text and not gov:
        # An action with nowhere to put it is not usable by anything that
        # answers "what is happening near me".
        return NewsReading(verdict="unclear", incident_type=inc[0],
                           reject_reason="no resolvable West Bank place")

    # A named settlement plus its governorate is the strongest shape; a bare
    # governorate locates the report only to admin2 and is worth less.
    conf = 0.80 if (place_text and gov) else (0.70 if place_text else 0.55)
    return NewsReading(
        verdict="incident", incident_type=inc[0], place_text=place_text,
        governorate=gov, confidence=conf, matched=inc[1],
        is_closure=inc[0] in ("closure", "siege"),
        evidence=[inc[1]],
    )
