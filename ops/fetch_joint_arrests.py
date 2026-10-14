"""The prisoner institutions' joint monthly report: arrests by Israeli forces each
month, January 2016 to January 2024, with children, women, Jerusalem and the
administrative detention orders issued.

    .venv/bin/python -m ops.fetch_joint_arrests                    # reads the list and every report page
    .venv/bin/python -m ops.fetch_joint_arrests --from-dir DIR     # the pages already saved (pages/, reports.json)

WHY (2026-10-14). Addameer's statistics page and HaMoked count how many people
are HELD; this counts how many were ARRESTED in a month and how many
administrative orders were issued. First issued for January 2016 by the
Commission of Detainees' Affairs, the Prisoners' Society, Addameer and (some
years) Al Mezan and the Wadi Hilweh centre; indexed on Addameer's site
(addameer.ps/ar/publications/monthly-reports, seven pages, 80 items), whose list
ends with January 2024 (later months are in the institutions' news: to read).

WHAT IS READ. Each report's lead sentence: «اعتقلت سلطات الاحتلال خلال شهر …
(N) فلسطينيًا … من بينهم (C) طفلاً، و(W) من النساء», and where it says so, the
arrests in Jerusalem and the administrative orders issued that month (new and
renewed). Figures said for the year, the half year, or "since the beginning of
the year" are never read as a month's. Annual, half-year and anniversary
reports, and the two reports that cover two months together (January-February
2018, March-April 2019), are listed and not read as months. The arrests count
arrest cases, not people. From October 2023 the reports count the West Bank
(Jerusalem included) only: those months are series of their own.

WHAT IT WRITES. data/raw/addameer/joint_monthly.json, ledgered as
`addameer:joint_monthly`; every page in bronze (`addameer_joint`).
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from ops import fetchlib as fl
from ops.build_market_channel import ARABIC_MONTHS, DIGITS

LIST = "https://addameer.ps/ar/publications/monthly-reports?page={n}"
BASE = "https://addameer.ps"
PAGES = 7
OUT = fl.ROOT / "data" / "raw" / "addameer" / "joint_monthly.json"
LABEL = "addameer:joint_monthly"
PAUSE = 3.0
FLOOR = 50
SOURCE_NAME = "Addameer Prisoner Support and Human Rights Association"   # routed to the source row `addameer`
_MONTHS = "|".join(sorted(ARABIC_MONTHS, key=len, reverse=True))
NOT_A_MONTH = re.compile(r"النصف|حصاد|يوم الأسير|تستعرض|خلال عام|خلال العام|عام \d{4}|خلال \d{4}|منذ|شهري")
# a figure said for a longer stretch than the month (looked for in the words just before it)
RUNNING = re.compile(r"منذ بداية|من بداية|الفترة ذاتها|خلال العام|العام الجاري|منذ مطلع|النصف|منذ السابع|منذ تشرين|حتى تاريخ")
# an order count: «(N) أمر/أمرا/أوامر … إداري» (and never «(13) امرأة», a woman)
ORDERS = re.compile(r"\(\s*([\d,]+)\s*\)\s*(?:أمر|امر|أوامر)(?!أة|اة)[\u0600-\u06FF]{0,2}\s*(?:اعتقال\s*)?إدار")
LINK = re.compile(r'<a[^>]+href="(/ar/(?:publications/(?!addameer$|annual|monthly-reports|factsheets|brochures|'
                  r'quarterly|reports$|other)[^"#?]+|media/\d+))"[^>]*>(.*?)</a>', re.S)


def text_of(page: str) -> str:
    page = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).translate(DIGITS)


def _n(s) -> int | None:
    return int(s.replace(",", "")) if s else None


def month_in(s: str) -> tuple[int, int] | None:
    m = re.search(rf"خلال\s+(?:شهر\s+)?({_MONTHS})\s*(?:/\s*(?:{_MONTHS}))?\s*،?\s*(?:العام\s*)?(\d{{4}})", s)
    return (int(m.group(2)), ARABIC_MONTHS[m.group(1)]) if m else None


def read_report(title: str, page: str) -> dict:
    """One report → its month and figures, or the reason it is not a month's."""
    title = re.sub(r"\s+", " ", title.translate(DIGITS)).strip()
    t = text_of(page)
    if "شهري" in title:
        return {"skip": "two months together"}
    ym = month_in(title)
    stamp = re.search(r"(\d{2})-(\d{2})-(\d{4})", t)
    if NOT_A_MONTH.search(title):
        # the half-year report of June 2022 opens with June's own figure: «اعتقل (464) مواطن/ة خلال حزيران/يونيو الماضي»
        m = re.search(rf"\((\d[\d,]*)\)\s*(?:مواطن|فلسطيني)[^()]*?خلال\s+(?:شهر\s+)?({_MONTHS})\s*/?\s*(?:{_MONTHS})?\s*الماضي", title)
        if m and stamp:
            return {"year": int(stamp.group(3)), "month": ARABIC_MONTHS[m.group(2)], "arrests": _n(m.group(1)),
                    "basis": "the month's figure in a half-year report's title"}
        return {"skip": "not a month's report"}
    i = t.find("اعتقلت")
    if i < 0:
        i = t.find("اعتقل ")
    lead = t[i:i + 600].split(" . ")[0] if i >= 0 else ""
    lead = re.split(r"(?<=[)\w])\s*\.\s", lead)[0]
    ym = ym or month_in(lead)
    if ym is None:
        return {"skip": "no month named"}
    arrests = _n((re.search(r"\(\s*([\d,]+)\s*\)\s*(?:فلسطيني|مواطن|حالة)", lead) or
                  re.search(r"\(\s*([\d,]+)\s*\)\s*(?:فلسطيني|مواطن)", title) or
                  re.search(r"اعتقل\s+(?:قرابة\s+|نحو\s+)?([\d,]+)\s+(?:فلسطيني|مواطن)", title) or [None, None])[1])
    children = _n((re.search(r"(?:بينهم|منهم)\s*\(\s*([\d,]+)\s*\)\s*(?:طفل|أطفال|قاصر)", lead) or
                    re.search(r"\(\s*([\d,]+)\s*\)\s*(?:من الأطفال|طفلا|أطفال|قاصر)", lead) or [None, None])[1])
    w = re.search(r"\(\s*([\d,]+)\s*\)\s*(?:من النساء|امرأة|سيدة|من الفتيات)|(?:من النساء|النساء)\s*\(\s*([\d,]+)\s*\)", lead)
    women = _n((w.group(1) or w.group(2))) if w else None
    after = t[i:i + 1500] if i >= 0 else ""
    jm = re.search(r"\(\s*([\d,]+)\s*\)\s*(?:مواطنا|مواطنًا|فلسطينيا|فلسطينيًا|حالة)?\s*(?:/\s*ة)?\s*من\s+(?:مدينة\s+)?القدس", after)
    admin = new = renewed = None
    for m in ORDERS.finditer(t):
        before = re.split(r"\s\.\s|\.\s|•", t[max(0, m.start() - 90):m.start()])[-1]   # this sentence only
        if RUNNING.search(before):
            continue                                       # «منذ بداية العام … (1829) أمر»: the year's, not the month's
        admin = _n(m.group(1))
        rest = t[m.end():m.end() + 140]
        new = _n((re.search(r"\(\s*([\d,]+)\s*\)\s*(?:أمرا?|أمراً)?\s*جديد", rest) or [None, None])[1])
        renewed = _n((re.search(r"\(\s*([\d,]+)\s*\)\s*(?:أمر\s*)?(?:تجديد|تمديد)", rest) or [None, None])[1])
        break
    in_title = re.search(r"\(\s*([\d,]+)\s*\)\s*(?:فلسطيني|مواطن)", title)
    title_says = _n(in_title.group(1)) if in_title else None
    return {"year": ym[0], "month": ym[1], "arrests": arrests, "children": children, "women": women,
            "jerusalem": _n(jm.group(1)) if jm else None, "admin_orders": admin, "admin_orders_new": new,
            "admin_orders_renewed": renewed, "west_bank_only": "الضفة" in title and (ym[0], ym[1]) >= (2023, 10),
            "title_says": title_says if title_says not in (None, arrests) else None,
            "basis": "the report's lead sentence"}


def records(reports: list[dict]) -> tuple[list[dict], dict]:
    notes = {"reports": len(reports), "not_months": [], "same_month_twice": []}
    by: dict[str, dict] = {}
    for r in reports:
        got = read_report(r["title"], r["page"])
        if "skip" in got:
            notes["not_months"].append(f"{got['skip']}: {r['title'][:90]}")
            continue
        key = f"{got['year']:04d}-{got['month']:02d}-01"
        if key in by:
            if {k: v for k, v in by[key].items() if k not in ("url", "title")} != got:
                notes["same_month_twice"].append(f"{key}: {r['title'][:80]}")
            continue
        by[key] = {**got, "url": BASE + r["href"], "title": r["title"]}
    src = {"name": SOURCE_NAME, "organization": "Addameer, the Prisoners' Society, the Commission of Detainees' Affairs",
           "url": "https://addameer.ps/ar/publications/monthly-reports"}
    recs = []
    for day, g in sorted(by.items()):
        scope = "_west_bank" if g.get("west_bank_only") or day >= "2023-10-01" else ""
        for m in ("arrests", "children", "women", "jerusalem", "admin_orders", "admin_orders_new", "admin_orders_renewed"):
            if g.get(m) is None:
                continue
            measure = ("total" if m == "arrests" else m) + scope
            recs.append({"stable_id": f"joint_arrests:{measure}:{day}", "measure": measure, "value": g[m],
                         "unit": "count" if m.startswith("admin") else "arrests", "date": day,
                         "title_says": g.get("title_says") if m == "arrests" else None,
                         "report": g["url"], "report_title": g["title"], "basis": g["basis"],
                         "location": {"region": "West Bank" if scope else "Palestine"}, "sources": [src]})
    notes["months"] = len(by)
    return recs, notes


def walk() -> list[dict]:
    from ingest import bronze
    reports = []
    for n in range(PAGES):
        time.sleep(PAUSE)
        page = fl.get(LIST.format(n=n)).decode("utf-8", "replace")
        for href, txt in LINK.findall(page):
            txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", txt))).strip()
            if txt and href not in [r["href"] for r in reports]:
                reports.append({"href": href, "title": txt})
    for r in reports:
        time.sleep(PAUSE)
        url = BASE + (r["href"] if "%" in r["href"] else urllib.parse.quote(r["href"]))   # the list's links are already encoded
        r["page"] = fl.get(url).decode("utf-8", "replace")
        bronze.put("addameer_joint", r["page"], "html", url=url)
    return reports


def from_dir(d: Path) -> list[dict]:
    reports = json.loads((d / "reports.json").read_text())
    for r in reports:
        r["page"] = (d / "pages" / r["file"]).read_text(encoding="utf-8", errors="replace")
    return reports


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    try:
        reports = from_dir(Path(argv[argv.index("--from-dir") + 1])) if "--from-dir" in argv else walk()
        recs, notes = records(reports)
        if notes["months"] < FLOOR:
            raise fl.FetchRefused(f"{LABEL}: {notes['months']} months below the floor of {FLOOR}")
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
    days = sorted({r["date"] for r in recs})
    meta = {"fetched_at": datetime.now(timezone.utc).isoformat(), "source": "The prisoner institutions' joint "
            "monthly report (Addameer's index)", "source_url": "https://addameer.ps/ar/publications/monthly-reports",
            "license": "\"All rights reserved\" (no-license-found); attribution",
            "attribution": "Arrests: the joint monthly report of the Palestinian prisoner institutions (via Addameer).",
            "first_month": days[0], "data_through": days[-1], **notes}
    print(f"  ok   {LABEL}: {notes['months']} months {days[0][:7]} → {days[-1][:7]}, {len(recs)} records; "
          f"{len(notes['not_months'])} reports not a month's; {len(notes['same_month_twice'])} months printed twice differently")
    if dry:
        return 0
    if "--from-dir" in argv:                               # the pages read earlier go to bronze as walk() would put them
        from ingest import bronze
        for r in reports:
            bronze.put("addameer_joint", r["page"], "html", url=BASE + r["href"])
    fl.write_atomic(OUT, {"metadata": meta, "data": recs})
    fl.event(LABEL, "ok", rows=len(recs), months=notes["months"], first=days[0][:7], data_through=days[-1][:7])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
