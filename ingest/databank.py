"""T2.3 — the databank migration loader.

Reads a reviewed mapping spec from db/mappings/<category>.yaml and executes
it: bronze the v1 files, transform every record through a per-category
transformer that implements the spec, resolve places, and write
`observation` rows idempotently (044's unique index on v1_stable_id).

The spec is the contract; the transformer is its implementation; the run
report is the proof. Refusals are structural:
  - no spec, spec not `status: reviewed`, or `migrate: false`  → refuse
  - a record whose source name is not in the spec's by_name    → run FAILS
  - fewer records than expect.min_records                      → run FAILS
  - resolution below the spec's floors                         → run FAILS
  - a drop reason not declared in the spec                     → run FAILS
Nothing is silently skipped: every record lands in exactly one bucket of the
run report (written, deduped, dropped-by-reason, failed).

Run:  .venv/bin/python -m ingest.databank <category> [--dry-run]
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ingest import bronze, engine
from ingest.spec import SpecInvalid, SpecRefused, validate_or_raise
from resolve.db import connect
from resolve.db import v1_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "db" / "mappings"
V1_UNIFIED = v1_path("public/data/unified")  # READ-ONLY
RUNS = ROOT / "ops" / "databank-runs.ndjson"


# ── spec loading ─────────────────────────────────────────────────────────────

def load_spec(category: str) -> dict:
    p = SPECS / f"{category}.yaml"
    if not p.exists():
        raise SpecRefused(f"no spec for {category!r}")
    spec = yaml.safe_load(p.read_text())
    # Format v2 is a registry now (ingest/spec.py), and the loader refuses a
    # spec that does not conform BEFORE it reads a single record. An unknown
    # key, a value of the wrong shape, or a key no code implements all stop
    # the run here. Three keys were declared-and-dead when this was written —
    # place.min_resolved_pct in 20 specs, source_routing.default in 21, the
    # latlon rung of place.fallback in 4 — and the only reason anyone found
    # out is that someone went looking. Now the machine looks, every run.
    validate_or_raise(spec, category)
    if spec.get("status") != "reviewed":
        raise SpecRefused(f"{category}: status={spec.get('status')!r}, not reviewed")
    if spec.get("migrate") is False:
        raise SpecRefused(f"{category}: migrate=false ({spec.get('skip_reason')})")

    # A migrating spec MUST declare how a row is identified and how many rows
    # are too many. Both were optional until 2026-08-07, and the eleven specs
    # that declared neither are exactly the ones that doubled overnight when
    # v1 re-hashed its corpus. Optional guards protect the datasets that
    # happened to be remembered.
    if not (spec.get("identity") or any(
            (d.get("overrides") or {}).get("identity")
            for d in spec.get("datasets", []))):
        raise SpecRefused(
            f"{category}: no `identity:` — declare what makes a row THIS row "
            "(per dataset via datasets[].overrides.identity where one key "
            "cannot describe them all), or v1 re-hashing its ids silently "
            "re-inserts the whole corpus")
    if not (spec.get("expect") or {}).get("max_observations"):
        raise SpecRefused(
            f"{category}: no `expect.max_observations` — the tripwire that "
            "catches an identity too FINE (a revision read as a new fact). "
            "Set it at ~1.15x the measured emission.")
    return spec


def _instant(v) -> str | None:
    """One spelling of a moment, whatever type it arrives as.

    `occurred_at_exact` renders the instant rather than the day, and the two
    callers of identity_key_for hand it two different types: the loader passes
    the transformer's ISO string '2026-07-24T12:25:00.000Z', and the backfill
    passes a datetime read back from Postgres, whose str() is
    '2026-07-24 12:25:00+00:00'. Same moment, different text, so the guard
    compared a key against itself and lost — 998 IODA rows re-inserted on
    2026-08-08 as a brand-new generation.

    This is the SAME failure the docstring below already describes for numbers
    (106.0 against 106), in a field nobody had keyed on until connectivity's
    outages needed sub-day resolution. One renderer means one rendering, and
    a renderer that trusts str() of whatever it is given is not one.
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    s = str(v)
    if len(s) == 10:                 # a plain date, already unambiguous
        return s
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s                     # not a timestamp we recognise; verbatim
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def content_of(*, value_num, value_text, unit, place_id, attrs) -> str:
    """What a row SAYS, as one comparable string. Identity is what a row is.

    The pair is what makes "corrections supersede" implementable. Identity
    alone can only answer "do we already hold this?", and answering yes made
    the loader skip a publisher's CORRECTION as if it were a re-fetch: OONI
    revised eight days' measurement counts upward and the databank kept the
    old numbers, silently, while reporting a clean run.

    Rendered here rather than in SQL, and from the same normalisation on both
    sides, for the reason identity_key_for's docstring gives: `value_num` is a
    double, so Python's repr and numeric::text disagree, and a fingerprint
    that disagrees with itself turns every row into a false revision — which
    would supersede and re-insert the whole databank in one night.
    """
    return json.dumps({
        "v": None if value_num is None else float(value_num),
        "t": value_text, "u": unit,
        "p": None if place_id is None else int(place_id),
        "a": attrs or {},
    }, sort_keys=True, ensure_ascii=False, default=str)


def identity_key_for(ident: dict, dataset_key: str, *, indicator, occurred_at,
                     place_id, value_num, attrs) -> str:
    """The ONE renderer for a row's declared identity.

    Both the loader (on a Row it just built) and the backfill (on a row read
    back from the database) call this. That is the whole point: the first
    version of the guard compared a Python-rendered key against a SQL-rendered
    one, and 106.0 != 106 made it fail OPEN — re-inserting rows it already
    held, which is the doubling it existed to prevent (measured: 998 of 1,000
    connectivity rows). One function, one rendering, no second opinion.
    """
    parts = [dataset_key]
    for f in ident.get("fields", []):
        # value_num is a DOUBLE in the database, so a stored key always spells
        # it as a float — while a fresh key renders whatever JSON parsed,
        # which is int 333 where the column reads back 333.0. str() of those
        # differ, the guard compares a key against itself and loses, and 044's
        # stable-id conflict masked it right up until v1 re-hashed: health
        # then read 2,487 integral values as brand-new identities. Third
        # spelling of the same bug this docstring already names twice.
        v = {"indicator": indicator,
             "occurred_at": str(occurred_at)[:10],
             "occurred_at_exact": _instant(occurred_at),
             "place_id": place_id,
             "value_num": None if value_num is None
             else float(value_num)}[f]
        parts.append("" if v is None else str(v))
    for a in ident.get("attrs", []):
        v = (attrs or {}).get(a)
        parts.append("" if v is None else str(v))
    return "|".join(parts)


def read_payload(f: Path) -> bytes:
    """A frozen corpus is gzipped; a v1 file is not. One reader for both.

    Stage 7 freezes finished categories into data/frozen/<cat>.json.gz — 92 MB
    of aid_access becomes 2.5 MB, which is the difference between a corpus
    this repository can carry and one only its author can reach.
    """
    b = f.read_bytes()
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


def _input_files(inp: dict) -> list[Path]:
    root = Path(inp["root"])
    if not root.is_absolute():
        root = ROOT / root
    # `glob:` may be a list. A publisher's own API is not one file per
    # category the way v1's unified tree was — T4P publishes the named
    # roster and the cumulative summary at two endpoints, and the spec
    # that reads them should name both rather than sweep a directory and
    # hope. Order is the spec's, not the filesystem's.
    globs = inp["glob"]
    out = []
    for g in ([globs] if isinstance(globs, str) else globs):
        out += [f for f in sorted(root.glob(g))
                if f.name not in ("index.json", "recent.json")]
    return out


def reads_fallback(spec: dict | None) -> bool:
    """True when the spec's primary input is absent and its declared
    `input.fallback` is what a run would read (a fresh clone that has never
    run the fetcher)."""
    inp = (spec or {}).get("input") or {}
    return bool(inp.get("fallback")) and not _input_files(inp)


def iter_v1_files(category: str, spec: dict | None = None):
    # Format v2 `input:` — a spec may read a v1 RAW tree instead of the
    # unified category (first user: conflict_westbank, whose cumulative
    # fields v1's unified transform destroys), or a FROZEN corpus in this
    # repository (Stage 7). Relative roots resolve against the repo, so a
    # frozen spec works from any working directory and on any machine.
    if spec and spec.get("input"):
        files = _input_files(spec["input"])
        # `input.fallback` (P1-B.3): a category whose live fetch replaced a
        # frozen corpus keeps the corpus as the answer for a machine that has
        # never fetched — so a fresh clone still loads, and the run says so.
        if not files and spec["input"].get("fallback"):
            files = _input_files(spec["input"]["fallback"])
            print(f"{category}: no fetched input under {spec['input']['root']} "
                  f"— reading the fallback {spec['input']['fallback']['glob']} "
                  "(additive only)", file=sys.stderr)
        yield from files
        return
    d = V1_UNIFIED / category
    if (d / "all-data.json").exists():
        yield d / "all-data.json"
        return
    for f in sorted((d / "partitions").glob("*.json")):
        if f.name != "index.json":
            yield f


def _records(payload, spec: dict | None = None):
    if isinstance(payload, list):
        return payload
    for key in ("data", "records"):
        if isinstance(payload.get(key), list):
            return payload[key]
    # `input.object_as_record` — a document that IS one record. T4P's
    # /v3/summary.json is a single JSON object holding one cumulative
    # snapshot; without this it reads as zero records and the summary row
    # disappears silently, which is precisely the class of failure the floors
    # exist to catch one layer later. Declared, never guessed: every other
    # payload keeps returning [] so a genuinely empty file stays empty.
    if payload and ((spec or {}).get("input") or {}).get("object_as_record"):
        return [payload]
    return []


# ── row model ────────────────────────────────────────────────────────────────

@dataclass
class Row:
    dataset_key: str
    indicator: str
    occurred_at: str            # ISO date/timestamp
    precision: str              # exact|hour|day|month|year|unknown
    v1_stable_id: str
    value_num: float | None = None
    value_text: str | None = None
    unit: str | None = None
    place_id: int | None = None
    located: bool = False       # point/locality/governorate-grade resolution
    reported_at: str | None = None
    raw_ref: str | None = None
    identity_key: str | None = None     # 052: the declared natural key
    attrs: dict = field(default_factory=dict)


@dataclass
class EventRow:
    dataset_key: str            # provenance only — event has no dataset FK
    event_type: str
    occurred_at: str
    precision: str
    v1_stable_id: str
    place_id: int | None = None
    lat: float | None = None
    lon: float | None = None
    located: bool = False
    confidence: float = 0.7
    independent_sources: int = 1
    metrics: dict = field(default_factory=dict)
    raw_ref: str | None = None
    attrs: dict = field(default_factory=dict)


@dataclass
class Drop:
    reason: str


@dataclass
class HeldEvent:
    """A current event row, as much of it as `decide_event_reading` compares."""
    event_id: int
    status: str
    note: str | None
    event_type: str
    day: str
    precision: str
    lat: float | None
    lon: float | None
    metrics: dict
    attrs: dict
    place_id: int | None = None


def event_content(event_type, day, precision, lat, lon, metrics, attrs,
                  rule: dict, held_attrs: dict | None = None) -> dict:
    """What an event STATES, for telling a publisher's revision from a re-fetch.

    The place row is not in it: which place a point falls in is this store's
    reading, and it moves when the gazetteer does. `content_attrs` are always
    compared. `content_attrs_when.attrs` are compared only against a held row
    that carries the marker attr (`held_has`): the 7,638 UCDP events loaded
    from v1's file never had UCDP's precision codes, and gaining a field is
    not the publisher changing its mind."""
    def pt(v):
        return None if v is None else round(float(v), 5)
    keys = list(rule.get("content_attrs") or [])
    when = rule.get("content_attrs_when") or {}
    basis = attrs if held_attrs is None else held_attrs
    if when and when.get("held_has") in (basis or {}):
        keys += list(when.get("attrs") or [])
    return {"type": event_type, "day": str(day)[:10], "precision": str(precision),
            "lat": pt(lat), "lon": pt(lon),
            "metrics": {k: v for k, v in (metrics or {}).items() if v not in (None, 0)},
            "attrs": {k: (attrs or {}).get(k) for k in keys}}


def decide_event_reading(held: dict, emitted: list, rule: dict) -> dict:
    """One dataset's events against the publisher's whole current reading.

    held     stable id -> HeldEvent (every current row, whatever its status)
    emitted  the EventRows of the reading, one per stable id

    new         an id the store does not hold
    revised     held and believed, and it now states something else: the held
                row takes the new reading (the old version goes to
                event_history through the versioning trigger)
    reinstated  an event this rule withdrew, published again
    withdrawn   held and believed, and no longer in the reading: marked
                `retracted`, kept, not served
    Anything held under another status (a duplicate retired by hand) is left
    exactly as it is."""
    label = rule["label"]
    out = {"new": [], "revised": [], "reinstated": [], "withdrawn": [],
           "same": 0, "left_as_held": 0}
    seen = set()
    for e in emitted:
        seen.add(e.v1_stable_id)
        h = held.get(e.v1_stable_id)
        if h is None:
            out["new"].append(e)
            continue
        if h.status == "retracted" and (h.note or "").startswith(label):
            out["reinstated"].append((h, e))
            continue
        if h.status != "believed":
            out["left_as_held"] += 1
            continue
        was = event_content(h.event_type, h.day, h.precision, h.lat, h.lon,
                            h.metrics, h.attrs, rule)
        now = event_content(e.event_type, e.occurred_at, e.precision, e.lat, e.lon,
                            e.metrics, e.attrs, rule, held_attrs=h.attrs)
        if was == now:
            out["same"] += 1
            continue
        changed = sorted([k for k in ("type", "day", "precision", "lat", "lon", "metrics")
                          if was[k] != now[k]]
                         + [k for k in now["attrs"] if was["attrs"].get(k) != now["attrs"][k]])
        out["revised"].append((h, e, changed))
    out["withdrawn"] = [h for sid, h in held.items()
                        if h.status == "believed" and sid not in seen]
    return out


def event_readings(spec: dict, category: str, from_fallback: bool = False,
                   root: Path | None = None) -> tuple[dict, dict]:
    """(dataset -> its `event_reading` rule, dataset -> the files of the reading)
    for the readings in force this run: every file of one is on disk. None of
    them on disk (a machine that has never fetched) or a fallback input: the
    rule sleeps and the dataset loads as it always did. Some of them: refused,
    because half a reading would retract every event of the missing half."""
    rules: dict[str, dict] = {}
    files_of: dict[str, set] = {}
    for rule in (spec.get("event_reading") or []):
        base = root or Path((spec.get("input") or {}).get("root", "data"))
        if not base.is_absolute():
            base = ROOT / base
        files = {base / f for f in rule["files"]}
        there = {f for f in files if f.exists()}
        if there and there != files:
            raise SpecRefused(
                f"{category}: {rule['dataset']} declares its publisher's reading as "
                f"{len(files)} files and {len(files - there)} of them are missing "
                f"({', '.join(sorted(f.name for f in files - there))}) — half a reading "
                "would retract every event of the missing part; nothing is read")
        if there and not from_fallback:
            rules[rule["dataset"]] = rule
            files_of[rule["dataset"]] = files
    return rules, files_of


def revised_event_place(h: HeldEvent, e, changed: list | None) -> int | None:
    """The place row a revised event is left with. The place is this store's
    reading of the point, so a revision that did not move the point does not
    move the place: 8 of GED 26.1's 812 revised events would have lost theirs
    (the Rafah crossing, Jerusalem city), because v1 had placed them by its
    own gazetteer and the release's record carries only the point, which falls
    outside every polygon. A point that moved is resolved again."""
    moved = changed is not None and ("lat" in changed or "lon" in changed)
    if moved:
        return e.place_id
    return h.place_id if h.place_id is not None else e.place_id


def revised_event_attrs(h: HeldEvent, e, rule: dict) -> dict:
    """The attrs a revised event is left with: what this store added to the
    held row stays (its enrichment marks), what the publisher says now wins,
    and a compared field the publisher no longer gives is gone."""
    attrs = {**(h.attrs or {}), **(e.attrs or {})}
    compared = list(rule.get("content_attrs") or []) + list(
        (rule.get("content_attrs_when") or {}).get("attrs") or [])
    for k in compared:
        if k not in (e.attrs or {}):
            attrs.pop(k, None)
    if "raw_lat" in attrs or "raw_lon" in attrs:
        attrs["raw_lat"], attrs["raw_lon"] = e.lat, e.lon
    attrs["v1_stable_id"] = e.v1_stable_id
    attrs["dataset_key"] = e.dataset_key
    if e.raw_ref:
        attrs["raw_ref"] = e.raw_ref
    return attrs


class PointResolver:
    """lat/lon → governorate place_id by containment (T2.3 prerequisite —
    resolve/geo.py is text-only). Cached per run; rounding to ~11 m."""

    def __init__(self, conn):
        self.conn = conn
        self.cache: dict = {}

    def resolve(self, lat, lon) -> int | None:
        if lat is None or lon is None:
            return None
        key = (round(float(lat), 4), round(float(lon), 4))
        if key not in self.cache:
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT place_id FROM place
                       WHERE kind = 'governorate' AND merged_into IS NULL
                         AND ST_Contains(geom::geometry,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                       LIMIT 1""", (key[1], key[0]))
                row = cur.fetchone()
            self.cache[key] = row[0] if row else None
        return self.cache[key]


def slug(s: str) -> str:
    """Global loader convention: lowercase, runs of non-alnum → '_'."""
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


# ── place maps (loaded once per run, keyed on names not ids) ────────────────

def load_places(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT place_id, kind, name_en, admin2_pcode
                       FROM place WHERE merged_into IS NULL
                         AND kind IN ('region', 'governorate', 'crossing')""")
        rows = cur.fetchall()
    by_name = {(k, n): pid for pid, k, n, _ in rows}
    by_pcode = {pc: pid for pid, k, n, pc in rows if k == "governorate" and pc}
    return {
        "region": {n: pid for (k, n), pid in by_name.items() if k == "region"},
        "governorate": {n: pid for (k, n), pid in by_name.items()
                        if k == "governorate"},
        "crossing": {n: pid for (k, n), pid in by_name.items()
                     if k == "crossing"},
        "pcode": by_pcode,
    }


# ── mojibake repair (README loader convention) ──────────────────────────────
# v1 double-encoded Arabic: UTF-8 bytes read as cp1252. The round trip
# restores it exactly; anything that does not round-trip cleanly passes
# through unchanged and is NOT counted as repaired.

_ARABIC = re.compile(r"[؀-ۿ]")


def demojibake(s, counts: Counter):
    if not isinstance(s, str) or _ARABIC.search(s):
        return s
    try:
        fixed = s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    if _ARABIC.search(fixed):
        counts["mojibake_repaired"] += 1
        return fixed
    return s


def region_place(places: dict, region: str, attrs: dict) -> tuple[int | None, bool]:
    """README's region rules. Returns (place_id, located)."""
    if region == "Gaza Strip":
        return places["region"]["Gaza Strip"], False
    if region == "West Bank":
        return places["region"]["West Bank"], False
    if region == "East Jerusalem":
        attrs["region"] = "East Jerusalem"
        return places["governorate"]["Jerusalem"], True
    attrs["region"] = region        # 'Palestine' and friends → honest NULL
    return None, False


# The publisher's own governorate NAME, as a rung (DATABANK-03, 2026-09-26).
# OCHA names the governorate on every demolition locality; it is the
# publisher's admin assignment, which is why it outranks point-in-polygon at a
# border (measured on the 526 fetched localities: 496 agree, 3 disagree —
# Umm al-'Asafir, Ein el Qilt, Wadi Qana, all on a governorate line). Spelling
# variants seen in the wild map onto our place names; an unknown spelling
# falls through to the next rung, never to a guess.
GOVERNORATE_SPELLINGS = {
    "qalqiliya": "Qalqilya", "qalqilyah": "Qalqilya", "tulkarem": "Tulkarm",
    "tulkarim": "Tulkarm", "ramallah and al bireh": "Ramallah",
    "ramallah al bireh": "Ramallah", "ramallah and al bira": "Ramallah",
    "jericho and al aghwar": "Jericho",
    "khan yunis": "Khan Younis", "deir al balah": "Deir Al-Balah",
    "al quds": "Jerusalem", "east jerusalem": "Jerusalem",
}


def governorate_by_name(places: dict, name) -> int | None:
    if not name or not isinstance(name, str):
        return None
    gov = places["governorate"]
    if name in gov:
        return gov[name]
    key = re.sub(r"[^a-z]+", " ", name.lower()).strip()
    for ours, pid in gov.items():
        if re.sub(r"[^a-z]+", " ", ours.lower()).strip() == key:
            return pid
    alias = GOVERNORATE_SPELLINGS.get(key)
    return gov.get(alias) if alias else None


def place_ladder(loc: dict, spec: dict, places: dict, attrs: dict,
                 counts: Counter, *, ds_key: str | None = None,
                 event_type: str | None = None,
                 default_region: str | None = None) -> tuple[int | None, bool]:
    """`place.strategy` + `place.fallback`, executed rung by rung.

    THE FIRST CONSTRUCT THE SPEC ACTUALLY DRIVES. Until 2026-08-08 the ladder
    was prose: education and infrastructure both declared
    `fallback: [latlon, region]`, and both transformers went pcode → region,
    skipping the middle rung entirely. That was invisible while v1 supplied
    pcodes. Then v1's rebuild dropped `location.admin2_pcode` from all 2,359
    education and all 3,537 infrastructure records — measured 2026-08-08, the
    same regression that took the demolition and historical gazetteer keys —
    and 5,881 rows fell to region grade while holding a perfectly good lat/lon.
    The floor that existed to catch it (`min_resolved_pct`) was read by
    nothing. Three dead keys in a row is not bad luck; it is what happens when
    a document is allowed to describe behaviour no code performs.

    Returns (place_id, located). `located` means point/locality/governorate
    grade — a region row is a true answer, not a located one.
    """
    place_spec = spec.get("place", {})
    if ds_key:
        place_spec = {**place_spec, **(_ds_over(spec, ds_key, "place") or {})}
    rungs = [place_spec.get("strategy")]
    fb = place_spec.get("fallback")
    rungs += (fb if isinstance(fb, list) else [fb] if fb else [])
    # `latlon_exclude` names event types whose lat/lon are fabricated —
    # barrier segments carry PROJECTED METRES, not degrees. A hard safety rule
    # (README Format v2), and the reason the rung is skipped rather than the
    # record dropped: the row is fine, only that one field is a lie.
    excluded = event_type in (place_spec.get("latlon_exclude") or [])

    # The source's own region label is data. region_place() preserves the
    # informative ones in attrs ('East Jerusalem', 'Palestine', 'Israel') —
    # but only when the region rung is the one that fires. A ladder that
    # resolves finer would otherwise DELETE the label as a side effect of
    # doing better, which is a strange way to improve. Measured harmless for
    # education and infrastructure (their regions are only the two plain
    # ones); recorded here so it stays harmless as the ladder spreads.
    label = loc.get("region")
    if label and label not in ("Gaza Strip", "West Bank"):
        attrs.setdefault("region", label)

    for rung in [r for r in rungs if r]:
        if rung in ("pcode", "admin2_pcode"):
            pid = places["pcode"].get(loc.get("admin2_pcode"))
            if pid is not None:
                counts["place_rung:pcode"] += 1
                return pid, True
        elif rung == "governorate":
            pid = governorate_by_name(places, loc.get("governorate"))
            if pid is not None:
                counts["place_rung:governorate"] += 1
                return pid, True
        elif rung == "latlon":
            if excluded:
                counts["place_rung:latlon_excluded"] += 1
                continue
            pid = places["_pip"].resolve(loc.get("lat"), loc.get("lon"))
            if pid is not None:
                counts["place_rung:latlon"] += 1
                return pid, True
        elif rung == "region":
            region = loc.get("region") or default_region
            if region:
                counts["place_rung:region"] += 1
                return region_place(places, region, attrs)
        elif rung == "none":
            return None, False
    counts["place_rung:exhausted"] += 1
    return None, False


def route(rec: dict, spec: dict, counts: Counter) -> str | None:
    """sources[0].name → dataset key via the spec's by_name. None = unroutable."""
    sources = rec.get("sources") or []
    name = sources[0].get("name") if sources and isinstance(sources[0], dict) else None
    routing = spec["source_routing"]
    by_name = routing["by_name"]
    if name is None and routing.get("default"):
        # `source_routing.default` — declared in 21 reviewed specs and read by
        # nothing until 2026-08-08. Its absence was not neutral: a record with
        # sources: [] routed to None, which FAILS the whole run. Twenty-one
        # documents promised a graceful path that did not exist.
        counts["routed_by_default"] += 1
        src_key = routing["default"]
    elif name not in by_name or by_name[name] is None:
        counts[f"unroutable:{name}"] += 1
        return None
    else:
        src_key = by_name[name]
    for ds in spec["datasets"]:
        if ds["source"] == src_key:
            return ds["key"]
    counts[f"no_dataset_for_source:{src_key}"] += 1
    return None


def moved(rec: dict, spec: dict) -> str | None:
    """Format v2 `source_routing.moved` (P1-B.3): the spec that reads this
    record's source now, or None. A moved record is a declared, counted drop
    in the spec it left — never an unroutable name that fails the run."""
    sources = rec.get("sources") or []
    name = sources[0].get("name") if sources and isinstance(sources[0], dict) else None
    return ((spec.get("source_routing") or {}).get("moved") or {}).get(name)


def passthrough(rec: dict, spec_list: list, base: dict | None = None) -> dict:
    """attrs_passthrough: dotted paths, absent/empty values omitted."""
    out = dict(base or {})
    for path in spec_list or []:
        cur = rec
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, "", [], {}):
            out[path.split(".")[-1]] = cur
    return out


# ── per-category transformers (each implements its reviewed spec) ────────────

def t_prisoners(rec, spec, places, counts):
    if moved(rec, spec):
        return Drop("moved")
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    metric = rec.get("prisoner_metric_type")
    day = str(rec.get("date"))[:10]
    # spec: 890/890 dates are the 1st of a month; month precision, month start.
    if not day or day[8:10] != "01":
        counts["date_not_month_start"] += 1
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    attrs["reference"] = "period-end stock"     # REVIEW.md decision 2
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    return [Row(dataset_key=ds, indicator=f"prisoners.{slug(metric)}",
                occurred_at=day, precision="month",
                v1_stable_id=rec["stable_id"],
                value_num=rec["metrics"]["count"], unit="persons",
                place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


# The frozen corpora (data/frozen/, v1's 2026-08-05 file) carry no span of
# their own: their cross-sections ran to the day v1 fetched them, and their
# 2026 row was a partial year. ops/fetch_ocha.py writes both facts into each
# record — the date of the latest record inside the row, and whether the year
# is still running — so a live row states its own span (P1-B.3).
FROZEN_COVERAGE_END = "2026-08-05"


def _partial_year(rec: dict, year: str) -> bool:
    if "partial_year" in rec:
        return bool(rec["partial_year"])
    return year == FROZEN_COVERAGE_END[:4]


def t_casualties(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    dim = rec.get("casualty_dimension")
    label = rec.get("casualty_breakdown_label")
    indicator = f"casualties.{slug(dim)}" + (f".{slug(label)}" if label else "")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    date = rec.get("date")
    if dim == "annual_total" and date:
        year = str(date)[:4]
        occurred, precision = f"{year}-01-01", "year"            # law 2
        if _partial_year(rec, year):
            attrs["partial_year"] = True                          # spec note
    else:
        occurred, precision = "2008-01-01", "unknown"             # series start
        attrs["coverage_start"] = "2008-01-01"
        attrs["coverage_end"] = rec.get("coverage_end") or FROZEN_COVERAGE_END
    loc = rec.get("location") or {}
    if dim == "governorate":
        gov = loc.get("governorate")
        # OCHA's spelling vs the gazetteer's: the one measured divergence.
        gov = {"Qalqiliya": "Qalqilya"}.get(gov, gov)
        pid = places["governorate"].get(gov)
        if pid is not None:
            place_id, located = pid, True
        elif gov in ("Israel", "Not listed"):
            attrs["breakdown_place"] = gov                        # honest NULL
            place_id, located = None, False
        else:
            counts[f"governorate_unresolved:{gov}"] += 1          # counted FAILURE
            place_id, located = None, False
    else:
        place_id, located = region_place(places, loc.get("region"), attrs)
    return [Row(dataset_key=ds, indicator=indicator,
                occurred_at=occurred, precision=precision,
                v1_stable_id=rec["stable_id"],
                value_num=rec["metrics"]["killed"], unit="fatalities",
                place_id=place_id, located=located, attrs=attrs)]


def t_demolitions(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    dim = rec.get("demolition_dimension")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    date = rec.get("date")
    if dim == "annual_total" and date:
        year = str(date)[:4]
        occurred, precision = f"{year}-01-01", "year"             # law 2
        attrs["coverage_area"] = "West Bank + East Jerusalem"     # spec note
        if _partial_year(rec, year):
            attrs["partial_year"] = True
    else:
        occurred, precision = "2009-01-01", "unknown"             # series start
        attrs["coverage_start"] = "2009-01-01"
        attrs["coverage_end"] = rec.get("coverage_end") or FROZEN_COVERAGE_END
    loc = rec.get("location") or {}
    if (rec.get("demolition_dimension") or "") == "locality":
        # THE FIX-FIRST NOTE, discharged (2026-08-07). The locality name was
        # in the source all along (location.name, 511 distinct of 516) and
        # this transformer dropped it, leaving these rows with no identity
        # but a governorate — which is why 828 of them collided and why the
        # dataset was frozen holding a superseded generation. governorate
        # rides along because five names repeat across governorates.
        attrs["locality_name"] = loc.get("name")
        attrs["governorate"] = loc.get("governorate")
    # DATABANK-03 (2026-09-26): this went pcode → region, so once v1 dropped
    # admin2_pcode (2026-08-08) and v2's own OCHA fetch carried none, every
    # locality — Jabal al Mukabbir's 416 structures, Burqa, Tatrit — was
    # filed under "West Bank" while holding its governorate and a point. The
    # spec's declared ladder now runs: pcode → OCHA's governorate name →
    # point-in-polygon → region. The point itself rides in attrs (observation
    # rows have no geometry), so a caller can map a locality.
    if dim == "locality":
        if loc.get("lat") is not None and loc.get("lon") is not None:
            attrs["lat"], attrs["lon"] = loc["lat"], loc["lon"]
        place_id, located = place_ladder(loc, spec, places, attrs, counts,
                                         ds_key=ds)
        if not located:
            counts["locality_resolution_miss"] += 1               # Al Malha
    else:
        place_id, located = region_place(places, loc.get("region"), attrs)
    m = rec.get("metrics") or {}
    sid = rec["stable_id"]
    rows = []
    # fan_out per the reviewed spec; suffixed stable ids per emitted row (044)
    if m.get("demolished") is not None:
        rows.append(Row(ds, f"demolitions.{slug(dim)}.structures", occurred,
                        precision, f"{sid}:structures",
                        value_num=m["demolished"], unit="structures",
                        place_id=place_id, located=located, attrs=attrs))
    if (m.get("displaced") or 0) > 0:
        rows.append(Row(ds, f"demolitions.{slug(dim)}.displaced", occurred,
                        precision, f"{sid}:displaced",
                        value_num=m["displaced"], unit="persons",
                        place_id=place_id, located=located, attrs=attrs))
    if (m.get("affected") or 0) > 0:
        rows.append(Row(ds, f"demolitions.{slug(dim)}.affected", occurred,
                        precision, f"{sid}:affected",
                        value_num=m["affected"], unit="persons",
                        place_id=place_id, located=located, attrs=attrs))
    return rows


def t_settlements(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    year = str(rec["date"])[:4]                                   # 100% -12-31
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    attrs["reference"] = "period-end stock"                       # REVIEW.md 2
    attrs["coverage"] = "West Bank, excludes East Jerusalem"      # spec caveat
    return [Row(ds, "settlements.settler_population", f"{year}-01-01", "year",
                rec["stable_id"], value_num=rec["metrics"]["count"],
                unit="settlers", place_id=places["region"]["West Bank"],
                attrs=attrs)]


# What v1's code wrote on every row of a kind without any publisher saying it
# (found by reading v1's fetchers against the publishers' files, 2026-10-12).
# A barrier segment "requires permits", every settlement is "Authorized", every
# demolition is a residential, privately owned, administratively demolished
# single structure with notice given: constants, served as facts. They are no
# longer carried. A record still arrives with them (the fetchers reproduce v1's
# record shape so held rows match); the next load supersedes each held row with
# one that says only what the publisher says.
_LAND_V1_DEFAULTS = {
    "checkpoint": ("permits_required", "operational_status"),
    "settlement": ("land_status", "legal_status", "settlement_type"),
    "demolition": ("land_status", "structure_type", "structures_demolished", "reason",
                   "notification_given", "owner_type"),
}


def t_land(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    etype = rec.get("event_type")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    for k in _LAND_V1_DEFAULTS.get(etype, ()):
        attrs.pop(k, None)
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    if etype == "demolition":
        # the one honest date in the category: demolition.demolition_date
        occurred = str((rec.get("demolition") or {}).get("demolition_date")
                       or rec["date"])[:10]
        precision = "day"
    else:
        occurred, precision = str(rec["date"])[:10], "unknown"    # law 1
    region = rec["location"]["region"]
    if ds == "v1_land_goodshepherd" and region == "Palestine":
        # v1's default. The collective's own page: "This data only represents
        # information from UN OCHA, which focuses on the West Bank and East
        # Jerusalem".
        region = "West Bank"
        attrs["coverage_area"] = "West Bank and East Jerusalem"
    place_id, located = region_place(places, region, attrs)
    m = rec.get("metrics") or {}
    # the barrier's status is the file's own (Constructed / Under Construction /
    # Projected); a settlement's "Authorized" was v1's constant
    status = rec.get("land_status") if etype == "checkpoint" else None
    return [Row(ds, f"land.{slug(etype)}", occurred, precision,
                rec["stable_id"], value_num=m.get("count"),
                value_text=status, unit=m.get("unit"),
                place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def t_culture(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    return [Row(ds, f"culture.heritage_site.{slug(rec['site_type'])}",
                str(rec["date"])[:10], "unknown",                 # law 1: 100%
                rec["stable_id"], value_num=rec["metrics"]["count"],
                value_text=rec.get("site_status"), unit="sites",
                place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def t_education(rec, spec, places, counts, _as_v1: bool = False):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = {k: demojibake(v, counts)
             for k, v in passthrough(rec, spec.get("attrs_passthrough")).items()}
    # "Active" and "Unknown" on all 2,359 rows are v1's constants: the
    # publisher's file has no status and no type column (found 2026-10-12).
    # A 2015 register cannot say a school is active today.
    if not _as_v1:
        attrs.pop("school_status", None)
        attrs.pop("school_type", None)
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    loc = rec.get("location") or {}
    # pcode → latlon → region, as the spec has always said. 'West Bank' is the
    # declared floor: location.region is 'West Bank' on 2,359/2,359.
    place_id, located = place_ladder(loc, spec, places, attrs, counts,
                                     default_region="West Bank")
    return [Row(ds, "education.school_record", str(rec["date"])[:10],
                "unknown",                                        # law 1: 100%
                rec["stable_id"], value_num=1,
                value_text=rec.get("school_status") if _as_v1 else None, unit="schools",
                place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def t_education_v1(rec, spec, places, counts):
    """The rows as they were written until 2026-10-12, v1's two constants
    included: what the as-of replay must reproduce for days before that."""
    return t_education(rec, spec, places, counts, _as_v1=True)


def t_connectivity_v2(rec, spec, places, counts):
    """OONI's daily anomaly rate and IODA's outages, from their own APIs.

    Replaces t_connectivity, which read v1's unified connectivity file. That
    file mixed both upstreams and v1 stopped updating the OONI half on
    2026-06-09 — gap_radar has been printing a sixty-day freshness alert
    against a seven-day allowance ever since, so this cut is the only way the
    series continues at all.

    ROUTING IS BY SHAPE, NOT BY NAME. A raw file has no `sources[]` block —
    v1 stamped that on during its own transform — and this category is the one
    that holds two publishers, so `source_routing.default` cannot pick between
    them. The two records are unmistakable: an IODA outage carries a
    datasource, an OONI day carries a measurement count. Anything else is a
    drop, loudly, rather than a guess.
    """
    if rec.get("outage_datasource"):                              # IODA
        counts["routed_by_shape:ioda"] += 1
        attrs = {"code": rec["entity_code"], "type": rec["entity_type"],
                 "unit": "seconds", "count": 0,
                 "severity_score": rec.get("severity_score"),
                 "outage_datasource": rec["outage_datasource"]}
        place_id, located = region_place(places, rec["region"], attrs)
        return [Row("v1_connectivity_ioda", "connectivity.internet_outage",
                    str(rec["outage_start"]), "hour",
                    # v1's `id`, which was already deterministic and built
                    # from IODA's own key — the good half of v1's identity.
                    # Its `stable_id` was a content hash and re-minted itself
                    # whenever IODA revised a score, which is the 2026-08-07
                    # generation-doubling bug in miniature.
                    rec["id"], value_num=rec.get("duration_seconds"),
                    place_id=place_id, located=located, attrs=attrs)]

    if rec.get("measurement_count"):                              # OONI
        counts["routed_by_shape:ooni"] += 1
        attrs = {"unit": "measurements", "count": rec["measurement_count"],
                 "anomaly_count": rec["anomaly_count"],
                 "confirmed_blocked": rec["confirmed_count"]}
        # region 'Palestine' → place_id NULL + attrs.region, which is the
        # honest answer for a country-wide measurement.
        place_id, located = region_place(places, "Palestine", attrs)
        return [Row("v1_connectivity_ooni",
                    "connectivity.censorship_measurement",
                    str(rec["date"])[:10], "day", rec["id"],
                    value_num=rec.get("anomaly_rate"),
                    place_id=place_id, located=located, attrs=attrs)]

    return Drop("unrecognised_shape")


def t_connectivity(rec, spec, places, counts):
    """v1's shape, kept for REPLAY ONLY — see t_martyrs_v1 for why."""
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    m = rec.get("metrics") or {}
    if rec.get("outage_start"):                                   # IODA
        occurred, precision = str(rec["outage_start"]), "hour"
        value = m.get("duration_seconds")
    else:                                                         # OONI
        occurred, precision = str(rec["date"])[:10], "day"
        value = rec.get("anomaly_rate", m.get("value"))
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    return [Row(ds, f"connectivity.{slug(rec['event_type'])}", occurred,
                precision, rec["stable_id"], value_num=value,
                place_id=place_id, located=located, attrs=attrs)]


def t_funding(rec, spec, places, counts):
    """NOT what runs: funding is spec-driven (`TRANSFORMERS["funding"]` is
    t_engine) and this is its hand-written twin, kept in step with the spec's
    template: the record's series (`parked_parent` for a parked parent with
    nothing left on it, ops/fetch_fts.py), else its status."""
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    f = rec.get("funding") or {}
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    return [Row(ds, f"funding.{slug(f.get('series') or f['status'])}", str(rec["date"])[:10],
                "day", rec["stable_id"], value_num=f.get("amount_usd"),
                unit="USD", place_id=place_id, located=located, attrs=attrs)]


def t_pcbs(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    year = str(rec["date"])[:4]                                   # 100% -01-01
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    return [Row(ds, f"pcbs.{slug(rec['indicator_code'])}", f"{year}-01-01",
                "year", rec["stable_id"], value_num=rec["metrics"]["value"],
                unit=rec["metrics"].get("unit"),
                place_id=place_id, located=located, attrs=attrs)]


def t_economic(rec, spec, places, counts):
    if moved(rec, spec):
        return Drop("moved")
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    key = (ds, rec.get("indicator_code"), str(rec.get("date"))[:10],
           (rec.get("location") or {}).get("region"))
    if key in t_economic.dup_keys:                                # REVIEW.md 4
        return Drop("contradictory_duplicate")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    year = str(rec["date"])[:4]              # -01-01 kept, -12-31 truncated:
    place_id, located = region_place(places, rec["location"]["region"], attrs)
    unit = rec["metrics"].get("unit")
    if ds == "v1_economic_imf" and unit == "number":
        # v1 stamped the literal 'number' on every IMF row (474 of 474: GDP in
        # billions of dollars, inflation in percent, an index alike), so the
        # unit was nulled here. ops/fetch_imf.py writes the IMF's own unit
        # (2026-10-12) and that one is carried; v1's placeholder, which only
        # the frozen fallback still holds, stays null.
        unit = None
    return [Row(ds, f"economic.{slug(rec['indicator_code'])}", f"{year}-01-01",
                "year", rec["stable_id"], value_num=rec["metrics"]["value"],
                unit=unit, place_id=place_id, located=located, attrs=attrs)]


def _economic_prepass(records, spec, counts):
    seen, dups = set(), set()
    for rec in records:
        key = ("v1_economic_pcbs_direct" if "pcbs.gov.ps"
               in str((rec.get("sources") or [{}])[0].get("url")) else "",
               rec.get("indicator_code"), str(rec.get("date"))[:10],
               (rec.get("location") or {}).get("region"))
        if key[0]:
            if key in seen:
                dups.add(key)
            seen.add(key)
    t_economic.dup_keys = {k for k in dups}


t_economic.prepass = _economic_prepass
t_economic.dup_keys = set()


def t_health_v1(rec, spec, places, counts):
    """v1's health record (WHO's HDX export through v1's unified tree), as it
    was loaded until 2026-10-12. Kept for REPLAY only: it is the transformer
    that produced the 12,502 rows the first GHO run closes. It reads ONE
    dimension per record (HDX's export kept one), which is the defect."""
    if not rec.get("indicator_code"):
        return Drop("no_indicator_identity")
    dim = (rec.get("dimension") or {}).get("code")
    indicator = f"health.{slug(rec['indicator_code'])}" + \
                (f".{slug(dim)}" if dim else "")                  # null-brace
    attrs = passthrough(rec, ["indicator_code", "indicator_name",
                              "dimension.type", "dimension.code",
                              "dimension.name", "value_low", "value_high"])
    year = str(rec["date"])[:4]                                   # 100% -01-01
    attrs["region"] = "Palestine"
    return [Row("v1_health_who", indicator, f"{year}-01-01", "year",
                rec["stable_id"], value_num=rec["metrics"]["value"],
                unit=rec["metrics"].get("unit"), attrs=attrs)]


# ── health — WHO GHO's own rows, every dimension kept (2026-10-12) ───────────
# Input: data/raw/gho/health_pse.json (ops/fetch_gho_health.py), one record per
# GHO OData row for SpatialDim PSE, the publisher's fields verbatim.

# What a GHO indicator NAME states about its unit. Ordered, first match wins.
# The unit is decided once per indicator and never from a value: v1 looked at
# each number ("between 0 and 100 and not whole → a percentage") and so wrote
# 'percentage' on the deaths from lung cancer and 'number' on the total beside
# them. A name that states nothing gets NO unit here; health.yaml's
# `value.unit_by_code` then decides from WHO's own indicator metadata, or
# declares that nothing can be said.
_GHO_UNIT_RULES = (
    (r"per 100 ?000\b", "per_100000"),
    (r"per 10 ?000\b", "per_10000"),
    (r"per 1 ?000\b", "per_1000"),
    (r"per 100 live births", "per_100"),
    (r"US\$ millions", "USD_millions"),
    (r"per capita in US\$", "USD_per_capita"),
    (r"\((in )?thousands\)", "thousand_persons"),   # every such name counts people
    (r"\(g/100 ?ml\)", "g_per_100ml"),
    (r"\(years\)", "years"),
    (r"%|\bpercentage\b", "percent"),
    (r"\b(sub-)?index\b", "index"),
    (r"\bnumber of\b.*\bdeaths\b", "persons"),
    (r"\bnumber of\b.*\bcases\b", "cases"),
    (r"\(number\)", "count"),
)


def gho_unit_from_name(name) -> str | None:
    """The unit WHO's indicator name states, or None when it states none."""
    if not name:
        return None
    n = re.sub(r"\s+", " ", str(name))     # \s covers the no-break spaces too
    for pattern, unit in _GHO_UNIT_RULES:
        if re.search(pattern, n, re.I):
            return unit
    return None


def gho_dims(rec: dict) -> list[tuple[str, str, str | None]]:
    """A GHO row's dimensions as [(type, code, label)], in the publisher's own
    slot order (Dim1, Dim2, Dim3). A row with none is the indicator's total."""
    out = []
    for i in (1, 2, 3):
        kind, code = rec.get(f"Dim{i}Type"), rec.get(f"Dim{i}")
        if kind and code:
            out.append((str(kind), str(code), rec.get(f"Dim{i}Label")))
    return out


def gho_dim_key(rec: dict) -> str:
    """The dimensions as ONE string, for the identity and the stable id:
    'SEX=SEX_FMLE;AGEGROUP=AGEGROUP_YEARS15-19', '' for a row with none. A
    string, not the dict: a dict's rendering depends on its key order, and
    jsonb does not keep ours."""
    return ";".join(f"{t}={c}" for t, c, _ in gho_dims(rec))


def gho_stable_id(rec: dict) -> str:
    """gho:<code>:<year>:<dimensions> — the publisher's own key for a row
    (measured 2026-10-12: unique on all 13,975 PSE rows of the 184 codes)."""
    return f"gho:{rec.get('IndicatorCode')}:{rec.get('TimeDim')}:{gho_dim_key(rec)}"


def t_health(rec, spec, places, counts):
    code, year = rec.get("IndicatorCode"), rec.get("TimeDim")
    if not code or not isinstance(year, int):
        return Drop("missing_identity")
    value = rec.get("NumericValue")
    if value is None:
        # WHO gave no number: a tobacco-control answer in words ("Yes", "No",
        # "ILS"), a placeholder ("—", ". . ."), or nothing at all. Not parsed
        # into one — "2006" under NumericValue null is a year of adoption, not
        # a measurement. The row stays in the raw file and in bronze.
        return Drop("no_numeric_value")
    updated = rec.get("Date")
    if updated and year > int(str(updated)[:4]):
        # dated after the day WHO last wrote it: a projection (the tobacco
        # trend estimates' 2030 point), not a measurement. Judged on the row's
        # own date, never on today's, so the same file always loads the same.
        return Drop("projection_after_publication")
    dims = gho_dims(rec)
    indicator = "health." + ".".join(slug(x) for x in [code] + [c for _, c, _ in dims])
    name = rec.get("indicator_name")
    by_code = (spec.get("value") or {}).get("unit_by_code") or {}
    unit = by_code[code] if code in by_code else gho_unit_from_name(name)
    attrs = {"region": "Palestine", "indicator_code": code,
             "dim": {t: c for t, c, _ in dims},
             "dim_label": {t: lab for t, _, lab in dims if lab},
             "dim_key": gho_dim_key(rec)}
    if name:
        attrs["indicator_name"] = name
    for ours, theirs in (("value_low", "Low"), ("value_high", "High")):
        if rec.get(theirs) is not None:
            attrs[ours] = rec[theirs]
    period = rec.get("TimeDimensionValue")
    if period and str(period) != str(year):
        attrs["period"] = str(period)          # '2017-2019': WHO files it under 2019
    if rec.get("DataSourceDim"):
        attrs["data_source"] = rec["DataSourceDim"]
    return [Row("v1_health_who", indicator, f"{year}-01-01", "year",
                gho_stable_id(rec), value_num=value, unit=unit, place_id=None,
                reported_at=updated, attrs=attrs)]


_FOOD_GOV = {"Ramallah and Albireh": "Ramallah", "Kan Younis": "Khan Younis"}


def t_food(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    day = str(rec["date"])[:10]                                   # 100% the 15th
    occurred = day[:8] + "01"                                     # month start
    loc = rec.get("location") or {}
    market = loc.get("name")
    if market in ("West Bank", "Gaza Strip"):                     # REVIEW.md 8
        place_id, located = region_place(places, market, attrs)
        attrs["basket"] = "region-wide"
    else:
        gov = _FOOD_GOV.get(loc.get("governorate"), loc.get("governorate"))
        pid = places["governorate"].get(gov)
        if pid is None:
            counts[f"governorate_unresolved:{gov}"] += 1
            place_id, located = None, False
        else:
            place_id, located = pid, True
    return [Row(ds, f"food.price.{slug(rec['commodity'])}", occurred, "month",
                rec["stable_id"], value_num=rec["metrics"]["price"],
                unit=rec["metrics"].get("unit"),
                place_id=place_id, located=located, attrs=attrs)]


_UNIT_CANON = {"truck": "truck", "trucks": "truck", "ton": "tonne",
               "mt": "tonne", "pallets": "pallet", "piece": "piece",
               "each": "piece", "ctn": "box", "box": "box",
               "vehicles": "vehicle", "tents": "tent"}
_CROSSINGS = {"Kerem Shalom": "Kerem Shalom Crossing",
              "Rafah Crossing": "Rafah Crossing",
              "Erez": "Erez Crossing (Beit Hanoun)",
              "Kissufim": "Kissufim Crossing",
              # Verified 2026-08-05: OCHA SitUpdate #326 equates the names —
              # "the Zikim crossing (Erez West/As Siafa)". UNRWA's dashboard
              # calls the same northern corridor 'Western Erez'.
              "Western Erez": "Zikim Crossing"}
# Gate 96 stays on the region row deliberately: it is a military gate on the
# Netzarim corridor serving CENTRAL Gaza — not a border terminal, and not in
# any crossings dictionary. JLOTS (the dismantled pier) likewise.


def t_aid_access(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    day = str(rec["date"])[:10]
    if day > "2024-05-05":
        attrs["upstream_partial"] = True          # source disclaimer, derived
    raw_unit = (rec.get("metrics") or {}).get("unit")
    unit = _UNIT_CANON.get(str(raw_unit).lower(), raw_unit)
    if unit != raw_unit:
        attrs["unit_raw"] = raw_unit
    crossing = rec.get("crossing")
    name_en = _CROSSINGS.get(crossing)
    if name_en:
        place_id, located = places["crossing"][name_en], True
    else:                                          # Western Erez / Gate 96 / JLOTS
        place_id, located = places["region"]["Gaza Strip"], False
    return [Row(ds, f"aid_access.consignment.{slug(rec['cargo_category'])}",
                day, "day", rec["stable_id"],
                value_num=(rec.get("metrics") or {}).get("quantity"),
                unit=unit, place_id=place_id, located=located, attrs=attrs)]


def t_martyrs_v1(rec, spec, places, counts):
    """v1's shape, kept for REPLAY ONLY — never registered in TRANSFORMERS.

    martyrs_snapshot_2023 was cut from v1 on 2026-08-08 and now reads T4P's
    own endpoints. But the evidence vault holds 38 days of v1-SHAPED snapshots,
    and ops/asof_harness.py proves the databank's sys_period against them by
    re-transforming what v1 served that day. Deleting this function would not
    change one stored row; it would destroy the ability to prove those rows
    were right — the cut must change what we read tomorrow without erasing how
    we check yesterday.
    """
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    if rec.get("event_type") == "cumulative_summary":
        return [Row(ds, "martyrs.cumulative_summary", str(rec["date"])[:10],
                    "day", rec["stable_id"],
                    value_num=rec["metrics"]["killed"], unit="persons",
                    attrs=attrs)]
    place_id, located = region_place(places,
                                     rec["location"]["region"], attrs)
    return [Row(ds, "martyrs.identified_killed", "2023-10-07", "unknown",
                rec["stable_id"], value_num=rec["metrics"]["killed"],
                value_text=rec.get("name"), unit="persons",
                place_id=place_id, located=located, attrs=attrs)]


# T4P publishes sex as a one-letter code; v1 spelled it out, and 72,835 rows
# in the databank already say 'male'/'female'. Same fact, and changing the
# spelling now would leave the stored rows saying one thing and the spec
# another — the identity guard means those rows can never be rewritten.
_T4P_SEX = {"m": "male", "f": "female"}


def t_martyrs_t4p(rec, spec, places, counts):
    """The named roster and the cumulative summary, from T4P's own endpoints.

    Replaces t_martyrs, which read v1's `martyrs_snapshot_2023` unified file.
    That file was measured (2026-08-08) to be a PURE RELABEL of T4P's
    killed-in-gaza.json — all 72,835 records matched by t4p_id with zero
    differences in name, name_ar, name_en, age, dob or killed. Every field
    below is that relabel, reproduced, so the cut moves no data:

        raw            v1 / here
        id          →  t4p_id, and the row's stable id
        en_name     →  value_text, name_en
        name        →  name_ar
        sex m|f     →  male|female
        age, dob    →  verbatim
        (constant)  →  metrics.killed 1, region 'Gaza Strip', 2023-10-07

    THE RAW `source` FIELD IS DELIBERATELY NOT CARRIED. T4P marks each record
    with a provenance letter; measured today it is 'u' on all 72,835, and v1
    replaced it with the constant string 'tech4palestine'. Adding the real
    letter would change attrs on 72,835 rows the identity guard can never
    rewrite, so the stored corpus would disagree with the spec. If that letter
    ever becomes informative it needs a deliberate supersede pass, not a quiet
    attribute.
    """
    ds = route(rec, spec, counts)          # no sources[] in a raw file →
    if ds is None:                         #   source_routing.default
        return Drop("unroutable")

    if "known_killed_in_gaza" in rec:      # /v3/summary.json, one object
        g, wb = rec.get("gaza") or {}, rec.get("west_bank") or {}
        gk, wk = g.get("killed") or {}, wb.get("killed") or {}
        day = str(g.get("last_update") or "")[:10]
        if not day or gk.get("total") is None:
            return Drop("summary_incomplete")
        attrs = {"event_type": "cumulative_summary", "cumulative": {
            "gaza": {
                "killed": gk.get("total"), "children": gk.get("children"),
                "women": gk.get("women"), "press": gk.get("press"),
                "medical": gk.get("medical"),
                "civil_defence": gk.get("civil_defence"),
                "injured": (g.get("injured") or {}).get("total"),
                "massacres": g.get("massacres"),
                # famine{} and aid_seeker{} are published EMPTY today. 0 would
                # assert 'measured zero'; null says 'not published', which is
                # the truth and is what law 6's spirit requires of a gap.
                "famine_total": (g.get("famine") or {}).get("total"),
                "famine_children": (g.get("famine") or {}).get("children"),
                "aid_seekers_killed": (g.get("aid_seeker") or {}).get("killed"),
                "aid_seekers_injured": (g.get("aid_seeker") or {}).get("injured"),
            },
            "west_bank": {
                "killed": wk.get("total"), "children": wk.get("children"),
                "injured": (wb.get("injured") or {}).get("total"),
                "injured_children": (wb.get("injured") or {}).get("children"),
                "settler_attacks": wb.get("settler_attacks"),
            },
            "identified_in_gaza_database":
                (rec.get("known_killed_in_gaza") or {}).get("records"),
            "press_identified":
                (rec.get("known_press_killed_in_gaza") or {}).get("records"),
            # T4P's own two dates for the roster, which v1 never carried and
            # which are the honest answer to 'how current is this list':
            # last_update is when T4P refreshed it, includes_until is how far
            # the MoH's identification had reached.
            "roster_last_update":
                (rec.get("known_killed_in_gaza") or {}).get("last_update"),
            "roster_includes_until":
                (rec.get("known_killed_in_gaza") or {}).get("includes_until"),
        }}
        return [Row(ds, "martyrs.cumulative_summary", day, "day",
                    f"t4p:summary:{day}",
                    value_num=(gk.get("total") or 0) + (wk.get("total") or 0),
                    unit="persons", attrs=attrs)]

    t4p_id = rec.get("id")
    if t4p_id in (None, ""):
        return Drop("no_t4p_id")           # identity is t4p_id; without it
    name_en = rec.get("en_name")           #   there is no row
    attrs = {"t4p_id": str(t4p_id), "event_type": "identified_killed",
             "t4p_source_marker": "tech4palestine"}
    for k, v in (("name_ar", rec.get("name")), ("name_en", name_en),
                 ("age", rec.get("age")),
                 ("sex", _T4P_SEX.get(rec.get("sex"), rec.get("sex"))),
                 ("dob", rec.get("dob"))):
        if v not in (None, "", [], {}):    # same omit-empty rule as
            attrs[k] = v                   #   passthrough(), so attrs match
    place_id, located = region_place(places, "Gaza Strip", attrs)
    return [Row(ds, "martyrs.identified_killed", "2023-10-07", "unknown",
                # A DETERMINISTIC id, not a content hash. v1's stable_id was
                # re-derived from the record's bytes, so a corrected age
                # minted a new id and re-inserted the person — the 2026-08-07
                # generation doubling. This one is the publisher's own key.
                f"t4p:killed_in_gaza:{t4p_id}", value_num=1,
                value_text=name_en, unit="persons",
                place_id=place_id, located=located, attrs=attrs)]


def t_infrastructure(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    etype = rec.get("event_type")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    m = rec.get("metrics") or {}
    loc = rec.get("location") or {}
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    detail = rec.get("infrastructure_detail") or {}
    if etype == "infrastructure_damage":
        indicator = f"infrastructure.damage.{slug(detail.get('type'))}"
        value, occurred, precision = m.get("count"), str(rec["date"])[:10], "day"
    elif etype == "satellite_damage_assessment":
        indicator = "infrastructure.satellite_damage_assessment"
        value = m.get("structures_total_affected")
        occurred, precision = str(rec["date"])[:10], "day"
    else:                                       # locality_record / barrier_segment
        indicator = f"infrastructure.{slug(etype)}"
        value = m.get("count")
        occurred, precision = str(rec["date"])[:10], "unknown"    # law 1: 100%
        # What v1 wrote and no publisher said (found 2026-10-12): every barrier
        # segment is "1 km" (the file's own lengths sum to 711.9 km over 261
        # segments) and every village boundary is "1 persons" named "Unknown
        # Locality" (the file names all 342). The fetcher carries the
        # publisher's length and name beside v1's shape; they are used here.
        if etype == "barrier_segment" and rec.get("shape_length_m") is not None:
            value = round(float(rec["shape_length_m"]) / 1000, 3)
        if etype == "locality_record":
            m = {**m, "unit": "localities"}
            if rec.get("village_name"):
                attrs["locality_name"] = rec["village_name"]
            attrs.pop("locality_type", None)        # "Village" on every row: v1's constant
        # The 603 HDX registers name every row "Unknown Locality" or
        # "Separation Barrier Segment": the source carries NO usable name, so
        # the only thing that makes a row THIS row is where it is. Measured
        # 603/603 distinct. Discarding it (as this transformer did until
        # 2026-08-07) left the dataset with no identity at all — and the
        # identity guard then froze it at 2 keys.
        if loc.get("lat") is not None and loc.get("lon") is not None:
            attrs["geo_key"] = f"{loc['lat']:.6f},{loc['lon']:.6f}"
    # pcode → latlon → region. barrier_segment lat/lon are projected metres,
    # not degrees (place.latlon_exclude), so that rung is skipped for them and
    # only for them — the record is sound, one field is not.
    place_id, located = place_ladder(
        loc, spec, places, attrs, counts, event_type=etype,
        default_region=("West Bank" if etype in ("barrier_segment",
                                                 "locality_record")
                        else "Gaza Strip"))
    return [Row(ds, indicator, occurred, precision, rec["stable_id"],
                value_num=value, value_text=detail.get("damage_level"),
                unit=m.get("unit"), place_id=place_id, located=located,
                reported_at=fetched, attrs=attrs)]


def t_engine(rec, spec, places, counts):
    """The spec-driven transformer — no category knowledge, none possible.

    A category using this one has `transform: engine` in its spec, and every
    decision it makes is a key a reviewer can read. What it CANNOT express, it
    refuses at build time rather than improvising at row time: see
    engine.EngineRefused.

    Migrating a category here is gated on ops/spec_equivalence.py proving the
    emitted tuples identical, field by field, over every record. The point is
    not that the engine is nicer; it is that the document becomes true.
    """
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")

    for d in spec.get("drop") or []:
        when = d.get("when")
        if when and engine.check(when, rec):
            return Drop(d["reason"])

    attrs = passthrough(rec, _ds_over(spec, ds, "attrs_passthrough",
                                      default=spec.get("attrs_passthrough")))
    # Constants the spec ASSERTS about every row of a dataset — a stock's
    # reference point, a coverage caveat. These were hardcoded in the
    # transformers, which is exactly the wrong place for a sentence like
    # 'West Bank, excludes East Jerusalem': it is a claim about the data that
    # a reader of the spec deserves to see and a reviewer deserves to check.
    for k, v in ((spec.get("attrs_literal") or {}) |
                 (_ds_over(spec, ds, "attrs_literal") or {})).items():
        attrs[k] = v
    for k in list(attrs):
        attrs[k] = demojibake(attrs[k], counts)

    oa = {**(spec.get("occurred_at") or {}),
          **(_ds_over(spec, ds, "occurred_at") or {})}
    occurred, precision, reported = engine.resolve_date(oa, rec, attrs)

    ind = {**(spec.get("indicator") or {}),
           **(_ds_over(spec, ds, "indicator") or {})}
    indicator = engine.render(ind["template"], rec, slug)

    val = {**(spec.get("value") or {}), **(_ds_over(spec, ds, "value") or {})}
    place_id, located = place_ladder(rec.get("location") or {}, spec, places,
                                     attrs, counts, ds_key=ds,
                                     event_type=rec.get("event_type"))

    stable = get_in(rec, spec.get("stable_id", "stable_id"))
    return [Row(ds, indicator, occurred, precision, stable,
                value_num=engine.first_non_null(rec, val.get("num_from")),
                value_text=engine.first_non_null(rec, val.get("text_from")),
                unit=engine.resolve_unit(val, rec),
                place_id=place_id, located=located,
                reported_at=reported if oa.get("keep_reported_at") else None,
                attrs=attrs)]


def get_in(rec, path):
    return engine.get_path(rec, path)


def _ds_over(spec, ds_key, *path, default=None):
    """datasets[].overrides lookup: _ds_over(spec, key, 'attrs_passthrough')."""
    for ds in spec["datasets"]:
        if ds["key"] == ds_key:
            cur = ds.get("overrides", {})
            for p in path:
                cur = cur.get(p, {}) if isinstance(cur, dict) else {}
            return cur or default
    return default


def t_conflict(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    etype = slug(rec.get("event_type"))
    loc = rec.get("location") or {}
    m = rec.get("metrics") or {}
    sources = rec.get("sources") or []

    # declared, measured, counted drops (spec drop blocks)
    if etype == "daily_casualty_report" and loc.get("region") == "West Bank":
        return Drop("v1_placeholder_all_metrics_zero")
    if sources and sources[0].get("name") == "Good Shepherd":
        return Drop("v1_placeholder_no_payload")

    # strictest-license-wins assertion for multi-source rows (REVIEW.md 7),
    # skipping declared provenance-only credits — a citation is not a
    # licence conflict (spec `provenance_only`, added 2026-08-07)
    if len(sources) > 1:
        by_name = spec["source_routing"]["by_name"]
        prov_only = set(spec.get("provenance_only") or [])
        routed_commercial = places["_commercial"].get(by_name.get(
            sources[0].get("name")))
        for s in sources[1:]:
            key = by_name.get(s.get("name"))
            if key in prov_only:
                counts["provenance_credit"] += 1
                continue
            other = places["_commercial"].get(key)
            if routed_commercial is True and other is False:
                counts["license_order_violation"] += 1

    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    if len(sources) > 1:
        attrs["provenance"] = [
            {"name": s.get("name"), "url": s.get("url")} for s in sources[1:]]

    # shape override: the cumulative Gaza series is a time series
    if etype in ("daily_casualty_report", "summary"):
        attrs["cumulative"] = True
        day = str(rec["date"])[:10]
        sid = rec["stable_id"]
        # THE REGION COMES FROM THE RECORD, not from a constant. Until
        # 2026-08-08 this branch hardcoded the Gaza indicator and the Gaza
        # place row for every daily report, and the spec's drop rule removes
        # only the all-zero West Bank ones — so four real West Bank figures
        # (killed 1,086 and 1,108; injured 11,132 and 11,399) were stored
        # inside the Gaza cumulative series, where the Gaza figure is 73,382.
        #
        # Found by building v_flow, which is exactly what conflict.yaml
        # predicted: the series read 73,381 → 1,108 → 73,382 and the first
        # difference came out as 72,274 killed in a single day. The same
        # arithmetic that produced this spec's famous ~35-million-dead
        # artifact, in miniature and for the same reason.
        region = (loc.get("region") or "Gaza Strip")
        slug_region = "westbank" if region == "West Bank" else "gaza"
        place_id = places["region"].get(region, places["region"]["Gaza Strip"])
        if region not in ("Gaza Strip", "West Bank"):
            counts[f"cumulative_unexpected_region:{region}"] += 1
        rows = [Row(ds, f"conflict.{slug_region}_cumulative_killed", day, "day",
                    f"{sid}:killed", value_num=m.get("killed"),
                    unit="persons", place_id=place_id, attrs=attrs)]
        if (m.get("injured") or 0) > 0:
            rows.append(Row(ds, f"conflict.{slug_region}_cumulative_injured",
                            day, "day", f"{sid}:injured",
                            value_num=m.get("injured"),
                            unit="persons", place_id=place_id, attrs=attrs))
        return rows

    # events
    if rec.get("date_precision"):                      # POM villages, verbatim
        precision = rec["date_precision"]
        if precision == "day" and str(rec.get("date") or "")[8:10] == "01":
            # "May 1948" written as 1948-05-01: held as the month (migration
            # 105 did the same to the held events; see t_historical)
            precision = "month"
    elif etype == "aggregate_fatality":                # B'Tselem period totals
        precision = "unknown"
    else:
        precision = "day"
    lat, lon = loc.get("lat"), loc.get("lon")
    pid = places["pcode"].get(loc.get("admin2_pcode"))
    located = False
    if pid is not None:
        located = True
    elif lat is not None:
        pid = places["_pip"].resolve(lat, lon)
        located = True                                  # point-grade geometry
    elif loc.get("gazetteer_key") in places["_v1key"]:
        pid = places["_v1key"][loc["gazetteer_key"]]
        located = True
    else:
        pid, located = region_place(places, loc.get("region"), attrs)
    metrics = {k: m.get(k) for k in ("killed", "injured", "displaced",
                                     "affected", "unit")
               if m.get(k) not in (None, 0)}
    q = (rec.get("quality") or {}).get("score") or 0.7
    return [EventRow(ds, f"conflict.{etype}", str(rec["date"])[:10],
                     precision, rec["stable_id"], place_id=pid,
                     lat=lat, lon=lon, located=located, confidence=q,
                     independent_sources=max(len(sources), 1),
                     metrics=metrics, attrs=attrs)]


_CENSUSES = (("population_1922", "1922"), ("population_1931", "1931"),
             ("population_1945", "1945"), ("population_2016", "2016"))


def t_historical(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    loc = rec.get("location") or {}
    m = rec.get("metrics") or {}

    if ds == "v1_historical_archives":                 # 27 timeline → events
        attrs = passthrough(rec, _ds_over(spec, ds, "attrs_passthrough",
                                          default=[]))
        attrs["summary"] = rec.get("description")      # sanctioned law-6 exemption
        attrs["source_citation"] = (rec.get("sources") or [{}])[0].get("name")
        day = str(rec["date"])[:10]
        etype = slug(rec.get("event_type"))
        if day.endswith("-12-31") and etype == "uprising":       # law 2
            occurred, precision = f"{day[:4]}-01-01", "year"
        else:
            occurred, precision = day, "day"
        pid, located = region_place(places, loc.get("region"), attrs)
        metrics = {k: m.get(k) for k in ("killed", "displaced")
                   if m.get(k) not in (None, 0)}
        return [EventRow(ds, f"historical.{etype}", occurred, precision,
                         rec["stable_id"], place_id=pid, located=located,
                         independent_sources=1, metrics=metrics, attrs=attrs)]

    # POM localities: fan out censuses + status (REVIEW.md / spec fan_out)
    attrs = passthrough(rec, _ds_over(spec, ds, "attrs_passthrough",
                                      default=[]))
    # Mandate Palestine reused names heavily: five villages called al-Tira,
    # and eight cases where a post-1948 Jewish locality took the name of the
    # Palestinian village beside it, inside the same 1945 district. Two
    # localities called En HaHoresh sit in Tulkarem. Where the name, district
    # and group all match, the coordinates are what remain — and they are the
    # honest answer, because these ARE different places.
    if loc.get("lat") is not None and loc.get("lon") is not None:
        attrs["geo_key"] = f"{loc['lat']:.5f},{loc['lon']:.5f}"
    # the historic locality itself first — most Mandate villages sit inside
    # 1948 Israel, where no modern governorate polygon contains them, so the
    # point-in-polygon test alone leaves 4,141 rows unplaced
    pid = places["_historic_geo"].get(
        (f"{loc['lat']:.5f}", f"{loc['lon']:.5f}")
    ) if loc.get("lat") is not None and loc.get("lon") is not None else None
    if pid is None:
        pid = places["_pip"].resolve(loc.get("lat"), loc.get("lon"))
    located = pid is not None
    sid = rec["stable_id"]
    rows = []
    for field_, year in _CENSUSES:
        v = m.get(field_)
        if v is not None and v > 0:
            rows.append(Row(ds, "historical.population", f"{year}-01-01",
                            "year", f"{sid}:c{year}", value_num=v,
                            unit="persons", place_id=pid, located=located,
                            attrs={**attrs, "census": year}))
    day = str(rec["date"])[:10]
    if day == "1945-04-01":                # Village Statistics reference date
        occurred, precision = "1945-01-01", "year"
    elif day.endswith("-01"):
        # The source writes "May 1948" as 1948-05-01 and marks no precision:
        # 143 of the 478 dated villages sit on the first of a month (74 on
        # 1 May 1948 alone, against two or three on an ordinary day). Which of
        # them are a real first of the month cannot be told, so all are held
        # as the month: said at month precision the statement is true of every
        # one of them, and at day precision it was false for most (2026-10-12).
        occurred, precision = day, "month"
        attrs = {**attrs, "date_basis": "the first of a month in the source; held as the month"}
    else:
        occurred, precision = day, "day"   # real 1948 depopulation dates
    rows.append(Row(ds, "historical.locality_status", occurred, precision,
                    f"{sid}:status", value_text=rec.get("locality_status"),
                    place_id=pid, located=located, attrs=attrs))
    return rows


_UNRWA_AGG = {"Jordan", "Lebanon", "Syria", "West Bank", "Gaza Strip",
              "Total registered refugees", "Registered refugees",
              "Other registered people", "Total registered people",
              "Refugees living within official camp borders",
              "% living within camp borders"}


def t_refugees(rec, spec, places, counts):
    ds = route(rec, spec, counts)
    if ds is None:
        return Drop("unroutable")
    loc = rec.get("location") or {}
    m = rec.get("metrics") or {}
    attrs = passthrough(rec, _ds_over(spec, ds, "attrs_passthrough",
                                      default=[]))
    if ds == "v1_refugees_unhcr":
        year = str(rec["date"])[:4]                    # 100% -12-31, law 2
        return [Row(ds, "refugees.cross_border", f"{year}-01-01", "year",
                    rec["stable_id"], value_num=m.get("count"), unit="people",
                    attrs=attrs)]
    if ds == "v1_refugees_idmc":
        day = str(rec["date"])[:10]
        if day.endswith("-12-31"):                     # law 2, hits 2 of 334
            occurred, precision = f"{day[:4]}-01-01", "year"
        else:
            occurred, precision = day, "day"
        pid = places["_pip"].resolve(loc.get("lat"), loc.get("lon")) \
            or places["pcode"].get(loc.get("admin2_pcode"))
        return [Row(ds, "refugees.displacement_event", occurred, precision,
                    rec["stable_id"], value_num=m.get("displaced"),
                    unit="persons", place_id=pid, located=pid is not None,
                    attrs=attrs)]
    # UNRWA camp registry: build-stamp date → unknown (law 1 by analogy)
    name = loc.get("name")
    fetched = (rec.get("sources") or [{}])[0].get("fetched_at")
    if name in _UNRWA_AGG:
        # NOT LOADED since 2026-10-12. The eleven "summary" rows of v1's
        # Wikipedia scrape are mislabelled: six are the table's 1990 column
        # (West Bank 414,298, total 2,422,514), five are the Gaza Strip column
        # of a 2018 table under whole-agency labels ("Registered refugees
        # 1,421,282" is Gaza alone; the table's total is 5,545,540; "41" is
        # Gaza's 41.8% cut short). The real totals are in unrwa_registered_hdx.
        # The dataset's generation is complete, so the held eleven close.
        return Drop("mislabelled_summary_row")
    pid = places["_pip"].resolve(loc.get("lat"), loc.get("lon"))
    return [Row(ds, "refugees.camp_population", str(rec["date"])[:10],
                "unknown", rec["stable_id"], value_num=m.get("count"),
                unit="people", place_id=pid, located=pid is not None,
                reported_at=fetched, attrs=attrs)]


# ── conflict_westbank — T4P's RAW West Bank cumulative series ────────────────
# v1's unified transform maps only the daily killed/injured fields (always 0
# for WB — the very rows conflict.yaml drops) and destroys the cumulative
# fields, so this spec reads the RAW quarterlies the healed nightly fetch
# refreshes. Law 1 applied to T4P's padding: flash_source='fill' days repeat
# yesterday's numbers on a date nothing was observed — the prepass keeps only
# 'un' days (real OCHA flash updates, even when values held) and fill days
# where a value actually moved.

_WB_CUMS = [
    ("killed_cum", "conflict.westbank_cumulative_killed", "persons"),
    ("injured_cum", "conflict.westbank_cumulative_injured", "persons"),
    ("killed_children_cum",
     "conflict.westbank_cumulative_killed_children", "persons"),
    ("injured_children_cum",
     "conflict.westbank_cumulative_injured_children", "persons"),
    ("settler_attacks_cum",
     "conflict.westbank_cumulative_settler_attacks", "attacks"),
    ("displaced_households_cum",
     "conflict.westbank_cumulative_displaced_households", "households"),
    ("displaced_persons_cum",
     "conflict.westbank_cumulative_displaced_persons", "persons"),
    ("displaced_children_cum",
     "conflict.westbank_cumulative_displaced_children", "persons"),
]


def _wb_day(rec):
    return str(rec.get("report_date") or rec.get("date") or "")[:10]


def t_conflict_westbank(rec, spec, places, counts):
    ds = "v1_conflict_t4p_westbank"
    day = _wb_day(rec)
    if not day:
        return Drop("missing_date")
    if day not in t_conflict_westbank.keep:
        return Drop("fill_padding")
    wb = places["region"]["West Bank"]
    attrs = {"cumulative": True, "flash_source": rec.get("flash_source")}
    rows = []
    for field_name, indicator, unit in _WB_CUMS:
        v = rec.get(field_name)
        if v is None:
            continue
        rows.append(Row(ds, indicator, day, "day",
                        f"t4praw-wb-{day}:{field_name}", value_num=v,
                        unit=unit, place_id=wb, attrs=attrs))
    return rows or Drop("no_metrics")


def _wb_prepass(all_recs, spec, counts):
    """Chronological change-detection over the whole series before any
    per-record transform: the keep-set is every 'un' day plus every fill
    day whose value tuple moved; everything else is carried-forward
    padding, dropped and counted."""
    recs = sorted((r for r in all_recs if isinstance(r, dict) and _wb_day(r)),
                  key=_wb_day)
    keep, prev = set(), None
    for r in recs:
        tup = tuple(r.get(k) for k, _, _ in _WB_CUMS)
        if r.get("flash_source") == "un" or prev is None or tup != prev:
            keep.add(_wb_day(r))
        prev = tup
    t_conflict_westbank.keep = keep


t_conflict_westbank.prepass = _wb_prepass


# ── conflict_gaza — T4P's Gaza daily series after v1 froze (F-12) ────────────
# The same publisher file v1 used to feed, read directly (conflict_gaza.yaml).
# Starts the day after the frozen series' last value so the two datasets meet
# and never overlap. Only rows T4P transcribed from a Ministry bulletin are
# served; a day with no bulletin is a counted gap, never filled.
GAZA_CUTOVER = "2026-08-09"


def t_conflict_gaza(rec, spec, places, counts):
    ds = "t4p_gaza_daily"
    day = str(rec.get("report_date") or "")[:10]
    if not day:
        return Drop("missing_date")
    # Until 2026-10-11 a day before the cut-over was dropped here whole; the
    # detail series now load from the first bulletin, so the cut-over applies
    # only to the two legacy totals (below) and a day with no total at all can
    # still carry its detail.
    killed, injured = rec.get("killed_cum"), rec.get("injured_cum")
    # T4P fills a day with no Ministry bulletin by subtracting the NEXT
    # bulletin's 24 h line from its total, and marks it report_source
    # "missing". Measured 2026-09-23: all 9 such rows in 2026 equal exactly
    # that subtraction. The 24 h line and the total count different things
    # (the B2 finding Zaid ratified), so the result is a number no bulletin
    # states — and on 2026-09-13 it put 73,784 on a day the bulletin itself
    # reads 73,786. A gap is honest; an inferred value served as published is
    # not.
    # DATABANK-V06 (2026-09-26): only "missing" is T4P's arithmetic. "gmotel"
    # is a bulletin from the Government Media Office — a published figure,
    # served with the office named in attrs.report_source (22 rows today, all
    # 2023, before the cut-over). Any other value is new vocabulary: an
    # UNDECLARED drop, so the run fails and a person reads it first.
    source = rec.get("report_source")
    if source == "missing":
        return Drop("t4p_inferred")
    if source not in ("mohtel", "gmotel"):
        return Drop("unknown_report_source")
    gaza = places["region"]["Gaza Strip"]
    attrs = {"cumulative": True, "region": "Gaza Strip",
             "report_source": rec.get("report_source")}
    rows = []
    # The two legacy totals start the day after v1's frozen series ends (the
    # cut-over); the detail series below never existed in the databank, so
    # they load from the first bulletin (2026-10-11, the fragments decision).
    if day >= GAZA_CUTOVER:
        for value, field_name, indicator in (
                (killed, "killed_cum", "conflict.gaza_cumulative_killed"),
                (injured, "injured_cum", "conflict.gaza_cumulative_injured")):
            if value is None:
                counts[f"one_total_missing:{field_name}"] += 1
                continue
            rows.append(Row(ds, indicator, day, "day", f"t4p-gaza-{day}:{field_name}",
                            value_num=value, unit="persons", place_id=gaza, attrs=attrs))
    else:
        counts["legacy_totals_before_cutover"] += 1
    # Detail cumulatives the ingest dropped until 2026-10-11: children, women,
    # medical staff, press, civil defence and "massacres" (T4P's count of
    # families with several members killed). T4P's `ext_` prefix means
    # "extended": on a bulletin day the value is the bulletin's; on a
    # "missing" day it is T4P's carry-forward, and those days were dropped
    # above, so nothing here is inferred.
    for field_name, indicator, unit in _GAZA_DETAIL_CUMS:
        value = rec.get(field_name)
        if value in (None, ""):
            continue
        rows.append(Row(ds, indicator, day, "day", f"t4p-gaza-{day}:{field_name}",
                        value_num=value, unit=unit, place_id=gaza, attrs=attrs))
    # The bulletin's own 24-hour line and its split (newly killed since the
    # ceasefire, died of wounds, added by the Ministry's judicial committee):
    # flows, summable, with the period the bulletin covered in attrs — the B2
    # finding is exactly that a 24 h line is not a difference of totals.
    daily_attrs = {"region": "Gaza Strip", "report_source": rec.get("report_source"),
                   "report_period_hours": rec.get("report_period")}
    for field_name, indicator in _GAZA_DAILY_FLOWS:
        value = rec.get(field_name)
        if value in (None, ""):
            continue
        rows.append(Row(ds, indicator, day, "day", f"t4p-gaza-{day}:{field_name}",
                        value_num=value, unit="persons", place_id=gaza, attrs=daily_attrs))
    return rows or Drop("no_metrics")


_GAZA_DETAIL_CUMS = (
    ("ext_killed_children_cum", "conflict.gaza_cumulative_killed_children", "persons"),
    ("ext_killed_women_cum", "conflict.gaza_cumulative_killed_women", "persons"),
    ("ext_med_killed_cum", "conflict.gaza_cumulative_killed_medical", "persons"),
    ("ext_press_killed_cum", "conflict.gaza_cumulative_killed_press", "persons"),
    ("ext_civdef_killed_cum", "conflict.gaza_cumulative_killed_civil_defence", "persons"),
    ("ext_massacres_cum", "conflict.gaza_cumulative_massacres", "events"),
)
_GAZA_DAILY_FLOWS = (
    ("killed", "conflict.gaza_daily_killed"),
    ("injured", "conflict.gaza_daily_injured"),
    ("killed_truce_new", "conflict.gaza_daily_killed_new"),
    ("killed_succumbed", "conflict.gaza_daily_killed_succumbed"),
    ("killed_committee", "conflict.gaza_daily_killed_committee"),
)


# ── water_gho — WHO GHO WASH indicators, v2's own fetch ──────────────────────
# The one code with PSE data the databank lacked (WSH_SANITATION_OD; the
# whole diff is in water_gho.yaml). Conventions mirror v1_health_who exactly
# so the water domain reads as one system.

_GHO_DIM_NAMES = {
    "RESIDENCEAREATYPE_RUR": "Rural",
    "RESIDENCEAREATYPE_URB": "Urban",
    "RESIDENCEAREATYPE_TOTL": "Total",
}


def t_water_gho(rec, spec, places, counts):
    ds = "who_gho_wash"
    code, year = rec.get("IndicatorCode"), rec.get("TimeDim")
    if not code or not year:
        return Drop("missing_identity")
    value, basis = rec.get("NumericValue"), "numeric"
    if value is None:
        # measured: GHO publishes this series as integer-rounded display
        # strings (Value "0"/"1"/"2") with NumericValue null — disclosed
        try:
            value = float(rec.get("Value"))
            basis = "gho_display_value"
        except (TypeError, ValueError):
            return Drop("no_value")
    dim = rec.get("Dim1") or "TOTAL"
    attrs = {"code": dim, "name": _GHO_DIM_NAMES.get(dim, dim),
             "type": rec.get("Dim1Type") or "", "region": "Palestine",
             "indicator_code": code, "value_basis": basis}
    return [Row(ds, f"water.{slug(code)}.{slug(dim)}", f"{year}-01-01",
                "year", f"gho-{code}-{year}-{dim}", value_num=value,
                unit="percentage", place_id=None, attrs=attrs)]


def t_population_wpp(rec, spec, places, counts):
    """P1-B.4 — UN WPP 2024 for the State of Palestine, 1950-2023: modelled
    estimates, one row per (year, indicator), the whole territory (place NULL,
    attrs.region 'Palestine' — the funding convention). Every row says it is
    an estimate. Projections never reach here: ops/fetch_wpp.py writes them to
    another file for t_population_wpp_projection, and a record that says it is
    one is dropped under a reason the spec does not declare, which fails the
    run rather than date a projection among the estimates."""
    year, ind = rec.get("year"), rec.get("indicator")
    if not isinstance(year, int) or not ind:
        return Drop("malformed")
    if rec.get("projection"):
        return Drop("projection_among_estimates")
    value = rec.get("value")
    if value is None:
        return Drop("no_value")
    attrs = {"region": "Palestine", "estimate": "modelled (WPP 2024, Medium variant)",
             "wpp_column": rec.get("wpp_column"), "wpp_unit": rec.get("wpp_unit"),
             "revision": "WPP2024"}
    return [Row("un_wpp_2024", f"population.wpp.{ind}", f"{year}-01-01", "year",
                rec["stable_id"], value_num=value, unit=rec.get("unit"),
                place_id=None, attrs=attrs)]


def t_population_wpp_projection(rec, spec, places, counts):
    """UN WPP 2024, the MEDIUM-VARIANT PROJECTION for the State of Palestine:
    the years after the last estimate (2024 to 2100, and 2101 for the 1 January
    population). A model's output released on 11 July 2024, not a measurement,
    so it is its own dataset and its own indicator family: no question about
    `population.wpp.*` can end in a projected year, and every row says what it
    is (attrs.projection, the variant as the UN names it, the edition, the
    release day, the UN's unit word as the estimate rows carry it). A record
    that does not say it is a projection (the estimates file, read by mistake)
    is dropped under a reason the spec does not declare, which fails the run."""
    year, ind = rec.get("year"), rec.get("indicator")
    if not isinstance(year, int) or not ind:
        return Drop("malformed")
    if rec.get("projection") is not True or not rec.get("variant") \
            or not rec.get("edition") or not rec.get("released"):
        return Drop("not_a_projection")
    value = rec.get("value")
    if value is None:
        return Drop("no_value")
    attrs = {"region": "Palestine", "projection": True, "variant": rec["variant"],
             "edition": rec["edition"], "released": rec["released"],
             "wpp_column": rec.get("wpp_column"), "wpp_unit": rec.get("wpp_unit")}
    return [Row("un_wpp_2024_projection", f"population.wpp_projection.{ind}",
                f"{year}-01-01", "year", rec["stable_id"], value_num=value,
                unit=rec.get("unit"), place_id=None, attrs=attrs)]


_QUARTER_MONTH = {"Q1": "03", "Q2": "06", "Q3": "09", "Q4": "12"}


def t_refugees_unrwa_registered(rec, spec, places, counts):
    """P1-B.4 — registered Palestine refugees per UNRWA field, sex and age, from
    UNRWA's own quarterly HDX release. One row per (field, column). Gaza and
    the West Bank land on their region rows; Jordan, Lebanon, Syria and
    "Unknown" carry the field in attrs (place NULL). The all-fields "Total"
    row gets its OWN indicator, so a sum across fields never counts everyone
    twice. Dated to the quarter's last month (a stock at the end of it)."""
    year, q, field = rec.get("year"), rec.get("quarter"), rec.get("field")
    month = _QUARTER_MONTH.get(q)
    if not isinstance(year, int) or not month or not field:
        return Drop("malformed")
    total_row = field.strip().lower() == "total"
    base = "refugees.unrwa_registered_all_fields" if total_row else "refugees.unrwa_registered"
    region = {"gaza": "Gaza Strip", "west bank": "West Bank"}.get(field.strip().lower())
    place_id = places["region"].get(region) if region else None
    rows = []
    for col, value in sorted((rec.get("counts") or {}).items()):
        name = {"Grand Total": "total", "Female Total": "female",
                "Male Total": "male"}.get(col, slug(col).replace("60", "60_plus")
                                          if col.endswith("+") else slug(col))
        attrs = {"field": field, "country": rec.get("country"), "quarter": f"{year} {q}",
                 "as_of": "end of quarter", "column": col}
        rows.append(Row("unrwa_registered_hdx", f"{base}.{name}", f"{year}-{month}-01",
                        "month", f"unrwa-reg:{year}{q}:{slug(field)}:{slug(col)}",
                        value_num=value, unit="persons", place_id=place_id,
                        located=place_id is not None, attrs=attrs))
    return rows


# ── insecurity_insight — one event per incident, weapon and victims kept ─────
# (insecurity_insight.yaml, 2026-10-11). v1's normalised HDX files, read from
# data/raw/insecurity_insight by ops/fetch_insecurity_insight.py.

def _ii_content(r: dict) -> str:
    return json.dumps([r.get("date"), r.get("category"), r.get("admin1"),
                       r.get("weapon"), r.get("perpetrator_type"),
                       r.get("location_type"), r.get("victims")], sort_keys=True)


_II_OLD_FILE = "2023 PSE SHCC Health Care Data.xlsx"
_II_NEW_FILE = "2023-2024 PSE SHCC Health Care Data.xlsx"
_II_REGIONS = ("Gaza Strip", "West Bank", "East Jerusalem")


def _ii_prepass(all_recs, spec, counts):
    """The 2023-only SHCC file is covered by the 2023-2024 one: an incident
    present in both (416 measured) is dropped from the older file, counted."""
    t_insecurity_insight.later = {_ii_content(r) for r in all_recs
                                  if isinstance(r, dict)
                                  and r.get("source_dataset") == _II_NEW_FILE}


def t_insecurity_insight(rec, spec, places, counts):
    ds = "insecurity_insight_incidents"
    day = str(rec.get("date") or "")[:10]
    if len(day) != 10:
        return Drop("missing_date")
    cat = slug(rec.get("category") or "")
    if not cat:
        return Drop("missing_category")
    if (rec.get("source_dataset") == _II_OLD_FILE
            and _ii_content(rec) in t_insecurity_insight.later):
        return Drop("superseded_by_later_file")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    lat, lon = rec.get("latitude"), rec.get("longitude")
    pid, located = None, False
    if lat is not None and lon is not None:
        pid = places["_pip"].resolve(lat, lon)
        located = True                                  # point-grade geometry
    else:
        a1 = rec.get("admin1") or ""
        if a1.endswith(" Governorate"):
            pid = governorate_by_name(places, a1[: -len(" Governorate")])
            located = pid is not None
        if pid is None:
            region = a1 if a1 in _II_REGIONS else "Palestine"
            pid, located = region_place(places, region, attrs)
    v = rec.get("victims") or {}
    metrics = {k: v.get(k) for k in ("killed", "injured", "kidnapped", "arrested")
               if v.get(k) not in (None, 0)}
    # a month the publisher gave as a month stays one (the 2019/2020 SHCC files)
    precision = "month" if rec.get("date_precision") == "month" else "day"
    return [EventRow(ds, f"attack.{cat}", day, precision, f"ii-{rec['incident_id']}",
                     place_id=pid, lat=lat, lon=lon, located=located,
                     confidence=0.7, independent_sources=1, metrics=metrics,
                     attrs=attrs)]


t_insecurity_insight.prepass = _ii_prepass
t_insecurity_insight.later = set()


# ── btselem_fatalities — one observation per person killed ───────────────────
# (btselem_fatalities.yaml, 2026-10-11). v1's frozen CSV, converted nightly by
# ops/fetch_btselem_file.py. Districts are the publisher's; the region is the
# landing for the settlement bloc and the Strip itself; Israel stays NULL.
_BTSELEM_REGION_DISTRICTS = {"Gush Katif": "Gaza Strip", "Gaza Strip": "Gaza Strip"}


def t_btselem_fatalities(rec, spec, places, counts):
    ds = "btselem_fatalities"
    day = str(rec.get("date_of_event") or "")[:10]
    if len(day) != 10:
        return Drop("missing_date")
    name = (rec.get("name") or "").strip()
    if not name:
        return Drop("missing_name")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    attrs["name"] = name
    district = rec.get("event_location_district") or ""
    region = rec.get("event_location_region") or ""
    pid, located = None, False
    if district in _BTSELEM_REGION_DISTRICTS:
        pid, located = region_place(places, _BTSELEM_REGION_DISTRICTS[district], attrs)
    else:
        pid = governorate_by_name(places, district)
        located = pid is not None
        if pid is None:
            counts[f"district_to_region:{district or '-'}"] += 1
            pid, located = region_place(places, region if region in
                                        ("Gaza Strip", "West Bank") else region or "Palestine", attrs)
    seq = rec.get("seq") or 0
    sid = "btselem-" + hashlib.sha1(
        f"{name}|{day}|{rec.get('date_of_death')}|{rec.get('place_of_residence')}|{seq}"
        .encode("utf-8")).hexdigest()[:20]
    return [Row(ds, "fatalities.person", day, "day", sid, value_num=1,
                value_text=name, unit="persons", place_id=pid, located=located,
                attrs=attrs)]


# ── unhcr_population — UNHCR's six HDX tables, one observation per figure ────
# (unhcr_population.yaml, 2026-10-11; ops/fetch_unhcr_hdx.py adds `table`).

def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_UNHCR_STOCKS = (("Refugees", "refugees"), ("Asylum seekers", "asylum_seekers"),
                 ("Other people in need of international protection", "oip"),
                 ("Internally displaced persons", "idps"), ("Stateless Persons", "stateless"),
                 ("Others of concern to UNHCR", "others_of_concern"), ("Host community", "host_community"))
_UNHCR_BANDS = (("0-4", "0_4"), ("5-11", "5_11"), ("12-17", "12_17"), ("18-59", "18_59"),
                ("60 or more", "60_plus"), ("Unknown", "unknown"), ("Total", "total"))
_UNHCR_DEMO = ([(f"{sex} {band}", f"{sex.lower()}_{s}") for sex in ("Female", "Male")
                for band, s in _UNHCR_BANDS] + [("Total", "total")])
_UNHCR_DECISIONS = (("Recognized", "recognized"), ("Complementary Protection", "complementary_protection"),
                    ("Otherwise Closed", "otherwise_closed"), ("Rejected", "rejected"), ("Total Decided", "total"))
_UNHCR_SOLUTIONS = (("Resettlement arrivals", "resettlement_arrivals"), ("Naturalisation", "naturalisation"),
                    ("Refugee returns", "refugee_returns"), ("IDP returns", "idp_returns"))


# table → (the columns that make a cell, the columns that are summed in it)
_UNHCR_APP_DIMS = ("Year", "Country of Origin Code", "Country of Asylum Code", "Procedure Type",
                   "Application Type Code", "Application Data Type")
_UNHCR_DEC_DIMS = ("Year", "Country of Origin Code", "Country of Asylum Code", "Procedure Type",
                   "Decision Type Code", "Decision Data Type")
_UNHCR_DEMO_DIMS = ("Year", "Country of Origin Code", "Country of Asylum Code", "Population Type",
                    "location", "urbanRural", "accommodationType")
_UNHCR_CELL = {
    "demographics_originating": (_UNHCR_DEMO_DIMS, tuple(c for c, _ in _UNHCR_DEMO)),
    "demographics_residing": (_UNHCR_DEMO_DIMS, tuple(c for c, _ in _UNHCR_DEMO)),
    "applications": (_UNHCR_APP_DIMS, ("Number of Applications",)),
    "decisions": (_UNHCR_DEC_DIMS, tuple(c for c, _ in _UNHCR_DECISIONS)),
}


def _unhcr_cell(rec) -> tuple:
    table = rec.get("table") or ""
    return (table,) + tuple(str(rec.get(k) or "") for k in _UNHCR_CELL[table][0])


def _unhcr_demo_key(rec) -> str:
    return "|".join(str(rec.get(k) or "") for k in (
        "Year", "Country of Origin Code", "Country of Asylum Code", "Population Type",
        "location", "urbanRural", "accommodationType"))


def _unhcr_prepass(all_recs, spec, counts):
    """The residing-in-Palestine table repeats the originating table's rows for
    people who are both from and in Palestine (8 measured): one fact, two
    files. The originating copy is kept; the residing copy is dropped, counted.

    A CELL MAY BE PUBLISHED AS TWO ROWS, AND THEY ADD (2026-10-12). HDX's
    export of UNHCR's tables drops a column the publisher keys on, so some
    cells arrive as two rows nothing tells apart: 39 demographics cells (one
    row with the sex and age breakdown, one with a bare Total), 45 applications
    cells and 6 decisions cells. They are parts, not revisions, measured two
    ways. Demographics: on every one of the 29 country-years that hold such a
    cell, UNHCR's own stocks table equals the SUM of the rows and never the
    first or the larger alone (Canada 2020: 357 + 1,420 = 1,777). Applications
    and decisions: UNHCR's API returns the same two rows with the column HDX
    drops, `dec_level` (first instance and administrative review), and totals
    them: PSE → Australia 2000, 134 + 15 = "applied": 149; even the one pair
    that is identical, Poland 2002, 5 + 5 = 10.
    The first load kept the first row and dropped the second as a repeat of
    its id, so 90 cells were understated; from the second night the second
    row met an identity already held and the run refused. A cell is now
    emitted once, summed, and says how many rows went into it."""
    t_unhcr_population.originating = {_unhcr_demo_key(r) for r in all_recs
                                      if isinstance(r, dict)
                                      and r.get("table") == "demographics_originating"}
    cells: dict[tuple, list] = defaultdict(list)
    for r in all_recs:
        if isinstance(r, dict) and r.get("table") in _UNHCR_CELL:
            cells[_unhcr_cell(r)].append(r)
    t_unhcr_population.summed = {}
    for k, recs in cells.items():
        if len(recs) > 1:
            cols = _UNHCR_CELL[k[0]][1]
            t_unhcr_population.summed[k] = (
                {col: sum(v for v in (_num(r.get(col)) for r in recs) if v is not None)
                 for col in cols if any(_num(r.get(col)) is not None for r in recs)},
                len(recs))
    t_unhcr_population.emitted_cells = set()


def t_unhcr_population(rec, spec, places, counts):
    ds = "unhcr_population_hdx"
    table = rec.get("table") or ""
    year = str(rec.get("Year") or "")[:4]
    if not year.isdigit():
        return Drop("missing_year")
    if table == "demographics_residing" and _unhcr_demo_key(rec) in t_unhcr_population.originating:
        return Drop("duplicate_of_originating")
    day = f"{year}-01-01"
    code = rec.get("Country of Asylum Code") or ""
    origin = rec.get("Country of Origin Code") or ""
    attrs = {"table": table, "asylum_country": rec.get("Country of Asylum Name"),
             "asylum_country_code": code, "origin_country_code": origin}
    if code == "PSE":
        attrs["region"] = "Palestine"           # people residing in Palestine: honest NULL place
    rows = []
    summed = None
    if table in _UNHCR_CELL:
        cell = _unhcr_cell(rec)
        summed = t_unhcr_population.summed.get(cell)
        if summed:
            if cell in t_unhcr_population.emitted_cells:
                return Drop("summed_into_cell")      # its figures are in the cell's first row
            t_unhcr_population.emitted_cells.add(cell)

    def val(col):
        """The column's figure: the cell's sum where the cell came as several rows."""
        return summed[0].get(col) if summed else _num(rec.get(col))

    def emit(ind, value, dims=None, key="", unit="persons"):
        a = dict(attrs)
        a.update(dims or {})
        sid = "unhcr-" + hashlib.sha1("|".join([table, year, origin, code, key, ind]).encode("utf-8")).hexdigest()[:20]
        rows.append(Row(ds, ind, day, "year", sid, value_num=value, unit=unit, attrs=a))

    if table == "stocks":
        for col, s in _UNHCR_STOCKS:
            v = _num(rec.get(col))
            if v is not None:
                emit(f"refugees.stock.{s}", v)
    elif table in ("demographics_originating", "demographics_residing"):
        dims = {"population_type": rec.get("Population Type"), "location": rec.get("location"),
                "urban_rural": rec.get("urbanRural"), "accommodation": rec.get("accommodationType")}
        key = "|".join(str(dims[k] or "") for k in ("population_type", "location", "urban_rural", "accommodation"))
        if summed:
            dims["rows_summed"] = summed[1]
        for col, s in _UNHCR_DEMO:
            v = val(col)
            if v is None or (v == 0 and not s.endswith("total")):
                continue                        # zero cells are not written, totals always are
            emit(f"refugees.demographics.{s}", v, dims, key)
    elif table == "applications":
        dims = {"procedure_type": rec.get("Procedure Type"), "procedure": rec.get("Procedure Name"),
                "application_type": rec.get("Application Type Code"),
                "application_data": rec.get("Application Data Type")}
        key = "|".join(str(dims[k] or "") for k in ("procedure_type", "application_type", "application_data"))
        if summed:
            dims["rows_summed"] = summed[1]
        v = val("Number of Applications")
        if v is not None:
            emit("refugees.asylum_applications", v, dims, key,
                 unit="cases" if dims["application_data"] == "C" else "persons")
    elif table == "decisions":
        dims = {"procedure_type": rec.get("Procedure Type"), "procedure": rec.get("Procedure Name"),
                "decision_type": rec.get("Decision Type Code"), "decision_data": rec.get("Decision Data Type")}
        key = "|".join(str(dims[k] or "") for k in ("procedure_type", "decision_type", "decision_data"))
        unit = "cases" if dims["decision_data"] == "C" else "persons"
        if summed:
            dims["rows_summed"] = summed[1]
        for col, s in _UNHCR_DECISIONS:
            v = val(col)
            if v is not None:
                emit(f"refugees.asylum_decisions.{s}", v, dims, key, unit=unit)
    elif table == "solutions":
        for col, s in _UNHCR_SOLUTIONS:
            v = _num(rec.get(col))
            if v is not None:
                emit(f"refugees.solutions.{s}", v)
    else:
        counts[f"unknown_table:{table or '-'}"] += 1
    return rows or Drop("no_values")


t_unhcr_population.prepass = _unhcr_prepass
t_unhcr_population.originating = set()
t_unhcr_population.summed = {}
t_unhcr_population.emitted_cells = set()


# ── fao_diem — FAO DIEM household-survey aggregates, one row per figure ───────
# (fao_diem.yaml, 2026-10-11; ops/fetch_fao_diem.py keeps the PSE rows).
_FAO_SKIP = frozenset(("objectid", "adm0_name", "adm0_iso3", "adm0_m49", "adm1_name", "adm1_pcode",
                       "adm2_pcode", "adm2_name", "adm_name", "adm_pcode", "adm_level", "round",
                       "coll_start_date", "coll_end_date", "coll_mid_date", "theme"))
_FAO_REGION = {"PS01": "West Bank", "PS02": "Gaza Strip"}


def _fao_date(s) -> str | None:
    try:
        return datetime.strptime(str(s or "").split(" ")[0], "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


_FAO_STATISTIC = ("_wmean", "_median", "_stddev")


def t_fao_diem(rec, spec, places, counts):
    ds = "fao_diem_household_surveys"
    theme = rec.get("theme") or "unknown"
    day = _fao_date(rec.get("coll_mid_date"))
    if not day:
        return Drop("missing_date")
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    attrs["coll_start_date"] = _fao_date(rec.get("coll_start_date"))
    attrs["coll_end_date"] = _fao_date(rec.get("coll_end_date"))
    pid, located = None, False
    if str(rec.get("adm_level")) == "2":
        pid = places["pcode"].get(rec.get("adm2_pcode"))
        located = pid is not None
    if pid is None:
        region = _FAO_REGION.get(rec.get("adm1_pcode") or "") or rec.get("adm1_name") or "Palestine"
        pid, located = region_place(places, region, attrs)
    rows = []
    for col, raw in rec.items():
        if col in _FAO_SKIP or col.startswith("﻿"):
            continue
        v = _num(raw)
        if v is None:
            continue
        unit = "count" if col.startswith(("tot_", "surveys")) else "percent"
        if col.endswith(_FAO_STATISTIC):
            # A mean, median or spread of a QUANTITY (kg harvested, hectares,
            # household size, a score) is not a share of households: 70 such
            # series were stored as "percent" (22,965.6 "percent" of harvest).
            # The quantity's own unit is in FAO's column description, which is
            # the series' name; the row carries no unit rather than a wrong one.
            unit = None
        sid = "fao-" + hashlib.sha1("|".join([theme, str(rec.get("round") or ""), str(rec.get("adm_pcode") or ""),
                                              day, col]).encode("utf-8")).hexdigest()[:20]
        rows.append(Row(ds, f"fao_diem.{theme}.{col}", day, "day", sid, value_num=v, unit=unit,
                        place_id=pid, located=located, attrs=attrs))
    return rows or Drop("no_values")


# ── acled_hdx — ACLED's monthly governorate aggregates, HELD under `internal` ─
# (acled_hdx.yaml, 2026-10-11; ops/fetch_acled_file.py adds `family`).
_ACLED_REGION = {"PS01": "West Bank", "PS02": "Gaza Strip"}


def t_acled_hdx(rec, spec, places, counts):
    ds = "acled_hdx_monthly"
    period = str(rec.get("date_period") or "")
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        return Drop("missing_month")
    day = period + "-01"
    family = rec.get("family") or "unknown"
    attrs = passthrough(rec, spec.get("attrs_passthrough"))
    pid = places["pcode"].get(rec.get("admin2_pcode"))
    located = pid is not None
    if pid is None:
        pid, located = region_place(places, _ACLED_REGION.get(rec.get("admin1_pcode") or "", "Palestine"), attrs)
    rows = []
    for field_name, indicator, unit in (("events", f"acled.{family}.events", "events"),
                                        ("fatalities", f"acled.{family}.fatalities", "persons")):
        v = _num(rec.get(field_name))
        if v is None:
            continue
        sid = f"acled-{family}-{rec.get('admin2_pcode')}-{period}-{field_name}"
        rows.append(Row(ds, indicator, day, "month", sid, value_num=v, unit=unit,
                        place_id=pid, located=located, attrs=attrs))
    return rows or Drop("no_values")


TRANSFORMERS = {
    "aid_un2720": t_engine,               # 2026-10-12: UN2720's daily aid series, spec-driven
    "aid_gazacham": t_engine,          # the Gaza Chamber of Commerce's weekly trucks (2026-10-14)
    "cited_figures": t_engine,            # 2026-10-12: hand-entered figures, one publisher's statement a row
    "acled_hdx": t_acled_hdx,                                   # 2026-10-11, internal
    "insecurity_insight": t_insecurity_insight,                 # 2026-10-11
    "btselem_fatalities": t_btselem_fatalities,                 # 2026-10-11
    "unhcr_population": t_unhcr_population,                     # 2026-10-11
    "fao_diem": t_fao_diem,                                     # 2026-10-11
    "refugees_unrwa_registered": t_refugees_unrwa_registered,   # P1-B.4
    "population_wpp": t_population_wpp,   # P1-B.4: the 1950s, from the UN
    "population_wpp_projection": t_population_wpp_projection,   # the UN's projection, kept apart
    "conflict": t_conflict,
    "conflict_westbank": t_conflict_westbank,
    "conflict_gaza": t_conflict_gaza,
    "water_gho": t_water_gho,
    "historical": t_historical,
    "refugees": t_refugees,
    "prisoners": t_prisoners,
    "prisoners_hamoked": t_prisoners,     # P1-B.3: v2's own HaMoked fetch
    "casualties": t_casualties,
    "demolitions": t_demolitions,
    "settlements": t_engine,
    "settlements_by_settlement": t_engine,   # 2026-10-13: Peace Now's population per settlement and year, spec-driven
    "land": t_land,
    "culture": t_engine,
    "education": t_education,
    "connectivity": t_connectivity_v2,
    "funding": t_engine,
    "pcbs": t_engine,
    "economic": t_economic,
    "economic_pcbs": t_economic,          # P1-B.3: v2's own PCBS fetch
    "health": t_health,
    "food": t_food,
    "aid_access": t_aid_access,
    "martyrs_snapshot_2023": t_martyrs_t4p,
    "infrastructure": t_infrastructure,
}

# A category cut from v1 keeps its old transformer HERE, and only here. It is
# never part of a run — ops/asof_harness.py uses it to replay the vault's
# v1-shaped snapshots for dates before the cut, which is the only way the
# historical as-of proof survives the cut. Twelve more of these are coming.
REPLAY_TRANSFORMERS = {
    "martyrs_snapshot_2023": t_martyrs_v1,
    "connectivity": t_connectivity,
    "health": t_health_v1,                # 2026-10-12: GHO's own rows replace v1's
    "education": t_education_v1,          # 2026-10-12: v1's "Active"/"Unknown" no longer loaded
}


# ── the run ──────────────────────────────────────────────────────────────────

def ensure_datasets(conn, spec, category) -> dict:
    """Upsert the spec's pre-declared datasets; return key → dataset_id."""
    out = {}
    with conn.cursor() as cur:
        for ds in spec["datasets"]:
            cur.execute("SELECT source_id FROM source WHERE key = %s",
                        (ds["source"],))
            row = cur.fetchone()
            if row is None:
                raise SpecRefused(f"dataset {ds['key']}: source {ds['source']!r}"
                                  " not in `source` — run migrations first")
            # Format v2 `v1_category:` — a spec whose file name is not the
            # serving category (conflict_westbank → conflict) declares which
            # category views its datasets join.
            cat_label = spec.get("v1_category", category)
            cur.execute("""
                INSERT INTO dataset (key, name, source_id, v1_category,
                                     cadence, active)
                VALUES (%s, %s, %s, %s, 'migration', true)
                ON CONFLICT (key) DO UPDATE SET v1_category = EXCLUDED.v1_category
                RETURNING dataset_id""",
                (ds["key"], f"v1 {category} — {ds['source']}",
                 row[0], cat_label))
            out[ds["key"]] = cur.fetchone()[0]
    return out


INSERT_SQL = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num,
                         value_text, unit, occurred_at, occurred_precision,
                         reported_at, raw_ref, v1_stable_id, identity_key,
                         attrs)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value_num)s,
        %(value_text)s, %(unit)s, %(occurred_at)s, %(precision)s,
        %(reported_at)s, %(raw_ref)s, %(v1_stable_id)s, %(identity_key)s,
        %(attrs)s)
-- The inference clause must reproduce the index's FULL predicate, including
-- 061's `upper(sys_period) IS NULL`. Postgres matches a partial unique index
-- only on an exact predicate match; with the old two-thirds version it found
-- no index at all and raised InvalidColumnReference on the first insert
-- after 061 — loudly, which is the right way for this to go wrong.
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE v1_stable_id IS NOT NULL AND upper(sys_period) IS NULL
DO NOTHING
"""

EVENT_REVISE_SQL = """
UPDATE event
   SET event_type = %(event_type)s, place_id = %(place_id)s,
       geom = CASE WHEN %(lon)s::float8 IS NULL THEN NULL
                   ELSE ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography END,
       occurred_at = %(occurred_at)s, occurred_precision = %(precision)s,
       status = 'believed', confidence = %(confidence)s,
       independent_sources = %(independent_sources)s,
       metrics = %(metrics)s, attrs = %(attrs)s,
       correction_note = %(note)s, updated_at = now()
 WHERE event_id = %(event_id)s AND upper_inf(sys_period)
"""

EVENT_INSERT_SQL = """
INSERT INTO event (event_type, place_id, geom, occurred_at,
                   occurred_precision, status, confidence, claim_count,
                   independent_sources, contradicted_by, metrics, attrs)
VALUES (%(event_type)s, %(place_id)s,
        CASE WHEN %(lon)s::float8 IS NULL THEN NULL
             ELSE ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
        END,
        %(occurred_at)s, %(precision)s, 'believed', %(confidence)s, 0,
        %(independent_sources)s, 0, %(metrics)s, %(attrs)s)
ON CONFLICT ((attrs->>'v1_stable_id'))
    WHERE attrs ? 'v1_stable_id' AND upper(sys_period) IS NULL
DO NOTHING
"""


def transform_all(category: str, spec: dict, places: dict, counts: Counter,
                  drops: Counter):
    """Read every record and run it through the transformer. No identity, no
    dedupe, no enforcement, no writes — just what the spec PRODUCES.

    Extracted so ops/spec_equivalence.py can compare emissions across a
    refactor without reproducing the read loop. A harness that re-implements
    the thing it verifies proves only that two copies agree.
    """
    transformer = TRANSFORMERS[category]
    if hasattr(transformer, "prepass"):
        # cross-record state (e.g. economic's contradictory-duplicate
        # detection) needs the whole category before the first transform
        all_recs = []
        for f in iter_v1_files(category, spec):
            all_recs.extend(_records(json.loads(read_payload(f)), spec))
        transformer.prepass(all_recs, spec, counts)
    for f in iter_v1_files(category, spec):
        payload = read_payload(f)
        for rec in _records(json.loads(payload), spec):
            if not isinstance(rec, dict):
                counts["not_a_dict"] += 1
                continue
            counts["records_read"] += 1
            result = transformer(rec, spec, places, counts)
            if isinstance(result, Drop):
                drops[result.reason] += 1
                continue
            for r in result:
                yield f, r


def _record_refusal(category: str, reason: str, counts: Counter,
                    drops: Counter, dry_run: bool) -> None:
    """A refused run leaves the same trace a successful one does.

    Both `raise SpecRefused` sites in `run` fire BEFORE the run report is
    written, so a category that failed its own spec check vanished from
    ops/databank-runs.ndjson with nothing to explain it — the ledger simply
    stopped. That is how 2026-10-04's `land` refusal (HDX 502 -> v1's 12-row
    fallback, correctly caught by min_records 627) left no evidence it had
    ever run. Refusals are the runs most worth reading: they are the ones
    where the floor did its job.
    """
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "category": category, "dry_run": dry_run, "status": "refused",
        "reason": reason,
        "records_read": counts.get("records_read", 0),
        "drops": dict(drops),
        "notes": {k: v for k, v in counts.items() if k != "records_read"},
    }
    try:
        with RUNS.open("a") as fh:
            fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    except OSError:
        pass          # never let the audit trail break the refusal it records


# ── the publisher's own vintage (2026-10-12) ─────────────────────────────────
# A register row (one school, one obstacle, one name on a list) has no date of
# its own: 3,834 of them were dated by the day v1 downloaded them, and the
# names roster by the first day of the war. The date that matters for such a
# dataset is the one the PUBLISHER gives it, and it belongs to the dataset, not
# to 72,835 rows that would all have to be rewritten each time it moves. A
# fetcher records it in what it writes, and every run copies it to
# dataset.attrs, with the day the run last looked:
#
#   in the raw file      "vintage", "vintage_basis", "vintage_url" at the top
#                        level or under "metadata" (a spec with one dataset),
#                        or "vintage_by_dataset": {dataset_key: {...}}
#   beside the raw file  _vintage.json: {dataset_key: {...}}, for a fetcher
#                        that stores the publisher's file untouched (T4P)
VINTAGE_KEYS = ("vintage", "vintage_basis", "vintage_url", "coverage_start")


def read_vintage(spec: dict, files, fed: dict | None = None) -> dict[str, dict]:
    """dataset_key -> what the input says about the publisher's vintage.

    `fed` maps an input file to what its records became: (dataset, indicator)
    pairs. A file that fed exactly one dataset speaks for that dataset (land's
    three files: OCHA's barrier, Peace Now's footprints, Good Shepherd's days).
    Two files that fed ONE dataset with two different dates (the barrier of
    2018 and the village boundaries of 2019, both in v1_infrastructure_hdx)
    give that dataset no single vintage: each indicator gets its own, under
    `vintage_by_indicator`. A file that fed several datasets must say which
    with `vintage_by_dataset`."""
    own = [d["key"] for d in spec.get("datasets", [])]
    out: dict[str, dict] = {}
    said: dict[str, list[tuple[dict, set]]] = defaultdict(list)

    def pick(src) -> dict | None:
        if isinstance(src, dict) and src.get("vintage"):
            return {k: str(src[k]) for k in VINTAGE_KEYS if src.get(k)}
        return None

    for f in files:
        f = Path(f)
        side = f.parent / "_vintage.json"
        if side.exists():
            try:
                for key, src in json.loads(side.read_text(encoding="utf-8")).items():
                    if key in own and pick(src):
                        out[key] = pick(src)
            except (ValueError, OSError, AttributeError):
                pass
        try:
            payload = json.loads(read_payload(f))
        except (ValueError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        became = (fed or {}).get(f) or (fed or {}).get(str(f)) or ()
        pairs = {(x, None) if isinstance(x, str) else tuple(x) for x in became}
        for holder in (payload, payload.get("metadata") or {}):
            if not isinstance(holder, dict):
                continue
            for key, src in (holder.get("vintage_by_dataset") or {}).items():
                if key in own and pick(src):
                    out[key] = pick(src)
            one = own if len(own) == 1 else sorted({ds for ds, _ in pairs})
            if len(one) == 1 and pick(holder):
                said[one[0]].append((pick(holder), {i for ds, i in pairs if i}))
                break
    for ds, items in said.items():
        if ds in out:
            continue
        if len({v["vintage"] for v, _ in items}) == 1:
            out[ds] = items[0][0]
        else:
            by_ind = {ind: v for v, inds in items for ind in sorted(inds)}
            if by_ind:
                out[ds] = {"vintage_by_indicator": by_ind}
            else:
                # Events have no indicator to hang a date on. UCDP's yearly
                # release (extracted 2026-03-30) and its monthly candidate
                # files (2026-09-20) feed one dataset, and an empty
                # `vintage_by_indicator` would have taken the dataset's
                # vintage away (2026-10-13). The dataset is as new as its
                # newest file, and the basis names the others.
                newest = max((v for v, _ in items), key=lambda v: v["vintage"])
                others = sorted({v["vintage"] for v, _ in items} - {newest["vintage"]})
                out[ds] = {**newest, "vintage_basis": (
                    (newest.get("vintage_basis") or "").rstrip(". ")
                    + "; the newest of this dataset's files (the others: "
                    + ", ".join(others) + ")")}
    return out


def apply_vintage(cur, vintage: dict[str, dict]) -> int:
    """Copy it to dataset.attrs, with today as the day we last looked. One
    statement per dataset, and it writes only when something differs."""
    n = 0
    today = datetime.now(timezone.utc).date().isoformat()
    for key, v in vintage.items():
        new = {**v, "vintage_checked_at": today}
        # a dataset whose indicators have their own dates has no single one
        drop = "- 'vintage'" if "vintage_by_indicator" in v else ""
        cur.execute(f"""UPDATE dataset SET attrs = (attrs {drop}) || %s::jsonb
                         WHERE key = %s AND NOT (attrs @> %s::jsonb)""",
                    (json.dumps(new), key, json.dumps(new)))
        n += cur.rowcount
    return n


# How a row stops being current. `tstzrange(lower(sys_period), now())` is an
# EMPTY range for a row born in this same transaction (its lower bound IS
# now()), and an empty range has no upper bound: the row stays "current" and
# the row meant to replace it hits the unique index. It bit the Ministry
# re-read on 2026-10-11 (two bulletins for one day in one transaction) and the
# same expression stood here and in three repair scripts, waiting for the first
# run that revises a row it has just written. A row from an earlier
# transaction closes at now() exactly as before, so its successor still abuts.
CLOSE_NOW = ("tstzrange(lower(sys_period), "
             "greatest(now(), lower(sys_period) + interval '1 microsecond'))")


def run(category: str, dry_run: bool = False, allow_absent: int | None = None) -> dict:
    """`allow_absent` raises the absent-upstream ceiling, and the ceiling on
    rows revised under a new identity, for THIS run only: the way a one-time
    transition (health's change of identity, 2026-10-12; funding's parked
    parents, 2026-10-13) is made by hand without writing a ceiling into the
    spec that every later night would inherit."""
    spec = load_spec(category)
    if category not in TRANSFORMERS:
        raise SpecRefused(f"{category}: spec is reviewed but no transformer "
                          "implements it yet — implement, do not improvise")
    transformer = TRANSFORMERS[category]
    # `transform:` is a CHECKED declaration, not a label. A half-migrated
    # format where the document says `engine` and a hand-written transformer
    # actually runs is worse than an unmigrated one: the reader is now
    # confidently wrong instead of uninformed.
    declared = spec.get("transform")
    actual = ("engine" if transformer is t_engine
              else f"python:{transformer.__name__}")
    if declared and declared != actual:
        raise SpecRefused(
            f"{category}: spec declares `transform: {declared}` but "
            f"{actual} is what runs. The declaration is the promise that "
            "nothing is hidden; a wrong one is worse than none")

    counts: Counter = Counter()
    drops: Counter = Counter()
    rows: list[Row] = []
    refs: dict[Path, str] = {}
    seen_stable: set[str] = set()
    seen_said: dict[str, tuple | None] = {}

    def _says(r):
        """What an observation row states, for telling a repeat from a twin."""
        if isinstance(r, EventRow):
            return None
        return (None if r.value_num is None else float(r.value_num), r.value_text, r.unit)
    from_fallback = reads_fallback(spec)
    if from_fallback:
        counts["input_fallback"] = 1

    # Format v2 `identity:` — cross-run natural-key idempotency for datasets
    # whose v1 stable_ids are unstable (2026-08-07: v1 re-hashed after the
    # T4P heal and every floor-less register re-inserted its whole
    # generation). 044's unique index cannot see this: new hash = new row.
    # Declared identity is what the row IS, independent of v1's hashing.
    identity_spec = spec.get("identity")
    # identity → (observation_id or None, the content currently held). A row
    # already here with the SAME content is a re-fetch and is skipped; the
    # same identity with DIFFERENT content is a correction, and corrections
    # supersede.
    known_identities: dict[str, tuple[int | None, str]] = {}
    # (dataset, stable id, day) -> the current row that holds it. A row this
    # run would write under a NEW identity while its stable id and day are held
    # is refused by the stable-id index at the insert, and for a keyed dataset
    # that fails the category. A dry run never reached the insert, so it could
    # not see it: migration 101 closed one copy of the damage series on the
    # belief that the loader emits the other, every dry run stayed green, and
    # the first real night would have failed (found 2026-10-12, hours before
    # it ran). Counted before any write now, in a dry run too.
    held_stable: dict[tuple, int] = {}
    stable_clash: list[tuple[str, int]] = []
    to_supersede: list[int] = []
    revision_samples: list[str] = []

    # Events need the same protection as observations: 046's index keys on
    # v1_stable_id, so a re-hashed upstream re-inserts the whole history
    # (measured 2026-08-07: conflict re-added 8,282 events). An event's
    # natural identity is what happened, where, when, at what scale.
    # DATABANK-05 (2026-09-26): the key (type|day|place|lat|lon|metrics)
    # cannot tell two different events apart when they share all of it —
    # UCDP's two Rafah-camp deaths of 1993-12-13, one per dyad (Government of
    # Israel–PFLP, –PIJ). As a SET, the second was "already held" and a fresh
    # load dropped 764 UCDP events. Now a MULTISET: an emitted event whose
    # own stable id is held is held; the rest are matched against how MANY
    # held events share their key, and only that many are skipped. A v1
    # re-hash (new ids, same events) still skips everything; a restore or a
    # new UCDP release keeps every distinct event. No held row is re-keyed.
    known_events: Counter = Counter()
    held_event_ids: set[str] = set()

    # [emitted, located] per dataset — a whole-category floor cannot see one
    # dataset going dark inside a healthy average, and refugees declares three
    # different floors precisely because its three datasets are three
    # different kinds of thing.
    per_ds: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    # Injectivity bookkeeping for the invariant below.
    emitted_identities: set[str] = set()
    # dataset → the values of its `identity.revises_by` attr this run emitted
    emitted_revision_ids: dict[str, set[str]] = defaultdict(set)
    identity_collisions: Counter = Counter()
    collision_samples: dict[str, list[str]] = defaultdict(list)

    def _event_identity(e) -> str:
        return "|".join([e.event_type, str(e.occurred_at)[:10],
                         str(e.place_id), str(e.lat), str(e.lon),
                         json.dumps(e.metrics, sort_keys=True)])

    # Identity is per DATASET, not per spec. That distinction is the whole
    # 2026-08-07 freeze: infrastructure.yaml holds a 730-day Gaza daily
    # series, a West Bank barrier register and a UNOSAT assessment series
    # under one identity that omitted occurred_at, so 5,840 rows collapsed to
    # 4 keys and the dataset could never write again — while the run
    # reported success. A spec may declare `identity:` once and override it
    # per dataset through the existing datasets[].overrides mechanism.
    identity_by_ds: dict[str, dict] = {}
    for _ds in spec.get("datasets", []):
        _id = ((_ds.get("overrides") or {}).get("identity")) or identity_spec
        if _id:
            identity_by_ds[_ds["key"]] = _id

    def _identity_of(r) -> str | None:
        if isinstance(r, EventRow):
            return None                 # handled by _event_identity below
        ident = identity_by_ds.get(r.dataset_key)
        if not ident:
            return None
        return identity_key_for(ident, r.dataset_key, indicator=r.indicator,
                                occurred_at=r.occurred_at,
                                place_id=r.place_id, value_num=r.value_num,
                                attrs=r.attrs)

    event_rows: list[EventRow] = []
    fed: dict[Path, set] = defaultdict(set)     # input file -> the (dataset, indicator) pairs it fed

    # ── `event_reading` (2026-10-13): events that follow their publisher ─────
    # An event used to be taken once and never touched: held under its id, it
    # was skipped whatever the publisher said about it later, and one the
    # publisher withdrew stayed current. UCDP's GED 26.1 revised 1,115 of the
    # 7,638 held events, withdrew 18 and added 493 dated 1989 to 2024 — and the
    # additions are only right beside the revisions (the deaths moved from
    # month-long rows into the new events), so none of it could be loaded.
    # A dataset that declares `event_reading` says: these files are the
    # publisher's WHOLE current reading of it. Then an emitted event whose id
    # is held and states something else replaces what is held; a held event
    # the reading no longer contains is retracted (kept, not served); and the
    # same dataset's records in any other input file are an older reading and
    # are not emitted at all. All or none of the files must be there: a
    # machine that has never fetched reads the frozen copy as before, and half
    # a reading is refused.
    reading_rule, reading_files = event_readings(spec, category, from_fallback)
    reading_decision: dict[str, dict] = {}
    reading_over: list[str] = []
    with connect() as conn:
        places = load_places(conn)
        places["_pip"] = PointResolver(conn)
        with conn.cursor() as cur:
            cur.execute("""SELECT source_refs->>'v1_canonical_key', place_id
                           FROM place WHERE source_refs ? 'v1_canonical_key'
                             AND merged_into IS NULL""")
            places["_v1key"] = dict(cur.fetchall())
            cur.execute("SELECT key, commercial_use FROM source")
            places["_commercial"] = dict(cur.fetchall())
            # Mandate-era localities, indexed by coordinate. v1 USED to carry
            # location.gazetteer_key and the Nakba gazetteer was re-pointed
            # against it by a one-off script; v1's rebuild has since dropped
            # that key from all 2,490 historical records (the same regression
            # that hit demolitions). Both sides came from Palestine Open Maps,
            # so the coordinates still agree — and resolving on them means a
            # reload lands correctly by itself instead of depending on a
            # follow-up script somebody has to remember.
            cur.execute("""SELECT ST_Y(geom::geometry), ST_X(geom::geometry),
                                  place_id
                           FROM place
                           WHERE geom IS NOT NULL AND merged_into IS NULL
                             AND ST_GeometryType(geom::geometry) = 'ST_Point'
                             AND (attrs->>'historic' = 'mandate-palestine'
                                  OR source_refs ? 'v1_canonical_key')""")
            # formatted in Python, exactly as the transformer formats the
            # record's own coordinates — one renderer, same lesson as
            # identity_key_for
            places["_historic_geo"] = {(f"{a:.5f}", f"{b:.5f}"): pid
                                       for a, b, pid in cur.fetchall()}
            # what each dataset already holds, read from the STORED key
            # (052). Recomputing it in SQL is what made the first guard fail
            # open — see identity_key_for's docstring.
            if identity_by_ds:
                # identity → (observation_id, what it currently says). The
                # second half is what makes a CORRECTION distinguishable from
                # a re-fetch; without it the loader could only skip.
                cur.execute("""
                    SELECT o.identity_key, o.observation_id, o.value_num,
                           o.value_text, o.unit, o.place_id, o.attrs,
                           d.key, o.v1_stable_id, o.occurred_at::date::text
                    FROM observation o JOIN dataset d
                      ON d.dataset_id = o.dataset_id
                    WHERE d.key = ANY(%s) AND o.identity_key IS NOT NULL
                      AND upper_inf(o.sys_period)""",
                    (list(identity_by_ds),))
                for row in cur.fetchall():
                    k, oid, vn, vt, un, pid, at = row[:7]
                    known_identities[k] = (oid, content_of(
                        value_num=vn, value_text=vt, unit=un, place_id=pid,
                        attrs=at))
                    if len(row) >= 10 and row[8]:
                        held_stable[(row[7], row[8], row[9])] = oid
            # every spec, not only event-shaped ones: historical declares
            # `observation` yet emits 27 events, which were reported as new
            # every night and refused one by one at the insert
            if spec.get("datasets"):
                cur.execute(
                    "SELECT event_type, occurred_at::date::text, "
                    "       place_id::text, "
                    "       ST_Y(geom::geometry)::text, "
                    "       ST_X(geom::geometry)::text, metrics "
                    "FROM event "
                    "WHERE attrs->>'dataset_key' = ANY(%s) "
                    "  AND upper_inf(sys_period)",
                    ([ds["key"] for ds in spec["datasets"]
                      if ds["key"] not in reading_rule],))
                held_keys = []
                for et, oc, pid, lat, lon, met in cur.fetchall():
                    held_keys.append("|".join([
                        et, oc, "None" if pid is None else pid,
                        "None" if lat is None else lat,
                        "None" if lon is None else lon,
                        json.dumps(met, sort_keys=True)]))
                cur.execute(
                    "SELECT attrs->>'v1_stable_id' FROM event "
                    "WHERE attrs->>'dataset_key' = ANY(%s) "
                    "  AND upper_inf(sys_period) AND attrs ? 'v1_stable_id'",
                    ([ds["key"] for ds in spec["datasets"]],))
                held_event_ids = {row[0] for row in cur.fetchall()}
                known_events = Counter(held_keys)
        for f, r in transform_all(category, spec, places, counts, drops):
            if (isinstance(r, EventRow) and r.dataset_key in reading_rule
                    and f not in reading_files[r.dataset_key]):
                counts[f"event_older_reading_not_emitted:{r.dataset_key}"] += 1
                continue
            fed[f].add((r.dataset_key, None if isinstance(r, EventRow) else r.indicator))
            if f not in refs:
                refs[f] = bronze.put(f"v1_{category}", read_payload(f),
                                     url=f"file://{f}").ref
            if r.v1_stable_id in seen_stable:
                counts["deduped"] += 1
                # THE SAME ID SAYING TWO THINGS IS NOT A DUPLICATE (2026-10-12).
                # A repeat of an id is dropped as a re-statement, and until now
                # nothing looked at whether it said the same thing: UNHCR's
                # doubled demographics cells (65 and 60 under one id) lost their
                # second row silently on the first load. It is counted, and for
                # a dataset that declares an identity it is the injectivity
                # failure it always was, on the first load and in a dry run too.
                first = seen_said.get(r.v1_stable_id)
                if first is not None and first != _says(r):
                    counts["deduped_but_said_otherwise"] += 1
                    if identity_by_ds.get(r.dataset_key):
                        identity_collisions[r.dataset_key] += 1
                        if len(collision_samples[r.dataset_key]) < 3:
                            collision_samples[r.dataset_key].append(
                                f"{r.v1_stable_id}: {first} vs {_says(r)}")
                continue
            # Marked HERE, not after the already-held skip below: a real run
            # skipped a held row before marking it, so its in-file twin was not
            # a "duplicate" on later nights and met the identity check instead
            # (192 collisions for UNHCR from its second night), while a dry run
            # and a first load deduped it. One rule for every mode.
            seen_stable.add(r.v1_stable_id)
            seen_said[r.v1_stable_id] = _says(r)
            # resolution floors judge what the TRANSFORM produced, not
            # what happened to be new this run — otherwise a healthy
            # no-op sync fails on a handful of unresolved stragglers
            counts["decided_total"] += 1
            if r.located:
                counts["located_total"] += 1
            # the same rule one level down. Counted after the already-held
            # skip (2026-08-08 to 09-21), a per-dataset floor judged only the
            # night's new rows: refugees failed four nights on IDMC "3/4"
            # while the dataset stood at 336/339, and a dataset already held
            # could never fail at all
            per_ds[r.dataset_key][0] += 1
            per_ds[r.dataset_key][1] += bool(r.located)
            if not isinstance(r, EventRow):
                counts["observations_emitted_full"] += 1
            ident = _identity_of(r)
            if ident is not None:
                # THE INVARIANT: an identity that cannot tell two rows
                # of THIS run apart cannot tell them apart across runs
                # either — it silently freezes the dataset. Recorded
                # per dataset here and enforced before any write.
                if ident in emitted_identities:
                    identity_collisions[r.dataset_key] += 1
                    if len(collision_samples[r.dataset_key]) < 3:
                        collision_samples[r.dataset_key].append(ident)
                emitted_identities.add(ident)
                _rev = (identity_by_ds.get(r.dataset_key, {}) or {}).get("revises_by")
                if _rev and (r.attrs or {}).get(_rev) is not None:
                    emitted_revision_ids[r.dataset_key].add(str(r.attrs[_rev]))
                indistinct = (identity_by_ds.get(r.dataset_key, {}) or {}).get(
                    "collision_kind") == "indistinguishable"
                if ident in known_identities and indistinct and \
                        known_identities[ident][0] is None:
                    # DATABANK-04 (2026-09-26). The map is seeded from the DB
                    # AND from this run's own rows, and an `indistinguishable`
                    # dataset stores no key — so the only entries it ever has
                    # are this run's. Skipping on them dropped every identical
                    # copy after the first: on a fresh load or a restore,
                    # aid_access wrote 25,872 of its 50,059 lorries and
                    # reported success. These copies are DIFFERENT things the
                    # source records identically; each goes to the write,
                    # where 044's stable-id index still refuses a re-fetch.
                    counts["indistinguishable_copies_kept"] += 1
                elif ident in known_identities:
                    oid, held = known_identities[ident]
                    fresh = content_of(
                        value_num=r.value_num, value_text=r.value_text,
                        unit=r.unit, place_id=r.place_id, attrs=r.attrs)
                    if fresh == held:
                        # already in the databank under an older v1 hash —
                        # the 2026-08-07 doubling, prevented at the source.
                        # Counted apart from a copy inside this very run,
                        # which is a different fact about the source.
                        counts["identity_already_held" if oid is not None
                               else "intra_run_duplicate_collapsed"] += 1
                        # a DRY RUN reports what the spec PRODUCES (the
                        # arithmetic under test); only a real run drops
                        # the already-held rows. emitted − already_held
                        # is what a write would insert.
                        if not dry_run:
                            continue
                    elif oid is None:
                        # DATABANK-V09 (2026-09-26): the same identity twice
                        # in ONE run with different content (a spec that
                        # allows measured collisions). There is nothing held
                        # to supersede — appending None and inserting both
                        # rows under one key made 052's index abort the
                        # transaction mid-run. The first copy stands; the
                        # count says how often the source disagreed with
                        # itself.
                        counts["intra_run_conflict_kept_first"] += 1
                        if not dry_run:
                            continue
                    elif from_fallback:
                        # The fallback is an OLD answer (a frozen corpus
                        # standing in for a fetch that has not happened on
                        # this machine). It may fill a hole; it may never
                        # overwrite what a live fetch put here — or deleting
                        # data/raw/ would roll the series back to June.
                        counts["fallback_revision_refused"] += 1
                        continue
                    else:
                        # A CORRECTION. Same row, different reading — the
                        # publisher revised it. Supersede what we hold and
                        # write the new one, which is the law this databank
                        # is built on and which the identity guard had
                        # quietly suspended: OONI revised eight days upward
                        # and the databank kept the stale numbers while
                        # reporting a clean run.
                        counts["revisions"] += 1
                        if len(revision_samples) < 5:
                            revision_samples.append(
                                f"{r.indicator}@{str(r.occurred_at)[:10]}: "
                                f"{held[:90]} → {fresh[:90]}")
                        if not dry_run:
                            to_supersede.append(oid)
                        known_identities[ident] = (oid, fresh)
                else:
                    known_identities[ident] = (None, content_of(
                        value_num=r.value_num, value_text=r.value_text,
                        unit=r.unit, place_id=r.place_id, attrs=r.attrs))
                    clash = held_stable.get(
                        (r.dataset_key, r.v1_stable_id, str(r.occurred_at)[:10]))
                    if clash is not None and not indistinct:
                        stable_clash.append((r.dataset_key, clash))
            # events are decided after the whole run is read (below): which
            # of two same-key events is "the held one" must not depend on
            # the order the file lists them in
            if ident is not None and (
                    identity_by_ds.get(r.dataset_key, {})
                    .get("collision_kind") != "indistinguishable"):
                # Only `indistinguishable` datasets go keyless — their
                # duplicates are DIFFERENT things the source records
                # identically (aid_access lorries), so collapsing them
                # would delete real data. A `duplicate_fact` dataset
                # keeps its key and lets 052 refuse the second copy,
                # which is the dedup we want. Getting this backwards
                # cost IDMC a silent doubling on 2026-08-07.
                r.identity_key = ident
            seen_stable.add(r.v1_stable_id)
            r.raw_ref = refs[f]
            (event_rows if isinstance(r, EventRow) else rows).append(r)

        # ── events: held or new, by count (DATABANK-05) ─────────────────────
        # Pass 1: an event whose own stable id is held is that held row, and
        # uses up one held copy of its key. Pass 2: the rest match the held
        # copies left, one each (a v1 re-hash). Whatever is left is new —
        # including every distinct event of a same-key pair: records with
        # distinct stable ids are distinct records (identical records were
        # already deduped by stable id above), so nothing collapses in-run.
        # `event_identity.match: stable_id` (2026-10-12): the ids ARE the
        # publisher's event numbers, so nothing but the id decides. The count
        # fallback protects against a re-hash that cannot happen here, and it
        # would do harm: 7,400 Protection incidents carry no coordinates and
        # mostly no victims, so hundreds share one key with each other and with
        # the retired copies of an incident (status superseded, still listed).
        by_id_only = (spec.get("event_identity") or {}).get("match") == "stable_id"
        rekey_problem = None
        if reading_rule:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_id, attrs->>'v1_stable_id', status::text, correction_note, "
                    "       event_type, occurred_at::date::text, occurred_precision::text, "
                    "       ST_Y(geom::geometry), ST_X(geom::geometry), metrics, attrs, "
                    "       attrs->>'dataset_key', place_id "
                    "FROM event WHERE attrs->>'dataset_key' = ANY(%s) "
                    "  AND upper_inf(sys_period) AND attrs ? 'v1_stable_id'",
                    (list(reading_rule),))
                held_by_ds: dict[str, dict] = defaultdict(dict)
                for (eid, sid, st, note, et, day, prec, la, lo, met, at, dsk,
                     pid) in cur.fetchall():
                    held_by_ds[dsk][sid] = HeldEvent(eid, st, note, et, day, prec, la, lo,
                                                     met or {}, at or {}, pid)
            others = []
            emitted_by_ds: dict[str, list] = defaultdict(list)
            for e in event_rows:
                (emitted_by_ds[e.dataset_key] if e.dataset_key in reading_rule
                 else others).append(e)
            kept = []
            for ds_key, rule in reading_rule.items():
                d = decide_event_reading(held_by_ds[ds_key], emitted_by_ds[ds_key], rule)
                reading_decision[ds_key] = d
                n_held = sum(1 for h in held_by_ds[ds_key].values() if h.status == "believed")
                counts["event_new"] += len(d["new"])
                counts["event_already_held"] += d["same"] + d["left_as_held"]
                counts[f"event_revised:{ds_key}"] = len(d["revised"])
                counts[f"event_reinstated:{ds_key}"] = len(d["reinstated"])
                counts[f"event_withdrawn:{ds_key}"] = len(d["withdrawn"])
                for what, key, default in (("revised", "max_revised", 0.05),
                                           ("withdrawn", "max_withdrawn", 0.01)):
                    cap = rule.get(key)
                    if cap is None:
                        cap = max(1, int(n_held * default))
                    if allow_absent is not None:
                        cap = max(cap, allow_absent)
                    if len(d[what]) > cap:
                        reading_over.append(
                            f"{ds_key}: {len(d[what])} held events {what} by the publisher's "
                            f"reading > ceiling {cap} of {n_held} — a new release or a broken "
                            "fetch, and applying it is a decision (run once by hand with "
                            "--allow-absent N); nothing is changed")
                for h, e, changed in d["revised"][:5]:
                    revision_samples.append(
                        f"event {h.event_id} {h.day}: {', '.join(changed)}")
                # a dry run reports what the spec emits; a real run inserts the new ones
                kept += emitted_by_ds[ds_key] if dry_run else d["new"]
            event_rows = others
        else:
            kept = []
        if event_rows and by_id_only and held_event_ids:
            # A night in which most of the held ids are not emitted is not a
            # night: the ids were re-keyed on one side only (the new fetch ran
            # and ops/rekey_insecurity_insight.py did not), and writing it
            # would hold every incident a second time under its new id.
            matched = sum(1 for e in event_rows if e.v1_stable_id in held_event_ids)
            if matched < 0.5 * len(held_event_ids):
                rekey_problem = (
                    f"only {matched} of {len(held_event_ids)} held event ids are in this "
                    "run's input — the held events carry other ids. Re-key them first "
                    "(ops/rekey_insecurity_insight.py); nothing is written")
        if event_rows and by_id_only:
            keep = []
            for e in event_rows:
                if e.v1_stable_id in held_event_ids:
                    counts["event_already_held"] += 1
                    if dry_run:
                        keep.append(e)
                else:
                    counts["event_new"] += 1
                    keep.append(e)
            event_rows = keep
        elif event_rows:
            keys = [_event_identity(e) for e in event_rows]
            by_id = [e.v1_stable_id in held_event_ids for e in event_rows]
            for ek, held_id in zip(keys, by_id):
                if held_id and known_events[ek] > 0:
                    known_events[ek] -= 1
            keep = []
            for e, ek, held_id in zip(event_rows, keys, by_id):
                if held_id:
                    counts["event_already_held"] += 1
                elif known_events[ek] > 0:
                    known_events[ek] -= 1
                    counts["event_already_held"] += 1
                else:
                    counts["event_new"] += 1
                    keep.append(e)
                    continue
                if dry_run:
                    keep.append(e)      # a dry run reports what the spec emits
            event_rows = keep
        event_rows = event_rows + kept

        # ── withdrawn upstream (DATABANK-V08 + -02, 2026-09-26) ─────────────
        # A dataset whose input is the source's WHOLE current publication
        # (`identity.generation: complete`) holds nothing the source no longer
        # says. Before this, a held identity the run stopped emitting stayed
        # current forever: IDMC renamed three events and both names counted;
        # one night in August placed 15 UNRWA camps nowhere, the next placed
        # them again, and every camp from that night was counted twice; a
        # revised value (106 → 120 displaced) was a second row beside the
        # first. Such rows are CLOSED — sys_period ends now, the row and its
        # value stay for as_of and rollback — never deleted. A fallback input
        # is an old answer and closes nothing. The ceiling is what separates
        # a correction from a shrink: above it the run fails.
        absent: list[tuple[str, int]] = []
        absent_over: list[str] = []
        complete = {k: v for k, v in identity_by_ds.items()
                    if (v or {}).get("generation") == "complete"}
        if complete and not from_fallback:
            held_n: Counter = Counter()
            gone: dict[str, list[tuple[str, int]]] = defaultdict(list)
            # where the indicator sits in a dataset's stored key, for the
            # datasets that declare the generation complete for some
            # indicators only (the names roster beside its daily summary)
            scope = {ds: (1 + v["fields"].index("indicator"),
                          set(v["generation_indicators"]))
                     for ds, v in complete.items()
                     if v.get("generation_indicators")}
            for k, (oid, _) in known_identities.items():
                ds_key = k.split("|", 1)[0]
                if oid is None or ds_key not in complete:
                    continue
                if ds_key in scope:
                    at, wanted = scope[ds_key]
                    parts = k.split("|")
                    if len(parts) <= at or parts[at] not in wanted:
                        continue
                held_n[ds_key] += 1
                if k not in emitted_identities:
                    gone[ds_key].append((k, oid))
            for ds_key, rows_gone in gone.items():
                cap = complete[ds_key].get("max_absent")
                if cap is None:
                    cap = max(1, int(held_n[ds_key] * 0.05))
                if allow_absent is not None:
                    cap = max(cap, allow_absent)
                counts[f"absent_upstream:{ds_key}"] = len(rows_gone)
                if len(rows_gone) > cap:
                    absent_over.append(
                        f"{ds_key}: {len(rows_gone)} held rows absent upstream "
                        f"> max_absent {cap} of {held_n[ds_key]} — a shrink, "
                        f"not a correction; nothing is closed")
                else:
                    absent.extend(rows_gone)

        # ── revised under a new identity (2026-10-11) ───────────────────────
        # Some sources number their own records and then revise them in the
        # fields our identity is built from. UN FTS keeps a flow's id while
        # its decision date moves and its status goes from commitment to
        # paid; with indicator and date in the key, each revision was a second
        # current row beside the original. Measured on 2026-10-11: 26 flows
        # twice inside `paid` ($97.3 M counted that is not there), 27 inside
        # `commitment` ($103.7 M), and 17 flows live as both committed and
        # paid. A dataset that declares `identity.revises_by: <attr>` says the
        # attr is the source's own record number: a held row this run did not
        # emit, whose number the run DID emit under another identity, is the
        # older reading of the same record and is closed. A held row whose
        # number is absent from the run is left alone (that is `generation`'s
        # question, and funding's input is a window). Same ceiling and the
        # same refusal as an absent row: a run that would close more than
        # that is a re-keying, not revisions.
        revised: list[tuple[str, int]] = []
        revising = {k: v["revises_by"] for k, v in identity_by_ds.items()
                    if (v or {}).get("revises_by")}
        if revising and not from_fallback:
            held_r: Counter = Counter()
            older: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for k, (oid, held_content) in known_identities.items():
                ds_key = k.split("|", 1)[0]
                if oid is None or ds_key not in revising:
                    continue
                held_r[ds_key] += 1
                if k in emitted_identities:
                    continue
                number = (json.loads(held_content).get("a") or {}).get(revising[ds_key])
                if number is not None and str(number) in emitted_revision_ids[ds_key]:
                    older[ds_key].append((k, oid))
            for ds_key, rows_old in older.items():
                cap = identity_by_ds[ds_key].get("max_absent")
                if cap is None:
                    cap = max(1, int(held_r[ds_key] * 0.05))
                if allow_absent is not None:
                    # the same one-run lift as the absent ceiling above. Until
                    # 2026-10-13 `--allow-absent` did not reach this ceiling,
                    # so a decided re-filing (funding's 554 parked parents
                    # leaving the status series, 535 held rows against a
                    # ceiling of 521) could not be made by hand at all.
                    cap = max(cap, allow_absent)
                counts[f"revised_upstream:{ds_key}"] = len(rows_old)
                if len(rows_old) > cap:
                    absent_over.append(
                        f"{ds_key}: {len(rows_old)} held rows revised under a new "
                        f"identity > ceiling {cap} of {held_r[ds_key]} — a re-keying, "
                        f"not revisions; nothing is closed")
                else:
                    revised.extend(rows_old)

        # ── enforcement, before any write ────────────────────────────────────
        n = counts["records_read"]
        problems = []
        if n < spec["expect"]["min_records"]:
            problems.append(f"records_read {n} < expect.min_records "
                            f"{spec['expect']['min_records']}")
        max_obs = spec["expect"].get("max_observations")
        # DATABANK-V10 (2026-09-26): judged on the FULL emission. len(rows) is
        # what is left after already-held rows are skipped, so on a real night
        # it was a handful and the tripwire could never fire — only a first
        # load or a dry run measured what the spec produces.
        emitted_full = counts.get("observations_emitted_full", len(rows))
        if max_obs and emitted_full > max_obs:
            # health's failure mode: a run that "succeeds with more" has
            # failed to dedupe and must say so
            problems.append(f"emitted {emitted_full} > expect.max_observations "
                            f"{max_obs}")
        # THE INJECTIVITY INVARIANT (added 2026-08-07 after the freeze).
        # An identity that maps two distinct rows to one key does not
        # de-duplicate — it DELETES. The failure is silent by construction:
        # the second row is skipped as "already held", the run reports
        # success, and the dataset can never grow again. infrastructure sat
        # at 5,840 rows / 4 keys for a day looking perfectly healthy.
        # A spec may declare `identity.allow_collisions: <measured N>`, and
        # only a measured number — the same posture `drop:` already requires.
        for ds_key, n_coll in identity_collisions.items():
            allowed = (identity_by_ds.get(ds_key, {}) or {}).get(
                "allow_collisions", 0)
            if n_coll > allowed:
                sample = "; ".join(collision_samples[ds_key])
                problems.append(
                    f"identity is not injective for {ds_key}: {n_coll} "
                    f"collisions (allowed {allowed}) — two different rows "
                    f"share one identity, so the second can never be "
                    f"written. Samples: {sample}")
        for k in counts:
            if k.startswith(("unroutable:", "no_dataset_for_source:",
                             "governorate_unresolved:",
                             "license_order_violation")):
                problems.append(f"{k} × {counts[k]}")
        declared = {d["reason"] for d in spec.get("drop", [])} | {"unroutable"}
        for reason in drops:
            if reason not in declared:
                problems.append(f"undeclared drop reason: {reason}")
        # `decided` is enforced by the explicit failure counters above — an
        # unroutable name or unresolved governorate already fails the run.
        # Deduped rows reached a decision; they are duplicates, not failures.
        decided = counts["decided_total"] or (len(rows) + len(event_rows))
        located = counts["located_total"] or (
            sum(1 for r in rows if r.located) +
            sum(1 for r in event_rows if r.located))
        place_spec = spec.get("place", {})
        # `min_decided_pct` (default 1.0) — every record the transform RETAINS
        # must reach an error-free place decision, and a deliberate NULL is a
        # decision. It is deliberately hard to violate: an unroutable name or
        # an unresolved governorate already fails above. What it catches is the
        # ladder falling off its last rung — place_rung:exhausted, a record
        # with geo the ladder could not use and no declared floor to land on.
        # This is the key README and REVIEW have declared since 2026-08-05,
        # while all 20 specs carried `min_resolved_pct`, which nothing read.
        min_decided = place_spec.get("min_decided_pct", 1.0)
        undecided = counts.get("place_rung:exhausted", 0)
        if decided and (decided - undecided) / decided < min_decided:
            problems.append(
                f"decided {decided - undecided}/{decided} < min_decided_pct "
                f"{min_decided} — {undecided} record(s) fell off the end of "
                "the place ladder with no rung left to land on")
        min_located = place_spec.get("min_located_pct")
        if min_located and located / max(decided, 1) < min_located:
            problems.append(f"located {located}/{decided} < {min_located}")
        # PER-DATASET floors. Declared in refugees' three datasets since the
        # spec was written and read by nothing until 2026-08-08 — the same
        # dead-key shape as min_resolved_pct, one level down, which is where
        # a registry that only knew top-level keys would never have looked.
        for ds in spec.get("datasets", []):
            floor = ((ds.get("overrides") or {}).get("place") or {}).get(
                "min_located_pct")
            n_ds, loc_ds = per_ds.get(ds["key"], [0, 0])
            if floor and n_ds and loc_ds / n_ds < floor:
                problems.append(
                    f"{ds['key']}: located {loc_ds}/{n_ds} = "
                    f"{loc_ds / n_ds:.3f} < min_located_pct {floor}")
        problems.extend(absent_over)
        problems.extend(reading_over)
        if rekey_problem:
            problems.append(rekey_problem)
        # a held row this same run closes frees its stable id for its successor
        closing = set(to_supersede) | {oid for _, oid in absent} | {oid for _, oid in revised}
        clashes: Counter = Counter(ds for ds, oid in stable_clash if oid not in closing)
        for ds_key, n_clash in clashes.items():
            counts[f"stable_id_held_under_another_identity:{ds_key}"] = n_clash
            problems.append(
                f"{ds_key}: {n_clash} row(s) carry a NEW identity and the stable id and day "
                "of a row already held — the insert would be refused by the stable-id "
                "index (a key disagreement between the spec and the store, not new data)")
        if problems:
            why = f"{category}: run FAILED — " + "; ".join(problems)
            _record_refusal(category, why, counts, drops, dry_run)
            raise SpecRefused(why)

        written = events_written = closed_absent = closed_revised = 0
        events_revised = events_withdrawn = 0
        if not dry_run:
            dataset_ids = ensure_datasets(conn, spec, category)
            with conn.cursor() as cur:
                if to_supersede:
                    # Corrections FIRST, in the same transaction as the rows
                    # that replace them: 052's unique index forbids two
                    # current rows sharing a key, so the revised row can only
                    # land once the stale one has stopped being current. If
                    # anything below fails, the rollback restores the old
                    # reading — a correction is never applied halfway.
                    cur.execute(f"""
                        UPDATE observation
                           SET sys_period = {CLOSE_NOW}
                         WHERE observation_id = ANY(%s)
                           AND upper_inf(sys_period)""", (to_supersede,))
                if absent:
                    cur.execute(f"""
                        UPDATE observation
                           SET sys_period = {CLOSE_NOW}
                         WHERE observation_id = ANY(%s)
                           AND upper_inf(sys_period)""",
                        ([oid for _, oid in absent],))
                    closed_absent = cur.rowcount
                if revised:
                    cur.execute(f"""
                        UPDATE observation
                           SET sys_period = {CLOSE_NOW}
                         WHERE observation_id = ANY(%s)
                           AND upper_inf(sys_period)""",
                        ([oid for _, oid in revised],))
                    closed_revised = cur.rowcount
                sent: Counter = Counter()
                took: Counter = Counter()
                for r in rows:
                    sent[r.dataset_key] += 1
                    cur.execute(INSERT_SQL, {
                        "dataset_id": dataset_ids[r.dataset_key],
                        "place_id": r.place_id, "indicator": r.indicator,
                        "value_num": r.value_num, "value_text": r.value_text,
                        "unit": r.unit, "occurred_at": r.occurred_at,
                        "precision": r.precision, "reported_at": r.reported_at,
                        "raw_ref": getattr(r, "raw_ref", None),
                        "v1_stable_id": r.v1_stable_id,
                        "identity_key": r.identity_key,
                        "attrs": json.dumps(r.attrs, ensure_ascii=False),
                    })
                    written += cur.rowcount
                    took[r.dataset_key] += cur.rowcount
                today = datetime.now(timezone.utc).date().isoformat()
                for ds_key, d in reading_decision.items():
                    rule = reading_rule[ds_key]
                    for h, e, changed in ([(h, e, c) for h, e, c in d["revised"]]
                                          + [(h, e, None) for h, e in d["reinstated"]]):
                        note = (f"{rule['label']} {today}: the publisher's current reading "
                                + (f"replaced the one held ({', '.join(changed)}); "
                                   "the version before is in event_history"
                                   if changed is not None else
                                   "holds this event again; it had been withdrawn"))
                        cur.execute(EVENT_REVISE_SQL, {
                            "event_id": h.event_id, "event_type": e.event_type,
                            "place_id": revised_event_place(h, e, changed),
                            "lat": e.lat, "lon": e.lon,
                            "occurred_at": e.occurred_at, "precision": e.precision,
                            "confidence": e.confidence,
                            "independent_sources": e.independent_sources,
                            "metrics": json.dumps(e.metrics, ensure_ascii=False),
                            "attrs": json.dumps(revised_event_attrs(h, e, rule),
                                                ensure_ascii=False),
                            "note": note})
                        events_revised += cur.rowcount
                    if d["withdrawn"]:
                        cur.execute(
                            "UPDATE event SET status = 'retracted', correction_note = %s, "
                            "       updated_at = now() "
                            " WHERE event_id = ANY(%s) AND upper_inf(sys_period) "
                            "   AND status = 'believed'",
                            (f"{rule['label']} {today}: no longer in the publisher's current "
                             "reading; kept, not served",
                             [h.event_id for h in d["withdrawn"]]))
                        events_withdrawn += cur.rowcount
                for e in event_rows:
                    attrs = dict(e.attrs)
                    attrs["v1_stable_id"] = e.v1_stable_id
                    attrs["dataset_key"] = e.dataset_key
                    if e.raw_ref:
                        attrs["raw_ref"] = e.raw_ref
                    cur.execute(EVENT_INSERT_SQL, {
                        "event_type": e.event_type, "place_id": e.place_id,
                        "lat": e.lat, "lon": e.lon,
                        "occurred_at": e.occurred_at,
                        "precision": e.precision,
                        "confidence": e.confidence,
                        "independent_sources": e.independent_sources,
                        "metrics": json.dumps(e.metrics, ensure_ascii=False),
                        "attrs": json.dumps(attrs, ensure_ascii=False),
                    })
                    events_written += cur.rowcount
                # DATABANK-V07 (2026-09-26): a row the stable-id index refuses
                # (ON CONFLICT DO NOTHING) landed in no bucket, so a correction
                # lost that way (061's scenario) read as a clean run. Counted
                # per dataset; for a dataset with a STORED identity every such
                # row passed the identity guard as new, so a refusal means two
                # keys disagree about one record — the run fails and rolls back.
                # Keyless (indistinguishable) datasets refuse re-fetches by
                # design and are only counted.
                refused = {k: sent[k] - took[k] for k in sent if sent[k] > took[k]}
                if refused:
                    counts.update({f"refused_by_stable_id:{k}": v
                                   for k, v in refused.items()})
                keyed_refusals = {
                    k: v for k, v in refused.items()
                    if k in identity_by_ds and (identity_by_ds[k] or {}).get(
                        "collision_kind") != "indistinguishable"}
                if keyed_refusals:
                    conn.rollback()
                    why = (f"{category}: run FAILED — rows with a new identity "
                           f"refused by the stable-id index (a key disagreement, "
                           f"not a re-fetch): {keyed_refusals}; nothing written")
                    _record_refusal(category, why, counts, drops, dry_run)
                    raise SpecRefused(why)
                refused_events = len(event_rows) - events_written
                if refused_events > 0:
                    counts["events_refused_by_stable_id"] = refused_events
                # the publisher's vintage, and the day this run looked: written
                # even on a night that brought no new row, because "we read it
                # again and it had not changed" is what a register's age is
                if not from_fallback:
                    apply_vintage(cur, read_vintage(spec, refs, fed))
            conn.commit()

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "category": category, "dry_run": dry_run,
        "records_read": counts["records_read"],
        "observations_emitted": len(rows),
        "events_emitted": len(event_rows),
        "written": written, "events_written": events_written,
        "deduped": counts["deduped"],
        "drops": dict(drops),
        "located_pct": round(located / max(decided, 1), 3),
        "notes": {k: v for k, v in counts.items()
                  if k not in ("records_read", "deduped")},
    }
    vintage = read_vintage(spec, refs, fed)
    if vintage:
        report["vintage"] = {k: v.get("vintage") or {i: x.get("vintage") for i, x in
                                                     (v.get("vintage_by_indicator") or {}).items()}
                             for k, v in vintage.items()}
    if revision_samples:
        # a correction is a fact about the SOURCE, not a plumbing detail —
        # it belongs in the run record where a reader can see what moved
        report["revisions"] = revision_samples
    if absent:
        # Rollback of a night's closes, exactly:
        #   UPDATE observation SET sys_period = tstzrange(lower(sys_period), NULL)
        #    WHERE observation_id = ANY(<absent_upstream.ids>);
        report["absent_upstream"] = {
            "closed": closed_absent, "would_close": len(absent),
            "ids": [oid for _, oid in absent][:500],
            "samples": [k for k, _ in absent][:8]}
    if revised:
        # Rollback, exactly as for absent rows:
        #   UPDATE observation SET sys_period = tstzrange(lower(sys_period), NULL)
        #    WHERE observation_id = ANY(<revised_upstream.ids>);
        report["revised_upstream"] = {
            "closed": closed_revised, "would_close": len(revised),
            "ids": [oid for _, oid in revised][:500],
            "samples": [k for k, _ in revised][:8]}
    for ds_key, d in reading_decision.items():
        # Rollback of a night's event changes: each changed event's version
        # before is the newest row of event_history for its event_id;
        # a withdrawn one is `UPDATE event SET status='believed',
        # correction_note=NULL WHERE event_id = ANY(<withdrawn_ids>)`.
        report.setdefault("event_reading", {})[ds_key] = {
            "same": d["same"], "left_as_held": d["left_as_held"], "new": len(d["new"]),
            "revised": len(d["revised"]), "reinstated": len(d["reinstated"]),
            "withdrawn": len(d["withdrawn"]),
            "revised_written": events_revised, "withdrawn_written": events_withdrawn,
            "revised_ids": [h.event_id for h, _, _ in d["revised"]][:2000],
            "withdrawn_ids": [h.event_id for h in d["withdrawn"]][:500],
            "changed_fields": dict(Counter(c for _, _, ch in d["revised"] for c in ch)),
        }
    with RUNS.open("a") as fh:
        fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    return report


def run_all(dry_run: bool = False) -> int:
    """The nightly sync: every migrating category, idempotently, after v1's
    ~02:51 refresh. New upstream records get new stable_ids and land; old
    rows never change (corrections supersede in T2.4, never overwrite).
    Returns the number of failed categories — the exit code."""
    failed = []
    grew = {}
    for cat in sorted(TRANSFORMERS):
        try:
            rep = run(cat, dry_run=dry_run)
            if rep["written"] or rep["events_written"]:
                grew[cat] = rep["written"] + rep["events_written"]
        except SpecRefused as e:
            if "migrate=false" in str(e):
                continue
            print(f"FAIL {cat}: {e}", file=sys.stderr)
            failed.append(cat)
        except Exception as e:                                  # noqa: BLE001
            # DATABANK-V11 (2026-09-26): only SpecRefused was isolated, so a
            # truncated raw file (JSONDecodeError) or a constraint error in one
            # category ended the loop and every category after it went
            # unloaded that night, with nothing naming them. run() holds its
            # writes in one transaction per category, so a crash here commits
            # nothing for THIS category; the rest still load.
            import traceback
            print(f"FAIL {cat}: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            failed.append(cat)
    print(json.dumps({"grew": grew, "failed": failed}, ensure_ascii=False))
    return len(failed)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        sys.exit(run_all(dry_run="--dry-run" in sys.argv))
    if not args:
        sys.exit("usage: python -m ingest.databank <category>|--all [--dry-run]")
    allow = None
    if "--allow-absent" in sys.argv:
        allow = int(sys.argv[sys.argv.index("--allow-absent") + 1])
        args = [a for a in args if a != str(allow)]
    out = run(args[0], dry_run="--dry-run" in sys.argv, allow_absent=allow)
    print(json.dumps(out, indent=2, ensure_ascii=False))
