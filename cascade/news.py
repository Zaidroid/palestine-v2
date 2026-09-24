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
                       # Round 8: "يغتال عبد الكريم بني جابر .. حصار واشتباكات" was
                       # served as a SIEGE because the killing had no verb here.
                       r"اغتال\w*|[يت]غتال\w*|اغتيال|[يت]عدم\w*|اعدام\w*\s+ميداني|"
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
                       r"حطم|دهس|قتح|سيطر|ستيلا|ستول|دشن|"
                       # Round 8 misses: grazing livestock in a village's olive
                       # groves and "desecrating" al-Aqsa are settler incursions.
                       r"مواشيهم|اغنامهم|قطعانهم|باغنام|بمواشي|بقطعان|ستبيح|ستباح|"
                       r"رعي\s+(?:اغنام|مواشي|ابقار|قطعان))"
                       r"|(عتد|هاجم|هجوم|عربد|عربده|قتح|رشق|قتلع|ضرم|شعال)\w*"
                       r"(?:\s+\S+){0,3}?\s*\S*(مستوطن|قطعان))"),
    # A beating by the army is harm without an injury noun: "تعتدي بالضرب على
    # صاحب محل" was rejected as having no incident verb (round 5). Settler
    # beatings keep their actor — settler_attack sits above this entry.
    ("injury",         r"(اصاب\w*|إصاب\w*|جرح\w*|اصيب|أصيب|اختناق|"
                       r"[اتين]?عتد\w*\s+بالضرب|اعتداء بالضرب|"
                       r"عتد\w*\s+علي\w*\s+بالضرب|الضرب\s+المبرح)"),
    # Arabic marks person/tense with a PREFIX, so "تقتحم" / "يقتحم" share no
    # leading letters with "اقتحم". Matching only the perfective missed the
    # commonest headline form in this corpus — "قوات الاحتلال تقتحم بلدة بيت
    # امر" — so every verb here is written as prefix + consonantal stem.
    # Stem "قتح", not "قتحم": the verbal noun "اقتحام" is ا-ق-ت-ح-ا-م and does
    # not contain the fuller stem, so requiring it dropped every headline that
    # names the raid rather than conjugating it.
    ("raid",           r"([اتين]?قتح\w*|[تي]?داهم\w*|مداهم\w*|توغل\w*|"
                       # A heavy troop deployment in a town's streets is an
                       # incursion (round 8 miss, Anata).
                       r"انتشار\s+(?:مكثف\s+|واسع\s+)?(?:ل?قوات|ل?جنود)\s+الاحتلال|انتشار\s+عسكري)"),
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
                       r"تسليم\s+اخطار|"
                       # Round 8: a threat, a "threatened with demolition"
                       # school, orders issued (at the head of the text, or as
                       # a COUNT of orders anywhere), a farmer leaving after
                       # "the occupation's notice to demolish it".
                       r"تهديد\w*\s+بهدم|مهدد\w*\s+(?:\S+\s+){0,2}?بالهدم|"
                       r"^\W*(?:\S+\s+){0,5}?(?:(?:[يت]صدر\w*|اصدر\w*)\s+(?:\S+\s+){0,3}?اوامر|"
                       r"اوامر\s+(?:عسكريه|بتجريف|جديده|مصادره))|"
                       r"اصدار\s+[\d٠-٩]+\s+(?:امر|اوامر)|[\d٠-٩]+\s+(?:امر|اوامر)\s+(?:هدم|عسكري\w*|مصادره)|"
                       r"اخطار\w*\s+(?:الاحتلال\s+)?ب?هدم\w*)"),
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
    ("statistical", r"(خلال النصف الاول|النصف\s+الاول\s+من\s+20|[\d٠-٩]{3,}\s+اعتداء|"
                    r"خلال العام|خلال الاسبوع الماضي|"
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
                r"انحاء متفرقه من الضفه|"
                # Round 8: "settler attacks in the past 24 hours", "in one week
                # more than 100 orders", "104 homes since 7 October", "the
                # main field developments" — many events, no one place.
                r"خلال\s+(?:24|٢٤)\s+ساعه|خلال\s+اسبوع\s+واحد|منذ\s+(?:7|٧)\s+اكتوبر|"
                r"ابرز\s+(?:المستجدات|الاحداث|اخبار)|الاشهر\s+(?:\S+\s+)?الماضيه|"
                r"خلال\s+الاشهر)"),
    # A propaganda channel's signature: the messages of the dead are not
    # reports (round 8: five of the twelve funeral-stratum rows).
    ("propaganda", r"(ارث العاروري|رساله الشيخ القائد|قناه ارث)"),
    # Court news: an acquittal months after the assault, a detention extended.
    ("court", r"([يت]برئ\w*|تبرئه|براءه\s+|تمديد\s+اعتقال|[يت]مدد\w*\s+اعتقال|"
              r"الحكم\s+علي|[يت]حكم\w*\s+علي|محكمه\s+\S+\s+(?:تقضي|تصدر|ترفض|تقرر))"),
    # A vigil, a march, a ceremony at the head of the text is the subject.
    ("gathering", r"^\W*(?:\S+\s+)?(?:وقفه|مسيره|فعاليه|حفل|مهرجان|معرض|ورشه|ندوه|مؤتمر)\b"),
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
                  # Round 8: a faction official or a party speaking, in the
                  # third person or the first-person plural.
                  r"القيادي\s+في|القياديه\s+في|\bحماس\s*:|\bفتح\s*:|الجهاد\s+الاسلامي|"
                  r"زياره\s+(?:اجراها\s+)?المحامي|تفاصيل\s+ظروف\s+اعتقال|"
                  r"الناطق\s+باسم|المتحدث\s+باسم|\bنحذر\b|\bنبارك\b|\bندعو\b|\bنناشد\b|"
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
_GOV_PAIR_NAMES = frozenset(" ".join(p) for p in _GOV_PAIRS)


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


# A governorate's name after one of these is a STREET named after the city:
# "شارع القدس شرق نابلس" is in Nablus, "بمنطقة شارع نابلس" in Tulkarm (round 8,
# two wrong places).
_STREET_HEADS = frozenset(["شارع", "طريق", "مدخل"])


def _find_governorate(toks: list[str]) -> str | None:
    """First governorate named as a whole word, in canonical normalized form."""
    for i, t in enumerate(toks):
        if i > 0 and _bare(toks[i - 1]) in _STREET_HEADS:
            continue
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
    "عائله", "عايله", "اسره", "الاسير", "المطارد", "مطارد",
    "شابين", "الشابين", "الشابان", "فتيين", "طفلين", "مواطنين", "اسيرين",
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
    # Administrative and relational words that follow a name without being
    # part of it: "ترمسعيا قضاء رام الله", "قصرة بمحافظة نابلس".
    "بين", "قضاء", "محافظه", "لواء", "ضواحي", "نواحي", "المجاوره", "المحيطه",
    "الخارج", "الداخل", "للخارج", "للداخل", "باتجاه", "اتجاه",
    "القريبه", "داخل", "خارج", "امام", "خلف", "قباله", "مقابل", "تجاه", "نحو",
    "حتي", "منذ", "عند", "عبر", "ضد", "لدي", "بينما", "ثم", "لكن", "ان",
    "انه", "هذا", "هذه", "تلك", "ذلك", "كل", "بعض", "عده", "عدد", "قرابه",
    "اكثر", "اقل", "فجر", "ظهر", "ليل", "ليله", "الليله", "الماضيه", "الجاريه",
    "الاسرائيلي", "الاسرائيليه", "المستوطنون", "مستوطنون", "مستوطنه",
    "مستوطنات", "بؤره", "الفلسطينيه", "الفلسطيني", "فلسطين",
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
    # Every name the text offers, most trusted first, with how it was read
    # (place_word | dual | prefix | bearing | cue | between | conjunct).
    place_candidates: list[tuple[str, str]] = field(default_factory=list)


_INCIDENT_RE = [(lbl, re.compile(_norm_pat(p))) for lbl, p in INCIDENT_PATTERNS]
# Funeral / obituary / memorial vocabulary. Deliberately WITHOUT the bare جثمان
# ("body"): a fresh death report often says where the body was taken.
_FUNERAL_RE = re.compile(_norm_pat(
    r"(تشييع|شيعت|شيع\s+جثمان|[يت]شيع\w*|جنازه|جنازة|موكب\s+(?:الشهيد|جنازه|جنازة|تشييع)|"
    r"\bنعي\b|[يت]نعي|ينعي|تنعي|ننعي|بيت\s+عزاء|عزاء|وداع\s+الشهيد|[يت]ودع\w*|يوم\s+الوداع|"
    # Round 8: "a sad farewell to the young man", "scenes from the farewell of",
    # "during the farewell of his brother", a body handed back months later, a
    # grave visited, a martyr of two years ago.
    r"وداع\s+(?:حزين\s+)?(?:ل?لشاب|ل?لطفل|ل?لفتي|ل?لشهيد|القمر|الطفل|الشاب|الفتي|شقيق\w*)|"
    r"مشاهد\s+من\s+وداع|خلال\s+وداع|استلام\s+جثمان|تسليم\s+جثمان|[يت]زور\w*\s+قبر|زياره\s+قبر|"
    r"قبل\s+(?:عام|عامين|سنه|سنتين|[\d٠-٩]+\s+(?:اعوام|سنوات|اشهر|شهور))|"
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
# A farewell or an obituary AT THE HEAD of the text is its subject, whatever
# verb follows (round 8: "وداع الشهيد الفتى .. خلال هجوم للمستوطنين" served as a
# settler attack). Not تشييع: a funeral procession attacked is an event.
_HEAD_FUNERAL_RE = re.compile(_norm_pat(
    r"^\W*(?:\S+\s+){0,3}?(?:وداع|جنازه|موكب\s+(?:الشهيد|الجنازه)|ننعي|نعي)\b"))
_RELEASE_RE = re.compile(_norm_pat(r"^\W*(?:\S+\s+){0,4}?(?:[يت]فرج\w*\s+عن|الافراج\s+عن)"))
_HARM_RE = re.compile(_norm_pat(r"(بالضرب|تنكيل|اصاب|إصاب|استشه|ارتقي|ارتقى)"))
_ACCIDENT_RE = re.compile(_norm_pat(r"حادث\s+(?:سير|مروري|طرق|تصادم)"))
_TESTIMONY_RE = re.compile(_norm_pat(r"([يت]تحدث\w*\s+عن|[يت]روي\s+)"))
_SIEGE_WORDS_RE = re.compile(_norm_pat(r"(حصار|محاصر)"))
_RAID_VERB_RE = re.compile(_norm_pat(r"([اتين]?قتح\w*|[تي]?داهم\w*|مداهم\w*|توغل\w*)"))
_ARMY_RE = re.compile(_norm_pat(r"(قوات|جيش|جنود|الاحتلال|شرطه|قوه)"))
_SETTLER_RE = re.compile(_norm_pat(r"(مستوطن|قطعان)"))
_HOMES_LEVELLED_RE = re.compile(_norm_pat(
    r"(?:تجريف|[يت]جرف\w*|جرفت)\s+(?:\S+\s+){0,3}?(?:مساكن|منازل|منزل|مسكن|بركسات|بركس|بيوت(?!ا?\s+بلاستيك)ا?)"))


def _first_match(text: str, patterns) -> tuple[str, str] | None:
    for label, rx in patterns:
        m = rx.search(text)
        if m:
            return label, m.group(0)[:60]
    return None


# Dual settlement words name TWO places at once — "بين بلدتي جالود وقصرة" — and
# the waw that joins them ends the first name and starts the second.
_DUAL_WORDS = frozenset(["قريتي", "بلدتي", "مدينتي", "مخيمي", "خربتي",
                         "قريتين", "بلدتين", "مخيمين"])

# Site words that are not settlement words. They say WHERE without saying what
# kind of place it is: "منطقة الديرات", "حي الطيرة", "سهل عرابة", "جبل
# الرحمة", "وادي الرخيم", "مدخل المنشية", "طريق المهلل", "أراضي قصرة". Measured
# on the 936 governorate-only events whose text named no settlement word
# (2026-09-24): منطقه appeared in 168 of them, طريق in 70, شارع in 54, حي in
# 49. Whole-token, bare or behind a fused preposition, never behind the
# article — "المنطقة الشرقية" is a description, not a name. What follows one
# resolves by exact or contained alias only; the gazetteer decides.
_CUE_WORDS = frozenset(["منطقه", "حي", "شارع", "سهل", "جبل", "واد", "وادي", "مدخل",
                        "طريق", "بوابه", "مقام", "عزبه", "اراضي", "اطراف", "محيط",
                        # "رئيس مجلس قروي فقوعة: اقتحم مستوطنون محيط منازل
                        # المواطنين في القرية" — the village is named only in
                        # the council's title (round 8 miss).
                        "قروي", "بلديه", "بلدي"])

# Toponym prefixes: a token that, with the next one, is a name on its own —
# "بيت أمر", "دير شرف", "كفر قدوم", "عين سينيا", "أبو نجيم", "أم صفا", "خربة
# التبان", "عرب الجهالين". Only an exact alias can answer for one of these (no
# contained fragment, no fuzzy neighbour): "أبو" opens a kunya as often as a
# village, and the gazetteer is the only thing that can tell them apart.
_NAME_PREFIXES = frozenset(["بيت", "دير", "كفر", "عين", "خربه", "خله", "عزبه",
                            "راس", "ام", "ابو", "عرب", "بير"])

# A region that is not a place: "خلة الحمص بمسافر يطا" names the hamlet, and
# "مسافر يطا" alone must not collapse to the town of Yatta.
_REGION_HEADS = frozenset(["مسافر", "بمسافر", "لمسافر", "ومسافر",
                           "الاغوار", "بالاغوار", "والاغوار", "اغوار"])

# Ranking of the ways a candidate was found, most trusted first. Within a
# rank, text order.
_HOW_RANK = {"place_word": 0, "station_word": 0, "dual": 0, "cue": 1, "bearing": 1,
             "prefix": 2, "between": 3, "conjunct": 4}
# A capture after one of these names a checkpoint, crossing or junction — the
# resolver should prefer that row over the village of the same name.
_STATION_WORDS = frozenset(["حاجز", "مفرق", "مفترق", "دوار", "معبر"])


def _word_class(tok: str, words: frozenset) -> bool:
    """Whole-token membership, bare or behind ONE fused preposition/conjunction
    (بحي، لمنطقه، وكفر). The article is deliberately not peeled here."""
    if tok in words:
        return True
    return len(tok) >= 3 and tok[0] in "بلكفو" and tok[1:] in words


def _bare(tok: str) -> str:
    for words in (PLACE_WORDS, _DUAL_WORDS, _CUE_WORDS, _NAME_PREFIXES):
        if tok in words:
            return tok
        if len(tok) >= 3 and tok[0] in "بلكفو" and tok[1:] in words:
            return tok[1:]
    return tok


def _ends_name(tok: str, first: bool) -> bool:
    """Whether a token ends the name being read, seen through any fused
    conjunction, preposition or article.

    "بمسافر" ends "خلة الحمص بمسافر يطا" at الحمص; "والقرى" ends "قرية جنيد
    والقرى المحيطة" at جنيد; "بالخليل" ends "خلة X بالخليل" at X. A cue word
    ends a name only when it is not the name's first token — "قرية وادي فوكين"
    keeps its وادي.
    """
    if len(tok) < 2 or tok.isdigit():
        return True
    for cand in _defused(tok):
        if (cand in _STOP_TOKENS or cand in PLACE_WORDS or cand in _DUAL_WORDS
                or cand in _REGION_HEADS or cand in _GOV_SINGLE):
            return True
        if not first and cand in _CUE_WORDS:
            return True
    return False


def _extract_places(text: str) -> tuple[list[tuple[str, str]], str | None]:
    """Every candidate place name in the text, most trusted first, plus the
    governorate when one is stated.

    Four readers, each measured against the corpus on 2026-09-24:

      place_word / dual  the 1–3 tokens after a settlement word ("بلدة",
                         "قرية", "مخيم", "خربة"…, or a dual "بلدتي X وY") —
                         the original reader, now returning every occurrence
                         rather than the first;
      prefix             a toponym prefix and its next token ("بيت أمر",
                         "خربة التبان");
      bearing            the tokens before "<bearing> <governorate>" — "قصرة
                         جنوب نابلس", "يرزا شرق طوباس" — emitted shortest
                         suffix first;
      cue / between      what follows a site word ("منطقة الديرات") or sits
                         between "بين" and a waw ("بين مركة وقباطية").

    Nothing here decides that a candidate IS a place; the gazetteer does that,
    in `ingest.sources.news_incidents.locate`, which also enforces that the
    resolved place lies in the governorate the message named. This function
    only refuses to LOSE a name: 881 of the 1,260 governorate-only events
    measured on 2026-09-24 carried a name the old single-pass reader never
    looked at.
    """
    toks = normalize(text).split()
    n = len(toks)
    found: list[tuple[str, str, int]] = []      # (name, how, text position)
    seen: set[str] = set()
    skipped: set[int] = set()                   # residences: origin ≠ site

    def add(parts: list[str], how: str, pos: int, gov_ok: bool = False) -> None:
        name = " ".join(parts).strip()
        if not name or name in seen:
            return
        if all(t in _CUE_WORDS for t in parts):
            return                                  # "بمنطقة شارع نابلس" → "شارع"
        # A governorate's name is a place only when a settlement word says so
        # ("مدينة نابلس"). Read off a prefix or a bearing it is the governorate
        # mention itself: "برية زعترة جنوب بيت لحم" must not pin to the city.
        if not gov_ok and (name in _GOV_TOKENS or name in _GOV_SINGLE
                           or name == normalize("رام الله")):
            return
        if not gov_ok and all(_ends_name(t, True) for t in parts):
            return
        seen.add(name)
        found.append((name, how, pos))

    def capture(i: int, how: str, gov_head: bool) -> None:
        """The name after the word at i. A governorate right after the word is
        the name itself ("مدينة نابلس") unless the word is a cue — "شارع نابلس"
        is a street named after the city, not the city."""
        head = toks[i + 1:i + 3]
        if head and head[0] in _GOV_TOKENS:
            if not gov_head:
                return
            two = " ".join(head)
            if two in _GOV_TOKENS or normalize("رام الله") == two:
                add([two], how, i, gov_ok=True)
            else:
                add([head[0]], how, i, gov_ok=True)
            return
        parts: list[str] = []
        j = i + 1
        while j < n and len(parts) < 3:
            nxt = toks[j]
            if _ends_name(nxt, first=not parts):
                break
            if parts and nxt.startswith("و") and len(nxt) > 3:
                # A conjunction: the first name ends, a second begins.
                add(parts, how, i)
                rest = [nxt[1:]]
                k = j + 1
                while (k < n and len(rest) < 3 and not _ends_name(toks[k], False)
                       and not (toks[k].startswith("و") and len(toks[k]) > 3)):
                    rest.append(toks[k])
                    k += 1
                add(rest, "conjunct", j)
                return
            parts.append(nxt)
            j += 1
        if parts:
            add(parts, how, i)
            # "رئيس مجلس قروي فقوعة بركات العمري": the village, then the
            # council head's name. The first token alone is offered too.
            if how == "cue" and len(parts) > 1:
                add(parts[:1], how, i)

    # ── 0. landmarks the gazetteer holds under the city ───────────────────────
    # "المسجد الأقصى" has no settlement word before it and is stormed weekly;
    # its aliases point at Jerusalem (round 8: two misses).
    for i, t in enumerate(toks):
        if t in ("الاقصي", "للاقصي", "بالاقصي"):
            add(["المسجد", "الاقصي"], "place_word", i)
            break

    # ── 1. settlement words, dual forms, cue words ────────────────────────────
    for i, t in enumerate(toks):
        is_settlement = _is_place_word(t) or _word_class(t, _DUAL_WORDS)
        if not is_settlement and not _word_class(t, _CUE_WORDS):
            continue
        if is_settlement:
            # ORIGIN IS NOT SITE. "اعتقل الشاب محمد من قرية المغير" states where
            # the man is FROM; the arrest happened wherever the rest of the
            # sentence says. Round 3 measured this as a distinct failure class —
            # an arrest at مفرق فصايل was pinned to المغير, the arrested man's
            # home village — and 12 of 20 round-3 failures were place
            # resolution. When the place word follows من and a person stands
            # just before it, the candidate is a residence: skip it, and keep
            # the later readers off those tokens too. A troop withdrawal
            # ("انسحبت قوات الاحتلال من قرية X") survives: قوات is not a person.
            if (i > 0 and toks[i - 1] in ("من", "ومن")
                    and any(_is_person(p) for p in toks[max(0, i - 5):i - 1])):
                skipped.update(range(i, i + 4))
                continue
            if _bare(t) in _STATION_WORDS:
                capture(i, "station_word", True)
            else:
                capture(i, "dual" if _word_class(t, _DUAL_WORDS) else "place_word", True)
        else:
            # "حي" is also the adjective in "رصاص حي" (live fire).
            if _bare(t) == "حي" and i > 0 and "رصاص" in toks[i - 1]:
                continue
            capture(i, "cue", False)

    # ── 2. the tokens before "<bearing> <governorate>" ────────────────────────
    j = 0
    while j < n:
        if toks[j] not in BEARING_WORDS:
            j += 1
            continue
        k = j
        while k + 1 < n and toks[k + 1] in BEARING_WORDS:
            k += 1
        after = toks[k + 1:k + 3]
        anchored = bool(after) and (after[0] in _GOV_SINGLE
                                    or " ".join(after) in _GOV_PAIR_NAMES
                                    or after[0] in ("المدينه", "مدينه"))
        if anchored:
            parts: list[str] = []
            i = j - 1
            while i >= 0 and len(parts) < 3:
                tok = toks[i]
                if (i in skipped or _is_person(tok) or _is_place_word(tok)
                        or _word_class(tok, _DUAL_WORDS) or _word_class(tok, _CUE_WORDS)
                        or _ends_name(tok, first=not parts)):
                    break
                if tok.startswith("و") and len(tok) > 3:
                    parts.insert(0, tok[1:])
                    break
                parts.insert(0, tok)
                i -= 1
            # "في مسافر يطا جنوب الخليل": a region, not the town of Yatta.
            if parts and (i >= 0 and toks[i] in _REGION_HEADS or parts[0] in _REGION_HEADS):
                parts = []
            # "قرية زويدين شرق يطا جنوب الخليل": what sits before "جنوب الخليل"
            # is "شرق يطا" — a REFERENCE town, not the site (round 8).
            if parts and i >= 0 and toks[i] in BEARING_WORDS:
                parts = []
            if parts and " ".join(parts) not in seen:
                for length in range(len(parts), 0, -1):
                    add(parts[-length:], "bearing", j)
        j = k + 1

    # ── 3. toponym prefixes ───────────────────────────────────────────────────
    for i, t in enumerate(toks):
        if i in skipped or i + 1 >= n:
            continue
        bare = _bare(t)
        if bare not in _NAME_PREFIXES:
            continue
        # The same residence guard as reader 1: "شابا من بيت أمر ويداهم
        # منازل في تفوح" arrests a man FROM Beit Ummar in Tuffah.
        if (i > 0 and toks[i - 1] in ("من", "ومن")
                and any(_is_person(q) for q in toks[max(0, i - 5):i - 1])):
            continue
        nxt = toks[i + 1]
        if _ends_name(nxt, True) or _is_person(nxt) or _is_place_word(nxt):
            continue
        add([bare, nxt], "prefix", i)
        if (bare in ("خربه", "خله", "عزبه", "عرب") and i + 2 < n
                and not _ends_name(toks[i + 2], False)
                and not toks[i + 2].startswith("و")):
            add([bare, nxt, toks[i + 2]], "prefix", i)

    # ── 4. "بين X وY" ─────────────────────────────────────────────────────────
    for i, t in enumerate(toks):
        if t != "بين" or i + 1 >= n:
            continue
        if _is_place_word(toks[i + 1]) or _word_class(toks[i + 1], _DUAL_WORDS):
            continue                                    # reader 1 has it
        parts = []
        j = i + 1
        while j < n and len(parts) < 3:
            tok = toks[j]
            if _ends_name(tok, first=not parts) or _is_person(tok):
                break
            if parts and tok.startswith("و") and len(tok) > 3:
                break
            parts.append(tok)
            j += 1
        if not parts or j >= n or not toks[j].startswith("و") or len(toks[j]) < 4:
            continue
        add(parts, "between", i)
        rest = [toks[j][1:]]
        k = j + 1
        while k < n and len(rest) < 3 and not _ends_name(toks[k], False):
            rest.append(toks[k])
            k += 1
        add(rest, "between", j)

    found.sort(key=lambda f: (_HOW_RANK[f[1]], f[2]))
    gov = _find_governorate(toks)
    return [(name, how) for name, how, _pos in found], gov


def _extract_place(text: str) -> tuple[str | None, str | None]:
    """(place name, governorate) — the most trusted candidate, for callers and
    tests that want one answer; `_extract_places` returns them all."""
    cands, gov = _extract_places(text)
    return (cands[0][0] if cands else None), gov


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
    itype = inc[0]
    if itype == "death":
        fun = _FUNERAL_RE.search(norm)
        if fun:
            return NewsReading(verdict="rejected", reject_reason="obituary or funeral",
                               matched=fun.group(0)[:60])
    head_fun = _HEAD_FUNERAL_RE.search(norm)
    if head_fun:
        return NewsReading(verdict="rejected", reject_reason="obituary or funeral",
                           matched=head_fun.group(0)[:60])
    # ROUND 8 (2026-09-24), each class measured on a fresh sample:
    # a release is not an arrest — unless the text reports the harm done
    # in custody, which is the event;
    if itype == "arrest" and _RELEASE_RE.search(norm) and not _HARM_RE.search(norm):
        return NewsReading(verdict="rejected", reject_reason="release",
                           matched=_RELEASE_RE.search(norm).group(0)[:60])
    # a traffic accident is not an occupation injury (a road it closes is
    # still a closure, so only these two types);
    if itype in ("injury", "death") and _ACCIDENT_RE.search(norm):
        return NewsReading(verdict="rejected", reject_reason="traffic accident",
                           matched=_ACCIDENT_RE.search(norm).group(0)[:60])
    # someone TALKING ABOUT harassment is a testimony; kept only for a siege,
    # where the testimony is the ongoing event (measured 2 vs 2 in round 7);
    tm = _TESTIMONY_RE.search(norm)
    if tm and not _SIEGE_WORDS_RE.search(norm):
        return NewsReading(verdict="rejected", reject_reason="testimony",
                           matched=tm.group(0)[:60])
    # settlers storming homes are a settler attack, not an army raid;
    if itype == "raid":
        rv = _RAID_VERB_RE.search(norm)
        before = norm[:rv.start()] if rv else ""
        if _SETTLER_RE.search(before) and not _ARMY_RE.search(before):
            itype = "settler_attack"
    # homes bulldozed are a demolition, whatever the verb.
    if itype == "land_levelling" and _HOMES_LEVELLED_RE.search(norm):
        itype = "demolition"

    candidates, gov = _extract_places(norm)
    place_text = candidates[0][0] if candidates else None
    if not place_text and not gov:
        # An action with nowhere to put it is not usable by anything that
        # answers "what is happening near me".
        return NewsReading(verdict="unclear", incident_type=itype,
                           reject_reason="no resolvable West Bank place")

    # A named settlement plus its governorate is the strongest shape; a bare
    # governorate locates the report only to admin2 and is worth less.
    conf = 0.80 if (place_text and gov) else (0.70 if place_text else 0.55)
    return NewsReading(
        verdict="incident", incident_type=itype, place_text=place_text,
        governorate=gov, confidence=conf, matched=inc[1],
        is_closure=itype in ("closure", "siege"),
        evidence=[inc[1]],
        place_candidates=candidates,
    )
