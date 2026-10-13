"""Humanitarian funding flows for the occupied Palestinian territory, read from
UN OCHA's Financial Tracking Service itself (2026-10-12).

    .venv/bin/python -m ops.fetch_fts
    .venv/bin/python -m ops.fetch_fts --dry-run [--stage DIR]

WHY
`funding` (dataset v1_funding_unfts, 10,431 current rows on 2026-10-12) was the
largest dataset still read through v1: v1's `scripts/sources/unfts.js` asked
FTS's public API every night, `funding-transformer.js` flattened each flow into
v1's unified record, and the loader read v1's partition files. The day v1 is
switched off the dataset stops. This asks the same API the same question and
writes the record the funding spec already reads.

THE QUESTION ASKED (v1's, unchanged)
    GET https://api.hpc.tools/v1/public/fts/flow?countryISO3=PSE&year=Y&limit=200
for every Y from 2015 to the current year, following `meta.nextLink`. No key.
FTS files a flow under each of its usage years, so the same flow comes back
under several Y; the first copy is kept (v1's rule; the copies are identical).

THE WINDOW IS KEPT, NOT WIDENED. `year` is the flow's usage year, so this is
"every flow FTS holds for PSE with a usage year from 2015 to this year" — not
FTS's whole history. Flows dated 2013 and 2014 are in it because their money
was for 2015 or later. Outside it, by FTS's own count on 2026-10-12: 4,759
rows under usage years 2000 to 2014, and 139 flows filed only under 2027 or
2028 (multi-year commitments; the 2027 ones enter on 1 January 2027, as they
would have under v1). A flow FTS deletes, or moves out of PSE, leaves the
answer; the loader does not close the held row for that (`identity.revises_by`
closes only a flow that REAPPEARS under a new status or date). Widening the
window is a decision with a count attached, not a default: `--count-outside`
prints FTS's count for every year outside the window and loads none of it.

WHAT IS WRITTEN
data/raw/fts/flows.json = {"metadata": {...}, "data": [record, ...]}. A record
carries the fields of v1's unified record that the loader reads (date,
location.name / .region, funding.*, sources[0]), built by the same rules as
v1's two scripts, so a held row reads back identical. It also carries, under
`fts`, the publisher's fields v1 threw away (versionId, updatedAt, the decision
and first-reported dates, every destination country of a shared flow, the
boundary) — in the raw file and in bronze, not in a served row.

A flow whose amount (amountUSD, else its parked amount) is not above zero is
not a record: v1's rule, 6 of 10,381 flows on 2026-10-13 (amountUSD 0 and no
parked amount).
A flow with no date at all is skipped and counted: v1 stamped it with the fetch
day, which is the ingest-date masquerade (mapping law 1). Measured 0.

A PARKED PARENT WITH NOTHING LEFT ON IT IS NOT FUNDING A SECOND TIME
(2026-10-13). FTS "parks" a contribution on a parent flow and files its
allocations as child flows; the parent's amountUSD is what is left unallocated
and fullParkedAmountUSD is the whole. v1's `amountUSD || parked` gave a fully
allocated parent (amountUSD 0) its whole parked amount again, beside the
children that carry the same money. Measured on the answer of 2026-10-13: 520
such parents, USD 1,926,516,664 (paid 397, commitment 122, pledge 1); 494 have
every child in the same answer and the children sum to the parked amount to
the dollar on all 494 (flow 152896 is USD 38,000,000 and its 16 children sum
to USD 38,000,000).

The rule, in one place (`is_parked_parent`): a flow with a parked amount above
zero, at least one child flow, and an amountUSD of zero OR BELOW is a parked
parent. Its record says `funding.series: parked_parent` (the loader's indicator
reads that field) and carries the whole parked amount, the count of its
children, their ids when the list is short, and how many of them are in this
answer. It is kept so the contribution stays visible; it is never part of the
paid, commitment or pledge series, where its children are. Every other record's
`series` is its status. Both of FTS's amounts are kept as FTS gave them, under
`fts.amount_usd` and `fts.full_parked_amount_usd`.

- BELOW ZERO: 34 parents on 2026-10-13 have a negative amountUSD (FTS shows
  more allocated to their children than was parked; on 11 of them by one
  dollar). v1 dropped them. Dropped, a parent held from a night when its
  remainder was still positive stays in the status series for ever, because
  its flow number is no longer emitted and nothing revises it: 3 such rows,
  USD 17,099,866, on 2026-10-13. They are parked parents like the rest.
- A partly allocated parent (amountUSD above zero, 231 on 2026-10-13) keeps
  what is left on it under its status, as before. 117 of them have no child
  yet and carry the whole amount. Of the 114 with children, 99 have every
  child in the answer, and remainder plus children equals the parked amount
  to the dollar on all 99.
- A chain needs no rule of its own: a child that is itself a parked parent
  with nothing left is treated the same way and its money is in ITS children.
  Measured 2026-10-13: no child is one; 21 children are parked flows nobody
  has allocated yet (they count, whole) and one is partly allocated.
- NOT EVERY CHILD IS IN THIS ANSWER. 26 of the 520 have a child FTS does not
  file under PSE inside the window (53 children, USD 57,351,135 of the
  1,926,516,664): allocations to another country (flow 277446, USD 600,234,
  went whole to UNRWA in Syria), to no country at all, or to a usage year the
  window has not reached (8 children under 2027, USD 11,195,842, which enter on
  1 January 2027). `child_flows_fetched` beside `child_flow_count` says so on
  the row.

STABLE ID: `fts-flow-<id>`, FTS's own flow number. v1's stable_id was a hash of
its whole unified record, so it changed whenever a description did. Rows are
matched on the spec's identity (indicator, date, place, flow_id), never on this
id, and the stable-id index covers current rows only, so a revised flow closes
its older reading and writes the new one under the same id.

VINTAGE: FTS states no dataset date. The newest `updatedAt` among the fetched
flows is the publisher's own last change, and that is what the file records.

POSTURE (ops/fetchlib.py): atomic, floored, ledgered. Every page is archived in
bronze before it is parsed. One page is retried once after a pause — 61 pages
in a row are fetched, and a single timeout would otherwise discard the night
(the reason fetchlib gives for adding a retry: this source needs it). A year
whose pages do not add up to FTS's own `meta.count` refuses the fetch;
yesterday's file stands. v1 skipped a failed year and wrote the rest.

ACCESS, read 2026-10-12 at https://api.hpc.tools/docs/v1/ : the public API is
"openly accessible as of December 2017 ... without any special credentials",
with an hourly request limit; for "regular continued access" OCHA advises
asking ocha-hpc@un.org for a client id. This fetcher sends none (v1 never did).
If FTS starts answering 401 or 429, that request is Zaid's to make.

LICENCE, read 2026-10-12. FTS's own terms (fts.unocha.org/content/terms-use,
"Last updated: 1 July 2015") name no Creative Commons licence: FTS data may be
included in documents, websites and teaching materials "provided that suitable
attribution of FTS as data source is given", citing FTS, the publication date
of the figures and the URL. OCHA FTS's release of the same flows on HDX
(pse-requirements-and-funding-data) is "Creative Commons Attribution for
Intergovernmental Organisations (CC BY-IGO)". Both are stamped in the file's
metadata; the source row `unfts` carries the stored grade and is not changed
here.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

BASE = "https://api.hpc.tools/v1/public/fts/flow"
COUNTRY = "PSE"
YEAR_FROM = 2015                  # v1's window start (scripts/sources/unfts.js)
LIMIT = 200
MAX_PAGES = 200                   # v1's hard stop per year
OUT = fl.ROOT / "data" / "raw" / "fts" / "flows.json"
LABEL = "fts:flows"
FLOOR = 9300                      # 0.9 × 10,341 records measured 2026-10-12
STABLE_PREFIX = "fts-flow-"
PARKED_PARENT = "parked_parent"   # `funding.series` of a parent with nothing left on it
CHILD_IDS_KEPT = 30               # a longer child list is counted, not listed
                                  #   (the longest on 2026-10-13 has 21)

# sources[0] exactly as v1 wrote it: the spec routes on `name`.
SOURCE = {"name": "UN OCHA Financial Tracking Service",
          "organization": "UN OCHA",
          "url": f"{BASE}?countryISO3={COUNTRY}",
          "license": "CC-BY-IGO-3.0"}
TERMS_URL = "https://fts.unocha.org/content/terms-use"
HDX_PAGE = "https://data.humdata.org/dataset/pse-requirements-and-funding-data"


class ShortYear(fl.FetchRefused):
    """A year's pages did not add up to the count FTS gave for it."""


# ── v1's rules, ported (scripts/sources/unfts.js, utils/funding-transformer.js,
#    utils/base-transformer.js) ───────────────────────────────────────────────

_GAZA = ("gaza", "rafah", "khan yun", "deir al-balah", "jabalia",
         "beit lahiya", "beit hanoun")
_WEST_BANK = ("west bank", "westbank", "ramallah", "hebron", "nablus", "jenin",
              "tulkarm", "qalqilya", "tubas", "salfit", "bethlehem", "jericho",
              "al-khalil", "ariha")
_JERUSALEM = ("jerusalem", "al-quds", "east jerusalem")


def classify_region(name) -> str:
    """BaseTransformer.classifyRegion: substring tests on the lowered name."""
    if not name or not isinstance(name, str):
        return "Palestine"
    n = name.lower().strip()
    if any(k in n for k in _GAZA):
        return "Gaza Strip"
    if any(k in n for k in _WEST_BANK):
        return "West Bank"
    if any(k in n for k in _JERUSALEM):
        return "East Jerusalem"
    return "Palestine"


def js_number(v):
    """`Number(v || 0)` as v1's JSON printed it: a whole number has no '.0'.

    The held attrs came through JavaScript, where 2000000 and 2000000.0 are one
    number printed one way. Python keeps them apart, and a 2000000.0 here would
    read as a revision of every row whose amount happens to be whole.
    """
    if v in (None, "", False):
        return 0
    if isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            return 0
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _first(objs, kind: str) -> dict | None:
    return next((o for o in objs or []
                 if isinstance(o, dict) and o.get("type") == kind), None)


def _all(objs, kind: str) -> list[dict]:
    return [o for o in objs or [] if isinstance(o, dict) and o.get("type") == kind]


def _day(v) -> str | None:
    """The first ten characters when they are a real calendar date."""
    s = str(v or "")[:10]
    try:
        date.fromisoformat(s)
    except ValueError:
        return None
    return s


def is_parked_parent(flow: dict) -> bool:
    """A parked contribution with nothing left on it: a parked amount above
    zero, at least one child flow, and a remainder (amountUSD) of zero or
    below. Its money is on its children (see the module docstring)."""
    remainder = js_number(flow.get("amountUSD"))
    parked = js_number(flow.get("fullParkedAmountUSD"))
    return (isinstance(parked, (int, float)) and parked > 0
            and isinstance(remainder, (int, float)) and remainder <= 0
            and bool(flow.get("childFlowIds")))


def flow_record(flow: dict, fetched_at: str) -> dict | str:
    """One FTS flow → the record the funding spec reads, or the reason it is
    not one ('no_amount' | 'undated')."""
    src, dst = flow.get("sourceObjects"), flow.get("destinationObjects")
    donor, recipient = _first(src, "Organization"), _first(dst, "Organization")
    dst_loc = _first(dst, "Location")
    cluster = _first(dst, "GlobalCluster") or _first(dst, "Cluster")
    plan, emergency = _first(dst, "Plan"), _first(dst, "Emergency")

    parent = is_parked_parent(flow)
    # A parked parent carries the whole contribution; any other flow carries
    # what FTS has on it (v1's `amountUSD || parked`).
    amount = (js_number(flow.get("fullParkedAmountUSD")) if parent else
              js_number(flow.get("amountUSD")) or js_number(flow.get("fullParkedAmountUSD")))
    if not (isinstance(amount, (int, float)) and amount > 0):
        return "no_amount"
    children = [str(c) for c in flow.get("childFlowIds") or []] if parent else []
    status = str(flow.get("status") or "commitment").lower()
    # v1: date || createdAt, then firstReportedDate, then decisionDate, then
    # the fetch day. The last rung is not taken (see the module docstring).
    day = (_day(flow.get("date")) or _day(flow.get("createdAt"))
           or _day(flow.get("firstReportedDate")) or _day(flow.get("decisionDate")))
    if day is None:
        return "undated"
    name = (dst_loc or {}).get("name") or "Occupied Palestinian Territory"
    flow_id = str(flow.get("id"))
    return {
        "stable_id": f"{STABLE_PREFIX}{flow_id}",
        "date": day,
        "category": "funding",
        "event_type": "humanitarian_funding",
        "location": {"name": name, "governorate": None,
                     "region": classify_region(name), "lat": None, "lon": None,
                     "precision": "country"},
        "metrics": {"value": amount, "unit": "USD", "count": 1},
        "funding": {
            "amount_usd": amount,
            "original_amount": js_number(flow.get("originalAmount")),
            "original_currency": flow.get("originalCurrency") or "USD",
            "status": status,
            # The series the loader files this record under: its status, or
            # `parked_parent`, which is never added to a status series.
            "series": PARKED_PARENT if parent else status,
            # A parked parent names its children; None on every other record
            # (an empty value is not passed through to a row's attrs).
            "child_flow_count": len(children) or None,
            "child_flow_ids": children if 0 < len(children) <= CHILD_IDS_KEPT else None,
            "child_flows_fetched": None,       # filled by build(), which sees every flow
            "flow_type": flow.get("flowType") or None,
            "contribution_type": flow.get("contributionType") or None,
            "method": flow.get("method") or None,
            "donor": {"name": (donor or {}).get("name") or "Unknown donor",
                      "type": ((donor or {}).get("organizationTypes") or [None])[0] or None},
            "recipient": {"name": (recipient or {}).get("name") or "Unknown recipient",
                          "type": ((recipient or {}).get("organizationTypes") or [None])[0] or None},
            "usage_years": [o.get("name") for o in _all(dst, "UsageYear")],
            "cluster": (cluster or {}).get("name") or None,
            "plan": (plan or {}).get("name") or None,
            "emergency": (emergency or {}).get("name") or None,
            "keywords": flow.get("keywords") if isinstance(flow.get("keywords"), list) else [],
            "new_money": bool(flow.get("newMoney")),
            "ref_code": flow.get("refCode") or None,
            "flow_id": flow_id,
        },
        "sources": [dict(SOURCE, fetched_at=fetched_at)],
        # The publisher's own fields v1 dropped. Not read by the loader.
        "fts": {
            # both amounts exactly as FTS gave them: what is left on the flow,
            # and the whole of a parked contribution (None on a flow not parked)
            "amount_usd": flow.get("amountUSD"),
            "full_parked_amount_usd": flow.get("fullParkedAmountUSD"),
            "version_id": flow.get("versionId"),
            "updated_at": flow.get("updatedAt"),
            "created_at": flow.get("createdAt"),
            "decision_date": _day(flow.get("decisionDate")),
            "first_reported_date": _day(flow.get("firstReportedDate")),
            "budget_year": flow.get("budgetYear"),
            "boundary": flow.get("boundary"),
            "on_boundary": flow.get("onBoundary"),
            "parent_flow_id": flow.get("parentFlowId"),
            "child_flow_ids": flow.get("childFlowIds"),
            "exchange_rate": flow.get("exchangeRate"),
            "status_as_published": flow.get("status"),
            "destination_locations": [o.get("name") for o in _all(dst, "Location")],
            "source_locations": [o.get("name") for o in _all(src, "Location")],
            "description": flow.get("description"),
        },
    }


def build(flows_by_year: dict[int, list[dict]], fetched_at: str) -> tuple[list[dict], dict]:
    """Every year's flows → records (first copy of a flow wins) and a summary."""
    seen: set[str] = set()
    recs: list[dict] = []
    skipped = {"no_amount": 0, "undated": 0}
    rows = status_defaulted = 0
    newest_update = None
    for year in sorted(flows_by_year):
        for flow in flows_by_year[year]:
            rows += 1
            fid = str(flow.get("id"))
            if fid in seen:
                continue
            seen.add(fid)
            up = flow.get("updatedAt")
            if up and (newest_update is None or up > newest_update):
                newest_update = up
            rec = flow_record(flow, fetched_at)
            if isinstance(rec, str):
                skipped[rec] += 1
                continue
            status_defaulted += not flow.get("status")
            recs.append(rec)
    # How many of a parked parent's children this answer carries: counted once
    # every flow is seen, because a child may be filed under a later usage year
    # than its parent. Fewer than `child_flow_count` means part of the
    # contribution was allocated outside PSE or outside the window.
    parents = [r for r in recs if r["funding"]["series"] == PARKED_PARENT]
    children_elsewhere = 0
    for r in parents:
        kids = [str(c) for c in r["fts"]["child_flow_ids"] or []]
        r["funding"]["child_flows_fetched"] = sum(1 for c in kids if c in seen)
        children_elsewhere += r["funding"]["child_flows_fetched"] < len(kids)
    return recs, {
        "years": [min(flows_by_year), max(flows_by_year)] if flows_by_year else None,
        "rows_returned": rows,
        "flows": len(seen),
        "records": len(recs),
        "skipped_no_amount": skipped["no_amount"],
        "skipped_undated": skipped["undated"],
        "status_defaulted_to_commitment": status_defaulted,
        # filed under `funding.parked_parent`, never under a status series
        "parked_parents": len(parents),
        "parked_parents_usd": sum(r["funding"]["amount_usd"] for r in parents),
        "parked_parents_with_a_child_outside_the_answer": children_elsewhere,
        "data_through": max((r["date"] for r in recs), default=None),
        "newest_flow_update": newest_update,
    }


# ── the fetch ────────────────────────────────────────────────────────────────

def _rel(p: Path) -> str:
    return str(p.relative_to(fl.ROOT)) if p.is_relative_to(fl.ROOT) else str(p)


def _get(url: str) -> bytes:
    try:
        return fl.get(url, timeout=120)
    except (urllib.error.URLError, OSError):
        time.sleep(5)
        return fl.get(url, timeout=120)


def year_url(year: int, limit: int = LIMIT) -> str:
    return f"{BASE}?countryISO3={COUNTRY}&year={year}&limit={limit}"


def fetch_year(year: int, get=_get, archive=None) -> list[dict]:
    """Every flow FTS files under one usage year, or ShortYear."""
    url, flows, count, page = year_url(year), [], None, 0
    while url and page < MAX_PAGES:
        body = get(url)
        if archive is not None:
            archive(url, body)
        doc = json.loads(body)
        flows += (doc.get("data") or {}).get("flows") or []
        meta = doc.get("meta") or {}
        count = meta.get("count", count)
        url = meta.get("nextLink")
        page += 1
    if count is not None and len(flows) != int(count):
        raise ShortYear(f"{LABEL}: {year} returned {len(flows)} flows, FTS "
                        f"counts {count} — a short answer; yesterday's file stands")
    return flows


def count_outside(this_year: int, get=_get) -> dict[int, int]:
    """What FTS files for PSE under the usage years outside the window (before
    2015, and the three years after this one), by FTS's own `meta.count`. One
    request a year, one flow each; nothing is loaded. A flow counts under every
    usage year it has, so these are rows, not distinct flows."""
    out = {}
    for year in [*range(1999, YEAR_FROM), *range(this_year + 1, this_year + 4)]:
        doc = json.loads(get(year_url(year, limit=1)))
        out[year] = int((doc.get("meta") or {}).get("count") or 0)
    return out


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    this_year = datetime.now(timezone.utc).year
    if "--count-outside" in argv:
        counts = count_outside(this_year)
        print(json.dumps({
            "window": [YEAR_FROM, this_year],
            "rows_by_usage_year_outside_the_window": counts,
            "before": sum(n for y, n in counts.items() if y < YEAR_FROM),
            "after": sum(n for y, n in counts.items() if y > this_year)}))
        return 0

    archive = None
    refs: list[str] = []
    if not dry:
        from ingest import bronze

        def archive(url: str, body: bytes) -> None:
            refs.append(bronze.put("fts_flow", body, "json", url=url).ref)

    by_year: dict[int, list[dict]] = {}
    try:
        for year in range(YEAR_FROM, this_year + 1):
            by_year[year] = fetch_year(year, archive=archive)
        fetched_at = datetime.now(timezone.utc).isoformat()
        recs, summary = build(by_year, fetched_at)
        if len(recs) < FLOOR:
            raise fl.FetchRefused(
                f"{LABEL}: {len(recs)} records below the floor of {FLOOR} — "
                "keeping the file already on disk")
    except fl.FetchRefused as e:
        if not dry:
            fl.event(LABEL, "refused", why=str(e)[:300])
        print(f"  REFUSED {e}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:300])
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1

    doc = {"metadata": {
        "fetched_at": fetched_at,
        "source": SOURCE["name"], "organization": SOURCE["organization"],
        "source_url": SOURCE["url"],
        "query": f"{BASE}?countryISO3={COUNTRY}&year=<{YEAR_FROM}..{this_year}>&limit={LIMIT}",
        "window": f"usage years {YEAR_FROM} to {this_year} (v1's window, unchanged)",
        "vintage": summary["newest_flow_update"],
        "vintage_basis": "the newest `updatedAt` among the fetched flows; FTS "
                         "states no dataset-level date",
        "vintage_url": SOURCE["url"],
        "license": "FTS terms of use (read 2026-10-12, last updated 1 July 2015): "
                   "use with attribution citing FTS, the publication date of the "
                   "figures and the URL; no Creative Commons licence is named there. "
                   "OCHA FTS's HDX release of the same flows is CC BY-IGO.",
        "license_url": TERMS_URL,
        "license_url_hdx": HDX_PAGE,
        "attribution": f"Financial Tracking Service (FTS), UN OCHA, figures as "
                       f"published {str(summary['newest_flow_update'])[:10]}, "
                       "https://fts.unocha.org",
        "rows_by_usage_year": {str(y): len(f) for y, f in by_year.items()},
        **summary}, "data": recs}
    print(f"  ok   {LABEL:<12} {len(recs):>6} records from {summary['flows']} flows "
          f"({summary['rows_returned']} rows over usage years {YEAR_FROM}–{this_year}), "
          f"data through {summary['data_through']}, newest update {summary['newest_flow_update']}")
    print(f"         skipped: no amount {summary['skipped_no_amount']}, "
          f"undated {summary['skipped_undated']}")
    print(f"         parked parents (not in a status series): {summary['parked_parents']}, "
          f"USD {summary['parked_parents_usd']:,.0f}; "
          f"{summary['parked_parents_with_a_child_outside_the_answer']} with a child outside this answer")
    if dry:
        print(f"         would write {_rel(OUT)}")
        fl.stage(staged, OUT.name, doc)
        return 0
    doc["metadata"]["bronze_pages"] = len(refs)
    fl.write_atomic(OUT, doc)
    fl.event(LABEL, "ok", rows=len(recs), data_through=summary["data_through"],
             vintage=summary["newest_flow_update"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
