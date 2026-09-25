"""The served formula, pinned from observation to answer.

    ./.venv/bin/python -m pytest tests/test_belief_serving.py -q

Every test writes synthetic rows — place, source, state_kind_config,
state_observation — inside a transaction, runs the real belief refresh
(`resolve.belief.refresh`) and reads the real serving views (`state_serving`,
`checkpoint_serving`), then rolls back. Nothing is committed.

Why this file exists: until it did, no test read `state_serving` at all. The
three serving gates (confidence floor, staleness band, assert ceiling) were
asserted only by hand-run SQL gates over live rows, which pass whenever no live
row happens to sit near a boundary (audit F110/F391). A change to the view's
decay expression, or `<` becoming `<=` on the floor, could not fail anything.
And the direction merge in `checkpoint_serving` — the row every default
checkpoint answer reads — was pinned by nothing (F377), which is how the
'both' travel row came to say `open` over two fresher `closed` readings (F008).
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.belief import (FUTURE_TOLERANCE, SINGLE_SOURCE_TRUST,  # noqa: E402
                            refresh)
from resolve.db import dsn                                        # noqa: E402

KIND = "_t_serving_kind"
FLOW = "checkpoint_flow"          # checkpoint_serving reads this kind by name


@pytest.fixture()
def db():
    """A transaction that is always rolled back. Never commits."""
    conn = psycopg.connect(dsn())
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _kind(cur, half_life=5400, floor=0.25, max_assert=21600) -> None:
    cur.execute("""INSERT INTO state_kind_config
                     (state_kind, half_life_seconds, confidence_floor,
                      max_assert_seconds)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (state_kind) DO UPDATE SET
                     half_life_seconds = EXCLUDED.half_life_seconds,
                     confidence_floor = EXCLUDED.confidence_floor,
                     max_assert_seconds = EXCLUDED.max_assert_seconds""",
                (KIND, half_life, floor, max_assert))


def _place(cur, name="T_serving") -> int:
    cur.execute("""INSERT INTO place (kind, name_en, geom)
                   VALUES ('checkpoint', %s,
                           ST_SetSRID(ST_MakePoint(35.21, 32.21), 4326))
                   RETURNING place_id""", (name,))
    return cur.fetchone()[0]


def _source(cur, key: str, kind: str = "telegram", group: str | None = None,
            trust: float | None = None) -> int:
    cur.execute("""INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                                       attribution_text,authority_rank,
                                       independence_group,trust_weight)
                   VALUES (%s,%s,%s,'NONE',false,'t',5,%s,%s)
                   RETURNING source_id""", (key, key, kind, group, trust))
    return cur.fetchone()[0]


def _observe(cur, place_id, source_id, value, *, kind=KIND, direction="both",
             at="now() - interval '1 minute'") -> None:
    cur.execute(f"""INSERT INTO state_observation
                      (place_id,state_kind,value,raw_value,observed_at,source_id,
                       confidence,direction,direction_explicit,modality)
                    VALUES (%s,%s,%s,%s, {at}, %s, 0.9, %s, %s, 'assertion')""",
                (place_id, kind, value, value, source_id, direction,
                 direction != "both"))


def _served(cur, place_id, kind=KIND, direction="both") -> dict | None:
    cur.execute("""SELECT value, last_known_value, confidence, staleness_band,
                          age_minutes
                     FROM state_serving
                    WHERE place_id=%s AND state_kind=%s AND direction=%s""",
                (place_id, kind, direction))
    r = cur.fetchone()
    if r is None:
        return None
    return dict(zip(("value", "last_known", "confidence", "band", "age"), r))


def _checkpoint(cur, place_id, direction="both") -> dict | None:
    cur.execute("""SELECT flow, last_known_flow, reported_for, passable,
                          staleness_band
                     FROM checkpoint_serving
                    WHERE place_id=%s AND direction=%s""", (place_id, direction))
    r = cur.fetchone()
    if r is None:
        return None
    return dict(zip(("flow", "last_known", "reported_for", "passable", "band"), r))


# ── the three serving gates, at their boundaries ─────────────────────────────

def test_a_fresh_single_source_reading_is_served_at_the_measured_trust(db):
    """One curated observer, one minute old, no measured decay curve: served,
    'live', at SINGLE_SOURCE_TRUST x 2^(-age/half-life)."""
    with db.cursor() as cur:
        _kind(cur)
        pid = _place(cur)
        _observe(cur, pid, _source(cur, "_t_s_fresh"), "open")
        refresh([KIND], conn=db)
        got = _served(cur, pid)
    assert got["value"] == "open" and got["band"] == "live"
    assert got["confidence"] == pytest.approx(
        SINGLE_SOURCE_TRUST * 0.5 ** (60 / 5400), abs=0.005)


def test_below_the_confidence_floor_is_unknown_and_keeps_the_last_value(db):
    """Floor 0.9 over a 0.85 reading: gate 1 alone must refuse it."""
    with db.cursor() as cur:
        _kind(cur, floor=0.9)
        pid = _place(cur)
        _observe(cur, pid, _source(cur, "_t_s_floor"), "open")
        refresh([KIND], conn=db)
        got = _served(cur, pid)
    assert got["value"] == "unknown"
    assert got["last_known"] == "open", "unknown must not forget what was said"
    assert got["band"] == "live", "only the floor fired here"


def test_the_assert_ceiling_fires_on_its_own_one_minute_past_it(db):
    """Gate 3 in isolation: half-life 2 h, ceiling 2 h. At 2 h + 1 min the
    decayed confidence (~0.42) is still over the floor and the band is only
    'recent', so the ceiling is the only thing that can say unknown."""
    with db.cursor() as cur:
        _kind(cur, half_life=7200, floor=0.25, max_assert=7200)
        pid = _place(cur)
        src = _source(cur, "_t_s_ceiling")
        _observe(cur, pid, src, "open", at="now() - interval '121 minutes'")
        refresh([KIND], conn=db, full=True)
        got = _served(cur, pid)
    assert got["confidence"] >= 0.25 and got["band"] == "recent"
    assert got["value"] == "unknown", "served past max_assert_seconds"
    assert got["last_known"] == "open"


def test_one_minute_inside_the_ceiling_is_still_served(db):
    with db.cursor() as cur:
        _kind(cur, half_life=7200, floor=0.25, max_assert=7200)
        pid = _place(cur)
        _observe(cur, pid, _source(cur, "_t_s_inside"), "open",
                 at="now() - interval '119 minutes'")
        refresh([KIND], conn=db)
        got = _served(cur, pid)
    assert got["value"] == "open"


def test_the_expired_band_is_unknown(db):
    """8 half-lives: the band gate. No ceiling configured, so the band is what
    stops it (the floor would too — this pins that nothing re-opens it)."""
    with db.cursor() as cur:
        _kind(cur, half_life=900, floor=0.01, max_assert=None)
        pid = _place(cur)
        _observe(cur, pid, _source(cur, "_t_s_band"), "open",
                 at="now() - interval '121 minutes'")
        refresh([KIND], conn=db, full=True)
        got = _served(cur, pid)
    assert got["band"] == "expired" and got["value"] == "unknown"


def test_forty_days_of_decay_does_not_underflow(db):
    """010's exponent guard: 40 days at a 15-minute half-life is 3,840
    halvings, past float8's range inside power()."""
    with db.cursor() as cur:
        _kind(cur, half_life=900)
        pid = _place(cur)
        _observe(cur, pid, _source(cur, "_t_s_old"), "open",
                 at="now() - interval '40 days'")
        refresh([KIND], conn=db, full=True)
        got = _served(cur, pid)
    assert got["value"] == "unknown" and got["confidence"] == 0


def test_a_measured_persistence_curve_scales_by_informativeness(db):
    """With a state_value_decay row the served confidence is
    base x clamp((p(t) - 0.5) / (p0 - 0.5)) — the fitted curve, not 2^-t."""
    with db.cursor() as cur:
        _kind(cur)
        cur.execute("""INSERT INTO state_value_decay
                         (state_kind, value, p0, asymptote, half_life_seconds,
                          observations)
                       VALUES (%s, 'open', 0.96, 0.88, 3600, 100)""", (KIND,))
        pid = _place(cur)
        _observe(cur, pid, _source(cur, "_t_s_decay"), "open",
                 at="now() - interval '60 minutes'")
        refresh([KIND], conn=db)
        got = _served(cur, pid)
    p = 0.88 + (0.96 - 0.88) * 0.5          # one persistence half-life
    expect = SINGLE_SOURCE_TRUST * (p - 0.5) / (0.96 - 0.5)
    assert got["confidence"] == pytest.approx(expect, abs=0.005)
    assert got["value"] == "open"


# ── a timestamp from the future (F331 / F117) ────────────────────────────────

def test_a_future_stamped_belief_is_not_served(db):
    """A row already in state_current with observed_at a day ahead (clock skew,
    a tz-naive string read as UTC, a date without a year). state_confidence
    clamps a negative age to FULL confidence and the band calls it 'live', so
    it used to be served as the freshest possible reading for a whole day."""
    with db.cursor() as cur:
        _kind(cur)
        pid = _place(cur)
        src = _source(cur, "_t_s_future_row")
        cur.execute("""INSERT INTO state_current
                         (place_id,state_kind,direction,value,observed_at,
                          source_id,base_confidence)
                       VALUES (%s,%s,'both','open', now() + interval '1 day',
                               %s, 0.85)""", (pid, KIND, src))
        got = _served(cur, pid)
    assert got["value"] == "unknown", "a reading from tomorrow was served"
    assert got["last_known"] == "open"


def test_a_few_seconds_of_clock_skew_is_tolerated(db):
    with db.cursor() as cur:
        _kind(cur)
        pid = _place(cur)
        _observe(cur, pid, _source(cur, "_t_s_skew"), "open",
                 at="now() + interval '30 seconds'")
        refresh([KIND], conn=db)
        got = _served(cur, pid)
    assert got["value"] == "open"
    assert FUTURE_TOLERANCE  # the tolerance is a named constant, not a literal


def test_a_future_observation_does_not_freeze_belief(db):
    """The upsert refuses to move observed_at backwards, so a row stamped three
    hours ahead used to block every genuine correction until the wall clock
    passed it — belief.py records this happening once (the G2.5 incident)."""
    with db.cursor() as cur:
        _kind(cur)
        pid = _place(cur)
        bad = _source(cur, "_t_s_skewed_feed")
        good = _source(cur, "_t_s_honest_feed", group="honest")
        _observe(cur, pid, bad, "open", at="now() + interval '3 hours'")
        # and the same row already believed, as production may hold it today
        cur.execute("""INSERT INTO state_current
                         (place_id,state_kind,direction,value,observed_at,
                          source_id,base_confidence)
                       VALUES (%s,%s,'both','open', now() + interval '3 hours',
                               %s, 0.85)""", (pid, KIND, bad))
        _observe(cur, pid, good, "closed", at="now() - interval '1 minute'")
        refresh([KIND], conn=db)
        got = _served(cur, pid)
    assert got["value"] == "closed", "the future-stamped 'open' froze belief"


# ── checkpoint_serving: the travel rows ──────────────────────────────────────

def _flow_setup(cur):
    pid = _place(cur, "T_cp_dir")
    return pid, _source(cur, "_t_cp_road"), _source(cur, "_t_cp_other", group="other")


def test_both_row_is_not_open_over_fresher_closed_in_both_directions(db):
    """F008. 13:00 'حوارة سالك' (both), 14:05 'مغلق للداخل ومغلق للخارج'
    (two direction-explicit facts, no 'both' fact). The default answer read
    the 'both' row, which only ever looked at 'both' readings: open."""
    with db.cursor() as cur:
        pid, a, b = _flow_setup(cur)
        _observe(cur, pid, a, "open", kind=FLOW, at="now() - interval '65 minutes'")
        _observe(cur, pid, b, "closed", kind=FLOW, direction="inbound",
                 at="now() - interval '2 minutes'")
        _observe(cur, pid, b, "closed", kind=FLOW, direction="outbound",
                 at="now() - interval '2 minutes'")
        refresh([FLOW], conn=db)
        both = _checkpoint(cur, pid)
        inb, outb = _checkpoint(cur, pid, "inbound"), _checkpoint(cur, pid, "outbound")
    assert inb["flow"] == "closed" and outb["flow"] == "closed"
    assert both["flow"] == "closed", "default answer says open over two fresh closures"
    assert both["passable"] is False


def test_one_fresh_directional_closure_is_not_hidden_by_an_old_both_open(db):
    """F016. An explicit 'inbound closed' 10 min ago and a 'both open' 5 h ago
    (inside the 6 h ceiling). The checkpoint is closed for somebody."""
    with db.cursor() as cur:
        pid, a, b = _flow_setup(cur)
        _observe(cur, pid, a, "open", kind=FLOW, at="now() - interval '5 hours'")
        _observe(cur, pid, b, "closed", kind=FLOW, direction="inbound",
                 at="now() - interval '10 minutes'")
        refresh([FLOW], conn=db)
        both = _checkpoint(cur, pid)
    assert both["flow"] == "closed"
    assert both["reported_for"] == "inbound", "the row must say where it came from"


def test_a_checkpoint_reported_only_per_direction_has_a_default_row(db):
    """F332/F016. Nothing tagged 'both' ever arrived; the default answer used
    to be 'no checkpoint reading has ever been recorded here'."""
    with db.cursor() as cur:
        pid, a, _ = _flow_setup(cur)
        _observe(cur, pid, a, "closed", kind=FLOW, direction="inbound")
        _observe(cur, pid, a, "open", kind=FLOW, direction="outbound")
        refresh([FLOW], conn=db)
        both = _checkpoint(cur, pid)
    assert both is not None, "a directionally-reported checkpoint vanished"
    assert both["flow"] == "closed" and both["passable"] is False


def test_one_direction_open_is_not_an_all_clear_for_both(db):
    """Only 'inbound open' is known. The default row may not reassure a
    traveller heading outbound on it: unknown, with the open kept as the last
    known value so the answer can still say what was seen."""
    with db.cursor() as cur:
        pid, a, _ = _flow_setup(cur)
        _observe(cur, pid, a, "open", kind=FLOW, direction="inbound")
        refresh([FLOW], conn=db)
        both = _checkpoint(cur, pid)
        inb = _checkpoint(cur, pid, "inbound")
    assert inb["flow"] == "open"
    assert both["flow"] == "unknown" and both["last_known"] == "open"
    assert both["passable"] is None


def test_both_directions_open_is_open(db):
    with db.cursor() as cur:
        pid, a, _ = _flow_setup(cur)
        _observe(cur, pid, a, "open", kind=FLOW, direction="inbound")
        _observe(cur, pid, a, "open", kind=FLOW, direction="outbound")
        refresh([FLOW], conn=db)
        both = _checkpoint(cur, pid)
    assert both["flow"] == "open" and both["passable"] is True


def test_only_both_readings_behave_exactly_as_before(db):
    """The common case today (13,096 'both' vs 1,279 explicit readings): the
    three travel rows are the one 'both' reading."""
    with db.cursor() as cur:
        pid, a, _ = _flow_setup(cur)
        _observe(cur, pid, a, "congested", kind=FLOW)
        refresh([FLOW], conn=db)
        rows = {d: _checkpoint(cur, pid, d) for d in ("both", "inbound", "outbound")}
    for d, r in rows.items():
        assert r["flow"] == "congested" and r["reported_for"] == "both", d


def test_a_fresher_both_reading_answers_a_directional_traveller(db):
    """F377, pinning 014's doctrine: freshest wins, so a generic 'سالك' five
    minutes after an explicit 'مغلق للخارج' answers the outbound traveller.
    Pinned so a change to it — in either direction — is a decision, not an
    accident."""
    with db.cursor() as cur:
        pid, a, b = _flow_setup(cur)
        _observe(cur, pid, b, "closed", kind=FLOW, direction="outbound",
                 at="now() - interval '5 minutes'")
        _observe(cur, pid, a, "open", kind=FLOW, at="now() - interval '2 minutes'")
        refresh([FLOW], conn=db)
        outb = _checkpoint(cur, pid, "outbound")
    assert outb["flow"] == "open" and outb["reported_for"] == "both"


def test_on_a_tie_the_direction_specific_reading_wins(db):
    with db.cursor() as cur:
        pid, a, b = _flow_setup(cur)
        at = "date_trunc('second', now()) - interval '3 minutes'"
        _observe(cur, pid, a, "open", kind=FLOW, at=at)
        _observe(cur, pid, b, "closed", kind=FLOW, direction="inbound", at=at)
        refresh([FLOW], conn=db)
        inb = _checkpoint(cur, pid, "inbound")
        both = _checkpoint(cur, pid)
    assert inb["flow"] == "closed" and inb["reported_for"] == "inbound"
    assert both["flow"] == "closed"


def test_directions_that_differ_are_both_visible_and_the_default_is_the_worse(db):
    """palhub's shape: every reading direction-explicit, the two directions
    different. The default row takes the more restrictive; each direction
    keeps its own."""
    with db.cursor() as cur:
        pid, a, _ = _flow_setup(cur)
        _observe(cur, pid, a, "slow", kind=FLOW, direction="inbound")
        _observe(cur, pid, a, "open", kind=FLOW, direction="outbound")
        refresh([FLOW], conn=db)
        rows = {d: _checkpoint(cur, pid, d) for d in ("both", "inbound", "outbound")}
    assert rows["inbound"]["flow"] == "slow"
    assert rows["outbound"]["flow"] == "open"
    assert rows["both"]["flow"] == "slow" and rows["both"]["reported_for"] == "inbound"
