"""OCHA's casualty incidents by month, the prisoner institutions' joint monthly
report, Ma'an's listing and Palestine Today's sitemaps (2026-10-14). No network:
each reader's pure part on text cut down from the real pages."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from ops import fetch_joint_arrests as ja
from ops import fetch_maan as maan
from ops import fetch_ocha_monthly as om
from ops import fetch_sitemaps as fs
from ops import fetchlib as fl
from ops import gap_radar

ROOT = Path(__file__).resolve().parent.parent


def page(lead: str, rest: str = "") -> str:
    return f"<html><nav>الاعتقال الإداري أوامر</nav><div>11-12-2022 {lead} . {rest}</div></html>"


def test_the_joint_report_reads_its_lead_sentence_and_the_months_orders():
    got = ja.read_report(
        "مؤسسات الأسرى: الاحتلال اعتقل (496) فلسطيني/ة خلال شهر يناير/ كانون الثاني 2020",
        page("اعتقلت قوات الاحتلال الإسرائيلي (496) فلسطيني/ة من الأرض الفلسطينية المحتلة خلال شهر يناير / كانون الثاني 2020، "
             "من بينهم (67) طفلا، ومن النساء (16)",
             "إلى أن سلطات الاحتلال اعتقلت (245) مواطنا من مدينة القدس . فيما بلغ عدد المعتقلين الأطفال قرابة (200) طفل، "
             "وبلغ عدد أوامر الاعتقال الإداري الصادرة (96) أمر إداري بينهم (32) جديد و(64) تجديد"))
    assert (got["year"], got["month"], got["arrests"], got["children"], got["women"]) == (2020, 1, 496, 67, 16)
    assert got["jerusalem"] == 245                     # and never the 200 children HELD
    assert (got["admin_orders"], got["admin_orders_new"], got["admin_orders_renewed"]) == (96, 32, 64)


def test_a_woman_is_not_an_order_and_a_years_orders_are_not_the_months():
    got = ja.read_report(
        "مؤسسات الأسرى: الاحتلال اعتقل (509) فلسطيني خلال شهر آذار 2017",
        page("اعتقلت خلال شهر آذار/مارس 2017 (509) فلسطينيا من الضفة الغربية وقطاع غزة والقدس، من بينهم (75) طفلا و(13) امرأة",
             "ومنذ بداية العام الجاري أصدرت (1829) أمر اعتقال إداري . أصدرت سلطات الاحتلال (111) أمرا إداريا، من بينها أمر"))
    assert got["women"] == 13 and got["admin_orders"] == 111      # «(13) امرأة» is not 13 orders; 1829 is the year's


def test_a_misprinted_title_is_kept_beside_the_texts_figure():
    got = ja.read_report("مؤسسات الأسرى: الاحتلال اعتقل (547) فلسطيني خلال شهر تموز 2016",
                         page("اعتقلت خلال شهر تموز/ يوليو 2016 (574) فلسطينيا من الضفة الغربية وقطاع غزة، من بينهم (111) طفلا و(12) سيدة"))
    assert (got["arrests"], got["title_says"], got["women"]) == (574, 547, 12)


def test_years_half_years_and_two_month_reports_are_not_months():
    assert ja.read_report("مؤسسات الأسرى: الاحتلال اعتقل أكثر من (5500) فلسطيني/ة خلال عام 2019", page("")) == \
        {"skip": "not a month's report"}
    assert ja.read_report("مؤسسات الأسرى: الاحتلال اعتقل 905 فلسطيني خلال شهري آذار ونيسان", page("")) == \
        {"skip": "two months together"}
    june = ja.read_report("مؤسسات الأسرى: الاحتلال اعتقل (464) مواطن/ة خلال حزيران/يونيو الماضي و(3873) فلسطينيا خلال النصف الأول من العام 2022",
                          "<div>07-07-2022 اعتقل جيش الاحتلال من بداية العام (3873)</div>")
    assert (june["year"], june["month"], june["arrests"]) == (2022, 6, 464)


def test_from_october_2023_the_reports_count_the_west_bank_alone():
    reports = [{"href": "/ar/media/5271", "title": "الاحتلال اعتقل من الضّفة خلال كانون الثاني/ يناير 2024، (1236) فلسطينيًا",
                "page": page("اعتقلت قوات الاحتلال الإسرائيلي (1236) مواطنا، بينهم (30) من النساء، و(73) من الأطفال، من الضفة خلال شهر كانون الثاني/ يناير 2024",
                             "حيث أصدر الاحتلال خلال شهر كانون الثاني (650) أمر اعتقال إداري بينهم (370) جديد و(280) تجديد")}]
    recs, _ = ja.records(reports)
    got = {r["measure"]: r["value"] for r in recs}
    assert got == {"total_west_bank": 1236, "children_west_bank": 73, "women_west_bank": 30,
                   "admin_orders_west_bank": 650, "admin_orders_new_west_bank": 370, "admin_orders_renewed_west_bank": 280}
    assert all(r["location"]["region"] == "West Bank" for r in recs)


def ms(y, m, d=15):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def test_ocha_counts_by_month_and_every_split_adds_up():
    rows = [[ms(2023, 10, 7), "West Bank", "Jenin", "Military forces", "Children", "Civilian", 2],
            [ms(2023, 10, 9), "West Bank", "Hebron", "Civilian-settler", "Adults", "Civilian", 1],
            [ms(2023, 10, 9), "Gaza Strip", "Gaza North", "Military forces", "Adults", "Armed group", 3],
            [ms(2023, 12, 1), "Israel", "Israel", "Non-military security forces", "Adults", "Unknown", 1]]
    recs, notes = om.monthly(rows, date(2024, 1, 9))
    v = {(r["measure"], r["date"]): r["value"] for r in recs}
    oct_ = "2023-10-01"
    assert v[("killed", oct_)] == 6 and v[("killed_west_bank", oct_)] == 3 and v[("killed_gaza_strip", oct_)] == 3
    assert v[("killed_by_israeli_forces", oct_)] == 5 and v[("killed_by_settlers", oct_)] == 1
    assert v[("killed_children", oct_)] == 2 and v[("killed_armed_group_members", oct_)] == 3
    assert v[("killed_gov_north_gaza", oct_)] == 3 and v[("killed_gov_jenin", oct_)] == 2   # «Gaza North» is North Gaza
    assert v[("killed", "2023-11-01")] == 0                    # nothing recorded: 0, not missing
    assert all(r["partial_month"] for r in recs if r["date"] == "2024-01-01")
    assert notes["governorate_not_listed"] == {"Israel": 1} and notes["killed_total"] == 7


def test_maans_listing_gives_id_headline_and_day():
    html = ('<a class="list-6__item" href="https://www.maannews.net/news/2170503.html" title="انهيار مبنى قيد التجديد في  تل أبيب">'
            '<div class="list-6__date">14/10/2026</div><div class="list-6__title">x</div></a>'
            '<a class="list-6__item" href="/news/6.html" title="&quot;عنوان&quot; قديم"><div class="list-6__date">09/05/2005</div></a>')
    got = maan.items_of(html)
    assert [(i["id"], i["title"], i["date"]) for i in got] == [
        ("2170503", "انهيار مبنى قيد التجديد في تل أبيب", "2026-10-14"), ("6", '"عنوان" قديم', "2005-05-09")]


@pytest.mark.parametrize("caption, address, ok", [
    ("أوفير بنيس: موشيه فيغلين هو زعيم الليكود وليس بنيامين نتنياهو", "خبر أوفير بنيس موشيه فيغلين هو", True),
    ("استقرار على الدولار وارتفاع سعر الدينار واليورو اليوم الأربعاء", "استقرار على الدولار وارتفاع سع", True),
    ("الديمقراطية", "الديمقراطية اقتحام مؤسسة الضمي", False),           # a one-word label is not the headline
    ("مرضى الثلاسيميا.", "صحة غزة إجلاء 5 مرضى فقط إلى ا", False),      # a photo's caption
])
def test_palestine_todays_caption_is_the_headline_only_when_it_covers_the_cut_address(caption, address, ok):
    assert fs._covers_cut_address(caption, address) is ok


def test_palestine_todays_items_without_a_headline_are_listed_apart():
    o = fs.OUTLETS["paltoday"]
    block = ("<loc>https://paltoday.ps/ar/post/545438/صحة-غزة-إجلاء-5-مرضى-فقط-إلى-ا</loc>"
             "<lastmod>2026-10-12T20:59:56+03:00</lastmod><image:image><image:caption>مرضى الثلاسيميا.</image:caption></image:image>")
    rec = fs.entry_of(o, block)
    assert rec["untitled"] and rec["title"] is None and rec["id"] == "545438" and rec["date"] == "2026-10-12"


def test_the_night_and_the_radar_know_the_new_datasets():
    sync = (ROOT / "ops" / "databank-sync.sh").read_text()
    assert "step .venv/bin/python -m ops.fetch_ocha_monthly" in sync
    assert "step .venv/bin/python -m ops.fetch_ocha_injuries" in sync
    assert gap_radar.SUPPLY_LINES["ocha-injuries"]["feeds"] == ["ocha_injuries_monthly"]
    assert gap_radar.SUPPLY_LINES["ocha-monthly"]["feeds"] == ["ocha_fatalities_monthly"]
    assert "arrests_joint_monthly" in gap_radar.CLOSED_CORPUS
    for name in ("ocha_monthly", "ocha_injuries", "arrests_joint"):
        spec = yaml.safe_load((ROOT / "db" / "mappings" / f"{name}.yaml").read_text(encoding="utf-8"))
        rules = spec["registry"]["rules"]
        assert rules and all(r["name_ar"] and r["serve_warning_ar"] for r in rules), name
    assert fl is not None


def test_ocha_injuries_by_month_add_up_and_count_children():
    """OCHA's injuries table joins the child flag and the sex in `SA`; every split must add up to the month."""
    from datetime import date
    from ops import fetch_ocha_injuries as oi
    jan = 1704067200000                                   # 2024-01-01
    rows = [[jan, "West Bank", "Hebron", "Military forces", "YesMale", 3],
            [jan, "West Bank", "Nablus", "Civilian-settler", "NoFemale", 2],
            [jan, "Israel (West Bank Related)", "Israel", "Civilian", "Unknownunknown", 1]]
    recs, notes = oi.monthly(rows, date(2024, 2, 10))
    v = {(r["measure"], r["date"]): r["value"] for r in recs}
    assert v[("injured", "2024-01-01")] == 6 and v[("injured_children", "2024-01-01")] == 3
    assert v[("injured_by_settlers", "2024-01-01")] == 2 and v[("injured_by_other_or_disputed", "2024-01-01")] == 1
    assert v[("injured_israel", "2024-01-01")] == 1 and v[("injured_gov_hebron", "2024-01-01")] == 3
    assert v[("injured", "2024-02-01")] == 0 and notes["governorate_not_listed"] == {"Israel": 1}
    assert oi.age_of("YesFemale") == "children" and oi.age_of("NoMale") == "adults" and oi.age_of(None) == "age_unknown"
