"""Read a palhub fuel-status card out of the image the channel now posts.

    from cascade.fuel_image import ocr_passes, parse_card
    card = parse_card(ocr_passes("card.jpg"), known_stations=[...],
                      known_regions=[...])

WHY THIS EXISTS
@palhubappfuel stopped posting text bulletins at 2026-08-01 09:14 and switched
to rendered images captioned "🔗 التفاصيل والتحديث اللحظي". The 196 stations
that were the largest data source in this system went dark the same hour.

The page behind that caption — palhub.app/fuel-status — is served behind a
Cloudflare challenge: 403 on every attempt, while /road-status returns 200 from
the same client in the same second. It is deliberately closed and is NOT read
here. The images are read instead. They arrive over a channel this account
legitimately subscribes to, and reading what a channel sends you circumvents
nothing.

THE CARD
One card per REGION, roughly 415 a day, rendered from a fixed template:

    حالة محطات الوقود بيت لحم          <- title carries the region
    آخر تحديث: ٠٨/٠٢، ٠٣:٣٩ م          <- SWEEP time, not observation time
    [بنزين] [سولار]  محطة الجزيرة      <- green pills = fuels AVAILABLE
    [بنزين] [سولار]  محطة عبادين  [أزمة متوسطة]
    9 محطة أخرى بلا وقود متوفر حالياً   <- dry stations are COUNTED, not named
    palhub.app/fuel-status

WHAT THE IMAGE WILL NOT TELL US, AND WHY IT MATTERS
Named stations are the ones WITH fuel. The rest are an aggregate count. So the
card carries per-station evidence for `available` and none whatsoever for
`unavailable` — it is biased toward exactly the value P2.4 guards hardest,
because a false "has diesel" spends a tank that could not be spared.

One clean negative survives. When a region has nothing the card says
"لا توجد محطة متوفر فيها وقود حالياً في هذه المدينة", and that covers every
station in the region unambiguously. It is taken. The per-station negative is
NOT inferred by subtraction: Bethlehem's card implies eleven stations where we
hold ten, so "named + dry = all of them" is already known to be wrong
somewhere, and a caution derived from an off-by-one would put "no diesel" on a
station that has it.

TWO OCR PASSES, MERGED — NEITHER MODE IS SUFFICIENT ALONE
Measured on six real cards:

    psm 6  reads titles and the all-dry sentence; MISSED THE PILLS ENTIRELY on
           Hebron and read its dry count as 0 when the card says 30.
    psm 4  reads pills, station names and counts; truncated "بيت لحم" to "ب",
           read "يطا" as "بطأ", and dropped the all-dry sentence on Tubas.

Running one and shipping it would have silently lost availability on some cards
and the region-wide negative on others. So both run and the readings merge.
Merging by UNION is safe here precisely because a missing pill means silence
rather than "unavailable" — a pass that sees nothing can only fail to add, it
can never subtract a fact the other pass found.

NAMES ARE MATCHED, NOT READ
Rather than trust the glyphs, the region is resolved first and station names
are matched against the stations we already hold FOR THAT REGION — a candidate
set of two to thirty, not an open vocabulary. Hebron's psm-6 pass produced
"حطة السلام", missing the mim; against the region's own list that is obvious,
and as free text it is a different station.

STALENESS IS UNMEASURED AND THIS IS QUARANTINE-ONLY OUTPUT
Every card in a sweep carries the same "آخر تحديث", so it is the render time and
says nothing about when any station was observed. That is exactly what made the
palhub ROAD bulletin unusable — median age 24 hours behind a timestamp that
looked live (P6.1). Nothing here may be written as `assertion` until it has been
measured against the overlap window on 2026-08-01, when the channel posted text
AND images for nine hours and the two can be compared directly.
"""
from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass, field

# Both modes run on every card. See the module docstring: each one loses
# something the other keeps, and which one loses depends on the card.
PSM_MODES = (6, 4)
OCR_TIMEOUT_SECONDS = 30

# ── vocabulary, written in FOLDED form ───────────────────────────────────────
# Every pattern below is matched against _fold() output, so it must itself be
# folded: ة->ه, أ/إ/آ->ا, ى->ي. Writing them the way the card renders them and
# matching them against folded text is a silent no-match, and it is silent in
# the direction that loses data rather than inventing it — which is why the
# first version of this file passed a smoke test and found nothing.

TITLE = re.compile(r"حاله\s+محطات\s+الوقود\s*(.*)$")
IS_CARD = re.compile(r"حاله\s+محطات\s+الوقود|محطه\s+اخري\s+بلا\s+وقود")

# Presence of the token IS the claim. A fuel that is unavailable has no pill at
# all, so absence is silence and never a negative.
FUELS = {"بنزين": "fuel_gasoline", "سولار": "fuel_diesel", "ديزل": "fuel_diesel"}

# "There is no station with fuel available currently in this city."
# Deliberately loose: Dura's OCR came back "لااكزجد ضعطة متزفر فيها وقود:خاليآ"
# — four substitutions and a stray colon. If this stops matching, the region
# quietly stops reporting "nobody has fuel", which reads as no-news rather than
# no-fuel, so the pattern is tuned to over-match on this phrase specifically.
# The trailing anchor is bare "مدين", not "المدينه": Dura's OCR turned the
# article into a double lam ("للمدينة"), and requiring a specific article threw
# the whole sentence away. The negation at the front plus a fuel word plus the
# word "city" is specific enough — no other line on these cards contains it.
NONE_AVAILABLE = re.compile(
    r"(?:لا\s*ت?[وؤ]?جد|لااكزجد).{0,40}?(?:وقود|بنزين|سولار).{0,25}?مدين")

# NOTE the ي: _fold maps ى -> ي, so a pattern written the way the card
# renders it ("أخرى") can never match its own folded output. That mistake
# cost every dry count and, on Hebron, the whole psm-4 pass — which was the
# only pass that saw the pills.
OTHERS_DRY = re.compile(r"(\d+)\s*محطه\s+اخري\s+بلا\s+وقود")

# The orange badge. Same family as the road bulletin's congestion levels and
# graded the same way: this is the QUEUE, not whether fuel exists.
CRISIS = {"ازمه خانقه": "severe", "ازمه شديده": "severe",
          "ازمه متوسطه": "moderate", "ازمه خفيفه": "light"}

NOISE = re.compile(r"palhub|fuel-?status|اخر\s+تحديث|اخر\s+تعديث|اخر\s+تديث", re.I)

_BIDI = dict.fromkeys([0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D,
                       0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0x200B, 0x200D])
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ARTEFACT = re.compile(r"[|‘’`~^:.،؛]+")


def _fold(s: str) -> str:
    """Normalise for MATCHING only — never for storage.

    Arabic writes the same name several ways: alef with and without hamza,
    ta-marbuta against ha, ya against alef-maqsura. `محطة` and `محطه` are the
    same word and OCR picks whichever the render happened to resemble.
    """
    s = unicodedata.normalize("NFKC", (s or "").translate(_BIDI))
    s = s.translate(_AR_DIGITS)
    s = _ARTEFACT.sub(" ", s)
    s = re.sub(r"[ً-ْٰـ]", "", s)   # harakat, tatweel
    s = (s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
           .replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و")
           .replace("ئ", "ي"))
    return re.sub(r"\s+", " ", s).strip()


def _bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def _similar(a: str, b: str) -> float:
    """Dice coefficient over character bigrams.

    Chosen over edit distance because OCR on Arabic drops and doubles marks
    rather than transposing: `محطة عبادين` arriving as `حطة عبادين` is one
    deletion, and four of five bigrams still match.
    """
    A, B = _bigrams(a), _bigrams(b)
    return 2 * len(A & B) / (len(A) + len(B)) if (A and B) else 0.0


# Below this a name is reported unmatched rather than guessed. On the six-card
# sample every true match scored >= 0.80 and the best WRONG match within the
# same region scored 0.52, so 0.70 sits in a wide gap. It also correctly
# REJECTS psm-4's truncations: "ب" against "بيت لحم" scores 0.0 and "بطا"
# against "يطا" scores 0.5, both of which the other pass gets right.
MATCH_FLOOR = 0.70


@dataclass
class StationReading:
    name_raw: str
    name_matched: str | None = None
    match_score: float = 0.0
    fuels: dict = field(default_factory=dict)     # state_kind -> 'available'
    crisis: str | None = None


@dataclass
class FuelCard:
    is_card: bool = False
    region_raw: str | None = None
    region_matched: str | None = None
    stations: list = field(default_factory=list)
    region_all_dry: bool = False        # the clean, attributable negative
    others_dry: int | None = None       # context only — never a station verdict
    unmatched: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def ocr_passes(image_path: str) -> list[str]:
    """Run tesseract once per segmentation mode. A failing mode is not fatal."""
    out = []
    for psm in PSM_MODES:
        try:
            r = subprocess.run(
                ["tesseract", str(image_path), "-", "-l", "ara", "--psm", str(psm)],
                capture_output=True, text=True, timeout=OCR_TIMEOUT_SECONDS)
            if r.stdout.strip():
                out.append(r.stdout)
        except (OSError, subprocess.SubprocessError):
            continue
    return out


def _parse_one(text: str, candidates: list[tuple[str, str]],
               regions: list[tuple[str, str]]) -> FuelCard:
    card = FuelCard()
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not any(IS_CARD.search(_fold(ln)) for ln in lines):
        return card
    card.is_card = True

    for raw in lines:
        folded = _fold(raw)
        if not folded or NOISE.search(folded):
            continue

        if card.region_raw is None:
            m = TITLE.search(folded)
            if m:
                # The corner logo bleeds glyphs onto the title line ("ليا بر
                # حالة محطات..."), always BEFORE the phrase, so anchoring on the
                # phrase rather than the line start drops them.
                region = m.group(1).strip()
                if region:
                    card.region_raw = region
                    if regions:
                        best, score = max(((r, _similar(region, f))
                                           for r, f in regions),
                                          key=lambda t: t[1])
                        if score >= MATCH_FLOOR:
                            card.region_matched = best
                continue

        if NONE_AVAILABLE.search(folded):
            card.region_all_dry = True
            continue

        m = OTHERS_DRY.search(folded)
        if m:
            card.others_dry = int(m.group(1))
            continue

        fuels = {kind: "available" for tok, kind in FUELS.items()
                 if tok in folded}
        crisis = next((lvl for tok, lvl in CRISIS.items() if tok in folded), None)
        if not fuels and not crisis:
            continue

        name = folded
        for tok in list(FUELS) + list(CRISIS):
            name = name.replace(tok, " ")
        name = re.sub(r"\b\d+\b", " ", name)
        # psm 4 leaves a lone artefact letter where it could not resolve a pill
        # ("د محطة الجزيرة"); a one-character token is never part of a name.
        name = " ".join(w for w in name.split() if len(w) > 1)
        if len(name) < 3:
            card.notes.append(f"row with pills but no name: {raw[:60]!r}")
            continue

        r = StationReading(name_raw=name, fuels=fuels, crisis=crisis)
        if candidates:
            best, score = max(((s, _similar(name, f)) for s, f in candidates),
                              key=lambda t: t[1])
            if score >= MATCH_FLOOR:
                r.name_matched, r.match_score = best, round(score, 3)
            else:
                r.match_score = round(score, 3)
                card.unmatched.append(name)
        card.stations.append(r)
    return card


def parse_card(ocr_text: str | list[str],
               known_stations: list[str] | None = None,
               known_regions: list[str] | None = None) -> FuelCard:
    """Parse one card, merging every OCR pass it was given.

    `known_stations` should be the stations we hold for this region. Without it
    every name comes back unmatched, because a name read off a card and not
    tied to a row in `place` is not evidence about anywhere.
    """
    texts = [ocr_text] if isinstance(ocr_text, str) else list(ocr_text)
    candidates = [(s, _fold(s)) for s in (known_stations or [])]
    regions = [(r, _fold(r)) for r in (known_regions or [])]

    parsed = [_parse_one(t, candidates, regions) for t in texts]
    parsed = [p for p in parsed if p.is_card]
    if not parsed:
        return FuelCard()

    merged = FuelCard(is_card=True)
    for p in parsed:
        merged.notes.extend(p.notes)
        # Prefer a region that MATCHED a known one; psm 4 truncates titles and
        # would otherwise win on ordering alone.
        if p.region_matched and not merged.region_matched:
            merged.region_matched, merged.region_raw = p.region_matched, p.region_raw
        elif p.region_raw and not merged.region_raw:
            merged.region_raw = p.region_raw
        merged.region_all_dry = merged.region_all_dry or p.region_all_dry
        if p.others_dry is not None:
            # Hebron: psm 6 read 0, psm 4 read 30 against a card saying 30. The
            # count drives no assertion, so take the larger and record that they
            # disagreed rather than silently picking one.
            if merged.others_dry is not None and merged.others_dry != p.others_dry:
                merged.notes.append(
                    f"OCR passes disagree on dry count: "
                    f"{merged.others_dry} vs {p.others_dry}")
            merged.others_dry = max(merged.others_dry or 0, p.others_dry)

    # Union the stations, keyed on the station we matched — or on the raw text
    # when nothing matched, so two passes reading the same unknown name do not
    # become two stations.
    by_key: dict[str, StationReading] = {}
    for p in parsed:
        for s in p.stations:
            key = s.name_matched or s.name_raw
            cur = by_key.get(key)
            if cur is None:
                by_key[key] = s
                continue
            cur.fuels.update(s.fuels)              # union: a pass can only add
            cur.crisis = cur.crisis or s.crisis
            if s.match_score > cur.match_score:
                cur.name_matched, cur.match_score = s.name_matched, s.match_score
                cur.name_raw = s.name_raw
    merged.stations = list(by_key.values())
    merged.unmatched = sorted({u for p in parsed for u in p.unmatched}
                              - {s.name_raw for s in merged.stations
                                 if s.name_matched})

    # A card that says the region is empty AND names a station with fuel is
    # self-contradictory. Trusting either half means picking one at random.
    if merged.region_all_dry and any(s.fuels for s in merged.stations):
        merged.notes.append("CONTRADICTION: 'no station has fuel' alongside "
                            "stations with pills — card discarded")
        merged.region_all_dry = False
        merged.stations = []
    return merged
