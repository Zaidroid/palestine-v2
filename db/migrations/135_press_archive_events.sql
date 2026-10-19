-- 135 — reviewed events read from the archive's news texts (the DeepSeek
-- harness's returns of 19 Oct 2026): settlement announcements and outposts,
-- Gaza's electricity rota statements; and PCBS's energy tables extend the
-- monthly fuel averages back to 2012 (2026-10-19).
--
-- Jobs 03, 04 and 05 came back read line by line (docs/jobs/JOB-0N-RETURN.md)
-- and Claude re-read 20 rows of each: the PCBS tables reproduce the dashboard
-- on all 720 overlapping cells; the settlement and rota rows read true. Jobs
-- 01 (water, 11 of 15 right) and 02 (hospital events dated by publication,
-- not by the event) are not loaded and go back with named fixes.
--
--   press_archive          a source for figures read from the archive's texts
--                          by a reviewed pass, each row with its quote and
--                          document; fair use, attributed to the outlets.
--   settlements_press_events  settlements.units_announced (one announcement:
--                          units, stage, settlement, East Jerusalem or the
--                          West Bank) and settlements.outpost_reported (one
--                          new outpost, placed on the village when named).
--   gaza_electricity_rota_press  energy.gaza.rota_hours_stated: the rota as
--                          GEDCO or the outlets stated it (X on / Y off → 24·X/(X+Y),
--                          or the stated daily hours), one row per statement,
--                          2010 → 2023; the OCHA table stays the daily source.
--   pcbs_fuel_monthly      its scope now starts in 2012 (the energy tables;
--                          2013 has no table) and the overlap note is recorded.

BEGIN;

-- The unit the announcements are counted in. db/registry/units.yaml carries it
-- too (with its aliases); the registry loads after the migrations, so the row
-- is created here first, as 130 did for hours_per_day and MW.
INSERT INTO unit_def (key, name_en, name_ar, dimension, notes)
VALUES ('housing_units', 'housing units', 'وحدات سكنية', 'count',
        'Dwellings in a plan, a tender or a count of construction starts; one unit is one home.')
ON CONFLICT (key) DO UPDATE
   SET name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar, dimension = EXCLUDED.dimension, notes = EXCLUDED.notes;

INSERT INTO source (key, name, kind, license_spdx, commercial_use, attribution_text,
                    authority_rank, reliability, independence_group, active,
                    redistribution, share_alike, attribution_required)
VALUES ('press_archive',
        'Figures and events read from the archive''s news texts by a reviewed pass (each row with its quote and document)',
        'derived', 'fair-use-attribution', false,
        'Read from Palestinian news texts in the archive; each figure carries its statement and its document.',
        3, 0.7, 'press_archive', true, 'attribution', false, true)
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, license_spdx = EXCLUDED.license_spdx, attribution_text = EXCLUDED.attribution_text,
       reliability = EXCLUDED.reliability, redistribution = EXCLUDED.redistribution, active = EXCLUDED.active;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'settlements_press_events',
       'Settlement announcements and new outposts as the outlets reported them, read from the archive and reviewed (2007 →)',
       source_id, 'settlements', 'irregular', true,
       '{"scope_note": "One row per announcement of housing units (an approval, plan, tender, permit or construction start, with the number of units, the stage and the settlement when named; East Jerusalem or the West Bank) and one row per new outpost (placed on the village when named), as Palestinian outlets reported them. Read from the archive by ops/extract_settlement_events.py, reviewed line by line (docs/jobs/JOB-04-RETURN.md); 434 announcements and 127 outposts kept of 640 and 188. A floor, not a count: an announcement no outlet printed is absent, and the same units pass through plans, approvals and tenders months apart, so stages are never summed together. The series for outposts is Peace Now''s list (peacenow_outposts).", "scope_note_ar": "صف لكل إعلان عن وحدات سكنية (مصادقة أو مخطط أو عطاء أو ترخيص أو بدء بناء، بعدد الوحدات والمرحلة والمستوطنة إن سُمّيت؛ القدس الشرقية أو الضفة) وصف لكل بؤرة استيطانية جديدة (على القرية إن سُمّيت)، كما نقلتها الصحافة الفلسطينية. قُرئت من الأرشيف وروجعت سطرًا سطرًا؛ 434 إعلانًا و127 بؤرة من 640 و188. حدّ أدنى لا عدّ: ما لم تطبعه الصحافة غائب، والوحدات نفسها تمرّ بالمخطط والمصادقة والعطاء على أشهر، فلا تُجمع المراحل. سلسلة البؤر هي قائمة السلام الآن.", "reader": "extract_settlement_events@1 + JOB-04 review"}'::jsonb,
       'Settlement announcements and outposts: read from Palestinian news texts in the archive, reviewed.'
FROM source WHERE key = 'press_archive'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs, attribution_text = EXCLUDED.attribution_text;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'gaza_electricity_rota_press',
       'Gaza''s electricity rota as stated (GEDCO, the Energy Authority, the outlets), one row per statement, 2010 → 2023, read from the archive and reviewed',
       source_id, 'infrastructure', 'irregular', true,
       '{"scope_note": "The distribution rota as a statement printed it: X hours on / Y hours off gives 24·X/(X+Y) hours a day, or the daily hours stated directly; one row per statement on the day it was published, the strip unless an area is named. Read from the archive (docs/jobs/JOB-05-RETURN.md): 237 statements with hours, 31 of the 84 months of 2010–2016 have a stated rota; the rest are gaps in the archive, not months without a rota. A rota is nominal: against OCHA''s delivered hours (2017 →) the stated rota sits 1–5 hours lower from 2020. The OCHA table is the daily source.", "scope_note_ar": "جدول التوزيع كما طبعه بيان: X ساعات وصل / Y قطع يعطي 24·X/(X+Y) ساعة في اليوم، أو الساعات اليومية المذكورة مباشرة؛ صف لكل بيان في يوم نشره، على القطاع ما لم تُسمَّ منطقة. قُرئ من الأرشيف: 237 بيانًا بساعات، 31 من 84 شهرًا في 2010–2016 لها جدول معلن؛ الباقي فجوات في الأرشيف لا أشهر بلا جدول. الجدول اسمي: مقابل ساعات أوتشا الفعلية (2017 فصاعدًا) يقلّ المعلن بساعة إلى خمس منذ 2020. جدول أوتشا هو المصدر اليومي.", "reader": "JOB-05 review"}'::jsonb,
       'Gaza electricity rota: statements in Palestinian news texts in the archive, reviewed.'
FROM source WHERE key = 'press_archive'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs, attribution_text = EXCLUDED.attribution_text;

UPDATE dataset
   SET attrs = attrs || '{"scope_note": "Monthly average consumer price from PCBS''s Consumer Price Survey, by region: 2012-01 → 2018-12 transcribed from PCBS''s yearly Energy Tables (2013 has no table; West Bank, Jerusalem J1, Gaza Strip; read line by line, docs/jobs/JOB-03-RETURN.md), 2019-01 onward from the CPI dashboard (Palestine, West Bank, Gaza Strip, Jerusalem J1). The two sources agree on all 720 cells of 2019–2023. Liquid fuels equal the official maximum in a month the maximum holds; the 12 kg cylinder is priced delivered to the home, 2–3 ILS above it.", "scope_note_ar": "متوسط سعر المستهلك الشهري من مسح أسعار المستهلك في الإحصاء الفلسطيني، حسب المنطقة: من كانون الثاني 2012 إلى كانون الأول 2018 منقول من جداول الطاقة السنوية (لا جدول لعام 2013؛ الضفة الغربية، القدس J1، قطاع غزة؛ قُرئ سطرًا سطرًا)، ومن كانون الثاني 2019 من لوحة الرقم القياسي. يتطابق المصدران في كل خلايا 2019–2023 السبعمئة والعشرين. المحروقات السائلة تساوي الحد الأقصى الرسمي في الشهر الذي يثبت فيه؛ أسطوانة 12 كغم مسعّرة واصلة للمنزل، أعلى منه بشيقلين إلى ثلاثة.", "energy_tables": "docs/jobs/JOB-03-RETURN.md"}'::jsonb
 WHERE key = 'pcbs_fuel_monthly';

INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status,
                           source_spec, notes, serve_warning, serve_warning_ar, ask_by_name, projection)
VALUES
 ('settlements.units_announced', 'settlement',
  'Housing units in one settlement announcement (approval, plan, tender, permit or start), as the outlets reported it',
  'الوحدات السكنية في إعلان استيطاني واحد (مصادقة أو مخطط أو عطاء أو ترخيص أو بدء بناء) كما نقلته الصحافة',
  'housing_units', 'flow', -1, 'day', 'region', 'generated', 'settlements_press_events',
  'One row per announcement; the stage, the settlement (Peace Now''s name when matched, else as printed) and the quote in attrs. East Jerusalem rows sit on the Jerusalem governorate, the rest on the West Bank.',
  'A floor read from the press, reviewed; the same units pass through plans, approvals and tenders months apart, so stages are never summed together.',
  'حدّ أدنى مقروء من الصحافة ومراجَع؛ الوحدات نفسها تمرّ بالمخطط والمصادقة والعطاء على أشهر، فلا تُجمع المراحل.', false, false),
 ('settlements.outpost_reported', 'settlement',
  'A new settler outpost as the outlets reported it, one row each, on the village when named (archive, reviewed)',
  'بؤرة استيطانية جديدة كما نقلتها الصحافة، صف لكل بؤرة، على القرية إن سُمّيت (الأرشيف، مراجَع)',
  'events', 'flow', -1, 'day', 'locality', 'generated', 'settlements_press_events',
  'Value 1 per outpost; the village, the governorate, the kind (farm, tent, caravan) and the quote in attrs. About a quarter to a third of Peace Now''s list by year: the detail, not the count.',
  'The press catches a quarter to a third of the outposts Peace Now lists; the count is settlements.outposts_established.',
  'تلتقط الصحافة ربع البؤر التي تعدّها السلام الآن إلى ثلثها؛ العدّ في settlements.outposts_established.', true, false),
 ('energy.gaza.rota_hours_stated', 'energy.supply',
  'Gaza Strip: hours of electricity a day as the distribution rota was stated (X on / Y off), one row per statement',
  'قطاع غزة: ساعات الكهرباء في اليوم كما أعلن جدول التوزيع (X وصل / Y قطع)، صف لكل بيان',
  'hours_per_day', 'stock', 1, 'day', 'region', 'generated', 'gaza_electricity_rota_press',
  'From the statement''s own rota (24·X/(X+Y)) or its stated daily hours; on, off, kind, area and the quote in attrs. 2010 → 2023; the months without a statement are gaps in the archive.',
  'A nominal rota as stated, not delivered hours; the OCHA table (energy.gaza.supply_hours_per_day) is the measured daily series from 2017.',
  'جدول اسمي كما أُعلن، لا ساعات فعلية؛ جدول أوتشا هو السلسلة اليومية المقيسة من 2017.', true, false)
ON CONFLICT (indicator) DO UPDATE
   SET concept_key = EXCLUDED.concept_key, name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
       canonical_unit = EXCLUDED.canonical_unit, measure_kind = EXCLUDED.measure_kind, polarity = EXCLUDED.polarity,
       grain = EXCLUDED.grain, place_grain = EXCLUDED.place_grain, status = EXCLUDED.status, source_spec = EXCLUDED.source_spec,
       notes = EXCLUDED.notes, serve_warning = EXCLUDED.serve_warning, serve_warning_ar = EXCLUDED.serve_warning_ar,
       ask_by_name = EXCLUDED.ask_by_name, projection = EXCLUDED.projection;

COMMIT;
