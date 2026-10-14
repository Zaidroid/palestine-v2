"""The databank's index: every area, dataset and series, measured on the store.

    .venv/bin/python -m ops.databank_index             # writes docs/databank/
    .venv/bin/python -m ops.databank_index --check     # prints the totals, writes nothing

WHY (2026-10-14). Zaid asked for "an index/readme for this databank for
accurate fast navigations". The store holds 62 datasets, 3,500 series, an event
table, the live tier and a news archive of 2.4 million texts; nothing listed
them in one place, so finding a series meant a query or a grep through specs.
This reads the store READ-ONLY and writes one Markdown page per area plus a
front page and a JSON copy for machines. Every figure on those pages is
measured at the time written on them; run this again to refresh them.

WHAT IT WRITES, under docs/databank/:
  README.md        the front page: totals, how to ask, every area and dataset
  <area>.md        one per area: each dataset (publisher, terms, rows, span,
                   freshness, what to read before use) and every series in it
  events.md        the event records (one row = one incident or one place)
  live.md          the live tier (checkpoints, fuel, weather, internet)
  archive.md       the news archive (headlines, articles, posts, reports)
  index.json       the same, compact, for machines
Nothing is written to the database (the session is set read-only first).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "databank"

# The datasets ported from the first system carry names like "v1 food — wfp".
# These are the names a reader needs (the Arabic ones were written 2026-10-14
# and are Claude's wording until Zaid passes them).
TITLES = {
    "gazacham_trucks_weekly": ("Trucks entering Gaza, looted and delivered, by week (Gaza Chamber of Commerce)",
                               "الشاحنات الداخلة إلى غزة والمنهوبة والواصلة، أسبوعياً (غرفة تجارة غزة)"),
    "un2720_aid_daily": ("Aid offloaded, collected and arrived in Gaza, per day (UN2720 Mechanism)",
                         "المساعدات المفرّغة والمستلمة والواصلة إلى غزة، يومياً (آلية 2720)"),
    "v1_aid_access_unrwa_aid_trucks": ("Aid consignments entering Gaza, Oct 2023 to Jan 2025 (UNRWA logistics log)",
                                       "شحنات المساعدات الداخلة إلى غزة، من تشرين الأول 2023 إلى كانون الثاني 2025 (الأونروا)"),
    "btselem_fatalities": ("Palestinians killed, one row per person, 2000 to September 2023 (B'Tselem)",
                           "الشهداء، سجلّ لكل شخص، من 2000 إلى أيلول 2023 (بتسيلم)"),
    "ocha_fatalities_monthly": ("Palestinians killed by Israelis, by month, area, perpetrator, age and governorate (OCHA)",
                                "الفلسطينيون الذين قتلهم إسرائيليون، شهرياً حسب المنطقة والفاعل والعمر والمحافظة (أوتشا)"),
    "v1_casualties_ocha_casualties": ("Palestinian casualties since 2008: yearly totals and splits (OCHA)",
                                      "الضحايا الفلسطينيون منذ 2008: المجاميع السنوية وتفصيلها (أوتشا)"),
    "acled_hdx_monthly": ("Political violence, demonstrations and attacks on civilians, by month and governorate (ACLED)",
                          "العنف السياسي والمظاهرات والاعتداءات على المدنيين، شهرياً حسب المحافظة (أكليد)"),
    "gaza_moh_daily": ("Gaza Ministry of Health daily reports: killed, injured, and more, from February 2024",
                       "تقارير وزارة الصحة في غزة اليومية: الشهداء والجرحى وغيرها، من شباط 2024"),
    "insecurity_insight_incidents": ("Attacks on health care, aid workers, schools, food and water systems (Insecurity Insight)",
                                     "الاعتداءات على الرعاية الصحية وعمّال الإغاثة والمدارس وأنظمة الغذاء والمياه (إنسكيوريتي إنسايت)"),
    "t4p_gaza_daily": ("Gaza's daily toll since 7 October 2023: killed, children, medics, press, civil defence (Tech for Palestine)",
                       "حصيلة غزة اليومية منذ 7 تشرين الأول 2023: الشهداء والأطفال والطواقم الطبية والصحفيون والدفاع المدني (تك فور بالستاين)"),
    "v1_conflict_btselem": ("B'Tselem events (served from the event table)", "أحداث بتسيلم (من جدول الأحداث)"),
    "v1_conflict_goodshepherd": ("Good Shepherd Collective events (served from the event table)",
                                 "أحداث مجموعة الراعي الصالح (من جدول الأحداث)"),
    "v1_conflict_palopenmaps": ("Depopulation of Palestinian localities, 1935 to 1967 (Palestine Open Maps, event table)",
                                "تهجير البلدات الفلسطينية، 1935 إلى 1967 (خرائط فلسطين المفتوحة، جدول الأحداث)"),
    "v1_conflict_t4p_westbank": ("West Bank toll since 7 October 2023: killed, injured, children, settler attacks (OCHA via Tech for Palestine)",
                                 "حصيلة الضفة منذ 7 تشرين الأول 2023: الشهداء والجرحى والأطفال واعتداءات المستوطنين (أوتشا عبر تك فور بالستاين)"),
    "v1_conflict_tech4palestine": ("Gaza and West Bank cumulative tolls (Tech for Palestine, continued by the daily datasets)",
                                   "الحصيلة التراكمية في غزة والضفة (تك فور بالستاين، تكملها المجموعات اليومية)"),
    "v1_conflict_ucdp": ("Georeferenced conflict events since 1989 (UCDP, event table)", "أحداث النزاع بمواقعها منذ 1989 (UCDP، جدول الأحداث)"),
    "v1_connectivity_ioda": ("Internet outages detected, with their duration (IODA)", "انقطاعات الإنترنت ومدتها (IODA)"),
    "v1_connectivity_ooni": ("Web censorship measurements, share anomalous per day (OONI)", "قياسات حجب المواقع، نسبة الشذوذ يومياً (OONI)"),
    "v1_culture_heritage_composite": ("Heritage sites and their reported status (composite register)", "مواقع التراث وحالتها المبلّغ عنها (سجل مركّب)"),
    "v1_demolitions_ocha_demolitions": ("Demolitions in the West Bank: structures and people displaced, by year and locality (OCHA)",
                                        "الهدم في الضفة: المنشآت والمهجّرون، سنوياً وحسب البلدة (أوتشا)"),
    "gazacham_cash": ("Commission paid in Gaza to turn a balance into cash, by day, week and month (Gaza Chamber of Commerce)",
                      "عمولة تحويل الرصيد إلى نقد في غزة، يومياً وأسبوعياً وشهرياً (غرفة تجارة غزة)"),
    "ilostat_quarterly": ("Unemployment and labour force participation by quarter, sex and age (ILO)",
                          "البطالة والمشاركة في القوى العاملة، فصلياً حسب الجنس والعمر (منظمة العمل الدولية)"),
    "un_wpp_2024": ("Population estimates 1950 to 2023: births, deaths, ages, life expectancy (UN World Population Prospects 2024)",
                    "تقديرات السكان 1950 إلى 2023: المواليد والوفيات والأعمار ومتوسط العمر (التوقعات السكانية للأمم المتحدة 2024)"),
    "un_wpp_2024_projection": ("Population projections 2024 to 2100, medium variant (UN World Population Prospects 2024)",
                               "إسقاطات السكان 2024 إلى 2100، المتغير المتوسط (الأمم المتحدة 2024)"),
    "v1_economic_imf": ("GDP, inflation, current account and population by year (IMF DataMapper)", "الناتج المحلي والتضخم والحساب الجاري والسكان سنوياً (صندوق النقد الدولي)"),
    "v1_economic_worldbank": ("World Development Indicators for Palestine, 1960 on (World Bank)", "مؤشرات التنمية العالمية لفلسطين، من 1960 (البنك الدولي)"),
    "v1_pcbs_pcbs": ("PCBS-sourced indicators as the World Bank republishes them", "مؤشرات مصدرها الإحصاء الفلسطيني كما يعيد البنك الدولي نشرها"),
    "v1_education_hdx": ("West Bank school register (Ministry of Education and UNICEF via OCHA)", "سجل مدارس الضفة (وزارة التربية واليونيسف عبر أوتشا)"),
    "fao_diem_household_surveys": ("Household surveys on crops, livestock, income and needs (FAO DIEM)", "مسوح الأسر عن المحاصيل والمواشي والدخل والاحتياجات (فاو)"),
    "gazacham_prices": ("Weekly market prices of 30 goods against pre-war, and the Gaza price index (Gaza Chamber of Commerce)",
                        "أسعار 30 سلعة أسبوعياً مقارنة بما قبل الحرب، ومؤشر أسعار غزة (غرفة تجارة غزة)"),
    "ipc_phases": ("People in each IPC phase of acute food insecurity in Gaza, by analysis and area (IPC)",
                   "السكان في كل مرحلة من مراحل انعدام الأمن الغذائي الحاد في غزة، حسب التحليل والمنطقة (IPC)"),
    "market_channel_prices": ("Gaza market prices by day, as a market channel posts them (68 goods by area)",
                              "أسعار سوق غزة يومياً كما تنشرها قناة الأسعار (68 سلعة حسب المنطقة)"),
    "v1_food_wfp": ("Monthly retail food prices by market, 2007 on (WFP)", "أسعار الغذاء بالتجزئة شهرياً حسب السوق، من 2007 (برنامج الأغذية العالمي)"),
    "v1_funding_unfts": ("Humanitarian funding flows: paid, committed, pledged (OCHA Financial Tracking Service)",
                         "تدفقات التمويل الإنساني: المدفوع والملتزم به والمتعهّد به (خدمة التتبع المالي، أوتشا)"),
    "v1_health_gaza_moh": ("Gaza Ministry of Health (served through the daily dataset)", "وزارة الصحة في غزة (عبر المجموعة اليومية)"),
    "v1_health_hdx": ("Health facilities (HDX, event table)", "المرافق الصحية (HDX، جدول الأحداث)"),
    "v1_health_who": ("Health indicators by year, 1975 on: mortality, disease, services, water and sanitation (WHO GHO)",
                      "مؤشرات الصحة سنوياً من 1975: الوفيات والأمراض والخدمات والمياه والصرف (منظمة الصحة العالمية)"),
    "who_ssa_monthly": ("Attacks on health care by month, 2017 on: attacks, killed, injured, what was hit (WHO SSA)",
                        "الاعتداءات على الرعاية الصحية شهرياً من 2017: الاعتداءات والشهداء والجرحى وما أصيب (منظمة الصحة العالمية)"),
    "cited_figures": ("Cited figures: one publisher's statement per row, with its document", "أرقام مقتبسة: تصريح ناشر واحد في كل سجل، مع وثيقته"),
    "v1_historical_archives": ("Historical events 1967 to 2000 (event table)", "أحداث تاريخية 1967 إلى 2000 (جدول الأحداث)"),
    "v1_historical_palopenmaps": ("Locality populations in 1922, 1931, 1945 and 2016, and what became of each place (Palestine Open Maps)",
                                  "سكان البلدات في 1922 و1931 و1945 و2016، ومصير كل بلدة (خرائط فلسطين المفتوحة)"),
    "nightlights_monthly": ("Night lights over each governorate by month, 2012 on (World Bank, Black Marble)",
                            "أضواء الليل فوق كل محافظة شهرياً من 2012 (البنك الدولي، بلاك ماربل)"),
    "v1_infrastructure_hdx": ("Mandate-era village boundaries and the Separation Barrier's segments (HDX)", "حدود القرى أيام الانتداب ومقاطع جدار الفصل (HDX)"),
    "v1_infrastructure_tech4palestine": ("Buildings destroyed in Gaza: homes, schools, mosques, to October 2025 (Tech for Palestine)",
                                         "المباني المدمّرة في غزة: المساكن والمدارس والمساجد، حتى تشرين الأول 2025 (تك فور بالستاين)"),
    "v1_infrastructure_unosat": ("Structures damaged in Gaza by satellite assessment (UNOSAT)", "المنشآت المتضررة في غزة بتقييم الأقمار الصناعية (يونوسات)"),
    "v1_land_goodshepherd": ("Structures demolished per day, West Bank and East Jerusalem (Good Shepherd Collective)",
                             "المنشآت المهدومة يومياً في الضفة والقدس الشرقية (مجموعة الراعي الصالح)"),
    "v1_land_ocha": ("Separation Barrier segments (OCHA, January 2018)", "مقاطع جدار الفصل (أوتشا، كانون الثاني 2018)"),
    "v1_land_peace_now": ("Israeli settlement built-up areas in the West Bank (Peace Now via OCHA)", "المناطق المبنية في المستوطنات الإسرائيلية في الضفة (السلام الآن عبر أوتشا)"),
    "v1_martyrs_snapshot_2023_tech4palestine": ("Gaza's dead identified by name (Ministry of Health list via Tech for Palestine)",
                                                "شهداء غزة بأسمائهم (قائمة وزارة الصحة عبر تك فور بالستاين)"),
    "v1_economic_pcbs_direct": ("Consumer price index, population and poverty, from PCBS itself", "الرقم القياسي لأسعار المستهلك والسكان والفقر، من الإحصاء الفلسطيني نفسه"),
    "arrests_joint_monthly": ("Arrests and administrative orders by month, 2016 to January 2024 (the prisoner institutions' joint report)",
                              "الاعتقالات وأوامر الاعتقال الإداري شهرياً، 2016 إلى كانون الثاني 2024 (التقرير المشترك لمؤسسات الأسرى)"),
    "v1_prisoners_addameer": ("Palestinians held by Israel by month, 2011 on: children, women, administrative detention and more (Addameer)",
                              "الأسرى لدى إسرائيل شهرياً من 2011: الأطفال والنساء والإداريون وغيرهم (الضمير)"),
    "v1_prisoners_hamoked": ("Palestinians held by Israel by month and status, 2008 on (HaMoked)", "الأسرى لدى إسرائيل شهرياً حسب الوضع، من 2008 (هموكيد)"),
    "unhcr_population_hdx": ("People from Palestine counted by UNHCR, by country of asylum, category, sex and age, 1976 on",
                             "الفلسطينيون في إحصاء المفوضية حسب بلد اللجوء والفئة والجنس والعمر، من 1976"),
    "unrwa_registered_hdx": ("UNRWA-registered Palestine refugees by field, sex and age (December 2025)", "لاجئو فلسطين المسجلون لدى الأونروا حسب الإقليم والجنس والعمر (كانون الأول 2025)"),
    "v1_refugees_idmc": ("Displacement events with the people displaced (IDMC)", "أحداث النزوح وعدد النازحين (مركز رصد النزوح الداخلي)"),
    "v1_refugees_unhcr": ("Palestinian refugees and asylum-seekers abroad, by country of asylum (UNHCR)", "اللاجئون وطالبو اللجوء الفلسطينيون في الخارج حسب بلد اللجوء (المفوضية)"),
    "v1_refugees_unrwa": ("Registered refugees per camp (UNRWA camp pages)", "اللاجئون المسجلون في كل مخيم (صفحات الأونروا)"),
    "peacenow_settlement_population": ("Population of 141 Israeli settlements by year, 1980 on (Peace Now)", "سكان 141 مستوطنة إسرائيلية سنوياً، من 1980 (السلام الآن)"),
    "v1_settlements_peace_now": ("Israeli settlers in the West Bank, excluding East Jerusalem, by year since 1967 (Peace Now)",
                                 "المستوطنون الإسرائيليون في الضفة عدا القدس الشرقية، سنوياً منذ 1967 (السلام الآن)"),
    "who_gho_wash": ("Water and sanitation: open defecation by area type (WHO GHO)", "المياه والصرف الصحي: التغوّط في العراء حسب نوع المنطقة (منظمة الصحة العالمية)"),
    "tier1_daily": ("The live tier's daily rollup: reports per checkpoint and state per day, from 9 June 2026",
                    "الملخص اليومي للراصد الحي: البلاغات لكل حاجز وحالة في اليوم، من 9 حزيران 2026"),
}
AREA_AR_FALLBACK = {"infrastructure": "البنية التحتية", "martyrs_snapshot_2023": "الشهداء بأسمائهم"}
STATUS = {
    "fresh": "fresh: read on its own rhythm and within its allowance",
    "late": "late: past its allowance",
    "stalled": "stalled: twice past its allowance",
    "closed_corpus": "closed collection: complete, nothing more will come",
    "dead_upstream": "ended by its publisher",
    "awaiting_permission": "waiting for the publisher's permission",
    "projection": "projection: its dates are projected years",
    "continued": "continued by a successor dataset",
    None: "not judged by the radar (the live tier's own rollup)",
}
OPEN = {"open", "attribution", "share-alike"}


def _q(cur, sql, *a):
    cur.execute(sql, a)
    return cur.fetchall()


def _d(x) -> str | None:
    return x.date().isoformat() if hasattr(x, "date") else (x.isoformat() if hasattr(x, "isoformat") else x)


def measure() -> dict:
    from ops import gap_radar as G
    from resolve.db import connect
    now = datetime.now(timezone.utc)
    m: dict = {"measured_at": now.isoformat(timespec="minutes")}
    with connect() as conn:
        conn.execute("SET default_transaction_read_only = on")
        with conn.cursor() as cur:
            one = lambda sql: _q(cur, sql)[0][0]                       # noqa: E731
            m["totals"] = {
                "rows_held": one("SELECT count(*) FROM observation WHERE upper_inf(sys_period)"),
                "rows_superseded_kept": one("SELECT count(*) FROM observation WHERE NOT upper_inf(sys_period)"),
                "rows_queryable": one("SELECT count(*) FROM databank_serving"),
                "rows_exportable": one("SELECT count(*) FROM databank_bulk"),
                "rows_withheld_from_partners": int(one("SELECT COALESCE(sum(rows_held),0) FROM v_withheld")),
                "datasets": one("SELECT count(*) FROM dataset"),
                "sources": one("SELECT count(*) FROM source"),
                "series_with_rows": one("SELECT count(DISTINCT indicator) FROM observation WHERE upper_inf(sys_period)"),
                "series_defined": one("SELECT count(*) FROM indicator_def"),
                "events": one("SELECT count(*) FROM event WHERE upper_inf(sys_period)"),
                "live_readings": one("SELECT count(*) FROM state_observation"),
                "crowd_messages": one("SELECT count(*) FROM claim"),
                "archive_texts": one("SELECT count(*) FROM document"),
                "places": one("SELECT count(*) FROM place WHERE merged_into IS NULL"),
            }
            cats = {k: (en, ar or AREA_AR_FALLBACK.get(k, "")) for k, en, ar in
                    _q(cur, "SELECT key, name_en, name_ar FROM category")}
            served = dict(_q(cur, "SELECT dataset_key, count(*) FROM databank_serving GROUP BY 1"))
            bulk = dict(_q(cur, "SELECT dataset_key, count(*) FROM databank_bulk GROUP BY 1"))
            held = {k: int(n) for k, n in _q(cur, "SELECT dataset_key, sum(rows_held) FROM v_withheld GROUP BY 1")}
            radar = {d["dataset"]: d for d in G.measure_datasets(cur, now.date())}
            events = dict(_q(cur, """SELECT attrs->>'dataset_key', count(*) FROM event
                                     WHERE upper_inf(sys_period) AND attrs ? 'dataset_key' GROUP BY 1"""))
            warn = defaultdict(list)
            names = {}
            for ind, en, ar, unit, kind, w in _q(cur, """SELECT indicator, name_en, name_ar, canonical_unit,
                                                        measure_kind, serve_warning FROM indicator_def"""):
                names[ind] = (en, ar, unit, kind, w)
            series = defaultdict(list)
            for ind, key, n, lo, hi, unit, places in _q(cur, """
                    SELECT o.indicator, d.key, count(*), min(o.occurred_at), max(o.occurred_at),
                           mode() WITHIN GROUP (ORDER BY o.unit), count(DISTINCT o.place_id)
                    FROM observation o JOIN dataset d USING (dataset_id)
                    WHERE upper_inf(o.sys_period) GROUP BY 1, 2 ORDER BY 2, 1"""):
                en, ar, cunit, kind, w = names.get(ind, (None, None, None, None, None))
                series[key].append({"indicator": ind, "name_en": en, "name_ar": ar, "unit": unit or cunit,
                                    "kind": kind, "rows": n, "from": _d(lo), "to": _d(hi), "places": places})
                if w and w not in warn[key]:
                    warn[key].append(w)
            ds = []
            for (key, name, cat, cadence, src, srcname, lic, comm, red, attr, terms, dlic, dcomm, dred, dattr, dterms,
                 attrs) in _q(cur, """
                    SELECT d.key, d.name, d.v1_category, d.cadence, s.key, s.name, s.license_spdx, s.commercial_use,
                           s.redistribution, s.attribution_text, s.terms_url, d.license_spdx, d.commercial_use,
                           d.redistribution, d.attribution_text, d.terms_url, d.attrs
                    FROM dataset d JOIN source s USING (source_id) ORDER BY d.v1_category NULLS LAST, d.key"""):
                rs = series.get(key, [])
                n = sum(s["rows"] for s in rs)
                r = radar.get(key, {})
                sup = _q(cur, """SELECT count(*) FROM observation o JOIN dataset d USING (dataset_id)
                                 WHERE d.key = %s AND NOT upper_inf(o.sys_period)""", key)[0][0]
                lo = min((s["from"] for s in rs if s["from"]), default=None)
                hi = max((s["to"] for s in rs if s["to"] and s["to"] <= f"{now.year + 1}"), default=None)
                en, ar = TITLES.get(key, (name, ""))
                ds.append({
                    "key": key, "title_en": en, "title_ar": ar, "area": cat or "live", "cadence": cadence,
                    "source": src, "publisher": srcname, "licence": dlic or lic,
                    "redistribution": dred or red, "commercial_use": dcomm if dcomm is not None else comm,
                    "attribution": dattr or attr, "terms_url": dterms or terms,
                    "rows": n, "queryable": served.get(key, 0), "exportable": bulk.get(key, 0),
                    "withheld_from_partners": held.get(key, 0), "superseded_kept": sup, "events": events.get(key, 0),
                    "series": len(rs), "from": lo, "to": hi,
                    "status": r.get("status"), "last_information_day": r.get("last_information_day"),
                    "scope_note": (attrs or {}).get("scope_note"), "warnings": warn.get(key, [])[:6],
                    "series_list": rs})
            m["areas"] = {k: {"en": en, "ar": ar} for k, (en, ar) in cats.items()}
            m["datasets"] = ds
            m["events_by_type"] = _q(cur, """SELECT event_type::text, coalesce(attrs->>'dataset_key', 'tracker'),
                                             count(*), min(occurred_at)::date::text, max(occurred_at)::date::text
                                             FROM event WHERE upper_inf(sys_period) GROUP BY 1, 2 ORDER BY 3 DESC""")
            m["live_by_kind"] = _q(cur, """SELECT state_kind::text, count(*), count(DISTINCT place_id),
                                           min(observed_at)::date::text, max(observed_at)::date::text
                                           FROM state_observation GROUP BY 1 ORDER BY 2 DESC""")
            m["places_by_kind"] = _q(cur, "SELECT kind::text, count(*) FROM place WHERE merged_into IS NULL GROUP BY 1 ORDER BY 2 DESC")
            m["archive"] = _q(cur, """SELECT d.source, coalesce(a.name, d.source), d.kind, count(*),
                                      min(d.published_at)::date::text, max(d.published_at)::date::text,
                                      count(*) FILTER (WHERE length(d.body) > 200)
                                      FROM document d LEFT JOIN archive_source a ON a.key = d.source
                                      GROUP BY 1, 2, 3 ORDER BY 4 DESC""")
    return m


def _n(x) -> str:
    return f"{x:,}" if isinstance(x, int) else ("" if x is None else str(x))


def _span(a, b) -> str:
    return f"{(a or '?')[:10]} → {(b or '?')[:10]}"


def _partners(d) -> str:
    if d["area"] == "live":
        return "not in the databank's doors"
    if d["withheld_from_partners"]:
        return f"withheld ({d['redistribution']}); the figure is cited with its source"
    if d["redistribution"] in OPEN:
        return f"yes ({d['redistribution']}{', non-commercial' if d['commercial_use'] is False else ''})"
    return d["redistribution"] or "?"


def _cell(s) -> str:
    return (s or "").replace("|", "/").replace("\n", " ")


def area_page(key: str, area: dict, ds: list[dict], when: str) -> str:
    L = [f"# {area['en']} · {area['ar']}", "",
         f"Measured on the store at {when} UTC by `ops/databank_index.py`. [Back to the index](README.md)", ""]
    for d in ds:
        L += [f"## {d['title_en']}", "", f"{d['title_ar']}" if d["title_ar"] else "", "",
              f"- **Key:** `{d['key']}` · **publisher:** {d['publisher']} (`{d['source']}`)",
              f"- **Rows:** {_n(d['rows'])} held · {_n(d['queryable'])} a question can reach · "
              f"{_n(d['exportable'])} exportable · {_n(d['superseded_kept'])} older values kept"
              + (f" · {_n(d['events'])} event records" if d["events"] else ""),
              f"- **Span:** {_span(d['from'], d['to'])} · **series:** {d['series']} · **cadence:** "
              f"{'as its publisher updates (ported from the first system)' if d['cadence'] == 'migration' else d['cadence']}",
              f"- **Freshness:** {STATUS.get(d['status'], d['status'])}"
              + (f" (last information {d['last_information_day']})" if d["last_information_day"] else ""),
              f"- **Terms:** {d['licence']} · partners: {_partners(d)} · terms: {d['terms_url'] or 'none found'}",
              f"- **Credit:** {_cell(d['attribution']) or 'none required'}"]
        if d["scope_note"]:
            L.append(f"- **Scope:** {_cell(d['scope_note'])}")
        for w in d["warnings"]:
            L.append(f"- **Read before use:** {_cell(w)}")
        if d["series_list"]:
            ex = max(d["series_list"], key=lambda s: s["rows"])["indicator"]
            L += [f"- **Ask:** MCP `databank(category=\"{key}\", indicator=\"{ex}\")` · "
                  f"REST `/v2/databank/{key}?indicator={ex}`", "",
                  "| Series | Name | Unit | Rows | From | To | Places |", "|---|---|---|---:|---|---|---:|"]
            for s in d["series_list"]:
                nm = _cell(s["name_en"]) + (f" · {_cell(s['name_ar'])}" if s["name_ar"] else "")
                L.append(f"| `{s['indicator']}` | {nm} | {s['unit'] or ''} | {_n(s['rows'])} | "
                         f"{(s['from'] or '')[:10]} | {(s['to'] or '')[:10]} | {_n(s['places'])} |")
        elif d["events"]:
            L.append(f"- **Ask:** its records are events: see [events](events.md)")
        L.append("")
    return "\n".join(L)


def front_page(m: dict, by_area: dict) -> str:
    t = m["totals"]
    when = m["measured_at"][:16].replace("T", " ")
    L = ["# The databank index · فهرس بنك البيانات", "",
         f"Every area, dataset and series of the Palestine databank, measured on the store at {when} UTC. "
         "Regenerate with `.venv/bin/python -m ops.databank_index` (read-only; a minute or two).", "",
         "## What is held", "",
         "| | |", "|---|---:|",
         f"| Observations held (current values) | {_n(t['rows_held'])} |",
         f"| … that a question can reach | {_n(t['rows_queryable'])} |",
         f"| … exportable as a file | {_n(t['rows_exportable'])} |",
         f"| … withheld from partners, the figure cited | {_n(t['rows_withheld_from_partners'])} |",
         f"| Older values kept after a correction (never deleted) | {_n(t['rows_superseded_kept'])} |",
         f"| Datasets · sources · series with rows | {_n(t['datasets'])} · {_n(t['sources'])} · {_n(t['series_with_rows'])} |",
         f"| Event records (incidents, attacks, depopulated places) | {_n(t['events'])} |",
         f"| Live readings (checkpoints, fuel, weather, internet, power) | {_n(t['live_readings'])} |",
         f"| Crowd messages read by the live tier | {_n(t['crowd_messages'])} |",
         f"| Archive texts (headlines, articles, posts, reports, chronologies) | {_n(t['archive_texts'])} |",
         f"| Places in the register | {_n(t['places'])} |", "",
         "## How to ask it", "",
         "- **MCP** (`https://live-api.zaidlab.xyz/mcp`): `databank(category, indicator)` for rows, "
         "`series(indicator)` for one series through time, `compare(indicators, place)`, "
         "`correlate(a, b)`, `licence(scope=\"sources\")` for terms. Answers come in Arabic and English with "
         "their source and licence.",
         "- **REST:** `/v2/databank/categories`, `/v2/databank/indicators`, "
         "`/v2/databank/where?indicator=…`, `/v2/databank/{category}?indicator=…`, `/v2/databank/radar` "
         "(freshness of every dataset).",
         "- **The archive** (no API yet): `.venv/bin/python -m ops.ask_archive 'words' --months`.",
         "- **Three words never blurred:** a value; `unknown` (nobody credible looked); `no source` "
         "(nothing measures it).", "",
         "## Areas", "",
         "| Area | | Datasets | Rows held | Series | Span |", "|---|---|---:|---:|---:|---|"]
    for key, ds in sorted(by_area.items(), key=lambda kv: -sum(d["rows"] for d in kv[1])):
        a = m["areas"].get(key, {"en": key, "ar": ""}) if key != "live" else {"en": "Live tier", "ar": "الراصد الحي"}
        lo = min((d["from"] for d in ds if d["from"]), default=None)
        hi = max((d["to"] for d in ds if d["to"]), default=None)
        L.append(f"| [{a['en']}]({key}.md) | {a['ar']} | {len(ds)} | {_n(sum(d['rows'] for d in ds))} | "
                 f"{_n(sum(d['series'] for d in ds))} | {_span(lo, hi)} |")
    L += ["", "Also: [events](events.md) · [the live tier](live.md) · [the news archive](archive.md) · "
          "[index.json](index.json)", "", "## Every dataset", "",
          "| Dataset | Area | Publisher | Rows | Series | Span | Freshness | Partners |",
          "|---|---|---|---:|---:|---|---|---|"]
    for d in sorted(m["datasets"], key=lambda d: (d["area"], -d["rows"])):
        L.append(f"| [{_cell(d['title_en'])}]({d['area']}.md) `{d['key']}` | {d['area']} | {_cell(d['publisher'])} | "
                 f"{_n(d['rows'] or d['events'])} | {d['series']} | {_span(d['from'], d['to'])} | "
                 f"{(d['status'] or 'live').replace('_', ' ')} | {_partners(d)} |")
    return "\n".join(L) + "\n"


def events_page(m: dict) -> str:
    L = ["# Events · الأحداث", "", "One record = one incident, one attack or one place (the depopulation record). "
         "Served by `databank(category=…)` for the databank's own event datasets, and by `incidents` for the "
         "live tier's. [Back to the index](README.md)", "",
         "| Type | From | Records | First | Last |", "|---|---|---:|---|---|"]
    for typ, src, n, lo, hi in m["events_by_type"]:
        L.append(f"| `{typ}` | {src} | {_n(n)} | {lo} | {hi} |")
    return "\n".join(L) + "\n"


def live_page(m: dict) -> str:
    L = ["# The live tier · الراصد الحي", "", "Readings written every few minutes from public channels, crowd "
         "reports, station prices and sensors. Each reading decays with age; an answer says how old it is and how "
         "many independent reporters agree. Asked through `checkpoint_status`, `can_i_travel`, `checkpoints`, "
         "`incidents`, `fuel_prices`, `weather_now`, `connectivity_now`. [Back to the index](README.md)", "",
         "| What is read | Readings | Places | First | Last |", "|---|---:|---:|---|---|"]
    for kind, n, places, lo, hi in m["live_by_kind"]:
        L.append(f"| `{kind}` | {_n(n)} | {_n(places)} | {lo} | {hi} |")
    L += ["", "| Places in the register | |", "|---|---:|"]
    L += [f"| {k} | {_n(n)} |" for k, n in m["places_by_kind"]]
    return "\n".join(L) + "\n"


def archive_page(m: dict) -> str:
    L = ["# The news archive · الأرشيف", "", "Every text the system has read: outlet headlines from their "
         "sitemaps and listings, articles from feeds, Telegram posts, reports and dated chronologies. Asked with "
         "`.venv/bin/python -m ops.ask_archive 'words' --months` (Arabic or English, OR between words). "
         "[Back to the index](README.md)", "",
         "| Source | Name | Kind | Texts | With full text | First | Last |", "|---|---|---|---:|---:|---|---|"]
    for key, name, kind, n, lo, hi, body in m["archive"]:
        L.append(f"| `{key}` | {_cell(name)} | {kind} | {_n(n)} | {_n(body)} | {lo or ''} | {hi or ''} |")
    return "\n".join(L) + "\n"


def write(m: dict) -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    by_area: dict[str, list] = defaultdict(list)
    for d in m["datasets"]:
        by_area[d["area"]].append(d)
    for ds in by_area.values():
        ds.sort(key=lambda d: -(d["rows"] or d["events"]))
    when = m["measured_at"][:16].replace("T", " ")
    files = []
    for key, ds in by_area.items():
        a = m["areas"].get(key) or {"en": "Live tier", "ar": "الراصد الحي"}
        p = OUT / f"{key}.md"
        p.write_text(area_page(key, a, ds, when), encoding="utf-8")
        files.append(p)
    for name, text in (("README.md", front_page(m, by_area)), ("events.md", events_page(m)),
                       ("live.md", live_page(m)), ("archive.md", archive_page(m))):
        (OUT / name).write_text(text, encoding="utf-8")
        files.append(OUT / name)
    compact = {"measured_at": m["measured_at"], "totals": m["totals"], "areas": m["areas"],
               "datasets": [{k: v for k, v in d.items() if k != "series_list"} |
                            {"series": [[s["indicator"], s["name_en"], s["name_ar"], s["unit"], s["rows"],
                                         s["from"], s["to"], s["places"]] for s in d["series_list"]]}
                            for d in m["datasets"]],
               "events_by_type": m["events_by_type"], "live_by_kind": m["live_by_kind"],
               "places_by_kind": m["places_by_kind"], "archive": m["archive"]}
    (OUT / "index.json").write_text(json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str),
                                    encoding="utf-8")
    files.append(OUT / "index.json")
    return files


def main(argv: list[str]) -> int:
    m = measure()
    t = m["totals"]
    print("  " + " · ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in t.items()))
    if "--check" in argv:
        return 0
    files = write(m)
    print(f"  wrote {len(files)} files under {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
