-- 134 — schools, students and teachers by year (PCBS, from the Ministry of
-- Education's survey), by region 1994/95 → and by governorate 2011/12 →
-- (2026-10-19).
--
-- Zaid, 19 Oct: education over time was the fourth fill; the area held one
-- day (the HDX school register of 2015). PCBS publishes the yearly counts by
-- supervising authority (government / UNRWA / private), CC BY 4.0: a long
-- bilingual workbook by region and three workbooks by governorate.
-- ops/fetch_pcbs_education.py reads them. A school year is loaded on
-- 1 September of its first year (precision year, the label in attrs). Gaza
-- stops at 2022/23 (PCBS: not available because of the war); Jerusalem
-- excludes the Israeli municipality's and Ma'arif schools (PCBS's footnote).

BEGIN;

INSERT INTO concept (key, parent, name_en, name_ar, definition, notes)
VALUES ('education.provision', NULL,
        'Schools, students and teachers',
        'المدارس والطلبة والمعلمون',
        'The yearly count of schools, of students enrolled and of teachers, by the authority that runs the school (government, UNRWA, private), as the Ministry of Education''s survey reports it to PCBS.',
        'Kindergartens are counted separately by PCBS and are not in these series.')
ON CONFLICT (key) DO UPDATE
   SET name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar, definition = EXCLUDED.definition, notes = EXCLUDED.notes;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'pcbs_education_yearly',
       'PCBS — schools, students and teachers by supervising authority, by region 1994/95 → and by governorate 2011/12 →',
       source_id, 'education', 'irregular', true,
       '{"scope_note": "Schools (kindergartens excluded), students enrolled and teachers, by supervising authority (government / UNRWA / private, and their total), for Palestine, the West Bank and the Gaza Strip from 1994/95 and for every governorate from 2011/12, as the Ministry of Education''s survey reports to PCBS. A school year sits on 1 September of its first year. Gaza stops at 2022/23 (not available because of the war). Jerusalem excludes the Israeli municipality''s and Ma''arif schools.", "scope_note_ar": "المدارس (دون رياض الأطفال) والطلبة الملتحقون والمعلمون حسب الجهة المشرفة (حكومة / وكالة / خاصة ومجموعها) لفلسطين والضفة الغربية وقطاع غزة من 1994/1995 ولكل محافظة من 2011/2012، كما يبلّغ مسح وزارة التربية والتعليم الإحصاء الفلسطيني. يُسجَّل العام الدراسي في 1 أيلول من سنته الأولى. يتوقف قطاع غزة عند 2022/2023 (غير متوفر بسبب الحرب). القدس لا تشمل مدارس البلدية والمعارف الإسرائيليتين.", "reader": "fetch_pcbs_education@1", "workbooks": ["Education1994_2024.xlsx", "Schools2011-2024.xlsx", "Students2011-2024.xlsx", "Teachers2011-2024.xlsx"]}'::jsonb,
       'Data: Palestinian Central Bureau of Statistics (pcbs.gov.ps), CC-BY-4.0, from the Ministry of Education and Higher Education''s education survey.'
FROM source WHERE key = 'pcbs_direct'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs, attribution_text = EXCLUDED.attribution_text;

INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status,
                           source_spec, notes, serve_warning, serve_warning_ar, ask_by_name, projection)
SELECT 'education.' || m.measure || '.' || a.authority, 'education.provision',
       m.name_en || ', ' || a.name_en || ', by school year (PCBS)',
       m.name_ar || '، ' || a.name_ar || '، حسب العام الدراسي (الإحصاء الفلسطيني)',
       m.unit, 'stock', 1, 'year', 'governorate', 'generated', 'pcbs_education_yearly',
       'The school year sits on 1 September of its first year; the label (e.g. 2024/2025) is in attrs. Regions from the long workbook (1994/95 →), governorates from the governorate workbooks (2011/12 →).',
       'Kindergartens excluded; Gaza stops at 2022/23; Jerusalem excludes the Israeli municipality''s and Ma''arif schools.',
       'دون رياض الأطفال؛ يتوقف قطاع غزة عند 2022/2023؛ القدس لا تشمل مدارس البلدية والمعارف الإسرائيليتين.',
       (a.authority <> 'total'), false
FROM (VALUES ('schools', 'Schools', 'المدارس', 'count'), ('students', 'Students enrolled', 'الطلبة الملتحقون', 'persons'),
             ('teachers', 'Teachers', 'المعلمون', 'persons')) AS m(measure, name_en, name_ar, unit)
CROSS JOIN (VALUES ('total', 'all authorities', 'كل الجهات'), ('government', 'government schools', 'المدارس الحكومية'),
                   ('unrwa', 'UNRWA schools', 'مدارس الوكالة'), ('private', 'private schools', 'المدارس الخاصة')) AS a(authority, name_en, name_ar)
ON CONFLICT (indicator) DO UPDATE
   SET concept_key = EXCLUDED.concept_key, name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
       canonical_unit = EXCLUDED.canonical_unit, measure_kind = EXCLUDED.measure_kind, polarity = EXCLUDED.polarity,
       grain = EXCLUDED.grain, place_grain = EXCLUDED.place_grain, status = EXCLUDED.status, source_spec = EXCLUDED.source_spec,
       notes = EXCLUDED.notes, serve_warning = EXCLUDED.serve_warning, serve_warning_ar = EXCLUDED.serve_warning_ar,
       ask_by_name = EXCLUDED.ask_by_name, projection = EXCLUDED.projection;

COMMIT;
