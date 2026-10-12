"""WHO Global Health Observatory: Palestine's rows for the indicators the databank holds, every dimension kept.

    .venv/bin/python -m ops.fetch_gho_health                  # fetch if the held copy is older than 6 days
    .venv/bin/python -m ops.fetch_gho_health --force
    .venv/bin/python -m ops.fetch_gho_health --accept-shrink  # a human has looked: WHO did withdraw rows

WHY
The health category read a frozen copy of v1's file (WHO's HDX export through
v1's unified tree, last refreshed 2026-08-05). That route kept ONE dimension
per row: WHO publishes an under-five wasting figure by sex AND age group AND
wealth quintile, the export wrote the sex and dropped the rest, and 4,521 held
rows sat side by side with nothing saying which was which (measured
2026-10-12: 1,050 groups of indicator and year holding 2 to 22 rows). It gave
no vintage and no reliable unit. GHO's own OData API gives all of it.

WHAT IS KEPT
For each of the 184 indicator codes the databank holds (CODES: the codes of
the 12,502 held rows, which are the codes of data/frozen/health.json.gz;
tests/test_supply_who.py holds that line, and no code is added here), every
row WHO publishes for SpatialDim PSE, its fields verbatim: TimeDim, the three
dimension slots with their types, NumericValue, the display Value, Low, High,
and Date, WHO's last update of that row, which is the row's vintage. Three
things are written beside WHO's fields: `indicator_name` (api/Indicator),
`Dim1Label`..`Dim3Label` (api/DIMENSION/<type>/DimensionValues) and
`stable_id` (gho:<code>:<year>:<dimensions>). Rows with no number (tobacco
policy answers in words, placeholders) are kept here; the transformer counts
them out.

POSTURE (ops/fetchlib.py): atomic, floored, ledgered, and three things more.
  POLITE      one request at a time, PAUSE seconds apart, fetchlib's User-Agent;
              about 215 requests. WHO revises a few times a year, so a held copy
              younger than MAX_AGE_DAYS is not re-fetched.
  RESUMABLE   each code's answer is written to data/raw/gho/health_parts/ as
              it arrives. A run killed halfway, or stopped by one bad answer,
              picks up from there: parts younger than RESUME_HOURS are reused.
  ONE RETRY   a request that fails is tried once more after RETRY_PAUSE. fetchlib
              deliberately has no retry; this fetcher needs one because 215
              answers in a row from one host fail somewhere on an ordinary night.
A code that still fails ends the run with nothing written. Floors: FLOOR_ROWS
and FLOOR_CODES (measured), and against the copy already on disk: fewer than
SHRINK of its rows, or more than GONE_CODES of its codes gone empty, is
refused unless --accept-shrink. The loader closes a held row WHO no longer
publishes (health.yaml, identity.generation: complete), so a short answer
must never reach it.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetchlib import (FetchRefused, check_floor, event, get_json,  # noqa: E402
                          write_atomic)

API = "https://ghoapi.azureedge.net/api"
TERMS_URL = "https://www.who.int/about/policies/publishing/data-policy/terms-and-conditions"
OUT = ROOT / "data" / "raw" / "gho" / "health_pse.json"
PARTS = ROOT / "data" / "raw" / "gho" / "health_parts"
LABEL = "gho:health"
SPATIAL = "PSE"
PAUSE = 0.5                 # seconds between requests
RETRY_PAUSE = 5.0
MAX_AGE_DAYS = 6            # fetched weekly from a nightly job
RESUME_HOURS = 36           # last night's parts are still this run's
FLOOR_ROWS = 12_500         # 13,975 on 2026-10-12
FLOOR_CODES = 175           # 183 of 184 codes had rows on 2026-10-12
SHRINK = 0.95               # of the rows already on disk
GONE_CODES = 5              # codes with rows on disk and none now

# The codes of the held rows (dataset v1_health_who), in one string so the
# list reads as a list. Derived, never extended: see the module docstring.
CODES = tuple((
    "AIR_41 AIR_42 AIR_7 AIR_90 CARE_SOURCE CHILDDEATH5TO14 CHILDMORT5TO14 CHILDVIOL CM_01 "
    "CM_02 CM_03 CM_04 DEATHADO FINANCIALHARDSHIP_PROPORTIONOFPOP "
    "FINPROTECTION_CATA_TOT_10_POP FINPROTECTION_CATA_TOT_25_POP FINPROTECTION_IMP_NP190_POP "
    "FINPROTECTION_IMP_NP215_POP FINPROTECTION_IMP_NP310_POP FINPROTECTION_IMP_NP365_POP "
    "FINPROTECTION_IMP_NPRELPL_POP FINPROTECTION_IMP_P190_POP FINPROTECTION_IMP_P215_POP "
    "FINPROTECTION_IMP_P310_POP FINPROTECTION_IMP_P365_POP FINPROTECTION_IMP_PRELPL_POP "
    "GHED_CHEGDP_SHA2011 GHED_CHE_pc_US_SHA2011 GHED_EXTCHE_SHA2011 GHED_EXT_pc_US_SHA2011 "
    "GHED_GGHE-DCHE_SHA2011 GHED_GGHE-DGDP_SHA2011 GHED_GGHE-DGGE_SHA2011 "
    "GHED_GGHE-D_pc_US_SHA2011 GHED_OOPSCHE_SHA2011 GHED_OOP_pc_US_SHA2011 "
    "GHED_PVT-DCHE_SHA2011 GHED_PVT-D_pc_US_SHA2011 IMMUNIZATION_VACCINATIONCARDSSEEN "
    "LBW_NUMBER LBW_PREVALENCE MCV2 MDG_0000000001 MDG_0000000003 MDG_0000000007 "
    "MDG_0000000020 MDG_0000000025 MH_12 MORTADO MORT_MATERNALNUM M_Est_cig_curr "
    "M_Est_cig_curr_std M_Est_smk_curr M_Est_smk_curr_std M_Est_tob_curr M_Est_tob_curr_std "
    "NCDMORT3070 NCD_BMI_18A NCD_BMI_18C NCD_BMI_25A NCD_BMI_25C NCD_BMI_30A NCD_BMI_30C "
    "NCD_BMI_MINUS2C NCD_BMI_PLUS1C NCD_BMI_PLUS2C NCD_CXCA_SCREENED_WITHIN_TIMEPERIOD "
    "NCD_DIABETES_PREVALENCE_AGESTD NCD_DIABETES_PREVALENCE_CRUDE "
    "NCD_DIABETES_TREATMENT_AGESTD NCD_DTH_TOT NCD_PAA NCD_PAC "
    "NCD_SENSORYFUNCTION_VISION_EREC NCD_UNDER70 NUTOVERWEIGHTNUM "
    "NUTRITION_ANAEMIA_CHILDREN_NUM NUTRITION_ANAEMIA_CHILDREN_PREV "
    "NUTRITION_ANAEMIA_REPRODUCTIVEAGE_NUM NUTRITION_ANAEMIA_REPRODUCTIVEAGE_PREV "
    "NUTRITION_ANT_HAZ_NE2 NUTRITION_ANT_WHZ_NE2 NUTRITION_WA_2 NUTRITION_WH_2 NUTRITION_WH_3 "
    "NUTSTUNTINGNUM NUTSTUNTINGPREV NUTWASTINGNUM NUT_BF_CBF NUT_BF_EBF NUT_BF_EBF2D "
    "NUT_BF_EIBF NUT_BF_EVBF NUT_CF_EFF NUT_CF_ISSSF NUT_CF_MAD NUT_CF_MDD NUT_CF_MMF "
    "PRETERMBIRTH_NUMBER PRETERMBIRTH_RATE ROTAC RS_198 RS_246 SDGHEPHBSAGPRV SDGODAWS "
    "SDGPM25 SDGPOISON SDGSUICIDE SRHINSTITUTIONALBIRTH TAXBEV_IMPORTDUTIES TAXBEV_OTHERTAXES "
    "TAXBEV_PRICE TAXBEV_SUGARCONTENT TAXBEV_TOTALTAXES TAXBEV_VATSALES TB_1 "
    "TB_c_dst_rlt_new_pct TB_c_dst_rlt_ret_pct TB_c_mdr_tsr TB_c_mdr_tx TB_c_new_tsr "
    "TB_c_newinc TB_c_ret_tsr TB_c_tbhiv_tsr TB_e_inc_num TB_e_inc_num_014 TB_e_inc_rr_num "
    "TB_e_inc_tbhiv_100k TB_e_inc_tbhiv_num TB_hivtest_pct TB_rr_mdr "
    "TOBACCO_MPOWER_M3_TOBACCOUSESMOKINGSCHOOL TOBACCO_MPOWER_M4_SMOKELESSECIGARETTESSCHOOL "
    "TOBACCO_MPOWER_NTCP TOBACCO_MPOWER_OVERVIEW TOBACCO_MPOWER_P2_SMOKEFREEPLACEDETAILS "
    "TOBACCO_MPOWER_R_AFFORDABILITY TOBACCO_MPOWER_R_INFLATIONADJUSTEDPRICES "
    "TOBACCO_MPOWER_R_PRICE TOBACCO_MPOWER_R_TAX TOBACCO_MPOWER_R_TAXREVENUELATEST "
    "TOBACCO_MPOWER_R_TAXREVENUEPREVIOUS TOBACCO_MPOWER_W1A_CIGARETTES "
    "TOBACCO_MPOWER_W1B_TOBACCOSMOKED TOBACCO_MPOWER_W1C_TOBACCOSMOKELESS "
    "TOBACCO_MPOWER_W2A_CIGARETTES TOBACCO_MPOWER_W2B_TOBACCOSMOKED "
    "TOBACCO_MPOWER_W2C_TOBACCOSMOKELESS UHC_INDEX_REPORTED UHC_SCI_CAPACITY UHC_SCI_INFECT "
    "UHC_SCI_NCD UHC_SCI_RMNCH WHOSIS_000001 WHOSIS_000002 WHOSIS_000003 WHOSIS_000004 "
    "WHOSIS_000007 WHOSIS_000014 WHOSIS_000015 WHOSIS_000016 WHS3_41 WHS3_42 WHS3_43 WHS3_46 "
    "WHS3_50 WHS3_53 WHS3_55 WHS3_56 WHS3_57 WHS3_62 WHS4_117 WHS4_129 WHS4_154 WHS4_543 "
    "WHS4_544 WHS6_102 WHS8_110 WSH_DOMESTIC_WASTE_SAFELY_TREATED WSH_HYGIENE_BASIC "
    "WSH_SANITATION_BASIC WSH_SANITATION_SAFELY_MANAGED WSH_WATER_BASIC "
    "WSH_WATER_SAFELY_MANAGED"
).split())


def data_url(code: str) -> str:
    return (f"{API}/{urllib.parse.quote(code)}?$filter="
            + urllib.parse.quote(f"SpatialDim eq '{SPATIAL}'"))


def _get(url: str):
    """One polite request, tried once more if it fails."""
    try:
        return get_json(url, timeout=60)
    except Exception:                                       # noqa: BLE001
        time.sleep(RETRY_PAUSE)
        return get_json(url, timeout=60)
    finally:
        time.sleep(PAUSE)


def fetch_code(code: str) -> list[dict]:
    """Every PSE row of one indicator. Follows OData paging if WHO ever pages
    a country's rows, and refuses an answer about another code or place."""
    rows, url = [], data_url(code)
    while url:
        payload = _get(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise ValueError(f"{code}: not an OData answer")
        rows.extend(payload["value"])
        url = payload.get("@odata.nextLink")
    for r in rows:
        if r.get("IndicatorCode") != code or r.get("SpatialDim") != SPATIAL:
            raise ValueError(f"{code}: the answer holds a row for "
                             f"{r.get('IndicatorCode')}/{r.get('SpatialDim')}")
    return rows


def load_part(code: str, now: float) -> list[dict] | None:
    p = PARTS / f"{code}.json"
    if not p.exists() or now - p.stat().st_mtime > RESUME_HOURS * 3600:
        return None
    try:
        return json.loads(p.read_text())["rows"]
    except (ValueError, KeyError):
        return None                     # a damaged part is fetched again


def dim_types(rows_by_code: dict[str, list[dict]]) -> list[str]:
    return sorted({r[f"Dim{i}Type"] for rows in rows_by_code.values()
                   for r in rows for i in (1, 2, 3) if r.get(f"Dim{i}Type")})


def dim_key(row: dict) -> str:
    """'SEX=SEX_FMLE;AGEGROUP=AGEGROUP_YEARS15-19' in WHO's own slot order;
    '' for a row with no dimension. ingest.databank.gho_dim_key renders the
    same string from the same fields (tests/test_supply_who.py)."""
    return ";".join(f"{row[f'Dim{i}Type']}={row[f'Dim{i}']}" for i in (1, 2, 3)
                    if row.get(f"Dim{i}Type") and row.get(f"Dim{i}"))


def stable_id(row: dict) -> str:
    return f"gho:{row.get('IndicatorCode')}:{row.get('TimeDim')}:{dim_key(row)}"


def records(rows_by_code: dict[str, list[dict]], names: dict[str, str],
            labels: dict[str, dict[str, str]]) -> list[dict]:
    """WHO's rows, each with its indicator's name, its dimension labels and a
    stable id written beside the publisher's own fields. Sorted, so the same
    answer is the same file."""
    out = []
    for code in sorted(rows_by_code):
        for row in rows_by_code[code]:
            rec = dict(row)
            rec["indicator_name"] = names.get(code)
            for i in (1, 2, 3):
                kind, value = row.get(f"Dim{i}Type"), row.get(f"Dim{i}")
                rec[f"Dim{i}Label"] = (labels.get(kind) or {}).get(value) if kind else None
            rec["stable_id"] = stable_id(row)
            out.append(rec)
    out.sort(key=lambda r: r["stable_id"])
    return out


def vintage(recs: list[dict]) -> str | None:
    """The newest `Date` among the rows: the day WHO last touched any of them."""
    best = None
    for r in recs:
        try:
            d = datetime.fromisoformat(str(r.get("Date")))
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if best is None or d > best:
            best = d
    return best.astimezone(timezone.utc).isoformat() if best else None


def build(rows_by_code: dict[str, list[dict]], names: dict[str, str],
          labels: dict[str, dict[str, str]], titles: dict[str, str],
          fetched_at: str) -> dict:
    recs = records(rows_by_code, names, labels)
    return {
        "metadata": {
            "source": "WHO Global Health Observatory (GHO) OData API",
            "url": f"{API}/",
            "spatial": SPATIAL,
            "fetched_at": fetched_at,
            "codes": len(rows_by_code),
            "codes_empty": sorted(c for c, rows in rows_by_code.items() if not rows),
            "rows": len(recs),
            "vintage": vintage(recs),
            "vintage_basis": "the newest `Date` among the rows (GHO OData's `Date` is "
                             "WHO's last update of that row; every record keeps its own)",
            "vintage_url": f"{API}/",
            "terms_url": TERMS_URL,
            "dimension_titles": {t: titles.get(t) for t in dim_types(rows_by_code)},
        },
        "data": recs,
    }


def check_against_held(payload: dict, held: dict | None, accept_shrink: bool) -> None:
    """The floor only this place can hold: the copy on disk beside the new one."""
    if not held or accept_shrink:
        return
    had = [r for r in held.get("data") or [] if isinstance(r, dict)]
    now_codes = {r["IndicatorCode"] for r in payload["data"]}
    gone = sorted({r.get("IndicatorCode") for r in had} - now_codes - {None})
    n, was = len(payload["data"]), len(had)
    if n < SHRINK * was or len(gone) > GONE_CODES:
        event(LABEL, "refused", rows=n, held_rows=was, codes_gone=gone[:20])
        raise FetchRefused(
            f"{LABEL}: {n} rows against {was} on disk, {len(gone)} code(s) with rows "
            f"on disk and none now ({', '.join(gone[:8])}). Keeping the file on disk: "
            "the loader closes rows WHO no longer publishes, and a short answer is "
            "not a withdrawal. If WHO did withdraw them, run again with --accept-shrink.")


def _fresh(path: Path, days: float = MAX_AGE_DAYS) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < days * 86400


def main(argv: list[str]) -> int:
    if "--force" not in argv and "--accept-shrink" not in argv and _fresh(OUT):
        print(f"{LABEL}: held copy is younger than {MAX_AGE_DAYS} days, not re-fetched")
        return 0
    started = time.time()
    try:
        rows_by_code: dict[str, list[dict]] = {}
        reused = 0
        for code in CODES:
            rows = load_part(code, started)
            if rows is None:
                rows = fetch_code(code)
                write_atomic(PARTS / f"{code}.json", {"code": code, "rows": rows})
            else:
                reused += 1
            rows_by_code[code] = rows
        names = {r["IndicatorCode"]: r["IndicatorName"]
                 for r in _get(f"{API}/Indicator")["value"]}
        titles = {r["Code"]: r["Title"] for r in _get(f"{API}/Dimension")["value"]}
        labels = {t: {v["Code"]: v["Title"]
                      for v in _get(f"{API}/DIMENSION/{urllib.parse.quote(t)}/DimensionValues")["value"]}
                  for t in dim_types(rows_by_code)}
        payload = build(rows_by_code, names, labels, titles,
                        datetime.now(timezone.utc).isoformat())
        meta = payload["metadata"]
        check_floor(LABEL, meta["rows"], FLOOR_ROWS)
        with_rows = meta["codes"] - len(meta["codes_empty"])
        if with_rows < FLOOR_CODES:
            event(LABEL, "refused", codes_with_rows=with_rows, floor=FLOOR_CODES)
            raise FetchRefused(f"{LABEL}: {with_rows} codes with rows, below the "
                               f"floor of {FLOOR_CODES}. Keeping the file on disk.")
        held = json.loads(OUT.read_text()) if OUT.exists() else None
        check_against_held(payload, held, "--accept-shrink" in argv)
    except FetchRefused as e:
        print(e, file=sys.stderr)
        return 1
    except Exception as e:                                  # noqa: BLE001
        event(LABEL, "error", error=str(e)[:300])
        print(f"{LABEL}: {e} (the parts fetched so far are kept for the next run)",
              file=sys.stderr)
        return 1
    write_atomic(OUT, payload)
    event(LABEL, "ok", rows=meta["rows"], codes=meta["codes"],
          codes_empty=meta["codes_empty"], vintage=meta["vintage"], parts_reused=reused)
    print(f"{LABEL}: {meta['rows']} rows, {with_rows} of {meta['codes']} codes with rows, "
          f"vintage {str(meta['vintage'])[:10]} → {OUT.relative_to(ROOT)}"
          + (f" ({reused} codes resumed from parts)" if reused else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
