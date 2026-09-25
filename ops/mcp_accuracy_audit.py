"""Does the MCP surface say exactly what the data says?

The partner's QA pass found wrong answers one at a time. This is the instrument
that looks for the whole class: it recomputes each payload's headline numbers
from the database, checks the arithmetic inside every payload, and tests the
serving view's own invariants across every row rather than a sample.

Run it after any change to the serving layer or a tool:

    sudo -n -u zaid bash -lc 'set -a; . /opt/stacks/palestine/services/westbank-alerts/.env; \
      set +a; cd /home/zaid/palestine-v2 && ./.venv/bin/python -m ops.mcp_accuracy_audit'

Exit 1 when a critical finding exists, 0 when none — so it can gate a
deploy, and so ops/with-heartbeat.sh can treat it as a working job that
reported something rather than as a job that broke.
Findings JSON: ops/mcp-accuracy.json

Nightly the unit runs it with alerting on; a critical finding pages the phone
once and stays open until a run comes back clean, which is the same shape as
the Gaza cross-check. The watchdog judges the `mcp-audit` HEARTBEAT that
ops/mcp-audit.sh writes around the run (not the artifact's age), so a job that
stops running at all is noticed too — one paging path each, no overlap.

THE TOOLS ARE CALLED THE WAY A CLIENT CALLS THEM (audit F243, 2026-09-25)
`check()` used to call the tool function directly. `answer_en` is attached by
the transports (serve/mcp_en.add_english, after serve/mcp_facades.route), so
every English check below ran on an empty string and could never fire, and a
façade name was never routed at all — the night of 09-23/24 this read 0/0/0
while a black-box pass rated four tools broken. `check()` now goes through the
same route() and add_english the stdio transport uses. The licence block
(licence.apply) is still not applied: it depends on the caller's tier, and the
arithmetic here is about the payload, not about what a tier may see.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve.app import q                                          # noqa: E402
from serve.mcp_en import add_english                             # noqa: E402
from serve.mcp_facades import route                              # noqa: E402
from serve.mcp_server import TOOLS                               # noqa: E402

FINDINGS: list[dict] = []


def finding(sev: str, tool: str, claim: str, expected, got, evidence: str = "") -> None:
    FINDINGS.append({"severity": sev, "tool": tool, "claim": claim,
                     "expected": expected, "got": got, "evidence": evidence})


def check(tool: str, args: dict) -> dict | None:
    """Call `tool` as a transport does: route a public (façade) name to the
    tool that answers, call it, and attach the English the client receives."""
    try:
        target, targs = route(tool, args)
        return add_english(target, TOOLS[target][0](**targs))
    except Exception as exc:                                     # noqa: BLE001
        finding("critical", tool, "tool raised", "a payload",
                f"{type(exc).__name__}: {exc}", traceback.format_exc()[-400:])
        return None


# ── A. the serving view's own contract, over every row ───────────────────────
def audit_serving_invariants() -> None:
    """The view promises: a value that is not `unknown` is fresh enough to call
    current, and its band is not `expired`. If that ever fails, every tool built
    on it is wrong at once — so it is checked over all 3,000+ rows, not sampled.
    """
    # The view's own rule: a value that is not `unknown` is not `expired`.
    # (The absolute-age ceiling needs `max_assert_seconds`, which the view
    # consumes rather than exposes, so it is checked through the serving tools
    # instead of guessed at here.)
    rows = q("""SELECT state_kind, count(*) AS n FROM state_serving
                 WHERE value <> 'unknown' AND staleness_band = 'expired'
                 GROUP BY 1 ORDER BY 2 DESC""")
    if rows:
        finding("critical", "state_serving",
                "a value is asserted while its band says expired",
                "0 rows", rows)
    total = q("SELECT count(*) AS n FROM state_serving")[0]["n"]
    unknown = q("SELECT count(*) AS n FROM state_serving WHERE value = 'unknown'")[0]["n"]
    print(f"  serving rows: {total}, unknown: {unknown} "
          f"({unknown / max(total, 1):.0%} — the honest state, not a defect)")


# ── B. payload numbers vs the database ───────────────────────────────────────
def audit_checkpoints_summary() -> None:
    d = check("checkpoints_summary", {})
    if not d:
        return
    db = {r["value"]: r["n"] for r in q("""
        SELECT value, count(*) AS n FROM state_serving
         WHERE state_kind = 'checkpoint_flow' AND direction = 'both' GROUP BY 1""")}
    if d["totals"] != db:
        finding("critical", "checkpoints_summary", "totals do not match state_serving",
                db, d["totals"])
    if sum(d["totals"].values()) != d["tracked"]:
        finding("major", "checkpoints_summary", "totals do not sum to tracked",
                d["tracked"], sum(d["totals"].values()))
    if len(d["closed_now"]) != d["totals"].get("closed", 0):
        finding("major", "checkpoints_summary", "closed_now length != closed total",
                d["totals"].get("closed"), len(d["closed_now"]))
    # A repeated NAME is legitimate (eight checkpoint names belong to two or
    # three distinct places each) as long as the entries are distinguishable.
    names = [c["name"] for c in d["closed_now"]]
    ids = [c.get("place_id") for c in d["closed_now"]]
    if any(i is None for i in ids):
        finding("major", "checkpoints_summary",
                "closed_now entry without a place id", "an id per entry", names[:3])
    elif len(set(ids)) != len(ids):
        finding("critical", "checkpoints_summary",
                "the same place listed twice in closed_now", "unique place ids",
                _dupes([str(i) for i in ids]))
    elif len(set(names)) != len(names) and len(set(ids)) == len(ids):
        pass                     # shared name, distinct places: now disambiguated


def audit_checkpoints_near() -> None:
    for place, radius in (("رام الله", 15), ("نابلس", 25), ("الخليل", 10)):
        d = check("checkpoints_near", {"place": place, "radius_km": radius, "limit": 50})
        if not d:
            continue
        c = d["counts"]
        if c["known"] + c["unknown"] != c["in_radius"]:
            finding("major", "checkpoints_near", f"{place}: known+unknown != in_radius",
                    c["in_radius"], c["known"] + c["unknown"])
        if len(d["checkpoints"]) != c["returned"]:
            finding("major", "checkpoints_near", f"{place}: returned != len(checkpoints)",
                    c["returned"], len(d["checkpoints"]))
        db_closed = q("""SELECT count(*) AS n FROM state_serving s
                           JOIN place p USING (place_id)
                          WHERE s.state_kind='checkpoint_flow' AND s.direction='both'
                            AND s.value='closed'
                            AND ST_DWithin(p.centroid, (SELECT centroid FROM place
                                             WHERE place_id = %s), %s)""",
                       (d.get("origin_place_id") or _place_id(place),
                        radius * 1000))[0]["n"]
        if c["closed"] != db_closed:
            finding("major", "checkpoints_near",
                    f"{place}: counts.closed != a direct SQL count",
                    db_closed, c["closed"])
        # the "nearest first" promise
        ages = [x.get("straight_km") for x in d["checkpoints"]]
        if any(a is not None for a in ages) and ages != sorted(a for a in ages if a is not None):
            finding("major", "checkpoints_near", f"{place}: not ordered by distance",
                    "monotonic straight_km", ages[:8])


def audit_incidents_summary() -> None:
    for hours in (24, 168):
        d = check("incidents_summary", {"hours": hours})
        if not d:
            continue
        db_total = q("""SELECT count(*) AS n FROM event
                         WHERE status = 'believed'
                           AND occurred_at >= now() - make_interval(hours => %s)""",
                     (hours,))[0]["n"]
        if d["total"] != db_total:
            finding("critical", "incidents_summary", f"{hours}h total != event table",
                    db_total, d["total"])
        by_n = sum(v.get("n", 0) for v in d["by_type"].values())
        if by_n != d["total"]:
            finding("major", "incidents_summary", f"{hours}h by_type does not sum to total",
                    d["total"], by_n)
        for k, v in d["by_type"].items():
            if v.get("corroborated", 0) > v.get("n", 0):
                finding("critical", "incidents_summary",
                        f"{k}: corroborated > n", v.get("n"), v.get("corroborated"))
        db_corrob = q("""SELECT count(*) AS n FROM event
                          WHERE status = 'believed' AND independent_sources >= 2
                            AND occurred_at >= now() - make_interval(hours => %s)""",
                      (hours,))[0]["n"]
        got_corrob = sum(v.get("corroborated", 0) for v in d["by_type"].values())
        if got_corrob != db_corrob:
            finding("major", "incidents_summary",
                    f"{hours}h corroborated total != event table", db_corrob, got_corrob)


def audit_insights() -> None:
    d = check("insights", {"place": "رام الله", "days": 7, "radius_km": 10})
    if not d:
        return
    ck = d["checkpoints"]
    if sum(ck["over_window"].values()) != ck["readings"]:
        finding("critical", "insights", "over_window does not sum to readings",
                ck["readings"], sum(ck["over_window"].values()))
    if sum(ck["now"].values()) != ck["places_now"]:
        finding("major", "insights", "now does not sum to places_now",
                ck["places_now"], sum(ck["now"].values()))
    if ck["unknown_now"] != ck["now"].get("unknown", 0):
        finding("major", "insights", "unknown_now != now.unknown",
                ck["now"].get("unknown", 0), ck["unknown_now"])
    db = q("""SELECT count(*) AS n FROM state_observation o JOIN place p USING (place_id)
               WHERE o.state_kind = 'checkpoint_flow' AND o.direction = 'both'
                 AND o.modality = 'assertion'
                 AND o.observed_at >= now() - interval '7 days'
                 AND ST_DWithin(p.centroid,
                     (SELECT centroid FROM place WHERE place_id = %s), 10000)""",
           (d["scope"]["place_id"],))[0]["n"]
    if abs(int(ck["readings"]) - int(db)) > max(5, db * 0.02):
        finding("major", "insights", "window readings differ from a direct SQL count",
                db, ck["readings"])


def audit_fuel_prices() -> None:
    d = check("fuel_prices", {})
    if not d:
        return
    rows = q("""SELECT product, price, unit, effective_from, status
                  FROM fuel_price_current ORDER BY product""")
    by_product = {r["product"]: r for r in rows}
    for p in d["prices"]:
        key = p.get("product") or p.get("key")
        r = by_product.get(key)
        if r and r["status"] == "confirmed" and p.get("price") is not None \
                and abs(float(p["price"]) - float(r["price"])) > 1e-9:
            finding("critical", "fuel_prices", f"{key}: price differs from the serving table",
                    float(r["price"]), p.get("price"))
    if d.get("as_of_date") and any(p.get("effective_from") == d["as_of_date"]
                                   for p in d["prices"]):
        pass
    dates = {p.get("effective_from") for p in d["prices"] if p.get("price") is not None}
    missing = [dt for dt in dates if dt not in (d.get("answer") or "")]
    if len(dates) > 1 and missing:
        finding("minor", "fuel_prices",
                "products carry effective dates the headline never names",
                sorted(dates), missing)


def audit_coverage() -> None:
    d = check("coverage", {})
    if not d:
        return
    db_total = q("""SELECT coalesce(sum(n), 0)::int AS total FROM (
                      SELECT count(c.*) AS n FROM source s
                      LEFT JOIN claim c USING (source_id)
                      GROUP BY s.source_id HAVING count(c.*) > 0) t""")[0]["total"]
    if d["total_claims"] != db_total:
        finding("major", "coverage", "total_claims != sum of per-source claims",
                db_total, d["total_claims"])
    if sum(d["places"].values()) != q("SELECT count(*) AS n FROM place")[0]["n"]:
        finding("minor", "coverage", "place counts do not cover the gazetteer",
                q("SELECT count(*) AS n FROM place")[0]["n"], sum(d["places"].values()))
    retired_live = [k for k, n in d["live_states"].items()
                    if k.startswith("fuel")]
    if retired_live:
        finding("major", "coverage",
                "retired state kinds still reported inside live_states",
                "no fuel kinds", retired_live)
    if "checkpoint_status" in d["live_states"] and not d.get("grain_note"):
        finding("minor", "coverage",
                "the legacy mixed kind is advertised as a live state with no note",
                "grain_note explaining it", "checkpoint_status")


def audit_crossings() -> None:
    d = check("crossings", {})
    if not d:
        return
    known = [c for c in d["crossings"] if c.get("value") not in (None, "unknown")]
    # THE NO-SOURCE BRANCH IS A DIFFERENT PAYLOAD, NOT A MISSING FIELD.
    # When nothing is known the tool answers "no source reports this" and omits
    # `with_a_current_reading` on purpose — there is no count to state. Comparing
    # 0 against a key that is correctly absent reported a major finding every
    # night the crossings feed was quiet, which is a bug in the instrument: what
    # must be checked there is that the branch agrees with its own premise.
    if d.get("no_source"):
        if known:
            finding("major", "crossings",
                    "claims no source reports crossing status while carrying "
                    "known values",
                    "no known values", len(known))
        if not d.get("warning"):
            finding("major", "crossings",
                    "the no-source branch without its warning — absence of "
                    "evidence must never read as 'open'",
                    "a warning", None)
    elif len(known) != d.get("with_a_current_reading"):
        finding("major", "crossings", "with_a_current_reading != known entries",
                len(known), d.get("with_a_current_reading"))
    for c in known:
        if not c.get("basis"):
            finding("major", "crossings", f"{c['name']}: a known value with no basis",
                    "basis names the layer", None)
        if not c.get("age_minutes"):
            finding("minor", "crossings", f"{c['name']}: known value without an age",
                    "age_minutes", None)


def audit_databank() -> None:
    d = check("databank", {})
    if not d:
        return
    # `categories` counts observation ROWS per category (206k), not datasets.
    db_datasets = q("SELECT count(*) AS n FROM dataset")[0]["n"]
    if d.get("datasets_registered") is None:
        finding("minor", "databank",
                "the list does not say how many datasets are registered but empty",
                "datasets_registered", list(d.keys()))
    elif d["datasets_registered"] < len(d["datasets"]):
        finding("major", "databank", "registered < listed", len(d["datasets"]),
                d["datasets_registered"])
    if not d["categories"]:
        finding("major", "databank", "no categories returned", "> 0", 0)
    for ds in d["datasets"][:5]:
        if not isinstance(ds, dict) or "dataset" not in ds:
            finding("minor", "databank", "dataset entry without a name",
                    "a dataset name per entry", str(ds)[:80])


def audit_area_history() -> None:
    d = check("area_history", {"days": 30})
    if not d:
        return
    for gov, g in d["governorates"].items():
        for kind, k in g.get("kinds", {}).items():
            if k.get("reports") is not None and k["reports"] < 0:
                finding("major", "area_history", f"{gov}/{kind}: negative reports",
                        ">= 0", k["reports"])
            vals = k.get("values") or {}
            if any(v < 0 for v in vals.values()):
                finding("major", "area_history", f"{gov}/{kind}: negative counts",
                        ">= 0", vals)


# ── C. the answer text must not contradict the payload ───────────────────────
FLOW_AR = {"open": ("سالك", "مفتوح"), "closed": ("مغلق", "مسكّر", "مسكر"),
           "congested": ("أزمة", "مزدحم"), "slow": ("بطيء", "بطي")}


def audit_answer_vs_payload() -> None:
    d = check("checkpoint_status", {"name": "حوارة"})
    if d and d.get("flow") in FLOW_AR:
        words = FLOW_AR[d["flow"]]
        if not any(w in d["answer"] for w in words):
            finding("critical", "checkpoint_status", "answer does not state the flow it returns",
                    words, d["answer"])

    c = check("connectivity_now", {})
    if c:
        st = c.get("status")
        contradictory = {
            "normal": ("no current measurement", "no measurement"),
            "degraded": ("normal", "no current measurement"),
            "unknown": (),
        }.get(st, ())
        low_ar = c["answer"].lower()
        low_en = (c.get("answer_en") or "").lower()
        for bad in contradictory:
            if bad in low_en or bad in low_ar:
                finding("critical", "connectivity_now",
                        f"answer contradicts status={st}", f"not contain {bad!r}",
                        f"{c['answer']} / {low_en[:80]}")

    p = check("place_pattern", {"place": "قلنديا"})
    if p and p.get("usually_by_hour_tally"):
        modal = max(p["usually_by_hour_tally"].items(), key=lambda kv: kv[1])[0]
        words = FLOW_AR.get(modal, ())
        if words and not any(w in p["answer"] for w in words):
            finding("critical", "place_pattern", "headline does not state the modal hour value",
                    (modal, words), p["answer"])

    i = check("incidents_summary", {"hours": 24})
    if i:
        for field in ("answer", "answer_en"):
            txt = i.get(field) or ""
            if "None" in txt:
                finding("major", "incidents_summary", f"{field} renders a None",
                        "no None", txt[:120])

    w = check("weather_now", {"place": "رام الله"})
    if w:
        govs = {g.get("governorate") for g in (w.get("governorates") or [])}
        if govs and len(govs) == 1 and "الضفة" in (w.get("answer") or "") \
                and "West Bank" in (w.get("answer_en") or ""):
            finding("minor", "weather_now",
                    "a single-governorate answer still reads as West Bank-wide",
                    f"about {list(govs)[0]}", w["answer"][:110])

    f = check("fuel_prices", {})
    if f:
        dates = sorted({p.get("effective_from") for p in f["prices"]
                        if p.get("price") is not None and p.get("effective_from")})
        missing = [dt for dt in dates if dt not in (f.get("answer") or "")]
        if len(dates) > 1 and missing:
            finding("minor", "fuel_prices",
                    "the headline leaves some effective dates unstated",
                    sorted(dates), missing)

    t = check("trend", {"indicator": "casualties.annual_total", "days": 90})
    if t and t.get("last"):
        if str(t["last"])[:10] not in (t.get("answer") or ""):
            finding("critical", "trend",
                    "the claim does not name the date of the reading it is about",
                    str(t["last"])[:10], t["answer"][:110])
        if "last_age_days" not in t:
            finding("major", "trend", "no age for the newest point", "last_age_days",
                    list(t.keys()))
    if t and len(t) <= 3:
        finding("major", "trend", "returns no series to check its own claim against",
                "points + ages", list(t.keys()))

    cs = check("checkpoints_summary", {})
    if cs:
        missing = [c["name"] for c in cs["closed_now"] if "place_id" not in c]
        if missing:
            finding("major", "checkpoints_summary",
                    "closed_now entries carry no place id, so a shared name looks "
                    "like a duplicate", "a place_id per entry", missing[:4])


# ── D. edges: a tool must refuse in words, never with a bare empty ───────────
def audit_edges() -> None:
    probes = [
        ("where_is", {"place": "زززززز"}),
        ("checkpoint_status", {"name": "ززززززز"}),
        ("insights", {"place": "ززززززز"}),
        ("place_history", {"place": "ززززززز"}),
        ("place_pattern", {"place": "ززززززز"}),
        ("incidents_near", {"place": "ززززززز"}),
        ("checkpoints_near", {"place": "ززززززز"}),
    ]
    for tool, args in probes:
        d = check(tool, args)
        if d is None:
            continue
        # Unconditional (audit F488): the old test fired only when the payload
        # happened to carry `found`, `count` or `answer`, so a bare `{}` or
        # `{"results": []}` for a place that does not exist — exactly the reply
        # this probe exists to catch — passed silently.
        if not isinstance(d, dict) or not (isinstance(d.get("answer"), str)
                                           and d["answer"].strip()):
            finding("major", tool, "refusal without words", "an answer", d)
    for tool, args in (("insights", {"place": "رام الله", "days": 365, "radius_km": 60}),
                       ("checkpoints_near", {"place": "نابلس", "radius_km": 60, "limit": 1}),
                       ("incidents_summary", {"hours": 24})):
        check(tool, args)              # must not raise; a raise is recorded by check()


def _place_id(place: str) -> int:
    from resolve.geo import resolve_place
    r = resolve_place(place, learn=False)
    return r.place_id if r else -1


def _dupes(names: list[str]) -> dict:
    seen: dict[str, int] = {}
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    return {k: v for k, v in seen.items() if v > 1}


ARTIFACTS = ("None", "nan", "NaN", "undefined", "[object", "null,")


RENDER_PROBES = {
    "coverage": {}, "checkpoints_summary": {}, "incidents_summary": {"hours": 24},
    "weather_now": {}, "fuel_prices": {}, "crossings": {},
    "connectivity_now": {}, "data_gaps": {}, "licenses": {}, "databank": {},
    "latest_news": {"limit": 3}, "search": {"text": "حاجز", "hours": 24},
    "area_history": {"days": 7}, "insights": {"place": "نابلس", "days": 7},
    "place_pattern": {"place": "نابلس"}, "place_history": {"place": "نابلس"},
    "place_profile": {"place": "نابلس"}, "where_is": {"place": "نابلس"},
    "checkpoints_near": {"place": "نابلس", "limit": 3},
    "checkpoint_status": {"name": "حوارة"},
    "incidents_near": {"place": "نابلس", "hours": 168, "limit": 3},
    "trend": {"indicator": "casualties.annual_total"},
    "can_i_travel": {"origin": "رام الله", "destination": "نابلس"},
}


def audit_renderer_artifacts() -> None:
    """Cheap and general: a sentence that contains "None" or "nan" is a
    formatting bug the reader sees, wherever it comes from. This is what caught
    "In the last Noneh" — as a class rather than one occurrence."""
    for tool, args in RENDER_PROBES.items():
        # A probe for a tool that no longer exists is a coverage claim that is
        # not true (audit F489: `fuels` was skipped here silently every night).
        # It is said out loud, as a minor, until the probe list is corrected.
        try:
            target = route(tool, args)[0]
        except TypeError:
            target = None
        if target not in TOOLS:
            finding("minor", "audit", f"probe names no tool: {tool}",
                    "a tool in TOOLS or a façade", None)
            continue
        d = check(tool, args)
        if not isinstance(d, dict):
            continue
        for field in ("answer", "answer_en", "caveat", "note"):
            txt = d.get(field)
            if isinstance(txt, str):
                for art in ARTIFACTS:
                    if art in txt:
                        finding("major", tool, f"{field} contains {art!r}",
                                "no rendering artifact", txt[:120])


ALERT_UNIT = "palestine-v2:mcp-audit"


def verdict(findings: list[dict]) -> dict:
    """The artifact ops/mcp-accuracy.json carries. Built here, not inline in
    main(), so its shape is testable on a checkout where the gitignored file
    has never been written (audit F492/F583)."""
    counts = {sev: sum(1 for f in findings if f.get("severity") == sev)
              for sev in ("critical", "major", "minor")}
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counts": counts, "findings": list(findings)}


def page(crit: list[dict]) -> None:
    """Alert on a critical, resolve when the surface comes back clean.

    A condition rather than an event: an unfixed critical must not page every
    night, and a fixed one must close what it opened. `--no-alert` exists for
    manual runs while fixing, which is when the alert would be noise about
    something the person running it already knows.
    """
    from ops.alert import open_alerts, raise_alert, resolve
    is_open = any(r.get("unit") == ALERT_UNIT for r in open_alerts())
    if crit and not is_open:
        first = crit[0]
        raise_alert(ALERT_UNIT,
                    f"{len(crit)} critical accuracy finding(s). First: "
                    f"{first['tool']} — {first['claim']} (expected "
                    f"{str(first['expected'])[:60]}, got {str(first['got'])[:60]}). "
                    f"See ops/mcp-accuracy.json.")
    elif not crit and is_open:
        resolve(ALERT_UNIT, "every accuracy check passes")


def main() -> int:
    ap = argparse.ArgumentParser(description="measured accuracy of the MCP surface")
    ap.add_argument("--no-alert", action="store_true",
                    help="report only; never page (manual runs while fixing)")
    a = ap.parse_args()
    print("MCP accuracy audit —", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for fn in (audit_serving_invariants, audit_checkpoints_summary, audit_checkpoints_near,
               audit_incidents_summary, audit_insights, audit_fuel_prices, audit_coverage,
               audit_crossings, audit_databank, audit_area_history,
               audit_answer_vs_payload, audit_edges, audit_renderer_artifacts):
        print(f"  {fn.__name__} ...")
        try:
            fn()
        except Exception as exc:                                 # noqa: BLE001
            finding("critical", "audit", f"{fn.__name__} crashed",
                    "a completed check", f"{type(exc).__name__}: {exc}")
    crit = [f for f in FINDINGS if f["severity"] == "critical"]
    major = [f for f in FINDINGS if f["severity"] == "major"]
    minor = [f for f in FINDINGS if f["severity"] == "minor"]
    print(f"\nfindings: {len(crit)} critical, {len(major)} major, {len(minor)} minor")
    for f in FINDINGS:
        print(f"  [{f['severity'][:4].upper()}] {f['tool']}: {f['claim']}\n"
              f"        expected {str(f['expected'])[:110]}\n"
              f"        got      {str(f['got'])[:110]}")
    (ROOT / "ops" / "mcp-accuracy.json").write_text(
        json.dumps(verdict(FINDINGS), indent=1, default=str))

    if not a.no_alert:
        page(crit)
    # 1, not the count: the wrapper's OK_EXIT_CODES treats 1 as "ran fine and
    # found something", and the count is in ops/mcp-accuracy.json.
    return 1 if crit else 0


if __name__ == "__main__":
    raise SystemExit(main())
