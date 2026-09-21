"""Organ A — what language a claim is actually in.

    from analyst.lang import detect
    detect("الاحتلال يقتحم بلدة سلوان")   -> ("ar", "lingua@2.2.0")
    detect("https://wp.me/paCNSd-uev")     -> ("und", "lingua@2.2.0")

WHY THIS EXISTS
Every claim ever written carries `lang = 'ar'`, hard-coded at all three insert
sites, including the RSS feeds and the English MoH bulletins. It was never a
measurement; it was a constant wearing a measurement's name, which is the
failure mode this project keeps finding in its own instruments. 99,376 rows say
"Arabic" with exactly as much evidence behind them as a blank column.

WHY THE TEXT IS CLEANED BEFORE IT IS ASKED ABOUT
Measured on 20,000 live claims: lingua confidently calls a bare
`https://wp.me/paCNSd-uev` ENGLISH, and 9 of the first 25 non-Arabic verdicts
in that sample were nothing but URLs. A URL is not a sentence in any language.
So URLs, @handles, digits, emoji and punctuation come out first, and what is
left is what gets asked about. If nothing linguistic is left — and 30,080 of
the corpus's claims are image-only fuel posts with no text at all — the answer
is `und`, not a plausible language. An honest nothing rather than a plausible
somewhere is the rule this repo already applies to places.

WHY THESE THREE LANGUAGES
lingua's accuracy on short text comes from restricting the candidate set, and a
detector offered 75 languages will find Urdu in Arabic and Afrikaans in a
headline. The sources carry Arabic (every Telegram channel and both RSS feeds),
English (the MoH bulletins, forwarded wire copy) and, when a Hebrew source is
finally added, Hebrew. Adding a language here is a deliberate act with a
re-measurement behind it, not a default.

LOW-ACCURACY MODE IS A MEASURED CHOICE
307 claims/second on this box with the language models preloaded, against a
corpus of 99k and ~1,800 new claims a day. High-accuracy mode buys nothing on
three languages that do not share a script.

IMPORT MUST NOT BE ABLE TO STOP INGESTION
The poller and the RSS reader call this on the insert path. If the library is
missing or broken, `detect_quietly` returns (None, None) and the claim is
written with a NULL lang — an honest "nobody has looked yet", which the analyst
loop's organ A then fixes on its next pass. A collector that dies because a
language detector could not be imported would be a far worse bug than the one
this file repairs.
"""
from __future__ import annotations

import re
import threading

# ISO 639-3's code for "undetermined". Not NULL, which means "nobody looked",
# and not a guess. The two states are different and both are real.
UNDETERMINED = "und"

# Enough letters left, after the noise is stripped, for a verdict to mean
# anything. Two Arabic letters are a word; two Latin letters are an abbreviation
# in no particular language. Applied to the cleaned text, so "🟢⛽️ بخصوص
# المحروقات" is judged on its four Arabic words and not on its emoji.
MIN_LETTERS = 4

_URL = re.compile(r"https?://\S+|www\.\S+|\b\S+\.(?:com|net|org|co|ps|il|me|io|gov|edu)\b/?\S*",
                  re.IGNORECASE)
_HANDLE = re.compile(r"[@#]\w+")
# Keep letters and whitespace from ANY script; drop digits, punctuation, emoji,
# bidi marks and the rest. `str.isalpha` is Unicode-aware, so this needs no
# per-script block list that a new source could fall outside of.
_KEEP = re.compile(r"\s+")

_lock = threading.Lock()
_detector = None
_detector_id: str | None = None


def _build():
    """Build the detector once, and name it with the version that built it."""
    global _detector, _detector_id
    if _detector is not None:
        return _detector, _detector_id
    with _lock:
        if _detector is not None:
            return _detector, _detector_id
        from importlib.metadata import version

        from lingua import Language, LanguageDetectorBuilder
        det = (LanguageDetectorBuilder
               .from_languages(Language.ARABIC, Language.HEBREW, Language.ENGLISH)
               .with_low_accuracy_mode()
               .with_preloaded_language_models()
               .build())
        _detector_id = f"lingua@{version('lingua-language-detector')}"
        _detector = det
        return _detector, _detector_id


def detector_id() -> str:
    """The provenance string stamped onto every row this organ touches."""
    return _build()[1]


def clean(text: str | None) -> str:
    """Strip everything that carries no language, and say what is left."""
    if not text:
        return ""
    t = _URL.sub(" ", text)
    t = _HANDLE.sub(" ", t)
    t = "".join(c if (c.isalpha() or c.isspace()) else " " for c in t)
    return _KEEP.sub(" ", t).strip()


def detect(text: str | None) -> tuple[str, str]:
    """(language code, detector id). `und` when the text decides nothing.

    Raises if the detector cannot be built — callers on the ingest path use
    `detect_quietly` instead, which cannot raise.
    """
    det, ident = _build()
    cleaned = clean(text)
    if sum(1 for c in cleaned if c.isalpha()) < MIN_LETTERS:
        return UNDETERMINED, ident
    lang = det.detect_language_of(cleaned)
    if lang is None:
        return UNDETERMINED, ident
    code = lang.iso_code_639_1.name.lower()
    return code, ident


def detect_quietly(text: str | None) -> tuple[str | None, str | None]:
    """For the ingest path. (None, None) if the detector is unavailable.

    A NULL `lang` on a fresh claim is not a hole in the record — it is the
    absence of the one stamp the analyst loop looks for, so organ A picks the
    row up on its next pass and fills it in. The collector keeps collecting.
    """
    try:
        return detect(text)
    except Exception as exc:                                    # noqa: BLE001
        import sys
        print(f"lang detection unavailable ({type(exc).__name__}: {exc}) — "
              f"claim written with no language; the analyst will fill it in",
              file=sys.stderr)
        return None, None
