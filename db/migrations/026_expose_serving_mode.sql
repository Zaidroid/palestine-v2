-- 026 — expose serving_mode so a consumer cannot mistake a sighting for a state.
--
-- Migration 025 marked the presence kinds as sightings but nothing downstream
-- could see it, which would have left the distinction as documentation — and
-- documentation is exactly what a caller reaching for `value` does not read.
-- Appended at the END of the column list so CREATE OR REPLACE accepts it.
--
-- For a sighting, read last_known_value WITH age_minutes. `value` stays gated
-- and will read 'unknown' almost always, which is correct: nobody has looked
-- at that checkpoint in the last 45 minutes.

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
            (base.base_confidence *
                CASE
                    WHEN base.persistence_p0 IS NULL OR base.persistence_p0 <= 0.5::double precision THEN base.persistence::double precision
                    ELSE GREATEST(0::real::double precision, LEAST(1::real::double precision, (base.persistence - 0.5::double precision) / (base.persistence_p0 - 0.5::double precision)))
                END)::real AS confidence
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
            WHEN confidence < confidence_floor THEN 'unknown'::text
            WHEN staleness_band = 'expired'::text THEN 'unknown'::text
            WHEN max_assert_seconds IS NOT NULL AND (now() - observed_at) > make_interval(secs => max_assert_seconds::double precision) THEN 'unknown'::text
            ELSE raw_value
        END AS value,
    staleness_band,
    serving_mode
   FROM scored;
