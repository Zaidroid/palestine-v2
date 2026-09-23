"""Organ C — the Gaza MoH daily bulletin, read into the casualty series.

WHY THIS MODULE EXISTS
The databank's Gaza casualty series has been frozen since **2026-08-08** at
73,384 killed / 174,242 injured while the publisher kept posting every single
day. The texts were already archived: 5,217 `tg_mohmediagaza` claims carry
text, 494 of them the daily statistical bulletin. Nothing read any of them.
The plan's W1 (F-10, F-11, F-12) is the route, and this is F-10's half.

WHAT ONE BULLETIN IS
Four labelled blocks, in this order, with the wording drifting between them:

    ⭕ ... خلال الـ 24 ساعة الماضية:      - N شهداء ... - M إصابة
    🔴 منذ وقف إطلاق النار (11 أكتوبر ...):  إجمالي الشهداء / الإصابات / الانتشال
    🔴 ... التراكمية منذ بداية العدوان ...:  تراكمي الشهداء / الإصابات
    وزارة الصحة <DD شهر YYYY>

Four things about this corpus were MEASURED, and each one broke a reader that
assumed otherwise:

1. The cumulative labels are written at least three ways — `تراكمي الشهداء`,
   `العدد التراكمي للشهداء`, `إجمالي الشهداء` — and the section header as
   `الإحصائية التراكمية` or `الحصيلة التراكمية`. A reader keyed on one phrasing
   read 6 of 201 bulletins.
2. The blocks are not always label-first. `- 5 شهداء` (value first) and
   `إجمالي الشهداء: 73,919` (label first) both occur, so the number has to be
   classified by the word around it, not by a fixed order.
3. The window is not always 24 hours. 48-hour bulletins appear throughout
   (`خلال الـ 48 ساعة الماضية`), which is why `window_hours` is read: a 48-hour
   window overlaps the previous bulletin's, and a delta check that assumes 24
   hours refuses honest rows.
4. Thousands separators are commas, dots (`72.292`) and Arabic thousands
   signs, and the first date in a bulletin is always the ceasefire date, never
   the bulletin's own date.

WHAT THIS MODULE IS NOT
It writes nothing, decides nothing, and calls no model. It reads text into a
typed payload and refuses a payload it cannot stand behind. F-11 scores a model
against the gold set this builds; F-12 wires whichever wins into the analyst
loop. Until then the series stays frozen, which is the honest state.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime

VERSION = "c/1"

# ── text cleaning ────────────────────────────────────────────────────────────
# Bidi marks and word joiners sit inside phrases in this corpus (81 U+2060, plus
# RLM/LRM runs), so a plain substring test for an Arabic phrase is unreliable
# until they are gone. Arabic-Indic digits appear in the raw text as well.
_CONTROL = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00ad\u2060]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_NUM = r"(\d[\d,.\u066c]*)"

MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5,
    "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أيلول": 9,
    "ايلول": 9, "أكتوبر": 10, "اكتوبر": 10, "تشرين الأول": 10, "نوفمبر": 11,
    "ديسمبر": 12, "كانون الأول": 12,
}

# The schema F-10 commits to. Enforced on the model's answer in F-11 (json_schema
# through the gateway) and on every gold row here. `null` is a legal value for
# the four demographic fields, because the daily statistical bulletin does not
# carry them: measured across the 201 bulletins of 2026, they appear zero times
# (one 2025 bulletin carries a children count). The MoH publishes a separate
# demographic bulletin; if it is wanted, it is a second organ, not a field.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["as_of_date", "cum_killed", "cum_injured",
                 "last_24h_killed", "last_24h_injured"],
    "properties": {
        "as_of_date": {"type": "string", "description": "YYYY-MM-DD as printed on the bulletin"},
        "cum_killed": {"type": "integer", "minimum": 1},
        "cum_injured": {"type": "integer", "minimum": 1},
        "last_24h_killed": {"type": "integer", "minimum": 0},
        "last_24h_injured": {"type": "integer", "minimum": 0},
        "children": {"type": ["integer", "null"], "minimum": 0},
        "women": {"type": ["integer", "null"], "minimum": 0},
        "medics": {"type": ["integer", "null"], "minimum": 0},
        "journalists": {"type": ["integer", "null"], "minimum": 0},
        "since_ceasefire_killed": {"type": ["integer", "null"], "minimum": 0},
        "since_ceasefire_injured": {"type": ["integer", "null"], "minimum": 0},
        "recovered": {"type": ["integer", "null"], "minimum": 0},
        # MEASURED ADDITION to the plan's field list — see the module docstring.
        "window_hours": {"type": ["integer", "null"], "minimum": 1, "maximum": 168},
    },
}

H24 = "h24"
CEASEFIRE = "ceasefire"
CUMULATIVE = "cumulative"

_H24_HEAD = re.compile(r"(\d{1,3})\s*ساعة[^\n]{0,30}?ماضية")
# A holiday window with no hours at all: `خلال ايام عيد الفطر وحتى الساعة:`.
# Two 2026 bulletins report a count this way, and a reader without this header
# reports those days as having no casualties stated anywhere.
_H24_HEAD_FALLBACK = re.compile(r"خلال\s+(?:ايام|أيام)[^\n]{0,60}?الساعة")
# And one bulletin names no period at all: `بلغ إجمالي ما وصل إلى مستشفيات قطاع
# غزة حتى هذه اللحظة.` — its numbers are stated, its window is not, so the
# numbers are read and `window_hours` stays None. Anchored on the reach-hospitals
# phrase, because the rubble sentence ends with the same three words.
_H24_HEAD_NO_WINDOW = re.compile(r"ما وصل إلى مستشفيات[^\n]{0,60}?حتى هذه اللحظة")
_CF_HEAD = re.compile(r"وقف إطلاق النار")
_CUM_HEAD = re.compile(r"منذ بداية العدوان|الحصيلة التراكمية|الإحصائية التراكمية")
_DATE_AR = re.compile(r"(\d{1,2})\s*(" + "|".join(MONTHS) + r")\s*(\d{4})")

_KILLED = ("شهداء", "شهيد", "الشهداء")
# `اصابة` without the hamza is the same word: one archived bulletin writes its
# 24 h injuries that way (`19 اصابة`) and a reader that knows only the hamzated
# spelling reports that day as having no injuries.
_INJURED = ("إصابات", "إصابة", "الإصابات", "اصابات", "اصابة")
_RECOVERED = ("انتشال", "الانتشال")
# Stated absence, not inferred absence: `ولا توجد إصابات` is the bulletin saying
# so, and it is read as 0. A window that merely omits a line is left as None and
# refused by the schema check, because silence is not a statement.
_NO_INJURED = re.compile(r"لا توجد (?:أي )?(?:إصاب|اصاب)")
_NO_KILLED = re.compile(r"لا توجد (?:أي )?(?:شهد|شهيد)")

_SEG_SPLIT = re.compile(r"[•⭕🔴\-\n]")


def clean(text: str) -> str:
    """Per-line trimmed text with no bidi marks and Arabic-Indic digits folded."""
    t = _CONTROL.sub("", text or "")
    t = t.translate(_DIGITS)
    t = t.replace("\u066c", ",").replace("\u060c", ",").replace("\u00a0", " ")
    return "\n".join(line.strip() for line in t.splitlines()).strip()


def _to_int(raw: str) -> int | None:
    """`73,919` · `72.292` · `١,٣٩٩` -> int. A dot is a separator here, not a point.

    One archived bulletin writes the cumulative as `72.292`; a reader that treats
    the dot as a decimal point returns 72, which then fails the delta check and
    is refused — correctly, but for the wrong reason.
    """
    s = raw.replace("\u066c", "").replace(",", "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    elif "." in s:
        return None
    return int(s) if s.isdigit() else None


def _nearest_after(text: str, limit: int = 15) -> str | None:
    """The label word closest after the number, if one is close enough."""
    best: tuple[int, str] | None = None
    for kind, words in (("injured", _INJURED), ("killed", _KILLED)):
        for w in words:
            i = text.find(w)
            if 0 <= i <= limit and (best is None or i < best[0]):
                best = (i, kind)
    return best[1] if best else None


def _nearest_before(text: str, limit: int = 15) -> str | None:
    """The label word closest before the number, if one is close enough."""
    best: tuple[int, str] | None = None
    for kind, words in (("injured", _INJURED), ("killed", _KILLED)):
        for w in words:
            i = text.rfind(w)
            if i != -1:
                dist = len(text) - (i + len(w))
                if dist <= limit and (best is None or dist < best[0]):
                    best = (dist, kind)
    return best[1] if best else None


def _classify_at(seg: str, start: int, end: int) -> str | None:
    """What the number at [start:end) counts: killed, injured, recovered, or none.

    Proximity decides, not a fixed order. `14 شهيد , و17 إصابة` carries two
    labels after the number, and a rule that asks "is any injured word nearby"
    classifies the death toll as an injury count — measured, on 65 rows. So each
    label is matched to its own number by distance, and `الانتشال` immediately
    before the number wins outright, because a line that says it is counting
    recovered bodies even when it ends with the word `شهيد`.
    """
    before, after = seg[max(0, start - 24):start], seg[end:end + 24]
    after_kind = _nearest_after(after)
    # `الانتشال: 834 شهيد` counts recovered bodies even though the word after the
    # number is `شهيد`; but `1 شهيد انتشال) و 1 إصابة` mentions انتشال one bullet
    # earlier and the number in hand is the injury count. The word that follows
    # the number decides when it is a different kind from the one before it.
    if any(w in before for w in _RECOVERED) and after_kind != "injured":
        return "recovered"
    return after_kind or _nearest_before(before)


def _blocks(text: str) -> dict[str, str]:
    """The three labelled blocks, as spans that begin AFTER their own header.

    Position-based, not line-based: a Telegram bulletin arrives flattened as
    often as it arrives with line breaks. The span starts after the header
    because the header itself carries digits — `خلال الـ 24 ساعة الماضية`
    contains the number 24, which a reader that starts at the header's first
    character then reports as the day's death toll (measured: 24 appeared as
    `last_24h_killed` in 30 rows).
    """
    heads = [(H24, (_H24_HEAD, _H24_HEAD_FALLBACK, _H24_HEAD_NO_WINDOW)),
             (CEASEFIRE, (_CF_HEAD,)), (CUMULATIVE, (_CUM_HEAD,))]
    hits: list[tuple[int, str]] = []
    for name, patterns in heads:
        for rx in patterns:
            for m in rx.finditer(text):
                hits.append((m.end(), name))
    hits.sort()
    spans: dict[str, list[str]] = {}
    for i, (pos, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        spans.setdefault(name, []).append(text[pos:end])
    return {name: "\n".join(parts) for name, parts in spans.items()}


_SPELLED = (
    # MEASURED: the 24 h line sometimes spells a small number. `شهيدان, و5 إصابات`
    # is the whole 24 h block of one bulletin, and it is the ONLY statement of
    # that day's deaths anywhere. 14 of the 201 bulletins of 2026 use the dual
    # form, several write `شهيد واحد`, and one writes a bare `شهيد` — which is
    # one death, written as a word. A reader that only looks for digits reports
    # those days as no deaths at all, which is the one error direction that
    # matters here.
    ("شهيدان", "2 شهيد"), ("شهيدين", "2 شهيد"), ("شهيد واحد", "1 شهيد"),
    ("إصابتان", "2 إصابة"), ("اصابتان", "2 إصابة"), ("إصابة واحدة", "1 إصابة"),
)

# A bare `شهيد` is one death when it stands alone (`شهيد, و 3 إصابات`) and is left
# alone when an adjective follows it (`1شهيد متأثر`, `شهيد جديد`) — the last form
# with no digit in front is left unread rather than guessed, and the row is then
# refused by the schema check, which is the visible outcome.
_BARE_ONE_KILLED = re.compile(r"(?<!\d)شهيد(?!\s*[\u0621-\u064a])")


def _expand_spelled(text: str) -> str:
    for phrase, replacement in _SPELLED:
        text = text.replace(phrase, replacement)
    return _BARE_ONE_KILLED.sub("1 شهيد", text)


def _read_block(span: str, allow_recovered: bool = True) -> dict[str, int]:
    """Every number in the span, classified; the first of each kind wins.

    Per NUMBER, not per segment, and the previous segment's tail counts as
    context. One segment can carry several numbers and only one is a count: a
    flattened ceasefire block reads `(11 أكتوبر 2025 حتى اليوم): إجمالي عدد
    الشهداء: 1,326`, where 11 and 2025 are a date. And a label can sit at the
    end of one line with its value on the next (`العدد التراكمي للإصابات:` then
    `171,304`), so a reader that resets at every newline reports that field as
    absent — which is how 23 bullets of 2026 lost their injured count.
    """
    out: dict[str, int] = {}
    context = ""
    for seg in _SEG_SPLIT.split(span):
        seg = seg.strip()
        if not seg:
            continue
        for m in re.finditer(_NUM, seg):
            val = _to_int(m.group(1))
            if val is None:
                continue
            kind = _classify_at(context + seg, len(context) + m.start(), len(context) + m.end())
            if kind is None or (kind == "recovered" and not allow_recovered):
                continue
            out.setdefault(kind, val)
        context = seg[-40:] + " "
    return out


def parse_date(text: str, reported_at: datetime | None) -> date | None:
    """The date the bulletin prints — the trailer, not the first date in the text.

    Every bulletin in this archive names the ceasefire date (11 October 2025)
    inside its second block, and the cumulative header names the war's start
    (7 October 2023). Taking the first date-shaped string therefore dates the
    whole corpus to one of those days: measured, and the reason this function
    reads backwards and prefers the sign-off line.
    """
    matches = list(_DATE_AR.finditer(text))
    if matches:
        tail_start = max(0, len(text) - 80)
        near = [m for m in matches if m.start() >= tail_start]
        m = (near or matches)[-1]
        d, month, y = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
        try:
            return date(y, month, d)
        except ValueError:
            pass
    return reported_at.date() if reported_at else None


def read(text: str, reported_at: datetime | None = None) -> dict:
    """The deterministic reading. No model, no guess: absent is `None`."""
    t = clean(text)
    blocks = _blocks(t)
    # Spelled numbers are expanded in the 24 h block only: the dual form appears
    # there, and expanding it inside the cumulative block would let a note after
    # the cumulative line (`شهيدان كلاهما طفلان`) masquerade as the day's total.
    h24_text = _expand_spelled(blocks.get(H24, ""))
    h24 = _read_block(h24_text, allow_recovered=False)
    if h24.get("killed") is None and _NO_KILLED.search(h24_text):
        h24["killed"] = 0
    if h24.get("injured") is None and _NO_INJURED.search(h24_text):
        h24["injured"] = 0
    cf = _read_block(blocks.get(CEASEFIRE, ""))
    cu = _read_block(blocks.get(CUMULATIVE, ""), allow_recovered=False)
    win = _H24_HEAD.search(t)
    out: dict = {
        "as_of_date": (parse_date(t, reported_at) or date(1970, 1, 1)).isoformat(),
        "window_hours": int(win.group(1)) if win else None,
        "cum_killed": cu.get("killed"),
        "cum_injured": cu.get("injured"),
        "last_24h_killed": h24.get("killed"),
        "last_24h_injured": h24.get("injured"),
        "children": None, "women": None, "medics": None, "journalists": None,
        "since_ceasefire_killed": cf.get("killed"),
        "since_ceasefire_injured": cf.get("injured"),
        "recovered": cf.get("recovered"),
    }
    for key, words in (("children", ("أطفال",)), ("women", ("نساء", "نساءً")),
                       ("medics", ("كوادر صحية", "مسعفين")),
                       ("journalists", ("صحفيين", "صحفيون"))):
        m = re.search(_NUM + r"[^\d\n]{0,16}?(?:" + "|".join(words) + r")", t)
        if m:
            out[key] = _to_int(m.group(1))
    return out


@dataclass
class Refusal:
    """Why a reading cannot be served, in words a human can act on."""
    code: str
    detail: str


@dataclass
class Verdict:
    ok: bool
    reasons: list[Refusal] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reasons": [asdict(r) for r in self.reasons]}


def schema_errors(reading: dict) -> list[str]:
    """Structural check against SCHEMA, without a jsonschema dependency."""
    errs: list[str] = []
    if not isinstance(reading, dict):
        return ["not an object"]
    for key in SCHEMA["required"]:
        if key not in reading:
            errs.append(f"{key}: missing")
            continue
        val = reading[key]
        if key == "as_of_date":
            if not isinstance(val, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
                errs.append(f"as_of_date: {val!r} is not YYYY-MM-DD")
            continue
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            errs.append(f"{key}: {val!r} is not a non-negative integer")
    for key in SCHEMA["properties"]:
        if key in SCHEMA["required"] or key not in reading or reading[key] is None:
            continue
        val = reading[key]
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            errs.append(f"{key}: {val!r} is not a non-negative integer or null")
    return errs


def validate(reading: dict, previous: dict | None = None,
             reported_at: datetime | None = None) -> Verdict:
    """The plan's three validators, plus the structural check.

    1. every required field present and of the right type (schema_errors)
    2. `as_of_date` within ±2 days of when the bulletin was posted
    3. cumulative counts never go backwards against the previous believed bulletin
    4. the reporting window and the cumulative block agree: the day's rise in a
       cumulative series is what the bulletin reported for its window, and a
       cumulative series that does not move while the window reports deaths is
       not a reading, it is a parse that lost a block.

    Only the LOW side of (4) is refused, and only for a 24-hour window. A rise
    larger than the window's count is the publisher's own arithmetic, not an
    error: recovered bodies are added to the cumulative separately, and one
    archived bulletin announces a committee approval that added **110** to the
    cumulative in a single day. A rise smaller than a 48-hour window's count is
    not evidence of anything either, because a 48-hour window overlaps the
    previous bulletin's window and those deaths are already inside the previous
    cumulative. Both directions are why `window_hours` is read.
    """
    reasons: list[Refusal] = []
    for e in schema_errors(reading):
        reasons.append(Refusal("schema", e))
    if reasons:
        return Verdict(False, reasons)

    as_of = date.fromisoformat(reading["as_of_date"])
    if reported_at is not None:
        drift = abs((as_of - reported_at.date()).days)
        if drift > 2:
            reasons.append(Refusal(
                "date-drift",
                f"bulletin is dated {as_of}, posted {reported_at.date()} — {drift} days apart"))

    if previous:
        window = reading.get("window_hours")
        for key, label in (("cum_killed", "killed"), ("cum_injured", "injured")):
            prev = previous.get(key)
            now = reading[key]
            if prev is None:
                continue
            if now < prev:
                reasons.append(Refusal(
                    "not-monotonic",
                    f"cumulative {label} fell {prev} -> {now} against the previous bulletin"))
            elif window is None or window <= 24:
                rise = now - prev
                day = reading.get("last_24h_killed" if key == "cum_killed" else "last_24h_injured")
                if day is not None and rise < day:
                    reasons.append(Refusal(
                        "delta-inconsistent",
                        f"cumulative {label} rose {rise} while the {window or 24} h line reported {day}"))
    return Verdict(not reasons, reasons)


def to_json(reading: dict) -> str:
    return json.dumps(reading, ensure_ascii=False, sort_keys=True)
