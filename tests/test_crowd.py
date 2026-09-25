"""P2 — the properties that decide whether a crowd can be trusted at all.

    ./.venv/bin/python -m pytest tests/test_crowd.py -q

These do not test that submissions work. They test the four things that, if any
one of them silently stopped holding, would turn a safety tool into a way to
send a family toward a closed checkpoint:

    1. one person with five phones is one observer
    2. a stranger cannot assert reassurance alone
    3. a stranger cannot make the system LESS sure by agreeing with it
    4. nothing a submitter says is ever discarded, including what is refused

Each runs against the real database inside a transaction that is rolled back,
because the thing under test is the SQL — a Python reimplementation of the
belief model would prove that the reimplementation is safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.belief import (MAX_CONFIDENCE, SINGLE_SOURCE_TRUST,  # noqa: E402
                            UNEARNED_CROWD_TRUST, refresh)
from resolve.db import dsn                                        # noqa: E402

# A synthetic kind, configured inside the rolled-back transaction. Using a real
# one meant every refresh rescanned 14k live checkpoint rows — 47 seconds for
# this file — and it also made the belief tests depend on whatever the live
# config happens to say. The vocabulary rules are asserted against the REAL
# config separately, at the bottom.
KIND = "_t_crowd_kind"


@pytest.fixture()
def db():
    """A transaction that is always rolled back. Never commits."""
    conn = psycopg.connect(dsn())
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _configure(cur) -> None:
    cur.execute("""INSERT INTO state_kind_config
                     (state_kind, half_life_seconds, confidence_floor,
                      max_assert_seconds, crowd_reportable, crowd_values,
                      crowd_gated_values, crowd_min_units)
                   VALUES (%s, 5400, 0.25, 21600, true,
                           ARRAY['open','closed'], ARRAY['open'], 2)
                   ON CONFLICT (state_kind) DO NOTHING""", (KIND,))


def _place(cur) -> int:
    cur.execute("""INSERT INTO place (kind, name_en, geom)
                   VALUES ('checkpoint','T_crowd',
                           ST_SetSRID(ST_MakePoint(35.2,32.2),4326))
                   RETURNING place_id""")
    return cur.fetchone()[0]


def _source(cur, key: str, kind: str, group: str | None,
            trust: float | None = None) -> int:
    cur.execute("""INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                                       attribution_text,authority_rank,
                                       independence_group,trust_weight)
                   VALUES (%s,%s,%s,'NONE',false,'t',5,%s,%s)
                   RETURNING source_id""",
                (key, key, kind, group, trust))
    return cur.fetchone()[0]


def _observe(cur, place_id: int, source_id: int, value: str,
             modality: str = "assertion", ago: str = "1 minute") -> None:
    cur.execute(f"""INSERT INTO state_observation
                     (place_id,state_kind,value,raw_value,observed_at,source_id,
                      confidence,direction,direction_explicit,modality)
                    VALUES (%s,%s,%s,%s, now() - interval '{ago}', %s,
                            0.9,'both',false,%s)""",
                (place_id, KIND, value, value, source_id, modality))


def _belief(cur, place_id: int):
    # Through refresh(), not REFRESH_SQL directly: refresh chooses the window
    # the statement scans, and the window is part of what is under test.
    refresh([KIND], conn=cur.connection)
    cur.execute("""SELECT value, base_confidence, independent_sources
                     FROM state_current
                    WHERE place_id=%s AND state_kind=%s AND direction='both'""",
                (place_id, KIND))
    return cur.fetchone()


# ── 1. one person with five phones ───────────────────────────────────────────

def test_five_accounts_in_the_unverified_group_are_one_observer(db):
    """The attack the whole design is built around.

    Five accounts run by one person look exactly like five independent
    confirmations, and the noisy-OR would take that to 0.97. They share one
    independence group, so they are one — and not because anything detected
    them.
    """
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        for i in range(5):
            sid = _source(cur, f"_t_sock{i}", "crowd", "crowd:unverified")
            _observe(cur, pid, sid, "closed")
        got = _belief(cur, pid)
    assert got is not None
    value, conf, units = got
    assert units == 1, "five sock puppets must count as one independence unit"
    assert conf == pytest.approx(SINGLE_SOURCE_TRUST * UNEARNED_CROWD_TRUST, abs=0.01)
    assert conf < 0.25, "and must land below every confidence floor"


def test_five_INDEPENDENT_crowd_units_do_count(db):
    """The other side of it: earning separation has to mean something, or the
    engine is just an elaborate way of ignoring people."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        for i in range(5):
            sid = _source(cur, f"_t_real{i}", "crowd", f"crowd:real{i}")
            _observe(cur, pid, sid, "closed")
        value, conf, units = _belief(cur, pid)
    assert units == 5
    assert conf > 0.5, "five genuinely separate witnesses should be believed"


# ── 2. P2.4 — reassurance needs corroboration ────────────────────────────────

def test_a_lone_crowd_report_cannot_assert_the_reassuring_value(db):
    """'open' sends someone toward the checkpoint. One stranger is not enough."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        sid = _source(cur, "_t_lone", "crowd", "crowd:earned_lone")
        _observe(cur, pid, sid, "open")
        assert _belief(cur, pid) is None, "gated value written on one crowd unit"


def test_a_lone_crowd_report_CAN_raise_a_caution(db):
    """The asymmetry has to cut one way only. A person who sees a checkpoint
    shut must be able to say so without finding a second witness first."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        sid = _source(cur, "_t_caution", "crowd", "crowd:earned_c")
        _observe(cur, pid, sid, "closed")
        got = _belief(cur, pid)
    assert got is not None and got[0] == "closed"


def test_a_non_crowd_witness_satisfies_the_gate(db):
    """Corroboration is never restricted — only sole authorship."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        ch = _source(cur, "_t_chan", "telegram", None)
        cw = _source(cur, "_t_agree", "crowd", "crowd:unverified")
        _observe(cur, pid, ch, "open", ago="3 minutes")
        _observe(cur, pid, cw, "open", ago="1 minute")
        got = _belief(cur, pid)
    assert got is not None and got[0] == "open"


def test_two_unverified_submitters_do_NOT_satisfy_the_gate(db):
    """Because they are one unit. This is the sock-puppet defence and the P2.4
    gate meeting, and it is the case an attacker would actually try."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        for i in range(2):
            sid = _source(cur, f"_t_pair{i}", "crowd", "crowd:unverified")
            _observe(cur, pid, sid, "open")
        assert _belief(cur, pid) is None


# ── 3. agreeing must never subtract ──────────────────────────────────────────

def test_a_stranger_agreeing_cannot_reduce_confidence(db):
    """This was live, and it was an inversion AND an abuse vector.

    The old formula scaled the whole noisy-OR by the LATEST reporter's trust, so
    an unverified stranger agreeing with a road channel dropped a checkpoint
    from 0.849 to 0.196. Corroboration made the system less sure, and anyone
    could blind any checkpoint by confirming it.
    """
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        ch = _source(cur, "_t_ch2", "telegram", None)
        _observe(cur, pid, ch, "closed", ago="3 minutes")
        _, alone, _ = _belief(cur, pid)

        cw = _source(cur, "_t_str", "crowd", "crowd:unverified")
        _observe(cur, pid, cw, "closed", ago="1 minute")
        _, together, units = _belief(cur, pid)

    assert units == 2
    assert together >= alone, "agreement must never lower confidence"
    assert together <= MAX_CONFIDENCE


def test_a_weak_witness_adds_only_a_little(db):
    """And it must not add as much as a real second source, or the crowd
    becomes a way to manufacture certainty."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        ch = _source(cur, "_t_ch3", "telegram", None)
        _observe(cur, pid, ch, "closed", ago="3 minutes")
        _, alone, _ = _belief(cur, pid)
        cw = _source(cur, "_t_weak", "crowd", "crowd:unverified")
        _observe(cur, pid, cw, "closed", ago="1 minute")
        _, with_crowd, _ = _belief(cur, pid)

        pid2 = _place(cur)
        c1 = _source(cur, "_t_ch4", "telegram", None)
        c2 = _source(cur, "_t_ch5", "telegram", "other")
        _observe(cur, pid2, c1, "closed", ago="3 minutes")
        _observe(cur, pid2, c2, "closed", ago="1 minute")
        _, two_channels, _ = _belief(cur, pid2)

    assert alone < with_crowd < two_channels


# ── 4. nothing is discarded ──────────────────────────────────────────────────

def test_a_refused_report_is_stored_and_never_believed(db):
    """Retention has no exception for reports we did not like — and the abuse
    loops need to see them. `modality` is what keeps the two facts apart."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        sid = _source(cur, "_t_limited", "crowd", "crowd:earned_l")
        _observe(cur, pid, sid, "closed", modality="rate_limited")
        assert _belief(cur, pid) is None, "rate_limited must not reach belief"
        cur.execute("""SELECT count(*) FROM state_observation
                        WHERE place_id=%s AND modality='rate_limited'""", (pid,))
        assert cur.fetchone()[0] == 1, "and must still be on the record"


def test_the_modality_vocabulary_admits_the_refusal_states(db):
    """If the CHECK constraint loses these, the engine cannot record a refusal
    at all and would have to choose between believing it and dropping it."""
    with db.cursor() as cur:
        cur.execute("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                        WHERE conrelid='state_observation'::regclass
                          AND conname='state_observation_modality_check'""")
        defn = cur.fetchone()[0]
    for m in ("assertion", "question", "unparsed", "rate_limited", "rejected"):
        assert m in defn


# ── configuration drives the engine, not code ────────────────────────────────

def test_every_gated_value_is_in_its_own_vocabulary(db):
    """A gated value that cannot be submitted is a gate on nothing, and would
    read as protection while protecting nothing."""
    with db.cursor() as cur:
        cur.execute("""SELECT state_kind, crowd_values, crowd_gated_values
                         FROM state_kind_config WHERE crowd_reportable""")
        for kind, values, gated in cur.fetchall():
            for g in gated:
                assert g in values, f"{kind}: gated {g!r} not in its vocabulary"


def test_every_crowd_reportable_kind_has_a_vocabulary(db):
    with db.cursor() as cur:
        cur.execute("""SELECT state_kind FROM state_kind_config
                        WHERE crowd_reportable AND coalesce(array_length(crowd_values,1),0)=0""")
        assert cur.fetchall() == []


def test_reassurance_is_gated_on_every_reportable_kind(db):
    """Every field tier 1 tracks has a direction that is dangerous to be wrong
    in. A kind that reaches production with an empty gate list has opted out of
    P2.4 silently, which is precisely the failure the policy exists to prevent.
    """
    with db.cursor() as cur:
        cur.execute("""SELECT state_kind FROM state_kind_config
                        WHERE crowd_reportable
                          AND coalesce(array_length(crowd_gated_values,1),0)=0""")
        ungated = [r[0] for r in cur.fetchall()]
    assert ungated == [], f"crowd-reportable with nothing gated: {ungated}"


# ── 5. a stranger's caution cannot blind a fresh channel reading (F017) ──────
#
# Registration is open by decision, and 'closed' is not gated (only the
# reassuring value is). So until this held, anyone could register and file
# 'closed' five minutes after a road channel said 'open': the newest assertion
# alone defined the served value, the stranger's 0.17 replaced the channel's
# 0.85, and state_serving turned it into `unknown` with 'closed' as the last
# known value — for every checkpoint, repeatably, until the channel posted
# again. Wrong in the cautious direction, but wrong, and the documented claim
# "a newcomer cannot move a served value alone" was false.

def _served(cur, place_id: int):
    cur.execute("""SELECT value, last_known_value FROM state_serving
                    WHERE place_id=%s AND state_kind=%s AND direction='both'""",
                (place_id, KIND))
    return cur.fetchone()


def test_a_strangers_caution_cannot_turn_a_fresh_channel_open_into_unknown(db):
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        ch = _source(cur, "_t_road", "telegram", None)
        cw = _source(cur, "_t_blinder", "crowd", "crowd:unverified")
        _observe(cur, pid, ch, "open", ago="5 minutes")
        _observe(cur, pid, cw, "closed", ago="1 minute")
        value, conf, _units = _belief(cur, pid)
        cur.execute("""SELECT contradicted_by FROM state_current
                        WHERE place_id=%s AND state_kind=%s""", (pid, KIND))
        dissent = cur.fetchone()[0]
        served = _served(cur, pid)
    assert value == "open", "a 0.17 stranger displaced a 0.85 channel reading"
    assert dissent == 1, "the stranger still counts — as dissent"
    assert conf == pytest.approx(SINGLE_SOURCE_TRUST * (1 - 0.25 / 2), abs=0.01)
    assert served[0] == "open"


def test_the_caution_still_counts_when_it_arrives_before_the_channel_is_read(db):
    """An attacker watching the channel posts 'closed' the moment the channel
    posts 'open', before the importer has read the channel. The crowd row is
    believed first; the channel's slightly OLDER reading must still be able to
    take its place — the upsert used to refuse to move observed_at back."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        ch = _source(cur, "_t_road_late", "telegram", None)
        cw = _source(cur, "_t_early_blinder", "crowd", "crowd:unverified")
        _observe(cur, pid, cw, "closed", ago="1 minute")
        assert _belief(cur, pid)[0] == "closed"
        _observe(cur, pid, ch, "open", ago="4 minutes")      # imported late
        value, _conf, _units = _belief(cur, pid)
    assert value == "open"


def test_a_lone_caution_after_the_window_is_still_raised(db):
    """The other side, and why the protection is bounded by the corroboration
    window: forty minutes after the channel spoke, a report of 'closed' is
    about a different moment. One person may raise an alarm alone (P2.4)."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        ch = _source(cur, "_t_road_old", "telegram", None)
        cw = _source(cur, "_t_witness", "crowd", "crowd:unverified")
        _observe(cur, pid, ch, "open", ago="45 minutes")
        _observe(cur, pid, cw, "closed", ago="1 minute")
        value, conf, _units = _belief(cur, pid)
    assert value == "closed" and conf < 0.25


def test_a_strangers_agreement_still_counts(db):
    """Only a DISAGREEING weak witness is held back. Agreement is never
    restricted."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        ch = _source(cur, "_t_road_agree", "telegram", None)
        cw = _source(cur, "_t_agreer", "crowd", "crowd:unverified")
        _observe(cur, pid, ch, "closed", ago="5 minutes")
        _observe(cur, pid, cw, "closed", ago="1 minute")
        value, conf, units = _belief(cur, pid)
    assert value == "closed" and units == 2
    assert conf > SINGLE_SOURCE_TRUST


# ── 6. dissent is a unit's LAST word, not every word (F429) ──────────────────

def test_a_unit_that_corrected_itself_is_not_dissent(db):
    """The copyset said 'closed' at T-20 and 'open' at T-2; a7walstreet says
    'open' at T. Every unit currently agrees. The old count put the copyset
    in both columns and discounted a reading nobody disputes."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        copy = _source(cur, "_t_copyset", "telegram", "copyset")
        a7 = _source(cur, "_t_a7", "telegram", "a7")
        _observe(cur, pid, copy, "closed", ago="20 minutes")
        _observe(cur, pid, copy, "open", ago="2 minutes")
        _observe(cur, pid, a7, "open", ago="0 minutes")
        _belief(cur, pid)
        cur.execute("""SELECT contradicted_by, independent_sources FROM state_current
                        WHERE place_id=%s AND state_kind=%s""", (pid, KIND))
        dissent, units = cur.fetchone()
    assert dissent == 0 and units == 2


# ── 7. same second, two values: deterministic (F428) ─────────────────────────

def test_a_tie_on_observed_at_is_decided_by_standing_not_by_chance(db):
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        ch = _source(cur, "_t_tie_ch", "telegram", None)
        cw = _source(cur, "_t_tie_cw", "crowd", "crowd:unverified")
        cur.execute("SELECT date_trunc('second', now()) - interval '2 minutes'")
        at = cur.fetchone()[0]
        for sid, v in ((cw, "closed"), (ch, "open")):
            cur.execute("""INSERT INTO state_observation
                             (place_id,state_kind,value,raw_value,observed_at,
                              source_id,confidence,direction,modality)
                           VALUES (%s,%s,%s,%s,%s,%s,0.9,'both','assertion')""",
                        (pid, KIND, v, v, at, sid))
        value, _conf, _units = _belief(cur, pid)
        cur.execute("""SELECT source_id FROM state_current
                        WHERE place_id=%s AND state_kind=%s""", (pid, KIND))
        author = cur.fetchone()[0]
    assert value == "open" and author == ch


# ── 8. slow kinds can be corroborated at all (F116) ──────────────────────────

def test_two_witnesses_an_hour_apart_corroborate_a_slow_kind(db):
    """crossing_status has a 12 h half-life. With a fixed 30-minute window two
    earned witnesses an hour apart were never counted together, so a crowd
    'open' on a slow kind could never clear P2.4 however many people saw it."""
    with db.cursor() as cur:
        cur.execute("""INSERT INTO state_kind_config
                         (state_kind, half_life_seconds, confidence_floor,
                          max_assert_seconds, crowd_reportable, crowd_values,
                          crowd_gated_values, crowd_min_units)
                       VALUES (%s, 43200, 0.3, 172800, true,
                               ARRAY['open','closed'], ARRAY['open'], 2)""",
                    ("_t_slow_kind",))
        pid = _place(cur)
        s1 = _source(cur, "_t_slow1", "crowd", "crowd:slow1", trust=0.9)
        s2 = _source(cur, "_t_slow2", "crowd", "crowd:slow2", trust=0.9)
        for sid, ago in ((s1, "70 minutes"), (s2, "5 minutes")):
            cur.execute(f"""INSERT INTO state_observation
                              (place_id,state_kind,value,raw_value,observed_at,
                               source_id,confidence,direction,modality)
                            VALUES (%s,'_t_slow_kind','open','open',
                                    now() - interval '{ago}',%s,0.9,'both',
                                    'assertion')""", (pid, sid))
        refresh(["_t_slow_kind"], conn=db)
        cur.execute("""SELECT value, independent_sources FROM state_current
                        WHERE place_id=%s AND state_kind='_t_slow_kind'""", (pid,))
        got = cur.fetchone()
    assert got is not None, "two earned witnesses an hour apart were not enough"
    assert got == ("open", 2)


def test_a_checkpoint_kind_keeps_its_thirty_minute_window(db):
    """The per-kind window must not widen the fast kinds: 45 minutes apart on
    a 90-minute half-life is still two moments, not corroboration."""
    with db.cursor() as cur:
        _configure(cur)
        pid = _place(cur)
        a = _source(cur, "_t_fast_a", "telegram", "fa")
        b = _source(cur, "_t_fast_b", "telegram", "fb")
        _observe(cur, pid, a, "closed", ago="45 minutes")
        _observe(cur, pid, b, "closed", ago="1 minute")
        _v, _c, units = _belief(cur, pid)
    assert units == 1


# ── 9. retired kinds are not reportable (F120) ───────────────────────────────

def test_a_retired_kind_is_neither_reportable_nor_refreshed_as_crowd(db):
    """070 retired fuel availability without clearing crowd_reportable, so the
    crowd refresh kept rebuilding it every two minutes and /v2/crowd/fields
    kept offering it while /v2/fuel/* answered 410."""
    from resolve.belief import _crowd_kinds
    with db.cursor() as cur:
        _configure(cur)
        cur.execute("""UPDATE state_kind_config SET retired_at = now(),
                              retired_reason = 'test'
                        WHERE state_kind = %s""", (KIND,))
        kinds = _crowd_kinds(cur)
    assert KIND not in kinds


def test_the_engine_refuses_a_retired_kind(db, monkeypatch):
    from crowd import engine
    with db.cursor() as cur:
        _configure(cur)
        cur.execute("UPDATE state_kind_config SET retired_at = now() WHERE state_kind=%s",
                    (KIND,))
    reg = engine.register("_t_retired_user", conn=db)
    res = engine.submit(reg["handle"], reg["token"], KIND, "anywhere", "closed",
                        conn=db)
    assert res.status == "rejected" and "retired" in res.detail


# ── 10. a crowd note is never read as news (F012) ────────────────────────────
#
# feeds_incidents defaulted to true and nothing set it false for the crowd, so
# a registered stranger's free-text note ("قوات الاحتلال تقتحم بلدة حوارة
# واغلاق مدخل البلدة") was read by the incident classifier within one tick and
# served as a believed raid plus a road_closure 'closed' — straight past the
# 0.17 that the belief layer was supposed to hold it to.

def test_a_registered_submitter_does_not_feed_the_incident_classifier(db):
    from crowd import engine
    reg = engine.register("_t_note_writer", conn=db)
    with db.cursor() as cur:
        cur.execute("SELECT feeds_incidents FROM source WHERE source_id=%s",
                    (reg["source_id"],))
        assert cur.fetchone()[0] is False


def test_no_crowd_source_can_be_made_to_feed_incidents(db):
    """Enforced by the schema (079), not by the one writer remembering: a
    crowd source inserted or updated any other way still reads false."""
    with db.cursor() as cur:
        sid = _source(cur, "_t_crowd_raw", "crowd", "crowd:unverified")
        cur.execute("UPDATE source SET feeds_incidents = true WHERE source_id=%s", (sid,))
        cur.execute("SELECT feeds_incidents FROM source WHERE source_id=%s", (sid,))
        assert cur.fetchone()[0] is False
        cur.execute("""SELECT count(*) FROM source
                        WHERE kind = 'crowd' AND feeds_incidents""")
        assert cur.fetchone()[0] == 0


# ── 11. what the door checks before writing anything ─────────────────────────

class _FakeRes:
    """A resolver answer, so the engine's own rule is tested and not the
    gazetteer (whose exact-alias path also commits its hit counter)."""
    def __init__(self, place_id, kind, confidence=0.9):
        self.place_id, self.kind, self.confidence = place_id, kind, confidence
        self.name_ar, self.name_en = None, "T_town"
        self.precision, self.method = "town", "fuzzy"


def test_a_report_resolved_to_the_wrong_kind_of_place_is_refused(db, monkeypatch):
    """F109. A misspelt checkpoint name falls through to the general resolver,
    which PREFERS the kind but does not require it, and the town of the same
    name comes back at 0.9. The report was accepted onto a locality no channel
    writes to — the trap 035 was meant to close."""
    from crowd import engine
    with db.cursor() as cur:
        _configure(cur)
        cur.execute("UPDATE state_kind_config SET place_kind='checkpoint' WHERE state_kind=%s",
                    (KIND,))
        cur.execute("""INSERT INTO place (kind, name_en, geom)
                       VALUES ('locality','T_town',
                               ST_SetSRID(ST_MakePoint(35.2,32.2),4326))
                       RETURNING place_id""")
        town = cur.fetchone()[0]
    monkeypatch.setattr(engine, "resolve_for_state_kind",
                        lambda conn, place, kind: _FakeRes(town, "locality"))
    monkeypatch.setattr(engine.bronze, "put", lambda *a, **k: pytest.fail("wrote bronze"))
    reg = engine.register("_t_wrong_kind", conn=db)
    res = engine.submit(reg["handle"], reg["token"], KIND, "T_twon", "closed", conn=db)
    assert res.status == "rejected" and "locality" in res.detail
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM state_observation WHERE place_id=%s", (town,))
        assert cur.fetchone()[0] == 0


def test_a_place_that_already_carries_the_kind_is_accepted_whatever_its_kind(db, monkeypatch):
    """v1's checkpoints include crossings and roads, and channels report
    checkpoint_flow on them. What matters is that other sources meet the
    report there, not the label on the row."""
    from crowd import engine

    class _Ref:
        ref = "bronze://t/0"
    with db.cursor() as cur:
        _configure(cur)
        cur.execute("UPDATE state_kind_config SET place_kind='checkpoint' WHERE state_kind=%s",
                    (KIND,))
        cur.execute("""INSERT INTO place (kind, name_en, geom)
                       VALUES ('crossing','T_road_cp',
                               ST_SetSRID(ST_MakePoint(35.2,32.2),4326))
                       RETURNING place_id""")
        road = cur.fetchone()[0]
        ch = _source(cur, "_t_road_ch", "telegram", None)
        _observe(cur, road, ch, "open", ago="3 hours")
    monkeypatch.setattr(engine, "resolve_for_state_kind",
                        lambda conn, place, kind: _FakeRes(road, "crossing"))
    monkeypatch.setattr(engine.bronze, "put", lambda *a, **k: _Ref())
    reg = engine.register("_t_right_place", conn=db)
    res = engine.submit(reg["handle"], reg["token"], KIND, "T_road_cp", "closed", conn=db)
    assert res.status == "accepted", res.detail


def test_an_unbounded_note_is_refused_before_anything_is_written(db, monkeypatch):
    """F350. Refusal never means deletion — so every refused report is a
    permanent bronze object, claim and observation, and the note had no
    length limit at all. A 15 KB note is not a report."""
    from crowd import engine
    monkeypatch.setattr(engine.bronze, "put", lambda *a, **k: pytest.fail("wrote bronze"))
    with db.cursor() as cur:
        _configure(cur)
    reg = engine.register("_t_long_note", conn=db)
    res = engine.submit(reg["handle"], reg["token"], KIND, "anywhere", "closed",
                        note="ح" * 15000, conn=db)
    assert res.status == "rejected" and str(engine.NOTE_MAX_CHARS) in res.detail
