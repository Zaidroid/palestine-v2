-- Gate 1 (Phase 1, fuel vertical) — safety assertions.
--
-- The headline requirement: "ZERO stations served available with age > 2x
-- half-life". This is the fuel analogue of v1's stale-open checkpoint bug —
-- during a shortage, an available reading that is actually hours old sends
-- someone driving across a governorate to an empty pump.
\set ON_ERROR_STOP on

\echo '--- G1.1: no station served "available" beyond 2x its half-life ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' stale rows served as available'
       END AS g1_no_stale_available
FROM state_serving s
JOIN state_kind_config k ON k.state_kind = s.state_kind
WHERE s.state_kind LIKE 'fuel%'
  AND s.value = 'available'
  AND s.age_minutes > (k.half_life_seconds * 2 / 60);

\echo '--- G1.2: no negative ages (the UTC/local timestamp bug) ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' rows dated in the future'
       END AS g1_no_future_observations
FROM state_serving WHERE age_minutes < 0;

\echo '--- G1.3: decayed readings become unknown, last value retained ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' rows lost last_known_value'
       END AS g1_last_known_retained
FROM state_serving
WHERE value = 'unknown' AND last_known_value IS NULL;

\echo '--- G1.4: every fuel state resolves to a place with geometry ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' fuel states without geometry'
       END AS g1_all_geolocated
FROM state_serving s
WHERE s.state_kind LIKE 'fuel%' AND s.centroid IS NULL;

\echo '--- G1.5: observations are retained, not overwritten (no-data-loss) ---'
-- state_current holds one row per (place,kind); state_observation must hold the
-- full history behind it.
SELECT CASE WHEN obs > cur THEN 'PASS (' || obs || ' observations behind ' || cur || ' current)'
            ELSE 'FAIL: history not accumulating'
       END AS g1_history_retained
FROM (SELECT (SELECT count(*) FROM state_observation) AS obs,
             (SELECT count(*) FROM state_current)     AS cur) x;

\echo '--- G1.6: half-life matches the measured feed cadence ---'
SELECT CASE WHEN half_life_seconds = 2700 THEN 'PASS'
            ELSE 'FAIL: fuel half-life is ' || half_life_seconds || 's, expected 2700'
       END AS g1_cadence_tuned
FROM state_kind_config WHERE state_kind = 'fuel_diesel';

\echo '--- context: current fuel picture ---'
SELECT state_kind,
       count(*) FILTER (WHERE value='available')   AS available,
       count(*) FILTER (WHERE value='unavailable') AS unavailable,
       count(*) FILTER (WHERE value='unknown')     AS unknown,
       round(avg(age_minutes))                     AS avg_age_min
FROM state_serving WHERE state_kind LIKE 'fuel%' GROUP BY 1 ORDER BY 1;

\echo '--- G1.7: image-derived fuel is QUARANTINED, never asserted ---'
-- Every card in a sweep carries the same "آخر تحديث", so it is the render time
-- and says nothing about when a station was seen. That is the exact shape of
-- the palhub ROAD bulletin, which looked live behind a median age of 24 hours
-- (P6.1). Nothing read from an image may be believed until it has been
-- measured against the 2026-08-01 overlap, when the channel posted text AND
-- cards for nine hours. If this ever fails, unmeasured data is being served.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' image-derived rows are modality='
                 || string_agg(DISTINCT modality, '/') || ', not quarantined'
       END AS g1_image_quarantined
FROM state_observation
WHERE attrs->>'via' = 'image' AND modality <> 'quarantined';

\echo '--- G1.8: the image feed is not a SECOND witness for the same channel ---'
-- source `telegram_fuel` (the tee-spool loader) and `tg_palhubappfuel` (the
-- poller) are the SAME Telegram channel read two ways. If image rows landed on
-- the poller's source, one witness would hold two votes and the belief model
-- would read a station confirmed by nobody as confirmed by two. Copy-collapse
-- would eventually catch it, but relying on a downstream defence for a
-- duplicate we created ourselves is backwards.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' image rows attributed to a source '
                 || 'other than telegram_fuel — one channel, two votes'
       END AS g1_one_channel_one_witness
FROM state_observation o JOIN source s USING (source_id)
WHERE o.attrs->>'via' = 'image' AND s.key <> 'telegram_fuel';

\echo '--- G1.9: a missing pill never became a caution ---'
-- The card lists the stations that HAVE fuel and only COUNTS the dry ones. The
-- single negative it states outright is "لا توجد محطة متوفر فيها وقود ... في
-- هذه المدينة", which covers a whole region. Any other `unavailable` from an
-- image means the loader inferred a caution by subtraction — and Bethlehem's
-- card implies eleven stations where we hold ten, so that subtraction is
-- already known to be wrong somewhere.
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' unavailable rows from an image with '
                 || 'no region_all_dry basis — a caution was inferred'
       END AS g1_no_inferred_caution
FROM state_observation
WHERE attrs->>'via' = 'image' AND value = 'unavailable'
  AND COALESCE(attrs->>'basis','') <> 'region_all_dry';
