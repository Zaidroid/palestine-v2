"""P0.13 tests — Arabic normalisation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.arabic import fold, is_probably_arabic, normalize, variants

PASS, FAIL = [], []
def check(name, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n         got={got!r} want={want!r}"))

print("--- normalize: diacritics + tatweel ---")
check("harakat stripped", normalize("قَلَنْدِيَا"), "قلنديا")
check("tatweel stripped", normalize("قلنـــديا"), "قلنديا")

print("--- normalize: letter folding ---")
check("alef hamza above", normalize("أريحا"), "اريحا")
check("alef hamza below", normalize("إسرائيل"), "اسراييل")
check("alef madda", normalize("آدم"), "ادم")
check("alef maqsura -> yeh", normalize("مصطفى"), "مصطفي")
check("teh marbuta -> heh", normalize("قرية"), "قريه")
check("hamza on waw", normalize("رؤوف"), "رووف")

print("--- normalize: digits ---")
check("arabic-indic digits", normalize("حاجز ٤٤٩"), "حاجز 449")
check("eastern arabic-indic digits", normalize("۱۲۳"), "123")

print("--- normalize: punctuation + whitespace ---")
check("arabic comma", normalize("نابلس، جنين"), "نابلس جنين")
check("whitespace collapsed", normalize("  نابلس   الكبرى  "), "نابلس الكبري")
check("empty safe", normalize(None), "")
check("idempotent", normalize(normalize("قَلَنْدِيَا")), normalize("قَلَنْدِيَا"))

print("--- fold: definite article ---")
check("al- stripped", fold("القدس"), "قدس")
check("bi+al stripped", fold("بالقدس"), "قدس")
check("li+al stripped", fold("للقدس"), "قدس")
check("al- stripped per token", fold("بيت الماء"), "بيت ماء")

print("--- fold: place-type prefixes ---")
check("hajiz prefix", fold("حاجز قلنديا"), "قلنديا")
check("mahatta prefix", fold("محطة الوفاء"), "وفاء")
check("nested prefixes", fold("حاجز مدخل نابلس"), "نابلس")
check("mukhayyam prefix", fold("مخيم بلاطة"), "بلاطه")
check("latin noise", fold("checkpoint Qalandia"), "qalandia")

print("--- fold: the key property ---")
# Everything a channel might write for one checkpoint must fold to one key.
qalandia = ["حاجز قلنديا", "قلنديا", "الحاجز قلنديا", "حاجز قلنـديا", "قَلَنْدِيَا"]
keys = {fold(v) for v in qalandia}
check("all Qalandia spellings share one key", len(keys), 1)

print("--- censorship-evasion dots ---")
# Channels write مسـ.ـتوطن and الاحـ.ـتلال to dodge platform filters. The
# tatweel strips, the dot then became a SPACE and split the word in half —
# a settler attack was rejected as "no incident verb" this way (round 5).
check("inner dot removed", normalize("مسـ.ـتوطن"), "مستوطن")
check("inner dot removed (ihtilal)", normalize("الاحـ.ـتلال"), "الاحتلال")
check("inner dot removed (askari)", normalize("العـ.ـسكري"), "العسكري")
check("sentence dot still splits", normalize("سالك. جيش"), "سالك جيش")
# Latin dots were ALREADY punctuation-to-space before the inner-dot rule;
# the rule must not change that.
check("latin dot spaces as before", normalize("palhub.app"), "palhub app")
# Evasion with two dots and a tatweel (claim 13259) is still evasion.
check("tatweel double dot removed", normalize("الاحتـ..ـلال"), "الاحتلال")
# A bare single dot inside a word is still evasion (claim 12506, مش.هد).
check("bare single dot removed", normalize("مش.هد"), "مشهد")
# An ELLIPSIS between two words is a pause, not evasion. The rule fused
# "المغير…شرق" into المغيرشرق, which matches no alias (F315).
check("ellipsis between words spaces", normalize("حوارة…مغلق"), "حواره مغلق")
check("three dots between words space", normalize("شاهد...رسائل المتعافين"),
      "شاهد رسايل المتعافين")
check("ellipsis keeps the village", normalize("قرية المغير…شرق رام الله"),
      "قريه المغير شرق رام الله")

print("--- invisible marks, emoji, Persian letters (F314/F353/F108) ---")
# Bidi and zero-width marks are invisible: a name followed by an RLM, or with a
# ZWJ inside it, looked right on screen and matched nothing.
check("RLM dropped", normalize("حوارة‏ مغلق"), "حواره مغلق")
check("bidi override and ZWJ dropped",
      normalize("حاجز قلنديا ‮مغلق‬ مفتوح‍​"),
      "حاجز قلنديا مغلق مفتوح")
check("ZWJ inside a name dropped", normalize("حوا‍رة"), "حواره")
check("isolates dropped", normalize("⁧البيضاء⁩"), "البيضاء")
check("zero-width space separates", normalize("حوارة​مغلق"), "حواره مغلق")
# An emoji glued to a word separates it exactly as a space does — the same
# rule checkpoint_text.tokens() already applies.
check("emoji before a word spaces", normalize("🔴حوارة مغلق"), "حواره مغلق")
check("emoji after a word spaces", normalize("حوارة🔴 جنوب نابلس"), "حواره جنوب نابلس")
check("station word behind an emoji", normalize("🚫حاجز حوارة مغلق"), "حاجز حواره مغلق")
check("variation selector and square", normalize("عابا ▫️وهو"), "عابا وهو")
check("pin emoji", normalize("📍في بيت ليد"), "في بيت ليد")
# A Farsi keyboard writes ی and ک; the gazetteer holds ي and ك.
check("farsi yeh", normalize("بيت لقی"), "بيت لقي")
check("farsi keheh", normalize("کفر قدوم"), "كفر قدوم")
check("idempotent on symbols", normalize(normalize("🔴حوارة‏")), normalize("🔴حوارة‏"))

print("--- fold: the article is stripped once (F522) ---")
# The second article pass stripped a stem that merely begins like one:
# الوالجة -> والجه -> جه, الفالوجة -> فالوجه -> وجه ("face").
check("al-walaja keeps its stem", fold("الوالجة"), "والجه")
check("al-faluja keeps its stem", fold("الفالوجة"), "فالوجه")
check("place-type then article still folds", fold("حاجز القدس"), "قدس")
check("article then place-type still folds", fold("الحاجز قلنديا"), "قلنديا")

print("--- variants + language detection ---")
check("variants deduped when equal", variants("قلنديا"), ["قلنديا"])
check("variants keeps both when differing", variants("حاجز قلنديا"), ["حاجز قلنديا", "قلنديا"])
check("arabic detected", is_probably_arabic("نابلس"), True)
check("latin not arabic", is_probably_arabic("Nablus"), False)
check("empty not arabic", is_probably_arabic(""), False)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
