-- Gate 2 — checkpoint accuracy invariants.
--
-- Each check corresponds to a defect measured in v1 or in an earlier version of
-- this pipeline. They are asserted rather than described because every one of
-- them is a silent failure: nothing errors, the API keeps answering, and the
-- answer is confidently wrong.
--
--   docker exec -i palestine-v2-db psql -U <user> -d palestine_v2 -f - < tests/test_gate2_checkpoints.sql

\echo '--- G2.1: nothing is asserted past its kind''s absolute age ceiling ---'
-- v1 asserts `open` with no decay; 166 of its readings rest on evidence over a
-- day old, the worst at 90 hours. This is the property that makes that
-- impossible here rather than merely unlikely.
SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || COUNT(*) || ' assertions past max_assert_seconds'
       END AS g2_max_age
FROM state_serving s
JOIN state_kind_config k USING (state_kind)
WHERE s.state_kind LIKE 'checkpoint%'
  AND s.value <> 'unknown'
  AND k.max_assert_seconds IS NOT NULL
  AND s.age_minutes * 60 > k.max_assert_seconds;

\echo '--- G2.2: no reading is asserted below its confidence floor ---'
SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || COUNT(*) || ' asserted under floor'
       END AS g2_floor
FROM state_serving s
JOIN state_kind_config k USING (state_kind)
WHERE s.state_kind LIKE 'checkpoint%'
  AND s.value <> 'unknown' AND s.confidence < k.confidence_floor;

\echo '--- G2.3: a decayed reading is preserved, never erased ---'
-- "unknown" must mean "we will not assert this", not "we forgot it". The
-- caller needs the last reading and its age to say something useful.
SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || COUNT(*) || ' unknown rows lost their last value'
       END AS g2_last_known_retained
FROM state_serving
WHERE state_kind LIKE 'checkpoint%'
  AND value = 'unknown' AND (last_known_value IS NULL OR last_known_value = 'unknown');

\echo '--- G2.4: questions never became evidence ---'
-- 12,536 of v1's stored updates come from interrogative lines, 4,566 of them
-- recorded as `open`. People ask about checkpoints they fear are CLOSED, so the
-- false evidence concentrates exactly where being wrong is most expensive.
--
-- The invariant is that a non-assertion never becomes BELIEF — not that no
-- non-assertion row may exist. The original form asserted the latter, which was
-- equivalent while `question` was the only reason for one. It stopped being
-- equivalent when migration 033 added `quarantined`: a source collected in full
-- while its accuracy is established. Palhub's 26,162 rows are exactly that, and
-- the old check called their existence a failure while the property it cared
-- about — none of them reaching a served value — was holding perfectly.
--
-- So the check now follows the row through to state_current, which is the thing
-- that would actually hurt somebody.
SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || COUNT(*) || ' beliefs built on a non-assertion'
       END AS g2_questions_excluded
FROM state_current sc
WHERE sc.state_kind IN ('checkpoint_flow','checkpoint_idf','checkpoint_police',
                        'checkpoint_settlers','checkpoint_inspection')
  AND NOT EXISTS (
        SELECT 1 FROM state_observation o
         WHERE o.place_id = sc.place_id AND o.state_kind = sc.state_kind
           AND o.direction = sc.direction AND o.observed_at = sc.observed_at
           AND o.source_id = sc.source_id AND o.modality = 'assertion');

\echo '--- G2.4b: quarantined sources are collected but never served ---'
-- The other half of the same property, stated positively: a quarantined source
-- must be accumulating rows AND authoring none of the belief.
SELECT CASE
         WHEN (SELECT count(*) FROM state_current sc JOIN source s USING (source_id)
                WHERE s.key = 'tg_palhubapproad') > 0
           THEN 'FAIL: a quarantined source is authoring served belief'
         ELSE 'PASS (' || (SELECT count(*) FROM state_observation o
                            JOIN source s USING (source_id)
                           WHERE s.key = 'tg_palhubapproad'
                             AND o.modality = 'quarantined')
              || ' rows collected, 0 served)'
       END AS g2_quarantine_holds;

\echo '--- G2.5: every belief traces to an observation that supports it ---'
SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || COUNT(*) || ' state rows with no matching observation'
       END AS g2_belief_grounded
FROM state_current sc
WHERE sc.state_kind LIKE 'checkpoint%' AND sc.state_kind <> 'checkpoint_status'
  AND NOT EXISTS (
    SELECT 1 FROM state_observation o
    WHERE o.place_id = sc.place_id AND o.state_kind = sc.state_kind
      AND o.direction = sc.direction AND o.value = sc.value
      AND o.observed_at = sc.observed_at);

\echo '--- G2.6: corroboration counts INDEPENDENT groups, not messages ---'
-- Nine of these channels agree 99.5-100% of the time over hundreds of chances
-- to differ. Counting them separately turns one report into "confirmed by
-- nine", which is worse than no corroboration model at all.
SELECT CASE WHEN bad = 0 THEN 'PASS (max ' || mx || ' independent sources)'
            ELSE 'FAIL: ' || bad || ' rows claim more sources than there are groups'
       END AS g2_copy_collapse
FROM (
  SELECT COUNT(*) FILTER (WHERE sc.independent_sources > (
           SELECT COUNT(DISTINCT COALESCE(independence_group, 'src:' || source_id::text))
           FROM source)) AS bad,
         MAX(sc.independent_sources) AS mx
  FROM state_current sc WHERE sc.state_kind LIKE 'checkpoint%'
) x;

\echo '--- G2.7: no unservable place is ever an answer ---'
-- 86 of the imported places were sentence fragments or duplicate spellings
-- ("الجيش نزل ع صره" — "the army went down to Sarra"). They stay resolvable
-- and stop being served.
SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || COUNT(*) || ' merged/unservable places in the serving view'
       END AS g2_no_fragments_served
FROM checkpoint_serving c
JOIN place p USING (place_id)
WHERE NOT p.servable OR p.merged_into IS NOT NULL;

\echo '--- G2.8: observations survive re-import (no-data-loss) ---'
SELECT CASE WHEN obs >= 90000 THEN 'PASS (' || obs || ' observations, ' || cur || ' current)'
            ELSE 'FAIL: only ' || obs || ' observations retained'
       END AS g2_history_retained
FROM (SELECT (SELECT COUNT(*) FROM state_observation WHERE state_kind LIKE 'checkpoint%') AS obs,
             (SELECT COUNT(*) FROM state_current    WHERE state_kind LIKE 'checkpoint%') AS cur) x;

\echo '--- G2.9: presence never displaces flow ---'
-- v1 stores one status on one axis, so an army sighting overwrote the answer to
-- "can I get through?" — the two flipped on the same place within ten minutes
-- 1,889 times. They are separate kinds here and must be able to coexist.
SELECT CASE WHEN COUNT(*) > 0 THEN 'PASS (' || COUNT(*) || ' places hold flow AND presence together)'
            ELSE 'INFO: no place currently has both (may be quiet, not broken)'
       END AS g2_axes_coexist
FROM checkpoint_serving
WHERE direction = 'both' AND flow <> 'unknown' AND present <> '{}';

\echo '--- G2.10: a sighting of ABSENCE is never served as presence ---'
-- "no army here" is recorded as value 'absent' on the same state_kind whose
-- NAME is 'checkpoint_idf'. The presence array used to be built with
-- `WHERE value <> 'unknown'` and then take the kind name as the answer, which
-- would have published "no army" as ARMY PRESENT. Same family as "hawmash
-- salik" matching "mish salik": the sign of the fact is lost, the fact still
-- looks fine.
SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS (no absent reading published as present)'
            ELSE 'FAIL: ' || COUNT(*) || ' places report someone as present who was reported ABSENT'
       END AS g2_absence_not_presence
FROM checkpoint_serving c
JOIN state_serving s
  ON s.place_id = c.place_id
 AND s.state_kind = 'checkpoint_' || (SELECT w FROM unnest(c.present) w LIMIT 1)
WHERE cardinality(c.present) > 0 AND s.value = 'absent';

\echo '--- G2.11: presence is served as a SIGHTING, not a state ---'
-- An army patrol has a MEASURED 15-minute half-life and is reported for a given
-- place every ~35 hours. Presence therefore cannot answer "is the army there
-- now?" and must not be configured as if it could. If this fails, someone has
-- loosened the cap to make a coverage number look better.
SELECT CASE WHEN COUNT(*) = 4 THEN 'PASS (all 4 presence kinds are sightings)'
            ELSE 'FAIL: only ' || COUNT(*) || ' of 4 presence kinds marked sighting'
       END AS g2_presence_is_sighting
FROM state_kind_config
WHERE state_kind IN ('checkpoint_idf','checkpoint_police',
                     'checkpoint_settlers','checkpoint_inspection')
  AND serving_mode = 'sighting';

\echo '--- G2.12: absence is actually being recorded ---'
-- 28.31% of presence mentions in the corpus are negated. Discarding them left
-- `present` as the ONLY value the kind could take, so it could never be
-- contradicted and its persistence fit returned 1.00 at every lag.
SELECT CASE WHEN n >= 500 THEN 'PASS (' || n || ' absence observations)'
            ELSE 'FAIL: only ' || n || ' — negated presence is being discarded again'
       END AS g2_absence_recorded
FROM (SELECT COUNT(*) AS n FROM state_observation
      WHERE state_kind LIKE 'checkpoint_%' AND value = 'absent') x;

\echo '--- context: what is being served right now ---'
SELECT flow, COUNT(*) AS n, ROUND(AVG(age_minutes)) AS avg_age_min,
       ROUND(AVG(confidence)::numeric, 3) AS avg_conf
FROM checkpoint_serving WHERE direction = 'both'
GROUP BY flow ORDER BY n DESC;

\echo '--- G2.13: every crowd-reportable kind has decided where its data lives ---'
-- place_kind was a dict in Python and the same silent failure happened THREE
-- times: crowd checkpoint reports landing on towns, MCP history returning
-- empty, crowd crossing reports landing on Rafah the city rather than Rafah the
-- crossing. Each time a new state kind had been added without anyone
-- remembering the list, and each time the report was accepted and stored
-- somewhere no other source would ever meet it.
--
-- NULL is a valid answer (locality-level) but it must be a DECISION. A kind
-- reaching production without one is how this recurs.
SELECT CASE WHEN count(*) = 0
            THEN 'PASS (' || (SELECT count(*) FROM state_kind_config
                               WHERE place_kind IS NOT NULL)
                 || ' kinds pinned to a place kind)'
            ELSE 'FAIL: ' || string_agg(state_kind, ', ')
                 || ' — crowd-reportable, point-shaped, and no place_kind'
       END AS g2_place_kind_decided
FROM state_kind_config
WHERE crowd_reportable
  AND place_kind IS NULL
  -- These genuinely describe a locality; anything else point-shaped must say so.
  AND state_kind NOT IN ('power','water','internet','weather','road_closure');

\echo '--- G2.14: a kind''s place_kind names a place kind that exists ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || string_agg(DISTINCT k.place_kind, ', ')
                 || ' is not a kind any place has' END AS g2_place_kind_real
FROM state_kind_config k
WHERE k.place_kind IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM place p WHERE p.kind::text = k.place_kind);
