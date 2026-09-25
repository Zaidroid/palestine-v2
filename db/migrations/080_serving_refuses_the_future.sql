-- 080 — a reading from the future is not served, and cannot freeze belief.
--
-- Audit F331/F117. The three serving gates (026) test the confidence floor,
-- the 'expired' band and the assert ceiling. A NEGATIVE age passes all three:
-- state_confidence (010) and value_persistence (015) return full confidence for
-- `halvings <= 0`, the band CASE calls any negative interval 'live', and
-- `now() - observed_at > max_assert` never fires. So an observation stamped a
-- day ahead — clock skew, a tz-naive string read as UTC, a date parsed without
-- its year — was served as the freshest, most confident reading in the system
-- for a whole day. Reproduced in tests/test_belief_serving.py
-- (test_a_future_stamped_belief_is_not_served).
--
-- The belief upsert refused to move observed_at backwards, so the same row also
-- blocked every genuine correction until the wall clock caught up with it;
-- resolve/belief.py records this happening once (the G2.5 incident). That half
-- is fixed in resolve/belief.py: `latest` ignores anything more than
-- FUTURE_TOLERANCE ahead and the upsert may replace a future-stamped row. This
-- migration is the serving half, for rows already in state_current and for any
-- writer that bypasses belief.py.
--
-- Same columns in the same order as 026 (CREATE OR REPLACE requires it); the
-- only changes are the future branch in `confidence` and gate 0 in `value`.
-- The tolerance (10 minutes) is resolve/belief.py's FUTURE_TOLERANCE;
-- tests/test_belief_serving.py pins both.
--
-- Rollback: re-run the CREATE OR REPLACE VIEW state_serving from
-- 026_expose_serving_mode.sql (identical column list, so it replaces cleanly).

CREATE OR REPLACE VIEW state_serving AS
WITH base AS (
         SELECT sc.place_id,
            sc.state_kind,
            sc.direction,
            sc.value AS raw_value,
            sc.observed_at,
            sc.base_confidence,
            sc.independent_sources,
            sc.contradicted_by,
            p.name_en,
            p.name_ar,
            p.kind AS place_kind,
            p.centroid,
            k.confidence_floor,
            k.serving_mode,
            k.max_assert_seconds,
            COALESCE(c.half_life_seconds, k.half_life_seconds) AS half_life_seconds,
            c.median_gap_seconds,
            c.place_id IS NOT NULL AS cadence_measured,
            d.state_kind IS NOT NULL AS persistence_measured,
                CASE
                    WHEN d.state_kind IS NOT NULL THEN value_persistence(d.p0, d.asymptote, d.half_life_seconds, sc.observed_at, now())
                    ELSE state_confidence(1.0::real, sc.observed_at, COALESCE(c.half_life_seconds, k.half_life_seconds), now())
                END AS persistence,
            d.p0 AS persistence_p0
           FROM state_current sc
             JOIN state_kind_config k ON k.state_kind = sc.state_kind
             JOIN place p ON p.place_id = sc.place_id
             LEFT JOIN place_state_cadence c ON c.place_id = sc.place_id AND c.state_kind = sc.state_kind AND c.direction = sc.direction
             LEFT JOIN state_value_decay d ON d.state_kind = sc.state_kind AND d.value = sc.value
        ), scored AS (
         SELECT base.place_id,
            base.state_kind,
            base.direction,
            base.raw_value,
            base.observed_at,
            base.base_confidence,
            base.independent_sources,
            base.contradicted_by,
            base.name_en,
            base.name_ar,
            base.place_kind,
            base.centroid,
            base.confidence_floor,
            base.serving_mode,
            base.max_assert_seconds,
            base.half_life_seconds,
            base.median_gap_seconds,
            base.cadence_measured,
            base.persistence_measured,
            base.persistence,
            base.persistence_p0,
            EXTRACT(epoch FROM now() - base.observed_at)::bigint / 60 AS age_minutes,
                CASE
                    WHEN (now() - base.observed_at) < make_interval(secs => base.half_life_seconds::double precision) THEN 'live'::text
                    WHEN (now() - base.observed_at) < make_interval(secs => (base.half_life_seconds * 2)::double precision) THEN 'recent'::text
                    WHEN (now() - base.observed_at) < make_interval(secs => (base.half_life_seconds * 8)::double precision) THEN 'stale'::text
                    ELSE 'expired'::text
                END AS staleness_band,
            -- 080: a reading stamped in the future carries no evidence about
            -- now. state_confidence/value_persistence clamp a negative age to
            -- FULL confidence, so without this it was the most confident row
            -- in the view.
            CASE
                WHEN base.observed_at > now() + '00:10:00'::interval THEN 0::real
                ELSE (base.base_confidence *
                CASE
                    WHEN base.persistence_p0 IS NULL OR base.persistence_p0 <= 0.5::double precision THEN base.persistence::double precision
                    ELSE GREATEST(0::real::double precision, LEAST(1::real::double precision, (base.persistence - 0.5::double precision) / (base.persistence_p0 - 0.5::double precision)))
                END)::real
            END AS confidence
           FROM base
        )
 SELECT place_id,
    name_en,
    name_ar,
    place_kind,
    centroid,
    state_kind,
    direction,
    raw_value AS last_known_value,
    observed_at,
    age_minutes,
    independent_sources,
    contradicted_by,
    half_life_seconds,
    median_gap_seconds,
    cadence_measured,
    persistence,
    persistence_measured,
    confidence,
        CASE
            -- 080, gate 0: not from the future. Ten minutes of tolerance for
            -- clock skew between a source and this database; beyond it the
            -- stamp is wrong and the value is not asserted (the reading stays
            -- visible as last_known_value with its negative age).
            WHEN observed_at > now() + '00:10:00'::interval THEN 'unknown'::text
            WHEN confidence < confidence_floor THEN 'unknown'::text
            WHEN staleness_band = 'expired'::text THEN 'unknown'::text
            WHEN max_assert_seconds IS NOT NULL AND (now() - observed_at) > make_interval(secs => max_assert_seconds::double precision) THEN 'unknown'::text
            ELSE raw_value
        END AS value,
    staleness_band,
    serving_mode
   FROM scored;
