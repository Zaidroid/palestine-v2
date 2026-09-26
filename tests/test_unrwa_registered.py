"""P1-B.4 — registered refugees per UNRWA field (ops/fetch_unrwa_registered.py)."""
from __future__ import annotations

from collections import Counter

import yaml

from ingest import databank, spec as spec_mod
from ops import fetch_unrwa_registered as f

HEADER = ["Year", "Quarter", "Country_ISOalpha3", "Country", "UNRWA_Field", "Grand Total",
          "Female_60+", "Female Total", "Male Total"]


def _rows():
    return [HEADER,
            ["2025", "Q4", "PSE", "State of Palestine", "Gaza", "1545991", "74990", "768258", "777733"],
            ["2025", "Q4", "JOR", "Jordan", "Jordan", "2398179", "172675", "1170851", "1227328"],
            ["2025", "Q4", "-", "Total", "Total", "5964782", "407698", "2937833", "3026949"],
            ["2025", "Q4", "", "", "", "", "", "", ""]]


def test_records_keep_every_field_row_and_skip_blanks():
    recs = f.records(_rows())
    assert [r["field"] for r in recs] == ["Gaza", "Jordan", "Total"]
    assert recs[0]["counts"]["Grand Total"] == 1545991


def test_the_total_row_has_its_own_indicator_so_field_sums_never_double():
    places = {"region": {"Gaza Strip": 1, "West Bank": 2}}
    rows = [r for rec in f.records(_rows())
            for r in databank.t_refugees_unrwa_registered(rec, {}, places, Counter())]
    per_field = [r for r in rows if r.indicator == "refugees.unrwa_registered.total"]
    assert sorted(r.value_num for r in per_field) == [1545991, 2398179]
    assert [r.value_num for r in rows
            if r.indicator == "refugees.unrwa_registered_all_fields.total"] == [5964782]
    gaza = next(r for r in per_field if r.attrs["field"] == "Gaza")
    assert gaza.place_id == 1 and gaza.occurred_at == "2025-12-01" and gaza.precision == "month"
    assert any(r.indicator == "refugees.unrwa_registered.female_60_plus" for r in rows)


def test_the_spec_validates():
    s = yaml.safe_load(open("db/mappings/refugees_unrwa_registered.yaml"))
    assert spec_mod.validate(s, "refugees_unrwa_registered") == []
