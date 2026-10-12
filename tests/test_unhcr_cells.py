"""UNHCR's tables as HDX exports them: a cell published as two rows is two
parts of one figure, and the parts add (2026-10-12).

HDX drops a column UNHCR keys on (`dec_level`: first instance / review), so
some cells arrive as two rows nothing tells apart. The first load kept the
first row and dropped the second as a repeat of its id (Palestinians in Canada
2020 read 357 where UNHCR's stocks table says 1,777), and from the second
night the loader refused the run. Pure: no database, no file.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import databank as D  # noqa: E402

BASE = {"Year": "2020", "Country of Origin Code": "PSE", "Country of Origin Name": "State of Palestine"}


def _demo(asylum, total, **cols):
    r = {**BASE, "table": "demographics_originating", "Country of Asylum Code": asylum,
         "Country of Asylum Name": asylum, "Population Type": "REF",
         "location": "Dispersed in the country / territory", "urbanRural": "V",
         "accommodationType": "U", "Total": str(total)}
    r.update({k: str(v) for k, v in cols.items()})
    return r


def _app(asylum, n, year="2000"):
    return {**BASE, "Year": year, "table": "applications", "Country of Asylum Code": asylum,
            "Country of Asylum Name": asylum, "Procedure Type": "G", "Procedure Name": "Government",
            "Application Type Code": "V", "Application Data Type": "C",
            "Number of Applications": str(n)}


def _load(recs):
    counts = Counter()
    D._unhcr_prepass(recs, {}, counts)
    rows, drops = [], []
    for r in recs:
        out = D.t_unhcr_population(r, {}, {}, counts)
        if isinstance(out, D.Drop):
            drops.append(out.reason)
        else:
            rows += out
    return rows, drops


def _value(rows, indicator, asylum):
    got = [r for r in rows if r.indicator == indicator and r.attrs["asylum_country_code"] == asylum]
    assert len(got) == 1, got
    return got[0]


def test_two_rows_of_one_demographics_cell_add():
    # Canada 2020 as published: 357 with a sex breakdown, 1,420 without; stocks say 1,777.
    recs = [_demo("CAN", 357, **{"Female Total": 150, "Male Total": 207}), _demo("CAN", 1420),
            _demo("DEU", 2016, **{"Female Total": 900, "Male Total": 1116})]
    rows, drops = _load(recs)
    assert drops == ["summed_into_cell"]
    total = _value(rows, "refugees.demographics.total", "CAN")
    assert total.value_num == 1777 and total.attrs["rows_summed"] == 2
    # the breakdown covers only the part that had one, and is not inflated
    assert _value(rows, "refugees.demographics.female_total", "CAN").value_num == 150
    # a cell published once is untouched and says nothing about summing
    one = _value(rows, "refugees.demographics.total", "DEU")
    assert one.value_num == 2016 and "rows_summed" not in one.attrs


def test_two_stages_of_one_applications_cell_add_even_when_equal():
    # Australia 2000: first instance 134 + review 15 = UNHCR's "applied": 149.
    # Poland 2002: 5 + 5 = 10; an identical pair is still two stages.
    rows, drops = _load([_app("AUS", 15), _app("AUS", 134),
                         _app("POL", 5, year="2002"), _app("POL", 5, year="2002")])
    assert drops == ["summed_into_cell", "summed_into_cell"]
    assert _value(rows, "refugees.asylum_applications", "AUS").value_num == 149
    assert _value(rows, "refugees.asylum_applications", "POL").value_num == 10


def test_the_summed_cell_keeps_the_first_rows_id_so_it_supersedes_what_is_held():
    alone, _ = _load([_demo("CAN", 357)])
    summed, _ = _load([_demo("CAN", 357), _demo("CAN", 1420)])
    a = _value(alone, "refugees.demographics.total", "CAN")
    b = _value(summed, "refugees.demographics.total", "CAN")
    assert a.v1_stable_id == b.v1_stable_id and a.value_num != b.value_num

