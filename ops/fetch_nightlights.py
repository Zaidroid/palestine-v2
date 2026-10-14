"""Night lights over Palestine by governorate and month, from the World Bank's
Space2Stats Black Marble files (2012 to 2025).

    .venv/bin/python -m ops.fetch_nightlights              # by hand, or monthly at most
    .venv/bin/python -m ops.fetch_nightlights --dry-run

WHY (2026-10-14). Light seen from space at night is the one measure of Gaza's
electricity and life that no checkpoint, ministry or blackout can stop: Gaza
governorate's sum of radiance was 8,315 in September 2023, 569 in November 2023
and 257 in January 2025. The World Bank computes NASA's Black Marble (VNP46A3)
monthly radiance per administrative area for the whole world (data catalog
0066940, "Space2Stats", CC BY 4.0), one file a year, about 230 MB each.

THE ROUTE. Each yearly file is sorted by country code, and its host answers
range requests: the reader finds Palestine's block (16 governorates, 12 months)
by bisection, about fifteen small reads a file, three seconds apart, and reads
only that block. A file whose Last-Modified has not moved since the last read is
not read again (data/cache/nightlights/). The file addresses are the catalog's
(DR0095686 to DR0095699 for 2012 to 2025); the catalog API answered 429 on
2026-10-14, so a new year's address is added here by hand when it appears.
No robots rule on the file host; the catalog's robots file names only a sitemap.

WHAT IS WRITTEN. data/raw/nightlights/monthly.json: per governorate and month,
the sum and the mean of radiance (nanowatts per square centimetre per
steradian, NASA's unit) and the share of pixels of good quality (attrs). The
World Bank publishes no district level for Palestine. Ledgered as
`nightlights:monthly`.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

from ops import fetchlib as fl

URL = "https://datacatalogfiles.worldbank.org/ddh-published/0066940/{dr}/ntl_adm2_monthly_{year}.csv"
PAGE = "https://datacatalog.worldbank.org/search/dataset/0066940"
FILES = {y: f"DR00956{86 + (y - 2012)}" for y in range(2012, 2026)}
OUT = fl.ROOT / "data" / "raw" / "nightlights" / "monthly.json"
CACHE = fl.ROOT / "data" / "cache" / "nightlights"
LABEL = "nightlights:monthly"
ISO = "PSE"
PAUSE = 3.0
PROBE = 8192
SPAN = 256 * 1024                 # bisection stops when the bracket is this narrow
CHUNK = 512 * 1024                # then reads forward this much at a time
SOURCE_NAME = "World Bank Space2Stats: Black Marble night lights by administrative area (NASA VNP46A3)"

# The World Bank's governorate names → the store's.
GOVERNORATE = {
    "bethlehem": "Bethlehem", "deir al-balah": "Deir Al-Balah", "deir el-balah": "Deir Al-Balah",
    "dier al-balah": "Deir Al-Balah", "gaza": "Gaza", "hebron": "Hebron", "jenin": "Jenin",
    "jericho": "Jericho", "jericho and al aghwar": "Jericho", "jerusalem": "Jerusalem",
    "khan yunis": "Khan Younis", "khan younis": "Khan Younis", "nablus": "Nablus",
    "north gaza": "North Gaza", "qalqilya": "Qalqilya", "qalqiliya": "Qalqilya", "rafah": "Rafah",
    "ramallah": "Ramallah", "ramallah and al-bireh": "Ramallah", "ramallah & al-bireh": "Ramallah",
    "salfit": "Salfit", "tubas": "Tubas", "tulkarm": "Tulkarm", "tulkarem": "Tulkarm",
    # as the World Bank's files name them (read 2026-10-14); North Gaza by its main town
    "al khalil (hebron)": "Hebron", "al quds (jerusalem)": "Jerusalem", "ariha (jericho)": "Jericho",
    "deir al balah": "Deir Al-Balah", "jabalya": "North Gaza",
}


def _req(url: str, method: str = "GET", rng: tuple[int, int] | None = None):
    h = {"User-Agent": fl.UA}
    if rng:
        h["Range"] = f"bytes={rng[0]}-{rng[1]}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=h, method=method), timeout=120)


def head(url: str) -> tuple[int, str]:
    with _req(url, "HEAD") as r:
        return int(r.headers["Content-Length"]), r.headers.get("Last-Modified") or ""


def read(url: str, a: int, b: int) -> bytes:
    time.sleep(PAUSE)
    with _req(url, rng=(a, b)) as r:
        if r.status != 206:
            raise fl.FetchRefused(f"{LABEL}: the host did not answer a range request ({r.status})")
        return r.read()


def first_code(url: str, offset: int) -> str:
    """The country code of the first whole line after `offset`."""
    chunk = read(url, offset, offset + PROBE)
    nl = chunk.find(b"\n")
    line = chunk[nl + 1:].split(b"\n", 1)[0] if nl >= 0 else b""
    return line.split(b",", 1)[0].decode("ascii", "replace")


def block(url: str, size: int) -> tuple[str, list[str]]:
    """Palestine's lines of one yearly file: bisection to the first line at or
    after the code, then forward reads until the code ends."""
    header = read(url, 0, 4095).split(b"\n", 1)[0].decode()
    lo, hi = 0, size - PROBE - 1
    while hi - lo > SPAN:
        mid = (lo + hi) // 2
        if first_code(url, mid) < ISO:
            lo = mid
        else:
            hi = mid
    lines: list[str] = []
    pos, carry, done = lo, b"", False
    while not done and pos < size:
        chunk = carry + read(url, pos, min(pos + CHUNK, size) - 1)
        pos = min(pos + CHUNK, size)
        parts = chunk.split(b"\n")
        carry = parts.pop()
        for raw in parts:
            code = raw.split(b",", 1)[0].decode("ascii", "replace")
            if code == ISO:
                lines.append(raw.decode("utf-8", "replace"))
            elif code > ISO and len(code) == 3 and code.isalpha():
                done = True
                break
    return header, lines


def records(header: str, lines: list[str]) -> tuple[list[dict], list[str]]:
    recs, unknown = [], set()
    src = {"name": SOURCE_NAME, "organization": "World Bank", "url": PAGE}
    for r in csv.DictReader(io.StringIO(header + "\n" + "\n".join(lines))):
        gov = GOVERNORATE.get((r.get("NAM_1") or "").strip().lower())
        if not gov:
            unknown.add(r.get("NAM_1"))
            continue
        day = (r.get("date") or "")[:10]

        def num(k):
            v = r.get(k)
            return None if v in (None, "", "NA") else float(v)
        good = num("ntl_quality_prop_0_good")
        for measure, field in (("radiance_sum", "ntl_sum"), ("radiance_mean", "ntl_mean")):
            v = num(field)
            if v is None:
                continue
            recs.append({"stable_id": f"nightlights:{measure}:{gov}:{day}", "measure": measure, "value": v,
                         "unit": "nW/cm2/sr", "date": day, "share_good_quality": good,
                         "adm1_code": r.get("ADM1CD_c"), "name_printed": r.get("NAM_1"),
                         "location": {"governorate": gov, "region": "Palestine"}, "sources": [src]})
    return recs, sorted(x for x in unknown if x)


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    CACHE.mkdir(parents=True, exist_ok=True)
    all_recs, read_years, kept_years, unknown = [], [], [], set()
    try:
        for year, dr in sorted(FILES.items()):
            url = URL.format(dr=dr, year=year)
            size, modified = head(url)
            cached = CACHE / f"{year}.json"
            if cached.exists():
                c = json.loads(cached.read_text())
                if c.get("last_modified") == modified and c.get("size") == size:
                    all_recs += c["records"]
                    kept_years.append(year)
                    continue
            header, lines = block(url, size)
            if len(lines) < 12:
                raise fl.FetchRefused(f"{LABEL}: {year}: {len(lines)} lines for {ISO}, fewer than a year of one area")
            recs, unk = records(header, lines)
            unknown |= set(unk)
            if not dry:
                fl.write_atomic(cached, {"last_modified": modified, "size": size, "url": url, "records": recs})
            all_recs += recs
            read_years.append(year)
        if unknown:
            raise fl.FetchRefused(f"{LABEL}: governorate names not known: {sorted(unknown)}")
    except fl.FetchRefused as e:
        print(f"  REFUSED {LABEL}: {e}", file=sys.stderr)
        if not dry:
            fl.event(LABEL, "refused", why=str(e)[:300])
        return 1
    except Exception as e:                                   # noqa: BLE001
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:300])
        return 1
    days = sorted({r["date"] for r in all_recs})
    meta = {"fetched_at": datetime.now(timezone.utc).isoformat(), "source": SOURCE_NAME, "source_url": PAGE,
            "license": "CC BY 4.0 (World Bank data catalog 0066940)",
            "attribution": "Night lights: World Bank Space2Stats, from NASA's Black Marble (VNP46A3).",
            "vintage": days[-1], "vintage_basis": "the newest month in the newest yearly file",
            "years_read": read_years, "years_from_cache": kept_years}
    print(f"  ok   {LABEL}: {len(all_recs)} records, {days[0]} to {days[-1]}; read {read_years}, cached {kept_years}")
    if dry:
        fl.stage(staged, OUT.name, {"metadata": meta, "data": all_recs})
        return 0
    fl.write_atomic(OUT, {"metadata": meta, "data": all_recs})
    fl.event(LABEL, "ok", rows=len(all_recs), vintage=days[-1], years_read=len(read_years))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
