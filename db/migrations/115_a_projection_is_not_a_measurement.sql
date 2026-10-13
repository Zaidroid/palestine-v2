-- 115 · a projection is not a measurement
-- 2026-10-13
--
-- The UN's World Population Prospects 2024 holds, beside its estimates for 1950
-- to 2023, a medium-variant PROJECTION for 2024 to 2100 (2101 for the population
-- on 1 January): 51 series, 3,928 values. It is a model's output released on 11
-- July 2024, and its first years are already contradicted by events. Until now
-- the store held no row dated after today, and every answer path read the
-- newest-dated row of a series as the latest fact; three of the projected years
-- (2024 to 2026) are not after today at all, so no date test can tell these
-- rows from facts.
--
-- This column is one declared fact about a series: it is a projection. A
-- registry rule declares it (`projection: true` in a spec's registry.rules),
-- ops/load_registry.py writes it, serve/app.py reads it in one place
-- (_projections). Such a series is never compared or correlated with an
-- observed one, never a candidate of the correlation scan, listed last and
-- flagged in /v2/databank/indicators, and spoken as "a projection, not a
-- measurement" with its farthest year: never as the latest figure and never
-- under `latest_by_indicator`. What keeps it out of a category's rows is NOT
-- this column: the same series declare `ask_by_name` (114), and the category
-- route keeps the one condition it has.
--
-- WHY THE 51 DEFINITIONS ARE WRITTEN HERE, BEFORE ANY ROW EXISTS.
-- ops/load_registry.py defines an indicator only once it has rows, and it runs
-- AFTER the loader. The API keeps registry answers for up to six hours
-- (serve/app.py CACHE_TTL_SECONDS). So on the first night there would be
-- minutes in which the rows are served and nothing says they are projections.
-- Written here, both flags, the names and the warning are in place before the
-- first row is loaded. The values are the ones the registry loader writes from
-- db/mappings/population_wpp_projection.yaml and db/registry/names.yaml
-- (generated from them, not typed; tests/test_more_projections_serving.py holds the
-- 51 rows to that), so its first run changes nothing in these rows.
--
-- THE ORDER: this file, then the API restart, then the first load of
-- population_wpp_projection, one straight after the other. Never the load
-- first: ops/load_registry.py refuses a night that finds rows of a declared
-- projection and no such column. And not long between the restart and the
-- load: while the 51 series are declared and have no row, the by-name lookup
-- (serve/app.py _ask_by_name) looks each of them up in vain, about 2.7 s for
-- the 51 on each cold read (measured read-only on 2026-10-13, when the 141
-- series that do have rows took 0.04 to 0.12 s).
--
-- A unit that is not registered yet is written as NULL (the sub-select) and
-- filled by the registry loader; on 2026-10-13 all seven were registered.
-- The column is added with a constant default (no table rewrite); the lock is
-- on indicator_def only, and it gives up after five seconds rather than wait
-- behind a reader. db/migrate.sh runs the file in one transaction.
--
-- Rollback (while no row of un_wpp_2024_projection is held; if one is, close
-- the dataset's rows first):
--   DELETE FROM indicator_def WHERE indicator LIKE 'population.wpp\_projection.%';
--   ALTER TABLE indicator_def DROP COLUMN projection;
--   (with the code of this commit, a missing column means "no such series".)

SET LOCAL lock_timeout = '5s';

ALTER TABLE indicator_def
  ADD COLUMN IF NOT EXISTS projection boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN indicator_def.projection IS
  'true = the series is a projection: a model''s output, not a measurement. Declared by a registry rule, written by ops/load_registry.py, read by serve/app.py _projections(): never compared with an observed series, never spoken as the latest figure. Such a series also declares ask_by_name (114). 115.';

INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status, source_spec,
                           projection, ask_by_name)
VALUES
  ('population.wpp_projection.population_total', 'population.count', 'Projection: Total population at mid-year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: إجمالي عدد السكان في منتصف السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'stock', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.births', 'population.count', 'Projection: Births per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد المواليد في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.deaths', 'population.count', 'Projection: Deaths per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد الوفيات في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.net_migration', 'population.count', 'Projection: Net migration per year, persons (UN World Population Prospects 2024, medium variant)',
   'إسقاط: صافي الهجرة في السنة (عدد الأشخاص) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.crude_birth_rate', 'population.structure', 'Projection: Crude birth rate per 1,000 population (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل المواليد الخام (لكل 1000 نسمة) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.crude_death_rate', 'mortality.general', 'Projection: Crude death rate per 1,000 population (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل الوفيات الخام (لكل 1000 نسمة) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.total_fertility_rate', 'population.structure', 'Projection: Total fertility rate, live births per woman (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل الخصوبة الكلي (مولود حي لكل امرأة) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'births_per_woman'), 'rate', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy', 'mortality.general', 'Projection: Life expectancy at birth, years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند الولادة (بالسنوات) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.infant_mortality_rate', 'mortality.general', 'Projection: Infant mortality rate per 1,000 live births (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل وفيات الرضّع (لكل 1000 مولود حي) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.under5_mortality_rate', 'mortality.general', 'Projection: Under-five mortality rate per 1,000 live births (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل وفيات الأطفال دون سن الخامسة (لكل 1000 مولود حي) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.median_age', 'population.structure', 'Projection: Median age of the population, years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر الوسيط للسكان (بالسنوات) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.population_growth_rate', 'population.structure', 'Projection: Population growth rate, % per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل النمو السكاني (% سنويًا) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'percent'), 'ratio', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.population_total_1jan', 'population.count', 'Projection: Total population on 1 January (UN World Population Prospects 2024, medium variant)',
   'إسقاط: إجمالي عدد السكان في 1 كانون الثاني/يناير (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'stock', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.population_male', 'population.count', 'Projection: Male population at mid-year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد السكان الذكور في منتصف السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'stock', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.population_female', 'population.count', 'Projection: Female population at mid-year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد السكان الإناث في منتصف السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'stock', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.sex_ratio', 'population.structure', 'Projection: Population sex ratio at mid-year, males per 100 females (UN World Population Prospects 2024, medium variant)',
   'إسقاط: نسبة الذكور إلى الإناث بين السكان في منتصف السنة (ذكور لكل 100 أنثى) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'males_per_100_females'), 'ratio', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.natural_change', 'population.count', 'Projection: Natural change per year, births minus deaths, persons (UN World Population Prospects 2024, medium variant)',
   'إسقاط: الزيادة الطبيعية في السنة: المواليد ناقص الوفيات (عدد الأشخاص) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.natural_change_rate', 'population.structure', 'Projection: Rate of natural change per 1,000 population (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل الزيادة الطبيعية (لكل 1000 نسمة) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.births_women_15_19', 'population.count', 'Projection: Births by women aged 15 to 19, per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد المواليد لأمهات في سن 15 إلى 19 سنة، في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.net_reproduction_rate', 'population.structure', 'Projection: Net reproduction rate, surviving daughters per woman (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل التكاثر الصافي (بنات باقيات على قيد الحياة لكل امرأة) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'daughters_per_woman'), 'rate', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mean_age_childbearing', 'population.structure', 'Projection: Mean age at childbearing, years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: متوسط العمر عند الإنجاب (بالسنوات) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.sex_ratio_at_birth', 'population.structure', 'Projection: Sex ratio at birth, male births per 100 female births (UN World Population Prospects 2024, medium variant)',
   'إسقاط: نسبة الذكور إلى الإناث عند الولادة (مواليد ذكور لكل 100 مولودة أنثى) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'males_per_100_females'), 'ratio', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.deaths_male', 'population.count', 'Projection: Male deaths per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد وفيات الذكور في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.deaths_female', 'population.count', 'Projection: Female deaths per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد وفيات الإناث في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_male', 'mortality.general', 'Projection: Male life expectancy at birth, years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند الولادة للذكور (بالسنوات) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_female', 'mortality.general', 'Projection: Female life expectancy at birth, years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند الولادة للإناث (بالسنوات) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_15', 'mortality.general', 'Projection: Life expectancy at age 15, remaining years, both sexes (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 15: السنوات المتبقية، كلا الجنسين (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_15_male', 'mortality.general', 'Projection: Male life expectancy at age 15, remaining years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 15 للذكور: السنوات المتبقية (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_15_female', 'mortality.general', 'Projection: Female life expectancy at age 15, remaining years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 15 للإناث: السنوات المتبقية (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_65', 'mortality.general', 'Projection: Life expectancy at age 65, remaining years, both sexes (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 65: السنوات المتبقية، كلا الجنسين (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_65_male', 'mortality.general', 'Projection: Male life expectancy at age 65, remaining years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 65 للذكور: السنوات المتبقية (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_65_female', 'mortality.general', 'Projection: Female life expectancy at age 65, remaining years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 65 للإناث: السنوات المتبقية (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_80', 'mortality.general', 'Projection: Life expectancy at age 80, remaining years, both sexes (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 80: السنوات المتبقية، كلا الجنسين (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_80_male', 'mortality.general', 'Projection: Male life expectancy at age 80, remaining years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 80 للذكور: السنوات المتبقية (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.life_expectancy_at_80_female', 'mortality.general', 'Projection: Female life expectancy at age 80, remaining years (UN World Population Prospects 2024, medium variant)',
   'إسقاط: العمر المتوقع عند سن 80 للإناث: السنوات المتبقية (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'years'), 'index', 1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.infant_deaths', 'population.count', 'Projection: Infant deaths (under age 1) per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد وفيات الرضّع (دون السنة الأولى من العمر) في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.births_surviving_to_age_1', 'population.count', 'Projection: Live births surviving to age 1, per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: المواليد الأحياء الباقون على قيد الحياة حتى إتمام سنتهم الأولى، في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.under5_deaths', 'population.count', 'Projection: Deaths under age 5 per year (UN World Population Prospects 2024, medium variant)',
   'إسقاط: عدد وفيات الأطفال دون سن الخامسة في السنة (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'persons'), 'flow', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_before_40', 'mortality.general', 'Projection: Mortality before age 40 per 1,000 live births, both sexes (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة قبل بلوغ سن 40، كلا الجنسين (لكل 1000 مولود حي) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_before_40_male', 'mortality.general', 'Projection: Male mortality before age 40 per 1,000 male live births (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة قبل بلوغ سن 40 للذكور (لكل 1000 مولود حي من الذكور) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_before_40_female', 'mortality.general', 'Projection: Female mortality before age 40 per 1,000 female live births (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة قبل بلوغ سن 40 للإناث (لكل 1000 مولودة حية من الإناث) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_before_60', 'mortality.general', 'Projection: Mortality before age 60 per 1,000 live births, both sexes (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة قبل بلوغ سن 60، كلا الجنسين (لكل 1000 مولود حي) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_before_60_male', 'mortality.general', 'Projection: Male mortality before age 60 per 1,000 male live births (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة قبل بلوغ سن 60 للذكور (لكل 1000 مولود حي من الذكور) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_before_60_female', 'mortality.general', 'Projection: Female mortality before age 60 per 1,000 female live births (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة قبل بلوغ سن 60 للإناث (لكل 1000 مولودة حية من الإناث) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_15_to_50', 'mortality.general', 'Projection: Mortality between ages 15 and 50 per 1,000 alive at age 15, both sexes (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة بين سن 15 و50، كلا الجنسين (لكل 1000 ممن بلغوا سن 15) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_15_to_50_male', 'mortality.general', 'Projection: Male mortality between ages 15 and 50 per 1,000 males alive at age 15 (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة بين سن 15 و50 للذكور (لكل 1000 من الذكور الذين بلغوا سن 15) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_15_to_50_female', 'mortality.general', 'Projection: Female mortality between ages 15 and 50 per 1,000 females alive at age 15 (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة بين سن 15 و50 للإناث (لكل 1000 من الإناث اللواتي بلغن سن 15) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_15_to_60', 'mortality.general', 'Projection: Mortality between ages 15 and 60 per 1,000 alive at age 15, both sexes (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة بين سن 15 و60، كلا الجنسين (لكل 1000 ممن بلغوا سن 15) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_15_to_60_male', 'mortality.general', 'Projection: Male mortality between ages 15 and 60 per 1,000 males alive at age 15 (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة بين سن 15 و60 للذكور (لكل 1000 من الذكور الذين بلغوا سن 15) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.mortality_15_to_60_female', 'mortality.general', 'Projection: Female mortality between ages 15 and 60 per 1,000 females alive at age 15 (UN World Population Prospects 2024, medium variant)',
   'إسقاط: احتمال الوفاة بين سن 15 و60 للإناث (لكل 1000 من الإناث اللواتي بلغن سن 15) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', -1, 'year', 'region', 'generated', 'population_wpp_projection', true, true),
  ('population.wpp_projection.net_migration_rate', 'population.structure', 'Projection: Net migration rate per 1,000 population (UN World Population Prospects 2024, medium variant)',
   'إسقاط: معدل صافي الهجرة (لكل 1000 نسمة) (التوقعات السكانية في العالم 2024، الأمم المتحدة، المتغير المتوسط)',
   (SELECT key FROM unit_def WHERE key = 'per_1000'), 'rate', NULL, 'year', 'region', 'generated', 'population_wpp_projection', true, true)
ON CONFLICT (indicator) DO UPDATE SET projection = true, ask_by_name = true;

UPDATE indicator_def
   SET serve_warning = $w$A PROJECTION, not a measurement: the United Nations' medium-variant projection from World Population Prospects 2024, a model's output released on 11 July 2024. It assumed a recovery that the years since have not shown: it has deaths falling from 38,937 in 2023 to 16,412 in 2026, and life expectancy at birth rising from 65.2 to 77.4 years. The UN's estimates end at 2023 (population.wpp.*); every year here, from 2024 on, is the model. The UN has announced its next revision for 11 July 2027.$w$,
       serve_warning_ar = $w$هاد إسقاط مش قياس: إسقاط الأمم المتحدة بالمتغير المتوسط من «التوقعات السكانية في العالم 2024»، يعني ناتج نموذج انتشر بـ11 تموز 2024. النموذج افترض تعافي ما شفناه بالسنين اللي بعدها: عنده الوفيات بتنزل من 38,937 سنة 2023 لـ16,412 سنة 2026، والعمر المتوقع عند الولادة بيطلع من 65.2 لـ77.4 سنة. تقديرات الأمم المتحدة بتوقف عند سنة 2023 (population.wpp.*)، وكل سنة هون، من 2024 وطالع، هي النموذج. والأمم المتحدة أعلنت إنه المراجعة الجاية بتطلع بـ11 تموز 2027.$w$
 WHERE projection AND indicator LIKE 'population.wpp\_projection.%';

-- 51 series, each a projection that is asked for by name, named in both
-- languages and carrying the warning: anything else stops the migration
DO $$
BEGIN
  IF (SELECT count(*) FROM indicator_def
       WHERE projection AND ask_by_name AND indicator LIKE 'population.wpp\_projection.%'
         AND name_en LIKE 'Projection: %' AND name_ar LIKE 'إسقاط: %'
         AND serve_warning IS NOT NULL AND serve_warning_ar IS NOT NULL) <> 51 THEN
    RAISE EXCEPTION 'expected 51 declared projection series';
  END IF;
END $$;
