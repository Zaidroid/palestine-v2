-- 048 — the databank's serving surface, with the license filter IN the SQL
--
-- T2.5 (P2.6), per Zaid's serving decision (2026-08-05): the free public
-- tier serves everything redistributable WITH attribution; the commercial
-- subset exists as a view whose correctness is gate-tested NOW, so the day
-- a paying customer appears only key issuance is new work — the filter they
-- can never bypass predates them. Enforcement is structural (a WHERE in the
-- view), not app-side filtering the next endpoint forgets.
--
-- databank_serving additionally hides superseded rows: a closed sys_period
-- means "v1 stopped serving this value"; it remains queryable via as_of,
-- never via the default surface.

CREATE OR REPLACE VIEW databank_serving AS
SELECT o.observation_id, o.occurred_at, o.occurred_precision,
       o.indicator, o.value_num, o.value_text, o.unit,
       o.place_id, o.attrs, o.reported_at, o.sys_period,
       d.key           AS dataset_key,
       d.v1_category,
       s.key           AS source_key,
       s.name          AS source_name,
       s.license_spdx,
       s.commercial_use,
       s.attribution_text
FROM observation o
JOIN dataset d ON d.dataset_id = o.dataset_id
JOIN source s  ON s.source_id  = d.source_id
WHERE o.v1_stable_id IS NOT NULL          -- the migrated databank
  AND upper_inf(o.sys_period);            -- superseded rows are as_of-only

COMMENT ON VIEW databank_serving IS
  'Free-tier databank surface: current rows only, attribution attached.';

CREATE OR REPLACE VIEW databank_commercial AS
SELECT * FROM databank_serving
WHERE commercial_use;                     -- THE filter. Tested by G5.5-G5.7.

COMMENT ON VIEW databank_commercial IS
  'Sellable subset. No key machinery exists yet by decision; the filter '
  'does, and its tests predate any customer.';
