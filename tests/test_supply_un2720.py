"""The UN2720 supply line: a NEW source, so there is no held data to match.

What is proved here instead, offline (no network, no database):
  - the fetcher reads the publisher's real answers (saved 2026-10-12 under
    tests/fixtures/supply_un2720/: the page's own block, the landing totals,
    and the three stages asked for July 2026) and refuses the shapes that
    would write a wrong series;
  - a quiet night leaves the raw file's bytes alone, a refused night leaves
    the file and says so in the ledger, a dry run leaves nothing;
  - the spec is valid, the engine turns the fetcher's records into rows whose
    declared identity is injective, and every indicator it emits has exactly
    one registry rule, with a warning in both languages;
  - it never becomes one series with UNRWA's truck log.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from ingest import databank
from ingest.databank import load_spec
from ops import fetch_un2720 as un
from ops import fetchlib as fl
from ops import gap_radar as gr
from ops.load_registry import classify, matches

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "supply_un2720"
PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2}, "governorate": {},
          "crossing": {}, "pcode": {}}
JULY = {"floor": "2026-07-01", "until": "2026-07-31", "capped": True,
        "intercepted": False}
# What the fixtures hold, counted by hand from the saved answers.
DAYS = {"offloaded": 22, "collected": 27, "arrived": 27}
TRUCKS = {"offloaded": 2849, "collected": 2480, "arrived": 2480}


def answers() -> dict:
    return {s: json.loads((FX / f"{s}_2026-07.json").read_text()) for s in un.STAGES}


def summary() -> dict:
    return json.loads((FX / "summary.json").read_text())


@pytest.fixture
def low_floors(monkeypatch):
    """The fixtures are one month; the real floors are for sixteen."""
    monkeypatch.setattr(un, "FLOORS", {s: 20 for s in un.STAGES})


def doc(props=JULY) -> dict:
    return un.build(dict(props), summary(), answers())


# ── the page's own window ────────────────────────────────────────────────────

def test_the_window_is_read_from_the_page_itself():
    props = un.landing_props((FX / "landing.html").read_text())
    assert props == {"floor": "2025-05-19", "until": "2026-08-31",
                     "capped": True, "intercepted": False}


def test_the_older_attribute_form_of_the_page_reads_the_same():
    page = ('<div id="app" data-page="{&quot;props&quot;:{&quot;floor&quot;:'
            '&quot;2025-05-19&quot;,&quot;until&quot;:&quot;2026-09-30&quot;,'
            '&quot;capped&quot;:false}}"></div>')
    assert un.landing_props(page) == {"floor": "2025-05-19", "until": "2026-09-30",
                                      "capped": False, "intercepted": False}


@pytest.mark.parametrize("page", [
    "<html><body>maintenance</body></html>",
    '<script data-page="app" type="application/json">{"props":{"floor":"2025-05-19"}}</script>',
    '<script data-page="app" type="application/json">{"props":{"floor":"2025-05-19","until":"soon"}}</script>',
    '<script data-page="app" type="application/json">{"props":{"floor":"2026-05-19","until":"2025-05-19"}}</script>',
])
def test_a_page_without_a_readable_window_is_refused(page):
    with pytest.raises(fl.FetchRefused):
        un.landing_props(page)


# ── the three stages ─────────────────────────────────────────────────────────

def test_each_stage_reads_as_the_publisher_charted_it():
    a = answers()
    series = {s: un.daily_series(s, a[s]) for s in un.STAGES}
    assert {s: len(v) for s, v in series.items()} == DAYS
    assert {s: sum(r["trucks"] for r in v) for s, v in series.items()} == TRUCKS
    # one day read by eye from the saved Offloaded answer
    assert series["offloaded"][0] == {"day": "2026-07-01", "trucks": 105,
                                      "pallets": 1940, "tonnes": 998.05}
    for v in series.values():
        days = [r["day"] for r in v]
        assert days == sorted(days) and len(set(days)) == len(days)
        assert all("2026-07-01" <= d <= "2026-07-31" for d in days)


def test_the_days_sum_to_the_publishers_own_total():
    a = answers()
    for s in un.STAGES:
        total = un.publisher_total(s, a[s])
        un.check_stage(s, un.daily_series(s, a[s]), total, floor_days=20)   # no refusal
        got = un.summarise(un.daily_series(s, a[s]))
        assert got["trucks"] == total["trucks"] and got["pallets"] == total["pallets"]
        assert abs(got["tonnes"] - total["tonnes"]) < 1.0
    assert un.publisher_total("offloaded", a["offloaded"]) == {
        "trucks": 2849, "pallets": 62036, "tonnes": 36605.269, "requests": 553}


def test_a_short_answer_is_refused():
    a = answers()
    s = un.daily_series("collected", a["collected"])
    with pytest.raises(fl.FetchRefused, match="below the floor"):
        un.check_stage("collected", s, un.publisher_total("collected", a["collected"]), 375)


def test_a_series_that_lost_a_day_is_refused_even_above_the_floor():
    """The floor cannot see one missing day; the publisher's total can."""
    a = answers()["offloaded"]
    cut = {**a, "barLabels": a["barLabels"][:-1], "barTrucks": a["barTrucks"][:-1],
           "barPallets": a["barPallets"][:-1], "barWeights": a["barWeights"][:-1]}
    with pytest.raises(fl.FetchRefused, match="not the whole of it"):
        un.check_stage("offloaded", un.daily_series("offloaded", cut),
                       un.publisher_total("offloaded", cut), 20)
    heavy = {**a, "barWeights": [w + 10 for w in a["barWeights"]]}
    with pytest.raises(fl.FetchRefused, match="publisher's total says"):
        un.check_stage("offloaded", un.daily_series("offloaded", heavy),
                       un.publisher_total("offloaded", heavy), 20)


@pytest.mark.parametrize("break_it", [
    lambda a: a.update(barLabels=a["barLabels"] + [a["barLabels"][0]],
                       barTrucks=a["barTrucks"] + [1], barPallets=a["barPallets"] + [1],
                       barWeights=a["barWeights"] + [1.0]),          # a day twice
    lambda a: a.update(barTrucks=a["barTrucks"][:-1]),                # ragged
    lambda a: a.update(barLabels=["July 1"] + a["barLabels"][1:]),    # not a date
    lambda a: a.update(barTrucks=[-1] + a["barTrucks"][1:]),          # negative
    lambda a: a.update(barWeights=["12.5"] + a["barWeights"][1:]),    # text
    lambda a: a.pop("barPallets"),                                    # field gone
])
def test_a_shape_that_cannot_be_read_whole_is_refused(break_it):
    a = answers()["offloaded"]
    break_it(a)
    with pytest.raises(fl.FetchRefused):
        un.daily_series("offloaded", a)


def test_days_outside_the_pages_window_are_counted_and_never_written():
    s = un.daily_series("offloaded", answers()["offloaded"])
    kept, outside = un.clip(s, "2026-07-01", "2026-07-15")
    assert outside == len(s) - len(kept) > 0
    assert max(r["day"] for r in kept) <= "2026-07-15"


# ── the document it writes ───────────────────────────────────────────────────

def test_the_document_carries_the_vintage_and_everything_the_publisher_said(low_floors):
    d = doc()
    m = d["metadata"]
    assert m["vintage"] == "2026-07-31" == m["until"] and m["floor"] == "2026-07-01"
    assert m["vintage_url"] == "https://tracking.un2720.org/" and "until" in m["vintage_basis"]
    assert m["capped"] is True and m["intercepted_section_published"] is False
    assert "none stated" in m["license"]
    assert {s: m["stages"][s]["days"] for s in un.STAGES} == DAYS
    assert m["records"] == len(d["data"]) == sum(DAYS.values()) * 3 == 228
    # the to-date splits are kept, not loaded
    assert d["publisher"]["offloaded"]["entryPoints"] == {"kerem shalom": 2849}
    assert d["publisher"]["summary"] == summary()
    assert d["publisher"]["window"] == JULY


def test_records_are_in_the_engines_shape_with_deterministic_ids(low_floors):
    recs = doc()["data"]
    ids = [r["stable_id"] for r in recs]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"un2720-(offloaded|collected|arrived)-2026-07-\d\d-"
                            r"(trucks|pallets|tonnes)", i) for i in ids)
    assert Counter(r["unit"] for r in recs) == {"truck": 76, "pallet": 76, "tonne": 76}
    first = recs[0]
    assert first == {
        "stable_id": "un2720-offloaded-2026-07-01-trucks", "date": "2026-07-01",
        "stage": "offloaded", "measure": "trucks", "value": 105, "unit": "truck",
        "indicator_name": "Offloaded (in any of the crossings along Gaza's perimeter): Trucks",
        "location": {"region": "Gaza Strip"}, "sources": [un.SOURCE]}
    assert doc()["data"] == recs                     # same answers, same records


def test_all_three_stages_pass_or_nothing_is_built(low_floors):
    a = answers()
    a["arrived"]["dailyTrucks"] = a["arrived"]["dailyTrucks"][:-1]
    with pytest.raises(fl.FetchRefused):
        un.build(dict(JULY), summary(), a)


def test_only_the_stamp_is_ignored_when_two_fetches_are_compared(low_floors):
    a, b = doc(), doc()
    b["metadata"]["fetched_at"] = "2099-01-01T00:00:00+00:00"
    assert un.same_content(a, b)
    b["data"][0]["value"] += 1
    assert not un.same_content(a, b)


# ── the run: quiet night, refused night, dry run ─────────────────────────────

def _wire(monkeypatch, tmp_path, fetched):
    out = tmp_path / "raw" / "un2720" / "daily.json"
    ledger = tmp_path / "fetch-events.ndjson"
    monkeypatch.setattr(un, "OUT", out)
    monkeypatch.setattr(fl, "ROOT", tmp_path)
    monkeypatch.setattr(fl, "EVENTS", ledger)
    monkeypatch.setattr(un, "fetch", fetched)
    return out, ledger


def _events(ledger):
    return [json.loads(x) for x in ledger.read_text().splitlines()] if ledger.exists() else []


def test_a_quiet_night_leaves_the_bytes_alone_and_a_revision_rewrites(monkeypatch, tmp_path, low_floors):
    state = {"a": answers()}
    out, ledger = _wire(monkeypatch, tmp_path, lambda: (dict(JULY), summary(), state["a"]))
    assert un.main([]) == 0
    first = out.read_bytes()
    assert un.main([]) == 0
    assert out.read_bytes() == first                       # nothing new for bronze
    ev = _events(ledger)
    assert [(e["label"], e["outcome"], e["changed"]) for e in ev] == [
        ("un2720:daily", "ok", True), ("un2720:daily", "ok", False)]
    assert ev[0]["vintage"] == "2026-07-31" and ev[0]["rows"] == 228
    # the publisher revises one day (and its own total with it)
    a = answers()
    a["offloaded"]["barTrucks"][0] += 5
    a["offloaded"]["totalSummary"]["trucks"] += 5
    state["a"] = a
    assert un.main([]) == 0
    assert out.read_bytes() != first
    assert json.loads(out.read_text())["data"][0]["value"] == 110
    assert _events(ledger)[-1]["changed"] is True


def test_a_refused_night_keeps_yesterdays_file_and_says_so(monkeypatch, tmp_path, low_floors):
    state = {"a": answers()}
    out, ledger = _wire(monkeypatch, tmp_path, lambda: (dict(JULY), summary(), state["a"]))
    assert un.main([]) == 0
    good = out.read_bytes()
    bad = answers()
    bad["collected"]["barLabels"] = bad["collected"]["barLabels"][:3]
    bad["collected"]["barTrucks"] = bad["collected"]["barTrucks"][:3]
    bad["collected"]["barPallets"] = bad["collected"]["barPallets"][:3]
    bad["collected"]["barWeights"] = bad["collected"]["barWeights"][:3]
    state["a"] = bad
    assert un.main([]) == 1
    assert out.read_bytes() == good
    last = _events(ledger)[-1]
    assert last["outcome"] == "refused" and "below the floor" in last["why"]

    def down():
        raise OSError("connection reset")
    monkeypatch.setattr(un, "fetch", down)
    assert un.main([]) == 1
    assert out.read_bytes() == good and _events(ledger)[-1]["outcome"] == "error"


def test_a_dry_run_writes_nothing_and_leaves_no_ledger_line(monkeypatch, tmp_path, low_floors):
    out, ledger = _wire(monkeypatch, tmp_path, lambda: (dict(JULY), summary(), answers()))
    assert un.main(["--dry-run"]) == 0
    assert not out.exists() and not ledger.exists()
    assert un.main(["--dry-run", "--stage", str(tmp_path / "staged")]) == 0
    assert not out.exists() and not ledger.exists()
    assert json.loads((tmp_path / "staged" / "daily.json").read_text())["metadata"]["records"] == 228


# ── the spec and the rows the engine makes of it ─────────────────────────────

def _rows(recs):
    spec = load_spec("aid_un2720")
    counts = Counter()
    out = []
    for rec in recs:
        got = databank.t_engine(rec, spec, PLACES, counts)
        assert not isinstance(got, databank.Drop), got
        out += got
    return spec, out, counts


def test_the_spec_is_valid_and_wired_to_the_fetcher():
    spec = load_spec("aid_un2720")                       # validates, or raises
    assert spec["transform"] == "engine"
    assert databank.TRANSFORMERS["aid_un2720"] is databank.t_engine
    assert spec["v1_category"] == "aid_access"
    assert [d["key"] for d in spec["datasets"]] == ["un2720_aid_daily"]
    assert spec["source_routing"]["by_name"] == {un.SOURCE["name"]: "un2720"}
    assert spec["datasets"][0]["source"] == "un2720"
    assert (ROOT / spec["input"]["root"] / spec["input"]["glob"]) == \
        ROOT / "data" / "raw" / "un2720" / "daily.json" == \
        ROOT / un.OUT.relative_to(fl.ROOT)
    assert spec["identity"]["generation"] == "complete"
    assert "value_num" not in spec["identity"]["fields"]   # a revision supersedes


def test_the_engine_emits_one_row_per_record_on_the_gaza_strip(low_floors):
    recs = doc()["data"]
    spec, rows, counts = _rows(recs)
    assert len(rows) == len(recs) == 228 and counts["place_rung:region"] == 228
    assert {r.dataset_key for r in rows} == {"un2720_aid_daily"}
    assert {r.place_id for r in rows} == {1} and {r.precision for r in rows} == {"day"}
    assert {r.attrs == {} for r in rows} == {True}       # nothing that moves nightly
    per = Counter(r.indicator for r in rows)
    assert per == {f"aid_un2720.{s}.{m}": DAYS[s] for s in un.STAGES for m in un.MEASURES}
    r = rows[0]
    assert (r.indicator, r.occurred_at, r.value_num, r.unit, r.v1_stable_id) == (
        "aid_un2720.offloaded.trucks", "2026-07-01", 105, "truck",
        "un2720-offloaded-2026-07-01-trucks")
    assert {(r.indicator.rsplit(".", 1)[1], r.unit) for r in rows} == {
        ("trucks", "truck"), ("pallets", "pallet"), ("tonnes", "tonne")}


def _identities(spec, rows):
    return [databank.identity_key_for(
        spec["identity"], r.dataset_key, indicator=r.indicator,
        occurred_at=r.occurred_at, place_id=r.place_id, value_num=r.value_num,
        attrs=r.attrs) for r in rows]


def test_the_declared_identity_is_injective_and_ignores_the_value(low_floors):
    d = doc()
    spec, rows, _ = _rows(d["data"])
    keys = _identities(spec, rows)
    assert len(set(keys)) == len(keys) == 228
    revised = json.loads(json.dumps(d["data"]))
    revised[0]["value"] += 7
    _, rows2, _ = _rows(revised)
    assert _identities(spec, rows2) == keys              # same row, new reading
    assert databank.content_of(value_num=rows2[0].value_num, value_text=None,
                               unit=rows2[0].unit, place_id=1, attrs={}) != \
        databank.content_of(value_num=rows[0].value_num, value_text=None,
                            unit=rows[0].unit, place_id=1, attrs={})


def test_the_fetched_file_if_present_is_injective_too():
    """Over the real raw file when this checkout has fetched one; the nightly
    proof is the loader's own invariant."""
    if not un.OUT.exists():
        pytest.skip("no data/raw/un2720/daily.json in this checkout")
    spec, rows, _ = _rows(json.loads(un.OUT.read_text())["data"])
    keys = _identities(spec, rows)
    assert len(set(keys)) == len(keys) >= spec["expect"]["min_records"]
    assert len(rows) <= spec["expect"]["max_observations"]


# ── meaning: every series has one rule, a unit and a warning ─────────────────

INDICATORS = [f"aid_un2720.{s}.{m}" for s in un.STAGES for m in un.MEASURES]
UNIT_OF = {"trucks": ("truck", "vehicles"), "pallets": ("pallet", "packages"),
           "tonnes": ("tonne", "tonne")}


def test_every_series_has_exactly_one_rule_and_it_is_a_days_flow():
    rules = load_spec("aid_un2720")["registry"]["rules"]
    assert len(rules) == 9
    for ind in INDICATORS:
        raw, canonical = UNIT_OF[ind.rsplit(".", 1)[1]]
        hit = [r for r in rules if matches(r, ind, raw)]
        assert len(hit) == 1, ind
        r = hit[0]
        assert (r["concept"], r["measure_kind"], r["grain"], r["place_grain"]) == (
            "aid.access", "flow", "day", "region")
        assert r["canonical_unit"] == canonical
        assert r["name_en"] and r["name_ar"]
    got, conflicts = classify([(i, UNIT_OF[i.rsplit(".", 1)[1]][0], 100)
                               for i in INDICATORS], rules)
    assert set(got) == set(INDICATORS) and not conflicts


def test_the_units_are_ones_the_registry_already_resolves():
    units = yaml.safe_load((ROOT / "db" / "registry" / "units.yaml").read_text())["units"]
    resolves = {}
    for key, u in units.items():
        resolves[key] = key
        for raw, a in (u.get("aliases") or {}).items():
            resolves[raw] = (a or {}).get("unit", key)
    assert {raw: resolves[raw] for raw, _ in UNIT_OF.values()} == {
        "truck": "vehicles", "pallet": "packages", "tonne": "tonne"}


def test_every_warning_says_what_the_number_is_not_in_both_languages():
    for r in load_spec("aid_un2720")["registry"]["rules"]:
        en, ar = r["serve_warning"], r["serve_warning_ar"]
        assert "UN2720" in en and "UNRWA" in en and "16 January 2025" in en
        assert "never one series" in en
        assert "only cargo sent through" in en
        assert "الأونروا" in ar and "2720" in ar and "16 كانون الثاني 2025" in ar
        assert re.search(r"[؀-ۿ]", ar) and not re.search(r"[A-Za-z]", ar)
    by = {r["when"]["equals"]: r for r in load_spec("aid_un2720")["registry"]["rules"]}
    # the publisher's own caution about truck sizes sits on the two truck counts
    assert "do not compare" in by["aid_un2720.offloaded.trucks"]["serve_warning"]
    assert "do not compare" in by["aid_un2720.collected.trucks"]["serve_warning"]
    assert "Collected is not delivered" in by["aid_un2720.collected.tonnes"]["serve_warning"]
    assert "nothing about distribution" in by["aid_un2720.arrived.trucks"]["serve_warning"]


# ── never one series with UNRWA's truck log ──────────────────────────────────

def test_the_two_aid_series_share_a_category_and_nothing_else():
    old, new = load_spec("aid_access"), load_spec("aid_un2720")
    assert new["v1_category"] == old["category"] == "aid_access"
    assert {d["key"] for d in old["datasets"]}.isdisjoint(d["key"] for d in new["datasets"])
    assert {d["source"] for d in old["datasets"]}.isdisjoint(d["source"] for d in new["datasets"])
    # neither spec's rules reach the other's indicators
    for ind in INDICATORS:
        assert not any(matches(r, ind, "truck") for r in old["registry"]["rules"])
    for ind in ("aid_access.consignment.food_items", "aid_access.consignment.medical_supplies"):
        assert not any(matches(r, ind, "pallet") for r in new["registry"]["rules"])
    # and the radar does not hand UNRWA's series over to it
    assert "v1_aid_access_unrwa_aid_trucks" not in gr.CONTINUED_BY
    assert "un2720_aid_daily" not in gr.CONTINUED_BY.values()
    assert "v1_aid_access_unrwa_aid_trucks" in gr.DEAD_UPSTREAM


# ── the radar and the proposed rows ──────────────────────────────────────────

def test_the_radar_knows_the_line_and_the_publishers_cap():
    line = gr.SUPPLY_LINES["un2720"]
    assert line["labels"] == [un.LABEL] and line["feeds"] == ["un2720_aid_daily"]
    assert (ROOT / line["fetcher"]).exists()
    # a daily series capped by its publisher six weeks back must not read as
    # stalled (age > 2 x allowance) on the night it is first loaded
    assert 42 <= gr.ALLOWANCE_OVERRIDE_DAYS["un2720_aid_daily"] <= 60


def test_the_proposed_rows_are_ask_and_match_the_spec():
    # the proposal, numbered as migration 106 on 2026-10-12
    sql = (ROOT / "db" / "migrations" / "106_un2720_aid_source.sql").read_text()
    spec = load_spec("aid_un2720")
    assert f"SELECT '{spec['datasets'][0]['source']}'," in sql
    assert f"SELECT '{spec['datasets'][0]['key']}'," in sql
    statements = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    assert "'no-license-found', false, false, true," in statements   # no licence; not commercial
    assert "\n       'ask',\n" in statements
    assert "'aid_access', 'daily', true" in statements
    assert "WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'un2720')" in statements
    for forbidden in ("UPDATE ", "DELETE ", "DROP ", "ALTER "):
        assert forbidden not in statements
