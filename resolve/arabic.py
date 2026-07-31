"""P0.13 — Arabic text normalisation for place matching.

Ported and extended from v1's `checkpoint_parser._normalise`. v1 handled
diacritics, alef forms, alef-maqsura and teh-marbuta. This adds what a
gazetteer needs and v1 lacked: Arabic-Indic digits, tatweel, hamza carriers,
punctuation, the definite article, and place-type prefixes.

Two levels, deliberately separate:

  normalize(s) — conservative. Safe to display; only removes what is never
                 semantically meaningful (diacritics, tatweel, digit form).
  fold(s)      — aggressive. Strips the definite article and place-type words
                 ("حاجز", "محطة", "بلدة"). Used ONLY as a matching key, never
                 shown to a user and never stored as a name.

Keeping them apart matters: folding "حاجز قلنديا" to "قلنديا" is right for
lookup and wrong for display.
"""
from __future__ import annotations

import re
import unicodedata

# ── character classes ────────────────────────────────────────────────────────
_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")   # harakat, superscript alef
_TATWEEL = re.compile(r"ـ")                                   # kashida
_ALEF = re.compile(r"[آأإٱ]")                  # آ أ إ ٱ -> ا
_ALEF_MAQSURA = re.compile(r"ى")                              # ى -> ي
_TEH_MARBUTA = re.compile(r"ة")                               # ة -> ه
_HAMZA_WAW = re.compile(r"ؤ")                                 # ؤ -> و
_HAMZA_YEH = re.compile(r"ئ")                                 # ئ -> ي
_PUNCT = re.compile(r"[،؛؟٪-٭۔"      # ، ؛ ؟ ٪ ٫ ٬ ٭ ۔
                    r"\"'`´’‘“”«»\[\]{}()<>.,;:!?/\\|_+*=~^&%$#@—–-]")
_WS = re.compile(r"\s+")

# Arabic-Indic (٠-٩) and Eastern Arabic-Indic (۰-۹) digits -> ASCII
_DIGITS = {**{chr(0x0660 + i): str(i) for i in range(10)},
           **{chr(0x06F0 + i): str(i) for i in range(10)}}
_DIGIT_RE = re.compile("[" + "".join(_DIGITS) + "]")

# Definite article. Three shapes, longest first:
#   لل    lam-lam elision — لـ + القدس writes as للقدس, NOT لالقدس
#   Xال   preposition + article — بالقدس, كالقدس, والقدس
#   ال    bare article — القدس
_ARTICLE = re.compile(r"^(?:لل|[بلكفو]ال|ال)")

# Place-type words that precede a name. Folded away for matching only.
# "حاجز قلنديا" and "قلنديا" must hit the same key.
_PLACE_TYPES = (
    "حاجز", "حواجز", "محطة", "محطه", "مفرق", "مدخل", "مخرج", "بوابة", "بوابه",
    "معبر", "بلدة", "بلده", "قرية", "قريه", "مدينة", "مدينه", "مخيم", "شارع",
    "طريق", "دوار", "جسر", "نفق", "منطقة", "منطقه", "حي", "بلد",
)
# Built from NORMALISED forms: fold() runs after normalize(), so a raw "محطة"
# in the list above could never match ("ة" is already "ه" by then).
# Longest-first so "محطه" is tried before "حي".
_PLACE_TYPE_RE: "re.Pattern[str]"  # set below, after normalize() is defined

# Latin transliteration noise seen in channel text.
_LATIN_NOISE = re.compile(r"^(?:checkpoint|cp|the)\s+", re.I)


def normalize(text: str | None) -> str:
    """Conservative normalisation. Idempotent."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _DIACRITICS.sub("", s)
    s = _TATWEEL.sub("", s)
    s = _ALEF.sub("ا", s)
    s = _ALEF_MAQSURA.sub("ي", s)
    s = _TEH_MARBUTA.sub("ه", s)
    s = _HAMZA_WAW.sub("و", s)
    s = _HAMZA_YEH.sub("ي", s)
    s = _DIGIT_RE.sub(lambda m: _DIGITS[m.group()], s)
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s)
    return s.strip().lower()


def _strip_article(tok: str) -> str:
    """Strip a leading article, unless doing so would gut the token."""
    out = _ARTICLE.sub("", tok)
    return out if len(out) >= 2 else tok


def fold(text: str | None) -> str:
    """Aggressive matching key. Not for display, not for storage as a name."""
    s = normalize(text)
    if not s:
        return ""
    s = _LATIN_NOISE.sub("", s)
    # Article BEFORE place-type: "الحاجز قلنديا" must become "حاجز قلنديا"
    # before the place-type strip can see a "حاجز" to remove. Doing these in
    # the other order silently leaves the prefix in place.
    s = " ".join(_strip_article(tok) for tok in s.split())
    # Repeat: "حاجز مدخل نابلس" needs two passes.
    for _ in range(3):
        new = _PLACE_TYPE_RE.sub("", s)
        if new == s:
            break
        s = new
    # Article again — the place-type strip can expose a fresh one
    # ("حاجز القدس" -> "القدس" -> "قدس").
    s = " ".join(_strip_article(tok) for tok in s.split())
    return _WS.sub(" ", s).strip()


_PLACE_TYPE_RE = re.compile(
    r"^(?:" + "|".join(sorted((re.escape(normalize(p)) for p in _PLACE_TYPES),
                              key=len, reverse=True)) + r")\s+"
)


def variants(text: str | None) -> list[str]:
    """Keys worth indexing for one name, most specific first, deduped."""
    out, seen = [], set()
    for v in (normalize(text), fold(text)):
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def is_probably_arabic(text: str | None) -> bool:
    if not text:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum("؀" <= c <= "ۿ" for c in letters) / len(letters) > 0.5


# Words that must never be a standalone alias. Several are real place-name
# components ("مخيم" in حي المخيم, "شارع" in a street name), but as a bare key
# they match every phrase containing the ordinary noun. Measured: indexing
# "مخيم" alone sent every "مخيم النصيرات" phrase 143 km to Hayy al Mukhayyam.
GENERIC_ALIAS_STOPWORDS = frozenset(
    [normalize(w) for w in _PLACE_TYPES] + [normalize(w) for w in (
        "شمال", "جنوب", "شرق", "غرب", "شمالي", "جنوبي", "شرقي", "غربي",
        "وسط", "قطاع", "اراضي", "أراضي", "منطقه", "قرب", "داخل",
        # NOT "ضفه": الضفة الغربية is a proper name, not a direction. Listing it
        # reduced "شمالي الضفة الغربية" to the bare adjective "غربيه", which
        # matched the neighbourhood Hayy al Gharbiyah ~25 km away.
        "north", "south", "east", "west", "central", "middle", "strip", "area",
        # Fuel domain. Several OSM stations are literally NAMED "كازية"
        # (gas station) or "محروقات" (fuel), so without these the generic word
        # becomes an alias and "كازية تل الربيع" resolves to the wrong station.
        "كازية", "كازيه", "محروقات", "بنزين", "سولار", "ديزل", "وقود", "بنزينه",
        "غاز", "محطه", "محطات",
        # Conversational query words that surround a place name in chatter.
        "وين", "فين", "اين", "حدا", "عنده", "علم", "يوجد", "متوفر", "بدي",
    )]
)


def is_generic_alias(key: str | None) -> bool:
    """True if this key is a generic noun that cannot identify a place.

    Deliberately NOT a length rule. Short keys are dangerous for *containment*
    matching (a 3-char substring hits everything) but perfectly valid for
    *exact* matching — Jit, Kur and غزه are real places with short names.
    Length is therefore enforced only in the containment branch of geo.py;
    conflating the two here silently deleted 175 resolvable phrases.
    """
    return bool(key) and key in GENERIC_ALIAS_STOPWORDS


def strip_preposition(token: str) -> str | None:
    """Strip a fused single-letter preposition (بـ لـ كـ فـ) from a token.

    Distinct from the article: "بالقدس" is بـ+ال+قدس and _ARTICLE handles it,
    but "بطولكرم" is بـ + a bare proper noun with no article, which it does not.
    Returns None when stripping is unsafe — real names begin with these letters
    ("بيت لحم"), so callers must treat the result as an ADDITIONAL probe, never
    as a replacement.
    """
    if len(token) < 5 or token[0] not in "بلكف":
        return None
    rest = token[1:]
    return rest if len(rest) >= 4 else None


def fold_for_match(text: str | None) -> str:
    """Matching probe: drop generic tokens ANYWHERE, not just at the start.

    fold() only strips a place-type prefix at position 0, so "غرب مدينة غزة"
    folds to "غرب مدينه غزه" and never matches the alias "غزه". Directional and
    place-type words carry no identifying information wherever they appear, so
    for matching purposes we drop them all and keep what is left.

        "غرب مدينة غزة"                  -> "غزه"      (then an EXACT hit)
        "جنوب شرقي مدينة غزة"            -> "غزه"
        "غربي مخيم النصيرات وسط قطاع غزة" -> "نصيرات غزه"
        "south"                          -> ""         (correctly unresolvable)

    Returns "" when nothing identifying remains — a bare direction is not a place.
    """
    s = fold(text)
    if not s:
        return ""
    kept = [t for t in s.split() if t not in GENERIC_ALIAS_STOPWORDS]
    return " ".join(kept).strip()
