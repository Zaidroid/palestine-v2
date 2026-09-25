-- 081 — the default checkpoint answer sees every direction.
--
-- checkpoint_serving (014, redefined in 027) fans each checkpoint out over three
-- travel rows and picks, per row, the freshest reading from {that direction,
-- 'both'}. For the inbound and outbound rows that is the documented doctrine
-- (014: a fresher 'both' report is the better answer for a directional
-- traveller) and it is kept unchanged here.
--
-- For the 'both' row the same filter reduces to `s.direction = 'both'`: it
-- never looked at a direction-specific reading at all. And the 'both' row is
-- the one every default answer reads — /v2/checkpoints/status (direction
-- defaults to both), MCP checkpoint_status, /v2/checkpoints/summary and its
-- closed_now list, /v2/crossings, insights. Audit F008/F016/F332, reproduced in
-- tests/test_belief_serving.py:
--
--   13:00 'حوارة سالك' (both); 14:05 'حوارة مغلق للداخل ومغلق للخارج', which
--   the parser reads as two direction-explicit closures and no 'both' fact.
--   The inbound and outbound rows said closed; the default row said OPEN,
--   passable, and MCP spoke it as 'حوارة: سالك'. A traveller was sent to a
--   checkpoint closed in both directions.
--
--   A checkpoint reported only per direction had no 'both' row at all, so the
--   default answer was "no checkpoint reading has ever been recorded here"
--   while a closure was minutes old, and the summary did not count it.
--
-- palhub's bulletin states every checkpoint per direction (P1-A.1 promotes it),
-- so this was about to become the common case rather than the edge.
--
-- THE RULE: the 'both' travel row is the MORE RESTRICTIVE of the inbound and
-- outbound travel rows —
--
--     closed > congested > slow > unknown > open
--
-- and a travel direction nobody has reported counts as unknown. `unknown`
-- ranks above `open` because the default row answers "can I get through?" for
-- a traveller whose direction we do not know; it may say open only when BOTH
-- directions are open on current evidence. That is the same asymmetry as P2.4:
-- a caution may stand on partial evidence, an all-clear may not. The cautions
-- rank above unknown because a closure seen in one direction is a closure at
-- the checkpoint, and hiding it behind "we don't know the other side" would
-- throw away the fact most worth saying.
--
-- On a tie the caution takes its FRESHEST confirmation and the all-clear its
-- OLDEST (the weakest link), so "open, 3 minutes ago" is never said of a
-- checkpoint whose other direction was last seen open three hours ago.
-- reported_for names the direction the chosen reading was filed for, so a
-- caller can see a default answer that came from one side.
--
-- WHAT IS UNCHANGED: when a checkpoint has only 'both' readings (13,096 of
-- 14,375 flow readings when PLAN §4 R3 was measured) the inbound and outbound
-- rows are that one reading, so the 'both' row is exactly what it was. The
-- presence arrays are untouched.
--
-- The CTE is NOT MATERIALIZED so a caller's `place_id = …` still reaches
-- state_serving (one checkpoint's rows, not every checkpoint's) as it did when
-- `flow` was referenced once.
--
-- Same columns in the same order as 027. Rollback: re-run the CREATE OR REPLACE
-- VIEW checkpoint_serving from 027_absence_is_not_presence.sql.

CREATE OR REPLACE VIEW checkpoint_serving AS
WITH travel AS (
         SELECT unnest(ARRAY['inbound'::text, 'outbound'::text]) AS dir
        ), flow_dir AS NOT MATERIALIZED (
         -- 014's doctrine, unchanged: per travel direction, the freshest of
         -- {that direction, 'both'}; on a tie the direction-specific report.
         SELECT DISTINCT ON (s.place_id, t.dir) s.place_id,
            t.dir AS direction,
            s.value,
            s.last_known_value,
            s.observed_at,
            s.age_minutes,
            s.confidence,
            s.staleness_band,
            s.half_life_seconds,
            s.independent_sources,
            s.contradicted_by,
            s.cadence_measured,
            s.direction AS reported_for
           FROM state_serving s
             CROSS JOIN travel t
          WHERE s.state_kind = 'checkpoint_flow'::text AND (s.direction = t.dir OR s.direction = 'both'::text)
          ORDER BY s.place_id, t.dir, s.observed_at DESC, (s.direction = t.dir) DESC
        ), flow_both AS (
         SELECT DISTINCT ON (x.place_id) x.place_id,
            'both'::text AS direction,
                CASE
                    -- one direction open, the other never reported: not an
                    -- all-clear (the open stays visible as last_known_flow)
                    WHEN x.value = 'open'::text AND x.n_dirs < 2 THEN 'unknown'::text
                    ELSE x.value
                END AS value,
            x.last_known_value,
            x.observed_at,
            x.age_minutes,
            x.confidence,
            x.staleness_band,
            x.half_life_seconds,
            x.independent_sources,
            x.contradicted_by,
            x.cadence_measured,
            x.reported_for
           FROM ( SELECT f.place_id, f.direction, f.value, f.last_known_value,
                    f.observed_at, f.age_minutes, f.confidence, f.staleness_band,
                    f.half_life_seconds, f.independent_sources, f.contradicted_by,
                    f.cadence_measured, f.reported_for,
                    count(*) OVER (PARTITION BY f.place_id) AS n_dirs
                   FROM flow_dir f) x
          ORDER BY x.place_id,
                CASE x.value
                    WHEN 'closed'::text THEN 4
                    WHEN 'congested'::text THEN 3
                    WHEN 'slow'::text THEN 2
                    WHEN 'open'::text THEN 0
                    ELSE 1
                END DESC,
                CASE WHEN x.value = ANY (ARRAY['closed'::text, 'congested'::text, 'slow'::text])
                     THEN x.observed_at END DESC NULLS LAST,
                x.observed_at,
                x.direction
        ), flow AS (
         SELECT flow_dir.place_id, flow_dir.direction, flow_dir.value,
            flow_dir.last_known_value, flow_dir.observed_at, flow_dir.age_minutes,
            flow_dir.confidence, flow_dir.staleness_band, flow_dir.half_life_seconds,
            flow_dir.independent_sources, flow_dir.contradicted_by,
            flow_dir.cadence_measured, flow_dir.reported_for
           FROM flow_dir
        UNION ALL
         SELECT flow_both.place_id, flow_both.direction, flow_both.value,
            flow_both.last_known_value, flow_both.observed_at, flow_both.age_minutes,
            flow_both.confidence, flow_both.staleness_band, flow_both.half_life_seconds,
            flow_both.independent_sources, flow_both.contradicted_by,
            flow_both.cadence_measured, flow_both.reported_for
           FROM flow_both
        ), presence AS (
         SELECT x.place_id,
            x.direction,
            array_agg(x.who ORDER BY x.who) FILTER (WHERE x.value = 'present') AS present,
            array_agg(x.who ORDER BY x.who) FILTER (WHERE x.value = 'absent') AS absent,
            min(x.age_minutes) AS presence_age_minutes,
            max(x.confidence) AS presence_confidence
           FROM ( SELECT DISTINCT ON (s.place_id, t.dir, s.state_kind) s.place_id,
                    t.dir AS direction,
                    replace(s.state_kind, 'checkpoint_'::text, ''::text) AS who,
                    s.value,
                    s.age_minutes,
                    s.confidence
                   FROM state_serving s
                     CROSS JOIN ( SELECT unnest(ARRAY['inbound'::text, 'outbound'::text, 'both'::text]) AS dir) t
                  WHERE (s.state_kind = ANY (ARRAY['checkpoint_idf'::text, 'checkpoint_police'::text, 'checkpoint_settlers'::text, 'checkpoint_inspection'::text])) AND (s.direction = t.dir OR s.direction = 'both'::text)
                  ORDER BY s.place_id, t.dir, s.state_kind, s.observed_at DESC, (s.direction = t.dir) DESC) x
          WHERE x.value = ANY (ARRAY['present'::text, 'absent'::text])
          GROUP BY x.place_id, x.direction
        )
 SELECT p.place_id,
    p.name_ar,
    p.name_en,
    p.kind AS place_kind,
    p.centroid,
    f.direction,
    f.value AS flow,
    f.last_known_value AS last_known_flow,
    f.reported_for,
    f.observed_at,
    f.age_minutes,
    f.confidence,
    f.staleness_band,
    f.half_life_seconds,
    f.cadence_measured,
    f.independent_sources,
    f.contradicted_by,
    COALESCE(pr.present, ARRAY[]::text[]) AS present,
    pr.presence_age_minutes,
        CASE f.value
            WHEN 'open'::text THEN true
            WHEN 'slow'::text THEN true
            WHEN 'congested'::text THEN true
            WHEN 'closed'::text THEN false
            ELSE NULL::boolean
        END AS passable,
    COALESCE(pr.absent, ARRAY[]::text[]) AS absent
   FROM flow f
     JOIN place p ON p.place_id = f.place_id
     LEFT JOIN presence pr ON pr.place_id = f.place_id AND pr.direction = f.direction
  WHERE p.servable;

COMMENT ON VIEW checkpoint_serving IS
  'One row per (checkpoint, travel direction). inbound/outbound: the freshest of '
  '{that direction, both} (014). both: the more restrictive of the two travel '
  'rows, closed > congested > slow > unknown > open, a direction never reported '
  'counting as unknown (081, audit F008/F016/F332).';
