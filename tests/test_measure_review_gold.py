"""Gold sets as the contract (P2-A.3) — ops/gold_contract.py and its place in
the weekly ops/measure_review.py.

    ./.venv/bin/python -m pytest tests/test_measure_review_gold.py -q

What must hold:

  the verdict        per version: servable only on a MEASURED score that
                     passes; NOT SERVABLE on a measured score below the gate or
                     on a projection that already fails; unmeasured otherwise.
                     The latest measured round decides — an old pass does not
                     survive a newer fail.
  the gate           the one serving states (serve/quality.py: 0.80 overall,
                     every type with n >= 5 at 0.70); a type under n=5 is not
                     judged either way.
  the MoH gold       the reader is scored on the human-read rows and on
                     reproducing its own gold; a model candidate is AGREEMENT
                     with the reader (F229) and must be exact on every row.
  no gold set        roads (the hook) and every registered organ with no gold
                     are named as such — never given a number.
  reporting only     the review records and prints the verdicts; --only is
                     for looking and never writes a partial week.

Everything runs on temporary files and fakes, except the tests marked "repo
files" (the committed ops/ artifacts, no database) and one read-only live test
that skips where there is no database.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import organ_c                                          # noqa: E402
from ops import gold_contract as gc                                   # noqa: E402
from ops import measure_review as mr                                  # noqa: E402

GATE = {"overall": 0.80, "per_type": 0.70, "min_n": 5}

BULLETIN = """
🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة
⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية:
- 5 شهداء (4 شهداء جدد، 1 شهيد متأثر بإصابته).
- 25 إصابة
🔴*منذ وقف إطلاق النار (11 أكتوبر 2025 حتى اليوم):*
- إجمالي الشهداء: 1,399 شهيد
- إجمالي الإصابات: 4,863 إصابة
- إجمالي حالات الانتشال: 834 شهيد
🔴*الحصيلة التراكمية منذ بداية العدوان:*
- إجمالي الشهداء: 73,919 شهيد
- إجمالي الإصابات: 174,977 إصابة
وزارة الصحة
22 سبتمبر 2026
"""


# ── the gate and the verdict ─────────────────────────────────────────────────

def test_the_gate_is_the_one_serving_states():
    from serve.quality import GATE_OVERALL, GATE_TYPE
    g = gc.incident_gate()
    assert (g["overall"], g["per_type"]) == (GATE_OVERALL, GATE_TYPE) == (0.80, 0.70)


def test_a_type_below_its_floor_fails_and_a_tiny_type_is_not_judged():
    ok, why, weakest = gc.judge_incidents(0.85, {"raid": (0.9, 15), "siege": (0.4, 3)}, GATE)
    assert ok and weakest == {"type": "raid", "score": 0.9, "n": 15}
    ok, why, _ = gc.judge_incidents(0.85, {"raid": (0.9, 15), "death": (0.6, 15)}, GATE)
    assert not ok and "death 0.6" in why
    ok, why, _ = gc.judge_incidents(0.79, {}, GATE)
    assert not ok and "overall 0.79 < 0.8" in why


def _s(basis, score, passes, at=None, rnd="8", why=""):
    return {"basis": basis, "score": score, "passes_gate": passes, "at": at,
            "round": rnd, "n": 100, "why": why, "weakest": None}


def test_the_latest_measured_round_decides_and_an_old_pass_does_not_survive():
    scores = [_s("measured", 0.897, True, "2026-08-04"),
              _s("measured", 0.717, False, "2026-09-21", why="overall 0.717 < 0.8")]
    servable, verdict = gc.decide(scores)
    assert servable is False and "0.717" in verdict


def test_a_passing_projection_is_still_unmeasured_and_a_failing_one_is_not_servable():
    assert gc.decide([_s("projection", 0.877, True)])[0] is None
    s, v = gc.decide([_s("projection", 0.877, True),
                      _s("projection", 0.826, False, rnd="7", why="below 0.7: demolition 0.636")])
    assert s is False and "round 7" in v and "demolition" in v
    assert gc.decide([_s("measured", 0.85, True, "2026-10-01"), _s("projection", 0.6, False)])[0] is True
    assert gc.decide([]) == (None, "no gold score for this version")


# ── incidents, on a temporary ops/ ───────────────────────────────────────────

def _write(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False))


def test_every_incident_version_gets_its_scores_and_one_verdict(tmp_path):
    ops = tmp_path
    (ops / "incident-rounds.ndjson").write_text("\n".join(json.dumps(r) for r in [
        {"scored_at": "2026-08-04T06:00:00+00:00", "classifier_version": "9.0",
         "overall": {"n": 68, "precision": 0.897}},
        {"scored_at": "2026-09-21T22:00:00+00:00", "classifier_version": "9.0",
         "overall": {"n": 180, "precision": 0.85}},
    ]) + "\n")
    # the 09-21 round's per-type file: overall passes, one real type fails
    _write(ops / "incident-precision-round7.json", {
        "measured_at": "2026-09-21T22:00:00+00:00",
        "per_type": {"raid": {"n": 15, "precision": 0.93}, "death": {"n": 15, "precision": 0.6},
                     "siege": {"n": 3, "precision": 0.33}}})
    # a recorded projection for a version that no longer serves
    _write(ops / "incident-precision-round7-rescored-9.1.json", {
        "round": "7", "classifier_version": "9.1", "projected_precision": 0.84,
        "tally": {"kept_right": 84, "kept_wrong": 16},
        "per_type": {"raid": {"tally": {"kept_right": 14, "kept_wrong": 1}, "projected_precision": 0.933}}})
    # two projectable rounds for the serving version
    for n in ("7", "8"):
        (ops / f"incident-sample-round{n}.ndjson").write_text("")
        (ops / f"incident-scored-round{n}.ndjson").write_text("")
    projected = []

    def project(n):
        projected.append(n)
        return {"round": n, "projected_precision": 0.9 if n == "8" else 0.82,
                "tally": {"kept_right": 90, "kept_wrong": 10, "type_moved": 2},
                "per_type": {"raid": {"tally": {"kept_right": 18, "kept_wrong": 2},
                                      "projected_precision": 0.9}}}

    out = {e["version"]: e for e in gc.incidents(ops=ops, serving="9.2", project=project)}
    assert projected == ["8", "7"]
    assert list(out) == ["9.2", "9.1", "9.0"]
    assert out["9.2"]["serving"] is True and out["9.2"]["servable"] is None
    assert [s["basis"] for s in out["9.2"]["scores"]] == ["projection", "projection"]
    assert out["9.2"]["scores"][0]["type_moved_unjudged"] == 2
    assert out["9.1"]["servable"] is None and out["9.1"]["scores"][0]["basis"] == "projection (recorded)"
    # 9.0: passed on 08-04, failed per type on 09-21 — the newer round decides
    assert out["9.0"]["servable"] is False
    assert "death 0.6" in out["9.0"]["verdict"] and "siege" not in out["9.0"]["verdict"]
    assert out["9.0"]["scores"][-1]["round"] == "7"


# ── moh ─────────────────────────────────────────────────────────────────────

POSTED = datetime(2026, 9, 22, 8, 39, tzinfo=timezone.utc)


def _moh_gold(tmp_path: Path, n: int = 3) -> tuple[Path, dict]:
    """A gold file built the way analyst/gold_moh.py builds it: the reader's
    own output, `read` on the first two rows."""
    texts, lines = {}, []
    for i in range(n):
        cid = 900 + i
        texts[cid] = (BULLETIN, POSTED)
        reading = organ_c.read(BULLETIN, POSTED)
        lines.append(json.dumps({"claim_id": cid, "reader": reading, "settled": reading,
                                 "label_method": "read" if i < 2 else "arithmetic"},
                                ensure_ascii=False))
    path = tmp_path / "moh_c.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, texts


def test_the_reader_is_unmeasured_until_f229s_hundred_rows_are_read(tmp_path):
    gold, texts = _moh_gold(tmp_path)
    reader = gc.moh(gold_path=gold, texts=texts, ops=tmp_path)[0]
    assert reader["version"] == organ_c.VERSION and reader["serving"] is False
    assert reader["servable"] is None
    assert "human-read on 2 of the 100" in reader["verdict"]
    human, reproduces = reader["scores"]
    assert (human["exact"], human["n"], reproduces["exact"], reproduces["n"]) == (2, 2, 3, 3)


def test_the_reader_is_servable_once_enough_rows_are_read_and_all_are_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "MOH_MIN_HUMAN_ROWS", 2)
    gold, texts = _moh_gold(tmp_path)
    assert gc.moh(gold_path=gold, texts=texts, ops=tmp_path)[0]["servable"] is True


def test_a_reader_that_no_longer_reproduces_its_gold_is_not_servable(tmp_path):
    gold, texts = _moh_gold(tmp_path)
    texts[902] = (BULLETIN.replace("73,919", "73,991"), POSTED)
    reader = gc.moh(gold_path=gold, texts=texts, ops=tmp_path)[0]
    assert reader["servable"] is False and "no longer reproduces 1 of its 3" in reader["verdict"]
    assert reader["scores"][1]["drifted"] == [902]


def test_without_the_database_the_reader_is_unscored_not_scored(tmp_path):
    gold, _ = _moh_gold(tmp_path)
    reader = gc.moh(gold_path=gold, ops=tmp_path, load_texts=lambda ids: None)[0]
    assert reader["servable"] is None and reader["scores"] == []
    assert "unscored" in reader["verdict"]


def test_a_model_candidate_is_agreement_and_must_be_exact_on_every_row(tmp_path):
    gold, texts = _moh_gold(tmp_path)
    truth = organ_c.read(BULLETIN, POSTED)
    wrong = {**truth, "last_24h_killed": 24}              # the header's own 24, read as the toll
    _write(tmp_path / "organ-c-scores.json", {
        "started_at": "2026-09-23T06:46:46+00:00",
        "status": {"good": "complete", "bad": "complete"},
        "rows": {"good": [{"claim_id": c, "answer": truth} for c in (900, 901, 902)],
                 "bad": [{"claim_id": 900, "answer": truth}, {"claim_id": 901, "answer": wrong},
                         {"claim_id": 902, "error": "HTTP 503"}]}})
    # the derived -rescored file is the same answers: never counted twice
    _write(tmp_path / "organ-c-scores-rescored.json", {"rows": {"good": []}})
    entries = {e["version"]: e for e in gc.moh(gold_path=gold, texts=texts, ops=tmp_path)[1:]}
    assert set(entries) == {"good", "bad"}
    assert entries["good"]["servable"] is None               # exact, but 2 human rows of 100
    assert entries["bad"]["servable"] is False
    assert "1 of 2 gold rows" in entries["bad"]["verdict"]
    assert entries["bad"]["scores"][0]["basis"].startswith("agreement with the reader")


# ── no gold set ──────────────────────────────────────────────────────────────

def test_roads_without_a_gold_file_says_so_and_gives_no_number(tmp_path):
    [e] = gc.roads(path=tmp_path / "roads.jsonl")
    assert e["verdict"] == "no gold set" and e["servable"] is None and e["scores"] == []


def test_the_roads_hook_reports_a_present_gold_set_and_calls_a_wired_scorer(tmp_path, monkeypatch):
    path = tmp_path / "roads.jsonl"
    path.write_text('{"id": 1}\n{"id": 2}\n')
    # the unwired branch, stated explicitly since P1-A.5 wired a real scorer
    monkeypatch.setitem(gc.SCORERS, "roads", None)
    [e] = gc.roads(path=path)
    assert e["servable"] is None and "gold set present (2 rows); no scorer" in e["verdict"]
    seen = []
    monkeypatch.setitem(gc.SCORERS, "roads", lambda rows: seen.append(len(rows)) or
                        [{"subject": "roads", "version": "d/1", "servable": False,
                          "verdict": "0.5 < 0.9", "scores": []}])
    assert gc.roads(path=path)[0]["version"] == "d/1" and seen == [2]


def test_every_registered_organ_without_gold_is_named():
    names = [e["subject"] for e in gc.organs_without_gold({"moh"})]
    assert names == ["organ:lang"]


# ── the whole contract, and the review ───────────────────────────────────────

def test_one_failing_subject_never_silences_the_others(monkeypatch):
    monkeypatch.setattr(gc, "incidents", lambda **kw: (_ for _ in ()).throw(OSError("no ops dir")))
    monkeypatch.setattr(gc, "moh", lambda **kw: [{"subject": "moh", "version": "c/2",
                                                   "servable": False, "verdict": "wrong", "scores": []}])
    rec = gc.contract()
    subjects = [e["subject"] for e in rec["entries"]]
    assert subjects[0] == "incidents" and "scoring failed" in rec["entries"][0]["verdict"]
    assert "moh" in subjects and "roads" in subjects
    assert rec["not_servable"] == ["moh c/2: wrong"]


def test_the_weekly_review_runs_the_contract_and_prints_not_servable(monkeypatch, tmp_path, capsys):
    assert mr.review_gold_contract in mr.REVIEWERS
    fake = {"measured_at": "2026-09-25T22:00:00+00:00", "serving": [],
            "entries": [{"subject": "incidents", "version": "1.8.0", "serving": False,
                         "servable": False, "verdict": "round 8 measured 0.767", "scores": []}],
            "not_servable": ["incidents 1.8.0: round 8 measured 0.767"]}
    monkeypatch.setattr(gc, "contract", lambda: fake)
    monkeypatch.setattr(mr, "LEDGER", tmp_path / "ledger.ndjson")
    monkeypatch.setattr(sys, "argv", ["measure_review", "--dry", "--only", "gold_contract"])
    assert mr.main() == 0
    out = capsys.readouterr().out
    assert '"feed": "gold_contract"' in out and "NOT SERVABLE" in out and "0.767" in out
    assert not (tmp_path / "ledger.ndjson").exists()


def test_only_is_for_looking_and_never_writes_a_partial_week(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["measure_review", "--only", "gold_contract"])
    with pytest.raises(SystemExit) as e:
        mr.main()
    assert e.value.code == 2


# ── repo files (the committed ops/ artifacts; no database) ───────────────────

def test_repo_files_round_8_keeps_1_8_0_not_servable_at_0_767():
    out = {e["version"]: e for e in gc.incidents()}
    e = out["1.8.0"]
    assert e["servable"] is False
    measured = [s for s in e["scores"] if s["basis"] == "measured"]
    assert measured[-1]["score"] == 0.767 and measured[-1]["round"] == "8"
    from ingest.sources.news_incidents import CLASSIFIER_VERSION
    serving = out[CLASSIFIER_VERSION]
    assert serving["serving"] is True
    live = [s for s in serving["scores"] if s["basis"] == "projection"]
    assert len(live) == gc.PROJECT_OVER


def test_repo_files_the_f11_night_engine_is_196_of_199_agreement_not_precision():
    models = [e for e in gc.moh(load_texts=lambda ids: None)[1:]
              if e["version"] == "engine" and "night" in e["run"]]
    [night] = models
    agreement = night["scores"][0]
    assert (agreement["exact"], agreement["n"]) == (196, 199)
    assert "F229" in agreement["basis"] and night["servable"] is False


# ── production, read only ────────────────────────────────────────────────────

def test_live_the_reader_reproduces_its_gold_and_is_human_read_on_twenty():
    texts = gc.load_moh_texts([json.loads(line)["claim_id"] for line in
                               gc.MOH_GOLD.read_text(encoding="utf-8").splitlines()])
    if not texts:
        pytest.skip("no database here")
    reader = gc.moh(texts=texts)[0]
    human, reproduces = reader["scores"]
    assert (human["exact"], human["n"]) == (20, 20)
    assert reproduces["exact"] == reproduces["n"] == 201
    assert reader["servable"] is None
