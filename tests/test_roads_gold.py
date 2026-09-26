"""P1-A.5 — the roads gold set's scorer and draw (learn/roads_gold.py)."""
from __future__ import annotations

from learn import roads_gold as rg


def _gold(gid, readings, report=True):
    return {"gold_id": gid, "is_road_report": report, "readings": readings}


def _r(key, direction, value, kind="flow"):
    return {"name": key, "canonical_key": key, "direction": direction,
            "kind": kind, "value": value}


def _v1(key, direction, status):
    return {"canonical_key": key, "status": status, "direction": direction}


def test_score_counts_readings_and_normalises_blank_direction():
    sample = [{"gold_id": "a:1", "v1": [_v1("قلنديا", "both", "congested"),
                                         _v1("جبع", "both", "open")]},
              {"gold_id": "a:2", "v1": []}]
    gold = [_gold("a:1", [_r("قلنديا", "both", "congested"),
                          _r("جبع", "both", "congested"),
                          {"name": "بوابة حزما", "canonical_key": None,
                           "direction": "both", "kind": "flow", "value": "open"}]),
            _gold("a:2", [_r("عطارة", "inbound", "closed")])]
    s = rg.score(gold, sample)
    assert s["counts"] == {"tp": 1, "fp": 1, "fn": 2}
    assert s["reading_precision"] == 0.5
    assert s["checkpoint_recall"] == round(2 / 3, 3)      # قلنديا, جبع found; عطارة not
    assert s["value_agreement_when_found"] == 0.5         # جبع: open vs congested
    assert s["gold_readings_unregistered"] == 1
    assert s["messages_with_readings_v1_missed"] == 1
    assert s["is_road_report_agreement"] == 0.5


def test_a_non_report_v1_left_alone_agrees():
    s = rg.score([_gold("a:3", [], report=False)], [{"gold_id": "a:3", "v1": []}])
    assert s["is_road_report_agreement"] == 1.0 and s["counts"]["fp"] == 0


def test_draw_respects_the_strata_and_is_deterministic():
    msgs = []
    for ch, n in (("big", 400), ("small", 6)):
        for i in range(n):
            parsed = i % 2 == 0
            msgs.append({"channel": ch, "msg_id": i, "date": None, "text": "x" * 5,
                         "v1": [_v1("k", "both", "open")] if parsed else [],
                         "v1_source_type": "admin" if parsed and i % 50 == 0 else "crowd"})
    a = rg.draw(40, 20, msgs)
    b = rg.draw(40, 20, msgs)
    assert [r["gold_id"] for r in a] == [r["gold_id"] for r in b]
    strata = [r["stratum"] for r in a]
    assert strata.count("unparsed") == 20
    assert strata.count("parsed:admin") + strata.count("parsed:crowd") == 40
    assert strata.count("parsed:admin") <= rg.ADMIN_CAP
    assert any(r["channel"] == "small" for r in a if r["stratum"] == "unparsed")


def test_the_contract_has_a_scorer_for_roads():
    from ops import gold_contract
    assert gold_contract.SCORERS["roads"] is not None
