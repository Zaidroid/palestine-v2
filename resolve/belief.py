"""How many observations become one belief. The single implementation.

`refresh(kinds)` recomputes `state_current` for the given state kinds from
`state_observation`, and is the only place in the system that decides what we
think is true. Checkpoints, fuel and the crowd path all call it.

WHY IT IS ONE FUNCTION NOW
It was three. `ingest/sources/checkpoints.py` had the real model — independence
units, noisy-OR, dissent discount, earned trust. `ingest/sources/palhub_loader.py`
had `SELECT DISTINCT ON (place_id, state_kind) ... independent_sources=1,
contradicted_by=0` and used the PARSE confidence as the belief confidence, a
flat 0.95 for every fuel row in the database. weather and power had their own.

Three implementations of "what do we believe" is three chances to disagree, and
they did: fuel asserted 0.95 for a single unverified observation while an
identical checkpoint observation asserted 0.85 and said so.

It became urgent rather than untidy when the crowd path arrived. The fuel
rebuild had **no modality filter and a hardcoded independent_sources=1**, so a
single crowd report — including one the engine had already refused and marked
`rate_limited` — would have overwritten belief at full confidence, bypassing
corroboration, earned trust, and the P2.4 gate in one step. On the vertical
where crowd reports were already arriving.

THE MODEL
  * Sources in one independence group count ONCE (copy-collapse). Nine road
    channels agreeing 99.5% of the time are one observer, and every unverified
    crowd submitter shares a single group until independence is earned.
  * Noisy-OR over independent units: one gives SINGLE_SOURCE_TRUST, two ~0.96,
    three ~0.97, capped at MAX_CONFIDENCE.
  * Discounted by dissent, then scaled by the reporter's EARNED trust_weight
    (Loop A). NULL trust coalesces to 1.0 — a source is never penalised for the
    system not yet having measured it.
  * Only `modality = 'assertion'` counts. Questions, unparsed text, and crowd
    reports the engine refused are retained and never believed.

P2.4 — THE ASYMMETRY
Being wrong is not symmetric. A false "closed" costs a detour; a false "open"
sends a family toward a checkpoint that is shut. A false "no diesel" costs a
detour; a false "has diesel" spends a tank that could not be spared. So values
listed in `state_kind_config.crowd_gated_values` — the reassuring ones — may not
be asserted on crowd evidence ALONE. They need `crowd_min_units` independent
units, or one observer who is not the crowd.

Note what is NOT restricted: corroboration, and cautions. A crowd report freely
strengthens a reassuring value somebody else already reported, and one person
may raise an alarm alone. Only sole authorship of reassurance is withheld.

A blocked row is not written, which means the previous belief stands and goes on
decaying toward `unknown` on its own. That is the honest outcome — we did not
learn enough to change our mind — and it needs no separate mechanism, because
the staleness gates already turn an unrefreshed value into "nobody has looked
recently".
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect                         # noqa: E402

# Two observations more than this apart are not corroborating each other; they
# are describing two different moments.
#
# PER KIND since the audit (F116): a third of the kind's half-life, clamped to
# [CORROBORATION_WINDOW, CORROBORATION_WINDOW_MAX]. A fixed 30 minutes meant
# that on crossing_status (12 h half-life) two people reporting Allenby open at
# 09:00 and 10:00 were never counted together, so a crowd 'open' on a slow kind
# could never clear P2.4 however many independent witnesses saw it. The floor
# keeps every checkpoint and fuel kind at exactly 30 minutes (their half-lives
# are 15-90 min), so nothing that is measured today moves.
# learn/reliability.py derives its comparison window the same way (1/3).
CORROBORATION_WINDOW = "30 minutes"
CORROBORATION_WINDOW_MAX = "6 hours"
CORROBORATION_FRACTION = 3

# How far ahead of this database's clock an observation may be stamped and
# still count. Beyond it the stamp is wrong, not early (clock skew, a tz-naive
# string read as UTC, a date parsed without its year): it is kept, never
# believed, and never served (migration 080 applies the same tolerance).
FUTURE_TOLERANCE = "10 minutes"

# P(correct | one independence unit, fresh), MEASURED by the backtest rather
# than chosen — see learn/accuracy.py and DECISIONS 2026-08-01. The earlier
# 0.70 was an assumption and was under-confident: the system said 0.3 and was
# right 73% of the time.
SINGLE_SOURCE_TRUST = 0.85

# Nothing is ever certain. The cap also keeps a single source below the
# ceiling, so a second independent group always still adds something — a model
# that saturates at one observer has stopped modelling anything.
MAX_CONFIDENCE = 0.97

# What an UNMEASURED reporter's word is worth, and why it depends on who they
# are.
#
# For curated sources the rule is "never penalised for the system not having
# measured you": a Telegram channel someone chose, vetted and added gets 1.0
# until Loop A says otherwise, because the absence of a measurement is our
# failing, not theirs.
#
# Applying that to the crowd would invert the principle this project is built
# on. A stranger who registered thirty seconds ago would arrive at 1.0 and their
# first report would be served at 0.85 — the same standing as a road channel
# with two years of history. Reputation would be granted, not earned, and the
# defence against a sock-puppet ring would be one shared independence unit
# holding back reports each worth 0.85.
#
# So an unmeasured crowd submitter is worth 0.20 — near the Wilson lower bound
# after a single correct report (0.207), which is this project's standing answer
# to "how much is one unverified success worth". 0.85 x 0.20 = 0.17, below every
# confidence floor in state_kind_config (0.25-0.35). A newcomer therefore cannot
# ASSERT a value alone, and does not need to be stopped by a rule that names
# newcomers: they simply have not earned it yet.
#
# That alone did not stop them MOVING one (audit F017): the newest assertion
# defined the value, so a stranger's 'closed' filed five minutes after a road
# channel's 'open' replaced it, and 0.17 under the floor served as `unknown` —
# any checkpoint, any time, from an account anyone can open. Hence the rule in
# `latest` below: inside one corroboration window, a reading that could not be
# served on its own does not displace one that can; it is counted as dissent.
#
# Not zero, deliberately. Zero would make a crowd report incapable of ever
# contributing, and Loop A scores submitters by comparing them against the
# consensus of other units whether or not their report was served — so a real
# reporter climbs out of 0.20 by being right, without ever having needed to be
# believed first.
UNEARNED_CROWD_TRUST = 0.20

# The window, per kind, as SQL over state_kind_config (see CORROBORATION_WINDOW).
_WINDOW_SQL = (
    f"LEAST(GREATEST(make_interval(secs => half_life_seconds::float8 / {CORROBORATION_FRACTION}),"
    f" INTERVAL '{CORROBORATION_WINDOW}'), INTERVAL '{CORROBORATION_WINDOW_MAX}')")

# %(since)s bounds what the statement reads. refresh() passes, per kind,
# now() - 2 x max_assert_seconds: anything older serves `unknown` whatever we
# conclude about it, and its state_current row was written while it was still
# inside the window. It used to be unbounded — every 2 minutes, a DISTINCT ON
# over the kind's whole history, decompressing every daily chunk to find the
# newest row per key (audit F291/F120). '-infinity' is the full recompute.
REFRESH_SQL = f"""
WITH grp AS (
  -- A unit's standing is its best witness; `p` is one source's own word.
  SELECT source_id,
         COALESCE(independence_group, 'src:' || source_id::text) AS unit,
         kind,
         {SINGLE_SOURCE_TRUST} * COALESCE(trust_weight,
               CASE WHEN kind = 'crowd'
                    THEN {UNEARNED_CROWD_TRUST} ELSE 1.0 END) AS p
  FROM source
),
cfg AS (
  SELECT state_kind, confidence_floor AS floor, {_WINDOW_SQL} AS w
  FROM state_kind_config
),
newest AS (
  -- Ties on observed_at are decided by standing, then by id, never by the
  -- order a hash join happened to return (audit F428: two sources in the same
  -- second flipped the served value between refreshes).
  SELECT DISTINCT ON (o.place_id, o.state_kind, o.direction)
         o.place_id, o.state_kind, o.direction, o.value, o.observed_at,
         o.source_id, g.p,
         COALESCE(k.floor, 0) AS floor,
         COALESCE(k.w, INTERVAL '{CORROBORATION_WINDOW}') AS w
  FROM state_observation o
  JOIN grp g ON g.source_id = o.source_id
  LEFT JOIN cfg k ON k.state_kind = o.state_kind
  WHERE o.state_kind = ANY(%(kinds)s) AND o.modality = 'assertion'
    AND o.observed_at >  %(since)s::timestamptz
    -- A stamp from the future is wrong, not early. Believing it served it as
    -- the freshest reading there is AND, through the upsert guard, blocked
    -- every later correction until the wall clock caught up (F117).
    AND o.observed_at <= now() + INTERVAL '{FUTURE_TOLERANCE}'
  ORDER BY o.place_id, o.state_kind, o.direction, o.observed_at DESC,
           g.p DESC, o.source_id
),
-- F017. Recency decides the value — except that inside one corroboration
-- window, a reading whose own standing is under the kind's floor (it could not
-- be served on its own) does not displace the last reading that could, when
-- the two disagree. The weaker reading is not lost: it lands in the window
-- below and counts as dissent. Past the window it describes a different
-- moment, and a lone caution is raised exactly as before (P2.4: one person may
-- raise an alarm alone). The LATERAL runs only for a weak newest reading.
latest AS (
  SELECT n.place_id, n.state_kind, n.direction, n.w,
         COALESCE(s.value, n.value)             AS value,
         COALESCE(s.observed_at, n.observed_at) AS observed_at,
         COALESCE(s.source_id, n.source_id)     AS source_id,
         n.observed_at                          AS upto
  FROM newest n
  LEFT JOIN LATERAL (
    SELECT o.value, o.observed_at, o.source_id
    FROM state_observation o
    JOIN grp g ON g.source_id = o.source_id
    WHERE n.p < n.floor
      AND o.place_id   = n.place_id
      AND o.state_kind = n.state_kind
      AND o.direction  = n.direction
      AND o.modality   = 'assertion'
      AND o.observed_at >= n.observed_at - n.w
      AND o.observed_at <  n.observed_at
      AND g.p >= n.floor
    ORDER BY o.observed_at DESC, g.p DESC, o.source_id
    LIMIT 1
  ) s ON s.value <> n.value
),
-- Every assertion in the moment `latest` describes: the window before it, and
-- (when a weak reading was held back) up to the newest reading.
win AS (
  SELECT l.place_id, l.state_kind, l.direction, l.value AS l_value,
         o.value, o.observed_at, g.unit, g.kind, g.p
  FROM latest l
  JOIN state_observation o
    ON  o.place_id   = l.place_id
    AND o.state_kind = l.state_kind
    AND o.direction  = l.direction
    AND o.modality   = 'assertion'
    AND o.observed_at BETWEEN l.observed_at - l.w AND l.upto
  JOIN grp g ON g.source_id = o.source_id
),
-- F429. Dissent is a unit's LAST word in the window, not every word: a unit
-- that said 'closed' at T-20 and 'open' at T-2 agrees with 'open' now, and was
-- being counted as contradicting itself.
unit_last AS (
  SELECT DISTINCT ON (place_id, state_kind, direction, unit)
         place_id, state_kind, direction, unit, value, l_value
  FROM win
  ORDER BY place_id, state_kind, direction, unit, observed_at DESC, p DESC
),
corr AS (
  SELECT l.place_id, l.state_kind, l.direction, l.value, l.observed_at, l.source_id,
         a.agree, a.noncrowd_agree, COALESCE(d.disagree, 0) AS disagree
  FROM latest l
  JOIN (
    SELECT place_id, state_kind, direction,
           COUNT(DISTINCT unit) FILTER (WHERE value = l_value) AS agree,
           -- Split the agreeing units by whether they are the crowd, so the
           -- gate below can tell "three strangers said so" from "a stranger
           -- agreed with the road channels".
           COUNT(DISTINCT unit) FILTER (
             WHERE value = l_value AND kind <> 'crowd') AS noncrowd_agree
    FROM win GROUP BY 1,2,3
  ) a USING (place_id, state_kind, direction)
  LEFT JOIN (
    SELECT place_id, state_kind, direction, COUNT(*) AS disagree
    FROM unit_last WHERE value <> l_value
    GROUP BY 1,2,3
  ) d USING (place_id, state_kind, direction)
),
-- Each agreeing UNIT's own reliability, best-witness-in-group.
unit_trust AS (
  SELECT place_id, state_kind, direction, unit, MAX(p) AS p
  FROM win
  WHERE value = l_value
  GROUP BY 1,2,3,4
),
-- The actual noisy-OR: 1 - PROD(1 - p_i) over independent agreeing units.
--
-- This replaces `(1 - 0.15^agree) * trust_weight(LATEST reporter)`, which
-- counted every unit as equally reliable and then scaled the total by whoever
-- happened to report most recently. With one kind of source that was a
-- harmless approximation. With a crowd it inverted: an unverified stranger
-- AGREEING with a road channel dropped a well-corroborated checkpoint from
-- 0.849 to 0.196, because their 0.20 scaled the whole product. Corroboration
-- made the system less sure, and one stranger could blind any checkpoint by
-- confirming it.
--
-- Per-unit, a weak witness can only ever add: 1-(1-0.85)(1-0.17) = 0.876. And
-- where every unit is a curated source with unmeasured trust it reduces to
-- exactly the old formula, which is why the checkpoint numbers do not move.
combined AS (
  SELECT place_id, state_kind, direction,
         1 - exp(SUM(ln(GREATEST(1 - p, 0.001)))) AS conf
  FROM unit_trust GROUP BY 1,2,3
)
INSERT INTO state_current
  (place_id,state_kind,direction,value,observed_at,source_id,base_confidence,
   independent_sources,contradicted_by,updated_at)
SELECT c.place_id, c.state_kind, c.direction, c.value, c.observed_at, c.source_id,
       LEAST(
         {MAX_CONFIDENCE},
         cb.conf
         * (1 - 0.25 * c.disagree::float8 / GREATEST(c.agree + c.disagree, 1))
       )::real,
       GREATEST(c.agree, 1), c.disagree, now()
FROM corr c
JOIN combined cb
  ON  cb.place_id = c.place_id AND cb.state_kind = c.state_kind
  AND cb.direction = c.direction
LEFT JOIN state_kind_config k ON k.state_kind = c.state_kind
-- P2.4. Withhold a reassuring value that only the crowd is asserting, until it
-- has the units the kind requires. Corroboration by anyone outside the crowd
-- satisfies it immediately; so does a second EARNED crowd unit.
WHERE NOT (
      c.value = ANY (COALESCE(k.crowd_gated_values, '{{}}'))
  AND c.noncrowd_agree = 0
  AND c.agree < COALESCE(k.crowd_min_units, 2)
)
ON CONFLICT (place_id, state_kind, direction) DO UPDATE SET
  value               = EXCLUDED.value,
  observed_at         = EXCLUDED.observed_at,
  source_id           = EXCLUDED.source_id,
  base_confidence     = EXCLUDED.base_confidence,
  independent_sources = EXCLUDED.independent_sources,
  contradicted_by     = EXCLUDED.contradicted_by,
  updated_at          = now()
-- Never move backwards onto an older reading — UNLESS the row being replaced
-- lies inside the window this statement just read, in which case the
-- statement saw it and decided against it: a future stamp (F117), a weak
-- reading now held back by F017's rule, an observation since re-marked as a
-- non-assertion. Under BELIEF_LOCK_SQL this statement's snapshot follows every
-- earlier writer's commit, so a stale snapshot can no longer land here (the
-- race the lock below was added for).
WHERE EXCLUDED.observed_at >= state_current.observed_at
   OR state_current.observed_at > %(since)s::timestamptz
"""


# Every writer that touches observations-then-belief serializes on this lock.
#
# WHY: a --full checkpoint rebuild ran concurrently with the 5-minute sync
# timer. The timer's refresh executed on a snapshot from BEFORE the rebuild's
# commit, its upserts then waited out the rebuild's row locks, and its
# stale-snapshot beliefs landed AFTER the clean ones — 20 rows carrying values
# the fixed parser no longer produces, with observed_at stamps far enough in
# the future that the `>=` guard blocked every later correction. Gate G2.5
# caught it. Serializing refresh against imports makes the interleaving
# impossible instead of unlikely.
BELIEF_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('palestine-v2-belief'))"


def _windows(cur, kinds, full: bool = False) -> list[tuple[str, object]]:
    """(kind, since) for each kind: how far back its refresh must read.

    now() - 2 x max_assert_seconds for a kind that already has belief. The
    full history ('-infinity') for a kind with no ceiling configured, or with
    no state_current row at all — the `--full` checkpoint rebuild deletes
    belief before re-importing, and a bounded refresh would then leave every
    checkpoint whose last reading is older than the window with no row, i.e.
    "never recorded" instead of "unknown, last known X". Per kind, so a slow
    kind's 6-day window never widens a checkpoint kind's 12 hours.
    """
    if full:
        return [(k, "-infinity") for k in kinds]
    cur.execute("""
        SELECT u.state_kind,
               -- as text: psycopg cannot load '-infinity' into a datetime
               (CASE WHEN k.max_assert_seconds IS NULL
                       OR NOT EXISTS (SELECT 1 FROM state_current sc
                                       WHERE sc.state_kind = u.state_kind)
                     THEN '-infinity'::timestamptz
                     ELSE now() - make_interval(secs => 2 * k.max_assert_seconds)
                END)::text
          FROM unnest(%s::text[]) AS u(state_kind)
          LEFT JOIN state_kind_config k USING (state_kind)""", (list(kinds),))
    return cur.fetchall()


def _refresh(cur, kinds, full: bool) -> int:
    cur.execute(BELIEF_LOCK_SQL)
    n = 0
    for kind, since in _windows(cur, kinds, full):
        cur.execute(REFRESH_SQL, {"kinds": [kind], "since": since})
        n += cur.rowcount
    return n


def refresh(kinds, conn=None, full: bool = False) -> int:
    """Recompute belief for `kinds`. Returns rows written.

    `full=True` reads each kind's whole history instead of its recent window —
    the control for the bounded refresh, and the thing to run after anything
    that rewrites old observations in place.
    """
    kinds = list(kinds)
    if conn is not None:
        with conn.cursor() as cur:
            return _refresh(cur, kinds, full)
    with connect() as own, own.cursor() as cur:
        n = _refresh(cur, kinds, full)
        own.commit()
        return n


def blocked_by_gate(kinds=None) -> list[dict]:
    """Rows the P2.4 gate is currently withholding.

    Exposed because a gate that silently drops things is indistinguishable from
    a gate that is not working. This is how you check it is doing something,
    and how a submitter can be told their report is waiting for corroboration
    rather than lost.
    """
    sql = REFRESH_SQL.split("INSERT INTO state_current")[0] + """
    SELECT c.place_id, c.state_kind, c.direction, c.value, c.observed_at,
           c.agree, c.noncrowd_agree, COALESCE(k.crowd_min_units, 2) AS need
    FROM corr c
    LEFT JOIN state_kind_config k ON k.state_kind = c.state_kind
    WHERE c.value = ANY (COALESCE(k.crowd_gated_values, '{}'))
      AND c.noncrowd_agree = 0
      AND c.agree < COALESCE(k.crowd_min_units, 2)
    ORDER BY c.observed_at DESC
    """
    out: list[dict] = []
    with connect() as conn, conn.cursor() as cur:
        for kind, since in _windows(cur, list(kinds) if kinds else _crowd_kinds(cur)):
            cur.execute(sql, {"kinds": [kind], "since": since})
            cols = [d[0] for d in cur.description]
            out += [dict(zip(cols, r)) for r in cur.fetchall()]
    out.sort(key=lambda r: r["observed_at"], reverse=True)
    return out


def _crowd_kinds(cur) -> list[str]:
    # Not retired (F120): 070 retired fuel availability without clearing
    # crowd_reportable, so this timer kept rebuilding three dead kinds every
    # two minutes and the engine kept offering them.
    cur.execute("""SELECT state_kind FROM state_kind_config
                    WHERE crowd_reportable AND retired_at IS NULL""")
    return [r[0] for r in cur.fetchall()]


def crowd_kinds() -> list[str]:
    with connect() as conn, conn.cursor() as cur:
        return _crowd_kinds(cur)
