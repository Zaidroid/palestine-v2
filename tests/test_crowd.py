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

from resolve.belief import (MAX_CONFIDENCE, REFRESH_SQL,          # noqa: E402
                            SINGLE_SOURCE_TRUST, UNEARNED_CROWD_TRUST)
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
    cur.execute(REFRESH_SQL, {"kinds": [KIND]})
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
