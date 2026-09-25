"""Loop A — the properties the crowd engine will rest on.

    ./.venv/bin/python -m pytest tests/test_reliability.py -q

These are not tests of the current 15 Telegram channels. They are tests of the
behaviour P2 needs from this loop when the reporter is a person with a phone,
written now because that behaviour is easy to break by "improving" the formula
later and impossible to notice from the aggregate numbers.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from learn.reliability import PRIOR_A, PRIOR_B, kappa, trust, wilson_lower  # noqa: E402


def mean(hits: int, misses: int) -> float:
    return (hits + PRIOR_A) / (hits + misses + PRIOR_A + PRIOR_B)


# ── reputation is EARNED, never seeded ───────────────────────────────────────

def test_a_perfect_newcomer_is_not_trusted():
    """One correct report is not a track record. This is what stops a fresh
    account — or fifty fresh accounts — from arriving pre-trusted, with no rule
    anywhere that says "new submitters are suspicious"."""
    assert mean(1, 0) > 0.6           # the posterior mean flatters them
    assert wilson_lower(1, 1) < 0.25  # the bound, which is what we use, does not


def test_trust_rises_only_with_evidence():
    """Same 100% accuracy, more evidence — trust must increase monotonically."""
    bounds = [wilson_lower(n, n) for n in (1, 5, 20, 100, 1000)]
    assert bounds == sorted(bounds)
    assert bounds[0] < 0.25 and bounds[-1] > 0.99


def test_a_long_good_record_beats_a_short_perfect_one():
    """90/100 must outrank 1/1, or volume of noise beats demonstrated accuracy
    and the engine rewards spam."""
    assert wilson_lower(90, 100) > wilson_lower(1, 1)


def test_being_contradicted_costs_standing():
    assert wilson_lower(80, 100) < wilson_lower(95, 100)


def test_unmeasured_is_none_not_a_guess():
    """A source nobody has been able to score must not silently become 0.5.
    27 of 42 sources are in this state; they keep their prior behaviour because
    the caller coalesces NULL to 1.0, which is a decision the caller makes
    explicitly rather than one this function makes for it."""
    assert trust(None, None) is None
    assert trust(0.9, 0) is None


# ── raw agreement is not skill ───────────────────────────────────────────────

def test_always_saying_the_common_value_scores_zero_kappa():
    """`open` is ~88% of checkpoint readings. A reporter that says "open" every
    time and understands nothing agrees ~88% of the time, and a raw agreement
    score would call that excellent. Kappa must call it worthless."""
    j = Counter({("open", "open"): 88, ("open", "closed"): 12})
    assert kappa(j) == 0.0


def test_kappa_rewards_actually_tracking_the_state():
    j = Counter({("open", "open"): 88, ("closed", "closed"): 12})
    assert kappa(j) == 1.0


def test_kappa_is_undefined_when_only_one_value_was_ever_seen():
    """Agreement is then guaranteed and carries no information. Returning 1.0
    would mark a reporter that has only ever seen one value as perfect."""
    assert kappa(Counter({("open", "open"): 500})) is None
    assert kappa(Counter()) is None


def test_worse_than_chance_is_negative():
    """A reporter who is systematically out of step should go BELOW zero, not
    bottom out at zero — an inverted reporter is a different problem from an
    uninformative one, and P2 needs to be able to tell them apart."""
    j = Counter({("open", "closed"): 40, ("closed", "open"): 40,
                 ("open", "open"): 10, ("closed", "closed"): 10})
    assert kappa(j) < 0


# ── who a unit is scored against (audit F114 / F487) ────────────────────────

from datetime import datetime, timedelta, timezone             # noqa: E402

import learn.reliability as rel                                 # noqa: E402

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


class _ObsCursor:
    """Stands in for the database in score_kind: OBS_SQL returns these rows."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


def _bucket(i: int, votes: dict[int, str]) -> list[tuple]:
    """One (place, direction, window) bucket: source_id -> value, one unit each."""
    at = T0 + timedelta(hours=i)
    return [(1, "both", at, v, sid, f"src:{sid}") for sid, v in votes.items()]


def test_two_units_that_disagree_are_a_miss_for_both():
    """The commonest bucket here is the copyset plus one other observer. The
    old consensus counted the scored unit's own vote, so 1-1 was a tie and
    nobody was scored: a unit could never be wrong in a two-unit bucket."""
    rows = [r for i in range(10) for r in _bucket(i, {1: "open", 2: "closed"})]
    k = rel.score_kind(_ObsCursor(rows), "k", 30, 1200)
    assert k["per_source"][1] == {"hits": 0, "misses": 10}
    assert k["per_source"][2] == {"hits": 0, "misses": 10}
    assert k["two_unit_buckets"] == 10


def test_a_shadowing_account_cannot_bank_hits_without_risking_misses():
    """The verifier's case: 100 buckets where a reporter disagreed with the
    channels and 50 where it agreed. The old rule scored it 50/0 — Wilson
    0.93 and a trust_weight near 1.0 — for being wrong two times in three."""
    rows = []
    for i in range(150):
        rows += _bucket(i, {1: "open", 9: "closed" if i < 100 else "open"})
    k = rel.score_kind(_ObsCursor(rows), "k", 30, 1200)
    assert k["per_source"][9] == {"hits": 50, "misses": 100}
    assert rel.wilson_lower(50, 150) < 0.5


def test_the_majority_does_not_confirm_itself():
    """Three units, two of them agreeing: the dissenter is outvoted by the two
    others and misses; each of the pair has one ally and one dissenter among
    ITS others, so neither is scored off its own vote."""
    rows = _bucket(0, {1: "open", 2: "open", 3: "closed"})
    k = rel.score_kind(_ObsCursor(rows), "k", 30, 1200)
    assert k["per_source"][3] == {"hits": 0, "misses": 1}
    assert 1 not in k["per_source"] and 2 not in k["per_source"]
    assert k["ties"] == 2

    rows = _bucket(0, {1: "open", 2: "open", 4: "open", 3: "closed"})
    k = rel.score_kind(_ObsCursor(rows), "k", 30, 1200)
    assert k["per_source"][1] == {"hits": 1, "misses": 0}
    assert k["per_source"][3] == {"hits": 0, "misses": 1}


# ── a measured zero is not "unmeasured" (audit F115) ────────────────────────

class _RunConn:
    """Enough of a connection for reliability.run(): canned reads, recorded writes."""

    def __init__(self, kinds, obs, names):
        self.kinds, self.obs, self.names = kinds, obs, names
        self.updates: list[tuple] = []
        self.sql = ""

    # connection
    def cursor(self): return self
    def commit(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False

    # cursor
    def execute(self, sql, params=None):
        self.sql = sql
        if sql.lstrip().startswith("UPDATE source"):
            self.updates.append(params)

    def fetchall(self):
        if self.sql is rel.KINDS_SQL:
            return self.kinds
        if self.sql is rel.OBS_SQL:
            return self.obs
        return self.names


def test_a_reporter_measured_at_zero_is_written_low_and_never_null(monkeypatch, tmp_path):
    """A reporter the consensus contradicted in all 120 buckets has
    wilson_lower(0, 120) = 0.0 and trust_weight 0.0, which the write turned
    into NULL — and belief reads NULL as "unmeasured", 1.0 for a channel. The
    worst reporter was served exactly like the best one."""
    obs = []
    for i in range(120):
        obs += _bucket(i, {1: "open", 2: "open", 4: "open", 3: "closed"})
    names = [(1, "a", ""), (2, "b", ""), (3, "wrong", ""), (4, "d", "")]
    conn = _RunConn([("k", 3600, 4)], obs, names)
    monkeypatch.setattr(rel, "connect", lambda: conn)
    monkeypatch.setattr(rel, "OUT", tmp_path / "reliability.ndjson")
    rel.run(30, write=True)
    written = {p[-1]: p for p in conn.updates}       # source_id -> params
    wrong_weight, good_weight = written[3][3], written[1][3]
    assert wrong_weight is not None, "a measured 0/120 was stored as unmeasured"
    assert 0 < wrong_weight < 0.05 < good_weight
    assert rel.stored_weight(None) is None           # unmeasured stays NULL


# ── a state with one value is not a measurement (audit F116) ────────────────

import learn.state_persistence as sp                            # noqa: E402


class _PairsConn:
    """Enough of a connection for state_persistence.run(): PAIRS_SQL returns
    these (value, gap_seconds, same) rows; nothing is written (no --apply)."""

    def __init__(self, rows):
        self.rows = rows

    def cursor(self): return self
    def commit(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): pass
    def fetchall(self): return self.rows


def _persisting(value: str, n_per_bucket: int = 80, same_every: int = 1) -> list[tuple]:
    """Pairs spread over five buckets; `same` is 0 on every `same_every`-th."""
    rows = []
    for gap in (100, 400, 900, 1500, 3000):
        for i in range(n_per_bucket):
            same = 0 if same_every > 1 and i % same_every == 0 else 1
            rows.append((value, gap, same))
    return rows


def test_a_single_valued_state_is_refused_not_fitted(monkeypatch):
    """`checkpoint_police` has 'present' and 18 absence pairs. Every pair of a
    one-valued state is X -> X, so p_same is 1.0 at every age and the fit
    says 'present' persists — which served it at 0.85 up to the cap once
    already (025:259-263). One `--kinds` flag re-applied it with no refusal."""
    rows = _persisting("present") + [("absent", 600, 0)] * 18
    monkeypatch.setattr(sp, "connect", lambda: _PairsConn(rows))
    results = {r["value"]: r for r in sp.run("checkpoint_police", apply_changes=False)}
    assert results["present"]["fitted"] is False
    assert "single-valued" in results["present"]["reason"]


def test_a_state_with_two_measured_values_is_still_fitted(monkeypatch):
    rows = _persisting("open", same_every=9) + _persisting("closed", same_every=3)
    monkeypatch.setattr(sp, "connect", lambda: _PairsConn(rows))
    results = {r["value"]: r for r in sp.run("checkpoint_flow", apply_changes=False)}
    assert results["open"]["fitted"] and results["closed"]["fitted"]


# ── the learning loop's writes, against the real tables ─────────────────────
#
# Everything above is pure. What follows runs the SQL the nightly job runs,
# inside a transaction that is always rolled back (the tests/test_crowd.py
# pattern), because the thing under test is what the job WRITES. A checkout
# with no database skips these rather than failing: they need the schema.

import psycopg                                                    # noqa: E402
import pytest                                                     # noqa: E402

from learn import source_independence as si                       # noqa: E402
from resolve.db import dsn                                        # noqa: E402

SI_KIND = "_t_si_kind"


@pytest.fixture()
def db():
    """A transaction that is always rolled back. Never commits."""
    try:
        conn = psycopg.connect(dsn(), connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"needs the database: {exc}")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _si_place(cur) -> int:
    cur.execute("""INSERT INTO place (kind, name_en, geom)
                   VALUES ('checkpoint','T_si',
                           ST_SetSRID(ST_MakePoint(35.2,32.2),4326))
                   RETURNING place_id""")
    return cur.fetchone()[0]


def _si_source(cur, key: str, kind: str, group: str | None) -> int:
    cur.execute("""INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                                       attribution_text,authority_rank,
                                       independence_group)
                   VALUES (%s,%s,%s,'NONE',false,'t',5,%s)
                   RETURNING source_id""", (key, key, kind, group))
    return cur.fetchone()[0]


def _si_observe(cur, place_id: int, source_id: int, value: str, mins_ago: int) -> None:
    cur.execute("""INSERT INTO state_observation
                     (place_id,state_kind,value,raw_value,observed_at,source_id,
                      confidence,direction,direction_explicit,modality)
                   VALUES (%s,%s,%s,%s, now() - make_interval(mins => %s), %s,
                           0.9,'both',false,'assertion')""",
                (place_id, SI_KIND, value, value, mins_ago, source_id))


def _group(cur, source_id: int) -> str | None:
    cur.execute("SELECT independence_group FROM source WHERE source_id=%s", (source_id,))
    return cur.fetchone()[0]


def test_copy_collapse_never_lifts_a_crowd_submitter_out_of_the_unverified_unit(db):
    """Audit F004. A crowd account that shadowed a channel 120 times while
    agreeing 80% was, on the next nightly `--apply`, written
    independence_group = NULL — a unit of its own in belief ('src:N'), with no
    Loop A record and no crowd_independence verdict. Five of those are five
    units, and five units clear the P2.4 gate on 'open'. Independence for a
    submitter is earned in learn/crowd_independence.py and nowhere else."""
    with db.cursor() as cur:
        pid = _si_place(cur)
        ch = _si_source(cur, "_t_si_chan", "telegram", None)
        cw = _si_source(cur, "_t_si_crowd", "crowd", "crowd:unverified")
        for i in range(120):
            _si_observe(cur, pid, ch, "open", i * 20)
            _si_observe(cur, pid, cw, "open" if i % 5 else "closed", i * 20 - 1)
        si._measure(cur, [SI_KIND])
        cur.execute("""SELECT count(*) FROM source_agreement
                        WHERE %s IN (source_a, source_b)""", (cw,))
        assert cur.fetchone()[0] == 0, "a crowd source was measured for copy-collapse"
        si._cluster(cur, apply_changes=True)
        assert _group(cur, cw) == "crowd:unverified"


def test_a_stale_agreement_row_cannot_release_a_crowd_source_either(db):
    """The guard is on the clustering and on the UPDATE too, not only on the
    measurement: a source_agreement row written by an older run must not be
    able to reach a crowd source."""
    with db.cursor() as cur:
        a = _si_source(cur, "_t_si_chan_a", "telegram", None)
        cw = _si_source(cur, "_t_si_crowd_b", "crowd", "crowd:unverified")
        lo, hi = sorted((a, cw))
        cur.execute("""INSERT INTO source_agreement
                         (source_a, source_b, state_kind, co_observations,
                          agreements, agreement_rate, window_seconds)
                       VALUES (%s, %s, %s, 500, 400, 0.8, 600)""", (lo, hi, SI_KIND))
        si._cluster(cur, apply_changes=True)
        assert _group(cur, cw) == "crowd:unverified"


def test_copy_collapse_still_merges_channels_that_are_one_voice(db):
    """The exclusion must not switch the channel half off: two channels that
    agree on every one of 120 chances are still one copyset."""
    with db.cursor() as cur:
        pid = _si_place(cur)
        a = _si_source(cur, "_t_si_copy_a", "telegram", None)
        b = _si_source(cur, "_t_si_copy_b", "telegram", None)
        for i in range(120):
            _si_observe(cur, pid, a, "open" if i % 3 else "closed", i * 20)
            _si_observe(cur, pid, b, "open" if i % 3 else "closed", i * 20 - 1)
        si._measure(cur, [SI_KIND])
        si._cluster(cur, apply_changes=True)
        ga, gb = _group(cur, a), _group(cur, b)
        assert ga is not None and ga == gb and ga.startswith("copyset:")


# ── the checkpoint backtest says what it measures (audit F234 / F235) ────────

from learn import accuracy                                       # noqa: E402

ACC_KIND = "_t_acc_kind"


def test_the_interval_counts_distinct_beliefs_not_pairs():
    """Ten reports scored against ONE prior belief are one trial of that
    belief, not ten. A Wilson interval over pairs would be far too narrow."""
    at = T0
    rows = [("open", "open", 60.0 * i, 0.8, True, True, 1, "both", at) for i in range(10)]
    out = accuracy.summarise(rows)
    assert out["precision"] == 1.0
    assert out["distinct_beliefs_asserted"] == 1
    lo, hi = out["ci95"]
    assert lo < 0.25, "one belief cannot bound precision above 0.25"


def _acc_setup(cur) -> int:
    cur.execute("""INSERT INTO state_kind_config
                     (state_kind, half_life_seconds, confidence_floor, max_assert_seconds)
                   VALUES (%s, 5400, 0.25, 21600)""", (ACC_KIND,))
    # What tonight's in-sample fit says: `open` barely beats a coin flip. Held
    # out of the judged window, there is no history to fit at all.
    cur.execute("""INSERT INTO state_value_decay
                     (state_kind, value, p0, asymptote, half_life_seconds, observations)
                   VALUES (%s, 'open', 0.52, 0.50, 60, 999)""", (ACC_KIND,))
    pid = _si_place(cur)
    a = _si_source(cur, "_t_acc_a", "telegram", None)
    b = _si_source(cur, "_t_acc_b", "telegram", None)
    for i in range(12):
        cur.execute("""INSERT INTO state_observation
                         (place_id,state_kind,value,raw_value,observed_at,source_id,
                          confidence,direction,direction_explicit,modality)
                       VALUES (%s,%s,'open','open', now() - make_interval(mins => %s),
                               %s, 0.9,'both',false,'assertion')""",
                    (pid, ACC_KIND, 5 * (12 - i), a if i % 2 else b))
    return pid


def test_the_backtest_replays_a_fit_held_out_of_the_window_it_judges(db):
    """The decay curves were refitted every night on ALL history, the judged
    week included, and the backtest replayed tonight's table over that week:
    a fit that has already absorbed the week cannot be surprised by it. The
    held-out replay fits on history before the window (here: none, so the
    kind's plain half-life applies) and never reads the serving table."""
    with db.cursor() as cur:
        _acc_setup(cur)
        held = accuracy._backtest(cur, ACC_KIND, 7, True)
        inside = accuracy._backtest(cur, ACC_KIND, 7, True, held_out=False)
    assert held["decay_fit"]["mode"] == "held_out"
    assert held["decay_fit"]["fitted_before"]
    assert held["decay_fit"]["values"] == []
    assert inside["decay_fit"]["mode"] == "in_sample"
    assert held["pairs_examined"] == inside["pairs_examined"] == 11
    # The in-sample table's p0 of 0.52 gates everything out; the held-out
    # replay does not see that table, so the two differ — which is the point.
    assert inside["would_have_asserted"] == 0
    assert held["would_have_asserted"] == 11
    assert "single_unit" in held["belief_model"]


# ── the incident precision round: one gate, the right version, the newest
#    round on the serving path (audit F210/F236, F212/F239, F240/F247, F237,
#    F238, F211) ─────────────────────────────────────────────────────────────

import json as _json                                             # noqa: E402

import learn.incident_precision as ip                            # noqa: E402


@pytest.fixture()
def rounds(tmp_path, monkeypatch):
    """ops/ in a temp dir, with the module's round globals restored after."""
    (tmp_path / "ops").mkdir()
    for name in ("ROOT", "SAMPLE_FILE", "SCORED_FILE", "RESULT_FILE", "ROUND"):
        monkeypatch.setattr(ip, name, getattr(ip, name))
    monkeypatch.setattr(ip, "ROOT", tmp_path)
    import ingest.sources.news_incidents as ni
    monkeypatch.setattr(ni, "CLASSIFIER_VERSION", "9.9.9")   # the code "now"

    def write(rnd, rows):
        """rows: (claim_id, incident_type, classifier_version, right, population)"""
        ip.use_round(str(rnd))
        with ip.SAMPLE_FILE.open("w") as fh:
            for cid, t, ver, _, pop in rows:
                fh.write(_json.dumps({"claim_id": cid, "verdict": "incident",
                                      "incident_type": t, "classifier_version": ver,
                                      "stratum": "core", "type_population": pop}) + "\n")
        with ip.SCORED_FILE.open("w") as fh:
            for cid, _, _, right, _ in rows:
                fh.write(_json.dumps({"claim_id": cid, "is_incident": True,
                                      "type_ok": right, "place_ok": True,
                                      "west_bank": True}) + "\n")
        return tmp_path / "ops"
    return write


def _typed(start, t, n_right, n, ver="1.8.0", pop=100):
    return [(start + i, t, ver, i < n_right, pop) for i in range(n)]


def test_the_per_type_gate_is_the_one_serving_uses(rounds):
    """Round 8: death 0.60 and siege 0.60, `types_below_floor: []` — the
    scorer gated at 0.60 while serve/quality.py and PLAN G3 say 0.70."""
    from serve.quality import GATE_OVERALL, GATE_TYPE
    assert (ip.GATE_PER_TYPE, ip.GATE_OVERALL) == (GATE_TYPE, GATE_OVERALL)
    rounds(8, _typed(0, "raid", 10, 10) + _typed(100, "death", 6, 10))
    r = ip.score()
    assert "death" in r["gate"]["types_below_floor"]
    assert r["gate"]["per_type_required"] == GATE_TYPE
    assert r["gate"]["pass"] is False


def test_a_round_is_stamped_with_the_version_that_classified_its_rows(rounds):
    """Scored after 1.8.1 landed, round 8 must still say 1.8.0 — in the round
    file, the serving file and the ledger measure_review reads."""
    ops = rounds(8, _typed(0, "raid", 9, 10, ver="1.8.0"))
    r = ip.score()
    assert r["classifier_version"] == "1.8.0"
    assert r["scoring_process_version"] == "9.9.9"
    ledger = [_json.loads(x) for x in (ops / "incident-rounds.ndjson").read_text().splitlines()]
    assert ledger[-1]["classifier_version"] == "1.8.0" and ledger[-1]["round"] == "8"
    assert _json.loads((ops / "incident-precision.json").read_text())["classifier_version"] == "1.8.0"


def test_a_round_drawn_across_two_versions_is_refused(rounds):
    rounds(8, _typed(0, "raid", 5, 5, ver="1.8.0") + _typed(50, "raid", 5, 5, ver="1.7.1"))
    with pytest.raises(SystemExit, match="more than one"):
        ip.score()


def test_rescoring_an_older_round_never_replaces_the_served_one(rounds):
    """`--score --round 7` rewrote the serving file with round 7's numbers and
    appended a fresh scored_at to the ledger — every incident answer said
    'round 7' and the weekly review saw a round scored today."""
    rounds(8, _typed(0, "raid", 9, 10))
    ip.score()
    ops = rounds(7, _typed(200, "raid", 5, 10, ver="1.6"))
    before = (ops / "incident-rounds.ndjson").read_text()
    r = ip.score()
    assert _json.loads((ops / "incident-precision.json").read_text())["round"] == "8"
    assert (ops / "incident-rounds.ndjson").read_text() == before
    assert r["promoted_to_serving"] is False
    assert _json.loads((ops / "incident-precision-round7.json").read_text())["round"] == "7"


def test_the_pooled_number_says_it_is_a_stratum_mean_and_the_served_mix_sits_beside_it(rounds):
    """Every type is capped at the same n, so the pooled precision weighs a
    rare type as much as the raids that dominate the stream."""
    rounds(8, _typed(0, "raid", 10, 10, pop=900) + _typed(100, "death", 5, 10, pop=100))
    o = ip.score()["overall"]
    assert o["precision"] == 0.75                      # (10 + 5) / 20
    assert "stratum mean" in o["basis"]
    sw = o["served_weighted"]
    assert sw["precision"] == 0.95                     # 0.9 * 1.0 + 0.1 * 0.5
    assert sw["ci95"][0] < 0.95 < sw["ci95"][1]


def test_the_sample_keeps_the_whole_text(rounds):
    """The classifier reads all of a text; the human and the rescore read the
    first 400 characters of it, and 'adv:long' is defined as longer than 700."""
    rounds(9, [])
    long_text = "خبر " * 300
    ip._write_sample([{"claim_id": 1, "raw_text": long_text, "confidence": 0.5}])
    row = _json.loads(ip.SAMPLE_FILE.read_text().splitlines()[0])
    assert len(row["raw_text"]) == len(long_text.strip())


def test_copies_of_one_text_are_one_row_of_a_draw(db):
    """Round 8's funeral stratum held five copies of one text in twelve rows.
    A draw takes one representative per text and fills the stratum from the
    next distinct ones."""
    with db.cursor() as cur:
        sid = _si_source(cur, "_t_ip_chan", "telegram", None)
        ids = []
        texts = ["نص مكرر عن اقتحام بلدة"] * 6 + ["نص آخر مختلف تماماً عن حدث آخر"]
        for i, text in enumerate(texts):
            cur.execute("""INSERT INTO claim (source_id, external_id, raw_ref, raw_text,
                                              claim_type, reported_at)
                           VALUES (%s, %s, 'test:ref', %s, 'unclassified', now())
                           RETURNING claim_id""", (sid, f"_t_ip_{i}", text))
            cid = cur.fetchone()[0]
            ids.append(cid)
            cur.execute("""INSERT INTO claim_classification
                             (claim_id, classifier, classifier_version, verdict,
                              incident_type, confidence)
                           VALUES (%s, 'news', 't', 'incident', '_t_ip_type', 0.5)""", (cid,))
        rows = [r for r in ip._draw(cur, [], per_type_cap=3, adversarial=0, rejects=0)
                if r["incident_type"] == "_t_ip_type"]
    assert len(rows) == 2, "six copies and one other text are two texts"
    assert len({r["copy_key"] for r in rows}) == 2
    assert sorted(r["copies_in_pool"] for r in rows) == [1, 6]
    assert all(r["type_population"] == 7 for r in rows)
