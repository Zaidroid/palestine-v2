"""MCP answers, rendered offline from REST-shaped payloads (audit 2026-09-25, plan 04-renderers).

The spoken `answer` (Arabic) and `answer_en` are read aloud to someone deciding
which road to take. These pin what each must say, with `api()` replaced by a
fixture so no API or database is needed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from serve import mcp_en, mcp_server  # noqa: E402

AGE_AR = re.compile(r"قبل \d+ (دقيقة|ساعة|يوم)")
AGE_EN = re.compile(r"\d+(\s?min|h|d) ago")


def _status_payload(inb, outb, top="closed", age=9):
    return {"found": True, "query": "حوارة", "match": {"resolved_to": "حوارة", "score": 1.0},
            "flow": top, "passable": top != "closed", "last_known_flow": top,
            "age_minutes": age, "present": [], "by_direction": {
                "inbound": {"flow": inb[0], "passable": None, "age_minutes": inb[1], "present": []},
                "outbound": {"flow": outb[0], "passable": None, "age_minutes": outb[1], "present": []}}}


def _status(monkeypatch, payload):
    monkeypatch.setattr(mcp_server, "api", lambda *a, **k: payload)
    out = mcp_server.checkpoint_status("حوارة")
    return out["answer"], mcp_en.checkpoint_status(out)


def test_r_01_direction_split_carries_each_age(monkeypatch):
    """F044/F035/F050 — 'سالك للداخل، ومغلق للخارج' with no age in either language."""
    ar, en = _status(monkeypatch, _status_payload(("open", 3), ("closed", 180)))
    assert "للداخل" in ar and "للخارج" in ar and len(AGE_AR.findall(ar)) >= 2, ar
    assert "inbound" in en and "outbound" in en and len(AGE_EN.findall(en)) >= 2, en


def test_r_02_a_fresh_closure_is_not_hidden_behind_an_unknown_direction(monkeypatch):
    """F009 (critical) — inbound closed 9 minutes ago, outbound unknown: the split
    only fired when BOTH were known, so the answer spoke the decayed row instead."""
    ar, en = _status(monkeypatch, _status_payload(("closed", 9), ("unknown", None), top="unknown"))
    assert "مغلق" in ar and "للداخل" in ar and AGE_AR.search(ar), ar
    assert "closed inbound" in en and AGE_EN.search(en), en


def test_r_03_known_checkpoint_never_read_is_not_an_unknown_name(monkeypatch):
    """F049 — 'ما عرفت حاجز اسمه …' for a checkpoint the registry knows but nobody reported."""
    payload = {"found": False, "query": "بيت فوريك", "resolved_to": "بيت فوريك",
               "reason": "no checkpoint reading has ever been recorded here"}
    ar, en = _status(monkeypatch, payload)
    assert "ما عرفت" not in ar and "بيت فوريك" in ar and "تقرير" in ar, ar
    assert "No checkpoint found" not in en and "never" in en, en


def test_r_04_english_never_says_none_for_an_unresolved_place():
    """F045/F046 — 'No recent checkpoint reports around None' / 'in the last None hours'."""
    err = {"answer": "ما عرفت وين زززز.", "error": "place not resolved"}
    for fn in (mcp_en.checkpoints_near, mcp_en.incidents_near):
        out = fn(err)
        assert "None" not in out and "not recognised" in out, (fn.__name__, out)


def _near_payload(rows, in_radius=None):
    return {"results": rows, "counts": {"in_radius": len(rows) if in_radius is None else in_radius,
                                        "unknown": 0}, "attribution": "t"}


def test_r_05_checkpoints_near_says_each_age(monkeypatch):
    """F052 — flows listed with no age."""
    rows = [{"name": "زعتره", "flow": "open", "passable": True, "age_minutes": 12, "present": []},
            {"name": "حوارة", "flow": "closed", "passable": False, "age_minutes": 95, "present": []}]
    monkeypatch.setattr(mcp_server, "api", lambda *a, **k: _near_payload(rows))
    out = mcp_server.checkpoints_near(lat=32.2, lon=35.2)
    assert len(AGE_AR.findall(out["answer"])) >= 2, out["answer"]
    assert len(AGE_EN.findall(mcp_en.checkpoints_near(out))) >= 2


def test_r_06_no_checkpoint_in_range_is_not_old_news(monkeypatch):
    """F052 — '0 checkpoints in the area but their news is old'."""
    monkeypatch.setattr(mcp_server, "api", lambda *a, **k: _near_payload([], 0))
    out = mcp_server.checkpoints_near(lat=32.2, lon=35.2, radius_km=5)
    assert "قديمة" not in out["answer"] and "5" in out["answer"], out["answer"]
    assert "old" not in mcp_en.checkpoints_near(out)


def test_r_07_village_ambiguous_is_not_spoken_as_the_city(monkeypatch):
    """F053 — an event whose village is ambiguous was placed 'in' the governorate city."""
    item = {"type": "raid", "place": "رام الله", "place_en": "Ramallah",
            "place_precision": "village_ambiguous", "named_place": "المزرعة",
            "occurred_at": "2026-09-25T06:00:00+00:00", "independent_sources": 1}
    payload = {"incidents": [item], "by_type": {"raid": 1}, "attribution": "t"}
    monkeypatch.setattr(mcp_server, "api", lambda *a, **k: payload)
    out = mcp_server.incidents_near(lat=31.9, lon=35.2, hours=24)
    assert "محافظة رام الله" in out["answer"] and "في رام الله " not in out["answer"], out["answer"]
    en = mcp_en.incidents_near(out)
    assert "governorate" in en and "in Ramallah " not in en, en


def test_r_08_crossings_decayed_is_not_no_source(monkeypatch):
    """F055 — every sourced crossing had merely decayed and the answer said
    'no source reports crossings at all'."""
    items = [{"name": "جسر الملك حسين", "name_en": "Allenby", "value": "unknown",
              "last_known_value": "open", "age_minutes": 840, "basis": "checkpoint_flow"},
             {"name": "رفح", "name_en": "Rafah", "value": None, "basis": None}]
    monkeypatch.setattr(mcp_server, "api", lambda *a, **k: {"crossings": items})
    out = mcp_server.crossings()
    assert "ما عندي ولا مصدر" not in out["answer"] and "جسر الملك حسين" in out["answer"], out["answer"]
    assert out.get("no_source") is not True
    en = mcp_en.crossings(out)
    assert not en.startswith("Every crossing") and "Allenby" in en and "Rafah" in en, en


class _Api:
    """A fake api() that answers by path and records what it was asked."""

    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, path, **p):
        self.calls.append((path, p))
        if path in self.fail:
            raise RuntimeError("boom")
        if path == "/v2/geo/resolve":
            if p.get("state_kind"):
                return {"found": True, "name": "حوارة", "place_id": 2, "kind": "checkpoint",
                        "lat": 32.15, "lon": 35.25}
            return {"found": True, "name": "حوارة", "place_id": 1, "kind": "locality",
                    "lat": 32.15, "lon": 35.25}
        if path == "/v2/checkpoints/status":
            return {"found": True, "match": {"resolved_to": p.get("name"), "score": 1.0},
                    "flow": "closed", "age_minutes": 20, "present": []}
        if path == "/v2/incidents/recent":
            return {"incidents": [{"type": "raid"}]}
        return {"series": []}


def test_r_09_place_profile_window_kind_name_age_and_errors(monkeypatch):
    """F059: hours=days*24 exceeded the REST cap (168) and the 422 was swallowed,
    so incidents never showed for days > 7. F058: the pattern read the legacy
    mixed kind. F010: the live status was fetched by the caller's text, not the
    resolved checkpoint, and spoken with no age. F060: a failed section read as
    'no recent information'."""
    fake = _Api(fail={"/v2/history/place"})
    monkeypatch.setattr(mcp_server, "api", fake)
    out = mcp_server.place_profile("Huwara", days=30)
    inc = [p for path, p in fake.calls if path == "/v2/incidents/recent"][0]
    pat = [p for path, p in fake.calls if path == "/v2/patterns/place"][0]
    st = [p for path, p in fake.calls if path == "/v2/checkpoints/status"][0]
    assert inc["hours"] <= 168
    assert pat["state_kind"] == "checkpoint_flow"
    assert st["name"] == "حوارة"
    assert AGE_AR.search(out["answer"]), out["answer"]
    assert "history" in (out.get("errors") or {}) and "ما قدرت أقرأ" in out["answer"], out["answer"]
    en = mcp_en.place_profile(out)
    assert AGE_EN.search(en) and "could not read" in en.lower(), en
