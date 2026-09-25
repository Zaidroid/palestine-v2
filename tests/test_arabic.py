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
