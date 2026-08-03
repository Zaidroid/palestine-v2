"""Regression cases for the news incident reader.

Every case is a real message from the agent2 feed that was classified WRONG at
some point. The recurring theme is that Arabic nouns and participles NAME
people and things far more often than they report events, and that verbs carry
tense on a prefix — so matching the dictionary form finds almost nothing.

    ./.venv/bin/python -m pytest tests/test_news.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade.news import read  # noqa: E402


def kind(text: str) -> str:
    r = read(text)
    return r.incident_type if r.verdict == "incident" else r.verdict


# ── verbs carry tense on a PREFIX ────────────────────────────────────────────
# "تقتحم" and "اقتحم" share no leading letters, and the imperfective is the
# commonest headline form. Matching only the perfective missed most raids.
@pytest.mark.parametrize("text,expect", [
    ("قوات الاحتلال تقتحم بلدة بيت امر شمال الخليل", "raid"),
    ("قوات الاحتلال اقتحمت بلدة يعبد جنوب جنين", "raid"),
    ("قوات الاحتلال تداهم عددًا من المنازل خلال اقتحامها لبلدة علار شمال طولكرم", "raid"),
    ("قوات الاحتلال تعتقل شابين من بلدة بيتا جنوب نابلس", "arrest"),
    ("الاحتلال يغلق مدخل بلدة سنجل شمال رام الله", "closure"),
])
def test_verb_prefixes(text, expect):
    assert kind(text) == expect


# ── a noun that names someone is not a report ────────────────────────────────
def test_martyr_noun_is_not_a_death_report():
    """"الشهيد" is overwhelmingly referential here — the grave OF martyr X, the
    father OF the martyrs. Treating the noun as a death filed a settler attack
    on a cemetery as a killing."""
    assert kind("مستوطنون يعتدون على قبر الشهيد محمد الجنيدي خلال اقتحام قرية الجنيد غرب نابلس") \
        == "settler_attack"
    assert kind("رسائل والد الشهيدين محمد ورامي أبو بكر") != "death"
    # A killing VERB still reports a death.
    assert kind("استشهد الشاب محمد خلال اقتحام قوات الاحتلال لبلدة يعبد جنوب جنين") == "death"


def test_detainee_noun_is_not_an_arrest():
    """Same shape: "المعتقل" names a person, it does not report an arrest."""
    assert kind("نادي الأسير: الطفل المعتقل محمد موسى حميد") != "arrest"


# ── geography is a hard filter ───────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "الشهيد الطفل زيد نوفل قتله الاحتلال فجر اليوم بغارة استهدفت منزلاً في مخيم البريج وسط قطاع غزة",
    "طواقم الهلال الأحمر تتجه نحو معبر رفح بعد وصول نداءات حول جرحى",
])
def test_gaza_is_rejected(text):
    """Real news, wrong geography. Counting it would attribute Gaza incidents to
    West Bank governorates."""
    assert read(text).verdict == "rejected"
    assert read(text).reject_reason == "gaza"


@pytest.mark.parametrize("text", [
    "رسميا الاردن تعلن الاحتفاظ بحق الرد على ايران والعراق",
    "القناة 13 العبرية: تشديد مواقف مجتبى خامنئي يثير قلقًا في إسرائيل",
])
def test_international_is_rejected(text):
    assert read(text).verdict == "rejected"


def test_commentary_is_rejected():
    assert read("هل بات الانتظار قدر الفلسطيني في الضفة؟؟ وقود وحواجز وأزمات متتالية").verdict \
        == "rejected"
    assert read("تمرّ علينا اليوم الذكرى الثانية لرحيل قائد الأمة").verdict == "rejected"


# ── place extraction ─────────────────────────────────────────────────────────
def test_place_survives_a_fused_preposition():
    """Arabic writes the preposition onto the noun — "لبلدة إذنا", "بمدينة بيت
    لحم". Matching only the bare form missed most of the corpus, because the
    place word almost always follows a verb of motion."""
    assert read("قوات الاحتلال تداهم منزلا خلال اقتحامها لبلدة إذنا").place_text == "اذنا"
    assert read("اقتحام قوات الاحتلال لمدينة سلفيت").place_text == "سلفيت"


def test_multiword_place_is_not_truncated():
    assert read("تواصل قوات الاحتلال اقتحامها لبلدة بيت أمر شمال الخليل").place_text == "بيت امر"


def test_bearing_does_not_leak_into_the_name():
    """"قرية المغير، شمال رام الله" must give المغير — normalize() has already
    turned the comma into a space, so punctuation cannot terminate the name."""
    r = read("إطلاق الرصاص الحي صوب الشبان خلال اقتحام قرية المغير، شمال رام الله")
    assert r.place_text == "المغير"
    assert r.governorate == "رام الله"


def test_waw_ends_the_name():
    """"قرية جنيد والقرى المحيطة" is one village, not three words of one."""
    assert read("قوات الاحتلال تقتحم قرية جنيد والقرى المحيطة بمدينة نابلس").place_text == "جنيد"


def test_neighbourhood_word_does_not_match_inside_another_word():
    """"حي" matched inside "الرصاص الحي" ("LIVE ammunition") and captured the
    next token as a place. Two-letter place words cannot be distinguished from
    substrings, so the word is not used at all."""
    r = read("٣ اصابات بالرصاص الحي في بيت امر قرب الخليل")
    assert r.place_text != "في"


def test_rejecting_is_the_default():
    """Anything without a concrete action AND a place stays unclassified. The
    claim is retained either way, so a miss costs nothing and a false positive
    is announced to a family planning a journey."""
    assert read("عشرات آلاف المصلين يؤدون صلاة الجمعة في باحات المسجد الأقصى").verdict != "incident"
    assert read("").verdict == "rejected"
    assert read(None).verdict == "rejected"


# ── P1.1 findings: every case below is a real message the classifier got wrong,
# found by hand-scoring a stratified sample of 163 classifications. The measured
# result was 0.732 overall with demolition at 0.353 and closure at 0.500, both
# under the 0.60 floor. ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    # Settlers storming a village was filed as an ARMY raid, because the
    # settler pattern spelled the stem "اقتحم" — the same tense-prefix bug this
    # file already tests for `raid`. "يقتحمون" contains "قتح", not "اقتحم".
    "مستوطنون رفقة أغنامهم يقتحمون أراضي المواطنين في خربة قواويس بمسافر يطا جنوب الخليل",
    # The actor came AFTER the verb, so the settler gate never fired.
    "جانب من اقتحام المستوطنين بحماية قوات الاحتلال منذ ساعات الصباح بلدة تل في نابلس",
    "مستوطنون يشعلون حريقًا في أراضي المواطنين شرق قرية أبو فلاح، شرق رام الله بالتزامن مع اقتحامهم المنطقة",
    # Seizure verbs were absent entirely.
    "مجموعات من المستوطنين تقوم بالاستيلاء على عين القصعة في أراضي مدينة البيرة",
])
def test_settler_actions_are_not_army_raids(text):
    """Recording a settler attack as an army raid gets the ACTOR wrong, which
    is the single fact a reader most needs from this feed."""
    assert kind(text) == "settler_attack"


@pytest.mark.parametrize("text", [
    # Nominal casualty reports have no verb at all. The referential-noun guard
    # correctly rejects "the grave of the martyr" and wrongly rejected these.
    "وزارة الصحة: شهيد ومصابان أحدهما بجروح حرجة برصاص الاحتلال في تل جنوب غرب نابلس",
    "الهلال الاحمر : شهيد و١٣ اصابة منهم ٣ اصابات خطيرة خلال اقتحام قوات الاحتلال لمخيم بلاطة في نابلس",
    "وزارة الصحة: ارتفاع حصيلة الشهداء في تل جنوب غرب نابلس إلى ٤ شهداء و٤ إصابات، ٣ منها حرجة",
])
def test_casualty_reports_are_deaths(text):
    """A death filed as a raid or an injury loses the most important fact in
    the message. A bare "شهيد" is still not enough — the count-and-casualty
    frame is what distinguishes a report from a reference to a person."""
    assert kind(text) == "death"


def test_the_grave_of_a_martyr_is_still_not_a_death():
    """The guard that made the above necessary must not be undone by it."""
    assert kind("مستوطنون يعتدون على قبر الشهيد محمد الجنيدي خلال اقتحام قرية الجنيد غرب نابلس") \
        == "settler_attack"


@pytest.mark.parametrize("text,reason", [
    # Three of twenty sampled `closure` incidents were road-status bulletins —
    # one of them reporting that the roads were OPEN. That is checkpoint data,
    # already carried by its own pipeline.
    ("احوال طرق اريحا ومحيطها ✅كافة حواجز أريحا سالكه ✅المعرجات كرملوا سالكين", "status bulletin"),
    ("⚪أحوال حواجز مدينة رام الله.. 🚧 عطارة: حاجز بالاتجاهين. ✅ عين سينيا: سالك. ❌ سنجل: مغلق", "status bulletin"),
    # A notice is not an act; the demolition may never follow.
    ("ماذا قال أصحاب منازل ومنشآت بعد تسليمهم إخطارات هدم في بلدة نحالين غرب بيت لحم؟", "notice not act"),
    # Four of seventeen sampled demolitions were one story about a woman freed
    # after 8 days, filed as a fresh demolition because it mentions هدم.
    ("الإفراج عن السيدة حنين فنون بعد 8 أيام من اعتقالها أثناء هدم منزل عائلتها في بلدة نحالين", "aftermath"),
    # A six-month statistic is not an event.
    ("تصدرت محافظتا القدس وقلقيلية عدد المنشآت التي هدمها الاحتلال خلال النصف الأول من عام 2026", "statistical"),
])
def test_non_events_are_rejected(text, reason):
    r = read(text)
    assert r.verdict != "incident", f"{reason}: served as {r.incident_type}"
    assert r.reject_reason == reason


def test_a_west_bank_university_is_not_foreign_news():
    """"الجامعة الأمريكية" is in Jenin. Matching "امريك" inside it rejected a
    real raid on student housing sheltering displaced people as world news."""
    assert kind("قوات الاحتلال تقتحم منطقة سكنات الجامعة الأمريكية التي تؤوي نازحين من مخيم جنين") \
        == "raid"


def test_gas_fired_at_people_is_an_incident():
    """Rejected as "no incident verb" while describing tear gas and stun
    grenades fired at a wedding."""
    assert kind("عاجل | قوات الاحتلال تطلق قنابل الغاز والصوت تجاه حفل زفاف في بلدة بيت أمر، شمال الخليل") \
        == "shooting"


def test_casualty_outranks_the_action_that_caused_it():
    """`raid` sat above `injury`, so a Red Crescent casualty report became a
    raid and the wounded man disappeared from the record."""
    assert kind("عاجل| الهلال الأحمر: إصابة شاب برصاص جيش الاحتلال في البطن خلال اقتحام بلدة بيت أمر شمال الخليل") \
        == "injury"


def test_threatening_to_demolish_is_not_demolishing():
    """A conditional threat filed a report of a detainee being tortured in
    Jericho prison as a demolition."""
    r = read("أجهزة أمن السلطة تعرض الأسير أمين القوقا للتعذيب في سجن أريحا، "
             "وقام الاحتلال بتهديده بنية هدم منزله إذا لم يسلم نفسه واعتقل أفراد عائلته")
    assert r.incident_type != "demolition"


def test_rural_locality_prefixes_resolve():
    """خربة / خلة are where settler incidents concentrate. Without them the
    event was read correctly and then dropped for having no place."""
    assert read("مستوطنون يسيطرون على المزيد من آبار المياه والأراضي في خلة الحمص جنوب يطا"
                ).place_text is not None


@pytest.mark.parametrize("text,expect", [
    # "رأي" (opinion) normalises to "راي", which is a SUBSTRING of "اسراييلي"
    # — إسرائيلي, "Israeli". 142 claims were rejected as commentary for
    # containing the word "Israeli".
    ("قوات الاحتلال الإسرائيلي تقتحم بلدة بيت أمر شمال الخليل", "raid"),
    # ...and of "حرايق" (fires), which filed a settler arson report as opinion.
    ("اندلاع حرائق في قرية كفر مالك، شمال شرق رام الله؛ إثر إطلاق قوات الاحتلال قنابل الغاز",
     "shooting"),
])
def test_short_reject_terms_do_not_match_inside_longer_words(text, expect):
    """The `حومش سالك` / `مش سالك` family, at corpus scale. In Arabic a short
    string is almost always inside a longer real word."""
    assert kind(text) == expect


def test_deportation_is_not_a_memorial():
    """"رحيل" (passing) sits inside "ترحيل" — DEPORTATION. It is still not
    CLASSIFIED, because the taxonomy has no type for it, but it must not be
    thrown away as a memorial post: `unclear` keeps the claim reachable for a
    later rule, `rejected/commentary` buries it."""
    r = read("الاحتلال يقرر ترحيل عائلة فلسطينية من منزلها في بلدة سلوان بالقدس")
    assert r.reject_reason != "commentary"


def test_genuine_commentary_is_still_rejected():
    """The boundary fix must not disarm the rule it protects."""
    r = read("بقلم الكاتب: رأي في الوضع الفلسطيني الراهن وتحليل المشهد السياسي")
    assert r.verdict == "rejected" and r.reject_reason == "commentary"


def test_the_verbal_noun_of_martyrdom_is_a_death():
    """استشهاد is ا-س-ت-ش-ه-ا-د and does not contain the perfective stem
    استشهد — the same trap as اقتحام/اقتحم. It filed a man who died of his
    wounds as an INJURY, which is the worst direction for the error to run."""
    assert kind("استشهاد الشاب محمود زياد العملة (٣٢ عاماً) متأثراً بجروح حرجة "
                "أصيب بها برصاص الاحتلال قرب بلدة بيت أولا شمال الخليل") == "death"


# ── closure needs a verb AND something that can be closed ────────────────────
# P1.1 round 3 measured `closure` at 0.167 — one right in six. The corrections
# came in three waves, each a different way for a CORRECT verb to describe the
# wrong thing, and the third is why the rule changed shape instead of growing
# another wordlist.

def _type(text):
    """The TYPE the patterns assign, independent of whether a place resolved.

    Deliberately not "was it served": read() also requires a resolvable West
    Bank place, so a fragment with no town in it comes back `unclear` no matter
    what the patterns did. Asserting on the served verdict would let every
    negative test below pass for the wrong reason — the string would be
    rejected for missing geography while the substring bug it exists to catch
    sat there untouched.
    """
    return read(text).incident_type


def test_askari_is_not_a_closure():
    """`سكر` unanchored sits inside `عسكري` — military — and `السكري`, diabetes.

    Four of the six sampled closures were this one substring: a checkpoint
    described as العسكري, a قرار عسكري, a نقطة عسكرية, and a health-ministry
    note on labour induction that mentioned diabetes.
    """
    for t in ("قرار عسكري اسرائيلي يقضم مزيدا من اراضي البيرة",
              "حوله الى نقطة عسكرية اثر ضغوط",
              "وجود السكري او الضغط لدى الحامل"):
        assert _type(t) != "closure", t


def test_sakr_the_surname_is_not_a_closure():
    """صادق سكر is a man. سُكّر is sugar. Anchoring alone did not save this."""
    assert _type("مصادر محلية: مصرع المواطن صادق سكر من مدينة قلقيلية بحادث طرق") != "closure"


def test_hanging_up_the_phone_is_not_a_closure():
    """"اغلق المحافظ الهاتف" — the verb is exactly right, the object is a phone.

    No wordlist fixes this. Requiring a road, gate, checkpoint or area does.
    """
    assert _type("حيث اغلق المحافظ الهاتف في وجه الطبيب") != "closure"


def test_real_closures_still_read():
    for t in ("بلدية الخليل تعلن عن إغلاق شارع نمرة بسبب اعمال تمديد خط صرف صحي",
              "إغلاق كامل لجميع الطرق الفرعية على شارع جنين نابلس بحدود دير شرف",
              "قوات الاحتلال تغلق حاجز الجيب العسكري شمال غرب القدس بالاتجاهين",
              "إقامة بؤرة استيطانية شرق جنين والاحتلال يغلق المنطقة بالسواتر الترابية",
              "لم يسمح لسيارة الاسعاف بالمرور عبر الحاجز بعد اغلاق بواباته"):
        assert _type(t) == "closure", t


def test_road_status_bulletin_is_rejected():
    """`ال?` means "alef then optional lam", NOT "optional article".

    So "احوال طرق اريحا ومحيطها" never matched its own reject pattern, and a
    bulletin listing eight OPEN checkpoints and one shut one was served as a
    closure incident — an event manufactured out of a routine status post.
    """
    r = read("🔴احوال طرق اريحا ومحيطها ✅كافة حواجز أريحا سالكه 🚫عين شبلي مغلق")
    assert r.verdict != "incident", r.incident_type
    assert r.reject_reason == "status bulletin"


def test_fuel_bulletin_is_rejected():
    """مغلقة about a petrol station is fuel data, not a road closure."""
    r = read("احوال المحطات في مدينة قلقيلية للمعنيين : جميع محطات المدينة مغلقة")
    assert r.verdict != "incident"


# ── #37: a substring is not a governorate ────────────────────────────────────
def test_gaza_massacre_is_not_a_nablus_death():
    """Claim 9516: 118 killed on شارع الرشيد, bodies recovered from دوار
    النابلسي to مجمع الشفاء — Gaza in every phrase and غزة in none of them.

    Two independent failures stacked: the Gaza reject knew only town names, and
    the governorate matcher found نابلس INSIDE النابلسي, so the one filter
    meant to stop exactly this was defeated by the same substring that caused
    it. Both are asserted here.
    """
    r = read("انتشال شهيدين من دوار النابلسي ووصولهم الى مجمع الشفاء الطبي. "
             "ارتفاع حصيلة مجزرة شارع الرشيد التي ارتكبتها قوات الاحتلال "
             "الاسرائيلي صباح الخميس الى 118 شهيدا و 760 اصابة")
    assert r.verdict == "rejected"
    assert r.reject_reason == "gaza"


def test_nabulsi_the_surname_does_not_name_nablus():
    """النابلسي is also one of the commonest Palestinian surnames. A raid on
    the Nabulsi family home says nothing about which governorate it is in."""
    r = read("قوات الاحتلال تداهم منزل عائلة النابلسي في البلدة القديمة")
    assert r.governorate is None


def test_governorate_survives_a_fused_preposition():
    """Token matching must not cost the fused forms the regex used to catch:
    بنابلس is بـ+نابلس, والخليل is و+الخليل."""
    assert read("اصابة شاب برصاص الاحتلال خلال المواجهات بنابلس").governorate == "نابلس"
    assert read("اعتقالات في مدن الضفة والخليل تشهد مواجهات عنيفة").governorate == "الخليل"


def test_khalil_the_first_name_is_not_hebron():
    """الخليل carries its article; the bare token خليل is a first name."""
    r = read("اعتقل الاحتلال الشاب خليل عوض خلال اقتحام بلدة قباطية جنوب جنين")
    assert r.governorate == "جنين"


def test_her_fetus_is_not_jenin():
    """جنينها — "her fetus" — contains جنين whole. Whole-token matching still
    rejects it because the possessive suffix makes it a different token."""
    assert read("فقدت سيدة جنينها بعد احتجازها لساعات على حاجز عورتا").governorate is None


# ── origin is not site ───────────────────────────────────────────────────────
def test_the_home_village_of_the_arrested_is_not_the_arrest_site():
    """Round 3: an arrest at مفرق فصايل was pinned to المغير — the village the
    arrested man is FROM. A person followed by "من قرية X" states residence;
    the junction the sentence actually names is the site."""
    r = read("اعتقلت قوات الاحتلال الشاب محمد صلاح من قرية المغير على مفرق فصايل")
    assert r.place_text == "فصايل"


def test_a_withdrawal_from_a_village_keeps_the_village():
    """من + place word with no person before it IS the site — a troop
    withdrawal must not lose its geography to the origin guard."""
    assert read("انسحبت قوات الاحتلال من بلدة يعبد بعد اقتحام استمر ساعات").place_text == "يعبد"


def test_a_checkpoint_closure_is_sited_at_the_checkpoint():
    """حاجز/مفرق/دوار/معبر are place words now: the infrastructure the incident
    happened AT was walked straight past while a residence 20km away was
    captured instead."""
    r = read("اغلق جيش الاحتلال حاجز حوارة جنوب نابلس امام المركبات")
    assert r.incident_type == "closure"
    assert r.place_text == "حواره"
    assert r.governorate == "نابلس"


# ── round 5 (v1.6): the month-end flood, and four hidden verbs ──────────────
def test_monthly_statistics_are_not_events():
    """Round 5 was drawn on Aug 1-3 and `death` measured 0/7 — every sample
    was a month-end tally. The statistical reject knew "خلال العام" but no
    month had a name, in either calendar."""
    for t in ("وثّق مركز فلسطين لدراسات الأسرى تنفيذ سلطات الاحتلال 600 حالة اعتقال في الضفة الغربية والقدس خلال شهر تموز الماضي",
              "16 شهيدا في الضفة الغربية والقدس خلال يوليو وارتفاع وتيرة الاعتداءات",
              "نفذ الاحتلال خلال تموز الماضي 80 عملية هدم طالت 165 منشأة في محافظات قلقيلية والخليل",
              "(265) عملاً مقاوماً في الضفة والقدس خلال شهر 7/2026، أسفر عن مقتل (2) مستوطنين"):
        r = read(t)
        assert r.verdict == "rejected", (t[:40], r.incident_type)
    # آب needs its lookahead: ابو فلاح is not the month of August.
    assert read("قوات الاحتلال تقتحم قرية ابو فلاح شمال شرق رام الله").verdict == "incident"


def test_a_regional_roundup_is_not_one_incident():
    """"اقتحامات واعتقالات في الضفة" aggregates a Bank-wide night; serving it
    pins every raid to whichever village is named first."""
    r = read("اقتحامات واعتقالات في الضفة.. تصعيد ميداني وإغلاق إذاعة في قلقيلية. شنت قوات الاحتلال حملة اقتحامات واسعة طالت مدنا وبلدات ومخيمات")
    assert r.verdict == "rejected"


def test_court_news_is_not_a_field_event():
    """The high court rejecting demolition petitions was served as a SHOOTING."""
    r = read("رفضت المحكمة العليا الإسرائيلية 15 التماسًا بشأن المخططات التفصيلية في خربة الديرات شرق يطا")
    assert r.verdict == "rejected"


def test_release_and_retrospective_are_aftermath():
    assert read("بعد اكثر من عام من الاعتقال بنان أبو الهيجا خارج السجن لتلتقي مع أطفالها الأربعة").verdict == "rejected"
    assert read("وفاة مواطنة متأثرة بجراحها الخطيرة التي أصيبت بها الأسبوع الماضي جراء حادث سير في بلدة بيت أولا").verdict == "rejected"


def test_a_notice_with_any_preposition_is_still_not_an_act():
    """"إخطارات بهدم" sailed past (هدم|بالهدم), and بهدم then matched the
    demolition pattern inside itself — a notice served as the act."""
    for t in ("قوات الاحتلال توزع اليوم إخطارات بهدم عدد من المنشآت التجارية شرق مدينة جنين",
              "سلطات الاحتلال وزعت 34 إخطارًا لهدم منشآت فلسطينية في محافظات بيت لحم والخليل"):
        r = read(t)
        assert r.verdict == "rejected", r.incident_type
        assert r.reject_reason in ("notice not act", "statistical")


def test_the_masdar_hides_its_own_verb_third_time():
    """اشعال is ا-ش-ع-ا-ل: the stem شعل is not inside it — same trap as
    اقتحام/اقتحم and استشهاد/استشهد. Plus ضرم, ستول and دشن, all round-5
    misses at Burqa, 'Urif and Sa'ir."""
    for t, want in (
        ("ميليشيات المستوطنين قاموا باشعال النار بالشجر القريب من المقبرة الشمالية لقرية برقة شمال غرب نابلس", "settler_attack"),
        ("مستوطنون يضرمون النيران بالأشجار قرب المقبرة الشمالية لقرية برقة شمال غرب نابلس", "settler_attack"),
        ("مستوطنو يتسهار يستولون على منطقة طبيعية تابعة لبلدة عوريف جنوب نابلس", "settler_attack"),
        ("مستوطنون يدشنون بؤرة استيطانية جديدة في منطقة العديسة في بلدة سعير شمال الخليل", "settler_attack"),
    ):
        assert kind(t) == want, t[:40]


def test_an_army_beating_is_harm_without_an_injury_noun():
    r = read("قوات الاحتلال تعتدي بالضرب على صاحب أحد المحلات التجارية في بلدة بيت فجار قبل الانسحاب من البلدة")
    assert r.verdict == "incident"
    assert r.incident_type == "injury"


def test_censorship_dots_do_not_hide_the_settler():
    """"مسـ.ـتوطن" — tatweel plus dot — dodges platform filters and dodged
    this classifier the same way: the dot became a space and split the word.
    A real attack on a vehicle was rejected as having no incident verb."""
    r = read("▫️▫️ مسـ.ـتوطن يهاجم مركبة أحد المواطنين بين قريتي المغير وأبو فلاح شرق رام الله")
    assert r.verdict == "incident"
    assert r.incident_type == "settler_attack"
