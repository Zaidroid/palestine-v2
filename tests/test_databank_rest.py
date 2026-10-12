"""The rest of the databank's defects from the 2026-10-11 audit (finding 08 and
plan H), fixed on 2026-10-12/13. One section per defect; each test says in its
name the thing a reader of an answer would have got wrong."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import licence                                                    # noqa: E402

FILTERED = {"grade": "share-alike", "partner_tier": "filtered"}


# ── the partner tier is a commercial one ─────────────────────────────────────
# Measured 2026-10-12: 22,140 served rows are licensed for non-commercial use
# only and graded attribution or share-alike (WHO 12,577, UCDP 7,638, OONI
# 1,376, IMF 474, the UNRWA camp rows 75). The partner filter asked for the
# grade alone, so every one of them travelled in a partner payload.

def _who_row(**over):
    return {"indicator": "health.x", "source_key": "who", "redistribution": "share-alike",
            "commercial_use": False, "value_num": 1.0} | over


def test_a_non_commercial_row_stays_out_of_a_partner_payload_and_the_cut_says_why():
    out = {"answer": "x", "answer_en": "x", "count": 3, "items": [
        _who_row(), _who_row(),
        {"indicator": "economic.y", "source_key": "worldbank",
         "redistribution": "attribution", "commercial_use": True}]}
    got = licence.apply("databank", out, "partner", FILTERED)
    assert [it["source_key"] for it in got["items"]] == ["worldbank"]
    w = got["licence"]["withheld"]
    assert w["rows"] == 2 and w["non_commercial_rows"] == 2
    assert w["by_source"] == {"who (share-alike, non-commercial)": 2}
    assert "non-commercial use only" in got["answer_en"]
    assert "الاستخدام التجاري" in got["answer"]
    assert got["count"] == 1


def test_a_non_commercial_series_keeps_its_summary_and_loses_its_points():
    out = {"answer": "x", "answer_en": "x", "series": [
        {"indicator": "connectivity.ooni", "redistribution": "share-alike",
         "commercial_use": False, "sources": ["OONI"],
         "points": [{"at": "2026-10-01", "value": 1}] * 7, "n": 7},
        {"indicator": "economic.y", "redistribution": "attribution",
         "commercial_use": True, "sources": ["World Bank"],
         "points": [{"at": "2020-01-01", "value": 1}] * 4, "n": 4}]}
    got = licence.apply("compare", out, "partner", FILTERED)
    ooni, wb = got["series"]
    assert ooni["points"] == [] and ooni["points_withheld"] == 7 and ooni["n"] == 7
    assert len(wb["points"]) == 4
    assert got["licence"]["withheld"]["non_commercial_rows"] == 7


def test_the_house_keeps_every_non_commercial_row():
    out = {"items": [_who_row(), _who_row()], "count": 2}
    got = licence.apply("databank", out, "house", FILTERED)
    assert len(got["items"]) == 2 and "withheld" not in got["licence"]


def test_a_row_that_does_not_say_is_judged_on_its_grade_as_before():
    # the live tier's rows and older payloads carry no flag at all
    assert licence.partner_may_carry("attribution", None) is None
    assert licence.partner_may_carry("ask", None) == "grade"
    assert licence.partner_may_carry("share-alike", False) == "non-commercial"
    assert licence.partner_may_carry("no-redistribution", False) == "grade"
    assert licence.partner_may_carry("open", True) is None


def test_the_mixed_cut_names_both_reasons():
    out = {"answer": "x", "answer_en": "x", "items": [
        _who_row(),
        {"indicator": "casualties.annual_total", "source_key": "ocha_casualties",
         "redistribution": "no-redistribution", "commercial_use": False}]}
    got = licence.apply("databank", out, "partner", FILTERED)
    assert got["items"] == []
    assert got["licence"]["withheld"]["rows"] == 2
    assert got["licence"]["withheld"]["non_commercial_rows"] == 1
    assert "redistribution or commercial use" in got["answer_en"]


def test_the_routes_hand_the_flag_to_the_licence_layer():
    src = (ROOT / "serve" / "app.py").read_text()
    assert "COALESCE(d.commercial_use, s.commercial_use)     AS commercial_use" in src
    assert '"license_spdx", "redistribution", "commercial_use")' in src
    assert '"commercial_use": commercial_use,' in src
    assert licence.table(lambda *a, **k: [], set())["partner_requires_commercial_use"] is True


# ── when a row is about ──────────────────────────────────────────────────────
# "5,304 persons in 2008-01-01" was OCHA's count of people killed in Gaza
# between 2008 and 2023; "1 schools in 2026-08-05" was a register row whose
# only date is the day v1 downloaded it.

from serve.when import when_ar, when_en                                      # noqa: E402

GAZA_TOTAL = {"indicator": "casualties.region.gaza_strip", "value_num": 5304.0,
              "occurred_at": "2008-01-01T00:00:00Z", "occurred_precision": "unknown",
              "attrs": {"coverage_start": "2008-01-01", "coverage_end": "2023-09-19"}}
SCHOOL = {"indicator": "education.school_record", "value_num": 1.0,
          "occurred_at": "2026-08-05T00:00:00Z", "occurred_precision": "unknown", "attrs": {}}


def test_a_period_total_names_both_ends_of_its_period():
    assert when_en(GAZA_TOTAL) == "between 2008-01-01 and 2023-09-19 (one total for the period)"
    assert "من 2008-01-01 لغاية 2023-09-19" in when_ar(GAZA_TOTAL)
    assert "2008-01-01" not in when_en(GAZA_TOTAL).split("between")[0]


def test_a_register_row_is_never_dated_by_the_day_it_was_fetched():
    assert "2026-08-05" not in when_en(SCHOOL) and "2026-08-05" not in when_ar(SCHOOL)
    assert when_en(SCHOOL) == "with no date given by the source"
    dated = SCHOOL | {"dataset_vintage": "2023-07-25"}
    assert when_en(dated) == "in the publisher's register of 2023-07-25"
    assert "2023-07-25" in when_ar(dated)


def test_a_dated_row_is_said_at_its_own_precision_and_no_finer():
    row = {"occurred_at": "2024-01-01T00:00:00Z", "attrs": {}}
    assert when_en(row | {"occurred_precision": "year"}) == "in 2024"
    assert when_en(row | {"occurred_precision": "month"}) == "in 2024-01"
    assert when_en(row | {"occurred_precision": "day"}) == "on 2024-01-01"
    assert when_ar(row | {"occurred_precision": "year"}) == "سنة 2024"


def test_the_english_databank_answer_uses_it():
    from serve import mcp_en
    said = mcp_en.databank({"category": "casualties", "count": 1,
                            "latest_by_indicator": [GAZA_TOTAL | {"unit": "persons"}]})
    assert "between 2008-01-01 and 2023-09-19" in said and "in 2008-01-01" not in said


def test_a_period_total_is_never_differenced_into_a_flow():
    sql = (ROOT / "db" / "migrations" /
           "104_flows_and_freshness_count_what_is_there.sql").read_text()
    assert "v.occurred_precision <> 'unknown'" in sql
    assert "FILTER (WHERE upper_inf(o.sys_period))" in sql and "FROM event e" in sql


# ── correlate: four things the audit found ───────────────────────────────────
from serve import correlate as C                                             # noqa: E402


def _s(ind, kind="flow", grain="day", place="region", concept="x", **over):
    return {"indicator": ind, "measure_kind": kind, "grain": grain, "place_grain": place,
            "concept_key": concept, "points": [], "source_names": {"p"}} | over


def test_the_advice_to_difference_a_running_total_can_be_followed():
    a, b = _s("a.cumulative", "cumulative", concept="a"), _s("b.daily", concept="b")
    assert any("CUMULATIVE" in r for r in C.check_comparable(a, b))
    assert C.check_comparable(a, b, "diff") == []


def test_a_running_totals_downward_correction_is_not_a_negative_flow():
    s = _s("a.cumulative", "cumulative", points=[
        {"at": i, "value": v, "prec": "day"} for i, v in enumerate([10, 15, 14, 20])])
    d = C.differenced(s)
    assert [p["value"] for p in d["points"]] == [5.0, 6.0] and d["revisions_left_out"] == 1
    said = C.caveats(d, _s("b", concept="b"), [(1, 1, 0, "day", "day")] * 40, 0)
    assert any("running total" in c and "1 downward correction" in c for c in said)


def test_a_daily_series_and_a_yearly_one_are_refused_as_a_pair():
    stop = C.check_comparable(_s("a", concept="a"), _s("b", grain="year", concept="b"))
    assert len(stop) == 1 and "time grains differ" in stop[0] and "daily" in stop[0]
    assert "الدقة الزمنية مختلفة" in C.reason_ar(stop[0])


def test_one_label_holding_two_units_is_refused():
    milk = _s("food.milk", concept="a", unit_mixed=True, units=["ILS_per_kg", "ILS_per_litre"])
    stop = C.check_comparable(milk, _s("b", concept="b"))
    assert len(stop) == 1 and "more than one unit (ILS_per_kg, ILS_per_litre)" in stop[0]
    assert "أكثر من وحدة" in C.reason_ar(stop[0])


def test_two_publishers_of_one_figure_are_not_pooled():
    from serve.app import _one_source
    pts = ([{"at": i, "source_key": "hamoked"} for i in range(192)]
           + [{"at": i, "source_key": "addameer"} for i in range(50)])
    kept, used, others = _one_source(pts, None)
    assert used == "hamoked" and len(kept) == 192 and others == {"addameer": 50}
    kept, used, others = _one_source(pts, "addameer")
    assert used == "addameer" and len(kept) == 50 and others == {"hamoked": 192}
    one = [{"at": 1, "source_key": "who"}] * 3
    assert _one_source(one, None) == (one, None, {})


def test_a_lag_is_an_order_in_time_and_the_answer_says_so():
    a, b = _s("raids", concept="a"), _s("closures", concept="b")
    said = C.caveats(a, b, [(1, 1, 0, "day", "day")] * 40, 7, shifts=29)
    assert any("raids moving before closures is an order in time, not a cause" in c for c in said)
    assert any("29 shifts were tried" in c for c in said)
    from serve import mcp_en
    en = mcp_en.correlate({"plain_english": "a weak association", "n": 40, "ci95": [0.0, 0.4],
                           "lag_days": 7, "caveats": said})
    assert "order in time, not a cause" in en and "at a lag of 7 days" in en


def test_the_interval_widens_with_the_number_of_shifts_tried():
    one, many = C.fisher_ci(0.5, 40, C.z_for_shifts(1)), C.fisher_ci(0.5, 40, C.z_for_shifts(29))
    assert abs(C.z_for_shifts(1) - 1.96) < 0.001
    assert many[0] < one[0] and many[1] > one[1]


def test_the_mcp_tool_can_ask_for_the_differenced_series():
    from serve import mcp_facades, mcp_server
    import inspect
    assert "detrend" in inspect.signature(mcp_server.correlate).parameters
    assert '"detrend": {"type": "string", "enum": ["none", "diff"]' in \
        (ROOT / "serve" / "mcp_facades.py").read_text()
    assert mcp_facades is not None


# ── a row closed in the transaction that wrote it ────────────────────────────

def test_no_ingest_path_closes_a_row_into_an_empty_range():
    """tstzrange(lower, now()) is EMPTY for a row born in the same transaction:
    it is then current under `upper(sys_period) IS NULL`, absent from every
    as_of, and its replacement hits the unique index (the Ministry re-read,
    2026-10-11)."""
    import re
    from ingest.databank import CLOSE_NOW
    assert "greatest(now(), lower(sys_period) + interval '1 microsecond')" in CLOSE_NOW
    bare = re.compile(r"SET sys_period = tstzrange\(lower\(sys_period\),\s*now\(\)\)")
    for rel in ("ingest/databank.py", "ops/repair_identity.py",
                "ops/backfill_identity.py", "ops/repair_conflict_region.py",
                "ingest/sources/moh_gaza.py"):
        assert not bare.search((ROOT / rel).read_text()), rel
    assert (ROOT / "ingest" / "databank.py").read_text().count("SET sys_period = {CLOSE_NOW}") == 3


# ── the publisher's vintage belongs to the dataset ───────────────────────────

def test_a_fetchers_vintage_reaches_the_dataset_it_names(tmp_path):
    import json
    from ingest.databank import read_vintage
    raw = tmp_path / "schools.json"
    raw.write_text(json.dumps({"metadata": {"vintage": "2023-07-25", "vintage_basis": "HDX dataset_date",
                                            "vintage_url": "https://data.humdata.org/x"}, "data": []}))
    one = {"datasets": [{"key": "v1_education_hdx"}]}
    assert read_vintage(one, [raw]) == {"v1_education_hdx": {
        "vintage": "2023-07-25", "vintage_basis": "HDX dataset_date",
        "vintage_url": "https://data.humdata.org/x"}}
    # a file feeding several datasets must say which one it speaks for
    three = {"datasets": [{"key": "a"}, {"key": "b"}]}
    assert read_vintage(three, [raw]) == {}
    raw.write_text(json.dumps({"vintage_by_dataset": {"b": {"vintage": "2025-10-11"}, "zz": {"vintage": "x"}}}))
    assert read_vintage(three, [raw]) == {"b": {"vintage": "2025-10-11"}}


def test_the_names_list_gets_its_own_cut_off_from_a_sidecar(tmp_path):
    import json
    from ingest.databank import read_vintage
    (tmp_path / "killed_in_gaza.json").write_text("[]")
    (tmp_path / "_vintage.json").write_text(json.dumps({
        "v1_martyrs_snapshot_2023_tech4palestine": {"vintage": "2026-05-07", "coverage_start": "2023-10-07"},
        "t4p_gaza_daily": {"vintage": "2026-10-12"}}))
    spec = {"datasets": [{"key": "v1_martyrs_snapshot_2023_tech4palestine"}]}
    got = read_vintage(spec, [tmp_path / "killed_in_gaza.json"])
    assert got == {"v1_martyrs_snapshot_2023_tech4palestine": {
        "vintage": "2026-05-07", "coverage_start": "2023-10-07"}}


def test_a_name_on_the_list_is_said_to_be_killed_within_the_lists_span_not_on_its_first_day():
    person = {"occurred_at": "2023-10-07T00:00:00Z", "occurred_precision": "unknown", "attrs": {},
              "dataset_vintage": "2026-05-07", "dataset_coverage_start": "2023-10-07"}
    assert when_en(person) == "between 2023-10-07 and 2026-05-07 (the source gives no day)"
    assert "بين 2023-10-07 و2026-05-07" in when_ar(person)


def test_the_roster_says_what_its_dates_are_worth():
    import yaml
    spec = yaml.safe_load((ROOT / "db" / "mappings" / "martyrs_snapshot_2023.yaml").read_text())
    rule = next(r for r in spec["registry"]["rules"] if r["when"] == {"prefix": "martyrs."})
    assert "no date of death" in rule["serve_warning"] and "1 January" in rule["serve_warning"]
    assert "شهداء" in rule["serve_warning_ar"] and "غرزة" not in rule["serve_warning_ar"]


# ── the aid log's own disclaimer, and a month held as a month ────────────────

def test_the_aid_log_says_it_is_partial_after_5_may_2024_and_ends():
    import yaml
    rule = yaml.safe_load((ROOT / "db" / "mappings" / "aid_access.yaml").read_text())["registry"]["rules"][0]
    assert "after 5 May 2024 are partial" in rule["serve_warning"]
    assert "16 January 2025" in rule["serve_warning"] and "floor" in rule["serve_warning"]
    assert "5 أيار 2024" in rule["serve_warning_ar"]


def test_a_village_dated_the_first_of_a_month_is_held_as_that_month():
    from ingest import databank as D
    src = (ROOT / "ingest" / "databank.py").read_text()
    assert 'occurred, precision = day, "month"' in src
    mig = (ROOT / "db" / "migrations" / "105_a_month_is_held_as_a_month.sql").read_text()
    assert "occurred_precision_before" in mig and "extract(day FROM occurred_at" in mig
    assert D is not None


# ── HaMoked's fourth figure ──────────────────────────────────────────────────

def test_the_people_held_as_unlawful_combatants_have_a_series_of_their_own():
    """October 2026: 9,265 held, of whom the three named series accounted for
    7,846. The other 1,419 were in the total and in no series."""
    from ops.fetch_hamoked import month_records
    recs = month_records([{"year": 2026, "month": 10, "sentenced": 1509, "remand": 3236,
                           "administrative": 3101, "unlawful_combatants": 1419}], "direct", "t")
    by = {r["prisoner_metric_type"]: r["metrics"]["count"] for r in recs}
    assert by == {"sentenced": 1509, "remand": 3236, "administrative": 3101,
                  "unlawful_combatants": 1419, "total": 9265}
    assert sum(v for k, v in by.items() if k != "total") == by["total"]


# ── cited figures: one publisher's statement a row ───────────────────────────

def _cite(value, publisher, **attrs):
    return {"indicator": "cited.nakba_1948.refugees", "occurred_at": "1948-01-01T00:00:00Z",
            "occurred_precision": "year", "value_num": value, "unit": "persons", "place_en": None,
            "place_ar": None, "attrs": {"publisher": publisher, "verification": "read", **attrs}}


def test_every_publisher_is_named_beside_its_figure_and_nothing_is_averaged():
    from serve import mcp_en
    items = [_cite(711000, "UNCCP", qualifier="about"), _cite(750000, "UNRWA", qualifier="about"),
             _cite(957000, "PCBS"), _cite(None, "IPS", value_low=714150, value_high=744150)]
    said = mcp_en.databank({"category": "historical", "count": 4, "items": items,
                            "latest_by_indicator": [items[2]]})
    assert "about 711,000 per UNCCP" in said and "about 750,000 per UNRWA" in said
    assert "957,000 per PCBS" in said and "714,150 to 744,150 per IPS" in said
    assert "in 1948" in said


def test_a_figure_seen_on_wikipedia_only_says_so():
    from serve.when import cited_ar, cited_en
    row = _cite(107, "Kan'ana and Zaytawi", verification="via_wikipedia")
    assert cited_en([row]).endswith("(seen on Wikipedia only)")
    assert "ويكيبيديا" in cited_ar([row]) and "حسب Kan'ana and Zaytawi" in cited_ar([row])


def test_the_cited_figures_file_is_well_formed_and_its_built_copy_is_current():
    import yaml
    from ops import build_cited_figures as B
    doc = yaml.safe_load(B.SRC.read_text(encoding="utf-8"))
    figures = [{**(doc.get("defaults") or {}), **f} for f in doc["figures"]]
    assert B.check(figures) == []
    built = __import__("json").loads(B.OUT.read_text(encoding="utf-8"))["data"]
    assert [r["cite_id"] for r in built] == [f["id"] for f in figures]
    assert B.said({"value": 15000, "qualifier": "more_than"}) == "more than 15,000"
    assert B.said({"low": 20, "high": 280}) == "20 to 280"


def test_an_entry_nobody_could_stand_behind_is_refused():
    from ops import build_cited_figures as B
    ok = {"id": "x-1", "topic": "t", "measure": "killed", "date": "1948-04-09", "precision": "day",
          "value": 100, "unit": "persons", "region": "Palestine", "publisher": "P", "document": "D",
          "verification": "read", "read_on": "2026-10-07"}
    assert B.check([ok]) == []
    assert any("publisher" in p for p in B.check([{**ok, "publisher": ""}]))
    assert any("verification" in p for p in B.check([{**ok, "verification": "heard"}]))
    assert any("not both" in p for p in B.check([{**ok, "low": 1, "high": 2}]))
    assert any("used twice" in p for p in B.check([ok, ok]))


# ── a national series asked at a town ────────────────────────────────────────

def test_a_national_series_asked_at_a_place_answers_with_the_national_figure_and_says_so(monkeypatch):
    """WHO, the World Bank, the IMF, UN funding, prisoners: 30,000 rows held at
    no place, their attrs saying region 'Palestine'. Asked at Ramallah they
    answered "no points"."""
    from serve import app as A
    calls = []

    def fake_at(indicator, place_id, frm, to, source=None, national=False):
        calls.append((place_id, national))
        pts = [{"at": 1, "value": 5.0}] if national else []
        return {"known": True, "points": pts, "n": len(pts), "indicator": indicator}

    monkeypatch.setattr(A, "_series_at", fake_at)
    monkeypatch.setattr(A, "_wider_places", lambda p: [{"place_id": 2, "name_ar": "الضفة", "name_en": "West Bank",
                                                        "kind": "region"}])
    s = A._series("economic.sp_pop_totl", 5, None, None)
    assert calls == [(5, False), (2, False), (None, True)]
    assert s["place_used"] == {"place_id": None, "name": "فلسطين كلها",
                               "name_en": "Palestine (the national figure)",
                               "kind": "country", "widened_from": 5}
    src = (ROOT / "serve" / "app.py").read_text()
    assert "v.place_id IS NULL AND v.attrs->>'region' = 'Palestine'" in src


# ── names ────────────────────────────────────────────────────────────────────

def test_a_series_is_named_by_its_publisher_and_its_cut():
    from ops.load_registry import derive_name, name_for
    doc = {"names": {}, "publisher_names": {"Adolescent birth rate (per 1000 women)": "معدل ولادات المراهقات"},
           "dimension_names": {"Female": "إناث"}}
    one_cut = ("Adolescent birth rate\n(per 1000 women)", 1, "Female")
    assert derive_name(one_cut, doc) == ("Adolescent birth rate (per 1000 women) — Female",
                                         "معدل ولادات المراهقات — إناث")
    # several cuts under one key, or none: the series' own name, no label
    assert derive_name(("GDP (current US$)", 2, "x"), doc) == ("GDP (current US$)", None)
    # half an Arabic name is not a name
    assert derive_name(("Adolescent birth rate (per 1000 women)", 1, "Urban"), doc)[1] is None
    # a cut of several dimensions: every label, or no Arabic at all
    doc["dimension_names"]["Both sexes"] = "الجنسان"
    two = ("Adolescent birth rate (per 1000 women)", 1, "Both sexes; Female")
    assert derive_name(two, doc) == ("Adolescent birth rate (per 1000 women) — Both sexes; Female",
                                     "معدل ولادات المراهقات — الجنسان؛ إناث")
    assert derive_name(("Adolescent birth rate (per 1000 women)", 1, "Both sexes; Rural"), doc)[1] is None
    # a rule's name wins, then the names file, then the publisher's
    doc["names"]["food.price.rice"] = {"en": "Retail price of rice", "ar": "سعر الأرز"}
    assert name_for("food.price.rice", None, None, doc) == ("Retail price of rice", "سعر الأرز")
    assert name_for("food.price.rice", {"name_en": "Rule name"}, None, doc)[0] == "Rule name"
    assert name_for("x.unknown", None, None, doc) == (None, None)


def test_an_answer_calls_a_series_by_its_name_and_falls_back_to_the_key():
    from serve import mcp_en
    from serve.when import label_ar, label_en
    d = {"names": {"prisoners.total": {"en": "People held by Israel (HaMoked)", "ar": "المحتجزون لدى إسرائيل"},
                   "x.en_only": {"en": "English only", "ar": None}}}
    assert label_en(d, "prisoners.total") == "People held by Israel (HaMoked)"
    assert label_ar(d, "prisoners.total") == "المحتجزون لدى إسرائيل"
    assert label_ar(d, "x.en_only") == "English only" and label_en(d, "no.name") == "no.name"
    said = mcp_en.compare({**d, "series": [{"indicator": "prisoners.total", "n": 220,
                                            "canonical_unit": "persons", "source_used": "hamoked"}],
                           "overlap": {}})
    assert "People held by Israel (HaMoked) (220 points, persons, hamoked's series only)" in said
    src = (ROOT / "serve" / "app.py").read_text()
    assert "i.name_ar ILIKE %(q)s" in src and src.count('out["names"] = names') == 3


def test_a_file_that_fed_one_dataset_of_three_speaks_for_that_one(tmp_path):
    import json
    from ingest.databank import read_vintage
    barrier, days = tmp_path / "barrier.json", tmp_path / "days.json"
    barrier.write_text(json.dumps({"metadata": {"vintage": "2018-01-01"}, "data": []}))
    days.write_text(json.dumps({"metadata": {"vintage": "2026-10-08"}, "data": []}))
    land = {"datasets": [{"key": "v1_land_ocha"}, {"key": "v1_land_goodshepherd"}, {"key": "v1_land_peace_now"}]}
    fed = {barrier: {"v1_land_ocha"}, days: {"v1_land_goodshepherd"}}
    assert read_vintage(land, [barrier, days], fed) == {
        "v1_land_ocha": {"vintage": "2018-01-01"}, "v1_land_goodshepherd": {"vintage": "2026-10-08"}}
    # a file that fed two datasets and does not say which is not guessed at
    assert read_vintage(land, [barrier], {barrier: {"v1_land_ocha", "v1_land_peace_now"}}) == {}


# ── constants the old system wrote as if a publisher had said them ───────────

def _land(etype, **extra):
    return {"event_type": etype, "stable_id": "x", "date": "2026-08-05", "land_name": "n",
            "land_type": etype, "land_status": "Authorized", "location": {"region": "Palestine"},
            "metrics": {"count": 1, "unit": "sites"},
            "sources": [{"name": extra.pop("source"), "fetched_at": "2026-10-12T00:00:00Z"}], **extra}


def test_a_settlement_row_no_longer_says_authorized_and_a_demolition_row_no_longer_invents_its_details():
    import yaml
    from ingest import databank as D
    spec = yaml.safe_load((ROOT / "db" / "mappings" / "land.yaml").read_text())
    places = {"region": {"West Bank": 2, "Gaza Strip": 1}}
    s = D.t_land(_land("settlement", source="Peace Now",
                       settlement={"settlement_type": "Settlement", "legal_status": "Authorized",
                                   "area_dunums": 2566}), spec, places, D.Counter())[0]
    assert s.value_text is None and s.attrs.get("area_dunums") == 2566
    assert not {"land_status", "legal_status", "settlement_type"} & set(s.attrs)
    d = D.t_land(_land("demolition", source="Good Shepherd Collective",
                       demolition={"demolition_date": "2026-01-04", "structure_type": "residential",
                                   "structures_demolished": 1, "reason": "Administrative demolition",
                                   "notification_given": True, "owner_type": "Private"}),
                 spec, places, D.Counter())[0]
    assert not {"structure_type", "structures_demolished", "reason", "notification_given",
                "owner_type"} & set(d.attrs)
    # the publisher says West Bank and East Jerusalem; "Palestine" was the old default
    assert d.place_id == 2 and d.attrs["coverage_area"] == "West Bank and East Jerusalem"
    b = D.t_land(_land("checkpoint", source="OCHA oPt", land_status="Projected",
                       checkpoint={"checkpoint_type": "Barrier", "permits_required": True,
                                   "operational_status": "Projected"}), spec, places, D.Counter())[0]
    assert b.value_text == "Projected" and "permits_required" not in b.attrs
    assert b.attrs.get("checkpoint_type") == "Barrier"          # part of the stored identity


def test_the_barrier_is_called_the_barrier_and_heritage_sites_are_not_called_intact():
    import yaml
    land = yaml.safe_load((ROOT / "db" / "mappings" / "land.yaml").read_text())
    rule = next(r for r in land["registry"]["rules"] if r["when"] == {"equals": "land.checkpoint"})
    assert "Separation Barrier" in rule["name_en"] and "not checkpoints" in rule["serve_warning"]
    assert rule["concept"] == "movement.closure"
    culture = yaml.safe_load((ROOT / "db" / "mappings" / "culture.yaml").read_text())
    assert culture["value"]["text_from"] is None
    assert "site_status" not in culture["attrs_passthrough"]
    assert "Wikidata" in culture["registry"]["rules"][0]["serve_warning"]


def test_two_files_with_two_dates_feeding_one_dataset_give_each_indicator_its_own(tmp_path):
    import json
    from ingest.databank import read_vintage
    barrier, villages = tmp_path / "barrier.json", tmp_path / "village_boundaries.json"
    barrier.write_text(json.dumps({"metadata": {"vintage": "2018-01-01"}, "data": []}))
    villages.write_text(json.dumps({"metadata": {"vintage": "2019-07-24"}, "data": []}))
    spec = {"datasets": [{"key": "v1_infrastructure_hdx"}, {"key": "v1_infrastructure_unosat"}]}
    fed = {barrier: {("v1_infrastructure_hdx", "infrastructure.barrier_segment")},
           villages: {("v1_infrastructure_hdx", "infrastructure.locality_record")}}
    assert read_vintage(spec, [barrier, villages], fed) == {"v1_infrastructure_hdx": {
        "vintage_by_indicator": {"infrastructure.barrier_segment": {"vintage": "2018-01-01"},
                                 "infrastructure.locality_record": {"vintage": "2019-07-24"}}}}
    src = (ROOT / "serve" / "app.py").read_text()
    assert "d.attrs->'vintage_by_indicator'->o.indicator->>'vintage'" in src


def test_a_register_that_did_not_change_upstream_is_not_rewritten(tmp_path):
    import json
    from ops import hdx
    out = tmp_path / "schools.json"
    doc = {"metadata": {"vintage": "2015-06-01", "fetched_at": "t1", "vintage_checked_at": "t1", "rows": 1},
           "data": [{"school_id": 1, "sources": [{"name": "HDX", "fetched_at": "t1"}]}]}
    out.write_text(json.dumps(doc))
    tonight = json.loads(json.dumps(doc).replace("t1", "t2"))
    assert hdx.says_the_same(out, tonight)
    tonight["data"][0]["school_id"] = 2
    assert not hdx.says_the_same(out, tonight)
    assert not hdx.says_the_same(tmp_path / "absent.json", doc)


# ── a one-time transition is made by hand, not written into the spec ─────────

def test_the_health_spec_carries_no_transition_ceiling_and_the_loader_takes_one_per_run():
    import inspect
    import yaml
    from ingest import databank as D
    health = yaml.safe_load((ROOT / "db" / "mappings" / "health.yaml").read_text())
    assert health["identity"]["generation"] == "complete"
    assert "max_absent" not in health["identity"]
    assert "allow_absent" in inspect.signature(D.run).parameters
    assert "cap = max(cap, allow_absent)" in inspect.getsource(D.run)
    # the nightly never passes it
    assert "allow_absent" not in inspect.getsource(D.run_all)


# ── the radar and the nightly know the new lines ─────────────────────────────

def test_every_declared_supply_line_has_its_fetcher_and_its_step_in_the_nightly():
    """A declared line that is never run reads dead and fails the night; a
    fetcher that is never run leaves its spec on the frozen fallback."""
    from ops import gap_radar as G
    sync = (ROOT / "ops" / "databank-sync.sh").read_text()
    for name, line in G.SUPPLY_LINES.items():
        fetcher = line["fetcher"]
        assert (ROOT / fetcher).exists(), name
        module = fetcher[:-3].replace("/", ".")
        assert f"-m {module}" in sync, f"{name}: {module} is not in the nightly"
    assert "-m ops.build_cited_figures" in sync
    assert "v1_settlements_peace_now" in G.ALLOWANCE_OVERRIDE_DAYS


def test_a_register_is_as_old_as_its_last_successful_reading():
    import inspect
    from ops import gap_radar as G
    src = inspect.getsource(G.measure_datasets)
    assert 'ds_attrs.get("vintage_checked_at")' in src and "CHECKED_BASIS" in src
    assert "{vintage}" in G.CHECKED_BASIS


def test_a_status_series_is_refused_whatever_the_grains():
    """The time-grain rule was first written INSIDE the status rule's place, so
    a categorical series was refused only when the grains also differed."""
    a, b = _s("x.status", "status", concept="a"), _s("y", concept="b")
    assert any("categorical" in r for r in C.check_comparable(a, b))
    assert any("categorical" in r for r in C.check_comparable(b, a))


# ── a World Bank series is called what the Bank calls it ─────────────────────

def test_a_record_carries_the_banks_own_name_for_its_code_and_a_unit_the_name_supports():
    """v1 typed its labels. EG.ELC.RNWX.ZS (electricity from renewables,
    excluding hydro) was served as "Renewable energy consumption"; GDP growth
    in annual % was a plain `number`, which the registry reads as a stock."""
    from ops import fetch_worldbank as W
    doc = {"metadata": {"indicators": {
               "EG.ELC.RNWX.ZS": {"indicator_name": "Electricity production from renewable sources, "
                                                    "excluding hydroelectric (% of total)"},
               "NY.GDP.MKTP.KD.ZG": {"indicator_name": "GDP growth (annual %)"},
               "SP.POP.TOTL": {"indicator_name": "Population, total"}}},
           "data": [
               {"indicator_code": "EG.ELC.RNWX.ZS", "metrics": {"value": 1.0, "unit": "percentage"},
                "indicator_name": "Renewable energy consumption (% of total final energy consumption)"},
               {"indicator_code": "NY.GDP.MKTP.KD.ZG", "metrics": {"value": 2.0, "unit": "number"},
                "indicator_name": "GDP growth (annual %)"},
               {"indicator_code": "SP.POP.TOTL", "metrics": {"value": 5.0, "unit": "number"},
                "indicator_name": "Population, total"},
               {"indicator_code": "XX.UNKNOWN", "metrics": {"value": 5.0, "unit": "number"},
                "indicator_name": "kept as it was"}]}
    a, b, c, d = W.relabel(doc)["data"]
    assert a["indicator_name"].startswith("Electricity production from renewable sources")
    assert b["metrics"]["unit"] == "percentage" and c["metrics"]["unit"] == "number"
    assert d["indicator_name"] == "kept as it was"
    assert W.publisher_unit("Gini index", "number") == "index"
    assert W.publisher_unit("Pupil-teacher ratio, primary", "number") == "ratio"
    assert W.publisher_unit("Cereal yield (kg per hectare)", "number") == "number"
    assert W.publisher_unit("anything (% of GDP)", "per_1000") == "per_1000"       # only v1's `number`
