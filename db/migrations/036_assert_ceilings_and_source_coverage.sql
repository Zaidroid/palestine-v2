-- 036 — the third serving gate for the kinds that never got one, and a way to
-- say "nothing on earth reports this to us".
--
-- ── PART 1: the missing assert ceilings ─────────────────────────────────────
--
-- Seven state kinds had max_assert_seconds NULL, including BOTH FUELS — the
-- largest data kind in the system. Three gates are supposed to stand between a
-- reading and a served answer: the confidence floor, the staleness band, and
-- the assert ceiling. Fuel had two.
--
-- The fuel outage on 2026-08-01 proved decay alone was enough THAT time:
-- confidence reached 0.000 against a 0.30 floor within a day, so nothing stale
-- was served. But that only held because the half-life happened to be tuned
-- tightly (45 min). The ceiling is the gate that does NOT depend on the
-- half-life being right, which is the entire reason for having three.
--
-- ONE RULE, NO SPECIAL PLEADING: 4x the half-life, which is what checkpoint_flow
-- and checkpoint_status already use. Picking a bespoke number per kind invites
-- exactly the drift this migration is repairing. Where a kind genuinely needs a
-- different ratio, that is a decision to record here with a reason, not a
-- default to reach for.

UPDATE state_kind_config
   SET max_assert_seconds = half_life_seconds * 4
 WHERE max_assert_seconds IS NULL
   AND half_life_seconds IS NOT NULL;

-- fuel 45min -> 3h, cooking_gas 90min -> 6h, internet 6h -> 24h,
-- road_closure 6h -> 24h, power 12h -> 48h, water 12h -> 48h.

COMMENT ON COLUMN state_kind_config.max_assert_seconds IS
  'The hard ceiling on how old an observation may be and still be asserted, '
  'independent of how its confidence has decayed. Defaults to 4x the '
  'half-life. Was NULL for seven kinds including both fuels until 036 — the '
  'gate that catches a mis-tuned half-life was itself missing exactly where a '
  'mis-tuned half-life would have done the most damage.';

-- ── PART 2: telling "quiet" apart from "we have no source at all" ───────────
--
-- power, water, cooking_gas and crossing_status have never had a single
-- observation. Not one, ever. But /v2/coverage builds `live_states` from
-- state_serving, so a kind with no data simply does not appear, and every
-- other endpoint reports it as `unknown` — the same word used for a checkpoint
-- nobody has mentioned in an hour.
--
-- Those are completely different statements:
--
--   "unknown"   — we watch this, and nobody has said anything recently.
--   "no source" — nothing on earth reports this to us, and asking again
--                 tomorrow will not help.
--
-- Collapsing the second into the first is the exact dishonesty this system was
-- built to avoid. It is the same reasoning that put the Gaza crossings in the
-- database with no data (034) rather than leaving them out: visible ignorance
-- beats invisible ignorance.
--
-- Derived, never declared. A boolean column would be one more hand-maintained
-- field that drifts the moment a source appears — the PREFER_PLACE_KIND lesson
-- from 035. This reads the observations, so the answer corrects itself.

CREATE OR REPLACE VIEW state_kind_coverage AS
SELECT k.state_kind,
       k.crowd_reportable,
       k.serving_mode,
       k.half_life_seconds,
       k.max_assert_seconds,
       COALESCE(o.observations, 0)          AS observations,
       COALESCE(o.non_crowd_sources, 0)     AS non_crowd_sources,
       o.last_observed_at,
       -- The headline. A kind is sourceless when no NON-CROWD source has ever
       -- asserted it: crowd reports alone cannot establish a field, because
       -- P2.4 gates every reassuring value behind two independent units and a
       -- lone crowd unit can never clear that on its own. A field with only
       -- crowd behind it is caution-only in practice, and callers deserve to
       -- know that before they build a green tick on top of it.
       (COALESCE(o.non_crowd_sources, 0) = 0) AS no_source,
       CASE
         WHEN COALESCE(o.observations, 0) = 0        THEN 'never_reported'
         WHEN COALESCE(o.non_crowd_sources, 0) = 0   THEN 'crowd_only'
         WHEN o.last_observed_at < now() - make_interval(secs => k.max_assert_seconds)
                                                     THEN 'stale'
         ELSE 'live'
       END AS coverage_state
  FROM state_kind_config k
  LEFT JOIN (
    SELECT so.state_kind,
           count(*)                                              AS observations,
           count(DISTINCT so.source_id) FILTER (WHERE s.kind IS DISTINCT FROM 'crowd')
                                                                 AS non_crowd_sources,
           max(so.observed_at)                                   AS last_observed_at
      FROM state_observation so
      JOIN source s ON s.source_id = so.source_id
     WHERE so.modality = 'assertion'
     GROUP BY 1
  ) o ON o.state_kind = k.state_kind;

COMMENT ON VIEW state_kind_coverage IS
  'Per state kind: is anything actually feeding this, and when did it last '
  'speak. Exists so the API can say "no source" instead of "unknown" for '
  'power, water, cooking_gas and crossing_status, which have never had a '
  'single observation. Derived from state_observation rather than declared in '
  'a column, so it corrects itself the day a source appears.';
