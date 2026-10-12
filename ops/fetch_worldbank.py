"""The World Bank's annual series for the West Bank and Gaza, read from the
World Bank's own API: the larger half of the `economic` category, taken off v1.

    .venv/bin/python -m ops.fetch_worldbank                      # tonight's run
    .venv/bin/python -m ops.fetch_worldbank --all                # read every series whatever the vintage
    .venv/bin/python -m ops.fetch_worldbank --names              # ... and every name
    .venv/bin/python -m ops.fetch_worldbank --dry-run            # print, write nothing
    .venv/bin/python -m ops.fetch_worldbank --dry-run --stage D  # ... and stage the file under D

WHY (2026-10-12)
`economic` read v1's unified tree (v1's `fetch-worldbank-data.js` → its
`EconomicTransformer` → `unified/economic/all-data.json`). The day v1 is
switched off, 3,541 World Bank rows stop. This reads the same API v1 read
(api.worldbank.org/v2, country PSE, no key) and writes the record shape
`t_economic` already transforms, so the spec gains an `input:` and nothing
else about a row changes.

THE LIST IS THE HELD LIST. v1 asked for 149 codes; 125 answer for PSE and are
held, the other 24 answered nothing in v1's last run (2026-10-12). SERIES
below is those 125, with the label and the unit token every held row
carries. A code the World Bank publishes that is not in SERIES is not fetched:
a new indicator needs a registry rule in db/mappings/economic.yaml and Zaid's
word, then one line here.

TWO NAMES PER SERIES, KEPT APART.
  records[].indicator_name       the label the held rows carry in attrs. v1
                                 typed these by hand; they are part of what a
                                 held row SAYS, so changing one supersedes the
                                 whole series. The unit token (`percentage`,
                                 `currency_usd`, ...) was derived by v1 from
                                 this label and the registry rules match on it.
  metadata.indicators[code]      what the World Bank itself calls the series:
                                 `indicator_name` (English), `indicator_name_ar`
                                 (Arabic), `unit` where the Bank states one,
                                 `source_note`, `source_organization`, and
                                 `lastupdated`. For the registry and for anyone
                                 checking a hand-typed label against the
                                 publisher's.
Names cost two requests per series, so they are re-read only when the name
the data answer itself carries differs from the one on disk (or with --names).
Measured 2026-10-12: 24 of the 125 held labels are not the Bank's name, and
11 of those name a different quantity (SI.POV.DDAY is held as "$2.15 a day
(2017 PPP)" and the Bank now publishes it at "$3.00 a day (2021 PPP)"). The
Bank gives an Arabic name for 90 of the 125 and answers in English for the
other 35, which are left without one. Its `unit` field is empty on all 125:
the unit is inside the name.

VINTAGE, AND WHAT IT SAVES. Every data answer's header carries `lastupdated`,
the day the Bank last updated the database the series sits in. 123 of the 125
are in World Development Indicators; SE.TER.GRAD.FE.SI.ZS is in Gender
Statistics and SH.STA.OWAD.ZS in Health Nutrition and Population Statistics,
each with its own date. It is recorded per series, per database
(metadata.databases) and, as World Development Indicators', in
metadata.vintage. It also decides the night: one series per database is asked
first (PROBE_CODE and two more), and if each still carries the `lastupdated`
the file on disk was read at, that read was complete, and it is less than
FULL_EVERY_DAYS old, nothing else is asked and the file is left as it is. The
numbers change when a database does, and the API is slow enough that this
matters: v1's nightly pull of the same series took 527 and 673 seconds on
2026-10-11 and -12.

POSTURE (ops/fetchlib.py): atomic, floored, ledgered. One line per run under
the label `worldbank:indicators` (an unchanged night says `unchanged: true`).
A series whose request fails, that the Bank has archived, or that answers
with no value at all is named in metadata and in the ledger line and makes
the run exit 1, but the other series are still written: the spec declares
no `generation: complete`, so a series missing from one night's file closes
nothing in the store, and the next night reads everything again. More than
MAX_MISSING missing, or fewer records than the floor, and yesterday's file
stands.

RETRY, AND WHO NEEDED IT. fetchlib leaves retry out until a source needs it.
This one does: 125 requests in a row to api.worldbank.org, where an answer
that is not in the API's cache took 19 s, one in the first six timed out, and
the full read (375 requests with every name) took 11 min 13 s (2026-10-12).
Three tries per request, a short pause between requests.

LICENCE: Creative Commons Attribution 4.0, the World Bank's Terms of Use for
Datasets (https://www.worldbank.org/ext/en/legal/terms-conditions/datasets,
read 2026-10-12): "Unless specifically labeled otherwise, these Datasets are
provided to you under a Creative Commons Attribution 4.0 International License
(CC BY 4.0), with the additional terms below." Recorded on the source row
`worldbank`; this fetcher changes no licence grade.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops import fetchlib as fl                                  # noqa: E402

API = "https://api.worldbank.org/v2"
COUNTRY = "PSE"
OUT = fl.ROOT / "data" / "raw" / "worldbank" / "indicators.json"
LABEL = "worldbank:indicators"
TERMS_URL = "https://www.worldbank.org/ext/en/legal/terms-conditions/datasets"

# 3,541 records over 125 series measured 2026-10-12; the floor is 0.9 of it.
FLOOR_RECORDS = 3186
# A night may lose this many series (a timeout, an archived code) and still
# write the rest; beyond it the API is having a bad night.
MAX_MISSING = 6
PAUSE = 0.15
# The series asked first, every night: its header says which vintage the
# Bank's database is at, and that decides whether the rest are asked at all.
PROBE_CODE = "SP.POP.TOTL"
# ... and however quiet the vintage, everything is read again this often.
FULL_EVERY_DAYS = 7

# code → (the label held rows carry, the unit token held rows carry).
# Extracted from v1's unified file on 2026-10-12 (125 codes, one label and one
# unit each); tests/test_supply_econ.py holds it to the frozen corpus.
SERIES: dict[str, tuple[str, str]] = {
    "AG.CON.FERT.ZS": ("Fertilizer consumption (kilograms per hectare of arable land)", "number"),
    "AG.LND.AGRI.ZS": ("Agricultural land (% of land area)", "percentage"),
    "AG.LND.ARBL.ZS": ("Arable land (% of land area)", "percentage"),
    "AG.LND.CROP.ZS": ("Permanent cropland (% of land area)", "percentage"),
    "AG.LND.FRST.ZS": ("Forest area (% of land area)", "percentage"),
    "AG.LND.IRIG.AG.ZS": ("Agricultural irrigated land (% of total agricultural land)", "percentage"),
    "AG.PRD.CROP.XD": ("Crop production index (2014-2016 = 100)", "number"),
    "AG.PRD.FOOD.XD": ("Food production index (2014-2016 = 100)", "number"),
    "AG.PRD.LVSK.XD": ("Livestock production index (2014-2016 = 100)", "number"),
    "AG.YLD.CREL.KG": ("Cereal yield (kg per hectare)", "number"),
    "BM.GSR.GNFS.CD": ("Imports of goods and services (BoP, current US$)", "currency_usd"),
    "BN.CAB.XOKA.GD.ZS": ("Current account balance (% of GDP)", "percentage"),
    "BX.GSR.GNFS.CD": ("Exports of goods and services (BoP, current US$)", "currency_usd"),
    "BX.KLT.DINV.CD.WD": ("Foreign direct investment, net inflows (BoP, current US$)", "currency_usd"),
    "BX.KLT.DINV.WD.GD.ZS": ("Foreign direct investment, net inflows (% of GDP)", "percentage"),
    "BX.TRF.PWKR.CD.DT": ("Personal remittances, received (current US$)", "currency_usd"),
    "EG.ELC.ACCS.RU.ZS": ("Access to electricity, rural (% of rural population)", "percentage"),
    "EG.ELC.ACCS.UR.ZS": ("Access to electricity, urban (% of urban population)", "percentage"),
    "EG.ELC.ACCS.ZS": ("Access to electricity (% of population)", "percentage"),
    "EG.ELC.RNEW.ZS": ("Renewable electricity output (% of total electricity output)", "percentage"),
    "EG.ELC.RNWX.ZS": ("Renewable energy consumption (% of total final energy consumption)", "percentage"),
    "EG.FEC.RNEW.ZS": ("Renewable energy consumption (% of total final energy consumption)", "percentage"),
    "EN.ATM.PM25.MC.M3": ("PM2.5 air pollution, mean annual exposure (micrograms per cubic meter)", "number"),
    "ER.H2O.FWST.ZS": ("Annual freshwater withdrawals, total (% of internal resources)", "percentage"),
    "ER.H2O.FWTL.ZS": ("Annual freshwater withdrawals, total (% of internal resources)", "percentage"),
    "FB.AST.NPER.ZS": ("Bank nonperforming loans to total gross loans (%)", "percentage"),
    "FB.BNK.CAPA.ZS": ("Bank capital to assets ratio (%)", "percentage"),
    "FM.LBL.BMNY.GD.ZS": ("Broad money (% of GDP)", "percentage"),
    "FP.CPI.TOTL.ZG": ("Inflation, consumer prices (annual %)", "number"),
    "FS.AST.PRVT.GD.ZS": ("Domestic credit to private sector by banks (% of GDP)", "percentage"),
    "IT.CEL.SETS.P2": ("Mobile cellular subscriptions (per 100 people)", "per_100"),
    "IT.MLT.MAIN.P2": ("Fixed telephone subscriptions (per 100 people)", "per_100"),
    "IT.NET.BBND.P2": ("Fixed broadband subscriptions (per 100 people)", "per_100"),
    "IT.NET.SECR.P6": ("Secure Internet servers (per 1 million people)", "number"),
    "IT.NET.USER.ZS": ("Individuals using the Internet (% of population)", "percentage"),
    "NE.EXP.GNFS.ZS": ("Exports of goods and services (% of GDP)", "percentage"),
    "NE.IMP.GNFS.ZS": ("Imports of goods and services (% of GDP)", "percentage"),
    "NE.TRD.GNFS.ZS": ("Trade (% of GDP)", "percentage"),
    "NV.AGR.TOTL.CD": ("Agriculture, forestry, and fishing, value added (current US$)", "currency_usd"),
    "NV.AGR.TOTL.ZS": ("Agriculture, forestry, and fishing, value added (% of GDP)", "percentage"),
    "NV.IND.MANF.ZS": ("Manufacturing, value added (% of GDP)", "percentage"),
    "NV.IND.TOTL.ZS": ("Industry (including construction), value added (% of GDP)", "percentage"),
    "NV.SRV.TOTL.ZS": ("Services, value added (% of GDP)", "percentage"),
    "NY.GDP.MKTP.CD": ("GDP (current US$)", "currency_usd"),
    "NY.GDP.MKTP.KD.ZG": ("GDP growth (annual %)", "number"),
    "NY.GDP.PCAP.CD": ("GDP per capita (current US$)", "currency_usd"),
    "NY.GDP.PCAP.KD.ZG": ("GDP per capita growth (annual %)", "number"),
    "NY.GNP.PCAP.CD": ("GNI per capita, Atlas method (current US$)", "currency_usd"),
    "SE.ADT.LITR.ZS": ("Literacy rate, adult total (% of people ages 15 and above)", "percentage"),
    "SE.PRM.CMPT.ZS": ("Primary completion rate, total (% of relevant age group)", "percentage"),
    "SE.PRM.DURS": ("Primary education, duration (years)", "years"),
    "SE.PRM.ENRL.TC.ZS": ("Pupil-teacher ratio, primary", "number"),
    "SE.PRM.ENRR": ("School enrollment, primary (% gross)", "number"),
    "SE.PRM.ENRR.FE": ("School enrollment, primary, female (% gross)", "number"),
    "SE.PRM.TENR": ("Adjusted net enrollment rate, primary (% of primary school age children)", "percentage"),
    "SE.SEC.DURS": ("Secondary education, duration (years)", "years"),
    "SE.SEC.ENRL.TC.ZS": ("Pupil-teacher ratio, secondary", "number"),
    "SE.SEC.ENRR": ("School enrollment, secondary (% gross)", "number"),
    "SE.SEC.ENRR.FE": ("School enrollment, secondary, female (% gross)", "number"),
    "SE.SEC.PROG.ZS": ("Progression to secondary school (%)", "percentage"),
    "SE.TER.ENRR": ("School enrollment, tertiary (% gross)", "number"),
    "SE.TER.ENRR.FE": ("School enrollment, tertiary, female (% gross)", "number"),
    "SE.TER.GRAD.FE.SI.ZS": ("Female graduates from tertiary education (% of total graduates)", "percentage"),
    "SE.XPD.TOTL.GD.ZS": ("Government expenditure on education, total (% of GDP)", "percentage"),
    "SH.DYN.MORT": ("Mortality rate, under-5 (per 1,000 live births)", "per_1000"),
    "SH.DYN.NMRT": ("Mortality rate, neonatal (per 1,000 live births)", "per_1000"),
    "SH.H2O.BASW.ZS": ("People using at least basic drinking water services (% of population)", "percentage"),
    "SH.H2O.SMDW.RU.ZS": ("People using safely managed drinking water services, rural (% of rural population)", "percentage"),
    "SH.H2O.SMDW.UR.ZS": ("People using safely managed drinking water services, urban (% of urban population)", "percentage"),
    "SH.H2O.SMDW.ZS": ("People using safely managed drinking water services (% of population)", "percentage"),
    "SH.IMM.HEPB": ("Immunization, HepB3 (% of one-year-old children)", "percentage"),
    "SH.IMM.IDPT": ("Immunization, DPT (% of children ages 12-23 months)", "percentage"),
    "SH.IMM.MEAS": ("Immunization, measles (% of children ages 12-23 months)", "percentage"),
    "SH.MED.BEDS.ZS": ("Hospital beds (per 1,000 people)", "per_1000"),
    "SH.MED.NUMW.P3": ("Nurses and midwives (per 1,000 people)", "per_1000"),
    "SH.MED.PHYS.ZS": ("Physicians (per 1,000 people)", "per_1000"),
    "SH.PRV.SMOK": ("Smoking prevalence, total (ages 15+)", "number"),
    "SH.STA.BASS.RU.ZS": ("People using at least basic sanitation services, rural (% of rural population)", "percentage"),
    "SH.STA.BASS.UR.ZS": ("People using at least basic sanitation services, urban (% of urban population)", "percentage"),
    "SH.STA.BASS.ZS": ("People using at least basic sanitation services (% of population)", "percentage"),
    "SH.STA.DIAB.ZS": ("Diabetes prevalence (% of population ages 20 to 79)", "percentage"),
    "SH.STA.MMRT": ("Maternal mortality ratio (per 100,000 live births)", "per_100000"),
    "SH.STA.OWAD.ZS": ("Prevalence of overweight (% of adults)", "percentage"),
    "SH.STA.SMSS.RU.ZS": ("People using safely managed sanitation services, rural (% of rural population)", "percentage"),
    "SH.STA.SMSS.UR.ZS": ("People using safely managed sanitation services, urban (% of urban population)", "percentage"),
    "SH.STA.SMSS.ZS": ("People using safely managed sanitation services (% of population)", "percentage"),
    "SH.STA.STNT.ZS": ("Prevalence of stunting, height for age (% of children under 5)", "percentage"),
    "SH.STA.SUIC.P5": ("Suicide mortality rate (per 100,000 population)", "per_100000"),
    "SH.XPD.CHEX.GD.ZS": ("Current health expenditure (% of GDP)", "percentage"),
    "SH.XPD.CHEX.PC.CD": ("Current health expenditure per capita (current US$)", "currency_usd"),
    "SH.XPD.CHEX.PP.CD": ("Current health expenditure per capita, PPP (current international $)", "number"),
    "SI.DST.05TH.20": ("Income share held by highest 20%", "number"),
    "SI.DST.FRST.20": ("Income share held by lowest 20%", "number"),
    "SI.POV.DDAY": ("Poverty headcount ratio at $2.15 a day (2017 PPP) (% of population)", "percentage"),
    "SI.POV.GAPS": ("Poverty gap at $2.15 a day (2017 PPP) (%)", "percentage"),
    "SI.POV.GINI": ("Gini index", "number"),
    "SI.POV.LMIC": ("Poverty headcount ratio at $3.65 a day (2017 PPP) (% of population)", "percentage"),
    "SI.POV.LMIC.GP": ("Poverty gap at $3.65 a day (2017 PPP) (%)", "percentage"),
    "SI.POV.NAHC": ("Poverty headcount ratio at national poverty lines (% of population)", "percentage"),
    "SI.POV.UMIC": ("Poverty headcount ratio at $6.85 a day (2017 PPP) (% of population)", "percentage"),
    "SL.EMP.VULN.ZS": ("Vulnerable employment, total (% of total employment)", "percentage"),
    "SL.TLF.CACT.FE.ZS": ("Labor force participation rate, female (% of female population ages 15+)", "percentage"),
    "SL.TLF.CACT.MA.ZS": ("Labor force participation rate, male (% of male population ages 15+)", "percentage"),
    "SL.TLF.CACT.ZS": ("Labor force participation rate, total (% of total population ages 15+)", "percentage"),
    "SL.TLF.TOTL.IN": ("Labor force, total", "number"),
    "SL.UEM.1524.ZS": ("Unemployment, youth total (% of total labor force ages 15-24)", "percentage"),
    "SL.UEM.ADVN.ZS": ("Unemployment with advanced education (% of total labor force)", "percentage"),
    "SL.UEM.TOTL.FE.ZS": ("Unemployment, female (% of female labor force)", "percentage"),
    "SL.UEM.TOTL.MA.ZS": ("Unemployment, male (% of male labor force)", "percentage"),
    "SL.UEM.TOTL.ZS": ("Unemployment, total (% of total labor force)", "percentage"),
    "SP.DYN.CBRT.IN": ("Birth rate, crude (per 1,000 people)", "per_1000"),
    "SP.DYN.CDRT.IN": ("Death rate, crude (per 1,000 people)", "per_1000"),
    "SP.DYN.LE00.FE.IN": ("Life expectancy at birth, female (years)", "years"),
    "SP.DYN.LE00.IN": ("Life expectancy at birth, total (years)", "years"),
    "SP.DYN.LE00.MA.IN": ("Life expectancy at birth, male (years)", "years"),
    "SP.DYN.TFRT.IN": ("Fertility rate, total (births per woman)", "births_per_woman"),
    "SP.POP.0014.TO.ZS": ("Population ages 0-14 (% of total)", "percentage"),
    "SP.POP.1564.TO.ZS": ("Population ages 15-64 (% of total)", "percentage"),
    "SP.POP.65UP.TO.ZS": ("Population ages 65 and above (% of total)", "percentage"),
    "SP.POP.GROW": ("Population growth (annual %)", "number"),
    "SP.POP.TOTL": ("Population, total", "number"),
    "SP.URB.GROW": ("Urban population growth (annual %)", "number"),
    "SP.URB.TOTL.IN.ZS": ("Urban population (% of total)", "percentage"),
    "TX.VAL.TECH.CD": ("High-technology exports (current US$)", "currency_usd"),
    "VC.IHR.PSRC.P5": ("Intentional homicides (per 100,000 people)", "per_100000"),
}


class Gone(Exception):
    """The API answered, and the answer is that the series is not there."""


def get_json(url: str, tries: int = 3, timeout: int = 45):
    """fetchlib.get_json with a retry (see the module docstring for who needed it)."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            return json.loads(fl.get(url, timeout=timeout))
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = e
            if attempt + 1 < tries:
                time.sleep(2.0 * (attempt + 1))
    assert last is not None
    raise last


def data_url(code: str, last_year: int, page: int = 1) -> str:
    """v1's request, character for character, for the first page (so the API's
    cache serves the answer v1's nightly run already paid for)."""
    return (f"{API}/country/{COUNTRY}/indicator/{code}"
            f"?format=json&date=1960:{last_year}&per_page=400"
            + (f"&page={page}" if page > 1 else ""))


def parse_answer(answer) -> tuple[dict, list[dict]]:
    """One data answer → (its header, its rows). The API has three shapes:
    [header, [rows]], [header, null] for a series with nothing in the range,
    and [{"message": [...]}] for a code it no longer knows."""
    if not isinstance(answer, list) or not answer or not isinstance(answer[0], dict):
        raise ValueError("not a World Bank API answer")
    head = answer[0]
    if "message" in head:
        said = "; ".join(str(m.get("value")) for m in head["message"] if isinstance(m, dict))
        raise Gone(said or "the API returned a message and no data")
    rows = answer[1] if len(answer) > 1 and isinstance(answer[1], list) else []
    return head, rows


def points(rows: list[dict]) -> list[tuple[int, float]]:
    """Rows → (year, value), oldest first; a null value is not a point (v1's rule)."""
    out = []
    for r in rows:
        year, value = str(r.get("date") or ""), r.get("value")
        if value is None or len(year) != 4 or not year.isdigit():
            continue
        out.append((int(year), value))
    return sorted(out)


def unified_record(*, stable_id: str, year: int, value, unit: str | None,
                   code: str, label: str, place_name: str, source: dict) -> dict:
    """The fields of v1's unified economic record that t_economic reads, and
    no others. Shared with ops/fetch_imf.py: the two halves of one category
    are one record shape."""
    return {"stable_id": stable_id,
            "date": f"{year}-01-01",
            "category": "economic",
            "event_type": "indicator_measurement",
            "location": {"name": place_name, "region": "Palestine", "precision": "region"},
            "metrics": {"value": value, "unit": unit},
            "indicator_code": code,
            "indicator_name": label,
            "sources": [source]}


def publisher_unit(name: str, held: str | None) -> str | None:
    """v1's unit detector called growth rates, enrolment rates, income shares
    and indices plain numbers (25 of the 27 series it marked `number`), and
    the registry reads `number` as a stock. Corrected only where the Bank's
    own name states the unit; a physical rate the vocabulary has no word for
    (kilograms per hectare, per million people) keeps v1's token."""
    if held != "number":
        return held
    n = name or ""
    if "%" in n or n.startswith("Income share held by"):
        return "percentage"
    if re.search(r"\bindex\b", n, re.I):
        return "index"
    if re.search(r"\bratio\b", n, re.I):
        return "ratio"
    return held


def relabel(doc: dict) -> dict:
    """Every record says the Bank's own name for its code, and a unit that
    name supports. v1's labels were typed, and eleven named another series:
    EG.ELC.RNWX.ZS (electricity from renewables, excluding hydro) was served as
    "Renewable energy consumption", the poverty lines at 2021 prices as the
    2017 ones, a STEM share as all female graduates (found 2026-10-12, 171
    rows; 13 more labels differed in wording). The values were always the
    code's; the name now is too."""
    names = (doc.get("metadata") or {}).get("indicators") or {}
    for r in doc.get("data") or []:
        said = " ".join(((names.get(r.get("indicator_code")) or {}).get("indicator_name") or "").split())
        if said:
            r["indicator_name"] = said
        m = r.get("metrics") or {}
        m["unit"] = publisher_unit(r.get("indicator_name"), m.get("unit"))
    return doc


def records_for(code: str, rows: list[dict]) -> list[dict]:
    label, unit = SERIES[code]
    source = {"name": "World Bank", "organization": "World Bank",
              "url": f"{API}/country/{COUNTRY}/indicator/{code}", "license": "CC-BY-4.0"}
    # location.name is the Bank's own name for the economy ("West Bank and
    # Gaza"), read from the answer as v1 read it, never typed here.
    place = next((r["country"]["value"] for r in rows
                  if isinstance(r.get("country"), dict) and r["country"].get("value")), "Palestine")
    return [unified_record(stable_id=f"wb:{COUNTRY}:{code}:{year}", year=year, value=value,
                           unit=unit, code=code, label=label, place_name=place, source=source)
            for year, value in points(rows)]


def name_in_answer(rows: list[dict]) -> str | None:
    for r in rows:
        ind = r.get("indicator")
        if isinstance(ind, dict) and ind.get("value"):
            return ind["value"]
    return None


def parse_names(en, ar) -> dict:
    """The two /indicator/<code> answers (English, Arabic) → the publisher's
    own description of the series. An empty string is the API's 'not stated'."""
    def first(answer) -> dict:
        _head, rows = parse_answer(answer)
        return rows[0] if rows else {}
    e, a = first(en), first(ar)

    def said(d: dict, key: str) -> str | None:
        v = d.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None
    out = {"indicator_name": said(e, "name"),
           "indicator_name_ar": said(a, "name"),
           "unit": said(e, "unit"),
           "source_note": said(e, "sourceNote"),
           "source_organization": said(e, "sourceOrganization"),
           "database": ((e.get("source") or {}).get("value") or None),
           "database_id": ((e.get("source") or {}).get("id") or None)}
    # The Arabic endpoint answers in English where the Bank has no translation;
    # an "Arabic name" with no Arabic letter in it is not one.
    if out["indicator_name_ar"] and not any("\u0600" <= c <= "\u06ff"
                                            for c in out["indicator_name_ar"]):
        out["indicator_name_ar"] = None
    return out


def fetch_names(code: str) -> dict:
    en = get_json(f"{API}/en/indicator/{code}?format=json")
    time.sleep(PAUSE)
    ar = get_json(f"{API}/ar/indicator/{code}?format=json")
    return parse_names(en, ar)


def fetch_series(code: str, last_year: int) -> tuple[dict, list[dict]]:
    head, rows = parse_answer(get_json(data_url(code, last_year)))
    for page in range(2, int(head.get("pages") or 1) + 1):
        _h, more = parse_answer(get_json(data_url(code, last_year, page)))
        rows += more
    return head, rows


def previous() -> dict | None:
    """The document already on disk, or None."""
    try:
        doc = json.loads(OUT.read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("data"), list) else None


def probe_codes(prev: dict | None) -> list[str]:
    """The series asked first: PROBE_CODE, and one more for every other World
    Bank database the file on disk drew on (123 of the 125 held series are in
    World Development Indicators, one is in Gender Statistics and one in
    Health Nutrition and Population Statistics; each database has its own
    `lastupdated`)."""
    by_db: dict[str, str] = {}
    held = ((prev or {}).get("metadata") or {}).get("indicators") or {}
    for code in SERIES:
        db = (held.get(code) or {}).get("sourceid")
        if db is not None:
            by_db.setdefault(str(db), code)
    mine = str((held.get(PROBE_CODE) or {}).get("sourceid"))
    return [PROBE_CODE] + sorted(c for db, c in by_db.items() if db != mine)


def unchanged(prev: dict | None, probed: dict[str, str | None], now: datetime) -> bool:
    """True when the file on disk already holds what the Bank publishes
    tonight: every probed series still carries the `lastupdated` it was read
    at, that read was complete, and it is less than FULL_EVERY_DAYS old.
    Anything else (no file, a database that moved, a read that missed a
    series, an old read) is a reason to read every series again."""
    meta = (prev or {}).get("metadata") or {}
    held = meta.get("indicators") or {}
    if not prev or not probed:
        return False
    if set(probed) != set(probe_codes(prev)):
        return False
    # Every held series must sit at the vintage its database's probe shows
    # tonight. That also catches a read taken while the API's cache was still
    # serving some series from before an update: such a file is mixed, and it
    # is read again until it is not.
    tonight = {str((held.get(code) or {}).get("sourceid")): vintage
               for code, vintage in probed.items()}
    for code in SERIES:
        one = held.get(code) or {}
        vintage = tonight.get(str(one.get("sourceid")))
        if not vintage or one.get("lastupdated") != vintage:
            return False
    if meta.get("series_failed") or meta.get("series_gone") or meta.get("series_empty"):
        return False
    try:
        read = datetime.fromisoformat(meta["fetched_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return (now - read).total_seconds() < FULL_EVERY_DAYS * 86400


def build(prev: dict | None = None, force_names: bool = False,
          now: datetime | None = None,
          asked: dict[str, tuple[dict, list[dict]]] | None = None,
          say=print) -> tuple[dict, dict]:
    """Read every series → (the document to write, a summary for the ledger).
    `asked` holds the probes' answers, so no series is asked twice."""
    asked = asked or {}
    now = now or datetime.now(timezone.utc)
    held_names = ((prev or {}).get("metadata") or {}).get("indicators") or {}
    recs: list[dict] = []
    indicators: dict[str, dict] = {}
    failed: dict[str, str] = {}
    gone: dict[str, str] = {}
    empty: list[str] = []
    names_read = 0
    for n, code in enumerate(SERIES, 1):
        if len(failed) + len(gone) > MAX_MISSING:
            break                       # a bad night; main() refuses on the count
        if n % 25 == 0:
            say(f"  ... {n} of {len(SERIES)} series asked, {len(recs)} records so far")
        try:
            if code in asked:
                head, rows = asked[code]
            else:
                head, rows = fetch_series(code, now.year)
                time.sleep(PAUSE)
        except Gone as e:
            gone[code] = str(e)[:200]
            continue
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
            failed[code] = f"{type(e).__name__}: {str(e)[:160]}"
            continue
        mine = records_for(code, rows)
        if not mine:
            empty.append(code)
        recs += mine
        said = name_in_answer(rows)
        names = dict(held_names.get(code) or {})
        if force_names or not names.get("indicator_name") or \
                (said and names.get("indicator_name") != said.strip()):
            try:
                names = fetch_names(code)
                names["names_read_at"] = now.isoformat()
                names_read += 1
            except (Gone, urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
                # the data is the point; a name that would not load tonight is
                # the name the answer itself carried, and is read again tomorrow
                names = {"indicator_name": (said or "").strip() or None,
                         "names_error": f"{type(e).__name__}: {str(e)[:120]}"}
            time.sleep(PAUSE)
        years = [int(r["date"][:4]) for r in mine]
        indicators[code] = {
            "indicator_name": names.get("indicator_name"),
            "indicator_name_ar": names.get("indicator_name_ar"),
            "unit": names.get("unit"),
            "source_note": names.get("source_note"),
            "source_organization": names.get("source_organization"),
            "database": names.get("database"),
            "database_id": names.get("database_id"),
            "names_read_at": names.get("names_read_at"),
            **({"names_error": names["names_error"]} if names.get("names_error") else {}),
            "held_label": SERIES[code][0],
            "held_unit": SERIES[code][1],
            "lastupdated": head.get("lastupdated"),
            "sourceid": head.get("sourceid"),
            "points": len(mine),
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
        }
    vintages = sorted({v["lastupdated"] for v in indicators.values() if v.get("lastupdated")})
    by_db: dict[str, dict] = {}
    for v in indicators.values():
        d = by_db.setdefault(str(v.get("sourceid")), {"database": v.get("database"),
                                                      "lastupdated": v.get("lastupdated"),
                                                      "series": 0})
        d["series"] += 1
    summary = {"records": len(recs), "series_held": len(SERIES),
               "series_answered": len(indicators), "series_empty": empty,
               "series_failed": failed, "series_gone": gone,
               "names_read": names_read,
               "vintage": vintages[-1] if vintages else None}
    doc = {"metadata": {
        "fetched_at": now.isoformat(),
        "source": "World Bank Open Data, World Development Indicators (API v2)",
        "organization": "World Bank",
        "source_url": f"{API}/country/{COUNTRY}/indicator/<code>?format=json",
        "country_code": COUNTRY,
        "license": "CC BY 4.0 (World Bank Terms of Use for Datasets)",
        "license_url": TERMS_URL,
        "attribution": "The World Bank: World Development Indicators.",
        "vintage": summary["vintage"],
        "vintage_basis": ("`lastupdated` in the header of the World Bank API's data answers: "
                          "the day the Bank last updated the database a series sits in. "
                          "This is World Development Indicators' (the latest over the series "
                          "read); every database's is in metadata.databases and each series' "
                          "own in metadata.indicators[code].lastupdated"),
        "vintage_url": data_url(PROBE_CODE, now.year),
        "vintages_seen": vintages,
        "databases": by_db,
        **{k: v for k, v in summary.items() if k != "vintage"},
        "indicators": indicators},
        "data": recs}
    return doc, summary


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    now = datetime.now(timezone.utc)
    prev = previous()
    asked: dict[str, tuple[dict, list[dict]]] = {}
    try:
        for code in probe_codes(prev):
            asked[code] = fetch_series(code, now.year)
            time.sleep(PAUSE)
    except (Gone, urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {str(e)[:200]}")
        print(f"{LABEL}: the World Bank API did not answer the probe "
              f"({', '.join(probe_codes(prev))}): {e}", file=sys.stderr)
        return 1
    probed = {code: head.get("lastupdated") for code, (head, _rows) in asked.items()}
    if "--all" not in argv and "--names" not in argv and unchanged(prev, probed, now):
        n = len(prev["data"])
        print(f"{LABEL}: unchanged. The World Bank's databases are at the vintages read on "
              f"{prev['metadata']['fetched_at'][:10]} ({', '.join(sorted(set(probed.values())))}); "
              f"{n} records stand, nothing re-read")
        if not dry:
            fl.event(LABEL, "ok", rows=n, vintage=prev["metadata"].get("vintage"), unchanged=True)
        return 0

    doc, s = build(prev, force_names="--names" in argv, now=now, asked=asked)
    # A held series that answers with nothing is as missing as one that does
    # not answer: either way somebody has to look.
    missing = {**s["series_failed"], **s["series_gone"],
               **{c: "answered with no value in any year" for c in s["series_empty"]}}
    print(f"{LABEL}: {s['records']} records over {s['series_answered']} of "
          f"{s['series_held']} series, World Bank vintage {s['vintage']}, "
          f"{s['names_read']} names read")
    for code, why in sorted(missing.items()):
        print(f"  MISSING {code}: {why}", file=sys.stderr)
    refusal = None
    if len(missing) > MAX_MISSING:
        refusal = f"{len(missing)} series missing by the time it stopped (more than {MAX_MISSING})"
    elif s["records"] < FLOOR_RECORDS:
        refusal = f"{s['records']} records below the floor of {FLOOR_RECORDS}"
    if refusal:
        if not dry:
            fl.event(LABEL, "refused", rows=s["records"], floor=FLOOR_RECORDS,
                     missing=sorted(missing), why=refusal)
        print(f"  REFUSED {LABEL}: {refusal}; the file already on disk stands", file=sys.stderr)
        return 1
    if dry:
        print(f"  would write {OUT.relative_to(fl.ROOT)}")
        fl.stage(staged, "worldbank_indicators.json", doc)
        return 1 if missing else 0
    fl.write_atomic(OUT, relabel(doc))
    fl.event(LABEL, "ok", rows=s["records"], series=s["series_answered"],
             vintage=s["vintage"], missing=sorted(missing))
    print(f"  wrote {OUT.relative_to(fl.ROOT)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
