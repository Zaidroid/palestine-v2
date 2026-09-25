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
# A dot run between two Arabic letters, with any tatweel either side of it
# captured. The tatweel (U+0640) sits inside ء-ي, so this runs BEFORE the
# tatweel strip, while the evidence of evasion is still in the string.
_INNER_DOT = re.compile("(?<=[\u0621-\u064a])(\u0640*)([.\u00b7\u2022]+)(\u0640*)(?=[\u0621-\u064a])")
# Persian letters a Farsi keyboard writes where the gazetteer holds the Arabic
# ones: ک ی ھ ۀ ە. "بيت لقی" matched nothing (F314).
_PERSIAN = {"\u06a9": "\u0643", "\u06cc": "\u064a", "\u06be": "\u0647",
            "\u06c0": "\u0647", "\u06d5": "\u0647"}
_PERSIAN_RE = re.compile("[" + "".join(_PERSIAN) + "]")
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


# Characters that are not letters and not visible, or not words at all.
#
# Invisible format characters (Unicode category Cf) — RLM/LRM, the bidi
# embeddings, overrides and isolates, ZWJ/ZWNJ, the BOM — are DROPPED: they
# carry no letter, and a name followed by an RLM or split by a ZWJ looked right
# on screen and matched nothing (F314/F353/F108: RLM/ZWSP/ZWJ/RLI/PDI in 15 of
# 928 corpus messages). The zero-width SPACE is the one exception: it is a word
# break, so it becomes a space. cascade/palhub_roads.py and moh_gaza.py each
# stripped their own bidi table; this is the same rule for everyone.
#
# Symbols (categories So/Sk/Sm: emoji, ▫, arrows, 🔴) become a SPACE, never
# nothing: "🚫حاجز" and "حوارة🔴" are one whitespace-token, and 45 % of corpus
# messages glue an emoji to an Arabic word. checkpoint_text.tokens() already
# splits on them ("an emoji between two words separates them exactly as a
# space does"); normalize now agrees with it. Variation selectors and the
# keycap mark are combining marks that only restyle the symbol before them, so
# they go with it. Currency signs (₪) are left alone — prices read them.
_ZW_SPACE = "\u200b"
_SYMBOL_CATS = frozenset(("So", "Sk", "Sm"))
_DROP_MARKS = frozenset(chr(c) for c in (*range(0xFE00, 0xFE10), 0x20E3))


# Everything outside ASCII/C1 and the Arabic letters, digits and marks
# (U+0620-U+06DC, U+06DF-U+06FF) is looked at one character at a time; the
# common case — plain Arabic and Latin — never leaves the regex engine. U+061C
# (the Arabic letter mark) and U+06DD (end of ayah) are format characters and
# U+06DE a symbol, so they fall outside the fast range on purpose.
_NOT_PLAIN = re.compile("[^\u0000-\u009f\u0620-\u06dc\u06df-\u06ff]")


def _clean_char(m: "re.Match[str]") -> str:
    ch = m.group()
    if ch == _ZW_SPACE:
        return " "
    if ch in _DROP_MARKS:
        return ""
    cat = unicodedata.category(ch)
    if cat == "Cf":
        return ""
    return " " if cat in _SYMBOL_CATS else ch


def _strip_invisible_and_symbols(s: str) -> str:
    return _NOT_PLAIN.sub(_clean_char, s)


def _inner_dot(m: "re.Match[str]") -> str:
    """Censorship-evasion dots vs an ellipsis between two words.

    A dot run next to a tatweel ("مسـ.ـتوطن", "الاحتـ..ـلال") or a single bare
    dot inside a word ("مش.هد") is evasion: removed, so the word is whole
    again. A bare run of two or more dots — "...", or "…" after NFKC — between
    two words is a pause: it becomes a space. The rule used to remove every run,
    which fused "قرية المغير…شرق رام الله" into the candidate المغيرشرق and
    "حاجز حوارة...مغلق" into حوارهمغلق (F315).
    """
    before, dots, after = m.group(1), m.group(2), m.group(3)
    if before or after or len(dots) == 1:
        return before + after              # the tatweels go at the next step
    return " "


def normalize(text: str | None) -> str:
    """Conservative normalisation. Idempotent."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _strip_invisible_and_symbols(s)
    s = _DIACRITICS.sub("", s)
    # Censorship-evasion dots: channels write "مسـ.ـتوطن" and "الاحـ.ـتلال" to
    # dodge platform filters. Stripping the tatweel leaves "مس.توطن", and the
    # dot then becomes a SPACE at the punctuation step — splitting the word in
    # half, so neither the settler pattern nor the place matcher ever sees it.
    # A real settler attack on a vehicle was rejected as "no incident verb"
    # this way (round 5, claim 12039). Read BEFORE the tatweel strip, which
    # would otherwise destroy the evidence that tells evasion from an
    # ellipsis, and before the punctuation pass. See _inner_dot.
    if "." in s or "\u00b7" in s or "\u2022" in s:     # the regex costs; a dot is rare
        s = _INNER_DOT.sub(_inner_dot, s)
    s = _TATWEEL.sub("", s)
    s = _PERSIAN_RE.sub(lambda m: _PERSIAN[m.group()], s)
    s = _ALEF.sub("\u0627", s)
    s = _ALEF_MAQSURA.sub("\u064a", s)
    s = _TEH_MARBUTA.sub("\u0647", s)
    s = _HAMZA_WAW.sub("\u0648", s)
    s = _HAMZA_YEH.sub("\u064a", s)
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
    # NO second article pass. The place-type strip removes whole leading
    # tokens only (the pattern ends in \s+), so every token left was already
    # article-stripped above ("حاجز القدس" is "حاجز قدس" before the strip).
    # A second pass could therefore only strip a stem that merely BEGINS like
    # an article: الوالجة -> والجه -> جه, الفالوجة -> فالوجه -> وجه ("face"),
    # an exact-matchable key for an ordinary word (F522).
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
