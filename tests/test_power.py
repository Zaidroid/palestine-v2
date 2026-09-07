"""NEDCO's scheduled-cut notices — the discovery half.

    ./.venv/bin/python -m pytest tests/test_power.py -q

The parser was never the problem. NEDCO publishes two lists on one page and
they are not the same list: a DATED news column (company announcements,
tenders, delegations) and an undated "تحديثات الموقع" marquee, which is the
only place a cut notice ever appears. The collector read the first one.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.sources.power import (LOCAL_TZ, PLACE_IN_TITLE,   # noqa: E402
                                  discover_notices, notices_in, parse_window,
                                  place_in_title)

# Captured from https://www.nedco.ps on 2026-08-31, decoded windows-1256.
# The two shapes are real and differ in BOTH ways that matter: the marquee
# spells the parameter `newsID`, and it nests the headline two divs inside
# the anchor instead of writing it directly after the tag.
REAL = """
<div id="vmarquee" style="position: absolute; width: 100%;">
\t\t<a href="?page=details&newsID=4876&cat=6">
\t\t<div class="subnews">
\t\t\t<div class="subnewsdate"><i class="fa fa-calendar"></i>23/08/2026</div>
\t\t\tاعلان فصل تيار كهربائي في قرية الباذان
\t\t</div>
\t\t</a>
\t\t<a href="?page=details&newsID=4875&cat=6">
\t\t<div class="subnews">
\t\t\t<div class="subnewsdate"><i class="fa fa-calendar"></i>20/08/2026</div>
\t\t\tاعلان فصل تيار كهربائي في بلدة عصيرة الشمالية
\t\t</div>
\t\t</a>
</div>
<div class="newslist">
\t<a href="?newsid=4870&cat=1">27/08/2026 - رئيس سلطة الطاقة يبحث في نابلس تعزيز التزويد الكهربائي والربط الإقليمي مع الأردن</a>
\t<a href="?newsid=4869&cat=1">13/08/2026 - كهرباء الشمال تستقبل الدكتور ياسر أبو بكر للاطلاع على احتياجات الشركة</a>
</div>
"""


def test_the_marquee_notices_are_discovered():
    """The regression. Before the fix this returned [] against this exact page
    while three cut notices sat in it, and the feed read `silent` for 8 days."""
    found = dict(notices_in(REAL))
    assert set(found) == {"4876", "4875"}


def test_the_headline_survives_without_its_date_chip():
    """The date lives in a sibling div inside the anchor. Left in the captured
    text it lands in front of the place name, and `PLACE_IN_TITLE` anchors on
    the END of the title — so a stray date silently costs the place."""
    found = dict(notices_in(REAL))
    assert found["4876"] == "اعلان فصل تيار كهربائي في قرية الباذان"
    assert "23/08/2026" not in found["4876"]

    place = PLACE_IN_TITLE.search(found["4876"])
    assert place is not None
    assert place.group(1).strip() == "قرية الباذان"


def test_company_news_is_not_a_cut_notice():
    """The dated column is corporate news and must stay out. Reading it as the
    cut list is what made 'the newest notice is 13/08' look like a quiet
    upstream rather than a collector looking in the wrong place."""
    found = dict(notices_in(REAL))
    assert "4870" not in found
    assert "4869" not in found


def test_both_link_spellings_are_accepted():
    """`newsID` in the marquee, `newsid` in the news list — the same site, one
    page. Matching case-sensitively reads whichever half the author last saw."""
    lower = REAL.replace("newsID=", "newsid=")
    upper = REAL.replace("?newsid=", "?newsID=")
    assert set(dict(notices_in(lower))) == {"4876", "4875"}
    assert set(dict(notices_in(upper))) == {"4876", "4875"}


# ---------------------------------------------------------------------------
# 2026-09-07: the marquee was the wrong list too.
# ---------------------------------------------------------------------------

# Captured from https://www.nedco.ps/?page=cat&cat=6 on 2026-09-07, decoded
# windows-1256. This is "أعطال الكهرباء" — the publisher's OWN index of cut
# notices, 38 of them going back to June. The homepage marquee carried seven,
# and the two newest cuts were not among them.
CUT_LIST_PAGE = """
<div class="internalhead"><div class="container">
<a class="index" href="../">الرئيسية</a> /<a href="?cat=1"> اعلانات الشركة </a> /<a href="?cat=6"> أعطال الكهرباء </a>
</div></div>
<div class="col-sm-4 nopadding"> <a class = "m4" href="?page=details&newsID=4879&cat=6">
<div><img class="catimg" alt="فصل تيار كهرائي - قرية تل ."><div style="padding: 4px;">
فصل تيار كهرائي - قرية تل . <p><font size="2"><i class="fa fa-calendar"></i>31/08/2026</font></p>
</div></div></a></div>
<div class="col-sm-4 nopadding"> <a class = "m4" href="?page=details&newsID=4878&cat=6">
<div><img class="catimg" alt="فصل تيار كهربائي - قرية تل ."><div style="padding: 4px;">
فصل تيار كهربائي - قرية تل . <p><font size="2"><i class="fa fa-calendar"></i>31/08/2026</font></p>
</div></div></a></div>
<div class="col-sm-4 nopadding"> <a class = "m4" href="?page=details&newsID=4876&cat=6">
<div><img class="catimg" alt="اعلان فصل تيار كهربائي في قرية الباذان"><div style="padding: 4px;">
اعلان فصل تيار كهربائي في قرية الباذان <p><font size="2"><i class="fa fa-calendar"></i>23/08/2026</font></p>
</div></div></a></div>
"""

# The real body of notice 4878, decoded and tag-stripped as `_text` leaves it.
# Published on the 31st; the cut is on the 1st. Both dates are in the text and
# only one of them is the fact.
BODY_4878 = (
    " / اعلانات الشركة / أعطال الكهرباء فصل تيار كهربائي - قرية تل . "
    "تاريخ النشر: 31/08/2026 - عدد القراءات: 377 "
    "في ضوء اعمال الصيانة والتطوير على الخطوط والشبكات الكهربائية تعتذر شركة "
    "توزيع كهرباء الشمال لمشتركيها الكرام عن فصل التيار الكهربائي في المناطق "
    "التالية في قرية تل في نابلس وتشمل: \"منطقة العاروط قرب محل اعلاف بلال "
    "نوفل والمنطقة المحيطة\". وذلك في الفترة الواقعة مابين الساعة 8:30 صباحاً "
    "الى الساعة 1:30 من ظهر يوم الثلاثاء الموافق 1/9/2026. نتميز بخدمتكم"
)

# 4854, published 2026-07-30: an unannounced fault, not a scheduled cut —
# "لمدة ساعة من الان". It states no day and no window, and never did.
BODY_4854_EMERGENCY = (
    "تاريخ النشر: 30/07/2026 - عدد القراءات: 372 #تنويه لمشتركينا الكرام في "
    "مدينة نابلس تعتذر شركة توزيع كهرباء الشمال عن انقطاع التيار الكهربائي عن "
    "المناطق التالية في مدينة نابلس : التعاون العلوي واسكان الكهرباء والمنطقة "
    "المحيطة وذلك لمدة ساعة من الان بسبب اعمال صيانة طارئة على الشبكة الكهربائية."
)


def test_the_dedicated_cut_list_is_the_discovery_surface():
    """THE REGRESSION. Discovery read the homepage, and the homepage marquee
    does not carry every notice: on 2026-09-07 it showed seven while the
    publisher's own أعطال الكهرباء index showed thirty-eight, including the
    two newest — a cut in قرية تل announced on 08-31 for 09-01. Neither ever
    reached the database, so `power` read silent for fifteen days while the
    fault was ours, again."""
    asked: list[str] = []

    def fake_get(url: str) -> str:
        asked.append(url)
        return CUT_LIST_PAGE if "cat=6" in url else REAL

    import ingest.sources.power as power
    real_get, power._get = power._get, fake_get
    try:
        found = dict(power.discover_notices())
    finally:
        power._get = real_get

    assert any("cat=6" in u for u in asked), "the cut list itself was never fetched"
    assert {"4879", "4878"} <= set(found)


def test_the_homepage_marquee_is_not_the_whole_list():
    """Stated as its own fact so it cannot quietly stop being true: the page
    the collector used to read does not contain the notices above."""
    assert {"4879", "4878"} & set(dict(notices_in(REAL))) == set()


def test_the_window_is_the_announced_day_not_the_day_it_was_published():
    """THE SECOND REGRESSION, and the one that reached serving. `parse_window`
    took the FIRST date in the body, which is always the publication chip
    ("تاريخ النشر"), never the announced day. Notices are posted one to three
    days ahead — so every cut this collector has ever recorded was filed on a
    day when there was no cut, and `active_now` could assert one there."""
    window = parse_window(BODY_4878)
    assert window is not None
    start, end = window
    assert start.astimezone(LOCAL_TZ).date().isoformat() == "2026-09-01"
    assert start.astimezone(LOCAL_TZ).strftime("%H:%M") == "08:30"
    assert end.astimezone(LOCAL_TZ).strftime("%H:%M") == "13:30"


def test_every_way_the_publisher_writes_the_announced_date():
    """Four separators and two orderings across 38 real notices, plus one
    notice that drops the alif ("لموافق"). A date form we cannot read falls
    back to nothing, which is correct — but it costs a whole notice, so the
    variants are worth naming."""
    stem = ("وذلك في الفترة الواقعة مابين الساعة 8:30 صباحاً الى الساعة 1:30 "
            "من ظهر يوم الثلاثاء ")
    for written, expected in [("الموافق 1/9/2026", "2026-09-01"),
                              ("الموافق 24_8_2026", "2026-08-24"),
                              ("الموافق 4-8-2026", "2026-08-04"),
                              ("الموافق 2026/7/21", "2026-07-21"),
                              ("لموافق 16/7/2026", "2026-07-16")]:
        window = parse_window("تاريخ النشر: 01/01/2020 " + stem + written)
        assert window is not None, f"unread: {written}"
        assert window[0].astimezone(LOCAL_TZ).date().isoformat() == expected


def test_an_unannounced_fault_gets_no_window_at_all():
    """The publication date must not stand in for an announced one. Two of the
    38 notices are live faults rather than schedules; they carry no day and no
    window, and inventing one from the posting date is how a cut gets asserted
    on a day nobody announced."""
    assert parse_window(BODY_4854_EMERGENCY) is None


def test_the_dash_form_title_keeps_its_place():
    """THE THIRD REGRESSION. Fourteen of the 38 titles name the place after a
    dash instead of "في", and `PLACE_IN_TITLE` only knows "في|عن ... $". Those
    notices were discovered and then dropped whole for want of a place —
    including both of the 08-31 cuts."""
    assert place_in_title("فصل تيار كهربائي - قرية تل .") == "قرية تل"
    assert place_in_title("فصل تيار كهرائي - قرية تل .") == "قرية تل"
    assert place_in_title("فصل تيار كهربائي -عصيرة الشمالية") == "عصيرة الشمالية"
    assert place_in_title("فصل تيار كهربائيي- عصيرة الشمالية") == "عصيرة الشمالية"
    assert place_in_title("فصل تيار كهربائي - بلدة ياصيد / نابلس .") == "بلدة ياصيد / نابلس"


def test_the_in_form_still_wins_and_still_reads_the_same():
    """The dash rule must not touch the majority form. These five are exactly
    what the collector resolves today."""
    assert place_in_title("اعلان فصل تيار كهربائي في قرية الباذان") == "قرية الباذان"
    assert place_in_title("فصل تيار كهربائي في مدينة نابلس") == "مدينة نابلس"
    assert place_in_title("فصل تيار كهربائي في سالم") == "سالم"
    assert place_in_title("فصل تيار كهربائي في منطقة التعاون العلوي في مدينة نابلس") \
        == "منطقة التعاون العلوي في مدينة نابلس"
    assert place_in_title("اعلان فصل تيار كهربائي") is None


def test_the_hour_is_read_when_the_publisher_spells_it_with_a_haa():
    """One notice in 38 writes "من الساعه 11:00" — hā' for tā' marbūṭa. TIME
    then matches once instead of twice, `parse_window` wants two, and a real
    announced cut (4871, نابلس, 2026-08-21 11:00–12:00) has no window and is
    never recorded. The variant costs a whole notice, so it is named."""
    body = ("تاريخ النشر: 20/08/2026 وذلك من الساعه 11:00 الى الساعة 12:00 "
            "من ظهر يوم الجمعة الموافق 21/8/2026.")
    window = parse_window(body)
    assert window is not None
    start, end = window
    assert start.astimezone(LOCAL_TZ).date().isoformat() == "2026-08-21"
    assert start.astimezone(LOCAL_TZ).strftime("%H:%M") == "11:00"
    assert end.astimezone(LOCAL_TZ).strftime("%H:%M") == "12:00"
