-- 086 — the databank says whose data it is, under the right name (P1-B.2).
--
-- 1. `pcbs` WAS WORLD BANK DATA (audit DATABANK-01 / F026; db/mappings/pcbs.yaml:
--    "THIS DATA IS NOT FROM PCBS"). All 2,060 rows of v1_pcbs_pcbs carry the
--    World Bank API url and World Bank indicator codes; 1,856 are byte-identical
--    (code, date, value) to rows already served from v1_economic_worldbank, so
--    the databank double-counted them under two publishers. Now:
--      * the 1,856 copies are closed (sys_period ends now, attrs.duplicate_of_086
--        names the economic row) — never deleted;
--      * the 204 rows only this dataset holds move with the dataset to the World
--        Bank source and the `economic` category (dataset-level licence cleared,
--        so the World Bank's CC-BY-4.0 and attribution apply);
--      * the REAL PCBS rows (v1_economic_pcbs_direct, 116, pcbs.gov.ps) become
--        the `pcbs` category, which is renamed for what it is.
--    db/mappings/pcbs.yaml is set `migrate: false` in the same commit, so the
--    nightly sync cannot re-insert the closed copies from v1's frozen file.
-- 2. SERVE WARNINGS on the indicators whose number misleads without one:
--    casualties.annual_total is B'Tselem-verified fatalities 2008+ — it
--    EXCLUDES the Gaza war dead (the MoH toll is in `conflict`), and the newest
--    year is partial. indicator_def gains serve_warning / serve_warning_ar,
--    which the category route returns and both answers speak.
-- 3. DEFINITIONS for the demolition indicators served with none.
--
-- Rollback (exact):
--   UPDATE observation SET sys_period = tstzrange(lower(sys_period), NULL),
--          attrs = attrs - 'duplicate_of_086'
--    WHERE attrs ? 'duplicate_of_086';
--   UPDATE dataset SET source_id = (SELECT source_id FROM source WHERE key='pcbs'),
--          v1_category = 'pcbs', attrs = attrs - 'relabelled_086' WHERE key = 'v1_pcbs_pcbs';
--   UPDATE dataset SET v1_category = 'economic', attrs = attrs - 'recategorised_086'
--    WHERE key = 'v1_economic_pcbs_direct';
--   UPDATE category SET name_en = 'Pcbs', name_ar = NULL, notes = NULL WHERE key = 'pcbs';
--   ALTER TABLE indicator_def DROP COLUMN serve_warning, DROP COLUMN serve_warning_ar;
--   DELETE FROM indicator_def WHERE source_spec = '086';
--   (and set db/mappings/pcbs.yaml back to migrate: true)

-- 1a. the copies
WITH wb AS (
  SELECT o.observation_id, o.indicator, o.occurred_at, o.value_num
    FROM observation o JOIN dataset d ON d.dataset_id = o.dataset_id
   WHERE d.key = 'v1_economic_worldbank' AND upper_inf(o.sys_period)
)
UPDATE observation p
   SET sys_period = tstzrange(lower(p.sys_period), now()),
       attrs = COALESCE(p.attrs, '{}'::jsonb) || jsonb_build_object('duplicate_of_086', w.observation_id)
  FROM dataset d, wb w
 WHERE p.dataset_id = d.dataset_id AND d.key = 'v1_pcbs_pcbs'
   AND upper_inf(p.sys_period)
   AND replace(w.indicator, 'economic.', '') = replace(p.indicator, 'pcbs.', '')
   AND w.occurred_at = p.occurred_at
   AND w.value_num IS NOT DISTINCT FROM p.value_num;

-- 1b. the dataset is the World Bank's, filed under economic
UPDATE dataset
   SET source_id = (SELECT source_id FROM source WHERE key = 'worldbank'),
       v1_category = 'economic',
       license_spdx = NULL, commercial_use = NULL, attribution_text = NULL,
       share_alike = NULL, attribution_required = NULL, redistribution = NULL,
       terms_url = NULL, terms_verified_at = NULL,
       attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object('relabelled_086',
               'v1 filed World Bank API rows (api.worldbank.org/v2, WDI codes) under PCBS with an invented licence; '
               'repointed to the World Bank source, CC-BY-4.0 (audit F026)')
 WHERE key = 'v1_pcbs_pcbs';

-- 1c. the real PCBS rows are the pcbs category
UPDATE dataset
   SET v1_category = 'pcbs',
       attrs = COALESCE(attrs, '{}'::jsonb) || jsonb_build_object('recategorised_086',
               'the Palestinian Central Bureau of Statistics'' own rows (pcbs.gov.ps) are the pcbs category')
 WHERE key = 'v1_economic_pcbs_direct';

UPDATE category
   SET name_en = 'PCBS (Palestinian Central Bureau of Statistics)',
       name_ar = 'الجهاز المركزي للإحصاء الفلسطيني',
       notes = '086: only rows published by PCBS itself; World Bank series are under economic.'
 WHERE key = 'pcbs';

-- 2. serve warnings
ALTER TABLE indicator_def ADD COLUMN IF NOT EXISTS serve_warning text,
                          ADD COLUMN IF NOT EXISTS serve_warning_ar text;
COMMENT ON COLUMN indicator_def.serve_warning IS
  'Said beside the number in every answer that serves this indicator: what the figure is NOT (086).';

UPDATE indicator_def
   SET serve_warning = 'B''Tselem-verified Palestinian fatalities since 2008: it EXCLUDES the Gaza war dead '
                       '(the Gaza Ministry of Health toll is in the conflict category), and the newest year is partial.',
       serve_warning_ar = 'هاد عدد الشهداء الموثّقين فردياً من بتسيلم منذ 2008 — ما بيشمل شهداء حرب غزة '
                          '(حصيلة وزارة الصحة بغزة بفئة conflict)، وآخر سنة ناقصة.'
 WHERE indicator = 'casualties.annual_total';

-- 3. demolition definitions
INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit, measure_kind,
                           polarity, grain, place_grain, status, source_spec, notes)
SELECT v.ind, 'demolition', v.en, v.ar, v.unit, 'flow', -1, v.grain, v.pgrain, 'generated', '086',
       'OCHA oPt demolition data; the newest year is partial.'
  FROM (VALUES
    ('demolitions.annual_total.structures', 'Structures demolished in the West Bank, per year (OCHA)',
     'مبانٍ هُدمت بالضفة سنوياً (أوتشا)', 'structures', 'year', 'region'),
    ('demolitions.annual_total.displaced', 'People displaced by demolitions in the West Bank, per year (OCHA)',
     'أشخاص هُجّروا بسبب الهدم بالضفة سنوياً (أوتشا)', 'persons', 'year', 'region'),
    ('demolitions.annual_total.affected', 'People affected by demolitions in the West Bank, per year (OCHA)',
     'أشخاص تضرّروا من الهدم بالضفة سنوياً (أوتشا)', 'persons', 'year', 'region')
  ) AS v(ind, en, ar, unit, grain, pgrain)
ON CONFLICT (indicator) DO NOTHING;

UPDATE indicator_def SET name_en = 'Structures demolished, by locality (OCHA)',
                         name_ar = 'مبانٍ هُدمت حسب التجمّع (أوتشا)'
 WHERE indicator = 'demolitions.locality.structures' AND name_en IS NULL;
UPDATE indicator_def SET name_en = 'People displaced by demolitions, by locality (OCHA)',
                         name_ar = 'أشخاص هُجّروا بسبب الهدم حسب التجمّع (أوتشا)'
 WHERE indicator = 'demolitions.locality.displaced' AND name_en IS NULL;

-- DATABANK-V02: a locality row is a total since 2009, not an event; registered as flow/event it was
-- offered to flow sums beside the annual series and doubled it. (Matches db/mappings/demolitions.yaml.)
-- Rollback: UPDATE indicator_def SET measure_kind = 'flow', grain = 'event'
--            WHERE indicator LIKE 'demolitions.locality.%' AND source_spec = 'demolitions';
UPDATE indicator_def SET measure_kind = 'cumulative', grain = 'period'
 WHERE indicator LIKE 'demolitions.locality.%' AND status <> 'reviewed';
