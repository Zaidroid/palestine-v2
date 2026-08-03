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
CORROBORATION_WINDOW = "30 minutes"

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
# move a served value alone, and does not need to be stopped by a rule that
# names newcomers: they simply have not earned it yet.
#
# Not zero, deliberately. Zero would make a crowd report incapable of ever
# contributing, and Loop A scores submitters by comparing them against the
# consensus of other units whether or not their report was served — so a real
# reporter climbs out of 0.20 by being right, without ever having needed to be
# believed first.
UNEARNED_CROWD_TRUST = 0.20

REFRESH_SQL = f"""
WITH grp AS (
  SELECT source_id,
         COALESCE(independence_group, 'src:' || source_id::text) AS unit,
         kind
  FROM source
),
latest AS (
  SELECT DISTINCT ON (place_id, state_kind, direction)
         place_id, state_kind, direction, value, observed_at, source_id
  FROM state_observation
  WHERE state_kind = ANY(%(kinds)s) AND modality = 'assertion'
  ORDER BY place_id, state_kind, direction, observed_at DESC
),
corr AS (
  SELECT l.place_id, l.state_kind, l.direction, l.value, l.observed_at, l.source_id,
         COUNT(DISTINCT g.unit) FILTER (WHERE o.value =  l.value) AS agree,
         COUNT(DISTINCT g.unit) FILTER (WHERE o.value <> l.value) AS disagree,
         -- Split the agreeing units by whether they are the crowd, so the
         -- gate below can tell "three strangers said so" from "a stranger
         -- agreed with the road channels".
         COUNT(DISTINCT g.unit) FILTER (
           WHERE o.value = l.value AND g.kind <> 'crowd') AS noncrowd_agree
  FROM latest l
  JOIN state_observation o
    ON  o.place_id   = l.place_id
    AND o.state_kind = l.state_kind
    AND o.direction  = l.direction
    AND o.modality   = 'assertion'
    AND o.observed_at BETWEEN l.observed_at - INTERVAL '{CORROBORATION_WINDOW}'
                          AND l.observed_at
  JOIN grp g ON g.source_id = o.source_id
  GROUP BY 1,2,3,4,5,6
),
-- Each agreeing UNIT's own reliability, best-witness-in-group.
unit_trust AS (
  SELECT l.place_id, l.state_kind, l.direction, g.unit,
         MAX({SINGLE_SOURCE_TRUST} * COALESCE(s.trust_weight,
               CASE WHEN s.kind = 'crowd'
                    THEN {UNEARNED_CROWD_TRUST} ELSE 1.0 END)) AS p
  FROM latest l
  JOIN state_observation o
    ON  o.place_id   = l.place_id
    AND o.state_kind = l.state_kind
    AND o.direction  = l.direction
    AND o.modality   = 'assertion'
    AND o.value      = l.value
    AND o.observed_at BETWEEN l.observed_at - INTERVAL '{CORROBORATION_WINDOW}'
                          AND l.observed_at
  JOIN grp g ON g.source_id = o.source_id
  JOIN source s ON s.source_id = o.source_id
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
WHERE EXCLUDED.observed_at >= state_current.observed_at
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


def refresh(kinds, conn=None) -> int:
    """Recompute belief for `kinds`. Returns rows written."""
    kinds = list(kinds)
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(BELIEF_LOCK_SQL)
            cur.execute(REFRESH_SQL, {"kinds": kinds})
            return cur.rowcount
    with connect() as own, own.cursor() as cur:
        cur.execute(BELIEF_LOCK_SQL)
        cur.execute(REFRESH_SQL, {"kinds": kinds})
        n = cur.rowcount
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
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, {"kinds": list(kinds) if kinds else _crowd_kinds(cur)})
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _crowd_kinds(cur) -> list[str]:
    cur.execute("SELECT state_kind FROM state_kind_config WHERE crowd_reportable")
    return [r[0] for r in cur.fetchall()]


def crowd_kinds() -> list[str]:
    with connect() as conn, conn.cursor() as cur:
        return _crowd_kinds(cur)
