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

from ingest.sources.power import (PLACE_IN_TITLE,   # noqa: E402
                                  notices_in)

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
