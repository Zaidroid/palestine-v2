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
    # Dual, plural and dialect forms the channels use, absent until the
    # 2026-09-25 audit (F020): "حوارة مسكرين", "مقفول", "الحاجزين مغلقان" were
    # read as nothing, so a closure was lost and the last "open" kept serving.
    "مغلقان": "closed", "مغلقتان": "closed", "مغلقتين": "closed",
    "مسكرين": "closed", "مسكرات": "closed", "مقفول": "closed",
    "مقفوله": "closed", "مقفولين": "closed", "سكروه": "closed",
    "سكرت": "closed", "اغلق": "closed", "اغلقت": "closed",
    "يغلق": "closed", "تغلق": "closed",
    # The 2026-10-11 audit read the 10,174 stored lines this table could not:
    # "جبع سلك" (it cleared), "عين شبلي بسلك بالاتجاهين", "صره للخارج بلش يمشي",
    # "المربعة فاضية" (empty: nothing waiting), "عين سينا مازم", "عين سينيا ارمه".
    "بسلك": "open", "بمشي": "open", "بتمشي": "open", "يمشي": "open",
    # "عين سينيا بحري", "دير شرف بحري حاليا بدون جيش": the channels' own word
    # for clear. 2,242 short stored lines; a caution follows one within 45
    # minutes 15% of the time, exactly the rate after "سالك".
    "بحري": "open",
    "فاضي": "open", "فاضيه": "open", "فاضيين": "open", "فاضين": "open",
    "مازم": "congested", "ازم": "congested", "ازمات": "congested",
    "ازمتها": "congested", "ارمه": "congested",
    # "صره زفت لطالع", "عورتا للخارج سيء": bad, with no word for how. Read as
    # the milder caution, at the confidence of a vague word (_SOFT).
    "زفت": "congested", "سيء": "congested", "سيي": "congested", "سييه": "congested",
}


def _forms(perfects: tuple, participles: tuple, value: str, objects: bool = True) -> dict[str, str]:
    """Every person, number and object form of a closing or opening stem.

    The table above was grown one miss at a time and 383 stored closures were
    still unread on 2026-10-11, each in a form nobody had typed in yet: "سكرو
    النبي صالح", "مسكرينها", "مغلقات", "فتحوهم", "سالكات". These channels
    conjugate freely, so the forms are generated from the stem instead.
    """
    out: dict[str, str] = {}
    for p in perfects:
        for subj in ("", "ت", "و", "وا"):
            out[p + subj] = value
            if objects:
                for obj in ("ه", "ها", "هم", "هن"):
                    out[p + ("و" if subj == "وا" else subj) + obj] = value
    for p in participles:
        for num in ("", "ه", "ا", "ين", "ات", "ان", "تين", "تان"):
            out[p + num] = value
        if objects:
            for obj in ("ه", "ها", "هم", "هن"):
                out[p + obj] = value
                out[p + "ين" + obj] = value
    return out


# "فتحه" is left out: it is the noun in "اعادة اغلاقه بعد فتحه لعدة دقائق" (closed
# again after its opening), where reading it as a verb served the gate open.
# No form of سد: "سدة قراوة" and "سده الفحص" are places.
_NOT_FORMS = frozenset(["فتحه"])
for _k, _v in {
        **_forms(("سكر", "قفل", "اغلق", "غلق"), ("مسكر", "مقفل", "مغلق", "مقفول"), "closed"),
        **_forms(("فتح",), ("فاتح", "مفتوح"), "open"),
        **_forms(("سلك",), ("سالك",), "open", objects=False)}.items():
    if _k not in _NOT_FORMS:
        FLOW_WORDS.setdefault(_k, _v)

# A vague word is weaker evidence than a named state.
# "جبع سلك" (it cleared) is news of a change: a caution follows it 29% of the
# time against 15% after "سالك", so it is held at a lower confidence.
_SOFT = {"زفت": 0.70, "سيء": 0.70, "سيي": 0.70, "سييه": 0.70, "سلك": 0.75, "سلكت": 0.75,
         "فاضي": 0.85, "فاضيه": 0.85, "فاضيين": 0.85, "فاضين": 0.85}
_EMPTY = frozenset(["فاضي", "فاضيه", "فاضيين", "فاضين"])

PRESENCE_WORDS: dict[str, str] = {
    "جيش": "idf", "عسكر": "idf", "مداهمه": "idf", "دبابات": "idf",
    "جنود": "idf", "عسكري": "idf", "جندي": "idf", "جنديين": "idf",
    "مجنده": "idf", "مجندات": "idf",
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
    # "ممنوع الدخول" / "منعوا الخروج" close ONE direction; the direction word
    # stays visible to _direction_positions, so the closure binds to it.
    ("ممنوع الدخول", "flow", "closed"), ("ممنوع الخروج", "flow", "closed"),
    ("منع الدخول", "flow", "closed"), ("منع الخروج", "flow", "closed"),
    ("منعوا الدخول", "flow", "closed"), ("منعوا الخروج", "flow", "closed"),
    ("منعو الدخول", "flow", "closed"), ("منعو الخروج", "flow", "closed"),
    # "فتحوا النار على الشباب عند الحاجز" is gunfire. Read word by word, فتحوا
    # is "opened" and the line served the checkpoint as OPEN (F019). Consuming
    # the phrase first leaves nothing for the flow lexicon to misread.
    ("فتح النار", "presence", "idf"), ("فتحوا النار", "presence", "idf"),
    ("فتحت النار", "presence", "idf"), ("فتحو النار", "presence", "idf"),
    ("وفتحوا النار", "presence", "idf"), ("اطلاق النار", "presence", "idf"),
    ("اطلاق نار", "presence", "idf"),
    # "جبع وقوف تام ولا حركة": a complete standstill. 88 stored lines.
    ("وقوف تام", "flow", "congested"), ("وقف تام", "flow", "congested"),
    ("توقف تام", "flow", "congested"),
    # "قوات الاحتلال تغلق حاجز جبع": the news register for the army.
    ("قوات الاحتلال", "presence", "idf"), ("قوات الجيش", "presence", "idf"),
    # A crossing's own bulletin: "يعمل المعبر اليوم باتجاه المغادرين", "يشهد
    # معبر الكرامة حركة سفر نشطة".
    ("يعمل المعبر", "flow", "open"), ("يعمل معبر", "flow", "open"),
    ("حركه سفر نشطه", "flow", "open"), ("حركه نشطه", "flow", "open"),
    # Barbed wire is not "it cleared": سلك is also the noun "wire". Consumed
    # here so the opening stem never sees it; the axis "none" records nothing.
    ("سلك شايك", "none", ""), ("اسلاك شايكه", "none", ""),
]

# "مفرق حارس برجع سيارات ضفة", "جسر الزاوية رجعوا الناس", "حاجز وارجاع
# المركبات": cars are being turned back, which is a closure for whoever is
# reading, said without one closure word.
PHRASES += [(f"{w}{v} {q}{o}", "flow", "closed")
            for w in ("", "و")
            for v in ("برجعو", "برجعوا", "برجع", "بيرجعو", "بيرجعوا", "رجعو", "رجعوا", "ارجاع")
            for q in ("", "كل ")
            for o in ("سيارات", "السيارات", "المركبات", "مركبات", "الناس")]

# Withdrawal / removal. These CLEAR presence rather than assert it, and usually
# imply the obstacle is gone. v1 has no concept of this, so "انسحب الجيش عن صرة"
# ("the army withdrew from Sarra") was stored as a place NAME.
CLEARING_WORDS = frozenset([
    "انسحب", "انسحبوا", "انسحبت", "شالو", "شالوا", "شال", "رفعوا", "رفع",
    "ازالوا", "فكوا", "راح", "راحت", "راحوا", "غادر", "غادروا", "تركوا",
    "خلص", "خلصت", "انتهي", "انتهت", "فتحوه", "فتحوها",
    "انفكت", "انفك", "فكت", "زالت",
    # "جبع فك الحاجز", "شالوه", "ازالو الحاجز": 179 stored lines said a
    # checkpoint was lifted in a form this set lacked.
    "فك", "فكو", "فكوه", "فكوها", "شالوه", "شالوها", "ازالو", "رفعو",
    "انشال", "انرفع",
])

# "لا" is deliberately ABSENT. In Palestinian Arabic an adjective is negated
# with "مش", not "لا"; before a status word "لا" is nearly always the discourse
# marker "no" answering someone — "لا مسكر" is "no, it's closed", which the
# negation rule inverted into "open".
# "دون": "المربعة فاتحة من دون حاجز".
NEGATORS = frozenset(["مش", "ما", "مو", "بدون", "دون", "بلا", "غير"])

# "There is no …" written as one word. "مافي جيش" and "مفيش ازمه" are the
# commonest ways to say the army is gone or the road is clear, and none of them
# was a negator, so each asserted the army PRESENT or the road CONGESTED (F023).
EXIST_NEG = frozenset(["مافي", "مافيش", "مافيه", "مفيش", "فش", "فيش", "ماكو"])

# What a negating ما / لا must stand before when it is not directly before the
# word it negates: "ما في جيش", "لا يوجد جيش".
_EXISTENTIAL = frozenset(["في", "فيه", "فيها", "عليه", "عليها", "يوجد", "يوجدش"])

# ما after these is RELATIVE or TEMPORAL — "بعد ما سكروا" (after they closed),
# "زي ما هو مسكر" (as it is: closed), "حسب ما سمعت مسكر" (as I heard: closed).
# Read as a negator it flipped every one of them to OPEN (F001, F005).
_REL_HEADS = frozenset(["بعد", "قبل", "زي", "زى", "مثل", "حسب", "كل", "اول",
                        "عقب", "طول", "عشان", "وقت", "بس"])
_PRONOUNS = frozenset(["هو", "هي", "هم", "هوه", "هيه"])

# Flow words that are NOUNS — the thing a clearing verb can clear ("انتهت الازمه")
# and the thing "لا … ولا …" / "ولا" can deny ("سالك ولا زحمه").
_FLOW_NOUNS = frozenset(["ازمه", "زحمه", "اختناق", "ازدحام", "كثافه", "تكدس",
                         "اغلاق", "ضغط"])

# Conditions: "اذا فتح حوارة بنمشي", "لو سكروا حوارة بنرجع" say nothing about
# now and were asserted as open/closed (F006).
_CONDITIONALS = frozenset(["اذا", "لو", "بحال"])

# "ممكن نزل الجيش": maybe. A guess is not a sighting — but what stood before
# it is still said: "جبع فاتحه بس في جيش، بجوز يسكرو باي وقت".
_HEDGES = frozenset(["ممكن", "يمكن", "احتمال", "بجوز", "يجوز"])

# Future particles. "راح يسكروا الحاجز" is "they are GOING TO close it", and
# راح is also a clearing verb ("راح الجيش" — the army left), so the forecast of
# a closure was served as an OPENING (F013, F024).
_FUTURE = frozenset(["راح", "رح", "بدهم", "بده", "بدو", "بدها"])

_TOMORROW = frozenset(["غد", "غدا", "بكره", "بكرا"])

# A clearing verb infers "open" only when it clears an obstacle. "الشباب تركوا
# المكان" (the young men left the place) is not a road report (F024).
_OBSTACLES = frozenset(["حاجز", "حواجز", "بوابه", "بوابات", "محسوم", "اغلاق",
                        "ازمه", "زحمه", "سواتر", "مكعبات"])

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
    # ع fused to the article: "عناب حاجز عالخارج".
    "عالخارج": "outbound", "عالداخل": "inbound", "عالطرفين": "both",
    "جهتين": "both",
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
                    "حدا متاكد",
                    # Not knowing is not reporting: "ما بعرف اذا حوارة سالك" was
                    # asserted as open at 0.90 (F006).
                    "ما بعرف", "مابعرف", "حد بعرف", "حد يعرف", "بعرف اذا",
                    "مش عارف", "مش عارفين",
                    )
# Opening hours are asked for, not reported: "عورتا اي ساعة بفتح", "تياسير وينتا
# بتسكر", "بيت ايل لاي ساعة فاتح" (stored as open 40 times). Matched on whole
# tokens: "بجوز يسكرو باي وقت" (they may close at any time) is a statement.
QUESTION_PHRASES_EXACT = ("اي ساعه", "لاي ساعه", "اني ساعه", "اي وقت", "لاي وقت",
                          "وينتا", "ايمتا", "ايمتي")

_WHICH = frozenset(["طريق", "شارع", "مدخل", "بوابه", "معبر", "مخرج", "حاجز"])

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


def _bare(tok: str) -> str:
    """The token without a fused article, for membership tests on noun sets."""
    s = _ARTICLE.sub("", tok)
    return s if len(s) >= 2 else tok


def _in(tok: str, words: frozenset) -> bool:
    """`tok` is one of `words`, allowing a fused article or a fused و."""
    return (_bare(tok) in words
            or (len(tok) >= 3 and tok[0] == "و" and _bare(tok[1:]) in words))


def _neg_form(tok: str) -> str | None:
    """The negator a token is, peeling one fused و/ف: "ومش" -> "مش", "وما" -> "ما".

    `_lex` peels the conjunction for lexicon words but the negation check
    compared the raw token, so "حوارة ومش سالك" served OPEN and "سالك وما في جيش"
    served army PRESENT (F002).
    """
    if tok in NEGATORS or tok in EXIST_NEG or tok in ("لا", "ولا"):
        return tok
    if len(tok) >= 3 and tok[0] in "وف" and (tok[1:] in NEGATORS or tok[1:] in EXIST_NEG):
        return tok[1:]
    return None


def _is_clearing(tok: str) -> bool:
    return tok in CLEARING_WORDS or (tok[:1] == "و" and tok[1:] in CLEARING_WORDS)


def _future_verb(tok: str) -> bool:
    """An imperfect verb whose stem is road or presence vocabulary: يسكروا, بيفتحوا."""
    if len(tok) < 3 or tok[0] not in "يتنب":
        return False
    if _lex(tok, FLOW_WORDS):
        return True                 # "راح يمشي": يمشي is itself in the table
    stems = [tok[1:], "ا" + tok[1:]]
    if tok[:2] in ("بي", "بت", "بن") and len(tok) >= 4:
        stems += [tok[2:], "ا" + tok[2:]]
    return any(_lex(st, FLOW_WORDS) or _lex(st, PRESENCE_WORDS) or st in CLEARING_WORDS
               for st in stems)


def _not_a_report(toks: list[str]) -> tuple[str, int] | None:
    """Why a clause states no current fact, and from which token: a condition
    (the whole clause) or a forecast (from its particle on). None if it does.

    The forecast used to void the whole clause, which was harmless while few
    verbs were known. With the closing forms generated, "عورتا سالكه بالاتجاهين
    الان 11 راح يسكرو البوابات" lost its first half — open NOW — to its second.
    """
    if any(t in _CONDITIONALS for t in toks) or " ".join(toks[:2]) == "في حال":
        return ("conditional", 0)
    # "الجسر يوم غد السبت مغلق": about tomorrow, whichever word comes first.
    if any(_bare(t) in _TOMORROW for t in toks):
        return ("forecast", 0)
    # "مواعيد الحواجز التالية", "تعديل على ساعات عمل المعابر": a timetable.
    if any(t in ("مواعيد", "مواعيده") or (t == "ساعات" and k + 1 < len(toks)
                                          and _bare(toks[k + 1]) in ("عمل", "دوام"))
           for k, t in enumerate(toks)):
        return ("schedule", 0)
    # "مفتوح من الساعة 8:00 صباحا وحتى 6:00 مساء": opening hours.
    for k, t in enumerate(toks[:-1]):
        if t == "من" and _bare(toks[k + 1]) == "ساعه" and any(
                x in ("حتي", "وحتي", "الي", "لغايه", "ل") for x in toks[k + 2:]):
            return ("schedule", 0)
    for k, t in enumerate(toks):
        if t in _HEDGES:
            return ("guess", k)
    for k, t in enumerate(toks[:-1]):
        if t in _FUTURE and _future_verb(toks[k + 1]):
            # "ما رح يفتح": the negator belongs to the forecast.
            return ("forecast", k - 1 if k and _neg_form(toks[k - 1]) else k)
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
    tag: str | None = None        # "checkpoint_up": a checkpoint is operating here


# ── the checkpoint noun as a report ──────────────────────────────────────────
# "حاجز" is the ordinary word for a checkpoint and v1 read every use of it as
# soldiers present — its largest false positive, removed here in August. But
# the removal went too far. In these channels "جبع حاجز", "عطاره حاجز للخارج
# الان", "عين سينيا محسوم للداخل" are how people say a checkpoint has gone up
# and is stopping cars: 2,540 stored lines on 2026-10-11, a quarter of every
# such report, and v2 kept none of them. Measured on the next report at the same
# place within 45 minutes: a caution follows "X حاجز" 70% of the time, against
# 56% after an army sighting this parser accepts and 35% after any line.
#
# What separates the report from the name is where the noun stands. BEFORE the
# place it is part of the name ("حاجز عناب سالك"); AFTER it, or before it with
# a locative between ("حاجز على مدخل اماتين"), it is the news. The definite
# "الحاجز" refers to a checkpoint already known and is never the news — except
# that it is what gets lifted ("جبع فك الحاجز").
CHECKPOINT_NOUNS = frozenset(["حاجز", "حواجز", "محسوم", "محاسيم", "مخصوم"])

# A caller that knows where the place names are (ingest/sources/roads.py does)
# replaces each with this token before calling read(): the name can then
# neither be read as a status nor be mistaken for the words around it.
NAME = "zzplacezz"

_NOW = frozenset(["الان", "هسا", "هسه", "هلا", "هلق", "هلقيت", "حاليا", "هسع", "توا"])
_AT = frozenset(["علي", "ع", "عل", "عند", "تحت", "قبل", "بعد", "قرب", "جنب", "فوق",
                 "مقابل"])
# What stands directly before a noun that is being REFERRED to, not reported:
# "ع حاجز جبع ازمه", "اي حاجز فيه", "من حاجز عطاره".
_REFERS = frozenset(["علي", "ع", "عل", "عند", "بعد", "قبل", "من", "الي", "ل", "لعند",
                     "باتجاه", "نحو", "حتي", "عن", "مع", "اي", "كل", "جميع", "اخر", "اول",
                     "نفس", "كم", "ثاني", "تاني", "غير"])


def _noun_kind(tok: str) -> str | None:
    """"indef" for حاجز / محسوم, "def" for الحاجز, None for anything else."""
    t = _ELONGATED.sub(r"\1", tok)
    if t in CHECKPOINT_NOUNS or (len(t) > 3 and t[0] == "و" and t[1:] in CHECKPOINT_NOUNS):
        return "indef"
    s = _ARTICLE.sub("", t)
    return "def" if s != t and s in CHECKPOINT_NOUNS else None


def _is_inspection(tok: str) -> bool:
    """تفتيش / وتفتيش / تدقيق: a search, with or without its waw."""
    return (_lex(tok, PRESENCE_WORDS) == "inspection"
            or (len(tok) > 3 and tok[0] == "و" and _lex(tok[1:], PRESENCE_WORDS) == "inspection"))


def _noun_role(toks: list[str], i: int, kind: str, found: list,
               subject_before: bool = False) -> tuple[str, float] | None:
    """What the checkpoint noun at toks[i] reports: ("up", confidence),
    ("absent", confidence), or None where it only names or refers.
    `subject_before`: an earlier clause of the same line named the place."""
    prev = toks[i - 1] if i else ""
    nxt = toks[i + 1] if i + 1 < len(toks) else ""
    # "لا حاجز للخارج" answers a question — "no; a checkpoint, outbound" as
    # easily as "no checkpoint". Only the list form "لا حاجز ولا اشي" is read.
    if prev == "لا":
        return ("absent", 0.86) if "ولا" in toks[i + 1:] else None
    if prev == "ولا":
        return ("absent", 0.86) if any(x in ("لا", "ولا") for x in toks[:i - 1]) else None
    fwd = toks[i + 1:i + 3]
    if _negated(toks, i) or (
            len(fwd) == 2 and _neg_form(fwd[0]) in ("مش", "ما", "مو")
            and fwd[1] in ("موجود", "موجوده", "موجودين", "في", "فيه")):
        return ("absent", 0.86)
    if (any(_is_clearing(toks[j]) for j in range(max(0, i - 2), i))
            or (nxt and _is_clearing(nxt))):
        return ("absent", 0.80)
    if kind != "indef" or prev in _REFERS:
        return None
    # "حاجز شرطه" is the police's and "مستوطن عامل حاجز" the settlers': each is
    # already recorded under its own name, and neither is the army.
    if _lex(nxt, PRESENCE_WORDS) == "police" or any(
            f[0] == "presence" and f[1] == "settlers" for f in found):
        return None
    if NAME in toks:
        before = NAME in toks[:i]
        if nxt == NAME:
            # "حاجز §" is the name with its prefix — unless that is the whole
            # message and it says when: "حاجز جبع الان".
            if before or found or not any(t in _NOW for t in toks):
                return None
            return ("up", 0.70)
        if before:
            return ("up", 0.80)
        if NAME not in toks[i + 1:]:
            return None
        between = toks[i + 1:toks.index(NAME, i + 1)]
        if between and between[0] in _AT and len(between) <= 3:
            return ("up", 0.78)
        return None
    # The name is not marked: a line v1 matched, read as it was stored.
    # "3.حاجز عناب عنبتا" in a timetable: a number is not what the noun follows.
    if not [t for t in toks[:i] if not t.isdigit() and t not in _NOW
            and not _lex(t, DIRECTION_WORDS)]:
        i = 0
        nxt = toks[1] if len(toks) > 1 else ""
    if i == 0:
        if nxt in _AT and len(toks) >= 3:
            return ("up", 0.78)
        # "🚧 فرش الهوى - حاجز": the place is the clause before this one.
        # "ترمسعيا - حاجز وتفتيش", "… والخارج حاجز وتفتيش": the checkpoint is
        # up and it searches; the inspection does not make the noun a name.
        alone = not [t for t in toks if not _noun_kind(t) and not t.isdigit()
                     and t not in _NOW and not _lex(t, DIRECTION_WORDS)
                     and not _is_inspection(t)]
        return ("up", 0.80) if subject_before and alone else None
    rest = [t for t in toks[i + 1:] if t not in _NOW and not _lex(t, DIRECTION_WORDS)
            and not _is_inspection(t)]
    if rest and any(f[0] == "flow" for f in found):
        return None                 # "شباب حاجز عطارة سالك": a name follows
    return ("up", 0.80)


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
    if any(f" {p} " in f" {joined} " for p in QUESTION_PHRASES_EXACT):
        return True
    if any(t in QUESTION_OPENERS for t in toks[:2]):
        return True
    # Disjunctive question: "بوابة بورين فاتحه ولا مسكره" — "…open OR closed?".
    # Two opposing flow words joined by "ولا" is a request for the status, not
    # a report of it, and often carries no question mark.
    #
    # But "ولا" before a NOUN is "and no …": "حوارة سالك ولا زحمه" is "flowing,
    # no jam" — a reassurance that was being discarded as a question — while
    # "حوارة سالك ولا لا" ("…or not?") asks and was asserted as open (F022).
    # "اي حاجز فك", "اي حاجز", "شباب اي طريق سالكة لحوارة": WHICH checkpoint,
    # which road — asked, not told.
    if any(t == "اي" and (_noun_kind(toks[k + 1]) or _bare(toks[k + 1]) in _WHICH)
           for k, t in enumerate(toks[:3]) if k + 1 < len(toks)):
        return True
    # "دورا فتحت ولا لسا": …or not yet?
    if toks and toks[-1] in ("ولالسا", "ولالسه") or (
            len(toks) >= 2 and toks[-2] in ("ولا", "والا") and toks[-1] in ("لسا", "لسه", "بعد")):
        return True
    # "عين سينيا سالكه ولا حاجز فهمونا", "مسكر ولا حاجز": clear, or a
    # checkpoint? Read as "and no checkpoint" it would be a reassurance made out
    # of somebody's doubt. The list form "لا جيش ولا حاجز" stays a statement.
    if any(t in ("ولا", "والا") and k + 1 < len(toks) and _noun_kind(toks[k + 1])
           and not any(x in ("لا", "ولا") for x in toks[:k])
           and any(_lex(x, FLOW_WORDS) or _lex(x, PRESENCE_WORDS) for x in toks[:k])
           for k, t in enumerate(toks)):
        return True
    # "والا" is the same "or", typed with its alef: "لسا فاتحين والا سكرو".
    if "والا" in toks:
        toks = ["ولا" if t == "والا" else t for t in toks]
    if "ولا" in toks:
        after = {k + 1 for k, t in enumerate(toks) if t == "ولا"}
        if any(k >= len(toks) or toks[k] in ("لا", "لاء") for k in after):
            return True
        vals = {v for idx, v in ((i, _lex(t, FLOW_WORDS)) for i, t in enumerate(toks))
                if v and not (idx in after and _in(toks[idx], _FLOW_NOUNS))}
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


def _assign_directions(found: list[tuple], dirs: list[tuple[int, str]],
                       toks: list[str] | None = None) -> list[tuple[str, bool]]:
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
    dirs = _collapse_enumerated_both(dirs, [f[3] for f in found if f[3] >= 0])
    n = len(found)
    if not dirs:
        return [("both", False)] * n
    if len({d for _, d in dirs}) == 1:
        return [(dirs[0][1], True)] * n

    result: list[tuple[str, bool] | None] = [None] * n
    claimed: set[int] = set()
    ties: list[tuple[int, list[int]]] = []          # (fact idx, tied dir idxs)

    for fi, f in enumerate(found):
        pos = f[3]
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
            # Still ambiguous: the postfix preference as the last resort —
            # among the tied, the direction that follows the status. Except
            # where both neighbours are the bare noun ("الداخل سالك الخارج بس
            # نمر صفر"): "الداخل" names a lane and what follows is said of it,
            # while "للداخل" points back at what came before.
            pos = found[fi][3]
            pick = min(tied, key=lambda di: 0 if dirs[di][0] > pos else 1)
            if toks and all(not toks[dirs[di][0]].startswith(("لل", "ل", "ع", "ب"))
                            for di in tied):
                pick = min(tied, key=lambda di: 0 if dirs[di][0] < pos else 1)
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

    Audit 2026-09-25 (F001, F002, F005, F014, F022, F023): a negator fused to و
    is still a negator; ما after بعد/زي/حسب… is relative, not negating, and a
    negating ما stands directly before its word or before في/يوجد; لا negates
    only before an existential, directly before a presence noun, as "ولا" before
    a flow noun, or as the first "لا" of a "لا X ولا Y" list.
    """
    for j in range(max(0, i - 2), i):
        neg = _neg_form(toks[j])
        if neg is None:
            continue
        nxt = toks[j + 1] if j + 1 < len(toks) else ""
        # "ما زال مغلق" — the particle is continuative, not negating.
        if nxt in CONTINUATIVES:
            continue
        if neg in ("لا", "ولا"):
            # "لا مسكر" is "no, it's closed": لا before a status adjective stays
            # the discourse marker.
            if not (nxt in _EXISTENTIAL
                    or (j == i - 1 and _lex(toks[i], PRESENCE_WORDS))
                    or (j == i - 1 and neg == "ولا" and _in(toks[i], _FLOW_NOUNS))
                    or (j == i - 1 and neg == "لا" and _in(toks[i], _FLOW_NOUNS)
                        and "ولا" in toks[i + 1:])):
                continue
        elif neg == "ما":
            if j > 0 and _in(toks[j - 1], _REL_HEADS):
                continue
            if nxt in _PRONOUNS:
                continue
            if not (j == i - 1 or nxt in _EXISTENTIAL):
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
    return any(_is_clearing(toks[j]) for j in range(lo, hi) if j != i)


def _scan_clause(clause: str, raw_clause: str,
                 subject_before: bool = False) -> tuple[list[tuple], bool]:
    """Return [(axis, value, confidence, token_pos[, tag])] found in a clause,
    and whether a clearing verb fired. `token_pos` is -1 where the finding has
    no single anchor token (emoji, clause-level inference)."""
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
        if axis == "none":
            continue
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
            # "انتهت الازمه", "رفعوا الاغلاق": the clearing verb BEFORE the jam
            # or closure noun reports it gone. Read as the noun alone it served
            # CONGESTED/CLOSED at 0.9 and restarted the closure's clock (F015,
            # F021). A clearing verb AFTER the noun ("ازمه وراح الجيش") clears
            # whoever follows it, not the jam.
            if (flow != "open" and _in(t, _FLOW_NOUNS)
                    and any(_is_clearing(toks[j]) for j in range(max(0, i - 2), i))):
                out.append(("flow", "open", 0.72, i))
                continue
            if _negated(toks, i):
                # "مش فاضي" is busy, not shut.
                out.append(("flow", "congested" if _bare(t) in _EMPTY
                            else _FLIP.get(flow, flow), 0.80, i))
            else:
                out.append(("flow", flow, _SOFT.get(t) or _SOFT.get(_bare(t), 0.90), i))
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
            fwd = toks[i + 1:i + 3]
            if _negated(toks, i) or (
                    len(fwd) == 2 and _neg_form(fwd[0]) in ("مش", "ما", "مو")
                    and fwd[1] in ("موجود", "موجوده", "موجودين", "في", "فيه")):
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

    # The checkpoint noun, where it is the news and not the name (see
    # CHECKPOINT_NOUNS). Judged after the lexicon pass, because "حاجز § الان"
    # is a report only when the clause says nothing else.
    for i, t in enumerate(toks):
        kind = None if i in consumed else _noun_kind(t)
        if not kind:
            continue
        role = _noun_role(toks, i, kind, out, subject_before)
        if role and role[0] == "up":
            out.append(("presence", "idf", role[1], i, "checkpoint_up"))
        elif role:
            out.append(("absence", "idf", role[1], i))

    # Emoji only where the words said nothing — and never on a FUEL line.
    # "الجلمة :سولار❌بنزين❌" is a fuel-availability report at the Jalama
    # crossing: none of its words is checkpoint vocabulary, so the ❌ fell
    # through to here and served the CROSSING as closed. The ❌ is about
    # diesel. A clause naming a fuel product keeps its words and loses only
    # the emoji inference.
    if not out and not any(_bare(t) in _FUEL_NOUNS for t in toks):
        # Several different emoji and no direction to bind them to: the most
        # restrictive wins. It used to be whichever came first in this dict,
        # so "✅❌" served OPEN (F003). Per-direction lines are split upstream.
        seen = [v for ch, v in EMOJI_FLOW.items() if ch in raw_clause]
        if seen:
            out.append(("flow", max(seen, key=lambda v: FLOW_SEVERITY[v]), 0.65, -1))

    # A clearing verb with no other flow signal means the obstacle is gone —
    # unless somebody ELSE is asserted present in the same line. "راح الجيش
    # اجو المستوطين بكسرو بالسيارات" clears the army and reports settlers
    # smashing cars; inferring `open` from the departure would be a
    # reassurance manufactured over an active attack. Same asymmetry as P2.4:
    # a caution stands on its own, a reassurance must not be inferred past one.
    near_obstacle = any(
        _is_clearing(toks[j]) and any(
            k != j and (_in(toks[k], _OBSTACLES) or _lex(toks[k], PRESENCE_WORDS))
            for k in range(max(0, j - 2), min(len(toks), j + 3)))
        for j in range(len(toks)))
    if (cleared and near_obstacle and not any(f[0] == "flow" for f in out)
            and not any(f[0] == "presence" for f in out)):
        out.append(("flow", "open", 0.72, -1))
    return out, cleared


def _split_emoji_directions(raw_clause: str) -> list[str]:
    """Split "الداخل ✅ الخارج ❌" into one segment per direction.

    `tokens()` drops emoji, so the two direction words end up adjacent and the
    enumerated-both rule merged them; the emoji fell back to a clause-wide
    reading and dict order picked ✅ — OPEN both ways over a closed exit (F003).
    Only lines whose words carry no status of their own are split, and only
    when they hold two different emoji and two direction words.
    """
    if len({v for ch, v in EMOJI_FLOW.items() if ch in raw_clause}) < 2:
        return [raw_clause]
    ws = raw_clause.split()
    parts = [tokens(normalize(w)) for w in ws]
    if any(_lex(p, FLOW_WORDS) or _lex(p, PRESENCE_WORDS) for ps in parts for p in ps):
        return [raw_clause]
    dir_idx = [k for k, ps in enumerate(parts) if any(_lex(p, DIRECTION_WORDS) for p in ps)]
    emo_idx = [k for k, w in enumerate(ws) if any(ch in w for ch in EMOJI_FLOW)]
    if len(dir_idx) < 2 or not emo_idx:
        return [raw_clause]
    if emo_idx[0] < dir_idx[0]:                 # "✅ الداخل ❌ الخارج"
        cuts = [d + 1 for d in dir_idx[:-1]]
    else:                                       # "الداخل ✅ الخارج ❌"
        cuts = dir_idx[1:]
    bounds = [0] + cuts + [len(ws)]
    return [" ".join(ws[a:b]) for a, b in zip(bounds, bounds[1:]) if a < b]


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
    subject = False
    last_dir: str | None = None        # the one direction the clause before named
    skipped: list[str] = []
    clauses = [seg for rc in _CLAUSE_SPLIT.split(_presplit_waw(raw)) if rc and rc.strip()
               for seg in _split_emoji_directions(rc)]
    has_dir = [bool(_direction_positions(tokens(normalize(c)))) for c in clauses]
    for n_clause, raw_clause in enumerate(clauses):
        clause = normalize(raw_clause)
        if not clause:
            continue
        ctoks = tokens(clause)
        why = _not_a_report(ctoks)
        if why:
            skipped.append(why[0])
            if why[1] == 0:
                continue
            clause = " ".join(ctoks[:why[1]])
        ctoks = tokens(clause)
        dirs = _direction_positions(ctoks)
        found, cleared = _scan_clause(clause, raw_clause, subject_before=subject)
        # A clause that names something and reports nothing is the subject of
        # the next one: "🚧 فرش الهوى - حاجز", "عورتا ⏎ حاجز".
        # Once the line has named its place, later clauses that name nothing
        # are still about it: "عين سينيا - الداخل سالك والخارج حاجز وتفتيش".
        subject = (subject or NAME in ctoks) if NAME in norm_all else (
            subject or (bool(ctoks) and not found))
        any_clear = any_clear or cleared
        bound = _assign_directions(found, dirs, ctoks)
        # "للخارج ازمة و تفتيش": the waw typed apart makes the search a clause
        # of its own with no direction, and it was read as both ways beside an
        # outbound jam. A clause that is presence words and nothing else takes
        # the direction of the clause it continues — when nothing after it
        # names a direction: in "سالك للداخل حاجز وتفتيش وازمة للخارج" the
        # search may as well belong to what follows, and stays unbound.
        if (not dirs and last_dir and found and NAME not in ctoks
                and not any(has_dir[n_clause + 1:])
                and all(_lex(t, PRESENCE_WORDS) or t in _NOW or
                        (len(t) > 3 and t[0] == "و" and _lex(t[1:], PRESENCE_WORDS))
                        for t in ctoks)):
            bound = [(last_dir, True)] * len(found)
        elif dirs:
            named = {d for _, d in dirs}
            last_dir = named.pop() if len(named) == 1 else None
        else:
            last_dir = None
        for f, (direction, explicit) in zip(found, bound):
            facts.append(Fact(direction=direction, axis=f[0], value=f[1],
                              direction_explicit=explicit, confidence=f[2],
                              clause=raw_clause.strip()[:160],
                              tag=f[4] if len(f) > 4 else None))

    if not facts:
        return Reading(modality="unparsed", cleared=any_clear,
                       note=(f"{skipped[0]} — not a report of now" if skipped
                             else "no status vocabulary found"))

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
