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
# ── closure needs a VERB *and* something that can be closed ─────────────────
#
# `closure` measured 0.167 in P1.1 round 3 — one right in six — and the
# corrections came in three waves, each a different way for a correct verb to
# describe the wrong thing.
#
#   1. `سكر` unanchored matched inside `عسكري` (military) and `السكري`
#      (diabetes). Four of six. Anchoring fixed those.
#   2. `سكر` anchored STILL matches صادق سكر — a man's surname — and سُكّر,
#      sugar. So the bare stem is gone entirely; only the unambiguous
#      inflections remain. A news wire writes "أغلق", not "سكر".
#   3. `اغلق المحافظ الهاتف` — "the governor HUNG UP THE PHONE". The verb is
#      exactly right and the object is a telephone.
#
# Wave 3 is the one no wordlist fixes, so the rule changed shape: a closure
# requires a closing verb AND something a person could be stopped by, within a
# clause of each other. That keeps every true positive in the samples — a
# street closed for paving, a checkpoint shut after a crash, an area sealed
# with earth berms, gates closed on an ambulance — and drops phones, shops and
# surnames without naming any of them.
_CLOSE_VERB = r"(?:[اتين]?غلق\w*|اغلاق|مسكر\w*|سكرت|سكروا|تسكير)"
_MOVE_OBJECT = (r"(?:شارع|شوارع|طريق|طرق|حاجز|حواجز|بوابه|بوابات|معبر|معابر|"
                r"مدخل|مداخل|مخرج|منطقه|بلده|قريه|مخيم|مفترق|دوار|جسر|نفق|الحركه)")
# `[^.،؛]` keeps the two inside one clause: crossing a full stop or a comma is
# usually crossing into a different sentence about a different thing.
# Installing a gate or earth mound IS the closure it announces: "the army
# installs an iron gate on the Jariot road near Beit Ur" was filed as a settler
# attack in al-Bireh (audit, 2026-09-24).
_INSTALL_BARRIER = (r"(?:تركيب|نصب|وضع|اقامه|اقامة|[يت]نصب|[يت]ركب|[يت]ضع)\s+"
                    r"(?:ال)?(?:بوابه|بوابة|بوابات|ساتر|سواتر|مكعبات|حواجز اسمنتيه|"
                    r"حواجز اسمنتية|كتل اسمنتيه|كتل اسمنتية)")
_CLOSURE_PATTERN = (
    r"(" + _CLOSE_VERB + r"[^.،؛]{0,40}?" + _MOVE_OBJECT +
    r"|" + _MOVE_OBJECT + r"[^.،؛]{0,40}?" + _CLOSE_VERB +
    r"|" + _INSTALL_BARRIER +
    r"|منع الحركة|قطع الطريق)")

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
    # شعال is the maṣdar: إشعال is ا-ش-ع-ا-ل and does NOT contain the stem
    # شعل — the third time a verbal noun has hidden its own verb (اقتحام,
    # استشهاد), found in round 5 when "قاموا باشعال النار" near the Burqa
    # cemetery read as "no incident verb". ضرم ("يضرمون النيران"), دشن
    # (founding a new outpost IS the land grab), and ستول (يستولون — the
    # existing ستولا only matched the noun) are round-5 misses too.
    ("settler_attack", r"(?:(مستوطن\w*|قطعان)(?:\s+\S+){0,5}?\s+\S*"
                       r"(عتد|هاجم|هجوم|عربد|حرق|شعل|شعال|ضرم|رشق|قتلع|خرب|"
                       r"حطم|دهس|قتح|سيطر|ستيلا|ستول|دشن)"
                       r"|(عتد|هاجم|هجوم|عربد|عربده|قتح|رشق|قتلع|ضرم|شعال)\w*"
                       r"(?:\s+\S+){0,3}?\s*\S*(مستوطن|قطعان))"),
    # A beating by the army is harm without an injury noun: "تعتدي بالضرب على
    # صاحب محل" was rejected as having no incident verb (round 5). Settler
    # beatings keep their actor — settler_attack sits above this entry.
    ("injury",         r"(اصاب\w*|إصاب\w*|جرح\w*|اصيب|أصيب|اختناق|"
                       r"[اتين]?عتد\w*\s+بالضرب|اعتداء بالضرب)"),
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
    # LAND LEVELLING IS NOT A DEMOLITION (classifier 1.7, 2026-09-24). The
    # audit caught "army bulldozing land in al-Mazra'a al-Gharbiya" served as a
    # demolition in Ramallah: 155 of 670 demolition claims carried تجريف with no
    # هدم at all. A levelled field and a demolished home are different harms
    # with different sources, and a closed vocabulary should say which.
    ("land_levelling", r"(تجريف|[يت]جرف\w*|جرفت)"),
    ("demolition",     r"((?<!بنيه )هدم\w*|جرافات)"),
    # NOT "معتقل" — like "شهيد", the participle names a person ("the detained
    # child Muhammad") rather than reporting an arrest.
    ("arrest",         r"([اتين]عتقل\w*|اعتقالات?)"),
    ("siege",          r"(حصار|طوق|محاصرة|[يت]حاصر)"),
    # `سكر` IS ANCHORED, and this is the single worst defect P1.1 round 3 found.
    #
    # Unanchored `سكر\w*` matches inside `عسكري` — "military" — one of the
    # commonest words in this corpus. FOUR of the six sampled `closure`
    # incidents were this one bug:
    #
    #   "حاجز عورتا العسكري"      a woman losing her fetus at a checkpoint
    #   "قرار عسكري اسراييلي"     a land-confiscation order
    #   "نقطة عسكرية"             a house seized as an army post
    #   "السكري"                  DIABETES, in a health-ministry note on
    #                             labour induction
    #
    # It also required the leading م of `مسكر`, so the anchored forms are
    # spelled out. This is the third time the same shape has bitten: "راي"
    # (opinion) inside "اسراييلي" (Israeli) rejected 142 real claims as
    # commentary, and "مش سالك" inside "حومش سالك" inverted a checkpoint. In
    # Arabic a short string is almost always inside a longer real word.
    ("closure",        _CLOSURE_PATTERN),
]

# Any of these and the message is not a report of a discrete local event.
REJECT_PATTERNS: list[tuple[str, str]] = [
    # Gaza — real news, wrong geography for a West Bank movement tracker.
    #
    # LANDMARKS, NOT JUST TOWNS. Claim 9516 — 118 killed on شارع الرشيد, bodies
    # recovered from دوار النابلسي to مجمع الشفاء — is Gaza in every phrase and
    # never says غزة. It sailed past this reject, and then the governorate
    # matcher found نابلس inside النابلسي and filed the massacre under Nablus.
    # The second bug is fixed at the matcher; this one is fixed by naming the
    # landmarks Gaza coverage actually uses. Multi-word phrases only where a
    # single word is ambiguous: الشفاء alone is "recovery" and appears in every
    # get-well wish for a West Bank casualty.
    ("gaza", r"(غزة|غزه|قطاع غزة|رفح|خان يونس|خانيونس|البريج|النصيرات|"
             r"دير البلح|بيت لاهيا|بيت حانون|جباليا|الشجاعية|المواصي|"
             r"شارع الرشيد|دوار النابلسي|مجمع الشفاء|مستشفى الشفاء|"
             r"كمال عدوان|المستشفى الاندونيسي|المستشفى المعمداني|المعمداني|"
             r"مستشفى ناصر|المغازي|الزوايدة|بني سهيلا|عبسان|"
             r"نتساريم|محور فيلادلفيا|الشيخ رضوان|تل الهوا)"),
    # A road/fuel STATUS bulletin is checkpoint or fuel data, not an incident.
    # Measured: three of twenty sampled `closure` incidents were these, and one
    # of them was reporting that the roads were OPEN. They duplicate the
    # checkpoint pipeline and misrepresent routine status as an event.
    # The article is OPTIONAL on every noun here. Without `ال?` the fuel
    # bulletin "احوال المحطات في مدينة قلقيلية ... جميع محطات المدينة مغلقة"
    # sailed past — the pattern had `محطات` but the text said `المحطات` — and
    # was served as a road CLOSURE in Qalqilya. A status bulletin reporting
    # that fuel stations are shut is the fuel pipeline's data; read as an
    # incident it becomes an event that never happened.
    # `(?:ال)?`, NOT `ال?`. The second means "alef, then an optional lam" — it
    # REQUIRES the alef — so "احوال طرق اريحا ومحيطها" never matched and a road
    # bulletin listing eight open checkpoints and one shut one was served as a
    # closure incident. The `\S+\s+ومحيطها` arm did not save it either: that
    # allows exactly one token between, and this had two.
    ("status bulletin", r"(احوال\s+(?:ال)?(طرق|بعض الطرق|حواجز|محطات|"
                        r"محطات الوقود)|احوال(\s+\S+){1,3}\s+ومحيطها)"),
    # A demolition ORDER is not a demolition. Kept out of the incident stream
    # rather than served as one — the act may never follow.
    # بهدم and لهدم: "إخطارات بهدم" and "34 إخطارًا لهدم" both sailed past the
    # (هدم|بالهدم) alternation and بهدم then matched the demolition pattern
    # INSIDE itself — a notice bulletin served as the act it only threatens.
    ("notice not act", r"(اخطار\w*\s+(هدم|بالهدم|بهدم|لهدم)|اوامر\s+هدم|"
                       r"انذار\w*\s+بالهدم|[يت]خطر\w*\s+ب?هدم|اخطرت\s+ب?هدم|"
                       r"تسليم\s+اخطار)"),
    # Follow-ups about an earlier event: a release days later, a family
    # inspecting old damage. Measured as four of seventeen sampled
    # `demolition` incidents — all one story about a woman freed after 8 days,
    # filed as a fresh demolition because the sentence mentions هدم.
    ("aftermath", r"(الافراج عن|افرجت?\s+\S*\s*عن|بعد\s+[\d٠-٩]+\s+(ايام|يوما|شهر)|"
                  # Round 5: a woman "خارج السجن" after a year served as a
                  # fresh arrest; a phone that exploded "قبل ايام" as a fresh
                  # injury; Al Jazeera's reconstruction of a months-old battle
                  # ("تعيد ... تركيب مشاهد") as a fresh death.
                  r"خارج السجن|بعد\s+(?:اكثر من\s+)?(?:عام|عامين)|"
                  r"قبل\s+(?:اشهر|شهور|اسابيع|ايام)|تركيب مشاهد|"
                  # "died of injuries sustained الأسبوع الماضي" — the event is
                  # last week's; today's news is its aftermath.
                  r"الاسبوع الماضي|"
                  # Testimony ABOUT an event: a shopkeeper narrating his
                  # eviction is coverage of coverage, not a fresh act.
                  r"يروي\s+تفاصيل|يتحدثون)"),
    # Period statistics and retrospectives are summaries, not events.
    #
    # MONTH NAMES, both calendars. Round 5 was drawn on Aug 1-3 and the
    # month-end tallies gutted it: every one of the seven sampled `death`
    # incidents was "16 شهيدا خلال يوليو" or its siblings, because this
    # pattern knew "خلال العام" but no month had a name. آب is written
    # with a lookahead because bare اب sits inside ابو.
    ("statistical", r"(خلال النصف الاول|خلال العام|خلال الاسبوع الماضي|"
                    r"خلال الشهر الماضي|احصائيه|إحصائية|حصيله\s+\S+\s+خلال|"
                    r"منذ\s+بدايه\s+(?:ال)?عام|"
                    r"خلال\s+(?:شهر\s+)?(?:يناير|فبراير|مارس|ابريل|مايو|يونيو|"
                    r"يوليو|اغسطس|سبتمبر|اكتوبر|نوفمبر|ديسمبر|"
                    r"كانون الثاني|شباط|اذار|نيسان|ايار|حزيران|تموز|اب(?!\w)|"
                    r"ايلول|تشرين الاول|تشرين الثاني|كانون الاول)|"
                    r"خلال شهر [0-9٠-٩]|وثق\w*\s+مركز|توثيق\s+\S+\s+حال)"),
    # A regional ROUNDUP aggregates many incursions into one story; serving it
    # as one incident pins a Bank-wide night to whichever village is named
    # first. Three of round 5's twenty `shooting` samples were these.
    ("roundup", r"(اقتحامات واعتقالات|اقتحامات ومواجهات|حمله اقتحامات|"
                r"تصعيد ميداني|يقتحم مدنا وبلدات|مدن وبلدات الضفه|"
                r"انحاء متفرقه من الضفه)"),
    # Court decisions about future demolitions are legal news, not field
    # events: "the high court rejected 15 petitions" was served as a SHOOTING.
    ("legal", r"(المحكمه العليا|التماس\w*)"),
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
                   # A FEATURE about a place is not an event in it (round 7:
                   # "Aaba east of Jenin under siege and demolition.. the council
                   # head talks about", "the camp of steadfastness despite the
                   # checkpoints", "a battle of existence").
                   # "يتحدث عن" was tried and removed: it rejected testimony
                   # about an ONGOING siege as often as a feature (2 vs 2).
                   r"معركه\s+وجود|يضيق\s+الخناق|"
                   r"لم\s+تعد\s+المسافه|يلتهم\s+الاستيطان|"
                   r"حكاية شهيد|تابعونا|اشترك|قناتنا|هل بات|كيف يحاول|"
                   r"في مثل هذا اليوم|رساله صمود)"),
    # Institutional statements rather than a located happening.
    ("statement", r"(نادي الاسير|نادي الأسير|تصريح|بيان صحفي|وزارة الصحة تعلن|"
                  r"تنعى|تدين|تستنكر|طالب\w* ب|دعا\w* الى|ناشد|"
                  # First-person-plural statements and calls to action are a
                  # faction speaking, not a field report.
                  r"\bندين\b|\bنستنكر\b|\bنؤكد\b|توجهوا\s+الي|كونوا\s+سندا|فكوا\s+حصار|"
                  r"اعتداءات\s+(?:المتكرره|المتكررة|متصاعده|متصاعدة))"),
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
                         "خربه", "خربة", "خله", "خلة", "تجمع",
                         # Movement infrastructure. An arrest "على مفرق فصايل"
                         # carried a resolvable junction name and the extractor
                         # walked straight past it to the arrested man's home
                         # village (round 3). These are whole-token checks, so
                         # the حي-inside-الرصاص-الحي substring hazard that keeps
                         # two-letter words out does not apply.
                         "حاجز", "مفرق", "مفترق", "دوار", "معبر"])
BEARING_WORDS = frozenset(["شمال", "جنوب", "شرق", "غرب", "شمالي", "جنوبي",
                           "شرقي", "غربي", "وسط", "شمالا", "جنوبا"])
GOVERNORATES = ["نابلس", "الخليل", "جنين", "طولكرم", "رام الله", "بيت لحم",
                "قلقيلية", "قلقيليه", "سلفيت", "اريحا", "أريحا", "طوباس",
                "القدس", "البيرة", "البيره"]
_GOV_TOKENS = frozenset(normalize(g) for g in GOVERNORATES) | {"رام", "الله"}

# Governorates are matched TOKEN-WISE, never by re.search over the string.
# `re.search(نابلس|...)` matched نابلس inside النابلسي — the Gaza roundabout —
# and claim 9516, reporting 118 killed on شارع الرشيد in Gaza, was filed as a
# death event in NABLUS (#37). The West Bank filter was defeated by the same
# match that caused the error, so no downstream check could catch it. A
# governorate is only named when it stands as its own word, possibly behind a
# fused conjunction/preposition and the article: بنابلس، والخليل، للقدس.
_GOV_SINGLE = frozenset(normalize(g) for g in GOVERNORATES if " " not in g)
_GOV_PAIRS = tuple(tuple(normalize(g).split()) for g in GOVERNORATES if " " in g)


def _defused(tok: str) -> list[str]:
    """The token plus its readings with fused prefixes removed, outermost first.

    Arabic writes conjunction and preposition onto the word: وبالخليل is
    و+ب+الخليل. Candidates are generated by peeling at most one conjunction
    (و ف), one preposition (ب ل ك), and the article — plus the لل contraction,
    where ل+الخليل is written للخليل with the article's alef elided. The
    original token always stays a candidate: real names begin with these
    letters (بيت لحم), so peeling is additive, never a replacement."""
    out = [tok]
    t = tok
    if t[:1] in "وف" and len(t) > 3:
        t = t[1:]
        out.append(t)
    if t[:1] in "بلك" and len(t) > 3:
        if t[:2] == "لل" and len(t) > 4:
            out.append("ال" + t[2:])
        t = t[1:]
        out.append(t)
    if t[:2] == "ال" and len(t) > 4:
        out.append(t[2:])
    return out


def _find_governorate(toks: list[str]) -> str | None:
    """First governorate named as a whole word, in canonical normalized form."""
    for i, t in enumerate(toks):
        for cand in _defused(t):
            if cand in _GOV_SINGLE:
                return cand
            for pair in _GOV_PAIRS:
                if cand == pair[0] and i + 1 < len(toks) and toks[i + 1] == pair[1]:
                    return " ".join(pair)
    return None


# Words naming a PERSON, article-stripped before comparison. Used to tell a
# residence from an incident site — see the origin guard in _extract_place.
_PERSON_WORDS = frozenset([
    "شاب", "شابا", "شابان", "شبان", "فتي", "فتاه", "طفل", "طفلا", "طفله",
    "مواطن", "مواطنا", "مواطنه", "مواطنان", "مواطنين", "اسير", "اسيرا",
    "اسيره", "اسري", "معتقل", "معتقلا", "شهيد", "شهيدا", "شهيده",
    "مسن", "مسنا", "مسنه", "سيده", "جريح", "مصاب", "عامل", "عاملا",
])


def _is_person(tok: str) -> bool:
    bare = tok[2:] if tok.startswith("ال") and len(tok) > 3 else tok
    return bare in _PERSON_WORDS

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
# Funeral / obituary / memorial vocabulary. Deliberately WITHOUT the bare جثمان
# ("body"): a fresh death report often says where the body was taken.
_FUNERAL_RE = re.compile(_norm_pat(
    r"(تشييع|شيعت|شيع\s+جثمان|[يت]شيع\w*|جنازه|جنازة|موكب\s+(?:الشهيد|جنازه|جنازة|تشييع)|"
    r"\bنعي\b|[يت]نعي|ينعي|تنعي|بيت\s+عزاء|عزاء|وداع\s+الشهيد|[يت]ودع\w*|يوم\s+الوداع|"
    r"ذكري\s+(?:استشهاد|رحيل)|الذكري\s+ال\S+\s+لاستشهاد|"
    # A EULOGY: a faction or a family "zaffs" (announces) its martyr — the
    # report of the killing came earlier, from a news channel. Round 7's
    # eleven wrong death rows were nine of these.
    r"\bتزف\b|\bيزف\b|\bنزف\b|تزف\w*\s+(?:حركه|حركة|كتائب|الكتله|الكتلة|سرايا)|"
    r"الشهيد\s+المجاهد|شهيدها\s+المجاهد|المجاهد\s+الشهيد|ابنها\s+البار|ابنه\s+البار|"
    r"القائد\s+الشهيد|القامه\s+الفلسطينيه|تقبل\s+الله|تقبله\s+الله|رحمه\s+الله|"
    # NOT a bare relative clause ("الشهيد X الذي ارتقى برصاص الاحتلال" is how a
    # plain report names the man, and rejecting it cost a real death in
    # round 7); the eulogy is recognised by its honorifics and its media.
    # Memorial media and back-story: an earlier video, a song, chants, a year.
    r"فيديو\s+سابق|مقطع\s+سابق|كلمات\s+الشهيد|وصيه\s+الشهيد|انشوده|الانشوده|قصيده|"
    r"هتافات|زغرتي|اقمار\s+في\s+سماء|شيخ\s+المطاردين|"
    r"(?:عام|سنه|سنة)\s+20[0-2][0-9]\b)"))
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
        # ORIGIN IS NOT SITE. "اعتقل الشاب محمد من قرية المغير" states where
        # the man is FROM; the arrest happened wherever the rest of the
        # sentence says. Round 3 measured this as a distinct failure class —
        # an arrest at مفرق فصايل was pinned to المغير, the arrested man's home
        # village — and 12 of 20 round-3 failures were place resolution. When
        # the place word follows من and a person stands just before it, this
        # candidate is a residence: skip it and keep scanning. A troop
        # withdrawal ("انسحبت قوات الاحتلال من قرية X") survives, because
        # قوات is not a person word.
        if (i > 0 and toks[i - 1] in ("من", "ومن")
                and any(_is_person(p) for p in toks[max(0, i - 5):i - 1])):
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

    # Governorate, wherever it appears — but only as its own word (see
    # _find_governorate for the النابلسي/#37 failure). Recorded separately from
    # the name so a village keeps its admin2 context for disambiguation —
    # several West Bank villages share a name across governorates.
    gov = _find_governorate(toks)
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

    # AN OBITUARY OR A FUNERAL IS NOT A DEATH REPORT (ZAID-9, 2026-09-23).
    # 36 of the 51 wrong rows in precision round 7 were funerals, obituaries and
    # memorial features read as deaths — the whole gap between 0.717 and the
    # 0.80 gate. The gate applies to DEATHS ONLY: funeral words appear in raid
    # and settler-attack reports too (a funeral procession attacked, a raid
    # during a wake), and those are events.
    if inc[0] == "death":
        fun = _FUNERAL_RE.search(norm)
        if fun:
            return NewsReading(verdict="rejected", reject_reason="obituary or funeral",
                               matched=fun.group(0)[:60])

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
