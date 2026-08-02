-- 027 - a sighting of ABSENCE must never be served as presence.
--
-- Migration 025 started recording "no army" as value 'absent' on the presence
-- state kinds. This view built its present array with
--
--     WHERE x.value <> 'unknown'
--
-- and then took the state_kind NAME as the answer, so any 'absent' reading
-- fresh enough to clear the gate would have been published as army PRESENT.
-- Exactly inverted, on the axis where inversion is most expensive.
--
-- It had not fired yet: only four presence readings in the whole system
-- currently clear the 45-minute cap and all four happen to be 'present'. That
-- is timing, not safety - the first fresh "no army here" would have done it.
-- Same shape as "hawmash salik" matching "mish salik", and as the negated
-- presence that used to be discarded: the SIGN of the fact was lost while the
-- fact itself still looked fine.
--
-- Absence is published in its own array, appended last because CREATE OR
-- REPLACE VIEW may only add columns at the end. "No army reported at Huwara
-- ten minutes ago" is worth as much to somebody planning a journey as the
-- sighting is, and it was already being collected - 1,948 observations of it.

CREATE OR REPLACE VIEW checkpoint_serving AS
WITH travel AS (
         SELECT unnest(ARRAY['inbound'::text, 'outbound'::text, 'both'::text]) AS dir
        ), flow AS (
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
    COALESCE(pr.absent, ARRAY[]::text[]) AS absent
   FROM flow f
     JOIN place p ON p.place_id = f.place_id
     LEFT JOIN presence pr ON pr.place_id = f.place_id AND pr.direction = f.direction
  WHERE p.servable;
