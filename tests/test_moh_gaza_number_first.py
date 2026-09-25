"""The Gaza daily series stopped on 2026-08-09: from 08-10 the Ministry wrote the
24-hour block number-first, and a ▪️ bullet posed as a section header. Found by
organ C's control run (P2-A.1); fixed in cascade/moh_gaza.py."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cascade.moh_gaza import parse                                          # noqa: E402

HEAD = "🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى\n⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية:\n"
TAIL = "\n🔴 منذ وقف إطلاق النار (11 أكتوبر):\nإجمالي الشهداء: 1,408 شهداء\nإجمالي الإصابات: 4,916 إصابة\n"


def test_number_first_lines_after_the_24_hour_header():
    r = parse(HEAD + "5 شهداء، بينهم شهيد متأثر بجراحه.\n35 إصابة." + TAIL)
    assert r.tiers["daily"] == {"deaths": 5, "injuries": 35}
    assert r.tiers["since_ceasefire"] == {"deaths": 1408, "injuries": 4916}


def test_bullets_and_dashes_are_data_not_headers():
    r = parse(HEAD + "▪️1 شهيد متأثر باصابته.\n▪️ 1 إصابة." + TAIL)
    assert r.tiers["daily"] == {"deaths": 1, "injuries": 1}
    r = parse(HEAD + "- 3 شهداء جدد\n- 18 إصابة" + TAIL)
    assert r.tiers["daily"] == {"deaths": 3, "injuries": 18}
    r = parse(HEAD + "5 شهداء(4 شهداء جدد+ 1 شهيد متاثر بجراحه) .\n14 إصابة." + TAIL)
    assert r.tiers["daily"] == {"deaths": 5, "injuries": 14}


def test_both_counts_on_one_line_joined_by_and():
    r = parse(HEAD + "• 2 شهداء (منهم شهيد واحد جديد و 1 شهيد انتشال) و 1 إصابة." + TAIL)
    assert r.tiers["daily"]["injuries"] == 1 and r.tiers["daily"]["deaths"] == 2


def test_a_48_hour_block_is_never_a_day():
    r = parse(HEAD.replace("24", "48") + "* عدد الشهداء 6 جديد\n• عدد الإصابات: 37 إصابات." + TAIL)
    assert "daily" not in r.tiers


def test_a_number_inside_a_sentence_is_not_taken():
    r = parse(HEAD + "لا يزال 12 شهيد تحت الركام حسب التقديرات" + TAIL)
    assert "daily" not in r.tiers
