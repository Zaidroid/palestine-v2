"""WHO's attacks on health care, ILO's quarters and the World Bank's night lights
(ops/fetch_who_ssa.py, ops/fetch_ilostat.py, ops/fetch_nightlights.py, 2026-10-14).
No network: each reader's pure part on rows cut down from the real replies."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from ops import fetch_ilostat as ilo
from ops import fetch_nightlights as ntl
from ops import fetch_who_ssa as who
from ops import gap_radar

ROOT = Path(__file__).resolve().parent.parent


def attack(ts: str, types: str, **kw) -> dict:
    rec = {"REPORTID": f"PSE{ts}{types}", "ATTACKTIMESTAMP": ts, "ATTACKTYPEID": types,
           "VICTIMSTOTALDEATH": 0, "VICTIMSTOTALINJURED": 0, "HCFACILITIES": "NO", "HCTRANSPORT": "NO",
           "HCPERSONNEL": "NO", "HCPATIENTS": "NO", "HCSUPPLIESASSETS": "NO", "HCWAREHOUSESTORAGE": "NO",
           "HWABDUCTON": 0, "HWARREST": 0, "HWDETENTION": 0, "PATIENTABDUCTION": 0, "PATIENTARREST": 0,
           "PATIENTDETENTION": 0}
    rec.update(kw)
    return rec


def test_who_counts_by_month_an_attack_under_each_type_and_target_and_fills_empty_months():
    incidents = [attack("2023-10-17T18:59:00", "5", VICTIMSTOTALDEATH=471, VICTIMSTOTALINJURED=342,
                        HCFACILITIES="YES", HCPATIENTS="YES"),
                 attack("2023-10-20T09:00:00", "10,11,4", HWARREST=2),
                 attack("2023-12-03T10:00:00", "7")]
    recs, notes = who.monthly(incidents, date(2024, 1, 9))
    v = {(r["measure"], r["date"]): r["value"] for r in recs}
    assert v[("attacks", "2023-10-01")] == 2 and v[("killed", "2023-10-01")] == 471
    assert v[("attacks_on_facilities", "2023-10-01")] == 1 and v[("attacks_on_patients", "2023-10-01")] == 1
    # one attack of three types is counted under each: the types do not add up to the attacks
    assert (v[("attacks_type_obstruction", "2023-10-01")], v[("attacks_type_psychological_violence", "2023-10-01")],
            v[("attacks_type_individual_weapons", "2023-10-01")], v[("attacks_type_heavy_weapons", "2023-10-01")]) == (1, 1, 1, 1)
    assert v[("health_workers_detained", "2023-10-01")] == 2
    assert v[("attacks", "2023-11-01")] == 0                 # the surveillance ran and recorded none
    assert v[("attacks_type_chemical_agent", "2023-12-01")] == 1
    newest = [r for r in recs if r["date"] == "2024-01-01"]
    assert newest and all(r["partial_month"] for r in newest) and v[("attacks", "2024-01-01")] == 0
    assert notes["unknown_type_ids"] == {} and notes["months"] == 4


def test_who_names_every_type_it_uses():
    assert set(who.TYPES) == {str(i) for i in range(15)}
    _, notes = who.monthly([attack("2024-01-02T00:00:00", "99")], date(2024, 1, 9))
    assert notes["unknown_type_ids"] == {"99": 1}             # counted, never silently dropped


def ilo_row(time: str, value: str, sex="SEX_T", age="AGE_YTHADULT_YGE15", src="R1:3513", status="") -> dict:
    return {"ref_area": "PSE", "source": "BA:592", "indicator": "UNE_DEAP_SEX_AGE_RT", "sex": sex,
            "classif1": age, "time": time, "obs_value": value, "obs_status": status,
            "note_classif": "", "note_indicator": "I12:415", "note_source": src}


def test_ilo_splits_the_quarters_that_exclude_gaza_into_series_of_their_own():
    rows = [ilo_row("2023Q3", "24.078"), ilo_row("2023Q4", "25.707", src="R1:3513_S4:6333", status="B"),
            ilo_row("2024Q1", "35.211", src="R1:3513_S4:6333"),
            ilo_row("2024Q1", "40.1", age="AGE_YTHADULT_Y20-24")]             # an age band not read
    recs, _ = ilo.records({"UNE_DEAP_SEX_AGE_RT_Q": rows},
                          {"S4:6333": "Geographical coverage: Excluding Gaza Strip"})
    got = {(r["measure"], r["quarter"]): r for r in recs}
    assert set(got) == {("unemployment_rate_total_15plus", "2023Q3"),
                        ("unemployment_rate_total_15plus_excluding_gaza", "2023Q4"),
                        ("unemployment_rate_total_15plus_excluding_gaza", "2024Q1")}
    q4 = got[("unemployment_rate_total_15plus_excluding_gaza", "2023Q4")]
    assert (q4["date"], q4["period_end"], q4["obs_status"], q4["location"]["region"]) == \
        ("2023-10-01", "2023-12-31", "break in series", "West Bank")
    assert "Geographical coverage: Excluding Gaza Strip" in q4["notes"]
    assert got[("unemployment_rate_total_15plus", "2023Q3")]["location"]["region"] == "Palestine"
    assert ilo.quarter_dates("2025Q4") == ("2025-10-01", "2025-12-31") and ilo.quarter_dates("2025") is None


NTL_HEADER = "ISO_A3,ADM1CD_c,ADM2CD_c,NAM_0,NAM_1,NAM_2,date,ntl_quality_prop_0_good,ntl_sum,ntl_mean"


def ntl_line(iso: str, name: str, day: str, s: float) -> str:
    return f"{iso},{iso}001,{iso}001001,X,{name},Administrative unit not available,{day},0.9,{s},{s / 100}"


def test_night_lights_reads_only_palestines_block_by_bisection(monkeypatch):
    lines = [NTL_HEADER] + [ntl_line(c, "A", "2023-01-01", 1) for c in ("ABW", "FRA", "ISR") for _ in range(400)]
    lines += [ntl_line("PSE", n, "2023-11-01", s) for n, s in (("Gaza", 569.29), ("Jabalya", 12.5), ("Hebron", 9000))]
    lines += [ntl_line(c, "A", "2023-01-01", 1) for c in ("QAT", "ZWE") for _ in range(400)]
    blob = ("\n".join(lines) + "\n").encode()
    reads = []

    def fake_read(url, a, b):
        reads.append((a, b))
        return blob[a:b + 1]
    monkeypatch.setattr(ntl, "read", fake_read)
    monkeypatch.setattr(ntl, "PROBE", 256)
    monkeypatch.setattr(ntl, "SPAN", 2048)                   # so the bisection runs on a small file
    monkeypatch.setattr(ntl, "CHUNK", 1000)                  # and the forward reads carry a cut line
    header, got = ntl.block("u", len(blob))
    assert [x.split(",")[4] for x in got] == ["Gaza", "Jabalya", "Hebron"]
    recs, unknown = ntl.records(header, got)
    assert unknown == []
    by = {(r["measure"], r["location"]["governorate"]): r["value"] for r in recs}
    assert by[("radiance_sum", "Gaza")] == 569.29 and by[("radiance_sum", "North Gaza")] == 12.5   # Jabalya
    assert len(reads) < 40 and reads[1][0] > 0                # bisected, not read from the start


def test_night_lights_knows_every_governorate_name_the_world_bank_uses():
    names = ["Al Khalil (Hebron)", "Al Quds (Jerusalem)", "Ariha (Jericho)", "Bethlehem", "Deir al Balah", "Gaza",
             "Jabalya", "Jenin", "Khan Yunis", "Nablus", "Qalqiliya", "Rafah", "Ramallah", "Salfit", "Tubas", "Tulkarm"]
    got = {ntl.GOVERNORATE[n.lower()] for n in names}
    assert len(got) == 16 and "North Gaza" in got and "Khan Younis" in got
    assert sorted(ntl.FILES) == list(range(2012, 2026)) and ntl.FILES[2023] == "DR0095697"


def test_the_night_reads_who_and_ilo_and_the_radar_knows_all_three():
    sync = (ROOT / "ops" / "databank-sync.sh").read_text()
    assert "step .venv/bin/python -m ops.fetch_who_ssa" in sync and "step .venv/bin/python -m ops.fetch_ilostat" in sync
    assert "fetch_nightlights" not in sync                     # by hand: one file a year
    assert gap_radar.SUPPLY_LINES["who-ssa"]["feeds"] == ["who_ssa_monthly"]
    assert gap_radar.SUPPLY_LINES["ilostat"]["feeds"] == ["ilostat_quarterly"]
    assert gap_radar.ALLOWANCE_OVERRIDE_DAYS["ilostat_quarterly"] == 550
    assert gap_radar.ALLOWANCE_OVERRIDE_DAYS["nightlights_monthly"] == 550


def test_the_specs_name_every_series_with_known_concepts_and_units():
    c = yaml.safe_load((ROOT / "db/registry/concepts.yaml").read_text())
    concepts = set(c.get("concepts") or c)
    units = yaml.safe_load((ROOT / "db/registry/units.yaml").read_text())["units"]
    aliases = {a for u in units.values() for a in (u.get("aliases") or {})}
    for name in ("who_ssa", "ilostat", "nightlights"):
        spec = yaml.safe_load((ROOT / "db" / "mappings" / f"{name}.yaml").read_text(encoding="utf-8"))
        rules = spec["registry"]["rules"]
        assert rules and all(r["name_en"] and r["name_ar"] and r["serve_warning_ar"] for r in rules), name
        assert {r["concept"] for r in rules} <= concepts, name
        assert {r["canonical_unit"] for r in rules} <= set(units), name
    assert {"attacks", "persons", "percent", "nW/cm2/sr"} <= aliases | set(units)
