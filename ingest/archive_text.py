"""Words for the archive's search: one rule, used when a text is stored and
when a question is asked.

WHY NOT THE DATABASE'S OWN ARABIC STEMMER. Measured on PostgreSQL 16 on
2026-10-13: it sends «ولاعة» to "لاع", «الولاعات» to "ولاع" and «ولاعات» to
"لاعا"; «مياه» to "ميا" and «المياه» to "مياه". The same word in three forms
lands on three stems, so a search finds a third of what is held and nothing
says so. And an exact-letter search (what /v2/news/latest does) makes «ولاعة»,
«قداحة» and "lighter" three questions, and finds «ولاعبيه» (a football story)
for «ولاع».

THE RULE HERE is light and, above all, the same in both directions. It is not
linguistics: «مياه» becomes "ميا" everywhere, which is wrong as grammar and
right as a key, because every form of the word arrives at the same place.

  1. fold     resolve.arabic.normalize (diacritics, tatweel, the dots channels
              put inside words, alef/ya/ta-marbuta/hamza forms, digit shapes,
              punctuation), after dropping a final tanwin alef («طفلاً» → طفل).
  2. article  one of وال بال كال فال لل ال is removed when 3 letters remain.
  3. suffix   ONE of هما ات ين ون وا ها هم هن ه is removed when 3 letters
              remain (ه covers ة, which the fold has already turned into ه).
  4. a stored word that begins with و ف ب ل ك is ALSO stored without that
     letter («بغزة» is found by «غزة», «وأطفال» by «أطفال»). A question is
     never expanded this way, so «ولاعة» does not find «لاعب».

Broken plurals do not meet their singular (أسير / أسرى, شيكل / شواكل): a
question lists the forms it wants with OR. Latin-script words are left to the
database's english configuration, on both sides.

VERSION is written beside every stored vector. Change the rule, bump it, and
`ingest.archive --reindex` rewrites the vectors that carry an older number.
"""
from __future__ import annotations

import re

from resolve.arabic import normalize

VERSION = 1
MAX_TOKENS = 20000           # a tsvector's positions stop at 16383; long reports are cut here
_TANWIN = re.compile("اً|ًا")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_ARABIC = re.compile(r"[ء-ي]")
_LATIN = re.compile(r"[a-z]")
_ARTICLES = ("وال", "بال", "كال", "فال", "لل", "ال")
_SUFFIXES = ("هما", "ات", "ين", "ون", "وا", "ها", "هم", "هن", "ه")
_ONE_LETTER = "وفبلك"
_WEIGHT = {"title": "A", "extra": "C", "body": ""}


def stem(tok: str) -> str:
    """A folded Arabic token → its key. Give it a folded token, never a key:
    a second pass would strip a second ending."""
    for a in _ARTICLES:
        if tok.startswith(a) and len(tok) - len(a) >= 3:
            tok = tok[len(a):]
            break
    for s in _SUFFIXES:
        if tok.endswith(s) and len(tok) - len(s) >= 3:
            return tok[:-len(s)]
    return tok


def tokens(text: str | None) -> list[str]:
    """Folded tokens in order, Arabic and Latin and numbers alike."""
    if not text:
        return []
    return _TOKEN.findall(normalize(_TANWIN.sub("", text)))


def keys(tok: str, stored: bool) -> list[str]:
    """The key(s) of one folded token. Latin and numbers give none here: the
    database's english configuration owns them."""
    if not _ARABIC.search(tok):
        return []
    out = [stem(tok)]
    if stored and len(tok) >= 4 and tok[0] in _ONE_LETTER:
        rest = stem(tok[1:])
        if len(rest) >= 3 and rest != out[0]:
            out.append(rest)
    return out


def vector(title: str | None, body: str | None, extra: str | None = None) -> str:
    """The Arabic half of a document's search vector, as tsvector text
    (`'key':1A,7 ...`). The caller adds the english half in SQL."""
    places: dict[str, list[str]] = {}
    pos = 0
    for part, text in (("title", title), ("body", body), ("extra", extra)):
        w = _WEIGHT[part]
        for tok in tokens(text):
            pos += 1
            if pos > MAX_TOKENS:
                break
            p = min(pos, 16383)
            for k in keys(tok, stored=True):
                slot = places.setdefault(k, [])
                if len(slot) < 255:
                    slot.append(f"{p}{w}")
    return " ".join(f"'{k}':{','.join(v)}" for k, v in sorted(places.items()))


def latin(text: str | None) -> str:
    """The text with Arabic-script words removed: what the english
    configuration is given, so it does not store every Arabic word a second
    time unstemmed."""
    if not text:
        return ""
    return " ".join(t for t in tokens(text)[:MAX_TOKENS] if not _ARABIC.search(t))


class BadQuestion(ValueError):
    pass


_Q = re.compile(r'"([^"]+)"|(\()|(\))|(\bOR\b|\|)|(-?)([^\s()"|]+)')


def question(q: str) -> str:
    """A question → the text of a tsquery, to be given to
    `to_tsquery('english', %s)` (which stems the Latin words and leaves the
    Arabic keys, already stemmed here, as they are).

        ولاعة OR قداحة OR lighter          any of the three
        مياه غزة                            both words
        "اعتقال الأطفال"                    the words side by side
        أسرى -غزة                           the first without the second
        (ولاعة OR قداحة) شيكل               brackets group
    """
    out: list[str] = []
    need_and = False

    def term(words: list[str]) -> str | None:
        ks = []
        for w in words:
            for t in tokens(w):
                k = keys(t, stored=False)
                ks.append(k[0] if k else t)
        ks = [k.replace("'", "") for k in ks if k]
        if not ks:
            return None
        return "(" + " <-> ".join(f"'{k}'" for k in ks) + ")" if len(ks) > 1 else f"'{ks[0]}'"

    for m in _Q.finditer(q.strip()):
        phrase, lpar, rpar, or_, neg, word = m.groups()
        if or_:
            if not out or out[-1] in ("|", "("):
                raise BadQuestion("OR needs a word on each side")
            out.append("|")
            need_and = False
            continue
        if rpar:
            out.append(")")
            need_and = True
            continue
        if need_and:
            out.append("&")
        if lpar:
            out.append("(")
            need_and = False
            continue
        t = term([phrase]) if phrase else term([word])
        if t is None:
            if out and out[-1] == "&":
                out.pop()
            continue
        out.append(("!" if neg and not phrase else "") + t)
        need_and = True
    while out and out[-1] in ("|", "&"):
        out.pop()
    if not out:
        raise BadQuestion("the question has no searchable word")
    if out.count("(") != out.count(")"):
        raise BadQuestion("a bracket is not closed")
    return " ".join(out)


def question_keys(q: str) -> set[str]:
    """The keys a question looks for (negated ones too): what a snippet
    should be cut around."""
    return set(re.findall(r"'([^']+)'", question(q)))


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def snippet(text: str, wanted: set[str], width: int = 260) -> str:
    """A window of `text` around the first word whose key is wanted. Works on
    the text as written, so what is shown is the publisher's own words."""
    flat = " ".join((text or "").split())
    for m in _WORD.finditer(flat):
        toks = tokens(m.group(0))
        if not toks:
            continue
        ks = set(keys(toks[0], stored=True)) | {toks[0]}
        if ks & wanted:
            a = max(0, m.start() - width // 3)
            b = min(len(flat), a + width)
            return ("…" if a else "") + flat[a:b].strip() + ("…" if b < len(flat) else "")
    return flat[:width] + ("…" if len(flat) > width else "")
