"""Taqwa's test, 2026-09-26: Ramallah→Nablus answered in 444/549 characters and
said "Huwara open, 3 hours ago" while palhub had reported the Huwara gate open
minutes earlier on a sibling row."""
from __future__ import annotations

from resolve import corridor as C


class _Cur:
    def __init__(self, rows): self.rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): pass
    def fetchall(self): return self.rows


class _Conn:
    def __init__(self, rows): self.rows = rows
    def cursor(self): return _Cur(self.rows)


def _cp(pid, name, age, flow="open", lat=32.178, lon=35.2735):
    c = C.CheckpointOnRoute(pid, name, 0.8, 100, lat, lon, flow=flow)
    c.age_minutes = age
    return c


# place_id, name_ar, name_en, lat, lon, flow, age, sources
SIBLINGS = [(1639, "بوابة حوارة", "Huwara Gate", 32.1595, 35.2545, "open", 9.0, 1),
            (1636, "حوارة زعترة", "Huwara-Za'tara Road", 32.145, 35.249, "open", 190.0, 1),
            (900, "بيتا", "Beita", 32.18, 35.27, "closed", 5.0, 1)]


def test_a_stale_checkpoint_takes_its_fresh_sibling_with_the_siblings_name():
    huwara = _cp(1630, "حوارة", 201.0)
    C._attach_group_readings(_Conn(SIBLINGS), "LINESTRING(0 0,1 1)", [huwara])
    g = huwara.group_reading
    assert g and g["name"] == "بوابة حوارة" and g["age_minutes"] == 9.0
    assert huwara.flow == "open" and huwara.age_minutes == 201.0      # its own reading is kept


def test_a_fresh_checkpoint_keeps_its_own_reading_and_strangers_never_count():
    fresh = _cp(1630, "حوارة", 20.0)
    other = _cp(5, "زعترة", None, flow="unknown")
    C._attach_group_readings(_Conn(SIBLINGS), "LINESTRING(0 0,1 1)", [fresh, other])
    assert fresh.group_reading is None                                  # fresh enough
    assert other.group_reading is None                                  # no shared name (بيتا ≠ زعترة)


def test_a_stale_sibling_is_never_offered():
    road = _cp(7, "حوارة زعترة", None, flow="unknown", lat=32.145, lon=35.249)
    rows = [r for r in SIBLINGS if r[0] == 1636] + [(1636 + 1000, "حوارة", "Huwara", 32.146, 35.25,
                                                     "open", 190.0, 1)]
    C._attach_group_readings(_Conn(rows), "LINESTRING(0 0,1 1)", [road])
    assert road.group_reading is None


def test_generic_words_and_attached_prefixes_do_not_make_siblings():
    assert C._core_tokens("بوابة حوارة") == {"حواره"}
    assert C._core_tokens("من عين سينا لزعترة") == {"سينا", "زعتره"}
    assert not (C._core_tokens("عين سينيا") & C._core_tokens("عين يبرود"))


def test_the_route_answer_is_short_and_names_its_checkpoints(mcp_call, mcp_payload):
    p = mcp_payload(mcp_call("can_i_travel", origin="رام الله", destination="نابلس"))
    assert len(p["answer"]) < 420 and len(p["answer_en"]) < 460, (p["answer"], p["answer_en"])
    assert "يمر عبر" not in p["answer"]                   # the settlement waypoints are gone
    for w in p["spoken"]["on_way"][:2]:
        if w["flow"] != "unknown":
            assert w["name"] in p["answer"]
