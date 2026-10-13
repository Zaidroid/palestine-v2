"""Fetch UCDP's Georeferenced Event Dataset (GED) for Israel and Palestine: the
yearly release, and the monthly candidate events for the months after it ends.

WHAT STOPPED, AND WHY NOTHING SAID SO. v1 took UCDP from a country extract on
HDX ("ucdp-data-for-israel"), which is GED 25.1 and ends on 2024-12-31
(measured 2026-10-12: v1's raw file and GED 25.1 hold the same 7,836 event
ids). UCDP published GED 26.1 on 2026-06-08 with 2025 in
it, and publishes candidate events every month; HDX's extract did not move, so
the store had neither 2025 nor 2026 and every freshness check passed.

WHAT THIS READS. UCDP's own bulk files, linked from its download page
(https://ucdp.uu.se/downloads/): the release zip (ged<NNN>-csv.zip, one global
CSV) and the candidate CSVs listed there (the latest quarterly bundle and the
months since). NOT the API: it answers 401 "API token required" (measured
2026-10-12) and a token is requested by e-mail; this fetcher never asks for
one. If the bulk files ever ask for an account the fetch fails and says so; it
does not look for another door.

THE SCOPE IS v1's, UNCHANGED. UCDP codes the Palestinian territories under the
country Israel (country_id 666). An event is kept when its sides, place,
first-level admin unit or conflict name mention Palestine, Gaza or the West
Bank, and its place is not in Israel proper (`region_of`); both rules are a
port of v1's scripts/sources/ucdp-conflict.js and populate-unified-data.js.

THE STABLE ID. v1's stable_id was NOT built from UCDP's event id: it is a
sha256 over the whole unified record, v1's own gazetteer enrichment included,
with `id` removed. `v1_stable_id` below reproduces all 7,638 held ids from the
frozen records, and `v1_unified_record` rebuilds every one of them from GED
25.1's own rows (measured 2026-10-12). A content hash changes when UCDP
corrects one word of a headline, so it cannot follow an event across releases;
UCDP's `id` can ("The same id number in versions 1.9 – 26.1 identifies the same
real-life event", GED codebook 26.1, section 5.1). So an event the store holds
keeps the id it is held under, looked up by UCDP id in the frozen copy of v1's
last file (data/frozen/conflict.json.gz), and every other event gets
`ucdp-ged:<UCDP id>`. A candidate event that reaches the next release keeps
its UCDP id (measured: 3,131 of the 3,150 candidate events of 2025 are in GED
26.1 under the same id), so it would keep its row.

A RELEASE IS A NEW READING OF OLD YEARS. Until 2026-10-13 the loader could not
apply one: an event whose stable id was held was skipped whatever the release
now said about it, and a held event the release no longer contained stayed
current. GED 26.1 shows why that matters (measured 2026-10-12 against the
7,638 held events): 1,115 were revised (812 of them in a field the store
holds; the rest in UCDP's source headlines and its low and high estimates,
which the store does not keep), 18 are gone, and 493 events dated 1989 to 2024
are in the release and not in the store. They belong together. October 2023
reads 10,582 deaths in GED 25.1 and 10,553 in 26.1, yet UCDP's month-long row
"Gaza Strip, October 2023" fell from 4,731 to 2,911: the deaths moved to 143
added events (1,378) and to events already there that were revised upward (473
net), while 4 events (60) were withdrawn. November is the same shape (the
month-long row 3,612 to 2,925, 83 events added with 623, the month 7,167 to
7,165). Loading the additions beside the unrevised rows would count those
deaths twice. So this fetcher writes three files, and since 2026-10-13 the
conflict spec declares the three together as UCDP's whole current reading
(`event_reading` in db/mappings/conflict.yaml): a held event that now states
something else is revised in place, and one the reading no longer holds is
retracted and kept.

  data/raw/ucdp/ged_revision.json  the release's reading of the period the
                                   store held before it: every event to
                                   2024-12-31, each marked identical, revised
                                   or not_held against v1's last file, with
                                   the held events it dropped listed in the
                                   metadata.
  data/raw/ucdp/ged.json           the release's events dated after that day:
                                   2025.
  data/raw/ucdp/candidate.json     the candidate events dated after the
                                   release's last year, tagged provisional.

The same reasoning pins the release. `LOADS_RELEASE` names the one whose events
the loader has been given; when the page lists a newer one the fetch stops and
says so (ledger outcome `pending`, exit 1), because by then the store holds
the older reading of the years it covers. Applying a release is a decision:
`--dry-run --stage DIR --any-release` shows what the new one contains. Since
2026-10-13 it is also a short one. Set `LOADS_RELEASE` (and the year in the
death series' serve warning, which tests/test_event_reading.py holds to it),
fetch, read `python -m ingest.databank conflict --dry-run` (it refuses and
says how many held events the release revises and withdraws), then run the
load once by hand with `--allow-absent N` just above that number. The nightly
ceilings (5% revised, 1% withdrawn) are sized for a month of candidate events
and refuse a release on purpose.

CANDIDATE EVENTS DRIFT, AND NOTHING HERE CAN STOP THAT. UCDP re-extracts them
("Not all events in UCDP Candidate will make it into the final UCDP GED and
new events will be added", candidate codebook 1.5). Measured on two months of
2025 against GED 26.1: of June's 334 events, 9 were dropped, 69 changed in
type, day, point or deaths, and 32 were added later; of October's 142, 8, 31
and 19. This file always holds UCDP's current reading, and the loader follows
it: the same rule revises and retracts a candidate event. Each record says `ucdp_candidate: true`, the
file it came from and UCDP's own code status, and carries no quality score.

Posture as fetchlib's: ATOMIC, FLOORED, LEDGERED. One more habit, for a 39 MB
yearly file and monthly ones: each is downloaded only when its HTTP
Last-Modified moved (a HEAD request each night), otherwise the files on disk
stand and the ledger line says `unchanged`.

LICENCE, as the publisher states it (read 2026-10-12): "All datasets are free
of charge and licensed under CC BY 4.0 — you are free to use and redistribute
them provided you cite the relevant publications listed with each dataset."
The store's grade for source `ucdp` is not this fetcher's to change.

Run: .venv/bin/python -m ops.fetch_ucdp                    # release + candidates
     .venv/bin/python -m ops.fetch_ucdp --dry-run          # print, write nothing
     .venv/bin/python -m ops.fetch_ucdp --dry-run --stage DIR
     .venv/bin/python -m ops.fetch_ucdp --force            # re-read an unchanged release
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import re
import sys
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

RAW = fl.ROOT / "data" / "raw" / "ucdp"
FROZEN = fl.ROOT / "data" / "frozen" / "conflict.json.gz"
DOWNLOADS = "https://ucdp.uu.se/downloads/"
COUNTRY_ID = "666"                   # Israel, which is where UCDP codes Palestine
SOURCE_NAME = "UCDP-GED"             # EXACTLY as conflict.yaml routes it
ORGANIZATION = "Uppsala Conflict Data Program"
LICENSE = "CC BY 4.0"
PARSER = 2                           # bump to make an unchanged release re-read

# The release whose events the loader has been given. A newer one on the page
# stops the fetch (see the docstring): it re-reads years the store holds.
LOADS_RELEASE = "26.1"

# What a release says about itself and cannot be read off the CSV: the day UCDP
# extracted it (title page of that release's codebook) and the yearly paper
# its download entry asks to be cited. A PDF is not read at night; a release
# this table does not know falls back to the file's HTTP Last-Modified and a
# pointer to the download page, and says so.
RELEASES = {
    "26.1": {
        "extracted": "2026-03-30",
        "codebook": "https://ucdp.uu.se/downloads/ged/ged261.pdf",
        "cite": "Davies, Pettersson and Öberg (2026), Organized violence 1989–2025, and "
                "violent political protests, Journal of Peace Research, "
                "https://doi.org/10.1093/jopres/xjag046",
    },
}
GED_PAPER = ("Sundberg and Melander (2013), Introducing the UCDP Georeferenced Event "
             "Dataset, Journal of Peace Research 50(4)")

# Floors. The release: 11,292 events in scope on 2026-10-12 (GED 26.1), and a
# release has not shrunk by more than 18 events of 7,821 (25.1 to 26.1), so
# anything under nine tenths of that is a broken read. The candidates are
# floored against what is already on disk for the same release, because their
# honest size depends on the month of the year.
RELEASE_FLOOR = 10_000
CANDIDATE_KEEP = 0.8

TYPE_OF_VIOLENCE = {"1": "state_based", "2": "non_state", "3": "one_sided"}

_RELEASE = re.compile(r"/ged/ged(\d{2})(\d)-csv\.zip$")
_CANDIDATE = re.compile(r"/candidateged/GEDEvent_v(\d+(?:_\d+)+)\.csv$", re.I)
_HREF = re.compile(r'href="([^"]+)"')

csv.field_size_limit(1 << 30)        # source_article runs to tens of kilobytes


class NewRelease(Exception):
    """The page lists a release this fetcher has not been told to load."""


# ── the download page ────────────────────────────────────────────────────────

def parse_downloads_page(html: str) -> dict:
    """The release zip and the candidate CSVs the page links to.

    Returns {"release": {"version", "url"}, "candidates": [{"version", "url"}]}.
    The highest release listed wins; candidates keep the page's order."""
    releases, candidates, seen = [], [], set()
    for href in _HREF.findall(html):
        url = urljoin(DOWNLOADS, href)
        if url in seen:
            continue
        seen.add(url)
        m = _RELEASE.search(url)
        if m:
            releases.append(((int(m.group(1)), int(m.group(2))), url))
            continue
        m = _CANDIDATE.search(url)
        if m:
            candidates.append({"version": m.group(1).replace("_", "."), "url": url})
    if not releases:
        raise ValueError("the UCDP download page links to no GED release csv")
    (major, minor), url = max(releases)
    return {"release": {"version": f"{major}.{minor}", "url": url},
            "candidates": candidates}


# ── scope: v1's two rules, ported ────────────────────────────────────────────

def is_palestinian(row: dict) -> bool:
    blob = " ".join(row.get(k) or "" for k in (
        "side_a", "side_b", "where_coordinates", "adm_1", "conflict_name")).lower()
    return "palest" in blob or "gaza" in blob or "west bank" in blob


def region_of(row: dict) -> str:
    blob = f"{row.get('where_coordinates') or ''} {row.get('adm_1') or ''}".lower()
    if "gaza" in blob:
        return "Gaza Strip"
    if "west bank" in blob:
        return "West Bank"
    if "jerusalem" in blob:
        return "East Jerusalem"
    if "israel" in blob:
        return "Israel"
    return "Palestine"       # a point inside Israel that names no district


def in_scope(row: dict) -> bool:
    return (row.get("country_id") == COUNTRY_ID and is_palestinian(row)
            and bool(_day(row)) and region_of(row) != "Israel")


# ── a CSV row, read the way v1 read it ───────────────────────────────────────

def _uid(row: dict) -> str:
    return str(row["id"]).strip()


def _day(row: dict) -> str:
    return (row.get("date_start") or "")[:10]


def _int(v) -> int:
    """JavaScript's `parseInt(v, 10) || 0`."""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _where(row: dict) -> str:
    return row.get("where_coordinates") or row.get("where_description") or ""


def _deaths(row: dict) -> dict:
    return {k: _int(row.get(k)) for k in (
        "deaths_a", "deaths_b", "deaths_civilians", "deaths_unknown")}


def read_events(fh) -> tuple[list[dict], dict]:
    """Rows of country 666 from one GED-format CSV, and what the file held.

    `fh` is a binary file object. The whole global file is walked (418,000 rows
    for 26.1) because the release's last year, which decides the candidate
    events it already covers, is a fact about every row."""
    text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
    rows, n, last_year = [], 0, 0
    for row in csv.DictReader(text):
        n += 1
        try:
            last_year = max(last_year, int(row.get("year") or 0))
        except ValueError:
            pass
        if row.get("country_id") == COUNTRY_ID:
            rows.append(row)
    return rows, {"rows_global": n, "last_year": last_year}


# ── the record t_conflict reads ──────────────────────────────────────────────

def stable_id_for(ucdp_id: str, held: dict) -> str:
    """The id the store holds this event under, or a new one from UCDP's id."""
    rec = held.get(str(ucdp_id))
    return rec["stable_id"] if rec else f"ucdp-ged:{ucdp_id}"


def to_record(row: dict, *, held: dict, url: str, fetched_at: str,
              release: str | None = None, candidate: str | None = None) -> dict:
    """One GED row as the unified conflict record t_conflict transforms.

    Exactly one of `release` / `candidate` names where the row came from."""
    if bool(release) == bool(candidate):
        raise ValueError("a UCDP row is from a release or a candidate file, not both")
    uid = _uid(row)
    d = _deaths(row)
    lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
    where = _where(row)
    day, end = _day(row), (row.get("date_end") or "")[:10]
    rec = {
        "id": f"ucdp-{uid}",
        "stable_id": stable_id_for(uid, held),
        "date": day,
        "category": "conflict",
        "event_type": TYPE_OF_VIOLENCE.get(row.get("type_of_violence"), "unknown"),
        "location": {"name": where or "Unknown",
                     "governorate": row.get("adm_2") or None,
                     "region": region_of(row), "lat": lat, "lon": lon,
                     "precision": "point" if lat else "region"},
        "metrics": {"killed": sum(d.values()), "injured": 0, "displaced": 0,
                    "affected": 0, "unit": "persons"},
        "name": where or None,
        "actors": [a for a in (row.get("side_a"), row.get("side_b")) if a],
        **d,
        "conflict_name": row.get("conflict_name"),
        "dyad_name": row.get("dyad_name"),
        "description": row.get("source_headline") or None,   # stays out of attrs
        "ucdp_id": uid,
        "ucdp_relid": row.get("relid"),
        "ucdp_date_prec": _int(row.get("date_prec")) or None,
        "ucdp_where_prec": _int(row.get("where_prec")) or None,
        "ucdp_date_end": end if end and end != day else None,
        "ucdp_best": _int(row.get("best")),
        "ucdp_low": _int(row.get("low")),
        "ucdp_high": _int(row.get("high")),
        "sources": [{"name": SOURCE_NAME, "organization": ORGANIZATION,
                     "url": url, "license": LICENSE, "fetched_at": fetched_at}],
    }
    if release:
        rec["ucdp_release"] = release
        rec["quality"] = {"score": 0.95}     # what every held UCDP event carries
    else:
        rec["ucdp_candidate"] = True
        rec["ucdp_candidate_version"] = candidate
        rec["ucdp_code_status"] = row.get("code_status") or None
    return rec


# ── how v1 built the ids the store holds ─────────────────────────────────────

def v1_unified_record(row: dict, enrichment: dict | None = None) -> dict:
    """v1's unified conflict record for a GED row, byte for byte.

    A port of ucdp-conflict.js (CSV row to raw event) and processUCDPConflict
    (raw event to unified record). `enrichment` is the frozen record's
    `location`: v1's attach-locations pass afterwards filled every location key
    the record had left empty (gazetteer_key, admin1, admin2, admin2_pcode, and
    `governorate` where UCDP names none) from its own gazetteer, never
    overwriting. That cannot be recomputed here, so it is taken from the frozen
    record of the same event, under the same rule."""
    d = _deaths(row)
    total = sum(d.values())
    best = _float(row.get("best"))
    best = int(best) if best is not None else 0
    lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
    where = _where(row)
    side_a, side_b = row.get("side_a"), row.get("side_b")
    loc = {"name": where or "Unknown", "governorate": row.get("adm_2") or None,
           "region": region_of(row), "lat": lat, "lon": lon,
           "precision": "point" if lat else "region"}
    for k, v in (enrichment or {}).items():
        if loc.get(k) is None and v is not None:
            loc[k] = v
    return {
        "id": f"ucdp-{row['id']}",
        "date": _day(row),
        "category": "conflict",
        "event_type": TYPE_OF_VIOLENCE.get(row.get("type_of_violence")) or "state_based",
        "schema_version": "3.0.0",
        "location": loc,
        "metrics": {"killed": total, "injured": 0, "displaced": 0, "affected": 0,
                    "demolished": 0, "detained": 0, "count": best or total,
                    "value": best or total, "unit": "persons"},
        "description": row.get("source_headline")
        or f"{side_a} vs {side_b} — {where} ({_int(row.get('year'))})",
        "actors": [a for a in (side_a, side_b) if a],
        "severity_index": min(10, math.ceil((best or 1) / 5)),
        **d,
        "conflict_name": row.get("conflict_name"),
        "dyad_name": row.get("dyad_name"),
        "quality": {"score": 0.95, "completeness": 1, "consistency": 1,
                    "accuracy": 1 if row.get("event_clarity") == "1" else 0.85,
                    "confidence": "high", "verified": True},
        "sources": [{"name": SOURCE_NAME, "organization": ORGANIZATION,
                     "url": "https://ucdp.uu.se/", "license": "CC-BY-IGO"}],
    }


def _js(v):
    """A value as JSON.stringify would write it: keys sorted, 32.0 as 32."""
    if isinstance(v, dict):
        return {k: _js(v[k]) for k in sorted(v)}
    if isinstance(v, list):
        return [_js(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def v1_stable_id(rec: dict) -> str:
    """v1's stable_id (scripts/utils/stable-id.js): sha256 of the record's
    canonical JSON without `id`, `stable_id`, each source's `fetched_at` and
    two derived temporal fields; the first 32 hex characters. UCDP's own event
    id is among the fields REMOVED, which is why this id cannot follow an
    event whose content a new release revises."""
    scrubbed = {}
    for k, v in rec.items():
        if k in ("stable_id", "id"):
            continue
        if k == "temporal_context" and isinstance(v, dict):
            v = {a: b for a, b in v.items()
                 if a not in ("days_since_baseline", "baseline_period")}
        elif k == "sources" and isinstance(v, list):
            v = [{a: b for a, b in s.items() if a != "fetched_at"}
                 if isinstance(s, dict) else s for s in v]
        scrubbed[k] = v
    canonical = json.dumps(_js(scrubbed), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def load_held(path: Path = FROZEN) -> dict:
    """UCDP event id → the frozen v1 record the store holds it under."""
    if not path.exists():
        return {}
    payload = json.loads(gzip.decompress(path.read_bytes()))
    return {r["id"].split("-", 1)[1]: r for r in payload.get("data") or []
            if isinstance(r, dict) and str(r.get("id", "")).startswith("ucdp-")
            and ((r.get("sources") or [{}])[0].get("name") == SOURCE_NAME)}


def held_through(held: dict) -> str:
    """The last day the store holds a UCDP event for ('' when it holds none)."""
    return max((r["date"] for r in held.values()), default="")


# What the store keeps of an event, by where a change to it would show.
_STORED = (("day", lambda r: r["date"]),
           ("type", lambda r: r["event_type"]),
           ("point", lambda r: (r["location"]["lat"], r["location"]["lon"])),
           ("killed", lambda r: r["metrics"]["killed"]),
           ("deaths_split", lambda r: (r["deaths_a"], r["deaths_b"],
                                       r["deaths_civilians"], r["deaths_unknown"])),
           ("dyad", lambda r: r["dyad_name"]),
           ("conflict", lambda r: r["conflict_name"]),
           ("place_name", lambda r: r["location"]["name"]))
_NOT_STORED = (("governorate", lambda r: r["location"]["governorate"]),
               ("headline", lambda r: r["description"]))


def compare_with_held(scoped: list[dict], held: dict) -> tuple[dict, dict]:
    """What a release did to the events the store holds, by UCDP id.

    `scoped` are the release's rows in scope. Returns the summary that goes
    into ged_revision.json and {ucdp id: "identical" | "revised" | "not_held"}
    for every scoped row dated inside the held period or held. An event is
    identical when v1's hash of the release's row (with the frozen record's
    enrichment) is still the held id; otherwise the release revised it."""
    by_id = {_uid(r): r for r in scoped}
    end = held_through(held)
    status, fields, samples = {}, Counter(), []
    killed_then = killed_now = 0
    for uid, old in held.items():
        row = by_id.get(uid)
        if row is None:
            continue
        new = v1_unified_record(row, old.get("location"))
        killed_then += old["metrics"]["killed"]
        killed_now += new["metrics"]["killed"]
        if v1_stable_id(new) == old["stable_id"]:
            status[uid] = "identical"
            continue
        status[uid] = "revised"
        stored = [name for name, get in _STORED if get(new) != get(old)]
        other = [name for name, get in _NOT_STORED if get(new) != get(old)]
        fields.update(stored + other)
        if stored:
            fields["any_stored_field"] += 1
        if {"day", "type", "killed"} & set(stored) and len(samples) < 5:
            samples.append({"ucdp_id": uid, "stable_id": old["stable_id"],
                            "place": old["location"]["name"],
                            "day": [old["date"], new["date"]],
                            "type": [old["event_type"], new["event_type"]],
                            "killed": [old["metrics"]["killed"], new["metrics"]["killed"]]})
    absent = sorted((uid for uid in held if uid not in by_id), key=int)
    # v1's hash could not tell two UCDP events apart when every field it read
    # was the same, and v1 kept one of each such group: the others were in the
    # release it read and never reached the store. `same_content` counts the
    # release's unheld events that today read the same as a held one; the rest
    # are unheld for another reason (the release added them, or it revised one
    # of a pair).
    kept = {v1_stable_id(v1_unified_record(by_id[u])) for u in held if u in by_id}
    unheld = [r for uid, r in by_id.items() if uid not in held and _day(r) <= end]
    for r in unheld:
        status[_uid(r)] = "not_held"
    twins = sum(1 for r in unheld if v1_stable_id(v1_unified_record(r)) in kept)
    n = Counter(status.values())
    return {
        "frozen_corpus_events": len(held),
        "held_through": end,
        "in_release": n["identical"] + n["revised"],
        "identical": n["identical"],
        "revised": n["revised"],
        "revised_fields": dict(sorted(fields.items())),
        "revised_samples": samples,
        "killed_as_held": killed_then,
        "killed_as_release_reads_them": killed_now,
        "absent_from_release": len(absent),
        "absent_killed": sum(held[u]["metrics"]["killed"] for u in absent),
        "absent": [{"ucdp_id": u, "stable_id": held[u]["stable_id"],
                    "day": held[u]["date"], "place": held[u]["location"]["name"],
                    "killed": held[u]["metrics"]["killed"]} for u in absent[:100]],
        "not_held": len(unheld),
        "not_held_killed": sum(sum(_deaths(r).values()) for r in unheld),
        "not_held_same_content_as_a_held_event": twins,
        "not_held_by_year": dict(sorted(Counter(_day(r)[:4] for r in unheld).items())),
    }, status


# ── http ─────────────────────────────────────────────────────────────────────

def _open(url: str, method: str = "GET", timeout: int = 300):
    req = urllib.request.Request(url, headers={"User-Agent": fl.UA}, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def _head(url: str) -> dict:
    with _open(url, "HEAD", 60) as r:
        return {"last_modified": r.headers.get("Last-Modified"),
                "etag": r.headers.get("ETag")}


def _get(url: str) -> tuple[bytes, dict]:
    with _open(url) as r:
        return r.read(), {"last_modified": r.headers.get("Last-Modified"),
                          "etag": r.headers.get("ETag")}


def _published(last_modified: str | None) -> str | None:
    """An HTTP Last-Modified as a UTC day."""
    try:
        return parsedate_to_datetime(last_modified).astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return None


def _on_disk(name: str) -> dict:
    try:
        return json.loads((RAW / name).read_text())
    except (OSError, ValueError):
        return {}


def _frozen_sha() -> str | None:
    return hashlib.sha256(FROZEN.read_bytes()).hexdigest()[:16] if FROZEN.exists() else None


# ── the release ──────────────────────────────────────────────────────────────

def release_csv(blob: bytes):
    """The one CSV inside a release zip, as a binary file object."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if len(names) != 1:
        raise ValueError(f"expected one csv in the release zip, found {names}")
    return z.open(names[0]), names[0]


def build_release(rows: list[dict], seen: dict, *, version: str, url: str,
                  head: dict, held: dict, fetched_at: str) -> tuple[dict, dict]:
    """(ged.json, ged_revision.json) from the release's country-666 rows.

    The first holds the events dated after everything the store holds; the
    second holds the release's reading of the held period and is not loaded."""
    scoped = [r for r in rows if in_scope(r)]
    summary, status = compare_with_held(scoped, held)
    end = summary["held_through"]
    after, inside = [], []
    for r in scoped:
        rec = to_record(r, held=held, url=url, fetched_at=fetched_at, release=version)
        if _uid(r) in status:
            rec["ucdp_vs_held"] = status[_uid(r)]
            inside.append(rec)
        else:
            after.append(rec)
    for recs in (after, inside):
        recs.sort(key=lambda r: (r["date"], int(r["ucdp_id"])))
    known = RELEASES.get(version) or {}
    extracted, codebook = known.get("extracted"), known.get("codebook")
    published = _published(head.get("last_modified"))
    common = {
        "fetched_at": fetched_at,
        "source": f"UCDP Georeferenced Event Dataset (GED) Global version {version}",
        "organization": f"{ORGANIZATION}, Uppsala University",
        "source_url": DOWNLOADS,
        "release": version,
        "release_url": url,
        "http_last_modified": head.get("last_modified"),
        "http_etag": head.get("etag"),
        "parser": PARSER,
        "frozen_sha": _frozen_sha(),
        "vintage": extracted or published,
        "vintage_basis": (
            f"GED codebook {version}, title page: 'Data extracted from UCDP systems on "
            f"{extracted}'; the release file's HTTP Last-Modified is {published}"
            if extracted else
            "HTTP Last-Modified of the release zip (the codebook's extraction day for "
            "this release is not in ops/fetch_ucdp.RELEASES yet)"),
        "vintage_url": codebook or url,
        "published": published,
        "scope": "country_id 666; sides, place, adm_1 or conflict name mention "
                 "Palestine, Gaza or the West Bank; place not in Israel proper",
        "license": f"{LICENSE} (stated on {DOWNLOADS})",
        "attribution": "; ".join([
            known.get("cite") or f"the yearly paper listed at {DOWNLOADS}#ged_global",
            GED_PAPER,
            f"UCDP, Uppsala University, GED version {version}"]),
        "release_counts": {
            "rows_global": seen["rows_global"], "rows_country_666": len(rows),
            "palestine_related": sum(1 for r in rows if is_palestinian(r)),
            "in_scope": len(scoped), "release_last_year": seen["last_year"],
            "dated_after_the_held_period": len(after),
            "inside_the_held_period": len(inside)},
    }

    def cover(recs):
        days = [r["date"] for r in recs]
        return {"first": min(days, default=None), "last": max(days, default=None)}

    load = {"metadata": {
        **common,
        "holds": f"the release's events dated after {end or 'nothing: the store holds none'}"
                 + (", the last day the store holds a UCDP event for" if end else ""),
        "coverage": cover(after),
        "counts": {"events": len(after),
                   "killed": sum(r["metrics"]["killed"] for r in after),
                   "by_type": dict(sorted(Counter(r["event_type"] for r in after).items())),
                   "by_month": dict(sorted(Counter(r["date"][:7] for r in after).items()))},
    }, "data": after}
    revision = {"metadata": {
        **common,
        "holds": f"the release's reading of the period the store holds (to {end}). "
                 "Read with ged.json and candidate.json as UCDP's whole current reading: "
                 "the loader revises a held event that changed and retracts one that left",
        "coverage": cover(inside),
        "held": summary,
    }, "data": inside}
    return load, revision


# ── the candidates ───────────────────────────────────────────────────────────

def build_candidates(files: list[dict], *, release: dict, fetched_at: str) -> dict:
    """candidate.json from the candidate files, oldest first.

    `files` are {"version", "url", "last_modified", "rows"} with rows of
    country 666; `release` is {"version", "ids", "last_year"}. An event in two
    files is taken from the newer one: UCDP re-extracts a quarter when it
    bundles it, and a monthly file repeats an event that spans two months."""
    files = sorted(files, key=lambda f: (_published(f.get("last_modified")) or "",
                                         f["version"]))
    chosen: dict[str, tuple[dict, dict]] = {}
    per_file, skipped = [], Counter()
    for f in files:
        scoped = [r for r in f["rows"] if in_scope(r)]
        kept = 0
        for r in scoped:
            uid = _uid(r)
            if uid in release["ids"]:
                skipped["id_in_release"] += 1
            elif int(_day(r)[:4]) <= release["last_year"]:
                skipped["dated_inside_release"] += 1
            else:
                if uid in chosen:
                    skipped["superseded_by_newer_file"] += 1
                chosen[uid] = (r, f)
                kept += 1
        per_file.append({"version": f["version"], "url": f["url"],
                         "http_last_modified": f.get("last_modified"),
                         "rows_country_666": len(f["rows"]), "in_scope": len(scoped),
                         "kept": kept})
    recs = [to_record(r, held={}, url=f["url"], fetched_at=fetched_at,
                      candidate=f["version"]) for r, f in chosen.values()]
    recs.sort(key=lambda r: (r["date"], int(r["ucdp_id"])))
    days = [r["date"] for r in recs]
    newest = max((_published(f.get("last_modified")) or "" for f in files), default="")
    return {"metadata": {
        "fetched_at": fetched_at,
        "source": "UCDP Candidate Events Dataset",
        "organization": f"{ORGANIZATION}, Uppsala University",
        "source_url": DOWNLOADS,
        "after_release": release["version"],
        "files": per_file,
        "parser": PARSER,
        "vintage": newest or None,
        "vintage_basis": "HTTP Last-Modified of the newest candidate file; the candidate "
                         "codebook 1.5 says 'Data extracted from UCDP systems on the 20th "
                         "of every month'",
        "vintage_url": files[-1]["url"] if files else DOWNLOADS,
        "coverage": {"first": min(days, default=None), "last": max(days, default=None)},
        "provisional": "Candidate events are not final: 'Not all events in UCDP Candidate "
                       "will make it into the final UCDP GED and new events will be added' "
                       "(candidate codebook 1.5).",
        "license": f"{LICENSE} (stated on {DOWNLOADS})",
        "attribution": "Hegre, Croicu, Eck and Högbladh (2020), Introducing the UCDP "
                       "Candidate Events Dataset, Research & Politics; UCDP, Uppsala University",
        "counts": {"events": len(recs),
                   "killed": sum(r["metrics"]["killed"] for r in recs),
                   "skipped": dict(sorted(skipped.items())),
                   "by_month": dict(sorted(Counter(r["date"][:7] for r in recs).items())),
                   "by_code_status": dict(sorted(Counter(
                       str(r["ucdp_code_status"]) for r in recs).items())),
                   "by_type": dict(sorted(Counter(r["event_type"] for r in recs).items()))},
    }, "data": recs}


# ── the run ──────────────────────────────────────────────────────────────────

def _refuse(label: str, n: int, floor: int, dry: bool) -> None:
    if n >= floor:
        return
    if dry:
        raise fl.FetchRefused(f"{label}: {n} events below the floor of {floor}")
    fl.check_floor(label, n, floor)


def fetch_release(listing: dict, held: dict, *, dry: bool, staged: Path | None,
                  force: bool, fetched_at: str) -> dict:
    """Write ged.json and ged_revision.json when the release moved; return
    {"version", "last_year", "ids"}, which decides the candidates."""
    label = "ucdp:ged"
    rel = listing["release"]
    head = _head(rel["url"])
    old = _on_disk("ged.json").get("metadata") or {}
    unchanged = (not dry and not force and old.get("release") == rel["version"]
                 and old.get("http_last_modified") == head["last_modified"]
                 and old.get("http_etag") == head["etag"]
                 and old.get("parser") == PARSER
                 and old.get("frozen_sha") == _frozen_sha()
                 and (RAW / "ged_revision.json").exists())
    if unchanged:
        on_disk = _on_disk("ged.json")
        print(f"  ok   {label:<16} GED {rel['version']} unchanged since "
              f"{head['last_modified']}; {len(on_disk['data'])} events on disk stand")
        fl.event(label, "ok", rows=len(on_disk["data"]), release=rel["version"],
                 unchanged=True)
        return {"version": rel["version"],
                "last_year": old["release_counts"]["release_last_year"],
                "ids": {r["ucdp_id"] for r in on_disk["data"]}
                | {r["ucdp_id"] for r in _on_disk("ged_revision.json")["data"]}}
    blob, head = _get(rel["url"])
    member, member_name = release_csv(blob)
    rows, seen = read_events(member)
    load, revision = build_release(rows, seen, version=rel["version"], url=rel["url"],
                                   head=head, held=held, fetched_at=fetched_at)
    m, h = load["metadata"], revision["metadata"]["held"]
    _refuse(label, m["release_counts"]["in_scope"], RELEASE_FLOOR, dry)
    print(f"  ok   {label:<16} GED {rel['version']} (vintage {m['vintage']}): "
          f"{m['release_counts']['in_scope']} events in scope")
    print(f"         to load: {len(load['data'])} events, "
          f"{m['coverage']['first']} to {m['coverage']['last']}")
    print(f"         held period (to {h['held_through']}), not loaded: of "
          f"{h['frozen_corpus_events']} held events {h['identical']} identical, "
          f"{h['revised']} revised ({h['revised_fields'].get('any_stored_field', 0)} "
          f"in a stored field), {h['absent_from_release']} absent; "
          f"{h['not_held']} in the release and not held")
    if dry:
        print(f"         would write {(RAW / 'ged.json').relative_to(fl.ROOT)} and "
              "ged_revision.json")
        fl.stage(staged, "ged.json", load)
        fl.stage(staged, "ged_revision.json", revision)
    else:
        from ingest import bronze
        ref = bronze.put("ucdp", blob, "zip", url=rel["url"], etag=head.get("etag")).ref
        for doc, name in ((revision, "ged_revision.json"), (load, "ged.json")):
            doc["metadata"]["csv_member"] = member_name
            doc["metadata"]["bronze"] = [ref]
            fl.write_atomic(RAW / name, doc)
        fl.event(label, "ok", rows=len(load["data"]), release=rel["version"],
                 data_through=m["coverage"]["last"], revised=h["revised"],
                 absent=h["absent_from_release"], not_held=h["not_held"])
    return {"version": rel["version"], "last_year": seen["last_year"],
            "ids": {_uid(r) for r in rows}}


def fetch_candidates(listing: dict, release: dict, *, dry: bool, staged: Path | None,
                     force: bool, fetched_at: str) -> None:
    """Write candidate.json when any listed candidate file moved."""
    label = "ucdp:candidate"
    prior = _on_disk("candidate.json").get("metadata") or {}
    same_release = prior.get("after_release") == release["version"]
    heads = {c["url"]: _head(c["url"])["last_modified"] for c in listing["candidates"]}
    on_disk = {f["url"]: f.get("http_last_modified") for f in prior.get("files") or []}
    if (not dry and not force and same_release and prior.get("parser") == PARSER
            and heads and heads == on_disk):
        n = (prior.get("counts") or {}).get("events", 0)
        print(f"  ok   {label:<16} {len(heads)} candidate files unchanged since "
              f"{prior.get('vintage')}; {n} events on disk stand")
        fl.event(label, "ok", rows=n, unchanged=True)
        return
    files = []
    for c in listing["candidates"]:
        blob, h = _get(c["url"])
        rows, _ = read_events(io.BytesIO(blob))
        files.append({**c, "last_modified": h["last_modified"], "rows": rows, "blob": blob})
    doc = build_candidates(files, fetched_at=fetched_at, release=release)
    m = doc["metadata"]
    n = len(doc["data"])
    floor = 1
    if same_release:
        floor = max(1, int(CANDIDATE_KEEP * (prior.get("counts") or {}).get("events", 0)))
    _refuse(label, n, floor, dry)
    print(f"  ok   {label:<16} {n} events after GED {release['version']}, "
          f"{m['coverage']['first']} to {m['coverage']['last']}, from "
          f"{len(files)} files (newest {m['vintage']})")
    print(f"         skipped: {m['counts']['skipped']}; code status: {m['counts']['by_code_status']}")
    if dry:
        print(f"         would write {(RAW / 'candidate.json').relative_to(fl.ROOT)}")
        fl.stage(staged, "candidate.json", doc)
        return
    from ingest import bronze
    m["bronze"] = [bronze.put("ucdp", f["blob"], "csv", url=f["url"]).ref for f in files]
    fl.write_atomic(RAW / "candidate.json", doc)
    fl.event(label, "ok", rows=n, data_through=m["coverage"]["last"])


def _attempt(label: str, dry: bool, step):
    """Run one half of the fetch; a failure is printed, ledgered under ITS
    label, and returned as None so the caller knows the half did not happen."""
    try:
        return step() or True
    except NewRelease as e:
        print(f"  PENDING {label}: {e}")
        outcome, extra = "pending", {"loads": LOADS_RELEASE}
    except fl.FetchRefused as e:
        print(f"  REFUSED {label}: {e}")
        return None                           # check_floor already ledgered it
    except urllib.error.HTTPError as e:
        # 401/403 here would mean the bulk files now want an account. That is
        # a decision for a person, not something to route around.
        print(f"  FAIL {label}: HTTP {e.code} from {e.url}"
              + ("  (the publisher is asking for credentials; stop and tell Zaid)"
                 if e.code in (401, 403) else ""))
        outcome, extra = "error", {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
        print(f"  FAIL {label}: {type(e).__name__}: {str(e)[:200]}")
        outcome, extra = "error", {"error": type(e).__name__}
    if not dry:
        fl.event(label, outcome, **extra)
    return None


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    force, any_release = "--force" in argv, "--any-release" in argv
    if any_release and not dry:
        raise SystemExit("--any-release only with --dry-run: a new release is looked at, "
                         "then LOADS_RELEASE is changed by hand")
    fetched_at = datetime.now(timezone.utc).isoformat()

    def release_half():
        listing = parse_downloads_page(fl.get(DOWNLOADS).decode("utf-8", "replace"))
        version = listing["release"]["version"]
        if version != LOADS_RELEASE and not any_release:
            raise NewRelease(
                f"the page lists GED {version}; this fetcher loads {LOADS_RELEASE}. A "
                "release re-reads years the store already holds, so it is applied by a "
                "person: `--dry-run --stage DIR --any-release` shows what it contains")
        held = load_held()
        if not held:
            print(f"  note: {FROZEN.relative_to(fl.ROOT)} is absent or holds no UCDP "
                  "record; every event gets a new id and nothing is held back")
        return listing, fetch_release(listing, held, dry=dry, staged=staged, force=force,
                                      fetched_at=fetched_at)

    got = _attempt("ucdp:ged", dry, release_half)
    ok = False
    if got:                                   # the candidates are defined by the release
        listing, release = got
        ok = bool(_attempt("ucdp:candidate", dry, lambda: fetch_candidates(
            listing, release, dry=dry, staged=staged, force=force, fetched_at=fetched_at)))
    print("\n  UCDP " + ("fetched" if ok else "NOT fetched")
          + ("  (dry run, nothing written)" if dry else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
