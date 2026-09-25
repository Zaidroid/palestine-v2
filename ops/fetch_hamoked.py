"""Fetch HaMoked's monthly count of Palestinians held by Israel — the v1
supply line `hamoked-detention`, dead since 2026-08-26 (P1-B.3).

WHAT HaMoked PUBLISHES. hamoked.org/prisoners-charts.php draws a bar per
month since May 2008 as a `<div class="pillar">` whose data attributes carry
the Israel Prison Service figures: data-judgment (sentenced), data-arrest
(remand / awaiting trial), data-administrative-arrest (held without charge)
and data-unnlawful-combatants (the "unlawful combatants" law, Gaza detainees).
The databank's series (v1_prisoners_hamoked) is total / sentenced / remand /
administrative, with total = the sum of all four — measured against the page:
June 2026 = 1,335 + 3,386 + 3,324 + 1,316 = 9,361, exactly the stored row.

WHY v1's STEP DIED, AND WHY THIS ONE HAS TWO DOORS. v1 rendered the page in a
headless browser because Cloudflare in front of hamoked.org refuses some
clients; the browser package left v1's image and the step failed in 0 s every
night. No browser is needed. Measured from this host 2026-09-25: the WAF
answers "Sorry, you have been blocked" (403) to curl and to Python's default
`Python-urllib` agent, and serves the full page (301 KB, 219 months) to a
plainly named client — this fetcher sends fetchlib's UA, which names the
project and a contact address. Because a WAF rule can change overnight, there
is a second door onto the same bytes: the Internet Archive's Wayback Machine
holds 200-status captures of the page (2026-08-19, 2026-08-24, …). So:

  1. HaMoked directly. If it answers with the chart, that is the source.
  2. Otherwise the newest 200-status Wayback capture of the same URL, read
     byte-for-byte (`id_` mode, no archive chrome). The capture timestamp is
     recorded as provenance (`via: wayback:<ts>`) and the data's own last
     month is what the gap radar judges — if nobody captures the page again,
     the series goes late and then stalled, in the open.

If both doors fail the fetch fails, the ledger says so, and after three
nights the radar calls the line dead. Its named successor is Addameer
(v1_prisoners_addameer, still flowing through v1's `prisoners` step): a
shorter series (2022→) of the same two headline figures, total and
administrative detention.

LICENCE: no licence found on HaMoked's site (source row `hamoked`,
commercial_use false, read 2026-08-05) — attribution, never sold.

Run: .venv/bin/python -m ops.fetch_hamoked
     .venv/bin/python -m ops.fetch_hamoked --dry-run
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

PAGE = "https://hamoked.org/prisoners-charts.php"
CDX = ("https://web.archive.org/cdx/search/cdx?url=hamoked.org/prisoners-charts.php"
       "&output=json&filter=statuscode:200&fl=timestamp,statuscode,digest"
       "&limit=-5")
WAYBACK = "https://web.archive.org/web/{ts}id_/" + PAGE
RAW = fl.ROOT / "data" / "raw" / "hamoked"
OUT = RAW / "detention.json"
LABEL = "hamoked:detention"
SOURCE_NAME = "HaMoked"                  # exactly as prisoners_hamoked.yaml routes it

# 218 months measured 2026-09-25 (May 2008 → Aug 2026). ~0.9 of the 216 the
# databank already holds; below it the page is not the page we know.
MIN_MONTHS = 195

_PILLAR = re.compile(r'<div class="pillar"[^>]*>')


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'data-{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def _int(v) -> int | None:
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_pillars(html: str) -> list[dict]:
    """One dict per month: year, month and the four IPS figures."""
    out = []
    for tag in _PILLAR.findall(html):
        year, month = _int(_attr(tag, "year")), _int(_attr(tag, "month"))
        if not year or not month or not 1 <= month <= 12:
            continue
        out.append({"year": year, "month": month,
                    "sentenced": _int(_attr(tag, "judgment")),
                    "remand": _int(_attr(tag, "arrest")),
                    "administrative": _int(_attr(tag, "administrative-arrest")),
                    "unlawful_combatants": _int(_attr(tag, "unnlawful-combatants"))})
    out.sort(key=lambda r: (r["year"], r["month"]))
    return out


def month_records(months: list[dict], via: str, fetched_at: str) -> list[dict]:
    """Months → records in the shape t_prisoners reads: four series a month.

    `total` is the sum of the four figures the page gives, which is how the
    held series was built (verified to the person on 2026-06). A month missing
    any figure has no honest total and gets none."""
    src = {"name": SOURCE_NAME, "url": PAGE, "license": "verify-required",
           "via": via, "fetched_at": fetched_at}
    recs = []
    seen = set()
    for m in months:
        day = f"{m['year']:04d}-{m['month']:02d}-01"
        if day in seen:
            continue                       # the page repeats nothing today;
        seen.add(day)                      # if it ever does, the first wins
        parts = (m["sentenced"], m["remand"], m["administrative"],
                 m["unlawful_combatants"])
        series = {"sentenced": m["sentenced"], "remand": m["remand"],
                  "administrative": m["administrative"],
                  "total": sum(parts) if None not in parts else None}
        for metric, count in series.items():
            if count is None:
                continue
            recs.append({
                "stable_id": f"hamoked:{day}:{metric}",
                "prisoner_metric_type": metric,
                "date": day,
                "location": {"name": "Palestine", "region": "Palestine"},
                "metrics": {"count": count, "unit": "persons"},
                "sources": [src]})
    return recs


def _get(url: str, ua: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": ua, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_capture(cdx_rows) -> str | None:
    """Newest 200-status timestamp from a CDX JSON answer (header row first)."""
    rows = [r for r in (cdx_rows or [])[1:] if len(r) >= 2 and r[1] == "200"]
    return max((r[0] for r in rows), default=None)


def fetch(get=_get) -> tuple[str, str, bytes, str]:
    """(html, via, raw bytes, url) — HaMoked first, then Wayback."""
    errors = []
    try:
        raw = get(PAGE, fl.UA)
        html = raw.decode("utf-8", "replace")
        if _PILLAR.search(html):
            return html, "direct", raw, PAGE
        errors.append("direct: 200 without pillars")
    except urllib.error.HTTPError as e:
        errors.append(f"direct: HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        errors.append(f"direct: {type(e).__name__}")
    try:
        ts = latest_capture(json.loads(get(CDX, fl.UA)))
        if not ts:
            raise ValueError("no 200 capture in the archive")
        url = WAYBACK.format(ts=ts)
        raw = get(url, fl.UA, timeout=120)
        return raw.decode("utf-8", "replace"), f"wayback:{ts}", raw, url
    except (urllib.error.URLError, OSError, ValueError) as e:
        errors.append(f"wayback: {type(e).__name__}: {str(e)[:80]}")
    raise OSError("; ".join(errors))


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    try:
        html, via, raw, url = fetch()
    except OSError as e:
        print(f"  FAIL {LABEL}: {e}")
        if not dry:
            fl.event(LABEL, "error", error=str(e)[:200])
        return 1
    months = parse_pillars(html)
    if len(months) < MIN_MONTHS:
        print(f"  REFUSED {LABEL}: {len(months)} months below the floor of "
              f"{MIN_MONTHS} (via {via}) — keeping the file already on disk")
        if not dry:
            fl.event(LABEL, "refused", rows=len(months), floor=MIN_MONTHS, via=via)
        return 1
    fetched_at = datetime.now(timezone.utc).isoformat()
    recs = month_records(months, via, fetched_at)
    last = f"{months[-1]['year']:04d}-{months[-1]['month']:02d}"
    first = f"{months[0]['year']:04d}-{months[0]['month']:02d}"
    print(f"  ok   {LABEL}  {len(months)} months {first} → {last}, "
          f"{len(recs)} records, via {via}")
    lm = months[-1]
    print(f"         latest {last}: sentenced {lm['sentenced']:,} · remand "
          f"{lm['remand']:,} · administrative {lm['administrative']:,} · "
          f"unlawful combatants {lm['unlawful_combatants']:,}")
    doc = {"metadata": {
        "fetched_at": fetched_at, "source": "HaMoked — Center for the Defence "
        "of the Individual", "source_url": PAGE, "via": via, "read_url": url,
        "license": "no licence found (verify-required); attribution",
        "attribution": "Detention figures: HaMoked (hamoked.org), sourced "
                       "from the Israel Prison Service.",
        "months": len(months), "first_month": first, "data_through": last},
        "data": recs}
    if dry:
        print(f"         would write {OUT.relative_to(fl.ROOT)} and 1 bronze "
              "payload under hamoked  (dry run, nothing written)")
        fl.stage(fl.stage_dir(argv), "detention.json", doc)
        return 0
    from ingest import bronze
    doc["metadata"]["bronze"] = bronze.put("hamoked", raw, "html", url=url).ref
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=len(recs), via=via, data_through=last)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
