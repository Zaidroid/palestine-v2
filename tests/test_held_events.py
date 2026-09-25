"""P1-B.1 — the held conflict events are served (migration 083).

The Nakba depopulation record, UCDP's events and the journalists sat in the
event table with no route to them. Measured before serving: the same file had
been imported twice (574 locality and 74 UCDP copies), and the localities'
"displaced" figure is each one's TOTAL 1945 population. The pure tests run
anywhere; the live ones skip until 083 is applied.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.backfill_conflict_names import enrich                              # noqa: E402
from serve import mcp_en as EN                                               # noqa: E402
from serve import mcp_server as S                                            # noqa: E402

MIGRATION = "083_serve_held_conflict_events.sql"


# ── the backfill ────────────────────────────────────────────────────────────
def test_a_village_gets_its_name_district_and_point():
    raw = {"location": {"name": "Ayn Hawd", "lat": 32.70, "lon": 34.98},
           "description": "Ayn Hawd (Haifa district) — Palestinian village depopulated during the 1948 Nakba"}
    out = enrich(raw, "v1_conflict_palopenmaps")
    assert out["name"] == "Ayn Hawd" and out["district_1945"] == "Haifa"
    assert out["raw_lat"] == 32.70 and out["enriched_by"].startswith("P1-B.1")


def test_a_journalist_gets_a_name_and_a_placeholder_flag():
    raw = {"location": {"name": "Gaza"},
           "description": "Journalist killed: عصام بهار (Essam Bhar). Bhar, a journalist for the Al-Aqsa TV"}
    out = enrich(raw, "v1_conflict_tech4palestine")
    assert out["name"] == "عصام بهار (Essam Bhar)" and out["date_is_placeholder"] is True


# ── the answers ─────────────────────────────────────────────────────────────
def _register(district=None):
    return {"category": "displacement", "district": district,
            "district_1945_key": "Ramle" if district else None,
            "event_summary": [{"indicator": "displacement.locality_depopulated", "events": 70,
                               "value_sum": 99999, "first": "1948-04-01", "last": "1948-12-01",
                               "undated": False}],
            "by": {"locality_group": [{"name": "Palestinian", "localities": 65},
                                      {"name": "Mixed", "localities": 5}],
                   "district_1945": [{"name": "Lydda", "localities": 98}],
                   "subdistrict_1945": [{"name": "Ramle", "localities": 70}]},
            "items": [{"value_text": "al-Mansura", "attrs": {"name_ar": "المنصورة"}},
                      {"value_text": "al-Mansura", "attrs": {"name_ar": "المنصورة"}},
                      {"value_text": "Qula", "attrs": {}}]}


def test_the_register_is_counted_never_summed():
    ar = S._displacement_answer_ar(_register(), None)
    en = EN._displacement_en(_register())
    assert "70 تجمّع هُجّر سنة 1948" in ar and "65 فلسطيني، 5 مختلط" in ar
    assert "70 localities depopulated in 1948" in en and "65 Palestinian, 5 Mixed" in en
    assert "99,999" not in ar and "99,999" not in en          # the populations are never added
    assert "مش عدد اللاجئين" in ar and "not a refugee count" in en


def test_a_district_lists_its_localities_once_each():
    ar = S._displacement_answer_ar(_register("الرملة"), "الرملة")
    en = EN._displacement_en(_register("الرملة"))
    assert "بقضاء/لواء الرملة" in ar and ar.count("المنصورة") == 1 and "Qula" in ar
    assert "in the Ramle district/subdistrict" in en and en.count("al-Mansura") == 1


def test_district_names_map_from_arabic():
    from serve.app import _district_1945
    assert _district_1945("الرملة") == "Ramle" and _district_1945("قضاء صفد") == "Safad"
    assert _district_1945("Ramla") == "Ramle" and _district_1945("Haifa") == "Haifa"


def test_the_event_note_names_registers_only():
    d = {"event_summary": [
        {"indicator": "conflict.deaths.state_based", "events": 7071, "value_sum": 55490,
         "first": "1989-05-03", "last": "2024-12-31", "undated": False},
        {"indicator": "conflict.journalists_killed", "events": 262, "value_sum": 262,
         "first": "2023-10-07", "last": "2023-10-07", "undated": True}]}
    ar, en = S._event_note_ar(d), EN._event_note_en(d)
    assert "7,071" in ar and "55,490" in ar and "بلا تواريخ" in ar
    assert "262 journalists killed" in en and "262 deaths" not in en and "2023–2023" not in en


# ── live, after 083 ─────────────────────────────────────────────────────────
def _applied() -> bool:
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (MIGRATION,))
        return cur.fetchone() is not None


def test_the_held_record_is_served_once(mcp_call, mcp_payload):
    if not _applied():
        pytest.skip(f"{MIGRATION} not applied")
    from resolve.db import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT indicator, count(*) FROM databank_event_rows GROUP BY 1""")
        n = dict(cur.fetchall())
        cur.execute("""SELECT count(*) FROM event WHERE attrs ? 'superseded_083' AND status = 'believed'""")
        assert cur.fetchone()[0] == 0
        cur.execute("""SELECT count(*) FROM v_tier_commercial_permissive WHERE dataset_key = 'v1_conflict_ucdp'""")
        assert cur.fetchone()[0] == 0                               # G5.11: unread terms, not sold
    assert n["displacement.locality_depopulated"] == 589
    assert sum(v for k, v in n.items() if k.startswith("conflict.deaths.")) == 7638
    assert n["conflict.journalists_killed"] == 262
    p = mcp_payload(mcp_call("databank", district="الرملة"))
    assert p["category"] == "displacement" and "الرملة" in p["answer"] and "Ramle" in p["answer_en"]
