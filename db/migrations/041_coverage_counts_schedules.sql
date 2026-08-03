-- 041 — coverage describes the SOURCE's pulse, not what we believe.
--
-- The coverage view counted only modality='assertion', so `power` — whose
-- NEDCO scraper now records every announced cut window (040) — still read
-- 'never_reported' while its source was demonstrably publishing. Coverage
-- answers "is anything feeding this kind, and when did it last speak";
-- belief stays assertion-only in resolve/belief.py, untouched. A scheduled
-- announcement is the source speaking. Questions, rejects and quarantined
-- rows are NOT counted: a quarantined feed is one we refuse to let vouch for
-- coverage, and a question is a human asking, not a source reporting.
CREATE OR REPLACE VIEW state_kind_coverage AS
SELECT k.state_kind,
       k.crowd_reportable,
       k.serving_mode,
       k.half_life_seconds,
       k.max_assert_seconds,
       COALESCE(o.observations, 0)          AS observations,
       COALESCE(o.non_crowd_sources, 0)     AS non_crowd_sources,
       o.last_observed_at,
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
     WHERE so.modality IN ('assertion', 'scheduled')
     GROUP BY 1
  ) o ON o.state_kind = k.state_kind;

COMMENT ON VIEW state_kind_coverage IS
  'Per state kind: is anything actually feeding this, and when did it last '
  'speak. Counts assertions and scheduled announcements — the source''s pulse '
  '— never questions, rejects or quarantined rows. Belief remains '
  'assertion-only in resolve/belief.py.';
