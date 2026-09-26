"""P1-B.4 — the 1950s from UN WPP 2024 (ops/fetch_wpp.py, t_population_wpp)."""
from __future__ import annotations

from collections import Counter

import yaml

from ingest import databank, spec as spec_mod
from ops import fetch_wpp


HEADER = "LocID,Location,Variant,Time," + ",".join(fetch_wpp.INDICATORS)


def _row(loc, variant, year, pop="944.624"):
    vals = [pop if c == "TPopulation1July" else "1.5" for c in fetch_wpp.INDICATORS]
    return f"{loc},X,{variant},{year}," + ",".join(vals)


def test_parse_keeps_palestine_estimates_and_never_projections():
    text = "\n".join([HEADER, _row("275", "Medium", 1950), _row("275", "Medium", 2030),
                      _row("400", "Medium", 1950), _row("275", "High", 1950)])
    recs = fetch_wpp.parse(text)
    assert {r["year"] for r in recs} == {1950}
    assert len(recs) == len(fetch_wpp.INDICATORS)
    pop = next(r for r in recs if r["indicator"] == "population_total")
    assert pop["value"] == 944624.0 and pop["unit"] == "persons" and pop["wpp_unit"] == "thousands"


def test_every_row_says_it_is_an_estimate_for_the_whole_territory():
    rec = {"stable_id": "wpp-2024:1955:births", "year": 1955, "indicator": "births",
           "value": 49418.0, "unit": "persons", "wpp_column": "Births", "wpp_unit": "thousands"}
    [row] = databank.t_population_wpp(rec, {}, {}, Counter())
    assert row.indicator == "population.wpp.births" and row.occurred_at == "1955-01-01"
    assert row.precision == "year" and row.place_id is None
    assert row.attrs["estimate"].startswith("modelled") and row.attrs["region"] == "Palestine"


def test_the_spec_validates_and_migrates():
    s = yaml.safe_load(open("db/mappings/population_wpp.yaml"))
    assert spec_mod.validate(s, "population_wpp") == []
    assert s.get("migrate", True) is True           # 089 applied 2026-09-26
    assert s["expect"]["min_records"] == fetch_wpp.FLOOR
