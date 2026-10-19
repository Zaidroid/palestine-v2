-- 130 — new settler outposts by month (Peace Now's list) and Gaza's daily
-- electricity supply 2017 → the blackout (OCHA's table from GEDCO's figures)
-- (2026-10-19).
--
-- Zaid, 19 Oct: "settlement units and outposts by month from the archive, then
-- a scout for GEDCO's own electricity schedules". The archive pass
-- (ops/extract_settlement_events.py) found about half of the outposts Peace
-- Now lists (2024: 23 against 59); the list itself is public, carries the
-- establishment MONTH from 2023 and coordinates, so it is the series and the
-- archive is its detail. GEDCO never published its area schedules as data;
-- OCHA built a daily table from GEDCO's figures (supply by line, demand, hours
-- of supply a day) for 2017-01-01 → 2023-09-30 and no longer offers it for
-- download; a copy survives in public course repositories and reproduces
-- OCHA's own published yearly average for 2019 (12 h). The grid has been down
-- since 11 October 2023; the table ends the day before the war.
--
--   peacenow_outposts            source peace_now (no licence found,
--                                no-redistribution: served here, withheld from
--                                partners). One row per outpost (value 1, the
--                                month, the governorate, name/type/coordinates
--                                in attrs) and the monthly count per governorate.
--                                A list of outposts STANDING today: evicted and
--                                legalised ones have left it, so early years are
--                                undercounts; the month is given for 2023 →.
--   ocha_gaza_electricity_daily  source ocha_electricity (OCHA's site terms,
--                                non-commercial, no redistribution). Six series
--                                a day on the Gaza Strip place. The column OCHA
--                                named "power cuts, hours/day" is HOURS OF SUPPLY
--                                (May 2018: 117 MW against 522 MW demand and 4.8,
--                                which only reads as supply); it is loaded as
--                                supply hours and the note travels with the rows.

BEGIN;

INSERT INTO unit_def (key, name_en, name_ar, dimension, notes)
VALUES ('hours_per_day', 'hours per day', 'ساعة في اليوم', 'time',
        'A daily average of hours (electricity supplied in a day). A rota of 4 on / 12 off is 6 hours a day; 8 / 8 is 12.'),
       ('MW', 'megawatts', 'ميغاواط', 'power',
        'Electrical power available or demanded, in megawatts (a daily figure as OCHA reported it).')
ON CONFLICT (key) DO UPDATE
   SET name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
       dimension = EXCLUDED.dimension, notes = EXCLUDED.notes;

INSERT INTO source (key, name, kind, license_spdx, commercial_use, attribution_text,
                    authority_rank, reliability, independence_group, active,
                    redistribution, share_alike, attribution_required, terms_url)
VALUES ('ocha_electricity',
        'UN OCHA oPt — Gaza Strip electricity supply (daily table from GEDCO''s figures)',
        'file', 'UN-ToU-NC', false,
        'Gaza electricity supply: UN OCHA oPt (ochaopt.org/page/gaza-strip-electricity-supply), from the Gaza Electricity Distribution Company''s daily figures.',
        1, 0.9, 'ocha', true, 'no-redistribution', false, true,
        'https://www.ochaopt.org/page/terms-use')
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, license_spdx = EXCLUDED.license_spdx,
       attribution_text = EXCLUDED.attribution_text, redistribution = EXCLUDED.redistribution,
       share_alike = EXCLUDED.share_alike, attribution_required = EXCLUDED.attribution_required,
       terms_url = EXCLUDED.terms_url, active = EXCLUDED.active;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'peacenow_outposts',
       'Peace Now — settler outposts by establishment month and governorate (Settlement Watch list)',
       source_id, 'settlements', 'irregular', true,
       '{"scope_note": "Peace Now''s list of settler outposts standing on the day of the sheet, each with its establishment year and (from 2023, nearly always) month, its district, nearest settlement and coordinates. Evicted and legalised outposts have left the list, so the earlier years are undercounts of what was established then. One row per outpost and a monthly count per governorate.", "scope_note_ar": "قائمة حركة السلام الآن للبؤر الاستيطانية القائمة يوم إصدار الجدول، لكل منها سنة الإقامة والشهر (من 2023 في الغالب) والمنطقة وأقرب مستوطنة والإحداثيات. البؤر التي أُخليت أو شُرعنت خرجت من القائمة، فالسنوات الأولى أقل من الواقع. صف لكل بؤرة وعدد شهري لكل محافظة.", "reader": "fetch_peacenow_outposts@1", "sheet": "https://docs.google.com/spreadsheets/d/1Hs_JdYPEs4oXs09zG3Hd4tWBpYo0ImkJ6WuXAEgMi0U/export?format=csv", "page": "https://peacenow.org.il/en/settlements-watch/settlements-data/population"}'::jsonb,
       'Outposts: Peace Now, Settlement Watch.'
FROM source WHERE key = 'peace_now'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs,
       attribution_text = EXCLUDED.attribution_text;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'ocha_gaza_electricity_daily',
       'UN OCHA oPt — Gaza Strip electricity supply, daily, 2017-01-01 → 2023-09-30 (from GEDCO''s figures)',
       source_id, 'infrastructure', 'migration', true,
       '{"scope_note": "Supply available to the Gaza Strip each day in megawatts, by line (Israeli lines, the Gaza power plant, the Egyptian lines), the estimated demand, and the hours of supply a day, as OCHA tabulated GEDCO''s daily figures from 1 January 2017 to 30 September 2023. The grid has been down since 11 October 2023; the table ends the day before the war. The column OCHA titled power cuts is hours of SUPPLY (May 2018: 117 MW against 522 MW demand and 4.8 hours). A daily average: a rota of 4 on / 12 off is 6 hours.", "scope_note_ar": "الطاقة المتاحة لقطاع غزة كل يوم بالميغاواط حسب المصدر (الخطوط الإسرائيلية، محطة توليد غزة، الخطوط المصرية)، والطلب المقدّر، وساعات الوصل في اليوم، كما جدولت أوتشا أرقام شركة توزيع الكهرباء اليومية من 1 كانون الثاني 2017 إلى 30 أيلول 2023. الشبكة متوقفة منذ 11 تشرين الأول 2023؛ ينتهي الجدول قبل الحرب بيوم. العمود الذي سمّته أوتشا ساعات القطع هو ساعات الوصل. معدّل يومي: جدول 4 وصل مقابل 12 قطع يساوي 6 ساعات.", "reader": "fetch_ocha_gaza_electricity@1", "page": "https://www.ochaopt.org/page/gaza-strip-electricity-supply", "copy": "https://raw.githubusercontent.com/sondosaabed/Gaza-Electricity-Supply-AVLTree/main/Electricy/src/resources/Electricity.csv", "copy_note": "OCHA no longer offers the table for download; this copy, used in a Birzeit course assignment, reproduces OCHA''s published 2019 average (12 h) and its 2017 crisis lows; 2017–18 run above OCHA''s November 2019 indicator PDF (7.3 against 5.7 / 6.6), so those two years are read with that caveat.", "end": "2023-09-30", "blackout_since": "2023-10-11"}'::jsonb,
       'Gaza electricity supply: UN OCHA oPt, from GEDCO''s daily figures.'
FROM source WHERE key = 'ocha_electricity'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs,
       attribution_text = EXCLUDED.attribution_text;

INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status,
                           source_spec, notes, serve_warning, serve_warning_ar,
                           ask_by_name, projection)
VALUES
 ('settlements.outposts_established', 'settlement',
  'Settler outposts established, count per month, by governorate (Peace Now list)',
  'البؤر الاستيطانية المقامة، العدد في الشهر، حسب المحافظة (قائمة السلام الآن)',
  'events', 'flow', -1, 'month', 'governorate', 'generated', 'peacenow_outposts',
  'Counted from Peace Now''s list of outposts standing today by establishment month; a year without a month is a yearly row. Governorate from the list''s district (Yatta → Hebron); 32 outposts carry no district and count on the West Bank only.',
  'A list of outposts standing today: evicted and legalised outposts are not in it, so earlier years undercount. Monthly from 2023; yearly before.',
  'قائمة البؤر القائمة اليوم: البؤر التي أُخليت أو شُرعنت ليست فيها، فالسنوات الأولى أقل من الواقع. شهري من 2023، سنوي قبل ذلك.',
  true, false),
 ('settlements.outpost', 'settlement',
  'A settler outpost, one row each, at its establishment month (Peace Now list)',
  'بؤرة استيطانية، صف لكل بؤرة، في شهر إقامتها (قائمة السلام الآن)',
  'events', 'flow', -1, 'month', 'point', 'generated', 'peacenow_outposts',
  'Value 1 per outpost; name, Hebrew name, type (outpost / farm outpost), nearest settlement, district and coordinates in attrs. The place is the governorate; the point is in attrs.',
  'One row is one outpost on Peace Now''s list; sum the rows for a count.',
  'كل صف بؤرة واحدة في قائمة السلام الآن؛ تُجمع الصفوف للعدد.',
  true, false),
 ('energy.gaza.supply_hours_per_day', 'energy.supply',
  'Gaza Strip: hours of electricity supply a day (OCHA, from GEDCO), daily',
  'قطاع غزة: ساعات وصل الكهرباء في اليوم (أوتشا، عن شركة التوزيع)، يوميًا',
  'hours_per_day', 'stock', 1, 'day', 'region', 'generated', 'ocha_gaza_electricity_daily',
  'OCHA''s column "Power cuts hours/day" read as hours of supply (the May 2018 check). A daily average across the strip: a rota of 4 on / 12 off is 6 hours.',
  'A daily average of supply hours across the strip, not the length of one on-period; the table ends 30 September 2023, the grid has been down since 11 October 2023.',
  'معدّل يومي لساعات الوصل في القطاع كله، لا طول فترة وصل واحدة؛ ينتهي الجدول في 30 أيلول 2023، والشبكة متوقفة منذ 11 تشرين الأول 2023.',
  true, false),
 ('energy.gaza.supply_mw', 'energy.supply',
  'Gaza Strip: total electricity supply available, megawatts (OCHA, from GEDCO), daily',
  'قطاع غزة: إجمالي الطاقة الكهربائية المتاحة بالميغاواط (أوتشا، عن شركة التوزيع)، يوميًا',
  'MW', 'stock', 1, 'day', 'region', 'generated', 'ocha_gaza_electricity_daily',
  'The sum of the Israeli lines, the Gaza power plant and the Egyptian lines, as OCHA tabulated it.',
  'Ends 30 September 2023; the grid has been down since 11 October 2023.',
  'ينتهي في 30 أيلول 2023؛ الشبكة متوقفة منذ 11 تشرين الأول 2023.',
  true, false),
 ('energy.gaza.supply_mw_israel_lines', 'energy.supply',
  'Gaza Strip: supply from the Israeli lines, megawatts (OCHA, from GEDCO), daily',
  'قطاع غزة: الطاقة من الخطوط الإسرائيلية بالميغاواط (أوتشا، عن شركة التوزيع)، يوميًا',
  'MW', 'stock', 1, 'day', 'region', 'generated', 'ocha_gaza_electricity_daily',
  'The ten lines from Israel, nominally 120 MW.', NULL, NULL, true, false),
 ('energy.gaza.supply_mw_power_plant', 'energy.supply',
  'Gaza Strip: supply from the Gaza power plant, megawatts (OCHA, from GEDCO), daily',
  'قطاع غزة: الطاقة من محطة توليد غزة بالميغاواط (أوتشا، عن شركة التوزيع)، يوميًا',
  'MW', 'stock', 1, 'day', 'region', 'generated', 'ocha_gaza_electricity_daily',
  'Zero on the days the plant had no fuel.', NULL, NULL, true, false),
 ('energy.gaza.supply_mw_egypt_lines', 'energy.supply',
  'Gaza Strip: supply from the Egyptian lines, megawatts (OCHA, from GEDCO), daily',
  'قطاع غزة: الطاقة من الخطوط المصرية بالميغاواط (أوتشا، عن شركة التوزيع)، يوميًا',
  'MW', 'stock', 1, 'day', 'region', 'generated', 'ocha_gaza_electricity_daily',
  'The lines to Rafah, out of service for most of the period.', NULL, NULL, true, false),
 ('energy.gaza.demand_mw', 'energy.supply',
  'Gaza Strip: estimated electricity demand, megawatts (OCHA, from GEDCO), daily',
  'قطاع غزة: الطلب المقدّر على الكهرباء بالميغاواط (أوتشا، عن شركة التوزيع)، يوميًا',
  'MW', 'stock', NULL, 'day', 'region', 'generated', 'ocha_gaza_electricity_daily',
  'Estimated by GEDCO from the day''s temperature, as OCHA''s page says.',
  'An estimate from the day''s temperature, not a measurement of consumption.',
  'تقدير من حرارة اليوم، لا قياس للاستهلاك.', true, false)
ON CONFLICT (indicator) DO UPDATE
   SET concept_key = EXCLUDED.concept_key, name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
       canonical_unit = EXCLUDED.canonical_unit, measure_kind = EXCLUDED.measure_kind,
       polarity = EXCLUDED.polarity, grain = EXCLUDED.grain, place_grain = EXCLUDED.place_grain,
       status = EXCLUDED.status, source_spec = EXCLUDED.source_spec, notes = EXCLUDED.notes,
       serve_warning = EXCLUDED.serve_warning, serve_warning_ar = EXCLUDED.serve_warning_ar,
       ask_by_name = EXCLUDED.ask_by_name, projection = EXCLUDED.projection;

COMMIT;
