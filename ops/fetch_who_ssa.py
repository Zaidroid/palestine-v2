"""WHO's Surveillance System for Attacks on Health Care (SSA): the attacks it
records in the occupied Palestinian territory, as monthly series.

    .venv/bin/python -m ops.fetch_who_ssa              # nightly
    .venv/bin/python -m ops.fetch_who_ssa --dry-run    # says what it would write

WHY (2026-10-14). The databank holds Insecurity Insight's attacks on health
care, incident by incident; WHO's own surveillance is the figure the UN and the
press quote ("WHO has recorded N attacks on health care"), with its own
definitions: what was hit (facility, transport, personnel, patients, supplies,
warehouse), the type of attack, the dead and injured, and the health workers and
patients abducted, arrested or detained. Measured on 2026-10-14: 3,507 attacks,
6 July 2017 to 7 October 2026, 1,083 killed and 3,303 injured.

THE ROUTE. The dashboard's own JSON, one GET, no key, no robots file on the
host: extranet.who.int/ssa/Ref/GetDashboardFullReport?Countries=178 (the oPt)
&WhoRegions=0&Types=0&DaterangeSTART=2017-01-01&DaterangeEND=<today> (the empty
filters must be 0). Terms (the dashboard's #copyright): permission from WHO is
not required for the use of the data available for download; WHO may withdraw a
record at any time. No place below the territory: no West Bank / Gaza split.

WHAT IS WRITTEN. data/raw/who_ssa/attacks.json: every incident as WHO gives it
(kept whole, and in bronze `who_ssa`); data/raw/who_ssa/monthly.json: the
series db/mappings/who_ssa.yaml loads, by the month of the attack (WHO's
ATTACKTIMESTAMP):
  attacks, killed, injured;
  attacks by what was hit (an attack is counted under each it hit);
  attacks by type (an attack carries one to four types: counted under each);
  health workers and patients abducted, arrested or detained (WHO's counts).
The newest month is partial until the month ends (attrs.partial_month). A month
with no attack is written as 0 between the first month and this one: the
surveillance ran and recorded none.

THE FLOOR. 3,000 incidents, and never more than a tenth fewer than the file on
disk: WHO may withdraw records, but a reply that shrinks by a tenth is a
failure until a person reads why. Ledgered as `who:ssa`.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from ops import fetchlib as fl

URL = ("https://extranet.who.int/ssa/Ref/GetDashboardFullReport?Countries=178&WhoRegions=0&Types=0"
       "&DaterangeSTART=2017-01-01&DaterangeEND={end}")
PAGE = "https://extranet.who.int/ssa/Index.aspx"
DIR = fl.ROOT / "data" / "raw" / "who_ssa"
RAW = DIR / "attacks.json"
OUT = DIR / "monthly.json"
LABEL = "who:ssa"
FLOOR = 3000
SHRINK = 0.10
SOURCE_NAME = "WHO Surveillance System for Attacks on Health Care (SSA)"

# WHO's attack types, by its ids (2026-10-14; 7, 12, 13 and 14 never appear alone
# and were read off the combined labels).
TYPES = {
    "0": ("other", "Other", "أخرى"),
    "1": ("abduction_arrest_detention", "abduction, arrest or detention of health personnel or patients",
          "اختطاف أو اعتقال أو احتجاز عاملين صحيين أو مرضى"),
    "2": ("removal_of_assets", "removal of health care assets (transport, supplies, materials)",
          "الاستيلاء على أصول الرعاية الصحية (نقل، إمدادات، مواد)"),
    "3": ("assault_without_weapons", "assault without weapons", "اعتداء دون سلاح"),
    "4": ("individual_weapons", "violence with individual weapons (knives, clubs, guns, grenades, IEDs)",
          "عنف بأسلحة فردية (سكاكين، هراوات، بنادق، قنابل يدوية، عبوات)"),
    "5": ("heavy_weapons", "violence with heavy weapons (tanks, missiles, bombs, mortars)",
          "عنف بأسلحة ثقيلة (دبابات، صواريخ، قنابل، هاون)"),
    "6": ("setting_fire", "setting fire", "إضرام النار"),
    "7": ("chemical_agent", "chemical agent", "مادة كيميائية"),
    "8": ("militarization", "militarization of a health care asset", "عسكرة منشأة أو أصل صحي"),
    "9": ("armed_search", "armed or violent search of health care personnel, facility or transport",
          "تفتيش مسلّح أو عنيف لعاملين صحيين أو منشأة أو وسيلة نقل"),
    "10": ("obstruction", "obstruction to health care delivery (physical, administrative, legal)",
           "عرقلة تقديم الرعاية الصحية (مادية أو إدارية أو قانونية)"),
    "11": ("psychological_violence", "psychological violence, threat of violence or intimidation",
           "عنف نفسي أو تهديد أو ترهيب"),
    "12": ("sexual_assault", "sexual assault", "اعتداء جنسي"),
    "13": ("unknown_type", "type unknown", "نوع غير معروف"),
    "14": ("criminalization", "criminalization of health care", "تجريم الرعاية الصحية"),
}
HIT = {
    "HCFACILITIES": ("facilities", "health facilities", "منشآت صحية"),
    "HCTRANSPORT": ("transport", "health transport (ambulances)", "وسائل نقل صحية (إسعاف)"),
    "HCPERSONNEL": ("personnel", "health personnel", "عاملين صحيين"),
    "HCPATIENTS": ("patients", "patients", "مرضى"),
    "HCSUPPLIESASSETS": ("supplies", "health supplies and assets", "إمدادات وأصول صحية"),
    "HCWAREHOUSESTORAGE": ("warehouses", "health warehouses and storage", "مستودعات ومخازن صحية"),
}
PEOPLE = {
    "health_workers_detained": (("HWABDUCTON", "HWARREST", "HWDETENTION"),
                                "health workers abducted, arrested or detained",
                                "عاملون صحيون اختُطفوا أو اعتُقلوا أو احتُجزوا"),
    "patients_detained": (("PATIENTABDUCTION", "PATIENTARREST", "PATIENTDETENTION"),
                          "patients abducted, arrested or detained", "مرضى اختُطفوا أو اعتُقلوا أو احتُجزوا"),
}


def type_ids(rec: dict) -> list[str]:
    return [x.strip() for x in str(rec.get("ATTACKTYPEID") or "").split(",") if x.strip()]


def month_of(rec: dict) -> str | None:
    s = str(rec.get("ATTACKTIMESTAMP") or "")
    return f"{s[:7]}-01" if len(s) >= 7 and s[4] == "-" else None


def _months(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while (y, m) <= (int(last[:4]), int(last[5:7])):
        out.append(f"{y}-{m:02d}-01")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly(incidents: list[dict], today: date) -> tuple[list[dict], dict]:
    """The incidents → one record per series and month."""
    by: dict[str, Counter] = defaultdict(Counter)
    undated, unknown_types = 0, Counter()
    for r in incidents:
        mo = month_of(r)
        if mo is None:
            undated += 1
            continue
        c = by[mo]
        c["attacks"] += 1
        c["killed"] += int(r.get("VICTIMSTOTALDEATH") or 0)
        c["injured"] += int(r.get("VICTIMSTOTALINJURED") or 0)
        for field, (key, _en, _ar) in HIT.items():
            if str(r.get(field) or "").upper() == "YES":
                c[f"attacks_on_{key}"] += 1
        for t in type_ids(r):
            if t in TYPES:
                c[f"attacks_type_{TYPES[t][0]}"] += 1
            else:
                unknown_types[t] += 1
        for key, (fields, _en, _ar) in PEOPLE.items():
            c[key] += sum(int(r.get(f) or 0) for f in fields)
    measures = (["attacks", "killed", "injured"] + [f"attacks_on_{k}" for k, _e, _a in HIT.values()]
                + [f"attacks_type_{k}" for k, _e, _a in TYPES.values()] + list(PEOPLE))
    this_month = f"{today.year}-{today.month:02d}-01"
    months = _months(min(by), this_month) if by else []
    unit = {"attacks": "attacks", "killed": "persons", "injured": "persons",
            "health_workers_detained": "persons", "patients_detained": "persons"}
    src = {"name": SOURCE_NAME, "organization": "World Health Organization", "url": PAGE}
    recs = [{"stable_id": f"who_ssa:{m}:{mo}", "measure": m, "value": by[mo][m], "date": mo,
             "unit": unit.get(m, "attacks"), "partial_month": True if mo == this_month else None,
             "location": {"region": "Palestine"}, "sources": [src]}
            for mo in months for m in measures]
    notes = {"incidents": len(incidents), "undated": undated, "unknown_type_ids": dict(unknown_types),
             "first_month": months[0] if months else None, "months": len(months)}
    return recs, notes


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    staged = fl.stage_dir(argv) if dry else None
    today = datetime.now(timezone.utc).date()
    try:
        raw = fl.get(URL.format(end=today.isoformat()), timeout=180)
        incidents = json.loads(raw)
        if not isinstance(incidents, list):
            raise fl.FetchRefused(f"{LABEL}: the reply is not a list of incidents")
        if len(incidents) < FLOOR:
            raise fl.FetchRefused(f"{LABEL}: {len(incidents)} incidents below the floor of {FLOOR}")
        if RAW.exists():
            held = len(json.loads(RAW.read_text()).get("data") or [])
            if held and len(incidents) < held * (1 - SHRINK):
                raise fl.FetchRefused(f"{LABEL}: {len(incidents)} incidents against {held} held, "
                                      f"more than a tenth fewer; the file on disk stays until a person reads why")
    except fl.FetchRefused as e:
        print(f"  REFUSED {LABEL}: {e}", file=sys.stderr)
        if not dry:
            fl.event(LABEL, "refused", why=str(e)[:300])
        return 1
    except Exception as e:                                   # noqa: BLE001
        print(f"  FAIL {LABEL}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        if not dry:
            fl.event(LABEL, "error", error=f"{type(e).__name__}: {e}"[:300])
        return 1
    recs, notes = monthly(incidents, today)
    newest = max((str(r.get("LASTMODIFIED") or "")[:10] for r in incidents), default=None)
    meta = {"fetched_at": datetime.now(timezone.utc).isoformat(), "source": SOURCE_NAME, "source_url": PAGE,
            "license": "WHO: permission is not required for the use of the SSA data available for download; "
                       "WHO may withdraw a record at any time",
            "attribution": "Attacks on health care: WHO Surveillance System for Attacks on Health Care (SSA).",
            "vintage": newest, "vintage_basis": "the newest LASTMODIFIED among the incidents", **notes}
    print(f"  ok   {LABEL}: {notes['incidents']} incidents, {notes['months']} months from {notes['first_month']}, "
          f"{len(recs)} monthly records; newest change {newest}")
    if dry:
        print(f"         would write {RAW.relative_to(fl.ROOT)} and {OUT.relative_to(fl.ROOT)} (dry run)")
        fl.stage(staged, OUT.name, {"metadata": meta, "data": recs})
        return 0
    from ingest import bronze
    bronze.put("who_ssa", raw.decode("utf-8", "replace"), "json", url=URL.format(end=today.isoformat()))
    fl.write_atomic(RAW, {"metadata": meta, "data": incidents})
    fl.write_atomic(OUT, {"metadata": meta, "data": recs})
    fl.event(LABEL, "ok", rows=len(recs), incidents=notes["incidents"], vintage=newest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
