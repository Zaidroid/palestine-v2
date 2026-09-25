"""P2-C.2 — press coverage linked to incidents (ops/press_links.py)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import press_links as P                                              # noqa: E402
from resolve.arabic import normalize                                          # noqa: E402

T0 = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)


def _art(title, lang="ar", hours=3):
    return {"source": "Quds News Network", "lang": lang, "title": title, "url": f"u/{title[:8]}",
            "at": T0 + timedelta(hours=hours),
            "text": normalize(title) if lang == "ar" else title.lower()}


EVENT = {"event_id": 1, "type": "raid", "at": T0, "name_ar": "بدو", "name_en": "Biddu"}


def test_a_named_village_and_its_type_link_the_article():
    out = P.match([EVENT], [_art("ضرب وتنكيل.. الاحتلال يقتحم منازل بدو ويحتجز 50 شابًا")])
    assert out[1][0]["source"] == "Quds News Network"


def test_the_wrong_type_or_the_wrong_day_does_not():
    assert P.match([EVENT], [_art("مستوطنون في بدو")]) == {}             # no raid word
    assert P.match([EVENT], [_art("الاحتلال يقتحم بدو", hours=30)]) == {}  # outside the half day


def test_a_governorate_city_is_too_general_to_link():
    city = {**EVENT, "name_ar": "نابلس", "name_en": "Nablus"}
    art = _art("الاحتلال يقتحم عدة بلدات في محافظة نابلس")
    assert P.match([city], [art]) != {}
    assert P.match([city], [art], stop={"نابلس", "Nablus"}) == {}


def test_english_articles_match_on_the_english_name():
    out = P.match([EVENT], [_art("Israeli forces raid Biddu, detain 53", lang="en")])
    assert 1 in out


def test_a_link_is_never_a_second_witness():
    import inspect
    src = inspect.getsource(P.main)
    assert "independent_sources" not in src and "claim_count" not in src
