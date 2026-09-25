-- 079 — the default ('both') checkpoint row is the WORSE of the two travel directions.
--
-- Audit 2026-09-25, F008 (critical) / F016 / F377. checkpoint_serving built its
-- 'both' travel row only from readings filed as 'both', and every default
-- surface reads that row (/v2/checkpoints/status, the summary, crossings, the
-- MCP checkpoint_status). So:
--
--     13:00  'حوارة سالك'                                  -> both = open
--     14:05  'حوارة مغلق للداخل ومغلق للخارج'              -> inbound = closed, outbound = closed
--
-- served "حوارة: سالك" for as long as the 13:00 reading lived. Direction is 9 %
-- of readings today (PLAN §4 R3); promoting palhub (P1-A.1), whose bulletin
-- carries in/out for every row, would have made this the common case.
--
-- Now: inbound and outbound are resolved exactly as before (the freshest of
-- {that direction, 'both'}, a tie to the direction-specific report), and the
-- 'both' row is the more restrictive of the two (closed > congested > slow >
-- unknown > open), freshest first among equals. 'unknown' outranks 'open' so
-- that one open direction beside an unknown or never-read one never makes the
-- default row say open (the last_known_flow keeps the open reading). `reported_for` still names the
-- report the row came from, and a new last column, `differs_by_direction`, says
-- when the two travel directions disagree.
--
-- The recency doctrine between a 'both' report and an explicit direction is
-- unchanged and now pinned by tests/test_belief_serving.py (F377).
--
-- Rollback: re-run the CREATE OR REPLACE VIEW checkpoint_serving statement in
-- 027_absence_is_not_presence.sql after `DROP VIEW checkpoint_serving` (the
-- appended column cannot be removed by CREATE OR REPLACE).

CREATE OR REPLACE VIEW checkpoint_serving AS
WITH travel AS (
         SELECT unnest(ARRAY['inbound'::text, 'outbound'::text, 'both'::text]) AS dir
        ), dirflow AS (
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
             CROSS JOIN (VALUES ('inbound'::text), ('outbound'::text)) t(dir)
          WHERE s.state_kind = 'checkpoint_flow'::text AND (s.direction = t.dir OR s.direction = 'both'::text)
          ORDER BY s.place_id, t.dir, s.observed_at DESC, (s.direction = t.dir) DESC
        ), bothflow AS (
         SELECT DISTINCT ON (d.place_id) d.place_id,
            'both'::text AS direction,
            CASE WHEN d.ndirs < 2 AND d.value = 'open' THEN 'unknown' ELSE d.value END AS value,
            CASE WHEN d.ndirs < 2 AND d.value = 'open' THEN 'open' ELSE d.last_known_value END AS last_known_value,
            d.observed_at,
            d.age_minutes,
            d.confidence,
            d.staleness_band,
            d.half_life_seconds,
            d.independent_sources,
            d.contradicted_by,
            d.cadence_measured,
            d.reported_for
           FROM (SELECT d.*, count(*) OVER (PARTITION BY d.place_id) AS ndirs
                   FROM dirflow d) d
          ORDER BY d.place_id,
                   -- 'unknown' outranks 'open' (Zaid, 2026-09-25): one open
                   -- direction beside an unknown one never makes the default
                   -- row say open; a closure, jam or slow in either direction
                   -- still does. ndirs < 2 = the other direction was never read.
                   CASE d.value WHEN 'closed' THEN 4 WHEN 'congested' THEN 3
                                WHEN 'slow' THEN 2 WHEN 'open' THEN 0 ELSE 1 END DESC,
                   d.observed_at DESC
        ), flow AS (
         SELECT * FROM dirflow
         UNION ALL
         SELECT * FROM bothflow
        ), differs AS (
         SELECT place_id, count(DISTINCT value) > 1 AS differs_by_direction
           FROM dirflow GROUP BY place_id
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
                     CROSS JOIN travel t
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
    COALESCE(pr.absent, ARRAY[]::text[]) AS absent,
    COALESCE(df.differs_by_direction, false) AS differs_by_direction
   FROM flow f
     JOIN place p ON p.place_id = f.place_id
     LEFT JOIN presence pr ON pr.place_id = f.place_id AND pr.direction = f.direction
     LEFT JOIN differs df ON df.place_id = f.place_id
  WHERE p.servable;

COMMENT ON VIEW checkpoint_serving IS
  'One row per (checkpoint, travel direction). inbound/outbound: the freshest of that direction or a both report. both: the more restrictive of inbound and outbound, unknown outranking open (079), with differs_by_direction. Flow and presence stay on separate axes. The API reads this, never state_current.';
