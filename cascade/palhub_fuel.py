"""P1.7 — parser for the palhubappfuel structured fuel feed.

The channel posts a COMPLETE state snapshot for all 14 West Bank regions every
~30 minutes (observed: 11:31, 11:37, 12:00, 12:07, 12:30 local). Each region is
one message:

    ⛽ حالة محطات الوقود  ضواحي القدس
    آخر تحديث: ٣١‏/٠٧، ١١:٣١ ص

    - محطة ابو الريش (كفر عقب): سولار ⚪ غير متوفر | بنزين 🔵 متوفر
    - محطة ابو شلبك  - مدخل الرام (الرام): سولار 🟠 متوفر | بنزين 🔵 متوفر

Structure notes established by measurement, not assumption:
  * The emoji is a COMMODITY marker, not a status modifier — 🟠 diesel,
    🔵 gasoline, ⚪ neither. Status is the TEXT (متوفر / غير متوفر), so parsing
    on emoji would be wrong. Verified across 1,600 readings.
  * "غير متوفر" contains "متوفر", so a naive substring test inverts the answer.
    Unavailability must be tested first.
  * ~58% of station lines carry a "(locality)" suffix; the rest are name-only.
  * Digits in the timestamp are Arabic-Indic and the string carries an RTL mark.

Because each sweep is a full snapshot, absence of a station from a sweep is
meaningful (it was delisted), and staleness is a property of the FEED, not of
an individual station.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.arabic import normalize

HEADER = re.compile(r"^⛽\s*حالة محطات الوقود\s+(?P<region>.+?)\s*$", re.M)
UPDATED = re.compile(r"^آخر تحديث:\s*(?P<stamp>.+?)\s*$", re.M)
STATION_LINE = re.compile(r"^-\s*(?P<body>.+)$", re.M)
LOCALITY = re.compile(r"\(([^)]+)\)\s*$")

# Commodity → canonical state_kind
COMMODITY = {
    "سولار": "fuel_diesel",
    "ديزل": "fuel_diesel",
    "بنزين": "fuel_gasoline",
    "غاز": "cooking_gas",
}
_COMMODITY_RE = "|".join(COMMODITY)
# Order matters: "غير متوفر" must be tried before "متوفر".
READING = re.compile(
    rf"(?P<commodity>{_COMMODITY_RE})\s*[^\w\s]*\s*(?P<status>غير\s*متوفر|متوفر)"
)

_AR_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_AR_DIGITS.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})


@dataclass
class Reading:
    station_raw: str
    station_name: str
    locality: str | None
    region: str
    state_kind: str          # fuel_diesel | fuel_gasoline | cooking_gas
    value: str               # available | unavailable
    raw_value: str


@dataclass
class Sweep:
    region: str
    updated_raw: str | None
    updated_at: datetime | None
    readings: list[Reading] = field(default_factory=list)
    unparsed_lines: list[str] = field(default_factory=list)


def parse_stamp(stamp: str | None, year: int | None = None) -> datetime | None:
    """Parse 'آخر تحديث: ٣١‏/٠٧، ١١:٣١ ص' → datetime (naive, channel-local).

    Arabic-Indic digits, an embedded RTL mark, and ص/م for AM/PM. The year is
    absent from the stamp, so the caller supplies it (from the Telegram message
    date) rather than this guessing.
    """
    if not stamp:
        return None
    s = stamp.translate(_AR_DIGITS)
    s = s.replace("‏", "").replace("‎", "")
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})[،,]?\s*(\d{1,2}):(\d{2})\s*(ص|م)?", s)
    if not m:
        return None
    day, month, hour, minute, ampm = m.groups()
    hour = int(hour)
    if ampm == "م" and hour < 12:      # PM
        hour += 12
    elif ampm == "ص" and hour == 12:   # 12 AM
        hour = 0
    try:
        return datetime(year or datetime.now().year, int(month), int(day), hour, int(minute))
    except ValueError:
        return None


def is_fuel_sweep(text: str | None) -> bool:
    return bool(text) and bool(HEADER.search(text))


def parse_message(text: str, msg_year: int | None = None) -> Sweep | None:
    """Parse one region message. Returns None if it is not a fuel sweep."""
    h = HEADER.search(text or "")
    if not h:
        return None
    u = UPDATED.search(text)
    stamp = u.group("stamp") if u else None
    sweep = Sweep(region=h.group("region").strip(),
                  updated_raw=stamp,
                  updated_at=parse_stamp(stamp, msg_year))

    for m in STATION_LINE.finditer(text):
        body = m.group("body").strip()
        # Split station from readings at the LAST colon before the first
        # commodity word — station names themselves can contain punctuation
        # ("محطة التايه . بيتا", "محطة جابر - اسو - البيرة- ش نابلس").
        cut = _split_station(body)
        if not cut:
            sweep.unparsed_lines.append(body)
            continue
        station_raw, rest = cut

        readings = list(READING.finditer(rest))
        if not readings:
            sweep.unparsed_lines.append(body)
            continue

        loc = LOCALITY.search(station_raw)
        locality = loc.group(1).strip() if loc else None
        name = LOCALITY.sub("", station_raw).strip() if loc else station_raw

        for r in readings:
            raw_status = r.group("status")
            # "غير متوفر" CONTAINS "متوفر" — test unavailability first or the
            # answer inverts, and an inverted fuel answer sends someone on a
            # wasted drive during a shortage.
            unavailable = bool(re.match(r"غير\s*متوفر", raw_status))
            sweep.readings.append(Reading(
                station_raw=station_raw,
                station_name=name,
                locality=locality,
                region=sweep.region,
                state_kind=COMMODITY[r.group("commodity")],
                value="unavailable" if unavailable else "available",
                raw_value=" ".join(raw_status.split()),
            ))
    return sweep


def _split_station(body: str) -> tuple[str, str] | None:
    """Return (station_part, readings_part) or None.

    Split on the RIGHTMOST colon whose tail actually parses as readings —
    never on the first commodity word. Station names legitimately contain
    commodity words: "محطة علاء للديزل (دير بلوط)" is Alaa's station *for
    diesel*, and anchoring on the commodity made that line unparseable.
    Rightmost-that-parses also preserves colons inside a station's own name.
    """
    for idx in reversed([i for i, c in enumerate(body) if c == ":"]):
        tail = body[idx + 1:].strip()
        if READING.search(tail):
            head = body[:idx].strip()
            if head:
                return head, tail
    return None


def parse_spool(lines) -> list[Sweep]:
    """Parse teed NDJSON rows (dicts) into sweeps, newest last."""
    import json
    out = []
    for line in lines:
        rec = line if isinstance(line, dict) else json.loads(line)
        if rec.get("channel") != "palhubappfuel" or not rec.get("text"):
            continue
        year = None
        if rec.get("date"):
            try:
                year = datetime.fromisoformat(rec["date"].replace("Z", "+00:00")).year
            except ValueError:
                pass
        s = parse_message(rec["text"], year)
        if s:
            s.msg_id = rec.get("msg_id")          # type: ignore[attr-defined]
            s.msg_date = rec.get("date")          # type: ignore[attr-defined]
            out.append(s)
    return out
