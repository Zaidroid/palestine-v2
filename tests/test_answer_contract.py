"""P0-A.2 — the answer contract, enforced (audit F155/F245/F379: the ledger
said this existed). Every public tool over a fixed input set, through the HTTP
dispatcher (the only path that attaches answer_en): the answer names its
subject, carries a datum or one of the three refusal words, states an age when
the payload has one, names the gap when a route is blind, and the two
languages carry the same numbers. Shape, not values — the tools call the live
API, so this runs on main-server with PALESTINE_API pointing at a dev API."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from serve.mcp_facades import LISTED                                        # noqa: E402

INPUTS = {
    "about": {}, "checkpoint_status": {"name": "حوارة"},
    "checkpoints": {"place": "نابلس", "limit": 3},
    "can_i_travel": {"origin": "رام الله", "destination": "نابلس"},
    "incidents": {"place": "نابلس", "hours": 168, "limit": 3},
    "place": {"place": "نابلس"}, "insights": {"place": "نابلس", "days": 7},
    "news": {"limit": 3}, "weather_now": {}, "connectivity_now": {},
    "fuel_prices": {}, "crossings": {},
    "databank": {"category": "demolitions", "limit": 3},
    "series": {"indicators": "casualties.annual_total"},
    "correlate": {"search": "price"}, "licence": {},
}
REFUSAL = re.compile(r"unknown|no source|refused|no recent|not|cannot|"
                     r"غير معروف|ما في|لا مصدر|ما عرفت|لا يمكن|ما قدرت|ما بقدر|بلا|لا سجلات|ما لقيت")
AGE_AR = re.compile(r"قبل |الآن|بتاريخ|يوم|ساعة|دقيقة|دقايق|ساعات|أيام")
AGE_EN = re.compile(r"\bago\b|now\b|\d{4}-\d{2}|today|yesterday|days?\b|hours?\b|min\b")
NUM = re.compile(r"(?<![\d.])\d{2,}(?![\d.])")
# a categorical VALUE is a datum too: 'normal', 'open', 'cut' — no number needed
VALUE = re.compile(r"normal|open|closed|congested|slow|passable|cut|active|"
                   r"شغال|طبيعي|سالك|مغلق|مسكّر|مفتوح|ازمة|أزمة|مقطوع|فيه")


def _nums(text: str) -> set[str]:
    return set(NUM.findall(text or ""))


@pytest.mark.parametrize("tool", [t for t in LISTED if t in INPUTS])
def test_every_public_answer_keeps_the_contract(tool, mcp_call, mcp_payload):
    reply = mcp_call(tool, **INPUTS[tool])
    assert "error" not in reply and not reply["result"].get("isError"), reply
    p = mcp_payload(reply)
    assert "error" not in p, p
    ar, en = p.get("answer") or "", p.get("answer_en") or ""
    assert ar.strip() and en.strip(), (tool, ar, en)
    assert not re.search(r"\bNone\b|\bnan\b|undefined", ar + en), (tool, ar, en)
    # (b) a datum, or one of the refusal words — never an empty confident sentence
    assert re.search(r"\d", ar) or REFUSAL.search(ar) or VALUE.search(ar), (tool, ar)
    assert re.search(r"\d", en) or REFUSAL.search(en) or VALUE.search(en), (tool, en)
    # (a) the subject: a place the caller named is named back (or its resolution)
    place = INPUTS[tool].get("place") or INPUTS[tool].get("name")
    if place:
        names = {place, p.get("name"), p.get("resolved_to"), (p.get("match") or {}).get("resolved_to"),
                 (p.get("place") or {}).get("name") if isinstance(p.get("place"), dict) else None}
        names = {n for n in names if n}
        assert any(n in ar or n in en for n in names), (tool, names, ar)
    # (c) an age is spoken when the payload carries one
    if p.get("age_minutes") is not None or p.get("newest_at") or p.get("freshest_reading_minutes") is not None:
        assert AGE_AR.search(ar), (tool, ar)
        assert AGE_EN.search(en), (tool, en)
    # (d) a blind route says so in the sentence
    cov = (p.get("coverage") or {}).get("coverage_fraction")
    if tool == "can_i_travel" and cov is not None and cov < 0.6:
        assert p.get("verdict") != "open" and ("بلا" in ar or "ما بقدر" in ar), (ar, cov)
        assert "unverified" in en.lower() or "cannot confirm" in en.lower() or "no tracked" in en.lower(), en
    # (e) parity: the numbers the English sentence states exist in the Arabic one or the payload
    body = json.dumps(p, ensure_ascii=False)
    missing = {n for n in _nums(en) if n not in ar and n not in body}
    assert not missing, (tool, missing, ar, en)
